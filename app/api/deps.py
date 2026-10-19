from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from app.config import get_settings
from app.db import get_db


def collection_or_404(cid: str) -> dict:
    col = get_db().get_collection(cid)
    if col is None:
        raise HTTPException(404, "پایگاه دانش پیدا نشد")
    return col


def document_or_404(did: str) -> dict:
    doc = get_db().get_document(did)
    if doc is None:
        raise HTTPException(404, "سند پیدا نشد")
    return doc


async def save_temp_upload(f: UploadFile) -> Path:
    """ذخیره جریانی فایل در پوشه موقت با بررسی سقف حجم."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    tmp_dir = get_settings().data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=tmp_dir, suffix=Path(f.filename or "").suffix.lower())
    size = 0
    try:
        with open(fd, "wb") as out:
            while chunk := await f.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"حجم فایل بیشتر از {get_settings().max_upload_mb} مگابایت است")
                out.write(chunk)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def page_png(path: Path, page: int, dpi: int = 110) -> Response:
    import pymupdf as fitz

    if path.suffix.lower() != ".pdf":
        raise HTTPException(400, "تصویر صفحه فقط برای PDF در دسترس است")
    with fitz.open(str(path)) as doc:
        if not 1 <= page <= len(doc):
            raise HTTPException(404, "شماره صفحه نامعتبر است")
        png = doc[page - 1].get_pixmap(dpi=max(40, min(dpi, 200))).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})
