// لایه ارتباط با API

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function detailMessage(data, status) {
  if (!data) return `خطای ${status}`;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("، ");
  return `خطای ${status}`;
}

export async function api(path, { method = "GET", body, form, signal } = {}) {
  const opts = { method, signal, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  let res;
  try { res = await fetch("/api" + path, opts); }
  catch (e) { if (e.name === "AbortError") throw e; throw new ApiError("ارتباط با سرور برقرار نشد", 0); }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch (e) { /* پاسخ غیر JSON */ }
  if (!res.ok) throw new ApiError(detailMessage(data, res.status), res.status);
  return data;
}

export const get = (p, o) => api(p, o);
export const post = (p, body, o = {}) => api(p, { ...o, method: "POST", body });
export const patch = (p, body) => api(p, { method: "PATCH", body });
export const del = (p) => api(p, { method: "DELETE" });

/** استریم SSE روی POST؛ handlers: {sources, token, done, error} */
export async function streamChat(body, handlers, signal) {
  const res = await fetch("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
  });
  if (!res.ok) {
    let data = null; try { data = await res.json(); } catch (e) {}
    throw new ApiError(detailMessage(data, res.status), res.status);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i); buf = buf.slice(i + 2);
      let event = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      try { handlers[event]?.(JSON.parse(data)); } catch (e) { console.error(e); }
    }
  }
}

/** انتظار برای پایان یک کار پس‌زمینه با گزارش پیشرفت */
export async function waitJob(id, onProgress, interval = 700) {
  for (;;) {
    const j = await get(`/jobs/${id}`);
    onProgress?.(j);
    if (["done", "error", "cancelled"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, interval));
  }
}
