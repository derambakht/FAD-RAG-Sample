"""آزمون واقعی گفتگو روی داده‌های اکسل با یک LLM واقعی (OpenAI یا هر سرویس سازگار مثل LM Studio/Ollama).

پاسخ درست هر پرسش مستقل از LLM و مستقیم از سطرهای فایل محاسبه می‌شود و بررسی می‌شود که عدد درست در پاسخ آمده باشد.

    python scripts/eval_excel_chat.py data.xlsx --base-url http://127.0.0.1:1234/v1 --model qwen2.5-7b-instruct
    python scripts/eval_excel_chat.py data.xlsx --model gpt-4o-mini        (با OPENAI_API_KEY در محیط)

پوشه داده موقت است و پایگاه دانش‌های واقعی دست نمی‌خورند. embedding جعلی است چون این آزمون مسیر SQL را می‌سنجد.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--only", type=int, nargs="*", help="فقط این شماره پرسش‌ها")
    a = ap.parse_args()

    os.environ.update({"RAG_ENV_FILE": "none", "DATA_DIR": tempfile.mkdtemp(prefix="rag-excel-eval-")})
    if a.base_url:
        os.environ["OPENAI_BASE_URL"] = a.base_url
        os.environ.setdefault("OPENAI_API_KEY", a.api_key or "local")
    elif a.api_key:
        os.environ["OPENAI_API_KEY"] = a.api_key

    from fastapi.testclient import TestClient
    from langchain_core.embeddings import Embeddings

    import app.api.routes_collections as rc
    import app.rag.retrieval as retrieval
    from app.core.normalize import clean_fa
    from app.core.spreadsheet import parse_file

    class HashEmbeddings(Embeddings):
        def _v(self, t):
            v = [0.0] * 256
            for w in re.findall(r"[\w‌]+", t):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
            n = math.sqrt(sum(x * x for x in v)) or 1
            return [x / n for x in v]

        def embed_documents(self, texts):
            return [self._v(t) for t in texts]

        def embed_query(self, text):
            return self._v(text)

    retrieval.get_embeddings = lambda p, m: HashEmbeddings()
    rc._check_provider = lambda p, m: None

    # --- پاسخ‌های درست، مستقیم از فایل -------------------------------------------------------
    recs = parse_file(Path(a.xlsx)).records
    by_branch: dict[str, dict] = defaultdict(lambda: {"qty": 0.0, "amount": 0.0, "discount": 0.0})
    for r in recs:
        for f in ("qty", "amount", "discount"):
            by_branch[r["branch"]][f] += r[f]
    branches = sorted(by_branch, key=lambda b: -by_branch[b]["amount"])
    pick = [b for b in ("شعبه مگامال", "شعبه اصفهان", "شعبه پاژ مشهد", "شعبه تنکابن", "شعبه شیراز") if b in by_branch]
    pick += [b for b in branches if b not in pick]
    b1, b2, b3, b4, b5 = (pick * 5)[:5]
    b4 = next((b for b in reversed(pick) if b != b1), b1)  # پرسش پیگیری باید شعبه دیگری باشد
    short = lambda b: b.replace("شعبه ", "")  # noqa: E731
    sup = sorted({r["supplier"] for r in recs})[0]
    tot = {f: sum(r[f] for r in recs if r["supplier"] == sup) for f in ("qty", "amount", "discount")}
    shiraz = defaultdict(float)
    for r in recs:
        if r["branch"] == b5:
            shiraz[r["product"]] += r["qty"]
    top_prod = max(shiraz, key=shiraz.get)
    top5_qty = sorted(by_branch, key=lambda b: -by_branch[b]["qty"])[:5]
    prod = recs[0]["product"]
    prod_disc = sum(r["discount"] for r in recs if r["product"] == prod)
    prod_branches = len({r["branch"] for r in recs if r["product"] == prod})
    n = lambda x: str(round(x))  # noqa: E731

    cases = [
        (f"جمع مبلغ فروش شعبه {short(b1)} چقدر است؟", [n(by_branch[b1]["amount"])], []),
        ("و در شعبه {}؟".format(short(b4)), [n(by_branch[b4]["amount"])], "follow"),
        (f"در شعبه {short(b2)} چند عدد کالا فروخته شده است؟", [n(by_branch[b2]["qty"])], []),
        (f"مجموع تخفیف سهم تامین کننده در {short(b3)} چقدر بوده؟", [n(by_branch[b3]["discount"])], []),
        ("کدام شعبه بیشترین مبلغ فروش را داشته و مبلغ آن چقدر است؟", [n(by_branch[branches[0]]["amount"])],
         [short(branches[0])]),
        (f"تعداد فروش، مبلغ فروش و تخفیف کل تامین کننده {sup} را بگو.", [n(tot["qty"]), n(tot["amount"]), n(tot["discount"])], []),
        (f"پرفروش‌ترین کالا از نظر تعداد در شعبه {short(b5)} کدام است؟", [n(shiraz[top_prod])], [top_prod.split()[0]]),
        ("۵ شعبه برتر از نظر تعداد فروش را با تعدادشان فهرست کن.", [n(by_branch[b]["qty"]) for b in top5_qty], []),
        (f"جمع تخفیف کالای «{prod}» در همه شعبه‌ها چقدر است و در چند شعبه فروش داشته؟", [n(prod_disc), str(prod_branches)], []),
    ]

    from app.main import app
    ok_count = 0
    results = []
    with TestClient(app) as c:
        col = c.post("/api/collections", json={"name": "ارزیابی اکسل", "embedding_provider": "openai",
                                               "embedding_model": "hash", "vector_backend": "chroma"}).json()
        with open(a.xlsx, "rb") as f:
            job = c.post(f"/api/collections/{col['id']}/documents", files=[("files", (Path(a.xlsx).name, f))]).json()
        jid = job["jobs"][0]["id"]
        while (j := c.get(f"/api/jobs/{jid}").json())["status"] not in ("done", "error"):
            time.sleep(0.5)
        assert j["status"] == "done", j
        print(f"ingest ok: {len(recs)} rows, {len(by_branch)} branches\n", flush=True)
        prev = None
        for i, (q, nums, extra) in enumerate(cases, 1):
            if a.only and i not in a.only:
                continue
            history = []
            if extra == "follow" and prev:
                history = [{"role": "user", "content": prev[0]}, {"role": "assistant", "content": prev[1]}]
            words = [] if extra == "follow" else extra
            t = time.time()
            with c.stream("POST", "/api/chat", json={"collection_id": col["id"], "question": q, "history": history,
                                                     "llm_provider": "openai", "llm_model": a.model,
                                                     "temperature": 0}) as r:
                body = "".join(r.iter_text())
            ans, sql, err = "", None, None
            ev = None
            for ln in body.splitlines():
                if ln.startswith("event: "):
                    ev = ln[7:]
                elif ln.startswith("data: "):
                    d = json.loads(ln[6:])
                    if ev == "token":
                        ans += d["t"]
                    elif ev == "sources":
                        sql = (d.get("analytics") or {}).get("sql")
                    elif ev == "error":
                        err = d["message"]
            plain = clean_fa(ans).replace(",", "").replace("٬", "")
            missing = [x for x in nums if x not in plain] + [w for w in words if clean_fa(w) not in clean_fa(ans)]
            ok = not missing and not err
            ok_count += ok
            prev = (q, ans)
            results.append({"q": q, "ok": ok, "missing": missing, "sql": sql, "answer": ans, "error": err,
                            "s": round(time.time() - t, 1)})
            print(f"[{'OK' if ok else 'FAIL'}] {i}. {q}  ({results[-1]['s']}s)\n  SQL: {sql}\n  پاسخ: {ans.strip()[:600]}"
                  + (f"\n  انتظار: {missing}" if missing else "") + (f"\n  خطا: {err}" if err else "") + "\n", flush=True)
    print(f"نتیجه: {ok_count} از {len(results)} درست")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
