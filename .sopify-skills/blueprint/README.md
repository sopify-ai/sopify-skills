# 项目蓝图索引

状态: 文档已收口，进入宿主入口守卫排期
创建日期: 2026-03-17
维护方式: 首次识别到真实项目仓库并触发 Sopify 时，至少创建本文件；索引区块由 Sopify 托管刷新，说明区块允许人工补充

## 当前目标

<!-- sopify:auto:goal:start -->
- 持续把 `sopify-skills` 的长期事实收口到蓝图索引。
- 通过 finalize 事务完成活动 metadata-managed plan 的正式收口，再进入下一轮规划。
<!-- sopify:auto:goal:end -->

## 项目概览

<!-- sopify:auto:overview:start -->
- blueprint: 长期项目真相，默认入库
- plan: 每轮任务生成的活动方案
- history: 由 `~go finalize` 产出的历史归档
- replay: 可选回放能力
<!-- sopify:auto:overview:end -->

## 架构地图

<!-- sopify:auto:architecture:start -->
```text
.sopify-skills/
├── blueprint/
├── plan/
├── history/
├── state/
└── replay/
```
<!-- sopify:auto:architecture:end -->

## 关键契约

<!-- sopify:auto:contracts:start -->
- 首次真实项目触发时创建 `blueprint/README.md`
- 首次进入 plan 生命周期时补齐深层 blueprint 文件
- 只有新 runtime 生成的 metadata-managed plan 支持 finalize
- `review_required` 缺少深层 blueprint 更新时仅警告；`design_required` 会阻断收口
<!-- sopify:auto:contracts:end -->

## 当前焦点

<!-- sopify:auto:focus:start -->
- 最近收口方案：`Prompt-Level Runtime Gate` -> `.sopify-skills/history/2026-03/20260320_prompt_runtime_gate`
- 当前已无活动 plan；下一轮规划会重新创建新的活动方案。
<!-- sopify:auto:focus:end -->

## 深入阅读入口

<!-- sopify:auto:read-next:start -->
- [项目技术约定](../project.md)
- [项目概览](../wiki/overview.md)
- [蓝图设计](./design.md)
- 最近归档: `../history/2026-03/20260320_prompt_runtime_gate`
<!-- sopify:auto:read-next:end -->

## 专项蓝图

- [Skill 标准对齐蓝图](./skill-standards-refactor.md)

## 维护说明

- 本文件是项目级入口索引，不承载单次任务的完整实现细节。
- 当前仓库已完成蓝图文档收口；blueprint bootstrap、metadata-managed plan 的 finalize 收口、execution gate、`decision_templates / decision_policy / decision bridge helper` 与 decision runtime contract 已落地；CLI interactive bridge、structured tradeoff policy、compare facade、scope clarify bridge 与 replay 摘要增强也已进入代码主线。当前新增主线收敛为“当前时间显示 + ~summary 今日详细摘要”，先满足用户侧可见时间与复盘学习诉求；`daily index`、`~replay` 与更重的按天 retrieval 维持后续可选能力。
- 自动区块优先保持“短、稳、可扫描”；深入说明进入 `background.md / design.md / tasks.md`。
- 若人工补充内容与代码、宿主契约、目录契约冲突，以实现与正式蓝图为准，并在后续收口时修正。
