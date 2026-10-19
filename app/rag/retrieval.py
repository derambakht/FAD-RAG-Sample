"""بازیابی: برداری، BM25 و ترکیبی با Reciprocal Rank Fusion + reranker اختیاری (بخش ۸ راهنما)."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass

import numpy as np
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.core.normalize import clean_fa
from app.core.text_utils import bm25_tokens
from app.db import get_db
from app.providers import get_embeddings
from app.vectorstores import dense_search, open_store

MODES = ("dense", "bm25", "hybrid")
MODE_LABELS = {"dense": "برداری", "bm25": "کلیدواژه‌ای (BM25)", "hybrid": "ترکیبی (RRF)"}


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    source: str
    page: int | None
    page_end: int | None
    section: str
    text: str
    body: str
    kind: str
    score: float = 0.0
    dense_score: float | None = None
    dense_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rerank_score: float | None = None
    jev_prob: float | None = None  # احتمال ارتباط از Jev

    def to_dict(self) -> dict:
        return asdict(self)

    def to_document(self) -> Document:
        return Document(page_content=self.text, metadata={k: v for k, v in self.to_dict().items() if k != "text"})


# --- کش store و BM25 ------------------------------------------------------------------
_stores: dict[str, object] = {}
_bm25: dict[str, tuple[int, BM25Okapi | None, list[str], list[str]]] = {}
_lock = threading.Lock()


def get_store(col: dict):
    key = col["id"]
    with _lock:
        if key not in _stores:
            emb = get_embeddings(col["embedding_provider"], col["embedding_model"])
            if not col.get("embedding_dim"):  # ابعاد بردار در اولین استفاده از مدل تعیین می‌شود
                col = {**col, "embedding_dim": len(emb.embed_query("آزمون"))}
                get_db().update_collection(key, embedding_dim=col["embedding_dim"])
            _stores[key] = open_store(col, emb)
        return _stores[key]


def forget_collection(cid: str) -> None:
    with _lock:
        _stores.pop(cid, None)
        _bm25.pop(cid, None)


def _bm25_index(col: dict) -> tuple[BM25Okapi | None, list[str], list[str]]:
    """ایندکس BM25 در حافظه؛ با تغییر version پایگاه دانش دوباره ساخته می‌شود."""
    cached = _bm25.get(col["id"])
    if cached and cached[0] == col["version"]:
        return cached[1], cached[2], cached[3]
    rows = get_db().all_chunks(col["id"])
    ids = [r["id"] for r in rows]
    doc_ids = [r["document_id"] for r in rows]
    corpus = [bm25_tokens(r["text"]) for r in rows]
    bm = BM25Okapi(corpus) if any(corpus) else None
    with _lock:
        _bm25[col["id"]] = (col["version"], bm, ids, doc_ids)
    return bm, ids, doc_ids


def sparse_search(col: dict, query: str, k: int, document_ids: list[str] | None = None) -> list[tuple[str, float]]:
    bm, ids, doc_ids = _bm25_index(col)
    toks = bm25_tokens(query)
    if bm is None or not toks:
        return []
    scores = bm.get_scores(toks)
    if document_ids:
        allowed = set(document_ids)
        scores = np.where([d in allowed for d in doc_ids], scores, -np.inf)
    order = np.argsort(scores)[::-1][:k]
    return [(ids[i], float(scores[i])) for i in order if np.isfinite(scores[i]) and scores[i] > 0]


def rrf_fuse(rankings: list[list[str]], k_rrf: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank)."""
    fused: dict[str, float] = {}
    for ranked in rankings:
        for r, cid in enumerate(ranked):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k_rrf + r + 1)
    return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)


def search(col: dict | str, query: str, mode: str = "hybrid", k: int = 5, fetch_k: int = 20,
           rerank: str | bool = "none", document_ids: list[str] | None = None, clean: bool = True,
           jev: bool = False, jev_threshold: float | None = None) -> tuple[list[Hit], dict]:
    """مرحله پرسش: clean_fa ← بازیابی (برداری/BM25/RRF) ← [Rerank] ← [فیلتر Jev] ← k متن نهایی.

    info["stages"] ورودی/خروجی و زمان هر مرحله را برای نمایش در پنل گزارش می‌کند.
    """
    from app.rag import jev as jev_mod
    from app.rag.rerank import METHOD_LABELS, normalize_method, rerank_scores

    rerank = normalize_method(rerank)
    refine = rerank != "none" or jev
    db = get_db()
    if isinstance(col, str):
        col = db.get_collection(col)
        if col is None:
            raise ValueError("پایگاه دانش پیدا نشد")
    if mode not in MODES:
        raise ValueError(f"حالت جستجوی نامعتبر: {mode}")
    t0 = time.perf_counter()
    q = clean_fa(query) if clean else query  # نرمال‌سازی پرسش الزامی است
    fetch = max(fetch_k, k)
    timings: dict[str, float] = {}

    dense: list[tuple[str, float]] = []
    if mode in ("dense", "hybrid"):
        t = time.perf_counter()
        res = dense_search(col, get_store(col), q, fetch, document_ids)
        dense = [(d.metadata.get("chunk_id") or d.id, float(s)) for d, s in res]
        timings["dense_ms"] = round((time.perf_counter() - t) * 1000)
    sparse: list[tuple[str, float]] = []
    if mode in ("bm25", "hybrid"):
        t = time.perf_counter()
        sparse = sparse_search(col, q, fetch, document_ids)
        timings["bm25_ms"] = round((time.perf_counter() - t) * 1000)

    if mode == "dense":
        ranked = dense
    elif mode == "bm25":
        ranked = sparse
    else:
        ranked = rrf_fuse([[c for c, _ in dense], [c for c, _ in sparse]])

    dense_info = {c: (i + 1, s) for i, (c, s) in enumerate(dense)}
    sparse_info = {c: (i + 1, s) for i, (c, s) in enumerate(sparse)}
    candidates = ranked[: fetch if refine else k]
    rows = db.get_chunks([c for c, _ in candidates])
    hits: list[Hit] = []
    for cid, score in candidates:
        r = rows.get(cid)
        if r is None:  # بردار یتیم (مثلاً سند حذف‌شده)
            continue
        h = Hit(chunk_id=cid, document_id=r["document_id"], source=r["source"], page=r["page"],
                page_end=r["page_end"], section=r["section"] or "", text=r["text"], body=r["body"],
                kind=r["kind"] or "text", score=round(score, 5))
        if cid in dense_info:
            h.dense_rank, h.dense_score = dense_info[cid][0], round(dense_info[cid][1], 4)
        if cid in sparse_info:
            h.bm25_rank, h.bm25_score = sparse_info[cid][0], round(sparse_info[cid][1], 3)
        hits.append(h)

    stages = [{"name": "retrieve", "label": MODE_LABELS[mode], "out": len(hits),
               "ms": timings.get("dense_ms", 0) + timings.get("bm25_ms", 0)}]

    if rerank != "none" and hits:
        t = time.perf_counter()
        scores = rerank_scores(rerank, q, [h.text for h in hits])
        for h, s in zip(hits, scores):
            h.rerank_score = round(float(s), 4)
            h.score = h.rerank_score
        hits.sort(key=lambda h: h.rerank_score or 0, reverse=True)
        timings["rerank_ms"] = round((time.perf_counter() - t) * 1000)
        stages.append({"name": "rerank", "label": METHOD_LABELS[rerank], "in": len(hits), "out": len(hits),
                       "ms": timings["rerank_ms"]})

    dropped = 0
    if jev and hits:
        t = time.perf_counter()
        threshold = get_settings().jev_threshold if jev_threshold is None else jev_threshold
        probs, jev_meta = jev_mod.relevance(q, [h.text for h in hits])
        for h, p in zip(hits, probs):
            h.jev_prob = round(p, 4)
        n_in = len(hits)
        # مرتب‌سازی پایدار: در احتمال برابر، ترتیب Rerank/بازیابی حفظ می‌شود
        hits = sorted((h for h in hits if (h.jev_prob or 0) >= threshold), key=lambda h: -(h.jev_prob or 0))
        for h in hits:
            h.score = h.jev_prob
        dropped = n_in - len(hits)
        timings["jev_ms"] = round((time.perf_counter() - t) * 1000)
        stages.append({"name": "jev", "label": "فیلتر ارتباط Jev", "in": n_in, "out": len(hits), "dropped": dropped,
                       "threshold": threshold, "ms": timings["jev_ms"], "model": jev_meta.get("model"),
                       "cost": (jev_meta.get("usage") or {}).get("cost")})

    # کدام مدل، از کجا (برای نمایش در پنل)
    from app.providers import describe
    models = [describe("embedding", "Embedding", col["embedding_provider"], col["embedding_model"])] if mode != "bm25" else []
    if rerank == "llm":
        from app.rag.rerank import llm_rerank_target
        models.append(describe("rerank", "Rerank", *llm_rerank_target()))
    elif rerank == "cross_encoder":
        models.append(describe("rerank", "Rerank", "huggingface", get_settings().reranker_model))
    if jev and stages[-1]["name"] == "jev":
        models.append(jev_mod.describe_model(stages[-1].get("model")))

    final = hits[:k]
    if refine:
        stages.append({"name": "topk", "label": f"{k} متن برتر", "in": len(hits), "out": len(final), "ms": 0})
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000)
    return final, {"query": q, "mode": mode, "rerank": rerank, "jev": jev, "timings": timings,
                   "stages": stages, "dropped": dropped, "models": models}


class PersianRetriever(BaseRetriever):
    """Retriever استاندارد LangChain روی همین پایپلاین؛ قابل استفاده در هر chain دیگری."""

    collection_id: str
    mode: str = "hybrid"
    k: int = 5
    rerank: str = "none"  # none | llm | cross_encoder
    jev: bool = False
    document_ids: list[str] | None = None

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        hits, _ = search(self.collection_id, query, self.mode, self.k, rerank=self.rerank, jev=self.jev,
                         document_ids=self.document_ids)
        return [h.to_document() for h in hits]
