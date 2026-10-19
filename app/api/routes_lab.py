"""آزمایشگاه متن: نرمال‌سازی، مقایسه ابزارهای استخراج و پیش‌نمایش chunkها بدون embedding."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.deps import page_png, save_temp_upload
from app.api.schemas import NormalizeRequest, PreviewRequest
from app.config import get_settings
from app.core.extract import SUPPORTED_EXT, compare_extractors
from app.core.normalize import char_stats, clean_steps, odd_chars
from app.core.text_utils import ntok, vocab_score
from app.rag.ingest import preview

router = APIRouter(prefix="/lab", tags=["lab"])
_TOKEN = re.compile(r"^[0-9a-f]{32}$")
LAB_TTL = 24 * 3600


def _lab_dir() -> Path:
    d = get_settings().data_dir / "lab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lab_file(token: str) -> Path:
    if not _TOKEN.match(token):
        raise HTTPException(400, "شناسه نامعتبر")
    matches = list(_lab_dir().glob(token + ".*"))
    if not matches:
        raise HTTPException(404, "فایل آزمایشگاه پیدا نشد یا منقضی شده است")
    return matches[0]


def _cleanup() -> None:
    cutoff = time.time() - LAB_TTL
    for f in _lab_dir().iterdir():
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


@router.post("/normalize")
def normalize(body: NormalizeRequest):
    steps = clean_steps(body.text)
    final = steps[-1]["text"]
    return {
        "steps": steps,
        "before": {"odd": odd_chars(body.text).most_common(25), "vocab": round(vocab_score(body.text), 3),
                   "stats": char_stats(body.text), "tokens": ntok(body.text), "chars": len(body.text)},
        "after": {"odd": odd_chars(final).most_common(25), "vocab": round(vocab_score(final), 3),
                  "stats": char_stats(final), "tokens": ntok(final), "chars": len(final)},
    }


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise HTTPException(400, f"نوع فایل پشتیبانی نمی‌شود: {ext}")
    await asyncio.to_thread(_cleanup)
    tmp = await save_temp_upload(file)
    token = uuid.uuid4().hex
    dest = _lab_dir() / f"{token}{ext}"
    tmp.replace(dest)
    pages = 1
    if ext == ".pdf":
        import pymupdf as fitz
        with fitz.open(str(dest)) as d:
            pages = len(d)
    return {"token": token, "filename": file.filename, "pages": pages, "ext": ext}


@router.get("/{token}/compare")
async def compare(token: str, page: int = 1):
    path = _lab_file(token)
    if path.suffix != ".pdf":
        raise HTTPException(400, "مقایسه ابزارها فقط برای PDF است")
    try:
        return await asyncio.to_thread(compare_extractors, path, page)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{token}/preview")
async def chunk_preview(token: str, body: PreviewRequest):
    from app.api.routes_collections import sanitize_settings
    path = _lab_file(token)
    return await asyncio.to_thread(preview, path, sanitize_settings(body.options))


@router.get("/{token}/pages/{page}.png")
async def lab_page(token: str, page: int, dpi: int = 110):
    return await asyncio.to_thread(page_png, _lab_file(token), page, dpi)
