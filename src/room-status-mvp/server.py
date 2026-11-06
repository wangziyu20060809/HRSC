# -*- coding: utf-8 -*-
"""server.py —— 单端口启动入口（云托管/容器用）

与 `uvicorn app:app` 等价，区别是：
  - 绑定 0.0.0.0，端口读环境变量 PORT（云平台注入），默认 8100
  - 启动前确保 data/ 存在，避免只读文件系统以外的路径问题
本地开发仍可直接用 `python -m uvicorn app:app --port 8100`。
"""
import os
from pathlib import Path

import uvicorn

BASE = Path(__file__).resolve().parent
(BASE / "data").mkdir(exist_ok=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8100"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
