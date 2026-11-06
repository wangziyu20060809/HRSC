# -*- coding: utf-8 -*-
"""domain/metrics.py — 指标计算

指标口径直接对齐访谈里管理层给出的两个基线：
- 高峰入住等待 38 分钟 → 目标 15 分钟（本项目用「已清扫 → 可售」的时效代理，真实等待需门店补测）
- 房态错误 24 次/周 → 目标 5 次（本项目用「入住闸门拦截次数」代理，被拦下的就是本该发生的错误）
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core import db
from domain.state_machine import STATES, age_minutes, decorate, sla_thresholds


def _day_start(offset: int = 0) -> str:
    d = datetime.now() - timedelta(days=offset)
    return d.strftime("%Y-%m-%d 00:00:00")


def room_counts() -> dict[str, int]:
    out = {k: 0 for k in STATES}
    for r in db.rows("SELECT state, COUNT(*) AS n FROM rooms GROUP BY state"):
        out[r["state"]] = r["n"]
    return out


def clean_to_ready_durations(days: int = 7) -> list[float]:
    """每间房每次「清扫完成 → 查房通过」的分钟数"""
    since = _day_start(days - 1)
    evs = db.rows(
        "SELECT room_no, to_state, created_at FROM room_events "
        "WHERE created_at >= ? AND to_state IN ('clean','inspecting','ready','cleaning') ORDER BY room_no, id",
        (since,),
    )
    started: dict[str, datetime] = {}
    out: list[float] = []
    for e in evs:
        room, st, ts = e["room_no"], e["to_state"], db.parse(e["created_at"])
        if st == "clean":
            started[room] = ts
        elif st == "ready" and room in started:
            out.append((ts - started.pop(room)).total_seconds() / 60)
        elif st in ("cleaning",) and room in started:
            started.pop(room)
    return out


def daily_series(days: int = 7) -> list[dict]:
    """近 N 天：拦截次数、可售产出、平均查房时效"""
    series = []
    for i in range(days - 1, -1, -1):
        start = _day_start(i)
        end = _day_start(i - 1) if i > 0 else (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        blocked = db.scalar(
            "SELECT COUNT(*) FROM interventions WHERE created_at >= ? AND created_at < ?", (start, end)
        )
        ready = db.scalar(
            "SELECT COUNT(DISTINCT room_no) FROM room_events "
            "WHERE to_state='ready' AND created_at >= ? AND created_at < ?",
            (start, end),
        )
        checkins = db.scalar(
            "SELECT COUNT(*) FROM checkins WHERE created_at >= ? AND created_at < ?", (start, end)
        )
        day = datetime.now() - timedelta(days=i)
        series.append(
            {
                "date": day.strftime("%m-%d"),
                "weekday": "一二三四五六日"[day.weekday()],
                "interventions": blocked,
                "ready": ready,
                "checkins": checkins,
            }
        )
    return series


def overview() -> dict:
    counts = room_counts()
    total = sum(counts.values())
    durations = clean_to_ready_durations(7)
    avg = round(sum(durations) / len(durations), 1) if durations else 0
    p90 = round(sorted(durations)[int(len(durations) * 0.9) - 1], 1) if len(durations) >= 5 else avg

    limits = sla_thresholds()
    rooms = db.rows("SELECT * FROM rooms")
    overdue_clean = [r for r in rooms if r["state"] == "clean" and age_minutes(r) > limits["clean"]]
    overdue_inspect = [r for r in rooms if r["state"] == "inspecting" and age_minutes(r) > limits["inspecting"]]
    overdue_dirty = [r for r in rooms if r["state"] == "dirty" and age_minutes(r) > limits["dirty"]]

    week_start = _day_start(6)
    week_blocked = db.scalar(
        "SELECT COUNT(*) FROM interventions WHERE created_at >= ?", (week_start,)
    )
    today_blocked = db.scalar("SELECT COUNT(*) FROM interventions WHERE created_at >= ?", (_day_start(0),))
    checkins_today = db.scalar("SELECT COUNT(*) FROM checkins WHERE created_at >= ?", (_day_start(0),))

    pending_actions = db.scalar("SELECT COUNT(*) FROM agent_actions WHERE status='pending'")
    decided = db.scalar("SELECT COUNT(*) FROM agent_actions WHERE status IN ('confirmed','rejected')")
    confirmed = db.scalar("SELECT COUNT(*) FROM agent_actions WHERE status='confirmed'")
    adoption = round(confirmed / decided * 100) if decided else 0

    return {
        "counts": counts,
        "total": total,
        "sellable": counts.get("ready", 0),
        "sellable_rate": round(counts.get("ready", 0) / total * 100) if total else 0,
        "avg_clean_to_ready_min": avg,
        "p90_clean_to_ready_min": p90,
        "samples_7d": len(durations),
        "overdue": {
            "clean": len(overdue_clean),
            "inspecting": len(overdue_inspect),
            "dirty": len(overdue_dirty),
            "total": len(overdue_clean) + len(overdue_inspect) + len(overdue_dirty),
        },
        "overdue_rooms": [decorate(r) for r in (overdue_clean + overdue_inspect + overdue_dirty)][:8],
        "blocked_week": week_blocked,
        "blocked_today": today_blocked,
        "checkins_today": checkins_today,
        "tasks_open": db.scalar("SELECT COUNT(*) FROM tasks WHERE status IN ('open','doing')"),
        "pending_actions": pending_actions,
        "ai_adoption": adoption,
        "limits": limits,
        "baseline": {"wait_min": 38, "target_wait_min": 15, "errors_per_week": 24, "target_errors": 5},
    }


def shift_summary() -> dict:
    """交接班摘要：未完成的事，按责任岗位分组"""
    rooms = db.rows("SELECT * FROM rooms")
    limits = sla_thresholds()
    waiting_inspection = [
        decorate(r) for r in rooms if r["state"] in ("clean", "inspecting")
    ]
    waiting_inspection.sort(key=lambda r: -r["age_min"])
    blocked = [decorate(r) for r in rooms if r["state"] == "blocked"]
    occupied = [decorate(r) for r in rooms if r["state"] == "occupied"]
    tasks = db.rows(
        "SELECT * FROM tasks WHERE status IN ('open','doing') ORDER BY "
        "CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at"
    )
    return {
        "generated_at": db.now_str(),
        "waiting_inspection": waiting_inspection,
        "overdue_count": sum(1 for r in waiting_inspection if r["overdue"]),
        "blocked": blocked,
        "occupied": occupied,
        "tasks": tasks,
        "handover_text": _handover_text(waiting_inspection, blocked, occupied, tasks, limits),
    }


def _handover_text(waiting, blocked, occupied, tasks, limits) -> str:
    lines = []
    if waiting:
        head = "、".join(f"{r['room_no']}({r['state_label']} {r['age_min']}分)" for r in waiting[:5])
        lines.append(f"待查房 {len(waiting)} 间：{head}")
    if blocked:
        lines.append("维修停用：" + "、".join(f"{r['room_no']}({r['block_reason'] or '待补原因'})" for r in blocked))
    if occupied:
        lines.append(f"在住 {len(occupied)} 间，退房后自动转待清扫")
    high = [t for t in tasks if t["priority"] == "high"]
    if high:
        lines.append("高优任务：" + "、".join(f"{t['room_no']}{t['note'] or t['kind']}" for t in high[:4]))
    lines.append(f"交接口径：已清扫≠可售，只有查房通过才可报可售；查房超时阈值 {limits['clean']} 分钟")
    return "；".join(lines)
