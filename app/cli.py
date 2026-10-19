"""خط فرمان برای کار بدون پنل (اسکریپت، سرور، نوت‌بوک).

نمونه‌ها:
  python -m app.cli kb list
  python -m app.cli kb create "آیین‌نامه‌ها" --provider ollama --model bge-m3 --backend qdrant
  python -m app.cli ingest "آیین‌نامه‌ها" docs/*.pdf
  python -m app.cli search "آیین‌نامه‌ها" "حداقل نمره قبولی؟" --mode hybrid
  python -m app.cli ask "آیین‌نامه‌ها" "حداقل نمره قبولی؟" --llm-provider ollama --llm-model qwen2.5:7b
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import tempfile
from pathlib import Path

from app.config import get_settings
from app.db import get_db


def _kb(name_or_id: str) -> dict:
    for c in get_db().list_collections():
        if name_or_id in (c["id"], c["name"]):
            return c
    sys.exit(f"پایگاه دانش «{name_or_id}» پیدا نشد")


def _progress(frac: float, msg: str = "") -> None:
    print(f"\r  {frac * 100:5.1f}%  {msg[:70]:<70}", end="", flush=True)


def cmd_kb(a) -> None:
    db = get_db()
    if a.action == "list":
        for c in db.list_collections():
            print(f"{c['name']}\t{c['vector_backend']}\t{c['embedding_provider']}/{c['embedding_model']}\t"
                  f"{c['documents']} سند\t{c['chunks']} chunk\t{c['id']}")
    elif a.action == "create":
        c = db.create_collection(name=a.name, embedding_provider=a.provider, embedding_model=a.model,
                                 vector_backend=a.backend or get_settings().vector_store,
                                 settings={"max_tokens": a.max_tokens, "strategy": a.strategy})
        print("ساخته شد:", c["id"])
    elif a.action == "delete":
        from app.rag.ingest import delete_collection
        delete_collection(_kb(a.name)["id"])
        print("حذف شد")


def cmd_ingest(a) -> None:
    from app.rag.ingest import ingest_document, store_upload
    col = _kb(a.kb)
    db = get_db()
    files = [Path(p) for pat in a.files for p in (glob.glob(pat) or [pat])]
    for f in files:
        fd, name = tempfile.mkstemp(suffix=f.suffix)
        os.close(fd)  # روی ویندوز فایل باز قابل جابه‌جایی نیست
        tmp = Path(name)
        shutil.copy(f, tmp)
        path, digest, size = store_upload(col["id"], tmp, f.name)
        if db.find_document_by_hash(col["id"], digest):
            print(f"تکراری: {f.name}")
            continue
        doc = db.create_document(col["id"], f.name, str(path), digest, size, {})
        print(f"{f.name}:")
        res = ingest_document(_progress, doc["id"])
        print(f"\n  {res['chunks']} chunk", *(f"\n  ⚠ {w}" for w in res["warnings"]))


def cmd_search(a) -> None:
    from app.rag.retrieval import search
    hits, info = search(_kb(a.kb), a.query, a.mode, a.k)
    print("پرسش نرمال‌شده:", info["query"], info["timings"])
    for i, h in enumerate(hits, 1):
        print(f"\n[{i}] {h.source} ص{h.page} · {h.section} · score={h.score}\n{h.body[:300]}")


def cmd_ask(a) -> None:
    from app.rag.chain import answer
    s = get_settings()
    text, hits = answer(_kb(a.kb)["id"], a.question, a.llm_provider or s.default_llm_provider,
                        a.llm_model or s.default_llm_model, mode=a.mode, k=a.k)
    print(text)
    for i, h in enumerate(hits, 1):
        print(f"  [{i}] {h.source}، صفحه {h.page} — {h.section}")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="RAG فارسی — خط فرمان")
    sub = p.add_subparsers(dest="cmd", required=True)

    kb = sub.add_parser("kb", help="مدیریت پایگاه‌های دانش")
    kb.add_argument("action", choices=["list", "create", "delete"])
    kb.add_argument("name", nargs="?")
    kb.add_argument("--provider", default=get_settings().default_embedding_provider)
    kb.add_argument("--model", default=get_settings().default_embedding_model)
    kb.add_argument("--backend", choices=["chroma", "qdrant"])
    kb.add_argument("--strategy", default="structure", choices=["structure", "recursive", "fixed"])
    kb.add_argument("--max-tokens", type=int, default=400)
    kb.set_defaults(fn=cmd_kb)

    ing = sub.add_parser("ingest", help="ایندکس فایل‌ها")
    ing.add_argument("kb")
    ing.add_argument("files", nargs="+")
    ing.set_defaults(fn=cmd_ingest)

    for name, fn, arg in (("search", cmd_search, "query"), ("ask", cmd_ask, "question")):
        sp = sub.add_parser(name)
        sp.add_argument("kb")
        sp.add_argument(arg)
        sp.add_argument("--mode", default="hybrid", choices=["dense", "bm25", "hybrid"])
        sp.add_argument("-k", type=int, default=5)
        if name == "ask":
            sp.add_argument("--llm-provider")
            sp.add_argument("--llm-model")
        sp.set_defaults(fn=fn)

    a = p.parse_args()
    if a.cmd == "kb" and a.action != "list" and not a.name:
        p.error("نام پایگاه دانش لازم است")
    from app.vectorstores import close_clients
    try:
        a.fn(a)
    finally:
        close_clients()


if __name__ == "__main__":
    main()
