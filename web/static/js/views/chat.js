// گفتگو با اسناد: پاسخ استریم‌شده با ارجاع به منابع

import { del, get, patch, post, streamChat } from "../api.js";
import {
  collectionSelect, currentCollectionId, getCollections, getSystem, modelsList, plannedModels, postprocessControls, showChunk, stagesBar,
} from "../state.js";
import {
  clear, confirmDialog, emptyState, faNum, field, fmtDate, h, highlight, icon, modal, persianize, prefs, renderMarkdown, seg, selectEl,
  spinner, switchEl, toast, toastError,
} from "../ui.js";

// پرسش‌های پیشنهادی را سرور از داده‌های همان پایگاه دانش و پرسش‌های قبلی کاربر می‌سازد؛
// این‌ها فقط وقتی نمایش داده می‌شوند که سرور در دسترس نباشد
const SUGGESTIONS = [
  "خلاصه‌ای از مهم‌ترین نکات اسناد بده.",
];
const TABLE_SUGGESTIONS = [
  "تعداد فروش، مبلغ فروش و تخفیف را به تفکیک شعبه نشان بده.",
  "جمع مبلغ فروش و تخفیف هر تامین‌کننده چقدر است؟",
  "۱۰ کالای پرفروش از نظر مبلغ فروش کدام‌اند؟",
  "کدام شعبه بیشترین تعداد فروش را داشته است؟",
];

export async function render(root) {
  const [sys, cols] = await Promise.all([getSystem(), getCollections()]);
  if (!cols.length) {
    root.append(h("div", { class: "card" }, emptyState("db", "ابتدا یک پایگاه دانش بسازید",
      "برای گفتگو با اسناد، یک پایگاه دانش بسازید و فایل‌های خود را بارگذاری کنید.",
      h("a", { class: "btn primary", href: "#/collections" }, icon("plus"), "پایگاه‌های دانش"))));
    return;
  }

  root.classList.add("fill");
  let colId = currentCollectionId(cols);
  let controller = null;
  const PREFS_VERSION = 2;
  let opts = prefs.get("chat-opts", {});
  if (opts.v !== PREFS_VERSION) opts = { ...opts, llm_provider: undefined, llm_model: undefined };  // تنظیمات نسخه قدیم
  // مدل پیش‌فرض: همان که در .env تعیین شده؛ اگر در دسترس نیست، بهترین گزینه موجود.
  // انتخاب خودکار ذخیره نمی‌شود تا با در دسترس قرار گرفتن مدل بهتر (مثلاً افزودن کلید OpenAI) خودش عوض شود.
  const avail = (p) => sys.providers[p]?.available;
  let defProvider = sys.defaults.llm_provider, defModel = sys.defaults.llm_model;
  if (!avail(defProvider)) {
    const alt = ["openai", "ollama", "huggingface"].find(avail);
    if (alt) {
      defProvider = alt;
      defModel = (alt === "ollama" && sys.providers.ollama.models[0]) || sys.presets.llm[alt][0];
    }
  }
  const userChoice = opts.llm_provider && avail(opts.llm_provider);
  const o = {
    llm_provider: userChoice ? opts.llm_provider : defProvider, llm_model: userChoice ? opts.llm_model : defModel,
    mode: opts.mode || "hybrid", k: opts.k || 5, condense: opts.condense ?? true, temperature: opts.temperature ?? 0.1,
    rerank: typeof opts.rerank === "string" ? opts.rerank : "none", jev: !!opts.jev,
    jev_threshold: opts.jev_threshold ?? sys.postprocess.jev.threshold, jev_answerable: opts.jev_answerable ?? true,
  };
  // فقط وقتی کاربر خودش مدل را عوض کند، انتخاب مدل ذخیره می‌شود
  let llmChosen = !!userChoice;
  const save = () => {
    prefs.set("chat-opts", {
      ...o, v: PREFS_VERSION, llm_provider: llmChosen ? o.llm_provider : undefined, llm_model: llmChosen ? o.llm_model : undefined });
    refreshModels();
  };
  // کارت «مدل‌های در حال استفاده»: با هر تغییر تنظیمات به‌روز می‌شود
  const modelsBox = h("div");
  function refreshModels() {
    clear(modelsBox, persianize(modelsList(plannedModels(sys, cols.find((c) => c.id === colId), o))));
  }
  // تاریخچه‌های نسخه قبل که در مرورگر ذخیره می‌شدند دیگر استفاده نمی‌شوند
  for (const c of cols) { try { localStorage.removeItem(`rag-chat-${c.id}`); } catch (e) { /* مرورگر بدون storage */ } }

  // --- جلسه‌های گفتگو (روی سرور ذخیره می‌شوند) ---
  let sessionId = null, sessions = [], messages = [];
  const sessKey = () => `chat-session-${colId}`;
  const sessionsBox = h("div", { class: "stack", style: { gap: "4px", maxHeight: "280px", overflowY: "auto" } });

  async function loadSessions() {
    sessions = await get(`/chat/sessions?collection_id=${colId}`);
    renderSessions();
  }

  function renderSessions() {
    clear(sessionsBox, sessions.length ? sessions.map((s) => {
      const active = s.id === sessionId;
      return h("div", { class: "row", style: { gap: "2px", flexWrap: "nowrap", borderRadius: "8px",
        background: active ? "var(--accent-soft)" : "transparent" } },
      h("button", { class: "btn ghost", style: { flex: 1, minWidth: 0, justifyContent: "flex-start", display: "grid", gap: 0,
        textAlign: "right", padding: "4px 8px", color: active ? "var(--accent)" : null }, "aria-current": active ? "true" : null,
        onclick: () => openSession(s.id) },
      h("span", { style: { fontWeight: active ? 700 : 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
        s.title || "گفتگوی بدون عنوان"),
      persianize(h("span", { class: "tiny muted" }, `${faNum(Math.ceil(s.messages / 2))} پرسش · ${fmtDate(s.updated_at)}`))),
      h("button", { class: "btn ghost sm icon", title: "تغییر نام", "aria-label": "تغییر نام", onclick: () => renameSession(s) }, icon("edit")),
      h("button", { class: "btn ghost sm icon", title: "حذف این گفتگو", "aria-label": "حذف", style: { color: "var(--err)" },
        onclick: () => deleteSession(s) }, icon("trash")));
    }) : h("div", { class: "muted small" }, "هنوز گفتگویی ذخیره نشده است."));
  }

  async function openSession(id) {
    controller?.abort();
    sessionId = id;
    prefs.set(sessKey(), id);
    messages = id ? (await get(`/chat/sessions/${id}`)).messages_list : [];
    renderMessages(); renderSessions(); input.focus();
  }

  async function openLatest() {
    await loadSessions();
    const saved = prefs.get(sessKey(), null);
    await openSession(sessions.some((s) => s.id === saved) ? saved : (sessions[0]?.id ?? null));
  }

  async function deleteSession(s) {
    if (!(await confirmDialog("حذف گفتگو", `گفتگوی «${s.title || "بدون عنوان"}» و همه پیام‌هایش حذف شود؟`))) return;
    try {
      await del(`/chat/sessions/${s.id}`);
      if (s.id === sessionId) sessionId = null;
      await loadSessions();
      if (!sessionId) await openSession(sessions[0]?.id ?? null);
    } catch (e) { toastError(e); }
  }

  async function clearAll() {
    if (!sessions.length) return;
    if (!(await confirmDialog("پاک کردن همه گفتگوها", `همه ${faNum(sessions.length)} گفتگوی این پایگاه دانش برای همیشه حذف شوند؟`))) return;
    try { await del(`/chat/sessions?collection_id=${colId}`); await loadSessions(); await openSession(null); toast("همه گفتگوها پاک شدند", "ok"); }
    catch (e) { toastError(e); }
  }

  function renameSession(s) {
    const title = h("input", { type: "text", value: s.title || "", maxlength: 120 });
    modal({ title: "تغییر نام گفتگو", body: field("عنوان", title), actions: [{ label: "انصراف" }, { label: "ذخیره", class: "primary",
      onClick: async () => { if (!title.value.trim()) return false; await patch(`/chat/sessions/${s.id}`, { title: title.value }); await loadSessions(); } }] });
  }

  // --- پنل تنظیمات ---
  const colSel = await collectionSelect((v) => { colId = v; refreshModels(); openLatest().catch(toastError); });
  const provider = selectEl(Object.keys(sys.provider_labels).map((p) => [p, sys.provider_labels[p] + (sys.providers[p].available ? "" : " ⚠")]), o.llm_provider);
  const model = h("input", { type: "text", class: "ltr", list: "llm-models", value: o.llm_model });
  const dl = h("datalist", { id: "llm-models" });
  const syncModels = (reset) => {
    const list = [...new Set([...(sys.presets.llm[provider.value] || []), ...(provider.value === "ollama" ? sys.providers.ollama.models : [])])];
    clear(dl, list.map((m) => h("option", { value: m })));
    if (reset) { model.value = list[0] || ""; o.llm_model = model.value; }
    o.llm_provider = provider.value;
  };
  provider.addEventListener("change", () => { llmChosen = true; syncModels(true); save(); });
  model.addEventListener("change", () => { llmChosen = true; o.llm_model = model.value.trim(); save(); });
  model.addEventListener("input", () => { o.llm_model = model.value.trim(); refreshModels(); });
  syncModels(false);
  const mode = seg([["dense", "برداری"], ["bm25", "BM25"], ["hybrid", "ترکیبی"]], o.mode, (v) => { o.mode = v; save(); });
  const kInput = h("input", { type: "range", min: 1, max: 10, value: o.k });
  const kVal = h("b", {}, faNum(o.k));
  kInput.addEventListener("input", () => { o.k = Number(kInput.value); kVal.textContent = faNum(o.k); save(); });
  const temp = h("input", { type: "number", min: 0, max: 1.5, step: 0.1, value: o.temperature });
  temp.addEventListener("change", () => { o.temperature = Number(temp.value); save(); });
  const pp = postprocessControls(sys, o, (v) => { Object.assign(o, v); save(); });
  Object.assign(o, pp.values());
  refreshModels();
  const condense = switchEl("بازنویسی پرسش‌های پیگیری", o.condense);
  condense.input.addEventListener("change", () => { o.condense = condense.input.checked; save(); });

  const side = h("aside", { class: "side-panel" },
    h("div", { class: "card stack", style: { gap: "10px" } },
      h("div", { class: "row" }, h("h3", { style: { margin: 0 } }, "گفتگوها"), h("span", { class: "spacer" }),
        h("button", { class: "btn primary sm", onclick: () => openSession(null) }, icon("plus"), "گفتگوی جدید")),
      field("پایگاه دانش", colSel),
      sessionsBox,
      h("button", { class: "btn ghost sm", style: { color: "var(--err)", justifySelf: "start" }, onclick: clearAll },
        icon("trash"), "پاک کردن همه گفتگوها")),
    h("div", { class: "card stack", style: { gap: "12px" } },
      h("h3", { style: { margin: 0 } }, "تنظیمات گفتگو"),
      field("مدل زبانی", provider), field("نام مدل", model), dl,
      field("روش بازیابی", mode.el),
      h("label", { class: "field" }, h("span", {}, "تعداد منابع (k): ", kVal), kInput),
      field("دما", temp),
      condense.el),
    h("div", { class: "card stack", style: { gap: "10px" } },
      h("h3", { style: { margin: 0 } }, "مرحله پس از بازیابی"),
      pp.el),
    h("div", { class: "card stack", style: { gap: "10px" } },
      h("h3", { style: { margin: 0 } }, "مدل‌های در حال استفاده"),
      h("p", { class: "hint", style: { margin: 0 } }, "با تنظیمات فعلی، هر مرحله با این مدل و از این منبع اجرا می‌شود:"),
      modelsBox),
    h("div", { class: "card small muted" },
      h("b", {}, "چه اتفاقی می‌افتد؟"),
      h("ol", { style: { margin: "6px 0 0", paddingRight: "18px" } },
        h("li", {}, "پرسش از clean_fa عبور می‌کند (ارقام، ی/ک عربی، نیم‌فاصله)."),
        h("li", {}, "بازیابی برداری و BM25 با RRF ترکیب می‌شوند."),
        h("li", {}, "اگر روشن باشند: Rerank ترتیب را اصلاح می‌کند و Jev متن‌های نامرتبط را حذف و کافی بودن شواهد را بررسی می‌کند."),
        h("li", {}, "LLM فقط بر اساس منابع و با ارجاع [n] پاسخ می‌دهد."),
        h("li", {}, "اگر فایل اکسل فروش در پایگاه دانش باشد، پرسش‌های آماری (جمع، مقایسه، به تفکیک شعبه/تامین‌کننده) به SQL تبدیل و روی همه سطرها دقیق محاسبه می‌شوند."),
        h("li", {}, "پرسش‌های پیشنهادی از داده‌های همین پایگاه دانش (نام واقعی شعبه‌ها، کالاها و بخش‌های اسناد)، نتیجه آخرین پاسخ و پرسش‌های قبلی شما ساخته می‌شوند.")),
      h("a", { href: "#/guide", class: "small" }, "نمودار کامل جریان در راهنما ←")));

  // --- پیام‌ها ---
  const scroll = h("div", { class: "chat-scroll", "aria-live": "polite" });
  const input = h("textarea", { rows: 1, placeholder: "پرسش خود را بنویسید… (Enter ارسال، Shift+Enter خط جدید)" });
  const sendBtn = h("button", { class: "btn primary", "aria-label": "ارسال" }, icon("send"), "ارسال");
  const autoGrow = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 200) + "px"; };
  input.addEventListener("input", autoGrow);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  sendBtn.addEventListener("click", () => (controller ? controller.abort() : send()));

  function renderMessages() {
    clear(scroll);
    if (!messages.length) {
      const tabular = (cols.find((c) => c.id === colId)?.table_rows || 0) > 0;
      scroll.append(h("div", { class: "empty", style: { margin: "auto 0" } }, icon("chat"),
        h("h3", {}, "از اسناد خود بپرسید"),
        h("p", {}, tabular ? "این پایگاه دانش داده جدولی (اکسل) دارد: جمع‌ها و مقایسه‌ها مستقیم از سطرهای فایل محاسبه می‌شوند."
          : "پاسخ فقط از متن اسناد ساخته می‌شود و هر ادعا به منبع ارجاع دارد."),
        suggestBox(false, tabular ? TABLE_SUGGESTIONS : SUGGESTIONS)));
      return;
    }
    for (const m of messages) scroll.append(m.role === "user" ? userMsg(m.content) : assistantMsg(m, false));
    const last = messages[messages.length - 1];
    if (last.role === "assistant" && last.content && !last.error) scroll.append(suggestBox(true));
    scroll.scrollTop = scroll.scrollHeight;
  }

  // پرسش‌های پیشنهادی هوشمند: سرور از داده‌های همین پایگاه دانش، گفتگوی فعلی و پرسش‌های قبلی کاربر می‌سازد
  let suggestSeq = 0;
  function suggestBox(followup, fallback = []) {
    const seq = ++suggestSeq;
    const list = h("div", { class: "suggest" }, [0, 1, 2, 3].map(() => h("div", { class: "skel", "aria-hidden": "true" })));
    const note = h("span", { class: "tiny muted" }, followup ? "در حال ساخت پرسش‌های بعدی…" : "در حال ساخت پیشنهاد از داده‌های این پایگاه دانش…");
    const head = h("div", { class: "suggest-head small muted" }, icon("spark"), h("b", {}, followup ? "پرسش‌های پیشنهادی بعدی" : "پرسش‌های پیشنهادی"), note);
    const box = h("div", { class: followup ? "followups" : null, style: followup ? null : { marginTop: "8px", textAlign: "right" } }, head, list);
    const fill = (items) => clear(list, items.map((s) => h("button", { onclick: () => { input.value = s; send(); } }, s)));
    post("/chat/suggestions", { collection_id: colId, session_id: sessionId, llm_provider: o.llm_provider, llm_model: o.llm_model, n: 4 })
      .then((r) => {
        if (seq !== suggestSeq && followup) return;
        if (!r.suggestions?.length) throw new Error("empty");
        fill(r.suggestions);
        const c = r.context || {};
        const basis = [c.tabular ? "داده‌های فروش این پایگاه دانش" : "محتوای اسناد این پایگاه دانش"];
        if (c.session_questions) basis.push("همین گفتگو");
        if (c.past_questions) basis.push(`${faNum(c.past_questions)} پرسش قبلی شما`);
        note.textContent = `بر اساس ${basis.join("، ")}${r.source === "data" ? " (بدون LLM)" : ""}`;
        if (followup && scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 260) scroll.scrollTop = scroll.scrollHeight;
      })
      .catch(() => {
        if (followup || !fallback.length) { box.remove(); return; }
        fill(fallback); note.textContent = "";
      });
    return box;
  }

  const userMsg = (text) => h("div", { class: "msg user" }, text);

  function assistantMsg(m, live) {
    const bubble = h("div", { class: "bubble" });
    const srcBox = h("div", { class: "sources" });
    const meta = h("div", { class: "meta" });
    const stagesBox = h("div", { style: { marginTop: "8px" } });
    const el = h("div", { class: "msg assistant" }, bubble, srcBox, stagesBox, meta);
    // streaming=true یعنی درخواست هنوز در جریان است؛ نشانگر بارگذاری فقط در این حالت و بدون خطا نمایش داده می‌شود
    const update = (streaming) => {
      clear(bubble);
      if (m.content) bubble.append(renderMarkdown(m.content, (n) => focusSource(srcBox, n)));
      else if (streaming && !m.error) {
        bubble.append(h("span", { class: "row muted" }, spinner(), m.info ? "در حال نوشتن پاسخ…" : "در حال جستجو در اسناد…"));
      }
      if (streaming && m.content) bubble.lastElementChild?.lastElementChild?.classList.add("cursor");
      if (m.error) bubble.append(h("div", { class: "alert err", role: "alert" }, h("b", {}, "خطا: "), m.error));
      else if (!streaming && m.aborted) bubble.append(h("div", { class: "muted small" }, "(متوقف شد)"));
      else if (!streaming && !m.content) bubble.append(h("div", { class: "muted small" }, "پاسخی دریافت نشد."));
      const ans = m.info?.answerable;
      if (ans && !ans.ok) bubble.append(persianize(h("div", { class: "alert warn small" },
        `Jev تشخیص داد متن‌های بازیابی‌شده برای پاسخ کافی نیستند (احتمال ${ans.prob} کمتر از آستانه ${ans.threshold})؛ LLM فراخوانی نشد.`)));
      if (m.info?.dropped && m.info?.jev && !m.hits?.length) bubble.append(persianize(h("div", { class: "alert warn small" },
        `Jev همه ${m.info.dropped} متن کاندید را نامرتبط تشخیص داد.`)));
      renderSources(srcBox, m);
      clear(stagesBox, persianize(stagesBar(m.info)),
        m.info?.models ? h("div", { style: { marginTop: "6px" } }, modelsList(m.info.models, { compact: true })) : null);
      clear(meta);
      if (m.info) {
        if (m.info.rewritten) meta.append(h("span", {}, `پرسش بازنویسی‌شده: ${m.info.rewritten}`));
        meta.append(h("span", {}, `پرسش نرمال‌شده: ${m.info.query}`));
        const t = m.info.timings || {};
        meta.append(h("span", {}, `${m.info.mode === "analytics" ? "SQL" : "بازیابی"} ${faNum(t.total_ms ?? 0)} ms`));
        if (m.done) meta.append(h("span", {}, `اولین توکن ${faNum(m.done.first_token_ms ?? 0)} ms · کل ${faNum(m.done.elapsed_ms)} ms`));
        meta.append(h("button", { class: "btn ghost sm", title: "کپی پاسخ", onclick: () => navigator.clipboard?.writeText(m.content).then(() => toast("کپی شد", "ok", 1500)) }, icon("copy")));
      }
      persianize(meta);
    };
    el._update = update;
    update(live);
    return el;
  }

  // نتیجه کوئری مستقیم از داده‌ها (بدون واسطه LLM) تا اعداد پاسخ قابل بررسی باشند
  function analyticsBlock(a) {
    const isNum = (v) => /^-?[\d,.]+$/.test(v);
    return h("details", { class: "sources", open: true },
      h("summary", {}, `محاسبه دقیق از داده‌های اکسل · ${faNum(a.row_count)} سطر نتیجه${a.truncated ? " (فقط بخشی نمایش داده شده)" : ""}`),
      a.row_count ? persianize(h("div", { class: "table-wrap", style: { maxHeight: "340px", marginTop: "6px" } }, h("table", {},
        h("thead", {}, h("tr", {}, a.columns.map((c) => h("th", {}, c)))),
        h("tbody", {}, a.rows.map((r) => h("tr", {}, r.map((v) => h("td", { class: isNum(v) ? "num" : null }, v)))))))) :
        h("div", { class: "muted small" }, "نتیجه کوئری خالی بود."),
      h("details", { style: { marginTop: "6px" } }, h("summary", { class: "tiny muted" }, "کوئری SQL اجراشده"),
        h("pre", { class: "ltr mono tiny", style: { whiteSpace: "pre-wrap" } }, a.sql)));
  }

  function renderSources(box, m) {
    clear(box);
    if (m.info?.analytics) { box.append(analyticsBlock(m.info.analytics)); return; }
    const hits = m.hits || [];
    if (!hits.length) return;
    const details = h("details", { class: "sources", open: hits.length <= 3 ? true : undefined },
      h("summary", {}, `${faNum(hits.length)} منبع بازیابی‌شده`),
      hits.map((hit, i) => {
        const text = h("div", { class: "src-text" }, highlight(hit.body, m.info?.query));
        return h("div", { class: "src", "data-n": i + 1 },
          h("div", { class: "src-head" },
            h("span", { class: "n" }, `[${faNum(i + 1)}]`), h("span", { class: "title" }, hit.source),
            hit.page ? h("span", { class: "badge" }, `ص ${faNum(hit.page)}`) : null,
            hit.section ? h("span", { class: "muted small" }, hit.section) : null,
            h("span", { class: "spacer" }),
            scoreBadges(hit),
            h("button", { class: "btn ghost sm", onclick: () => text.classList.toggle("open") }, "متن کامل"),
            h("button", { class: "btn ghost sm", title: "مشاهده کنار صفحه PDF", onclick: () => showChunk(hit) }, icon("eye"))),
          persianize(text));
      }));
    box.append(details);
  }

  function focusSource(box, n) {
    const d = box.querySelector("details"); if (d) d.open = true;
    const el = box.querySelector(`.src[data-n="${n}"]`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  }

  async function send() {
    const q = input.value.trim();
    if (!q || controller) return;
    if (!o.llm_model) { toast("نام مدل زبانی را وارد کنید", "warn"); return; }
    // حالت «در حال ارسال» از همین لحظه، تا Enter دوباره پیش از ساخته شدن جلسه، جلسه دوم نسازد
    controller = new AbortController();
    clear(sendBtn, icon("stop"), "توقف");
    if (!sessionId) {  // جلسه جدید با اولین پرسش ساخته می‌شود
      try {
        sessionId = (await post("/chat/sessions", { collection_id: colId })).id;
        prefs.set(sessKey(), sessionId);
      } catch (e) {
        toastError(e);
        controller = null; clear(sendBtn, icon("send"), "ارسال");
        return;
      }
    }
    input.value = ""; autoGrow();
    suggestSeq++;  // پیشنهادهای در حال بارگذاری دیگر نمایش داده نشوند
    if (!messages.length) clear(scroll);
    scroll.querySelectorAll(".followups").forEach((e) => e.remove());
    messages.push({ role: "user", content: q });
    scroll.append(userMsg(q));
    const m = { role: "assistant", content: "", hits: [], info: null };
    messages.push(m);
    const el = assistantMsg(m, true);
    scroll.append(el);
    scroll.scrollTop = scroll.scrollHeight;
    let raf = 0;
    const repaint = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; el._update(true); scroll.scrollTop = scroll.scrollHeight; }); };
    try {
      // تاریخچه را سرور از همین جلسه می‌خواند و پرسش و پاسخ را ذخیره می‌کند
      await streamChat({ collection_id: colId, question: q, session_id: sessionId, llm_provider: o.llm_provider, llm_model: o.llm_model,
        mode: o.mode, k: o.k, rerank: o.rerank, condense: o.condense, temperature: o.temperature,
        jev: o.jev, jev_threshold: o.jev_threshold, jev_answerable: o.jev_answerable }, {
        sources: (d) => { m.hits = d.hits; m.info = d; repaint(); },
        token: (d) => { m.content += d.t; repaint(); },
        done: (d) => { m.done = d; },
        error: (d) => { m.error = d.message; },
      }, controller.signal);
    } catch (e) {
      if (e.name === "AbortError") m.content += m.content ? "\n\n*(متوقف شد)*" : "*(متوقف شد)*";
      else { m.error = e.message; toastError(e); }
    } finally {
      controller = null;
      cancelAnimationFrame(raf);
      clear(sendBtn, icon("send"), "ارسال");
      el._update(false);
      if (m.content && !m.error && !m.aborted) scroll.append(suggestBox(true));
      loadSessions().catch(() => {});  // عنوان و ترتیب جلسه‌ها به‌روز شود
      input.focus();
    }
  }

  root.append(h("div", { class: "chat-layout" },
    h("section", { class: "chat-main" }, scroll, h("div", { class: "composer" }, input, sendBtn)), side));
  await openLatest();
  return () => controller?.abort();
}

export function scoreBadges(hit) {
  return h("span", { class: "row", style: { gap: "4px" } },
    hit.dense_rank ? h("span", { class: "badge", title: `شباهت کسینوسی ${hit.dense_score}` }, `بردار #${faNum(hit.dense_rank)}`) : null,
    hit.bm25_rank ? h("span", { class: "badge", title: `امتیاز BM25 ${hit.bm25_score}` }, `BM25 #${faNum(hit.bm25_rank)}`) : null,
    hit.rerank_score !== null && hit.rerank_score !== undefined ? h("span", { class: "badge info" }, `rerank ${faNum(hit.rerank_score)}`) : null,
    hit.jev_prob !== null && hit.jev_prob !== undefined ? h("span", { class: `badge ${hit.jev_prob >= 0.5 ? "ok" : "warn"}`,
      title: "احتمال ارتباط از Jev" }, `Jev ${faNum(Math.round(hit.jev_prob * 100))}٪`) : null);
}
