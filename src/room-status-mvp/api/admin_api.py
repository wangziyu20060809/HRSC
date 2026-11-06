# -*- coding: utf-8 -*-
"""api/admin_api.py — 运营管理：审计、助手配置、账号、助手运行统计"""

from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import db, security
from core.errors import ApiError
from core.security import ROLE_LABEL, hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])

EDITABLE_SETTINGS = {
    "sla_clean_wait_min": "已清扫 → 开始查房（分钟）",
    "sla_inspect_min": "查房中 → 出结论（分钟）",
    "sla_dirty_min": "待清扫 → 开始清扫（分钟）",
    "agent_enabled": "启用助手（1/0）",
    "agent_allow_write_tools": "允许助手生成改房态提案（1/0）",
    "agent_system_prompt": "助手系统提示词",
}


@router.get("/audit")
def audit(
    action: str = Query(""),
    actor: str = Query(""),
    limit: int = Query(100, le=500),
    user: dict = Depends(security.require_roles("admin")),
):
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params: list = []
    if action:
        sql += " AND action LIKE ?"
        params.append(f"%{action}%")
    if actor:
        sql += " AND (actor LIKE ? OR target LIKE ?)"
        params += [f"%{actor}%", f"%{actor}%"]
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = db.rows(sql, params)
    for r in rows:
        r["role_label"] = ROLE_LABEL.get(r["role"], r["role"])
    return {"code": 0, "items": rows}


@router.get("/settings")
def get_settings(user: dict = Depends(security.require_roles("admin"))):
    from agent.prompts import DEFAULT_SYSTEM_PROMPT

    values = {k: db.get_setting(k, db.DEFAULT_SETTINGS.get(k, "")) for k in EDITABLE_SETTINGS}
    return {
        "code": 0,
        "settings": values,
        "editable": EDITABLE_SETTINGS,
        "default_prompt": DEFAULT_SYSTEM_PROMPT,
    }


class SettingsBody(BaseModel):
    settings: dict[str, str]


@router.put("/settings")
def put_settings(body: SettingsBody, user: dict = Depends(security.require_roles("admin"))):
    changed = []
    for k, v in body.settings.items():
        if k not in EDITABLE_SETTINGS:
            continue
        if k in ("sla_clean_wait_min", "sla_inspect_min", "sla_dirty_min"):
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise ApiError(40001, f"{EDITABLE_SETTINGS[k]} 必须是整数")
            if iv < 1 or iv > 720:
                raise ApiError(40001, f"{EDITABLE_SETTINGS[k]} 应在 1-720 之间")
            v = str(iv)
        db.set_setting(k, v)
        changed.append(k)
    db.audit(user["username"], user["role"], "settings:update", "", "、".join(changed))
    return {"code": 0, "message": f"已保存 {len(changed)} 项设置（立即生效）", "changed": changed}


@router.get("/users")
def users(user: dict = Depends(security.require_roles("admin"))):
    rows = db.rows(
        "SELECT id, username, display, role, post, is_active, created_at FROM users ORDER BY id"
    )
    for r in rows:
        r["role_label"] = ROLE_LABEL.get(r["role"], r["role"])
    return {"code": 0, "users": rows}


class UserBody(BaseModel):
    username: str
    display: str
    role: str
    post: str = ""
    password: str


@router.post("/users")
def create_user(body: UserBody, user: dict = Depends(security.require_roles("admin"))):
    if body.role not in ROLE_LABEL:
        raise ApiError(40001, "岗位不合法")
    if db.row("SELECT id FROM users WHERE username=?", (body.username.strip(),)):
        raise ApiError(40001, "账号已存在")
    if len(body.password) < 6:
        raise ApiError(40001, "口令至少 6 位")
    db.exec_write(
        "INSERT INTO users(username, display, role, post, password_hash, created_at) VALUES(?,?,?,?,?,?)",
        (body.username.strip(), body.display.strip(), body.role, body.post.strip(),
         hash_password(body.password), db.now_str()),
    )
    db.audit(user["username"], user["role"], "user:create", body.username, f"岗位 {body.role}")
    return {"code": 0, "message": f"已创建 {body.display}（{ROLE_LABEL[body.role]}）"}


@router.post("/users/{uid}/toggle")
def toggle(uid: int, user: dict = Depends(security.require_roles("admin"))):
    u = db.row("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(40001, "账号不存在")
    if u["username"] == user["username"]:
        raise ApiError(40003, "不能停用自己的账号")
    db.exec_write("UPDATE users SET is_active=? WHERE id=?", (0 if u["is_active"] else 1, uid))
    db.audit(user["username"], user["role"], "user:toggle", u["username"], "停用" if u["is_active"] else "启用")
    return {"code": 0, "message": f"已{'停用' if u['is_active'] else '启用'} {u['display']}"}


class ResetBody(BaseModel):
    password: str


@router.post("/users/{uid}/reset-password")
def reset_pwd(uid: int, body: ResetBody, user: dict = Depends(security.require_roles("admin"))):
    u = db.row("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(40001, "账号不存在")
    if len(body.password) < 6:
        raise ApiError(40001, "口令至少 6 位")
    db.exec_write("UPDATE users SET password_hash=? WHERE id=?", (hash_password(body.password), uid))
    db.audit(user["username"], user["role"], "user:reset_password", u["username"], "")
    return {"code": 0, "message": f"已重置 {u['display']} 的口令"}


@router.get("/agent-stats")
def agent_stats(user: dict = Depends(security.require_roles("admin"))):
    since = (db.parse(db.now_str()) - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
    msgs = db.rows(
        "SELECT trace, latency_ms FROM agent_messages WHERE role='assistant' AND created_at>=?", (since,)
    )
    tool_counter: Counter[str] = Counter()
    for m in msgs:
        try:
            for t in json.loads(m["trace"] or "[]"):
                tool_counter[t.get("tool", "?")] += 1
        except json.JSONDecodeError:
            pass
    lat = [m["latency_ms"] for m in msgs if m["latency_ms"]]
    confirmed = db.scalar("SELECT COUNT(*) FROM agent_actions WHERE status='confirmed'")
    rejected = db.scalar("SELECT COUNT(*) FROM agent_actions WHERE status='rejected'")
    return {
        "code": 0,
        "sessions_7d": db.scalar("SELECT COUNT(*) FROM agent_sessions WHERE created_at>=?", (since,)),
        "messages_7d": len(msgs),
        "avg_latency_ms": round(sum(lat) / len(lat)) if lat else 0,
        "avg_steps": round(sum(len(json.loads(m["trace"] or "[]")) for m in msgs) / len(msgs), 1) if msgs else 0,
        "tools": tool_counter.most_common(12),
        "actions": {
            "pending": db.scalar("SELECT COUNT(*) FROM agent_actions WHERE status='pending'"),
            "confirmed": confirmed,
            "rejected": rejected,
            "failed": db.scalar("SELECT COUNT(*) FROM agent_actions WHERE status='failed'"),
            "adoption": round(confirmed / (confirmed + rejected) * 100) if (confirmed + rejected) else 0,
        },
    }
