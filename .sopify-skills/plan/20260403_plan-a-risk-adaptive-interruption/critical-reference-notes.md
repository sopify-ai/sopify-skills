# 参考笔记：Harness Book × Plan A

> **定位** — Plan A 研究附录。不替代 `background.md`、`design.md`、`tasks.md`，不构成新的 machine truth。
>
> **用途** — ① 沉淀外部参考阅读中对 Plan A 最值得保留的判断；② 区分"已吸收 / 可借鉴 / 不应照搬"。

---

## 1 核心结论

这本书最值得 Sopify 学的不是产品外形，而是三条判断顺序：

```
① 先分清当前 machine truth 由谁拥有
② 先把允许动作面收敛成结构化 contract
③ 只有在 deterministic facts 不能唯一裁决时，才让局部语义判定参与
```

> Plan A 的主问题不是"缺一个更聪明的分类器"，而是"状态主权、恢复证据链、局部动作裁决"还需要继续收口。

---

## 2 章节提炼与 Sopify 映射

下表将 Harness Book 各章核心思想一一映射到 Sopify 的现有机制与 Plan A 设计。

| # | Book 章节 | 核心思想 | Sopify 对应机制 | Plan A 设计原则 |
|---|----------|---------|----------------|---------------|
| 1 | Ch.2 — Two Control Planes | 运行纪律不应长期寄托在 prompt 和聊天惯性上；规则、边界、状态应变成**显式控制面** | `runtime gate` · `ContextResolvedSnapshot` · `current_handoff` · `execution_gate` · `decision_tables` | 结构化 contract 优先于"模型大概会按规矩来" |
| 2 | Ch.3 — Loop, Thread, Rollout | 连续性的真相源必须**独立于聊天正文**存在 | `gate + snapshot + handoff` 优先于 assistant prose；session / global / history 分层 | 活跃链不靠 transcript 恢复 |
| 3 | Ch.4 — Tools, Sandbox, Exec Policy | 高风险动作先经过**确定性政策层**，再考虑更智能的判定 | 执行前依次过 `allowed_response_mode` → `required_host_action` → `current_run.stage` → `checkpoint_request / execution_gate` | deterministic guard 在局部语义之前 |
| 4 | Ch.5 — Skills, Hooks, Local Governance | 值得学"本地治理资产化"，不值得学"治理点越多越强" | 规则、表、模板、schema 优先落成版本化资产 | 治理层不应反过来成为新复杂度来源 |
| 5 | Ch.6 — Delegation, Verification, State | 委派、验证、状态恢复不能混成一团；live truth / audit trail / resume hint 各有归属 | `current_handoff`（live truth） · `replay/`（audit trail） · `best_proven_resume_target`（resume hint） | 三类信息分层独立 |
| 6 | Ch.7 — Convergence & Divergence | 殊途同归——harness 才是秩序源；但骨架分运行时共和制 vs 控制面立宪制 | Sopify 偏重**显式控制面纪律**，而非运行时临场装配 | machine truth 先于 prose；checkpoint/handoff 先于自由恢复 |

---

## 3 Plan A 借鉴思想提炼

以下五条从两轮阅读中提炼，均保持原意。

### 3.1 判动作，不判全局意图

Plan A 将对象定义为 `action-in-context classifier` 是正确方向。

```
真正要判的：当前 machine truth 下，宿主下一步
  → 能不能继续
  → 要不要打断
  → 是否应停在当前 checkpoint
  → 是否要改道 inspect / consult
```

### 3.2 局部上下文压缩优先

局部动作判定的输入应被严格收敛：

| 优先级 | 输入 | 说明 |
|:------:|------|------|
| 1 | 当前用户输入 | 直接信号源 |
| 2 | 最近少量相关用户消息 | 窗口化上下文 |
| 3 | 当前 checkpoint / execution gate 摘要 | 机器状态 |
| 4 | 当前允许动作集合 | 控制面约束 |
| 5 | 当前 runtime 限制与长期偏好摘要 | 全局策略 |

> 完整 transcript 或 assistant prose 不应作为主要判定输入。

### 3.3 规则优先，语义后置

```
deterministic guard   →  排除不可能动作
       ↓
局部信号提取          →  提取结构化候选
       ↓
优先级表查表          →  winner_action
       ↓
失败                  →  fail-close
```

> "先理解，再回头校验"不符合 Sopify 当前体系。

### 3.4 classifier 只当侧路增强

若未来引入 classifier，其能力边界必须受限：

| 可以 | 不可以 |
|------|--------|
| 处理局部 ambiguity | 升级为主路由器 |
| 输出结构化候选 | 直接写状态 |
| 回流到统一裁决表 | 绕过 deterministic guard |
| 失败时退回 inspect / explicit choice | 静默通过 |

### 3.5 live truth 和研究附录分层

```
稳定 truth  ←  runtime / state / contract
研究判断   ←  研究附录 / 设计笔记（如本文）
```

二者不应混为同一层。

---

## 4 Sopify 当前吸收度评估

### 4.1 已吸收

| 特征 | 书中要求 | Sopify 现状 | 评估 |
|------|---------|------------|------|
| 入口守卫 | 控制面先于执行 | `runtime gate` 强制首跳 | ✅ 已到位 |
| 状态收敛 | 真相源独立于 transcript | `ContextResolvedSnapshot` 统一供 router/engine/handoff | ✅ 已到位 |
| 确定性政策层 | 高风险先过 policy | `execution_gate` + `allowed_response_mode` | ✅ 已到位 |
| 治理资产化 | 规则落成可版本化资产 | Signal / Failure / Side-Effect 三张表已 YAML 化 + schema | ⚙️ 已资产化，CI 集成收口中 |
| 受限出口 | 非正式路径不应成自由回退 | `consult_readonly` 设计冻结为受限出口 | ⚙️ 已设计，待独立运行时验证 |

> Sopify 不缺方法论方向，缺的是"把方向进一步收口成唯一机器事实"的最后几步。

### 4.2 当前短板

| 短板 | 症状 | 优先级 |
|------|------|:------:|
| 状态主权残留 | 全局 `current_run / current_handoff / current_decision` 仍有旧 carrier 残留 | **P0** |
| live truth 解耦不彻底 | 系统可恢复到更新 truth，但 live truth / 历史残留 / 恢复线索尚未完全分离 | **P0** |
| prompt 资产可识别性弱 | 宿主侧 prompt 仍以大块规则文本和宿主头文件承载，非 typed fragment | **P1（v2）** |

> 主矛盾：状态主权和恢复真相，优先级高于扩大全局语义理解。

### 4.3 主要风险类型判定

```
Sopify 当前更怕:  规则来源不清 + 状态主权不唯一
Sopify 不太怕:    长会话中意图逐步漂移
```

原因：入口守卫、状态收敛、停点体系已基本成型，但 live truth / global / session / recovery 之间仍可能存在残留差异。

---

## 5 明确不照搬清单

| # | 不照搬什么 | 原因 | 正确替代 |
|---|-----------|------|---------|
| 1 | 产品外形 | 不应为"看起来像某类 agent"引入新术语/线程模型 | 借鉴底层原则：状态主权、恢复证据链、动作面控制、风险前置 |
| 2 | classifier 上主链 | v1 应坚持 parser-first + fail-close | classifier 准入条件：状态主权稳定 + action projection 成型 + 样本矩阵够 |
| 3 | 参考实现污染叙事 | 公开文档不应写成"翻译某产品到 Sopify" | 用 Sopify 自己的概念表达：我们的机制抽象、风险约束、验证框架 |
| 4 | 扩大关键词风险扫描 | `execution_gate` 聚合描述文本做检测，早期合理但长期有害 | 逐步向显式 risk metadata + decision persistence 收敛 |

---

## 6 实施原则与优先级

### 6.1 硬约束：v1 实施面应显著小于设计面

```
设计面    ─────────────────────────── 完备
                    ↑
实施面    ────────── 小而闭合
```

含义不是削弱设计，而是：
- 设计先把边界讲清楚
- 进入 runtime wiring 的子集尽量小而闭合
- 先做最小可工作 machine contract，再逐步增加附属制度层

> 每调整一次 recovery 语义，可能需同步改动 YAML + schema + fixture + CI + 文档。v1 还没形成稳定主链前，维护成本会先拖慢进度。

### 6.2 执行边界定义产品

以下不是"安全补丁"，而是 Sopify 的**产品行为**：

| 机制 | 产品含义 |
|------|---------|
| `fail-close` | 不确定时停下，不是工程保守 |
| `checkpoint_only` / `error_visible_retry` | 正式交互模式，不是异常旁路 |
| 确定性前置链 | `gate → allowed_response_mode → required_host_action → stage` |

> 不需因"看起来更重"而回退到自由聊天式继续。

### 6.3 推荐任务顺序

```
① 收口 legacy / quarantine / escape hatch
     ↓
② 收口 Local Context Builder / Action Projection / Resolution Planner
     ↓
③ 补强真实语料、边界例与禁止副作用断言
     ↓
④ 考虑 guarded hybrid classifier
```

> 状态主权不稳时，引入更强语义层只会放大歧义，不会消除歧义。

### 6.4 优化路线图

以下路线图基于 §6.3 推荐顺序具体化，经批判审视后收紧了实现落点和优先级。

#### 总览

```
boundary-core 收口          guard-rails 分支              sample-invariant-gate       v2 scope
─────────────────    ──────────────────────────    ──────────────────────    ────────────
  S2                   S1 → M1 → S4 → S3                   M2                 L1 → L2 → L3
                                        ↘
                                    M3 (guard-rails 后段
                                     或 scope-finalize 前)
```

#### 短期：boundary-core 收口 + guard-rails

| ID | 优化项 | 优先级 | 做什么 | 不做什么 | 落点 | tasks 映射 |
|----|--------|:------:|--------|---------|------|-----------|
| S2 | 收紧 `failure_recovery.py` 结构检测 | **P0** | `_looks_like_decision_tables_asset` 的 `startswith("decision_tables.")` 改为精确 allowlist `{"decision_tables.v1"}`；sentinel keys 从 `issubset` 改为要求 `failure_recovery_table` 必须存在；`assert_failure_recovery_tables_consistent` 增加 sentinel key 完整性断言 | 不引入泛化版本协商；v1 精确匹配足够 | `runtime/failure_recovery.py:332` | 9.x 补丁 |
| S1 | 清理 legacy carrier 残留 | **P0** | 在已有 promotion / escape-hatch / explicit cleanup helper 路径上扩展：session carrier 被确认为 live truth 后，**显式清除**对应 global legacy carrier；quarantine 注解增加 `cleanup_eligible: true` 字段（**受控 schema 变更**：触及 `decision_tables.yaml` 冻结的 `quarantine_annotation_fields`，连带 schema / fixture / CI 同步，不是注释级改动）；补 CI 断言 | **不把清理逻辑放进 `resolve_context_snapshot` 后处理**——snapshot resolver 职责仍是"识别并 quarantine"，不是"写回并清理"；清理由 `engine.py` 的 promotion hook / cleanup helper 负责，与 `:397` `:505` 已有先例一致 | `runtime/engine.py` promotion 路径 | **19.x** 延伸（quarantine/cleanup/resume 边界已冻结在 19.x），配合 3.x |
| M1 ⟨短期⟩ | Local Context Builder 实现 | **P0** | 新增 `runtime/context_builder.py`，单函数 `build_local_context()` → `LocalContext` frozen dataclass；5 项输入压缩（用户输入、窗口化消息 max=3、checkpoint 摘要、allowed_actions、runtime 约束摘要）；硬约束过滤 `role=assistant` 纯 prose；补 test | 不承担信号提取职责（那是 Stage 3） | `runtime/context_builder.py`（新） | 3.1~3.4 |
| S4 | action projection allowed_actions 冻结 | **P1** | 在 `decision_tables.yaml` 中新增 `action_projection_table` section，**仅冻结最小映射**：`(required_host_action, checkpoint_kind) → allowed_actions[]`；补 CI 断言：Signal Priority Table 每个 `winner_action` ∈ 对应行的 `allowed_actions` | **不一口气把 artifact fields、resume 语义、host copy 全带进去**——否则违反 §6.1 硬约束 | `runtime/contracts/decision_tables.yaml` | 4.1~4.3 |
| S3 | `consult_readonly` 最小出口断言 | **P1** | 在 consult 路径出口处增加 `assert_consult_readonly_contract(handoff, side_effects)`，从 `decision_tables.yaml` 的 `consult_readonly_contract.forbidden_effects` 和 `switch_to_consult_readonly.forbidden_state_effects`（`:474`）读取并校验；补 1 条 test case | **不抽象成通用 side-effect runtime**——这项是"把现有 contract 接线验证"，不是新设计 | `runtime/engine.py` 或 `runtime/handoff.py` consult 出口 | 4.x |

#### 中期：sample-invariant-gate + scope-finalize

| ID | 优化项 | 优先级 | 做什么 | 不做什么 | 落点 | tasks 映射 |
|----|--------|:------:|--------|---------|------|-----------|
| M2 | 禁止副作用断言矩阵覆盖率 | **P1** | **复用已有 `forbidden_state_effects` 字段**（`:431`），不新增近似命名；补运行时断言遍历 Side-Effect Mapping Table 所有行，校验 forbidden 与 allowed 不交集；补 fixture case（inspect 下产生 `plan_materialization` → 预期断言失败） | **不新增 `forbidden_side_effects[]` 字段**——`decision_tables.yaml` 和 `decision_tables.py:1220` 已有 `forbidden_state_effects`，复用即可 | `runtime/decision_tables.py` 断言 + `tests/` | 5.x~6.x |
| M3 | live truth / audit / resume 命名分层收束 | **P1-** | 在 `RuntimeHandoff` 模型中以注释/metadata 标注字段层级（truth / resume_hint / audit）；`replay/` 写入时关联 `resolution_id` | **不拆 handoff JSON 为多文件**（v1 维护成本不值得）；不和 S1/M1 争首屏预算——`resolution_id` 成对打标（`state.py:233`）和 snapshot 传递（`context_recovery.py:50`）已部分在场，本项是命名/分层收束，不是先手堵漏洞 | `runtime/handoff.py` + `runtime/replay.py` | guard-rails 后段 → scope-finalize 前 |

#### 长期：v2 scope

| ID | 优化项 | 优先级 | 方向 | 准入条件 |
|----|--------|:------:|------|---------|
| L1 | 宿主 prompt 资产 typed fragment 化 | **P1(v2)** | 参考 Codex fragment marker 模式，为宿主头文件关键规则块增加 typed marker；runtime gate preload 按 marker 识别/排序/去重 | 状态主权和恢复证据链先收口 |
| L2 | guarded hybrid classifier 试验 | **P2(v2)** | classifier 只在 Stage 3 产出候选，受 Signal Priority Table `origin_evidence_cap` 约束；术语对齐现有资产：origin 使用 `semantic_classifier`，evidence cap 使用 `weak_semantic_hint`（对齐 `decision_tables.yaml:115` 已有定义） | S1 + M1 + S4 + M2 完成；边界例 ≥ 20 组 |
| L3 | execution_gate risk metadata 化 | **P2(v2)** | plan 创建时写入结构化 `risk_metadata`，execution_gate 优先消费 metadata 而非 re-scan 描述文本；渐进迁移保留 text scan 作 fallback | — |

#### 推荐执行序

```
S2 → S1 → M1 → S4 → S3 → M2 → M3 → L1 → L2 → L3
 │    │     │     │     │     │     │
 │    │     │     │     │     │     └─ guard-rails 后段 / scope-finalize 前
 │    │     │     │     │     └─────── sample-invariant-gate
 │    │     │     │     └───────────── guard-rails
 │    │     │     └─────────────────── guard-rails
 │    │     └───────────────────────── guard-rails (核心)
 │    └─────────────────────────────── 19.x 延伸 + guard-rails
 └──────────────────────────────────── boundary-core 收口
```

#### 纪律提醒

> 本路线图服从 §6.1 硬约束：先补最小 machine contract 漏洞，不让 guard-rails 反过来变成新的制度负担。每项实现前应回问：它是在收口已有 contract，还是在发明新的治理面？

---

## 7 可晋升结论候选

以下判断若经实现、回归、跨任务验证后稳定成立，可提升至 blueprint：

| # | 结论 | 晋升目标 |
|---|------|---------|
| 1 | 先 machine truth，后语义判定 | `blueprint/design.md` |
| 2 | 先 deterministic guard，后局部分类 | `blueprint/design.md` |
| 3 | live truth / audit trail / resume hint 必须分层 | `blueprint/design.md` |
| 4 | classifier 只能作为局部 ambiguity 的侧路增强 | `blueprint/design.md` |
| 5 | 失败恢复语义必须统一，不允许各模块各自解释 | `project.md` |
| 6 | v1 实施面应显著小于设计面 | `project.md` |

---

## 8 存放与生命周期

### 8.1 当前位置

`20260403_plan-a-risk-adaptive-interruption/critical-reference-notes.md` — 随 Plan A 生命周期管理。

### 8.2 理由

| 判断 | 依据 |
|------|------|
| 首先属于 Plan A 研究附录 | 直接服务于 Plan A 的设计收敛、边界判断、阶段路线 |
| 不适合直接升格 blueprint | 仍含外部参考解释、当前阶段批判判断、未完全固化的取舍 |
| 适合作为"可批判参考" | Plan A finalize 归档后应随之进入 `history/` |

### 8.3 迁移规则

| 目标 | 条件 |
|------|------|
| `blueprint/design.md` | 已成为跨任务、跨方案都成立的稳定架构原则 |
| `project.md` | 已成为实现组织、测试策略或模块约定 |
| `history/` | 主要是某轮方案收敛的设计背景与决策依据 |

### 8.4 推荐消费方式

**适合用来回答：**
1. 为什么当前不先上全局 classifier
2. 为什么状态主权和恢复证据链优先级更高
3. 为什么某些外部经验只作思想借鉴，不直接照搬

**不适合替代：**
1. runtime code 的行为真相
2. `tasks.md` 的执行真相
3. `current_* state` 的机器事实

---

## 9 来源索引

### 外部来源

| # | 章节 | URL | 用途 |
|---|------|-----|------|
| 1 | 目录页 | `https://harness-books.agentway.dev/book2-comparing/` | 分析框架索引 |
| 2 | Ch.2 — Two Control Planes | `https://harness-books.agentway.dev/book2-comparing/chapter-02-two-control-planes.html` | 控制面分析 |
| 3 | Ch.4 — Tools, Sandbox, Exec Policy | `https://harness-books.agentway.dev/book2-comparing/chapter-04-tools-sandbox-and-exec-policy.html` | 执行策略分析 |
| 4 | Ch.7 — Convergence & Divergence | `https://harness-books.agentway.dev/book2-comparing/chapter-07-convergence-and-divergence.html` | 路线取舍框架 |

### 仓库内对照证据

| 文件/路径 | 对应判断 |
|-----------|---------|
| `runtime/gate.py` | 入口守卫、`allowed_response_mode`、严格 ingress 契约 |
| `runtime/context_snapshot.py` | 统一状态收敛、quarantine、conflict 处理 |
| `runtime/contracts/decision_tables.yaml` | truth status、fail-close、signal priority、consult readonly 冻结规则 |
| `runtime/decision_tables.py` | schema / validator / asset loading 制度化实现 |
| `.sopify-skills/blueprint/design.md` | `L1 stable / L2 active / runtime` 正式分层 |
| `.sopify-skills/state/current_run.json` | state ownership 全局残留风险 |
| `.sopify-skills/state/sessions/session-ca94b8dcbebf/current_run.json` | session-scope recovery truth 对照 |
| `installer/hosts/base.py` | 宿主抽象基类结构化程度 |
| `installer/hosts/codex.py` | Codex 宿主实现 |
| `installer/hosts/claude.py` | Claude 宿主实现 |
| `Codex/Skills/CN/AGENTS.md` | 宿主 prompt 资产以大块文本承载 |
| `Claude/Skills/CN/CLAUDE.md` | 宿主 prompt 资产以大块文本承载 |

### 使用边界

来源标注是为了**可追溯性**和**可批判性**。来源存在 ≠ 自动提升为正式结论。

消费顺序：`runtime / state / contract 的现行机器事实` → `本文研究判断` → `经验证后升格到 blueprint`。
