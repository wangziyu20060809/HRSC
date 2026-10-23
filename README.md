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
| 设计方案与报价单 | [`docs/设计方案与报价单/`](docs/设计方案与报价单/) | 21 页 Word 正式版（附 PDF 预览），三档报价 |
| 可运行 Demo | [`src/`](src/) | 纯前端实现，无构建步骤 |

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
│   ├── 流程图/                   # 现状 + 数智化转型后（SVG/PNG）
│   └── 设计方案与报价单/          # docx + PDF 预览
├── src/                          # 可运行 Demo（HTML/JS/CSS）
│   ├── index.html
│   ├── engine.js                 # 业务核心：三态投影/缺口检出/校验/脱敏
│   ├── store.js                  # localStorage 状态与闸门
│   ├── app.js                    # 路由与六个视图
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
4. 跑起 [Demo](src/index.html) 体验三态协同与人工闸门。

## 许可证

[MIT](LICENSE)
