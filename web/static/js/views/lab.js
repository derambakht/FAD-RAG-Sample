// آزمایشگاه متن: clean_fa گام‌به‌گام، مقایسه ابزارهای استخراج PDF و پیش‌نمایش chunkبندی بدون embedding

import { api, get, post } from "../api.js";
import { METHOD_LABEL, STRATEGY_LABEL, getSystem, loadingBlock, settingsForm } from "../state.js";
import { clear, faNum, field, h, icon, persianize, prefs, seg, spinner, toastError } from "../ui.js";

const SAMPLE = "اـــــیران كشوري با تاريخ ۱۴۰۲/۰۵/۱۲ و جمعيت ٨٥ ميليون نفر است. ﻫﻮﺵ مصنوعي در دانشگاه هاي آن تدريس مي شود؛ " +
  "هزينه دوره ۱۲٬۵۰۰٫۷۵ تومان و سهم آن ۳۰٪ است. منظور از» هنرجو «شخصي است كه عِلْم مي آموزد.";

export async function render(root) {
  const sys = await getSystem();
  let tab = prefs.get("lab-tab", "normalize");
  let file = prefs.get("lab-file", null);
  const body = h("div");
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const TABS = [["normalize", "نرمال‌سازی گام‌به‌گام"], ["compare", "مقایسه ابزارهای استخراج"], ["preview", "پیش‌نمایش chunkبندی"]];
  const renderTabs = () => clear(tabs, TABS.map(([k, l]) => h("button", { role: "tab", class: tab === k ? "on" : "", "aria-selected": String(tab === k),
    onclick: () => { tab = k; prefs.set("lab-tab", k); renderTabs(); show(); } }, l)));

  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "آزمایشگاه متن"),
    h("p", {}, "در RAG فارسی بیشتر خطاها از مرحله استخراج و پاک‌سازی متن می‌آیند، نه از انتخاب مدل. اینجا هر مرحله را جداگانه ببینید."))),
  tabs, body);

  // --- فایل مشترک تب‌های ۲ و ۳ ---
  const fileBar = h("div", { class: "card", style: { marginBottom: "16px" } });
  const fileInput = h("input", { type: "file", accept: sys.supported_ext.join(","), hidden: true });
  fileInput.addEventListener("change", async () => {
    const f = fileInput.files[0]; if (!f) return;
    const form = new FormData(); form.append("file", f);
    clear(fileBar, h("div", { class: "row" }, spinner(), "در حال بارگذاری…"));
    try { file = await api("/lab/upload", { method: "POST", form }); prefs.set("lab-file", file); }
    catch (e) { toastError(e); }
    fileInput.value = ""; show();
  });
  const renderFileBar = () => clear(fileBar, h("div", { class: "row" },
    file ? [h("b", {}, file.filename), h("span", { class: "badge" }, `${faNum(file.pages)} صفحه`)] : h("span", { class: "muted" }, "یک فایل PDF/DOCX/TXT برای آزمایش انتخاب کنید (در ایندکس ذخیره نمی‌شود)."),
    h("span", { class: "spacer" }), h("button", { class: "btn", onclick: () => fileInput.click() }, icon("upload"), file ? "فایل دیگر" : "انتخاب فایل"), fileInput));

  function show() {
    clear(body);
    if (tab === "normalize") return normalizeTab(body);
    renderFileBar(); body.append(fileBar);
    if (!file) return;
    if (tab === "compare") compareTab(body);
    else previewTab(body);
  }

  async function guard(fn) {
    try { await fn(); } catch (e) {
      if (e.status === 404) { file = null; prefs.set("lab-file", null); show(); }
      toastError(e);
    }
  }

  // --- تب ۱ ---
  function normalizeTab(box) {
    const input = h("textarea", { rows: 5 }); input.value = prefs.get("lab-text", SAMPLE);
    const out = h("div", { class: "stack" });
    const run = async () => {
      prefs.set("lab-text", input.value);
      clear(out, loadingBlock());
      try {
        const r = await post("/lab/normalize", { text: input.value });
        clear(out,
          h("div", { class: "grid grid-2" }, statCard("قبل از clean_fa", r.before), statCard("بعد از clean_fa", r.after)),
          h("div", { class: "card stack", style: { gap: "10px" } }, h("h3", { style: { margin: 0 } }, "خروجی هر مرحله (ترتیب مهم است)"),
            r.steps.map((s, i) => h("div", { class: `step ${s.changed ? "changed" : ""}` },
              h("div", { class: "step-head" }, h("span", { class: "badge accent" }, faNum(i + 1)), s.name,
                h("span", { class: `badge ${s.changed ? "ok" : ""}` }, s.changed ? "تغییر داد" : "بدون تغییر")),
              h("div", { class: "pre", style: { maxHeight: "160px" } }, s.text)))));
      } catch (e) { toastError(e); clear(out); }
    };
    box.append(h("div", { class: "card stack", style: { marginBottom: "16px" } },
      field("متن ورودی (از PDF کپی کنید یا نمونه را ببینید)", input),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: run }, icon("play"), "اجرای clean_fa"),
        h("button", { class: "btn ghost", onclick: () => { input.value = SAMPLE; run(); } }, "متن نمونه پرخطا"))), out);
    run();
  }

  function statCard(title, s) {
    return persianize(h("div", { class: "card" }, h("h3", {}, title),
      h("dl", { class: "kv" },
        h("dt", {}, "امتیاز واژگان"), h("dd", {}, String(s.vocab)),
        h("dt", {}, "کاراکتر / توکن"), h("dd", {}, `${s.chars} / ${s.tokens}`),
        h("dt", {}, "شکل نمایشی حروف"), h("dd", {}, String(s.stats.presentation_forms)),
        h("dt", {}, "کاراکترهای ناسازگار"), h("dd", {}, s.odd.length ? h("span", { class: "ltr" },
          s.odd.map(([c, n]) => `${JSON.stringify(c)}${c.length === 1 ? ` U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}` : ""} ×${n}`).join("   "))
          : h("span", { class: "badge ok" }, "هیچ")))));
  }

  // --- تب ۲ ---
  function compareTab(box) {
    if (file.ext !== ".pdf") { box.append(h("div", { class: "alert" }, "مقایسه ابزارها فقط برای PDF است.")); return; }
    let page = 1, view = "cleaned";
    const pageInput = h("input", { type: "number", min: 1, max: file.pages, value: 1, style: { width: "90px" } });
    const out = h("div");
    const viewSeg = seg([["raw", "متن خام"], ["cleaned", "پس از clean_fa"]], view, (v) => { view = v; paint(); });
    let data = null;
    const paint = () => {
      if (!data) return;
      clear(out, h("div", { class: "cols", style: { gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))" } },
        h("div", { class: "card" }, h("h3", {}, `تصویر صفحه ${faNum(page)}`),
          h("img", { src: `/api/lab/${file.token}/pages/${page}.png?dpi=90`, alt: "تصویر صفحه", style: { width: "100%", border: "1px solid var(--line)", borderRadius: "8px", background: "#fff" } })),
        data.methods.map((m) => h("div", { class: "card" },
          h("div", { class: "card-head" }, h("h3", { class: "ltr", style: { textAlign: "right" } }, m.name),
            m.broken ? h("span", { class: "badge err" }, "خراب؛ OCR لازم است") : m.reversed ? h("span", { class: "badge warn" }, "معکوس اصلاح شد") : null),
          persianize(h("div", { class: "row tiny", style: { marginBottom: "8px" } },
            h("span", { class: "badge" }, `واژگان خام ${m.vocab_raw}`), h("span", { class: `badge ${m.vocab_clean > 0.8 ? "ok" : "warn"}` }, `پس از پاک‌سازی ${m.vocab_clean}`),
            h("span", { class: "badge" }, `شکل نمایشی ${m.stats.presentation_forms}`), m.stats.mojibake ? h("span", { class: "badge err" }, `mojibake ${m.stats.mojibake}`) : null)),
          h("div", { class: "pre", style: { maxHeight: "520px" }, dir: "rtl" }, (view === "raw" ? m.raw : m.cleaned) || "(خالی)")))));
    };
    const load = () => guard(async () => {
      page = Math.max(1, Math.min(file.pages, Number(pageInput.value) || 1));
      clear(out, loadingBlock("در حال استخراج با همه ابزارها…"));
      data = await get(`/lab/${file.token}/compare?page=${page}`);
      paint();
    });
    pageInput.addEventListener("change", load);
    box.append(h("div", { class: "row", style: { marginBottom: "14px" } }, h("label", { class: "row small" }, "صفحه", pageInput),
      h("span", { class: "muted small" }, `از ${faNum(file.pages)}`), viewSeg.el, h("span", { class: "spacer" }),
      h("span", { class: "hint" }, "قاعده: متن پر از Çáã یا مربع خالی یعنی فونت بدون ToUnicode و تنها راه OCR است.")), out);
    load();
  }

  // --- تب ۳ ---
  function previewTab(box) {
    const sf = settingsForm(prefs.get("lab-opts", {}), sys.defaults.settings);
    const out = h("div");
    const run = () => guard(async () => {
      prefs.set("lab-opts", sf.values());
      clear(out, loadingBlock("استخراج، پاک‌سازی و بخش‌بندی…"));
      const r = await post(`/lab/${file.token}/preview`, { options: sf.values() });
      const e = r.extract, a = r.audit, s = r.stats;
      clear(out, persianize(h("div", { class: "stack" },
        h("div", { class: "tiles" },
          tileEl("chunk", s.chunks), tileEl("میانگین توکن", s.avg_tokens), tileEl("بیشینه توکن", s.max_tokens),
          tileEl("بخش / عنوان", `${s.sections} / ${s.headings}`), tileEl("مشکوک", a.suspects), tileEl("واژگان میانگین", e.avg_vocab)),
        e.warnings.map((w) => h("div", { class: "alert warn small" }, w)),
        h("div", { class: "small muted" }, "ابزار استخراج: ", Object.entries(e.methods).map(([m, n]) => `${METHOD_LABEL[m] || m} (${n} صفحه)`).join("، "),
          ` · روش بخش‌بندی: ${STRATEGY_LABEL[sf.values().strategy]}`),
        h("div", { class: "stack", style: { gap: "8px" } }, r.chunks.map((c, i) => h("div", { class: "hit" },
          h("div", { class: "row small" }, h("span", { class: "rank" }, `#${i + 1}`), h("span", { class: "badge" }, `ص ${c.page}`),
            h("span", { class: "badge" }, `${c.tokens} توکن`), h("span", { class: "badge" }, `واژگان ${c.vocab}`),
            c.kind === "table" ? h("span", { class: "badge info" }, "جدول") : null,
            ...(c.flags || []).filter((f) => f !== "no_title").map((f) => h("span", { class: "badge warn" }, a.flag_labels[f])),
            h("span", { class: "muted tiny" }, c.section)),
          h("div", { class: "text small" }, c.body)))),
        r.truncated ? h("div", { class: "muted small" }, "فقط ۳۰۰ chunk اول نمایش داده شد.") : null)));
    });
    box.append(h("div", { class: "card stack", style: { marginBottom: "16px" } }, sf.el,
      h("div", { class: "row end" }, h("button", { class: "btn primary", onclick: run }, icon("play"), "اجرای پیش‌نمایش"))), out);
  }

  renderTabs(); show();
}

function tileEl(label, value) {
  return h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, typeof value === "number" ? faNum(value) : value));
}
