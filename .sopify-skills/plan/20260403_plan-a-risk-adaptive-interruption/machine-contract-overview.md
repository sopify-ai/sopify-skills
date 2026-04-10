# 机器协议总纲

## 1. 定位

本文用于概述 Plan A 当前设计口径下的 machine contract 执行闭环，帮助宿主、设计者与实现者快速对齐全链路。

本文是总览导读，不新增 machine truth，也不替代 runtime code、state 文件、三张真理表或 checkpoint contract；细节规则以 `design.md`、`runtime/*`、`current_handoff.json` 与各 checkpoint state 为准。
与 `feature/context-boundary-core` 首笔受控 spike 相关的资产路径、schema 路线、熔断键与记分规则，以 `design.md` §0 与 `tasks.md` §9 / §11 / §16 / §18 为唯一真相源；本文只做交叉引用，不重复展开。

## 2. 一句话总括

当前 Plan A 可以理解为三层闭环：外层由 runtime contract（gate + snapshot + handoff）先收敛 machine truth、响应模式与宿主允许动作，中层只在当前允许动作面上做局部语义裁决，末层宿主只能沿 handoff 继续；若无法唯一化，则退回 `inspect / explicit_choice_required / stay_blocked`，仅在稳定只读可答时才允许降级到 `continue_host_consult / consult_readonly`。

## 3. 图示速览

### 3.1 总图

```text
用户输入
  |
  v
[外层 runtime contract]
  gate -> snapshot -> handoff
  输出:
    - status
    - gate_passed
    - allowed_response_mode
    - required_host_action
  |
  v
[中层局部语义裁决]
  Guard
    -> Local Context
    -> Signal + Projection
    -> Priority Resolution
    -> Failure Recovery
    -> Side-Effect Mapping
  |
  v
[末层宿主执行]
  - 只能沿 required_host_action 继续
  - 默认套 Sopify 标题/footer 模板
  - 不得在未闭环场景下自动推进
```

### 3.2 外层分支图

```text
gate contract
  |
  +-- status != ready 或 gate_passed != true
  |     -> error_visible_retry
  |     -> 只允许可见错误 / 重试
  |
  +-- allowed_response_mode = checkpoint_only
  |     -> 停在当前 checkpoint 链
  |     -> 只允许 checkpoint 响应
  |
  +-- allowed_response_mode = normal_runtime_followup
        -> 可以继续宿主后续动作
        -> 仍只能沿 handoff 继续
```

### 3.3 主状态链图

```text
clarification_pending
  -> answer_questions
  -> checkpoint_only

decision_pending
  -> confirm_decision
  -> checkpoint_only

plan_proposal_pending
  -> confirm_plan_package
  -> checkpoint_only

ready_for_execution / execution_confirm_pending
  -> confirm_execute
  -> checkpoint_only

resume_active / exec_plan
  -> continue_host_develop
  -> normal_runtime_followup

consult
  -> continue_host_consult
  -> normal_runtime_followup

workflow / light_iterate
  -> continue_host_workflow
  -> normal_runtime_followup
```

### 3.4 中层流水线图

```text
Deterministic Guard
  - 先裁掉当前不可能动作
  - 不能被 parser / classifier 旁路

Local Context Builder
  - 只保留本轮判定必需上下文
  - 不直接吃整段聊天和 assistant prose

Signal Extraction + Action Projection
  - parser-first 产出候选信号
  - classifier 最多只能补候选信号

Signal Priority Resolution
  - 规则信号永远压过 classifier 信号
  - 只要未唯一化，就不能推进

Failure Recovery
  - ambiguous / no_match / state_missing -> fail-close

Side-Effect Mapping
  - 只有动作稳定后，才允许决定:
    - 写哪些状态
    - 暴露哪个 handoff

Handoff Guardrail Artifacts
  - 对 guard-stable 路由追加:
    - deterministic_guard
    - action_projection
    - resolution_planner
    - sidecar_classifier_boundary
    - vnext_phase_boundary

V1 Scope Registry
  - `runtime/context_v1_scope.py` 冻结:
    - checkpoint kind allowlist
    - state effect allowlist / forbidden side effects
    - candidate file map / observe-only file map
```

### 3.5 安全边界图

```text
无法唯一化
  |
  +-- inspect
  +-- explicit_choice_required
  +-- stay_blocked
  \-- visible_error

这四类都是 fail-close 正式出口
不允许:
  - 隐式 continue
  - 隐式 confirm
  - 隐式执行
```

### 3.6 唯一允许的可回答型最终降级

```text
前提必须同时满足:
  1. machine truth 稳定
  2. 副作用边界清楚
  3. 上下文足以形成稳定只读结果

满足时:
  -> continue_host_consult / consult_readonly

仍然禁止:
  - 提交 checkpoint
  - 推进 run stage
  - 物化 plan
  - 触发执行
```

## 4. 三层闭环

### 4.1 外层：runtime contract

外层先解决“机器现在到底处于什么状态、宿主当前允许做什么”。

它由三部分组成：

1. gate contract：给出 `status / gate_passed / allowed_response_mode`
2. snapshot：把 `current_run / current_plan / current_* state` 收敛成唯一 machine truth
3. handoff：给出 `required_host_action` 与宿主后续动作边界

### 4.2 中层：局部语义裁决

中层不做全局自由意图理解，只在当前允许动作面上做局部判定。

固定流水线为：

1. `Deterministic Guard`
2. `Local Context Builder`
3. `Signal Extraction + Action Projection`
4. `Signal Priority Resolution`
5. `Failure Recovery Table`
6. `Side-Effect Mapping Table`

当路由命中当前 v1 guardrail 支持面时，handoff 导出层还会附带 `deterministic_guard`、`action_projection`、`resolution_planner`、`sidecar_classifier_boundary`、`vnext_phase_boundary` 五类 artifact，供宿主与调试路径读取同一份局部判定证据。

与之配套，`runtime/context_v1_scope.py` 提供 V1 scope registry：冻结 `checkpoint_kind`、状态副作用 allowlist / forbidden set、candidate file map 与 observe-only file map，并在越界时直接 fail-close。

### 4.3 末层：宿主执行

末层只负责两件事：

1. 沿 `required_host_action` 继续
2. 按模板规则向用户输出

宿主不得在 machine truth 未闭环时自行脑补推进。

## 5. 真相源矩阵

| 层 | 真相源 | 关键字段 | 作用 |
| --- | --- | --- | --- |
| gate | runtime gate contract | `status`, `gate_passed`, `allowed_response_mode` | 决定本轮是否允许继续、是否只能 checkpoint 响应 |
| snapshot | `ContextResolvedSnapshot` | `current_run`, `current_plan`, `current_*`, `is_conflict` | 把分散 state 收敛成唯一 machine truth |
| handoff | `current_handoff.json` | `required_host_action`, `route_name`, `checkpoint_request`, `deterministic_guard`, `action_projection`, `resolution_planner`, `sidecar_classifier_boundary`, `vnext_phase_boundary` | 约束宿主下一步可执行动作，并暴露本轮 guardrail 证据 |
| checkpoint state | `current_clarification.json` / `current_decision.json` / `current_plan_proposal.json` / `current_run.json` | `questions`, `options`, `missing_facts`, `execution_gate` | 决定 checkpoint 的具体内容与恢复方式 |
| v1 scope registry | `runtime/context_v1_scope.py` | `SUPPORTED_CHECKPOINT_KINDS_V1`, `ALLOWED_V1_STATE_EFFECTS`, `FORBIDDEN_V1_SIDE_EFFECTS`, `V1_IMPLEMENTATION_CANDIDATE_FILES`, `V1_OBSERVE_ONLY_FILES` | 冻结 Checkpoint C 白名单、状态副作用边界与越界阻断规则 |

## 6. 最外层 gate 分支

| gate 结果 | 宿主允许做什么 | 含义 |
| --- | --- | --- |
| `error_visible_retry` | 只允许可见错误与重试提示 | preflight、handoff 或 strict entry 不成立 |
| `checkpoint_only` | 只允许停留在当前 checkpoint 链响应 | 当前仍有阻塞点，不能自动推进 |
| `normal_runtime_followup` | 可以继续宿主后续动作 | 当前 machine truth 已允许继续 workflow、develop 或 consult |

## 7. 主状态链矩阵

| 当前 machine truth / route | `required_host_action` | 宿主允许动作 | 默认响应形态 |
| --- | --- | --- | --- |
| `clarification_pending` | `answer_questions` | 展示缺失事实、等待补充、允许 inspect / cancel | `checkpoint_only` |
| `decision_pending` | `confirm_decision` | 展示问题与选项，等待 `choose / status / cancel` | `checkpoint_only` |
| `plan_proposal_pending` | `confirm_plan_package` | 展示 proposal，等待 `continue / status / revise / cancel` | `checkpoint_only` |
| `ready_for_execution` / `execution_confirm_pending` | `confirm_execute` | 展示执行摘要，等待 `continue / revise / cancel` | `checkpoint_only` |
| `resume_active` / `exec_plan` | `continue_host_develop` | 宿主继续 develop；如再分叉，必须走 develop checkpoint callback | `normal_runtime_followup` |
| `consult` | `continue_host_consult` | 宿主只读回答 | `normal_runtime_followup` |
| `workflow` / `light_iterate` | `continue_host_workflow` | 宿主继续主流程或方案评审 | `normal_runtime_followup` |
| `state_conflict` | `resolve_state_conflict` 或 `continue_host_workflow` | 先消解冲突，再决定是否恢复主流程 | 阻断优先 |

## 8. 中层判定流水线

| 阶段 | 输入 | 输出 | 不能做什么 |
| --- | --- | --- | --- |
| `Deterministic Guard` | 基于 machine fact 的 proof surface：`allowed_response_mode` × `required_host_action` 一致性、`checkpoint_request.checkpoint_kind` 与 action 的映射校验（`_CHECKPOINT_REQUEST_KIND_BY_ACTION`）、plan identity proof（`plan_id` / `plan_path` / `current_plan`）、`current_run.stage`、`execution_gate` | 裁掉当前不可能动作；proof 不够时 fail-close 到 `contract_invalid` | 不能让语义层越过 machine fact |
| `Local Context Builder` | 当前用户输入、最近 1-3 条相关用户消息、checkpoint 摘要、允许动作集合 | 局部上下文块 | 不能直接下放整段聊天与 assistant prose |
| `Signal Extraction + Action Projection` | parser-first 候选信号 + 当前 checkpoint 的最小动作面 | 候选信号与动作面 | classifier 不能直接输出最终动作 |
| `Signal Priority Resolution` | 候选信号 | `resolved / ambiguous / no_candidate` | 规则信号不能被弱语义提示压过 |
| `Failure Recovery Table` | `ambiguous / no_match / state_missing / ...` | `inspect / stay_blocked / explicit_choice_required / visible_error` | 不能靠补猜推进 |
| `Side-Effect Mapping Table` | 已稳定的 `resolved_action` | `state_mutators + handoff_protocol` | 未稳定前不得改状态、不得推进 |

## 9. Action Projection 动作面

| checkpoint / 场景 | 最小动作面 | 当前状态 |
| --- | --- | --- |
| `answer_questions` | `missing_facts`, `questions`, `allowed_actions=[answer, inspect, cancel]` | 设计已明确 |
| `confirm_decision` | `question`, `options`, `recommended_option_id`, `allowed_actions=[choose, status, cancel]` | 设计已明确 |
| `confirm_plan_package` | `analysis_summary`, `proposed_path`, `estimated_task_count`, `allowed_actions=[confirm, inspect, revise, cancel, retopic]` | 设计已明确 |
| `confirm_execute` | `plan_path`, `risk_level`, `key_risk`, `mitigation`, `allowed_actions=[confirm, inspect, revise, cancel]` | 设计已明确 |
| `review_or_execute_plan` | `plan_id`, `plan_path`, `run_stage`, `next_required_action`, `summary`(可选), `task_count`(可选), `risk_level`(可选), `key_risk`(可选), `mitigation`(可选), `allowed_actions=[continue, inspect, revise, cancel]` | 设计已明确 |
| `continue_host_consult` | `consult_mode`, `allowed_actions=[consult, block]` | 设计已明确 |
| `continue_host_develop` | `active_run_stage`, `task_refs`, `changed_files`, `verification_todo`, `allowed_actions=[continue, checkpoint, consult, block]` | 设计已明确 |

## 10. 信号、恢复与副作用闭环

跨层 P0 冻结口径以 `design.md` §0 `P0 Freeze | 分层联动矩阵（最小冻结）` 为准，本文只保留总览摘要。

### 10.1 信号裁决

高优先级 signal 压制低优先级 signal。`cancel_current_checkpoint` 可压过 `continue_current_checkpoint`；`analysis_only_no_write_brake` 可压住推进型动作并改道只读分析。

### 10.2 失败恢复

当 Guard、Parser、Projection 或未来 classifier 任一层无法稳定给出动作时，统一走 fail-close：

- `inspect`
- `explicit_choice_required`
- `stay_blocked`
- 必要时 `visible_error`

### 10.3 副作用映射

只有 `resolved_action` 已稳定时，才允许进入副作用表。副作用表同时约束两件事：

1. 哪些内部状态允许 `preserve / clear / update / write`
2. 宿主只暴露哪个 `required_host_action / artifacts / resume_route / output_mode`

## 11. 降级与阻断

### 11.1 可回答型最终降级

唯一允许的可回答型最终降级，仅限以下条件同时满足：

1. machine truth 稳定
2. 副作用边界清楚
3. 现有上下文足以形成稳定只读结果

此时唯一出口为 `continue_host_consult / consult_readonly`。

该出口只读：

- 不提交 checkpoint
- 不推进 run stage
- 不物化 plan
- 不触发执行

### 11.2 阻断型安全停点

其余未唯一化场景仍应停留在：

- `inspect`
- `explicit_choice_required`
- `stay_blocked`

这些停点是 fail-close 的正式组成部分，不是异常旁路。

## 12. 宿主输出规则

当 gate contract 满足 `status=ready` 且 `gate_passed=true` 时，宿主对外响应默认应复用 Sopify 标准标题/footer 模板。

约束如下：

1. `allowed_response_mode` 只影响正文类型与下一步提示，不影响是否套用模板
2. 宿主不得默认退化为无模板自由 prose
3. 自由 prose 仅作为 debug、开发态排障或显式错误可见化的例外输出

## 13. 当前仍属设计空档

以下内容应继续视为设计空档，而不是已完整落地的 live runtime matrix：

1. Host Output Adapter Matrix 仍未完整成型，目前冻结的是模板规则，不是完整 adapter 层
2. `cancel_current_checkpoint` 的副作用映射样例仍可继续补齐

## 14. Read Next

建议按以下顺序继续阅读：

1. `design.md`：先读 §0 `P0 Freeze | 分层联动矩阵（最小冻结）`，再读三张表、样例行、已拍板产品行为
2. `tasks.md`：执行真相与待补空档
3. `runtime/context_v1_scope.py`
4. `runtime/action_projection.py`
5. `runtime/handoff.py`
6. `runtime/gate.py`
7. `runtime/context_snapshot.py`
8. `runtime/output.py`
