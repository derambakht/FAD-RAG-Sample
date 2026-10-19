"""بخش‌بندی دقیق فارسی (بخش ۷ راهنما): ابتدا ساختار، سپس جمله، سپس بودجه توکن.

دو روش پایه هم برای مقایسه در ارزیابی وجود دارد: recursive (LangChain با جداکننده‌های فارسی)
و fixed (برش ثابت کاراکتری).
"""
from __future__ import annotations

import bisect
import re
import statistics
from dataclasses import dataclass, field

from app.core.extract import ExtractResult, Line
from app.core.normalize import clean_fa
from app.core.text_utils import ntok, split_sentences

END = re.compile(r"[.!؟?:؛»)\]]\s*$")

_ORDINALS = "اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|یازدهم|دوازدهم|یکم|نخست|آخر|پایانی"
HEADING_LEVELS = {
    "باب": 1, "فصل": 1, "بخش": 1, "قسمت": 1, "پیوست": 1,
    "مبحث": 2, "گفتار": 2, "درس": 2,
    "ماده": 3, "اصل": 3,
}
KEYWORD_HEADING = re.compile(
    rf"^({'|'.join(HEADING_LEVELS)})\s+(\d+|{_ORDINALS})(\s*[-–:.)]|\s*$|\s+\S)"
)
KEYWORD_ONLY = re.compile(rf"^({'|'.join(HEADING_LEVELS)})\s+(\d+|{_ORDINALS})$")
HEAD_STRIP = " -–—:.)"
KEYWORD_LEAD =re.compile(rf"^({'|'.join(HEADING_LEVELS)})\s+(\d+|{_ORDINALS})\s*[-–:.)]?\s*")
NUMBERED_HEADING =re.compile(r"^(\d+(?:\.\d+)*)[-.)]?\s+\S")
NOTE = re.compile(r"^تبصره(\s+\d+|\s*[-–:])")  # تبصره همراه ماده خودش می‌ماند
LIST_ITEM = re.compile(r"^([•▪●◾■\-–*]|\d+[).]|[ا-ی][)-])\s")


@dataclass
class ChunkOptions:
    strategy: str = "structure"  # structure | recursive | fixed
    max_tokens: int = 400
    overlap_sents: int = 1
    overlap_tokens: int = 60  # برای recursive
    chunk_chars: int = 800  # برای fixed
    heading_by_font: bool = True
    contextual_header: bool = True  # عنوان بخش داخل متن chunk (برای embedding)
    min_chunk_tokens: int = 0  # chunkهای کوچک‌تر به قبلی همان بخش ملحق می‌شوند

    @classmethod
    def from_dict(cls, d: dict | None) -> "ChunkOptions":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Paragraph:
    text: str
    page: int
    heading: bool = False
    level: int = 0


@dataclass
class Section:
    title: str
    path: str
    paras: list[Paragraph] = field(default_factory=list)


# --- تشخیص عنوان ---------------------------------------------------------------------
def body_font_size(lines: list[Line]) -> float:
    """اندازه فونت متن اصلی = میانه وزنی اندازه‌ها بر اساس تعداد کاراکتر."""
    weights: dict[float, int] = {}
    for ln in lines:
        if ln.size:
            weights[ln.size] = weights.get(ln.size, 0) + len(ln.text)
    total = sum(weights.values())
    acc = 0
    for size in sorted(weights):
        acc += weights[size]
        if acc >= total / 2:
            return size
    return 0.0


def heading_level(ln: Line, body_size: float, by_font: bool) -> int:
    """۰ یعنی عنوان نیست؛ عدد بزرگ‌تر یعنی عنوان سطح پایین‌تر."""
    t = ln.text.strip()
    if not t or len(t) > 120:
        return 0
    if ln.heading:
        return 1
    if m := KEYWORD_HEADING.match(t):
        return HEADING_LEVELS[m.group(1)]
    words = len(t.split())
    if (m := NUMBERED_HEADING.match(t)) and words <= 12 and not END.search(t):
        return 1 + m.group(1).count(".")
    if by_font and body_size and words <= 15 and not END.search(t):
        if ln.size >= body_size * 1.4:
            return 1
        if ln.size >= body_size * 1.15:
            return 2
        if ln.bold and ln.size >= body_size * 0.98 and words <= 10:
            return 3
    return 0


# --- خطوط به پاراگراف (گام ۳ بخش ۴ راهنما) ----------------------------------------------
def lines_to_paragraphs(lines: list[Line], by_font: bool = True) -> list[Paragraph]:
    body = body_font_size(lines)
    lens = [len(ln.text.strip()) for ln in lines if len(ln.text.strip()) > 20]
    median_len = statistics.median(lens) if lens else 60

    paras: list[Paragraph] = []
    buf: list[str] = []
    buf_page = 1

    def flush():
        nonlocal buf
        if buf:
            paras.append(Paragraph(" ".join(buf), buf_page))
            buf = []

    for ln in lines:
        t = ln.text.strip()
        if not t:  # خط خالی = پایان پاراگراف
            flush()
            continue
        # «ماده 5 - نمره نهایی. نمره نهایی از ...» در یک خط: عنوان «ماده 5» و بقیه متن پاراگراف است
        if not ln.heading and len(t.split()) > 8 and (m := KEYWORD_LEAD.match(t)):
            flush()
            paras.append(Paragraph(m.group(0).strip(HEAD_STRIP), ln.page, heading=True,
                                   level=HEADING_LEVELS[m.group(1)]))
            t = t[m.end():].strip()
            buf_page = ln.page
        elif lvl := heading_level(ln, body, by_font):
            flush()
            title = t.strip(HEAD_STRIP)
            prev = paras[-1] if paras else None
            # «فصل 1» و «کلیات» در دو خط جدا: یک عنوان «فصل 1 - کلیات»
            if prev and prev.heading and prev.page == ln.page and KEYWORD_ONLY.match(prev.text) \
                    and not KEYWORD_HEADING.match(title) and lvl >= prev.level:
                prev.text = f"{prev.text} - {title}"
            else:
                paras.append(Paragraph(title, ln.page, heading=True, level=lvl))
            continue
        elif NOTE.match(t) or LIST_ITEM.match(t):
            flush()
        if not buf:
            buf_page = ln.page
            t = t.lstrip("-–—:. ")  # خط تیره بعد از «ماده 1» در خط جدا
            if not t:
                continue
        buf.append(t)
        if END.search(t) and (len(t) < 0.75 * median_len or len(t) < 40):  # خط کوتاه پایانی پاراگراف
            flush()
    flush()
    return paras


def split_sections(paras: list[Paragraph]) -> list[Section]:
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    cur = Section("", "")
    for p in paras:
        if p.heading:
            if cur.paras:
                sections.append(cur)
            while stack and stack[-1][0] >= p.level:
                stack.pop()
            stack.append((p.level, p.text))
            cur = Section(p.text, " › ".join(t for _, t in stack))
        else:
            cur.paras.append(p)
    if cur.paras:
        sections.append(cur)
    return sections


# --- بخش‌بندی ساختارمحور -----------------------------------------------------------------
def _split_long(sent: str, budget: int) -> list[str]:
    """جمله طولانی‌تر از بودجه: ابتدا روی ؛ و ، و سپس روی کلمات شکسته می‌شود."""
    if ntok(sent) <= budget:
        return [sent]
    for sep in ("؛", "،", " "):
        parts = [p for p in re.split(f"(?<={sep})", sent) if p.strip()]
        if len(parts) > 1:
            out, buf = [], ""
            for p in parts:
                if buf and ntok(buf + p) > budget:
                    out.append(buf.strip())
                    buf = ""
                buf += p
            if buf.strip():
                out.append(buf.strip())
            return [x for piece in out for x in _split_long(piece, budget)] if sep != " " else out
    return [sent]


def _make(header: str, sents: list[tuple[str, int, int]], contextual: bool, kind: str = "text") -> dict:
    body = " ".join(s for s, _, _ in sents)
    text = f"{header}\n{body}".strip() if (header and contextual) else body
    return {"text": text, "body": body, "section": header, "page": sents[0][1],
            "page_end": sents[-1][1], "tokens": ntok(text), "kind": kind}


def chunk_structure(sections: list[Section], o: ChunkOptions) -> list[dict]:
    chunks: list[dict] = []
    for sec in sections:
        header = sec.path if o.contextual_header else sec.title
        budget = max(50, o.max_tokens - (ntok(header) if (header and o.contextual_header) else 0))
        sents: list[tuple[str, int, int]] = []
        for p in sec.paras:
            for s in split_sentences(p.text):
                for piece in _split_long(s, budget):
                    sents.append((piece, p.page, ntok(piece)))
        buf: list[tuple[str, int, int]] = []
        buf_tok = 0
        start = len(chunks)
        for item in sents:
            t = item[2]
            if buf and buf_tok + t > budget:
                chunks.append(_make(header, buf, o.contextual_header))
                buf = buf[-o.overlap_sents:] if o.overlap_sents else []
                buf_tok = sum(x[2] for x in buf)
                if buf_tok + t > budget:
                    buf, buf_tok = [], 0
            buf.append(item)
            buf_tok += t
        if buf:
            last = _make(header, buf, o.contextual_header)
            # chunk خیلی کوچک انتهای بخش به chunk قبلی همان بخش می‌پیوندد
            if o.min_chunk_tokens and len(chunks) > start and last["tokens"] < o.min_chunk_tokens:
                prev = chunks[-1]
                new_sents = [x for x in buf if x[0] not in prev["body"]]
                if new_sents:
                    merged_body = prev["body"] + " " + " ".join(s for s, _, _ in new_sents)
                    prev["body"] = merged_body
                    prev["text"] = f"{header}\n{merged_body}".strip() if (header and o.contextual_header) else merged_body
                    prev["page_end"] = new_sents[-1][1]
                    prev["tokens"] = ntok(prev["text"])
            else:
                chunks.append(last)
    return chunks


# --- روش‌های پایه برای مقایسه -------------------------------------------------------------
def _joined_with_offsets(paras: list[Paragraph]) -> tuple[str, list[int], list[int]]:
    text, starts, pages = "", [], []
    for p in paras:
        if text:
            text += "\n\n"
        starts.append(len(text))
        pages.append(p.page)
        text += p.text
    return text, starts, pages


def chunk_baseline(paras: list[Paragraph], o: ChunkOptions) -> list[dict]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    text, starts, pages = _joined_with_offsets(paras)
    if o.strategy == "fixed":
        splitter = RecursiveCharacterTextSplitter(separators=[""], chunk_size=o.chunk_chars, chunk_overlap=0)
    else:
        splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", ".", "؟", "!", "؛", "،", " ", ""],
            chunk_size=o.max_tokens, chunk_overlap=o.overlap_tokens,
            length_function=ntok, keep_separator="end",
        )
    out = []
    for d in splitter.create_documents([text], metadatas=[{}]) if text else []:
        body = d.page_content.strip()
        if not body:
            continue
        pos = text.find(d.page_content)
        i = max(0, bisect.bisect_right(starts, pos) - 1)
        j = max(0, bisect.bisect_right(starts, pos + len(d.page_content)) - 1)
        out.append({"text": body, "body": body, "section": "", "page": pages[i] if pages else 1,
                    "page_end": pages[j] if pages else 1, "tokens": ntok(body), "kind": "text"})
    return out


# --- جدول‌ها --------------------------------------------------------------------------
def table_chunks(tables: list[dict], max_tokens: int) -> list[dict]:
    """جدول کامل نگه داشته می‌شود؛ اگر بزرگ بود بر اساس سطر شکسته و سطر عنوان تکرار می‌شود."""
    out = []
    for i, t in enumerate(tables, 1):
        header = f"جدول {i} (صفحه {t['page']})"
        lines = t["markdown"].split("\n")
        head, rows = lines[:2], lines[2:]
        buf: list[str] = []
        for r in rows + [None]:
            if r is None or (buf and ntok("\n".join(head + buf + [r])) > max_tokens):
                if buf:
                    body = "\n".join(head + buf)
                    out.append({"text": f"{header}\n{body}", "body": body, "section": header,
                                "page": t["page"], "page_end": t["page"], "tokens": ntok(body), "kind": "table"})
                buf = []
            if r is not None:
                buf.append(r)
    return out


# --- ورودی اصلی --------------------------------------------------------------------------
def build_chunks(ext: ExtractResult, o: ChunkOptions, clean: bool = True) -> tuple[list[dict], dict]:
    paras = lines_to_paragraphs(ext.lines, o.heading_by_font)
    if clean:
        for p in paras:
            p.text = clean_fa(p.text)
        paras = [p for p in paras if p.text]
    if o.strategy == "structure":
        sections = split_sections(paras)
        chunks = chunk_structure(sections, o)
        n_sections = len(sections)
    else:
        chunks = chunk_baseline([p for p in paras], o)
        n_sections = 0
    chunks += table_chunks(ext.tables, o.max_tokens)
    for i, c in enumerate(chunks):
        c["idx"] = i
    stats = {
        "paragraphs": len(paras),
        "headings": sum(p.heading for p in paras),
        "sections": n_sections,
        "chunks": len(chunks),
        "avg_tokens": round(sum(c["tokens"] for c in chunks) / max(len(chunks), 1), 1),
        "max_tokens": max((c["tokens"] for c in chunks), default=0),
    }
    return chunks, stats
