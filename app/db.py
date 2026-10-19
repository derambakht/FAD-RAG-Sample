"""رجیستری SQLite: پایگاه‌های دانش، اسناد، chunkها و مجموعه‌های ارزیابی.

متن chunkها اینجا هم نگه داشته می‌شود؛ BM25، audit و ارزیابی بدون نیاز به vector store کار می‌کنند
و vector store فقط بردارها را نگه می‌دارد.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

from app.config import get_settings

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER,
    vector_backend TEXT NOT NULL,
    vector_collection TEXT NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    pages INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    stats TEXT NOT NULL DEFAULT '{}',
    options TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_docs_col ON documents(collection_id);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    text TEXT NOT NULL,
    body TEXT NOT NULL,
    section TEXT DEFAULT '',
    page INTEGER,
    page_end INTEGER,
    tokens INTEGER,
    kind TEXT DEFAULT 'text'
);
CREATE INDEX IF NOT EXISTS ix_chunks_col ON chunks(collection_id);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id);
CREATE TABLE IF NOT EXISTS eval_sets (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_items (
    id TEXT PRIMARY KEY,
    eval_set_id TEXT NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    gold_chunk_id TEXT,
    gold_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_col ON chat_sessions(collection_id, updated_at);
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_session ON chat_messages(session_id, created_at);
CREATE TABLE IF NOT EXISTS sales_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    sheet TEXT DEFAULT '',
    row_no INTEGER,
    supplier TEXT NOT NULL DEFAULT '',
    supplier_code TEXT DEFAULT '',
    branch TEXT NOT NULL DEFAULT '',
    barcode TEXT DEFAULT '',
    product TEXT NOT NULL DEFAULT '',
    qty REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    discount REAL NOT NULL DEFAULT 0,
    extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_sales_col ON sales_rows(collection_id);
CREATE INDEX IF NOT EXISTS ix_sales_doc ON sales_rows(document_id);
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    eval_set_id TEXT NOT NULL REFERENCES eval_sets(id) ON DELETE CASCADE,
    config TEXT NOT NULL,
    results TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

JSON_FIELDS = {"settings", "stats", "options", "config", "results", "meta"}
_lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_FIELDS & d.keys():
        d[k] = json.loads(d[k] or "{}")
    return d


class DB:
    def __init__(self, path: str | None = None):
        self.path = str(path or get_settings().db_path)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        with _lock:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def _all(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        with self.conn() as c:
            return [_row(r) for r in c.execute(sql, tuple(args)).fetchall()]

    def _one(self, sql: str, args: Iterable[Any] = ()) -> dict | None:
        with self.conn() as c:
            return _row(c.execute(sql, tuple(args)).fetchone())

    def _exec(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self.conn() as c:
            return c.execute(sql, tuple(args)).rowcount

    # --- collections ---
    def create_collection(self, **kw) -> dict:
        cid = new_id()
        kw.setdefault("vector_collection", "kb_" + cid.replace("-", "")[:16])
        with self.conn() as c:
            c.execute(
                """INSERT INTO collections(id,name,description,embedding_provider,embedding_model,embedding_dim,
                   vector_backend,vector_collection,settings,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (cid, kw["name"], kw.get("description", ""), kw["embedding_provider"], kw["embedding_model"],
                 kw.get("embedding_dim"), kw["vector_backend"], kw["vector_collection"],
                 json.dumps(kw.get("settings", {}), ensure_ascii=False), now()),
            )
        return self.get_collection(cid)

    def get_collection(self, cid: str) -> dict | None:
        return self._one(
            """SELECT c.*, (SELECT COUNT(*) FROM documents d WHERE d.collection_id=c.id) AS documents,
                      (SELECT COUNT(*) FROM chunks k WHERE k.collection_id=c.id) AS chunks,
                      (SELECT COUNT(*) FROM sales_rows s WHERE s.collection_id=c.id) AS table_rows
               FROM collections c WHERE c.id=?""", (cid,))

    def list_collections(self) -> list[dict]:
        return self._all(
            """SELECT c.*, (SELECT COUNT(*) FROM documents d WHERE d.collection_id=c.id) AS documents,
                      (SELECT COUNT(*) FROM chunks k WHERE k.collection_id=c.id) AS chunks,
                      (SELECT COUNT(*) FROM sales_rows s WHERE s.collection_id=c.id) AS table_rows
               FROM collections c ORDER BY c.created_at DESC""")

    def update_collection(self, cid: str, **kw) -> None:
        sets, args = [], []
        for k, v in kw.items():
            sets.append(f"{k}=?")
            args.append(json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else v)
        if sets:
            self._exec(f"UPDATE collections SET {', '.join(sets)} WHERE id=?", [*args, cid])

    def bump_version(self, cid: str) -> None:
        self._exec("UPDATE collections SET version=version+1 WHERE id=?", (cid,))

    def delete_collection(self, cid: str) -> None:
        self._exec("DELETE FROM collections WHERE id=?", (cid,))

    # --- documents ---
    def create_document(self, collection_id: str, filename: str, path: str, sha256: str, size: int,
                        options: dict) -> dict:
        did = new_id()
        self._exec(
            """INSERT INTO documents(id,collection_id,filename,path,sha256,size,options,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (did, collection_id, filename, path, sha256, size, json.dumps(options, ensure_ascii=False), now()))
        return self.get_document(did)

    def get_document(self, did: str) -> dict | None:
        return self._one(
            "SELECT d.*, (SELECT COUNT(*) FROM chunks k WHERE k.document_id=d.id) AS chunks FROM documents d WHERE d.id=?",
            (did,))

    def find_document_by_hash(self, collection_id: str, sha256: str) -> dict | None:
        return self._one("SELECT * FROM documents WHERE collection_id=? AND sha256=?", (collection_id, sha256))

    def list_documents(self, collection_id: str) -> list[dict]:
        return self._all(
            """SELECT d.*, (SELECT COUNT(*) FROM chunks k WHERE k.document_id=d.id) AS chunks
               FROM documents d WHERE d.collection_id=? ORDER BY d.created_at DESC""", (collection_id,))

    def update_document(self, did: str, **kw) -> None:
        sets, args = [], []
        for k, v in kw.items():
            sets.append(f"{k}=?")
            args.append(json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else v)
        self._exec(f"UPDATE documents SET {', '.join(sets)} WHERE id=?", [*args, did])

    def delete_document(self, did: str) -> None:
        self._exec("DELETE FROM documents WHERE id=?", (did,))

    def mark_interrupted(self) -> None:
        self._exec("UPDATE documents SET status='error', error='پردازش با توقف سرور قطع شد' "
                   "WHERE status IN ('pending','processing')")

    # --- chunks ---
    def insert_chunks(self, rows: list[dict]) -> None:
        with self.conn() as c:
            c.executemany(
                """INSERT INTO chunks(id,collection_id,document_id,idx,text,body,section,page,page_end,tokens,kind)
                   VALUES(:id,:collection_id,:document_id,:idx,:text,:body,:section,:page,:page_end,:tokens,:kind)""",
                rows)

    def chunk_ids_for_document(self, did: str) -> list[str]:
        with self.conn() as c:
            return [r[0] for r in c.execute("SELECT id FROM chunks WHERE document_id=?", (did,))]

    def delete_chunks_for_document(self, did: str) -> None:
        self._exec("DELETE FROM chunks WHERE document_id=?", (did,))

    def get_chunks(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        rows = self._all(
            f"""SELECT k.*, d.filename AS source FROM chunks k JOIN documents d ON d.id=k.document_id
                WHERE k.id IN ({q})""", ids)
        return {r["id"]: r for r in rows}

    def all_chunks(self, collection_id: str, document_ids: list[str] | None = None) -> list[dict]:
        sql = """SELECT k.*, d.filename AS source FROM chunks k JOIN documents d ON d.id=k.document_id
                 WHERE k.collection_id=?"""
        args: list[Any] = [collection_id]
        if document_ids:
            sql += f" AND k.document_id IN ({','.join('?' * len(document_ids))})"
            args += document_ids
        return self._all(sql + " ORDER BY d.created_at, k.idx", args)

    def list_chunks(self, collection_id: str, document_id: str | None, q: str | None,
                    offset: int, limit: int) -> tuple[list[dict], int]:
        where, args = ["k.collection_id=?"], [collection_id]
        if document_id:
            where.append("k.document_id=?")
            args.append(document_id)
        if q:
            where.append("k.text LIKE ?")
            args.append(f"%{q}%")
        w = " AND ".join(where)
        with self.conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM chunks k WHERE {w}", args).fetchone()[0]
        rows = self._all(
            f"""SELECT k.*, d.filename AS source FROM chunks k JOIN documents d ON d.id=k.document_id
                WHERE {w} ORDER BY d.created_at, k.idx LIMIT ? OFFSET ?""", [*args, limit, offset])
        return rows, total

    def get_chunk(self, chunk_id: str) -> dict | None:
        return self.get_chunks([chunk_id]).get(chunk_id)

    # --- داده‌های جدولی (اکسل فروش) ---
    def insert_sales_rows(self, collection_id: str, document_id: str, records: list[dict]) -> None:
        with self.conn() as c:
            c.executemany(
                """INSERT INTO sales_rows(collection_id,document_id,sheet,row_no,supplier,supplier_code,branch,barcode,
                   product,qty,amount,discount,extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(collection_id, document_id, r.get("sheet", ""), r.get("row_no"), r["supplier"],
                  r.get("supplier_code", ""), r["branch"], r.get("barcode", ""), r.get("product", ""),
                  r["qty"], r["amount"], r["discount"], json.dumps(r.get("extra") or {}, ensure_ascii=False))
                 for r in records])

    def delete_sales_rows_for_document(self, did: str) -> None:
        self._exec("DELETE FROM sales_rows WHERE document_id=?", (did,))

    def sales_rows(self, collection_id: str, document_ids: list[str] | None = None) -> list[dict]:
        sql = """SELECT s.sheet, s.row_no, s.supplier, s.supplier_code, s.branch, s.barcode, s.product, s.qty,
                        s.amount, s.discount, s.document_id, d.filename AS source
                 FROM sales_rows s JOIN documents d ON d.id=s.document_id
                 WHERE s.collection_id=? AND d.status='ready'"""  # نسخه در حال پردازش با نسخه قبلی دوبار شمرده نشود
        args: list[Any] = [collection_id]
        if document_ids:
            sql += f" AND s.document_id IN ({','.join('?' * len(document_ids))})"
            args += document_ids
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql + " ORDER BY s.id", args).fetchall()]

    def sales_keys(self, document_id: str) -> set[tuple]:
        """کلید هر سطر (تامین‌کننده، شعبه، بارکد یا نام کالا) برای تشخیص نسخه‌های مختلف یک گزارش."""
        with self.conn() as c:
            return {(r[0], r[1], r[2] or r[3]) for r in c.execute(
                "SELECT supplier, branch, barcode, product FROM sales_rows WHERE document_id=?", (document_id,))}

    def count_sales_rows(self, collection_id: str) -> int:
        with self.conn() as c:
            return c.execute("SELECT COUNT(*) FROM sales_rows WHERE collection_id=?", (collection_id,)).fetchone()[0]

    # --- evaluation ---
    def create_eval_set(self, collection_id: str, name: str) -> dict:
        sid = new_id()
        self._exec("INSERT INTO eval_sets(id,collection_id,name,created_at) VALUES(?,?,?,?)",
                   (sid, collection_id, name, now()))
        return self.get_eval_set(sid)

    def get_eval_set(self, sid: str) -> dict | None:
        return self._one(
            """SELECT s.*, (SELECT COUNT(*) FROM eval_items i WHERE i.eval_set_id=s.id) AS items
               FROM eval_sets s WHERE s.id=?""", (sid,))

    def list_eval_sets(self, collection_id: str | None = None) -> list[dict]:
        sql = """SELECT s.*, c.name AS collection_name,
                        (SELECT COUNT(*) FROM eval_items i WHERE i.eval_set_id=s.id) AS items
                 FROM eval_sets s JOIN collections c ON c.id=s.collection_id"""
        if collection_id:
            return self._all(sql + " WHERE s.collection_id=? ORDER BY s.created_at DESC", (collection_id,))
        return self._all(sql + " ORDER BY s.created_at DESC")

    def delete_eval_set(self, sid: str) -> None:
        self._exec("DELETE FROM eval_sets WHERE id=?", (sid,))

    def add_eval_items(self, sid: str, items: list[dict]) -> None:
        with self.conn() as c:
            c.executemany(
                """INSERT INTO eval_items(id,eval_set_id,question,gold_chunk_id,gold_text,source,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                [(new_id(), sid, it["question"], it.get("gold_chunk_id"), it["gold_text"],
                  it.get("source", "manual"), now()) for it in items])

    def list_eval_items(self, sid: str) -> list[dict]:
        return self._all("SELECT * FROM eval_items WHERE eval_set_id=? ORDER BY created_at", (sid,))

    def delete_eval_item(self, item_id: str) -> None:
        self._exec("DELETE FROM eval_items WHERE id=?", (item_id,))

    def save_eval_run(self, sid: str, config: dict, results: dict) -> dict:
        rid = new_id()
        self._exec("INSERT INTO eval_runs(id,eval_set_id,config,results,created_at) VALUES(?,?,?,?,?)",
                   (rid, sid, json.dumps(config, ensure_ascii=False), json.dumps(results, ensure_ascii=False), now()))
        return self._one("SELECT * FROM eval_runs WHERE id=?", (rid,))

    def list_eval_runs(self, sid: str) -> list[dict]:
        return self._all("SELECT * FROM eval_runs WHERE eval_set_id=? ORDER BY created_at DESC", (sid,))

    def delete_eval_run(self, rid: str) -> None:
        self._exec("DELETE FROM eval_runs WHERE id=?", (rid,))

    # --- جلسه‌های گفتگو ---
    def create_chat_session(self, collection_id: str, title: str = "") -> dict:
        sid, ts = new_id(), now()
        self._exec("INSERT INTO chat_sessions(id,collection_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                   (sid, collection_id, title, ts, ts))
        return self.get_chat_session(sid)

    def get_chat_session(self, sid: str) -> dict | None:
        return self._one(
            """SELECT s.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id=s.id) AS messages
               FROM chat_sessions s WHERE s.id=?""", (sid,))

    def list_chat_sessions(self, collection_id: str) -> list[dict]:
        return self._all(
            """SELECT s.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id=s.id) AS messages
               FROM chat_sessions s WHERE s.collection_id=? ORDER BY s.updated_at DESC""", (collection_id,))

    def rename_chat_session(self, sid: str, title: str) -> None:
        self._exec("UPDATE chat_sessions SET title=? WHERE id=?", (title, sid))

    def delete_chat_session(self, sid: str) -> None:
        self._exec("DELETE FROM chat_sessions WHERE id=?", (sid,))

    def delete_chat_sessions(self, collection_id: str) -> int:
        return self._exec("DELETE FROM chat_sessions WHERE collection_id=?", (collection_id,))

    def add_chat_message(self, session_id: str, role: str, content: str, meta: dict | None = None) -> None:
        ts = now()
        with self.conn() as c:
            c.execute("INSERT INTO chat_messages(id,session_id,role,content,meta,created_at) VALUES(?,?,?,?,?,?)",
                      (new_id(), session_id, role, content, json.dumps(meta or {}, ensure_ascii=False), ts))
            c.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (ts, session_id))

    def recent_user_questions(self, collection_id: str, exclude_session: str | None = None, limit: int = 30) -> list[str]:
        """آخرین پرسش‌های کاربر در گفتگوهای این پایگاه دانش (جدیدترین اول)."""
        rows = self._all(
            """SELECT m.content FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id
               WHERE s.collection_id=? AND m.role='user' AND m.session_id<>?
               ORDER BY m.created_at DESC, m.rowid DESC LIMIT ?""", (collection_id, exclude_session or "", limit))
        return [r["content"] for r in rows]

    def list_chat_messages(self, session_id: str) -> list[dict]:
        # ترتیب درج (rowid) برای پیام‌هایی که در یک ثانیه ثبت شده‌اند
        return self._all("SELECT * FROM chat_messages WHERE session_id=? ORDER BY created_at, rowid", (session_id,))


_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        _db = DB()
    return _db


def reset_db(path: str | None = None) -> DB:
    """برای تست‌ها."""
    global _db
    _db = DB(path)
    return _db
