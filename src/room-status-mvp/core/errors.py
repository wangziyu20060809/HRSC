# -*- coding: utf-8 -*-
"""core/errors.py — 统一错误码与响应格式"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

# 错误码约定：4xxxx 客户端 / 5xxxx 服务端，后三位语义
CODES: dict[int, str] = {
    40001: "参数不合法",
    40002: "房间不存在",
    40003: "房态不允许该操作",
    40101: "账号或口令错误",
    40102: "登录已过期",
    40301: "当前岗位无此权限",
    40302: "该操作需人工确认",
    40401: "任务不存在",
    40901: "房间状态已变化，请刷新后重试",
    42901: "请求过于频繁",
    50001: "大模型调用失败，已降级为规则模式",
    50002: "知识库检索异常",
}


def status_for(code: int) -> int:
    """错误码前三位即 HTTP 状态（40001→400 / 40301→403 / 40901→409 / 50001→500）。

    这样调用方只需按错误码判语义，HTTP 状态码与码族始终一致；
    此前 40301 走默认值 400，导致「越权」与「参数错」在状态码上无法区分。
    """
    derived = code // 100
    return derived if 400 <= derived <= 599 else 400


class ApiError(Exception):
    def __init__(self, code: int, message: str = "", status: int | None = None, detail: str = ""):
        self.code = code
        self.message = message or CODES.get(code, "请求失败")
        self.status = status if status is not None else status_for(code)
        self.detail = detail or None
        super().__init__(self.message)


def install_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(
            {"code": exc.code, "message": exc.message, "detail": exc.detail},
            status_code=exc.status,
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):  # noqa: BLE001
        return JSONResponse(
            {"code": 50000, "message": "服务异常，请稍后重试", "detail": str(exc)[:200]},
            status_code=500,
        )
