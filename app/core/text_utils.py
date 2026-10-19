"""ابزارهای مشترک: امتیاز واژگان، شمارش توکن، جمله‌بندی و توکن‌سازی BM25."""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from app.core.normalize import ZWNJ

log = logging.getLogger(__name__)

FA_WORD = re.compile(r"[؀-ۿ‌]+")
_SUFFIXES = ("هایی", "هایم", "هایت", "هایش", "هایمان", "ترین", "های", "ها", "تر", "ات", "ان", "ای", "ام", "اش", "یم", "ید", "ند", "ی", "م", "ت", "ش")


# --- واژگان (بخش ۴ راهنما) --------------------------------------------------------
@lru_cache(maxsize=1)
def vocab() -> frozenset[str]:
    try:
        from hazm.utils import words_list
        return frozenset(w[0] for w in words_list())
    except Exception:  # pragma: no cover - hazm اختیاری است
        log.warning("واژگان hazm در دسترس نیست؛ vocab_score تقریبی خواهد بود")
        return frozenset()


def _known(tok: str, v: frozenset[str]) -> bool:
    if tok in v or tok.replace(ZWNJ, "") in v:
        return True
    parts = [p for p in tok.split(ZWNJ) if len(p) > 1 and p not in ("می", "نمی")]
    if any(p in v for p in parts):
        return True
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 2 and tok[: -len(suf)] in v:
            return True
    return False


def vocab_score(text: str) -> float:
    """نسبت کلمات فارسی شناخته‌شده؛ برای انتخاب بهترین خروجی استخراج و تشخیص متن خراب."""
    toks = FA_WORD.findall(text)
    if not toks:
        return 0.0
    v = vocab()
    if not v:  # جایگزین تقریبی: کلمات تک‌حرفی پشت سر هم نشانه خرابی‌اند
        return sum(len(t) > 1 for t in toks) / len(toks)
    return sum(_known(t, v) for t in toks) / len(toks)


def fa_token_count(text: str) -> int:
    return len(FA_WORD.findall(text))


# --- شمارش توکن -----------------------------------------------------------------------
@lru_cache(maxsize=1)
def _encoder():
    from app.config import get_settings
    try:
        import tiktoken
        return tiktoken.get_encoding(get_settings().tokenizer_encoding)
    except Exception as e:  # pragma: no cover - مثلاً بدون اینترنت در اولین اجرا
        log.warning("توکنایزر tiktoken بارگذاری نشد (%s)؛ از تخمین استفاده می‌شود", e)
        return None


def ntok(text: str) -> int:
    enc = _encoder()
    if enc is None:
        return max(1, round(len(text) / 2.6))
    return len(enc.encode(text, disallowed_special=()))


# --- جمله‌بندی --------------------------------------------------------------------------
_SENT_FALLBACK = re.compile(r"(?<=[.!؟?])\s+|\n+")


@lru_cache(maxsize=1)
def _hazm_sent():
    try:
        from hazm import sent_tokenize
        return sent_tokenize
    except ImportError:  # pragma: no cover
        return None


def split_sentences(text: str) -> list[str]:
    fn = _hazm_sent()
    sents = fn(text) if fn else _SENT_FALLBACK.split(text)
    return [s.strip() for s in sents if s and s.strip()]


# --- توکن‌سازی BM25 ---------------------------------------------------------------------
STOPWORDS = frozenset("""
و در به از که این را با است برای آن یک تا بر هم نیز اما یا اگر هر ها های شود شده می‌شود
بود باشد کرد کرده کند کنند دارد داشت خود دیگر پس چون چه همین همان آنها ایشان او ما شما
ولی بلکه نه هیچ بین روی زیر پیش بعد قبل وی نیست هست باید شد شوند گردد گردید
""".split())
_WORD = re.compile(r"[\w‌]+", re.UNICODE)


def bm25_tokens(text: str) -> list[str]:
    """توکن‌های BM25؛ برای کلمات نیم‌فاصله‌دار، اجزا هم اضافه می‌شوند (کتاب‌ها -> کتاب)."""
    out: list[str] = []
    for w in _WORD.findall(text.lower()):
        w = w.strip(ZWNJ)
        if not w or w in STOPWORDS:
            continue
        out.append(w)
        if ZWNJ in w:
            out.extend(p for p in w.split(ZWNJ) if len(p) > 1 and p not in STOPWORDS and p not in ("می", "نمی"))
    return out


def word_set(text: str) -> set[str]:
    return set(bm25_tokens(text))


def overlap_coefficient(a: str, b: str) -> float:
    """|A∩B| / min(|A|,|B|) روی مجموعه کلمات؛ برای تطبیق gold بین پایگاه‌های با chunkبندی متفاوت."""
    sa, sb = word_set(a), word_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))
