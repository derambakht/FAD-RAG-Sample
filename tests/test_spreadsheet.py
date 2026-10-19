"""داده‌های جدولی (اکسل فروش): خواندن چیدمان گزارشی و تخت، ذخیره ساختاریافته و پاسخ آماری با SQL در گفتگو."""
import json
import sqlite3
import time
from pathlib import Path

import pytest

from app.core.spreadsheet import parse_file, parse_number, split_supplier
from app.rag import analytics
from tests.conftest import ROOT

SAMPLE_XLSX = ROOT / "sample_data" / "sales-report-sample.xlsx"


def _wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    raise TimeoutError(job_id)


def _events(body: str) -> list[tuple[str, dict]]:
    out, event = [], None
    for ln in body.splitlines():
        if ln.startswith("event: "):
            event = ln[7:]
        elif ln.startswith("data: "):
            out.append((event, json.loads(ln[6:])))
    return out


# --- خواندن فایل ---------------------------------------------------------------------------
def test_parse_report_layout():
    res = parse_file(SAMPLE_XLSX)
    assert not res.warnings
    assert len(res.blocks) == 3 and len(res.records) == 279
    assert {r["branch"] for r in res.records} == {"شعبه مگامال", "شعبه میدان صنعت", "شعبه فرشته تهران"}
    assert {(r["supplier"], r["supplier_code"]) for r in res.records} == {("گل پخش اول", "11572")}
    mega = [r for r in res.records if r["branch"] == "شعبه مگامال"]
    assert len(mega) == 136
    # سطر «جمع» فایل: 30,287,125,571 و 960,499,172 (اعداد PDF گرد شده‌اند، پس اختلاف چند واحدی مجاز است)
    assert abs(sum(r["amount"] for r in mega) - 30_287_125_571) < 10
    assert abs(sum(r["discount"] for r in mega) - 960_499_172) < 10
    first = res.records[0]
    assert first["barcode"] == "6264961900760" and first["qty"] == 141 and first["amount"] == 102_545_455


def test_parse_flat_csv_with_arabic_chars_and_persian_digits(tmp_path: Path):
    f = tmp_path / "flat.csv"
    f.write_text(
        "شعبه,تامين كننده,نام كالا,تعداد فروش,مبلغ فروش,تخفیف\n"
        "شعبه مگامال,گل پخش اول 11572,شامپو گلرنگ,\"۱۲\",\"۱,۲۰۰,۰۰۰\",\n"
        "شعبه شيراز,پخش البرز,آدامس,3,45000.5,100\n"
        "جمع,,,15,1245000.5,100\n", encoding="utf-8")
    res = parse_file(f)
    assert len(res.records) == 2 and not res.warnings
    a, b = res.records
    assert (a["branch"], a["supplier"], a["supplier_code"], a["qty"], a["amount"], a["discount"]) == \
        ("شعبه مگامال", "گل پخش اول", "11572", 12, 1_200_000, 0)
    assert b["branch"] == "شعبه شیراز" and b["product"] == "آدامس" and b["amount"] == 45000.5


def test_total_row_mismatch_is_reported(tmp_path: Path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in (["تامین کننده :", "پخش نمونه 900"], ["شعبه :", "شعبه یک"],
                ["[ردیف]", "[بارکد_کاال]", "[نام_کاال]", "[مقدار_فروش_رفته]", "[مبلغ_فروش_رفته]"],
                [1, "111", "کالای الف", 2, 1000], [2, "222", "کالای ب", 3, 2000], ["جمع :", None, None, None, 9999]):
        ws.append(row)
    path = tmp_path / "bad-total.xlsx"
    wb.save(path)
    res = parse_file(path)
    assert len(res.records) == 2 and res.records[0]["supplier"] == "پخش نمونه"
    assert res.warnings and "جمع" in res.warnings[0]


@pytest.mark.parametrize("raw,expected", [("1,234", 1234), ("۱٬۲۳۴", 1234), ("(50)", -50), ("", None), ("abc", None)])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


def test_split_supplier():
    assert split_supplier("گل پخش اول 11572") == ("گل پخش اول", "11572")
    assert split_supplier("11572 - گل پخش اول") == ("گل پخش اول", "11572")
    assert split_supplier("پخش البرز") == ("پخش البرز", "")


# --- لایه SQL -----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def data():
    return analytics.SalesData([{**r, "source": "s.xlsx"} for r in parse_file(SAMPLE_XLSX).records])


@pytest.mark.parametrize("sql", ["DELETE FROM sales", "DROP TABLE sales", "SELECT * FROM sqlite_master",
                                 "ATTACH 'x.db' AS x", "PRAGMA table_info(sales)",
                                 "INSERT INTO sales(product) VALUES ('x')"])
def test_sql_is_read_only(data, sql):
    with pytest.raises(sqlite3.Error):
        data.run(sql)
    assert data.run("SELECT COUNT(*) FROM sales")[1] == [(279,)]


def test_literals_normalized_like_data(data):
    # یای عربی و نیم‌فاصله در کوئری LLM با داده‌های نرمال‌شده جور می‌شوند
    sql = analytics.normalize_literals("SELECT COUNT(*) FROM sales WHERE branch = 'شعبه ميدان صنعت'")
    assert data.run(sql)[1] == [(112,)]
    assert "تامین کننده" in analytics.normalize_literals("SELECT '%تامین‌کننده%'")


def test_cte_and_group_by(data):
    cols, rows, _ = data.run("WITH b AS (SELECT branch, SUM(amount) a FROM sales GROUP BY branch) "
                             "SELECT branch, a FROM b ORDER BY a DESC")
    assert [r[0] for r in rows] == ["شعبه مگامال", "شعبه میدان صنعت", "شعبه فرشته تهران"]


@pytest.mark.parametrize("raw,sql", [
    ("```sql\nSELECT 1;\n```", "SELECT 1"),
    ("NONE", None),
    ("بفرمایید:\nSELECT SUM(qty) FROM sales", "SELECT SUM(qty) FROM sales"),
    ("```sql\nNONE\n```", None),
])
def test_extract_sql(raw, sql):
    assert analytics.extract_sql(raw) == sql


# --- جریان کامل در API ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sales_kb(client):
    r = client.post("/api/collections", json={"name": "فروش اکسل", "embedding_provider": "openai",
                                              "embedding_model": "fake", "vector_backend": "chroma"})
    assert r.status_code == 201, r.text
    col = r.json()
    with open(SAMPLE_XLSX, "rb") as f:
        r = client.post(f"/api/collections/{col['id']}/documents", files=[("files", (SAMPLE_XLSX.name, f))])
    assert r.status_code == 202, r.text
    job = _wait(client, r.json()["jobs"][0]["id"])
    assert job["status"] == "done", job
    yield col
    assert client.delete(f"/api/collections/{col['id']}").status_code == 204


def _fake_llm(monkeypatch, responses: list[str]):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    import app.rag.chain as chain
    model = FakeListChatModel(responses=responses)
    monkeypatch.setattr(chain, "get_llm", lambda *a, **k: model)


def _chat(client, kb, question):
    with client.stream("POST", "/api/chat", json={"collection_id": kb["id"], "question": question,
                                                   "llm_provider": "openai", "llm_model": "fake"}) as r:
        return _events("".join(r.iter_text()))


def test_excel_document_indexed(client, sales_kb):
    col = client.get(f"/api/collections/{sales_kb['id']}").json()
    assert col["table_rows"] == 279 and col["chunks"] == col["vectors"] > 0
    doc = client.get(f"/api/collections/{sales_kb['id']}/documents").json()[0]
    assert doc["status"] == "ready" and doc["stats"]["table"]["rows"] == 279
    # خلاصه هر شعبه هم برای جستجوی معنایی chunk شده است
    hits = client.post("/api/search", json={"collection_id": sales_kb["id"], "query": "خلاصه شعبه میدان صنعت",
                                            "mode": "bm25", "k": 3}).json()["hits"]
    assert any("میدان صنعت" in h["text"] for h in hits)


def test_chat_answers_aggregate_with_exact_sql(client, sales_kb, monkeypatch):
    sql = ("```sql\nSELECT branch AS \"شعبه\", SUM(qty) AS \"تعداد\", SUM(amount) AS \"مبلغ\" FROM sales "
           "WHERE branch LIKE '%مگامال%' GROUP BY branch\n```")
    _fake_llm(monkeypatch, [sql, "جمع مبلغ فروش شعبه مگامال 30,287,125,574 است."])
    ev = _chat(client, sales_kb, "جمع فروش شعبه مگامال چقدر است؟")
    kinds = [e for e, _ in ev]
    assert kinds[0] == "sources" and kinds[-1] == "done" and "error" not in kinds
    a = ev[0][1]["analytics"]
    assert a["columns"] == ["شعبه", "تعداد", "مبلغ"]
    assert a["rows"] == [["شعبه مگامال", "16,306", "30,287,125,574"]]
    assert "".join(d["t"] for e, d in ev if e == "token").startswith("جمع مبلغ فروش")


def test_chat_retries_when_filter_matches_nothing(client, sales_kb, monkeypatch):
    bad = "```sql\nSELECT SUM(discount) FROM sales WHERE branch LIKE '%میدان صنعتی%'\n```"
    good = "```sql\nSELECT SUM(discount) AS \"تخفیف\" FROM sales WHERE branch LIKE '%صنعت%'\n```"
    _fake_llm(monkeypatch, [bad, good, "تخفیف ..."])
    a = _chat(client, sales_kb, "تخفیف میدان صنعتی؟")[0][1]["analytics"]
    assert a["attempts"] == 2 and a["rows"] == [["276,365,558"]]


def test_non_data_question_falls_back_to_rag(client, sales_kb, monkeypatch):
    _fake_llm(monkeypatch, ["NONE", "پاسخ از متن [1]."])
    ev = _chat(client, sales_kb, "بارکد آدامس مینی استیک توت فرنگی چیست؟")
    src = ev[0][1]
    assert "analytics" not in src and src["hits"]


@pytest.mark.parametrize("q,sql,bad", [
    ("۵ شعبه برتر از نظر تعداد فروش", "SELECT branch, COUNT(*) FROM sales GROUP BY branch", True),
    ("۵ شعبه برتر از نظر تعداد فروش", "SELECT branch, SUM(qty) FROM sales GROUP BY branch", False),
    ("جمع تخفیف مگامال", "SELECT SUM(amount) FROM sales", True),
    ("چند قلم کالا در مگامال هست؟", "SELECT COUNT(*) FROM sales", False),
])
def test_metric_column_check(q, sql, bad):
    assert bool(analytics.check_metrics(q, sql)) is bad


def test_chat_corrects_count_instead_of_sum(client, sales_kb, monkeypatch):
    wrong = "```sql\nSELECT branch, COUNT(*) AS \"تعداد\" FROM sales GROUP BY branch ORDER BY 2 DESC LIMIT 1\n```"
    right = "```sql\nSELECT branch, SUM(qty) AS \"تعداد فروش\" FROM sales GROUP BY branch ORDER BY 2 DESC LIMIT 1\n```"
    _fake_llm(monkeypatch, [wrong, right, "..."])
    a = _chat(client, sales_kb, "کدام شعبه بیشترین تعداد فروش را داشته؟")[0][1]["analytics"]
    assert a["rows"] == [["شعبه مگامال", "16,306"]] and a["attempts"] == 2


def test_chat_runs_rejected_sql_if_llm_insists(client, sales_kb, monkeypatch):
    q = "```sql\nSELECT COUNT(*) AS \"n\" FROM sales WHERE branch LIKE '%مگامال%'\n```"
    _fake_llm(monkeypatch, [q, q, "..."])
    a = _chat(client, sales_kb, "تعداد فروش رفته مگامال؟")[0][1]["analytics"]
    assert a["rows"] == [["136"]]


def test_report_pdf_detected_and_parsed():
    from app.core.spreadsheet import is_report_pdf
    pdf = ROOT / "sample_data" / "sales-report-sample.pdf"
    assert is_report_pdf(pdf) and not is_report_pdf(ROOT / "sample_data" / "aeen-nameh-namoone.pdf")
    res = parse_file(pdf)
    assert len(res.records) == 279 and not res.warnings
    assert {r["branch"] for r in res.records} == {"شعبه مگامال", "شعبه میدان صنعت", "شعبه فرشته تهران"}
    mega = [r for r in res.records if r["branch"] == "شعبه مگامال"]
    assert abs(sum(r["amount"] for r in mega) - 30_287_125_571) < 10
    assert mega[0]["product"] == "آدامس مینی استیک بدون شکر با طعم توت فرنگی بایودنت"


def test_ambiguous_branch_filter_detected():
    d = analytics.SalesData([
        {"source": "f", "sheet": "", "row_no": 1, "supplier": "گل پخش اول", "supplier_code": "1", "branch": b,
         "barcode": "", "product": "x", "qty": 1, "amount": 1, "discount": 0}
        for b in ("شعبه اصفهان", "زرین شهر اصفهان", "شعبه شیراز")])
    assert "زرین شهر اصفهان" in analytics.check_ambiguous(d, "SELECT 1 FROM sales WHERE branch LIKE '%اصفهان%'")
    assert analytics.check_ambiguous(d, "SELECT 1 FROM sales WHERE branch LIKE '%شیراز%'") is None
    assert analytics.check_ambiguous(d, "SELECT 1 FROM sales WHERE branch = 'شعبه اصفهان'") is None
