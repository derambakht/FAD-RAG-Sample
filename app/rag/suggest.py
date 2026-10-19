"""پرسش‌های پیشنهادی هوشمند: از داده‌های همان پایگاه دانش و در ادامه پرسش‌های قبلی همان کاربر.

ورودی LLM سه بخش است:
- «داده‌ها»: برای فایل‌های فروش، نام دقیق شعبه‌ها/تامین‌کننده‌ها/کالاها و رتبه‌ها (از خود جدول)؛
  برای اسناد متنی، بخش‌ها و متن‌های مرتبط با پرسش‌های کاربر.
- پرسش‌های قبلی کاربر در گفتگوهای دیگر همین پایگاه دانش (علایق کاربر).
- گفتگوی فعلی همراه با نتیجه آخرین پاسخ (مثلاً سطرهای جدول SQL) تا پیشنهادها پیگیری همان مسیر باشند.
اگر LLM در دسترس نباشد یا خطا بدهد، پیشنهادها با الگو از همان داده‌ها و پرسش‌های قبلی ساخته می‌شوند.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
from collections import Counter, OrderedDict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.normalize import display_fa
from app.core.spreadsheet import fmt_num, norm_text
from app.db import get_db
from app.rag import analytics

log = logging.getLogger(__name__)

LLM_TIMEOUT_S = 30
PAST_QUESTIONS = 8   # پرسش‌های گفتگوهای دیگر که به LLM داده می‌شود
SESSION_TURNS = 6    # پیام‌های آخر گفتگوی فعلی

SUGGEST_SYSTEM = """تو پرسش‌های پیشنهادی برای کاربرِ یک دستیار گفتگو با پایگاه دانش می‌نویسی: پرسش‌هایی که کاربر به احتمال زیاد می‌خواهد بعداً بپرسد.
قواعد:
- هر پرسش باید با همین «داده‌ها» قابل پاسخ باشد. فقط نام‌های دقیقی را بیاور که در داده‌ها آمده است و نامی نساز.
- اگر گفتگوی فعلی هست، پرسش‌ها ادامه منطقی آن باشند: جزئی‌تر کردن نتیجه آخر (مثلاً کالاها یا شعبه‌های همان نتیجه)، مقایسه با شعبه/تامین‌کننده/کالای مشابه، یا شاخص دیگر همان موضوع.
- اگر گفتگوی فعلی خالی است، از علایق کاربر در پرسش‌های قبلی‌اش الهام بگیر؛ اگر آن هم نیست، پرسش‌های متنوع درباره مهم‌ترین بخش‌های داده بنویس.
- پرسش‌ها تکرار پرسش‌های قبلی کاربر نباشند و از نوع‌های مختلف باشند (مثلاً یکی جزئی‌تر، یکی مقایسه مستقیم، یکی رتبه‌بندی یا سهم). پرسش قبلی را فقط با عوض کردن یک نام تکرار نکن؛ به‌جایش مقایسه مستقیم آن دو را پیشنهاد بده.
- هر پرسش مستقل و بدون گفتگو قابل فهم باشد: نام شعبه/کالا/موضوع را صریح بیاور و از «آن»، «این شعبه»، «همین» یا گروه‌های مبهم مثل «شعبه‌های مشابه» استفاده نکن.
- کوتاه (حداکثر ۲۰ واژه) و به فارسی روان.
{extra}
خروجی: دقیقاً {n} پرسش، هر کدام در یک خط، بدون شماره، توضیح یا متن دیگر."""

TABLE_RULES = """- داده فقط این ستون‌ها را دارد: شعبه، تامین‌کننده، کالا، بارکد، تعداد فروش، مبلغ فروش، تخفیف سهم تامین‌کننده. تاریخ، ماه، موجودی، سود و مشتری ندارد؛ درباره روند زمانی یا این موارد نپرس.
- پرسش‌های آماری خوب: جمع/مقایسه/رتبه‌بندی/درصد سهم/نسبت تخفیف به فروش/میانگین مبلغ هر عدد، به تفکیک شعبه، تامین‌کننده یا کالا."""

TEXT_RULES = ("- فقط درباره اطلاعاتی بپرس که صریحاً در متن‌های داده‌شده آمده و پاسخش در همان متن‌ها هست؛ "
              "از دانش عمومی یا موضوعی که در متن نیست پرسش نساز.")

SUGGEST_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SUGGEST_SYSTEM),
    ("human", "داده‌ها:\n{profile}\n\nپرسش‌های قبلی کاربر در گفتگوهای دیگر این پایگاه دانش:\n{past}\n\n"
              "گفتگوی فعلی:\n{conversation}\n\n{n} پرسش پیشنهادی:"),
])


# --- زمینه: پرسش‌های کاربر ---------------------------------------------------------------
def gather_context(collection_id: str, session_id: str | None) -> dict:
    db = get_db()
    turns: list[dict] = []
    if session_id:
        for m in db.list_chat_messages(session_id):
            meta = m.get("meta") or {}
            if not m["content"] or meta.get("error"):
                continue
            t = {"role": m["role"], "content": m["content"]}
            a = (meta.get("info") or {}).get("analytics")
            if m["role"] == "assistant" and a:
                t["analytics"] = a
            turns.append(t)
    asked = {norm_text(t["content"]) for t in turns if t["role"] == "user"}  # همه پرسش‌های این گفتگو
    turns = turns[-SESSION_TURNS:]
    past, seen = [], set(asked)
    for q in db.recent_user_questions(collection_id, exclude_session=session_id, limit=60):
        k = norm_text(q)
        if k and k not in seen:
            seen.add(k)
            past.append(q.strip())
        if len(past) >= PAST_QUESTIONS:
            break
    return {"turns": turns, "past": past, "asked": seen}


def _conversation_text(turns: list[dict]) -> str:
    if not turns:
        return "(گفتگوی جدید است)"
    out = []
    for t in turns:
        if t["role"] == "user":
            out.append(f"کاربر: {t['content']}")
            continue
        out.append(f"دستیار: {t['content'][:600]}")
        a = t.get("analytics")
        if a and a.get("rows"):
            head = " | ".join(a.get("columns") or [])
            rows = "\n".join(" | ".join(map(str, r)) for r in a["rows"][:8])
            out.append(f"(نتیجه محاسبه: {a.get('row_count', len(a['rows']))} سطر)\n{head}\n{rows}")
    return "\n".join(out)


# --- زمینه: داده‌ها -----------------------------------------------------------------------
def _branch_label(b: str) -> str:
    return b if b.startswith("شعبه") else f"شعبه {b}"


def mentioned(names, text: str) -> list[str]:
    """نام‌هایی که در متن آمده‌اند؛ نام طولانی‌تر اول، تا «اصفهان» داخل «زرین شهر اصفهان» جدا شمرده نشود."""
    t = _plain(text)
    found = []
    for name in sorted(names, key=lambda n: -len(n)):
        for form in (name, re.sub(r"^شعبه\s+", "", name)):
            f = _plain(form)
            if len(f) > 3 and f in t:
                found.append((t.find(f), name))
                t = t.replace(f, " ")
                break
    return [n for _, n in sorted(found)]


def _plain(text: str) -> str:
    return " " + " ".join(re.sub(r"[^\w\s]", " ", norm_text(text)).split()) + " "


# واژه‌های عمومی پرسش که نباید کالای مرتبط پیدا کنند
_GENERIC = {"عدد", "فروخته", "شده", "داشته", "بوده", "اند", "کالاهای", "ها", "نشان", "بده", "بگو", "نسبت", "درصد",
            "مقایسه", "کن", "کم", "زیاد", "فهرست", "برتر", "تفکیک", "چیست", "هست", "شعبه‌ها", "شعبه", "تامین‌کننده"}


def focus_products(data: analytics.SalesData, text: str, n: int = 5) -> list[str]:
    q = set(analytics._tokens(text)) - _GENERIC
    if not q:
        return []
    need = 1 if len(q) == 1 else 2
    scored = [(len(q & t), p) for p, t in data._ptokens]
    scored = sorted((x for x in scored if x[0] >= need), key=lambda x: (-x[0], x[1]))
    return [p for _, p in scored[:n]]


class TableFacts:
    def __init__(self, data: analytics.SalesData, focus_text: str):
        self.data = data
        q = lambda sql: data.run(sql)[1]  # noqa: E731
        self.total = q("SELECT COUNT(*), SUM(qty), SUM(amount), SUM(discount) FROM sales")[0]
        self.branches = [r[0] for r in q("SELECT branch FROM sales GROUP BY branch ORDER BY SUM(amount) DESC")]
        self.suppliers = [r[0] for r in q("SELECT supplier FROM sales GROUP BY supplier ORDER BY SUM(amount) DESC")]
        self.top_products = [r[0] for r in q(
            "SELECT product FROM sales GROUP BY product ORDER BY SUM(amount) DESC LIMIT 8")]
        self.focus_branches = mentioned(self.branches, focus_text)
        self.focus_suppliers = mentioned([s for s in self.suppliers if s], focus_text)
        rest = _plain(focus_text)
        for name in self.focus_branches + self.focus_suppliers:  # نام شعبه/تامین‌کننده، کالا پیدا نکند
            rest = rest.replace(_plain(name), " ").replace(_plain(re.sub(r"^شعبه\s+", "", name)), " ")
        self.focus_products = focus_products(data, rest)

    def branch_top(self, branch: str, n: int = 5) -> list[str]:
        sql = ("SELECT product FROM sales WHERE branch = '" + branch.replace("'", "''") +
               f"' GROUP BY product ORDER BY SUM(amount) DESC LIMIT {n}")
        return [r[0] for r in self.data.run(sql)[1]]

    def neighbour(self, branch: str) -> str | None:
        """شعبه هم‌رتبه برای مقایسه."""
        if branch not in self.branches or len(self.branches) < 2:
            return None
        i = self.branches.index(branch)
        return self.branches[i + 1] if i + 1 < len(self.branches) else self.branches[i - 1]

    def profile(self) -> str:
        n, qty, amount, disc = self.total
        lines = [f"داده جدولی فروش: {fmt_num(n)} سطر، جمع تعداد {fmt_num(qty)}، جمع مبلغ {fmt_num(amount)}، "
                 f"جمع تخفیف {fmt_num(disc)}",
                 f"تامین‌کننده‌ها: {'، '.join(s for s in self.suppliers[:20] if s)}",
                 f"شعبه‌ها به ترتیب مبلغ فروش (از بیشترین): {'، '.join(self.branches[:60])}",
                 f"پرفروش‌ترین کالاها از نظر مبلغ: {'؛ '.join(self.top_products)}"]
        for b in self.focus_branches[:2]:
            lines.append(f"پرفروش‌ترین کالاهای {b}: {'؛ '.join(self.branch_top(b))}")
            i = self.branches.index(b)
            near = [x for x in self.branches[max(0, i - 1):i + 3] if x != b][:2]
            if near:
                lines.append("مقایسه‌های مناسب: " + "؛ ".join(f"{b} با {x}" for x in near))
        if self.focus_products:
            lines.append(f"کالاهای مرتبط با پرسش‌های کاربر: {'؛ '.join(self.focus_products)}")
        return "\n".join(lines)

    def templates(self) -> list[str]:
        out = []
        for b in self.focus_branches[:2]:
            bl = _branch_label(b)
            out += [f"۵ کالای پرفروش {bl} از نظر مبلغ فروش کدام‌اند؟",
                    f"جمع تخفیف سهم تامین‌کننده در {bl} چقدر است؟"]
            if (o := self.neighbour(b)):
                out.append(f"{bl} و {_branch_label(o)} را از نظر تعداد، مبلغ فروش و تخفیف مقایسه کن.")
            out.append(f"سهم {bl} از کل مبلغ فروش چند درصد است؟")
        for s in self.focus_suppliers[:1]:
            out.append(f"مبلغ فروش تامین‌کننده {s} به تفکیک شعبه چقدر است؟")
        for p in self.focus_products[:2]:
            out.append(f"کالای «{p}» در کدام شعبه‌ها بیشترین فروش را داشته است؟")
        top = self.branches[0] if self.branches else None
        out += ["کدام شعبه بیشترین مبلغ فروش را داشته است؟",
                "۱۰ کالای پرفروش از نظر مبلغ فروش کدام‌اند؟",
                "نسبت تخفیف به مبلغ فروش در هر شعبه چند درصد است؟"]
        if top:
            out.append(f"تعداد فروش، مبلغ فروش و تخفیف {_branch_label(top)} چقدر است؟")
        out.append("کم‌فروش‌ترین ۵ شعبه از نظر مبلغ فروش کدام‌اند؟")
        if len(self.suppliers) > 1:
            out.append("جمع مبلغ فروش و تخفیف هر تامین‌کننده چقدر است؟")
        return out


class TextFacts:
    def __init__(self, collection_id: str, focus_text: str):
        db = get_db()
        chunks = [c for c in db.all_chunks(collection_id) if c.get("kind") != "table"]
        self.sources = list(dict.fromkeys(c["source"] for c in chunks))
        self.sections = [s for s, _ in Counter(c["section"].strip() for c in chunks
                                               if (c.get("section") or "").strip()).most_common(30)]
        self.related: list[dict] = []
        if focus_text.strip():
            try:
                from app.rag.retrieval import search
                hits, _ = search(collection_id, focus_text[-800:], "bm25", 4)
                self.related = [{"section": h.section, "text": h.text} for h in hits]
            except Exception as e:  # pragma: no cover - بازیابی نباید پیشنهاد را متوقف کند
                log.warning("بازیابی برای پیشنهاد ناموفق بود: %s", e)
        if not self.related and chunks:
            step = max(1, len(chunks) // 4)
            self.related = [{"section": c["section"], "text": c["body"]} for c in chunks[::step][:4]]

    def profile(self) -> str:
        lines = [f"اسناد: {'، '.join(self.sources[:20])}"]
        if self.sections:
            lines.append(f"بخش‌ها: {'؛ '.join(self.sections)}")
        for r in self.related:
            lines.append(f"---\n[{r['section'] or 'متن'}] {r['text'][:500]}")
        return "\n".join(lines)

    def templates(self) -> list[str]:
        secs = list(dict.fromkeys([r["section"] for r in self.related if r["section"]] + self.sections))
        out = [f"در بخش «{s}» چه نکاتی آمده است؟" for s in secs[:6]]
        out += [f"خلاصه سند «{s}» چیست؟" for s in self.sources[:2]]
        return out + ["خلاصه‌ای از مهم‌ترین نکات اسناد بده."]


# --- تولید ---------------------------------------------------------------------------------
# پرسش‌هایی با ارجاع مبهم که بدون گفتگو پاسخ‌پذیر نیستند
_VAGUE = re.compile(r"هم[\s‌]?رتبه|مشابه|همین|این شعبه|آن شعبه|این کالا|موارد بالا")
_LEAD = re.compile(r"^\s*(?:[-*•–]+|[\d۰-۹]+\s*[.)\-:،]|سوال\s*[\d۰-۹]*\s*:|پرسش\s*[\d۰-۹]*\s*:)\s*")


def parse_questions(text: str) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        q = _LEAD.sub("", line).strip().strip("\"'«»“”`").strip()
        q = re.sub(r"\*\*|__", "", q).strip()
        if (not q or q.endswith(":") or len(q) < 8 or len(q) > 200 or not re.search(r"[؀-ۿ]", q)
                or _VAGUE.search(q)):
            continue
        if q.endswith("?"):
            q = q[:-1] + "؟"
        out.append(display_fa(q))
    return out


def pick(candidates: list[str], asked: set[str], n: int) -> list[str]:
    out, seen = [], set(asked)
    for q in candidates:
        k = norm_text(q)
        if k and k not in seen:
            seen.add(k)
            out.append(q)
        if len(out) >= n:
            break
    return out


_cache: OrderedDict[str, dict] = OrderedDict()
_cache_lock = threading.Lock()


async def suggest(collection_id: str, session_id: str | None, llm_provider: str | None, llm_model: str | None,
                  n: int = 4) -> dict:
    db = get_db()
    col = db.get_collection(collection_id)
    ctx = await asyncio.to_thread(gather_context, collection_id, session_id)
    key = hashlib.sha1(json.dumps([collection_id, col["version"], ctx["turns"], ctx["past"], llm_provider,
                                   llm_model, n], ensure_ascii=False, default=str).encode()).hexdigest()
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    # تمرکز: پرسش‌های گفتگوی فعلی (آخری مهم‌تر) و در گفتگوی جدید، پرسش‌های قبلی کاربر
    user_turns = [t["content"] for t in ctx["turns"] if t["role"] == "user"]
    focus = " ".join(user_turns[-2:]) if user_turns else " ".join(ctx["past"][:3])
    last = next((t for t in reversed(ctx["turns"]) if t["role"] == "assistant"), None)
    if last and last.get("analytics"):
        focus += " " + " ".join(str(r[0]) for r in last["analytics"].get("rows", [])[:3] if r)

    data = await asyncio.to_thread(analytics.get_data, collection_id)
    facts = await asyncio.to_thread(TableFacts, data, focus) if data is not None else \
        await asyncio.to_thread(TextFacts, collection_id, focus)
    templates = facts.templates()

    result = None
    if llm_provider and llm_model:
        try:
            from app.providers import get_llm
            llm = get_llm(llm_provider, llm_model, 0.4)
            raw = await asyncio.wait_for((SUGGEST_PROMPT | llm | StrOutputParser()).ainvoke({
                "n": n, "extra": TABLE_RULES if data is not None else TEXT_RULES,
                "profile": await asyncio.to_thread(facts.profile),
                "past": "\n".join(f"- {q}" for q in ctx["past"]) or "(ندارد)",
                "conversation": _conversation_text(ctx["turns"]),
            }), LLM_TIMEOUT_S)
            got = pick(parse_questions(raw), ctx["asked"], n)
            if got:
                result = {"suggestions": pick(got + templates, ctx["asked"], n), "source": "llm"}
        except Exception as e:
            log.warning("ساخت پرسش پیشنهادی با LLM ناموفق بود: %s", e)
    if result is None:
        result = {"suggestions": pick(templates, ctx["asked"], n), "source": "data"}
    result["context"] = {"session_questions": len(user_turns), "past_questions": len(ctx["past"]),
                         "tabular": data is not None}
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > 256:
            _cache.popitem(last=False)
    return result
