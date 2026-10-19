// رسم نمودار جریان با SVG درون‌خطی؛ رنگ‌ها از متغیرهای تم (روشن/تیره) می‌آیند.
// node: {id, x, y, w, h, t: عنوان, s: [زیرعنوان‌ها], kind: hot|opt|store|ext|warn|group}
// edge: {from, to, label, route: "v"|"h"|"side", opt, points: [[x,y],...] برای مسیر دستی}

const NS = "http://www.w3.org/2000/svg";
let uid = 0;

function el(tag, attrs = {}, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

const W = 220, H = 64;
const cx = (n) => n.x + n.w / 2;
const cy = (n) => n.y + n.h / 2;

function nodeEl(n) {
  const g = el("g");
  g.append(el("rect", { x: n.x, y: n.y, width: n.w, height: n.h, rx: n.kind === "group" ? 14 : 9, class: `bx ${n.kind || ""}` }));
  if (n.kind === "group") {
    g.append(el("text", { x: n.x + n.w - 12, y: n.y + 18, class: "gt", "text-anchor": "start" }, n.t));
    return g;
  }
  const lines = n.s || [];
  const total = 17 + lines.length * 15;
  let y = cy(n) - total / 2 + 13;
  g.append(el("text", { x: cx(n), y, class: "t", "text-anchor": "middle" }, n.t));
  for (const s of lines) { y += 15; g.append(el("text", { x: cx(n), y, class: "s", "text-anchor": "middle" }, s)); }
  return g;
}

function route(a, b, e) {
  if (e.points) return e.points;
  const kind = e.route || (Math.abs(cy(a) - cy(b)) < 4 ? "h" : "v");
  if (kind === "h") {  // در یک ردیف: از لبه یکی به لبه دیگری
    const leftward = cx(b) < cx(a);
    const y = e.y ?? cy(a);
    return [[leftward ? a.x : a.x + a.w, y], [leftward ? b.x + b.w : b.x, y]];
  }
  if (kind === "side") {  // از کنار گره مبدأ به بالای گره مقصد
    const leftward = cx(b) < cx(a);
    const sx = leftward ? a.x : a.x + a.w;
    return [[sx, cy(a)], [cx(b), cy(a)], [cx(b), b.y]];
  }
  const sx = e.sx ?? cx(a), tx = e.tx ?? cx(b);  // عمودی با شکست
  const y1 = a.y + a.h, y2 = b.y;
  if (Math.abs(sx - tx) < 1) return [[sx, y1], [tx, y2]];
  const mid = e.midY ?? (y1 + y2) / 2;
  return [[sx, y1], [sx, mid], [tx, mid], [tx, y2]];
}

function labelPos(pts) {
  // وسط طولانی‌ترین قطعه
  let best = 0, len = -1;
  for (let i = 0; i < pts.length - 1; i++) {
    const l = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
    if (l > len) { len = l; best = i; }
  }
  const [a, b] = [pts[best], pts[best + 1]];
  const horizontal = Math.abs(a[1] - b[1]) < 1;
  // در متن RTL، anchor=start یعنی لبه راست متن روی x است؛ برچسب قطعه عمودی سمت چپ خط می‌نشیند
  return { x: (a[0] + b[0]) / 2 + (horizontal ? 0 : -7), y: (a[1] + b[1]) / 2 + (horizontal ? -6 : 4), anchor: horizontal ? "middle" : "start" };
}

/** ساخت figure کامل با svg و توضیح زیر آن */
export function diagram({ width, height, nodes, edges = [], label, caption, notes = [] }) {
  const id = `dg${++uid}`;
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, class: "dg", role: "img", "aria-label": label, direction: "rtl" });
  const defs = el("defs");
  for (const kind of ["", "opt"]) {
    const m = el("marker", { id: `${id}-a${kind}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    m.append(el("path", { d: "M0 0L10 5L0 10z", class: `mk ${kind}` }));
    defs.append(m);
  }
  svg.append(defs);
  const byId = Object.fromEntries(nodes.map((n) => [n.id, { w: W, h: H, ...n }]));
  for (const n of Object.values(byId).filter((n) => n.kind === "group")) svg.append(nodeEl(n));
  const lines = el("g"), labels = el("g");
  for (const e of edges) {
    const pts = route(byId[e.from], byId[e.to], e);
    lines.append(el("polyline", { points: pts.map((p) => p.join(",")).join(" "), class: `ln ${e.opt ? "opt" : ""}`,
      "marker-end": `url(#${id}-a${e.opt ? "opt" : ""})` }));
    if (e.label) {
      const p = { anchor: "middle", ...(e.labelAt || labelPos(pts)) };
      labels.append(el("text", { x: p.x, y: p.y, class: "lb", "text-anchor": p.anchor }, e.label));
    }
  }
  svg.append(lines);
  for (const n of Object.values(byId).filter((n) => n.kind !== "group")) svg.append(nodeEl(n));
  for (const nt of notes) svg.append(el("text", { x: nt.x, y: nt.y, class: "note", "text-anchor": nt.anchor || "middle" }, nt.text));
  svg.append(labels);
  const fig = document.createElement("figure");
  fig.className = "diagram";
  const wrap = document.createElement("div");
  wrap.append(svg);
  fig.append(wrap);
  if (caption) { const fc = document.createElement("figcaption"); fc.textContent = caption; fig.append(fc); }
  return fig;
}
