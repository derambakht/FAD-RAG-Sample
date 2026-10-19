"""خواندن گزارش‌های جدولی اکسل/CSV (مثل گزارش فروش تامین‌کننده به تفکیک شعبه).

دو چیدمان پشتیبانی می‌شود و در یک فایل هم می‌توانند کنار هم باشند:
- گزارشی: سطرهای «تامین کننده : ...» و «شعبه : ...» بالای هر جدول، سطر عنوان ستون‌ها، سطرهای داده و سطر «جمع».
- تخت: یک سطر عنوان که ستون شعبه و تامین‌کننده را هم دارد.

هر سطر داده به یک رکورد با فیلدهای استاندارد تبدیل می‌شود تا هم در SQLite برای محاسبه دقیق جمع و
گروه‌بندی ذخیره شود و هم به‌صورت متن برای بازیابی معنایی chunk شود.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.normalize import clean_fa

TABLE_EXT = {".xlsx", ".xlsm", ".xls", ".csv"}
ZWNJ = "‌"

# فیلدهای استاندارد؛ ترتیب بررسی مهم است (از خاص به عام)
FIELDS = ("row_no", "barcode", "product", "qty", "amount", "discount", "branch", "supplier", "supplier_code")
FIELD_LABELS = {
    "row_no": "ردیف", "barcode": "بارکد کالا", "product": "نام کالا", "qty": "تعداد فروش رفته",
    "amount": "مبلغ فروش رفته", "discount": "مبلغ تخفیف سهم تامین‌کننده", "branch": "شعبه",
    "supplier": "تامین‌کننده", "supplier_code": "کد تامین‌کننده",
}
NUMERIC = {"qty", "amount", "discount"}

_SUPPLIER_RE = re.compile(r"^(تامین|تأمین)\s*کننده|^تولید\s*کننده|^پخش\s*کننده")
_BRANCH_RE = re.compile(r"^(شعبه|فروشگاه|نام شعبه)$")
_TOTAL_RE = re.compile(r"^(جمع|جمع کل|مجموع|total)\b", re.I)
_KV_RE = re.compile(r"^\s*(تامین\s*کننده|تأمین\s*کننده|شعبه|فروشگاه)\s*[:：]\s*(.*)$")


def norm_text(v) -> str:
    """نرمال‌سازی یکسان مقدار سلول‌ها و پرسش‌ها (حروف عربی، ارقام، نیم‌فاصله ← فاصله)."""
    if v is None:
        return ""
    s = str(v).strip()
    return _norm(s) if s else ""


@lru_cache(maxsize=65536)  # نام شعبه، تامین‌کننده و کالا در فایل بارها تکرار می‌شوند
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", clean_fa(s).replace(ZWNJ, " ")).strip()


def norm_header(v) -> str:
    s = norm_text(v).strip("[]{}() :")
    s = s.replace("_", " ").replace("کاال", "کالا")  # «کاال» شکل شکسته «کالا» در خروجی برخی گزارش‌ها
    return re.sub(r"\s+", " ", s)


def classify_header(h: str) -> str | None:
    if not h:
        return None
    if h == "ردیف" or h in ("#", "row"):
        return "row_no"
    if "تخفیف" in h:
        return "discount"
    if "بارکد" in h or h in ("کد کالا", "barcode"):
        return "barcode"
    if "تامین" in h or "تأمین" in h:
        return "supplier_code" if "کد" in h else "supplier"
    if "مبلغ" in h or "فروش ریالی" in h or h in ("ارزش فروش", "amount"):
        return "amount"
    if any(w in h for w in ("مقدار", "تعداد")) or h in ("qty", "quantity"):
        return "qty"
    if _BRANCH_RE.match(h) or "شعبه" in h:
        return "branch"
    if "کالا" in h or "محصول" in h or h in ("شرح", "نام", "product"):
        return "product"
    return None


def parse_number(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = clean_fa(str(v)).replace(",", "").replace("٬", "").replace(" ", "")
    s = s.replace("٫", ".").replace("/", ".") if re.fullmatch(r"-?\d+[٫/]\d+", s) else s
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def split_supplier(label: str) -> tuple[str, str]:
    """«گل پخش اول 11572» ← («گل پخش اول»، «11572»)."""
    m = re.match(r"^(.*?)[\s\-–:]*\(?(\d{2,})\)?$", label)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2)
    m = re.match(r"^\(?(\d{2,})\)?[\s\-–:]+(.+)$", label)
    if m:
        return m.group(2).strip(), m.group(1)
    return label, ""


@dataclass
class TableBlock:
    sheet: str
    sheet_index: int
    supplier: str
    supplier_code: str
    branch: str
    columns: dict[int, str]  # شماره ستون ← فیلد استاندارد
    extra_columns: dict[int, str]  # ستون‌های ناشناخته ← عنوان
    records: list[dict] = field(default_factory=list)
    reported_total: dict[str, float] = field(default_factory=dict)  # از سطر «جمع» فایل


@dataclass
class SheetParse:
    blocks: list[TableBlock] = field(default_factory=list)
    generic: list[dict] = field(default_factory=list)  # شیت‌هایی که گزارش فروش نبودند: {sheet, rows}
    warnings: list[str] = field(default_factory=list)

    @property
    def records(self) -> list[dict]:
        out = []
        for b in self.blocks:
            out.extend(b.records)
        return out

    def summary(self) -> dict:
        recs = self.records
        return {
            "tables": len(self.blocks),
            "rows": len(recs),
            "branches": sorted({r["branch"] for r in recs}),
            "suppliers": sorted({r["supplier"] for r in recs}),
            "generic_sheets": len(self.generic),
            "warnings": self.warnings,
        }


# --- خواندن فایل -------------------------------------------------------------------------
def read_sheets(path: Path) -> list[tuple[str, list[list]]]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        finally:
            wb.close()
    if ext == ".xls":
        try:
            import xlrd
        except ImportError as e:
            raise ValueError("برای فایل .xls بسته xlrd لازم است: pip install xlrd") from e
        book = xlrd.open_workbook(str(path))
        return [(sh.name, [sh.row_values(i) for i in range(sh.nrows)]) for sh in book.sheets()]
    if ext == ".csv":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "utf-16", "cp1256"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [(path.stem, [row for row in csv.reader(io.StringIO(text), dialect)])]
    raise ValueError(f"نوع فایل جدولی پشتیبانی نمی‌شود: {ext}")


# --- تحلیل ساختار --------------------------------------------------------------------------
def _cells(row: list) -> list[tuple[int, object]]:
    return [(i, c) for i, c in enumerate(row) if c is not None and str(c).strip() != ""]


def _kv(row: list) -> tuple[str, str] | None:
    """سطر «تامین کننده : X» یا «شعبه : Y» (در یک سلول یا دو سلول کنار هم)."""
    cells = _cells(row)
    if not cells or len(cells) > 4:
        return None
    texts = [norm_text(c) for _, c in cells]
    for j, t in enumerate(texts):
        m = _KV_RE.match(t)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if not val and j + 1 < len(texts):
            val = texts[j + 1]
        if not val:
            continue
        return ("supplier" if "کننده" in key else "branch"), val
    # «تامین کننده» در یک سلول و مقدار در سلول بعدی، بدون دونقطه
    if len(texts) == 2:
        k = texts[0].rstrip(" :")
        if _SUPPLIER_RE.match(k):
            return "supplier", texts[1]
        if _BRANCH_RE.match(k):
            return "branch", texts[1]
    return None


def _header(row: list) -> tuple[dict[int, str], dict[int, str]] | None:
    cols: dict[int, str] = {}
    extra: dict[int, str] = {}
    for i, c in _cells(row):
        if isinstance(c, (int, float)) or parse_number(c) is not None:
            return None  # سطر عنوان عدد ندارد (در CSV همه سلول‌ها متن‌اند)
        h = norm_header(c)
        f = classify_header(h)
        if f and f not in cols.values():
            cols[i] = f
        elif h:
            extra[i] = h
    fields = set(cols.values())
    if ({"product", "barcode"} & fields) and ({"qty", "amount", "discount"} & fields) and len(fields) >= 3:
        return cols, extra
    return None


def _is_total(row: list) -> bool:
    for _, c in _cells(row)[:3] + _cells(row)[-3:]:
        if isinstance(c, str) and _TOTAL_RE.match(norm_text(c).strip(" :")):
            return True
    return False


def _total_values(row: list, block: TableBlock) -> dict[str, float]:
    """اعداد سطر جمع؛ چون ممکن است در ستون‌های جابه‌جا باشند، به ترتیب ستون‌های عددی بلوک نسبت داده می‌شوند."""
    out: dict[str, float] = {}
    nums = [(i, parse_number(c)) for i, c in _cells(row)]
    nums = [(i, n) for i, n in nums if n is not None]
    for i, n in nums:
        f = block.columns.get(i)
        if f in NUMERIC:
            out[f] = n
    return out


def _record(row: list, block: TableBlock) -> dict | None:
    rec: dict = {"extra": {}}
    for i, f in block.columns.items():
        v = row[i] if i < len(row) else None
        if f in NUMERIC:
            rec[f] = parse_number(v)
        elif f == "row_no":
            n = parse_number(v)
            rec[f] = int(n) if n is not None else None
        elif f == "barcode":
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            rec[f] = norm_text(v).strip("[]")
        else:
            rec[f] = norm_text(v)
    for i, h in block.extra_columns.items():
        v = row[i] if i < len(row) else None
        if v is not None and str(v).strip():
            rec["extra"][h] = v if isinstance(v, (int, float)) else norm_text(v)
    if not (rec.get("product") or rec.get("barcode")):
        return None
    if all(rec.get(f) is None for f in NUMERIC):
        return None
    for f in NUMERIC:
        rec[f] = rec.get(f) or 0.0
    sup_label = rec.get("supplier") or block.supplier
    sup, code = split_supplier(sup_label) if sup_label else ("نامشخص", "")
    rec["supplier"] = sup
    rec["supplier_code"] = rec.get("supplier_code") or code or block.supplier_code
    rec["branch"] = rec.get("branch") or block.branch or "نامشخص"
    rec["sheet"] = block.sheet
    rec.setdefault("product", "")
    rec.setdefault("barcode", "")
    rec.setdefault("row_no", None)
    return rec


def _default_sheet_name(name: str) -> bool:
    return bool(re.fullmatch(r"(sheet|برگه|صفحه|شیت)\s*\d*", norm_text(name), re.I))


def parse_sheets(sheets: list[tuple[str, list[list]]], default_supplier: str = "") -> SheetParse:
    res = SheetParse()
    for si, (name, rows) in enumerate(sheets, 1):
        ctx = {"supplier": default_supplier, "branch": ""}
        block: TableBlock | None = None
        n_blocks = len(res.blocks)
        for row in rows:
            row = list(row or [])
            if not _cells(row):
                continue
            kv = _kv(row)
            if kv:
                ctx[kv[0]] = kv[1]
                if block is not None:  # شروع گزارش بعدی (شعبه یا تامین‌کننده جدید)
                    block = None
                continue
            hdr = _header(row)
            if hdr:
                if block is not None and block.supplier == ctx["supplier"] and block.branch == ctx["branch"] \
                        and hdr[0] == block.columns:
                    continue  # عنوان تکرارشونده در صفحه‌های بعدی همان گزارش
                sup, code = split_supplier(ctx["supplier"]) if ctx["supplier"] else ("", "")
                branch = ctx["branch"] or ("" if _default_sheet_name(name) else norm_text(name))
                block = TableBlock(sheet=name, sheet_index=si, supplier=sup, supplier_code=code, branch=branch,
                                   columns=hdr[0], extra_columns=hdr[1])
                res.blocks.append(block)
                continue
            if block is None:
                continue
            if _is_total(row):
                block.reported_total = _total_values(row, block)
                continue
            rec = _record(row, block)
            if rec:
                block.records.append(rec)
        if len(res.blocks) == n_blocks:
            if any(_cells(r) for r in rows):
                res.generic.append({"sheet": name, "sheet_index": si, "rows": [list(r) for r in rows if _cells(list(r or []))]})
    res.blocks = [b for b in res.blocks if b.records]
    _validate(res)
    return res


def _validate(res: SheetParse) -> None:
    """مقایسه جمع محاسبه‌شده با سطر «جمع» خود فایل؛ اختلاف یعنی سطری جا افتاده یا ستون اشتباه خوانده شده."""
    for b in res.blocks:
        for f, reported in b.reported_total.items():
            got = sum(r[f] for r in b.records)
            if abs(got - reported) > max(1.0, abs(reported) * 1e-6):
                res.warnings.append(
                    f"جمع «{FIELD_LABELS[f]}» در {b.branch or b.sheet} با سطر جمع فایل یکسان نیست: "
                    f"محاسبه‌شده {got:,.0f} و در فایل {reported:,.0f}")
    if not res.blocks and not res.generic:
        res.warnings.append("هیچ جدولی در فایل پیدا نشد")


# --- PDF گزارش فروش (خروجی سامانه فروشگاه) -----------------------------------------------
REPORT_HEADER = ["ردیف", "بارکد_کالا", "نام_کالا", "مقدار_فروش_رفته", "مبلغ_فروش_رفته", "مبلغ_تخفیف_سهم_تامین_کننده"]
_REPORT_KV = re.compile(r"^(تامین کننده|شعبه)\s*:\s*(.+)$")


def _fa_visual(text: str) -> str:
    """متن فارسی که pdfplumber با ترتیب بصری (حروف معکوس) برمی‌گرداند."""
    from app.core.extract import reverse_line
    from app.core.normalize import pre_clean
    t = pre_clean(text or "").strip()
    return reverse_line(t) if re.search(r"[؀-ۿ]", t) else t


def _report_num(s):
    s = (s or "").replace(",", "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def is_report_pdf(path: Path) -> bool:
    """PDF گزارش فروش تامین‌کننده/شعبه است؟ (فقط صفحه اول بررسی می‌شود)"""
    if path.suffix.lower() != ".pdf":
        return False
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return False
            lines = [_fa_visual(ln) for ln in (pdf.pages[0].extract_text() or "").splitlines()[:6]]
    except Exception:
        return False
    keys = {m.group(1) for ln in lines if (m := _REPORT_KV.match(ln))}
    return keys == {"تامین کننده", "شعبه"}


def read_report_pdf(path: Path, progress=None) -> list[tuple[str, list[list]]]:
    """جدول‌های PDF گزارش فروش ← سطرها با همان چیدمان گزارشی اکسل (تامین‌کننده، شعبه، عنوان، سطرها، جمع)."""
    import pdfplumber

    rows: list[list] = []
    supplier = branch = None
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if progress and i % 10 == 0:
                progress(i / max(n, 1), f"خواندن صفحه {i + 1} از {n}")
            lines = [_fa_visual(ln) for ln in (page.extract_text() or "").splitlines()]
            for ln in lines:
                m = _REPORT_KV.match(ln)
                if not m:
                    continue
                if m.group(1) == "تامین کننده":
                    supplier = m.group(2)
                elif m.group(2) != branch:
                    branch = m.group(2)
                    rows += [["تامین کننده :", supplier], ["شعبه :", branch], [f"[{h}]" for h in REPORT_HEADER]]
            for table in page.extract_tables():
                for r in table:
                    r = list(r)[::-1]  # ستون‌ها از راست به چپ‌اند
                    if len(r) < 6 or not (r[0] or "").strip().isdigit():
                        continue
                    rows.append([int(r[0]), (r[1] or "").strip("[] "), _fa_visual(r[2]),
                                 _report_num(r[3]), _report_num(r[4]), _report_num(r[5])])
            for ln in lines:
                m = re.match(r"^جمع\s*:\s*([\d,]+)\s+([\d,]+)", ln) or re.match(r"^([\d,]+)\s+([\d,]+)\s*:\s*جمع$", ln)
                if m:
                    small, big = sorted((_report_num(m.group(1)), _report_num(m.group(2))))
                    rows += [["جمع :", None, None, None, big, small], []]
    return [(path.stem, rows)]


def parse_file(path: Path, default_supplier: str = "", progress=None) -> SheetParse:
    if path.suffix.lower() == ".pdf":
        return parse_sheets(read_report_pdf(path, progress), default_supplier)
    return parse_sheets(read_sheets(path), default_supplier)


# --- متن برای بازیابی معنایی ---------------------------------------------------------------
def fmt_num(n: float | None) -> str:
    if n is None:
        return "-"
    return f"{n:,.0f}" if float(n).is_integer() else f"{n:,.2f}"


def block_title(b: TableBlock) -> str:
    sup = b.supplier + (f" (کد {b.supplier_code})" if b.supplier_code else "")
    return f"گزارش فروش تامین‌کننده {sup or 'نامشخص'} در {b.branch or 'شعبه نامشخص'}"


def record_line(r: dict) -> str:
    parts = [f"کالا: {r['product']}"]
    if r.get("barcode"):
        parts.append(f"بارکد: {r['barcode']}")
    parts += [f"تعداد فروش: {fmt_num(r['qty'])}", f"مبلغ فروش: {fmt_num(r['amount'])}",
              f"تخفیف سهم تامین‌کننده: {fmt_num(r['discount'])}"]
    for k, v in (r.get("extra") or {}).items():
        parts.append(f"{k}: {v}")
    return " | ".join(parts)


def summary_text(b: TableBlock, top: int = 10) -> str:
    recs = b.records
    q, a, d = (sum(r[f] for r in recs) for f in ("qty", "amount", "discount"))
    lines = [
        f"خلاصه {block_title(b)}:",
        f"تعداد اقلام (ردیف کالا): {len(recs)}",
        f"جمع تعداد فروش رفته: {fmt_num(q)}",
        f"جمع مبلغ فروش رفته: {fmt_num(a)}",
        f"جمع مبلغ تخفیف سهم تامین‌کننده: {fmt_num(d)}",
        f"{top} کالای پرفروش از نظر مبلغ:",
    ]
    for i, r in enumerate(sorted(recs, key=lambda r: -r["amount"])[:top], 1):
        lines.append(f"{i}. {r['product']}: مبلغ {fmt_num(r['amount'])}، تعداد {fmt_num(r['qty'])}")
    return "\n".join(lines)


def overall_text(res: SheetParse, filename: str) -> str:
    """خلاصه کل فایل به تفکیک شعبه و تامین‌کننده."""
    recs = res.records
    lines = [f"خلاصه کل فایل {filename}: {len(recs)} ردیف کالا در {len(res.blocks)} گزارش"]
    for key, label in (("branch", "شعبه"), ("supplier", "تامین‌کننده")):
        groups: dict[str, list[dict]] = {}
        for r in recs:
            groups.setdefault(r[key], []).append(r)
        lines.append(f"به تفکیک {label}:")
        for g, rs in sorted(groups.items(), key=lambda kv: -sum(r["amount"] for r in kv[1])):
            lines.append(f"- {g}: تعداد فروش {fmt_num(sum(r['qty'] for r in rs))}، مبلغ فروش "
                         f"{fmt_num(sum(r['amount'] for r in rs))}، تخفیف {fmt_num(sum(r['discount'] for r in rs))}، "
                         f"{len(rs)} ردیف")
    lines.append(f"جمع کل: تعداد فروش {fmt_num(sum(r['qty'] for r in recs))}، مبلغ فروش "
                 f"{fmt_num(sum(r['amount'] for r in recs))}، تخفیف {fmt_num(sum(r['discount'] for r in recs))}")
    return "\n".join(lines)


def build_table_chunks(res: SheetParse, filename: str, max_tokens: int = 400) -> list[dict]:
    """chunkهای متنی: یک خلاصه کلی، یک خلاصه برای هر گزارش و سطرها در دسته‌های هم‌اندازه با عنوان تکرارشونده."""
    from app.core.text_utils import ntok

    chunks: list[dict] = []

    def add(text: str, section: str, page: int, kind: str = "table") -> None:
        chunks.append({"text": text, "body": text, "section": section, "page": page, "page_end": page,
                       "tokens": ntok(text), "kind": kind})

    if res.blocks:
        add(overall_text(res, filename), "خلاصه کل", 1, "summary")
    for b in res.blocks:
        title = block_title(b)
        add(summary_text(b), title, b.sheet_index, "summary")
        buf: list[str] = []
        for r in b.records + [None]:
            line = record_line(r) if r else None
            if line is None or (buf and ntok("\n".join([title, *buf, line])) > max_tokens):
                if buf:
                    add("\n".join([title, *buf]), title, b.sheet_index)
                buf = []
            if line:
                buf.append(line)
    for g in res.generic:  # شیت‌های دیگر: سطر به سطر با عنوان ستون‌ها
        head = [norm_text(c) for c in g["rows"][0]]
        title = f"شیت {g['sheet']}"
        buf = []
        for row in g["rows"][1:] + [None]:
            line = None
            if row is not None:
                line = " | ".join(f"{h or 'ستون ' + str(i + 1)}: {norm_text(c)}" for i, (h, c) in
                                  enumerate(zip(head + [""] * (len(row) - len(head)), row)) if str(c or "").strip())
            if line is None or (buf and ntok("\n".join([title, *buf, line])) > max_tokens):
                if buf:
                    add("\n".join([title, *buf]), title, g["sheet_index"])
                buf = []
            if line:
                buf.append(line)
    for i, c in enumerate(chunks):
        c["idx"] = i
    return chunks
