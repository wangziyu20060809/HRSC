# -*- coding: utf-8 -*-
"""config.py — 运行配置（.env 零依赖加载，优先于环境变量默认值）"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """极简 .env 加载：KEY=VALUE，# 开头为注释；已存在的环境变量不覆盖。"""
    path = BASE_DIR / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()

# —— 服务 ——
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8100"))

# —— 大模型（OpenAI 兼容；留空则 Agent 走规则降级规划器）——
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "45"))

# —— 鉴权 ——
JWT_SECRET = os.getenv("JWT_SECRET", "room-status-mvp-dev-secret-change-me")
JWT_TTL = int(os.getenv("JWT_TTL", str(10 * 3600)))

# —— 数据 ——
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "mvp.db")))

# —— 业务阈值（管理端可改 settings，这里是兜底默认）——
SLA_CLEAN_WAIT_MIN = 12   # 已清扫 → 开始查房，超过即超时
SLA_INSPECT_MIN = 15      # 查房中 → 可售，超过即超时
SLA_DIRTY_MIN = 90        # 待清扫 → 清扫中，超过即积压

HOTEL_NAME = os.getenv("HOTEL_NAME", "山海旅居")


def llm_ready() -> bool:
    return bool(LLM_BASE_URL and LLM_API_KEY)
