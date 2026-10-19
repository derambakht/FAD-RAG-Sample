from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import jobs
from app.api.deps import collection_or_404
from app.api.schemas import EvalItemCreate, EvalRunRequest, EvalSetCreate, GenerateRequest
from app.db import get_db
from app.rag.evaluation import generate_questions, run_eval

router = APIRouter(tags=["evaluation"])


def _set_or_404(sid: str) -> dict:
    s = get_db().get_eval_set(sid)
    if s is None:
        raise HTTPException(404, "مجموعه ارزیابی پیدا نشد")
    return s


@router.get("/eval-sets")
def list_sets(collection_id: str | None = None):
    return get_db().list_eval_sets(collection_id)


@router.post("/eval-sets", status_code=201)
def create_set(body: EvalSetCreate):
    collection_or_404(body.collection_id)
    return get_db().create_eval_set(body.collection_id, body.name.strip())


@router.get("/eval-sets/{sid}")
def get_set(sid: str):
    s = _set_or_404(sid)
    db = get_db()
    return {**s, "items_list": db.list_eval_items(sid), "runs": db.list_eval_runs(sid)}


@router.delete("/eval-sets/{sid}", status_code=204)
def delete_set(sid: str):
    _set_or_404(sid)
    get_db().delete_eval_set(sid)


@router.post("/eval-sets/{sid}/generate", status_code=202)
def generate(sid: str, body: GenerateRequest):
    s = _set_or_404(sid)
    return jobs.submit("eval", f"تولید {body.n} پرسش برای «{s['name']}»", generate_questions, sid, body.n,
                       body.llm_provider, body.llm_model, body.seed, meta={"eval_set_id": sid})


@router.post("/eval-sets/{sid}/items", status_code=201)
def add_item(sid: str, body: EvalItemCreate):
    s = _set_or_404(sid)
    db = get_db()
    gold_text = (body.gold_text or "").strip()
    if body.gold_chunk_id:
        c = db.get_chunk(body.gold_chunk_id)
        if c is None or c["collection_id"] != s["collection_id"]:
            raise HTTPException(400, "chunk طلایی در این پایگاه دانش پیدا نشد")
        gold_text = c["body"]
    if not gold_text:
        raise HTTPException(422, "متن طلایی یا شناسه chunk طلایی لازم است")
    db.add_eval_items(sid, [{"question": body.question.strip(), "gold_chunk_id": body.gold_chunk_id,
                             "gold_text": gold_text, "source": "manual"}])
    return {"ok": True}


@router.delete("/eval-items/{item_id}", status_code=204)
def delete_item(item_id: str):
    get_db().delete_eval_item(item_id)


@router.post("/eval-sets/{sid}/run", status_code=202)
def run(sid: str, body: EvalRunRequest):
    s = _set_or_404(sid)
    if not s["items"]:
        raise HTTPException(400, "مجموعه ارزیابی خالی است")
    for c in body.configs:
        collection_or_404(c.collection_id)
    return jobs.submit("eval", f"ارزیابی «{s['name']}» ({len(body.configs)} پیکربندی)", run_eval, sid,
                       [c.model_dump() for c in body.configs], body.k, meta={"eval_set_id": sid})


@router.delete("/eval-runs/{rid}", status_code=204)
def delete_run(rid: str):
    get_db().delete_eval_run(rid)
