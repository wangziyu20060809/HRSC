# -*- coding: utf-8 -*-
"""
llm_stream.py — 流式 LLM 调用 + 降级摘要

【核心模块 · 全阶段复用】
  阶段 1 的 chat_llm() 是非流式版本；本文件是其流式扩展：
    · stream_chat(messages) —— OpenAI 兼容 stream=true，逐 delta 产出文本
    · fallback_summary()    —— 无密钥或调用失败时的降级摘要（沿用阶段 1 策略）
  供应商仍全部由环境变量配置，业务层零改动即可切换。
"""

import json
import os
from collections.abc import Generator

# 供应商配置（与阶段 1 同名环境变量，保持一致）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# 系统提示词：与阶段 1 同源的护栏约束，酒店房态场景措辞
SYSTEM_PROMPT = (
    "你是酒店的房态管理制度问答助手。回答必须：1) 只基于提供的制度条款，"
    "不要编造数字或条款；2) 引用条款号作为出处；"
    "3) 条款中没有依据时明确回答\"当前制度库中未找到依据\"；"
    "4) 不出现员工姓名、工号、手机号、客人身份等个人信息；5) 回答控制在 200 字以内。"
)


def llm_ready() -> bool:
    """是否具备真实 LLM 调用条件"""
    return bool(LLM_BASE_URL and LLM_API_KEY)


def stream_chat(messages: list[dict]) -> Generator[str, None, None]:
    """
    流式调用 OpenAI 兼容 LLM，逐段 yield 文本增量。

    :param messages: 完整消息列表（system + 历史 + 当前问题），由调用方组装
    :raises RuntimeError: 未配置供应商；httpx 异常向上抛，由 app 层转降级
    """
    if not llm_ready():
        raise RuntimeError("未配置 LLM_BASE_URL / LLM_API_KEY")

    import httpx

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "stream": True,  # 关键：开启 SSE 流式返回
    }
    # with stream 保证连接随生成器关闭，避免长连接泄漏
    with httpx.stream(
        "POST",
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json=payload,
        timeout=60,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            # OpenAI 兼容 SSE 行格式：data: {...}，结束标记 data: [DONE]
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue  # 心跳/注释行跳过
            if delta:
                yield delta


def fallback_summary(hits: list[dict]) -> str:
    """
    降级摘要：把 top3 条款组织成可读文本。
    触发场景：未配置密钥 / LLM 网络失败 / 供应商 5xx。
    与阶段 1 的 _fallback_answer 同策略，但输出为完整字符串便于流式切片。
    """
    parts = ["大模型服务暂不可用，以下为检索到的相关制度条款原文："]
    for h in hits:
        clause = h.get("clause_no") or f"片段{h['rank'] + 1}"
        parts.append(f"\n【{clause}】{h['content']}")
    return "\n".join(parts)


def chunk_text(text: str, size: int = 8) -> Generator[str, None, None]:
    """
    把完整文本切成小片段，供降级路径"模拟流式"输出。
    这样前端打字机效果在降级时也能工作，体验一致。
    """
    for i in range(0, len(text), size):
        yield text[i : i + size]


def build_messages(question: str, hits: list[dict], history: list[dict],
                   system_prompt: str | None = None) -> list[dict]:
    """
    组装发给 LLM 的完整消息列表：
      system（护栏） + 历史（最近 6 轮） + 当前问题（含检索条款上下文）

    system_prompt 传 None 时使用模块内默认模板；
    管理后台保存的模板由调用方（app 层）从 DB 读出后传入——保存即生效。
    历史消息只取 user/assistant 两种角色，tool 消息不进上下文。
    """
    context = "\n\n".join(
        f"【{h.get('clause_no') or f'片段{h['rank'] + 1}'}】{h['content']}" for h in hits
    )
    current = (
        f"=== 检索到的制度条款 ===\n{context}\n\n"
        f"=== 员工问题 ===\n{question}\n\n"
        f"请只依据上述条款回答，并注明条款号。"
    )
    messages = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
    for m in history:
        if m["role"] in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": current})
    return messages
