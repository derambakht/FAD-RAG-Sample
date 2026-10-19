"""پرسش‌های آماری روی داده‌های جدولی (اکسل فروش): پرسش فارسی ← SQL ← اجرای دقیق ← پاسخ.

بازیابی معنایی برای «جمع فروش شعبه X» یا «پرفروش‌ترین کالا» کافی نیست، چون LLM فقط چند chunk می‌بیند و
جمع بستن صدها عدد را هم نباید به LLM سپرد. اینجا LLM فقط کوئری را می‌نویسد؛ محاسبه را SQLite انجام می‌دهد
و LLM نتیجه را به فارسی توضیح می‌دهد. جدول نتیجه هم بدون واسطه LLM در پنل نمایش داده می‌شود.

کوئری روی یک کپی درون‌حافظه‌ای و فقط‌خواندنی از سطرهای همین پایگاه دانش اجرا می‌شود؛ هیچ دسترسی به
جدول‌های دیگر یا پایگاه دانش‌های دیگر ندارد.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
import time
from collections import Counter

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.core.spreadsheet import fmt_num, norm_text
from app.db import get_db

log = logging.getLogger(__name__)

MAX_ROWS = 200  # سقف سطرهای نتیجه که خوانده می‌شود
SHOW_ROWS = 60  # سطرهایی که به LLM داده می‌شود
TIMEOUT_S = 5.0

COLUMNS = ("source", "sheet", "row_no", "supplier", "supplier_code", "branch", "barcode", "product",
           "qty", "amount", "discount")

SCHEMA = """جدول sales — هر سطر فروش یک کالا در یک شعبه از یک تامین‌کننده است (از فایل‌های اکسل بارگذاری‌شده):
- supplier (TEXT): نام تامین‌کننده
- supplier_code (TEXT): کد تامین‌کننده
- branch (TEXT): نام شعبه/فروشگاه
- product (TEXT): نام کالا (معمولاً نام برند در انتهای آن آمده است)
- barcode (TEXT): بارکد کالا
- qty (REAL): مقدار/تعداد فروش رفته
- amount (REAL): مبلغ فروش رفته
- discount (REAL): مبلغ تخفیف سهم تامین‌کننده
- source (TEXT): نام فایل، sheet (TEXT): نام شیت، row_no (INTEGER): ردیف در گزارش"""

SQL_SYSTEM = """تو تحلیلگر داده‌ای هستی که پرسش فارسی کاربر را به یک کوئری SQLite روی جدول sales تبدیل می‌کنی.

{schema}

مقادیر موجود در داده‌ها:
{values}

قواعد:
- فقط یک دستور SELECT (یا WITH ... SELECT) داخل ```sql ... ``` بنویس و هیچ توضیح دیگری نده.
- اگر پرسش به داده‌های فروش این جدول ربطی ندارد (مثلاً احوالپرسی یا پرسش درباره متن اسناد دیگر)، فقط بنویس: NONE
- «تعداد فروش» یا «مقدار فروش» یعنی SUM(qty)؛ «مبلغ فروش» یعنی SUM(amount)؛ «تخفیف» یعنی SUM(discount). COUNT(*) فقط برای «چند قلم/چند ردیف کالا» است.
- برای یک شعبه یا تامین‌کننده مشخص، نام کامل را از فهرست بالا بردار و با = فیلتر کن (مثل branch = 'شعبه مگامال')، چون بخشی از نام ممکن است در چند شعبه باشد (مثل «اصفهان» در «شعبه اصفهان» و «زرین شهر اصفهان»). LIKE فقط برای کالا/برند، یا وقتی کاربر عمداً چند شعبه را می‌خواهد (مثل «همه شعبه‌های کرج»).
- «به تفکیک»، «هر شعبه» یا «مقایسه» یعنی GROUP BY؛ نتیجه را با ORDER BY مرتب کن.
- برای ستون‌های خروجی نام فارسی خوانا با AS "..." بگذار و ستون‌های گروه‌بندی را هم در خروجی بیاور.
- برای فهرست کالاها LIMIT بگذار (پیش‌فرض 20، حداکثر 100) مگر کاربر تعداد دیگری بخواهد.
- مبلغ‌ها را گرد نکن و واحدشان را تغییر نده. برای درصد و سهم از ROUND(100.0 * ... / ..., 2) استفاده کن.
- «میانگین مبلغ هر عدد» یا «میانگین قیمت» یعنی SUM(amount) / SUM(qty) (نه AVG(amount / qty))؛ «نسبت تخفیف به فروش» یعنی ROUND(100.0 * SUM(discount) / SUM(amount), 2).
- اگر کاربر شعبه یا تامین‌کننده‌ای را مشخص نکرده، روی همه داده‌ها حساب کن.
- پرسش‌های پیگیری را با توجه به گفتگوی قبلی کامل کن (مثلاً «و در شعبه دیگر؟»).

نمونه‌ها:
پرسش: جمع فروش شعبه مگامال چقدر است؟
```sql
SELECT SUM(qty) AS "جمع تعداد فروش", SUM(amount) AS "جمع مبلغ فروش", SUM(discount) AS "جمع تخفیف" FROM sales WHERE branch = 'شعبه مگامال'
```
پرسش: فروش شعبه‌ها را مقایسه کن
```sql
SELECT branch AS "شعبه", SUM(qty) AS "تعداد فروش", SUM(amount) AS "مبلغ فروش", SUM(discount) AS "تخفیف" FROM sales GROUP BY branch ORDER BY SUM(amount) DESC
```
پرسش: ۳ شعبه برتر از نظر تعداد فروش
```sql
SELECT branch AS "شعبه", SUM(qty) AS "تعداد فروش" FROM sales GROUP BY branch ORDER BY SUM(qty) DESC LIMIT 3
```
پرسش: ۵ کالای پرفروش سافتلن از نظر تعداد
```sql
SELECT product AS "کالا", SUM(qty) AS "تعداد فروش", SUM(amount) AS "مبلغ فروش" FROM sales WHERE product LIKE '%سافتلن%' GROUP BY product ORDER BY SUM(qty) DESC LIMIT 5
```"""

SQL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SQL_SYSTEM),
    MessagesPlaceholder("history"),
    ("human", "{question}"),
])

RETRY_HUMAN = """کوئری قبلی:
```sql
{sql}
```
{problem}
کوئری اصلاح‌شده را بنویس (یا NONE)."""

ANSWER_SYSTEM = """تو دستیار تحلیل فروش هستی و به فارسی روان پاسخ می‌دهی. پاسخ را فقط بر اساس «نتیجه کوئری» بنویس که از
داده‌های واقعی فایل‌های اکسل محاسبه شده است.
قواعد:
- اعداد را دقیقاً همان‌طور که در نتیجه آمده (با جداکننده هزارگان) بنویس؛ خودت عددی را جمع، گرد یا تخمین نزن.
- بگو نتیجه برای کدام شعبه/تامین‌کننده/کالا است (فیلترهای کوئری).
- برای چند سطر نتیجه، فهرست یا جدول markdown کوتاه بنویس.
- اگر نتیجه خالی است یا مقدارش خالی است، بگو داده‌ای مطابق این پرسش پیدا نشد و نام‌های نزدیک را پیشنهاد بده.
- واحد پول در فایل ذکر نشده؛ واحد (ریال/تومان) اضافه نکن.
- از SQL حرفی نزن مگر کاربر بپرسد."""

ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ANSWER_SYSTEM),
    MessagesPlaceholder("history"),
    ("human", "پرسش: {question}\n\nفیلتر/محاسبه انجام‌شده (SQL):\n{sql}\n\nنتیجه کوئری ({n} سطر{more}):\n{table}"),
])


# --- پایگاه درون‌حافظه‌ای هر پایگاه دانش ---------------------------------------------------
class SalesData:
    def __init__(self, rows: list[dict]):
        self.rows = len(rows)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.execute(f"CREATE TABLE sales ({', '.join(COLUMNS)})")
        self.conn.executemany(f"INSERT INTO sales VALUES ({','.join('?' * len(COLUMNS))})",
                              [tuple(r.get(c) for c in COLUMNS) for r in rows])
        self.conn.commit()
        self.conn.create_function("norm", 1, norm_text, deterministic=True)
        self.conn.set_authorizer(_authorizer)
        self.branches = Counter(r["branch"] for r in rows)
        self.suppliers = Counter(f"{r['supplier']}" + (f" (کد {r['supplier_code']})" if r["supplier_code"] else "")
                                 for r in rows)
        self.products = sorted({r["product"] for r in rows if r["product"]})
        self.sources = Counter(r["source"] for r in rows)
        self._ptokens = [(p, set(_tokens(p))) for p in self.products]

    def values_text(self, question: str) -> str:
        lines = [f"- تعداد سطرها: {self.rows}، تعداد کالاهای متمایز: {len(self.products)}",
                 f"- فایل‌ها: {'، '.join(self.sources)}",
                 f"- تامین‌کننده‌ها ({len(self.suppliers)}): {'، '.join(list(self.suppliers)[:80])}",
                 f"- شعبه‌ها ({len(self.branches)}): {'، '.join(sorted(self.branches)[:200])}"]
        related = self.related_products(question)
        if related:
            lines.append("- کالاهای مرتبط با پرسش: " + "؛ ".join(related))
        return "\n".join(lines)

    def related_products(self, question: str, n: int = 15) -> list[str]:
        q = set(_tokens(question))
        if not q:
            return []
        scored = [(len(q & t), p) for p, t in self._ptokens if q & t]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [p for _, p in scored[:n]]

    def matching(self, col: str, pattern: str) -> list[str]:
        """نام‌های شعبه/تامین‌کننده که با الگوی LIKE جور می‌شوند."""
        values = self.branches if col == "branch" else {s.split(" (کد")[0] for s in self.suppliers}
        parts = [re.escape(p).replace("_", ".") for p in pattern.split("%")]
        rx = re.compile("^" + ".*".join(parts) + "$", re.I | re.S)
        return sorted(v for v in values if rx.match(v))

    def run(self, sql: str) -> tuple[list[str], list[tuple], bool]:
        with self.lock:
            deadline = time.monotonic() + TIMEOUT_S
            self.conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            try:
                cur = self.conn.execute(sql)
                cols = [d[0] for d in cur.description or []]
                rows = cur.fetchmany(MAX_ROWS + 1)
            finally:
                self.conn.set_progress_handler(None, 0)
        return cols, rows[:MAX_ROWS], len(rows) > MAX_ROWS


_STOP = {"در", "از", "به", "با", "و", "که", "را", "این", "آن", "چه", "چقدر", "چند", "است", "بود", "کدام", "برای",
         "فروش", "مبلغ", "تعداد", "تخفیف", "شعبه", "کالا", "کالای", "رفته", "کل", "جمع", "مجموع", "هر", "سهم",
         "تامین", "کننده", "بیشترین", "کمترین", "پرفروش", "ترین", "گرمی", "گ", "عددی", "حاوی", "مخصوص"}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w]+", norm_text(text)) if len(t) > 1 and t not in _STOP and not t.isdigit()]


_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, getattr(sqlite3, "SQLITE_FUNCTION", 31),
            getattr(sqlite3, "SQLITE_RECURSIVE", 33)}


def _authorizer(action, arg1, arg2, dbname, source):
    """فقط خواندن از جدول sales؛ هر نوشتن، PRAGMA، ATTACH یا ساخت جدول رد می‌شود."""
    if action not in _ALLOWED:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ and arg1 != "sales":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


_cache: dict[tuple, SalesData] = {}
_cache_lock = threading.Lock()


def get_data(collection_id: str, document_ids: list[str] | None = None) -> SalesData | None:
    db = get_db()
    col = db.get_collection(collection_id)
    if col is None:
        return None
    key = (collection_id, col["version"], tuple(sorted(document_ids or [])))
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    rows = db.sales_rows(collection_id, document_ids)
    data = SalesData(rows) if rows else None
    with _cache_lock:
        for k in [k for k in _cache if k[0] == collection_id and k[1] != col["version"]]:
            _cache.pop(k).conn.close()
        if data is not None:
            _cache[key] = data
    return data


def has_data(collection_id: str) -> bool:
    return get_db().count_sales_rows(collection_id) > 0


# --- SQL -------------------------------------------------------------------------------
_SQL_BLOCK = re.compile(r"```(?:sql|sqlite)?\s*(.+?)```", re.S | re.I)
_LITERAL = re.compile(r"'((?:[^']|'')*)'")


def extract_sql(text: str) -> str | None:
    """کوئری از پاسخ LLM؛ None یعنی پرسش آماری نیست."""
    text = (text or "").strip()
    m = _SQL_BLOCK.search(text)
    sql = m.group(1) if m else text
    sql = sql.strip().rstrip(";").strip()
    if not sql or re.fullmatch(r"[`\s]*NONE[`.\s]*", sql, re.I) or (not m and "NONE" in text.upper()[:20]):
        return None
    if not re.match(r"^(SELECT|WITH)\b", sql, re.I):
        m2 = re.search(r"\b(SELECT|WITH)\b.+", sql, re.I | re.S)
        if not m2:
            return None
        sql = m2.group(0)
    if ";" in sql.strip().rstrip(";"):
        sql = sql.split(";")[0]
    return sql.strip()


def normalize_literals(sql: str) -> str:
    """رشته‌های داخل کوئری با همان نرمال‌سازی داده‌ها (ی/ک عربی، ارقام، نیم‌فاصله) یکسان می‌شوند."""
    def fix(m: re.Match) -> str:
        raw = m.group(1).replace("''", "'")
        parts = [norm_text(p) if p.strip() else p for p in re.split(r"([%_])", raw)]
        val = "".join(parts)
        return "'" + val.replace("'", "''") + "'"
    return _LITERAL.sub(fix, sql)


# پرسش درباره یک معیار، کوئری باید ستون همان معیار را بخواند (خطای رایج: COUNT(*) به جای SUM(qty))
_METRIC_CHECKS = (
    (re.compile(r"تعداد\s*(فروش|فروخته|کالای فروخته)|مقدار\s*فروش|چند\s*(عدد|تا|واحد)\s*.*فروخته|فروخته\s*شده"), "qty",
     "پرسش درباره تعداد/مقدار فروش رفته است؛ باید از SUM(qty) استفاده شود، نه COUNT(*) یا تعداد ردیف‌ها."),
    (re.compile(r"مبلغ|ریالی|درآمد"), "amount", "پرسش درباره مبلغ فروش است؛ باید از ستون amount (مثلاً SUM(amount)) استفاده شود."),
    (re.compile(r"تخفیف"), "discount", "پرسش درباره تخفیف است؛ باید از ستون discount (مثلاً SUM(discount)) استفاده شود."),
)


def check_metrics(question: str, sql: str) -> str | None:
    q, low = norm_text(question), sql.lower()
    for pat, col, problem in _METRIC_CHECKS:
        if pat.search(q) and not re.search(rf"\b{col}\b", low):
            return problem
    return None


_NAME_LIKE = re.compile(r"\b(branch|supplier)\s+LIKE\s+'((?:[^']|'')*)'", re.I)


def check_ambiguous(data: "SalesData", sql: str) -> str | None:
    """فیلتر LIKE روی شعبه/تامین‌کننده که با چند نام مختلف جور می‌شود (مثل «اصفهان»)."""
    for col, pat in _NAME_LIKE.findall(sql):
        names = data.matching(col.lower(), pat.replace("''", "'"))
        if len(names) > 1:
            return (f"فیلتر {col} LIKE '{pat}' با چند نام مختلف جور است: {'، '.join(names[:10])}. "
                    "اگر کاربر یکی از آن‌ها را می‌خواهد با = و نام کامل فیلتر کن؛ اگر واقعاً همه را می‌خواهد همین کوئری را تکرار کن.")
    return None


def _is_empty(cols: list[str], rows: list[tuple]) -> bool:
    return not rows or all(all(v is None for v in r) for r in rows)


def fmt_cell(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return fmt_num(v) if v.is_integer() or abs(v) >= 1000 else f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return fmt_num(v) if abs(v) >= 1000 else str(v)
    return str(v).replace("|", "/")


def to_markdown(cols: list[str], rows: list[tuple], limit: int = SHOW_ROWS) -> str:
    if not cols:
        return "(بدون ستون)"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt_cell(v) for v in r) + " |" for r in rows[:limit]]
    return "\n".join(lines)


class _Rejected(Exception):
    """کوئری پیش از اجرا رد شد (ستون معیار پرسش را نمی‌خواند)."""


async def generate_and_run(llm, data: SalesData, question: str, history: list) -> dict | None:
    """تولید SQL با LLM و اجرای آن؛ در صورت خطا یا نتیجه خالی یک بار با بازخورد اصلاح می‌شود.

    خروجی None یعنی پرسش آماری نبود؛ در غیر این صورت {sql, columns, rows, truncated, attempts, error?}.
    """
    chain = SQL_PROMPT | llm | StrOutputParser()
    vars_ = {"schema": SCHEMA, "values": data.values_text(question), "history": history, "question": question}
    raw = await chain.ainvoke(vars_)
    sql = extract_sql(raw)
    if sql is None:
        return None
    attempts: list[dict] = []
    best: dict | None = None
    force = False  # LLM همان کوئری ردشده را تکرار کرد: اجرا شود
    for attempt in range(3):
        sql = normalize_literals(sql)
        problem = None if force or attempt == 2 else (check_metrics(question, sql) or check_ambiguous(data, sql))
        rejected = bool(problem)
        if problem:
            attempts.append({"sql": sql, "error": problem})
        t = time.perf_counter()
        try:
            if problem:
                raise _Rejected(problem)
            cols, rows, truncated = await asyncio.to_thread(data.run, sql)
            res = {"sql": sql, "columns": cols, "rows": rows, "truncated": truncated,
                   "ms": round((time.perf_counter() - t) * 1000)}
            attempts.append({"sql": sql, "rows": len(rows)})
            if not _is_empty(cols, rows):
                best = res
                break
            best = best or res
            problem = ("نتیجه این کوئری خالی بود. احتمالاً فیلتر نام شعبه/تامین‌کننده/کالا با داده‌ها جور نیست؛ "
                       "املای مقادیر موجود را بررسی کن یا بخش کوتاه‌تری از نام را در LIKE بگذار. "
                       "اگر واقعاً داده‌ای وجود ندارد، همان کوئری را تکرار کن.")
        except _Rejected:
            pass
        except sqlite3.Error as e:
            attempts.append({"sql": sql, "error": str(e)})
            problem = f"اجرای این کوئری خطا داد: {e}"
        if attempt == 2:
            break
        retry = ChatPromptTemplate.from_messages([
            ("system", SQL_SYSTEM), MessagesPlaceholder("history"), ("human", "{question}"),
            ("ai", "```sql\n{prev}\n```"), ("human", RETRY_HUMAN)])
        raw = await (retry | llm | StrOutputParser()).ainvoke({**vars_, "prev": sql, "sql": sql, "problem": problem})
        new_sql = extract_sql(raw)
        if new_sql is None or normalize_literals(new_sql) == sql:
            if not rejected:
                break
            force = True
            continue
        sql = new_sql
    if best is None:
        return {"sql": sql, "columns": [], "rows": [], "truncated": False, "attempts": attempts,
                "error": attempts[-1].get("error") if attempts else "کوئری ساخته نشد"}
    best["attempts"] = attempts
    return best


def public_result(res: dict) -> dict:
    """نتیجه برای ارسال به پنل (JSON)."""
    return {"sql": res["sql"], "columns": res["columns"], "rows": [[fmt_cell(v) for v in r] for r in res["rows"]],
            "row_count": len(res["rows"]), "truncated": res.get("truncated", False),
            "attempts": len(res.get("attempts", [])), "error": res.get("error")}


def answer_inputs(res: dict, question: str, history: list) -> dict:
    n = len(res["rows"])
    more = f"، {SHOW_ROWS} سطر اول نمایش داده شده" if n > SHOW_ROWS else ""
    if res.get("truncated"):
        more = f"، بیش از {MAX_ROWS} سطر؛ {SHOW_ROWS} سطر اول نمایش داده شده"
    table = to_markdown(res["columns"], res["rows"]) if n else "(نتیجه خالی است)"
    return {"history": history, "question": question, "sql": res["sql"], "n": n, "more": more, "table": table}
