# -*- coding: utf-8 -*-
"""core/seed.py — 演示数据初始化

一台「已经营业两周」的酒店：24 间房、近 7 天房态流水、当班待办、拦截记录。
种子数据是刻意造的，用来让指标一打开就有东西可看；文档与页面都会标注「演练数据」。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from core import db, security
from domain.state_machine import STATES, sla_thresholds

random.seed(20261106)

ROOM_TYPES = ["大床房", "双床房", "大床房", "双床房", "家庭房", "套房"]

# 当前房态编排：覆盖全部七个状态，且包含 3 个超时房，便于演示告警
CURRENT = {
    "occupied": ["802", "903", "1005", "1102"],
    "ready": ["801", "804", "902", "1001", "1004", "1106"],
    "clean": ["803", "905", "1002", "1103", "1105"],
    "inspecting": ["1104"],
    "cleaning": ["805", "904", "1101"],
    "dirty": ["806", "901", "1003"],
    "blocked": ["906", "1006"],
}

GUESTS = ["张伟", "李娜", "王强", "陈静", "周敏", "赵磊"]

# 已清扫/查房中房间的「距今分钟」：803、1103 故意超时
AGE_MIN = {
    "803": 26, "905": 9, "1002": 4, "1103": 34, "1105": 7,
    "1104": 19, "805": 22, "904": 41, "1101": 6,
    "806": 8, "901": 105, "1003": 35,
    "906": 780, "1006": 1450,
    "801": 62, "804": 240, "902": 15, "1001": 330, "1004": 88, "1106": 460,
    "802": 210, "903": 95, "1005": 40, "1102": 300,
}

USERS = [
    ("admin", "运营管理", "admin", "运营部", "Admin@123"),
    ("front", "林亦舟", "front", "前台", "Front@123"),
    ("house", "唐映秋", "house", "客房调度", "House@123"),
    ("qa", "傅景", "qa", "服务质量", "Qa@123"),
]


def _ts(minutes_ago: float = 0) -> str:
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _all_rooms() -> list[dict]:
    out = []
    for floor, base in ((8, 800), (9, 900), (10, 1000), (11, 1100)):
        for i in range(1, 7):
            out.append(
                {
                    "room_no": f"{base + i}",
                    "floor": floor,
                    "room_type": ROOM_TYPES[i - 1],
                }
            )
    return out


def _seed_users() -> None:
    for username, display, role, post, pwd in USERS:
        if not db.row("SELECT id FROM users WHERE username=?", (username,)):
            db.exec_write(
                "INSERT INTO users(username, display, role, post, password_hash, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (username, display, role, post, security.hash_password(pwd), db.now_str()),
            )


def _seed_rooms() -> None:
    for room in _all_rooms():
        state, age = "dirty", 0
        for st, nos in CURRENT.items():
            if room["room_no"] in nos:
                state, age = st, AGE_MIN.get(room["room_no"], 0)
                break
        guest = random.choice(GUESTS) if state == "occupied" else ""
        nights = random.randint(1, 3) if state == "occupied" else 0
        block_reason = ""
        if state == "blocked":
            block_reason = "空调不制冷，等待工程检修" if room["room_no"] == "906" else "卫生间漏水，外委维修"
        eta = ""
        if state in ("clean", "inspecting"):
            limits = sla_thresholds()
            left = max(3, limits["clean"] + limits["inspecting"] - age)
            eta = (datetime.now() + timedelta(minutes=left)).strftime("%H:%M")
        db.exec_write(
            "INSERT INTO rooms(room_no, floor, room_type, state, state_since, guest_name, nights, "
            "eta, block_reason, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                room["room_no"], room["floor"], room["room_type"], state, _ts(age),
                guest, nights, eta, block_reason, "seed",
            ),
        )


def _seed_history(days: int = 7) -> None:
    """近 N 天：每天有一部分房间翻房（退房→清扫→查房→可售），产生可用于时效统计的流水

    注意不是「每间房每天都翻一轮」——那样每天转可售的都是 24 间，趋势图会变成一条直线，
    既不真实也看不出差异。真实门店每天翻房数在十几到二十之间波动。
    """
    for d in range(days, 0, -1):
        day = (datetime.now() - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        turnover = random.randint(13, 20)
        for room in random.sample(_all_rooms(), turnover):
            t0 = day + timedelta(hours=9, minutes=random.randint(0, 240))
            clean_gap = random.randint(3, 34)          # 已清扫 → 开始查房：长尾在这里
            inspect = random.randint(7, 18)
            seq = [
                ("occupied", "dirty", t0, "客人退房", "front"),
                ("dirty", "cleaning", t0 + timedelta(minutes=random.randint(6, 28)), "开始清扫", "house"),
                ("cleaning", "clean", t0 + timedelta(minutes=random.randint(38, 62)), "提交已清扫", "house"),
                ("clean", "inspecting", t0 + timedelta(minutes=60 + clean_gap), "开始查房", "qa"),
                ("inspecting", "ready", t0 + timedelta(minutes=60 + clean_gap + inspect), "查房通过", "qa"),
            ]
            for from_s, to_s, ts, reason, role in seq:
                db.exec_write(
                    "INSERT INTO room_events(room_no, from_state, to_state, actor, role, reason, created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (room["room_no"], from_s, to_s, f"{role}_seed", role, reason,
                     ts.strftime("%Y-%m-%d %H:%M:%S")),
                )


def _seed_interventions() -> None:
    """近 7 天拦截记录：模拟「前台拿已清扫当可售」被系统拦下"""
    per_day = [2, 3, 4, 2, 3, 3, 2]
    for i, n in enumerate(per_day):
        for _ in range(n):
            room_no = random.choice(["803", "905", "1002", "1103", "1105"])
            created = (datetime.now() - timedelta(days=6 - i)).replace(
                hour=random.randint(10, 20), minute=random.randint(0, 59)
            )
            db.exec_write(
                "INSERT INTO interventions(room_no, kind, attempted_state, detail, actor, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    room_no, "premature_checkin", "clean",
                    "前台尝试为「已清扫待查房」的房间办理入住，被闸门拦截",
                    "front", created.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )


def _seed_checkins() -> None:
    for i, room_no in enumerate(CURRENT["occupied"]):
        created = (datetime.now() - timedelta(minutes=AGE_MIN[room_no])).strftime("%Y-%m-%d %H:%M:%S")
        db.exec_write(
            "INSERT INTO checkins(room_no, guest_name, nights, operator, created_at) VALUES(?,?,?,?,?)",
            (room_no, GUESTS[i % len(GUESTS)], random.randint(1, 3), "front", created),
        )
    # 前几天的入住记录（趋势用）
    for d in range(1, 7):
        for room_no in random.sample([r["room_no"] for r in _all_rooms()], 8):
            created = (datetime.now() - timedelta(days=d)).replace(hour=random.randint(10, 21))
            db.exec_write(
                "INSERT INTO checkins(room_no, guest_name, nights, operator, created_at) "
                "VALUES(?,?,?,?,?)",
                (room_no, random.choice(GUESTS), random.randint(1, 3), "front", created.strftime("%Y-%m-%d %H:%M:%S")),
            )


def _seed_tasks() -> None:
    limits = sla_thresholds()
    for state, rooms in CURRENT.items():
        for room_no in rooms:
            age = AGE_MIN.get(room_no, 0)
            if state == "clean":
                kind, note, prio = "inspection", "清扫完成，等待查房", "high" if age > limits["clean"] else "normal"
                due = (datetime.now() + timedelta(minutes=max(-30, limits["clean"] - age))).strftime("%Y-%m-%d %H:%M:%S")
            elif state == "inspecting":
                kind, note, prio = None, "", "normal"
                due = ""
            elif state in ("dirty", "cleaning"):
                kind, note, prio = "cleaning", "待清扫", "normal"
                due = (datetime.now() + timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
            elif state == "blocked":
                kind, note, prio = "maintenance", "维修处理", "high"
                due = (datetime.now() + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
            else:
                continue
            if not kind:
                continue
            db.exec_write(
                "INSERT INTO tasks(room_no, kind, status, priority, source, note, created_at, due_at) "
                "VALUES(?,?,'open',?,?,?,?,?)",
                (room_no, kind, prio, "system", note, _ts(age), due),
            )


def _seed_handover() -> None:
    db.exec_write(
        "INSERT INTO handovers(shift, summary, issues, created_by, created_at) VALUES(?,?,?,?,?)",
        (
            "早班",
            "待查房 5 间（803 已超时 26 分钟）；在住 4 间；可售 6 间。已清扫≠可售，交接口径已强调。",
            "906 空调待修、1006 卫生间漏水；803 客人 14:00 到店，需优先查房。",
            "front",
            _ts(180),
        ),
    )


def _seed_today_events() -> None:
    """补今天的迁移流水：让「当前状态」在事件表里有来历，趋势图今天不再是 0"""
    enter = {
        "clean": ("cleaning", "提交已清扫", "house"),
        "inspecting": ("clean", "开始查房", "qa"),
        "ready": ("inspecting", "查房通过", "qa"),
        "occupied": ("ready", "办理入住", "front"),
        "blocked": ("ready", "报修停用", "house"),
    }
    for state, rooms in CURRENT.items():
        spec = enter.get(state)
        if not spec:
            continue
        from_s, reason, role = spec
        for room_no in rooms:
            db.exec_write(
                "INSERT INTO room_events(room_no, from_state, to_state, actor, role, reason, created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (room_no, from_s, state, f"{role}_seed", role, reason, _ts(AGE_MIN.get(room_no, 0))),
            )


def init(force: bool = False) -> dict:
    db.init_db()
    for k, v in db.DEFAULT_SETTINGS.items():
        if not db.row("SELECT 1 FROM settings WHERE key=?", (k,)):
            db.set_setting(k, v)

    if db.scalar("SELECT COUNT(*) FROM rooms") and not force:
        _seed_users()
        return {"seeded": False, "reason": "已存在房间数据"}

    if force:
        for t in ("rooms", "room_events", "tasks", "checkins", "interventions", "handovers",
                  "audit_log", "agent_messages", "agent_actions", "agent_sessions",
                  "kb_chunks", "kb_docs"):
            db.exec_write(f"DELETE FROM {t}")

    _seed_users()
    _seed_rooms()
    _seed_history()
    _seed_today_events()
    _seed_interventions()
    _seed_checkins()
    _seed_tasks()
    _seed_handover()
    db.audit("system", "admin", "seed", "全部", "初始化演示数据：24 间房 / 7 天流水")

    from kb import store as kb_store

    n = kb_store.seed_from_files()
    kb_store.reindex_all()
    return {"seeded": True, "rooms": db.scalar("SELECT COUNT(*) FROM rooms"),
            "events": db.scalar("SELECT COUNT(*) FROM room_events"), "kb_docs": n}


if __name__ == "__main__":
    print(init(force="--force" in __import__("sys").argv))
