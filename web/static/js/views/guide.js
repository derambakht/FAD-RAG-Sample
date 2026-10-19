// راهنمای پروژه: هر چیزی که در پروژه استفاده شده، با نمودار جریان

import { diagram } from "../diagram.js";
import { getSystem } from "../state.js";
import { h, persianize } from "../ui.js";

const SECTIONS = [
  ["overview", "نمای کلی معماری"], ["ingest", "جریان ایندکس‌سازی"], ["clean", "نرمال‌سازی clean_fa"],
  ["chunking", "بخش‌بندی"], ["query", "مرحله پرسش و پاسخ"], ["postprocess", "Rerank و Jev"],
  ["eval", "ارزیابی"], ["stack", "معرفی ابزارها و لینک‌ها"], ["deploy", "استقرار"], ["config", "تنظیمات"],
  ["files", "نقشه فایل‌ها"], ["exercises", "تمرین‌ها"],
];

const table = (head, rows) => h("div", { class: "table-wrap", style: { margin: "8px 0 14px" } }, h("table", {},
  h("thead", {}, h("tr", {}, head.map((x) => h("th", {}, x)))),
  h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))));
const code = (t) => h("code", {}, t);
const sec = (id, n, title, ...children) => h("section", { id }, h("h2", {}, h("span", { class: "n" }, n), title), ...children);

// ---------------------------------------------------------------------------------- معرفی ابزارها
// همه لینک‌ها بررسی شده‌اند (مهر ۱۴۰۵)؛ برای مخزن‌های منتقل‌شده آدرس جدید آمده است.
const GH = "https://github.com/";
const TOOL_GROUPS = [
  ["چارچوب RAG و مدل‌های زبانی", [
    { name: "LangChain", ver: "langchain-core 1.6", what: "چارچوب ساخت برنامه‌های مبتنی بر LLM: رابط یکسان برای مدل‌ها، embedding، vector store، retriever و زنجیره‌ها (LCEL).",
      use: "اتصال یکسان به OpenAI/Ollama/HuggingFace، Chroma و Qdrant؛ زنجیره پرامپت ← LLM ← خروجی؛ PersianRetriever؛ splitter پایه.",
      where: "providers.py · vectorstores.py · chain.py", links: [["GitHub", GH + "langchain-ai/langchain"], ["مستندات", "https://docs.langchain.com"]] },
    { name: "OpenAI Python SDK", ver: "از طریق langchain-openai 1.7", what: "کتابخانه رسمی فراخوانی API شرکت OpenAI.",
      use: "embedding با text-embedding-3-small و پاسخ و Rerank با gpt-4o-mini.", where: "providers.py",
      links: [["GitHub", GH + "openai/openai-python"], ["مدل‌ها", "https://developers.openai.com/api/docs/models"]] },
    { name: "Ollama", ver: "سرور 0.40", what: "اجرای مدل‌های زبانی و embedding متن‌باز به‌صورت لوکال با یک دستور (ollama pull).",
      use: "گزینه کاملاً لوکال راهنما: bge-m3 برای embedding و qwen2.5:7b برای پاسخ. روی سرور CPU فعلی نصب نیست.", where: "providers.py · docker-compose.yml",
      links: [["GitHub", GH + "ollama/ollama"], ["سایت", "https://ollama.com"]] },
    { name: "Hugging Face Transformers", ver: "", what: "کتابخانه مرجع بارگذاری و اجرای مدل‌های ترنسفورمر از Hugging Face Hub.",
      use: "اجرای مدل‌های لوکال روی CPU سرور (از طریق sentence-transformers و LLM لوکال).", where: "providers.py",
      links: [["GitHub", GH + "huggingface/transformers"], ["مستندات", "https://huggingface.co/docs/transformers"]] },
    { name: "Sentence Transformers", ver: "6.1", what: "کتابخانه embedding و cross-encoder روی پایه Transformers (SBERT).",
      use: "embedding لوکال (multilingual-e5) و Rerank با cross-encoder.", where: "providers.py · rag/rerank.py",
      links: [["GitHub", GH + "huggingface/sentence-transformers"], ["مستندات", "https://sbert.net"]] },
    { name: "Hugging Face Hub", ver: "", what: "کلاینت دانلود و کش مدل‌ها از huggingface.co.",
      use: "دانلود و کش مدل‌ها؛ حالت HF_HUB_OFFLINE برای سروری که HuggingFace آن را محدود کرده.", where: "config.py",
      links: [["GitHub", GH + "huggingface/huggingface_hub"]] },
    { name: "PyTorch", ver: "2.14 (CPU)", what: "کتابخانه یادگیری عمیق که مدل‌های Transformers روی آن اجرا می‌شوند.",
      use: "موتور اجرای مدل‌های لوکال؛ نسخه CPU روی سرور.", where: "requirements-hf.txt",
      links: [["GitHub", GH + "pytorch/pytorch"], ["سایت", "https://pytorch.org"]] },
  ]],
  ["مدل‌ها و سرویس‌های تصمیم‌گیری", [
    { name: "text-embedding-3-small و gpt-4o-mini", ver: "OpenAI", what: "مدل embedding (۱۵۳۶ بعدی) و مدل زبانی سبک و ارزان OpenAI.",
      use: "پیش‌فرض پایگاه دانش «OpenAI» و پاسخ‌گویی روی سرور.", where: ".env",
      links: [["مستندات مدل‌ها", "https://developers.openai.com/api/docs/models"]] },
    { name: "multilingual-e5", ver: "small / base", what: "مدل embedding چندزبانه مایکروسافت؛ پرسش با پیشوند query: و متن با passage: کد می‌شوند.",
      use: "پایگاه دانش «e5 لوکال» روی CPU سرور؛ پیشوندها خودکار اضافه می‌شوند.", where: "providers.py (PrefixedEmbeddings)",
      links: [["Hugging Face", "https://huggingface.co/intfloat/multilingual-e5-base"], ["GitHub", GH + "microsoft/unilm"]] },
    { name: "BGE-M3 و bge-reranker-v2-m3", ver: "BAAI", what: "embedding و reranker چندزبانه قوی با پشتیبانی خوب از فارسی (حدود ۲ گیگابایت).",
      use: "گزینه پیشنهادی راهنما برای embedding لوکال (از Ollama یا HuggingFace) و reranker دقیق‌تر روی GPU.", where: ".env",
      links: [["GitHub", GH + "FlagOpen/FlagEmbedding"], ["bge-m3", "https://huggingface.co/BAAI/bge-m3"], ["reranker", "https://huggingface.co/BAAI/bge-reranker-v2-m3"]] },
    { name: "mmarco-mMiniLMv2 cross-encoder", ver: "L12-H384", what: "cross-encoder چندزبانه سبک (حدود ۴۷۰ مگابایت) برای امتیازدهی جفت (پرسش، متن).",
      use: "Rerank لوکال روی CPU سرور؛ در فارسی ضعیف‌تر از Rerank با LLM است.", where: "RERANKER_MODEL",
      links: [["Hugging Face", "https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"]] },
    { name: "Qwen2.5", ver: "7B", what: "مدل زبانی متن‌باز Alibaba با پشتیبانی چندزبانه، پیشنهاد راهنما برای نسخه لوکال.",
      use: "LLM لوکال از طریق Ollama (روی سرور CPU فعلی کند است).", where: ".env",
      links: [["Ollama", "https://ollama.com/library/qwen2.5"], ["Hugging Face", "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct"]] },
    { name: "Jev (TypeSafe AI)", ver: "jev-1.14", what: "مدل تصمیم‌گیری که متن تولید نمی‌کند و به پرسش‌های بله/خیر، انتخابی و درجه‌ای احتمال کالیبره برمی‌گرداند.",
      use: "فیلتر ارتباط متن‌های بازیابی‌شده و بررسی پاسخ‌پذیری پیش از LLM؛ روی سرور از طریق OpenRouter.", where: "rag/jev.py",
      links: [["GitHub SDK", GH + "typesafe-ai/typesafe-sdk-python"], ["مستندات", "https://docs.typesafe.ai"], ["OpenRouter", "https://openrouter.ai/typesafe/jev-1.14"]] },
    { name: "OpenRouter", ver: "", what: "درگاه یکپارچه دسترسی به مدل‌های شرکت‌های مختلف با یک کلید API.",
      use: "مسیر دسترسی به Jev روی سرور؛ با تنظیم JEV_BASE_URL در فایل ‎.env‎.", where: ".env",
      links: [["مستندات", "https://openrouter.ai/docs"], ["راهنمای Jev", "https://openrouter.ai/docs/guides/community/jev"]] },
  ]],
  ["ذخیره‌سازی", [
    { name: "ChromaDB", ver: "1.5", what: "پایگاه داده برداری متن‌باز و سبک؛ بدون سرور جداگانه روی دیسک کار می‌کند.",
      use: "vector store پیش‌فرض اجرای لوکال (پوشه data/chroma) با فاصله کسینوسی.", where: "vectorstores.py",
      links: [["GitHub", GH + "chroma-core/chroma"], ["مستندات", "https://docs.trychroma.com"], ["langchain-chroma", GH + "langchain-ai/langchain/tree/master/libs/partners/chroma"]] },
    { name: "Qdrant", ver: "1.19", what: "پایگاه داده برداری سرور‌محور به زبان Rust با فیلتر payload و API کامل.",
      use: "vector store سرور (باینری روی localhost:6333) و حالت embedded برای توسعه.", where: "vectorstores.py · scripts/server_*.sh",
      links: [["GitHub", GH + "qdrant/qdrant"], ["کلاینت پایتون", GH + "qdrant/qdrant-client"], ["مستندات", "https://qdrant.tech/documentation/"]] },
    { name: "SQLite", ver: "", what: "پایگاه داده رابطه‌ای درون‌فایلی بدون سرور.",
      use: "رجیستری پایگاه‌ها و اسناد، متن chunkها (برای BM25 و audit)، ارزیابی‌ها و جلسه‌های گفتگو.", where: "db.py",
      links: [["سایت", "https://www.sqlite.org"], ["GitHub (آینه)", GH + "sqlite/sqlite"]] },
  ]],
  ["استخراج PDF و پردازش متن فارسی", [
    { name: "PyMuPDF", ver: "1.28", what: "کتابخانه سریع خواندن PDF بر پایه MuPDF: متن با مختصات و فونت، تصویر صفحه.",
      use: "ابزار پیش‌فرض استخراج، تصویر صفحه برای بازبینی chunk، ساخت PDF نمونه.", where: "core/extract.py",
      links: [["GitHub", GH + "pymupdf/PyMuPDF"], ["مستندات", "https://pymupdf.readthedocs.io/en/latest/"]] },
    { name: "pdfplumber", ver: "0.11", what: "استخراج دقیق متن و جدول از PDF با کنترل فاصله کاراکترها.",
      use: "جایگزین خودکار برای صفحات با امتیاز واژگان پایین (بهترین x_tolerance) و استخراج جدول.", where: "core/extract.py",
      links: [["GitHub", GH + "jsvine/pdfplumber"]] },
    { name: "python-docx", ver: "1.2", what: "خواندن و نوشتن فایل‌های Word.",
      use: "استخراج متن، عنوان‌ها و جدول‌های DOCX.", where: "core/extract.py",
      links: [["GitHub", GH + "python-openxml/python-docx"], ["مستندات", "https://python-docx.readthedocs.io/en/latest/"]] },
    { name: "Tesseract OCR و pytesseract", ver: "زبان fas", what: "موتور متن‌باز OCR با بسته زبان فارسی، و رابط پایتون آن.",
      use: "OCR خودکار صفحات اسکن‌شده یا با فونت بدون ToUnicode.", where: "core/extract.py",
      links: [["GitHub", GH + "tesseract-ocr/tesseract"], ["داده زبان‌ها", GH + "tesseract-ocr/tessdata"], ["pytesseract", GH + "madmaze/pytesseract"]] },
    { name: "hazm", ver: "0.12", what: "کتابخانه پردازش زبان فارسی: نرمال‌ساز، جمله‌بندی، ریشه‌یابی، برچسب‌گذاری و فهرست واژگان.",
      use: "نیم‌فاصله و فاصله علائم در clean_fa، جمله‌بندی برای chunk، واژگان برای vocab_score.", where: "core/normalize.py · text_utils.py",
      links: [["GitHub", GH + "roshan-research/hazm"]] },
    { name: "tiktoken", ver: "0.14", what: "توکنایزر سریع BPE مدل‌های OpenAI.",
      use: "سنجش اندازه chunk بر حسب توکن (o200k_base)، نه کاراکتر.", where: "text_utils.py",
      links: [["GitHub", GH + "openai/tiktoken"]] },
    { name: "rank_bm25", ver: "0.2", what: "پیاده‌سازی الگوریتم‌های رتبه‌بندی BM25 در پایتون.",
      use: "بازیابی کلیدواژه‌ای روی متن chunkها در کنار بازیابی برداری.", where: "rag/retrieval.py",
      links: [["GitHub", GH + "dorianbrown/rank_bm25"]] },
    { name: "NumPy", ver: "2.5", what: "کتابخانه محاسبات عددی پایتون.", use: "مرتب‌سازی و فیلتر امتیازهای BM25.", where: "rag/retrieval.py",
      links: [["GitHub", GH + "numpy/numpy"], ["سایت", "https://numpy.org"]] },
  ]],
  ["وب‌سرور و API", [
    { name: "FastAPI", ver: "0.146", what: "چارچوب ساخت API پایتون با اعتبارسنجی خودکار و مستندات تعاملی.",
      use: "همه مسیرهای ‎/api‎، استریم SSE پاسخ‌ها، ورود با رمز، ارائه فایل‌های پنل و ‎/api/docs‎.", where: "app/main.py · app/api/",
      links: [["GitHub", GH + "fastapi/fastapi"], ["مستندات", "https://fastapi.tiangolo.com"]] },
    { name: "Uvicorn", ver: "0.54", what: "سرور ASGI سبک و سریع برای اجرای برنامه‌های FastAPI.",
      use: "اجرای برنامه روی پورت 8000 (لوکال) و 8888 (سرور).", where: "app/__main__.py · server_start.sh",
      links: [["GitHub", GH + "Kludex/uvicorn"]] },
    { name: "Pydantic و pydantic-settings", ver: "2.14 · 2.16", what: "اعتبارسنجی داده با type hint، و خواندن تنظیمات از متغیرهای محیطی و ‎.env‎.",
      use: "اعتبارسنجی بدنه درخواست‌های API و همه تنظیمات ‎.env‎.", where: "api/schemas.py · config.py",
      links: [["GitHub", GH + "pydantic/pydantic"], ["pydantic-settings", GH + "pydantic/pydantic-settings"], ["مستندات", "https://docs.pydantic.dev"]] },
    { name: "HTTPX", ver: "0.28", what: "کلاینت HTTP پایتون با پشتیبانی همگام و ناهمگام.",
      use: "فراخوانی API Jev و بررسی وضعیت Ollama.", where: "rag/jev.py · providers.py",
      links: [["GitHub", GH + "encode/httpx"], ["مستندات", "https://www.python-httpx.org"]] },
  ]],
  ["پنل وب", [
    { name: "marked", ver: "12", what: "مبدل سریع Markdown به HTML در مرورگر.", use: "نمایش قالب‌بندی پاسخ‌های LLM (فهرست، پررنگ، جدول).",
      where: "web/static/vendor", links: [["GitHub", GH + "markedjs/marked"], ["سایت", "https://marked.js.org"]] },
    { name: "DOMPurify", ver: "3.1", what: "پاک‌کننده HTML برای جلوگیری از حمله XSS.", use: "امن‌سازی HTML حاصل از پاسخ LLM پیش از نمایش.",
      where: "web/static/vendor", links: [["GitHub", GH + "cure53/DOMPurify"]] },
    { name: "وزیرمتن (Vazirmatn)", ver: "33", what: "فونت متن‌باز فارسی.", use: "فونت پنل؛ به‌صورت محلی و بدون CDN.",
      where: "web/static/fonts", links: [["GitHub", GH + "rastikerdar/vazirmatn"]] },
  ]],
  ["توسعه، تست و استقرار", [
    { name: "uv", ver: "", what: "مدیر بسته و محیط پایتون بسیار سریع به زبان Rust.", use: "نصب Python 3.12 و وابستگی‌ها روی سرور RunPod.",
      where: "scripts/server_install.sh", links: [["GitHub", GH + "astral-sh/uv"], ["مستندات", "https://docs.astral.sh/uv/"]] },
    { name: "pytest", ver: "9.1", what: "چارچوب تست پایتون.", use: "تست‌های واحد و جریان کامل API روی Chroma و Qdrant بدون کلید و GPU.",
      where: "tests/", links: [["GitHub", GH + "pytest-dev/pytest"], ["مستندات", "https://docs.pytest.org/en/stable/"]] },
    { name: "Playwright", ver: "1.64", what: "کنترل خودکار مرورگر برای تست رابط کاربری.", use: "تست پنل در مرورگر واقعی و گرفتن تصویر صفحه‌ها.",
      where: "تست‌های توسعه", links: [["GitHub", GH + "microsoft/playwright-python"], ["مستندات", "https://playwright.dev/python/"]] },
    { name: "Docker Compose", ver: "", what: "اجرای چند سرویس کانتینری با یک فایل تعریف.", use: "استقرار برنامه + Qdrant + Ollama اختیاری روی سرورهای دارای Docker.",
      where: "Dockerfile · docker-compose.yml", links: [["GitHub", GH + "docker/compose"], ["مستندات", "https://docs.docker.com/compose/"]] },
    { name: "RunPod", ver: "", what: "سرویس ابری اجاره سرور GPU و CPU به‌صورت کانتینر.", use: "میزبان فعلی سایت (pod با ۲ CPU و ۸ گیگ حافظه).",
      where: "scripts/server_*.sh", links: [["مستندات", "https://docs.runpod.io"], ["runpodctl", GH + "runpod/runpodctl"]] },
  ]],
];

function toolsSection() {
  return TOOL_GROUPS.map(([group, tools]) => h("div", {},
    h("h3", {}, group),
    h("div", { class: "grid grid-2", style: { gap: "12px" } }, tools.map((t) => h("div", { class: "tool-card" },
      h("div", { class: "row", style: { gap: "8px" } }, h("b", { class: "tool-name" }, t.name),
        t.ver ? h("span", { class: "badge ltr" }, t.ver) : null),
      h("p", {}, t.what),
      h("p", { class: "small" }, h("b", {}, "در این پروژه: "), t.use),
      h("div", { class: "tiny muted" }, "کجا: ", h("span", { class: "ltr" }, t.where)),
      h("div", { class: "tool-links" }, t.links.map(([label, url]) =>
        h("a", { href: url, target: "_blank", rel: "noopener noreferrer", title: url }, label))))))));
}

// ---------------------------------------------------------------------------------- نمودارها
function archDiagram() {
  const mods = [["ingest", "ایندکس‌سازی", "ingest.py · extract · chunking", 670], ["ret", "بازیابی", "retrieval.py · BM25 · RRF", 460],
    ["chain", "پاسخ‌گویی", "chain.py · LCEL · Rerank · Jev", 250], ["ev", "ارزیابی", "evaluation.py · Hit@k · MRR", 40]];
  return diagram({
    width: 900, height: 470, label: "معماری: پنل وب، FastAPI، چهار ماژول اصلی، ذخیره‌سازی و ارائه‌دهنده‌های مدل",
    nodes: [
      { id: "web", x: 340, y: 14, w: 220, h: 58, t: "مرورگر — پنل فارسی", s: ["صفحات راست‌به‌چپ، بدون build"] },
      { id: "api", x: 200, y: 108, w: 500, h: 60, kind: "hot", t: "FastAPI + uvicorn", s: ["ورود با رمز · مسیرهای API · استریم SSE · کارهای پس‌زمینه"] },
      ...mods.map(([id, t, s, x]) => ({ id, x, y: 210, w: 190, h: 62, t, s: [s] })),
      { id: "store", x: 470, y: 318, w: 410, h: 136, kind: "group", t: "ذخیره‌سازی" },
      { id: "sql", x: 750, y: 350, w: 125, h: 64, kind: "store", t: "SQLite", s: ["متن و metadata"] },
      { id: "vec", x: 615, y: 350, w: 125, h: 64, kind: "store", t: "Chroma / Qdrant", s: ["بردارها"] },
      { id: "files", x: 480, y: 350, w: 125, h: 64, kind: "store", t: "پوشه data", s: ["فایل‌ها · کش مدل"] },
      { id: "prov", x: 20, y: 318, w: 430, h: 136, kind: "group", t: "ارائه‌دهنده‌های مدل" },
      { id: "oai", x: 342, y: 350, w: 98, h: 64, kind: "ext", t: "OpenAI", s: ["embedding · LLM"] },
      { id: "oll", x: 238, y: 350, w: 98, h: 64, kind: "ext", t: "Ollama", s: ["لوکال"] },
      { id: "hf", x: 134, y: 350, w: 98, h: 64, kind: "ext", t: "HuggingFace", s: ["e5 · reranker"] },
      { id: "jev", x: 30, y: 350, w: 98, h: 64, kind: "ext", t: "Jev", s: ["TypeSafe AI"] },
    ],
    edges: [
      { from: "web", to: "api", label: "HTTPS: fetch و SSE" },
      ...mods.map(([id]) => ({ from: "api", to: id, midY: 190 })),
      { from: "ingest", to: "store", points: [[765, 272], [765, 318]], label: "می‌نویسد" },
      { from: "ret", to: "store", points: [[555, 272], [555, 318]], label: "می‌خواند" },
      { from: "chain", to: "prov", points: [[345, 272], [345, 318]], label: "LLM · Rerank · Jev" },
      { from: "ev", to: "prov", points: [[135, 272], [135, 318]], label: "تولید پرسش" },
    ],
    caption: "پنل فقط با API صحبت می‌کند. متن chunkها در SQLite و بردارها در Chroma یا Qdrant ذخیره می‌شوند؛ ارائه‌دهنده مدل برای هر پایگاه دانش و هر گفتگو جداگانه انتخاب می‌شود.",
  });
}

function ingestDiagram() {
  return diagram({
    width: 880, height: 840, label: "جریان ایندکس‌سازی از بارگذاری فایل تا ذخیره متن در SQLite و بردار در Chroma یا Qdrant",
    nodes: [
      { id: "up", x: 330, y: 14, w: 220, h: 72, t: "بارگذاری فایل", s: ["PDF · DOCX · TXT · MD", "هش SHA-256 ← حذف تکراری"] },
      { id: "pym", x: 330, y: 132, w: 220, h: 72, t: "استخراج با PyMuPDF", s: ["خط، اندازه فونت، bold", "حذف نوار سرصفحه/پاورقی"] },
      { id: "ocr", x: 630, y: 132, w: 230, h: 72, kind: "warn", t: "OCR با Tesseract (fas)", s: ["صفحه اسکن‌شده یا", "فونت بدون ToUnicode"] },
      { id: "plb", x: 20, y: 132, w: 230, h: 72, kind: "warn", t: "pdfplumber", s: ["بهترین x_tolerance", "با امتیاز واژگان hazm"] },
      { id: "pre", x: 270, y: 262, w: 340, h: 72, t: "پاک‌سازی سطح خط", s: ["pre_clean · اصلاح جهت معکوس در سطح صفحه", "حذف سرصفحه تکراری و شماره صفحه"] },
      { id: "par", x: 270, y: 384, w: 340, h: 72, t: "خطوط ← پاراگراف", s: ["تشخیص عنوان: regex فصل/ماده + اندازه فونت", "تبصره کنار ماده خودش می‌ماند"] },
      { id: "cl", x: 270, y: 506, w: 340, h: 64, kind: "hot", t: "clean_fa", s: ["NFKC، حروف عربی، اعراب، ارقام، نیم‌فاصله"] },
      { id: "ch", x: 270, y: 620, w: 340, h: 72, t: "بخش‌بندی", s: ["ساختار ← جمله ← بودجه توکن (tiktoken)", "جدول‌ها به markdown · روش‌های پایه برای مقایسه"] },
      { id: "sql", x: 470, y: 750, w: 270, h: 72, kind: "store", t: "SQLite", s: ["متن chunk + فایل/صفحه/بخش", "← BM25، audit و ارزیابی"] },
      { id: "vec", x: 140, y: 750, w: 270, h: 72, kind: "store", t: "Embedding ← Chroma / Qdrant", s: ["OpenAI · Ollama · HuggingFace", "یک collection برای هر مدل"] },
    ],
    edges: [
      { from: "up", to: "pym" },
      { from: "pym", to: "ocr", route: "h", label: "متن خراب/خالی" },
      { from: "pym", to: "plb", route: "h", label: "واژگان < ۰٫۵۵" },
      { from: "pym", to: "pre", label: "متن سالم" },
      { from: "ocr", to: "pre", points: [[745, 204], [745, 298], [610, 298]] },
      { from: "plb", to: "pre", points: [[135, 204], [135, 298], [270, 298]] },
      { from: "pre", to: "par" }, { from: "par", to: "cl" }, { from: "cl", to: "ch" },
      { from: "ch", to: "sql", tx: 605, label: "متن" }, { from: "ch", to: "vec", tx: 275, label: "بردار" },
    ],
    caption: "انتخاب ابزار استخراج برای هر صفحه جداگانه و خودکار است (حالت auto). پاک‌سازی دو مرحله دارد: پاک‌سازی سبک روی تک‌خط‌ها برای تشخیص جهت، و clean_fa کامل روی پاراگراف‌ها.",
  });
}

function cleanDiagram() {
  const steps = [
    ["NFKC و کشیده", ["ﻫﻮﺵ ← هوش", "اـــیران ← ایران"]], ["حروف عربی", ["ي ك ة ← ی ک ه"]], ["حذف اعراب", ["عِلْم ← علم"]],
    ["«» و () وارونه", ["» هنرجو « ← «هنرجو»"]], ["ارقام و کنترل جهت", ["۱۲٬۵۰۰٫۷۵ ← 12500.75"]],
    ["نیم‌فاصله با hazm", ["می شود ← می‌شود"]], ["اصلاح نهایی", ["تاریخ و درصد بدون فاصله"]],
  ];
  const xs = [690, 470, 250, 30];
  const nodes = steps.map(([t, s], i) => ({ id: `s${i}`, x: xs[i % 4], y: i < 4 ? 14 : 140, w: 190, h: 72,
    kind: i === 6 ? "hot" : "", t: `${"۱۲۳۴۵۶۷"[i]}. ${t}`, s }));
  const edges = steps.slice(1).map((_, i) => (i === 3
    ? { from: "s3", to: "s4", points: [[125, 86], [125, 113], [785, 113], [785, 140]] }
    : { from: `s${i}`, to: `s${i + 1}`, route: "h" }));
  return diagram({ width: 900, height: 230, nodes, edges, label: "هفت مرحله clean_fa به ترتیب اجرا",
    caption: "ترتیب مهم است: ارقام پیش از hazm یکسان می‌شوند تا hazm اعداد را نشکند. همین تابع روی پرسش کاربر هم اجرا می‌شود؛ وگرنه «ماده ۱۲» با «ماده 12» جور نمی‌شود." });
}

function queryDiagram() {
  const c = (id, y, hh, t, s, kind) => ({ id, x: 420, y, w: 220, h: hh, t, s, kind });
  return diagram({
    width: 760, height: 1050, label: "مرحله پرسش و پاسخ با مراحل اختیاری Rerank و Jev",
    nodes: [
      c("q", 14, 60, "پرسش کاربر", ["مثلاً: «حداقل نمره قبولي چند است؟»"]),
      c("cl", 110, 60, "clean_fa روی پرسش", ["همان تابع اسناد: ي ← ی، ۱۲ ← 12"], "hot"),
      c("rw", 206, 60, "بازنویسی پرسش پیگیری", ["اختیاری · با تاریخچه گفتگو"], "opt"),
      { id: "den", x: 535, y: 304, w: 205, h: 62, t: "بازیابی برداری", s: ["embedding پرسش ← Chroma/Qdrant"] },
      { id: "bm", x: 310, y: 304, w: 205, h: 62, t: "BM25", s: ["rank_bm25 روی متن SQLite"] },
      c("rrf", 404, 60, "ادغام RRF", ["۲۰ کاندید (fetch_k)"]),
      c("rr", 500, 68, "Rerank", ["اختیاری · LLM یا Cross-encoder", "فقط ترتیب عوض می‌شود"], "opt"),
      c("jf", 604, 68, "Jev: فیلتر ارتباط", ["اختیاری · P(مرتبط) برای هر متن", "زیر آستانه حذف می‌شود"], "opt"),
      c("tk", 708, 56, "k متن برتر", ["پیش‌فرض ۵"]),
      c("ja", 800, 62, "Jev: بررسی پاسخ‌پذیری", ["اختیاری · شواهد کافی است؟"], "opt"),
      { id: "nf", x: 60, y: 800, w: 250, h: 62, kind: "warn", t: "«پاسخ در اسناد موجود نیست»", s: ["LLM فراخوانی نمی‌شود"] },
      c("llm", 898, 60, "پرامپت فارسی + LLM", ["LangChain LCEL · استریم توکن"]),
      c("ans", 990, 56, "پاسخ با ارجاع [n]", ["SSE: sources ← token ← done"], "hot"),
    ],
    edges: [
      { from: "q", to: "cl" }, { from: "cl", to: "rw", opt: true },
      { from: "rw", to: "den", sx: 580, midY: 285 }, { from: "rw", to: "bm", sx: 480, midY: 285 },
      { from: "den", to: "rrf", tx: 580, label: "رتبه‌ها" }, { from: "bm", to: "rrf", tx: 480, label: "رتبه‌ها" },
      { from: "rrf", to: "rr" }, { from: "rr", to: "jf", label: "ترتیب جدید" },
      { from: "jf", to: "tk", label: "متن‌های مرتبط" }, { from: "tk", to: "ja" },
      { from: "ja", to: "nf", route: "h", label: "کافی نیست" }, { from: "ja", to: "llm", label: "کافی است" },
      { from: "llm", to: "ans" },
    ],
    notes: [
      { x: 200, y: 140, text: "یکسان‌سازی پرسش با متن ایندکس‌شده" },
      { x: 200, y: 438, text: "امتیاز هر متن = مجموع 1/(60 + رتبه)" },
      { x: 200, y: 530, text: "LLM: امتیاز ۰ تا ۱۰ در یک فراخوانی" },
      { x: 200, y: 548, text: "Cross-encoder: مدل لوکال روی جفت (پرسش، متن)" },
      { x: 200, y: 634, text: "یک درخواست برای همه کاندیدها" },
      { x: 200, y: 652, text: "خروجی: احتمال کالیبره، نه متن" },
    ],
    caption: "کادرهای خط‌چین مراحلی هستند که در پنل روشن یا خاموش می‌شوند؛ وقتی خاموش‌اند، داده بدون تغییر از آنها عبور می‌کند. Rerank فقط ترتیب را عوض می‌کند، اما Jev می‌تواند متن‌ها را حذف کند و حتی جلوی فراخوانی LLM را بگیرد.",
  });
}

function evalDiagram() {
  return diagram({
    width: 900, height: 290, label: "جریان ارزیابی از تولید پرسش تا محاسبه Hit@k و MRR",
    nodes: [
      { id: "ch", x: 660, y: 14, w: 220, h: 66, t: "chunkهای پایگاه مرجع", s: ["نمونه تصادفی با seed"] },
      { id: "qg", x: 400, y: 14, w: 220, h: 66, t: "تولید پرسش", s: ["QGEN با LLM یا دستی", "+ chunk طلایی"] },
      { id: "set", x: 140, y: 14, w: 220, h: 66, t: "مجموعه ارزیابی", s: ["پرسش + متن طلایی"] },
      { id: "cfg", x: 20, y: 180, w: 200, h: 72, t: "پیکربندی‌ها", s: ["پایگاه × روش بازیابی", "× Rerank × Jev × clean_fa"] },
      { id: "sr", x: 240, y: 180, w: 200, h: 72, t: "جستجو برای هر پرسش", s: ["همان مرحله پرسش گفتگو"] },
      { id: "mt", x: 460, y: 180, w: 200, h: 72, t: "تطبیق با طلایی", s: ["شناسه chunk یا", "همپوشانی کلمات ≥ ۶۰٪"] },
      { id: "mx", x: 680, y: 180, w: 200, h: 72, kind: "hot", t: "Hit@k و MRR", s: ["نمودار + پرسش‌های ناموفق"] },
    ],
    edges: [
      { from: "ch", to: "qg", route: "h" }, { from: "qg", to: "set", route: "h" },
      { from: "set", to: "cfg", sx: 200, tx: 120 },
      { from: "cfg", to: "sr", route: "h" }, { from: "sr", to: "mt", route: "h" }, { from: "mt", to: "mx", route: "h" },
    ],
    caption: "هر پیکربندی روی همه پرسش‌ها اجرا می‌شود. تطبیق متنی اجازه می‌دهد پایگاه‌هایی با chunkبندی متفاوت (مثلاً ۲۰۰ و ۸۰۰ توکن) با یک مجموعه پرسش مقایسه شوند.",
  });
}

function deployDiagram() {
  return diagram({
    width: 900, height: 330, label: "استقرار روی RunPod: پراکسی HTTPS، برنامه روی پورت 8888، Qdrant روی localhost",
    nodes: [
      { id: "br", x: 680, y: 50, w: 200, h: 64, t: "مرورگر کاربر", s: ["فرم ورود (Basic Auth)"] },
      { id: "px", x: 450, y: 50, w: 200, h: 64, kind: "ext", t: "پراکسی RunPod", s: ["HTTPS ← پورت 8888"] },
      { id: "pod", x: 20, y: 10, w: 400, h: 300, kind: "group", t: "pod: کانتینر Ubuntu · ۲ CPU · ۸ گیگ" },
      { id: "app", x: 200, y: 50, w: 200, h: 64, kind: "hot", t: "uvicorn + FastAPI", s: ["0.0.0.0:8888 · Python 3.12"] },
      { id: "qd", x: 200, y: 170, w: 200, h: 64, kind: "store", t: "Qdrant (باینری)", s: ["فقط 127.0.0.1:6333"] },
      { id: "dt", x: 40, y: 170, w: 140, h: 64, kind: "store", t: "پوشه data", s: ["SQLite · فایل‌ها · کش HF"] },
      { id: "oai", x: 680, y: 220, w: 200, h: 64, kind: "ext", t: "OpenAI API", s: ["embedding · gpt-4o-mini"] },
      { id: "jv", x: 450, y: 220, w: 200, h: 64, kind: "ext", t: "Jev API", s: ["TypeSafe · اختیاری"] },
    ],
    edges: [
      { from: "br", to: "px", route: "h", label: "HTTPS" }, { from: "px", to: "app", route: "h", label: "8888" },
      { from: "app", to: "qd", label: "HTTP محلی" },
      { from: "app", to: "dt", points: [[200, 98], [110, 98], [110, 170]], label: "فایل" },
      // خط خروجی زیر ردیف پراکسی عبور می‌کند تا از روی کادرها رد نشود
      { from: "app", to: "oai", points: [[400, 104], [420, 104], [420, 160], [780, 160], [780, 220]], label: "خروجی HTTPS",
        labelAt: { x: 665, y: 153 } },
      { from: "app", to: "jv", points: [[550, 160], [550, 220]], opt: true, labelAt: { x: 543, y: 196, anchor: "start" }, label: "اختیاری" },
    ],
    caption: "فقط برنامه از بیرون در دسترس است و Qdrant به localhost محدود است. اسکریپت server_start.sh هر دو را اجرا می‌کند و اسکریپت post_start.sh رانپاد آن را پس از روشن شدن pod خودکار فراخوانی می‌کند.",
  });
}

// ---------------------------------------------------------------------------------- صفحه
export async function render(root) {
  const sys = await getSystem();
  const toc = h("nav", { class: "guide-toc card", "aria-label": "فهرست راهنما" },
    h("b", { class: "small" }, "فهرست"), SECTIONS.map(([id, t], i) => h("a", { href: "#/guide", onclick: (e) => {
      e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
    } }, `${(i + 1).toLocaleString("fa-IR")}. ${t}`)));

  const main = h("div", {},
    sec("overview", "۱", "نمای کلی معماری",
      h("p", {}, "این پروژه پیاده‌سازی کامل «راهنمای ساخت RAG فارسی از روی PDF» است. پیام اصلی آن راهنما در طراحی رعایت شده: در RAG فارسی بیشتر خطاها از استخراج و پاک‌سازی متن می‌آیند، نه از انتخاب مدل. به همین دلیل هر مرحله جداگانه قابل مشاهده، تنظیم و سنجش است."),
      archDiagram(),
      table(["صفحه پنل", "کاربرد"], [
        ["گفتگو با اسناد", "پرسش و پاسخ استریم‌شده با ارجاع [n]؛ روشن/خاموش کردن Rerank و Jev؛ نوار مراحل زیر هر پاسخ"],
        ["پایگاه‌های دانش", "ساخت پایگاه (مدل embedding، Chroma یا Qdrant، تنظیمات استخراج و بخش‌بندی)، بارگذاری و ایندکس مجدد"],
        ["آزمون بازیابی", "یک پرسش، سه ستون: برداری، BM25، ترکیبی — با یا بدون Rerank و Jev، بدون LLM"],
        ["بررسی chunkها", "audit خودکار، هیستوگرام توکن، بازبینی chunk کنار تصویر صفحه PDF"],
        ["ارزیابی Hit@k و MRR", "مقایسه کمّی پیکربندی‌ها روی یک مجموعه پرسش"],
        ["آزمایشگاه متن", "clean_fa گام‌به‌گام، مقایسه ابزارهای استخراج، پیش‌نمایش chunkبندی"],
        ["وضعیت سیستم", "اتصال مدل‌ها، پایگاه‌های داده، OCR، Rerank، Jev و کارهای پس‌زمینه"],
      ])),

    sec("ingest", "۲", "جریان ایندکس‌سازی",
      h("p", {}, "هر فایل در یک کار پس‌زمینه (jobs.py) پردازش می‌شود و پیشرفت آن زنده در صفحه پایگاه دانش نمایش داده می‌شود. اگر embedding در میانه کار شکست بخورد، chunkها و بردارهای ناقص برگردانده می‌شوند."),
      ingestDiagram(),
      table(["مرحله", "ابزار", "جزئیات"], [
        ["تشخیص متن خراب", code("looks_broken"), "نسبت کاراکترهای mojibake (Çáã) و Private Use به حروف فارسی"],
        ["امتیاز واژگان", code("vocab_score"), "نسبت کلمات موجود در واژگان ۱۹۳ هزارتایی hazm؛ با حذف پسوندها"],
        ["جهت خط", code("_fix_page_direction"), "اگر ۶۰٪ خطوط صفحه با معکوس شدن امتیاز بهتری بگیرند، کل صفحه معکوس و اعداد/لاتین دوباره برگردانده می‌شوند"],
        ["سرصفحه تکراری", code("remove_repeated_lines"), "خطی که (با نادیده گرفتن اعداد) در نیمی از صفحات تکرار شده"],
        ["تشخیص عنوان", code("heading_level"), "regex فصل/بخش/ماده/مبحث، شماره‌گذاری 1.2، اندازه فونت ≥ ۱٫۱۵ برابر متن، bold؛ «فصل 1» و «کلیات» در دو خط ادغام می‌شوند"],
      ])),

    sec("clean", "۳", "نرمال‌سازی clean_fa",
      cleanDiagram(),
      h("p", {}, "پیاده‌سازی در ", code("app/core/normalize.py"), ". گام‌به‌گام آن را در «آزمایشگاه متن» ببینید. نیم‌فاصله‌ها با ", code("hazm.Normalizer"), " اصلاح می‌شوند و اگر hazm نصب نباشد، قواعد جایگزین ساده اجرا می‌شوند.")),

    sec("chunking", "۴", "بخش‌بندی",
      table(["روش", "کار", "کاربرد"], [
        ["ساختار + جمله + توکن (پیش‌فرض)", "مرز بخش شکسته نمی‌شود؛ جمله‌ها با hazm؛ سقف با توکنایزر o200k؛ همپوشانی یک جمله؛ مسیر عنوان داخل متن chunk", "روش اصلی"],
        ["Recursive فارسی", "RecursiveCharacterTextSplitter از LangChain با جداکننده‌های . ؟ ! ؛ ، و طول بر حسب توکن", "مقایسه"],
        ["برش ثابت کاراکتری", "بدون توجه به کلمه و جمله", "خط پایه بد برای تمرین"],
      ]),
      h("ul", {},
        h("li", {}, "عنوان بخش (مثل ", code("فصل 3 - ارزشیابی › ماده 5"), ") داخل متن chunk قرار می‌گیرد تا جمله‌ای مثل «مهلت آن ۱۴ روز است» قابل بازیابی باشد."),
        h("li", {}, "جمله خیلی بلند ابتدا روی «؛» و «،» و سپس روی کلمات شکسته می‌شود."),
        h("li", {}, "جدول‌ها (اختیاری) کامل به markdown تبدیل و اگر بزرگ باشند بر اساس سطر با تکرار سطر عنوان شکسته می‌شوند."))),

    sec("query", "۵", "مرحله پرسش و پاسخ",
      queryDiagram(),
      h("h3", {}, "ادغام RRF"),
      h("div", { class: "formula" }, "RRF(d) = Σ  1 / (60 + rank_i(d))"),
      h("p", {}, "BM25 اسامی، شماره ماده و اصطلاحات دقیق را بهتر پیدا می‌کند و جستجوی برداری هم‌معنی‌ها را؛ RRF فقط از رتبه‌ها استفاده می‌کند و به مقیاس امتیازها حساس نیست."),
      h("h3", {}, "پرامپت و استریم"),
      h("p", {}, "زنجیره با LCEL ساخته شده (", code("ChatPromptTemplate | llm | StrOutputParser"), "). متن‌ها با سرعنوان «[n] منبع: فایل، صفحه، بخش» به LLM داده می‌شوند و پاسخ با رویدادهای SSE به پنل می‌رسد: ", code("sources"), " (منابع و مراحل)، ", code("token"), " و ", code("done"), ". کلاس ", code("PersianRetriever"), " همین بازیابی را به‌صورت Retriever استاندارد LangChain در اختیار نوت‌بوک‌ها می‌گذارد.")),

    sec("postprocess", "۶", "Rerank و Jev: مرحله پس از بازیابی",
      h("p", {}, "هر دو روی کاندیدهای بازیابی (۲۰ متن) کار می‌کنند و در صفحه گفتگو (بخش «مرحله پس از بازیابی»)، آزمون بازیابی و ارزیابی قابل روشن و خاموش کردن‌اند. بازیابی اولیه سقف کیفیت را تعیین می‌کند: متنی که در کاندیدها نباشد با هیچ‌کدام برنمی‌گردد."),
      table(["", "Rerank با LLM", "Rerank با Cross-encoder", "Jev"], [
        ["چه می‌کند", "امتیاز ۰ تا ۱۰ برای هر متن در یک فراخوانی", "امتیاز مدل لوکال برای هر جفت (پرسش، متن)", "احتمال کالیبره «این متن واقعاً پاسخ می‌دهد»"],
        ["اثر روی فهرست", "فقط ترتیب", "فقط ترتیب", "ترتیب + حذف زیر آستانه + توقف پیش از LLM"],
        ["هزینه و سرعت", "یک فراخوانی LLM (چند صدم سنت)", "رایگان؛ روی CPU کند", "$0.042 برای هر میلیون توکن ورودی؛ حدود ۱۰۰ms"],
        ["تنظیم", code("RERANK_LLM_PROVIDER/MODEL"), code("RERANKER_MODEL"), code("TYPESAFE_API_KEY · JEV_THRESHOLD")],
        ["وضعیت این سرور", sys.postprocess.rerank.llm.available ? "فعال" : "غیرفعال",
          sys.postprocess.rerank.cross_encoder.available ? "فعال" : "غیرفعال (مدل تنظیم نشده)",
          sys.postprocess.jev.available ? "فعال" : "غیرفعال (کلید تنظیم نشده)"],
      ]),
      h("h3", {}, "Jev چیست؟"),
      h("p", {}, "Jev مدل تصمیم‌گیری شرکت TypeSafe AI است؛ متن تولید نمی‌کند و به پرسش‌های ساختاریافته پاسخ احتمالاتی می‌دهد. سه نوع پرسش دارد: Noul (بله/خیر)، Choice (انتخاب از گزینه‌ها) و Score (درجه‌بندی). این پروژه از Noul در دو جا استفاده می‌کند:"),
      h("ol", {},
        h("li", {}, h("b", {}, "فیلتر ارتباط: "), "برای هر کاندید یک پرسش Noul «آیا این متن مستقیماً به پرسش پاسخ می‌دهد؟ (اشتراک کلمه کافی نیست)» در یک درخواست ارسال می‌شود. متن‌ها بر اساس احتمال مرتب و زیر آستانه (پیش‌فرض ۰٫۳۵، قابل تنظیم در پنل) حذف می‌شوند."),
        h("li", {}, h("b", {}, "بررسی پاسخ‌پذیری: "), "«آیا این متن‌ها روی‌هم برای پاسخ کافی‌اند؟» اگر احتمال زیر ۰٫۵ باشد، LLM فراخوانی نمی‌شود و پاسخ «در اسناد موجود نیست» برمی‌گردد: صرفه‌جویی در هزینه و جلوگیری از پاسخ ساختگی.")),
      h("div", { class: "formula" }, "POST {JEV_BASE_URL}/v1/systemone   {model, state: {question}, questions: {p0: {type: \"noul\", instructions}}}"),
      h("p", { class: "small muted" }, "کلید را از TypeSafe بگیرید، یا با کلید OpenRouter: JEV_BASE_URL=https://openrouter.ai/api و JEV_MODEL=typesafe/jev-1.14. پاسخ Jev در هر کارت منبع به‌صورت «Jev ٪» و تعداد متن‌های حذف‌شده در نوار مراحل زیر پاسخ نمایش داده می‌شود.")),

    sec("eval", "۷", "ارزیابی",
      evalDiagram(),
      h("div", { class: "formula" }, "Hit@k = (پرسش‌هایی که chunk درست در k نتیجه اول آنهاست) / (همه پرسش‌ها)"),
      h("div", { class: "formula" }, "MRR = میانگین 1 / rank اولین نتیجه درست   (اگر نبود: 0)"),
      h("p", {}, "تطبیق متنی با ضریب همپوشانی |A∩B| / min(|A|,|B|) روی کلمات نرمال‌شده انجام می‌شود. audit لایه اول بدون مدل اجرا می‌شود و این نشانه‌ها را دارد: توکن کمتر از ۵۰، امتیاز واژگان کمتر از ۰٫۶، کاراکتر نرمال‌نشده (شکل نمایشی، کشیده، ي/ك)، پایان نیمه‌کاره جمله، و chunk تکراری."),
      h("p", { class: "alert warn small" }, "پرسش‌های مصنوعی معمولاً واژه‌های chunk را تکرار می‌کنند و نتیجه را خوش‌بینانه نشان می‌دهند؛ ۱۰ تا ۲۰ پرسش دست‌نویس واقعی هم اضافه کنید.")),

    sec("stack", "۸", "معرفی ابزارها و لینک‌ها",
      h("p", {}, "هر ابزار و مدلی که در پروژه استفاده شده: چیست، چه نقشی در این پروژه دارد، در کدام فایل استفاده می‌شود و لینک مخزن GitHub و مستندات آن. نسخه‌ها همان نسخه‌های نصب‌شده روی سرور هستند."),
      toolsSection()),

    sec("deploy", "۹", "استقرار",
      deployDiagram(),
      table(["حالت", "دستور"], [
        ["لوکال", code("python -m app")],
        ["Docker (برنامه + Qdrant + Ollama اختیاری)", code("docker compose up -d --build")],
        ["سرور بدون Docker (مثل RunPod)", code("bash scripts/server_install.sh && bash scripts/server_start.sh")],
        ["خط فرمان", code("python -m app.cli ask \"نام پایگاه\" \"پرسش\"")],
      ])),

    sec("config", "۱۰", "تنظیمات فایل .env",
      table(["متغیر", "کاربرد"], [
        [code("OPENAI_API_KEY · OPENAI_BASE_URL"), "OpenAI یا سرویس سازگار"],
        [code("OLLAMA_BASE_URL · HF_DEVICE · HF_TOKEN · HF_HUB_OFFLINE"), "مدل‌های لوکال"],
        [code("VECTOR_STORE · QDRANT_URL · CHROMA_HOST"), "پایگاه داده برداری پیش‌فرض"],
        [code("DEFAULT_EMBEDDING_* · DEFAULT_LLM_*"), "مدل‌های پیش‌فرض پنل"],
        [code("RERANKER_MODEL · RERANK_LLM_PROVIDER · RERANK_LLM_MODEL"), "Rerank"],
        [code("TYPESAFE_API_KEY · JEV_BASE_URL · JEV_MODEL · JEV_THRESHOLD · JEV_ANSWERABLE_THRESHOLD"), "Jev"],
        [code("APP_USERNAME · APP_PASSWORD"), "ورود به پنل روی سرور عمومی"],
        [code("TESSERACT_CMD · OCR_LANG"), "OCR"],
      ])),

    sec("files", "۱۱", "نقشه فایل‌ها",
      table(["فایل", "مسئولیت"], [
        [code("app/core/normalize.py"), "clean_fa و همه مراحل نرمال‌سازی"],
        [code("app/core/extract.py"), "استخراج، جهت خط، سرصفحه تکراری، OCR، مقایسه ابزارها"],
        [code("app/core/chunking.py"), "پاراگراف‌سازی، تشخیص عنوان، chunk_fa و روش‌های پایه"],
        [code("app/rag/ingest.py"), "جریان ایندکس‌سازی و پیش‌نمایش"],
        [code("app/rag/retrieval.py"), "برداری، BM25، RRF و مراحل Rerank/Jev"],
        [code("app/rag/rerank.py"), "Rerank با LLM و cross-encoder"],
        [code("app/rag/jev.py"), "کلاینت Jev: فیلتر ارتباط و پاسخ‌پذیری"],
        [code("app/rag/chain.py"), "پرامپت، LCEL و استریم SSE"],
        [code("app/rag/evaluation.py"), "audit، تولید پرسش، Hit@k و MRR"],
        [code("web/static/js/"), "پنل؛ هر صفحه در views/ و نمودارها در diagram.js"],
      ])),

    sec("exercises", "۱۲", "تمرین‌ها",
      h("ol", {},
        h("li", {}, "در آزمایشگاه متن، سه ابزار استخراج را روی یک PDF justify‌شده مقایسه کنید."),
        h("li", {}, "سه پایگاه دانش با max_tokens برابر ۲۰۰، ۴۰۰ و ۸۰۰ بسازید و در ارزیابی Hit@5 آنها را مقایسه کنید."),
        h("li", {}, "پرسشی با ارقام فارسی و «ي» عربی را با و بدون clean_fa ارزیابی کنید (گزینه «هر دو»)."),
        h("li", {}, h("b", {}, "Rerank: "), "در ارزیابی «بدون Rerank» و «Rerank با LLM» را با هم اجرا کنید. MRR معمولاً بیشتر از Hit@k تغییر می‌کند؛ چرا؟"),
        h("li", {}, h("b", {}, "Jev: "), "در آزمون بازیابی، Jev را با آستانه‌های ۰٫۲، ۰٫۵ و ۰٫۸ اجرا کنید و تعداد متن‌های حذف‌شده را ببینید. پرسشی بپرسید که پاسخش در اسناد نیست و ببینید Jev جلوی فراخوانی LLM را می‌گیرد یا نه."),
        h("li", {}, "بدترین پرسش‌های ارزیابی را در «آزمون بازیابی» باز کنید و علت را در «بررسی chunkها» پیدا کنید."))),
  );

  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "راهنمای پروژه"),
    h("p", {}, "همه اجزای پروژه، از استخراج PDF تا پاسخ و ارزیابی، با نمودار جریان."))),
  persianize(h("div", { class: "guide" }, main, toc)));
}
