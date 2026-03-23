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
