"""تبدیل PDF گزارش فروش تامین‌کننده (خروجی سامانه فروشگاه) به اکسل با همان چیدمان گزارشی.

پنل این PDF ها را مستقیم هم می‌پذیرد؛ این اسکریپت برای ساخت فایل نمونه اکسل است:
    python scripts/report_pdf_to_xlsx.py report.pdf sample_data/sales-report-sample.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.spreadsheet import read_report_pdf  # noqa: E402


def convert(src: Path, dest: Path) -> int:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "گزارش فروش"
    ws.sheet_view.rightToLeft = True
    n = 0
    for _, rows in read_report_pdf(src):
        for r in rows:
            ws.append(r)
            n += bool(r) and isinstance(r[0], int)
    for col, w in zip("ABCDEF", (6, 16, 70, 12, 16, 16)):
        ws.column_dimensions[col].width = w
    wb.save(str(dest))
    return n


if __name__ == "__main__":
    print(f"{convert(Path(sys.argv[1]), Path(sys.argv[2]))} rows -> {sys.argv[2]}")
