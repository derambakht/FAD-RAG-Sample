"""مدیریت کارهای پس‌زمینه (ایندکس‌سازی، تولید پرسش، ارزیابی) با گزارش پیشرفت."""
from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

log = logging.getLogger(__name__)

# یک worker برای هر نوع کار: مدل‌های embedding لوکال و Qdrant embedded را از رقابت thread حفظ می‌کند
_executors = {kind: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"job-{kind}") for kind in ("ingest", "eval")}
_jobs: dict[str, dict] = {}
_lock = threading.Lock()
MAX_JOBS = 300


class JobCancelled(Exception):
    pass


def _public(j: dict) -> dict:
    return {k: v for k, v in j.items() if not k.startswith("_")}


def submit(kind: str, title: str, fn: Callable[..., Any], *args, meta: dict | None = None, **kwargs) -> dict:
    jid = str(uuid.uuid4())
    job = {"id": jid, "kind": kind, "title": title, "status": "pending", "progress": 0.0, "message": "در صف",
           "result": None, "error": None, "meta": meta or {}, "created_at": time.time(), "finished_at": None,
           "_cancel": threading.Event()}
    with _lock:
        _jobs[jid] = job
        if len(_jobs) > MAX_JOBS:
            for old in sorted(_jobs.values(), key=lambda j: j["created_at"])[: len(_jobs) - MAX_JOBS]:
                if old["status"] in ("done", "error", "cancelled"):
                    _jobs.pop(old["id"], None)

    def progress(frac: float, message: str = "") -> None:
        if job["_cancel"].is_set():
            raise JobCancelled()
        job["progress"] = round(max(0.0, min(1.0, frac)), 4)
        if message:
            job["message"] = message

    def run():
        if job["_cancel"].is_set():
            return
        job["status"], job["message"] = "running", "در حال اجرا"
        try:
            job["result"] = fn(progress, *args, **kwargs)
            job["status"], job["progress"], job["message"] = "done", 1.0, "انجام شد"
        except JobCancelled:
            job["status"], job["message"] = "cancelled", "لغو شد"
        except Exception as e:
            log.error("کار %s ناموفق بود:\n%s", title, traceback.format_exc())
            job["status"], job["error"], job["message"] = "error", str(e), "خطا"
        finally:
            job["finished_at"] = time.time()

    _executors[kind].submit(run)
    return _public(job)


def get(jid: str) -> dict | None:
    j = _jobs.get(jid)
    return _public(j) if j else None


def list_jobs(active_only: bool = False) -> list[dict]:
    jobs = sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)
    if active_only:
        jobs = [j for j in jobs if j["status"] in ("pending", "running")]
    return [_public(j) for j in jobs[:100]]


def cancel(jid: str) -> bool:
    j = _jobs.get(jid)
    if not j or j["status"] not in ("pending", "running"):
        return False
    j["_cancel"].set()
    if j["status"] == "pending":
        j["status"], j["message"] = "cancelled", "لغو شد"
    return True
