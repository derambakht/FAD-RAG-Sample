"""Rerank پس از بازیابی: با LLM (مثلاً gpt-4o-mini) یا cross-encoder لوکال.

هر دو روی همان فهرست کاندیدها کار می‌کنند و فقط ترتیب را عوض می‌کنند؛ بازیابی
اولیه تعیین می‌کند چه متن‌هایی اصلاً در فهرست باشند.
"""
from __future__ import annotations

import json
import logging
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.config import get_settings
from app.providers import ProviderError, get_llm, get_reranker

log = logging.getLogger(__name__)

METHODS = ("none", "llm", "cross_encoder")
METHOD_LABELS = {"none": "بدون Rerank", "llm": "Rerank با LLM", "cross_encoder": "Rerank با Cross-encoder"}

LLM_RERANK_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "تو داور ارتباط متن با پرسش هستی. به هر متن از 0 تا 10 امتیاز بده: 10 یعنی متن مستقیماً و کامل به "
               "پرسش پاسخ می‌دهد، 5 یعنی بخشی از پاسخ یا زمینه مرتبط دارد، 0 یعنی بی‌ربط است یا فقط کلمات مشترک دارد. "
               "فقط JSON برگردان به شکل {{\"scores\": [{{\"id\": 1, \"score\": 7}}, ...]}} برای همه متن‌ها."),
    ("human", "پرسش: {question}\n\nمتن‌ها:\n{passages}"),
])


def normalize_method(rerank) -> str:
    """سازگاری با نسخه قبل: True یعنی cross-encoder."""
    if rerank is True:
        return "cross_encoder"
    if not rerank:
        return "none"
    if rerank not in METHODS:
        raise ValueError(f"روش rerank نامعتبر: {rerank}")
    return rerank


def llm_rerank_target() -> tuple[str, str]:
    s = get_settings()
    return (s.rerank_llm_provider or s.default_llm_provider, s.rerank_llm_model or s.default_llm_model)


def _parse_scores(text: str, n: int) -> list[float]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("پاسخ LLM برای rerank قالب JSON نداشت")
    data = json.loads(m.group(0))
    scores = [0.0] * n
    for item in data.get("scores", []):
        i = int(item.get("id", 0)) - 1
        if 0 <= i < n:
            scores[i] = max(0.0, min(10.0, float(item.get("score", 0))))
    return scores


def rerank_llm(question: str, texts: list[str]) -> list[float]:
    """یک فراخوانی برای همه کاندیدها؛ امتیاز ۰ تا ۱۰ برای هر متن."""
    provider, model = llm_rerank_target()
    passages = "\n\n".join(f"[{i}] {t[:1500]}" for i, t in enumerate(texts, 1))
    chain = LLM_RERANK_PROMPT | get_llm(provider, model, 0.0) | StrOutputParser()
    return _parse_scores(chain.invoke({"question": question, "passages": passages}), len(texts))


def rerank_cross_encoder(question: str, texts: list[str]) -> list[float]:
    try:
        model = get_reranker()
    except ProviderError:
        raise
    except Exception as e:  # دانلود ناموفق مدل و مانند آن
        raise ProviderError(f"مدل cross-encoder «{get_settings().reranker_model}» بارگذاری نشد: {e.__class__.__name__}") from e
    return [float(s) for s in model.predict([(question, t) for t in texts])]


def rerank_scores(method: str, question: str, texts: list[str]) -> list[float]:
    if method == "llm":
        return rerank_llm(question, texts)
    if method == "cross_encoder":
        return rerank_cross_encoder(question, texts)
    raise ValueError(method)


def status() -> dict:
    s = get_settings()
    provider, model = llm_rerank_target()
    from app.providers import provider_status
    ps = provider_status()
    return {
        "llm": {"available": ps.get(provider, {}).get("available", False), "provider": provider, "model": model},
        "cross_encoder": {"available": bool(s.reranker_model) and ps["huggingface"]["available"],
                          "model": s.reranker_model or None},
    }
