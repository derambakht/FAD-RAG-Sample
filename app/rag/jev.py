"""Jev (مدل تصمیم‌گیری TypeSafe AI) در مرحله پرسش.

Jev متن تولید نمی‌کند؛ به پرسش‌های بله/خیر (Noul) احتمال کالیبره‌شده برمی‌گرداند. اینجا دو کار انجام می‌دهد:
  ۱. فیلتر ارتباط: برای هر متن بازیابی‌شده P(متن واقعاً به پرسش پاسخ می‌دهد) را می‌دهد؛ متن‌ها بر اساس آن مرتب
     و زیر آستانه حذف می‌شوند.
  ۲. بررسی پاسخ‌پذیری: آیا متن‌های باقی‌مانده روی‌هم برای پاسخ کافی‌اند؟ اگر نه، LLM اصلاً فراخوانی نمی‌شود.

API: POST {JEV_BASE_URL}/v1/systemone  با  {"model", "state", "questions": {id: {"type": "noul", "instructions"}}}
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import get_settings
from app.providers import ProviderError

log = logging.getLogger(__name__)

RELEVANCE_INSTRUCTIONS = (
    "Does the passage below directly answer the user's question in `state.question`, or contain the specific "
    "facts needed to answer it? Answer no if it only shares keywords or the general topic. "
    "The question and passage are in Persian.\n\nPassage:\n{passage}"
)
ANSWERABLE_INSTRUCTIONS = (
    "Taken together, do the passages in `state.passages` contain enough information to fully and correctly answer "
    "the question in `state.question`? The texts are in Persian."
)

# برای تست‌ها جایگزین می‌شود
_transport: httpx.BaseTransport | None = None


def configured() -> bool:
    return bool(get_settings().typesafe_api_key)


def where() -> tuple[str, str]:
    """(میزبان، واسط): مثلاً ("openrouter.ai", "OpenRouter") یا ("api.typesafe.ai", "TypeSafe")."""
    from urllib.parse import urlparse
    host = urlparse(get_settings().jev_base_url).netloc
    return host, ("OpenRouter" if "openrouter" in host else "TypeSafe")


def describe_model(model: str | None = None) -> dict:
    from app.providers import describe
    host, via = where()
    return describe("jev", "Jev", "jev", model or get_settings().jev_model, where=f"{via} · {host}",
                    provider_label="TypeSafe Jev")


def status() -> dict:
    s = get_settings()
    host, via = where()
    return {"available": configured(), "base_url": s.jev_base_url, "model": s.jev_model, "where": host, "via": via,
            "threshold": s.jev_threshold, "answerable_threshold": s.jev_answerable_threshold,
            "reason": None if configured() else "TYPESAFE_API_KEY در .env تنظیم نشده"}


def _prob(ans) -> float:
    """پاسخ Noul را با تحمل تفاوت قالب‌ها به احتمال تبدیل می‌کند."""
    if isinstance(ans, (int, float)):
        return float(ans)
    if isinstance(ans, dict):
        for key in ("noul", "probability", "p", "yes"):
            if isinstance(ans.get(key), (int, float)):
                return float(ans[key])
    raise ValueError(f"قالب پاسخ Jev ناشناخته است: {str(ans)[:120]}")


def system_one(state: dict, questions: dict[str, dict]) -> tuple[dict[str, float], dict]:
    s = get_settings()
    if not s.typesafe_api_key:
        raise ProviderError("Jev فعال نیست: کلید TYPESAFE_API_KEY را در .env تنظیم کنید (یا کلید OpenRouter با "
                            "JEV_BASE_URL=https://openrouter.ai/api).")
    url = s.jev_base_url.rstrip("/") + "/v1/systemone"
    body = {"model": s.jev_model, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {s.typesafe_api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30, transport=_transport) as client:
        for attempt in range(3):
            r = client.post(url, json=body, headers=headers)
            if r.status_code in (429, 529) and attempt < 2:  # محدودیت نرخ یا شلوغی سرویس
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    if r.status_code == 401:
        raise ProviderError("کلید Jev (TYPESAFE_API_KEY) نامعتبر است")
    if r.status_code >= 400:
        raise ProviderError(f"خطای Jev ({r.status_code}): {r.text[:200]}")
    data = r.json()
    answers = data.get("answers") or data.get("nouls") or {}
    probs = {qid: _prob(answers[qid]) for qid in questions if qid in answers}
    if len(probs) != len(questions):
        raise ProviderError("پاسخ Jev برای همه پرسش‌ها برنگشت")
    return probs, {"model": data.get("model"), "usage": data.get("usage")}


def relevance(question: str, passages: list[str]) -> tuple[list[float], dict]:
    """یک درخواست برای همه متن‌ها؛ خروجی P(مرتبط) به همان ترتیب."""
    qs = {f"p{i}": {"type": "noul", "instructions": RELEVANCE_INSTRUCTIONS.format(passage=p[:6000])}
          for i, p in enumerate(passages)}
    probs, meta = system_one({"question": question}, qs)
    return [probs[f"p{i}"] for i in range(len(passages))], meta


def answerable(question: str, passages: list[str]) -> tuple[float, dict]:
    probs, meta = system_one({"question": question, "passages": [p[:6000] for p in passages]},
                             {"answerable": {"type": "noul", "instructions": ANSWERABLE_INSTRUCTIONS}})
    return probs["answerable"], meta
