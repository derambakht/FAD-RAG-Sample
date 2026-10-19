// جزئیات پایگاه دانش: بارگذاری اسناد، پیشرفت ایندکس، فهرست اسناد و تنظیمات

import { api, del, get, patch, post, waitJob } from "../api.js";
import { BACKEND_LABEL, METHOD_LABEL, STRATEGY_LABEL, getSystem, invalidateCollections, loadingBlock, setCurrentCollection, settingsForm } from "../state.js";
import {
  clear, confirmDialog, emptyState, faNum, fmtDate, fmtSize, field, h, icon, modal, persianize, statusBadge, switchEl, toast, toastError,
} from "../ui.js";

export async function render(root, { id }) {
  setCurrentCollection(id);
  root.append(loadingBlock());
  const [col, sys] = await Promise.all([get(`/collections/${id}`), getSystem()]);
  clear(root);
  let alive = true;
  const watched = new Set();

  const tiles = h("div", { class: "tiles" });
  const jobsBox = h("div", { class: "stack" });
  const docsBox = h("div");

  const refresh = async () => {
    const [c, docs] = await Promise.all([get(`/collections/${id}`), get(`/collections/${id}/documents`)]);
    renderTiles(c); renderDocs(docs);
    return docs;
  };

  function renderTiles(c) {
    clear(tiles,
      tile("اسناد", c.documents), tile("chunkها", c.chunks),
      tile("بردارها", c.vectors ?? "—", c.vectors !== null && c.vectors !== c.chunks ? "با تعداد chunk برابر نیست" : null),
      tile("ابعاد بردار", c.embedding_dim ?? "—", c.embedding_dim ? null : "در اولین ایندکس تعیین می‌شود"));
    persianize(tiles);
  }

  function renderDocs(docs) {
    if (!docs.length) { clear(docsBox, emptyState("file", "سندی بارگذاری نشده", "فایل‌های PDF، DOCX، TXT، MD یا اکسل (XLSX، XLS، CSV) را در کادر بالا رها کنید.")); return; }
    const rows = docs.map((d) => {
      const s = d.stats || {};
      const detail = h("tr", { hidden: true }, h("td", { colspan: 7 }, docDetail(d)));
      const tr = h("tr", {},
        h("td", {}, h("button", { class: "btn ghost sm", "aria-label": "جزئیات", onclick: () => { detail.hidden = !detail.hidden; } }, "▾"),
          h("b", {}, d.filename), h("div", { class: "tiny muted" }, `${fmtSize(d.size)} · ${fmtDate(d.created_at)}`)),
        h("td", {}, statusBadge(d.status), d.error ? h("div", { class: "tiny", style: { color: "var(--err)", maxWidth: "280px" } }, d.error) : null),
        h("td", { class: "num" }, faNum(d.pages || 0)),
        h("td", { class: "num" }, faNum(d.chunks || 0)),
        h("td", { class: "num" }, s.avg_vocab !== undefined ? faNum(s.avg_vocab) : "—"),
        h("td", {}, liveOverlaps(d, docs).length ? h("button", { class: "badge err", style: { border: 0, cursor: "pointer" },
          title: "این سند با سند دیگری هم‌پوشانی دارد؛ برای تصمیم کلیک کنید", onclick: () => overlapDialog(d, liveOverlaps(d, docs)) },
          "نسخه تکراری") : null,
        (s.warnings || []).length ? h("span", { class: "badge warn", title: s.warnings.join("\n") }, `${faNum(s.warnings.length)} هشدار`) : null,
          s.audit ? h("span", { class: `badge ${s.audit.suspects ? "warn" : "ok"}` }, `${faNum(s.audit.suspects)} مشکوک`) : null),
        h("td", {}, h("div", { class: "row", style: { flexWrap: "nowrap", gap: "4px" } },
          h("a", { class: "btn sm ghost", href: `#/audit?collection=${id}&document=${d.id}`, title: "بررسی chunkها" }, icon("audit")),
          h("a", { class: "btn sm ghost", href: `/api/documents/${d.id}/file`, title: "دانلود", download: "" }, icon("download")),
          h("button", { class: "btn sm ghost", title: "ایندکس مجدد", disabled: d.status === "processing", onclick: () => reindexDialog(d) }, icon("refresh")),
          h("button", { class: "btn sm ghost", title: "حذف", style: { color: "var(--err)" }, disabled: d.status === "processing", onclick: async () => {
            if (!(await confirmDialog("حذف سند", `«${d.filename}» و همه chunkها و بردارهای آن حذف شوند؟`))) return;
            try { await del(`/documents/${d.id}`); toast("سند حذف شد", "ok"); invalidateCollections(); refresh(); } catch (e) { toastError(e); }
          } }, icon("trash")))));
      return [tr, detail];
    });
    clear(docsBox, h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["سند", "وضعیت", "صفحه", "chunk", "امتیاز واژگان", "کیفیت", ""].map((t, i) =>
        h("th", { class: [2, 3, 4].includes(i) ? "num" : "" }, t)))),
      h("tbody", {}, rows))));
    persianize(docsBox);
    // سندهای در صف/در حال پردازش که job آنها را از قبل نمی‌شناسیم
    if (docs.some((d) => d.status === "pending" || d.status === "processing")) watchActive();
  }

  async function watchActive() {
    const jobs = await get("/jobs?active=true");
    for (const j of jobs) if (j.meta?.collection_id === id) watchJob(j);
  }

  function watchJob(job) {
    if (watched.has(job.id)) return;
    watched.add(job.id);
    const bar = h("i", { style: { width: "0%" } });
    const msg = h("span", { class: "small muted" }, job.message);
    const card = h("div", { class: "card", style: { padding: "12px 16px" } },
      h("div", { class: "row" }, h("b", { class: "small" }, job.title), h("span", { class: "spacer" }), msg,
        h("button", { class: "btn ghost sm", onclick: () => post(`/jobs/${job.id}/cancel`).catch(toastError) }, "لغو")),
      h("div", { class: "progress", style: { marginTop: "8px" } }, bar));
    jobsBox.append(card);
    waitJob(job.id, (j) => { bar.style.width = `${Math.round(j.progress * 100)}%`; msg.textContent = j.message; }).then((j) => {
      card.remove(); watched.delete(job.id);
      if (!alive) return;
      if (j.status === "done") toast(`${j.title}: ${faNum(j.result?.chunks ?? 0)} chunk ساخته شد`, "ok");
      else if (j.status === "error") {
        toast(`${j.title}: ${j.error}`, "err", 9000);
        if (j.meta?.replaces?.length) toast("چون پردازش نسخه جدید ناموفق بود، نسخه قبلی حذف نشد و دست‌نخورده باقی ماند.", "warn", 9000);
      }
      (j.result?.replaced || []).forEach((f) => toast(`نسخه قبلی «${f}» حذف و با نسخه جدید جایگزین شد`, "ok", 7000));
      (j.result?.warnings || []).forEach((w) => toast(w, "warn", 8000));
      invalidateCollections();
      refresh().then((docs) => {
        // محتوای سند جدید با سند دیگری یکی است (مثلاً همان گزارش با نام دیگر): کاربر تصمیم بگیرد
        const doc = docs.find((d) => d.id === j.meta?.document_id);
        const ov = liveOverlaps(doc, docs);
        if (j.status === "done" && ov.length) overlapDialog(doc, ov);
      });
    }).catch(toastError);
  }

  // --- بارگذاری ---
  const fileInput = h("input", { type: "file", multiple: true, accept: sys.supported_ext.join(","), hidden: true });
  const override = switchEl("تنظیمات اختصاصی برای این بارگذاری", false);
  const sf = settingsForm(col.settings, sys.defaults.settings);
  const sfBox = h("div", { hidden: true, style: { marginTop: "12px" } }, sf.el);
  override.input.addEventListener("change", () => { sfBox.hidden = !override.input.checked; });

  async function upload(files) {
    if (!files.length) return;
    // نسخه قبلی همین سندها (همان نام، یا نام همراه با «(1)»، «نسخه ۲»، «اصلاح شده»، ...)
    let replace = {};
    try {
      const check = await post(`/collections/${id}/documents/check`, { files: files.map((f) => f.name) });
      const conflicts = check.files.filter((c) => c.previous.length);
      if (conflicts.length) {
        const choice = await versionDialog(conflicts);
        if (!choice) { fileInput.value = ""; return; }
        if (choice === "replace") replace = Object.fromEntries(conflicts.map((c) => [c.filename, c.previous.map((p) => p.id)]));
        else toast("هر دو نسخه نگه داشته می‌شوند؛ داده‌های مشترک دو بار حساب خواهند شد.", "warn", 9000);
      }
    } catch (e) { toastError(e); fileInput.value = ""; return; }
    const form = new FormData();
    for (const f of files) form.append("files", f);
    form.append("options", JSON.stringify(override.input.checked ? sf.values() : {}));
    form.append("replace", JSON.stringify(replace));
    try {
      dz.classList.add("over");
      const res = await api(`/collections/${id}/documents`, { method: "POST", form });
      res.skipped.forEach((s) => toast(`${s.filename}: ${s.reason}`, "warn", 7000));
      res.jobs.forEach(watchJob);
      if (res.documents.length) toast(`${faNum(res.documents.length)} سند در صف ایندکس قرار گرفت`, "ok");
      refresh();
    } catch (e) { toastError(e); } finally { dz.classList.remove("over"); fileInput.value = ""; }
  }
  fileInput.addEventListener("change", () => upload([...fileInput.files]));
  const dz = h("div", { class: "dropzone", tabindex: 0, role: "button",
    onclick: () => fileInput.click(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") fileInput.click(); },
    ondragover: (e) => { e.preventDefault(); dz.classList.add("over"); }, ondragleave: () => dz.classList.remove("over"),
    ondrop: (e) => { e.preventDefault(); dz.classList.remove("over"); upload([...e.dataTransfer.files]); } },
  icon("upload"), h("div", { style: { fontWeight: 700 } }, "فایل‌ها را اینجا رها کنید یا کلیک کنید"),
  h("div", { class: "small" }, `${sys.supported_ext.join("، ")} · حداکثر ${faNum(sys.max_upload_mb)} مگابایت`));

  // --- دیالوگ‌ها ---
  // پیش از بارگذاری: نسخه قبلی همین سند وجود دارد؛ پیش‌فرض و توصیه: حذف نسخه قبلی
  function versionDialog(conflicts) {
    const tabular = conflicts.some((c) => c.previous.some((p) => p.rows) || /\.(xlsx|xlsm|xls|csv)$/i.test(c.filename));
    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => { done = true; resolve(v); };
      modal({
        title: "نسخه قبلی این سند در پایگاه دانش وجود دارد", wide: true,
        onClose: () => { if (!done) resolve(null); },
        body: h("div", { class: "stack" },
          h("p", { style: { margin: 0 } }, conflicts.length > 1
            ? `برای ${faNum(conflicts.length)} فایلی که انتخاب کرده‌اید، سندی با همان نام از قبل در این پایگاه دانش هست. احتمالاً این‌ها نسخه جدید (اصلاح‌شده) همان اسناد هستند:`
            : "فایلی که انتخاب کرده‌اید با نام یکسان از قبل در این پایگاه دانش هست. احتمالاً این نسخه جدید (اصلاح‌شده) همان سند است:"),
          versionsTable(conflicts.map((c) => ({ name: c.filename, previous: c.previous }))),
          dupExplain(tabular),
          h("div", { class: "alert ok" }, h("b", {}, "توصیه: نسخه قبلی حذف شود. "),
            "حذف فقط پس از پردازش موفق نسخه جدید انجام می‌شود؛ اگر پردازش نسخه جدید خطا بدهد، نسخه قبلی دست‌نخورده می‌ماند. ",
            "تا پایان پردازش، محاسبه‌های گفتگو فقط از نسخه قبلی انجام می‌شود."),
          h("p", { class: "small muted", style: { margin: 0 } },
            "«نگه داشتن هر دو» فقط وقتی درست است که این دو فایل واقعاً اسناد متفاوتی باشند (مثلاً گزارش دوره یا تامین‌کننده دیگر با نام مشابه).")),
        actions: [
          { label: "انصراف", onClick: () => finish(null) },
          { label: "نگه داشتن هر دو نسخه", onClick: () => finish("keep") },
          { label: "حذف نسخه قبلی و بارگذاری نسخه جدید (توصیه‌شده)", class: "primary", onClick: () => finish("replace") },
        ],
      });
    });
  }

  // پس از پردازش: محتوای سند با سند دیگری مشترک است (مثلاً همان گزارش با نام دیگر)
  function overlapDialog(doc, overlaps) {
    const tabular = !!doc.stats?.table;
    const unit = tabular ? "سطر فروش" : "بخش متن";
    modal({
      title: "این سند تکراری است: محتوای آن در سند دیگری هم هست", wide: true,
      body: h("div", { class: "stack" },
        h("p", { style: { margin: 0 } }, `بخش بزرگی از ${unit}‌های «${doc.filename}» عیناً در سند(های) زیر هم وجود دارد؛ یعنی احتمالاً نسخه دیگری از همان سند است:`),
        persianize(h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, ["سند موجود", "تاریخ بارگذاری", `${unit} مشترک`, "سهم مشترک"].map((t) => h("th", {}, t)))),
          h("tbody", {}, overlaps.map((o) => h("tr", {}, h("td", {}, h("b", {}, o.filename)), h("td", {}, fmtDate(o.created_at)),
            h("td", { class: "num" }, `${faNum(o.shared)} از ${faNum(o.total)}`),
            h("td", { class: "num" }, `${faNum(Math.round(o.ratio * 100))}٪`))))))),
        dupExplain(tabular),
        h("div", { class: "alert ok" }, h("b", {}, "توصیه: سند قدیمی‌تر حذف شود "), `تا فقط «${doc.filename}» (نسخه تازه‌بارگذاری‌شده) بماند.`)),
      actions: [
        { label: "نگه داشتن هر دو" },
        { label: overlaps.length > 1 ? `حذف ${faNum(overlaps.length)} سند قدیمی (توصیه‌شده)` : "حذف سند قدیمی (توصیه‌شده)", class: "primary", onClick: async () => {
          for (const o of overlaps) await del(`/documents/${o.document_id}`);
          toast("سند قدیمی حذف شد؛ از این پس فقط نسخه جدید در پاسخ‌ها استفاده می‌شود", "ok", 7000);
          invalidateCollections(); refresh();
        } },
      ],
    });
  }

  function reindexDialog(doc) {
    const f = settingsForm({ ...col.settings, ...doc.options }, sys.defaults.settings);
    modal({ title: `ایندکس مجدد «${doc.filename}»`, wide: true,
      body: h("div", { class: "stack" }, h("p", { class: "muted", style: { margin: 0 } },
        "chunkها و بردارهای فعلی این سند حذف و با تنظیمات زیر دوباره ساخته می‌شوند."), f.el),
      actions: [{ label: "انصراف" }, { label: "ایندکس مجدد", class: "primary", onClick: async () => {
        watchJob(await post(`/documents/${doc.id}/reindex`, { options: f.values() })); refresh();
      } }] });
  }

  function settingsDialog() {
    const name = h("input", { type: "text", value: col.name });
    const desc = h("input", { type: "text", value: col.description || "" });
    const f = settingsForm(col.settings, sys.defaults.settings);
    modal({ title: "ویرایش پایگاه دانش", wide: true,
      body: h("div", { class: "stack" }, h("div", { class: "form-grid" }, field("نام", name), field("توضیح", desc)),
        h("div", { class: "alert" }, "تغییر تنظیمات روی اسناد جدید یا پس از «ایندکس مجدد همه» اعمال می‌شود. مدل embedding قابل تغییر نیست."), f.el),
      actions: [{ label: "انصراف" }, { label: "ذخیره", class: "primary", onClick: async () => {
        const res = await patch(`/collections/${id}`, { name: name.value, description: desc.value, settings: f.values() });
        (res.warnings || []).forEach((w) => toast(w, "warn", 8000));
        toast("ذخیره شد", "ok"); invalidateCollections(); render(clear(root), { id });
      } }] });
  }

  async function reindexAll() {
    if (!(await confirmDialog("ایندکس مجدد همه اسناد", "همه اسناد با تنظیمات فعلی پایگاه دانش دوباره پردازش و embedding می‌شوند. ادامه می‌دهید؟", { danger: false, ok: "شروع" }))) return;
    try { const r = await post(`/collections/${id}/reindex`); r.jobs.forEach(watchJob); refresh(); } catch (e) { toastError(e); }
  }

  async function deleteCollection() {
    if (!(await confirmDialog("حذف پایگاه دانش", `پایگاه دانش «${col.name}» با همه اسناد، chunkها، بردارها و مجموعه‌های ارزیابی آن برای همیشه حذف شود؟`))) return;
    try { await del(`/collections/${id}`); invalidateCollections(); toast("پایگاه دانش حذف شد", "ok"); location.hash = "#/collections"; } catch (e) { toastError(e); }
  }

  const s = col.effective_settings;
  root.append(
    h("div", { class: "page-head" },
      h("div", {},
        h("a", { href: "#/collections", class: "small" }, "← پایگاه‌های دانش"),
        h("h1", {}, col.name),
        persianize(h("div", { class: "row small", style: { marginTop: "4px" } },
          h("span", { class: "badge info" }, BACKEND_LABEL[col.vector_backend]),
          h("span", { class: "badge accent ltr" }, `${col.embedding_provider} / ${col.embedding_model}`),
          h("span", { class: "badge" }, STRATEGY_LABEL[s.strategy]),
          s.strategy !== "fixed" ? h("span", { class: "badge" }, `سقف ${s.max_tokens} توکن`) : h("span", { class: "badge" }, `${s.chunk_chars} کاراکتر`),
          h("span", { class: "badge" }, `استخراج: ${METHOD_LABEL[s.method]}`),
          !s.clean ? h("span", { class: "badge warn" }, "بدون clean_fa") : null))),
      h("div", { class: "actions" },
        h("a", { class: "btn primary", href: "#/chat" }, icon("chat"), "گفتگو"),
        h("button", { class: "btn", onclick: settingsDialog }, icon("settings"), "تنظیمات"),
        h("button", { class: "btn", onclick: reindexAll }, icon("refresh"), "ایندکس مجدد همه"),
        h("button", { class: "btn danger", onclick: deleteCollection }, icon("trash"), "حذف"))),
    h("div", { class: "stack" },
      tiles,
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "بارگذاری اسناد"), override.el), dz, fileInput, sfBox),
      jobsBox,
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "اسناد"),
        h("button", { class: "btn sm ghost", onclick: () => refresh().catch(toastError) }, icon("refresh"), "به‌روزرسانی")), docsBox)));

  await refresh();
  return () => { alive = false; };
}

// هم‌پوشانی‌هایی که سند طرف مقابل هنوز وجود دارد
function liveOverlaps(doc, docs) {
  const ids = new Set(docs.map((d) => d.id));
  return (doc?.stats?.overlaps || []).filter((o) => ids.has(o.document_id));
}

function versionsTable(items) {
  const desc = (p) => [fmtDate(p.created_at), fmtSize(p.size),
    p.rows ? `${faNum(p.rows)} سطر فروش${p.branches ? ` در ${faNum(p.branches)} شعبه` : ""}` : `${faNum(p.chunks || 0)} chunk`,
    p.status === "ready" ? null : `وضعیت: ${p.status}`].filter(Boolean).join(" · ");
  return persianize(h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "فایل جدید"), h("th", {}, "نسخه قبلی در پایگاه دانش"))),
    h("tbody", {}, items.map((c) => h("tr", {}, h("td", {}, h("b", {}, c.name)),
      h("td", {}, c.previous.map((p) => h("div", {}, h("b", {}, p.filename), h("div", { class: "tiny muted" }, desc(p)))))))))));
}

// چرا داده تکراری نتایج را خراب می‌کند
function dupExplain(tabular) {
  const items = tabular ? [
    "هر سطر کالا دو بار در محاسبه‌ها می‌آید: جمع «تعداد فروش»، «مبلغ فروش» و «تخفیف» هر شعبه و هر تامین‌کننده تقریباً دو برابر مقدار واقعی گزارش می‌شود. مثال واقعی: جمع تعداد فروش شعبه مگامال در نسخه اصلاح‌شده ۱۷٬۳۰۶ است، اما با ماندن نسخه قبلی دستیار ۳۳٬۶۱۲ پاسخ می‌دهد.",
    "ردیف‌هایی که در نسخه جدید اصلاح کرده‌اید، در نسخه قبلی با مقدار اشتباه باقی می‌مانند و با مقدار درست جمع زده می‌شوند؛ یعنی اصلاح شما عملاً اثری ندارد و عدد نهایی نه با نسخه قدیم می‌خواند نه با نسخه جدید.",
    "رتبه‌بندی‌ها (پرفروش‌ترین شعبه یا کالا)، درصد سهم هر شعبه، میانگین‌ها و مقایسه‌ها هم جابه‌جا و نادرست می‌شوند.",
    "در جستجوی متنی، سطرها و خلاصه‌های تکراری جای منابع دیگر را می‌گیرند و ممکن است پاسخ از روی نسخه قدیمی ساخته شود.",
  ] : [
    "متن‌های تکراری در جستجو دو بار پیدا می‌شوند و جای منابع دیگر را در k نتیجه برتر می‌گیرند؛ پس پاسخ‌ها از شواهد کمتر و ناقص‌تری ساخته می‌شوند.",
    "اگر در نسخه جدید چیزی را اصلاح کرده‌اید، نسخه قبلی با اطلاعات قدیمی هم بازیابی می‌شود و دستیار ممکن است پاسخ قدیمی و اشتباه را بدهد یا دو پاسخ متناقض را کنار هم بیاورد.",
    "ارجاع به منابع و ارزیابی بازیابی (Hit@k و MRR) هم گمراه‌کننده می‌شود، چون یک متن در دو سند تکرار شده است.",
  ];
  return h("div", { class: "alert warn" },
    h("b", {}, "چرا داده تکراری خطرناک است؟ "), "اگر هر دو نسخه در پایگاه دانش بمانند، نتایج گفتگو می‌تواند کاملاً اشتباه شود:",
    h("ul", { style: { margin: "6px 0 0", paddingRight: "18px" } }, items.map((t) => h("li", {}, t))));
}

function tile(label, value, sub) {
  return h("div", { class: "tile" }, h("div", { class: "label" }, label),
    h("div", { class: "value" }, typeof value === "number" ? faNum(value) : value), sub ? h("div", { class: "sub" }, sub) : null);
}

// فایل اکسل/CSV: سطرها در جدول ساختاریافته برای محاسبه دقیق و chunkها برای جستجوی معنایی
function tableDetail(d, s) {
  const t = s.table;
  return persianize(h("div", { class: "grid grid-2", style: { padding: "6px 0" } },
    h("dl", { class: "kv" },
      h("dt", {}, "نوع"), h("dd", {}, "داده جدولی (اکسل) — پرسش‌های آماری با SQL دقیق پاسخ داده می‌شوند"),
      h("dt", {}, "گزارش‌ها (جدول)"), h("dd", {}, String(t.tables ?? 0)),
      h("dt", {}, "سطرهای کالا"), h("dd", {}, String(t.rows ?? 0)),
      h("dt", {}, "تامین‌کننده‌ها"), h("dd", {}, (t.suppliers || []).join("، ") || "—"),
      h("dt", {}, `شعبه‌ها (${(t.branches || []).length})`), h("dd", {}, (t.branches || []).join("، ") || "—"),
      h("dt", {}, "شیت‌های غیرفروش"), h("dd", {}, String(t.generic_sheets ?? 0)),
      h("dt", {}, "chunk / میانگین توکن"), h("dd", {}, `${s.chunks ?? "—"} / ${s.avg_tokens ?? "—"}`)),
    h("div", { class: "stack", style: { gap: "8px" } },
      (s.warnings || []).length ? (s.warnings || []).map((w) => h("div", { class: "alert warn small" }, w))
        : h("div", { class: "alert ok small" }, "جمع ستون‌ها با سطر «جمع» فایل مطابقت دارد (یا فایل سطر جمع نداشت)."))));
}

function docDetail(d) {
  const s = d.stats || {};
  if (s.table) return tableDetail(d, s);
  if (!s.pages && !s.chunks) return h("div", { class: "muted small" }, "آماری ثبت نشده است.");
  const methods = Object.entries(s.methods || {}).map(([m, n]) => `${METHOD_LABEL[m] || m}: ${n}`).join("، ");
  const pd = s.page_details || [];
  return persianize(h("div", { class: "grid grid-2", style: { padding: "6px 0" } },
    h("dl", { class: "kv" },
      h("dt", {}, "ابزار استخراج"), h("dd", {}, methods || "—"),
      h("dt", {}, "صفحات معکوس اصلاح‌شده"), h("dd", {}, String(s.reversed_pages ?? 0)),
      h("dt", {}, "پاراگراف / عنوان / بخش"), h("dd", {}, `${s.paragraphs ?? "—"} / ${s.headings ?? "—"} / ${s.sections ?? "—"}`),
      h("dt", {}, "میانگین / بیشینه توکن"), h("dd", {}, `${s.avg_tokens ?? "—"} / ${s.max_tokens ?? "—"}`),
      h("dt", {}, "جدول‌ها"), h("dd", {}, String(s.tables ?? 0)),
      h("dt", {}, "تنظیمات اختصاصی"), h("dd", { class: "ltr tiny mono" }, Object.keys(d.options || {}).length ? JSON.stringify(d.options) : "—")),
    h("div", { class: "stack", style: { gap: "8px" } },
      ...(s.warnings || []).map((w) => h("div", { class: "alert warn small" }, w)),
      pd.length ? h("details", {}, h("summary", { class: "small", style: { cursor: "pointer" } }, `جزئیات ${pd.length} صفحه`),
        h("div", { class: "table-wrap", style: { maxHeight: "260px", marginTop: "6px" } }, h("table", {},
          h("thead", {}, h("tr", {}, ["صفحه", "ابزار", "خط", "واژگان", "معکوس", "شکل نمایشی"].map((t) => h("th", {}, t)))),
          h("tbody", {}, pd.map((p) => h("tr", {}, h("td", {}, String(p.page)), h("td", {}, METHOD_LABEL[p.method] || p.method),
            h("td", {}, String(p.lines)), h("td", {}, String(p.vocab)), h("td", {}, p.reversed ? "بله" : "—"),
            h("td", {}, String(p.presentation_forms ?? 0)))))))) : null)));
}
