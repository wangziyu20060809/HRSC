# -*- coding: utf-8 -*-
"""
db.py — SQLite 持久化层（阶段 2 表结构，与接口设计一致）

设计说明：
  · 标准库 sqlite3，零额外依赖；MVP 数据量小（单用户演示），同步调用足够。
  · sessions / messages 两张表沿用阶段 1 架构文档的字段定义；
    向量索引仍用阶段 1 的本地 FAISS 文件（rag_index/），不重复入 SQLite。
  · messages.content 入库前由调用方完成脱敏（本层只负责存取）。
  · 后续阶段切换 PostgreSQL 时，仅需替换本文件，业务层不变。
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path

# 数据库文件固定在本目录下，避免相对路径随工作目录漂移
DB_PATH = Path(__file__).resolve().parent / "expense.db"


def _conn() -> sqlite3.Connection:
    """每次调用新建连接：SQLite 写锁粒度下最简单可靠的用法"""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row          # 查询结果可按列名访问
    conn.execute("PRAGMA journal_mode=WAL")  # 读写不互斥，聊天场景更稳
    return conn


def init_db() -> None:
    """建表（幂等）：服务启动时调用一次"""
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id              TEXT PRIMARY KEY,   -- UUID 会话ID
                user_id         TEXT NOT NULL,      -- 归属用户（MVP 固定演示账号）
                title           TEXT NOT NULL DEFAULT '新会话',
                status          TEXT NOT NULL DEFAULT 'active',
                created_at      TEXT NOT NULL,
                last_active_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,        -- UUID 消息ID
                session_id  TEXT NOT NULL,           -- 所属会话
                role        TEXT NOT NULL,           -- user / assistant / tool
                content     TEXT NOT NULL,           -- 已脱敏正文
                citations   TEXT,                    -- JSON：引用条款数组
                tool_calls  TEXT,                    -- JSON：工具调用记录
                redacted    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );

            -- 历史消息按会话+时间取最近 N 条，此索引避免全表扫描
            CREATE INDEX IF NOT EXISTS idx_messages_session_time
                ON messages(session_id, created_at);
            """
        )


# ----------------------------------------------------------------------
# 会话操作
# ----------------------------------------------------------------------
def create_session(user_id: str = "staff-demo", title: str = "新会话") -> dict:
    """新建会话并返回会话对象"""
    sid = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions(id,user_id,title,status,created_at,last_active_at) VALUES(?,?,?,?,?,?)",
            (sid, user_id, title, "active", now, now),
        )
    return {"session_id": sid, "title": title, "created_at": now}


def list_sessions(user_id: str = "staff-demo") -> list[dict]:
    """会话列表（按最近活跃倒序）"""
    with _conn() as c:
        rows = c.execute(
            "SELECT id,title,status,created_at,last_active_at FROM sessions "
            "WHERE user_id=? AND status='active' ORDER BY last_active_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict | None:
    """按 ID 取会话；不存在返回 None（由接口层转为 40001 错误）"""
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def touch_session(session_id: str, title: str | None = None) -> None:
    """更新活跃时间；首轮提问时用问题前 20 字自动命名会话"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as c:
        if title:
            c.execute(
                "UPDATE sessions SET last_active_at=?, title=? WHERE id=?",
                (now, title[:20], session_id),
            )
        else:
            c.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (now, session_id))


# ----------------------------------------------------------------------
# 消息操作
# ----------------------------------------------------------------------
def add_message(
    session_id: str,
    role: str,
    content: str,
    citations: list | None = None,
    tool_calls: list | None = None,
    redacted: bool = False,
) -> str:
    """写入一条消息，返回消息 ID"""
    mid = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as c:
        c.execute(
            "INSERT INTO messages(id,session_id,role,content,citations,tool_calls,redacted,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                mid,
                session_id,
                role,
                content,
                json.dumps(citations, ensure_ascii=False) if citations else None,
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                1 if redacted else 0,
                now,
            ),
        )
    return mid


def get_recent_messages(session_id: str, limit: int = 12) -> list[dict]:
    """
    取最近 N 条消息（默认 12 条 = 6 轮问答），按时间正序返回。
    接口设计的"历史窗口 6 轮"由此实现；更长历史由上层按 token 预算再截断。
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT role,content,citations,created_at FROM messages "
            "WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    # 反转为正序，供拼入 LLM 上下文
    return [dict(r) for r in reversed(rows)]


def get_all_messages(session_id: str) -> list[dict]:
    """拉取完整历史（前端刷新页面时恢复聊天记录用）"""
    with _conn() as c:
        rows = c.execute(
            "SELECT id,role,content,citations,created_at FROM messages "
            "WHERE session_id=? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        # citations 列是 JSON 字符串，转回对象方便前端直接渲染
        item["citations"] = json.loads(item["citations"]) if item["citations"] else []
        result.append(item)
    return result
