"""زنجیره پاسخ‌گویی فارسی با LangChain (LCEL) و استریم SSE."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.config import get_settings
from app.core.normalize import display_fa
from app.providers import describe, get_llm
from app.rag import analytics
from app.rag.jev import answerable as jev_answerable_prob
from app.rag.jev import describe_model as jev_describe
from app.rag.retrieval import Hit, search

log = logging.getLogger(__name__)

NOT_FOUND = "پاسخ این پرسش در اسناد موجود نیست."

SYSTEM_PROMPT = """تو یک دستیار پژوهشی دقیق و فارسی‌زبان هستی. فقط بر اساس «متن‌های بازیابی‌شده» پاسخ بده و همیشه به فارسی روان و معیار بنویس.
قواعد:
- اگر پاسخ در متن‌ها نیست، فقط بنویس: «""" + NOT_FOUND + """» و چیزی از دانش خودت اضافه نکن.
- بعد از هر جمله یا ادعا، شماره منبع را به شکل [1] یا [2][3] بیاور.
- اعداد، تاریخ‌ها، شماره مواد و نام‌ها را دقیقاً مطابق متن نقل کن.
- پاسخ را منظم و مختصر بنویس و در صورت نیاز از فهرست استفاده کن.
- هرگز به زبان دیگری جز فارسی پاسخ نده، مگر اصطلاح تخصصی لاتین در خود متن آمده باشد."""

ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder("history"),
    ("human", "متن‌های بازیابی‌شده:\n\n{context}\n\n---\nپرسش: {question}"),
])

CONDENSE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "پرسش آخر کاربر را با توجه به گفتگو به یک پرسش مستقل و کامل فارسی بازنویسی کن که بدون گفتگو "
               "قابل فهم باشد. فقط پرسش بازنویسی‌شده را بنویس، بدون هیچ توضیح دیگری."),
    MessagesPlaceholder("history"),
    ("human", "پرسش آخر: {question}"),
])


def format_context(hits: list[Hit]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        page = f"صفحه {h.page}" + (f" تا {h.page_end}" if h.page_end and h.page_end != h.page else "")
        head = f"[{i}] منبع: {h.source}، {page}" + (f"، بخش: {h.section}" if h.section else "")
        parts.append(f"{head}\n{h.text}")
    return "\n\n---\n\n".join(parts)


def to_messages(history: list[dict] | None, limit: int = 6) -> list:
    msgs = []
    for m in (history or [])[-limit:]:
        content = (m.get("content") or "")[:4000]
        msgs.append(HumanMessage(content) if m.get("role") == "user" else AIMessage(content))
    return msgs


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def analytics_stream(llm, data: analytics.SalesData, question: str, hist: list, llm_provider: str,
                           llm_model: str, t0: float) -> AsyncIterator[str] | None:
    """مسیر داده‌های جدولی: اگر پرسش آماری باشد رویدادهای پاسخ را برمی‌گرداند، وگرنه None (ادامه با RAG)."""
    t = time.perf_counter()
    try:
        res = await analytics.generate_and_run(llm, data, question, hist)
    except Exception as e:  # خطای LLM یا کوئری نباید گفتگو را متوقف کند؛ RAG معمولی امتحان می‌شود
        log.warning("مسیر تحلیل جدولی ناموفق بود: %s", e)
        return None
    if res is None or res.get("error"):
        return None
    sql_ms = round((time.perf_counter() - t) * 1000)

    async def gen() -> AsyncIterator[str]:
        pub = analytics.public_result(res)
        info = {
            "query": question, "mode": "analytics", "analytics": pub,
            "stages": [{"name": "sql", "label": "تبدیل پرسش به SQL", "in": data.rows, "out": pub["row_count"],
                        "ms": sql_ms, "attempts": pub["attempts"]},
                       {"name": "answer", "label": "نوشتن پاسخ از نتیجه", "in": pub["row_count"], "out": 1}],
            "timings": {"total_ms": sql_ms, "sql_ms": res.get("ms")},
            "models": [describe("llm", "LLM (SQL و پاسخ)", llm_provider, llm_model)],
        }
        yield sse("sources", {"hits": [], **info})
        chain = analytics.ANSWER_PROMPT | llm | StrOutputParser()
        first = None
        async for tok in chain.astream(analytics.answer_inputs(res, question, hist)):
            if first is None:
                first = time.perf_counter()
            yield sse("token", {"t": display_fa(tok)})
        yield sse("done", {"elapsed_ms": round((time.perf_counter() - t0) * 1000),
                           "first_token_ms": round(((first or time.perf_counter()) - t0) * 1000)})
    return gen()


async def answer_stream(*, collection_id: str, question: str, llm_provider: str, llm_model: str,
                        mode: str = "hybrid", k: int = 5, rerank: str | bool = "none",
                        history: list[dict] | None = None, condense: bool = False,
                        document_ids: list[str] | None = None, temperature: float | None = None,
                        jev: bool = False, jev_threshold: float | None = None,
                        jev_answerable: bool = True) -> AsyncIterator[str]:
    t0 = time.perf_counter()
    try:
        llm = get_llm(llm_provider, llm_model, temperature)
        hist = to_messages(history)
        # داده‌های جدولی (اکسل): پرسش‌های آماری با SQL دقیق پاسخ داده می‌شوند
        data = await asyncio.to_thread(analytics.get_data, collection_id, document_ids)
        if data is not None:
            stream = await analytics_stream(llm, data, question, hist, llm_provider, llm_model, t0)
            if stream is not None:
                async for ev in stream:
                    yield ev
                return
        retrieval_q = question
        if condense and hist:
            retrieval_q = (await (CONDENSE_PROMPT | llm | StrOutputParser()).ainvoke(
                {"history": hist, "question": question})).strip() or question
        hits, info = await asyncio.to_thread(search, collection_id, retrieval_q, mode, k, rerank=rerank,
                                             document_ids=document_ids, jev=jev, jev_threshold=jev_threshold)
        info["rewritten"] = retrieval_q if retrieval_q != question else None
        info["models"] = info.get("models", []) + [describe("llm", "LLM پاسخ", llm_provider, llm_model)]

        # Jev: اگر شواهد کافی نیست، LLM اصلاً فراخوانی نمی‌شود (صرفه‌جویی و جلوگیری از توهم)
        if jev and jev_answerable and hits:
            t = time.perf_counter()
            p, ans_meta = await asyncio.to_thread(jev_answerable_prob, info["query"], [h.text for h in hits])
            if not any(m["stage"] == "jev" for m in info["models"]):
                info["models"].insert(-1, jev_describe(ans_meta.get("model")))
            thr = get_settings().jev_answerable_threshold
            info["answerable"] = {"prob": round(p, 4), "threshold": thr, "ok": p >= thr}
            info["stages"].append({"name": "answerable", "label": "بررسی پاسخ‌پذیری Jev", "in": len(hits),
                                   "out": len(hits) if p >= thr else 0, "prob": round(p, 4), "threshold": thr,
                                   "ms": round((time.perf_counter() - t) * 1000)})
        skip_llm = not hits or bool(info.get("answerable") and not info["answerable"]["ok"])
        if skip_llm:
            info["models"][-1]["skipped"] = True  # LLM پاسخ فراخوانی نمی‌شود
        yield sse("sources", {"hits": [h.to_dict() for h in hits], **info})

        if skip_llm:
            yield sse("token", {"t": NOT_FOUND})
        else:
            chain = ANSWER_PROMPT | llm | StrOutputParser()
            first = None
            async for tok in chain.astream({"history": hist, "context": format_context(hits),
                                            "question": info["query"]}):
                if first is None:
                    first = time.perf_counter()
                yield sse("token", {"t": display_fa(tok)})
            info["first_token_ms"] = round(((first or time.perf_counter()) - t0) * 1000)
        yield sse("done", {"elapsed_ms": round((time.perf_counter() - t0) * 1000),
                           "first_token_ms": info.get("first_token_ms")})
    except Exception as e:
        log.exception("خطا در تولید پاسخ")
        yield sse("error", {"message": str(e)})


def answer(collection_id: str, question: str, llm_provider: str, llm_model: str, **kw) -> tuple[str, list[Hit]]:
    """نسخه همگام (برای CLI و نوت‌بوک)."""
    data = analytics.get_data(collection_id)
    if data is not None:
        llm = get_llm(llm_provider, llm_model)
        res = asyncio.run(analytics.generate_and_run(llm, data, question, []))
        if res is not None and not res.get("error"):
            text = (analytics.ANSWER_PROMPT | llm | StrOutputParser()).invoke(analytics.answer_inputs(res, question, []))
            return display_fa(text), []
    hits, info = search(collection_id, question, kw.get("mode", "hybrid"), kw.get("k", 5),
                        rerank=kw.get("rerank", "none"), jev=kw.get("jev", False))
    if not hits:
        return NOT_FOUND, []
    chain = ANSWER_PROMPT | get_llm(llm_provider, llm_model) | StrOutputParser()
    text = chain.invoke({"history": [], "context": format_context(hits), "question": info["query"]})
    return display_fa(text), hits
