# -*- coding: utf-8 -*-
"""api/rooms.py — 房态看板、房态迁移、入住闸门、概览指标"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import db, security
from core.errors import ApiError
from domain import metrics
from domain.state_machine import (
    STATES,
    apply,
    checkin_gate,
    decorate,
    record_intervention,
    sla_thresholds,
)

router = APIRouter(prefix="/api", tags=["rooms"])


def _rows(state: str = "", floor: int | None = None) -> list[dict]:
    sql = "SELECT * FROM rooms WHERE 1=1"
    params: list = []
    if state:
        sql += " AND state=?"
        params.append(state)
    if floor:
        sql += " AND floor=?"
        params.append(floor)
    sql += " ORDER BY room_no"
    return [decorate(r) for r in db.rows(sql, params)]


@router.get("/rooms")
def list_rooms(
    state: str = Query("", description="房态筛选"),
    floor: int | None = Query(None),
    user: dict = Depends(security.require_login),
):
    rooms = _rows(state, floor)
    return {
        "code": 0,
        "rooms": rooms,
        "counts": metrics.room_counts(),
        "states": [
            {"key": k, "label": v["label"], "color": v["color"], "sellable": v["sellable"]}
            for k, v in STATES.items()
        ],
        "limits": sla_thresholds(),
        "server_time": db.now_str(),
    }


@router.get("/rooms/{room_no}")
def room_detail(room_no: str, user: dict = Depends(security.require_login)):
    room = db.row("SELECT * FROM rooms WHERE room_no=?", (room_no,))
    if not room:
        raise ApiError(40002, f"房间 {room_no} 不存在")
    events = db.rows(
        "SELECT from_state, to_state, actor, role, reason, created_at FROM room_events "
        "WHERE room_no=? ORDER BY id DESC LIMIT 12",
        (room_no,),
    )
    for e in events:
        e["from_label"] = STATES.get(e["from_state"], {}).get("label", e["from_state"])
        e["to_label"] = STATES.get(e["to_state"], {}).get("label", e["to_state"])
    return {"code": 0, "room": decorate(room), "events": events, "gate": checkin_gate(room_no)}


class TransitionBody(BaseModel):
    action: str
    reason: str = ""
    checklist: dict[str, bool] | None = None
    expected_state: str = ""


@router.post("/rooms/{room_no}/transition")
def transition(room_no: str, body: TransitionBody, user: dict = Depends(security.require_login)):
    result = apply(
        room_no,
        body.action,
        user["display"],
        user["role"],
        reason=body.reason,
        payload={"checklist": body.checklist or {}, "expected_state": body.expected_state},
        source="ui",
    )
    return {"code": 0, **result}


class CheckinBody(BaseModel):
    guest_name: str
    nights: int = 1


@router.post("/rooms/{room_no}/checkin")
def checkin(room_no: str, body: CheckinBody, user: dict = Depends(security.require_login)):
    """入住闸门：不可售一律拦下并留痕，这就是「房态错误」指标的数据来源"""
    gate = checkin_gate(room_no)
    if not gate["allowed"]:
        record_intervention(
            room_no, "premature_checkin", gate["room"]["state"],
            f"{user['display']} 尝试入住被拦截：{gate['reason']}", user["username"],
        )
        raise ApiError(40003, f"{room_no} 不能入住：{gate['reason']}", detail=gate["next_step"])

    result = apply(
        room_no, "check_in", user["display"], user["role"],
        payload={"guest_name": body.guest_name, "nights": body.nights}, source="ui",
    )
    db.exec_write(
        "INSERT INTO checkins(room_no, guest_name, nights, operator, created_at) VALUES(?,?,?,?,?)",
        (room_no, body.guest_name.strip(), body.nights, user["username"], db.now_str()),
    )
    return {"code": 0, **result, "guest_name": body.guest_name.strip(), "nights": body.nights}


@router.get("/checkin/gate")
def gate(room_no: str = Query(...), user: dict = Depends(security.require_login)):
    return {"code": 0, **checkin_gate(room_no)}


@router.get("/dashboard")
def dashboard(user: dict = Depends(security.require_login)):
    o = metrics.overview()
    o["series"] = metrics.daily_series(7)
    o["server_time"] = db.now_str()
    return {"code": 0, **o}
