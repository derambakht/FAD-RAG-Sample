"""ایندکس‌سازی اسناد: استخراج ← پاک‌سازی ← بخش‌بندی ← ذخیره در SQLite ← embedding در vector store.

فایل‌های اکسل/CSV مسیر جداگانه دارند: سطرها در جدول sales_rows ذخیره می‌شوند (برای جمع و گروه‌بندی دقیق
با SQL در گفتگو) و همان سطرها به همراه خلاصه هر شعبه و تامین‌کننده به‌صورت chunk هم embedding می‌شوند.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path

from app.config import get_settings
from app.core.chunking import ChunkOptions, build_chunks
from app.core.extract import SUPPORTED_EXT, ExtractOptions, extract_file
from app.core.spreadsheet import TABLE_EXT, build_table_chunks, is_report_pdf, parse_file
from app.db import get_db, new_id
from app.rag.evaluation import audit_chunks
from app.rag.retrieval import forget_collection, get_store
from app.vectorstores import add_chunks, delete_ids, drop_collection

log = logging.getLogger(__name__)

DEFAULT_SETTINGS = {**ExtractOptions().__dict__, **ChunkOptions().__dict__}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w؀-ۿ‌.\- ]", "_", name).strip() or "file"
    return name[:150]


def store_upload(collection_id: str, src: Path, filename: str) -> tuple[Path, str, int]:
    """فایل موقت را در data/uploads/<collection>/ ذخیره می‌کند."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"نوع فایل پشتیبانی نمی‌شود: {ext} (مجاز: {', '.join(sorted(SUPPORTED_EXT))})")
    digest = sha256_file(src)
    dest_dir = get_settings().uploads_dir / collection_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest[:12]}_{safe_filename(filename)}"
    shutil.move(str(src), dest)
    return dest, digest, dest.stat().st_size


def effective_options(col: dict, doc: dict | None = None) -> dict:
    return {**DEFAULT_SETTINGS, **(col.get("settings") or {}), **((doc or {}).get("options") or {})}


# --- نسخه‌های مختلف یک سند ---------------------------------------------------------------------
# نشانه‌های نسخه/کپی در انتهای نام فایل؛ تاریخ و دوره (مثل 1404-07) عمداً حذف نمی‌شوند چون گزارش دوره دیگری است
_VERSION_SUFFIX = re.compile(
    r"(?:\s*\(\s*[\d۰-۹]+\s*\)|[\s_\-.]+(?:copy|کپی|final|نهایی|new|جدید|edited|updated|اصلاح[\s‌]*شده|ویرایش[\s‌]*شده)"
    r"|[\s_\-.]+(?:v|ver|version|نسخه|ویرایش)[\s_\-.]*[\d۰-۹]+)$", re.I)
OVERLAP_MIN = 0.5  # کمینه سهم سطرها/متن‌های مشترک برای اینکه دو سند نسخه‌های یک سند شمرده شوند


def version_key(filename: str) -> str:
    stem = Path(filename).stem.lower().replace("‌", " ")
    while True:
        new = _VERSION_SUFFIX.sub("", stem).strip(" _-.")
        if new == stem:
            break
        stem = new
    return re.sub(r"[\s_\-.]+", " ", stem).strip()


def previous_versions(collection_id: str, filename: str) -> list[dict]:
    """اسناد این پایگاه دانش که با همین نام (یا نام همراه با «(1)»، «کپی»، «نسخه ۲»، پسوند دیگر و ...) آمده‌اند."""
    key = version_key(filename)
    return [d for d in get_db().list_documents(collection_id) if key and version_key(d["filename"]) == key]


def _content_keys(db, doc: dict) -> set:
    if (doc.get("stats") or {}).get("table"):
        return db.sales_keys(doc["id"])
    return {hashlib.sha1(" ".join(c["body"].split()).encode()).hexdigest()
            for c in db.all_chunks(doc["collection_id"], [doc["id"]]) if c["body"].strip()}


def content_overlaps(doc_id: str, exclude: set[str] = frozenset()) -> list[dict]:
    """اسنادی که بخش بزرگی از سطرهای فروش یا متن‌های این سند را دارند (احتمالاً نسخه دیگری از همین سند)."""
    db = get_db()
    doc = db.get_document(doc_id)
    mine = _content_keys(db, doc)
    if not mine:
        return []
    out = []
    for other in db.list_documents(doc["collection_id"]):
        if other["id"] == doc_id or other["id"] in exclude or other["status"] != "ready":
            continue
        if bool((other.get("stats") or {}).get("table")) != bool((doc.get("stats") or {}).get("table")):
            continue
        shared = len(mine & _content_keys(db, other))
        if shared / len(mine) >= OVERLAP_MIN:
            out.append({"document_id": other["id"], "filename": other["filename"], "created_at": other["created_at"],
                        "shared": shared, "total": len(mine), "ratio": round(shared / len(mine), 3)})
    return sorted(out, key=lambda o: -o["ratio"])


def ingest_document(progress, doc_id: str, replaces: list[str] | None = None) -> dict:
    """ایندکس سند؛ اگر replaces داده شود، آن اسناد (نسخه‌های قبلی) فقط پس از پردازش موفق همین سند حذف می‌شوند."""
    result = _ingest_document(progress, doc_id)
    db = get_db()
    doc = db.get_document(doc_id)
    replaces = [r for r in (replaces or []) if r != doc_id]
    replaced = []
    for rid in replaces:
        old = db.get_document(rid)
        if old and old["collection_id"] == doc["collection_id"] and old["status"] != "processing":
            delete_document(rid)
            replaced.append(old["filename"])
    overlaps = content_overlaps(doc_id, exclude=set(replaces))
    if overlaps:
        db.update_document(doc_id, stats={**(doc["stats"] or {}), "overlaps": overlaps})
    return {**result, "replaced": replaced, "overlaps": overlaps}


def _ingest_document(progress, doc_id: str) -> dict:
    db = get_db()
    doc = db.get_document(doc_id)
    if doc is None:
        raise ValueError("سند پیدا نشد")
    col = db.get_collection(doc["collection_id"])
    opts = effective_options(col, doc)
    eopts, copts = ExtractOptions.from_dict(opts), ChunkOptions.from_dict(opts)
    db.update_document(doc_id, status="processing", error=None)
    store = get_store(col)
    new_ids: list[str] = []
    try:
        old_ids = db.chunk_ids_for_document(doc_id)
        if old_ids:  # ایندکس مجدد
            progress(0.02, "حذف chunkهای قبلی")
            delete_ids(store, old_ids)
            db.delete_chunks_for_document(doc_id)
            db.bump_version(col["id"])
        db.delete_sales_rows_for_document(doc_id)

        if _is_table_doc(Path(doc["path"])):
            return _ingest_table(progress, db, col, doc, store, copts, new_ids)

        ext = extract_file(Path(doc["path"]), eopts, lambda f, m: progress(0.05 + 0.35 * f, m))
        progress(0.42, "پاک‌سازی و بخش‌بندی")
        chunks, cstats = build_chunks(ext, copts, clean=eopts.clean)
        if not chunks:
            raise ValueError("هیچ متنی از سند استخراج نشد. " + " ".join(ext.warnings))

        rows = [{"id": new_id(), "collection_id": col["id"], "document_id": doc_id, **c} for c in chunks]
        new_ids = [r["id"] for r in rows]
        db.insert_chunks([{k: r[k] for k in ("id", "collection_id", "document_id", "idx", "text", "body", "section",
                                             "page", "page_end", "tokens", "kind")} for r in rows])
        for r in rows:
            r["source"] = doc["filename"]
        add_chunks(store, rows, progress=lambda d, t: progress(0.45 + 0.53 * d / t, f"embedding {d} از {t} chunk"))

        aud = audit_chunks(rows)["summary"]
        stats = {**ext.summary(), **cstats, "audit": aud, "page_details": [p.summary() for p in ext.pages][:500]}
        db.update_document(doc_id, status="ready", pages=len(ext.pages), stats=stats, error=None)
        db.bump_version(col["id"])
        return {"document_id": doc_id, "chunks": len(rows), "warnings": ext.warnings}
    except BaseException as e:
        if new_ids:  # برگرداندن تغییرات ناقص
            try:
                delete_ids(store, new_ids)
            except Exception:
                log.warning("حذف بردارهای ناقص ناموفق بود")
            db.delete_chunks_for_document(doc_id)
            db.bump_version(col["id"])
        db.delete_sales_rows_for_document(doc_id)
        db.update_document(doc_id, status="error", error=str(e) or e.__class__.__name__)
        raise


def _is_table_doc(path: Path) -> bool:
    """اکسل/CSV، یا PDF گزارش فروش تامین‌کننده/شعبه که متنش برای RAG معمولی قابل استفاده نیست."""
    return path.suffix.lower() in TABLE_EXT or is_report_pdf(path)


def _ingest_table(progress, db, col: dict, doc: dict, store, copts: ChunkOptions, new_ids: list[str]) -> dict:
    """اکسل/CSV: سطرها ← sales_rows، و سطرها + خلاصه‌ها ← chunk و embedding."""
    progress(0.05, "خواندن جدول‌های فایل")
    res = parse_file(Path(doc["path"]), progress=lambda f, m: progress(0.05 + 0.3 * f, m))
    records = res.records
    if records:
        db.insert_sales_rows(col["id"], doc["id"], records)
    progress(0.35, "ساخت متن سطرها و خلاصه‌ها")
    chunks = build_table_chunks(res, doc["filename"], copts.max_tokens)
    if not chunks:
        raise ValueError("هیچ داده‌ای از فایل خوانده نشد. " + " ".join(res.warnings))
    rows = [{"id": new_id(), "collection_id": col["id"], "document_id": doc["id"], **c} for c in chunks]
    new_ids.extend(r["id"] for r in rows)
    db.insert_chunks([{k: r[k] for k in ("id", "collection_id", "document_id", "idx", "text", "body", "section",
                                         "page", "page_end", "tokens", "kind")} for r in rows])
    for r in rows:
        r["source"] = doc["filename"]
    add_chunks(store, rows, progress=lambda d, t: progress(0.4 + 0.58 * d / t, f"embedding {d} از {t} chunk"))
    summary = res.summary()
    stats = {"table": summary, "chunks": len(rows), "warnings": res.warnings,
             "avg_tokens": round(sum(c["tokens"] for c in chunks) / len(chunks), 1),
             "max_tokens": max(c["tokens"] for c in chunks), "audit": audit_chunks(rows)["summary"]}
    db.update_document(doc["id"], status="ready", pages=len({b.sheet for b in res.blocks}) or len(res.generic),
                       stats=stats, error=None)
    db.bump_version(col["id"])
    return {"document_id": doc["id"], "chunks": len(rows), "rows": len(records), "warnings": res.warnings}


def delete_document(doc_id: str) -> None:
    db = get_db()
    doc = db.get_document(doc_id)
    if doc is None:
        return
    col = db.get_collection(doc["collection_id"])
    ids = db.chunk_ids_for_document(doc_id)
    if ids:
        delete_ids(get_store(col), ids)
    db.delete_document(doc_id)
    db.bump_version(col["id"])
    try:
        if not any(d["path"] == doc["path"] for d in db.list_documents(col["id"])):
            Path(doc["path"]).unlink(missing_ok=True)
    except OSError:
        pass


def delete_collection(cid: str) -> None:
    db = get_db()
    col = db.get_collection(cid)
    if col is None:
        return
    forget_collection(cid)
    drop_collection(col)
    db.delete_collection(cid)
    shutil.rmtree(get_settings().uploads_dir / cid, ignore_errors=True)


def preview(path: Path, options: dict, max_chunks: int = 300) -> dict:
    """پیش‌نمایش استخراج و بخش‌بندی بدون embedding (آزمایشگاه)."""
    opts = {**DEFAULT_SETTINGS, **options}
    eopts, copts = ExtractOptions.from_dict(opts), ChunkOptions.from_dict(opts)
    if _is_table_doc(path):
        res = parse_file(path)
        chunks = build_table_chunks(res, path.name, copts.max_tokens)
        aud = audit_chunks(chunks)
        summary = res.summary()
        return {"extract": {"pages": len(res.blocks), "methods": {"table": len(res.blocks)}, "reversed_pages": 0,
                            "avg_vocab": 1.0, "tables": len(res.blocks), "warnings": res.warnings},
                "pages": [], "stats": {"chunks": len(chunks), "rows": summary["rows"], "sections": len(res.blocks),
                                       "headings": 0, "branches": len(summary["branches"]),
                                       "suppliers": len(summary["suppliers"]),
                                       "avg_tokens": round(sum(c["tokens"] for c in chunks) / max(len(chunks), 1), 1),
                                       "max_tokens": max((c["tokens"] for c in chunks), default=0)},
                "audit": aud["summary"], "chunks": [{**c, **a} for c, a in zip(chunks, aud["rows"])][:max_chunks],
                "truncated": len(chunks) > max_chunks}
    ext = extract_file(path, eopts)
    chunks, cstats = build_chunks(ext, copts, clean=eopts.clean)
    aud = audit_chunks(chunks)
    return {
        "extract": ext.summary(),
        "pages": [p.summary() for p in ext.pages],
        "stats": cstats,
        "audit": aud["summary"],
        "chunks": [{**c, **a} for c, a in zip(chunks, aud["rows"])][:max_chunks],
        "truncated": len(chunks) > max_chunks,
    }
