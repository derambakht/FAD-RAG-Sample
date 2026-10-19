"""مرحله پرسش: Rerank با LLM و Jev (فیلتر ارتباط + بررسی پاسخ‌پذیری) با سرویس‌های شبیه‌سازی‌شده."""
import json
import re

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from tests.conftest import SAMPLE_PDF
from tests.test_api import _wait


@pytest.fixture(scope="module")
def kb(client):
    col = client.post("/api/collections", json={"name": "پس‌پردازش", "embedding_provider": "openai",
                                                "embedding_model": "fake", "vector_backend": "chroma"}).json()
    with open(SAMPLE_PDF, "rb") as f:
        r = client.post(f"/api/collections/{col['id']}/documents", files=[("files", (SAMPLE_PDF.name, f))])
    assert _wait(client, r.json()["jobs"][0]["id"])["status"] == "done"
    yield col
    client.delete(f"/api/collections/{col['id']}")


@pytest.fixture()
def jev_mock(monkeypatch):
    """Jev جعلی: متنی که «قبولی» دارد مرتبط است؛ پاسخ‌پذیری با کلید answerable_prob کنترل می‌شود."""
    from app.config import get_settings
    import app.rag.jev as jev
    calls, ctl = [], {"answerable": 0.9}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/systemone"
        answers = {}
        for qid, q in body["questions"].items():
            assert q["type"] == "noul"
            if qid == "answerable":
                answers[qid] = {"type": "noul", "noul": ctl["answerable"]}
            else:
                answers[qid] = {"type": "noul", "noul": 0.95 if "قبولی" in q["instructions"] else 0.05}
        return httpx.Response(200, json={"answers": answers, "model": "jev-test", "usage": {"input_tokens": 10}})

    monkeypatch.setattr(jev, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(get_settings(), "typesafe_api_key", "test-key")
    return calls, ctl


def test_jev_filters_and_reorders(client, kb, jev_mock):
    calls, _ = jev_mock
    r = client.post("/api/search", json={"collection_id": kb["id"], "query": "نمره لازم برای قبول شدن", "mode": "hybrid",
                                         "k": 5, "jev": True}).json()
    assert len(calls) == 1  # یک درخواست برای همه کاندیدها
    assert r["hits"] and all("قبولی" in h["text"] for h in r["hits"])
    assert all(h["jev_prob"] >= 0.35 for h in r["hits"])
    jev_stage = next(s for s in r["stages"] if s["name"] == "jev")
    assert jev_stage["dropped"] == r["dropped"] > 0 and jev_stage["out"] == len(r["hits"])
    # «کدام مدل، از کجا»: embedding پایگاه و نسخه واقعی Jev که پاسخ داده
    stages = {m["stage"]: m for m in r["models"]}
    assert stages["embedding"]["model"] == "fake" and stages["embedding"]["where"] == "api.openai.com"
    assert stages["jev"]["model"] == "jev-test" and "TypeSafe" in stages["jev"]["where"]


def test_jev_answerability_skips_llm(client, kb, jev_mock, monkeypatch):
    _, ctl = jev_mock
    ctl["answerable"] = 0.1
    import app.rag.chain as chain

    def no_llm_call(*a, **k):  # LLM ساخته می‌شود ولی نباید فراخوانی شود
        return FakeListChatModel(responses=["این پاسخ نباید تولید شود"])
    monkeypatch.setattr(chain, "get_llm", no_llm_call)
    with client.stream("POST", "/api/chat", json={"collection_id": kb["id"], "question": "حداقل نمره قبولی؟",
                                                   "llm_provider": "openai", "llm_model": "fake", "jev": True}) as r:
        body = "".join(r.iter_text())
    tokens = "".join(json.loads(m)["t"] for m in re.findall(r"event: token\ndata: (.*)", body))
    assert tokens == chain.NOT_FOUND
    sources = json.loads(re.search(r"event: sources\ndata: (.*)", body).group(1))
    assert sources["answerable"]["ok"] is False and sources["stages"][-1]["name"] == "answerable"
    assert [m["stage"] for m in sources["models"]] == ["embedding", "jev", "llm"]
    assert sources["models"][-1]["skipped"] is True


def test_jev_without_key_gives_clear_error(client, kb):
    r = client.post("/api/search", json={"collection_id": kb["id"], "query": "قبولی", "jev": True})
    assert r.status_code == 400 and "TYPESAFE_API_KEY" in r.json()["detail"]


def test_llm_rerank(client, kb, monkeypatch):
    import app.rag.rerank as rerank

    def fake_llm(*a, **k):
        """امتیاز ۱۰ برای متنی که «جبرانی» دارد و ۱ برای بقیه."""
        def respond(prompt_value):
            text = prompt_value.to_string()
            ids = re.findall(r"\[(\d+)\] ", text)
            parts = re.split(r"\[\d+\] ", text)[1:]
            scores = [{"id": int(i), "score": 10 if "جبرانی" in p else 1} for i, p in zip(ids, parts)]
            return json.dumps({"scores": scores})
        from langchain_core.runnables import RunnableLambda
        return RunnableLambda(respond)
    monkeypatch.setattr(rerank, "get_llm", fake_llm)
    r = client.post("/api/search", json={"collection_id": kb["id"], "query": "نمره", "mode": "hybrid", "k": 3,
                                         "rerank": "llm"}).json()
    assert "جبرانی" in r["hits"][0]["text"] and r["hits"][0]["rerank_score"] == 10
    assert [s["name"] for s in r["stages"]] == ["retrieve", "rerank", "topk"]


def test_eval_with_postprocess_configs(client, kb, jev_mock):
    es = client.post("/api/eval-sets", json={"collection_id": kb["id"], "name": "jev"}).json()
    gold = client.get(f"/api/collections/{kb['id']}/chunks", params={"q": "قبولی"}).json()["items"][0]
    client.post(f"/api/eval-sets/{es['id']}/items", json={"question": "حداقل نمره قبولی؟", "gold_chunk_id": gold["id"]})
    job = client.post(f"/api/eval-sets/{es['id']}/run", json={"k": 3, "configs": [
        {"collection_id": kb["id"], "mode": "hybrid"}, {"collection_id": kb["id"], "mode": "hybrid", "jev": True}]}).json()
    j = _wait(client, job["id"])
    assert j["status"] == "done", j
    assert [r["jev"] for r in j["result"]["results"]] == [False, True]
