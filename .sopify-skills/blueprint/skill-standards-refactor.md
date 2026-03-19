# Skill 标准对齐蓝图

状态: 已收口（2026-03-19 决议已落地）
创建日期: 2026-03-19
定位: 面向 `Anthropic Agent Skills + Gemini CLI Agent Skills` 的专项重构蓝图

## 一页结论

### 可以学（直接吸收）

1. 渐进披露：metadata 预加载，激活后再读取正文与资源。[A1][A2][A3]
2. skill package 分层：`SKILL.md + scripts/references/assets`。[G2]
3. 发现分层：`workspace > user > extension/bundled`，兼容 `.agents/skills`。[G1]
4. 权限与宿主能力显式声明；当前仅 `schema + host_support + permission_mode` fail-closed。[A4][G3]
5. 评测前置：先建 eval，再大规模重构。[A3]

### 值得改（优先级）

1. `P0` discovery tier 扩展与 precedence 固化
2. `P0` skill package 结构试点（`analyze/design/develop`）
3. `P0` source-of-truth 单向生成链（package -> catalog）
4. `P0` 权限最小字段集与执行约束
5. `P0` skill authoring eval baseline
6. `P1` host abstraction / extension tier / observability

## 当前收口结果（2026-03-19）

1. `P0` discovery tier 与 precedence 已落地，声明式 route 绑定优先于 legacy fallback。
2. `analyze/design/develop` 已完成 Codex CN/EN prompt-layer 分层试点，Claude 侧通过 sync 镜像。
3. builtin machine metadata 已收敛到 `runtime/builtin_skill_packages/*/skill.yaml`，catalog 走单向生成链并有 drift gate。
4. 权限边界当前只对 `skill.yaml` schema、`host_support`、runtime `permission_mode` fail-closed；`tools / disallowed_tools / allowed_paths / requires_network` 先作为声明字段保留。
5. eval baseline / SLO / gate / smoke 已进入仓库，并接入 preflight / CI。
6. release automation 不再单列为“是否保留 release hook”的待决项；仓库提供 `commit-msg` hook，启用后由 commit 路径触发 shell preflight + version sync。

## 背景与问题

当前仓库在 runtime control-plane、entry guard、state/handoff 方面已经较完整，但 `skill package` 仍不是第一事实源，导致“能运行”与“可移植、可审查、可演进”之间存在结构性差距。[A1][A2][A3][A4][G1][G2][G3]

核心问题：

1. 发现层偏私有路径，跨宿主兼容不足
2. `SKILL.md` 偏重，目录未充分承接渐进披露
3. catalog/router/runtime 三处分散持有语义，source-of-truth 倒置
4. 权限边界缺少正式元数据契约
5. 缺少 skill authoring 维度的回归评测

## 目标（重构后应达到）

### 目标 1: 标准化 skill package

统一逻辑模型：

```text
Codex/Skills/{CN,EN}/skills/sopify/my-skill/
├── SKILL.md
├── scripts/
├── references/
└── assets/

runtime/builtin_skill_packages/my-skill/
└── skill.yaml
```

约束：

1. `SKILL.md` 只保留触发语义、流程骨架、关键边界
2. 长模板迁入 `assets/`
3. 长规范迁入 `references/`
4. 确定性逻辑迁入 `scripts/`
5. machine metadata 以同名 skill id 落在 `runtime/builtin_skill_packages/*/skill.yaml`

### 目标 2: 重做 discovery tier

发现层级：

1. workspace
2. user
3. bundled/extension

兼容路径：

1. `.agents/skills` / `.gemini/skills` / `skills`
2. `~/.agents/skills` / `~/.gemini/skills` / `~/.codex/skills` / `~/.claude/skills`

规则：

1. workspace > user > bundled
2. builtin 默认不可静默覆盖，需显式声明

### 目标 3: source-of-truth 单向生成

目标链路：

```text
skill package -> validate -> generate catalog/manifest -> runtime consume
```

限制：

1. 允许保留 catalog 作为 runtime 加速产物
2. 禁止继续手写 catalog 作为长期事实源

### 目标 4: 权限与宿主能力声明

最小字段集：

```yaml
tools:
  - read
disallowed_tools:
  - write
allowed_paths:
  - .
requires_network: false
permission_mode: default
host_support:
  - codex
  - claude
```

策略：

1. 当前强执行范围是 `skill.yaml` schema、`host_support`、runtime `permission_mode`
2. `tools / disallowed_tools / allowed_paths / requires_network` 当前只做声明，不在 runtime 强执行
3. 已落地的约束边界不允许被文档或实现静默放宽

### 目标 5: 评测纳入标准流程

最小 eval 套件：

1. discovery/precedence eval
2. selection/activation eval
3. navigation eval（references/assets/scripts）
4. split-regression eval（拆分前后命中与完成率）
5. cross-model smoke eval

## 四项架构契约（必须同时成立）

### 契约 A: 声明式 skill 选择

1. Router 负责路由判定，不再长期持有硬编码 skill 绑定关系
2. skill 选择由声明字段驱动（至少含 `supports_routes/triggers/host_support/priority`）
3. 允许短期兼容 fallback，但必须可追踪并有退场计划

### 契约 B: 权限边界（当前落地）

1. 当前已强执行 `skill.yaml` schema、`host_support`、runtime `permission_mode`
2. `tools / path / network` 相关字段当前保留为声明字段，不得在文档中表述为“已 runtime 强执行”
3. 后续若升级到 host + runtime 双保险，必须补齐测试与 gate，再更新口径

### 契约 C: package -> catalog 单向生成

1. skill package（prompt-layer + builtin metadata）是唯一事实源
2. builtin catalog 只作为生成产物，禁止手工长期维护
3. CI 必须有 drift 校验（package 与 catalog 不一致即失败）

### 契约 D: eval 质量门

1. 除 smoke 外，必须定义 SLO 阈值（误触发率、漏触发率、跨模型漂移）
2. 不达阈值不得进入发布
3. 拆分前后必须有可对比的回归指标

## 决策模式契约（四标准）

### policy_id 列表

1. `skill_selection_policy_choice`
2. `permission_enforcement_mode_choice`
3. `catalog_generation_timing_choice`
4. `eval_slo_threshold_choice`

### 触发规则

1. 存在 2 个及以上可行方案，且都会影响长期契约
2. 当前 `project/blueprint` 没有唯一答案
3. 会影响安装入口、runtime 入口、权限边界或质量门阈值
4. 命中后必须进入 `required_host_action=confirm_decision`

### 不触发规则

1. `project/blueprint` 已明确写死默认策略
2. 仅涉及局部实现细节，不改变长期契约
3. 可由确定性规则唯一推导

### fail-closed

1. 若检测到 tradeoff 信号却未生成 checkpoint request，必须 fail-closed
2. reason code 统一使用 `checkpoint_request_missing_but_tradeoff_detected`

## 入口守卫补充（直改白名单 vs runtime-first）

默认策略：

1. 先判定白名单（可直改）
2. 未命中白名单即进入 runtime-first 主路径（黑名单即主路径）

### 直改白名单（允许不经 runtime）

1. `consult` 类型咨询问答，且未显式使用 `~go/~compare` 前缀
2. 纯文案润色/排版/链接修复，不涉及状态文件与流程资产
3. 用户明确指定“只改某文件文本”，且目标不在受保护路径

### runtime-first（必须经 `scripts/sopify_runtime.py`）

1. 命中 `plan/design/develop/decision/checkpoint/handoff` 任一流程语义
2. 命中 `~go/~go plan/~go exec/~go finalize/~compare` 任一命令语义
3. 变更目标位于 `.sopify-skills/plan/*` 的结构化任务资产
4. 任何 `required_host_action` 处于 pending 三态（`answer_questions/confirm_decision/confirm_execute`）

### 咨询问答边界

1. `consult` 默认可直答，不强制 runtime
2. 若咨询内容涉及长期契约分叉、tradeoff 或可能触发 checkpoint，必须切回 runtime-first
3. 显式命令前缀优先级高于“咨询语气”，即使是问句也要走 runtime

## 实施策略（先兼容，后收敛）

### P0（必须先做）

1. 发现层扩展与 precedence 固化
2. 三个 builtin skill 的结构试点拆分
3. package -> catalog 生成链初版
4. 权限元数据最小集 + 当前 fail-closed 基线（`schema / host_support / permission_mode`）
5. eval baseline 与回归门

### P1（在 P0 稳定后）

1. host adapter 升级为能力适配层
2. bundled/extension tier 统一加载与校验
3. 技能激活与导航的可观测性
4. 多模型评测与统计闭环

## 非目标

1. 本轮不重写 runtime control-plane 主链路
2. 本轮不把 Gemini CLI 直接作为正式宿主接入对象
3. 本轮不承诺一次性消除所有旧 prompt-layer 文档

## 已拍板结果

1. `skill.yaml` 作为 builtin machine metadata 主入口；prompt-layer 文档与 machine metadata 先分层存放。
2. discovery precedence 固化为 `workspace > user > bundled`，且声明式 `priority/source` 优先于 legacy fallback。
3. catalog 通过 `scripts/generate-builtin-catalog.py` 在构建 / preflight / CI 路径生成，`runtime/builtin_catalog.generated.json` 作为产物消费。
4. 权限边界当前仅对 `skill.yaml` schema、`host_support`、runtime `permission_mode` fail-closed；其余权限字段先声明不强执。
5. eval 资产独立落位在 `evals/`，与 `tests/` 分责。
6. release automation 采用 `commit-msg` hook 触发 `scripts/release-preflight.sh` + `scripts/release-sync.sh`；不再单列独立 release-hook 决策项。

## 参考文献

- [A1] Anthropic, “Equipping agents for the real world with Agent Skills”, 2025-10-16, https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills
- [A2] Anthropic, “Agent Skills - Overview”, https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- [A3] Anthropic, “Skill authoring best practices”, https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- [A4] Anthropic, “Create custom subagents”, https://docs.anthropic.com/en/docs/claude-code/sub-agents
- [G1] Gemini CLI, “Agent Skills”, https://geminicli.com/docs/cli/skills/
- [G2] Gemini CLI, “Creating Agent Skills”, https://geminicli.com/docs/cli/creating-skills/
- [G3] Gemini CLI, “Activate skill tool (`activate_skill`)", https://geminicli.com/docs/tools/activate-skill/
- [G4] Gemini CLI, “Release notes”, https://geminicli.com/docs/changelogs/
