"""تست chunkها و سنجش بازیابی (بخش ۹ راهنما): audit خودکار، تولید پرسش و Hit@k / MRR."""
from __future__ import annotations

import hashlib
import random
import re
import statistics

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.normalize import BAD_CHARS, clean_fa
from app.core.text_utils import overlap_coefficient, vocab_score, word_set

ENDS_OK = re.compile(r"[.!؟?:؛»)\]]$")
FLAG_LABELS = {
    "short": "توکن کم (chunk بی‌زمینه)",
    "low_vocab": "امتیاز واژگان پایین (متن خراب)",
    "bad_chars": "کاراکتر نرمال‌نشده",
    "no_end": "جمله نیمه‌کاره",
    "dup": "تکراری",
    "no_title": "بدون عنوان بخش",
}


# --- لایه ۱: audit --------------------------------------------------------------------
def audit_chunks(chunks: list[dict], min_tokens: int = 50, min_vocab: float = 0.6) -> dict:
    rows = []
    for i, c in enumerate(chunks):
        t = (c.get("body") or c.get("text") or "").strip()
        is_table = c.get("kind") == "table"
        rows.append({
            "id": c.get("id", i),
            "tokens": c.get("tokens") or 0,
            "vocab": round(vocab_score(t), 2),
            "ends_ok": True if is_table else bool(ENDS_OK.search(t)),
            "bad_chars": len(BAD_CHARS.findall(t)),
            "has_title": bool(c.get("section")),
            "hash": hashlib.md5(t.encode()).hexdigest()[:10],
        })
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["hash"]] = counts.get(r["hash"], 0) + 1
    for r in rows:
        r["dup"] = counts[r["hash"]] > 1
        flags = []
        if r["tokens"] < min_tokens:
            flags.append("short")
        if r["vocab"] < min_vocab:
            flags.append("low_vocab")
        if r["bad_chars"]:
            flags.append("bad_chars")
        if not r["ends_ok"]:
            flags.append("no_end")
        if r["dup"]:
            flags.append("dup")
        r["flags"] = flags
        r["suspect"] = bool(flags)
        if not r["has_title"]:
            r["flags"] = flags + ["no_title"]  # اطلاع‌رسانی؛ chunk را مشکوک نمی‌کند

    toks = [r["tokens"] for r in rows] or [0]
    q = statistics.quantiles(toks, n=4) if len(toks) > 1 else [toks[0]] * 3
    edges = [0, 50, 100, 200, 300, 400, 500, 700, 1000, 10**9]
    hist = [{"from": a, "to": b if b < 10**9 else None, "count": sum(a <= t < b for t in toks)}
            for a, b in zip(edges, edges[1:])]
    summary = {
        "total": len(rows),
        "suspects": sum(r["suspect"] for r in rows),
        "flags": {f: sum(f in r["flags"] for r in rows) for f in FLAG_LABELS},
        "flag_labels": FLAG_LABELS,
        "tokens": {"min": min(toks), "p25": round(q[0]), "median": round(q[1]), "p75": round(q[2]),
                   "max": max(toks), "mean": round(sum(toks) / len(toks), 1)},
        "vocab_mean": round(sum(r["vocab"] for r in rows) / max(len(rows), 1), 3),
        "histogram": hist,
        "thresholds": {"min_tokens": min_tokens, "min_vocab": min_vocab},
    }
    return {"rows": rows, "summary": summary}


# --- لایه ۳: سنجش کمّی ---------------------------------------------------------------
QGEN_PROMPT = ChatPromptTemplate.from_messages([
    ("human", """از متن زیر یک پرسش فارسی طبیعی بساز که پاسخش فقط در همین متن باشد.
از کلمات متن کپی نکن؛ با بیان دیگر بپرس. فقط پرسش را بنویس.

متن:
{chunk}"""),
])


def _clean_question(q: str) -> str:
    q = q.strip().split("\n")[0].strip()
    q = re.sub(r"^(پرسش|سوال|سؤال|question)\s*[:：]\s*", "", q, flags=re.I)
    q = re.sub(r"^[\d۰-۹]+[.)-]\s*", "", q)
    return q.strip(" \"'«»*")


def generate_questions(progress, set_id: str, n: int, llm_provider: str, llm_model: str,
                       seed: int = 7, min_tokens: int = 60) -> dict:
    from app.db import get_db
    from app.providers import get_llm

    db = get_db()
    es = db.get_eval_set(set_id)
    rows = db.all_chunks(es["collection_id"])
    pool = [r for r in rows if (r["tokens"] or 0) >= min_tokens and r["kind"] == "text"] or rows
    if not pool:
        raise ValueError("این پایگاه دانش هنوز chunk ندارد")
    sample = random.Random(seed).sample(pool, min(n, len(pool)))
    chain = QGEN_PROMPT | get_llm(llm_provider, llm_model, 0.3) | StrOutputParser()
    items = []
    for i, r in enumerate(sample):
        progress(i / len(sample), f"تولید پرسش {i + 1} از {len(sample)}")
        q = _clean_question(chain.invoke({"chunk": r["text"]}))
        if q:
            items.append({"question": q, "gold_chunk_id": r["id"], "gold_text": r["body"], "source": "generated"})
    db.add_eval_items(set_id, items)
    return {"added": len(items)}


def find_rank(hits, item: dict, exact: bool, threshold: float = 0.6) -> int | None:
    """رتبه اولین chunk درست. در تطبیق متنی هر دو طرف نرمال می‌شوند تا پایگاهی که بدون clean_fa
    ساخته شده (شکل‌های نمایشی، ي/ك) فقط به‌خاطر کدگذاری متفاوت بازنده حساب نشود."""
    gold = clean_fa(item["gold_text"])
    gold_words = len(word_set(gold))
    for i, h in enumerate(hits, 1):
        if exact:
            if h.chunk_id == item["gold_chunk_id"]:
                return i
            continue
        body = clean_fa(h.body)
        if min(gold_words, len(word_set(body))) >= 5 and overlap_coefficient(gold, body) >= threshold:
            return i
    return None


def run_eval(progress, set_id: str, configs: list[dict], k: int = 5) -> dict:
    """هر config: {collection_id, mode, rerank, clean_query}. نتیجه: Hit@k و MRR برای هر پیکربندی.

    اگر پایگاه هدف همان پایگاه مجموعه ارزیابی باشد، تطبیق با شناسه chunk است؛ وگرنه
    (مثلاً پایگاهی با chunkبندی دیگر) با همپوشانی کلمات متن طلایی.
    """
    from app.db import get_db
    from app.rag.rerank import normalize_method
    from app.rag.retrieval import MODE_LABELS, search

    db = get_db()
    es = db.get_eval_set(set_id)
    items = db.list_eval_items(set_id)
    if not items:
        raise ValueError("مجموعه ارزیابی خالی است")
    total = len(items) * len(configs)
    done = 0
    results = []
    for cfg in configs:
        col = db.get_collection(cfg["collection_id"])
        if col is None:
            continue
        same = col["id"] == es["collection_id"]
        ranks = []
        for it in items:
            progress(done / total, f"{col['name']} · {MODE_LABELS.get(cfg['mode'], cfg['mode'])}: پرسش {len(ranks) + 1}")
            exact = same and bool(it["gold_chunk_id"]) and db.get_chunk(it["gold_chunk_id"]) is not None
            hits, _ = search(col, it["question"], cfg["mode"], k, rerank=cfg.get("rerank", "none"),
                             clean=cfg.get("clean_query", True), jev=cfg.get("jev", False))
            ranks.append(find_rank(hits, it, exact))
            done += 1
        n = len(ranks)
        results.append({
            "collection_id": col["id"], "collection_name": col["name"],
            "embedding": f"{col['embedding_provider']}/{col['embedding_model']}",
            "strategy": (col.get("settings") or {}).get("strategy", "structure"),
            "mode": cfg["mode"], "rerank": normalize_method(cfg.get("rerank", "none")), "jev": cfg.get("jev", False),
            "clean_query": cfg.get("clean_query", True),
            "hit": round(sum(r is not None for r in ranks) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
            "n": n,
            "ranks": [{"item_id": it["id"], "rank": r} for it, r in zip(items, ranks)],
        })
    run = db.save_eval_run(set_id, {"k": k, "configs": configs}, {"k": k, "results": results})
    return {"run_id": run["id"], "results": results}
