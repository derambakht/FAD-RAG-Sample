// ابزارهای رابط کاربری: ساخت عنصر، آیکون، اعلان، مودال، ارقام فارسی، markdown و نمودار

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el, ...children) { el.replaceChildren(); append(el, children); return el; }

const ICONS = {
  chat: "M4 5h16v11H8l-4 4z",
  db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm9 16-4.3-4.3",
  audit: "M9 11l2 2 4-4M5 4h14v16H5z",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  lab: "M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3",
  system: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
  plus: "M12 5v14M5 12h14",
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v4h16v-4",
  trash: "M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  send: "M5 12h14M13 6l6 6-6 6",
  stop: "M7 7h10v10H7z",
  x: "M6 6l12 12M18 6 6 18",
  file: "M6 3h8l4 4v14H6zM14 3v4h4",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  download: "M12 4v12m0 0-4-4m4 4 4-4M4 20h16",
  settings: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  play: "M7 5v14l11-7z",
  copy: "M8 8h12v12H8zM4 16V4h12",
  edit: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
  book: "M12 6c-2-1.5-5-2-8-2v14c3 0 6 .5 8 2 2-1.5 5-2 8-2V4c-3 0-6 .5-8 2zm0 0v14",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z",
};

export function icon(name, size) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  if (size) { svg.setAttribute("width", size); svg.setAttribute("height", size); }
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", ICONS[name] || ""); svg.append(p);
  return svg;
}

// --- ترجیحات (localStorage امن) ---
export const prefs = {
  get(k, d) { try { const v = localStorage.getItem("rag-" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("rag-" + k, JSON.stringify(v)); } catch (e) {} },
};

// --- ارقام فارسی ---
const FA = "۰۱۲۳۴۵۶۷۸۹";
export const faDigitsOn = () => prefs.get("fa-digits", true);
export function faNum(x) {
  const s = typeof x === "number" ? x.toLocaleString("en-US", { maximumFractionDigits: 3 }) : String(x ?? "");
  return faDigitsOn() ? s.replace(/[0-9]/g, (d) => FA[d]).replace(/,/g, "٬").replace(/(\d|[۰-۹])\.(?=[۰-۹])/g, "$1٫") : s;
}
/** ارقام متن‌های داخل عنصر را فارسی می‌کند (به‌جز کد و بخش‌های LTR) */
export function persianize(root) {
  if (!faDigitsOn() || !root) return root;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => n.parentElement?.closest("code,pre,.ltr,.mono,input,textarea,svg,.formula") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    // اعداد چسبیده به حروف لاتین (مثل Hit@5 یا gpt-4o) دست نمی‌خورند
    n.nodeValue = n.nodeValue.replace(/(^|[^A-Za-z0-9@\-_.:/])(\d+(?:[.,/]\d+)*)(?![A-Za-z\d])/g,
      (m, pre, num) => pre + num.replace(/\d/g, (d) => FA[d]).replace(/,/g, "٬").replace(/\./g, "٫"));
  }
  return root;
}

export function pct(x) { return faNum(Math.round(x * 1000) / 10) + "٪"; }
export function fmtDate(iso) {
  if (!iso) return "";
  const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  try { return d.toLocaleString(faDigitsOn() ? "fa-IR" : "fa-IR-u-nu-latn", { dateStyle: "medium", timeStyle: "short" }); }
  catch (e) { return d.toISOString(); }
}
export function fmtSize(b) {
  if (b < 1024) return faNum(b) + " بایت";
  if (b < 1048576) return faNum(Math.round(b / 102.4) / 10) + " KB";
  return faNum(Math.round(b / 104857.6) / 10) + " MB";
}

// --- اعلان ---
export function toast(msg, type = "info", ms = 4500) {
  const el = h("div", { class: `toast ${type}`, role: "status" }, msg);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), ms);
}
export function toastError(e) { if (e?.name !== "AbortError") toast(e?.message || String(e), "err", 7000); }

// --- مودال ---
export function modal({ title, body, actions = [], wide = false, onClose } = {}) {
  const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); onClose?.(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const foot = actions.length ? h("div", { class: "modal-foot" }, actions.map((a) =>
    h("button", { class: `btn ${a.class || ""}`, onclick: async (ev) => {
      if (!a.onClick) return close();
      const btn = ev.currentTarget; btn.disabled = true;
      try { if ((await a.onClick()) !== false) close(); } catch (e) { toastError(e); } finally { btn.disabled = false; }
    } }, a.label))) : null;
  const overlay = h("div", { class: "overlay", onmousedown: (e) => { if (e.target === overlay) close(); } },
    h("div", { class: `modal ${wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "modal-head" }, h("h3", {}, title),
        h("button", { class: "btn icon ghost", "aria-label": "بستن", onclick: close }, icon("x"))),
      h("div", { class: "modal-body" }, body), foot));
  document.body.append(overlay);
  document.addEventListener("keydown", onKey);
  overlay.querySelector("input,select,textarea")?.focus();
  return { close, el: overlay };
}

export function confirmDialog(title, text, { danger = true, ok = "تأیید" } = {}) {
  return new Promise((resolve) => {
    let done = false;
    modal({ title, body: h("p", { style: { margin: 0 } }, text), onClose: () => { if (!done) resolve(false); },
      actions: [
        { label: "انصراف" },
        { label: ok, class: danger ? "danger" : "primary", onClick: () => { done = true; resolve(true); } },
      ] });
  });
}

// --- فرم ---
export function field(label, input, hint) {
  return h("label", { class: "field" }, label, input, hint ? h("span", { class: "hint" }, hint) : null);
}
export function switchEl(label, checked, attrs = {}) {
  const inp = h("input", { type: "checkbox", ...attrs }); inp.checked = !!checked;
  return { el: h("label", { class: "switch" }, inp, label), input: inp };
}
export function selectEl(options, value, attrs = {}) {
  const s = h("select", attrs, options.map(([v, l, dis]) => h("option", { value: v, disabled: dis }, l)));
  if (value !== undefined) s.value = value;
  return s;
}
export function seg(options, value, onChange) {
  const el = h("div", { class: "seg", role: "group" });
  // گزینه سوم هر مورد (اختیاری): غیرفعال بودن آن گزینه
  const render = () => clear(el, options.map(([v, l, dis]) => h("button", { type: "button", class: v === value ? "on" : "",
    disabled: !!dis, "aria-pressed": String(v === value), onclick: () => { value = v; render(); onChange?.(v); } }, l)));
  render();
  return { el, get value() { return value; } };
}
export function spinner() { return h("span", { class: "spinner", role: "status", "aria-label": "در حال بارگذاری" }); }
export function emptyState(iconName, title, text, action) {
  return h("div", { class: "empty" }, icon(iconName), h("h3", {}, title), text ? h("p", {}, text) : null, action || null);
}
export const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

export function statusBadge(status) {
  const map = { ready: ["ok", "آماده"], processing: ["info", "در حال پردازش"], pending: ["", "در صف"], error: ["err", "خطا"],
    done: ["ok", "انجام شد"], running: ["info", "در حال اجرا"], cancelled: ["warn", "لغو شد"] };
  const [cls, label] = map[status] || ["", status];
  return h("span", { class: `badge ${cls}` }, status === "processing" || status === "running" ? spinner() : null, label);
}

// --- markdown و ارجاع‌ها ---
export function renderMarkdown(text, onCite) {
  const div = h("div", { class: "md" });
  let html;
  if (window.marked && window.DOMPurify) html = DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
  else html = text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])).replace(/\n/g, "<br>");
  div.innerHTML = html;
  // [1] و [۲] به دکمه ارجاع تبدیل می‌شوند
  const walker = document.createTreeWalker(div, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => n.parentElement.closest("code,pre") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  const re = /\[([0-9۰-۹]{1,2})\]/g;
  for (const n of nodes) {
    if (!re.test(n.nodeValue)) continue;
    re.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0, m;
    while ((m = re.exec(n.nodeValue))) {
      frag.append(n.nodeValue.slice(last, m.index));
      const num = Number(m[1].replace(/[۰-۹]/g, (d) => FA.indexOf(d)));
      frag.append(h("button", { class: "cite", type: "button", title: `منبع ${num}`, onclick: () => onCite?.(num) }, faNum(num)));
      last = m.index + m[0].length;
    }
    frag.append(n.nodeValue.slice(last));
    n.replaceWith(frag);
  }
  return persianize(div);
}

/** برجسته‌سازی کلمات پرسش در متن (پس از نرمال‌سازی) */
export function highlight(text, query) {
  const words = [...new Set((query || "").split(/[\s،.؟?!:؛]+/).filter((w) => w.length > 2))];
  if (!words.length) return document.createTextNode(text);
  const re = new RegExp("(" + words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "g");
  const frag = document.createDocumentFragment();
  text.split(re).forEach((part, i) => frag.append(i % 2 ? h("mark", {}, part) : part));
  return frag;
}

// --- tooltip نمودار ---
let tip;
export function showTip(e, html) {
  if (!tip) { tip = h("div", { class: "tooltip", role: "tooltip" }); document.body.append(tip); }
  tip.innerHTML = html; tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let x = e.clientX - r.width / 2, y = e.clientY - r.height - 12;
  x = Math.max(8, Math.min(window.innerWidth - r.width - 8, x)); if (y < 8) y = e.clientY + 16;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
export function hideTip() { if (tip) tip.hidden = true; }

/** هیستوگرام تک‌سری (توزیع توکن chunkها) */
export function histogram(bins, { label = "تعداد" } = {}) {
  const max = Math.max(1, ...bins.map((b) => b.count));
  const name = (b) => b.to === null ? `${faNum(b.from)}+` : `${faNum(b.from)}–${faNum(b.to)}`;
  const chart = h("div", { class: "chart", role: "img", "aria-label": "توزیع تعداد توکن chunkها" },
    h("div", { class: "hist" }, bins.map((b) => h("div", { class: "col",
      onmousemove: (e) => showTip(e, `<b>${name(b)} توکن</b><br>${label}: ${faNum(b.count)}`), onmouseleave: hideTip },
      b.count ? h("span", { class: "val" }, faNum(b.count)) : null,
      h("div", { class: "bar", style: { height: `${(b.count / max) * 100}%` } })))),
    h("div", { class: "hist-axis" }, bins.map((b) => h("span", {}, name(b)))));
  return chart;
}

/** نمودار میله‌ای افقی گروهی برای Hit@k و MRR (مقیاس مشترک ۰ تا ۱) */
export function groupedBars(groups, series) {
  return h("div", { class: "chart" },
    h("div", { class: "chart-legend" }, series.map((s) => h("span", {}, h("i", { style: { background: `var(${s.color})` } }), s.label))),
    h("div", { class: "hbars" }, groups.map((g) => h("div", { class: "hbar-group" },
      h("div", { class: "hbar-label" }, g.label),
      h("div", { class: "hbar-track" }, series.map((s) => h("div", { class: "hbar-row",
        onmousemove: (e) => showTip(e, `<b>${g.label}</b><br>${s.label}: ${faNum(g.values[s.key])}`), onmouseleave: hideTip },
        h("div", { class: "hbar", style: { width: `${Math.max(0.4, g.values[s.key] * 100) * 0.85}%`, background: `var(${s.color})` } }),
        h("span", { class: "v" }, faNum(g.values[s.key])))))))));
}
