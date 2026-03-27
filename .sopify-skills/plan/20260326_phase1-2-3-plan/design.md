# 技术设计: Sopify 推广优化 program plan

## 技术方案
- 核心目标: 把“轻入口、按风险打断、可旁路恢复”的推广方向，收口成可分批实施的后续子 plan
- 本方案定位:
  - 这是总纲 plan，不是直接执行代码改造的 implementation plan
  - 这份文档负责锁定边界、依赖、优先级与待拍板项
  - 后续所有实现都应通过独立子 plan 承接

## 设计原则
1. 先减阻力，再加能力
   先处理最直接的推广阻力，再进入更深的路径与状态语义改造。

2. 先保 contract，再改 behavior
   能通过内部打分与策略层解决的问题，不先改共享机器契约。

3. Ghost 不是单个 feature
   `延迟物化`、`Ghost State`、`Ghost Knowledge` 不是一个量级，不能绑成同一轮。

4. Side task 必须有边界
   目标是 `suspend -> bounded side task -> resume`，不是自由漫游。

5. 文档只宣传已交付能力
   对外定位可以提前设计，但不能提前承诺未实现能力。

## 总拆分
后续路线拆为六个命名方案：

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
状态: upgraded to current priority child plan

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

1. Plan B1
2. Plan A
3. Plan D 在 B1 与 A 收口后推进
4. Plan B2
5. Plan C
6. Plan B3

补充说明:
- `B1` 现阶段是当前最高优先级 child plan，因为它直接解决 adoption friction、workspace 侵入感与 control-plane 漂移问题
- `A` 可继续保留分析结论，但 host-facing implementation 不应与 `B1` 的 control-plane contract 迁移交叉推进
- `D` 必须等 `B1` 与 `A` 两侧对外语义都稳定后再更新对外文档
- `B2` 不依赖 `A`，但应在 `B1` 之后，避免同时处理 control-plane bundle 迁移与运行态目录迁移
- `C` 的 contract design 可早于 `B2`，但 full implementation 建议在 `A` 与 `B1/B2` 稳定后进行
- `B3` 必须单独决策后再开工

## 当前执行窗口
当前总纲下的最高优先级子 plan 是：

- `.sopify-skills/plan/20260326_5-plan-20260326-phase1-2-3-plan-plan-20260326-ph`

它与总纲的关系如下：

1. 它是当前 `Plan B1` 的升级落地窗口，不是 `B2 / B3 / Plan C` 的前置偷渡
2. 它先处理 control-plane：global bundle、thin stub/pin、bootstrap ignore、dual-host preflight、legacy fallback
3. 它收口后，`Plan A` 才进入真正的下一优先级执行窗口
4. `Plan D` 必须等 `B1 + A` 稳定后再跟进，以免外部叙事与真实能力错位
5. `B2 / C / B3` 继续保持后移，不并入当前窗口

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

1. Plan A
   - 覆盖既有 blocking_reason 的正例 / 反例 / 边界例
   - 验证 `gate_status` 语义不变

2. Plan D
   - 文档不提前承诺未实现功能
   - 文案与当前支持面一致

3. Plan B1
   - 验证首次需要时才发生物化
   - 验证不影响现有 workspace-relative plan contract

4. Plan B2
   - 验证 state/replay 移出 workspace
   - 验证 `plan/blueprint/history` 行为不变

5. Plan C
   - 验证 `suspend -> side task -> resume` 一进一出完整可回
   - 验证 resume 后 plan truth 不漂移

6. Plan B3
   - 需要独立定义更高等级的 contract migration gate

## 安全与性能
- 安全:
  - 不以“减少打断”为理由绕过高风险确认
  - 不以 Ghost 为理由破坏 plan truth
- 性能:
  - 优先通过策略层与路径路由层收口，不做全量重写
  - 总 plan 只作为协调文档，不加载超出当前决策所需的额外复杂度
