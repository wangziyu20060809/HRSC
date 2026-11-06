# -*- coding: utf-8 -*-
"""api/agent_api.py — 助手对话、历史、待确认动作"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import config
from agent import runtime, tools
from core import db, security
from core.errors import ApiError

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ChatBody(BaseModel):
    message: str
    session_id: int | None = None


@router.post("/chat")
def chat(body: ChatBody, user: dict = Depends(security.require_login)):
    out = runtime.chat(user, body.message, body.session_id)
    if out.get("code"):
        raise ApiError(out["code"], out.get("message", "提问失败"))
    return out


@router.get("/history")
def history(session_id: int, user: dict = Depends(security.require_login)):
    msgs = db.rows(
        "SELECT id, role, content, trace, citations, latency_ms, created_at "
        "FROM agent_messages WHERE session_id=? ORDER BY id",
        (session_id,),
    )
    import json

    for m in msgs:
        for k in ("trace", "citations"):
            try:
                m[k] = json.loads(m[k] or "[]")
            except json.JSONDecodeError:
                m[k] = []
    return {"code": 0, "messages": msgs}


@router.get("/status")
def status(user: dict = Depends(security.require_login)):
    return {
        "code": 0,
        "llm_ready": config.llm_ready(),
        "model": config.LLM_MODEL if config.llm_ready() else "规则模式",
        "agent_enabled": db.get_setting("agent_enabled", "1") == "1",
        "write_tools": db.get_setting("agent_allow_write_tools", "1") == "1",
        "tools": [
            {"name": n, "write": tools.is_write(n), "desc": s["schema"]["function"]["description"]}
            for n, s in tools.ALL_TOOLS.items()
        ],
    }


@router.post("/actions/{action_id}/confirm")
def confirm(action_id: int, user: dict = Depends(security.require_login)):
    out = tools.confirm_action(action_id, user)
    if out.get("code"):
        raise ApiError(out["code"], out.get("message", "执行失败"), 400, str(out.get("gate", "")))
    return out


@router.post("/actions/{action_id}/reject")
def reject(action_id: int, user: dict = Depends(security.require_login)):
    out = tools.reject_action(action_id, user)
    if out.get("code"):
        raise ApiError(out["code"], out.get("message", "操作失败"))
    return out


@router.get("/actions")
def actions(status: str = "pending", user: dict = Depends(security.require_login)):
    rows = db.rows(
        "SELECT * FROM agent_actions WHERE status=? ORDER BY id DESC LIMIT 50", (status,)
    )
    return {"code": 0, "actions": rows}
