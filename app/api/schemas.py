from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Provider = Literal["openai", "ollama", "huggingface"]
Mode = Literal["dense", "bm25", "hybrid"]
# روش Rerank؛ bool برای سازگاری با نسخه قبل (true = cross-encoder)
Rerank = Literal["none", "llm", "cross_encoder"] | bool


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    embedding_provider: Provider
    embedding_model: str = Field(min_length=1)
    vector_backend: Literal["chroma", "qdrant"] | None = None
    settings: dict = Field(default_factory=dict)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    settings: dict | None = None


class ReindexRequest(BaseModel):
    options: dict | None = None


class VersionCheck(BaseModel):
    files: list[str] = Field(min_length=1, max_length=200)


class SearchRequest(BaseModel):
    collection_id: str
    query: str = Field(min_length=1, max_length=4000)
    mode: Mode = "hybrid"
    k: int = Field(default=5, ge=1, le=50)
    rerank: Rerank = "none"
    jev: bool = False
    jev_threshold: float | None = Field(default=None, ge=0, le=1)
    clean: bool = True
    document_ids: list[str] | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    collection_id: str
    question: str = Field(min_length=1, max_length=4000)
    llm_provider: Provider
    llm_model: str
    mode: Mode = "hybrid"
    k: int = Field(default=5, ge=1, le=20)
    rerank: Rerank = "none"
    jev: bool = False
    jev_threshold: float | None = Field(default=None, ge=0, le=1)
    jev_answerable: bool = True
    condense: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    history: list[ChatMessage] = Field(default_factory=list)
    document_ids: list[str] | None = None
    # اگر داده شود، تاریخچه از سرور خوانده و پرسش و پاسخ در همین جلسه ذخیره می‌شوند
    session_id: str | None = None


class SuggestRequest(BaseModel):
    collection_id: str
    session_id: str | None = None
    llm_provider: Provider | None = None
    llm_model: str | None = None
    n: int = Field(default=4, ge=1, le=8)


class SessionCreate(BaseModel):
    collection_id: str
    title: str = Field(default="", max_length=120)


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class EvalSetCreate(BaseModel):
    collection_id: str
    name: str = Field(min_length=1, max_length=120)


class GenerateRequest(BaseModel):
    n: int = Field(default=30, ge=1, le=500)
    llm_provider: Provider
    llm_model: str
    seed: int = 7


class EvalItemCreate(BaseModel):
    question: str = Field(min_length=2)
    gold_chunk_id: str | None = None
    gold_text: str | None = None


class EvalConfig(BaseModel):
    collection_id: str
    mode: Mode = "hybrid"
    rerank: Rerank = "none"
    jev: bool = False
    clean_query: bool = True


class EvalRunRequest(BaseModel):
    configs: list[EvalConfig] = Field(min_length=1, max_length=24)
    k: int = Field(default=5, ge=1, le=20)


class NormalizeRequest(BaseModel):
    text: str = Field(max_length=200_000)


class PreviewRequest(BaseModel):
    options: dict = Field(default_factory=dict)
