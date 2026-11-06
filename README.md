# HRSC · 酒店房态与入住协同

> Hotel Room-Status & Check-in Collaboration — 山海旅居「酒店房态与入住协同」FDE 项目全套交付物：业务发现、行业分析、流程图、设计方案与报价单，以及一个可直接运行的协同 Demo。

## 这是什么

围绕酒店「已清扫 / 已查房 / 可售」三态时序脱节问题（客房标了已清扫、前台以为能入住、查房还没完成），完成从业务挖掘到方案报价的完整 FDE（Forward Deployed Engineering）交付：

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| 业务挖掘 | [`docs/业务挖掘-发现报告.md`](docs/业务挖掘-发现报告.md) | 实验室系统生成：36 条访谈事实、6 角色、6 项候选需求 |
| 行业分析 | [`docs/行业分析.md`](docs/行业分析.md) | 由发现报告 docx 整理：问题定性、需求优先级、方法与局限 |
| 开源项目参考 | [`docs/开源项目参考.md`](docs/开源项目参考.md) | 6 个同类 GitHub 项目横向比对（voyant-travel/pms、hotelito 等） |
| 流程图 | [`docs/流程图/`](docs/流程图/) | 现状业务流程图 + 数智化转型后流程图（SVG/PNG 双格式） |
| 典型事件资料 | [`docs/典型事件资料.docx`](docs/典型事件资料.docx) | 12 页：具体事件台账、量化指标、两张现状流程图（附 [PDF](docs/典型事件资料.pdf)） |
| 需求分析方案 | [`docs/需求分析方案.docx`](docs/需求分析方案.docx) | 23 页：九痛点 → AI 改造与优先级、FR/NFR、追溯矩阵、三层验收（附 [PDF](docs/需求分析方案.pdf)） |
| 项目设计方案 V2.0 | [`docs/项目设计方案.docx`](docs/项目设计方案.docx) | 34 页：架构、里程碑、低/中/高三档报价与投入产出测算（附 [PDF](docs/项目设计方案.pdf)） |
| 设计方案与报价单（旧版） | [`docs/设计方案与报价单/`](docs/设计方案与报价单/) | 21 页，已被 V2.0 替代，留档 |
| 访谈记录 | [`docs/访谈记录/`](docs/访谈记录/) | 六人访谈（md/json/csv 同源）+ 典型事件采访誊录 txt + AI 整理版 docx |
| 上线交付运行手册 | [`docs/项目上线交付运行手册.docx`](docs/项目上线交付运行手册.docx) | 12 章：启动守护、配置、上线检查清单、巡检、备份恢复、故障处置、回滚 |
| 测试 | [`docs/测试/`](docs/测试/) | 测试方案（md + docx，53 条量化用例）、五份场景过程文档（含 25 张实拍截图）、[线上部署地址](docs/测试/线上部署地址.md) |
| 可运行 Demo | [`src/`](src/) | 纯前端实现，无构建步骤 |
| 问答助手（三角色） | [`src/hotel-assistant/`](src/hotel-assistant/README.md) | FastAPI + SSE + RAG：客人问 / AI 答 / 转人工 / 管理端可改，v1.0.0 归档 |
| 房态与入住协同 MVP | [`src/room-status-mvp/`](src/room-status-mvp/README.md) | 员工端 + 管理端 · 状态机 + 入住闸门 + Agent 框架 + 知识库，41 项单测 |

## 快速开始

```bash
# 方式一：本地服务（推荐，数据可持久化到 localStorage）
cd src
python -m http.server 8777
# 浏览器打开 http://127.0.0.1:8777

# 方式二：直接双击 src/index.html（file:// 打开，使用内嵌兜底数据）
```

Demo 包含六个页面：项目总览、九阶段流程（每阶段带人工闸门）、协同 Demo（8 间演示客房、交接单校验、人工复核队列、脱敏审计）、业务流程图、ROI 测算、成果导出。

运行测试（Node ≥ 18，无需安装依赖）：

```bash
node tests/test_engine.js
```

### 跑起问答助手（阶段 2 归档版）

```bash
cd src/hotel-assistant
pip install -r requirements.txt
cp .env.example .env        # 填模型密钥；不填则走检索摘要模式
python seed.py && python ingest.py
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

三端入口：客人端 `/guest`（填房号免登录）、员工端 `/staff`（`staff` / `Staff@123`）、管理端 `/admin`（`admin` / `Admin@123`）。完整验收路径见 [该目录 README](src/hotel-assistant/README.md)。

### 跑起房态与入住协同 MVP

```bash
cd src/room-status-mvp
pip install -r requirements.txt
cp .env.example .env        # 可选：填 LLM_API_KEY 启用真模型，不填走规则模式
python -m uvicorn app:app --host 127.0.0.1 --port 8100
```

两个入口：员工端 `/staff`（`front` / `Front@123` 或 `qa` / `Qa@123`）、管理端 `/admin`（`admin` / `Admin@123`）。首次启动自动建库并写入 24 间房、近 7 天房态流水与 5 篇制度。架构与边界见 [docs/ARCHITECTURE.md](src/room-status-mvp/docs/ARCHITECTURE.md)。

## 目录结构

```
HRSC/
├── README.md
├── LICENSE                       # MIT
├── CHANGELOG.md                  # 版本记录
├── CONTRIBUTING.md               # 贡献指南
├── package.json                  # 元信息（本项目无第三方依赖）
├── docs/                         # 交付文档
│   ├── 业务挖掘-发现报告.md
│   ├── 行业分析.md
│   ├── 开源项目参考.md
│   ├── 需求清单-一页纸.md
│   ├── 设计架构.md
│   ├── 流程图/                   # 现状 + 数智化转型后（SVG/PNG）
│   └── 设计方案与报价单/          # docx + PDF 预览
├── src/                          # 可运行 Demo（HTML/JS/CSS）
│   ├── index.html
│   ├── engine.js                 # 业务核心：三态投影/缺口检出/校验/脱敏
│   ├── store.js                  # localStorage 状态与闸门
│   ├── app.js                    # 路由与六个视图
│   ├── prototype/                # 阶段1最小原型（Python CLI 制度问答）
│   │   ├── stage1_rag_cli.py     # RAG：条款切500字→FAISS；BM25+向量 RRF 检索→LLM
│   │   ├── data/                 # 示例制度文档
│   │   └── requirements.txt
│   ├── hotel-assistant/          # 阶段2 问答助手 v1.0.0（FastAPI + 三角色 + RAG）
│   │   ├── app.py                # 路由与 SSE
│   │   ├── auth.py / db.py       # JWT+RBAC / SQLite 数据层
│   │   ├── chat_engine.py        # 检索→生成→落库→违规标记
│   │   ├── templates/ static/    # 客人端、员工端、管理端六页
│   │   ├── data/                 # 示例制度语料
│   │   ├── screenshots/          # 界面快照
│   │   └── README.md             # 三端入口、验收闭环、接口清单
│   ├── room-status-mvp/          # 房态与入住协同 MVP（员工端 + 管理端）
│   │   ├── app.py                # 入口：路由挂载、页面、启动即播种
│   │   ├── core/                 # db（SQLite/WAL）、security（JWT+岗位矩阵）、seed
│   │   ├── domain/               # 状态机（7 状态 10 迁移 + 入住闸门）、指标
│   │   ├── api/                  # 34 个接口：房态/任务/交接/助手/知识库/管理
│   │   ├── agent/                # 预取→生成→校验三段式、11 个工具（写操作只提案）
│   │   ├── kb/                   # 5 篇制度 + BM25/哈希向量 RRF 检索
│   │   ├── templates/ static/    # 员工端、管理端、登录页
│   │   ├── tests/                # 41 项单测（19 业务内核 / 22 知识与护栏）
│   │   ├── screenshots/          # 界面快照
│   │   └── docs/ARCHITECTURE.md  # 工程架构、Agent 框架、知识库、边界
│   └── data/                     # 演示数据（房型/规则/九阶段课程）
├── tests/test_engine.js          # 业务核心单测（Node 原生运行）
├── examples/                     # 使用示例说明
├── scripts/serve.sh              # 一键本地服务
└── config/default.yaml           # 演示参数
```

## 文档导航

1. 先读 [行业分析](docs/行业分析.md) 了解问题定性与需求优先级；
2. 再看 [流程图](docs/流程图/README.md) 对比现状与转型后流程；
3. [设计方案与报价单](docs/设计方案与报价单/设计方案与报价单.docx) 是可签字的正式版本；
4. 跑起 [Demo](src/index.html) 体验三态协同与人工闸门；
5. 跑起 [问答助手](src/hotel-assistant/README.md) 体验「AI 先答、答不了转人工、管理端可改」的完整闭环；
6. 跑起 [房态 MVP](src/room-status-mvp/README.md) 体验「已清扫 ≠ 可售」的入住闸门与只提案不改数据的助手。

## 许可证

[MIT](LICENSE)
