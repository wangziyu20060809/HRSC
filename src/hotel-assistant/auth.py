# -*- coding: utf-8 -*-
"""
auth.py — 登录鉴权与三角色 RBAC

角色：guest（免登录，不走本模块）/ staff（员工）/ admin（管理员）
机制：JWT（HS256）放 HttpOnly Cookie，8 小时过期；接口级权限用 FastAPI 依赖校验。
口令哈希：PBKDF2-HMAC-SHA256 + 随机盐（标准库实现，无额外依赖；
生产环境建议换 Argon2，本层接口不变）。
"""

import base64
import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------
# 配置（生产环境必须通过环境变量覆盖 JWT_SECRET！）
# ---------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "hotel-assistant-dev-secret-change-me")
JWT_ALG = "HS256"
TOKEN_TTL_SECONDS = 8 * 3600  # 8 小时
COOKIE_NAME = "hotel_token"

# ---------------------------------------------------------------------
# 口令哈希（PBKDF2：sha256, 12 万轮，格式: pbkdf2$轮数$盐$哈希）
# ---------------------------------------------------------------------
_PBKDF2_ROUNDS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_b64, hash_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(rounds)
        )
        return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------
# JWT 签发与校验
# ---------------------------------------------------------------------
def issue_token(user: dict) -> str:
    """签发 JWT：载荷只放必要字段（用户ID、角色、岗位）"""
    payload = {
        "sub": user["id"],
        "username": user["username"],
        "role": user["role"],
        "post": user.get("post", ""),
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict | None:
    """校验并解析 JWT；过期/签名错误返回 None"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------
# FastAPI 依赖：接口级权限校验
# ---------------------------------------------------------------------
class AuthError(Exception):
    def __init__(self, message: str, http_status: int = 401):
        self.message = message
        self.http_status = http_status


def get_current_user(request: Request) -> dict:
    """依赖：要求已登录（员工或管理员）；未登录抛 40101"""
    token = request.cookies.get(COOKIE_NAME, "")
    payload = decode_token(token) if token else None
    if not payload:
        raise AuthError("登录已失效，请重新登录", 401)
    return payload


def require_staff(user: dict = Depends(get_current_user)) -> dict:
    """依赖：员工及以上（staff / admin 都可用员工工作台）"""
    if user["role"] not in ("staff", "admin"):
        raise AuthError("无权访问员工工作台", 403)
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """依赖：仅管理员"""
    if user["role"] != "admin":
        raise AuthError("无权访问管理后台，需要管理员权限", 403)
    return user
