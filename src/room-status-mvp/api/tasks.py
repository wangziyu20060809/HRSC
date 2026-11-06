# -*- coding: utf-8 -*-
"""api/tasks.py — 任务队列（查房、清扫、维修）"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import db, security
from core.errors import ApiError

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

KIND_LABEL = {"inspection": "查房", "cleaning": "清扫", "maintenance": "维修"}
STATUS_LABEL = {"open": "待接单", "doing": "处理中", "done": "已完成", "cancelled": "已取消"}


@router.get("")
def list_tasks(
    status: str = Query("open,doing"),
    room_no: str = Query(""),
    user: dict = Depends(security.require_login),
):
    wanted = [s.strip() for s in status.split(",") if s.strip()]
    sql = "SELECT * FROM tasks"
    params: list = []
    cond = []
    if wanted:
        cond.append("status IN (%s)" % ",".join("?" for _ in wanted))
        params += wanted
    if room_no:
        cond.append("room_no=?")
        params.append(room_no)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at"

    out = []
    for t in db.rows(sql, params):
        room = db.row("SELECT * FROM rooms WHERE room_no=?", (t["room_no"],))
        t["kind_label"] = KIND_LABEL.get(t["kind"], t["kind"])
        t["status_label"] = STATUS_LABEL.get(t["status"], t["status"])
        t["room_state"] = room["state"] if room else ""
        t["room_state_label"] = room["state"] if room else ""
        if room:
            from domain.state_machine import STATES

            t["room_state_label"] = STATES.get(room["state"], {}).get("label", room["state"])
        out.append(t)
    return {"code": 0, "tasks": out, "count": len(out)}


class TaskAction(BaseModel):
    action: str  # claim / done / reopen


@router.post("/{task_id}/action")
def task_action(task_id: int, body: TaskAction, user: dict = Depends(security.require_login)):
    task = db.row("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not task:
        raise ApiError(40401, "任务不存在")
    if body.action == "claim":
        if task["status"] != "open":
            raise ApiError(40901, "该任务已被接单")
        db.exec_write(
            "UPDATE tasks SET status='doing', assignee=? WHERE id=?", (user["display"], task_id)
        )
        db.audit(user["username"], user["role"], "task:claim", task["room_no"], f"任务 {task_id}")
        return {"code": 0, "message": f"已接单：{task['room_no']} {KIND_LABEL.get(task['kind'], task['kind'])}"}
    if body.action == "done":
        db.exec_write(
            "UPDATE tasks SET status='done', closed_at=? WHERE id=?", (db.now_str(), task_id)
        )
        db.audit(user["username"], user["role"], "task:done", task["room_no"], f"任务 {task_id}")
        return {"code": 0, "message": "任务已标记完成"}
    if body.action == "reopen":
        db.exec_write("UPDATE tasks SET status='open', closed_at='' WHERE id=?", (task_id,))
        return {"code": 0, "message": "任务已重新打开"}
    raise ApiError(40001, f"未知任务动作：{body.action}")
