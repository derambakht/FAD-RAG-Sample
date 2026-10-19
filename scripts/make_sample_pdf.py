"""ساخت PDF نمونه فارسی برای کلاس و تست‌ها.

عمداً شامل مشکلات رایج است: کاف/یای عربی، کشیده، ارقام فارسی و عربی، متن justify،
سرصفحه و شماره صفحه تکراری، و ساختار فصل/ماده/تبصره.

اجرا:  python scripts/make_sample_pdf.py  [مسیر فونت TTF با پشتیبانی فارسی]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_data" / "aeen-nameh-namoone.pdf"
FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/tahoma.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"),
]

PAGES = [
    """
<h1>آیین‌نامه آموزشی دوره مهندسی هوش مصنوعی</h1>
<h2>فصل ۱ - کليات</h2>
<p><b>ماده ۱ - هدف.</b> هدف از اين آيين‌نامه، تعيين ضوابط برگزاری دوره‌های آموزشی مهندسی هوش مصنوعی و ارزيابی هنرجويان است. این آیین‌نامه در تاریخ ۱۴۰۵/۰۷/۲۷ به تصويب شورای آموزشی رسید و از ابتدای نيمسال اول اجرا می‌شود.</p>
<p><b>ماده ۲ - تعاریف.</b> در این آیین‌نامه منظور از «هنرجو» شخصی است که در دوره ثبت‌نام کرده و شهریه آن را پرداخت کرده است. منظور از «جلسه» یک نشست آموزشی ۱۸۰ دقیقه‌ای است که به صورت حضوری یا برخط برگزار می‌شود.</p>
<p><b>ماده ۳ - مدت دوره.</b> مدت هر دوره ۱۶ هفته است و در هر هفته يک جلسه برگزار می‌شود. حداکثر ظرفيت هر کلاس ۲۵ نفر است.</p>
<p>تبصره ۱ - در صورت درخواست بیش از ۴۰ نفر، کلاس دوم با همان سرفصل تشکیل می‌شود.</p>
<h2>فصل ۲ - حضور و غیاب</h2>
<p><b>ماده ۴ - غیبت مجاز.</b> هر هنرجو حداکثر مجاز به ۳ جلسه غیبت در طول دوره است. غيبت بيش از اين تعداد موجب حذف دوره می‌شود و شهريه آن قابل استرداد نيست.</p>
<p>تبصره ۱ - غیبت به دلیل بیماری با ارائه گواهی پزشک ظرف مدت ۷ روز، موجه محسوب می‌شود.</p>
<p>تبصره ۲ - تأخیر بیش از ۲۰ دقیقه، معادل نیم جلسه غیبت در نظر گرفته می‌شود.</p>
""",
    """
<h2>فصل ٣ - ارزشیابی</h2>
<p><b>ماده ٥ - نمره نهایی.</b> نمره نهایی از ۲۰ محاسبه می‌شود: ۴۰ درصد پروژه پایانی، ۳۰ درصد تمرین‌های هفتگی، ۲۰ درصد آزمون میان‌دوره و ۱۰ درصد مشارکت در کلاس. حداقل نمره قبولی ۱۲ است.</p>
<p><b>ماده ٦ - پروژه پایانی.</b> پروژه پایانی باید یک سامانه RAG فارسی کامل باشد که روی دست‌کم ۵ سند PDF ارزیابی شده و معیارهای Hit@5 و MRR آن گزارش شود. مهلت تحويل پروژه ۱۴ روز پس از آخرین جلسه است و تحويل با تأخير تا ۷ روز با کسر ۲ نمره پذيرفته می‌شود.</p>
<p><b>ماده ۷ - آزمون جبرانی.</b> هنرجویانی که نمره آنها بین ۱۰ و ۱۲ باشد، می‌توانند یک بار در آزمون جبرانی شرکت کنند. هزینه آزمون جبرانی ۱٬۵۰۰٬۰۰۰ ریال است.</p>
<h2>فصل ۴ - گواهینامه</h2>
<p><b>ماده ۸ - صدور گواهی.</b> به هنرجویانی که دوره را با موفقیت به پایان برسانند، گواهینامه پایان دوره با امضای مدیر آموزش اعطا می‌شود. گواهی‌ها حداکثر ۳۰ روز پس از اعلام نمرات صادر می‌شوند و از طریق سامانه قابل استعلام هستند.</p>
<p><b>ماده ۹ - اعتبار.</b> گواهینامه فاقد تاریخ انقضا است. هنرجویانی که نمره بالای ۱۸ کسب کنند، گواهی ممتاز دريافت می‌کنند و برای همکاری در پروژه‌های پژوهشی معرفی می‌شوند.</p>
<p><b>ماده ۱۰ - اجرا.</b> این آیین‌نامه در ۱۰ ماده و ۳ تبصره تنظیم شده و مسئولیت اجرای آن بر عهده معاون آموزشی است.</p>
""",
]

CSS = """
@font-face {{ font-family: fa; src: url({font}); }}
* {{ font-family: fa; }}
body {{ direction: rtl; text-align: justify; font-size: 11pt; line-height: 1.7; }}
h1 {{ font-size: 18pt; text-align: center; }}
h2 {{ font-size: 14pt; }}
p {{ margin-bottom: 6pt; }}
"""


def main(font_path: Path | None = None) -> Path:
    font = font_path or next((f for f in FONT_CANDIDATES if f.exists()), None)
    if font is None:
        raise SystemExit("فونت فارسی پیدا نشد؛ مسیر یک فایل TTF را به‌عنوان آرگومان بدهید.")
    archive = fitz.Archive(str(font.parent))
    css = CSS.format(font=font.name)
    doc = fitz.open()
    for i, html in enumerate(PAGES, 1):
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox(fitz.Rect(60, 70, 535, 790), html, css=css, archive=archive)
        # سرصفحه و شماره صفحه تکراری (باید در ایندکس حذف شوند)
        page.insert_htmlbox(fitz.Rect(60, 20, 535, 45), "<p>مؤسسه آموزش عالی نمونه — نسخه آزمایشی</p>",
                            css=css + "p{font-size:8pt;text-align:center}", archive=archive)
        page.insert_htmlbox(fitz.Rect(60, 805, 535, 830), f"<p>صفحه {i}</p>",
                            css=css + "p{font-size:8pt;text-align:center}", archive=archive)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.subset_fonts()  # فقط glyphهای استفاده‌شده؛ حجم فایل از چند مگابایت به چند ده کیلوبایت می‌رسد
    doc.save(str(OUT), garbage=3, deflate=True)
    return OUT


if __name__ == "__main__":
    print(main(Path(sys.argv[1]) if len(sys.argv) > 1 else None))
