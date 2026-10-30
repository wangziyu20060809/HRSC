# 酒店房态管理 · 员工问答入口（阶段 2）

FastAPI 异步后端 + 原生 HTML/JS 单页前端。检索复用阶段 1 的混合检索核心（BM25 + FAISS + RRF），新增 SSE 流式问答、SQLite 会话持久化、引用条款展示。

## 快速开始

```bash
cd src/hotel-assistant

# 1. 安装依赖
pip install -r requirements.txt

# 2. 入库制度文档（生成 rag_index/）
python ingest.py

# 3. 启动服务
python -m uvicorn app:app --host 127.0.0.1 --port 8000

# 4. 浏览器打开
#    http://127.0.0.1:8000
```

**未配置 LLM 密钥时**，系统自动降级为「条款摘要」流式输出（前端标题栏显示"检索摘要模式"），功能完整可用。配置后即为真实 AI 回答：

```bash
set LLM_BASE_URL=https://api.deepseek.com/v1
set LLM_API_KEY=你的密钥
set LLM_MODEL=deepseek-chat
```

## 接口

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/chat` | POST | `{session_id, question}` → SSE：status → citations → token… → done |
| `/sessions` | POST/GET | 新建 / 列出会话 |
| `/sessions/{sid}/messages` | GET | 完整历史（含引用） |
| `/healthz` | GET | 健康检查，含 llm_ready |

错误统一 `{"code":…,"message":"中文","detail":null}`；错误码表见接口设计（40001 会话不存在 / 40002 问题非法 / 40404 未入库 / 42901 并发 / 50001 LLM 降级 / 50002 检索异常）。

## 文件说明

| 文件 | 职责 |
| --- | --- |
| `app.py` | FastAPI 入口、SSE 生成器、统一错误、并发锁 |
| `db.py` | SQLite 会话与消息（最近 6 轮上下文、历史恢复） |
| `rag.py` | 加载 FAISS 索引，复用阶段 1 `HybridRetriever` |
| `llm_stream.py` | 流式 LLM（OpenAI 兼容 stream=true）、降级摘要、上下文组装 |
| `ingest.py` | 制度文档切片向量化入库 |
| `static/index.html` | 单页聊天界面（打字机、检索状态、引用卡、错误重试） |
| `data/客房管理制度.md` | 示例制度语料（12 条，v1.2） |

## 验收路径（5 分钟）

1. 打开页面 → 自动创建会话，显示「正在检索制度…」→ 逐字回答 → 底部可展开引用卡；
2. 问「维修房解除封锁需要什么证据」→ 应命中第七条/第八条；
3. 同会话追问「那照片要保留多久」→ 验证历史上下文；
4. 刷新页面 → 历史消息与引用完整恢复；
5. 输入空问题 / 伪造 session_id → 返回对应中文错误码。
