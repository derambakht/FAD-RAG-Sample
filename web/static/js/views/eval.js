// ارزیابی کمّی بازیابی: مجموعه پرسش، تولید پرسش با LLM، اجرای Hit@k و MRR روی چند پیکربندی

import { del, get, post, waitJob } from "../api.js";
import { RERANK_LABEL, STRATEGY_LABEL, getCollections, getSystem, loadingBlock } from "../state.js";
import {
  clear, confirmDialog, emptyState, faNum, field, fmtDate, groupedBars, h, icon, modal, persianize, prefs, seg, selectEl, spinner,
  switchEl, toast, toastError,
} from "../ui.js";

const MODE_LABEL = { dense: "برداری", bm25: "BM25", hybrid: "ترکیبی" };

export async function render(root) {
  const [cols, sys] = await Promise.all([getCollections(), getSystem()]);
  root.append(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "ارزیابی Hit@k و MRR"),
      h("p", {}, "برای هر chunk نمونه یک پرسش ساخته می‌شود که پاسخش فقط در همان chunk است؛ سپس بررسی می‌شود retriever آن را در k نتیجه اول برمی‌گرداند یا نه.")),
    h("div", { class: "actions" }, h("button", { class: "btn primary", disabled: !cols.length, onclick: () => newSet() }, icon("plus"), "مجموعه ارزیابی جدید"))));
  if (!cols.length) { root.append(h("div", { class: "card" }, emptyState("db", "ابتدا یک پایگاه دانش بسازید"))); return; }

  const listBox = h("div", { class: "stack", style: { gap: "8px" } });
  const detail = h("div", { class: "stack" });
  root.append(h("div", { style: { display: "grid", gap: "16px", gridTemplateColumns: "minmax(0, 260px) minmax(0, 1fr)" }, class: "eval-layout" },
    h("div", { class: "card", style: { alignSelf: "start" } }, h("h3", {}, "مجموعه‌ها"), listBox), detail));
  const mq = window.matchMedia("(max-width: 900px)");
  const layout = root.querySelector(".eval-layout");
  const fit = () => { layout.style.gridTemplateColumns = mq.matches ? "minmax(0,1fr)" : "minmax(0, 260px) minmax(0, 1fr)"; };
  mq.addEventListener("change", fit); fit();

  let selected = prefs.get("eval-set", null);
  let alive = true;

  async function loadList() {
    const sets = await get("/eval-sets");
    clear(listBox, sets.length ? sets.map((s) => h("button", { class: `btn ${s.id === selected ? "primary" : "ghost"}`,
      style: { justifyContent: "flex-start", textAlign: "right", whiteSpace: "normal", display: "grid", gap: 0 },
      onclick: () => { selected = s.id; prefs.set("eval-set", s.id); loadList(); loadDetail(); } },
    h("b", {}, s.name), h("span", { class: "tiny", style: { opacity: .8 } }, `${s.collection_name} · ${faNum(s.items)} پرسش`)))
      : h("div", { class: "muted small" }, "هنوز مجموعه‌ای نساخته‌اید."));
    if (!sets.some((s) => s.id === selected)) { selected = sets[0]?.id || null; }
    return sets;
  }

  async function newSet() {
    const colSel = selectEl(cols.map((c) => [c.id, c.name]));
    const name = h("input", { type: "text", placeholder: "مثلاً: پرسش‌های مصنوعی ۳۰تایی" });
    modal({ title: "مجموعه ارزیابی جدید", body: h("div", { class: "stack" }, field("پایگاه دانش مرجع", colSel, "پرسش‌ها از chunkهای این پایگاه ساخته می‌شوند"), field("نام", name)),
      actions: [{ label: "انصراف" }, { label: "ساخت", class: "primary", onClick: async () => {
        if (!name.value.trim()) { toast("نام را وارد کنید", "warn"); return false; }
        const s = await post("/eval-sets", { collection_id: colSel.value, name: name.value });
        selected = s.id; prefs.set("eval-set", s.id); await loadList(); loadDetail();
      } }] });
  }

  async function loadDetail() {
    if (!selected) { clear(detail, h("div", { class: "card" }, emptyState("chart", "یک مجموعه ارزیابی بسازید", "مجموعه شامل پرسش‌ها و chunk طلایی هر پرسش است."))); return; }
    clear(detail, loadingBlock());
    const s = await get(`/eval-sets/${selected}`);
    const col = cols.find((c) => c.id === s.collection_id);
    const jobBox = h("div");

    const track = async (job, after) => {
      const bar = h("i", { style: { width: "0%" } }); const msg = h("span", { class: "small muted" }, job.title);
      clear(jobBox, h("div", { class: "card", style: { padding: "12px 16px" } }, h("div", { class: "row" }, spinner(), msg),
        h("div", { class: "progress", style: { marginTop: "8px" } }, bar)));
      const j = await waitJob(job.id, (x) => { bar.style.width = `${x.progress * 100}%`; msg.textContent = x.message; });
      clear(jobBox);
      if (!alive) return;
      if (j.status === "error") toast(j.error, "err", 9000); else if (j.status === "done") after?.(j);
      loadList(); loadDetail();
    };

    // --- اجرای ارزیابی ---
    const colChecks = cols.map((c) => ({ c, sw: switchEl(c.name, c.id === s.collection_id) }));
    const modeChecks = Object.entries(MODE_LABEL).map(([m, l]) => ({ m, sw: switchEl(l, m !== "bm25") }));
    const pp = sys.postprocess;
    const rerankChecks = Object.entries(RERANK_LABEL).map(([m, l]) => ({ m,
      sw: switchEl(m === "none" ? "بدون Rerank" : `Rerank با ${l}`, m === "none", { disabled: m !== "none" && !pp.rerank[m]?.available }) }));
    const noJev = !pp.jev.available;
    const jevSeg = seg([["off", "بدون Jev"], ["on", "با Jev", noJev], ["both", "هر دو", noJev]], "off");
    const cleanQ = seg([["on", "با clean_fa"], ["off", "بدون clean_fa"], ["both", "هر دو"]], "on");
    const k = h("input", { type: "number", min: 1, max: 20, value: 5, style: { width: "90px" } });
    const runBtn = h("button", { class: "btn primary", disabled: !s.items, onclick: async () => {
      const configs = [];
      const cleans = cleanQ.value === "both" ? [true, false] : [cleanQ.value === "on"];
      const jevs = jevSeg.value === "both" ? [false, true] : [jevSeg.value === "on"];
      const reranks = rerankChecks.filter((x) => x.sw.input.checked).map((x) => x.m);
      for (const { c, sw } of colChecks) if (sw.input.checked)
        for (const { m, sw: ms } of modeChecks) if (ms.input.checked)
          for (const rr of reranks) for (const jv of jevs) for (const cq of cleans)
            configs.push({ collection_id: c.id, mode: m, rerank: rr, jev: jv, clean_query: cq });
      if (!configs.length) { toast("حداقل یک پایگاه دانش، یک روش بازیابی و یک گزینه Rerank انتخاب کنید", "warn"); return; }
      if (configs.length > 24) { toast(`${faNum(configs.length)} پیکربندی انتخاب شده؛ حداکثر ۲۴ مجاز است`, "warn"); return; }
      try { track(await post(`/eval-sets/${s.id}/run`, { configs, k: Number(k.value) }), () => toast("ارزیابی کامل شد", "ok")); }
      catch (e) { toastError(e); }
    } }, icon("play"), "اجرای ارزیابی");

    const runCard = h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "اجرای ارزیابی")),
      h("div", { class: "grid grid-2" },
        h("div", {}, h("div", { class: "small muted", style: { marginBottom: "4px" } }, "پایگاه‌های دانش (برای مقایسه chunkبندی یا مدل embedding)"),
          h("div", { class: "stack", style: { gap: "6px" } }, colChecks.map((x) => x.sw.el))),
        h("div", { class: "stack", style: { gap: "10px" } },
          h("div", {}, h("div", { class: "small muted", style: { marginBottom: "4px" } }, "روش‌های بازیابی"), h("div", { class: "row" }, modeChecks.map((x) => x.sw.el))),
          h("div", {}, h("div", { class: "small muted", style: { marginBottom: "4px" } }, "مرحله پس از بازیابی"),
            h("div", { class: "row" }, rerankChecks.map((x) => x.sw.el)), h("div", { style: { marginTop: "6px" } }, jevSeg.el)),
          h("div", {}, h("div", { class: "small muted", style: { marginBottom: "4px" } }, "نرمال‌سازی پرسش (تمرین ۵ راهنما)"), cleanQ.el),
          h("label", { class: "row small" }, "k =", k))),
      h("p", { class: "hint" }, "در پایگاه مرجع، تطبیق با شناسه chunk طلایی است؛ در پایگاه‌های دیگر (chunkبندی متفاوت) chunkی درست حساب می‌شود که دست‌کم ۶۰٪ کلماتش با متن طلایی مشترک باشد."),
      h("div", { class: "row end" }, runBtn));

    // --- نتایج ---
    const items = s.items_list;
    const itemById = Object.fromEntries(items.map((i) => [i.id, i]));
    const runsBox = h("div", { class: "stack" });
    if (s.runs.length) {
      s.runs.forEach((run, idx) => runsBox.append(runCardEl(run, idx === 0, itemById, () => loadDetail())));
    }

    // --- پرسش‌ها ---
    const itemsCard = h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, `پرسش‌ها (${faNum(items.length)})`),
        h("div", { class: "row" },
          h("button", { class: "btn sm", onclick: () => generateDialog(s, sys, (job) => track(job, (j) => toast(`${faNum(j.result.added)} پرسش ساخته شد`, "ok"))) }, icon("plus"), "تولید با LLM"),
          h("button", { class: "btn sm", onclick: () => manualDialog(s, () => loadDetail()) }, icon("edit"), "افزودن دستی"))),
      items.length ? h("div", { class: "table-wrap", style: { maxHeight: "460px" } }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "پرسش"), h("th", {}, "منبع"), h("th", {}, "متن طلایی"), h("th", {}, ""))),
        h("tbody", {}, items.map((it) => h("tr", {},
          h("td", { style: { minWidth: "220px" } }, it.question),
          h("td", {}, h("span", { class: `badge ${it.source === "manual" ? "info" : ""}` }, it.source === "manual" ? "دستی" : "LLM")),
          h("td", { class: "small muted", style: { minWidth: "240px" } }, it.gold_text.slice(0, 140) + (it.gold_text.length > 140 ? "…" : "")),
          h("td", {}, h("div", { class: "row", style: { flexWrap: "nowrap", gap: "2px" } },
            h("a", { class: "btn ghost sm", title: "آزمون بازیابی این پرسش", href: `#/search?collection=${s.collection_id}&q=${encodeURIComponent(it.question)}` }, icon("search")),
            h("button", { class: "btn ghost sm", title: "حذف", style: { color: "var(--err)" }, onclick: async () => {
              try { await del(`/eval-items/${it.id}`); loadDetail(); loadList(); } catch (e) { toastError(e); }
            } }, icon("trash"))))))))) :
        emptyState("chat", "پرسشی وجود ندارد", "با LLM پرسش بسازید (مثلاً ۳۰ پرسش) و ۱۰ تا ۲۰ پرسش دست‌نویس واقعی هم اضافه کنید؛ پرسش‌های مصنوعی نتیجه را خوش‌بینانه نشان می‌دهند."));

    clear(detail,
      h("div", { class: "page-head", style: { marginBottom: 0 } },
        h("div", {}, h("h2", { style: { margin: 0 } }, s.name),
          persianize(h("div", { class: "row small muted" }, `پایگاه مرجع: ${col?.name || "—"}`, "·", `${faNum(s.items)} پرسش`, "·", fmtDate(s.created_at)))),
        h("button", { class: "btn danger sm", onclick: async () => {
          if (!(await confirmDialog("حذف مجموعه ارزیابی", `«${s.name}» با همه پرسش‌ها و نتایج حذف شود؟`))) return;
          await del(`/eval-sets/${s.id}`); selected = null; prefs.set("eval-set", null); await loadList(); loadDetail();
        } }, icon("trash"), "حذف مجموعه")),
      jobBox, runCard, runsBox, itemsCard);
  }

  await loadList();
  await loadDetail();
  return () => { alive = false; };
}

function configLabel(r) {
  const parts = [r.collection_name, MODE_LABEL[r.mode]];
  const rr = r.rerank === true ? "cross_encoder" : r.rerank;
  if (rr && rr !== "none") parts.push(`Rerank ${RERANK_LABEL[rr]}`);
  if (r.jev) parts.push("Jev");
  if (!r.clean_query) parts.push("بدون clean_fa");
  return parts.join(" · ");
}

function runCardEl(run, open, itemById, onDelete) {
  const res = run.results.results || [];
  const k = run.results.k;
  const groups = res.map((r) => ({ label: configLabel(r), values: { hit: r.hit, mrr: r.mrr } }));
  const best = Math.max(...res.map((r) => r.mrr));
  const failures = h("div", { class: "stack", style: { gap: "6px" } }, res.map((r) => {
    const missed = r.ranks.filter((x) => !x.rank);
    if (!missed.length) return null;
    return h("details", {}, h("summary", { class: "small", style: { cursor: "pointer" } }, `${configLabel(r)}: ${faNum(missed.length)} پرسش بازیابی نشد`),
      h("ul", { class: "small", style: { margin: "6px 0" } }, missed.map((x) => h("li", {}, itemById[x.item_id]?.question || "(حذف‌شده)"))));
  }));
  return persianize(h("details", { class: "card", open: open || undefined },
    h("summary", { style: { cursor: "pointer", fontWeight: 700 } }, `نتیجه ارزیابی ${fmtDate(run.created_at)} · k=${k} · ${res.length} پیکربندی`),
    h("div", { class: "stack", style: { marginTop: "14px" } },
      groupedBars(groups, [{ key: "hit", label: `Hit@${k}`, color: "--series-1" }, { key: "mrr", label: "MRR", color: "--series-2" }]),
      h("div", { class: "stack", style: { gap: "10px" } },
        h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, "پیکربندی"), h("th", {}, "Embedding / بخش‌بندی"), h("th", { class: "num" }, `Hit@${k}`), h("th", { class: "num" }, "MRR"))),
          h("tbody", {}, res.map((r) => h("tr", {},
            h("td", {}, configLabel(r), r.mrr === best && res.length > 1 ? h("span", { class: "badge ok", style: { marginRight: "6px" } }, "بهترین") : null),
            h("td", { class: "tiny" }, h("span", { class: "ltr" }, r.embedding), h("br"), STRATEGY_LABEL[r.strategy] || r.strategy),
            h("td", { class: "num" }, String(r.hit)), h("td", { class: "num" }, String(r.mrr))))))),
        failures,
        h("div", { class: "row end" }, h("button", { class: "btn ghost sm", style: { color: "var(--err)" }, onclick: async () => {
          await del(`/eval-runs/${run.id}`); onDelete();
        } }, icon("trash"), "حذف این نتیجه"))))));
}

async function generateDialog(set, sys, onJob) {
  const provider = selectEl(Object.keys(sys.provider_labels).map((p) => [p, sys.provider_labels[p]]), sys.defaults.llm_provider);
  const model = h("input", { type: "text", class: "ltr", value: sys.defaults.llm_model, list: "gen-models" });
  const dl = h("datalist", { id: "gen-models" });
  const sync = (reset) => {
    const list = [...new Set([...(sys.presets.llm[provider.value] || []), ...(provider.value === "ollama" ? sys.providers.ollama.models : [])])];
    clear(dl, list.map((m) => h("option", { value: m }))); if (reset) model.value = list[0] || "";
  };
  provider.addEventListener("change", () => sync(true)); sync(false);
  const n = h("input", { type: "number", min: 1, max: 500, value: 30 });
  const seed = h("input", { type: "number", value: 7 });
  modal({ title: "تولید پرسش با LLM", body: h("div", { class: "stack" },
    h("p", { class: "muted", style: { margin: 0 } }, "از chunkهای تصادفی (با حداقل ۶۰ توکن) پرسش فارسی طبیعی ساخته می‌شود که پاسخش فقط در همان chunk است. مدل قوی‌تر پرسش‌های بهتری می‌سازد."),
    h("div", { class: "form-grid" }, field("ارائه‌دهنده", provider), field("مدل", model), dl, field("تعداد پرسش", n), field("seed", seed, "برای تکرارپذیری"))),
  actions: [{ label: "انصراف" }, { label: "شروع تولید", class: "primary", onClick: async () => {
    onJob(await post(`/eval-sets/${set.id}/generate`, { n: Number(n.value), llm_provider: provider.value, llm_model: model.value.trim(), seed: Number(seed.value) }));
  } }] });
}

function chunkPicker(collectionId) {
  let chosen = null;
  const q = h("input", { type: "search", placeholder: "جستجو در متن chunkها…" });
  const list = h("div", { class: "stack", style: { gap: "6px", maxHeight: "300px", overflowY: "auto" } });
  const search = async () => {
    clear(list, spinner());
    const res = await get(`/collections/${collectionId}/chunks?limit=30&q=${encodeURIComponent(q.value)}`);
    clear(list, res.items.length ? res.items.map((c) => {
      const el = h("label", { class: "hit", style: { cursor: "pointer" } },
        h("div", { class: "row small" }, h("input", { type: "radio", name: "gold", onchange: () => { chosen = c; } }),
          h("b", {}, c.source), c.page ? h("span", { class: "badge" }, `ص ${faNum(c.page)}`) : null, h("span", { class: "muted tiny" }, c.section || "")),
        h("div", { class: "small" }, c.body.slice(0, 260) + (c.body.length > 260 ? "…" : "")));
      return el;
    }) : h("div", { class: "muted small" }, "chunkی پیدا نشد"));
  };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
  search().catch(toastError);
  return { el: h("div", { class: "stack", style: { gap: "8px" } }, h("div", { class: "row" }, q, h("button", { class: "btn", type: "button", onclick: search }, icon("search"))), list), get value() { return chosen; } };
}

function manualDialog(set, onAdded) {
  const question = h("textarea", { rows: 2, placeholder: "پرسش واقعی کاربر؛ مثلاً با ارقام فارسی یا «ي/ك» عربی برای تست نرمال‌سازی" });
  const picker = chunkPicker(set.collection_id);
  modal({ title: "افزودن پرسش دستی", wide: true, body: h("div", { class: "stack" }, field("پرسش", question), h("div", { class: "small muted" }, "chunk طلایی (پاسخ درست در کدام chunk است؟)"), picker.el),
    actions: [{ label: "انصراف" }, { label: "افزودن", class: "primary", onClick: async () => {
      if (!question.value.trim() || !picker.value) { toast("پرسش و chunk طلایی را مشخص کنید", "warn"); return false; }
      await post(`/eval-sets/${set.id}/items`, { question: question.value, gold_chunk_id: picker.value.id });
      toast("پرسش افزوده شد", "ok"); onAdded();
    } }] });
}

/** از صفحه بررسی chunkها: ساخت پرسش ارزیابی با این chunk به‌عنوان پاسخ طلایی */
export async function addQuestionForChunk(chunk) {
  const sets = (await get(`/eval-sets?collection_id=${chunk.collection_id}`));
  const setSel = selectEl([...sets.map((s) => [s.id, s.name]), ["__new", "+ مجموعه جدید"]]);
  const newName = h("input", { type: "text", placeholder: "نام مجموعه جدید", hidden: sets.length > 0 });
  setSel.addEventListener("change", () => { newName.hidden = setSel.value !== "__new"; });
  const question = h("textarea", { rows: 2, placeholder: "پرسشی که پاسخش در این chunk است" });
  modal({ title: "افزودن پرسش ارزیابی برای این chunk", body: h("div", { class: "stack" },
    h("div", { class: "pre small", style: { maxHeight: "140px" } }, chunk.body.slice(0, 500)),
    field("پرسش", question), field("مجموعه ارزیابی", setSel), newName),
  actions: [{ label: "انصراف" }, { label: "افزودن", class: "primary", onClick: async () => {
    if (!question.value.trim()) { toast("پرسش را وارد کنید", "warn"); return false; }
    let sid = setSel.value;
    if (sid === "__new") sid = (await post("/eval-sets", { collection_id: chunk.collection_id, name: newName.value.trim() || "پرسش‌های دستی" })).id;
    await post(`/eval-sets/${sid}/items`, { question: question.value, gold_chunk_id: chunk.id });
    toast("پرسش به مجموعه ارزیابی افزوده شد", "ok");
  } }] });
}
