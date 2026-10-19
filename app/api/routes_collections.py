from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app import jobs
from app.api.deps import collection_or_404, document_or_404, page_png, save_temp_upload
from app.api.schemas import CollectionCreate, CollectionUpdate, ReindexRequest, VersionCheck
from app.config import get_settings
from app.db import get_db
from app.providers import PROVIDER_LABELS, needs_e5_prefix, provider_status
from app.rag import ingest
from app.rag.evaluation import audit_chunks
from app.vectorstores import count_vectors

router = APIRouter(tags=["collections"])

_CHOICES = {"strategy": {"structure", "recursive", "fixed"}, "method": {"auto", "pymupdf", "pdfplumber", "ocr"}}
_RANGES = {"max_tokens": (50, 4000), "overlap_sents": (0, 5), "overlap_tokens": (0, 1000),
           "chunk_chars": (100, 10000), "min_chunk_tokens": (0, 1000), "margin": (0.0, 0.3)}


def sanitize_settings(d: dict | None) -> dict:
    """فقط کلیدهای شناخته‌شده با نوع و بازه درست پذیرفته می‌شوند."""
    out = {}
    for k, v in (d or {}).items():
        if k not in ingest.DEFAULT_SETTINGS:
            continue
        default = ingest.DEFAULT_SETTINGS[k]
        try:
            if isinstance(default, bool):
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif isinstance(default, int):
                v = int(v)
            elif isinstance(default, float):
                v = float(v)
            else:
                v = str(v)
        except (TypeError, ValueError):
            raise HTTPException(422, f"مقدار نامعتبر برای {k}")
        if k in _CHOICES and v not in _CHOICES[k]:
            raise HTTPException(422, f"مقدار نامعتبر برای {k}: {v}")
        if k in _RANGES and not (_RANGES[k][0] <= v <= _RANGES[k][1]):
            raise HTTPException(422, f"{k} باید بین {_RANGES[k][0]} و {_RANGES[k][1]} باشد")
        out[k] = v
    return out


def _settings_warnings(model: str, settings: dict) -> list[str]:
    w = []
    eff = {**ingest.DEFAULT_SETTINGS, **settings}
    if needs_e5_prefix(model) and eff["max_tokens"] > 450:
        w.append("مدل‌های e5 حداکثر ۵۱۲ توکن ورودی دارند؛ max_tokens را زیر ۴۵۰ نگه دارید.")
    if not eff["clean"]:
        w.append("پاک‌سازی clean_fa خاموش است؛ فقط برای آزمایش مقایسه‌ای توصیه می‌شود.")
    return w


def _check_provider(provider: str, model: str) -> None:
    st = provider_status()[provider]
    if not st["available"]:
        raise HTTPException(400, f"{PROVIDER_LABELS[provider]} در دسترس نیست: {st.get('reason') or ''}")
    if provider == "ollama":
        names = set(st["models"]) | {m.split(":")[0] for m in st["models"] if m.endswith(":latest")}
        if model not in names:
            raise HTTPException(400, f"مدل «{model}» روی Ollama نصب نیست. اجرا کنید: ollama pull {model}")


def _public_collection(col: dict) -> dict:
    col = dict(col)
    col["effective_settings"] = {**ingest.DEFAULT_SETTINGS, **(col.get("settings") or {})}
    return col


# --- پایگاه‌های دانش ---------------------------------------------------------------------
@router.get("/collections")
def list_collections():
    return [_public_collection(c) for c in get_db().list_collections()]


@router.post("/collections", status_code=201)
async def create_collection(body: CollectionCreate):
    await asyncio.to_thread(_check_provider, body.embedding_provider, body.embedding_model)
    settings = sanitize_settings(body.settings)
    try:
        col = get_db().create_collection(
            name=body.name.strip(), description=body.description.strip(),
            embedding_provider=body.embedding_provider, embedding_model=body.embedding_model.strip(),
            vector_backend=body.vector_backend or get_settings().vector_store, settings=settings)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "پایگاه دانشی با این نام وجود دارد")
    return {**_public_collection(col), "warnings": _settings_warnings(body.embedding_model, settings)}


@router.get("/collections/{cid}")
async def get_collection(cid: str):
    col = collection_or_404(cid)
    return {**_public_collection(col), "vectors": await asyncio.to_thread(count_vectors, col)}


@router.patch("/collections/{cid}")
def update_collection(cid: str, body: CollectionUpdate):
    col = collection_or_404(cid)
    kw = {}
    if body.name is not None:
        kw["name"] = body.name.strip()
    if body.description is not None:
        kw["description"] = body.description.strip()
    if body.settings is not None:
        kw["settings"] = {**(col["settings"] or {}), **sanitize_settings(body.settings)}
    try:
        get_db().update_collection(cid, **kw)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "پایگاه دانشی با این نام وجود دارد")
    col = collection_or_404(cid)
    return {**_public_collection(col), "warnings": _settings_warnings(col["embedding_model"], col["settings"])}


@router.delete("/collections/{cid}", status_code=204)
async def delete_collection(cid: str):
    collection_or_404(cid)
    await asyncio.to_thread(ingest.delete_collection, cid)


@router.post("/collections/{cid}/reindex")
def reindex_collection(cid: str):
    collection_or_404(cid)
    out = []
    for d in get_db().list_documents(cid):
        get_db().update_document(d["id"], status="pending", error=None)
        out.append(jobs.submit("ingest", f"ایندکس مجدد {d['filename']}", ingest.ingest_document, d["id"],
                               meta={"document_id": d["id"], "collection_id": cid}))
    return {"jobs": out}


# --- اسناد ---------------------------------------------------------------------------
@router.get("/collections/{cid}/documents")
def list_documents(cid: str):
    collection_or_404(cid)
    return get_db().list_documents(cid)


def _version_info(d: dict) -> dict:
    t = (d.get("stats") or {}).get("table") or {}
    return {"id": d["id"], "filename": d["filename"], "created_at": d["created_at"], "size": d["size"],
            "status": d["status"], "chunks": d.get("chunks", 0), "pages": d.get("pages", 0), "rows": t.get("rows"),
            "branches": len(t.get("branches") or []) or None}


@router.post("/collections/{cid}/documents/check")
def check_versions(cid: str, body: VersionCheck):
    """پیش از بارگذاری: آیا نسخه قبلی همین سند‌ها (همان نام یا نام همراه با «(1)»، «نسخه ۲»، ...) وجود دارد؟"""
    collection_or_404(cid)
    return {"files": [{"filename": name, "previous": [_version_info(d) for d in ingest.previous_versions(cid, name)]}
                      for name in body.files]}


@router.post("/collections/{cid}/documents", status_code=202)
async def upload_documents(cid: str, files: list[UploadFile] = File(...), options: str = Form("{}"),
                           replace: str = Form("{}")):
    """replace: {"نام فایل": [شناسه سندهای نسخه قبلی]} — پس از پردازش موفق فایل جدید حذف می‌شوند."""
    collection_or_404(cid)
    try:
        opts = sanitize_settings(json.loads(options or "{}"))
        replace_map = json.loads(replace or "{}")
    except json.JSONDecodeError:
        raise HTTPException(422, "options و replace باید JSON معتبر باشند")
    if not isinstance(replace_map, dict):
        raise HTTPException(422, "replace باید نگاشت نام فایل به فهرست شناسه اسناد باشد")
    db = get_db()
    for ids in replace_map.values():
        for rid in ids if isinstance(ids, list) else [ids]:
            old = db.get_document(str(rid))
            if old is None or old["collection_id"] != cid:
                raise HTTPException(404, "سند نسخه قبلی در این پایگاه دانش پیدا نشد")
            if old["status"] == "processing":
                raise HTTPException(409, f"نسخه قبلی «{old['filename']}» در حال پردازش است؛ پس از پایان دوباره تلاش کنید")
    created, skipped, job_list = [], [], []
    for f in files:
        tmp = await save_temp_upload(f)
        try:
            path, digest, size = await asyncio.to_thread(ingest.store_upload, cid, tmp, f.filename or "file")
        except ValueError as e:
            tmp.unlink(missing_ok=True)
            skipped.append({"filename": f.filename, "reason": str(e)})
            continue
        if (dup := db.find_document_by_hash(cid, digest)) is not None:
            if Path(dup["path"]) != path:
                path.unlink(missing_ok=True)
            skipped.append({"filename": f.filename, "reason": f"تکراری است (همان «{dup['filename']}»)"})
            continue
        doc = db.create_document(cid, f.filename or path.name, str(path), digest, size, opts)
        created.append(doc)
        ids = replace_map.get(f.filename or "", [])
        replaces = [str(x) for x in (ids if isinstance(ids, list) else [ids])]
        job_list.append(jobs.submit("ingest", f"ایندکس {doc['filename']}", ingest.ingest_document, doc["id"], replaces,
                                    meta={"document_id": doc["id"], "collection_id": cid, "replaces": replaces}))
    return {"documents": created, "skipped": skipped, "jobs": job_list}


@router.get("/documents/{did}")
def get_document(did: str):
    return document_or_404(did)


@router.delete("/documents/{did}", status_code=204)
async def delete_document(did: str):
    doc = document_or_404(did)
    if doc["status"] == "processing":
        raise HTTPException(409, "سند در حال پردازش است")
    await asyncio.to_thread(ingest.delete_document, did)


@router.post("/documents/{did}/reindex", status_code=202)
def reindex_document(did: str, body: ReindexRequest):
    doc = document_or_404(did)
    if doc["status"] == "processing":
        raise HTTPException(409, "سند در حال پردازش است")
    if body.options is not None:
        get_db().update_document(did, options=sanitize_settings(body.options))
    get_db().update_document(did, status="pending", error=None)
    return jobs.submit("ingest", f"ایندکس مجدد {doc['filename']}", ingest.ingest_document, did,
                       meta={"document_id": did, "collection_id": doc["collection_id"]})


@router.get("/documents/{did}/file")
def download_document(did: str):
    doc = document_or_404(did)
    return FileResponse(doc["path"], filename=doc["filename"])


@router.get("/documents/{did}/pages/{page}.png")
async def document_page(did: str, page: int, dpi: int = 110):
    doc = document_or_404(did)
    return await asyncio.to_thread(page_png, Path(doc["path"]), page, dpi)


# --- chunkها و audit -------------------------------------------------------------------
@router.get("/collections/{cid}/chunks")
def list_chunks(cid: str, document_id: str | None = None, q: str | None = None,
                offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    collection_or_404(cid)
    from app.core.normalize import clean_fa
    rows, total = get_db().list_chunks(cid, document_id, clean_fa(q) if q else None, offset, limit)
    return {"items": rows, "total": total}


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    c = get_db().get_chunk(chunk_id)
    if c is None:
        raise HTTPException(404, "chunk پیدا نشد")
    return c


@router.get("/collections/{cid}/audit")
async def audit(cid: str, document_id: str | None = None, min_tokens: int = 50, min_vocab: float = 0.6):
    collection_or_404(cid)
    rows = get_db().all_chunks(cid, [document_id] if document_id else None)
    res = await asyncio.to_thread(audit_chunks, rows, min_tokens, min_vocab)
    for r, c in zip(res["rows"], rows):
        r.update(source=c["source"], document_id=c["document_id"], page=c["page"], page_end=c["page_end"],
                 section=c["section"], idx=c["idx"], kind=c["kind"], preview=c["body"][:220])
    return res
