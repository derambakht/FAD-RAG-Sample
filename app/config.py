"""تنظیمات برنامه؛ همه مقادیر از متغیرهای محیطی یا فایل .env خوانده می‌شوند."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- وب سرور ---
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = BASE_DIR / "data"
    max_upload_mb: int = 100
    cors_origins: str = ""  # با کاما جدا شود؛ خالی = غیرفعال
    # ورود ساده (HTTP Basic) برای سرور عمومی؛ APP_PASSWORD خالی = بدون ورود
    app_username: str = "admin"
    app_password: str = ""

    # --- پایگاه داده برداری ---
    # chroma برای توسعه لوکال، qdrant برای سرور. هر پایگاه دانش هنگام ساخت backend خودش را ثبت می‌کند.
    vector_store: Literal["chroma", "qdrant"] = "chroma"
    chroma_host: str | None = None  # اگر تنظیم شود از Chroma سرور (HttpClient) استفاده می‌شود
    chroma_port: int = 8000
    qdrant_url: str | None = None  # مثل http://qdrant:6333
    qdrant_api_key: str | None = None
    qdrant_path: Path | None = None  # حالت embedded (بدون سرور)؛ پیش‌فرض data/qdrant

    # --- ارائه‌دهنده‌های مدل ---
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"  # روی ویندوز localhost اول IPv6 را امتحان می‌کند و کند است
    hf_device: str = "cpu"  # cpu / cuda / mps
    hf_token: str | None = None  # برای دانلود مدل‌ها روی IP های مشترک (خطای 429)
    hf_hub_offline: bool = False  # فقط از کش محلی بارگذاری کن (بدون تماس شبکه با HuggingFace)

    default_embedding_provider: Literal["openai", "ollama", "huggingface"] = "openai"
    default_embedding_model: str = "text-embedding-3-small"
    default_llm_provider: Literal["openai", "ollama", "huggingface"] = "openai"
    default_llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1500

    # --- مرحله پس از بازیابی (قابل روشن/خاموش در پنل) ---
    # Rerank با cross-encoder لوکال HuggingFace؛ خالی = این گزینه غیرفعال
    reranker_model: str = ""
    # Rerank با LLM؛ خالی = همان مدل پیش‌فرض گفتگو
    rerank_llm_provider: str = ""
    rerank_llm_model: str = ""
    # Jev (TypeSafe AI): فیلتر ارتباط و بررسی پاسخ‌پذیری با احتمال کالیبره
    typesafe_api_key: str | None = None
    jev_base_url: str = "https://api.typesafe.ai"  # یا https://openrouter.ai/api با کلید OpenRouter
    jev_model: str = "jev-latest"  # روی OpenRouter: typesafe/jev-1.14
    jev_threshold: float = 0.35  # حداقل احتمال ارتباط برای نگه داشتن یک متن
    jev_answerable_threshold: float = 0.5

    # --- پردازش متن ---
    tokenizer_encoding: str = "o200k_base"
    ocr_lang: str = "fas"
    tesseract_cmd: str | None = None

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rag.sqlite3"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def qdrant_local_path(self) -> Path:
        return self.qdrant_path or (self.data_dir / "qdrant")

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.chroma_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    # RAG_ENV_FILE=none: فایل .env خوانده نشود (برای تست‌ها روی سروری که .env واقعی دارد)
    s = Settings(_env_file=None) if os.environ.get("RAG_ENV_FILE") == "none" else Settings()
    s.ensure_dirs()
    # کتابخانه huggingface_hub این مقادیر را از محیط (و پیش از import) می‌خواند، نه از .env
    if s.hf_token:
        os.environ.setdefault("HF_TOKEN", s.hf_token)
    if s.hf_hub_offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    return s
