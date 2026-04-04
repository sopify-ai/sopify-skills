# 变更提案: 局部语义收口方案 | 风险自适应打断与局部语义分类收敛

## 需求背景

当前总纲已经把既有 control-plane 契约主线记录为主线收口，并明确下一步是在 `3.2` 的 control-plane contract 稳定后推进当前方案包。这意味着本方案现在已经进入可正式拆包的窗口，但还不适合直接进入代码实施。

当前更合适的动作，是先把本方案从总纲中的“冻结边界 + 样本矩阵 + 零散探讨”收敛成一个独立的标准方案包，作为真正开工前持续迭代的设计工作台。

本方案当前要解决的问题，不是再修一轮既有 correctness hotfix 主线那类状态机修补，而是把 pending checkpoint 语境下的 host-facing recall debt 系统化收口。近期真实样本已经稳定指向以下几类问题：

1. explain-only / analysis-only 请求被重新物化成 proposal 或其他 pending checkpoint
2. existing plan referent 被误判成新的阻断路径
3. “取消 checkpoint”类表达在局部语境下不够稳健
4. mixed clause 在逗号后从句里仍存在局部歧义
5. `no-write / no-package / just-analyze` brake signal 会被 process semantic 覆盖
6. `ready_for_execution + state_conflict(abort_conflict)` 仍需要作为本方案的设计门禁显式追踪
7. 公开方案包中若残留显性来源锚点（第三方产品名/仓库名/专有函数名/源码路径），会带来版权/合规观感风险并削弱方案抽象独立性

因此，本 plan 的目的不是“马上实现局部语义分类器”，而是把下面四类信息先写进一个可持续优化的正式方案包：

1. 总纲中已经冻结的本方案边界与硬约束
2. 外部参考实现中可借鉴的设计模式
3. 当前已经定下来的候选方案、非目标、风险与实施前门禁
4. 公开发布面的去显性来源化约束与验收口径

## 研究输入

本 plan 主要承接以下输入：

1. program plan 中的本方案总纲与任务门禁
   - `.sopify-skills/plan/20260326_phase1-2-3-plan/design.md`
   - `.sopify-skills/plan/20260326_phase1-2-3-plan/tasks.md`
2. 本轮已冻结的 A0 语义契约与 A-1 ~ A-8 样本矩阵
3. 本地参考材料中与权限语义分类、工具权限门禁、局部上下文压缩相关的实现模式
4. 当前公开口径评审结论：活动 plan 的目录名、`plan_id`、`feature_key` 保留为机器字段；Doc-1 只治理正文术语、图示标签、示例标识、分支名等展示层来源锚点

## 当前已冻结约束

以下内容已经在总纲层面冻结，本子 plan 只能承接，不能推翻：

1. 本方案的职责是 host-facing 语义召回增强，不重开既有 correctness hotfix 主线已收口的状态机正确性修复
2. 只允许在局部 checkpoint 语境下增强召回，不做全局自由语义理解
3. 默认不改 runtime state model / handoff contract / resolution contract
4. `ExecutionGate` 核心机器语义保持稳定
5. `gate_status` 值集在 v1 不改
6. `gate_status / blocking_reason / plan_completion / next_required_action` 不改名
7. 不接受“单词/短语补丁式”修复，必须按同一语义类一次收口
8. 默认与既有对外 contract 主线保持向后兼容

## 为什么现在要起标准方案包

当前适合起 `standard` 而不是 `light`，原因有三点：

1. 它已经不是单点 parser 修补，而是要把背景、设计、任务门禁、候选方案和实施前 acceptance gate 分层写清楚
2. 它需要同时承接总纲冻结内容、样本矩阵、参考实现经验，信息密度已经超过 `plan.md` 单文件能稳定承载的范围
3. 真正实施前还会持续迭代，因此需要 `background.md + design.md + tasks.md` 三段结构来容纳“已定事实 / 候选方案 / 待决问题”

## 当前方向判断

基于这轮分析，本方案的推荐方向不是“先上一个全局自然语言分类器”，而是：

1. 先用 deterministic guard 把 checkpoint machine facts 定死
2. 再在局部语境里定义“当前可判动作面”
3. 先收口 parser / structural semantics 能稳定覆盖的语义类
4. 只把 residual ambiguity 留给后续可选的 semantic side classifier

这个判断与本轮提炼出的参考实现经验一致：

1. 不是词匹配优先，而是动作语义优先
2. 不是全文自由理解，而是局部语境压缩后再判断
3. 不是模型先判，而是 deterministic-first
4. 不是分类失败继续猜，而是 fail-close 或降级人工确认

## 影响范围

本轮只创建并收敛方案包，不执行代码修改。后续 implementation candidate scope 预计会落在以下区域，但本 plan 暂不承诺全部实施：

- `runtime/router.py`
- `runtime/plan_proposal.py`
- `runtime/checkpoint_cancel.py`
- `runtime/output.py`
- `runtime/context_snapshot.py`
- `runtime/engine.py`
- 相关 `tests/` 与回归样本
- 当前方案包的公开命名与术语治理（标题、正文、图示标签、示例标识、分支命名）

## 风险评估

### 风险 1

过早把外部参考实现中的侧路语义分类机制直接等同于 Sopify v1 实现，导致与当前已冻结的“parser 层优先收口”原则冲突。

缓解：

- 先把参考实现经验写成参考模式，而不是直接写成既定实现
- 在 design 中显式区分“v1 推荐路径”和“vNext 候选方向”

验证入口：见 tasks.md §C.4。

### 风险 2

把既有 correctness hotfix 主线问题、本方案 recall debt、以及产品行为拍板问题混成一轮。

缓解：

- 明确列出 non-goals
- `plan_proposal_pending + command prefix` 已冻结为显式 fail-close，不视为自动继续信号
- 把 A-6 的 state-conflict case 当成本方案的设计门禁，而不是顺手修补项

验证入口：见 tasks.md §B.2.1/2.2。

### 风险 3

方案包起得太早，但内容仍停留在模板壳子，后续无法作为真正的设计工作台持续迭代。

缓解：

- 本轮就把总纲冻结内容、样本矩阵、参考实现经验与候选路线写全
- tasks 只写设计收敛任务，不伪装成开发任务

当前状态：已脱离模板壳，后续持续性收敛见 tasks.md。

### 风险 4

显性来源锚点在公开方案包中残留，导致对外读者形成“影射式搬运”观感，并引出版权/合规讨论风险。

缓解：

- 将“私有研究映射”与“公开抽象原则”分层管理：活动 plan 的机器身份保持不动，公开层只保留机制与约束，私有层保留具体映射笔记
- 公开层只治理标题、正文、图示标签、示例标识、分支命名，不在文档侧直接改写目录名、`plan_id`、`feature_key`
- 对展示层来源锚点执行一次性 denylist 扫描，要求零命中后再进入对外分享

验证入口：见 tasks.md §F.8。

## 评分

- 方案质量: 9/10
- 落地就绪: 7/10
- 评分理由: 本方案的目标、边界、样本与兼容性约束已经足够清楚，适合正式拆成 standard 子 plan；但真正进入实施前，仍需先收口产品行为拍板项、状态不变量、以及“parser-first 还是 hybrid classifier”的阶段化策略。
