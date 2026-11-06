# -*- coding: utf-8 -*-
"""agent/runtime.py — Agent 运行时

结构是「三段式」，也是这一版的工程重点：

1. **预取（deterministic grounding）**：先用确定性代码把可能要用的事实查出来——
   问句里的房号 → 查房态；问库存 → 查可售；问指标 → 查指标；问规则 → 检索制度。
   把这些作为【当班数据】【可用制度片段】塞进系统消息。
2. **生成（LLM）**：模型只负责判断还缺什么（可继续 function calling）和把结论写成员工能读懂的话。
3. **校验（guardrail）**：引用了不存在的文档、指标数字与工具返回不一致、提到没查过的房号——
   任一条命中就判定不合格，改用规则答案，并在返回里标注 mode=guarded。

宁可回答得笨一点，也不能让前台拿着编造的条款去跟客人解释。
"""

from __future__ import annotations

import json
import re
import time

import httpx

import config
from agent import tools
from agent.prompts import system_prompt
from core import db
from kb import store as kb_store

MAX_STEPS = 4
MIN_KB_BM25 = 1.2

ROOM_NO_RE = re.compile(r"(?<!\d)(\d{3,4})(?!\d)")
DOC_TITLE_RE = re.compile(r"《([^》]{2,40})》")
QUOTED_RE = re.compile(r"[「『“\"][^」』”\"]{0,60}[」』”\"]")

ROOM_TYPE_WORDS = (("大床", "大床房"), ("双床", "双床房"), ("家庭", "家庭房"), ("套房", "套房"))

# 明确要求"动手"的说法 → 对应的提案工具（AI 只能提案，不能直接改）
ACTION_HINTS = (
    ("start_inspection", ("发起查房", "安排查房", "开始查房", "催查房", "去查房")),
    ("pass_inspection", ("判定通过", "置为可售", "标记可售", "设为可售", "查房通过")),
    ("block", ("报修", "停用", "转维修")),
    ("check_in", ("办入住", "开房", "办理入住")),
)
IMPERATIVE = ("帮我", "给我", "替我", "现在", "马上", "立即", "直接", "麻烦", "去")


def _action_intent(msg: str) -> str:
    """识别"要求执行某个动作"的指令；单纯问规则不算"""
    if not any(k in msg for k in IMPERATIVE):
        return ""
    for action, kws in ACTION_HINTS:
        if any(k in msg for k in kws):
            return action
    return ""


# ---------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------
def new_session(user: dict, title: str = "") -> int:
    return db.exec_write(
        "INSERT INTO agent_sessions(username, role, title, created_at) VALUES(?,?,?,?)",
        (user["username"], user["role"], title or "值班咨询", db.now_str()),
    )


def _history(session_id: int, limit: int = 6) -> list[dict]:
    rows = db.rows(
        "SELECT role, content FROM agent_messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _save(session_id: int, role: str, content: str, trace=None, citations=None, latency: int = 0) -> None:
    db.exec_write(
        "INSERT INTO agent_messages(session_id, role, content, trace, citations, latency_ms, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            session_id, role, content,
            json.dumps(trace or [], ensure_ascii=False),
            json.dumps(citations or [], ensure_ascii=False),
            latency, db.now_str(),
        ),
    )


# ---------------------------------------------------------------------
# 意图识别（规则模式与预取共用同一套判据）
# ---------------------------------------------------------------------
def _intent(msg: str) -> dict:
    return {
        "room_no": (ROOM_NO_RE.search(msg).group(1) if ROOM_NO_RE.search(msg) else ""),
        "rule": any(k in msg for k in ("为什么", "规则", "制度", "标准", "口径", "怎么算", "凭什么", "依据",
                                       "流程", "能不能", "是否", "等于", "区别", "算不算")),
        "metric": any(k in msg for k in ("指标", "数据", "多少", "时效", "拦截", "本周", "今天", "统计", "平均")),
        "shift": any(k in msg for k in ("交接", "交班", "班次", "摘要", "汇总")),
        "inspect": any(k in msg for k in ("查房", "待查", "超时")),
        "avail": any(k in msg for k in ("可售", "空房", "有房", "能入住", "可以入住", "还有", "分配", "安排",
                                        "大床", "双床", "家庭房", "套房", "房吗", "房间吗", "办入住")),
        "block": any(k in msg for k in ("维修", "报修", "坏了")),
        "room_type": next((full for kw, full in ROOM_TYPE_WORDS if kw in msg), ""),
    }


# ---------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------
def chat(user: dict, message: str, session_id: int | None = None) -> dict:
    message = (message or "").strip()
    if not message:
        return {"code": 40001, "message": "问题不能为空"}
    if len(message) > 500:
        return {"code": 40001, "message": "问题过长（上限 500 字）"}

    sid = session_id or new_session(user, message[:20])
    _save(sid, "user", message)

    started = time.time()
    intent = _intent(message)
    pre = _pre_retrieve(message)
    ctx, facts, pre_trace = _pre_fetch(user, sid, message, intent)

    mode, note = "llm", ""
    if config.llm_ready() and db.get_setting("agent_enabled", "1") == "1":
        try:
            answer, trace, citations, facts = _llm_loop(user, sid, message, pre, ctx, facts, pre_trace)
            ok, why = _validate(answer, facts, pre, trace)
            if not ok:
                fb_answer, fb_trace, fb_cites = _fallback(user, sid, message, intent)
                answer = fb_answer
                citations = _dedupe_citations(fb_cites + citations)
                trace += fb_trace
                mode = "guarded"
                note = f"模型输出未通过依据校验（{why}），已改用规则答案"
        except Exception as exc:  # noqa: BLE001
            mode, note = "fallback", f"模型调用失败（{str(exc)[:80]}），已降级为规则模式"
            answer, trace, citations = _fallback(user, sid, message, intent)
    else:
        mode, note = "fallback", "未配置模型密钥，使用规则模式"
        answer, trace, citations = _fallback(user, sid, message, intent)

    # 员工明确要求"动手"时，必须真的生成待确认动作，不能只在嘴上答应
    act = _action_intent(message)
    if act and not any(t.get("write") for t in trace):
        made = _force_action(user, sid, act, intent, message)
        if made:
            trace.append(made["trace"])
            answer = made["answer"]
            mode = "guarded" if mode == "llm" else mode
            note = "模型只给了说法、没有生成动作，已按你的指令直接生成待确认动作"

    answer = _clean_answer(answer)
    latency = int((time.time() - started) * 1000)
    _save(sid, "assistant", answer, trace, citations, latency)

    pending = db.rows(
        "SELECT id, tool, summary FROM agent_actions WHERE session_id=? AND status='pending' ORDER BY id DESC",
        (sid,),
    )
    actions, seen = [], set()
    for p in pending:
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        actions.append({"id": p["id"], "tool": p["tool"], "summary": p["summary"]})

    return {
        "code": 0,
        "session_id": sid,
        "answer": answer,
        "mode": mode,
        "note": note,
        "trace": trace,
        "citations": citations,
        "actions": actions[:4],
        "latency_ms": latency,
    }


# ---------------------------------------------------------------------
# 预取：确定性查事实，减少模型自由发挥的空间
# ---------------------------------------------------------------------
def _pre_retrieve(message: str, k: int = 3) -> list[dict]:
    try:
        hits = kb_store.search(message, top_k=k)
    except Exception:  # noqa: BLE001
        return []
    return [h for h in hits if h["bm25"] >= MIN_KB_BM25][:3]


def _pre_fetch(user: dict, sid: int, message: str, intent: dict):
    facts: dict = {}
    trace: list[dict] = []
    lines: list[str] = []

    def run(name: str, args: dict) -> dict:
        t0 = time.time()
        out = tools.call(name, args, user, sid)
        trace.append({"tool": name, "args": args, "brief": _brief(name, out),
                      "ms": int((time.time() - t0) * 1000), "write": tools.is_write(name), "prefetch": True})
        _collect_facts(name, out, facts)
        return out

    if intent["room_no"]:
        r = run("get_room", {"room_no": intent["room_no"]})
        if "error" not in r:
            lines.append(
                f"- 房间 {r['room_no']}：{r['state_label']}，已保持 {r['age_min']} 分钟"
                + ("（已超时）" if r["overdue"] else "")
                + f"；能否入住：{'能' if r['can_checkin'] else '不能'}（{r['checkin_reason']}）"
                + (f"；下一步：{r['next_step']}" if r.get("next_step") else "")
                + (f"；可替代房：{'、'.join(r['alternatives'][:3])}" if r["alternatives"] else "")
                + (f"；在住客人：{r['guest_name']} {r['nights']} 晚" if r["guest_name"] else "")
            )

    if intent["avail"] or intent["room_no"] and intent["avail"]:
        a = run("find_available_rooms", {"room_type": intent["room_type"], "limit": 6})
        lines.append(
            f"- 可售房（{intent['room_type'] or '全部房型'}）：{a['count']} 间"
            + ("：" + "、".join(f"{r['room_no']}({r['room_type']})" for r in a["rooms"]) if a["rooms"] else "（无）")
        )

    if intent["metric"] or intent["shift"]:
        m = run("get_metrics", {})
        lines.append(
            f"- 指标：可售 {m['sellable']} 间（{m['sellable_rate_pct']}%）、待查房 {m['counts'].get('clean', 0)} 间、"
            f"查房中 {m['counts'].get('inspecting', 0)} 间、维修 {m['counts'].get('blocked', 0)} 间、"
            f"在住 {m['counts'].get('occupied', 0)} 间；超时 {m['overdue']['total']} 间；"
            f"近 7 天平均「已清扫→可售」{m['avg_clean_to_ready_min']} 分钟（P90 {m['p90_clean_to_ready_min']}，样本 {m['samples_7d']}）；"
            f"本周拦截 {m['blocked_week']} 次、今日 {m['blocked_today']} 次（基线 24 次/周，目标 5 次/周）；"
            f"今日入住 {m['checkins_today']} 单。"
        )

    if intent["inspect"]:
        q = run("list_pending_inspections", {"overdue_only": False})
        rooms = "、".join(f"{r['room_no']}({r['state_label']},{r['wait_min']}分{'/超时' if r['overdue'] else ''})"
                          for r in q["rooms"][:6])
        lines.append(f"- 待查房 {q['count']} 间：{rooms or '无'}；阈值：已清扫后 {q['limit_clean_wait_min']} 分钟内开始查房。")

    if intent["shift"]:
        s = tools.call("get_shift_summary", {}, user, sid)
        facts["shift"] = {"waiting": len(s.get("waiting_inspection", [])), "overdue": s.get("overdue_count")}
        lines.append(f"- 交接摘要：{s.get('handover_text', '')}")

    if intent["block"]:
        blocked = db.rows("SELECT room_no, block_reason FROM rooms WHERE state='blocked'")
        facts["blocked"] = [r["room_no"] for r in blocked]
        lines.append("- 维修中：" + ("、".join(f"{r['room_no']}({r['block_reason'] or '待补原因'})" for r in blocked) or "无"))

    text = "【当班数据（本轮已查询，可直接引用，不得改写数字）】\n" + "\n".join(lines) + "\n" if lines else ""
    return text, facts, trace


def _force_action(user: dict, sid: int, act: str, intent: dict, message: str) -> dict | None:
    """员工明确要求执行动作、但模型没生成提案时，由运行时按指令补齐（仍然是提案，不是直接改）"""
    room_no = intent["room_no"]
    if not room_no:
        return None
    if act == "start_inspection":
        name, args = "propose_start_inspection", {"room_no": room_no}
    elif act == "pass_inspection":
        name, args = "propose_mark_ready", {"room_no": room_no}
    elif act == "block":
        name, args = "propose_block_room", {"room_no": room_no, "reason": f"现场报修：{message[:40]}"}
    elif act == "check_in":
        m = re.search(r"客人([\u4e00-\u9fa5]{2,4})", message)
        name, args = "propose_checkin", {"room_no": room_no, "guest_name": m.group(1) if m else "待补姓名", "nights": 1}
    else:
        return None

    t0 = time.time()
    out = tools.call(name, args, user, sid)
    entry = {"tool": name, "args": args, "brief": _brief(name, out),
             "ms": int((time.time() - t0) * 1000), "write": True, "forced": True}
    if out.get("status") == "pending_confirmation":
        text = f"已生成待确认动作：{out['summary']}。确认后才会执行，你可以在下面点「确认执行」。"
    else:
        text = out.get("message") or out.get("error") or "这个动作没能生成，请核对房号与当前房态。"
    return {"trace": entry, "answer": text}


def _kb_block(hits: list[dict]) -> str:
    if not hits:
        return "【可用制度片段】本轮没有检索到相关制度。涉及规则时直接说「制度里没有对应口径」，不要引用任何文档名。\n"
    lines = ["【可用制度片段】回答制度问题时只能引用以下片段，引用格式必须是「《文档名》第N段」，不得出现其他文档名："]
    for i, h in enumerate(hits, 1):
        lines.append(f"[{i}] {h['ref']}：{h['text'][:220]}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------
# LLM：function calling 循环
# ---------------------------------------------------------------------
def _post(messages: list[dict]) -> dict:
    allow_write = db.get_setting("agent_allow_write_tools", "1") == "1"
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "tools": tools.schemas(allow_write),
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 700,
    }
    with httpx.Client(timeout=config.LLM_TIMEOUT) as client:
        r = client.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        return r.json()


def _llm_loop(user: dict, session_id: int, message: str, pre: list[dict], ctx: str,
              facts: dict, pre_trace: list[dict]):
    system = system_prompt() + "\n\n" + _kb_block(pre) + ("\n" + ctx if ctx else "")
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += _history(session_id, 6)[:-1]
    messages.append({"role": "user", "content": message})

    trace: list[dict] = list(pre_trace)
    citations: list[dict] = _kb_citations_from(pre)
    answer = ""

    for _step in range(MAX_STEPS):
        data = _post(messages)
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = (msg.get("content") or "").strip()
            break
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for tc in calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t0 = time.time()
            result = tools.call(name, args, user, session_id)
            trace.append({"tool": name, "args": args, "brief": _brief(name, result),
                          "ms": int((time.time() - t0) * 1000), "write": tools.is_write(name)})
            _collect_facts(name, result, facts)
            if name == "search_knowledge":
                citations += _kb_citations_from(result.get("hits", []))
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps(result, ensure_ascii=False)[:2400]})

    if not answer:
        answer = _compose_from_trace(trace) or "我没有查到能支撑结论的数据，请换一种问法或直接看房态看板。"
    return answer, trace, _dedupe_citations(citations), facts


def _collect_facts(name: str, result: dict, facts: dict) -> None:
    if not isinstance(result, dict) or "error" in result:
        return
    if name == "get_metrics":
        facts["metrics"] = {
            "sellable": result.get("sellable"),
            "clean": result.get("counts", {}).get("clean"),
            "overdue": result.get("overdue", {}).get("total"),
            "blocked_week": result.get("blocked_week"),
            "blocked_today": result.get("blocked_today"),
            "avg": result.get("avg_clean_to_ready_min"),
            "checkins_today": result.get("checkins_today"),
        }
    elif name == "get_room":
        facts.setdefault("rooms", {})[result["room_no"]] = {
            "state": result["state_label"], "can_checkin": result["can_checkin"], "age": result["age_min"],
        }
    elif name == "find_available_rooms":
        facts["available"] = [r["room_no"] for r in result.get("rooms", [])]
    elif name == "list_pending_inspections":
        facts["pending"] = [r["room_no"] for r in result.get("rooms", [])]
    elif name == "list_rooms":
        facts["rooms_listed"] = [r["room_no"] for r in result.get("rooms", [])]


def _brief(name: str, result: dict) -> str:
    if not isinstance(result, dict):
        return "已执行"
    if name == "search_knowledge":
        return f"命中 {len(result.get('hits', []))} 段制度"
    if name == "find_available_rooms":
        rooms = result.get("rooms", [])
        return f"可售 {result.get('count', 0)} 间" + ("：" + "、".join(r["room_no"] for r in rooms[:5]) if rooms else "")
    if name == "list_pending_inspections":
        return f"待查房 {result.get('count', 0)} 间，超时 {sum(1 for r in result.get('rooms', []) if r.get('overdue'))} 间"
    if name == "get_room":
        if "error" in result:
            return result["error"]
        return f"{result['room_no']} {result['state_label']}，等待 {result['age_min']} 分，可入住={result['can_checkin']}"
    if name == "get_metrics":
        return f"可售 {result.get('sellable')}，均时 {result.get('avg_clean_to_ready_min')} 分，拦截 {result.get('blocked_week')} 次/周"
    if name == "list_rooms":
        return f"共 {result.get('count')} 间"
    if name == "get_shift_summary":
        return f"待查房 {len(result.get('waiting_inspection', []))}，超时 {result.get('overdue_count')}"
    if tools.is_write(name):
        return result.get("summary") or result.get("message") or result.get("error", "")
    return "已执行"


# ---------------------------------------------------------------------
# 依据校验
# ---------------------------------------------------------------------
def _norm_title(t: str) -> str:
    t = re.sub(r"\s+", "", t or "")
    t = re.sub(r"[·・]?第\d+段$", "", t)
    for suffix in ("——制度", "——操作规范", "——指引", "制度"):
        t = t.replace(suffix, "")
    return t


def _validate(answer: str, facts: dict, pre: list[dict], trace: list[dict] | None = None) -> tuple[bool, str]:
    trace = trace or []
    known = {_norm_title(r["title"]) for r in db.rows("SELECT title FROM kb_docs")}
    known |= {_norm_title(h["doc_title"]) for h in pre}
    for title in DOC_TITLE_RE.findall(answer):
        if _norm_title(title) not in known:
            return False, f"引用了不存在的文档《{title}》"

    # 声称"已经发起/已经办理"但本轮没有生成任何待确认动作 → 这是在骗人
    if re.search(r"已(为|给|帮|替你|按)[^，。；]{0,12}(发起|生成|提交|办理|标记|置为)", answer):
        if not any(t.get("write") for t in trace):
            return False, "声称已执行动作，但本轮没有生成待确认动作"

    m = facts.get("metrics") or {}
    shift = facts.get("shift") or {}
    allowed_map = {
        "拦截": {m.get("blocked_week"), m.get("blocked_today")},
        "可售": {m.get("sellable")} | ({len(facts["available"])} if "available" in facts else set()),
        "待查房": {m.get("clean")} | ({len(facts["pending"])} if "pending" in facts else set()) | {shift.get("waiting")},
        "超时": {m.get("overdue")} | {shift.get("overdue")},
    }
    for kw, unit in (("拦截", "次"), ("可售", "间"), ("待查房", "间"), ("超时", "间")):
        nums = [int(x) for x in re.findall(rf"{kw}[^\d。；]{{0,8}}(\d+)\s*{unit}", answer)]
        if not nums:
            continue
        allowed = {v for v in allowed_map[kw] if v is not None}
        if not allowed:
            return False, f"给出了「{kw}」数字但本轮没有查询对应数据"
        if not set(nums) & allowed:
            return False, f"「{kw}」数字与系统数据不一致（模型写 {nums}，实际 {sorted(allowed)}）"

    body = QUOTED_RE.sub(" ", answer)
    known_rooms = set(facts.get("rooms", {})) | set(facts.get("available", [])) | set(facts.get("pending", []))
    known_rooms |= set(facts.get("rooms_listed", [])) | set(facts.get("blocked", []))
    for no in ROOM_NO_RE.findall(body):
        if db.row("SELECT room_no FROM rooms WHERE room_no=?", (no,)) and no not in known_rooms:
            return False, f"提到房号 {no} 但本轮没有查询该房间"
    return True, ""


# ---------------------------------------------------------------------
# 规则模式
# ---------------------------------------------------------------------
def _fallback(user: dict, session_id: int, message: str, intent: dict | None = None):
    intent = intent or _intent(message)
    trace: list[dict] = []
    citations: list[dict] = []

    def run(name: str, args: dict) -> dict:
        t0 = time.time()
        out = tools.call(name, args, user, session_id)
        trace.append({"tool": name, "args": args, "brief": _brief(name, out),
                      "ms": int((time.time() - t0) * 1000), "write": tools.is_write(name)})
        return out

    room_no = intent["room_no"]

    if room_no and (intent["rule"] or intent["avail"] or intent["metric"] or "这间" in message
                    or "房间" in message or len(message) <= 8):
        room = run("get_room", {"room_no": room_no})
        if "error" in room:
            return room["error"], trace, []
        parts = [
            f"{room['room_no']}（{room['floor']} 楼 {room['room_type']}）现在是「{room['state_label']}」，"
            f"已保持 {room['age_min']} 分钟" + ("，已超时" if room["overdue"] else "") + "。"
        ]
        if room["can_checkin"]:
            parts.append("这间可以办理入住。")
        else:
            parts.append(f"现在不能入住：{room['checkin_reason']}。下一步：{room['next_step']}。")
            if room["alternatives"]:
                parts.append("可替代房间：" + "、".join(room["alternatives"]) + "。")
        if room["guest_name"]:
            parts.append(f"在住客人 {room['guest_name']}，{room['nights']} 晚。")
        if intent["rule"]:
            kb = run("search_knowledge", {"query": message, "top_k": 2})
            citations += _kb_citations_from(kb.get("hits", []))
            if kb.get("hits"):
                parts.append("依据 " + kb["hits"][0]["ref"] + "：" + _clip(kb["hits"][0]["text"], 70))
        return "".join(parts), trace, _dedupe_citations(citations)

    if intent["shift"]:
        s = run("get_shift_summary", {})
        return s["handover_text"] + f"（当前超时 {s['overdue_count']} 间，未完成任务 {s['open_tasks']} 项）", trace, []

    if intent["rule"]:
        kb = run("search_knowledge", {"query": message, "top_k": 3})
        citations += _kb_citations_from(kb.get("hits", []))
        if kb.get("hits"):
            top = _best_hit(kb["hits"])
            return f"依据 {top['ref']}：{_snippet(top['text'])}", trace, _dedupe_citations(citations)
        return "知识库里没有这段口径，建议问质检或查管理制度原文。", trace, []

    if intent["block"]:
        blocked = db.rows("SELECT * FROM rooms WHERE state='blocked'")
        kb = run("search_knowledge", {"query": "报修 维修房 停用 恢复 可售", "top_k": 2})
        citations += _kb_citations_from(kb.get("hits", []))
        rooms = "、".join(f"{r['room_no']}（{r['block_reason'] or '待补原因'}）" for r in blocked) or "无"
        return f"维修中：{rooms}。维修完成后要先转待清扫，再走清扫与查房，不能直接置为可售。", trace, _dedupe_citations(citations)

    if intent["inspect"]:
        q = run("list_pending_inspections", {"overdue_only": False})
        if not q["count"]:
            return "当前没有待查房或查房中的房间。", trace, []
        overdue = [r for r in q["rooms"] if r["overdue"]]
        head = "、".join(f"{r['room_no']}（{r['state_label']}，{r['wait_min']} 分钟）" for r in q["rooms"][:6])
        tail = (f"其中 {len(overdue)} 间已超时：" + "、".join(r["room_no"] for r in overdue) + "。") if overdue else "暂无超时。"
        kb = run("search_knowledge", {"query": "已清扫 多久 开始查房 超时", "top_k": 1})
        citations += _kb_citations_from(kb.get("hits", []))
        return f"待查房 {q['count']} 间：{head}。{tail}标准是已清扫后 {q['limit_clean_wait_min']} 分钟内开始查房。", trace, _dedupe_citations(citations)

    if intent["metric"]:
        o = run("get_metrics", {})
        return (
            f"现在可售 {o['sellable']} 间（{o['sellable_rate_pct']}%），待查房 {o['counts'].get('clean', 0)} 间，"
            f"超时 {o['overdue']['total']} 间。近 7 天平均「已清扫→可售」{o['avg_clean_to_ready_min']} 分钟"
            f"（P90 {o['p90_clean_to_ready_min']} 分钟，样本 {o['samples_7d']} 次），"
            f"本周入住闸门拦截 {o['blocked_week']} 次（基线 24 次/周，目标 5 次/周）。"
        ), trace, []

    if intent["avail"]:
        f = run("find_available_rooms", {"room_type": intent["room_type"], "limit": 6})
        label = intent["room_type"] or "房间"
        if not f["count"]:
            return f"当前没有可售的{label}；已清扫待查房的要先查房通过才能分配。", trace, []
        rooms = "、".join(f"{r['room_no']}（{r['room_type']}）" for r in f["rooms"])
        kb = run("search_knowledge", {"query": "只有可售能办入住 已清扫不等于可售", "top_k": 1})
        citations += _kb_citations_from(kb.get("hits", []))
        return f"当前可售的{label}共 {f['count']} 间：{rooms}。只有可售房能办入住，已清扫待查房的要先查房。", trace, _dedupe_citations(citations)

    o = run("get_metrics", {})
    return (
        f"我可以查房态、待查房队列、可售房、时效指标和制度口径。当前：可售 {o['sellable']} 间、"
        f"待查房 {o['counts'].get('clean', 0)} 间、超时 {o['overdue']['total']} 间、"
        f"本周拦截 {o['blocked_week']} 次。你可以问我「803 能入住吗」「还有大床房吗」「交接班要注意什么」。"
    ), trace, []


# ---------------------------------------------------------------------
# 工具输出 → 引用 / 文案
# ---------------------------------------------------------------------
def _kb_citations_from(hits: list[dict]) -> list[dict]:
    return [
        {
            "type": "kb",
            "ref": h["ref"],
            "doc_title": h["doc_title"],
            "text": _clip(h["text"], 160),
            "score": h.get("score", 0),
        }
        for h in hits
    ]


def _dedupe_citations(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in items:
        key = (_norm_title(c["doc_title"]), c["text"][:30])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out[:4]


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:n] + ("…" if len(text) > n else "")


def _snippet(text: str, n: int = 150) -> str:
    """把制度片段压成一句可读的引用，去掉标题行、加粗符号与多余空白"""
    t = re.sub(r"^#+\s.*$", " ", text or "", flags=re.M)
    t = t.replace("**", "").replace("`", "").replace("- ", "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n] + ("…" if len(t) > n else "")


def _best_hit(hits: list[dict]) -> dict:
    for h in hits:
        s = _snippet(h["text"])
        if len(s) > 40 and not s.startswith("适用岗位"):
            return h
    return hits[0]


def _clean_answer(text: str) -> str:
    """去掉模型爱漏的内部细节：工具名、代码块"""
    text = re.sub(r"`[^`]*`", lambda m: "" if any(t in m.group(0) for t in tools.ALL_TOOLS) else m.group(0), text)
    for name in tools.ALL_TOOLS:
        text = text.replace(f"{name}(", "（系统操作）")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _compose_from_trace(trace: list[dict]) -> str:
    if not trace:
        return ""
    return f"{trace[-1]['brief']}。"
