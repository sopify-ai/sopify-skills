# 文档治理蓝图背景

状态: 文档已收口，待实现
创建日期: 2026-03-17

## 需求背景

当前 Sopify 已具备以下基础能力：

- runtime 可在项目内生成最小知识库与活动 plan
- `plan/`、`history/`、`state/`、`replay/` 均已有基本约定
- 宿主可通过 vendored runtime 进入 plan / develop / compare / replay 等链路

但当前文档资产仍存在明显断层：

1. 仓库内长期蓝图与单次 plan 的职责边界不稳定
2. `CHANGELOG` 更适合发布记录，不适合沉淀长期架构真相
3. 下游项目即使接入 Sopify，也缺一个默认存在、可快速理解项目的全局入口索引
4. 文档更新更多依赖语义触发和人工记忆，缺少稳定的生命周期收口点
5. `plan` 与 `history` 的落点、时机、是否进 git 目前没有统一默认策略

## 当前 runtime 基线

本蓝图已吸收原 `20260313_sopify_runtime_blueprint` 的有效结论，后续不再双维护旧目录。

当前 runtime 的已收口基线是：

- 最小对外 runtime 发布切片仍是 `runtime-backed ~go plan`
- 当前默认 repo-local 原始输入入口是 `scripts/sopify_runtime.py`
- `scripts/go_plan_runtime.py` 仅保留为 plan-only helper
- runtime 已可写入 `plan / state / current_handoff`
- 最小 KB bootstrap 已落地，当前最小文件集包括：
  - `project.md`
  - `wiki/overview.md`
  - `user/preferences.md`
  - `history/index.md`
- `workflow-learning` 的 replay 能力仍保留为可选扩展，不纳入基础文档治理契约
- `~compare` 的宿主专用桥接、`~go exec` develop bridge、history 自动归档仍属于后续阶段能力

当前不变的工程原则：

- 默认无配置也能跑主路径
- 命令路由、状态落盘、最小上下文恢复优先代码化
- 禁止全量自动加载 `.sopify-skills/`
- 先收口核心流程，再考虑外围产品层

## 目标

### 1. 零配置开箱即用

- 用户不需要增加额外配置、开关或 commit hook
- 首次触发 Sopify 时，只要当前目录是“真实项目仓库”，就能自动建立项目入口索引

### 2. 统一文档分层

- `blueprint/` 负责项目级长期真相
- `plan/` 负责当前活动方案
- `history/` 负责收口后的归档
- `replay/` 保持为可选能力，不纳入基础治理契约

### 3. 工程化约束优先

- 用固定生命周期和机器字段约束文档更新
- 尽量避免“模型自己判断应该写什么”的纯语义化触发

### 4. 支持后续决策确认能力

- 设计阶段若出现多方案分叉，应能先进入决策确认，再生成唯一正式 plan
- 决策结果能稳定落到 plan 与 blueprint，而不是散落在聊天上下文中

## 范围

### 范围内

- `.sopify-skills/blueprint/` 的正式目录与模板
- `plan -> 收口 -> history` 的生命周期规则
- `blueprint/README.md` 作为项目全局索引的强约束模板
- 首次触发与首次进入 plan 生命周期时的默认文档行为
- 与 decision checkpoint 的衔接规则

### 范围外

- 不在本轮实现新的用户配置项
- 不在本轮依赖 commit 阶段强校验
- 不在本轮让 `history/` 或 `replay/` 成为默认入库资产
- 不在本轮引入多份 draft plan 或并发 plan 模型

## 关键约束

- 必须保持当前“单活动 plan”模型，避免新增复杂目录层级
- 必须适配接入 Sopify 的下游项目，不能只为当前源仓库定制
- 必须允许用户保留对 `.gitignore` 的自主修改权，但默认行为应自洽
- `blueprint/README.md` 要可被人和 LLM 快速扫描，不能退化成冗长设计文档

## 成功标准

满足以下条件，可认为文档治理闭环成立：

1. 首次触发 Sopify 时，真实项目仓库会自动得到 `blueprint/README.md`
2. 首次进入 plan 生命周期时，项目会补齐完整 `blueprint/` 骨架
3. 当前任务只维护一份活动 plan，不产生额外草稿目录
4. 任务收口时能稳定刷新 README 索引区块，并在需要时同步深层 blueprint
5. 任务收口后能归档到 `history/`，同时更新索引
6. 决策确认能力后续可直接复用这套文档与状态契约
