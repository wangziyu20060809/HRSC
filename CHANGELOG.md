# Changelog

本项目的全部重要变更都会记录在本文件。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.1.0] - 2026-10-23

### Added

- `docs/` 交付文档目录：
  - 业务挖掘发现报告（实验室系统生成内容整理）；
  - 行业分析（由发现报告 docx 整理）；
  - 流程图：现状业务流程图、数智化转型后业务流程图（SVG/PNG）；
  - 设计方案与报价单（21 页 Word，三档报价，附 PDF 预览）。
- `src/` 可运行 Demo：项目总览、九阶段流程（人工闸门）、协同 Demo（三态投影 / 交接单校验 / 人工复核队列 / 脱敏审计）、业务流程图、ROI 测算、成果导出。
- `tests/test_engine.js`：三态投影、交接单校验、脱敏函数的单元测试。
- `examples/`、`scripts/serve.sh`、`config/default.yaml`。

## [1.0.0] - 2026-10-23

### Added

- 初版：《山海旅居 · 业务需求发现报告》docx 与 markdown 源稿。
