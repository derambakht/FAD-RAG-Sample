"""لایه یکسان روی ChromaDB (لوکال) و Qdrant (سرور یا embedded) از طریق LangChain.

هر پایگاه دانش یک collection مستقل دارد؛ هرگز بردارهای دو مدل embedding متفاوت در یک collection نمی‌روند.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Callable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from app.config import get_settings

log = logging.getLogger(__name__)
BACKENDS = ("chroma", "qdrant")
_lock = threading.Lock()


# --- کلاینت‌ها (singleton) ----------------------------------------------------------
# ساخت هم‌زمان دو کلاینت روی یک مسیر (به‌ویژه Qdrant embedded که پوشه را قفل می‌کند) نباید رخ دهد
_client_lock = threading.Lock()


def _locked(fn):
    cached = lru_cache(maxsize=1)(fn)

    def wrapper():
        if cached.cache_info().currsize:
            return cached()
        with _client_lock:
            return cached()
    wrapper.cache_info, wrapper.cache_clear = cached.cache_info, cached.cache_clear
    return wrapper


@_locked
def chroma_client():
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    s = get_settings()
    cs = ChromaSettings(anonymized_telemetry=False, allow_reset=False)
    if s.chroma_host:
        return chromadb.HttpClient(host=s.chroma_host, port=s.chroma_port, settings=cs)
    return chromadb.PersistentClient(path=str(s.chroma_dir), settings=cs)


@_locked
def qdrant_client():
    from qdrant_client import QdrantClient

    s = get_settings()
    if s.qdrant_url:
        return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=60)
    s.qdrant_local_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(s.qdrant_local_path))  # حالت embedded؛ فقط برای توسعه


def close_clients() -> None:
    if qdrant_client.cache_info().currsize:
        try:
            qdrant_client().close()
        except Exception:
            pass
        qdrant_client.cache_clear()


def backend_status() -> dict:
    s = get_settings()
    out = {"default": s.vector_store}
    try:
        chroma_client().heartbeat()
        out["chroma"] = {"available": True, "mode": f"server {s.chroma_host}:{s.chroma_port}" if s.chroma_host
                         else f"persistent {s.chroma_dir}"}
    except Exception as e:
        out["chroma"] = {"available": False, "reason": str(e)}
    try:
        qdrant_client().get_collections()
        out["qdrant"] = {"available": True, "mode": f"server {s.qdrant_url}" if s.qdrant_url
                         else f"embedded {s.qdrant_local_path}"}
    except Exception as e:
        out["qdrant"] = {"available": False, "reason": str(e)}
    return out


# --- ساخت / باز کردن -----------------------------------------------------------------
def _ensure_qdrant_collection(name: str, dim: int) -> None:
    from qdrant_client import models

    client = qdrant_client()
    if not client.collection_exists(name):
        client.create_collection(name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
        if get_settings().qdrant_url:  # ایندکس payload برای فیلتر بر اساس سند (حالت embedded پشتیبانی نمی‌کند)
            try:
                client.create_payload_index(name, "metadata.document_id", models.PayloadSchemaType.KEYWORD)
            except Exception as e:
                log.warning("ساخت ایندکس payload ناموفق بود: %s", e)


def open_store(col: dict, embeddings: Embeddings) -> VectorStore:
    name, backend = col["vector_collection"], col["vector_backend"]
    with _lock:
        if backend == "chroma":
            from langchain_chroma import Chroma
            return Chroma(collection_name=name, embedding_function=embeddings, client=chroma_client(),
                          collection_configuration={"hnsw": {"space": "cosine"}})
        if backend == "qdrant":
            from langchain_qdrant import QdrantVectorStore
            _ensure_qdrant_collection(name, col["embedding_dim"])
            return QdrantVectorStore(client=qdrant_client(), collection_name=name, embedding=embeddings)
    raise ValueError(f"backend نامعتبر: {backend}")


def drop_collection(col: dict) -> None:
    name = col["vector_collection"]
    try:
        if col["vector_backend"] == "chroma":
            chroma_client().delete_collection(name)
        else:
            if qdrant_client().collection_exists(name):
                qdrant_client().delete_collection(name)
    except Exception as e:
        log.warning("حذف collection %s ناموفق بود: %s", name, e)


def count_vectors(col: dict) -> int | None:
    try:
        if col["vector_backend"] == "chroma":
            return chroma_client().get_collection(col["vector_collection"]).count()
        return qdrant_client().count(col["vector_collection"]).count
    except Exception:
        return None


# --- عملیات ---------------------------------------------------------------------------
def _clean_meta(m: dict) -> dict:
    return {k: v for k, v in m.items() if v is not None and v != ""}


def add_chunks(store: VectorStore, chunks: list[dict], batch_size: int = 64,
               progress: Callable[[int, int], None] | None = None) -> None:
    total = len(chunks)
    for i in range(0, total, batch_size):
        batch = chunks[i: i + batch_size]
        store.add_texts(
            texts=[c["text"] for c in batch],
            metadatas=[_clean_meta({"chunk_id": c["id"], "document_id": c["document_id"], "source": c.get("source"),
                                    "page": c.get("page"), "page_end": c.get("page_end"),
                                    "section": c.get("section"), "kind": c.get("kind")}) for c in batch],
            ids=[c["id"] for c in batch],
        )
        if progress:
            progress(min(i + batch_size, total), total)


def delete_ids(store: VectorStore, ids: list[str]) -> None:
    for i in range(0, len(ids), 500):
        store.delete(ids=ids[i: i + 500])


def _filter(backend: str, document_ids: list[str] | None):
    if not document_ids:
        return None
    if backend == "chroma":
        return {"document_id": {"$in": document_ids}}
    from qdrant_client import models
    return models.Filter(must=[models.FieldCondition(key="metadata.document_id",
                                                     match=models.MatchAny(any=document_ids))])


def dense_search(col: dict, store: VectorStore, query: str, k: int,
                 document_ids: list[str] | None = None) -> list[tuple[Document, float]]:
    """جستجوی برداری؛ امتیاز خروجی شباهت کسینوسی (بزرگ‌تر = نزدیک‌تر) است."""
    flt = _filter(col["vector_backend"], document_ids)
    res = store.similarity_search_with_score(query, k=k, filter=flt)
    if col["vector_backend"] == "chroma":  # Chroma فاصله کسینوسی برمی‌گرداند
        return [(d, 1.0 - s) for d, s in res]
    return res
