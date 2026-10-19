// بررسی chunkها: audit خودکار، توزیع توکن و بازبینی چشمی کنار صفحه PDF (بخش ۹ راهنما)

import { get } from "../api.js";
import { collectionSelect, currentCollectionId, getCollections, loadingBlock, showChunk } from "../state.js";
import { clear, emptyState, faNum, field, h, histogram, persianize, selectEl, switchEl, toastError } from "../ui.js";
import { addQuestionForChunk } from "./eval.js";

const PAGE = 100;

export async function render(root, params) {
  const cols = await getCollections();
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "بررسی chunkها"),
    h("p", {}, "بازرسی خودکار بدون مدل: توکن کم، امتیاز واژگان پایین، کاراکتر نرمال‌نشده، جمله نیمه‌کاره و تکراری. روی هر ردیف کلیک کنید تا chunk را کنار صفحه اصلی ببینید."))));
  if (!cols.length) { root.append(h("div", { class: "card" }, emptyState("db", "پایگاه دانشی وجود ندارد"))); return; }

  let colId = params.collection || currentCollectionId(cols);
  let docId = params.document || "";
  const docSel = selectEl([["", "همه اسناد"]], "");
  const colSel = await collectionSelect(async (v) => { colId = v; docId = ""; await loadDocs(); load(); }, { value: colId });
  const minTok = h("input", { type: "number", min: 0, max: 1000, value: 50 });
  const minVocab = h("input", { type: "number", min: 0, max: 1, step: 0.05, value: 0.6 });
  const onlySuspect = switchEl("فقط chunkهای مشکوک", false);
  const text = h("input", { type: "search", placeholder: "جستجو در متن" });
  const summaryBox = h("div");
  const tableBox = h("div");
  let data = null, flagFilter = null, shown = PAGE;

  async function loadDocs() {
    const docs = await get(`/collections/${colId}/documents`);
    clear(docSel, h("option", { value: "" }, "همه اسناد"), docs.map((d) => h("option", { value: d.id }, d.filename)));
    docSel.value = docs.some((d) => d.id === docId) ? docId : "";
  }
  docSel.addEventListener("change", () => { docId = docSel.value; load(); });
  [minTok, minVocab].forEach((i) => i.addEventListener("change", load));
  onlySuspect.input.addEventListener("change", () => { shown = PAGE; renderTable(); });
  text.addEventListener("input", () => { shown = PAGE; renderTable(); });

  async function load() {
    clear(summaryBox, loadingBlock()); clear(tableBox);
    try {
      const qs = new URLSearchParams({ min_tokens: minTok.value, min_vocab: minVocab.value });
      if (docId) qs.set("document_id", docId);
      data = await get(`/collections/${colId}/audit?${qs}`);
      flagFilter = null; shown = PAGE;
      renderSummary(); renderTable();
    } catch (e) { toastError(e); clear(summaryBox); }
  }

  function renderSummary() {
    const s = data.summary;
    if (!s.total) { clear(summaryBox, h("div", { class: "card" }, emptyState("audit", "chunkی برای بررسی وجود ندارد"))); return; }
    const chips = h("div", { class: "row" }, Object.entries(s.flag_labels).map(([f, label]) =>
      h("button", { class: `btn sm ${flagFilter === f ? "primary" : ""}`, disabled: !s.flags[f],
        onclick: () => { flagFilter = flagFilter === f ? null : f; shown = PAGE; renderSummary(); renderTable(); } },
      `${label}: ${faNum(s.flags[f])}`)));
    clear(summaryBox, h("div", { class: "grid grid-2", style: { marginBottom: "16px" } },
      h("div", { class: "stack" },
        h("div", { class: "tiles" },
          tile("کل chunkها", s.total), tile("مشکوک", s.suspects, s.suspects ? "نیاز به بازبینی" : "بدون مشکل"),
          tile("میانه توکن", s.tokens.median, `بازه ${faNum(s.tokens.min)} تا ${faNum(s.tokens.max)}`),
          tile("میانگین واژگان", s.vocab_mean)),
        h("div", { class: "card" }, h("h3", {}, "فیلتر بر اساس نوع مشکل"), chips,
          h("p", { class: "hint", style: { margin: "8px 0 0" } }, "«بدون عنوان بخش» فقط اطلاع‌رسانی است و chunk را مشکوک نمی‌کند."))),
      h("div", { class: "card" }, h("h3", {}, "توزیع تعداد توکن chunkها"), histogram(s.histogram, { label: "تعداد chunk" }),
        h("p", { class: "hint", style: { margin: "8px 0 0" } }, `آستانه‌ها: حداقل ${faNum(s.thresholds.min_tokens)} توکن و امتیاز واژگان ${faNum(s.thresholds.min_vocab)}؛ با توجه به توزیع اسناد خودتان تنظیم کنید.`))));
    persianize(summaryBox);
  }

  function renderTable() {
    if (!data?.summary.total) return;
    const needle = text.value.trim();
    let rows = data.rows;
    if (onlySuspect.input.checked) rows = rows.filter((r) => r.suspect);
    if (flagFilter) rows = rows.filter((r) => r.flags.includes(flagFilter));
    if (needle) rows = rows.filter((r) => r.preview.includes(needle) || (r.section || "").includes(needle));
    const labels = data.summary.flag_labels;
    const body = rows.slice(0, shown).map((r) => h("tr", { class: "clickable", tabindex: 0,
      onclick: () => open(r), onkeydown: (e) => { if (e.key === "Enter") open(r); } },
    h("td", { class: "num" }, faNum(r.idx + 1)),
    h("td", {}, h("div", { class: "small", style: { fontWeight: 700 } }, r.source), h("div", { class: "tiny muted" }, r.page ? `ص ${faNum(r.page)}` : "")),
    h("td", { style: { minWidth: "260px" } }, r.section ? h("div", { class: "tiny muted" }, r.section) : null, h("div", { class: "small" }, r.preview + (r.preview.length >= 220 ? "…" : ""))),
    h("td", { class: "num" }, faNum(r.tokens)),
    h("td", { class: "num" }, faNum(r.vocab)),
    h("td", {}, r.flags.map((f) => h("span", { class: `badge flag ${f === "no_title" ? "" : "warn"}`, style: { margin: "1px" } }, labels[f])))));
    clear(tableBox, h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, `chunkها (${faNum(rows.length)})`), h("div", { class: "row" }, onlySuspect.el, text)),
      rows.length ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", { class: "num" }, "#"), h("th", {}, "منبع"), h("th", {}, "متن"), h("th", { class: "num" }, "توکن"),
          h("th", { class: "num" }, "واژگان"), h("th", {}, "نشانه‌ها"))),
        h("tbody", {}, body))) : h("div", { class: "empty" }, "موردی با این فیلتر وجود ندارد"),
      rows.length > shown ? h("div", { class: "row", style: { justifyContent: "center", marginTop: "12px" } },
        h("button", { class: "btn", onclick: () => { shown += PAGE; renderTable(); } }, `نمایش ${faNum(Math.min(PAGE, rows.length - shown))} مورد دیگر`)) : null));
  }

  async function open(r) {
    try {
      const chunk = await get(`/chunks/${r.id}`);
      showChunk(chunk, { extraActions: [{ label: "افزودن پرسش ارزیابی", onClick: () => { addQuestionForChunk(chunk); } }] });
    } catch (e) { toastError(e); }
  }

  root.append(h("div", { class: "card", style: { marginBottom: "16px" } }, h("div", { class: "form-grid" },
    field("پایگاه دانش", colSel), field("سند", docSel), field("حداقل توکن", minTok), field("حداقل امتیاز واژگان", minVocab))),
  summaryBox, tableBox);
  await loadDocs();
  if (params.document) docSel.value = params.document;
  docId = docSel.value;
  load();
}

function tile(label, value, sub) {
  return h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, faNum(value)),
    sub ? h("div", { class: "sub" }, sub) : null);
}
