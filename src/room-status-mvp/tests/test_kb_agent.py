# -*- coding: utf-8 -*-
"""tests/test_kb_agent.py — 知识库检索与 Agent 规则模式（不依赖外部模型）

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"
config.LLM_BASE_URL = ""
config.LLM_API_KEY = ""   # 强制走规则模式，测试不依赖外网

from agent import runtime, tools  # noqa: E402
from core import db, seed  # noqa: E402
from kb import store as kb  # noqa: E402

USER = {"id": 2, "username": "front", "display": "林亦舟", "role": "front", "post": "前台", "role_label": "前台"}


class TestKnowledgeBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.init(force=True)

    def test_docs_seeded(self):
        self.assertGreaterEqual(kb.stats()["docs"], 5)
        self.assertGreater(kb.stats()["chunks"], 10)

    def test_clean_is_not_sellable_hit(self):
        hits = kb.search("已清扫能不能办入住", top_k=3)
        self.assertTrue(hits)
        joined = " ".join(h["text"] for h in hits)
        self.assertIn("查房", joined)

    def test_chunking_respects_size(self):
        text = "段落一。" * 120 + "\n\n" + "段落二。" * 120
        chunks = kb.chunk_text(text)
        self.assertTrue(all(len(c) <= kb.MAX_CHARS for c in chunks))
        self.assertGreaterEqual(len(chunks), 2)

    def test_upsert_and_delete(self):
        out = kb.upsert_doc("测试制度·临时", "# 测试制度\n\n这是一段临时制度，用于验证增删。", "制度")
        self.assertGreater(out["chunks"], 0)
        hits = kb.search("临时制度", top_k=2)
        self.assertTrue(any("临时" in h["text"] for h in hits))
        kb.delete_doc(out["id"])
        self.assertIsNone(db.row("SELECT id FROM kb_docs WHERE id=?", (out["id"],)))

    def test_reindex_is_idempotent(self):
        first = kb.reindex_all()
        second = kb.reindex_all()
        self.assertEqual(first, second)


class TestTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.init(force=True)

    def test_get_room_reports_gate(self):
        db.exec_write("UPDATE rooms SET state='clean', state_since=? WHERE room_no='803'",
                      (db.now_str(),))
        r = tools.call("get_room", {"room_no": "803"}, USER, 0)
        self.assertFalse(r["can_checkin"])
        self.assertIn("查房", r["checkin_reason"])
        self.assertTrue(r["alternatives"])

    def test_find_available_excludes_clean(self):
        r = tools.call("find_available_rooms", {}, USER, 0)
        for room in r["rooms"]:
            state = db.row("SELECT state FROM rooms WHERE room_no=?", (room["room_no"],))
            self.assertEqual(state["state"], "ready")

    def test_checkin_proposal_blocked_for_clean_room(self):
        db.exec_write("UPDATE rooms SET state='clean', state_since=? WHERE room_no='905'", (db.now_str(),))
        out = tools.call("propose_checkin", {"room_no": "905", "guest_name": "张三"}, USER, 0)
        self.assertTrue(out.get("blocked"))
        self.assertIn("不能入住", out["message"])

    def test_write_tool_creates_pending_action(self):
        db.exec_write("UPDATE rooms SET state='clean', state_since=? WHERE room_no='1002'", (db.now_str(),))
        out = tools.call("propose_start_inspection", {"room_no": "1002"}, USER, 0)
        self.assertEqual(out["status"], "pending_confirmation")
        act = db.row("SELECT * FROM agent_actions WHERE id=?", (out["action_id"],))
        self.assertEqual(act["status"], "pending")
        # 提案不影响房态
        self.assertEqual(db.row("SELECT state FROM rooms WHERE room_no='1002'")["state"], "clean")

    def test_reject_action(self):
        db.exec_write("UPDATE rooms SET state='clean', state_since=? WHERE room_no='1003'", (db.now_str(),))
        out = tools.call("propose_start_inspection", {"room_no": "1003"}, USER, 0)
        res = tools.reject_action(out["action_id"], USER)
        self.assertEqual(res["code"], 0)
        self.assertEqual(db.row("SELECT status FROM agent_actions WHERE id=?", (out["action_id"],))["status"], "rejected")


class TestAgentFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.init(force=True)

    def test_room_question(self):
        db.exec_write("UPDATE rooms SET state='clean', state_since=? WHERE room_no='803'", (db.now_str(),))
        out = runtime.chat(USER, "803 能入住吗")
        self.assertEqual(out["mode"], "fallback")
        self.assertIn("不能入住", out["answer"])
        self.assertTrue(any(t["tool"] == "get_room" for t in out["trace"]))

    def test_availability_question(self):
        out = runtime.chat(USER, "还有大床房吗")
        self.assertIn("可售", out["answer"])
        self.assertTrue(any(t["tool"] == "find_available_rooms" for t in out["trace"]))

    def test_rule_question_has_citation(self):
        out = runtime.chat(USER, "已清扫能不能办入住")
        self.assertTrue(out["citations"])
        self.assertTrue(out["citations"][0]["doc_title"])
        self.assertIn("第", out["citations"][0]["ref"])

    def test_metric_question_numbers_match_db(self):
        out = runtime.chat(USER, "本周拦截几次")
        blocked = db.scalar("SELECT COUNT(*) FROM interventions WHERE created_at>=?", (db.now_str()[:10] + " 00:00:00",))
        self.assertIn(str(blocked), out["answer"])

    def test_action_intent_creates_proposal(self):
        db.exec_write("UPDATE rooms SET state='clean', state_since=? WHERE room_no='1104'", (db.now_str(),))
        qa = {"id": 4, "username": "qa", "display": "傅景", "role": "qa", "post": "服务质量", "role_label": "质检"}
        out = runtime.chat(qa, "帮我给 1104 发起查房")
        self.assertTrue(out["actions"], "应生成待确认动作")
        self.assertEqual(out["actions"][0]["tool"], "start_inspection")

    def test_session_persists_messages(self):
        out = runtime.chat(USER, "现在有多少可售房")
        sid = out["session_id"]
        n = db.scalar("SELECT COUNT(*) FROM agent_messages WHERE session_id=?", (sid,))
        self.assertEqual(n, 2)


class TestValidation(unittest.TestCase):
    """护栏本身的测试：宁可答得笨，也不能编"""

    def test_fake_doc_title_rejected(self):
        bad = "依据《山海旅居房态闸门规则》第2.1条，房间必须查房。"
        ok, why = runtime._validate(bad, {}, [])
        self.assertFalse(ok)
        self.assertIn("不存在", why)

    def test_existing_doc_title_accepted(self):
        good = "依据《入住办理与可售闸门》第2段，只有可售才能办入住。"
        ok, _ = runtime._validate(good, {}, [])
        self.assertTrue(ok)

    def test_metric_number_mismatch_rejected(self):
        ok, why = runtime._validate("本周拦截 3 次。", {"metrics": {"blocked_week": 19}}, [])
        self.assertFalse(ok)
        self.assertIn("不一致", why)

    def test_unqueried_room_rejected(self):
        ok, why = runtime._validate("803 现在可以入住。", {}, [])
        self.assertFalse(ok)
        self.assertIn("没有查询", why)

    def test_quoted_example_not_flagged(self):
        ok, _ = runtime._validate("你可以问我「803 能入住吗」这类问题。", {}, [])
        self.assertTrue(ok)

    def test_claim_without_action_rejected(self):
        ok, why = runtime._validate("已为 1105 发起查房。", {}, [])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
