# -*- coding: utf-8 -*-
"""
app.py — 酒店房态管理问答系统 · FastAPI 入口（三角色：guest / staff / admin）

页面（服务端渲染，SaaS 风格）：
  /login            统一登录页（员工/管理员）
  /guest            客人问答页（免登录）
  /staff            员工工作台（工单队列 + 制度问答）
  /staff/tickets/{id} 工单详情（回复/完结）
  /admin/*          管理后台（首页/知识库/提示词/页面内容/审计/账号）

接口：
  鉴权   /auth/login|logout|me
  客人   /guest/sessions|/guest/chat|/guest/sessions/{id}/escalate|messages
  员工   /chat（SSE 制度问答）+ /staff/tickets/* 工单操作
  管理   /admin/api/* 知识库/提示词/页面内容/审计/账号

统一错误：{"code":…,"message":"中文","detail":null}
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path


def _load_local_env() -> None:
    """零依赖加载项目根目录的 .env（已被 .gitignore 排除，不进版本库）。

    只补充「尚未设置」的变量，方便用系统环境变量覆盖本地文件。
    必须在 import llm_stream / kb 之前调用（它们在导入时读取环境变量）。
    """
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:   # 已存在则不覆盖（外部优先）
            os.environ[key] = value


_load_local_env()

from fastapi import Depends, FastAPI, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    JSONResponse, RedirectResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import auth
import chat_engine
import db
import kb
import llm_stream
import rag
import rules

app = FastAPI(title="酒店房态管理问答系统", version="0.3.0")
templates = Jinja2Templates(directory="templates")

_session_locks: dict[str, asyncio.Lock] = {}  # 同会话并发锁（防串话）


# =====================================================================
# 启动：建表 + 无账号时自动播种（演示口令见 seed.py）
# =====================================================================
@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    if not db.get_user_by_username("admin"):
        import seed  # 延迟导入，避免启动即写死依赖

        seed.main()


# =====================================================================
# 统一错误处理
# =====================================================================
class ApiError(Exception):
    def __init__(self, code: int, message: str, http_status: int = 400):
        self.code, self.message, self.http_status = code, message, http_status


@app.exception_handler(ApiError)
async def _api_error(_, exc: ApiError):
    return JSONResponse(status_code=exc.http_status,
                        content={"code": exc.code, "message": exc.message, "detail": None})


@app.exception_handler(auth.AuthError)
async def _auth_error(_, exc: auth.AuthError):
    code = 40301 if exc.http_status == 403 else 40101
    return JSONResponse(status_code=exc.http_status,
                        content={"code": code, "message": exc.message, "detail": None})


@app.exception_handler(RequestValidationError)
async def _validation_error(_, __):
    return JSONResponse(status_code=400,
                        content={"code": 40002, "message": "请求参数不合法", "detail": None})


def sse_stream(gen: AsyncGenerator[str, None]) -> StreamingResponse:
    """SSE 响应的统一包装（关缓冲，保证逐 token 到达）"""
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# =====================================================================
# 鉴权接口
# =====================================================================
class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(body: LoginBody, response=None):
    user = db.get_user_by_username(body.username.strip())
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise ApiError(40101, "用户名或密码错误", 401)
    if not user["is_active"]:
        raise ApiError(40301, "账号已被停用，请联系管理员", 403)
    token = auth.issue_token(user)
    redirect = "/admin" if user["role"] == "admin" else "/staff"
    # 手工构造响应并种 Cookie（HttpOnly，前端 JS 读不到，防 XSS 窃取）
    resp = JSONResponse({"code": 0, "message": "登录成功",
                         "role": user["role"], "redirect": redirect})
    resp.set_cookie(auth.COOKIE_NAME, token, max_age=auth.TOKEN_TTL_SECONDS,
                    httponly=True, samesite="lax")
    return resp


@app.post("/auth/logout")
def logout():
    resp = JSONResponse({"code": 0, "message": "已退出登录"})
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


@app.get("/auth/me")
def me(user: dict = Depends(auth.get_current_user)):
    return {"code": 0, "username": user["username"], "role": user["role"], "post": user["post"]}


# =====================================================================
# 页面：登录 / 客人端
# =====================================================================
@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/")
def index():
    return RedirectResponse("/guest")


@app.get("/guest")
def guest_page(request: Request):
    page = db.get_page_content("home")
    return templates.TemplateResponse(request, "guest.html", {"page": page})


# =====================================================================
# 客人端接口（免登录，按会话 ID 区分）
# =====================================================================
class ChatRequest(BaseModel):
    session_id: str
    question: str = Field(min_length=1, max_length=500)


class EscalateBody(BaseModel):
    note: str = Field(default="", max_length=200)


def _validate_chat(req: ChatRequest) -> tuple[dict, str]:
    """会话存在性 + 问题非空校验，返回 (会话, 问题)"""
    question = req.question.strip()
    if not question:
        raise ApiError(40002, "问题不能为空，且不能超过 500 字")
    session = db.get_session(req.session_id)
    if not session:
        raise ApiError(40001, "会话不存在，请先创建会话", 404)
    return session, question


def _chat_guard(session: dict, question: str) -> None:
    """同会话并发锁：进行中的回答未结束时拒绝新请求（42901）"""
    lock = _session_locks.setdefault(session["id"], asyncio.Lock())
    if lock.locked():
        raise ApiError(42901, "请求过于频繁，请等待上一个回答完成", 429)


@app.post("/guest/sessions")
def guest_sessions():
    s = db.create_session(channel="guest")
    return {"guest_session_id": s["session_id"]}


@app.post("/guest/chat")
async def guest_chat(req: ChatRequest):
    session, question = _validate_chat(req)
    if session["channel"] != "guest":
        raise ApiError(40301, "该会话不是客人会话", 403)
    _chat_guard(session, question)
    async with _session_locks[session["id"]]:
        return sse_stream(chat_engine.build_stream(session["id"], question, actor="guest"))


@app.post("/guest/sessions/{sid}/escalate")
def guest_escalate(sid: str, body: EscalateBody):
    session = db.get_session(sid)
    if not session or session["channel"] != "guest":
        raise ApiError(40001, "会话不存在", 404)
    if session["escalated"]:
        raise ApiError(40901, "该会话已提交人工，请耐心等待员工回复", 409)
    db.escalate_session(sid, body.note.strip())
    db.touch_session(sid)
    return {"code": 0, "message": "已转人工，值班员工将尽快回复您"}


@app.get("/guest/sessions/{sid}/messages")
def guest_messages(sid: str):
    """客人端轮询接口：转人工后拉取员工新回复"""
    session = db.get_session(sid)
    if not session or session["channel"] != "guest":
        raise ApiError(40001, "会话不存在", 404)
    return {"messages": db.get_all_messages(sid),
            "assignee_name": session.get("assignee_name") or "",
            "resolved": bool(session.get("resolved_at")),
            "escalated": bool(session.get("escalated"))}


class SayBody(BaseModel):
    """转人工后客人直发员工的消息体"""
    content: str = Field(min_length=1, max_length=500)


@app.post("/guest/sessions/{sid}/say")
def guest_say(sid: str, body: SayBody):
    """转人工后：客人与员工在同一工单线程内直接对话（AI 不再介入）。

    前提：会话已转人工且工单未完结；消息同样过违规规则并留痕。
    """
    session = db.get_session(sid)
    if not session or session["channel"] != "guest":
        raise ApiError(40001, "会话不存在", 404)
    if not session["escalated"]:
        raise ApiError(40901, "请先点击「转人工」，再与员工对话", 409)
    if session["resolved_at"]:
        raise ApiError(40901, "该工单已完结，如有新问题请重新发起会话", 409)
    content = body.content.strip()
    flagged, flag_reason = rules.check_violation(content)  # 客人直发消息同样留痕
    db.add_message(sid, "user", content, actor="guest",
                   flagged=flagged, flag_reason=flag_reason)
    db.touch_session(sid)
    return {"code": 0, "message": "已发送给员工"}


# =====================================================================
# 员工端：工单工作台 + 制度问答
# =====================================================================
@app.get("/staff")
def staff_home(request: Request, user: dict = Depends(auth.require_staff)):
    tickets = {s: db.list_tickets(s) for s in ("pending", "claimed", "resolved")}
    return templates.TemplateResponse(request, "staff.html",
                                      {"user": user, "tickets": tickets,
                                       "status": "pending"})


@app.get("/staff/tickets")
def staff_tickets(request: Request, status: str = "pending",
                  user: dict = Depends(auth.require_staff)):
    tickets = {s: db.list_tickets(s) for s in ("pending", "claimed", "resolved")}
    return templates.TemplateResponse(request, "staff.html",
                                      {"user": user, "tickets": tickets,
                                       "status": status if status in tickets else "pending"})


@app.get("/staff/tickets/{sid}")
def staff_ticket_detail(sid: str, request: Request, user: dict = Depends(auth.require_staff)):
    session = db.get_session(sid)
    if not session or session["channel"] != "guest":
        raise ApiError(40001, "工单不存在", 404)
    messages = db.get_all_messages(sid)
    return templates.TemplateResponse(request, "staff_ticket.html",
                                      {"user": user, "session": session, "messages": messages})


class ReplyBody(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


@app.post("/staff/tickets/{sid}/claim")
def staff_claim(sid: str, user: dict = Depends(auth.require_staff)):
    session = db.get_session(sid)
    if not session or session["channel"] != "guest" or not session["escalated"]:
        raise ApiError(40001, "工单不存在", 404)
    if session["assignee_id"] and session["assignee_id"] != user["sub"]:
        raise ApiError(40901, f"该工单已由 {session['assignee_name']} 认领", 409)
    db.claim_ticket(sid, user["sub"], user["username"])
    return {"code": 0, "message": "认领成功"}


@app.post("/staff/tickets/{sid}/reply")
def staff_reply(sid: str, body: ReplyBody, user: dict = Depends(auth.require_staff)):
    session = db.get_session(sid)
    if not session or not session["escalated"]:
        raise ApiError(40001, "工单不存在", 404)
    if session["resolved_at"]:
        raise ApiError(40901, "该工单已完结，无法回复", 409)
    content = body.content.strip()
    flagged, flag_reason = rules.check_violation(content)  # 员工回复同样过违规规则
    db.add_message(sid, "assistant", content, actor="staff",
                   flagged=flagged, flag_reason=flag_reason)
    db.touch_session(sid)
    return {"code": 0, "message": "回复已发送"}


@app.post("/staff/tickets/{sid}/resolve")
def staff_resolve(sid: str, user: dict = Depends(auth.require_staff)):
    session = db.get_session(sid)
    if not session or not session["escalated"]:
        raise ApiError(40001, "工单不存在", 404)
    db.resolve_ticket(sid)
    return {"code": 0, "message": "工单已完结"}


@app.get("/staff/chat")
def staff_chat_page(request: Request, user: dict = Depends(auth.require_staff)):
    return templates.TemplateResponse(request, "staff_chat.html", {"user": user})


@app.post("/sessions")
def staff_sessions(user: dict = Depends(auth.require_staff)):
    s = db.create_session(user_id=user["sub"], channel="staff")
    return {"session_id": s["session_id"]}


@app.get("/sessions")
def staff_session_list(user: dict = Depends(auth.require_staff)):
    return {"sessions": db.list_sessions(user["sub"])}


@app.get("/sessions/{sid}/messages")
def staff_session_messages(sid: str, user: dict = Depends(auth.require_staff)):
    session = db.get_session(sid)
    if not session:
        raise ApiError(40001, "会话不存在", 404)
    if session["user_id"] and session["user_id"] != user["sub"]:
        raise ApiError(40301, "无权访问该会话", 403)
    return {"messages": db.get_all_messages(sid)}


@app.post("/chat")
async def staff_chat(req: ChatRequest, user: dict = Depends(auth.require_staff)):
    session, question = _validate_chat(req)
    _chat_guard(session, question)
    async with _session_locks[session["id"]]:
        return sse_stream(chat_engine.build_stream(session["id"], question, actor="staff"))


# =====================================================================
# 管理后台页面
# =====================================================================
def _admin_ctx(request: Request, user: dict, active: str):
    """后台页面公共上下文：侧边导航高亮 + 统计卡"""
    stats = {
        "docs": len(db.list_documents()),
        "sessions": len(db.list_tickets("pending")) + len(db.list_tickets("claimed")),
        "messages": len(db.audit_messages(limit=500)),
        "flags": len(db.audit_messages(flagged="1", limit=500)),
    }
    return {"request": request, "user": user, "active": active, "stats": stats}


@app.get("/admin")
def admin_home(request: Request, user: dict = Depends(auth.require_admin)):
    return templates.TemplateResponse(request, "admin/index.html", _admin_ctx(request, user, "home"))


@app.get("/admin/kb")
def admin_kb(request: Request, user: dict = Depends(auth.require_admin)):
    ctx = _admin_ctx(request, user, "kb")
    ctx["docs"] = db.list_documents()
    return templates.TemplateResponse(request, "admin/kb.html", ctx)


@app.get("/admin/prompts")
def admin_prompts(request: Request, user: dict = Depends(auth.require_admin)):
    ctx = _admin_ctx(request, user, "prompts")
    ctx["prompt"] = db.get_prompt()
    ctx["default_prompt"] = db.DEFAULT_PROMPT
    return templates.TemplateResponse(request, "admin/prompts.html", ctx)


@app.get("/admin/pages")
def admin_pages(request: Request, user: dict = Depends(auth.require_admin)):
    ctx = _admin_ctx(request, user, "pages")
    ctx["page"] = db.get_page_content("home")
    return templates.TemplateResponse(request, "admin/pages.html", ctx)


@app.get("/admin/audit")
def admin_audit(request: Request, user: dict = Depends(auth.require_admin)):
    ctx = _admin_ctx(request, user, "audit")
    return templates.TemplateResponse(request, "admin/audit.html", ctx)


@app.get("/admin/users")
def admin_users(request: Request, user: dict = Depends(auth.require_admin)):
    ctx = _admin_ctx(request, user, "users")
    ctx["users"] = db.list_users()
    return templates.TemplateResponse(request, "admin/users.html", ctx)


# =====================================================================
# 管理后台接口
# =====================================================================
class KbUploadMeta(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=32)


@app.get("/admin/api/kb/docs")
def api_kb_list(user: dict = Depends(auth.require_admin)):
    return {"documents": db.list_documents()}


@app.post("/admin/api/kb/docs")
async def api_kb_upload(file: UploadFile, title: str = Form(...), version: str = Form(...),
                        user: dict = Depends(auth.require_admin)):
    content = await file.read()
    try:
        text, file_hash = kb.parse_upload(file.filename or "", content)
        doc_id, chunk_count = kb.ingest_document(title.strip(), version.strip(), text,
                                                 uploaded_by=user["username"])
    except kb.ParseError as e:
        raise ApiError(40010, str(e))
    db.add_document(title.strip(), version.strip(), file_hash, chunk_count,
                    uploaded_by=user["username"])
    rag.reload_retriever()
    return {"code": 0, "message": f"入库成功，共 {chunk_count} 个分块", "doc_id": doc_id}


@app.delete("/admin/api/kb/docs/{doc_id}")
def api_kb_delete(doc_id: str, user: dict = Depends(auth.require_admin)):
    if not kb.delete_document(doc_id):
        raise ApiError(40001, "文档不存在或已删除", 404)
    db.delete_document(doc_id)
    rag.reload_retriever()
    return {"code": 0, "message": "已删除并重建索引"}


@app.post("/admin/api/kb/reindex")
def api_kb_reindex(user: dict = Depends(auth.require_admin)):
    n = kb.reindex()
    rag.reload_retriever()
    return {"code": 0, "message": f"索引已重建，共 {n} 个分块"}


@app.get("/admin/api/prompts/default")
def api_prompt_get(user: dict = Depends(auth.require_admin)):
    return {"key": "default", "content": db.get_prompt()}


class PromptBody(BaseModel):
    content: str = Field(min_length=10, max_length=2000)


@app.put("/admin/api/prompts/default")
def api_prompt_put(body: PromptBody, user: dict = Depends(auth.require_admin)):
    db.set_prompt("default", body.content.strip(), updated_by=user["username"])
    return {"code": 0, "message": "已保存，对下一条提问立即生效"}


@app.post("/admin/api/prompts/default/reset")
def api_prompt_reset(user: dict = Depends(auth.require_admin)):
    db.set_prompt("default", db.DEFAULT_PROMPT, updated_by=user["username"])
    return {"code": 0, "message": "已恢复默认模板"}


class HomePageBody(BaseModel):
    welcome: str = Field(min_length=1, max_length=500)
    faq: list = Field(default_factory=list)


@app.get("/admin/api/pages/home")
def api_page_get(user: dict = Depends(auth.require_admin)):
    return {"key": "home", "content": db.get_page_content("home")}


@app.put("/admin/api/pages/home")
def api_page_put(body: HomePageBody, user: dict = Depends(auth.require_admin)):
    db.set_page_content("home", {"welcome": body.welcome.strip(), "faq": body.faq},
                        updated_by=user["username"])
    return {"code": 0, "message": "页面内容已保存，客人端刷新即生效"}


@app.get("/admin/api/audit/messages")
def api_audit(channel: str = "", start: str = "", end: str = "",
              flagged: str = "", user: dict = Depends(auth.require_admin)):
    return {"messages": db.audit_messages(channel=channel, start=start, end=end, flagged=flagged)}


class FlagBody(BaseModel):
    flagged: bool
    reason: str = ""


@app.post("/admin/api/audit/messages/{mid}/flag")
def api_audit_flag(mid: str, body: FlagBody, user: dict = Depends(auth.require_admin)):
    db.set_flag(mid, body.flagged, body.reason.strip())
    return {"code": 0, "message": "标记已更新"}


class UserCreateBody(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = "staff"
    post: str = ""
    password: str = Field(min_length=6, max_length=64)


@app.post("/admin/api/users")
def api_user_create(body: UserCreateBody, user: dict = Depends(auth.require_admin)):
    if body.role not in ("staff", "admin"):
        raise ApiError(40002, "角色只能是 staff 或 admin")
    if db.get_user_by_username(body.username.strip()):
        raise ApiError(40901, "用户名已存在", 409)
    db.create_user(body.username.strip(), body.display_name.strip(), body.role,
                   body.post.strip(), auth.hash_password(body.password))
    return {"code": 0, "message": "账号已创建"}


class PasswordBody(BaseModel):
    password: str = Field(min_length=6, max_length=64)


@app.post("/admin/api/users/{uid}/reset-password")
def api_user_reset(uid: str, body: PasswordBody, user: dict = Depends(auth.require_admin)):
    target = db.get_user(uid)
    if not target:
        raise ApiError(40001, "账号不存在", 404)
    db.update_user_password(uid, auth.hash_password(body.password))
    return {"code": 0, "message": "密码已重置"}


class ToggleBody(BaseModel):
    is_active: bool


@app.post("/admin/api/users/{uid}/toggle")
def api_user_toggle(uid: str, body: ToggleBody, user: dict = Depends(auth.require_admin)):
    if uid == user["sub"]:
        raise ApiError(40901, "不能停用自己的账号")
    db.toggle_user(uid, body.is_active)
    return {"code": 0, "message": "状态已更新"}


# =====================================================================
# 公共：健康检查 + 静态资源
# =====================================================================
@app.get("/healthz")
def healthz():
    return {"status": "ok", "llm_ready": llm_stream.llm_ready(),
            "index_chunks": _index_chunk_count()}


def _index_chunk_count() -> int:
    try:
        return len(kb.all_chunks_flat(kb._load_docs()))
    except Exception:
        return 0


app.mount("/static", StaticFiles(directory="static"), name="static")
