# 技术设计: 局部语义收口方案 | 风险自适应打断与局部语义分类收敛

总览导读：见 `machine-contract-overview.md`。该文档前半部分已收纳图示速览，后半部分保留详细矩阵；它只做导读，不替代本文和 runtime/state 真相源。

## 设计目标

本子 plan 的设计目标不是立刻交付代码，而是把本方案的实现前提收敛成一套可执行的设计骨架：

1. 明确哪些约束已经冻结，后续实现不得突破
2. 把总纲中的样本矩阵转成可消费的语义类与任务拆分
3. 把外部参考实现中的可借鉴实践翻译成适合 Sopify 的分层方案
4. 形成一条“真正开工前先持续优化设计”的稳定路径

## 已冻结设计约束

以下约束视为本 plan 的输入，不在本 plan 中重新拍板：

1. 仅处理局部 checkpoint / execution gate 语境下的风险自适应打断
2. 不扩展成全局自由语义理解
3. 不破坏 `ExecutionGate` v1 核心机器契约
4. 不改 `gate_status` 值集与核心字段名
5. 默认不改 runtime state model / handoff contract / resolution contract
6. 不接受“补一个词”式修复，按语义类一次收口
7. 默认与既有对外 contract 主线保持兼容

## 问题重述

本方案真正要分类的对象，不是“整句用户话术属于哪个词槽”，而是：

当前机器状态下，宿主下一步准备执行的动作，是否应该：

1. 继续
2. 打断
3. 留在当前 checkpoint
4. 取消当前 checkpoint
5. 改道到 consult / inspect

因此，本方案的核心设计对象应该是“action-in-context classifier”，而不是“全局意图分类器”。

## 发布面治理规则（Doc-1）

定位：

1. 本规则组用于公开方案包的去显性来源化治理。
2. 本规则组不并入 A-1 ~ A-8 的 runtime 语义收敛 case，不参与 parser / router 的行为判定逻辑。

### 1. 命名治理

1. 对当前仍被 `current_plan / current_run / current_decision / current_handoff` 任一活动状态引用的方案包，目录名、`plan_id`、`feature_key` 视为受控机器字段，不纳入 Doc-1 去显性来源化范围。
2. 展示层命名统一采用中性、能力导向写法，包括标题、正文术语、图示标签、示例标识、分支名等。
3. 若未来必须调整机器身份，只能走带备份、统一改写、校验与回滚的受控迁移，不得直接在文档侧手改。

### 2. 术语治理

1. 正文和图示优先使用通用术语，例如“外部参考实现经验”“动作语义投影接口”“独立侧路判定”。
2. 禁止出现可一一映射到单一第三方实现的专有标识串（产品名、仓库名、专有函数名、源码路径）。
3. 公开层只描述原则、机制、约束与验收，不描述“师承关系”。

### 3. 叙事治理

1. 统一写法为“我们的机制抽象与验证框架”，不采用“把某产品做法翻译到 Sopify”的叙事。
2. 若需保留来源细节，转移到私有研究笔记，不进入公开方案包。

### 4. 校验治理

1. 对当前方案包的展示层内容执行来源锚点 denylist 扫描并要求零命中。
2. 校验范围覆盖标题、正文、图示标签、示例标识、分支命名等展示层字段，不覆盖活动 plan 的目录名、`plan_id`、`feature_key`。

对外流通约束：`public-surface-governance` 合并前，本方案包仅限内部使用，不得向公司外部或外部合作方流通。

执行跟踪真相源：见 tasks.md §F.8。

## 从参考实现经验提炼出的设计模式

### 1. 规则优先

外部参考实现会先走拒绝规则、确认规则、工具级权限校验与安全检查，再进入自动分类器。模型只处理规则无法唯一决策的模糊区，不抢第一层决策权。

对 Sopify 的映射：

1. 先看 `allowed_response_mode`
2. 再看 `required_host_action`
3. 再看 `current_run.stage`
4. 再看 `checkpoint_request / execution_gate`
5. 只有硬事实不能唯一决定时，才进入局部语义判定

### 2. 局部语境压缩

参考实现中的分类输入只保留用户消息和结构化工具调用事件，刻意排除 assistant prose，避免模型被自己前文带偏。

对 Sopify 的映射：

局部分类输入不应直接使用整段聊天，而应压缩成：

1. 当前用户输入
2. 最近 1-3 条相关用户消息
3. 当前 pending checkpoint / execution gate 摘要
4. 当前允许动作集合
5. 当前 runtime 限制与长期偏好摘要

### 3. 动作语义投影

参考实现会通过动作语义投影接口，把每个工具的输入压缩成最小但足够的安全语义，而不是原样暴露所有参数。

对 Sopify 的映射：

局部分类器不直接吃完整 state JSON，而是按当前 checkpoint 做 action projection。例如：

- `confirm_plan_package`：
  - `checkpoint_kind`
  - `analysis_summary`
  - `proposed_path`
  - `estimated_task_count`
  - `allowed_actions=[confirm, inspect, revise, cancel, retopic]`
- `confirm_execute`：
  - `plan_path`
  - `risk_level`
  - `key_risk`
  - `mitigation`
  - `allowed_actions=[confirm, inspect, revise, cancel]`
- `continue_host_develop`：
  - `active_run_stage`
  - `task_refs`
  - `changed_files`
  - `verification_todo`
  - `allowed_actions=[continue, checkpoint, consult, block]`

### 4. 模型只参与独立侧路判定

参考实现中的模型参与点是独立侧路判定，而不是把主会话模型直接当分类器。并且它支持 fast / reasoning 两阶段，失败时可降级到人工确认。

对 Sopify 的映射：

即便后续引入 semantic classifier，也应满足：

1. 只判局部 ambiguity
2. 只返回结构化结果
3. 失败时 fail-close 或退回 inspect / 人工确认
4. 不把 side-classifier 变成新的主路由器

## Sopify 的鲁棒表驱动决策流水线 (Robust Table-Driven Decision Pipeline)

本节将风险自适应打断的理念，彻底下沉为 v1 可直接指导编码的三张真理表与一条固定流水线。
设计核心不是把自然语言硬解析成脆弱 AST，而是：**先用 machine facts 做强预检，再提取高置信度信号，随后查表裁决；若冲突或信息不足，则安全降级。**

所有表共用以下核心枚举与约束，确保全链路契约一致：
- `reason_code`: 统一词法规范 `[layer].[rule].[outcome][.qualifier]`
- `checkpoint_kind`: 表示当前拦截点的类型
- `resolved_action`: 归一化后的系统推断动作
- `prompt_mode`: 决定抛给宿主的交互形态
- `target_kind`: 信号旨在作用的目标槽位
- `evidence_tier`: 提取信号的置信度证据等级

### 流水线固定阶段

1. `Deterministic Guard`
   先读取 `allowed_response_mode / required_host_action / current_run.stage / checkpoint_request / execution_gate`，裁掉当前不可能执行的动作。
2. `Local Context Builder`
   只保留本轮判定真正需要的局部上下文，不把完整聊天和解释性 prose 直接下放。
3. `Signal Extraction + Action Projection`
   由 parser-first 主线抽取候选信号，并把当前 checkpoint 投影成稳定的动作面；vNext classifier 如存在，也只能在这一层产出候选信号。
4. `Signal Priority Table`
   对候选信号做优先级裁决与冲突消解，得到 `resolved_action` 或 `ambiguous`。
5. `Failure Recovery Table`
   若 Guard / Parser / Projection / Classifier 任一层无法稳定给出动作，则统一查失败恢复表，决定退守方式、熔断累计与宿主交互形态。
6. `Side-Effect Mapping Table`
   仅当 `resolved_action` 已经稳定时，才允许查副作用表，决定内部状态突变与宿主交接协议。

约束：

1. Parser 和未来 classifier 只负责产出候选信号或 `resolved_action`，不直接改写状态。
2. `Deterministic Guard` 永远在三张表之前执行，不能被信号裁决旁路。
3. 三张表是动作决策的真理来源，不是对 prose 说明的补充注释。

### 三张表的边界与跨切层

1. `Signal Priority Table / Failure Recovery Table / Side-Effect Mapping Table` 是语言无关、宿主无关的规范层，不承载中文/英文别名，也不承载某个宿主 UI 的差异。
2. locale 差异只允许出现在 `Signal Extraction` 层；无论是中文、英文还是后续其他语言，最终都必须回落到统一的 `signal_id / resolved_action / reason_code`。
3. 宿主差异只允许出现在 `Handoff / Output Adapter` 层；无论是终端、IDE 还是其他宿主，三张表与 `handoff_protocol` 的核心 schema 不应分叉。
4. parser-first v1 与未来 classifier 都必须消费同一套 action projection 和三张表；不允许为不同语言或不同宿主分别维护多套真理表。

### 0. P0 Freeze | 分层联动矩阵（最小冻结）

**定位：**

1. 本节冻结 Checkpoint A / P0 所需的跨层最小闭环，是三张表之前的前置约束。
2. 本节只冻结 truth 层、主失败裁决、`consult_readonly_contract` 与 `best_proven_resume_target`，不扩展成新的状态树。
3. `tasks.md` 的 `9.x / 10.x / 19.x` 以本节为共同规范源；`machine-contract-overview.md` 只保留导读与导航，不重复本节正文。

#### 0.1 Truth 层最小冻结

**硬不变量：**

1. `truth_status != stable` 时，禁止进入 action resolution mainline；但必须允许进入 failure recovery / blocking branch。
2. `quarantine` 默认只作为 annotation，不单独晋升为顶层 `truth_status`；只有切断活跃链证明时，才提升为 `state_missing` 或 `state_conflicted`。
3. `malformed_input / semantic_unavailable / context_budget_exceeded` 属于 failure family，不进入 truth 层。

| `truth_status` | 含义 | `resolution_enabled` | 默认宿主侧去向 |
| --- | --- | --- | --- |
| `stable` | 当前活跃链 machine truth 可由 `gate + snapshot + handoff` 稳定证明 | `true` | 沿当前 machine contract 继续；`allowed_response_mode` 仍由 gate contract 决定 |
| `state_missing` | 当前活跃链必需 carrier 缺失，或被 quarantine 后无法证明当前 checkpoint / route | `false` | 进入 failure recovery / blocking branch；默认不允许自动推进 |
| `state_conflicted` | 两个或以上可竞争 carrier 在 `durable identity / required_host_action / current_run.stage / checkpoint identity` 上互相冲突 | `false` | 进入 failure recovery / blocking branch；默认不允许自动推进 |
| `contract_invalid` | 决定当前合法动作面所必需的机器契约失效 | `false` | 进入 failure recovery / blocking branch；若 strict entry / gate contract 本身不可用，可升级到 `error_visible_retry` |

`quarantine_annotation` 最小字段冻结为：

- `state_kind`
- `path`
- `scope`
- `active_chain_relevance`
- `promotion_decision`
- `reason_code`
- `durable_identity_ref`

`quarantine_annotation` 的硬规则：

1. `snapshot` 是 annotation 的唯一真相源。
2. `handoff.artifacts` 只能回显 annotation，不得反向生成 annotation truth。
3. annotation 必须是 carrier-scoped；单个非活跃残留文件不得把整轮 truth 拉成假不稳定。

#### 0.2 主失败裁决优先级

**硬规则：**

1. 每轮只允许一个 `primary_failure_type` 驱动 fallback；其他失败原因只进入 `secondary_reason_codes` 做观测，不参与主裁决。
2. 主裁决优先级固定为：`non-stable truth > truth-layer contract_invalid > resolution failure > effect_contract_invalid`。
3. `effect_contract_invalid` 只在 `truth_status == stable` 后才可能成为 `primary_failure_type`；若 truth 已不稳定，它只能进入 `secondary_reason_codes`。

| 优先级 | `primary_failure_type` 家族 | 代表项 | 说明 |
| --- | --- | --- | --- |
| 1 | `non_stable_truth` | `state_missing`, `state_conflicted` | machine truth 优先于局部 resolution 与 effect |
| 2 | `truth_layer_contract_invalid` | `gate_contract_invalid`, `handoff_contract_invalid`, `checkpoint_contract_invalid`, `action_projection_contract_invalid` | 只覆盖决定当前合法动作面的机器契约失效 |
| 3 | `resolution_failure` | `no_match`, `ambiguous`, `malformed_input`, `semantic_unavailable`, `context_budget_exceeded` | 仅在 truth 已稳定时参与主裁决 |
| 4 | `effect_contract_invalid` | `schema_mismatch`, `version_mismatch`, `missing_required_field`, `unsupported_transition` | truth 已知，但 effect 层无法安全执行 |

#### 0.3 `consult_readonly_contract`（条件必需契约）

**定位：**

1. `consult_readonly_contract` 是独立 schema，由 `Side-Effect Mapping Table` 产出，并通过 `current_handoff.artifacts.consult_readonly_contract` 暴露给宿主消费。
2. 它是条件必需契约，不是全局必需契约。
3. 它只作为只读 consult 出口的受控证明，不替代 `gate + handoff` 的全局真相。

**P0 实施载体补充冻结：**

1. Signal/Failure/Side-Effect 三张真理表的正式物理载体路径固定为 `runtime/contracts/decision_tables.yaml`，不放入 `runtime/config/`。
2. 表资产的 schema 路线固定为“独立版本化 schema + runtime stdlib strict validator”；runtime 不引入非 stdlib 运行时依赖。
3. 与普通 checkpoint 主线隔离的忽略名单字段，命名固定为 `ignored_required_host_actions`，其语义绑定 `required_host_action`，不得再使用 `ignored_on_routes` 这类易误接命名。
4. `feature/context-boundary-core` 的首笔实现只允许作为 `tracked spike / non-checkpoint-credit / no runtime wiring` 的受控原型入库；其作用是固定资产与离线校验入口，不代表 Checkpoint A 或 boundary-core 已完成。
5. 当前 spike 仅冻结 P0 底座与失败恢复矩阵（`decision_tables + failure_recovery_table`）；`Signal Priority Table / Side-Effect Mapping Table` 的独立资产化与完整接线仍以后续 `9.1-9.4 / 18.3+` 为准。

**准入规则：**

1. 只有当 `Side-Effect Mapping` 明确改道到 `continue_host_consult`，或当前出口正在校验 consult 准入时，该合同才成为必需契约。
2. 合同存在且 schema 有效，才允许只读 consult 出口。
3. 在上述条件下，合同缺失或无效统一并入 `truth-layer contract_invalid`，并回到 fail-close。
4. 在普通 `confirm_* / answer_questions / review_or_execute_plan` 主线中，合同缺失必须被忽略，不得污染普通 checkpoint truth。

**最小字段冻结：**

| 字段 | 角色 | 约束 |
| --- | --- | --- |
| `required_host_action` | echoed assertion | 固定为 `continue_host_consult` |
| `allowed_response_mode` | echoed assertion | 固定为 `normal_runtime_followup` |
| `resume_route` | echoed assertion | 必须由 machine contract 产出 |
| `preserved_identity` | echoed assertion | 表示只读出口必须保留的 `plan / checkpoint / decision` 身份锚点 |
| `context_sufficiency` | consult-local constraint | 必须达到 `sufficient` 才允许宿主作答 |
| `forbidden_effects` | consult-local constraint | 至少禁止 `checkpoint_submission / run_stage_advance / plan_materialization / execution` |

补充约束：

1. `eligible` 不作为独立字段冻结；“合同存在且 schema 有效”本身就代表准入成立。
2. 宿主不得因为“语义感觉像咨询”就自由 prose 降级；只有合同显式放行才可答。

#### 0.4 `best_proven_resume_target`（evidence-first 恢复目标）

**硬规则：**

1. 恢复目标必须由 `durable identity + resume_route` 证明，不得由 transcript、时间最近原则或宿主 prose 猜测恢复。
2. `resume_target_kind` 的 P0 最小枚举固定为：`checkpoint | plan_review | workflow_safe_start`。
3. 若同时存在两个或以上可证明恢复目标，直接进入 `state_conflicted`，不得“择近”或“择优”猜恢复。

| 证明顺序 | `resume_target_kind` | 最小证明 |
| --- | --- | --- |
| 1 | `checkpoint` | `current_handoff.required_host_action + matching checkpoint state + durable identity` 可直接证明当前活跃 checkpoint |
| 2 | `checkpoint` | `current_run.stage + matching durable identities` 可在 handoff 证明缺失时证明安全 checkpoint |
| 3 | `plan_review` | `current_handoff.required_host_action == review_or_execute_plan` 且 `current_handoff.plan_id == current_plan.plan_id` 且 `current_handoff.plan_path == current_plan.path`，并且 `gate/snapshot` 证明它是当前可恢复入口，而不是宿主自由回退 |
| 4 | `workflow_safe_start` | 上述证明不足，但 machine contract 仍能产出安全 workflow 入口 |

补充约束：

1. `review_or_execute_plan` 默认归类为 `plan_review`，仅在 durable proof 不足时退回 `workflow_safe_start`。
2. `plan_review` 证明不足时，禁止宿主脑补“反正像是在 review plan”。

#### 0.4.1 no-progress fuse 键冻结补充

1. `same checkpoint no-progress streak` 的聚合键，P0 默认冻结为 `checkpoint_id + unresolved_outcome_family + durable_identity`。
2. 其中 `unresolved_outcome_family` 作为稳定聚合维度，优先于更细粒度的 outcome 文本，避免后续 outcome 细化导致 streak key 抖动。
3. 若未来需要在 family 之下继续细分，只允许作为观测维度追加，不得回写破坏 P0 streak 主键。

#### 0.5 P0 适用边界与非目标

1. 本节只冻结跨层最小闭环，不冻结 continuity / projection 的计划语境连续性层。
2. 本节不新增顶层 `truth_status`，也不把 `quarantine`、`legacy_ignored`、`contract_recovered` 扩成新的状态树。
3. 本节不允许任何 transcript-based recovery；所有恢复都必须回到 machine contract 可证明的 target。

### 1. 信号优先级表 (Signal Priority Table)

**作用：** 解决自然语言混合输入时“这句话到底算 cancel、consult、status、revise 还是 confirm”的冲突判定。
**同级冲突判定规则：** 只有当两个信号同时满足“同优先级 + 同 `target_slot` + `mutually_exclusive_with` 命中 + `evidence_tier` 相当”时，才判定为 `ambiguous`。若优先级相同但 `target_slot` 不同且可并存，则允许共同存在；若证据等级不同，则高证据等级优先。

**最小可编码 Schema：**
- `signal_id`: string (唯一信号名，如 cancel_checkpoint)
- `signal_group`: enum (hard_stop | hard_constraint | inspect_request | route_shift | progress_action)
- `target_kind`: enum (checkpoint | plan | execution | host_action | write_scope)
- `target_slot`: string (更细粒度的目标槽位，如 checkpoint_lifecycle | host_route | execution_write_scope)
- `evidence_tier`: enum (literal_alias | explicit_pattern | local_clause_inference | weak_semantic_hint)
- `priority`: int (数值优先级，严格排序)
- `scope`: enum (global | current_clause | current_checkpoint)
- `mutually_exclusive_with`: [signal_id] 
- `suppresses`: [signal_id] (它能压制哪些信号)
- `can_coexist_with`: [signal_id] 
- `winner_action`: enum (归一化后的目标动作，如 cancel_current_checkpoint)
- `fallback_on_conflict`: enum (ambiguous | inspect | explicit_choice_required)
- `reason_code`: string (如 `signal.hard_stop.cancel_overrides_progress`)

**首批样例行（v0.1）：**

| case_ref | signal_id | signal_group | target_kind | target_slot | evidence_tier | priority | suppresses | winner_action | reason_code |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| normal_status_inspect | `inspect_current_checkpoint_status` | `inspect_request` | `checkpoint` | `checkpoint_view` | `literal_alias` | 70 | `[]` | `stay_in_checkpoint_and_inspect` | `signal.inspect_request.status_to_inspect` |
| A-8_analysis_only_no_write | `analysis_only_no_write_brake` | `hard_constraint` | `write_scope` | `materialize_or_execute` | `explicit_pattern` | 80 | `[continue_current_checkpoint, continue_execute, submit_revision_feedback]` | `switch_to_consult_readonly` | `signal.hard_constraint.analysis_only_routes_consult_readonly` |
| normal_confirm | `continue_current_checkpoint` | `progress_action` | `checkpoint` | `checkpoint_lifecycle` | `literal_alias` | 50 | `[]` | `continue_checkpoint_confirmation` | `signal.progress_action.continue_to_confirmation` |
| cancel_dominates_progress | `cancel_current_checkpoint` | `hard_stop` | `checkpoint` | `checkpoint_lifecycle` | `literal_alias` | 90 | `[continue_current_checkpoint]` | `cancel_current_checkpoint` | `signal.hard_stop.cancel_overrides_progress` |

说明：

1. `normal_confirm` 与 `cancel_dominates_progress` 共享 `target_slot=checkpoint_lifecycle`，但优先级不同，因此不进入 `ambiguous`，而是由 `cancel_current_checkpoint` 直接压制。
2. A-8 将 `analysis-only / no-write` 固定为 brake signal，默认压住推进型动作，并在 pending checkpoint 场景改道 `consult_readonly`。
3. `consult_readonly` 只允许输出分析，不得提交决策、不得推进 stage、不得物化 plan 或触发执行。

### 1.1 Signal Priority Table 接线规范 v0.1

**定位：**

1. 本规范只定义候选信号如何接入《信号优先级表》并完成冲突裁决。
2. classifier 只能输出候选信号，不能直接输出 `resolved_action` 或发起状态突变。
3. 规则优先权必须写成显式裁决顺序，而不是依赖隐含 prompt 约定。

**上游输入契约：**

所有来源都必须先归一成同一份 `CandidateSignal`：

```yaml
CandidateSignal:
  signal_id: string
  signal_origin: deterministic_rule | parser_clause_inference | semantic_classifier
  checkpoint_kind: string
  target_kind: checkpoint | plan | execution | host_action | write_scope
  target_slot: string
  signal_group: hard_stop | hard_constraint | inspect_request | route_shift | progress_action
  scope: current_clause | current_checkpoint | global
  evidence_tier: literal_alias | explicit_pattern | local_clause_inference | weak_semantic_hint
  confidence_band: high | medium | low | none
  reason_code: string
```

**表行扩展 Schema：**

```yaml
SignalPriorityRow:
  signal_id: string
  enabled_checkpoint_kinds: [string]
  signal_group: hard_stop | hard_constraint | inspect_request | route_shift | progress_action
  target_kind: checkpoint | plan | execution | host_action | write_scope
  target_slot: string
  allowed_origins:
    - deterministic_rule
    - parser_clause_inference
    - semantic_classifier
  origin_evidence_cap:
    deterministic_rule: literal_alias | explicit_pattern | local_clause_inference | weak_semantic_hint
    parser_clause_inference: local_clause_inference | weak_semantic_hint
    semantic_classifier: weak_semantic_hint
  mutually_exclusive_with: [signal_id]
  can_coexist_with: [signal_id]
  suppresses: [signal_id]
  priority: integer
  winner_action: string
  fallback_on_conflict: ambiguous | inspect | explicit_choice_required
  reason_code: string
```

**全局固定排序：**

```yaml
origin_precedence:
  deterministic_rule: 300
  parser_clause_inference: 200
  semantic_classifier: 100

evidence_rank:
  literal_alias: 400
  explicit_pattern: 300
  local_clause_inference: 200
  weak_semantic_hint: 100
```

**classifier 接线硬约束：**

1. classifier 只允许在 `recovery_decision=eligible_for_semantic_escalation` 后被调用。
2. classifier 输出必须满足 `signal_origin=semantic_classifier`，且 `evidence_tier` 在 v0.1 固定上限为 `weak_semantic_hint`。
3. classifier 只能输出当前 `checkpoint_kind` 下、且 `allowed_origins` 包含 `semantic_classifier` 的 `signal_id`。
4. classifier 缺失 `signal_id / checkpoint_kind / target_slot` 任一关键字段，视为无效输出并直接回原 fail-close。

**接线流程：**

1. `Deterministic Guard` 先裁掉当前不合法动作。
2. parser / classifier 统一产出 `CandidateSignal[]`。
3. 裁决器先做表匹配，只保留 `enabled_checkpoint_kinds` 命中、`allowed_origins` 允许、且 `evidence_tier` 未超过 `origin_evidence_cap` 的候选。
4. 以 `target_slot` 为冲突域分桶；只有同 `target_slot` 且命中 `mutually_exclusive_with` 时，才进入冲突裁决。
5. 冲突裁决顺序固定为：`origin_precedence -> evidence_rank -> priority`。
6. 若仍无法唯一决策，统一落入 `fallback_on_conflict`，不得让 classifier 补猜最终动作。

**输出契约：**

```yaml
SignalPriorityResolution:
  resolution_status: resolved | ambiguous | no_candidate
  primary_signal_id: string | null
  resolved_action: string | null
  applied_constraints: [signal_id]
  suppressed_signals: [signal_id]
  winning_reason_code: string
```

**v0.1 铁律：**

1. 规则信号永远压制 classifier 信号。
2. classifier 只能发候选信号，不能发最终动作。
3. 一旦同槽位冲突仍无法唯一化，必须 fail-close，不能因为 classifier 给了答案就推进。

> 收敛依据：v1 收敛以 Checkpoint B 为准。完整口径见本文档 §Checkpoint B。

### 2. 失败恢复表 (Failure Recovery Table)

**作用：** 解决判定失败（无法识别、冲突、状态缺失等）时，系统如何安全退守并避免陷入死循环。

**求值顺序：**

1. 先根据 `failure_type + source_layer` 命中基础恢复行，得到基础 `fallback_action`。
2. 再根据 `counts_toward_streak` 与当前 streak 计数，决定是否升级到 `soft_warning_action` 或 `fuse_blown_action`。
3. `fallback_action` 决定状态级退守方向，`prompt_mode` 决定宿主如何交互；熔断只允许升级交互强度，不允许降低 fail-close 等级。

**最小可编码 Schema：**
- `failure_type`: string (如 no_match, ambiguous, state_missing)
- `source_layer`: enum (guard | parser | projection | classifier | state_guard)
- `recoverability`: enum (deterministic_permanent | transient_retryable | user_recoverable)
- `fallback_action`: enum (inspect | stay_blocked | explicit_choice_required | visible_error)
- `prompt_mode`: enum (free_text_hint | constrained_choice_required | hard_block_until_choice)
- `visible_error`: bool (是否需要显式报错给宿主用户)
- `counts_toward_streak`: bool (是否计入无进展熔断)
- `soft_warning_action`: enum (none | free_text_hint)
- `fuse_blown_action`: enum (none | constrained_choice_required | hard_block_until_choice)
- `reset_streak_when`: [enum] (如 checkpoint_changed | explicit_choice_submitted | state_progressed)
- `retry_policy`: enum (no_retry | host_retry_allowed | user_rephrase_only)
- `reason_code`: string (如 `recovery.transient.ambiguous.inspect`)

**首批样例行（v0.1）：**

| case_ref | failure_type | source_layer | recoverability | fallback_action | prompt_mode | counts_toward_streak | soft_warning_action | fuse_blown_action | reset_streak_when | retry_policy | reason_code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A-5_mixed_clause_conflict | `ambiguous` | `parser` | `user_recoverable` | `inspect` | `free_text_hint` | `true` | `free_text_hint` | `constrained_choice_required` | `[checkpoint_changed, explicit_choice_submitted, state_progressed]` | `user_rephrase_only` | `recovery.user_recoverable.ambiguous.inspect` |
| missing_runtime_state | `state_missing` | `state_guard` | `deterministic_permanent` | `stay_blocked` | `hard_block_until_choice` | `false` | `none` | `none` | `[]` | `no_retry` | `recovery.deterministic.state_missing.blocked` |
| vnext_classifier_budget_exceeded | `context_budget_exceeded` | `classifier` | `deterministic_permanent` | `inspect` | `free_text_hint` | `false` | `none` | `none` | `[checkpoint_changed, state_progressed]` | `no_retry` | `recovery.deterministic.context_budget_exceeded.inspect` |

说明：

1. `A-5_mixed_clause_conflict` 是当前 parser-first v1 最典型的用户可恢复失败：先退回 `inspect`，再由 streak 逻辑决定是否升级为 `constrained_choice_required`。
2. `state_missing` 属于 machine-fact 不足，不应靠自由重试或模型补猜恢复。
3. `context_budget_exceeded` 主要为 vNext classifier 预留；当前样例固定为 deterministic failure，不做自动重试。

> 收敛依据：v1 收敛以 Checkpoint B 为准。完整口径见本文档 §Checkpoint B。

### 3. 结果副作用映射表 (Side-Effect Mapping Table)

**作用：** 保护 Runtime 状态不被破坏。直接定义规范化动作对应的内部状态突变权限和宿主交接协议。

**分层原则：**

1. `state_mutators` 只描述内部持久化状态如何 `preserve / clear / update / write`。
2. `handoff_protocol` 只描述对宿主暴露的 `required_host_action / artifacts / resume_route / output_mode`。
3. `current_handoff.json` 虽然落盘，但在设计上视为宿主交接协议层，不与普通 state 文件混为一层。

**最小可编码 Schema：**
- `resolved_action`: enum (如 stay_in_checkpoint_and_inspect)
- `checkpoint_kind`: enum (必须复用现有 runtime contract 的拦截点类型；如 `confirm_plan_package | confirm_execute | confirm_decision | answer_questions | continue_host_develop | continue_host_consult`)
- `state_mutators`:
  - `preserve`: [state_key]
  - `clear`: [state_key]
  - `update`: [state_key]
  - `write`: [state_key]
- `forbidden_state_effects`: [string] (如 "不得清 current_decision")
- `preserved_identity`: [identity_key] (需保留的身份锚点，如 checkpoint_id, plan_id)
- `handoff_protocol`:
  - `required_host_action`: enum (必须复用现有 handoff contract 的值；如 `confirm_decision | answer_questions | continue_host_develop | continue_host_consult`)
  - `artifact_keys`: [string] (需要附带的 artifacts 字段)
  - `resume_route`: string (恢复路由)
  - `output_mode`: enum (inspect_only | checkpoint_only | consult_answer | continue_develop)
- `terminality`: enum (non_terminal | checkpoint_terminal | route_terminal)
- `reason_code`: string (如 `effect.state_guard.decision_preserved`)

**首批样例行（v0.1）：**

```yaml
- case_ref: normal_status_inspect
  resolved_action: stay_in_checkpoint_and_inspect
  checkpoint_kind: confirm_plan_package
  state_mutators:
    preserve: [current_plan_proposal, current_run]
    clear: []
    update: []
    write: []
  forbidden_state_effects:
    - materialize_new_plan_package
    - clear_current_plan_proposal
    - advance_to_develop
  preserved_identity: [checkpoint_id, reserved_plan_id, topic_key]
  handoff_protocol:
    required_host_action: confirm_plan_package
    artifact_keys: [checkpoint_request, proposal]
    resume_route: plan_proposal_pending
    output_mode: inspect_only
  terminality: checkpoint_terminal
  reason_code: effect.checkpoint.inspect_preserve_proposal

- case_ref: proposal_revision_feedback
  resolved_action: submit_revision_feedback
  checkpoint_kind: confirm_plan_package
  state_mutators:
    preserve: [current_run]
    clear: []
    update: [current_plan_proposal]
    write: []
  forbidden_state_effects:
    - materialize_new_plan_package
    - clear_current_plan_proposal
    - rewrite_reserved_plan_id
  preserved_identity: [checkpoint_id, reserved_plan_id, topic_key]
  handoff_protocol:
    required_host_action: confirm_plan_package
    artifact_keys: [checkpoint_request, proposal]
    resume_route: plan_proposal_pending
    output_mode: checkpoint_only
  terminality: checkpoint_terminal
  reason_code: effect.checkpoint.revise_preserve_identity

- case_ref: analysis_only_brake_to_consult
  resolved_action: switch_to_consult_readonly
  checkpoint_kind: confirm_decision
  state_mutators:
    preserve: [current_decision, current_run]
    clear: []
    update: []
    write: []
  forbidden_state_effects:
    - submit_decision_selection
    - clear_current_decision
    - materialize_new_plan_package
    - advance_to_develop
  preserved_identity: [checkpoint_id, decision_id, plan_id]
  handoff_protocol:
    required_host_action: continue_host_consult
    artifact_keys: [checkpoint_request, decision_checkpoint, decision_submission_state]
    resume_route: decision_pending
    output_mode: consult_answer
  terminality: route_terminal
  reason_code: effect.hard_constraint.analysis_only_consult_readonly

- case_ref: execution_confirmed_to_develop
  resolved_action: continue_checkpoint_confirmation
  checkpoint_kind: confirm_execute
  state_mutators:
    preserve: [current_plan]
    clear: []
    update: [current_run]
    write: []
  forbidden_state_effects:
    - recreate_execution_confirm_checkpoint
    - mutate_plan_identity
  preserved_identity: [plan_id]
  handoff_protocol:
    required_host_action: continue_host_develop
    artifact_keys: [execution_summary, execution_gate]
    resume_route: develop
    output_mode: continue_develop
  terminality: route_terminal
  reason_code: effect.execution.confirm_to_develop
```

说明：

1. 首批样例优先覆盖”保留 proposal / 修订 proposal / analysis-only 改道只读 consult / 从 execution confirm 进入 develop”四种最常见状态转移。
2. `state_mutators` 与 `handoff_protocol` 故意分层书写，避免把内部状态变更与宿主动作混成同一类副作用。
3. `analysis-only` 改道 `consult_readonly` 已拍板并进入首批样例行；`plan_proposal_pending + command prefix` 与 A-6 归属也已完成 Checkpoint A 口径拍板。

> 收敛依据：v1 收敛以 Checkpoint B 为准。完整口径见本文档 §Checkpoint B。

## 推荐实施路线 (Pipeline Workflow)

### Phase 0 | 当前 plan 的职责

先完成设计收敛，不写代码。

输出：

1. 已冻结约束清单
2. 语义类矩阵
3. 候选架构
4. 实施前 acceptance gate

### Phase 1 | parser-first v1

推荐先走 parser / structural semantics 收口已知样本，不直接引入 side classifier。

适用范围：

1. A-1 explain-only
2. A-3 existing plan referent
3. A-4 cancel checkpoint
4. A-5 mixed clause after comma
5. A-8 explicit no-write + process semantic
6. A-6 execution-confirm / state-conflict evidence gate

冻结口径：

1. `A-1 / A-3 / A-4 / A-5 / A-6 / A-8` 构成当前 v1 implementation gate。
2. `A-7` 继续作为已冻结回归基线保留，必须持续通过，但不再作为新一轮语义扩写入口。
3. `A-2` 归入 `V1.x parser robustness backlog`，用于后续稳健性增强，不作为当前 v1 开工门禁。
4. v1 必须为主要决策路径产出完整的 `signal.* / recovery.* / effect.*` 三层 `reason_code`，否则后续 rollout 无法判定 residual ambiguity 是否值得进入 classifier。

原因：

1. 与当前总纲冻结的“parser 层优先收口”原则一致
2. 兼容既有对外 contract 主线
3. 更容易做确定性回归与副作用断言

### Phase 1.5 | rollout / observability

在 parser-first v1 之后，先做一轮只观察、不扩面的 rollout。

观察重点：

1. `ambiguous_rate / fail_close_rate / manual_resolution_rate / streak_fuse_rate`
2. `signal.* / recovery.* / effect.*` 是否能串起完整行为链
3. 剩余问题到底是“边界未定义”，还是“边界已定义但 parser 提取能力不足”

### Phase 2 | guarded hybrid classifier

只有在以下条件都满足后，才考虑引入 semantic side classifier：

1. 既有 control-plane 契约主线已稳定，且 parser-first v1 已通过当前 acceptance gate
2. rollout 证明剩余问题确实集中在 residual ambiguity，而不是边界未定义或副作用契约未冻结
3. 已建立稳定的 `Local Context Builder + Action Projection + Failure Recovery` 契约，以及对应 replay/eval 机制
4. side-classifier 只返回结构化候选信号与 `reason_code`，不能旁路 `Deterministic Guard`、不能绕开三张表、也不能直接写状态

## 当前推荐结论

本子 plan 的推荐路线为：

1. v1 不直接照搬外部参考实现中的侧路语义分类机制
2. 先把参考实现中的设计模式翻译成 Sopify 的分层原则
3. 实现阶段优先选择 `deterministic guard + local context + action projection + parser-first closure`
4. 把 semantic side classifier 保留为本方案的二阶段增强选项

## 分支拆分、分批合并与 Checkpoint 卡点

默认沿用 `main + topic branches` 的分批合并策略；topic 分支级通过不等于可直接进入下一阶段实施。每个分支都必须绑定 checkpoint 卡点，未满足则 fail-close。

| 顺序 | 建议分支 | 承载任务 | 目标 |
| --- | --- | --- | --- |
| 1 | `feature/context-boundary-core` | `1.1-1.3`、`2.1-2.2`、`9.1-9.7`、`10.1-10.6`、`11.1-11.3` | 冻结 V1 的边界、fail-close contract、三张表结构与失败矩阵 |
| 2 | `feature/public-surface-governance` | `8.1-8.4` | 并行完成公开发布面的去显性来源化治理 |
| 3 | `feature/context-v1-guard-rails`（4a） | `3.1-3.4`、`4.1-4.3`、`17.1-17.3`、`18.1-18.6`、`19.1-19.5` | 先落物理防线：范围守卫、真理表资产、模板安全、legacy quarantine 出口 |
| 4 | `feature/context-sample-invariant-gate` | `5.1-5.3`、`6.1-6.6`、`16.1-16.5` | 用 A-1~A-8（含历史错例）完成三张表可填平验证与状态不变量断言 |
| 5 | `feature/context-v1-scope-finalize`（4b） | `7.1-7.4`、`17.4` | 基于样本压测结果锁定 v1 file map/模块白名单与 rollout/rollback 口径 |
| 6 | `feature/context-vnext-gate` | `4.4`、`12.1-12.4`、`13.1-13.4` | 冻结 vNext 升级条件、预算门槛与回滚信号（不把 classifier 主链上线） |

依赖关系：

1. `boundary-core` 先行。
2. `public-surface-governance` 可与 `boundary-core` 并行。
3. `v1-guard-rails(4a)` 依赖 `boundary-core`，并作为样本压测前的物理防线。
4. `sample-invariant-gate` 必须在已合入 `4a` 的基线上执行，不允许裸奔压测。
5. `v1-scope-finalize(4b)` 依赖 `sample-invariant-gate` 的压测结论。
6. `vnext-gate` 依赖 `4b` 的 v1 稳定基线观测。

## Checkpoint 强卡点（A-D）

### Checkpoint A | 边界与决策口径冻结

进入条件：`feature/context-boundary-core + feature/context-v1-guard-rails` 准备合并。

必填决策：

1. `plan_proposal_pending + command prefix` 的最终动作口径冻结为“保持显式 fail-close，不视为自动继续信号”。
2. A-6 归属冻结为“继续留在本方案，不拆出 contract-safety 子项”。
3. `P0 Freeze` 的 truth / failure / consult-readonly / resume-target 边界，以及 fail-close 默认动作矩阵版本与 `reason_code` 词法冻结。
4. 三张真理表资产化与 Schema 冻结（`runtime/contracts/decision_tables.yaml` + 独立版本化 schema + runtime stdlib strict validator + CI 校验）完成。
5. `reason_code -> host_facing_message_template` 与插值安全校验冻结，模板渲染失败必须 fail-open 到安全兜底文案。
6. legacy pending state 的 quarantine / escape hatch / 审计事件冻结，禁止因 schema 不兼容直接 crash。

未满足处理：禁止进入样本矩阵压测与 v1 scope finalize。

### Checkpoint B | 样本矩阵与不变量可填平

进入条件：`feature/context-sample-invariant-gate` 准备合并。

必填决策：

1. A-1~A-8 每个样本唯一映射到 `resolved_action + reason_code + side_effect_profile`。
2. 历史错例强制代入三张表后无“表格填不平”残留。
3. A-6 独立证据链与普通 parser case 解耦。
4. 压测结果必须建立在已合入 `4a guard-rails` 的基线上。
5. `check-fail-close-contract` 已升级为 pytest 数据驱动入口并接入 CI 回归。

未满足处理：禁止进入 `v1-scope-finalize(4b)` 与 `Ready-for-V1-Execution`。

### Checkpoint C | v1 实施范围锁死

进入条件：`feature/context-v1-scope-finalize` 准备合并。

必填决策：

1. v1 implementation file map 与模块白名单冻结。
2. 运行态范围锁死骨架完成（常量注册表 + 守卫测试），超范围改动必须失败。
3. rollout / rollback 与既有对外 contract 主线的 compatibility 口径冻结。
4. 仅允许在 Checkpoint B 已通过后执行白名单最终锁定。

未满足处理：禁止从设计收敛切到开发实施。

### Checkpoint D | vNext 升级门槛冻结

进入条件：`feature/context-vnext-gate` 准备合并。

必填决策：

1. 价值门：残余 ambiguity 的收益阈值（质量改善）冻结。
2. 预算门：`tokens / latency / cost / stage1_vs_stage2` 上限冻结。
3. 安全门：`classifier_no_value_rate / projection_reject_after_classifier_rate / effect_reject_after_classifier_rate` 回滚阈值冻结。
4. 结构门：classifier 只回流候选信号与 `reason_code`，不得旁路 Guard/三张表，且不得直接写状态。

未满足处理：不得切换到 `hybrid classifier vNext`，但不阻断 v1 执行主链。

## 分层阻断口径（正式冻结）

1. `Ready-for-V1-Execution`（阻断 V1）：
   必须通过 Checkpoint A/B/C；Checkpoint D 不是 V1 前置条件。
2. `Ready-for-V2-Trial`（阻断 V2，不阻断 V1）：
   必须通过 Checkpoint D，且已具备 v1 rollout 证据（残余 ambiguity 收敛收益、预算与回滚阈值可审计）。
3. classifier 定位：
   `v2` 仅为 guarded side path，不是主链路替换，不允许旁路 Guard/三张表。

## 已拍板产品行为

1. 命中 `analysis-only / no-write / no-package` 且处于 pending checkpoint 时，默认改道到 `consult_readonly`。
2. `consult_readonly` 固定为只读分析出口：不提交 checkpoint 选项、不推进 run stage、不物化 plan、不触发执行。
3. 宿主侧动作只能沿 `required_host_action` 继续；machine truth 不允许时，必须继续停留在当前 checkpoint 链并保持 fail-close，不得自动推进。仅在稳定只读可答时，才允许降级到 `continue_host_consult / consult_readonly`，且该出口只读、不提交、不推进、不执行；其余未唯一化场景仍停留在 `inspect / explicit_choice_required / stay_blocked` 等安全槽位。
4. 当 gate contract 满足 `status=ready` 且 `gate_passed=true` 时，宿主对外响应默认复用 Sopify 标准标题/footer 模板；`allowed_response_mode` 只影响正文类型与下一步提示，不影响是否套用模板。
5. 若输入同时包含显式推进动作（如 `continue`、`1/2`、`option_x`、`cancel`），仍按 checkpoint 决策链处理，不走只读咨询降级。
6. `plan_proposal_pending + command prefix` 不视为自动继续信号，保持显式 fail-close；用户必须先完成当前 checkpoint 的确认或修订。

## 已拍板范围归属

1. A-6 继续留在本方案，作为 v1 gate 成员之一处理，不拆出单独的 `contract-safety` 子项。
2. 因此 Checkpoint A 上与 `plan_proposal_pending + command prefix`、A-6 归属相关的开放问题已清零。

**A-6 当前冻结口径：** 留在本方案（v1 gate 成员，见 §Phase 1 冻结口径）。后续若未来另起子项，视为新的范围决策，不回溯改写本轮 Checkpoint A 结论。

### Ready-for-V2-Trial（v1 上线后再确认，阻断 V2，不阻断 V1）

1. semantic side classifier 在 Sopify v1 不进入实现范围，仅作为 v2 试点项（Checkpoint D）
2. v2 试点价值门/预算门/安全门阈值的冻结值与回滚线最终拍板（Checkpoint D）

## Acceptance Gate（分层）

### Ready-for-V1-Execution 必须满足

1. A-1 ~ A-8 已完成按语义类分组与优先级排序
2. `required_host_action / checkpoint_id / current_plan_proposal / current_decision / plan/` 的禁止副作用断言已冻结
3. `ExecutionGate` 核心字段与 reason code 兼容性检查已冻结
4. `plan_proposal_pending + command prefix` 的产品决策已明确
5. `analysis-only` 的只读咨询降级规则已冻结，并完成 A-1 ~ A-8 沙盘映射不变量检查
6. 已明确“v1 parser-first，v2 再评估 hybrid classifier”的阶段策略
7. Checkpoint A/B/C 已通过且留痕完整（PR 必填字段、commit trailer、CI 强检记录）

### Ready-for-V2-Trial 必须满足

1. Checkpoint D 已通过且留痕完整
2. 已建立 v1 rollout 证据链，证明 residual ambiguity 改善值得进入 v2
3. `tokens / latency / cost / stage1_vs_stage2` 与回滚阈值冻结
4. classifier 仍受 Guard + 三张表约束，不得成为主链替换路由
