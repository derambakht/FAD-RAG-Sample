// آزمون بازیابی: مقایسه هم‌زمان جستجوی برداری، BM25 و ترکیبی برای یک پرسش

import { post } from "../api.js";
import {
  collectionSelect, currentCollectionId, getCollections, getSystem, modelsList, postprocessControls, showChunk, stagesBar,
} from "../state.js";
import { clear, emptyState, faNum, field, h, highlight, icon, persianize, spinner, switchEl, toastError } from "../ui.js";
import { scoreBadges } from "./chat.js";

const MODES = [["dense", "برداری (Embedding)"], ["bm25", "کلیدواژه‌ای (BM25)"], ["hybrid", "ترکیبی (RRF)"]];

export async function render(root, params) {
  const [sys, cols] = await Promise.all([getSystem(), getCollections()]);
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "آزمون بازیابی"),
    h("p", {}, "یک پرسش را هم‌زمان با سه روش بازیابی کنید و ببینید کدام chunk در رتبه بالاتر می‌آید. بدون فراخوانی LLM."))));
  if (!cols.length) { root.append(h("div", { class: "card" }, emptyState("db", "پایگاه دانشی وجود ندارد", null, h("a", { class: "btn primary", href: "#/collections" }, "ساخت پایگاه دانش")))); return; }

  let colId = params.collection || currentCollectionId(cols);
  const colSel = await collectionSelect((v) => { colId = v; }, { value: colId });
  const q = h("input", { type: "search", placeholder: "مثلاً: حداقل نمره قبولي چند است؟", value: params.q || "" });
  const k = h("input", { type: "number", min: 1, max: 20, value: 5 });
  const clean = switchEl("نرمال‌سازی پرسش با clean_fa", true);
  const pp = postprocessControls(sys, {});
  const out = h("div");
  const run = async () => {
    if (!q.value.trim()) return;
    clear(out, h("div", { class: "row muted" }, spinner(), "در حال جستجو…"));
    const v = pp.values();
    try {
      const results = await Promise.all(MODES.map(([mode]) => post("/search", {
        collection_id: colId, query: q.value, mode, k: Number(k.value), clean: clean.input.checked,
        rerank: v.rerank, jev: v.jev, jev_threshold: v.jev_threshold })));
      clear(out,
        persianize(h("div", { class: "alert", style: { marginBottom: "10px" } }, "پرسش پس از نرمال‌سازی: ", h("b", {}, results[0].query))),
        h("div", { style: { marginBottom: "14px" } }, modelsList(results[2].models, { compact: true })),
        h("div", { class: "cols" }, results.map((r, i) => column(MODES[i][1], r))));
    } catch (e) { toastError(e); clear(out); }
  };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });

  root.append(h("div", { class: "card", style: { marginBottom: "16px" } },
    h("div", { class: "form-grid", style: { gridTemplateColumns: "minmax(0,3fr) minmax(160px,1fr) 100px" } },
      field("پرسش", q), field("پایگاه دانش", colSel), field("k", k)),
    h("details", { style: { marginTop: "12px" } },
      h("summary", { style: { cursor: "pointer", fontWeight: 700 } }, "مرحله پس از بازیابی: Rerank و Jev"),
      h("div", { style: { marginTop: "10px", maxWidth: "460px" } }, pp.el)),
    h("div", { class: "row", style: { marginTop: "12px" } }, clean.el, h("span", { class: "spacer" }),
      h("button", { class: "btn primary", onclick: run }, icon("search"), "جستجو"))), out);
  if (params.q) run();
}

function column(title, r) {
  const t = r.timings || {};
  return h("div", { class: "stack", style: { gap: "10px" } },
    h("div", { class: "row" }, h("h3", { style: { margin: 0, fontSize: "15px" } }, title), h("span", { class: "spacer" }),
      h("span", { class: "tiny muted" }, `${faNum(t.total_ms ?? 0)} ms`)),
    persianize(stagesBar(r)),
    r.hits.length ? r.hits.map((hit, i) => persianize(h("div", { class: "hit" },
      h("div", { class: "row small" }, h("span", { class: "rank" }, `#${i + 1}`), h("b", {}, hit.source),
        hit.page ? h("span", { class: "badge" }, `ص ${hit.page}`) : null, h("span", { class: "spacer" }),
        h("span", { class: "tiny muted ltr" }, `score ${hit.score}`)),
      hit.section ? h("div", { class: "tiny muted" }, hit.section) : null,
      h("div", { class: "text small" }, highlight(hit.body.length > 420 ? hit.body.slice(0, 420) + "…" : hit.body, r.query)),
      h("div", { class: "row" }, scoreBadges(hit), h("span", { class: "spacer" }),
        h("button", { class: "btn ghost sm", onclick: () => showChunk(hit) }, icon("eye"), "مشاهده"))))) :
      h("div", { class: "empty small" }, "نتیجه‌ای پیدا نشد"));
}
