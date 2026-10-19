from fastapi import APIRouter

from app.api import routes_chat, routes_collections, routes_eval, routes_lab, routes_system

router = APIRouter(prefix="/api")
for r in (routes_system, routes_collections, routes_chat, routes_eval, routes_lab):
    router.include_router(r.router)
