import pytest

from app.core.chunking import ChunkOptions, build_chunks, lines_to_paragraphs, split_sections
from app.core.extract import ExtractOptions, ExtractResult, Line, PageResult, extract_file
from app.rag.evaluation import audit_chunks
from tests.conftest import SAMPLE_PDF


def _ext(lines):
    return ExtractResult(pages=[PageResult(1, lines, "test")])


def test_paragraph_joining_and_headings():
    lines = [
        Line("فصل 1", 1, 14), Line("کلیات", 1, 14),
        Line("ماده 1 - این یک متن طولانی است که در خط اول شروع شده و", 1, 11),
        Line("در خط دوم ادامه پیدا می‌کند و تمام می‌شود.", 1, 11),
        Line("تبصره 1 - این تبصره همراه ماده می‌ماند.", 1, 11),
        Line("ماده 2", 1, 11), Line("متن ماده دوم.", 1, 11),
    ]
    paras = lines_to_paragraphs(lines)
    sections = split_sections(paras)
    assert [s.path for s in sections] == ["فصل 1 - کلیات › ماده 1", "فصل 1 - کلیات › ماده 2"]
    assert "در خط دوم" in sections[0].paras[0].text  # خطوط به پاراگراف وصل شده‌اند
    assert any("تبصره 1" in p.text for p in sections[0].paras)


def test_chunk_never_crosses_sections_and_respects_budget():
    body = " ".join(f"جمله شماره {i} درباره موضوع مهم آموزشی است." for i in range(60))
    lines = [Line("ماده 1", 1), Line(body, 1), Line("", 1), Line("ماده 2", 2), Line("متن کوتاه ماده دو.", 2)]
    chunks, stats = build_chunks(_ext(lines), ChunkOptions(max_tokens=120, overlap_sents=1))
    assert all(c["tokens"] <= 125 for c in chunks)
    assert not any("ماده 1" in c["section"] and "ماده دو" in c["body"] for c in chunks)
    assert chunks[-1]["section"] == "ماده 2"
    assert all(c["text"].startswith(c["section"]) for c in chunks)  # عنوان داخل متن chunk
    # همپوشانی یک جمله
    first, second = chunks[0]["body"], chunks[1]["body"]
    assert first.split(".")[-2].strip() in second


@pytest.mark.parametrize("strategy", ["structure", "recursive", "fixed"])
def test_strategies_on_sample_pdf(strategy):
    ext = extract_file(SAMPLE_PDF, ExtractOptions())
    chunks, stats = build_chunks(ext, ChunkOptions(strategy=strategy, max_tokens=200))
    assert chunks and all(c["page"] in (1, 2) for c in chunks)
    assert all("مؤسسه آموزش عالی نمونه" not in c["text"] for c in chunks)  # سرصفحه حذف شده
    if strategy == "structure":
        assert stats["sections"] == 10
        assert any(c["section"].endswith("ماده 5") and "قبولی 12" in c["body"] for c in chunks)


def test_sample_pdf_extraction_quality():
    ext = extract_file(SAMPLE_PDF, ExtractOptions())
    s = ext.summary()
    assert s["pages"] == 2 and s["avg_vocab"] > 0.85
    text = "\n".join(ln.text for ln in ext.lines)
    assert "ي" not in text and "ك" not in text and "۱" not in text


def test_audit_flags():
    chunks = [
        {"body": "متن کامل و سالم فارسی است که به درستی تمام شده است.", "tokens": 80, "section": "الف"},
        {"body": "متن کامل و سالم فارسی است که به درستی تمام شده است.", "tokens": 80, "section": "الف"},
        {"body": "كتاب ناقص", "tokens": 5, "section": ""},
    ]
    res = audit_chunks(chunks)
    rows = res["rows"]
    assert rows[0]["dup"] and rows[1]["dup"]
    assert {"short", "bad_chars", "no_end"} <= set(rows[2]["flags"])
    assert res["summary"]["suspects"] == 3
