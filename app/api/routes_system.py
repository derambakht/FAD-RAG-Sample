from __future__ import annotations

import asyncio
import importlib.util

from fastapi import APIRouter, HTTPException

from app import __version__, jobs
from app.config import get_settings
from app.core.extract import SUPPORTED_EXT, ocr_status
from app.providers import EMBEDDING_PRESETS, LLM_PRESETS, PROVIDER_LABELS, provider_status, provider_where
from app.rag.ingest import DEFAULT_SETTINGS
from app.rag.jev import status as jev_status
from app.rag.rerank import status as rerank_status
from app.rag.retrieval import MODE_LABELS
from app.vectorstores import backend_status

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/system")
async def system():
    s = get_settings()
    providers, backends = await asyncio.gather(asyncio.to_thread(provider_status), asyncio.to_thread(backend_status))
    return {
        "version": __version__,
        "providers": providers,
        "provider_labels": PROVIDER_LABELS,
        "provider_where": {p: provider_where(p) for p in ("openai", "ollama", "huggingface")},
        "backends": backends,
        "ocr": ocr_status(),
        "hazm": importlib.util.find_spec("hazm") is not None,
        "presets": {"embedding": EMBEDDING_PRESETS, "llm": LLM_PRESETS},
        "defaults": {
            "embedding_provider": s.default_embedding_provider, "embedding_model": s.default_embedding_model,
            "llm_provider": s.default_llm_provider, "llm_model": s.default_llm_model,
            "vector_store": s.vector_store, "settings": DEFAULT_SETTINGS,
        },
        "modes": MODE_LABELS,
        "supported_ext": sorted(SUPPORTED_EXT),
        "max_upload_mb": s.max_upload_mb,
        "reranker": s.reranker_model or None,
        # مراحل اختیاری پس از بازیابی که کاربر در پنل روشن/خاموش می‌کند
        "postprocess": {"rerank": await asyncio.to_thread(rerank_status), "jev": jev_status()},
    }


@router.get("/jobs")
def list_jobs(active: bool = False):
    return jobs.list_jobs(active)


@router.get("/jobs/{jid}")
def get_job(jid: str):
    j = jobs.get(jid)
    if j is None:
        raise HTTPException(404, "کار پیدا نشد")
    return j


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    return {"cancelled": jobs.cancel(jid)}
