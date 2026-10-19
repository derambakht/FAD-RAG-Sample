"""نرمال‌سازی متن فارسی (بخش‌های ۴ تا ۶ راهنما).

قاعده اصلی: همین تابع clean_fa هم روی اسناد و هم روی پرسش کاربر اجرا می‌شود.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from functools import lru_cache

ZWNJ = "‌"

# --- گام ۱: justify و شکل‌های نمایشی -------------------------------------------------
TATWEEL = "ـ"
_FILL_SPACES = re.compile(r"[ \t  -   　]+")
_INVISIBLE = re.compile(r"[​‍­﻿]")  # ZWSP, ZWJ, soft hyphen, BOM (ZWNJ حفظ می‌شود)
_ZWNJ_RUNS = re.compile(r"‌{2,}")
# نیم‌فاصله کنار فاصله یا ابتدا/انتهای خط بی‌معناست؛ hazm بعداً «می شود» را درست وصل می‌کند
_ZWNJ_EDGE = re.compile(r"‌(?=[ \n])|(?<=[ \n])‌|^‌|‌$")


_SOFT_HYPHEN_DASH = re.compile(r"(?<=\s)­(?=\s)")


def fix_justify(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)  # ﻫﻮﺷ -> هوش
    text = text.replace(TATWEEL, "")  # حذف کشیده
    text = _SOFT_HYPHEN_DASH.sub("-", text)  # برخی PDFها خط تیره را با U+00AD نگاشت می‌کنند
    text = _INVISIBLE.sub("", text)
    text = _FILL_SPACES.sub(" ", text)  # فاصله‌های پرکننده
    text = _ZWNJ_RUNS.sub(ZWNJ, text)
    return _ZWNJ_EDGE.sub("", text)


# --- گام ۲: اعداد و کنترل‌های جهت ---------------------------------------------------
FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
DIGITS = str.maketrans(FA_DIGITS + AR_DIGITS, "0123456789" * 2)
TO_FA_DIGITS = str.maketrans("0123456789", FA_DIGITS)
BIDI_CTRL = re.compile(r"[‎‏؜‪-‮⁦-⁩]")
_THOUSANDS = re.compile(r"(?<=\d)[٬,](?=\d{3}\b)")


def normalize_numbers(text: str) -> str:
    text = BIDI_CTRL.sub("", text)
    text = text.translate(DIGITS)
    text = _THOUSANDS.sub("", text)
    text = re.sub(r"(?<=\d) ?٫ ?(?=\d)", ".", text)
    return text.replace("٬", "،").replace("٪", "%")


LTR_RUN = re.compile(r"[0-9A-Za-z][0-9A-Za-z./:%\-]*")


def unreverse_ltr_runs(line: str) -> str:
    """بعد از معکوس کردن یک خط بصری، تکه‌های عددی/لاتین را دوباره برگردان."""
    return LTR_RUN.sub(lambda m: m.group(0)[::-1], line)


def fix_date_order(text: str) -> str:
    """12/05/1402 -> 1402/05/12 (فقط وقتی سال چهاررقمی شمسی در انتهاست)."""
    return re.sub(r"\b(\d{1,2})/(\d{1,2})/(1[34]\d\d)\b", r"\3/\2/\1", text)


def to_persian_digits(text: str) -> str:
    return text.translate(TO_FA_DIGITS)


# --- گام ۳: حروف عربی و اعراب --------------------------------------------------------
AR2FA = str.maketrans({
    "ي": "ی", "ى": "ی", "ې": "ی", "ۍ": "ی", "ێ": "ی",
    "ك": "ک", "ڪ": "ک", "ګ": "گ",
    "ة": "ه", "ە": "ه", "ھ": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "ٲ": "ا", "ٳ": "ا",
    "ؤ": "و",
    "‍": None,
})
# فتحه، ضمه، کسره، تنوین، تشدید، سکون، همزه بالا/پایین، الف کوچک و علائم قرآنی
DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")


def ar_to_fa(text: str) -> str:
    return text.translate(AR2FA)


# --- علائم قرینه وارونه -----------------------------------------------------------------
_PAIRS = (("«", "»"), ("(", ")"), ("[", "]"))


def fix_mirrored_pairs(text: str) -> str:
    """در استخراج راست‌به‌چپ، «» و () گاهی قرینه می‌شوند: «» هنرجو «» به‌جای «هنرجو».

    اگر اولین علامت هر جفت در یک خط، علامت بسته باشد و تعداد باز و بسته برابر باشد، جابه‌جا می‌شوند.
    """
    out = []
    for line in text.split("\n"):
        for o, c in _PAIRS:
            i, j = line.find(o), line.find(c)
            if j != -1 and (i == -1 or j < i) and line.count(o) == line.count(c):
                line = line.translate(str.maketrans({o: c, c: o}))
        out.append(line)
    return "\n".join(out)


# --- hazm (اختیاری اما توصیه‌شده) ----------------------------------------------------
@lru_cache(maxsize=1)
def _hazm_normalizer():
    try:
        from hazm import Normalizer
    except ImportError:  # pragma: no cover
        return None
    # اعداد را خودمان مدیریت می‌کنیم؛ اعراب و حروف خاص را هم پیش‌تر پاک کرده‌ایم
    return Normalizer(persian_numbers=False, remove_diacritics=False, remove_specials_chars=False)


_FALLBACK_RULES = [
    (re.compile(r"(?<![\w‌])(ن?می)\s+(?=[؀-ۿ])"), r"\1" + ZWNJ),
    (re.compile(r"(?<=[؀-ۿ])\s+(ها|های|هایی|هایم|هایت|هایش|ترین|تر)(?![\w‌])"), ZWNJ + r"\1"),
    (re.compile(r"\s+([.،؛:!؟?)\]»])"), r"\1"),
    (re.compile(r"([(\[«])\s+"), r"\1"),
]


def _fallback_normalize(text: str) -> str:
    for pat, rep in _FALLBACK_RULES:
        text = pat.sub(rep, text)
    return text


def _spacing(text: str) -> str:
    norm = _hazm_normalizer()
    return norm.normalize(text) if norm else _fallback_normalize(text)


# --- تابع نهایی ------------------------------------------------------------------------
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_SPACE_NL = re.compile(r" *\n *")
_DIGIT_SEP = re.compile(r"(?<=\d) ?([/:.]) ?(?=\d)")  # hazm تاریخ را «1405 / 07 / 27» می‌کند
_PERCENT = re.compile(r"(?<=\d) +%")
_LATIN_AT = re.compile(r"(?<=[A-Za-z])@ (?=\w)")


def pre_clean(text: str) -> str:
    """پاک‌سازی ارزان بدون hazm؛ برای تشخیص جهت خط و امتیاز واژگان روی تک‌خط‌ها."""
    text = fix_justify(text)
    text = ar_to_fa(text)
    text = DIACRITICS.sub("", text)
    return normalize_numbers(text)


def _post_spacing(text: str) -> str:
    text = _DIGIT_SEP.sub(r"\1", text)
    text = _PERCENT.sub("%", text)
    text = _LATIN_AT.sub("@", text)
    text = _ZWNJ_EDGE.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    return _SPACE_NL.sub("\n", text)


def clean_fa(text: str) -> str:
    """تمام اصلاحات با ترتیب درست؛ هم برای اسناد و هم برای پرسش کاربر."""
    if not text:
        return ""
    text = fix_justify(text)  # NFKC + حذف کشیده + فاصله‌ها
    text = ar_to_fa(text)  # حروف عربی -> فارسی
    text = DIACRITICS.sub("", text)  # اعراب
    text = fix_mirrored_pairs(text)  # «» و () وارونه
    text = normalize_numbers(text)  # ارقام لاتین + حذف کنترل‌های bidi (پیش از hazm تا اعداد را نشکند)
    text = _spacing(text)  # نیم‌فاصله، فاصله علائم، می/ها
    text = normalize_numbers(text)  # hazm ممیز را دوباره «٫» می‌کند
    return _post_spacing(text).strip()


def clean_steps(text: str) -> list[dict]:
    """خروجی هر مرحله clean_fa برای نمایش در آزمایشگاه متن."""
    steps = []
    t = text
    for name, fn in (
        ("NFKC، حذف کشیده و فاصله‌های پرکننده", fix_justify),
        ("تبدیل حروف عربی به فارسی", ar_to_fa),
        ("حذف اعراب", lambda s: DIACRITICS.sub("", s)),
        ("اصلاح «» و () وارونه", fix_mirrored_pairs),
        ("یکسان‌سازی ارقام و حذف کنترل‌های جهت", normalize_numbers),
        ("نیم‌فاصله و فاصله علائم (hazm)", lambda s: normalize_numbers(_spacing(s))),
        ("اصلاح فاصله تاریخ و پاک‌سازی نهایی فاصله‌ها", _post_spacing),
    ):
        nt = fn(t)
        steps.append({"name": name, "text": nt, "changed": nt != t})
        t = nt
    final = clean_fa(text)
    steps.append({"name": "خروجی نهایی clean_fa", "text": final, "changed": final != t})
    return steps


def display_fa(text: str) -> str:
    """اصلاح سبک خروجی LLM برای نمایش: فقط حروف عربی را فارسی می‌کند و به ارقام دست نمی‌زند."""
    return text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")


# --- کاراکترهای مشکوک (بخش ۶ و ۹ راهنما) ----------------------------------------------
ARABIC_ONLY = set("يكىةأإٱۀـ")
BAD_CHARS = re.compile(r"[ﭐ-﷿ﹰ-﻿ـيك�-]")


def odd_chars(text: str) -> Counter:
    return Counter(
        c for c in text
        if c in ARABIC_ONLY
        or not ("ء" <= c <= "ی" or c.isascii() or c in " \n‌«»،؛؟٪" or c.isdigit())
    )


def char_stats(text: str) -> dict:
    """نشانه‌های خرابی استخراج (looks_broken راهنما)."""
    fa = sum("؀" <= c <= "ۿ" for c in text)
    pres = sum("ﭐ" <= c <= "﻿" for c in text)
    latin1 = sum("À" <= c <= "ÿ" for c in text)
    pua = sum("" <= c <= "" or c == "�" for c in text)
    letters = sum(c.isalpha() for c in text) or 1
    return {
        "fa": fa,
        "presentation_forms": pres,
        "mojibake": latin1,
        "private_use": pua,
        "fa_ratio": round((fa + pres) / letters, 3),
    }


def looks_broken(text: str) -> bool:
    """متن بدون ToUnicode یا فونت غیر یونیکد: تنها راه OCR است."""
    s = char_stats(text)
    if len(text.strip()) < 30:
        return False
    junk = s["mojibake"] + s["private_use"]
    return junk > 0.2 * max(s["fa"] + s["presentation_forms"], 1) or (s["fa_ratio"] < 0.2 and s["mojibake"] > 20)
