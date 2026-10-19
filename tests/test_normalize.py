from app.core.normalize import (
    clean_fa, fix_date_order, fix_mirrored_pairs, looks_broken, normalize_numbers, odd_chars, to_persian_digits,
    unreverse_ltr_runs,
)
from app.core.extract import fix_line_direction
from app.core.text_utils import bm25_tokens, overlap_coefficient, vocab_score


def test_numbers():
    assert normalize_numbers("۱۴۰۲/۰۵/۱۲") == "1402/05/12"
    assert normalize_numbers("۱۲٬۵۰۰٫۷۵") == "12500.75"
    assert normalize_numbers("١٤٠٢") == "1402"
    assert normalize_numbers("‏۵۰٪") == "50%"
    assert to_persian_digits("1402") == "۱۴۰۲"


def test_date_order_and_ltr_runs():
    assert fix_date_order("12/05/1402") == "1402/05/12"
    assert fix_date_order("12/05/2024") == "12/05/2024"
    assert unreverse_ltr_runs("2041 ASAN") == "1402 NASA"


def test_arabic_chars_and_presentation_forms():
    out = clean_fa("كتاب علمي ﻫﻮﺵ مصنوعی")
    assert out == "کتاب علمی هوش مصنوعی"
    assert not odd_chars(out)


def test_tatweel_diacritics_zwj():
    assert clean_fa("اـــــیران") == "ایران"
    assert clean_fa("عِلْمٌ") == "علم"
    assert "‍" not in clean_fa("می‍شود")


def test_half_space():
    out = clean_fa("کتاب ها را مي خوانم")
    assert out == "کتاب‌ها را می‌خوانم"
    # نیم‌فاصله کنار فاصله حذف می‌شود
    assert clean_fa("کتاب‌ را") == "کتاب را"


def test_query_and_document_match():
    """قاعده طلایی: «ماده ۱۲» و «ماده 12» پس از clean_fa یکسان‌اند."""
    assert clean_fa("ماده ۱۲") == clean_fa("ماده 12") == clean_fa("ماده ١٢")


def test_date_spacing_preserved():
    assert "1405/07/27" in clean_fa("تاريخ ۱۴۰۵/۰۷/۲۷ است")


def test_numbers_survive_hazm_spacing():
    out = clean_fa("هزینه ۱۲٬۵۰۰٫۷۵ تومان و سهم ۳۰٪ و نسخه 2.5 است")
    assert "12500.75 تومان" in out and "30%" in out and "2.5" in out


def test_mirrored_pairs():
    assert fix_mirrored_pairs("منظور از» هنرجو «است") == "منظور از« هنرجو »است"
    assert fix_mirrored_pairs("(الف) و (ب)") == "(الف) و (ب)"
    assert "«هنرجو»" in clean_fa("منظور از» هنرجو «است")


def test_line_direction():
    line = "این کتاب بسیار مهم است و دانشجویان باید آن را بخوانند"
    fixed, rev = fix_line_direction(line[::-1])
    assert rev and fixed == line
    same, rev2 = fix_line_direction(line)
    assert not rev2 and same == line


def test_vocab_score():
    good = "پردازش زبان فارسی در سامانه‌های بازیابی اطلاعات اهمیت دارد"
    assert vocab_score(good) > 0.8
    assert vocab_score(good[::-1]) < 0.4


def test_looks_broken():
    assert looks_broken("ÇáÓáÇã Úáíßã " * 10)
    assert not looks_broken("این یک متن سالم فارسی است که باید درست تشخیص داده شود.")


def test_bm25_tokens():
    toks = bm25_tokens("کتاب‌ها و مقاله‌ها در کتابخانه")
    assert "کتاب‌ها" in toks and "کتاب" in toks
    assert "و" not in toks and "در" not in toks


def test_overlap():
    assert overlap_coefficient("نمره نهایی از بیست محاسبه می‌شود", "نمره نهایی از بیست محاسبه می‌شود و قبولی دوازده") == 1.0
    assert overlap_coefficient("الف ب", "ج د") == 0.0
