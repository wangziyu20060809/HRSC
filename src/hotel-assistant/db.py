# -*- coding: utf-8 -*-
"""
db.py — SQLite 持久化层（三角色版本：guest/staff/admin）

表结构：
  sessions     会话（channel: guest|staff；escalated/assignee/resolved 支撑工单流）
  messages     消息（actor: ai|staff|guest；flagged/flag_reason 支撑审计）
  users        员工/管理员账号
  prompts      提示词模板（问答链路实时读取，保存即生效）
  pages_content 页面内容（客人端欢迎语 + FAQ，管理员可编辑）
  policy_documents 制度文档元数据（分块向量仍在 rag_index/ 本地文件）

设计说明：
  · 标准库 sqlite3，WAL 模式；MVP 数据量小，同步调用足够；
  · 老库兼容：新增列用 ensure_column 幂等补列，不重建库；
  · 切换 PostgreSQL 时仅需替换本文件，业务层不变。
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "hotel.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _ensure_column(c: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    """幂等补列：列已存在则跳过（用于老库升级，无需删库重建）"""
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]
    if name not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    """建表 + 老库补列（幂等）：服务启动时调用一次"""
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id              TEXT PRIMARY KEY,
                user_id         TEXT NOT NULL DEFAULT '',
                title           TEXT NOT NULL DEFAULT '新会话',
                status          TEXT NOT NULL DEFAULT 'active',
                channel         TEXT NOT NULL DEFAULT 'staff',
                escalated       INTEGER NOT NULL DEFAULT 0,
                escalated_note  TEXT,
                assignee_id     TEXT,
                assignee_name   TEXT,
                resolved_at     TEXT,
                created_at      TEXT NOT NULL,
                last_active_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                actor       TEXT NOT NULL DEFAULT 'guest',
                content     TEXT NOT NULL,
                citations   TEXT,
                tool_calls  TEXT,
                redacted    INTEGER NOT NULL DEFAULT 0,
                flagged     INTEGER NOT NULL DEFAULT 0,
                flag_reason TEXT,
                created_at  TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                display_name  TEXT NOT NULL,
                role          TEXT NOT NULL,          -- staff / admin
                post          TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prompts (
                key         TEXT PRIMARY KEY,
                content     TEXT NOT NULL,
                updated_by  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pages_content (
                key         TEXT PRIMARY KEY,
                content     TEXT NOT NULL,            -- JSON 字符串
                updated_by  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS policy_documents (
                id           TEXT PRIMARY KEY,
                title        TEXT NOT NULL,
                version      TEXT NOT NULL,
                file_hash    TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'active',
                chunk_count  INTEGER NOT NULL DEFAULT 0,
                uploaded_by  TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_time
                ON messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_channel
                ON sessions(channel, escalated);
            """
        )
        # —— 老库（三角色版本之前的结构）幂等补列 ——
        _ensure_column(c, "sessions", "channel", "channel TEXT NOT NULL DEFAULT 'staff'")
        _ensure_column(c, "sessions", "escalated", "escalated INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "sessions", "escalated_note", "escalated_note TEXT")
        _ensure_column(c, "sessions", "assignee_id", "assignee_id TEXT")
        _ensure_column(c, "sessions", "assignee_name", "assignee_name TEXT")
        _ensure_column(c, "sessions", "resolved_at", "resolved_at TEXT")
        _ensure_column(c, "messages", "actor", "actor TEXT NOT NULL DEFAULT 'guest'")
        _ensure_column(c, "messages", "flagged", "flagged INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "messages", "flag_reason", "flag_reason TEXT")


# =====================================================================
# 会话
# =====================================================================
def create_session(user_id: str = "", channel: str = "staff", title: str = "新会话") -> dict:
    sid = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions(id,user_id,title,status,channel,created_at,last_active_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (sid, user_id, title, "active", channel, now, now),
        )
    return {"session_id": sid, "title": title, "created_at": now}


def get_session(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions(user_id: str = "staff-demo") -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,title,status,channel,created_at,last_active_at FROM sessions "
            "WHERE user_id=? AND status='active' ORDER BY last_active_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def touch_session(session_id: str, title: str | None = None) -> None:
    now = _now()
    with _conn() as c:
        if title:
            c.execute("UPDATE sessions SET last_active_at=?, title=? WHERE id=?",
                      (now, title[:20], session_id))
        else:
            c.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (now, session_id))


# =====================================================================
# 消息
# =====================================================================
def add_message(
    session_id: str,
    role: str,
    content: str,
    actor: str = "guest",
    citations: list | None = None,
    tool_calls: list | None = None,
    redacted: bool = False,
    flagged: bool = False,
    flag_reason: str = "",
) -> str:
    mid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO messages(id,session_id,role,actor,content,citations,tool_calls,"
            "redacted,flagged,flag_reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (mid, session_id, role, actor, content,
             json.dumps(citations, ensure_ascii=False) if citations else None,
             json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
             1 if redacted else 0, 1 if flagged else 0, flag_reason, _now()),
        )
    return mid


def get_recent_messages(session_id: str, limit: int = 12) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role,actor,content,citations,created_at FROM messages "
            "WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_all_messages(session_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,role,actor,content,citations,flagged,flag_reason,created_at "
            "FROM messages WHERE session_id=? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["citations"] = json.loads(item["citations"]) if item["citations"] else []
        result.append(item)
    return result


# =====================================================================
# 用户（员工 / 管理员）
# =====================================================================
def create_user(username: str, display_name: str, role: str, post: str, password_hash: str) -> str:
    uid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO users(id,username,display_name,role,post,password_hash,is_active,created_at)"
            " VALUES(?,?,?,?,?,?,1,?)",
            (uid, username, display_name, role, post, password_hash, _now()),
        )
    return uid


def get_user_by_username(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,username,display_name,role,post,is_active,created_at FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def update_user_password(user_id: str, password_hash: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))


def toggle_user(user_id: str, is_active: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET is_active=? WHERE id=?", (1 if is_active else 0, user_id))


# =====================================================================
# 提示词模板（保存即生效：/chat 每次请求实时读取）
# =====================================================================
DEFAULT_PROMPT = (
    "你是酒店房态管理助手，只根据提供的制度条文回答；不确定时明确说\"制度中未找到\"；"
    "回答末尾附引用来源（文件名·版本·条款号）；不得编造房态处理标准与对客承诺口径。"
)


def get_prompt(key: str = "default") -> str:
    """读取提示词模板；未配置过则返回默认模板（与代码内默认值一致）"""
    with _conn() as c:
        row = c.execute("SELECT content FROM prompts WHERE key=?", (key,)).fetchone()
    return row["content"] if row else DEFAULT_PROMPT


def set_prompt(key: str, content: str, updated_by: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO prompts(key,content,updated_by,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET content=excluded.content,"
            " updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (key, content, updated_by, _now()),
        )


# =====================================================================
# 页面内容（客人端欢迎语 + FAQ）
# =====================================================================
DEFAULT_HOME_PAGE = {
    "welcome": "您好，这里是山海旅居智能服务。可咨询房态规则、入住流程等问题；若回答未解决，可点击「转人工」由值班员工为您服务。",
    "faq": [
        {"q": "退房后多久可以再次入住？", "a": "客房完成清扫并查房合格后即恢复可售，通常在退房后 1 小时内。"},
        {"q": "房间设施故障怎么办？", "a": "我们将立即安排维修；维修期间该房间将封锁，不会分配给其他客人。"},
    ],
}


def get_page_content(key: str = "home") -> dict:
    with _conn() as c:
        row = c.execute("SELECT content FROM pages_content WHERE key=?", (key,)).fetchone()
    return json.loads(row["content"]) if row else DEFAULT_HOME_PAGE


def set_page_content(key: str, content: dict, updated_by: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO pages_content(key,content,updated_by,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET content=excluded.content,"
            " updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (key, json.dumps(content, ensure_ascii=False), updated_by, _now()),
        )


# =====================================================================
# 制度文档元数据
# =====================================================================
def add_document(title: str, version: str, file_hash: str, chunk_count: int, uploaded_by: str = "") -> str:
    doc_id = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO policy_documents(id,title,version,file_hash,status,chunk_count,uploaded_by,created_at)"
            " VALUES(?,?,?,?,'active',?,?,?)",
            (doc_id, title, version, file_hash, chunk_count, uploaded_by, _now()),
        )
    return doc_id


def list_documents() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM policy_documents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_document(doc_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM policy_documents WHERE id=?", (doc_id,)).fetchone()
    return dict(row) if row else None


def delete_document(doc_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM policy_documents WHERE id=?", (doc_id,))


# =====================================================================
# 工单（客人转人工 → 员工处理）
# =====================================================================
def escalate_session(session_id: str, note: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET escalated=1, escalated_note=?, last_active_at=? WHERE id=?",
            (note, _now(), session_id),
        )


def list_tickets(status: str = "pending") -> list[dict]:
    """
    工单三态：
      pending  = 已转人工、未认领
      claimed  = 已认领、处理中
      resolved = 已完结
    """
    where, params = {
        "pending": ("channel='guest' AND escalated=1 AND assignee_id IS NULL AND resolved_at IS NULL", ()),
        "claimed": ("channel='guest' AND escalated=1 AND assignee_id IS NOT NULL AND resolved_at IS NULL", ()),
        "resolved": ("channel='guest' AND escalated=1 AND resolved_at IS NOT NULL", ()),
    }[status]
    with _conn() as c:
        rows = c.execute(
            f"SELECT id,title,escalated_note,assignee_name,resolved_at,created_at,last_active_at"
            f" FROM sessions WHERE {where} ORDER BY last_active_at DESC LIMIT 100", params,
        ).fetchall()
    return [dict(r) for r in rows]


def claim_ticket(session_id: str, staff_id: str, staff_name: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET assignee_id=?, assignee_name=?, last_active_at=? WHERE id=?",
            (staff_id, staff_name, _now(), session_id),
        )


def resolve_ticket(session_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET resolved_at=?, last_active_at=? WHERE id=?",
                  (_now(), _now(), session_id))


# =====================================================================
# 审计
# =====================================================================
def audit_messages(channel: str = "", start: str = "", end: str = "",
                   flagged: str = "", limit: int = 200) -> list[dict]:
    """按渠道/时间/标记筛选消息（审计页用）"""
    cond, params = ["1=1"], []
    if channel:
        cond.append("s.channel=?")
        params.append(channel)
    if start:
        cond.append("m.created_at>=?")
        params.append(start)
    if end:
        cond.append("m.created_at<=?")
        params.append(end + " 23:59:59" if len(end) == 10 else end)
    if flagged == "1":
        cond.append("m.flagged=1")
    elif flagged == "0":
        cond.append("m.flagged=0")
    sql = (
        "SELECT m.id, m.session_id, m.role, m.actor, m.content, m.flagged, m.flag_reason,"
        " m.created_at, s.channel, s.title AS session_title "
        "FROM messages m JOIN sessions s ON m.session_id=s.id "
        f"WHERE {' AND '.join(cond)} ORDER BY m.created_at DESC LIMIT ?"
    )
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def set_flag(message_id: str, flagged: bool, reason: str = "") -> None:
    with _conn() as c:
        c.execute("UPDATE messages SET flagged=?, flag_reason=? WHERE id=?",
                  (1 if flagged else 0, reason, message_id))
