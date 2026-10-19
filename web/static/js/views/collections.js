// فهرست پایگاه‌های دانش و ساخت پایگاه جدید

import { post } from "../api.js";
import { BACKEND_LABEL, STRATEGY_LABEL, getCollections, getSystem, invalidateCollections, loadingBlock, setCurrentCollection, settingsForm } from "../state.js";
import { clear, emptyState, faNum, fmtDate, field, h, icon, modal, persianize, selectEl, toast } from "../ui.js";

export async function render(root) {
  const list = h("div", { class: "grid grid-3" }, loadingBlock());
  root.append(
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "پایگاه‌های دانش"),
        h("p", {}, "هر پایگاه دانش یک مدل embedding و یک collection مستقل در ChromaDB یا Qdrant دارد؛ بردارهای دو مدل هرگز با هم مخلوط نمی‌شوند.")),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => createDialog() }, icon("plus"), "پایگاه دانش جدید"))),
    list);

  const cols = await getCollections(true);
  clear(list);
  if (!cols.length) {
    list.style.display = "block";
    list.append(h("div", { class: "card" }, emptyState("db", "هنوز پایگاه دانشی ندارید",
      "یک پایگاه دانش بسازید، PDFهای فارسی را بارگذاری کنید و سپس از بخش گفتگو پرسش بپرسید.",
      h("button", { class: "btn primary", onclick: () => createDialog() }, icon("plus"), "ساخت اولین پایگاه دانش"))));
    return;
  }
  for (const c of cols) {
    const s = c.effective_settings;
    list.append(persianize(h("a", { class: "card", href: `#/collections/${c.id}`, style: { textDecoration: "none", color: "inherit", display: "grid", gap: "10px" },
      onclick: () => setCurrentCollection(c.id) },
      h("div", { class: "card-head", style: { margin: 0 } }, h("h3", {}, c.name),
        h("span", { class: "badge info" }, BACKEND_LABEL[c.vector_backend] || c.vector_backend)),
      c.description ? h("p", { class: "muted small", style: { margin: 0 } }, c.description) : null,
      h("div", { class: "row small" },
        h("span", { class: "badge accent ltr" }, `${c.embedding_provider} / ${c.embedding_model}`),
        h("span", { class: "badge" }, STRATEGY_LABEL[s.strategy] || s.strategy),
        s.strategy !== "fixed" ? h("span", { class: "badge" }, `${faNum(s.max_tokens)} توکن`) : null,
        !s.clean ? h("span", { class: "badge warn" }, "بدون clean_fa") : null),
      h("div", { class: "row small muted" },
        h("span", {}, `${faNum(c.documents)} سند`), h("span", {}, "·"), h("span", {}, `${faNum(c.chunks)} chunk`),
        h("span", { class: "spacer" }), h("span", { class: "tiny" }, fmtDate(c.created_at))))));
  }
}

export async function createDialog(onCreated) {
  const sys = await getSystem(true);
  const provLabel = (p) => `${sys.provider_labels[p]}${sys.providers[p].available ? "" : " — در دسترس نیست"}`;
  const provider = selectEl(Object.keys(sys.provider_labels).map((p) => [p, provLabel(p)]), sys.defaults.embedding_provider);
  const model = h("input", { type: "text", list: "emb-models", class: "ltr", value: sys.defaults.embedding_model });
  const dl = h("datalist", { id: "emb-models" });
  const status = h("div", { class: "small" });
  const syncModels = (reset) => {
    const p = provider.value;
    const presets = [...(sys.presets.embedding[p] || []), ...(p === "ollama" ? sys.providers.ollama.models : [])];
    clear(dl, [...new Set(presets)].map((m) => h("option", { value: m })));
    if (reset) model.value = presets[0] || "";
    const st = sys.providers[p];
    clear(status, st.available ? null : h("div", { class: "alert warn" }, st.reason || "در دسترس نیست"));
  };
  provider.addEventListener("change", () => syncModels(true));
  syncModels(false);

  // برچسب کوتاه در گزینه؛ مسیر یا آدرس کامل در tooltip (مسیر طولانی در کادر بریده می‌شد)
  const backendMode = (b) => {
    const st = sys.backends[b];
    if (!st?.available) return "در دسترس نیست";
    return st.mode.startsWith("server") ? "سرور" : st.mode.startsWith("embedded") ? "embedded (توسعه)" : "لوکال روی دیسک";
  };
  const backend = selectEl(["chroma", "qdrant"].map((b) => [b, `${BACKEND_LABEL[b]} — ${backendMode(b)}`, !sys.backends[b]?.available]),
    sys.defaults.vector_store);
  const syncBackendTitle = () => { backend.title = sys.backends[backend.value]?.mode || ""; };
  backend.addEventListener("change", syncBackendTitle);
  syncBackendTitle();
  const name = h("input", { type: "text", placeholder: "مثلاً: آیین‌نامه‌های آموزشی" });
  const desc = h("input", { type: "text", placeholder: "اختیاری" });
  const sf = settingsForm({}, sys.defaults.settings);
  const adv = h("details", {}, h("summary", { style: { cursor: "pointer", fontWeight: 700 } }, "تنظیمات استخراج و بخش‌بندی"),
    h("div", { style: { marginTop: "12px" } }, sf.el));

  modal({ title: "پایگاه دانش جدید", wide: true,
    body: h("div", { class: "stack" },
      h("div", { class: "form-grid" }, field("نام", name), field("توضیح", desc)),
      h("div", { class: "form-grid" }, field("ارائه‌دهنده embedding", provider), field("مدل embedding", model, "پس از ساخت قابل تغییر نیست"), dl,
        field("پایگاه داده برداری", backend)),
      status,
      h("p", { class: "hint", style: { margin: 0 } }, "برای مدل‌های e5 پیشوند query:/passage: خودکار اعمال می‌شود. مدل‌های HuggingFace در اولین استفاده دانلود می‌شوند."),
      adv),
    actions: [
      { label: "انصراف" },
      { label: "ساخت پایگاه دانش", class: "primary", onClick: async () => {
        if (!name.value.trim()) { toast("نام پایگاه دانش را وارد کنید", "warn"); return false; }
        const col = await post("/collections", { name: name.value, description: desc.value, embedding_provider: provider.value,
          embedding_model: model.value.trim(), vector_backend: backend.value, settings: sf.values() });
        (col.warnings || []).forEach((w) => toast(w, "warn", 8000));
        toast(`پایگاه دانش «${col.name}» ساخته شد`, "ok");
        invalidateCollections(); setCurrentCollection(col.id);
        if (onCreated) onCreated(col); else location.hash = `#/collections/${col.id}`;
      } },
    ] });
}
