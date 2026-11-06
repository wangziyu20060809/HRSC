# -*- coding: utf-8 -*-
"""agent/tools.py — 工具注册表

分两类，这是整个 Agent 的信任边界：
- read 工具：直接执行，幂等、无副作用。
- write 工具：**不执行**，只生成 agent_actions 里的一条 pending 提案，附带「要做什么、为什么」，
  由有权限的员工在界面上确认。LLM 再强也改不了房态，这是刻意的。

每个工具都返回结构化 dict，既给模型看，也给前端渲染（例如 find_available_rooms 的结果直接画成房卡）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from core import db
from domain import metrics as M
from domain.state_machine import (
    STATES,
    apply,
    checkin_gate,
    decorate,
    record_intervention,
    sla_thresholds,
)
from kb import store as kb_store

# ---------------------------------------------------------------------
# 只读工具
# ---------------------------------------------------------------------


def _list_rooms(state: str = "", floor: int | None = None) -> dict:
    sql = "SELECT * FROM rooms WHERE 1=1"
    params: list[Any] = []
    if state:
        sql += " AND state=?"
        params.append(state)
    if floor:
        sql += " AND floor=?"
        params.append(floor)
    sql += " ORDER BY room_no"
    rooms = [decorate(r) for r in db.rows(sql, params)]
    return {
        "count": len(rooms),
        "counts": M.room_counts(),
        "rooms": [
            {
                "room_no": r["room_no"],
                "floor": r["floor"],
                "room_type": r["room_type"],
                "state": r["state"],
                "state_label": r["state_label"],
                "age_min": r["age_min"],
                "overdue": r["overdue"],
                "sellable": r["sellable"],
                "guest_name": r["guest_name"],
            }
            for r in rooms
        ],
    }


def _get_room(room_no: str) -> dict:
    room = db.row("SELECT * FROM rooms WHERE room_no=?", (room_no,))
    if not room:
        return {"error": f"房间 {room_no} 不存在"}
    events = db.rows(
        "SELECT from_state, to_state, actor, role, reason, created_at FROM room_events "
        "WHERE room_no=? ORDER BY id DESC LIMIT 6",
        (room_no,),
    )
    gate = checkin_gate(room_no)
    r = decorate(room)
    return {
        "room_no": r["room_no"],
        "floor": r["floor"],
        "room_type": r["room_type"],
        "state": r["state"],
        "state_label": r["state_label"],
        "state_desc": r["state_desc"],
        "sellable": r["sellable"],
        "state_since": r["state_since"],
        "age_min": r["age_min"],
        "sla_min": r["sla_min"],
        "overdue": r["overdue"],
        "guest_name": r["guest_name"],
        "nights": r["nights"],
        "eta": r["eta"],
        "block_reason": r["block_reason"],
        "task": (r["task"] or {}).get("kind") if r["task"] else None,
        "can_checkin": gate["allowed"],
        "checkin_reason": gate["reason"],
        "next_step": gate.get("next_step", ""),
        "alternatives": [a["room_no"] for a in gate.get("alternatives", [])],
        "recent_events": events,
    }


def _find_available_rooms(room_type: str = "", floor: int | None = None, limit: int = 5) -> dict:
    rooms = [decorate(r) for r in db.rows("SELECT * FROM rooms WHERE state='ready' ORDER BY room_no")]
    if room_type:
        rooms = [r for r in rooms if room_type in r["room_type"]]
    if floor:
        rooms = [r for r in rooms if r["floor"] == int(floor)]
    return {
        "count": len(rooms),
        "filter": {"room_type": room_type, "floor": floor},
        "rooms": [
            {"room_no": r["room_no"], "floor": r["floor"], "room_type": r["room_type"], "age_min": r["age_min"]}
            for r in rooms[: int(limit)]
        ],
        "note": "只有「可售」纳入统计；已清扫待查房不算库存。",
    }


def _list_pending_inspections(overdue_only: bool = False) -> dict:
    limits = sla_thresholds()
    rooms = [decorate(r) for r in db.rows("SELECT * FROM rooms WHERE state IN ('clean','inspecting')")]
    if overdue_only:
        rooms = [r for r in rooms if r["overdue"]]
    rooms.sort(key=lambda r: -r["age_min"])
    return {
        "count": len(rooms),
        "limit_clean_wait_min": limits["clean"],
        "limit_inspect_min": limits["inspecting"],
        "rooms": [
            {
                "room_no": r["room_no"],
                "state": r["state"],
                "state_label": r["state_label"],
                "wait_min": r["age_min"],
                "overdue": r["overdue"],
                "eta": r["eta"],
            }
            for r in rooms
        ],
    }


def _get_metrics() -> dict:
    o = M.overview()
    return {
        "counts": o["counts"],
        "sellable": o["sellable"],
        "sellable_rate_pct": o["sellable_rate"],
        "avg_clean_to_ready_min": o["avg_clean_to_ready_min"],
        "p90_clean_to_ready_min": o["p90_clean_to_ready_min"],
        "samples_7d": o["samples_7d"],
        "overdue": o["overdue"],
        "blocked_week": o["blocked_week"],
        "blocked_today": o["blocked_today"],
        "checkins_today": o["checkins_today"],
        "tasks_open": o["tasks_open"],
        "limits": o["limits"],
        "baseline": o["baseline"],
    }


def _search_knowledge(query: str, top_k: int = 3) -> dict:
    hits = kb_store.search(query, top_k=int(top_k))
    return {
        "query": query,
        "hits": [
            {"ref": h["ref"], "doc_title": h["doc_title"], "text": h["text"], "score": h["score"]}
            for h in hits
        ],
    }


def _get_shift_summary() -> dict:
    s = M.shift_summary()
    return {
        "generated_at": s["generated_at"],
        "waiting_inspection": [
            {"room_no": r["room_no"], "state_label": r["state_label"], "wait_min": r["age_min"]}
            for r in s["waiting_inspection"]
        ],
        "overdue_count": s["overdue_count"],
        "blocked": [{"room_no": r["room_no"], "reason": r["block_reason"]} for r in s["blocked"]],
        "occupied_count": len(s["occupied"]),
        "open_tasks": len(s["tasks"]),
        "handover_text": s["handover_text"],
    }


# ---------------------------------------------------------------------
# 写工具：只生成提案，不改数据
# ---------------------------------------------------------------------
def _proposal(user: dict, session_id: int, tool: str, args: dict, summary: str) -> dict:
    if db.get_setting("agent_allow_write_tools", "1") != "1":
        return {"status": "disabled", "message": "管理端已关闭助手的写操作提案"}
    action_id = db.exec_write(
        "INSERT INTO agent_actions(session_id, tool, args, summary, status, created_by, created_at) "
        "VALUES(?,?,?,?, 'pending', ?, ?)",
        (session_id, tool, json.dumps(args, ensure_ascii=False), summary, user["username"], db.now_str()),
    )
    db.audit(user["username"], user["role"], f"agent_propose:{tool}", args.get("room_no", ""), summary)
    return {
        "status": "pending_confirmation",
        "action_id": action_id,
        "summary": summary,
        "hint": "已生成待确认动作，需有权限的员工在界面上确认后才执行。",
    }


def _propose_start_inspection(user: dict, session_id: int, room_no: str) -> dict:
    room = db.row("SELECT * FROM rooms WHERE room_no=?", (room_no,))
    if not room:
        return {"error": f"房间 {room_no} 不存在"}
    if room["state"] != "clean":
        return {"error": f"{room_no} 当前是「{STATES[room['state']]['label']}」，只有「已清扫待查房」才能发起查房"}
    return _proposal(
        user, session_id, "start_inspection", {"room_no": room_no},
        f"对 {room_no} 发起查房（当前已等待 {decorate(room)['age_min']} 分钟）",
    )


def _propose_mark_ready(user: dict, session_id: int, room_no: str) -> dict:
    room = db.row("SELECT * FROM rooms WHERE room_no=?", (room_no,))
    if not room:
        return {"error": f"房间 {room_no} 不存在"}
    if room["state"] != "inspecting":
        return {"error": f"{room_no} 当前是「{STATES[room['state']]['label']}」，只有「查房中」才能下通过结论"}
    return _proposal(
        user, session_id, "pass_inspection", {"room_no": room_no},
        f"判定 {room_no} 查房通过并转为可售（确认即视为你本人下的结论）",
    )


def _propose_block_room(user: dict, session_id: int, room_no: str, reason: str) -> dict:
    room = db.row("SELECT * FROM rooms WHERE room_no=?", (room_no,))
    if not room:
        return {"error": f"房间 {room_no} 不存在"}
    if room["state"] == "blocked":
        return {"error": f"{room_no} 已经是维修中"}
    return _proposal(
        user, session_id, "block", {"room_no": room_no, "reason": reason},
        f"将 {room_no} 转维修停用：{reason}",
    )


def _propose_checkin(user: dict, session_id: int, room_no: str, guest_name: str, nights: int = 1) -> dict:
    gate = checkin_gate(room_no)
    if not gate["allowed"]:
        alts = "、".join(a["room_no"] for a in gate.get("alternatives", [])) or "暂无"
        return {
            "blocked": True,
            "reason": gate["reason"],
            "state_label": gate.get("state_label"),
            "next_step": gate.get("next_step"),
            "alternatives": gate.get("alternatives", []),
            "message": f"{room_no} 不能入住：{gate['reason']}。可替代房间：{alts}。",
        }
    return _proposal(
        user, session_id, "check_in",
        {"room_no": room_no, "guest_name": guest_name, "nights": int(nights)},
        f"为 {guest_name} 办理 {room_no} 入住，{nights} 晚",
    )


# ---------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------
READ_TOOLS: dict[str, dict] = {
    "list_rooms": {
        "fn": _list_rooms,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_rooms",
                "description": "列出房间及房态；可按状态与楼层筛选。state 取 dirty/cleaning/clean/inspecting/ready/occupied/blocked。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "state": {"type": "string", "description": "房态英文键，可空"},
                        "floor": {"type": "integer", "description": "楼层，可空"},
                    },
                },
            },
        },
    },
    "get_room": {
        "fn": _get_room,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_room",
                "description": "查单个房间的房态、等待时长、客人、最近流水、能否入住、替代房。",
                "parameters": {
                    "type": "object",
                    "properties": {"room_no": {"type": "string", "description": "房号，如 803"}},
                    "required": ["room_no"],
                },
            },
        },
    },
    "find_available_rooms": {
        "fn": _find_available_rooms,
        "schema": {
            "type": "function",
            "function": {
                "name": "find_available_rooms",
                "description": "查当前真正可售（查房已通过）的房间，用于给客人分配。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room_type": {"type": "string", "description": "房型关键词，如 大床房"},
                        "floor": {"type": "integer", "description": "楼层，可空"},
                        "limit": {"type": "integer", "description": "返回条数，默认 5"},
                    },
                },
            },
        },
    },
    "list_pending_inspections": {
        "fn": _list_pending_inspections,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_pending_inspections",
                "description": "查待查房/查房中的队列，按等待时长倒序，标注是否超时。",
                "parameters": {
                    "type": "object",
                    "properties": {"overdue_only": {"type": "boolean", "description": "只看超时的"}},
                },
            },
        },
    },
    "get_metrics": {
        "fn": _get_metrics,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_metrics",
                "description": "查当班与近 7 天指标：可售数、平均清扫到可售时长、超时数、拦截次数、在住数。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },
    "search_knowledge": {
        "fn": _search_knowledge,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "description": "检索酒店房态制度知识库：口径、查房标准、闸门规则、超时升级、异常处置。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索问题，用员工原话即可"},
                        "top_k": {"type": "integer", "description": "返回条数，默认 3"},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    "get_shift_summary": {
        "fn": _get_shift_summary,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_shift_summary",
                "description": "生成交接班摘要：待查房、超时、维修、在住、未完成任务。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },
}

WRITE_TOOLS: dict[str, dict] = {
    "propose_start_inspection": {
        "fn": _propose_start_inspection,
        "schema": {
            "type": "function",
            "function": {
                "name": "propose_start_inspection",
                "description": "提议对某间已清扫的房间发起查房（生成待确认动作，不直接改房态）。",
                "parameters": {
                    "type": "object",
                    "properties": {"room_no": {"type": "string"}},
                    "required": ["room_no"],
                },
            },
        },
    },
    "propose_mark_ready": {
        "fn": _propose_mark_ready,
        "schema": {
            "type": "function",
            "function": {
                "name": "propose_mark_ready",
                "description": "提议判定某间查房中的房间通过并转可售（生成待确认动作）。",
                "parameters": {
                    "type": "object",
                    "properties": {"room_no": {"type": "string"}},
                    "required": ["room_no"],
                },
            },
        },
    },
    "propose_block_room": {
        "fn": _propose_block_room,
        "schema": {
            "type": "function",
            "function": {
                "name": "propose_block_room",
                "description": "提议把某间房转维修停用，必须给原因（生成待确认动作）。",
                "parameters": {
                    "type": "object",
                    "properties": {"room_no": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["room_no", "reason"],
                },
            },
        },
    },
    "propose_checkin": {
        "fn": _propose_checkin,
        "schema": {
            "type": "function",
            "function": {
                "name": "propose_checkin",
                "description": "提议为客人办理入住；房间不可售时会被闸门拦下并给出替代房（生成待确认动作）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room_no": {"type": "string"},
                        "guest_name": {"type": "string"},
                        "nights": {"type": "integer"},
                    },
                    "required": ["room_no", "guest_name"],
                },
            },
        },
    },
}

ALL_TOOLS = {**READ_TOOLS, **WRITE_TOOLS}


def schemas(allow_write: bool = True) -> list[dict]:
    items = list(READ_TOOLS.values())
    if allow_write:
        items = items + list(WRITE_TOOLS.values())
    return [t["schema"] for t in items]


def is_write(name: str) -> bool:
    return name in WRITE_TOOLS


def call(name: str, args: dict, user: dict, session_id: int) -> dict:
    spec = ALL_TOOLS.get(name)
    if not spec:
        return {"error": f"工具 {name} 不存在"}
    fn: Callable = spec["fn"]
    try:
        if is_write(name):
            return fn(user, session_id, **args)
        return fn(**args)
    except TypeError as exc:
        return {"error": f"参数不匹配：{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"工具执行失败：{exc}"}


# ---------------------------------------------------------------------
# 确认执行（人工点击之后）
# ---------------------------------------------------------------------
def confirm_action(action_id: int, user: dict) -> dict:
    act = db.row("SELECT * FROM agent_actions WHERE id=?", (action_id,))
    if not act:
        return {"code": 40401, "message": "待确认动作不存在"}
    if act["status"] != "pending":
        return {"code": 40901, "message": f"该动作已处于 {act['status']} 状态"}

    args = json.loads(act["args"])
    tool = act["tool"]
    room_no = args.get("room_no", "")

    try:
        if tool == "check_in":
            gate = checkin_gate(room_no)
            if not gate["allowed"]:
                record_intervention(
                    room_no, "premature_checkin", gate["room"].get("state", ""),
                    f"通过助手提案尝试入住被拦截：{gate['reason']}", user["username"],
                )
                db.exec_write(
                    "UPDATE agent_actions SET status='failed', result=?, decided_by=?, decided_at=? WHERE id=?",
                    (gate["reason"], user["username"], db.now_str(), action_id),
                )
                return {"code": 40003, "message": f"入住被拦截：{gate['reason']}", "gate": gate}
            result = apply(
                room_no, "check_in", user["display"], user["role"],
                payload={"guest_name": args.get("guest_name", ""), "nights": args.get("nights", 1)},
                source="agent",
            )
            db.exec_write(
                "INSERT INTO checkins(room_no, guest_name, nights, operator, channel, created_at) "
                "VALUES(?,?,?,?,'agent',?)",
                (room_no, args.get("guest_name", ""), int(args.get("nights", 1)), user["username"], db.now_str()),
            )
        elif tool == "pass_inspection":
            result = apply(room_no, "pass_inspection", user["display"], user["role"],
                           reason="助手提案，员工确认", source="agent")
        elif tool == "start_inspection":
            result = apply(room_no, "start_inspection", user["display"], user["role"],
                           reason="助手提案，员工确认", source="agent")
        elif tool == "block":
            result = apply(room_no, "block", user["display"], user["role"],
                           reason=args.get("reason", "报修"), source="agent")
        else:
            return {"code": 40001, "message": f"不支持的动作类型 {tool}"}
    except Exception as exc:  # ApiError 也算失败
        db.exec_write(
            "UPDATE agent_actions SET status='failed', result=?, decided_by=?, decided_at=? WHERE id=?",
            (str(exc), user["username"], db.now_str(), action_id),
        )
        return {"code": 40003, "message": str(exc)}

    db.exec_write(
        "UPDATE agent_actions SET status='confirmed', result=?, decided_by=?, decided_at=? WHERE id=?",
        (json.dumps(result, ensure_ascii=False), user["username"], db.now_str(), action_id),
    )
    db.audit(user["username"], user["role"], "agent_confirm", room_no, act["summary"])
    return {"code": 0, "message": result["message"], "result": result}


def reject_action(action_id: int, user: dict) -> dict:
    act = db.row("SELECT * FROM agent_actions WHERE id=?", (action_id,))
    if not act or act["status"] != "pending":
        return {"code": 40901, "message": "该动作不可忽略"}
    db.exec_write(
        "UPDATE agent_actions SET status='rejected', decided_by=?, decided_at=? WHERE id=?",
        (user["username"], db.now_str(), action_id),
    )
    db.audit(user["username"], user["role"], "agent_reject", act["tool"], act["summary"])
    return {"code": 0, "message": "已忽略该建议"}
