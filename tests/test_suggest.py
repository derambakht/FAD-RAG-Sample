"""پرسش‌های پیشنهادی: از داده‌های همان پایگاه دانش و مرتبط با پرسش‌های قبلی کاربر."""
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.rag import suggest
from tests.test_spreadsheet import SAMPLE_XLSX, _fake_llm, _wait

BRANCHES = ["شعبه اصفهان", "زرین شهر اصفهان", "شعبه مگامال", "آناهید تهرانپارس"]


@pytest.fixture(scope="module")
def kb(client):
    col = client.post("/api/collections", json={"name": "پیشنهاد فروش", "embedding_provider": "openai",
                                                "embedding_model": "fake", "vector_backend": "chroma"}).json()
    with open(SAMPLE_XLSX, "rb") as f:
        r = client.post(f"/api/collections/{col['id']}/documents", files=[("files", (SAMPLE_XLSX.name, f))])
    assert _wait(client, r.json()["jobs"][0]["id"])["status"] == "done"
    yield col
    client.delete(f"/api/collections/{col['id']}")


def _llm(monkeypatch, reply, seen=None):
    import app.providers as providers

    def run(prompt):
        if seen is not None:
            seen.append(prompt.to_string())
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(reply)
    monkeypatch.setattr(providers, "get_llm", lambda *a, **k: RunnableLambda(run))


def _suggest(client, kb, session_id=None, llm=True):
    body = {"collection_id": kb["id"], "session_id": session_id}
    if llm:
        body |= {"llm_provider": "openai", "llm_model": "fake"}
    r = client.post("/api/chat/suggestions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _session_with_question(client, kb, monkeypatch, question="جمع فروش شعبه مگامال چقدر است؟"):
    sid = client.post("/api/chat/sessions", json={"collection_id": kb["id"]}).json()["id"]
    sql = "```sql\nSELECT SUM(amount) AS \"مبلغ\" FROM sales WHERE branch = 'شعبه مگامال'\n```"
    _fake_llm(monkeypatch, [sql, "جمع مبلغ فروش شعبه مگامال 30,287,125,574 است."])
    with client.stream("POST", "/api/chat", json={"collection_id": kb["id"], "question": question, "session_id": sid,
                                                   "llm_provider": "openai", "llm_model": "fake"}) as r:
        "".join(r.iter_text())
    return sid


def test_mentioned_prefers_full_branch_name():
    assert suggest.mentioned(BRANCHES, "فروش زرین شهر اصفهان چقدر است؟") == ["زرین شهر اصفهان"]
    assert suggest.mentioned(BRANCHES, "در شعبه اصفهان چند عدد فروخته شده؟") == ["شعبه اصفهان"]
    assert suggest.mentioned(BRANCHES, "مگامال را با آناهید تهرانپارس مقایسه کن") == ["شعبه مگامال", "آناهید تهرانپارس"]
    assert suggest.mentioned(BRANCHES, "کدام شعبه بیشترین فروش را داشته؟") == []


def test_parse_questions_cleans_llm_output():
    raw = "پرسش‌های پیشنهادی:\n1. جمع تخفیف شعبه مگامال چقدر است?\n- «۵ کالای پرفروش شعبه مگامال کدام‌اند؟»\n\n**سهم مگامال از کل فروش؟**"
    assert suggest.parse_questions(raw) == ["جمع تخفیف شعبه مگامال چقدر است؟", "۵ کالای پرفروش شعبه مگامال کدام‌اند؟",
                                            "سهم مگامال از کل فروش؟"]
    # ارجاع مبهم بدون گفتگو پاسخ‌پذیر نیست
    assert suggest.parse_questions("تعداد فروش شعبه‌های هم‌رتبه با اصفهان چقدر است؟\nتخفیف همین شعبه چقدر است؟") == []


def test_new_chat_suggestions_come_from_the_data(client, kb):
    # بدون LLM و بدون پرسش قبلی: پیشنهادها با نام واقعی پرفروش‌ترین شعبه از خود داده ساخته می‌شوند
    r = _suggest(client, kb, llm=False)
    assert r["source"] == "data" and len(r["suggestions"]) == 4 and r["context"]["tabular"]
    assert any("شعبه مگامال" in s for s in r["suggestions"])


def test_followups_use_conversation_result_and_skip_asked(client, kb, monkeypatch):
    sid = _session_with_question(client, kb, monkeypatch)
    seen = []
    _llm(monkeypatch, "1. جمع فروش شعبه مگامال چقدر است؟\n2. ۵ کالای پرفروش شعبه مگامال کدام‌اند؟\n"
                      "3. شعبه مگامال و شعبه میدان صنعت را مقایسه کن.\n4. جمع تخفیف شعبه مگامال چقدر است؟\n"
                      "5. سهم شعبه مگامال از کل فروش چند درصد است؟", seen)
    r = _suggest(client, kb, sid)
    assert r["source"] == "llm" and r["context"]["session_questions"] == 1
    # پرسشی که کاربر پرسیده بود دوباره پیشنهاد نمی‌شود
    assert r["suggestions"] == ["۵ کالای پرفروش شعبه مگامال کدام‌اند؟", "شعبه مگامال و شعبه میدان صنعت را مقایسه کن.",
                                "جمع تخفیف شعبه مگامال چقدر است؟", "سهم شعبه مگامال از کل فروش چند درصد است؟"]
    prompt = seen[0]
    assert "کاربر: جمع فروش شعبه مگامال چقدر است؟" in prompt and "30,287,125,574" in prompt  # گفتگو و نتیجه آن
    assert "پرفروش‌ترین کالاهای شعبه مگامال" in prompt and "شعبه میدان صنعت" in prompt     # داده‌های واقعی
    assert "تاریخ" in prompt  # محدودیت ستون‌ها گفته شده تا پرسش بی‌پاسخ پیشنهاد نشود


def test_questions_asked_earlier_in_long_chat_not_suggested(client, kb, monkeypatch):
    sid = _session_with_question(client, kb, monkeypatch, "جمع تخفیف شعبه فرشته تهران چقدر است؟")
    db = __import__("app.db", fromlist=["get_db"]).get_db()
    for i in range(5):  # پرسش اول از پنجره پیام‌های آخر بیرون می‌رود
        db.add_chat_message(sid, "user", f"پرسش شماره {i} درباره فروش")
        db.add_chat_message(sid, "assistant", "پاسخ")
    _llm(monkeypatch, "جمع تخفیف شعبه فرشته تهران چقدر است؟\nسهم شعبه فرشته تهران از کل فروش چند درصد است؟")
    r = _suggest(client, kb, sid)
    assert "جمع تخفیف شعبه فرشته تهران چقدر است؟" not in r["suggestions"]
    assert r["suggestions"][0] == "سهم شعبه فرشته تهران از کل فروش چند درصد است؟"


def test_followups_without_llm_focus_on_previous_branch(client, kb, monkeypatch):
    sid = _session_with_question(client, kb, monkeypatch, "تعداد فروش شعبه مگامال چقدر است؟")
    _llm(monkeypatch, RuntimeError("LLM در دسترس نیست"))
    r = _suggest(client, kb, sid)
    assert r["source"] == "data"
    assert r["suggestions"][0] == "۵ کالای پرفروش شعبه مگامال از نظر مبلغ فروش کدام‌اند؟"
    assert all("مگامال" in s for s in r["suggestions"][:3])


def test_new_chat_uses_users_past_questions(client, kb, monkeypatch):
    _session_with_question(client, kb, monkeypatch, "جمع تخفیف شعبه میدان صنعت چقدر است؟")
    seen = []
    _llm(monkeypatch, "۵ کالای پرفروش شعبه میدان صنعت کدام‌اند؟", seen)
    r = _suggest(client, kb)  # گفتگوی جدید
    assert r["context"]["past_questions"] >= 1 and r["context"]["session_questions"] == 0
    assert "- جمع تخفیف شعبه میدان صنعت چقدر است؟" in seen[0] and "پرفروش‌ترین کالاهای شعبه میدان صنعت" in seen[0]
    # پیشنهاد LLM اول، بقیه از الگوهای همان داده؛ پرسش قبلی تکرار نمی‌شود
    assert r["suggestions"][0] == "۵ کالای پرفروش شعبه میدان صنعت کدام‌اند؟" and len(r["suggestions"]) == 4
    assert "جمع تخفیف شعبه میدان صنعت چقدر است؟" not in r["suggestions"]


def test_session_of_other_collection_rejected(client, kb, monkeypatch):
    other = client.post("/api/collections", json={"name": "دیگر", "embedding_provider": "openai",
                                                  "embedding_model": "fake", "vector_backend": "chroma"}).json()
    sid = client.post("/api/chat/sessions", json={"collection_id": other["id"]}).json()["id"]
    r = client.post("/api/chat/suggestions", json={"collection_id": kb["id"], "session_id": sid})
    assert r.status_code == 400
    client.delete(f"/api/collections/{other['id']}")


def test_text_collection_suggestions_follow_sections(client, monkeypatch, tmp_path):
    col = client.post("/api/collections", json={"name": "آیین‌نامه پیشنهاد", "embedding_provider": "openai",
                                                "embedding_model": "fake", "vector_backend": "chroma"}).json()
    md = tmp_path / "rules.md"
    md.write_text("# شرایط غیبت\nغیبت دانشجو در هر درس نباید از سه جلسه بیشتر شود.\n\n"
                  "# نمره قبولی\nحداقل نمره قبولی در هر درس ۱۰ است.\n", encoding="utf-8")
    with open(md, "rb") as f:
        r = client.post(f"/api/collections/{col['id']}/documents", files=[("files", ("rules.md", f))])
    assert _wait(client, r.json()["jobs"][0]["id"])["status"] == "done"
    seen = []
    _llm(monkeypatch, "حداکثر غیبت مجاز در هر درس چند جلسه است؟", seen)
    r = _suggest(client, col)
    assert r["source"] == "llm" and not r["context"]["tabular"]
    assert "غیبت دانشجو" in seen[0]  # متن واقعی اسناد به LLM داده شده
    _llm(monkeypatch, RuntimeError("x"))
    r = _suggest(client, col, llm=False)
    assert any("شرایط غیبت" in s for s in r["suggestions"])
    client.delete(f"/api/collections/{col['id']}")
