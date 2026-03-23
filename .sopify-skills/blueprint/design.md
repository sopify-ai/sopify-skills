# 知识布局 V2 蓝图设计

状态: 已与 runtime V2 contract 对齐

## 正式结论

1. `blueprint/README.md` 只保留入口索引与状态，不承载长说明。
2. 长期知识层固定为 `project.md + blueprint/{background,design,tasks}`。
3. `plan/` 是活动工作层，`history/` 是显式 finalize 后才出现的归档层。
4. `knowledge_sync` 是唯一正式同步契约；`blueprint_obligation` 只保留 legacy reject / projection 语义。
5. `active_plan` 的正式解析口径是 `current_plan.path + current_plan.files`。

## 第一性原理分层结论

- `user/preferences.md` 承载当前 workspace 的协作风格试运行，包括第一性原理纠偏和局部“两段式协作”偏好。
- `analyze` 只吸收可复用的稳定子集：目标/路径分离、目标模糊先澄清、次优路径给替代、SMART 风格成功标准收口。
- `consult/runtime` 输出层保留为二期配置化能力；“所有问答都两段式输出”不进入当前默认契约。
- promotion gate 的后续跨仓库 Batch 2/3 只用于优化 trigger matrix、示例边界和 threshold 校准，不反向改写本轮 `v1` 分层边界。
- `45` 样本 / `3` 类环境的 round-1 pilot 已完成独立 decision pass，并以 `propose-promotion` 作为正式结论；后续只保留 wording/examples 校准，不再回退本轮 promotion 决策。

## 目录分层

| Layer | Paths | Meaning |
|-----|------|------|
| `L0 index` | `blueprint/README.md` | 纯索引页，只做入口与状态暴露 |
| `L1 stable` | `project.md`, `blueprint/background.md`, `blueprint/design.md`, `blueprint/tasks.md` | 长期知识与稳定契约 |
| `L2 active` | `plan/YYYYMMDD_feature/` | 当前活动方案与机器元数据 |
| `L3 archive` | `history/index.md`, `history/YYYY-MM/...` | 显式 finalize 后的归档与查找入口 |
| `runtime` | `state/*.json`, `replay/` | 运行态 machine truth 与可选学习记录 |

## Runtime state scope

- review state 默认落在 `state/sessions/<session_id>/`，覆盖 `current_plan/current_run/current_handoff/current_clarification/current_decision/last_route`
- 根级 `state/` 继续只承载 global execution truth，主要服务 `execution_confirm_pending / resume_active / exec_plan / finalize_active`
- `session_id` 可以由宿主显式透传，也可以由 runtime gate 自动生成并回传；同一条 review 续轮必须复用同一个 `session_id`
- 并发 review 使用不同 `session_id`；global execution truth 只补 soft ownership 观测字段，不引入 lease / heartbeat / takeover 锁
- clarification / decision bridge 先读 session review state，再回退到 global execution truth，保证 develop 阶段生成的 checkpoint 仍可桥接

## Runtime gate ingress contract

- `persisted_handoff` 继续是 runtime gate 的唯一正向机器证据；`runtime_result.handoff` 只用于诊断归因，不替代 persisted 成功证据。
- `evidence.handoff_source_kind` 的稳定值域固定为：`missing / current_request_not_persisted / reused_prior_state / current_request_persisted / persisted_runtime_mismatch`。
- gate 判定优先级固定为：`strict_runtime_entry_missing` 优先，其次区分 `handoff_missing / handoff_normalize_failed`，最后才由 `handoff_source_kind` 决定 `ready` 或 source-kind-specific error。
- `reused_prior_state` 保持允许态；它用于 `~summary` 等不产出新 handoff 的只读恢复路径，不在当前阶段提升为错误面。
- `observability.previous_receipt` 作为稳定诊断面，最小字段固定为：`exists / written_at / request_sha1_match / route_name_match / stale_reason`。
- `observability.previous_receipt.stale_reason` 的稳定枚举固定为：`not_stale / request_sha1_mismatch / route_name_mismatch / both_mismatch / parse_error`。

## 生命周期

1. 首次真实项目触发：只要求 `project.md`、`user/preferences.md` 与 `blueprint/README.md`。
2. 首次进入 plan 生命周期：补齐 `blueprint/background.md`、`blueprint/design.md`、`blueprint/tasks.md`，并生成当前 `plan/`。
3. 显式 `~go finalize`：根据 `knowledge_sync` 复核长期知识，再写 `history/index.md` 与归档目录。

## 消费契约

| Context Profile | Reads | Fail-open Rule | Notes |
|-----|------|------|------|
| `bootstrap` | `project.md`, `user/preferences.md`, `blueprint/README.md` | 缺深层 blueprint 或 history 不报错 | 只建立最小长期知识骨架 |
| `consult` | `project.md`, `user/preferences.md`, `blueprint/README.md` | 不要求 `background/design/tasks` | 咨询与轻问答不应强行物化 plan |
| `plan` | `project.md`, `user/preferences.md`, `blueprint/README.md`, `blueprint/background.md`, `blueprint/design.md`, `blueprint/tasks.md`, `active_plan` | 若深层 blueprint 缺失，先按生命周期补齐；history 缺失仍可继续 | `active_plan = current_plan.path + current_plan.files`；仅 state 绑定的 plan 视为 machine-active |
| `develop` | `plan` 档位读取集 + `state/*.json` | history 缺失不阻断；长期知识缺失按 `knowledge_sync` 只警告或待 finalize 时阻断 | 默认继续消费当前活动 plan，不回读 history 正文 |
| `finalize` | `active_plan`, `knowledge_sync`, `project.md`, `blueprint/background.md`, `blueprint/design.md`, `blueprint/tasks.md`, `history/index.md` | `history/index.md` 缺失时现场创建；`knowledge_sync=required` 的长期文档未更新则阻断 | finalize 才允许把 L2 写入 L3 |

## `knowledge_sync` contract

```yaml
knowledge_sync:
  project: skip|review|required
  background: skip|review|required
  design: skip|review|required
  tasks: skip|review|required
```

语义固定：

- `skip`: 本轮无需同步该长期文件。
- `review`: 本轮可能受影响，finalize 时至少复核。
- `required`: 本轮必须更新，否则 finalize 阻断。

## 评分输出 contract

正式 plan 包与方案摘要默认带上：

```md
评分:
- 方案质量: X/10
- 落地就绪: Y/10

评分理由:
- 优点: 1 行
- 扣分: 1 行
```

## 文档治理约定

- public README 只保留新用户需要的价值主张、快速开始、精简目录结构与 FAQ。
- workflow 细节下沉到 `docs/how-sopify-works.md` / `.en.md`，不把维护者操作塞回 README。
- 维护者操作统一收口到 `CONTRIBUTING.md` / `CONTRIBUTING_CN.md`。
- `blueprint/README.md` 继续只做索引页，不承载长说明。
- `plan/` 是活动工作层；`history/` 是显式 finalize 后的归档层；`state/` 是运行态 machine truth。

## KB 职责矩阵

| Path | Layer | Responsibility | Created When | Git Default |
|-----|------|------|------|------|
| `.sopify-skills/blueprint/README.md` | `L0 index` | 项目索引与当前状态 | 首次真实项目触发 | tracked |
| `.sopify-skills/project.md` | `L1 stable` | 可复用技术约定 | 首次 bootstrap | tracked |
| `.sopify-skills/blueprint/{background,design,tasks}.md` | `L1 stable` | 长期目标、契约、延后事项 | 首次进入 plan 生命周期 | tracked |
| `.sopify-skills/plan/YYYYMMDD_feature/` | `L2 active` | 当前活动方案包 | 每次正式进入方案流 | ignored |
| `.sopify-skills/history/YYYY-MM/...` | `L3 archive` | 已收口方案归档 | 显式 `~go finalize` | ignored |
| `.sopify-skills/state/*.json` | `runtime` | handoff / checkpoint / gate machine truth | runtime 执行期间 | ignored |
| `.sopify-skills/replay/` | `optional` | 复盘摘要与学习记录 | 命中主动记录策略时 | ignored |

## Checkpoint 契约补充

### Clarification checkpoint

- 只在 planning 路由内生效，用于补齐最小事实锚点。
- 命中后 runtime 会写入 `current_clarification.json`，并在 handoff 中暴露 `checkpoint_request`。
- 宿主应优先读取结构化问题列表，等待用户补充后再恢复默认 runtime 入口。

### Decision checkpoint

- 只在 planning 路由内生效，用于处理显式多方案分叉或结构化 tradeoff 候选。
- 命中后 runtime 会写入 `current_decision.json`，并在 handoff 中暴露推荐项与提交状态。
- 宿主确认后再恢复默认 runtime 入口，不得在确认前擅自物化正式 plan。

### Develop-first callback

- 当 `required_host_action == continue_host_develop` 时，宿主继续负责代码修改。
- 若开发中再次出现用户拍板分叉，宿主必须调用 `scripts/develop_checkpoint_runtime.py` 回调 runtime。
- payload 至少带上 `active_run_stage / current_plan_path / task_refs / changed_files / working_summary / verification_todo`。

### Execution gate 与 execution confirm

- plan 物化后会写入 `execution_gate` machine contract，区分 `plan_generated` 与 `ready_for_execution`。
- 当 gate 结果为 `ready` 时，runtime 会进入 `execution_confirm_pending`，并通过 `confirm_execute` 等待用户确认。
- 宿主应优先展示 `execution_summary` 中的计划、风险与缓解，而不是直接跳到 develop。

## 分层试点材料（2026-03）

- promotion gate pilot 的历史工件保留在 `history/2026-03/20260321_go-plan/`。
- 关键参考包括：
  - `pilot_sample_matrix.md`
  - `trigger_matrix.md`
  - `pilot_review_rubric.md`
- 这些材料属于长期项目知识，不进入 public README，也不进入 maintainer 快速入口。
