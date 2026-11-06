# -*- coding: utf-8 -*-
"""domain/state_machine.py — 房态状态机（本项目的业务内核）

问题根因不是「缺一个数字看板」，而是三套口径各自为政：
    客房部「已清扫」  →  前台理解成「可入住」  →  查房还没做
所以状态机故意把 clean（已清扫）与 ready（已查房可售）拆成两个节点，
并规定只有 ready 能进 occupied。前台点「已清扫」的房，系统必须拦下来并给出替代房。

七个状态、十条迁移，全部带守卫；迁移即事件，事件即审计与时效统计的原料。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core import db
from core.errors import ApiError
from core.security import TRANSITION_ROLES, can

# ---------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------
STATES: dict[str, dict[str, Any]] = {
    "dirty": {
        "label": "待清扫",
        "short": "待清",
        "color": "#8c9791",
        "desc": "客人已退房或房间需要整理，尚未开始清扫",
        "sellable": False,
    },
    "cleaning": {
        "label": "清扫中",
        "short": "清扫",
        "color": "#d08a2c",
        "desc": "客房部正在清扫，尚不能进入查房",
        "sellable": False,
    },
    "clean": {
        "label": "已清扫待查房",
        "short": "待查",
        "color": "#2f7ec4",
        "desc": "客房部已提交清扫完成，但查房未通过——不等于可入住",
        "sellable": False,
    },
    "inspecting": {
        "label": "查房中",
        "short": "查房",
        "color": "#7a5cc4",
        "desc": "质检/领班正在按检查项核对，尚未出结论",
        "sellable": False,
    },
    "ready": {
        "label": "可售",
        "short": "可售",
        "color": "#2d654f",
        "desc": "查房通过，唯一允许办理入住的状态",
        "sellable": True,
    },
    "occupied": {
        "label": "在住",
        "short": "在住",
        "color": "#4a5a6a",
        "desc": "客人已入住",
        "sellable": False,
    },
    "blocked": {
        "label": "维修中",
        "short": "维修",
        "color": "#b4443a",
        "desc": "设施故障停用，须记录原因与责任岗位",
        "sellable": False,
    },
}

# 迁移表：action -> 定义。from 里列出允许的来源状态。
TRANSITIONS: dict[str, dict[str, Any]] = {
    "start_cleaning": {
        "label": "开始清扫",
        "from": ["dirty"],
        "to": "cleaning",
        "need_reason": False,
        "task_kind": None,
    },
    "finish_cleaning": {
        "label": "提交已清扫",
        "from": ["cleaning"],
        "to": "clean",
        "need_reason": False,
        "task_kind": "inspection",
        "task_note": "清扫完成，等待查房",
    },
    "start_inspection": {
        "label": "开始查房",
        "from": ["clean"],
        "to": "inspecting",
        "need_reason": False,
        "task_kind": None,
    },
    "pass_inspection": {
        "label": "查房通过",
        "from": ["inspecting"],
        "to": "ready",
        "need_reason": False,
        "task_kind": None,
        "close_task": "inspection",
    },
    "fail_inspection": {
        "label": "查房不通过",
        "from": ["inspecting"],
        "to": "cleaning",
        "need_reason": True,
        "task_kind": "cleaning",
        "task_note": "查房不通过，返工清扫",
        "priority": "high",
        "close_task": "inspection",
    },
    "check_in": {
        "label": "办理入住",
        "from": ["ready"],
        "to": "occupied",
        "need_reason": False,
        "task_kind": None,
    },
    "check_out": {
        "label": "办理退房",
        "from": ["occupied"],
        "to": "dirty",
        "need_reason": False,
        "task_kind": "cleaning",
        "task_note": "退房待清扫",
    },
    "block": {
        "label": "报修停用",
        "from": ["dirty", "cleaning", "clean", "inspecting", "ready", "occupied"],
        "to": "blocked",
        "need_reason": True,
        "task_kind": "maintenance",
        "task_note": "维修处理",
        "priority": "high",
    },
    "unblock": {
        "label": "维修完成",
        "from": ["blocked"],
        "to": "dirty",
        "need_reason": False,
        "task_kind": "cleaning",
        "task_note": "维修完成，重新清扫",
    },
    "rework": {
        "label": "临时返工",
        "from": ["ready"],
        "to": "dirty",
        "need_reason": True,
        "task_kind": "cleaning",
        "task_note": "临时返工，重新清扫",
        "priority": "high",
    },
}


# ---------------------------------------------------------------------
# 派生信息
# ---------------------------------------------------------------------
def age_minutes(room: dict, at: str | None = None) -> int:
    start = db.parse(room["state_since"])
    end = db.parse(at) if at else datetime.now()
    return max(0, int((end - start).total_seconds() // 60))


def sla_thresholds() -> dict[str, int]:
    return {
        "clean": db.get_int_setting("sla_clean_wait_min", 12),
        "inspecting": db.get_int_setting("sla_inspect_min", 15),
        "dirty": db.get_int_setting("sla_dirty_min", 90),
    }


def decorate(room: dict) -> dict:
    """给房间补上展示字段与超时标记，前端直接用，不再二次判断"""
    st = STATES.get(room["state"], STATES["dirty"])
    age = age_minutes(room)
    limits = sla_thresholds()
    limit = limits.get(room["state"], 0)
    overdue = bool(limit and age > limit)
    task = db.row(
        "SELECT * FROM tasks WHERE room_no=? AND status IN ('open','doing') "
        "ORDER BY id DESC LIMIT 1",
        (room["room_no"],),
    )
    room = dict(room)
    room.update(
        {
            "state_label": st["label"],
            "state_short": st["short"],
            "state_color": st["color"],
            "state_desc": st["desc"],
            "sellable": st["sellable"],
            "age_min": age,
            "sla_min": limit,
            "overdue": overdue,
            "task": task,
            "allowed_actions": allowed_actions(room["state"]),
        }
    )
    return room


def allowed_actions(state: str) -> list[dict]:
    out = []
    for action, spec in TRANSITIONS.items():
        if state in spec["from"]:
            out.append(
                {
                    "action": action,
                    "label": spec["label"],
                    "to": spec["to"],
                    "need_reason": spec["need_reason"],
                    "roles": sorted(TRANSITION_ROLES.get(action, set())),
                }
            )
    return out


# ---------------------------------------------------------------------
# 迁移执行
# ---------------------------------------------------------------------
def _open_task(room_no: str, kind: str, note: str, priority: str, due_min: int, source: str) -> None:
    exists = db.row(
        "SELECT * FROM tasks WHERE room_no=? AND kind=? AND status IN ('open','doing')",
        (room_no, kind),
    )
    if exists:
        # 已有同类任务：仅当新任务优先级更高时升级，避免重复建单
        if priority == "high" and exists["priority"] != "high":
            db.exec_write("UPDATE tasks SET priority='high', note=? WHERE id=?", (note or exists["note"], exists["id"]))
        return
    created = datetime.now()
    due = (created + timedelta(minutes=due_min)).strftime("%Y-%m-%d %H:%M:%S")
    db.exec_write(
        "INSERT INTO tasks(room_no, kind, status, priority, source, note, created_at, due_at) "
        "VALUES(?,?,'open',?,?,?,?,?)",
        (room_no, kind, priority, source, note, created.strftime("%Y-%m-%d %H:%M:%S"), due),
    )


def _close_task(room_no: str, kind: str) -> None:
    db.exec_write(
        "UPDATE tasks SET status='done', closed_at=? "
        "WHERE room_no=? AND kind=? AND status IN ('open','doing')",
        (db.now_str(), room_no, kind),
    )


def apply(
    room_no: str,
    action: str,
    actor: str,
    role: str,
    reason: str = "",
    payload: dict | None = None,
    source: str = "ui",
) -> dict:
    """执行一次房态迁移。所有业务规则集中在此，任何入口（页面/接口/Agent）都必须走这里。"""
    payload = payload or {}
    spec = TRANSITIONS.get(action)
    if not spec:
        raise ApiError(40001, f"未知操作：{action}")

    if role != "admin" and not can(role, action):
        raise ApiError(40301, f"「{spec['label']}」不在当前岗位职责内，请交接给对应岗位")

    room = db.row("SELECT * FROM rooms WHERE room_no=?", (room_no,))
    if not room:
        raise ApiError(40002, f"房间 {room_no} 不存在")

    if payload.get("expected_state") and payload["expected_state"] != room["state"]:
        raise ApiError(40901, "房间状态已变化，请刷新后重试")

    if room["state"] not in spec["from"]:
        cur = STATES[room["state"]]["label"]
        raise ApiError(
            40003,
            f"房间当前是「{cur}」，不能执行「{spec['label']}」",
            detail=f"允许的来源状态：{'、'.join(STATES[s]['label'] for s in spec['from'])}",
        )

    reason = (reason or "").strip()
    if spec["need_reason"] and not reason:
        raise ApiError(40001, f"「{spec['label']}」必须填写原因（留痕用）")

    if action == "check_in":
        guest = (payload.get("guest_name") or "").strip()
        if not guest:
            raise ApiError(40001, "请填写入住客人姓名")
        if payload.get("nights") is not None:
            try:
                nights = int(payload["nights"])
            except (TypeError, ValueError):
                raise ApiError(40001, "住晚数必须是整数")
            if nights < 1 or nights > 30:
                raise ApiError(40001, "住晚数应在 1-30 之间")
        else:
            nights = 1

    if action == "pass_inspection":
        checklist = payload.get("checklist") or {}
        failed = [k for k, v in checklist.items() if v is False]
        if failed:
            raise ApiError(40003, f"检查项未全部通过（{len(failed)} 项不合格），请选择「查房不通过」并说明返工内容")

    now = db.now_str()
    to_state = spec["to"]

    # —— 落地：更新房间 + 记流水 + 记审计 + 衍生任务 ——
    fields = ["state=?", "state_since=?", "updated_by=?"]
    values: list[Any] = [to_state, now, actor]
    if action == "check_in":
        fields += ["guest_name=?", "nights=?", "eta=''"]
        values += [payload["guest_name"].strip(), nights]
    if action == "check_out":
        fields += ["guest_name=''", "nights=0", "eta=''"]
    if action == "block":
        fields += ["block_reason=?", "eta=''"]
        values += [reason]
    if action == "unblock":
        fields += ["block_reason=''"]
    if action == "rework":
        fields += ["note=?", "eta=''"]
        values += [reason]
    values.append(room_no)
    db.exec_write(f"UPDATE rooms SET {', '.join(fields)} WHERE room_no=?", values)

    db.exec_write(
        "INSERT INTO room_events(room_no, from_state, to_state, actor, role, reason, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (room_no, room["state"], to_state, actor, role, reason, now),
    )
    if spec.get("close_task"):
        _close_task(room_no, spec["close_task"])
    if spec.get("task_kind"):
        due = 20 if spec["task_kind"] == "inspection" else 45
        _open_task(
            room_no,
            spec["task_kind"],
            spec.get("task_note", ""),
            spec.get("priority", "normal"),
            due,
            source,
        )

    db.audit(
        actor,
        role,
        f"state:{action}",
        room_no,
        f"{STATES[room['state']]['label']} → {STATES[to_state]['label']}" + (f"｜{reason}" if reason else ""),
    )

    from_label = STATES[room["state"]]["label"]
    to_label = STATES[to_state]["label"]
    return {
        "room_no": room_no,
        "from_state": room["state"],
        "to_state": to_state,
        "to_label": to_label,
        "message": f"{room_no}：「{from_label}」→「{to_label}」",
    }


# ---------------------------------------------------------------------
# 入住闸门：本项目的核心业务价值
# ---------------------------------------------------------------------
def checkin_gate(room_no: str) -> dict:
    """判断这个房间能不能办入住，不能时说明原因并给出替代房。

    返回结构直接给前端/AI 用：
      allowed=True  → 可以办，带房间信息
      allowed=False → 拦截原因、需要谁做什么、预计多久、可替代房间
    """
    room = db.row("SELECT * FROM rooms WHERE room_no=?", (room_no,))
    if not room:
        raise ApiError(40002, f"房间 {room_no} 不存在")

    state = room["state"]
    st = STATES[state]
    age = age_minutes(room)
    limits = sla_thresholds()

    if state == "ready":
        return {
            "allowed": True,
            "room_no": room_no,
            "room": decorate(room),
            "reason": "查房已通过，房态为可售",
            "wait_min": 0,
        }

    reasons = {
        "dirty": ("房间待清扫，尚未开始整理", limits["dirty"] + 30),
        "cleaning": ("客房部正在清扫，清扫完成后还需查房", 40),
        "clean": ("已清扫但查房未完成——这正是「客人到店只能在大堂等」的断点", max(3, limits["clean"] + 8 - age)),
        "inspecting": ("查房进行中，尚未出结论", max(3, limits["inspecting"] - age)),
        "occupied": ("房间在住，不能分配", 0),
        "blocked": (f"房间维修停用：{room['block_reason'] or '未填原因'}", 0),
    }
    why, eta = reasons.get(state, ("房态不可售", 0))

    # 替代房：同房型优先，其次同楼层，最后任意可售房
    alts = db.rows("SELECT * FROM rooms WHERE state='ready' ORDER BY room_no")
    alts.sort(key=lambda r: (r["room_type"] != room["room_type"], r["floor"] != room["floor"], r["room_no"]))
    alternatives = [
        {
            "room_no": r["room_no"],
            "floor": r["floor"],
            "room_type": r["room_type"],
            "reason": "同房型同楼层" if (r["room_type"] == room["room_type"] and r["floor"] == room["floor"])
            else ("同房型" if r["room_type"] == room["room_type"] else "其他空房"),
        }
        for r in alts[:3]
    ]

    next_step = {
        "dirty": "请客房调度安排清扫，清扫完成后仍需查房才能入住",
        "cleaning": "等待客房部提交「已清扫」，随后质检/领班查房",
        "clean": "请质检/领班立即查房（查房通过后系统才允许入住）",
        "inspecting": "等待查房结论，超时可升级给当班主管",
        "occupied": "该房在住，请选择其他房间",
        "blocked": "维修完成前不参与分配，请选择其他房间",
    }.get(state, "请人工核实房态")

    return {
        "allowed": False,
        "room_no": room_no,
        "room": decorate(room),
        "reason": why,
        "state_label": st["label"],
        "wait_min": eta,
        "next_step": next_step,
        "alternatives": alternatives,
        "owner": {"clean": "质检/领班", "inspecting": "质检/领班", "dirty": "客房调度", "cleaning": "客房部"}.get(state, "前台"),
    }


def record_intervention(room_no: str, kind: str, attempted_state: str, detail: str, actor: str) -> None:
    db.exec_write(
        "INSERT INTO interventions(room_no, kind, attempted_state, detail, actor, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (room_no, kind, attempted_state, detail, actor, db.now_str()),
    )
