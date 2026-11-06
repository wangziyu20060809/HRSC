# -*- coding: utf-8 -*-
"""api/auth.py — 登录、登出、当前用户"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from core import db, security
from core.errors import ApiError
from core.security import ROLE_LABEL

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


HOME = {"admin": "/admin", "front": "/staff", "house": "/staff", "qa": "/staff"}


@router.post("/login")
def login(body: LoginBody):
    user = db.row("SELECT * FROM users WHERE username=?", (body.username.strip(),))
    if not user or not security.verify_password(body.password, user["password_hash"]):
        raise ApiError(40101, "账号或口令错误", 401)
    if not user["is_active"]:
        raise ApiError(40301, "账号已停用，请联系运营管理", 403)
    token = security.issue_token(user)
    resp = JSONResponse(
        {
            "code": 0,
            "message": "登录成功",
            "user": {
                "username": user["username"],
                "display": user["display"],
                "role": user["role"],
                "role_label": ROLE_LABEL.get(user["role"], user["role"]),
                "post": user["post"],
            },
            "redirect": HOME.get(user["role"], "/staff"),
        }
    )
    resp.set_cookie(
        security.COOKIE_NAME, token, max_age=config.JWT_TTL,
        httponly=True, samesite="lax",
    )
    db.audit(user["username"], user["role"], "login", "", "登录成功")
    return resp


@router.post("/logout")
def logout(request: Request):
    user = security.current_user(request)
    if user:
        db.audit(user["username"], user["role"], "logout", "", "退出登录")
    resp = JSONResponse({"code": 0, "message": "已退出"})
    resp.delete_cookie(security.COOKIE_NAME)
    return resp


@router.get("/me")
def me(user: dict = Depends(security.require_login)):
    return {"code": 0, "user": user}
