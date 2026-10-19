from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import collection_or_404
from app.api.schemas import ChatRequest, SearchRequest, SessionCreate, SessionUpdate, SuggestRequest
from app.db import get_db
from app.rag.chain import answer_stream
from app.rag.retrieval import search
from app.rag.suggest import suggest

router = APIRouter(tags=["chat"])
log = logging.getLogger(__name__)
HISTORY_TURNS = 6  # تعداد پیام‌های قبلی که به LLM داده می‌شود


@router.post("/search")
async def search_endpoint(body: SearchRequest):
    col = collection_or_404(body.collection_id)
    hits, info = await asyncio.to_thread(search, col, body.query, body.mode, body.k, rerank=body.rerank,
                                         document_ids=body.document_ids, clean=body.clean, jev=body.jev,
                                         jev_threshold=body.jev_threshold)
    return {"hits": [h.to_dict() for h in hits], **info}


# --- جلسه‌های گفتگو ------------------------------------------------------------------
def _session_or_404(sid: str) -> dict:
    s = get_db().get_chat_session(sid)
    if s is None:
        raise HTTPException(404, "جلسه گفتگو پیدا نشد")
    return s


def _public_message(m: dict) -> dict:
    meta = m.get("meta") or {}
    return {"id": m["id"], "role": m["role"], "content": m["content"], "created_at": m["created_at"],
            "hits": meta.get("hits", []), "info": meta.get("info"), "done": meta.get("done"),
            "error": meta.get("error"), "aborted": meta.get("aborted", False)}


@router.get("/chat/sessions")
def list_sessions(collection_id: str):
    collection_or_404(collection_id)
    return get_db().list_chat_sessions(collection_id)


@router.post("/chat/sessions", status_code=201)
def create_session(body: SessionCreate):
    collection_or_404(body.collection_id)
    return get_db().create_chat_session(body.collection_id, body.title.strip())


@router.get("/chat/sessions/{sid}")
def get_session(sid: str):
    s = _session_or_404(sid)
    return {**s, "messages_list": [_public_message(m) for m in get_db().list_chat_messages(sid)]}


@router.patch("/chat/sessions/{sid}")
def rename_session(sid: str, body: SessionUpdate):
    _session_or_404(sid)
    get_db().rename_chat_session(sid, body.title.strip())
    return get_db().get_chat_session(sid)


@router.delete("/chat/sessions/{sid}", status_code=204)
def delete_session(sid: str):
    _session_or_404(sid)
    get_db().delete_chat_session(sid)


@router.delete("/chat/sessions")
def delete_all_sessions(collection_id: str):
    collection_or_404(collection_id)
    return {"deleted": get_db().delete_chat_sessions(collection_id)}


@router.post("/chat/suggestions")
async def suggestions(body: SuggestRequest):
    """پرسش‌های پیشنهادی از داده‌های همین پایگاه دانش و در ادامه پرسش‌های قبلی کاربر."""
    collection_or_404(body.collection_id)
    if body.session_id and _session_or_404(body.session_id)["collection_id"] != body.collection_id:
        raise HTTPException(400, "این جلسه متعلق به پایگاه دانش دیگری است")
    return await suggest(body.collection_id, body.session_id, body.llm_provider, body.llm_model, body.n)


# --- گفتگو ---------------------------------------------------------------------------
def _parse_sse(chunk: str) -> tuple[str, dict]:
    event, data = "message", "{}"
    for line in chunk.split("\n"):
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
    return event, json.loads(data)


async def _persisting(stream: AsyncIterator[str], session_id: str) -> AsyncIterator[str]:
    """رویدادها را بی‌تغییر عبور می‌دهد و در پایان (حتی اگر کاربر متوقف کند) پاسخ را در جلسه ذخیره می‌کند."""
    content, meta = "", {}
    try:
        async for chunk in stream:
            try:
                event, data = _parse_sse(chunk)
                if event == "sources":
                    meta["hits"] = data.pop("hits", [])
                    meta["info"] = data
                elif event == "token":
                    content += data.get("t", "")
                elif event == "done":
                    meta["done"] = data
                elif event == "error":
                    meta["error"] = data.get("message")
            except Exception:  # pragma: no cover - ذخیره نباید استریم را خراب کند
                log.exception("خطا در خواندن رویداد برای ذخیره")
            yield chunk
    finally:
        if "done" not in meta and "error" not in meta:
            meta["aborted"] = True
        try:
            get_db().add_chat_message(session_id, "assistant", content, meta)
        except Exception:
            log.exception("ذخیره پاسخ در جلسه ناموفق بود")


@router.post("/chat")
async def chat(body: ChatRequest):
    collection_or_404(body.collection_id)
    history = [m.model_dump() for m in body.history]
    if body.session_id:
        db = get_db()
        session = _session_or_404(body.session_id)
        if session["collection_id"] != body.collection_id:
            raise HTTPException(400, "این جلسه متعلق به پایگاه دانش دیگری است")
        history = [{"role": m["role"], "content": m["content"]} for m in db.list_chat_messages(body.session_id)
                   if m["content"] and not (m["meta"] or {}).get("error")][-HISTORY_TURNS:]
        db.add_chat_message(body.session_id, "user", body.question)
        if not session["title"]:  # عنوان خودکار از اولین پرسش
            q = " ".join(body.question.split())
            db.rename_chat_session(body.session_id, q[:60] + ("…" if len(q) > 60 else ""))
    stream = answer_stream(
        collection_id=body.collection_id, question=body.question, llm_provider=body.llm_provider,
        llm_model=body.llm_model, mode=body.mode, k=body.k, rerank=body.rerank,
        history=history, condense=body.condense,
        document_ids=body.document_ids, temperature=body.temperature,
        jev=body.jev, jev_threshold=body.jev_threshold, jev_answerable=body.jev_answerable,
    )
    if body.session_id:
        stream = _persisting(stream, body.session_id)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
