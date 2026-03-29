# 技术设计: Sopify 推广优化 program plan

## 技术方案
- 核心目标: 把“轻入口、按风险打断、可旁路恢复”的推广方向，收口成可分批实施的后续子 plan
- 本方案定位:
  - 这是总纲 plan，不是直接执行代码改造的 implementation plan
  - 这份文档负责锁定边界、依赖、优先级与待拍板项
  - 后续所有实现都应通过独立子 plan 承接

## 设计原则
1. 先治状态机，再放大全局控制面
   若 runtime 连“当前 checkpoint 到底是什么”都不能唯一收敛，那么全局 bundle、shared runtime、diagnostics 只会放大状态漂移。

2. 先减阻力，再加能力
   先处理最直接的推广阻力，再进入更深的路径与状态语义改造。

3. 先保 contract，再改 behavior
   能通过内部打分与策略层解决的问题，不先改共享机器契约。

4. Ghost 不是单个 feature
   `延迟物化`、`Ghost State`、`Ghost Knowledge` 不是一个量级，不能绑成同一轮。

5. Side task 必须有边界
   目标是 `suspend -> bounded side task -> resume`，不是自由漫游。

6. 文档只宣传已交付能力
   对外定位可以提前设计，但不能提前承诺未实现能力。

## 总拆分
后续路线拆为七个命名方案：

### Plan H | 状态机 Hotfix（B1 前置门禁）
状态: immediate prerequisite

目标:
- 修复 stale-state、ghost proposal、checkpoint 解析分裂与 handoff 对冲

范围:
- 统一 checkpoint resolver / immutable snapshot
- 收口 proposal / clarification / decision 的作用域与 provenance
- 收口 `state_conflict` 与 `~go abort` 脱困路径
- 补状态机专项回归测试

硬约束:
- Proposal 只允许 Session-only，不保留 global fallback
- Router / Engine / Handoff 只消费同一份 resolved snapshot
- `state_conflict` 必须可见且可恢复，不能在构建期直接 Fatal
- `current_plan / current_run` 不纳入 abort 清理范围

### Plan A | 风险自适应打断
状态: committed next

目标:
- 把“打断过多”从流程问题改成风险分级问题

范围:
- 调整 risk detection、risk scoring、interruption policy
- 引入 `conservative / balanced / aggressive` 三档策略
- 收口稳定 reason code

硬约束:
- `ExecutionGate` 的核心机器语义保持稳定
- `gate_status` 值集不在 v1 改动
- 核心字段名 `gate_status / blocking_reason / plan_completion / next_required_action` 不改名
- `blocking_reason` 如需扩展，必须验证未知值消费兼容性

承接边界（来自 Plan H 收口后的 carry-over）:
- Plan H 负责 checkpoint correctness hotfix：唯一 pending 收敛、cancel bridge 放行、execution-confirm 污染冲突、doctor/status 协商态解释
- Plan A 只承接 host-facing 语义召回增强，不重开 Plan H 已收口的状态机正确性修复

非目标:
- 不扩大全局语义理解；仅允许在局部 checkpoint 语境下增强召回
- 不在本计划中改 runtime state model / handoff contract / resolution contract
- 不把 polite prefix、同义词、更多 tail token 的扩展伪装成 Plan H 热修

启动条件:
- 仅在 `Plan H + Plan B1` 各自收口后，才进入 Plan A 子 plan
- 启动前必须先登记真实漏判样本或用户反馈阈值，避免长期欠债无限后延，也避免过早侵入 control-plane 迁移窗口

Case（后续拆分 Plan A 子计划时必须覆盖）:
- Case A-1 | checkpoint 中 explain-only 咨询不应二次物化
  - 场景: 已存在 `confirm_plan_package / confirm_decision` 等 pending checkpoint 时，用户提出“只分析、不改文件”的追问。
  - 期望: 优先按 consult 回答并保持当前 checkpoint 身份稳定；除非用户明确提交 `继续 / 取消 / 1/2/...`，不得新建或重开 plan proposal，也不得仅因存在 pending decision 就自动重跑 execution gate。
  - 验收: 同一 session 连续 explain-only 问答后，不新增 proposal `checkpoint_id`，且 `plan/` 下无新建方案包目录。
  - 验收补充: 当消息显式锚定 existing plan（如 `plan_id / plan path / plan title / 当前方案`）且语义仍为“分析 / 解释 / 判断是否认可 / 还有什么需要确认”时，应继续返回 consult；`current_decision` 身份保持稳定，不得漂移为新的 decision/proposal checkpoint。
- Case A-2 | 决策编号确认携带补充文本应稳健消费
  - 场景: 用户以 `1/2` 开头确认决策，同时附带后续动作文本（如“并把 case 补进总纲”）。
  - 期望: 先稳定消费 decision selection，再把后续文本作为 follow-up 意图处理，避免回退到“无效选择”或重复 decision checkpoint。
- Case A-3 | 引用受保护 plan 资产的分析请求不应默认升级阻断
  - 场景: 用户消息包含 `.sopify-skills/plan/...` 路径引用，或显式引用 existing plan（如 `plan_id / plan title`），但意图是“只分析/不改文件/判断是否认可”。
  - 期望: 优先按 consult 或非阻断路径处理；仅在命中明确执行动作（如 `继续/next/开始/选择`）时进入 checkpoint 约束，不得因为“显式 plan 引用 + pending checkpoint”组合而默认升级为阻断路径。
  - 验收: 在同一 session 下，连续分析问答不会新增 `plan_proposal_pending`；`required_host_action` 不因“只分析”从 consult 漂移到阻断 checkpoint。
  - 验收补充: `分析下 <plan_id> 可以执行了吗还有什么需要确认` 这类请求，在未命中明确确认动作时，应保持为 consult / inspect 类回答，不得直接消费或重开 `confirm_decision`。
- Case A-4 | “取消 checkpoint”应幂等收口，不得派生新 pending
  - 场景: 当前处于 `confirm_decision / confirm_plan_package` pending，用户输入“取消这个 checkpoint”。
  - 期望: 只取消当前 pending（或返回已取消状态），并恢复到稳定可继续态；不得创建新的 proposal 或切到其他 checkpoint 类型。
  - 验收: 取消后 `current_handoff.required_host_action` 不再是新的 pending checkpoint；不会出现“取消动作触发新 plan_proposal_pending”的链路漂移。
  - 验收补充: 当用户输入“取消这个 checkpoint”等含取消关键词的自由文本时，必须按 `cancel` 处理，并允许 `status=cancelled/resume_action=cancel` 在无 `selected_option_id` 的情况下生效，且不得派生新的 pending checkpoint。
- Case A-5 | 逗号混合句的局部语境歧义应单独细化
  - 场景: 当前为保留 `"取消这个 checkpoint，不要取消全部"` 这类混合句的可执行语义，`, / ，` 仍作为 cancel 成功边界。
  - 已知残余风险: `"取消这个 checkpoint，为什么还会回到 pending"` 这类分析/追问句仍可能误命中 cancel。
  - 期望: 在 Plan A 中统一细化逗号后从句的局部语境，区分否定补充、解释性补充与疑问补充；该项不回流到 Plan H。
  - 验收: 保留 `"取消这个 checkpoint，不要取消全部"` 的 cancel 语义，同时降低 `"取消这个 checkpoint，为什么..."` 类问句的误触发率。

### Plan D | 对外定位与文档
状态: committed after Plan A scope is stable

目标:
- 把对外叙事从“重管控工作流”收口为“轻入口，复杂时再结构化”

范围:
- 更新 `README.md`
- 更新 `README.zh-CN.md`
- 更新 `docs/how-sopify-works.en.md`

硬约束:
- 只宣传已交付能力
- 不预售 Ghost / Suspend / Side Task 的未实现行为

### Plan B1 | 延迟物化
状态: current control-plane child plan, but state-chain-sensitive slices are blocked by Plan H

目标:
- 将原“延迟物化”升级为完整的 control-plane decoupling：
  - 重型 runtime bundle 留在宿主全局 payload
  - workspace 只保留本地 thin stub / pin
  - bootstrap 同时补 ignore、host-aware preflight 与 legacy compatibility

范围:
- 调整 bootstrap 与首次物化时机
- 调整 workspace-local `.sopify-runtime/manifest.json` 契约
- 调整 host-aware payload 解析与 dual-host 同仓库选择
- 调整 payload index、installer diagnostics、doctor/status/smoke
- 调整 legacy vendored fallback 的可观测性

硬约束:
- thin stub 不能只改字段，不改 bootstrap / validate / inspection 判定器
- dual-host 解析必须显式 host-aware
- payload 索引化必须同步升级 `validate / inspection / doctor / status / smoke`
- ignore 默认优先 `.git/info/exclude`，仅“提交版本锁”模式才写 `.gitignore`
- `stub 优先 / legacy vendored fallback 次之 / no_silent_downgrade` 必须有可见 reason code
- 不吸收 `runtime/state / router / engine / handoff` 的协商态一致性修复；该部分由 `Plan H` 单独承接
- 与 `Plan H` 并行时，只允许纯 filesystem / manifest / payload index / thin stub / ignore 脚手架，且不得 `import runtime.state` 或读取 `.sopify-skills/state/*.json`

非目标:
- 不改变 `plan/blueprint/history` 路径 contract
- 不引入 Ghost 全局缓存语义
- 不触碰 `B2 / B3` 的路径合约改造

### Plan B2 | Ghost State
状态: deferred but named

目标:
- 将 `state/`、`replay/` 等纯运行态数据从 workspace 移出

范围:
- 路由 `config.state_dir`
- 路由 replay session 存储
- 视实现需要决定是否增加 bundle cache

硬约束:
- 不改 `plan_path` 语义
- 不改 `knowledge_layout`
- 不改 `finalize`
- 不改 `plan/blueprint/history` 的 workspace-relative contract

### Plan C | Suspend / Side Task / Resume
状态: deferred but named

目标:
- 允许在 active plan 中做低风险旁路任务，再安全回到主线

范围:
- 先定义 suspend/resume contract
- 后实现 bounded side task flow

硬约束:
- side task 只允许 low-risk
- 不允许借 side task 绕开正式 planning / decision checkpoint
- contract design 可先做，full implementation 依赖前序方案稳定

### Plan B3 | Ghost Knowledge
状态: explicitly deferred

目标:
- 重新定义 `plan/blueprint/history` 的 materialization 与 path contract

说明:
- 这不是 B2 的附带工作
- 这是重量级路径合约改造，需要单独立项

影响面:
- `plan_path`
- `knowledge_layout`
- `finalize/history`
- `router` path protection
- mixed-mode collaboration

## 依赖与顺序
推荐顺序如下：

1. Plan H
2. Plan B1
3. Plan A
4. Plan D 在 B1 与 A 收口后推进
5. Plan B2
6. Plan C
7. Plan B3

补充说明:
- `Plan H` 是 `B1` 的前置门禁，因为它解决的是“runtime 当前到底在等哪个 checkpoint”这一层唯一事实源问题
- `B1` 仍是当前主 control-plane child plan，但其涉及 runtime 状态链路与协商恢复的切片必须等待 `Plan H` 解锁
- `B1` 在 `Plan H` 执行期间只允许推进纯 filesystem / manifest / payload index / thin stub / ignore 脚手架
- `A` 可继续保留分析结论，但 host-facing implementation 不应与 `B1` 的 control-plane contract 迁移交叉推进
- `D` 必须等 `B1` 与 `A` 两侧对外语义都稳定后再更新对外文档
- `B2` 不依赖 `A`，但应在 `B1` 之后，避免同时处理 control-plane bundle 迁移与运行态目录迁移
- `C` 的 contract design 可早于 `B2`，但 full implementation 建议在 `A` 与 `B1/B2` 稳定后进行
- `B3` 必须单独决策后再开工

## 当前执行窗口
当前总纲下的即时执行窗口分成两个层次：

- `.sopify-skills/plan/20260327_hotfix`
- `.sopify-skills/plan/20260326_5-plan-20260326-phase1-2-3-plan-plan-20260326-ph`

它与总纲的关系如下：

1. `20260327_hotfix` 是即时门禁窗口，负责修复 stale-state / ghost checkpoint / contradictory handoff
2. `20260326_5-plan-20260326-phase1-2-3-plan-plan-20260326-ph` 仍是当前 `Plan B1` 的升级落地窗口，但只保留可并行的 control-plane 脚手架
3. 任何触碰 runtime 状态链路、checkpoint 恢复、handoff 唯一出口、`doctor/status/smoke` 协商态解释的 B1 子任务，必须等待 `20260327_hotfix` 的 H5 解锁
4. `Plan A` 只有在 `Plan H + B1` 各自收口后才进入真正下一优先级执行窗口
5. `Plan D` 必须等 `B1 + A` 稳定后再跟进，以免外部叙事与真实能力错位
6. `B2 / C / B3` 继续保持后移，不并入当前窗口

## 待拍板的产品决策
以下事项必须先拍板，不能留到实现 plan 中边做边定：

1. 默认策略档位
   建议: `balanced`

2. Ghost 是否 `opt-in`
   建议: 是

3. Ghost v1 是否止步于 `B2`
   建议: 是，`B3` 只作为后续路线图

4. Side task 是否强约束为 `low-risk only`
   建议: 是

5. 若未来开启 `B3`，`plan_path` 的新语义是什么
   说明: 该项只在 B3 立项前拍板，不是当前主线阻塞项

6. 若未来开启 `B3`，Ghost 下是否保留 `finalize/history`
   说明: 该项只在 B3 立项前拍板

7. 若未来开启 `B3`，mixed-mode 协作如何定义
   说明: 该项只在 B3 立项前拍板

## 验收门
每个后续子 plan 都必须显式写出 acceptance gate，最低要求如下：

1. Plan H
   - Proposal 不再以 global fallback 参与当前会话路由
   - `state_conflict` 与 `~go abort` 构成完整脱困闭环
   - `current_handoff` 与 `current_run.stage` 不再对冲输出不同 checkpoint

2. Plan A
   - 覆盖既有 blocking_reason 的正例 / 反例 / 边界例
   - 验证 `gate_status` 语义不变

3. Plan D
   - 文档不提前承诺未实现功能
   - 文案与当前支持面一致

4. Plan B1
   - 验证首次需要时才发生物化
   - 验证不影响现有 workspace-relative plan contract
   - 验证与 `Plan H` 并行时不触碰 runtime checkpoint 状态系统

5. Plan B2
   - 验证 state/replay 移出 workspace
   - 验证 `plan/blueprint/history` 行为不变

6. Plan C
   - 验证 `suspend -> side task -> resume` 一进一出完整可回
   - 验证 resume 后 plan truth 不漂移

7. Plan B3
   - 需要独立定义更高等级的 contract migration gate

## 安全与性能
- 安全:
  - 不以“减少打断”为理由绕过高风险确认
  - 不以 Ghost 为理由破坏 plan truth
- 性能:
  - 优先通过策略层与路径路由层收口，不做全量重写
  - 总 plan 只作为协调文档，不加载超出当前决策所需的额外复杂度
