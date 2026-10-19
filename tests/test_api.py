"""جریان کامل: ساخت پایگاه دانش ← بارگذاری PDF ← جستجو ← گفتگو ← audit ← ارزیابی، روی Chroma و Qdrant."""
import json
import time

import pytest

from tests.conftest import SAMPLE_PDF


def _wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    raise TimeoutError(job_id)


@pytest.fixture(scope="module", params=["chroma", "qdrant"])
def kb(request, client):
    r = client.post("/api/collections", json={
        "name": f"آیین‌نامه {request.param}", "embedding_provider": "openai", "embedding_model": "fake",
        "vector_backend": request.param, "settings": {"max_tokens": 200}})
    assert r.status_code == 201, r.text
    col = r.json()
    with open(SAMPLE_PDF, "rb") as f:
        r = client.post(f"/api/collections/{col['id']}/documents",
                        files=[("files", (SAMPLE_PDF.name, f, "application/pdf"))], data={"options": "{}"})
    assert r.status_code == 202, r.text
    job = _wait(client, r.json()["jobs"][0]["id"])
    assert job["status"] == "done", job
    yield col
    assert client.delete(f"/api/collections/{col['id']}").status_code == 204


def test_system(client):
    s = client.get("/api/system").json()
    assert s["backends"]["chroma"]["available"] and s["backends"]["qdrant"]["available"]
    assert "hybrid" in s["modes"]
    # پنل روی provider_labels حلقه می‌زند و برای هر کدام وضعیت providers[p] را می‌خواند
    assert set(s["provider_labels"]) <= set(s["providers"]) and set(s["provider_where"]) == set(s["provider_labels"])


def test_document_ready(client, kb):
    docs = client.get(f"/api/collections/{kb['id']}/documents").json()
    assert docs[0]["status"] == "ready" and docs[0]["chunks"] == 10
    assert client.get(f"/api/collections/{kb['id']}").json()["vectors"] == 10
    png = client.get(f"/api/documents/{docs[0]['id']}/pages/1.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"


def test_duplicate_upload_skipped(client, kb):
    with open(SAMPLE_PDF, "rb") as f:
        r = client.post(f"/api/collections/{kb['id']}/documents", files=[("files", (SAMPLE_PDF.name, f))])
    assert r.json()["skipped"] and not r.json()["documents"]


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_search_with_persian_digits_and_arabic_chars(client, kb, mode):
    # پرسش با ارقام فارسی و یای عربی؛ باید پس از clean_fa به ماده 5 برسد
    r = client.post("/api/search", json={"collection_id": kb["id"], "query": "حداقل نمره قبولي چند است؟",
                                         "mode": mode, "k": 3})
    assert r.status_code == 200, r.text
    hits = r.json()["hits"]
    assert hits and hits[0]["section"].endswith("ماده 5")
    assert r.json()["query"] == "حداقل نمره قبولی چند است؟"


def test_chat_stream(client, kb):
    with client.stream("POST", "/api/chat", json={"collection_id": kb["id"], "question": "نمره قبولی؟",
                                                   "llm_provider": "openai", "llm_model": "fake"}) as r:
        body = "".join(r.iter_text())
    events = [ln[7:] for ln in body.splitlines() if ln.startswith("event: ")]
    assert events[0] == "sources" and "token" in events and events[-1] == "done"
    tokens = "".join(json.loads(ln[6:])["t"] for ln, prev in zip(body.splitlines()[1:], body.splitlines())
                     if prev == "event: token")
    assert "12" in tokens


def test_chat_sessions(client, kb):
    s = client.post("/api/chat/sessions", json={"collection_id": kb["id"]}).json()
    assert s["title"] == "" and s["messages"] == 0
    for q in ("حداقل نمره قبولی چند است؟", "و آزمون جبرانی؟"):
        with client.stream("POST", "/api/chat", json={"collection_id": kb["id"], "question": q, "session_id": s["id"],
                                                       "llm_provider": "openai", "llm_model": "fake"}) as r:
            "".join(r.iter_text())
    full = client.get(f"/api/chat/sessions/{s['id']}").json()
    msgs = full["messages_list"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert full["title"] == "حداقل نمره قبولی چند است؟"  # عنوان خودکار از اولین پرسش
    assert msgs[1]["content"] and msgs[1]["hits"] and msgs[1]["info"]["query"] and msgs[1]["done"]
    # فهرست، تغییر نام، حذف یکی و حذف همه
    s2 = client.post("/api/chat/sessions", json={"collection_id": kb["id"], "title": "دوم"}).json()
    assert [x["id"] for x in client.get("/api/chat/sessions", params={"collection_id": kb["id"]}).json()][-1] == s["id"]
    assert client.patch(f"/api/chat/sessions/{s2['id']}", json={"title": "نام جدید"}).json()["title"] == "نام جدید"
    assert client.delete(f"/api/chat/sessions/{s2['id']}").status_code == 204
    assert client.get(f"/api/chat/sessions/{s2['id']}").status_code == 404
    assert client.delete("/api/chat/sessions", params={"collection_id": kb["id"]}).json()["deleted"] == 1
    assert client.get("/api/chat/sessions", params={"collection_id": kb["id"]}).json() == []


def test_chat_session_wrong_collection(client, kb):
    other = client.post("/api/collections", json={"name": f"دیگر {kb['vector_backend']}", "embedding_provider": "openai",
                                                  "embedding_model": "fake", "vector_backend": "chroma"}).json()
    s = client.post("/api/chat/sessions", json={"collection_id": other["id"]}).json()
    r = client.post("/api/chat", json={"collection_id": kb["id"], "question": "سلام", "session_id": s["id"],
                                       "llm_provider": "openai", "llm_model": "fake"})
    assert r.status_code == 400
    client.delete(f"/api/collections/{other['id']}")
    assert client.get(f"/api/chat/sessions/{s['id']}").status_code == 404  # حذف آبشاری با پایگاه دانش


def test_audit(client, kb):
    res = client.get(f"/api/collections/{kb['id']}/audit").json()
    assert res["summary"]["total"] == 10
    assert res["summary"]["flags"]["bad_chars"] == 0


def test_evaluation(client, kb):
    es = client.post("/api/eval-sets", json={"collection_id": kb["id"], "name": "دستی"}).json()
    chunks = client.get(f"/api/collections/{kb['id']}/chunks", params={"q": "قبولی"}).json()["items"]
    assert chunks
    r = client.post(f"/api/eval-sets/{es['id']}/items",
                    json={"question": "کمترین نمره لازم برای قبولی چقدر است؟", "gold_chunk_id": chunks[0]["id"]})
    assert r.status_code == 201
    run = client.post(f"/api/eval-sets/{es['id']}/run", json={"k": 5, "configs": [
        {"collection_id": kb["id"], "mode": "hybrid"}, {"collection_id": kb["id"], "mode": "bm25"}]}).json()
    job = _wait(client, run["id"])
    assert job["status"] == "done", job
    results = job["result"]["results"]
    assert len(results) == 2 and all(r["hit"] == 1.0 for r in results)
    gen = client.post(f"/api/eval-sets/{es['id']}/generate", json={"n": 2, "llm_provider": "openai",
                                                                  "llm_model": "fake"}).json()
    assert _wait(client, gen["id"])["status"] == "done"
    assert client.get(f"/api/eval-sets/{es['id']}").json()["items"] == 3


def test_reindex_and_delete_document(client, kb):
    doc = client.get(f"/api/collections/{kb['id']}/documents").json()[0]
    r = client.post(f"/api/documents/{doc['id']}/reindex", json={"options": {"strategy": "recursive"}})
    assert _wait(client, r.json()["id"])["status"] == "done"
    assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "ready"
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/collections/{kb['id']}").json()["chunks"] == 0


def test_lab(client):
    r = client.post("/api/lab/normalize", json={"text": "كتاب ها ۱۲۳"}).json()
    assert r["steps"][-1]["text"] == "کتاب‌ها 123"
    with open(SAMPLE_PDF, "rb") as f:
        up = client.post("/api/lab/upload", files={"file": (SAMPLE_PDF.name, f)}).json()
    assert up["pages"] == 2
    cmp = client.get(f"/api/lab/{up['token']}/compare", params={"page": 1}).json()
    assert len(cmp["methods"]) >= 3
    prev = client.post(f"/api/lab/{up['token']}/preview", json={"options": {"max_tokens": 150}}).json()
    assert prev["stats"]["chunks"] >= 10


def test_basic_auth(client):
    from app.config import get_settings
    s = get_settings()
    s.app_password = "رمز-تست"
    try:
        assert client.get("/api/collections").status_code == 401
        assert client.get("/").status_code == 401
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/collections", auth=("admin", "اشتباه")).status_code == 401
        import base64
        tok = base64.b64encode("admin:رمز-تست".encode()).decode()
        assert client.get("/api/collections", headers={"Authorization": f"Basic {tok}"}).status_code == 200
    finally:
        s.app_password = ""


def test_validation(client):
    r = client.post("/api/collections", json={"name": "x", "embedding_provider": "openai", "embedding_model": "m",
                                              "settings": {"strategy": "bad"}})
    assert r.status_code == 422
