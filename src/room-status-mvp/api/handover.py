# -*- coding: utf-8 -*-
"""api/handover.py — 交接班：系统生成草稿，人工补充后提交"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import db, security
from domain import metrics

router = APIRouter(prefix="/api/handover", tags=["handover"])


@router.get("/draft")
def draft(user: dict = Depends(security.require_login)):
    s = metrics.shift_summary()
    return {"code": 0, **{k: v for k, v in s.items() if k != "tasks"}, "tasks": s["tasks"]}


class HandoverBody(BaseModel):
    shift: str = "当班"
    summary: str
    issues: str = ""


@router.post("")
def create(body: HandoverBody, user: dict = Depends(security.require_login)):
    if not body.summary.strip():
        from core.errors import ApiError

        raise ApiError(40001, "交接内容不能为空")
    hid = db.exec_write(
        "INSERT INTO handovers(shift, summary, issues, created_by, created_at) VALUES(?,?,?,?,?)",
        (body.shift, body.summary.strip(), body.issues.strip(), user["display"], db.now_str()),
    )
    db.audit(user["username"], user["role"], "handover:create", f"handover#{hid}", body.summary[:80])
    return {"code": 0, "id": hid, "message": "交接单已提交"}


@router.get("/history")
def history(user: dict = Depends(security.require_login)):
    return {"code": 0, "items": db.rows("SELECT * FROM handovers ORDER BY id DESC LIMIT 20")}
