---
plan_id: 20260403_plan-a-risk-adaptive-interruption
feature_key: plan-a-risk-adaptive-interruption
level: standard
lifecycle_state: active
knowledge_sync:
  project: review
  background: review
  design: review
  tasks: review
blueprint_obligation: review_required
archive_ready: false
plan_status: design_active
---

# 任务清单: 局部语义收口方案 | 风险自适应打断与局部语义分类收敛

## 当前状态

- 本 plan 当前只用于设计收敛，不进入代码实施。
- `ExecutionGate` 当前保持 `blocked / missing_info` 是预期行为，因为本 plan 仍在收口实施边界。
- 后续允许持续迭代 `background.md / design.md / tasks.md`，直到进入真正开工窗口。
- 在进入正式 implementation 之前，允许先做一笔文档 freeze patch 与一笔 `feature/context-boundary-core` 受控 spike；该 spike 身份固定为 `tracked spike / non-checkpoint-credit / no runtime wiring`，不计入任何 Checkpoint 完成。

**导航：** Checkpoint A 前的颗粒度补齐范围，以 design.md §分支拆分、分批合并与 Checkpoint 卡点 和各 Checkpoint 必填决策为准；本任务清单各条任务是执行真相源。

**解锁索引（导航，非第二份真相源）：**

| 解锁目标 | 前置条件 | 当前状态 |
|---------|---------|---------|
| Ready-for-V1-Execution | boundary-core + v1-guard-rails + sample-invariant-gate + v1-scope-finalize \| Checkpoint A/B/C | ⬜ 未就绪 |
| Ready-for-V2-Trial | v1 rollout 观察期 + vnext-gate \| Checkpoint D（不阻断 V1） | ⬜ 未就绪 |

## A. 已承接的冻结决策

- [x] A.1 本方案现在进入正式子 plan 窗口，前置依据是 program plan 中的 `3.2 -> 3.3`
- [x] A.2 本方案只承接 host-facing recall debt，不重开既有 correctness hotfix 主线
- [x] A.3 仅在局部 checkpoint / execution gate 语境下增强召回
- [x] A.4 默认不修改 `ExecutionGate` v1 核心字段与 `gate_status` 值集
- [x] A.4.1 新引入的 `reason_code` 词法、streak 统计与相关扩展字段只能以非破坏性扩展附加，绝不污染或覆盖既有 `ExecutionGate / gate_status` 核心契约
- [x] A.5 默认与既有对外 contract 主线保持兼容
- [x] A.6 不接受“单词/短语补丁式”修复；修复必须在统一决策契约层收口，不得通过孤立词规则或局部 parser 特判绕过统一裁决链
- [x] A.7 A-7 `question signal + retopic signal + plan referent` 已作为回归基线冻结
- [x] A.8 当前 plan 的职责是设计收敛，不是立即实施局部语义分类器
- [x] A.9 决断失败或遭遇不可调和冲突时，必须统一实施 Fail-Close；默认降级到 `inspect / stay_blocked / explicit_choice_required`，禁止任何形式的隐式推进
- [x] A.10 坚持信号解析与状态突变的物理隔离；Parser / classifier 只允许输出规范化动作与依据，所有写操作必须后置到 `Side-Effect Mapping Table`
- [x] A.11 `Deterministic Guard` 必须先于信号解析与任何 classifier 执行，不允许被 parser、classifier 或局部规则旁路

## B. 背景与范围收敛

> 导航：本组任务构成 boundary-core 分支的输入，是 Checkpoint A 的前置条件（非被其阻塞）。

### 1. carry-over recall debt

- [ ] 1.1 把总纲中的 A-1 ~ A-8 重新分组为语义类簇，而不是逐 case 平铺
- [ ] 1.2 为每个语义类簇补齐“为何属于本方案，而不是既有 correctness hotfix 主线 / 既有对外 contract 主线”的边界说明
- [ ] 1.3 把 `analysis-only / no-write / no-package` 统一冻结成 brake signal 语义，而不是散落样本描述

验收标准：

- 每个 case 都能落入稳定语义类
- 不再出现“这是 parser hotfix 还是本方案 recall debt”边界含混

### 2. non-goals 与行为边界

- [ ] 2.1 显式补齐本子 plan 的 non-goals 清单
- [x] 2.2 已拍板：`plan_proposal_pending + command prefix` 保持显式 fail-close，不视为自动继续；并与 parser 收口任务解耦
- [x] 2.3 已拍板：`analysis-only / no-write / no-package` 在各类 pending checkpoint 下默认出口为 `consult_readonly`（只分析，不执行）
- [x] 2.4 已拍板：宿主侧动作只能沿 machine contract 已显式收敛出的 `required_host_action` 继续；machine truth 不允许时，必须继续停留在当前 checkpoint 链并保持 fail-close，不得自动推进
- [x] 2.5 已拍板：唯一允许的可回答型最终降级，仅限稳定只读可答场景，出口为 `continue_host_consult / consult_readonly`；该出口只读，不提交 checkpoint、不推进 run stage、不物化 plan、不触发执行
- [x] 2.6 已拍板：当 gate contract 满足 `status=ready` 且 `gate_passed=true` 时，宿主对外响应默认复用 Sopify 标准标题/footer 模板；`allowed_response_mode` 只影响正文类型与下一步提示，不影响是否套用模板

验收标准：

- 本 plan 中不再把产品行为拍板项混入 parser 设计任务
- 同一问题不会同时出现在“已定约束”和“待决问题”
- `analysis-only` 刹车后进入 `consult_readonly` 时，`current_decision/current_plan_proposal/current_run.stage` 保持不变
- 宿主后续动作不存在“未闭环时自动继续”的隐式出口
- `continue_host_consult / consult_readonly` 的只读出口副作用边界明确
- `status=ready && gate_passed=true` 的宿主对外响应默认套用标准标题/footer 模板

## C. 架构设计收敛

### 3. 局部语义分类骨架

- [ ] 3.1 定义 `Deterministic Guard` 的输入、输出与 fail-close 行为
- [ ] 3.2 定义 `Local Context Builder` 的最小上下文块，限制 assistant prose 污染
- [ ] 3.3 定义各 `required_host_action` 对应的 `Action Projection` schema
- [ ] 3.4 定义 `Resolution Planner` 的标准动作集合与禁止副作用

验收标准：

- 每个阶段都能回答“当前在判什么动作”
- 不再以原始 state JSON 直接充当分类输入

### 4. 参考实现经验的落地转译

- [ ] 4.1 把“规则优先”明确映射到 Sopify 的 runtime facts
- [ ] 4.2 把“动作语义投影接口”的思想映射为 Sopify 的 action projection contract
- [ ] 4.3 把“独立侧路判定”明确降级为候选机制，而不是 v1 既定实现
- [ ] 4.4 写清 `parser-first v1 / hybrid classifier vNext` 的阶段路线与切换条件

验收标准：

- 参考实现经验被转译为 Sopify 设计原则，而不是机械照搬实现
- 能明确回答“为什么现在不直接上全局语义分类器”

## D. 样本矩阵、状态不变量与评估

### 5. 样本矩阵补强

- [ ] 5.1 以 `正例 / 反例 / 边界例 / 禁止副作用` 四列为基线，补齐 A-1 ~ A-8 的可执行矩阵
- [ ] 5.2 为 A-1 / A-3 / A-4 / A-5 / A-8 增补 replay 级真实语料
- [ ] 5.3 为 A-6 明确单独的状态链路证据要求，不与普通 parser case 混测

验收标准：

- 每个 case 至少有一组真实语料与一组禁止副作用断言
- A-6 单独保留证据链，不被稀释成“一个例外 case”

### 6. 状态不变量

- [ ] 6.1 冻结 `required_host_action / checkpoint_id / current_plan_proposal / current_decision / plan/` 的副作用断言
- [ ] 6.2 明确 explain-only / cancel / revise / confirm 各自允许写哪些状态文件
- [ ] 6.3 为 `ready_for_execution + state_conflict(abort_conflict)` 写出单次收敛的不变量
- [ ] 6.4 定义 legacy pending state 的 schema 识别与 quarantine 入口，禁止因字段不兼容直接 crash
- [ ] 6.5 定义 quarantine 的标准 Escape Hatch（命令或自然语言重置动作），禁止要求用户手动清理状态目录
- [ ] 6.6 定义 quarantine 清理边界与审计事件（清理哪些状态、保留哪些资产、写入何种 reason_code）

验收标准：

- “解释型请求不重新物化 plan”
- “取消型请求不派生新 pending checkpoint”
- “abort_conflict 后不再回到同一 mismatch 循环”
- legacy state 不匹配时进入可恢复态（`quarantine/state_conflict`），不出现 runtime 崩溃
- 用户可通过标准动作完成恢复，且恢复路径可回放、可审计

## E. 实施前门禁

### 7. ready-to-start checklist

- [ ] 7.1 明确 v1 implementation candidate file map
- [ ] 7.2 明确哪些模块允许在 v1 变更，哪些只保留为观察点
- [ ] 7.3 明确 rollout / rollback 与既有对外 contract 主线 compatibility 口径
- [ ] 7.4 明确“什么时候允许从设计收敛切换到开发实施”

验收标准：

- 能给出一份不含歧义的 v1 实施边界
- 能说明为什么当前已经可以起包，但还不应该直接开工

## F. 发布面治理（Doc-1）

### 8. 去显性来源化收敛

- [x] 8.1 已校正：活动 plan 的目录名、`plan_id`、`feature_key` 视为受控机器字段，不纳入 Doc-1 去显性来源化治理
  说明：活动 plan 以机器真相判断；只要仍被 `current_plan / current_run / current_decision / current_handoff` 任一活动状态引用，上述字段就不得在文档侧直接改写。
- [x] 8.2 已完成：`background.md / design.md / tasks.md` 正文中的来源显式映射写法已替换为通用术语
- [x] 8.3 已完成：图示标签、示例标识与分支命名中的来源锚点已替换为机制导向标签
- [x] 8.4 已完成：对当前方案包展示层内容执行预定义来源锚点 denylist 扫描，结果为零命中

验收标准：

- 活动 plan 的目录名、`plan_id`、`feature_key` 保持机器真相，不纳入公开层治理范围
- 标题、正文、图示标签、示例标识、分支命名等展示层字段无显性来源锚点
- 扫描结果零命中，且扫描范围只覆盖展示层内容，不把机器字段纳入误伤
- 该治理项与 A-1 ~ A-8 runtime case 解耦，不影响 parser-first 主线验收

## G. v0.3 增补骨架

### 9. 统一 checkpoint parser 的 fail-close contract

规范来源：见 `design.md` §0 `P0 Freeze | 分层联动矩阵（最小冻结）`。本组与 §10 / §19 共享该节冻结口径。
补充口径：`9.x` 的完成定义显式绑定 `18.x`；仅提交 YAML/loader 原型不构成 `9.x` 完成。

- [ ] 9.1 盘点各 `required_host_action` 在未知输入下的默认动作，找出所有不一致项
- [ ] 9.2 为 `confirm_plan_package / confirm_execute / confirm_decision / answer_questions` 定义统一的 fail-close 入口与禁止隐式推进规则
- [ ] 9.3 冻结 `signal_group / target_kind / target_slot / evidence_tier / mutually_exclusive_with / fallback_on_conflict` 的最小裁决字段，并明确未知输入何时直接落入 fail-close
- [ ] 9.4 冻结 `signal_origin / allowed_origins / origin_evidence_cap / origin_precedence / evidence_rank` 的最小接线字段与固定裁决顺序，明确“规则信号永远压制 classifier 信号”的实现口径
- [ ] 9.5 将 Signal/Failure/Side-Effect 三张真理表外置为声明式资产（`runtime/contracts/decision_tables.yaml`）
- [ ] 9.6 为三张表定义统一、独立版本化 Schema，并冻结版本；runtime 侧只允许使用 stdlib strict validator 消费，不引入非 stdlib 运行时依赖
- [ ] 9.7 在 CI / preflight 增加表资产结构校验，禁止运行时隐式容错加载

验收标准：

- 未知输入不再被隐式解释成 `confirm / revise / cancel`
- 每个 checkpoint 都有显式的 fail-close 默认动作
- 同级冲突只在“同优先级 + 同 `target_slot` + 命中 `mutually_exclusive_with` + `evidence_tier` 相当”时降为 `ambiguous`
- `Signal Priority Table` 已明确 classifier 候选信号如何接线、如何被规则压制、以及何时统一落入 `fallback_on_conflict`
- 三张真理表可以独立通过 lint/schema 校验，且版本可追踪

### 10. 局部判定失败矩阵与降级语义

规范来源：见 `design.md` §0 `P0 Freeze | 分层联动矩阵（最小冻结）`。失败 family、主裁决优先级与 `secondary_reason_codes` 以该节为准。

- [ ] 10.1 冻结 `resolution_failure / effect_contract_invalid` 的最小 family 集；其中 `resolution_failure` 至少覆盖 `no_match / ambiguous / malformed_input / semantic_unavailable / context_budget_exceeded`
- [ ] 10.2 为每类失败 family 定义 `fallback_action / prompt_mode / retry_policy / reason_code` 的跨 checkpoint 降级映射，并明确 `primary_failure_type / secondary_reason_codes` 的归并口径
- [ ] 10.3 明确 parser-first v1 与 vNext classifier 共享同一失败语义层，而不是各自定义一套 fallback
- [ ] 10.4 建立 `reason_code -> host_facing_message_template` 映射表，补齐 fail-close 后的可执行引导语
- [ ] 10.5 增加模板插值安全校验：模板中的 `{variable}` 必须存在于 `ActionProjection/ContextSnapshot` 允许变量集合
- [ ] 10.6 定义模板渲染失败兜底：回退安全文案并记录 `message_template_render_failed`，不得引发主链异常

验收标准：

- 失败类型可枚举、可回放、可统计
- 同类失败不会在不同模块中被随意解释成不同动作
- `Failure Recovery Table` 的求值顺序固定为：基础 `fallback_action` -> streak 升级 -> 宿主交互形态
- fail-close 场景均有用户可理解且可执行的下一步提示
- 模板变量缺失不会导致 `KeyError` 或 runtime 崩溃

### 11. 同 checkpoint 无进展熔断

- [ ] 11.1 定义 `checkpoint_id + unresolved_outcome_family + durable_identity` 级别的 no-progress streak 统计口径
- [ ] 11.2 明确 `counts_toward_streak / soft_warning_action / fuse_blown_action / reset_streak_when` 的最小字段与升级边界
- [ ] 11.3 断言连续 `inspect / invalid / ambiguous / fail_closed` 不会形成无限循环，且熔断不会降低 fail-close 等级

验收标准：

- 同一 checkpoint 不会无限重复弱提示
- 熔断后仍不绕过现有 gate / state contract
- `status-only`、显式选择提交、状态推进、checkpoint 切换等 reset 条件口径明确且可回放

### 12. vNext classifier 的条件化扩展

- [ ] 12.1 写清 parser-first 升级到 guarded hybrid classifier 的前置条件
- [ ] 12.2 定义 `Local Context Builder + Signal Extraction + Action Projection + 独立侧路调用 + 两阶段判定` 的最小契约
- [ ] 12.3 明确 classifier 只返回结构化判定与 `reason_code`，不直接写状态或决定最终宿主输出
- [ ] 12.4 冻结 classifier 输出 schema：`decision_status / stage / checkpoint_kind / target_slot / candidate_signals / signal_origin / evidence_tier / confidence_band / reason_code`

验收标准：

- vNext classifier 被限定为条件化增强，而不是当前默认主线
- 升级条件、输入约束、输出约束都可单独审查
- classifier 永远位于 `Deterministic Guard` 之后，且不旁路三张表
- classifier 输出只能回流《Signal Priority Table》，不能直接生成 `resolved_action` 或触发状态写入

### 13. 可观测性拆分

- [ ] 13.1 v1 先定义 `reason_code / outcome / fallback_path / checkpoint_kind` 的基础统计口径
- [ ] 13.2 vNext 再补 `tokens / latency / cost / stage1_vs_stage2` 的预算与 rollout 观察项
- [ ] 13.3 明确 `signal.* / recovery.* / effect.*` 三层 `reason_code` 如何支持 rollout / rollback 与回归对比
- [ ] 13.4 冻结 post-classification 观测指标：`classifier_no_value_rate / projection_reject_after_classifier_rate / effect_reject_after_classifier_rate`

验收标准：

- parser-first 阶段已经具备最小可观测性
- classifier 预算指标不提前压进 v1 主线
- 同一条行为链可以串起信号裁决、失败恢复和副作用结果的观测事件
- classifier rollout 已具备“无价值率 / 接线越界率 / 副作用拒绝率”的最小回滚信号

## H. 当前推荐顺序

1. 先完成 `feature/context-boundary-core`（B 组核心 + G-9~G-11）。
2. 并行完成 `feature/public-surface-governance`（F 组），不阻塞主契约收敛。
3. 再完成 `feature/context-v1-guard-rails`（4a，承载 C 组骨架 + L 组 + M/N 组基础能力）。
4. 在 `boundary-core + 4a guard-rails` 合并前统一通过 Checkpoint A。
5. 在 guard-rails 基线上完成 `feature/context-sample-invariant-gate`（D 组），并通过 Checkpoint B。
6. 然后完成 `feature/context-v1-scope-finalize`（4b，承载 E 组 + L 组收口），并通过 Checkpoint C。
7. 当 Checkpoint A/B/C 均通过，进入 `Ready-for-V1-Execution`（阻断 V1 的正式执行门）。
8. 最后完成 `feature/context-vnext-gate`（4.4 + G-12 + G-13），并通过 Checkpoint D。
9. 当 Checkpoint D 通过且具备 v1 rollout 证据后，进入 `Ready-for-V2-Trial`（仅阻断 V2，不阻断 V1）。

## I. 分支矩阵与合并顺序

### 14. Topic 分支拆分

- [ ] 14.1 建立 `feature/context-boundary-core`，承载 `1.x + 2.1/2.2 + 9.x + 10.x + 11.x`
- [ ] 14.2 建立 `feature/public-surface-governance`，承载 `8.x`（允许与 14.1 并行）
- [ ] 14.3 建立 `feature/context-v1-guard-rails`（4a），承载 `3.x + 4.1-4.3 + 17.1-17.3 + 18.x + 19.x(入口/出口定义)`
- [ ] 14.4 建立 `feature/context-sample-invariant-gate`，承载 `5.x + 6.x`
- [ ] 14.5 建立 `feature/context-v1-scope-finalize`（4b），承载 `7.x + 17.4`
- [ ] 14.6 建立 `feature/context-vnext-gate`，承载 `4.4 + 12.x + 13.x`
- [ ] 14.7 冻结依赖拓扑：`boundary-core -> 4a guard-rails -> sample-invariant-gate -> 4b scope-finalize -> vnext-gate`
- [ ] 14.8 要求 `sample-invariant-gate` 基于已合入的 `4a guard-rails` 基线执行，不允许裸奔压测

验收标准：

- 分支职责互斥且无任务漂移
- 合并顺序满足依赖：`14.1 -> 14.3 -> 14.4 -> 14.5 -> 14.6`，`14.2` 只与 `14.1` 并行

## J. 决策波次 A-D 的 Checkpoint 强卡点

### 15. Checkpoint 治理落地

- [ ] 15.1 在 PR 模板中增加必填字段：`Context-Checkpoint(A/B/C/D)`、`Decision IDs`、`Blocked by`、`Out-of-scope touched`
- [ ] 15.2 在提交规范中增加 trailer：`Context-Checkpoint: A|B|C|D`
- [ ] 15.3 新增 CI 强检脚本 `scripts/check-context-checkpoints.py`，缺字段或决策未冻结即 fail
- [x] 15.4 Checkpoint A 已绑定：`plan_proposal_pending + command prefix` 保持显式 fail-close，A-6 继续留在本方案
- [ ] 15.5 Checkpoint B 绑定：A-1~A-8 唯一映射与“表格填不平”清零
- [ ] 15.6 Checkpoint C 绑定：v1 file map/白名单冻结与超范围变更阻断
- [ ] 15.7 Checkpoint D 绑定：vNext 价值/预算/安全/结构门槛冻结
- [ ] 15.8 Checkpoint A 增加“表资产落地 + Schema 冻结 + 插值安全校验”通过条件
- [ ] 15.9 Checkpoint A 增加“legacy quarantine + escape hatch + 审计事件”通过条件
- [ ] 15.10 Checkpoint B 增加“在 4a guard-rails 基线上通过样本压测”通过条件
- [ ] 15.11 Checkpoint C 增加“仅在 B 通过后锁定白名单与越界阻断”通过条件

验收标准：

- checkpoint 通过成为分支合并前置条件，而非文档建议
- 任一 checkpoint 缺失时，流水线可稳定 fail-close
- `Ready-for-V1-Execution` 只依赖 A/B/C；`Ready-for-V2-Trial` 依赖 D，不反向阻断 v1

## K. 分支 1 纸上沙盘（为分支 3 铺垫）

### 16. 离线契约干跑

说明：本组首笔提交只允许作为 `feature/context-boundary-core` 的受控 spike 入库，固定身份为 `tracked spike / non-checkpoint-credit / no runtime wiring`；其作用是固定资产载体、fixture 与离线校验入口，不代表 Checkpoint A 或 boundary-core 已完成。

- [x] 16.1 在 `feature/context-boundary-core` 提交 `scripts/check-fail-close-contract.py`
- [x] 16.2 补充离线 fixture（如 `tests/fixtures/context_fail_close_contract.yaml`），可枚举 `required_host_action -> fallback_action`
- [x] 16.3 先覆盖 A-1~A-8 的规则级判定预期，再扩到历史错例回放输入（当前完成口径为 failure family 组合覆盖；A-1~A-8 语义级规则覆盖待 1.x / 5.x / 9.x 收口）
- [x] 16.4 将 `scripts/check-fail-close-contract.py` 升级为 pytest 数据驱动测试入口
- [x] 16.5 固定接入 CI 回归套件，新增 case 必须先补数据样本再合并（已接入 CI/preflight；默认 `auto` runner 优先 pytest 参数化，缺失 pytest 时降级 native 并显式提示，非强制 pytest 门槛）

验收标准：

- 不依赖运行态状态文件也能验证 fail-close contract 的最小一致性
- 分支 3 引入真实样本时可直接复用该脚本做“表格可填平”预检
- 干跑能力可直接转化为长期回归资产，而非一次性脚本

## L. 分支 4a/4b v1 范围锁死骨架

### 17. 可见性级边界锁定

- [ ] 17.1 在 `feature/context-v1-guard-rails` 提交 `runtime/context_v1_scope.py`（常量注册表）
- [ ] 17.2 至少冻结常量：`SUPPORTED_CHECKPOINT_KINDS_V1`、`ALLOWED_V1_STATE_EFFECTS`、`FORBIDDEN_V1_SIDE_EFFECTS`
- [ ] 17.3 提交 `tests/test_context_v1_scope.py`，对越界动作做阻断断言
- [ ] 17.4 把 `7.1~7.4` 的名单口径映射到上述注册表与测试，不允许“只写文档不落守卫”

验收标准：

- v1 实施边界具备代码层可见性，不靠口头约束
- 超范围变更会被测试或 CI 直接拦截

## M. 真理表载体与模板安全

### 18. 表资产化与插值安全校验

- [ ] 18.1 冻结三张真理表的物理载体路径：`runtime/contracts/decision_tables.yaml`
- [ ] 18.2 定义三张表的独立版本化 Schema 契约，并在 CI 执行结构校验；runtime 侧固定采用 stdlib strict validator 消费
- [ ] 18.3 新增 `reason_code -> host_facing_message_template` 映射表，统一用户可见解释出口
- [ ] 18.4 新增模板插值安全校验：模板中的 `{variable}` 必须存在于 `ActionProjection/ContextSnapshot` 允许变量集合
- [ ] 18.5 约束模板渲染失败时 fail-open 到安全兜底文案，不允许因 `KeyError` 中断主流程
- [ ] 18.6 将 `18.2~18.5` 纳入 Checkpoint A 的必过项

验收标准：

- YAML 可独立 lint/schema 校验通过
- 模板变量缺失在 CI 即失败，运行时不崩溃
- 每条失败恢复路径都可映射到用户可读提示

## N. 遗留状态隔离与退出机制

### 19. legacy state quarantine + escape hatch

规范来源：见 `design.md` §0 `P0 Freeze | 分层联动矩阵（最小冻结）`。`quarantine_annotation`、promotion 规则与 `best_proven_resume_target` 证明顺序以该节为准。

- [ ] 19.1 定义 legacy pending state 的侦测规则与 quarantine 进入条件
- [ ] 19.2 定义 quarantine 下的标准逃生动作（命令或自然语言重置），不得要求用户手动清理状态目录
- [ ] 19.3 定义 quarantine 清理边界（清理哪些状态、保留哪些资产）与审计事件
- [ ] 19.4 定义 quarantine 恢复后的 resume 语义：回到可继续 checkpoint 的安全起点
- [ ] 19.5 将 `19.1~19.4` 纳入 Checkpoint A 的必过项

验收标准：

- legacy schema 不匹配进入可恢复态，不出现 crash 或死锁
- 用户可通过标准 escape hatch 自助恢复
- 恢复动作具备 reason_code 与审计留痕
