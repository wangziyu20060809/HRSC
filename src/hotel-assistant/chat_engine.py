# -*- coding: utf-8 -*-
"""
chat_engine.py — 共享的流式问答生成器

员工 /chat 与客人 /guest/chat 复用同一套逻辑，差异只在：
  · 会话 channel（staff / guest）
  · 消息 actor（谁在说话）
  · 提示词模板（每次请求实时从 DB 读取，管理员保存即生效）

事件顺序：status(检索中) → citations → token… → done；异常推 error。
LLM 失败自动降级条款摘要（前端体验一致）。
"""

import json
from collections.abc import AsyncGenerator

import db
import llm_stream
import rag
import rules


def sse(event: str, data) -> str:
    """SSE 帧格式化：event + data 两行，JSON 保留中文"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_stream(session_id: str, question: str, actor: str) -> AsyncGenerator[str, None]:
    """
    生成一次问答的完整 SSE 事件流。

    :param session_id: 会话 ID（已在外层校验存在）
    :param question:   已校验非空的问题文本
    :param actor:      提问者标记（guest / staff）
    """

    async def gen():
        # —— 1. 检索 ——
        yield sse("status", {"stage": "retrieving", "text": "正在检索制度…"})
        try:
            hits = rag.search(question, top_k=3)
        except rag.IndexNotReadyError:
            yield sse("error", {"code": 40404, "message": "制度库尚未初始化，请联系管理员先执行入库"})
            return
        except Exception:
            yield sse("error", {"code": 50002, "message": "检索服务异常，请稍后重试"})
            return
        if not hits:
            yield sse("error", {"code": 50002, "message": "未检索到相关条款，请换个问法试试"})
            return

        # —— 2. 引用（文件名 + 版本 + 条款号 + 片段）——
        doc_titles = {h.get("title", "") for h in hits}
        citations = []
        for h in hits:
            citations.append({
                "doc_title": h.get("title") or "客房管理制度",
                "version": h.get("version") or "",
                "clause_no": h.get("clause_no") or f"片段{h['rank'] + 1}",
                "snippet": h["content"][:120],
            })
        yield sse("citations", citations)

        # —— 3. 违规检查（确定性规则）：提问即留痕 ——
        flagged, flag_reason = rules.check_violation(question)

        # —— 4. 提问入库；首轮自动命名会话 ——
        history = db.get_recent_messages(session_id, limit=12)
        db.add_message(session_id, "user", question, actor=actor,
                       flagged=flagged, flag_reason=flag_reason)
        if len(history) == 0:
            db.touch_session(session_id, title=question)

        # —— 5. 生成：提示词实时从 DB 读取（管理员保存即生效）——
        system_prompt = db.get_prompt()
        messages = llm_stream.build_messages(question, hits, history, system_prompt)
        answer_parts: list[str] = []
        degraded = False
        try:
            for delta in llm_stream.stream_chat(messages):
                answer_parts.append(delta)
                yield sse("token", {"text": delta})
        except Exception:
            degraded = True
            yield sse("status", {"stage": "degraded", "code": 50001,
                                 "text": "大模型服务暂不可用，已为你降级为条款摘要"})
            summary = llm_stream.fallback_summary(hits)
            for piece in llm_stream.chunk_text(summary, size=8):
                answer_parts.append(piece)
                yield sse("token", {"text": piece})

        # —— 6. 回答入库（含引用与工具记录，审计可重建）——
        answer = "".join(answer_parts)
        message_id = db.add_message(
            session_id, "assistant", answer, actor="ai", citations=citations,
            tool_calls=[{"tool": "hybrid_search", "top_k": 3, "degraded": degraded}],
        )
        db.touch_session(session_id)
        yield sse("done", {"message_id": message_id, "degraded": degraded})

    return gen()
