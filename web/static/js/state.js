// وضعیت مشترک: اطلاعات سیستم، پایگاه‌های دانش و اجزای پرکاربرد

import { get } from "./api.js";
import { clear, faNum, field, h, modal, persianize, prefs, selectEl, spinner, switchEl } from "./ui.js";

let system = null;
let collections = null;

export async function getSystem(force = false) {
  if (!system || force) system = await get("/system");
  return system;
}
export async function getCollections(force = false) {
  if (!collections || force) collections = await get("/collections");
  return collections;
}
export function invalidateCollections() { collections = null; }

export function currentCollectionId(list) {
  const saved = prefs.get("collection", null);
  if (list?.length) return list.some((c) => c.id === saved) ? saved : list[0].id;
  return saved;
}
export function setCurrentCollection(id) { prefs.set("collection", id); }

export async function collectionSelect(onChange, { value, allowEmpty = false } = {}) {
  const list = await getCollections();
  const sel = selectEl([
    ...(allowEmpty ? [["", "— انتخاب کنید —"]] : []),
    ...list.map((c) => [c.id, `${c.name} (${faNum(c.chunks)} chunk)`]),
  ], value ?? currentCollectionId(list));
  sel.addEventListener("change", () => { setCurrentCollection(sel.value); onChange?.(sel.value); });
  return sel;
}

export const BACKEND_LABEL = { chroma: "ChromaDB", qdrant: "Qdrant" };
export const STRATEGY_LABEL = { structure: "ساختار + جمله + توکن", recursive: "Recursive فارسی", fixed: "برش ثابت کاراکتری" };
export const METHOD_LABEL = { auto: "خودکار", pymupdf: "PyMuPDF", pdfplumber: "pdfplumber", ocr: "OCR" };

/** فرم تنظیمات استخراج و بخش‌بندی (پایگاه دانش، ایندکس مجدد، آزمایشگاه) */
export function settingsForm(values = {}, defaults = {}) {
  const v = { ...defaults, ...values };
  const num = (k, min, max, step = 1) => { const i = h("input", { type: "number", min, max, step }); i.value = v[k]; return i; };
  const inputs = {
    strategy: selectEl(Object.entries(STRATEGY_LABEL), v.strategy),
    max_tokens: num("max_tokens", 50, 4000, 10),
    overlap_sents: num("overlap_sents", 0, 5),
    overlap_tokens: num("overlap_tokens", 0, 1000, 10),
    chunk_chars: num("chunk_chars", 100, 10000, 50),
    min_chunk_tokens: num("min_chunk_tokens", 0, 1000, 5),
    method: selectEl(Object.entries(METHOD_LABEL), v.method),
    margin: num("margin", 0, 0.3, 0.01),
  };
  const sw = {
    clean: switchEl("پاک‌سازی clean_fa", v.clean),
    fix_direction: switchEl("اصلاح خطوط معکوس", v.fix_direction),
    remove_repeated: switchEl("حذف سرصفحه/پاورقی تکراری", v.remove_repeated),
    extract_tables: switchEl("استخراج جدول‌ها به markdown", v.extract_tables),
    heading_by_font: switchEl("تشخیص عنوان با اندازه فونت", v.heading_by_font),
    contextual_header: switchEl("عنوان بخش داخل متن chunk", v.contextual_header),
    ocr_fallback: switchEl("OCR خودکار برای صفحات خراب", v.ocr_fallback),
    reverse_word_order: switchEl("معکوس کردن ترتیب کلمات (کل سند)", v.reverse_word_order),
  };
  // فیلدهای وابسته به روش بخش‌بندی؛ max_tokens بین structure و recursive مشترک است
  const strategyBox = h("div", { class: "form-grid" });
  const rebuild = () => {
    const s = inputs.strategy.value;
    if (s === "structure") clear(strategyBox,
      field("سقف توکن هر chunk", inputs.max_tokens, "با توکنایزر o200k سنجیده می‌شود"),
      field("همپوشانی (تعداد جمله)", inputs.overlap_sents),
      field("حداقل توکن chunk انتهای بخش", inputs.min_chunk_tokens, "کوچک‌ترها به chunk قبلی می‌پیوندند؛ ۰ = خاموش"));
    else if (s === "recursive") clear(strategyBox,
      field("سقف توکن هر chunk", inputs.max_tokens), field("همپوشانی (توکن)", inputs.overlap_tokens));
    else clear(strategyBox, field("طول هر chunk (کاراکتر)", inputs.chunk_chars, "خط پایه برای مقایسه"));
  };
  inputs.strategy.addEventListener("change", rebuild);
  rebuild();

  const el = h("div", { class: "stack" },
    h("div", { class: "form-grid" }, field("روش بخش‌بندی", inputs.strategy), field("ابزار استخراج PDF", inputs.method),
      field("نوار سرصفحه/پاورقی", inputs.margin, "نسبت ارتفاع صفحه")),
    strategyBox,
    h("div", { class: "form-grid" }, Object.values(sw).map((s) => s.el)));
  return {
    el,
    values() {
      const out = {};
      for (const [k, i] of Object.entries(inputs)) out[k] = i.type === "number" ? Number(i.value) : i.value;
      for (const [k, s] of Object.entries(sw)) out[k] = s.input.checked;
      return out;
    },
  };
}

/** نمایش chunk کنار تصویر همان صفحه PDF (لایه ۲ بازبینی راهنما) */
export function showChunk(chunk, { extraActions = [] } = {}) {
  const pdf = (chunk.source || "").toLowerCase().endsWith(".pdf");
  const pages = [];
  for (let p = chunk.page; p && p <= (chunk.page_end || chunk.page) && pages.length < 3; p++) pages.push(p);
  const textBox = persianize(h("div", { class: "stack" },
    h("div", { class: "row" },
      h("span", { class: "badge accent" }, chunk.source || ""),
      chunk.page ? h("span", { class: "badge" }, `صفحه ${chunk.page}${chunk.page_end && chunk.page_end !== chunk.page ? " تا " + chunk.page_end : ""}`) : null,
      chunk.tokens ? h("span", { class: "badge" }, `${chunk.tokens} توکن`) : null,
      chunk.kind === "table" ? h("span", { class: "badge info" }, "جدول") : null),
    chunk.section ? h("div", { class: "small" }, h("b", {}, "بخش: "), chunk.section) : null,
    h("div", { class: "chunk-text pre", style: { maxHeight: "60vh" } }, chunk.body || chunk.text),
    h("div", { class: "tiny muted mono" }, chunk.id || chunk.chunk_id || "")));
  const imgBox = h("div", { class: "stack" });
  if (pdf && chunk.document_id && pages.length) {
    for (const p of pages) {
      const img = h("img", { alt: `تصویر صفحه ${p}`, loading: "lazy", src: `/api/documents/${chunk.document_id}/pages/${p}.png?dpi=110` });
      imgBox.append(img);
    }
  } else imgBox.append(h("div", { class: "empty small" }, "تصویر صفحه فقط برای PDF در دسترس است"));
  return modal({ title: "بازبینی chunk کنار صفحه اصلی", wide: true,
    body: h("div", { class: "chunk-view" }, textBox, imgBox),
    actions: [...extraActions, { label: "بستن" }] });
}

export const RERANK_LABEL = { none: "بدون", llm: "LLM", cross_encoder: "Cross-encoder" };

/** کنترل‌های مرحله پس از بازیابی (Rerank و Jev) — در گفتگو و آزمون بازیابی */
export function postprocessControls(sys, values = {}, onChange) {
  const pp = sys.postprocess;
  const v = { rerank: "none", jev: false, jev_threshold: pp.jev.threshold, jev_answerable: true, ...values };
  if (v.rerank !== "none" && !pp.rerank[v.rerank]?.available) v.rerank = "none";
  if (!pp.jev.available) v.jev = false;
  const emit = () => onChange?.({ ...v });

  const rerankSeg = h("div", { class: "seg", role: "group", "aria-label": "روش Rerank" });
  const paintRerank = () => clear(rerankSeg, Object.entries(RERANK_LABEL).map(([k, l]) => {
    const ok = k === "none" || pp.rerank[k]?.available;
    return h("button", { type: "button", class: v.rerank === k ? "on" : "", disabled: !ok, "aria-pressed": String(v.rerank === k),
      title: k === "llm" ? `${pp.rerank.llm.provider} / ${pp.rerank.llm.model}` : k === "cross_encoder" ? (pp.rerank.cross_encoder.model || "RERANKER_MODEL تنظیم نشده") : "",
      onclick: () => { v.rerank = k; paintRerank(); emit(); } }, l);
  }));
  paintRerank();

  const jevSw = switchEl("Jev: فیلتر ارتباط", v.jev, { disabled: !pp.jev.available });
  const thr = h("input", { type: "range", min: 0.05, max: 0.95, step: 0.05, value: v.jev_threshold });
  const thrVal = h("b", {}, faNum(v.jev_threshold));
  const ansSw = switchEl("Jev: بررسی پاسخ‌پذیری قبل از LLM", v.jev_answerable);
  const jevBox = h("div", { class: "stack", style: { gap: "8px", paddingRight: "12px", borderRight: "2px solid var(--line)" } },
    h("label", { class: "field" }, h("span", {}, "آستانه احتمال ارتباط: ", thrVal), thr), ansSw.el);
  const syncJev = () => { jevBox.hidden = !v.jev; };
  jevSw.input.addEventListener("change", () => { v.jev = jevSw.input.checked; syncJev(); emit(); });
  thr.addEventListener("input", () => { v.jev_threshold = Number(thr.value); thrVal.textContent = faNum(v.jev_threshold); emit(); });
  ansSw.input.addEventListener("change", () => { v.jev_answerable = ansSw.input.checked; emit(); });
  syncJev();

  const el = h("div", { class: "stack", style: { gap: "10px" } },
    field("Rerank", rerankSeg, pp.rerank.llm.available ? null : "Rerank با LLM به یک مدل زبانی در دسترس نیاز دارد"),
    jevSw.el,
    pp.jev.available ? null : h("span", { class: "hint" }, "برای Jev کلید TYPESAFE_API_KEY را در .env تنظیم کنید"),
    jevBox);
  return { el, values: () => ({ ...v }) };
}

/** مدل‌هایی که با تنظیمات فعلی استفاده خواهند شد (پیش از ارسال پرسش) */
export function plannedModels(sys, col, o) {
  const d = (stage, label, provider, model, where) => ({ stage, label, provider, model,
    provider_label: provider === "jev" ? "TypeSafe Jev" : (sys.provider_labels[provider] || provider),
    where: where ?? sys.provider_where[provider] ?? "" });
  const out = [];
  if (col && o.mode !== "bm25") out.push(d("embedding", "Embedding", col.embedding_provider, col.embedding_model));
  if (o.rerank === "llm") out.push(d("rerank", "Rerank", sys.postprocess.rerank.llm.provider, sys.postprocess.rerank.llm.model));
  if (o.rerank === "cross_encoder") out.push(d("rerank", "Rerank", "huggingface", sys.postprocess.rerank.cross_encoder.model));
  if (o.jev) out.push(d("jev", "Jev", "jev", sys.postprocess.jev.model, `${sys.postprocess.jev.via} · ${sys.postprocess.jev.where}`));
  if (o.llm_provider) out.push(d("llm", "LLM پاسخ", o.llm_provider, o.llm_model));
  return out;
}

/** فهرست «کدام مدل، از کجا» */
export function modelsList(models, { compact = false } = {}) {
  if (!models?.length) return null;
  if (compact) {
    return h("div", { class: "row", style: { gap: "4px" } }, h("span", { class: "tiny muted" }, "مدل‌ها:"),
      // هر بخش جداگانه isolate می‌شود تا ترتیب برچسب فارسی و نام لاتین مدل در متن راست‌به‌چپ به هم نریزد
      models.map((m) => h("span", { class: "badge", title: `${m.provider_label} · ${m.where}`, style: m.skipped ? { opacity: 0.6 } : null },
        h("b", { style: { unicodeBidi: "isolate" } }, m.label),
        h("span", { class: "ltr", style: m.skipped ? { textDecoration: "line-through" } : null }, m.model),
        m.skipped ? h("span", { class: "muted" }, "فراخوانی نشد")
          : h("span", { class: "muted ltr" }, m.where))));
  }
  return h("dl", { class: "kv small", style: { gap: "6px 12px" } }, models.flatMap((m) => [
    h("dt", {}, m.label),
    h("dd", {}, h("div", { class: "ltr", style: { fontWeight: 700, textAlign: "right" } }, m.model),
      h("div", { class: "tiny muted" }, `${m.provider_label} · ${m.where}`)),
  ]));
}

/** نوار مراحل مرحله پرسش: بازیابی ← Rerank ← Jev ← پاسخ‌پذیری */
export function stagesBar(info) {
  const stages = info?.stages || [];
  if (stages.length < 2) return null;
  const item = (s) => {
    let detail = "";
    if (s.name === "retrieve") detail = `${faNum(s.out)} کاندید`;
    else if (s.name === "rerank") detail = `${faNum(s.in)} مرتب شد`;
    else if (s.name === "jev") detail = `${faNum(s.in)} ← ${faNum(s.out)}` + (s.dropped ? ` (${faNum(s.dropped)} حذف)` : "");
    else if (s.name === "answerable") detail = `احتمال ${faNum(s.prob)}`;
    else if (s.name === "topk") detail = `${faNum(s.out)} متن`;
    else if (s.name === "sql") detail = `${faNum(s.in)} سطر داده ← ${faNum(s.out)} سطر نتیجه` + (s.attempts > 1 ? ` (${faNum(s.attempts)} تلاش)` : "");
    else if (s.name === "answer") detail = "LLM";
    const bad = s.name === "answerable" && s.prob < s.threshold;
    return h("span", { class: `badge ${bad ? "err" : s.name === "jev" || s.name === "answerable" ? "info" : ""}`,
      title: s.ms ? `${s.ms} ms` : "" }, h("b", {}, s.label), "·", detail);
  };
  return h("div", { class: "row", style: { gap: "4px" } },
    stages.flatMap((s, i) => (i ? [h("span", { class: "muted tiny" }, "←"), item(s)] : [item(s)])));
}

export function loadingBlock(text = "در حال بارگذاری…") {
  return h("div", { class: "row muted", style: { padding: "24px", justifyContent: "center" } }, spinner(), text);
}
