// مسیریاب و پوسته برنامه

import { get } from "./api.js";
import { loadingBlock } from "./state.js";
import { clear, h, icon, prefs, toastError } from "./ui.js";
import * as chat from "./views/chat.js";
import * as collections from "./views/collections.js";
import * as collection from "./views/collection.js";
import * as search from "./views/search.js";
import * as audit from "./views/audit.js";
import * as evaluation from "./views/eval.js";
import * as lab from "./views/lab.js";
import * as system from "./views/system.js";
import * as guide from "./views/guide.js";

const ROUTES = [
  { path: "chat", label: "گفتگو با اسناد", icon: "chat", view: chat },
  { path: "collections", label: "پایگاه‌های دانش", icon: "db", view: collections },
  { path: "search", label: "آزمون بازیابی", icon: "search", view: search },
  { path: "audit", label: "بررسی chunkها", icon: "audit", view: audit },
  { path: "eval", label: "ارزیابی Hit@k و MRR", icon: "chart", view: evaluation },
  { path: "lab", label: "آزمایشگاه متن", icon: "lab", view: lab },
  { path: "system", label: "وضعیت سیستم", icon: "system", view: system },
  { path: "guide", label: "راهنما", icon: "book", view: guide },
];

const viewEl = document.getElementById("view");
const nav = document.getElementById("nav");
let cleanup = null;

nav.append(...ROUTES.map((r) => h("a", { href: `#/${r.path}`, "data-path": r.path }, icon(r.icon), r.label)));

function parseHash() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  return { parts, params: Object.fromEntries(new URLSearchParams(query)) };
}

async function route() {
  const { parts, params } = parseHash();
  let r = ROUTES.find((x) => x.path === parts[0]);
  let view = r?.view;
  if (parts[0] === "collections" && parts[1]) { view = collection; params.id = parts[1]; }
  if (!r) { location.replace("#/chat"); return; }
  nav.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.path === r.path));
  document.getElementById("sidebar").classList.remove("open");
  if (typeof cleanup === "function") { try { cleanup(); } catch (e) {} }
  cleanup = null;
  // نشانگر بارگذاری تا وقتی صفحه اولین محتوای خودش را اضافه کند
  const loading = loadingBlock();
  viewEl.className = "";
  clear(viewEl, loading);
  const obs = new MutationObserver(() => { if (viewEl.childElementCount > 1 || !viewEl.contains(loading)) { loading.remove(); obs.disconnect(); } });
  obs.observe(viewEl, { childList: true });
  document.title = `${r.label} · RAG فارسی`;
  try { cleanup = await view.render(viewEl, params); }
  catch (e) { toastError(e); viewEl.append(h("div", { class: "alert err" }, e.message || String(e))); }
  finally { loading.remove(); obs.disconnect(); }
}

window.addEventListener("hashchange", route);
export const rerender = route;

// --- تم ---
const themeSeg = document.getElementById("theme-seg");
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem("rag-theme", t) : localStorage.removeItem("rag-theme"); } catch (e) {}
  themeSeg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.t === (t || "")));
}
themeSeg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) applyTheme(b.dataset.t); });
applyTheme(document.documentElement.dataset.theme || "");

// --- ارقام فارسی ---
const digits = document.getElementById("fa-digits");
digits.checked = prefs.get("fa-digits", true);
digits.addEventListener("change", () => { prefs.set("fa-digits", digits.checked); route(); });

document.getElementById("menu-btn").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));

// --- نشانگر کارهای پس‌زمینه ---
const pill = document.getElementById("jobs-pill"), pillText = document.getElementById("jobs-text");
async function pollJobs() {
  try {
    const jobs = await get("/jobs?active=true");
    pill.classList.toggle("busy", jobs.length > 0);
    pillText.textContent = jobs.length ? `${jobs.length.toLocaleString("fa-IR")} کار در حال اجرا` : "کار فعالی نیست";
  } catch (e) { pillText.textContent = "سرور در دسترس نیست"; }
  setTimeout(pollJobs, 3000);
}
pollJobs();

if (!location.hash) location.replace("#/chat"); else route();
