"""نقطه ورود FastAPI: API زیر /api و پنل وب فارسی در ریشه."""
from __future__ import annotations

import base64
import logging
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router as api_router
from app.config import BASE_DIR, get_settings
from app.db import get_db
from app.providers import ProviderError, provider_status
from app.vectorstores import backend_status, close_clients

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WEB_DIR = BASE_DIR / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db().mark_interrupted()  # کارهای نیمه‌تمام قبل از ری‌استارت
    for warm in (provider_status, backend_status):  # گرم کردن کش وضعیت و کلاینت‌های پایگاه داده
        threading.Thread(target=warm, daemon=True).start()
    yield
    close_clients()


app = FastAPI(title="RAG فارسی", version=__version__, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

if origins := [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """ورود ساده با HTTP Basic وقتی APP_PASSWORD تنظیم شده باشد (مرورگر خودش فرم ورود را نشان می‌دهد)."""
    s = get_settings()
    if not s.app_password or request.url.path == "/api/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            user, pwd = "", ""
        if secrets.compare_digest(user.encode(), s.app_username.encode()) and \
                secrets.compare_digest(pwd.encode(), s.app_password.encode()):
            return await call_next(request)
    return Response("نیاز به ورود", status_code=401, media_type="text/plain; charset=utf-8",
                    headers={"WWW-Authenticate": 'Basic realm="RAG-FA", charset="UTF-8"'})


@app.exception_handler(ProviderError)
async def provider_error(_: Request, exc: ProviderError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


class RevalidatedStatic(StaticFiles):
    """فایل‌های JS/CSS پنل با هر بارگذاری اعتبارسنجی می‌شوند (ETag) تا نسخه قدیمی در مرورگر نماند."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        if not resp.headers.get("content-type", "").startswith("font/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


app.include_router(api_router)
app.mount("/static", RevalidatedStatic(directory=WEB_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})
