# -*- coding: utf-8 -*-
"""tests/test_domain.py — 状态机与入住闸门（业务内核的回归测试）

运行：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from core import db, seed  # noqa: E402
from domain import metrics  # noqa: E402
from domain.state_machine import STATES, apply, checkin_gate, decorate  # noqa: E402


def set_state(room_no: str, state: str, minutes_ago: int = 0) -> None:
    ts = (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    db.exec_write("UPDATE rooms SET state=?, state_since=? WHERE room_no=?", (state, ts, room_no))


class TestStateMachine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.init(force=True)

    def setUp(self):
        set_state("801", "ready", 30)
        db.exec_write("UPDATE rooms SET guest_name='', nights=0 WHERE room_no='801'")

    # —— 核心口径：已清扫不等于可售 ——
    def test_clean_room_cannot_check_in(self):
        set_state("801", "clean", 5)
        with self.assertRaises(Exception) as ctx:
            apply("801", "check_in", "测试前台", "front", payload={"guest_name": "张三", "nights": 1})
        self.assertIn("已清扫待查房", str(ctx.exception))

    def test_ready_room_can_check_in(self):
        out = apply("801", "check_in", "测试前台", "front", payload={"guest_name": "张三", "nights": 2})
        self.assertEqual(out["to_state"], "occupied")
        room = db.row("SELECT * FROM rooms WHERE room_no='801'")
        self.assertEqual(room["guest_name"], "张三")
        self.assertEqual(room["nights"], 2)

    def test_check_in_requires_guest_name(self):
        with self.assertRaises(Exception):
            apply("801", "check_in", "测试前台", "front", payload={"guest_name": "  "})

    # —— 岗位边界：谁下的结论谁负责 ——
    def test_front_cannot_pass_inspection(self):
        set_state("801", "inspecting", 3)
        with self.assertRaises(Exception) as ctx:
            apply("801", "pass_inspection", "测试前台", "front", payload={"checklist": {}})
        self.assertIn("岗位", str(ctx.exception))

    def test_qa_can_pass_inspection(self):
        set_state("801", "inspecting", 3)
        out = apply("801", "pass_inspection", "测试质检", "qa", payload={"checklist": {}})
        self.assertEqual(out["to_state"], "ready")

    def test_inspection_with_failed_item_is_rejected(self):
        set_state("801", "inspecting", 3)
        with self.assertRaises(Exception):
            apply("801", "pass_inspection", "测试质检", "qa",
                  payload={"checklist": {"bed": True, "bath": False}})

    def test_fail_inspection_requires_reason(self):
        set_state("801", "inspecting", 3)
        with self.assertRaises(Exception):
            apply("801", "fail_inspection", "测试质检", "qa")
        out = apply("801", "fail_inspection", "测试质检", "qa", reason="床单有毛发")
        self.assertEqual(out["to_state"], "cleaning")
        task = db.row("SELECT * FROM tasks WHERE room_no='801' AND kind='cleaning' AND status='open'")
        self.assertIsNotNone(task)
        self.assertEqual(task["priority"], "high")

    # —— 迁移合法性 ——
    def test_illegal_transition_rejected(self):
        set_state("801", "dirty", 5)
        with self.assertRaises(Exception) as ctx:
            apply("801", "pass_inspection", "测试质检", "qa", payload={"checklist": {}})
        self.assertIn("不能执行", str(ctx.exception))

    def test_block_requires_reason_and_leaves_inventory(self):
        with self.assertRaises(Exception):
            apply("801", "block", "测试前台", "front")
        apply("801", "block", "测试前台", "front", reason="空调不制冷")
        gate = checkin_gate("801")
        self.assertFalse(gate["allowed"])
        self.assertIn("维修", gate["reason"])

    def test_blocked_room_returns_dirty_after_unblock(self):
        set_state("801", "blocked", 10)
        out = apply("801", "unblock", "测试客房", "house")
        self.assertEqual(out["to_state"], "dirty")

    def test_expected_state_detects_stale_page(self):
        with self.assertRaises(Exception) as ctx:
            apply("801", "start_cleaning", "测试客房", "house", payload={"expected_state": "clean"})
        self.assertIn("已变化", str(ctx.exception))

    def test_events_are_appended(self):
        set_state("801", "dirty", 4)
        before = db.scalar("SELECT COUNT(*) FROM room_events WHERE room_no='801'")
        apply("801", "start_cleaning", "测试客房", "house")
        after = db.scalar("SELECT COUNT(*) FROM room_events WHERE room_no='801'")
        self.assertEqual(after, before + 1)
        ev = db.row("SELECT * FROM room_events WHERE room_no='801' ORDER BY id DESC LIMIT 1")
        self.assertEqual((ev["from_state"], ev["to_state"]), ("dirty", "cleaning"))


class TestGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.init(force=True)

    def test_clean_gate_offers_alternatives(self):
        set_state("905", "clean", 4)
        gate = checkin_gate("905")
        self.assertFalse(gate["allowed"])
        self.assertLessEqual(len(gate["alternatives"]), 3)
        self.assertTrue(all(a["room_no"] != "905" for a in gate["alternatives"]))
        self.assertIn("查房", gate["next_step"])

    def test_alternatives_prefer_same_room_type(self):
        set_state("803", "clean", 4)  # 大床房
        gate = checkin_gate("803")
        first = gate["alternatives"][0]
        room = db.row("SELECT room_type FROM rooms WHERE room_no=?", (first["room_no"],))
        self.assertEqual(room["room_type"], "大床房")

    def test_occupied_has_no_wait_estimate(self):
        gate = checkin_gate("802")
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["wait_min"], 0)

    def test_decorate_marks_overdue(self):
        set_state("1002", "clean", 40)  # 阈值 12 分钟
        room = decorate(db.row("SELECT * FROM rooms WHERE room_no='1002'"))
        self.assertTrue(room["overdue"])
        self.assertEqual(room["state_label"], "已清扫待查房")
        self.assertFalse(room["sellable"])


class TestMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.init(force=True)

    def test_overview_shape(self):
        o = metrics.overview()
        self.assertEqual(o["total"], 24)
        self.assertGreater(o["samples_7d"], 100)
        self.assertGreater(o["avg_clean_to_ready_min"], 0)
        self.assertGreaterEqual(o["p90_clean_to_ready_min"], o["avg_clean_to_ready_min"])

    def test_durations_are_positive(self):
        d = metrics.clean_to_ready_durations(7)
        self.assertTrue(all(x > 0 for x in d))

    def test_shift_summary_mentions_rule(self):
        s = metrics.shift_summary()
        self.assertIn("已清扫≠可售", s["handover_text"])
        self.assertIsInstance(s["waiting_inspection"], list)


if __name__ == "__main__":
    unittest.main()
