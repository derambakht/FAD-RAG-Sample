// وضعیت سیستم: ارائه‌دهنده‌های مدل، پایگاه‌های داده برداری، OCR و کارهای پس‌زمینه

import { get, post } from "../api.js";
import { getSystem, loadingBlock } from "../state.js";
import { clear, faNum, fmtDate, h, icon, persianize, statusBadge, toastError } from "../ui.js";

export async function render(root) {
  root.append(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "وضعیت سیستم"), h("p", {}, "اتصال به مدل‌ها و پایگاه‌های داده، و کارهای پس‌زمینه. تنظیمات از فایل .env خوانده می‌شوند.")),
    h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => { clear(root); render(root); } }, icon("refresh"), "بررسی مجدد"))));
  const box = h("div", {}, loadingBlock("در حال بررسی اتصال‌ها…"));
  root.append(box);
  const sys = await getSystem(true);
  const p = sys.providers;
  const dot = (ok) => h("span", { class: `status-dot ${ok ? "ok" : "err"}` });
  const card = (title, ok, ...rows) => h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, title),
    h("span", { class: `badge ${ok ? "ok" : "err"}` }, dot(ok), ok ? "در دسترس" : "در دسترس نیست")), h("dl", { class: "kv" }, ...rows));
  const kv = (k, v) => [h("dt", {}, k), h("dd", {}, v)];

  const jobsBox = h("div");
  clear(box, h("div", { class: "stack" },
    h("h2", { style: { margin: "4px 0 0", fontSize: "18px" } }, "مدل‌ها"),
    h("div", { class: "grid grid-3" },
      card("OpenAI", p.openai.available, ...kv("آدرس", h("span", { class: "ltr" }, p.openai.base_url)), ...(p.openai.reason ? kv("علت", p.openai.reason) : [])),
      card("Ollama", p.ollama.available, ...kv("آدرس", h("span", { class: "ltr" }, p.ollama.base_url)),
        ...kv("مدل‌های نصب‌شده", p.ollama.models.length ? h("span", { class: "ltr small" }, p.ollama.models.join(", ")) : "—"),
        ...(p.ollama.reason ? kv("راهنما", h("div", {}, "Ollama را اجرا کنید و مدل‌ها را بگیرید:",
          h("div", { class: "mono ltr", style: { textAlign: "left" } }, "ollama pull bge-m3"),
          h("div", { class: "mono ltr", style: { textAlign: "left" } }, "ollama pull qwen2.5:7b"))) : [])),
      card("HuggingFace (لوکال)", p.huggingface.available, ...kv("دستگاه", h("span", { class: "ltr" }, p.huggingface.device)),
        ...kv("torch", h("span", { class: "ltr" }, p.huggingface.torch || "—")), ...kv("CUDA", p.huggingface.cuda === undefined ? "پس از بارگذاری اولین مدل مشخص می‌شود" : p.huggingface.cuda ? "بله" : "خیر"),
        ...kv("Reranker", h("span", { class: "ltr" }, p.reranker.model || "غیرفعال")))),
    h("h2", { style: { margin: "4px 0 0", fontSize: "18px" } }, "مرحله پس از بازیابی"),
    h("div", { class: "grid grid-3" },
      card("Rerank با LLM", sys.postprocess.rerank.llm.available,
        ...kv("مدل", h("span", { class: "ltr" }, `${sys.postprocess.rerank.llm.provider} / ${sys.postprocess.rerank.llm.model}`)),
        ...kv("تنظیم", h("span", { class: "ltr small" }, "RERANK_LLM_PROVIDER / RERANK_LLM_MODEL"))),
      card("Rerank با Cross-encoder", sys.postprocess.rerank.cross_encoder.available,
        ...kv("مدل", h("span", { class: "ltr" }, sys.postprocess.rerank.cross_encoder.model || "RERANKER_MODEL تنظیم نشده"))),
      card("Jev (TypeSafe AI)", sys.postprocess.jev.available,
        ...kv("از طریق", `${sys.postprocess.jev.via}`),
        ...kv("آدرس", h("span", { class: "ltr small" }, sys.postprocess.jev.base_url)),
        ...kv("مدل", h("span", { class: "ltr" }, sys.postprocess.jev.model)),
        ...kv("آستانه ارتباط / پاسخ‌پذیری", `${sys.postprocess.jev.threshold} / ${sys.postprocess.jev.answerable_threshold}`),
        ...(sys.postprocess.jev.reason ? kv("علت", sys.postprocess.jev.reason) : []))),
    h("h2", { style: { margin: "4px 0 0", fontSize: "18px" } }, "ذخیره‌سازی و پردازش متن"),
    h("div", { class: "grid grid-3" },
      card("ChromaDB", sys.backends.chroma.available, ...kv("حالت", h("span", { class: "ltr small" }, sys.backends.chroma.mode || sys.backends.chroma.reason)),
        ...kv("پیش‌فرض", sys.backends.default === "chroma" ? "بله" : "خیر")),
      card("Qdrant", sys.backends.qdrant.available, ...kv("حالت", h("span", { class: "ltr small" }, sys.backends.qdrant.mode || sys.backends.qdrant.reason)),
        ...kv("پیش‌فرض", sys.backends.default === "qdrant" ? "بله" : "خیر")),
      card("پردازش فارسی", sys.hazm, ...kv("hazm", sys.hazm ? "نصب است" : "نصب نیست (نرمال‌ساز جایگزین)"),
        ...kv("OCR", sys.ocr.available ? h("span", { class: "badge ok" }, "Tesseract + fas") : h("span", { class: "muted" }, sys.ocr.reason)),
        ...kv("نسخه برنامه", h("span", { class: "ltr" }, sys.version)))),
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "کارهای پس‌زمینه اخیر"),
      h("button", { class: "btn ghost sm", onclick: () => loadJobs() }, icon("refresh"))), jobsBox)));
  persianize(box);

  async function loadJobs() {
    try {
      const jobs = await get("/jobs");
      clear(jobsBox, jobs.length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["عنوان", "وضعیت", "پیشرفت", "پیام", "زمان", ""].map((t) => h("th", {}, t)))),
        h("tbody", {}, jobs.map((j) => h("tr", {},
          h("td", {}, j.title), h("td", {}, statusBadge(j.status)),
          h("td", { class: "num" }, faNum(Math.round(j.progress * 100)) + "٪"),
          h("td", { class: "small", style: { maxWidth: "360px" } }, j.error || j.message),
          h("td", { class: "tiny muted" }, fmtDate(j.created_at)),
          h("td", {}, ["pending", "running"].includes(j.status) ? h("button", { class: "btn sm", onclick: () => post(`/jobs/${j.id}/cancel`).then(loadJobs).catch(toastError) }, "لغو") : null))))))
        : h("div", { class: "muted small" }, "کاری ثبت نشده است (سابقه کارها با ری‌استارت سرور پاک می‌شود)."));
    } catch (e) { toastError(e); }
  }
  loadJobs();
}
