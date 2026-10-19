"""کارخانه مدل‌های Embedding و LLM برای OpenAI، Ollama و HuggingFace (بخش ۸ راهنما)."""
from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from app.config import get_settings

log = logging.getLogger(__name__)

PROVIDERS = ("openai", "ollama", "huggingface")
PROVIDER_LABELS = {"openai": "OpenAI", "ollama": "Ollama (لوکال)", "huggingface": "HuggingFace (لوکال)"}

EMBEDDING_PRESETS = {
    "openai": ["text-embedding-3-small", "text-embedding-3-large"],
    "ollama": ["bge-m3", "nomic-embed-text", "snowflake-arctic-embed2"],
    "huggingface": [
        "BAAI/bge-m3",
        "intfloat/multilingual-e5-large",
        "intfloat/multilingual-e5-base",
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    ],
}
LLM_PRESETS = {
    "openai": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o", "gpt-4.1"],
    "ollama": ["qwen2.5:7b", "llama3.1:8b", "gemma2:9b", "qwen2.5:14b"],
    "huggingface": ["Qwen/Qwen2.5-1.5B-Instruct", "Qwen/Qwen2.5-3B-Instruct"],
}


class ProviderError(RuntimeError):
    pass


# --- «از کجا»: منبع هر مدل برای نمایش در پنل ------------------------------------------
def provider_where(provider: str) -> str:
    from urllib.parse import urlparse
    s = get_settings()
    if provider == "openai":
        return urlparse(s.openai_base_url).netloc if s.openai_base_url else "api.openai.com"
    if provider == "ollama":
        return urlparse(s.ollama_base_url).netloc or s.ollama_base_url
    if provider == "huggingface":
        return f"لوکال روی همین سرور ({s.hf_device.upper()})"
    return ""


def describe(stage: str, label: str, provider: str, model: str, where: str | None = None,
             provider_label: str | None = None) -> dict:
    """یک ردیف «کدام مدل، از کجا» برای مراحل پاسخ."""
    return {"stage": stage, "label": label, "provider": provider,
            "provider_label": provider_label or PROVIDER_LABELS.get(provider, provider),
            "model": model, "where": where if where is not None else provider_where(provider)}


# --- Embedding ----------------------------------------------------------------------
class PrefixedEmbeddings(Embeddings):
    """مدل‌های e5 بدون پیشوند query:/passage: دقت بازیابی محسوسی از دست می‌دهند."""

    def __init__(self, inner: Embeddings, query_prefix: str = "query: ", doc_prefix: str = "passage: "):
        self.inner, self.query_prefix, self.doc_prefix = inner, query_prefix, doc_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents([self.doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(self.query_prefix + text)


def needs_e5_prefix(model: str) -> bool:
    return "e5" in model.lower().split("/")[-1]


_emb_lock = threading.Lock()


@lru_cache(maxsize=8)
def _build_embeddings(provider: str, model: str) -> Embeddings:
    s = get_settings()
    if provider == "openai":
        if not s.openai_api_key:
            raise ProviderError("کلید OPENAI_API_KEY در فایل .env تنظیم نشده است")
        from langchain_openai import OpenAIEmbeddings
        emb: Embeddings = OpenAIEmbeddings(model=model, api_key=s.openai_api_key, base_url=s.openai_base_url,
                                           chunk_size=256)
    elif provider == "ollama":
        from langchain_ollama import OllamaEmbeddings
        emb = OllamaEmbeddings(model=model, base_url=s.ollama_base_url)
    elif provider == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as e:
            raise ProviderError("بسته‌های HuggingFace نصب نیستند: pip install -r requirements-hf.txt") from e
        try:
            emb = HuggingFaceEmbeddings(model_name=model, model_kwargs={"device": s.hf_device},
                                        encode_kwargs={"normalize_embeddings": True, "batch_size": 16})
        except OSError as e:  # دانلود ناموفق، محدودیت نرخ (429) روی IP های اشتراکی، نام اشتباه
            raise ProviderError(
                f"مدل «{model}» از HuggingFace بارگذاری نشد. نام مدل و اتصال اینترنت را بررسی کنید؛ "
                f"روی سرورهای ابری با IP مشترک، HF_TOKEN را در .env تنظیم کنید. ({e.__class__.__name__})") from e
    else:
        raise ProviderError(f"ارائه‌دهنده نامعتبر: {provider}")
    return PrefixedEmbeddings(emb) if needs_e5_prefix(model) else emb


def get_embeddings(provider: str, model: str) -> Embeddings:
    with _emb_lock:  # بارگذاری هم‌زمان یک مدل سنگین HF را جلوگیری می‌کند
        return _build_embeddings(provider, model)


def embedding_dim(provider: str, model: str) -> int:
    try:
        return len(get_embeddings(provider, model).embed_query("آزمون"))
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"اتصال به مدل embedding ناموفق بود ({provider}/{model}): {e}") from e


# --- LLM ------------------------------------------------------------------------------
@lru_cache(maxsize=8)
def get_llm(provider: str, model: str, temperature: float | None = None) -> BaseChatModel:
    s = get_settings()
    temp = s.llm_temperature if temperature is None else temperature
    if provider == "openai":
        if not s.openai_api_key:
            raise ProviderError("کلید OPENAI_API_KEY در فایل .env تنظیم نشده است")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=temp, api_key=s.openai_api_key, base_url=s.openai_base_url,
                          max_tokens=s.llm_max_tokens, streaming=True)
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model, temperature=temp, base_url=s.ollama_base_url, num_predict=s.llm_max_tokens)
    if provider == "huggingface":
        try:
            from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline
        except ImportError as e:
            raise ProviderError("بسته‌های HuggingFace نصب نیستند: pip install -r requirements-hf.txt") from e
        device = 0 if s.hf_device == "cuda" else -1
        try:
            pipe = HuggingFacePipeline.from_model_id(
                model_id=model, task="text-generation", device=device,
                pipeline_kwargs={"max_new_tokens": s.llm_max_tokens, "do_sample": temp > 0,
                                 "temperature": temp or None, "return_full_text": False},
            )
        except OSError as e:
            raise ProviderError(
                f"مدل زبانی «{model}» از HuggingFace بارگذاری نشد (در کش نیست و دانلود ممکن نشد). "
                "در تنظیمات گفتگو مدل زبانی دیگری مثل OpenAI را انتخاب کنید.") from e
        return ChatHuggingFace(llm=pipe)
    raise ProviderError(f"ارائه‌دهنده نامعتبر: {provider}")


# --- Reranker -------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_reranker():
    s = get_settings()
    if not s.reranker_model:
        raise ProviderError("RERANKER_MODEL تنظیم نشده است")
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as e:
        raise ProviderError("sentence-transformers نصب نیست: pip install -r requirements-hf.txt") from e
    return CrossEncoder(s.reranker_model, device=s.hf_device, max_length=512)


# --- وضعیت ----------------------------------------------------------------------------
def ollama_models() -> list[str] | None:
    try:
        # اتصال به پورت بسته روی ویندوز ~۲ ثانیه طول می‌کشد؛ سرور در حال اجرا فوراً وصل می‌شود
        r = httpx.get(get_settings().ollama_base_url.rstrip("/") + "/api/tags", timeout=httpx.Timeout(3.0, connect=0.6))
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:
        return None


def hf_status() -> dict:
    try:
        import importlib.util
        ok = all(importlib.util.find_spec(m) for m in ("sentence_transformers", "langchain_huggingface"))
    except Exception:
        ok = False
    info: dict = {"installed": bool(ok), "device": get_settings().hf_device}
    if ok:
        import sys
        from importlib.metadata import PackageNotFoundError, version
        try:
            info["torch"] = version("torch")  # بدون import سنگین torch
        except PackageNotFoundError:
            pass
        try:  # فقط اگر torch قبلاً (با بارگذاری مدل) کامل import شده باشد
            info["cuda"] = sys.modules["torch"].cuda.is_available()
        except (KeyError, AttributeError):
            pass
    return info


_status_cache: tuple[float, dict] | None = None


def provider_status(max_age: float = 15.0) -> dict:
    """وضعیت ارائه‌دهنده‌ها با کش کوتاه‌مدت (بررسی Ollama شبکه‌ای است)."""
    global _status_cache
    if _status_cache and time.monotonic() - _status_cache[0] < max_age:
        return _status_cache[1]
    st = _provider_status()
    _status_cache = (time.monotonic(), st)
    return st


def _provider_status() -> dict:
    s = get_settings()
    om = ollama_models()
    hf = hf_status()
    return {
        "openai": {"available": bool(s.openai_api_key), "base_url": s.openai_base_url or "api.openai.com",
                   "reason": None if s.openai_api_key else "OPENAI_API_KEY تنظیم نشده"},
        "ollama": {"available": om is not None, "base_url": s.ollama_base_url, "models": om or [],
                   "reason": None if om is not None else "سرور Ollama در دسترس نیست"},
        "huggingface": {**hf, "available": hf["installed"],
                        "reason": None if hf["installed"] else "requirements-hf.txt نصب نشده"},
        "reranker": {"model": s.reranker_model or None, "available": bool(s.reranker_model) and hf["installed"]},
    }
