# -*- coding: utf-8 -*-
"""core/security.py — 登录口令、JWT 与岗位权限（RBAC）

岗位与职责边界来自访谈材料（客户简报六个角色）：
- front 前台接待员：现场操作与异常处理，能办入住/退房，不能改查房结论
- house 客房调度员：流程交接与资料责任，能发起清扫与报修
- qa    服务质量专员：风险、权限、留存与审计，能下查房结论
- admin 运营管理：可改口径、阈值、知识库与账号

「谁能改房态」是权限设计的核心：把结论权（qa）与执行权（front/house）分开，
避免前台为了赶入住自己把「已清扫」改成「可售」——这正是当前断点的成因。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

import jwt
from fastapi import Depends, Request

import config
from core import db
from core.errors import ApiError

COOKIE_NAME = "rs_token"

ROLE_LABEL = {
    "admin": "运营管理",
    "front": "前台",
    "house": "客房",
    "qa": "质检",
}

# 房态迁移 → 允许的岗位（state_machine 会读这张表做二次校验）
TRANSITION_ROLES: dict[str, set[str]] = {
    "start_cleaning": {"house", "admin"},
    "finish_cleaning": {"house", "admin"},
    "start_inspection": {"qa", "house", "admin"},
    "pass_inspection": {"qa", "admin"},
    "fail_inspection": {"qa", "admin"},
    "check_in": {"front", "admin"},
    "check_out": {"front", "admin"},
    "block": {"front", "house", "qa", "admin"},
    "unblock": {"house", "qa", "admin"},
    "rework": {"qa", "house", "admin"},
}


def hash_password(password: str, rounds: int = 120_000) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return "pbkdf2${}${}${}".format(
        rounds, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_b64, hash_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(rounds))
        return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)
    except (ValueError, TypeError):
        return False


def issue_token(user: dict) -> str:
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "display": user["display"],
        "role": user["role"],
        "post": user["post"],
        "iat": int(time.time()),
        "exp": int(time.time()) + config.JWT_TTL,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME) or ""
    if token.startswith("Bearer "):
        token = token[7:]
    if not token:
        return None
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    user = db.row("SELECT * FROM users WHERE id=?", (int(payload["sub"]),))
    if not user or not user["is_active"]:
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "display": user["display"],
        "role": user["role"],
        "post": user["post"],
        "role_label": ROLE_LABEL.get(user["role"], user["role"]),
    }


def require_login(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise ApiError(40102, "登录已过期，请重新登录", 401)
    return user


def require_roles(*roles: str):
    def _dep(request: Request) -> dict:
        user = require_login(request)
        if user["role"] not in roles:
            raise ApiError(40301, f"该操作仅限 {'/'.join(ROLE_LABEL.get(r, r) for r in roles)}", 403)
        return user

    return _dep


def require_admin(user: dict = Depends(require_roles("admin"))) -> dict:
    return user


def can(role: str, action: str) -> bool:
    return role in TRANSITION_ROLES.get(action, set())
