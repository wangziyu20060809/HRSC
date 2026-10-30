# -*- coding: utf-8 -*-
"""
app.py — 酒店房态管理 FastAPI 入口（员工问答入口，阶段 2 接口实现）

接口：
  GET  /                              单页聊天界面
  GET  /healthz                       健康检查
  POST /sessions                      新建会话
  GET  /sessions                      会话列表
  GET  /sessions/{sid}/messages       拉取完整历史（含引用）
  POST /chat                          提问 → SSE 流式回答

错误约定：所有错误统一 {"code": 错误码, "message": 中文信息, "detail": 可选}
SSE 事件顺序：status(检索中) → citations → token… → done；中途异常推 error 事件。
"""

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import llm_stream
import rag

# ----------------------------------------------------------------------
# 应用初始化
# ----------------------------------------------------------------------
app = FastAPI(title="酒店房态管理 · 员工问答入口", version="0.2.0")

# 同会话并发锁：防止同一 session 同时跑两个回答导致串话（42901）
_session_locks: dict[str, asyncio.Lock] = {}


@app.on_event("startup")
def _startup() -> None:
    db.init_db()  # 建表（幂等）


# ----------------------------------------------------------------------
# 统一错误模型
# ----------------------------------------------------------------------
class ApiError(Exception):
    """业务错误：code 用于前端分支处理，message 为中文提示"""

    def __init__(self, code: int, message: str, http_status: int = 400, detail=None):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail


@app.exception_handler(ApiError)
async def api_error_handler(_, exc: ApiError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "detail": exc.detail},
    )


def sse(event: str, data) -> str:
    """SSE 帧格式化：event + data 两行，JSON 不转义中文"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ----------------------------------------------------------------------
# 请求模型
# ----------------------------------------------------------------------
class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    question: str = Field(..., min_length=1, max_length=500, description="问题，1-500 字")


# ----------------------------------------------------------------------
# 会话接口
# ----------------------------------------------------------------------
@app.post("/sessions")
def create_session():
    return db.create_session()


@app.get("/sessions")
def list_sessions():
    return {"sessions": db.list_sessions()}


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    if not db.get_session(session_id):
        raise ApiError(40001, "会话不存在，请先创建会话", http_status=404)
    return {"messages": db.get_all_messages(session_id)}


# ----------------------------------------------------------------------
# 健康检查
# ----------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "llm_ready": llm_stream.llm_ready(),  # 前端可据此提示"当前为摘要模式"
    }


# ----------------------------------------------------------------------
# 核心：POST /chat —— SSE 流式问答
# ----------------------------------------------------------------------
def _build_event_stream(session_id: str, question: str) -> AsyncGenerator[str, None]:
    """
    流式生成器：检索 → 引用 → 逐 token → 落库 → done。
    LLM 任何失败自动降级为条款摘要（错误码 50001 以 status 事件告知前端）。
    """

    async def gen():
        # —— 1. 检索阶段：先推状态，前端显示"正在检索制度…" ——
        yield sse("status", {"stage": "retrieving", "text": "正在检索制度…"})
        try:
            hits = rag.search(question, top_k=3)
        except rag.IndexNotReadyError:
            yield sse("error", {"code": 40404, "message": "制度库尚未初始化，请联系管理员先执行入库"})
            return
        except Exception:
            yield sse("error", {"code": 50002, "message": "检索服务异常，请稍后重试"})
            return

        if not hits:
            yield sse("error", {"code": 50002, "message": "未检索到相关条款，请换个问法试试"})
            return

        # —— 2. 引用事件：先把条款来源推给前端（回答底部展示） ——
        citations = rag.to_citations(
            hits, source_title="客房管理制度.md", version="v1.2"
        )
        yield sse("citations", citations)

        # —— 3. 组装上下文：最近 6 轮历史 + 检索条款 + 当前问题 ——
        history = db.get_recent_messages(session_id, limit=12)
        messages = llm_stream.build_messages(question, hits, history)

        # —— 4. 用户消息立即入库（首轮用问题自动命名会话） ——
        db.add_message(session_id, "user", question)
        if len(history) == 0:
            db.touch_session(session_id, title=question)

        # —— 5. 生成阶段：真实 LLM 流式，失败走降级摘要 ——
        answer_parts: list[str] = []
        degraded = False
        try:
            for delta in llm_stream.stream_chat(messages):
                answer_parts.append(delta)
                yield sse("token", {"text": delta})
        except Exception:
            # 降级：完整摘要切片后模拟流式，前端体验一致
            degraded = True
            yield sse(
                "status",
                {"stage": "degraded", "code": 50001, "text": "大模型服务暂不可用，已为你降级为条款摘要"},
            )
            summary = llm_stream.fallback_summary(hits)
            for piece in llm_stream.chunk_text(summary, size=8):
                answer_parts.append(piece)
                yield sse("token", {"text": piece})

        # —— 6. 完整回答入库（含引用，供历史恢复） ——
        answer = "".join(answer_parts)
        message_id = db.add_message(
            session_id, "assistant", answer, citations=citations,
            tool_calls=[{"tool": "hybrid_search", "top_k": 3, "degraded": degraded}],
        )
        db.touch_session(session_id)
        yield sse("done", {"message_id": message_id, "degraded": degraded})

    return gen()


@app.post("/chat")
async def chat(req: ChatRequest):
    # —— 前置校验：错误走普通 JSON（非 SSE），与接口设计一致 ——
    question = req.question.strip()
    if not question:
        raise ApiError(40002, "问题不能为空，且不能超过 500 字")
    if not db.get_session(req.session_id):
        raise ApiError(40001, "会话不存在，请先创建会话", http_status=404)

    # —— 并发控制：同会话只允许一个进行中的回答 ——
    lock = _session_locks.setdefault(req.session_id, asyncio.Lock())
    if lock.locked():
        raise ApiError(42901, "请求过于频繁，请等待上一个回答完成", http_status=429)

    async with lock:
        return StreamingResponse(
            _build_event_stream(req.session_id, question),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证逐 token 到达
            },
        )


# ----------------------------------------------------------------------
# 前端静态页（最后挂载，避免覆盖 API 路由）
# ----------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
