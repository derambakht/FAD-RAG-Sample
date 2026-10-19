"""پیکربندی تست‌ها: پوشه داده موقت، embedding جعلی واژه‌محور و LLM جعلی (بدون نیاز به کلید یا GPU)."""
from __future__ import annotations

import hashlib
import math
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="rag-fa-test-")
os.environ.update({"RAG_ENV_FILE": "none", "DATA_DIR": _tmp, "VECTOR_STORE": "chroma", "QDRANT_URL": "", "CHROMA_HOST": "",
                   "QDRANT_PATH": str(Path(_tmp) / "qdrant"), "RERANKER_MODEL": ""})

import pytest  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402

SAMPLE_PDF = ROOT / "sample_data" / "aeen-nameh-namoone.pdf"


class HashEmbeddings(Embeddings):
    """embedding کیسه‌واژه با hash؛ برای تست بازیابی بدون مدل واقعی کافی است."""

    dim = 256

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for w in re.findall(r"[\w‌]+", text):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    import app.api.routes_collections as rc
    import app.rag.chain as chain
    import app.rag.evaluation as ev
    import app.rag.retrieval as retrieval

    retrieval.get_embeddings = lambda provider, model: HashEmbeddings()
    rc._check_provider = lambda provider, model: None
    fake_llm = lambda *a, **k: FakeListChatModel(responses=["حداقل نمره قبولی 12 است [1]."])  # noqa: E731
    chain.get_llm = fake_llm
    import app.providers as providers
    providers.get_llm = fake_llm  # برای تولید پرسش در evaluation
    _ = ev

    from app.main import app
    with TestClient(app) as c:
        yield c
