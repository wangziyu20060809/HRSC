# -*- coding: utf-8 -*-
"""app.py — 山海旅居 · 房态与入住协同 MVP 入口

启动：python -m uvicorn app:app --port 8100
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from api import admin_api, agent_api, auth as auth_api, handover, kb_api, rooms, tasks
from core import db, security
from core.errors import install_error_handlers
from core.seed import init as seed_init

BASE = config.BASE_DIR

templates = Jinja2Templates(directory=str(BASE / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    out = seed_init()
    app.state.seed = out
    yield


app = FastAPI(title="山海旅居 · 房态与入住协同 MVP", version="0.1.0", lifespan=lifespan)
install_error_handlers(app)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

for r in (auth_api.router, rooms.router, tasks.router, handover.router,
          agent_api.router, kb_api.router, admin_api.router):
    app.include_router(r)


# ---------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------
@app.get("/")
def index(request: Request):
    user = security.current_user(request)
    if not user:
        return RedirectResponse("/login")
    return RedirectResponse("/admin" if user["role"] == "admin" else "/staff")


@app.get("/login")
def login_page(request: Request):
    if security.current_user(request):
        return RedirectResponse("/")
    return templates.TemplateResponse(request, "login.html", {"hotel": config.HOTEL_NAME})


@app.get("/staff")
def staff_page(request: Request):
    user = security.current_user(request)
    if not user:
        return RedirectResponse("/login")
    if user["role"] == "admin":
        return RedirectResponse("/admin")
    return templates.TemplateResponse(request, "staff.html", {"user": user, "hotel": config.HOTEL_NAME})


@app.get("/admin")
def admin_page(request: Request):
    user = security.current_user(request)
    if not user:
        return RedirectResponse("/login")
    if user["role"] != "admin":
        return RedirectResponse("/staff")
    return templates.TemplateResponse(request, "admin.html", {"user": user, "hotel": config.HOTEL_NAME})


@app.get("/healthz")
def healthz():
    """公开健康检查：只暴露是否就绪，不暴露账号与数据明细"""
    from kb import store as kb_store

    return {
        "status": "ok",
        "llm_ready": config.llm_ready(),
        "model": config.LLM_MODEL if config.llm_ready() else "rule-fallback",
        "rooms": db.scalar("SELECT COUNT(*) FROM rooms"),
        "events": db.scalar("SELECT COUNT(*) FROM room_events"),
        "kb": kb_store.stats(),
    }
