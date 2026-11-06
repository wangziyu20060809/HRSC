# -*- coding: utf-8 -*-
"""core/db.py — SQLite 数据访问底座

设计取舍（MVP）：
- 每次请求新建连接（SQLite 打开成本极低），避免 FastAPI 线程池里的跨线程连接问题；
- WAL 模式支撑「多个值班终端同时读、少量写」；
- 全部 SQL 集中在本文件与 repo 层，接口层不写 SQL，便于后续换 PostgreSQL/pgvector。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    display       TEXT NOT NULL,
    role          TEXT NOT NULL,          -- admin / front / house / qa
    post          TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

-- 房间：state 是唯一事实源，state_since 用于 SLA 判定
CREATE TABLE IF NOT EXISTS rooms (
    room_no      TEXT PRIMARY KEY,
    floor        INTEGER NOT NULL,
    room_type    TEXT NOT NULL,
    state        TEXT NOT NULL,
    state_since  TEXT NOT NULL,
    guest_name   TEXT DEFAULT '',
    nights       INTEGER DEFAULT 0,
    eta          TEXT DEFAULT '',          -- 预计可售时间（前台可见）
    block_reason TEXT DEFAULT '',
    note         TEXT DEFAULT '',
    updated_by   TEXT DEFAULT ''
);

-- 房态流水：每一次流转都留痕，审计与时效统计的唯一依据
CREATE TABLE IF NOT EXISTS room_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no    TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state   TEXT NOT NULL,
    actor      TEXT NOT NULL,
    role       TEXT NOT NULL,
    reason     TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no    TEXT NOT NULL,
    kind       TEXT NOT NULL,             -- inspection / cleaning / maintenance
    status     TEXT NOT NULL,             -- open / doing / done / cancelled
    priority   TEXT NOT NULL DEFAULT 'normal',
    assignee   TEXT DEFAULT '',
    source     TEXT DEFAULT 'system',     -- system / agent / manual
    note       TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    due_at     TEXT DEFAULT '',
    closed_at  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS checkins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no     TEXT NOT NULL,
    guest_name  TEXT NOT NULL,
    nights      INTEGER NOT NULL DEFAULT 1,
    operator    TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'front_desk',
    created_at  TEXT NOT NULL,
    released_at TEXT DEFAULT ''
);

-- 拦截记录：把「本该发生的房态错误」变成可计数指标
CREATE TABLE IF NOT EXISTS interventions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no         TEXT NOT NULL,
    kind            TEXT NOT NULL,        -- premature_checkin / stale_clean / manual_override
    attempted_state TEXT DEFAULT '',
    detail          TEXT DEFAULT '',
    actor           TEXT DEFAULT '',
    prevented       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handovers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shift      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    issues     TEXT DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor      TEXT NOT NULL,
    role       TEXT NOT NULL,
    action     TEXT NOT NULL,
    target     TEXT DEFAULT '',
    detail     TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_docs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT '制度',
    body       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id  INTEGER NOT NULL,
    ord     INTEGER NOT NULL,
    text    TEXT NOT NULL,
    tokens  TEXT NOT NULL,
    vec     BLOB
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    role       TEXT NOT NULL,
    title      TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role       TEXT NOT NULL,             -- user / assistant
    content    TEXT NOT NULL,
    trace      TEXT DEFAULT '',
    citations  TEXT DEFAULT '',
    latency_ms INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Agent 的写操作一律先落「提案」，人工确认后才执行
CREATE TABLE IF NOT EXISTS agent_actions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER DEFAULT 0,
    tool       TEXT NOT NULL,
    args       TEXT NOT NULL,
    summary    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending / confirmed / rejected / failed
    result     TEXT DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT DEFAULT '',
    decided_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_room  ON room_events(room_no, created_at);
CREATE INDEX IF NOT EXISTS idx_events_time  ON room_events(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_room   ON tasks(room_no, status);
CREATE INDEX IF NOT EXISTS idx_chunks_doc   ON kb_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_actions_st   ON agent_actions(status);
"""


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def rows(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def row(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with connect() as conn:
        r = conn.execute(sql, tuple(params)).fetchone()
        return dict(r) if r else None


def exec_write(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.lastrowid or cur.rowcount


def scalar(sql: str, params: Iterable[Any] = (), default: Any = 0) -> Any:
    with connect() as conn:
        r = conn.execute(sql, tuple(params)).fetchone()
        return default if r is None or r[0] is None else r[0]


# ---------------------------------------------------------------------
# 设置项
# ---------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "sla_clean_wait_min": str(config.SLA_CLEAN_WAIT_MIN),
    "sla_inspect_min": str(config.SLA_INSPECT_MIN),
    "sla_dirty_min": str(config.SLA_DIRTY_MIN),
    "agent_enabled": "1",
    "agent_allow_write_tools": "1",
}


def get_setting(key: str, default: str = "") -> str:
    r = row("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key: str, value: str) -> None:
    exec_write(
        "INSERT INTO settings(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_int_setting(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except ValueError:
        return default


def audit(actor: str, role: str, action: str, target: str = "", detail: str = "") -> None:
    exec_write(
        "INSERT INTO audit_log(actor, role, action, target, detail, created_at) VALUES(?,?,?,?,?,?)",
        (actor, role, action, target, detail, now_str()),
    )
