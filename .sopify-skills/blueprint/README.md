# 项目蓝图索引

状态: 文档已收口，待实现
创建日期: 2026-03-17
维护方式: 首次识别到真实项目仓库并触发 Sopify 时，至少创建本文件；索引区块由 Sopify 托管刷新，说明区块允许人工补充

## 当前目标

<!-- sopify:auto:goal:start -->
- 建立零配置开箱即用的 Sopify 文档治理闭环
- 让 `blueprint/README.md` 成为项目级长期入口索引，而不是依赖当前 plan 或历史归档
- 在不要求用户额外配置的前提下，稳定支持 blueprint / plan / history 的生命周期
<!-- sopify:auto:goal:end -->

## 项目概览

<!-- sopify:auto:overview:start -->
- blueprint: 项目级长期蓝图，默认进入版本管理
- plan: 当前活动方案，默认本地使用、默认忽略
- history: 收口后的方案归档，默认本地使用、默认忽略
- replay: 可选回放能力，不属于基础文档治理契约
<!-- sopify:auto:overview:end -->

## 架构地图

<!-- sopify:auto:architecture:start -->
```text
.sopify-skills/
├── blueprint/
│   ├── README.md
│   ├── background.md
│   ├── design.md
│   └── tasks.md
├── plan/
├── history/
├── state/
└── replay/
```
<!-- sopify:auto:architecture:end -->

## 关键契约

<!-- sopify:auto:contracts:start -->
- 不要求用户新增配置；默认行为即完成 bootstrap、索引刷新与方案收口
- 首次 Sopify 触发只要求创建轻量 `blueprint/README.md`
- 首次进入 plan 生命周期时，再补齐 `blueprint/background.md / design.md / tasks.md`
- `plan` 只保留当前活动方案；到“本轮任务收口、准备交付验证”时再归档到 `history/`
- `full` 任务必须更新深层 blueprint；`standard` 仅在边界或契约变化时更新；`light` 不强制
<!-- sopify:auto:contracts:end -->

## 当前焦点

<!-- sopify:auto:focus:start -->
- 先实现文档治理闭环
- 再在 design 阶段引入决策确认能力（decision checkpoint）
- 保持单活动 plan 模型，不引入额外 drafts 目录或 commit 阶段强校验
<!-- sopify:auto:focus:end -->

## 深入阅读入口

<!-- sopify:auto:read-next:start -->
- [背景与目标](./background.md)
- [治理设计](./design.md)
- [实施任务](./tasks.md)
- [项目技术约定](../project.md)
- [项目概览](../wiki/overview.md)
- 当前活动方案: 见 `../plan/`
<!-- sopify:auto:read-next:end -->

## 维护说明

- 本文件是项目级入口索引，不承载单次任务的完整实现细节。
- 当前仓库已完成蓝图文档收口；自动创建、自动刷新、收口归档等行为仍待 runtime 实现对齐。
- 自动区块优先保持“短、稳、可扫描”；深入说明进入 `background.md / design.md / tasks.md`。
- 若人工补充内容与代码、宿主契约、目录契约冲突，以实现与正式蓝图为准，并在后续收口时修正。
