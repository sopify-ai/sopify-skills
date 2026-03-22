# Sopify (Sop AI) Skills

<div align="center">

**标准 Sop AI Skills - 配置驱动的 Codex/Claude 技能包：按任务复杂度自动路由执行流程**

[![许可证](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![文档](https://img.shields.io/badge/docs-CC%20BY%204.0-green.svg)](./LICENSE-docs)
[![版本](https://img.shields.io/badge/version-2026--03--22.183053-orange.svg)](#版本历史)
[![欢迎PR](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

[English](./README_EN.md) · [简体中文](./README.md) · [快速开始](#快速开始) · [配置说明](#配置说明)

</div>

---

## 为什么选择 Sopify (Sop AI) Skills？

**问题：** 传统 AI 编程助手对所有任务都使用相同的重量级流程 - 简单的 typo 修复也要走完整的需求分析、方案设计流程，效率低下且输出冗余。

**解决方案：** Sopify (Sop AI) Skills 引入**自适应工作流**，根据任务复杂度自动选择最优路径：

| 任务类型 | 传统方式 | Sopify (Sop AI) Skills |
|---------|---------|--------------|
| 简单修改 (≤2 文件) | 完整 3 阶段流程 | 直接执行，跳过规划 |
| 中等任务 (3-5 文件) | 完整 3 阶段流程 | 轻量方案 (单文件) + 执行 |
| 复杂任务 (>5 文件) | 完整 3 阶段流程 | 完整 3 阶段流程 |

### 核心特性

- **一次安装，项目触发自动准备 runtime** - 安装宿主 payload 后，进入任意项目触发 Sopify 即可按需 bootstrap / update `.sopify-runtime/`
- **manifest-first 机器契约** - 宿主优先读取 `.sopify-runtime/manifest.json` 与 `.sopify-skills/state/current_handoff.json`，不靠自由发挥猜下一步
- **planning-mode 自动闭环** - `go_plan_runtime.py` 现已升级为 planning-mode orchestrator，会自动串接 clarification / decision，并在 `review_or_execute_plan` 或 `confirm_execute` 稳定停下
- **全阶段统一 checkpoint contract** - handoff 会优先暴露标准化 `checkpoint_request`；其中 develop-first callback 已落地，宿主在 `continue_host_develop` 中遇到用户拍板分叉时必须先回调 runtime
- **零项目级额外依赖** - 当前 runtime 维持 `stdlib_only`，不要求每个仓库单独安装额外 Python 依赖
- **自适应工作流与方案分级** - 简单任务直接执行，中等任务 light 方案，复杂任务完整规划
- **工作流学习与跨平台支持** - 支持回放/复盘，并兼容 Claude Code 与 Codex CLI

---

## 快速开始

### 前置条件

- CLI 环境 (Claude Code 或 Codex CLI)
- 文件系统访问权限

### 安装

**一键接入（推荐）：**

```bash
# 仅做全局安装（推荐首次在本仓库根目录执行）
bash scripts/install-sopify.sh --target codex:zh-CN

# 显式预热某个目标仓库（可选）
bash scripts/install-sopify.sh --target claude:en-US --workspace /path/to/project
```

当前支持的 `target`：

- `codex:zh-CN`
- `codex:en-US`
- `claude:zh-CN`
- `claude:en-US`

说明：

- installer 会安装宿主提示层，并在宿主根目录下安装全局 Sopify payload
- 若传入 `--workspace`，installer 会额外为该仓库预热 `.sopify-runtime/`
- 若不传 `--workspace`，后续只要在任意项目仓库里触发 Sopify，宿主会按需自动 bootstrap 当前仓库的 `.sopify-runtime/`
- 该命令适合作为最终用户的一键接入入口

### 验证安装

重启终端，输入：
```
显示技能列表
```

**预期输出：** Agent 列出 7 个技能 (analyze, design, develop, kb, templates, model-compare, workflow-learning)

### 二次接入 runtime bundle

如果需要从维护者视角手工控制 bundle 同步过程，可以单独执行：

```bash
# 1. 从当前仓库同步 runtime bundle
bash scripts/sync-runtime-assets.sh /path/to/project

# 2. 在目标仓库验证原始输入入口
python3 /path/to/project/.sopify-runtime/scripts/sopify_runtime.py --workspace-root /path/to/project "重构数据库层"

# 3. 可选：运行便携测试与 smoke
python3 -m unittest /path/to/project/.sopify-runtime/tests/test_runtime.py
bash /path/to/project/.sopify-runtime/scripts/check-runtime-smoke.sh
```

说明：

- 选定宿主的全局 payload 默认位于 `~/.codex/sopify/` 或 `~/.claude/sopify/`
- 全局 payload 采用 `payload-manifest.json + bundle/ + helpers/` 结构
- 宿主在项目仓库内识别到 Sopify 触发后，会先读取全局 payload，再按需为当前仓库补齐 `.sopify-runtime/`
- 若当前仓库的 `.sopify-runtime/` 缺少 manifest 要求的 bridge capability 或缺少 bridge / CLI 关键文件，宿主必须将其视为 incompatible 并刷新，而不是仅按同版本跳过
- `.sopify-runtime/` 保持 `runtime/` + `scripts/` + `tests/` 的自包含布局
- `.sopify-runtime/manifest.json` 是 bundle 的机器契约；宿主接入必须优先读取 manifest，再回退到默认脚本路径
- vendored 入口默认是 `.sopify-runtime/scripts/sopify_runtime.py`
- 当 Sopify 被触发后，宿主第一跳必须改为 `.sopify-runtime/scripts/runtime_gate.py enter`；实际 helper 路径与 contract version 以 `manifest.json -> limits.runtime_gate_entry / limits.runtime_gate_contract_version` 为准
- 只有当 gate 返回 `status=ready`、`gate_passed=true`、`evidence.handoff_found=true`、`evidence.strict_runtime_entry=true` 时，宿主才可声称“已进入 runtime”并继续普通阶段
- `evidence.handoff_found` 的含义固定为：`current_handoff.json` 已成功落盘；runtime 内存中的 handoff 只可作为 normalize fallback，不可单独作为通过证据
- `.sopify-skills/state/current_gate_receipt.json` 只用于 smoke / debug / doctor 可见性，不是宿主主链路 machine truth；主 machine truth 仍是 `current_handoff.json`
- plan-only orchestrator 对应 `.sopify-runtime/scripts/go_plan_runtime.py`
- `answer_questions` 命中后可选使用内部 helper `.sopify-runtime/scripts/clarification_bridge_runtime.py` 读取/写回轻量 clarification form；它不是新的主入口
- manifest 会通过 `limits.clarification_bridge_entry` 与 `limits.clarification_bridge_hosts` 暴露该 helper 与宿主桥接提示
- `confirm_decision` 命中后可选使用内部 helper `.sopify-runtime/scripts/decision_bridge_runtime.py` 读取/写回桥接契约；它不是新的主入口
- manifest 会通过 `limits.decision_bridge_entry` 与 `limits.decision_bridge_hosts` 暴露该 helper 与宿主桥接提示
- `continue_host_develop` 命中后，若宿主在开发中再次遇到用户拍板分叉，必须调用内部 helper `.sopify-runtime/scripts/develop_checkpoint_runtime.py submit --payload-json ...` 生成标准化 develop checkpoint；它不是新的主入口
- manifest 会通过 `limits.develop_checkpoint_entry / limits.develop_checkpoint_hosts / limits.develop_resume_context_required_fields / limits.develop_resume_after_actions` 暴露该 helper 与 `resume_context` 契约
- `answer_questions / confirm_decision / confirm_execute` 命中时，handoff 会优先附带标准化 `checkpoint_request`
- builtin skill 发现由 `runtime/builtin_catalog.py` 负责，不依赖 bundle 内再携带 `Codex/Skills` 或 `Claude/Skills` 文档目录
- 非闭环路由现在会写入 `.sopify-skills/state/current_handoff.json`，`Next:` 文案优先基于 handoff contract 渲染
- 后续 `codex/claude` host bridge 与 Cursor 插件都应复用同一个 runtime gate core，而不是各自复制 ingress 逻辑

### 长期偏好预载入

宿主在每次 Sopify 调用前，应基于当前 `workspace_root + plan.directory` 尝试读取：

```text
<workspace_root>/<plan.directory>/user/preferences.md
```

最小约束：

- 路径解析必须与 runtime 配置优先级保持一致，不能硬编码 `.sopify-skills/user/preferences.md`
- `preferences.md` 缺失或读取失败不阻断主链路，首版采用 `fail-open with visibility`
- 若成功读取，宿主应把它作为“当前工作区的长期协作规则”注入 LLM
- 固定优先级为：当前任务明确要求 > `preferences.md` > 默认规则
- “当前任务明确要求”指用户在当前任务中显式给出的临时执行指令；冲突时它优先于 `preferences.md`，不冲突时与长期偏好叠加生效，且默认不回写为长期偏好
- 这是一段宿主 preflight 能力，不是 runtime 新阶段，也不改变 `RecoveredContext` 语义

### 硬约束复核（2026-03-19）

以下三条约束已按隔离 smoke 复核：

- 仍保持“一次安装”模型，不要求第二个安装命令来准备 workspace bundle
- 首次项目触发时，runtime 仍通过已安装 payload 自动补齐 `.sopify-runtime/`
- 默认主入口仍是 `scripts/sopify_runtime.py` / `.sopify-runtime/scripts/sopify_runtime.py`

复核命令：

```bash
python3 scripts/check-install-payload-bundle-smoke.py \
  --output-json /tmp/sopify-install-payload-bundle-smoke.json
```

复核记录：

- [专项蓝图收口文档](./.sopify-skills/blueprint/skill-standards-refactor.md)

### 首次使用

```bash
# 进入任意项目仓库后，直接触发 Sopify；
# 若当前仓库尚未准备 `.sopify-runtime/`，宿主会先自动补齐再继续执行。
# 文档治理约定下，真实项目仓库首次触发后应至少拥有 `.sopify-skills/blueprint/README.md` 作为项目索引。

# 1. 简单任务 → 直接执行
"修复 src/utils.ts 第 42 行的 typo"

# 2. 中等任务 → 轻量方案 + 执行
"给登录、注册、找回密码添加错误处理"

# 3. 复杂任务 → 完整流程
"~go 添加用户认证功能，使用 JWT"

# 4. 只规划不执行
"~go plan 重构数据库层"

# 5. 回放/复盘最近一次实现
"回放最近一次实现，重点讲为什么这么做"

# 6. 多模型并发对比（人工选择）
"~compare 给这个重构方案做对比分析"
"对比分析：给这个重构方案做对比分析"
```

### 仓库内最小验证

当前仓库已经收口的最小 runtime 验证路径：

```bash
# 默认原始输入入口
python3 scripts/sopify_runtime.py "重构数据库层"

# prompt-level runtime gate 入口
python3 scripts/runtime_gate.py enter --workspace-root . --request "重构数据库层"

# 显式命令也走同一个通用入口
python3 scripts/sopify_runtime.py "~go plan 重构数据库层"

# 显式收口当前 metadata-managed plan
python3 scripts/sopify_runtime.py "~go finalize"

# 只验证 plan-only orchestrator
python3 scripts/go_plan_runtime.py "重构数据库层"

# 指向其他工作区验证
python3 scripts/sopify_runtime.py --workspace-root /path/to/project "重构数据库层"

# 自检当前 runtime bundle
bash scripts/check-runtime-smoke.sh
```

预期结果：

- 首次在真实项目仓库触发时，只初始化最小长期知识骨架：
  - `.sopify-skills/project.md`
  - `.sopify-skills/user/preferences.md`
  - `.sopify-skills/blueprint/README.md`
- 首次进入 plan 生命周期时，按需补齐：
  - `.sopify-skills/blueprint/background.md`
  - `.sopify-skills/blueprint/design.md`
  - `.sopify-skills/blueprint/tasks.md`
  - `.sopify-skills/plan/YYYYMMDD_feature/`
- 首次显式 `~go finalize` 时，按需生成：
  - `.sopify-skills/history/index.md`
  - `.sopify-skills/history/YYYY-MM/...`
- 更新 `.sopify-skills/state/`
- 在命中主动记录策略时写入 `.sopify-skills/replay/`
- 终端输出 Sopify 统一摘要，而不是原始结构化对象
- `runtime_gate.py` 返回结构化 gate contract，并在需要时写出 `.sopify-skills/state/current_gate_receipt.json`

当前边界：

- 当前对外承诺的最小 runtime 发布切片：`runtime-backed ~go plan + develop-first checkpoint callback`
- 已收口 repo-local runtime helper：
  - `scripts/sopify_runtime.py`：默认原始输入入口
  - `scripts/go_plan_runtime.py`：plan-only orchestrator
  - `scripts/clarification_bridge_runtime.py`：`answer_questions` 阶段的内部宿主桥接 helper，提供 `inspect / submit / prompt`，不替代默认入口
  - `scripts/decision_bridge_runtime.py`：`confirm_decision` 阶段的内部宿主桥接 helper，提供 `inspect / submit / prompt`，不替代默认入口
  - `scripts/develop_checkpoint_runtime.py`：`continue_host_develop` 中命中用户拍板分叉时的内部 callback helper，提供 `inspect / submit`，不替代默认入口
- 已提供 `scripts/sync-runtime-assets.sh`，用于把 runtime bundle 同步到目标仓库的 `.sopify-runtime/`
- bundle 同步后会生成 `.sopify-runtime/manifest.json`，用于描述入口、支持路由、builtin catalog 与 handoff 文件位置
- workspace bootstrap 的 `READY` 判定现在同时要求：
  - 满足 payload 声明的 required capabilities
  - 本地 bundle 具备关键 bridge / CLI 文件（如 `runtime/cli_interactive.py`、`scripts/clarification_bridge_runtime.py`、`scripts/decision_bridge_runtime.py`）
- runtime 现已真正写入 `.sopify-skills/state/current_handoff.json`，供宿主读取结构化下一步动作
- runtime 现已在真实项目首次触发时补最小 `blueprint/README.md`，并在首次进入 plan 生命周期时补齐完整 `blueprint/`
- runtime 现已支持增强版 clarification checkpoint：当 planning 请求缺少最小事实锚点时，会先写入 `.sopify-skills/state/current_clarification.json`；handoff 会同时附带 `clarification_form / clarification_submission_state`，宿主可通过 `runtime/clarification_bridge.py + scripts/clarification_bridge_runtime.py` 采集结构化补充信息，再通过默认入口恢复规划
- runtime 现已支持增强版 decision checkpoint：除显式多方案分叉外，还可优先消费 `RouteDecision.artifacts.decision_candidates` 的结构化候选方案，在满足“至少 2 个有效候选且 tradeoff 显著”时通过 `runtime/decision_templates.py + runtime/decision_policy.py` 生成统一 checkpoint，写入 handoff artifacts 与 `.sopify-skills/state/current_decision.json`，待确认后再生成正式 plan
- handoff 现已统一附带 `checkpoint_request`，作为 clarification / decision / execution_confirm 的标准化上游契约
- 若 runtime skill 或 develop callback 暴露结构化 tradeoff 信号但缺失可用 `checkpoint_request`，系统会输出 reason code `checkpoint_request_missing_but_tradeoff_detected` 并按 fail-closed 处理，防止“看起来有决策点但未进入标准 checkpoint 主链”的假闭环
- runtime 现已支持第一版 develop-first callback：宿主继续负责写代码，但开发中一旦出现用户拍板分叉，必须先通过 `runtime/develop_checkpoint.py + scripts/develop_checkpoint_runtime.py` 归一化为标准化 checkpoint，再复用既有 clarification / decision / resume 主链
- runtime 现已支持第一版 execution gate：plan 物化后会写入 machine contract，区分 `plan_generated` 与 `ready_for_execution`，不再只靠 `Next:` 文案暗示
- prompt-level runtime gate 已收口为 Layer 1 稳定层；它约束宿主必须先消费 gate contract，但不等同于宿主级硬入口
- `scripts/check-prompt-runtime-gate-smoke.py` 验证的是 Layer 1 gate contract 与 fail-closed 行为；`scripts/check-runtime-smoke.sh` 继续只验证 bundle/runtime 资产完整性，不证明宿主第一跳顺序
- 宿主级 first-hop ingress proof 与 doctor/smoke 仍属于下一层 host bridge 方案，不在当前发布切片内
- runtime 现已支持第一版 execution confirm：gate ready 后会统一输出 `execution_confirm_pending` handoff，写入 `confirm_execute` machine action 与最小执行摘要
- `go_plan_runtime.py` 现已默认自动消费 planning-mode 的 clarification / decision；若无法获得输入或桥接不完整，会 fail-closed 退出；仅 `--no-bridge-loop` 保留单次调试语义
- `~compare` 在至少返回 2 个成功结果时，会在 `current_handoff.json.artifacts.compare_decision_contract` 中附带 shortlist facade，供宿主复用 `DecisionCheckpoint` 形态的选择 UI；当前不会自动改写成主链路 `current_decision.json`
- replay 摘要现已稳定记录 decision checkpoint 创建、推荐项、推荐理由、最终选择与关键约束；`input / textarea` 原文默认不回放
- runtime 现已支持第一版 `~go finalize`：对 metadata-managed 活动 plan 执行 README 托管区块刷新、`history/` 归档与活动状态清理
- `.sopify-runtime/` bundle 内已包含便携 `tests/test_runtime.py` 与 `scripts/check-runtime-smoke.sh`
- 当前 `P1-A/P1-B` 已落地：首次运行会 bootstrap 最小 KB 骨架，显式 `~go finalize` 可完成 metadata-managed plan 的收口归档
- 旧遗留 plan 当前不会被自动迁移；第一版 finalize 只支持新 runtime 生成、带元数据的 plan
- 当前 KB 快照只读取根配置、manifest 与顶层目录，不做源码级扫描
- 不属于本轮发布切片：`~compare` 通过通用入口自动创建/恢复 `current_decision.json`、`workflow-learning` 的独立 runtime helper、runtime 全接管 develop orchestrator
- 因此当前已经适合“自用 + 二次接入”，但仍不是完整宿主安装器形态

### 文档治理约定

本节定义当前对外文档契约；runtime 自动化会按该契约逐步对齐。

接入 Sopify 的项目默认遵循以下文档治理模型：

- `blueprint/README.md` 是纯索引页，只保留 `状态 / 维护方式 / 当前目标 / 当前焦点 / 深入阅读入口`
- `blueprint/` 是项目级长期蓝图，默认进入版本管理
- 若 `blueprint/` 根层存在额外长期专题文档，`blueprint/README.md` 必须显式列出入口
- `plan/` 是工作中的方案包目录，默认本地使用、默认忽略；只有 `current_plan.path + current_plan.files` 绑定的那一个才是 machine-active plan
- `history/` 是收口后的方案归档，默认本地使用、默认忽略
- `state/` 是运行态 checkpoint / handoff 状态，始终忽略
- `replay/` 是可选回放能力，不属于基础文档治理契约
- 首次在真实项目仓库触发 Sopify 时，应至少拥有 `.sopify-skills/blueprint/README.md`
- 首次进入 plan 生命周期时，再补齐 `blueprint/background.md / design.md / tasks.md`
- 当前活动 plan 通过显式 `~go finalize` 进入“本轮任务收口、准备交付验证”事务后再归档到 `history/`
- 第一版 finalize 只支持 metadata-managed plan；旧遗留 plan 不自动迁移
- `active_plan` 的正式解析口径是 `current_plan.path + current_plan.files`
- `knowledge_sync` 是唯一正式同步契约；`blueprint_obligation` 只保留 legacy reject / projection 语义
- `blueprint/tasks.md` 只保留未完成长期项与明确延后项；已完成项不继续保留在该文件

### KB 职责矩阵

| Path | Layer | Responsibility | Created When | Default Consumer | Git Default |
|-----|------|------|------|------|------|
| `.sopify-skills/blueprint/README.md` | L0 index | 项目入口索引与阶段状态 | 首次真实项目触发 | 宿主、LLM、人 | tracked |
| `.sopify-skills/project.md` | L1 stable | 可复用技术约定 | 首次 bootstrap | runtime、planning、人 | tracked |
| `.sopify-skills/blueprint/background.md` | L1 stable | 长期目标、范围、非目标 | 首次 plan 生命周期或 `kb_init: full` | planning、人 | tracked |
| `.sopify-skills/blueprint/design.md` | L1 stable | 模块边界、宿主契约、目录契约、消费契约 | 首次 plan 生命周期或 `kb_init: full` | planning、develop、人 | tracked |
| `.sopify-skills/blueprint/tasks.md` | L1 stable | 未完成长期项与明确延后项 | 首次 plan 生命周期或 `kb_init: full` | finalize、人 | tracked |
| `.sopify-skills/plan/YYYYMMDD_feature/` | L2 active | 工作中的方案包；仅 `current_plan` 绑定的 plan 视为 machine-active | 每次正式进入方案流 | 宿主、develop、execution gate | ignored |
| `.sopify-skills/history/index.md` | L3 archive | 归档索引，仅用于查找 | 首次显式 `~go finalize` | 人 | ignored |
| `.sopify-skills/history/YYYY-MM/...` | L3 archive | 已收口方案归档 | 每次显式 `~go finalize` | 人、审计 | ignored |
| `.sopify-skills/state/*.json` | runtime | handoff / checkpoint / gate machine truth | runtime 执行期间 | 宿主、runtime | ignored |
| `.sopify-skills/replay/` | optional | 复盘摘要与学习记录 | 命中主动记录策略时 | 人 | ignored |

第一版 decision checkpoint 说明：

- 仅在 `~go plan / ~go / 进入 planning 路由` 时生效
- 当前自动触发已收口到 `runtime/decision_policy.py`：基线仍支持“显式多选分叉 + 架构关键词（如 `还是 / vs / or`）”；若 `RouteDecision.artifacts.decision_candidates` 提供结构化候选，则优先按“至少 2 个有效候选且 tradeoff 显著”触发，并支持 `decision_suppress / decision_preference_locked / decision_single_obvious / decision_information_only` 抑制
- 命中后会先暂停正式 plan 生成；宿主必须优先读取 `current_handoff.json.artifacts.decision_checkpoint / decision_submission_state`，`.sopify-skills/state/current_decision.json` 作为状态兜底
- 第一版模板已收口到 `runtime/decision_templates.py::strategy_pick`，并保留文本 fallback，供用户直接回复 `1/2` 或 `~decide choose <option_id>`
- handoff 还会附带 `decision_policy_id / decision_trigger_reason`，便于宿主或 replay 摘要理解本次 checkpoint 的触发依据
- handoff 还会优先附带标准化 `checkpoint_request`；宿主若已接入该 contract，必须优先消费它，再回退到 route-specific artifact
- 当前文档范围内，宿主可通过内部 helper `scripts/decision_bridge_runtime.py inspect` 读取 CLI bridge contract，再通过 `submit` 或 `prompt --renderer interactive|text|auto` 写回结构化 submission；默认恢复入口仍是 `scripts/sopify_runtime.py`
- vendored bundle 会通过 `.sopify-runtime/manifest.json -> limits.decision_bridge_entry / limits.decision_bridge_hosts` 暴露该 helper 与宿主 UI 提示
- `go_plan_runtime.py` 默认会自动进入 decision bridge；若无法完成用户输入或桥接恢复，则以非 0 fail-closed 退出；仅 `--no-bridge-loop` 保留单次调试语义

第一版 clarification checkpoint 说明：

- 仅在 `~go plan / ~go / 进入 planning 路由` 时生效
- 当前自动触发基于“缺最小事实锚点”的确定性规则，例如目标对象或预期结果仍不明确
- 命中后会先暂停正式 plan 生成，并写入 `.sopify-skills/state/current_clarification.json`
- 宿主看到 `current_handoff.json.required_host_action == answer_questions` 时，必须优先读取 `current_handoff.json.artifacts.clarification_form / clarification_submission_state`；`.sopify-skills/state/current_clarification.json` 继续作为状态兜底
- handoff 还会优先附带标准化 `checkpoint_request`；宿主若已接入该 contract，必须优先消费它，再回退到 clarification-specific artifact
- 当前文档范围内，宿主可通过内部 helper `scripts/clarification_bridge_runtime.py inspect` 读取轻量 form contract，再通过 `submit` 或 `prompt --renderer interactive|text|auto` 写回结构化补充信息；默认恢复入口仍是 `scripts/sopify_runtime.py`
- vendored bundle 会通过 `.sopify-runtime/manifest.json -> limits.clarification_bridge_entry / limits.clarification_bridge_hosts` 暴露该 helper 与宿主 UI 提示
- 当前主交互宿主是 CLI 型宿主（例如 Codex CLI、Claude Code）；decision / clarification 的当前文档范围只收口 CLI 终端问答桥接
- `go_plan_runtime.py` 默认会自动进入 clarification bridge；若无法完成用户输入或桥接恢复，则以非 0 fail-closed 退出；仅 `--no-bridge-loop` 保留单次调试语义

第一版 develop-first callback 说明：

- 仅在 `current_handoff.json.required_host_action == continue_host_develop` 后生效
- 宿主继续负责真实代码修改、测试与验证；runtime 不接管 develop 执行器
- 若 develop 中再次出现需要用户补事实或拍板选路的分叉，宿主不得直接自由追问，也不得手写 `current_decision.json / current_handoff.json`
- 当前文档范围内，宿主必须调用 `scripts/develop_checkpoint_runtime.py inspect` 确认当前上下文可回调，再通过 `submit --payload-json <json>` 提交结构化 payload；vendored bundle 对应 `.sopify-runtime/scripts/develop_checkpoint_runtime.py`
- payload 必须包含 `checkpoint_kind` 与 `resume_context`；当前 `resume_context` 至少要求 `active_run_stage / current_plan_path / task_refs / changed_files / working_summary / verification_todo`
- helper 会把 payload 归一化为标准化 `checkpoint_request`，写回 `.sopify-skills/state/current_decision.json` 或 `.sopify-skills/state/current_clarification.json`，并刷新 `.sopify-skills/state/current_handoff.json`
- handoff 会同时附带 `checkpoint_request / resume_context / develop_resume_context`；宿主必须继续复用既有 clarification / decision bridge 收集用户输入
- 用户确认后，runtime 会根据 `resume_context.resume_after` 返回 `continue_host_develop` 或 `review_or_execute_plan`

第一版 execution gate 说明：

- gate 会在 plan 物化后立即运行，并把 machine contract 写入 `current_run.json.execution_gate` 与 `current_handoff.json.artifacts.execution_gate`
- 当前固定字段为 `gate_status / blocking_reason / plan_completion / next_required_action`
- `plan_generated` 表示 plan 已存在但 gate 尚未通过；`ready_for_execution` 表示 plan 已通过机器执行门禁
- decision confirmed 后不会直接跳到 develop，而是会重新进入 gate；若 gate 仍发现阻塞风险，会再次回到 `decision_pending`

第一版 execution confirm 说明：

- 当 gate 结果为 `ready` 时，runtime 会把当前 plan 收口到 `execution_confirm_pending`，并把 `required_host_action` 设为 `confirm_execute`
- `current_handoff.json.artifacts.execution_summary` 会稳定提供 `plan_path / summary / task_count / risk_level / key_risk / mitigation`
- 用户可以直接用自然语言 `继续 / next / 开始` 确认执行；确认后活动 run 会进入 `executing`
- 若用户在确认阶段给出修改意见，runtime 会保留 execution-confirm 路径，但把 handoff 回退为 `review_or_execute_plan`
- 普通主链路不需要记忆 `~go exec`；宿主继续按 `confirm_execute` handoff 与自然语言确认入口推进即可
- `~go exec` 仅保留为高级恢复/调试入口；即使在 gate ready 阶段也不会直接跳入 develop，而是会先落到同一套 execution-confirm 入口

第一版 replay 摘要说明：

- replay 会记录 decision checkpoint 创建、推荐项、推荐理由、最终选择与关键约束摘要
- `~compare` 至少产生 2 个成功结果时，replay 也会记录 shortlist 数量、推荐结果与推荐依据
- `input / textarea` 等自由输入默认只记为“已提供补充说明”，不会在 replay 中回放原文

---

## 配置说明

### 配置文件

配置加载优先级（建议）：项目根 (`./sopify.config.yaml`) > 全局 (`~/.codex/sopify.config.yaml`，Claude 使用 `~/.claude/sopify.config.yaml`) > 内置默认值。

默认不会自动写入配置文件。推荐首次使用直接复制示例配置到项目根目录：

```bash
cp examples/sopify.config.yaml ./sopify.config.yaml
```

Windows 环境：请手动复制 `examples/sopify.config.yaml` 到项目根并重命名为 `sopify.config.yaml`。

在项目根目录创建（或使用示例复制生成的）`sopify.config.yaml`：

```yaml
# 品牌名: auto(默认由项目名生成 {repo}-ai) 或 自定义
brand: auto

# 语言: zh-CN / en-US
language: zh-CN

# 输出风格: minimal(简洁) / classic(带emoji)
output_style: minimal

# 标题颜色: green/blue/yellow/cyan/none
title_color: green

# 工作流配置
workflow:
  mode: adaptive        # strict / adaptive / minimal
  require_score: 7      # 需求评分阈值
  auto_decide: false    # AI 是否自动决策
  learning:
    auto_capture: by_requirement  # always / by_requirement / manual / off

# 方案包配置
plan:
  level: auto           # auto / light / standard / full
  directory: .sopify-skills    # 知识库目录

# 多模型对比（MVP）配置
multi_model:
  enabled: true
  trigger: manual       # 仅在 ~compare 或“对比分析：”触发
  timeout_sec: 25
  max_parallel: 3
  include_default_model: true  # 可选；默认 true（未配置也会生效）
  context_bridge: true  # 可选；默认 true（扩展模型默认走上下文桥接，false 为应急旁路）
  candidates:
    - id: glm
      enabled: true
      provider: openai_compatible
      base_url: https://open.bigmodel.cn/api/paas/v4
      model: glm-4.7
      api_key_env: GLM_API_KEY
    - id: qwen
      enabled: true
      provider: openai_compatible
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
      model: qwen-plus
      api_key_env: DASHSCOPE_API_KEY
```

说明：`title_color` 仅作用于输出标题行的轻量着色；终端不支持颜色时自动回退为纯文本。
说明：`workflow.learning.auto_capture` 仅控制是否主动记录；“回放/复盘/为什么这么做”意图识别始终开启。
说明：`multi_model.enabled` 是功能总开关，`multi_model.candidates[*].enabled` 是候选参与开关；两者语义不同且同时生效。
说明：`multi_model.include_default_model` 默认是 `true`（即使不写配置也会纳入当前会话默认模型）。
说明：`multi_model.context_bridge` 默认是 `true`；`false` 为应急旁路（仅发送问题文本）。执行细节统一以 `scripts/model_compare_runtime.py` 为准。
说明：进入并发对比需至少 2 个可用模型；不足时会降级单模型并输出原因明细。
说明：建议降级原因使用统一 reason code（如 `MISSING_API_KEY`、`INSUFFICIENT_USABLE_MODELS`）。
说明：`multi_model.candidates[*].api_key_env` 只读取环境变量，不建议在配置文件里写明文 key。

### 工作流模式

| 模式 | 说明 | 适用场景 |
|-----|------|---------|
| `strict` | 强制 3 阶段流程 | 需要完整文档的正式项目 |
| `adaptive` | 根据复杂度自动选择 (默认) | 日常开发 |
| `minimal` | 跳过规划，直接执行 | 快速原型、紧急修复 |

### workflow-learning 主动记录策略

| 配置值 | 行为 |
|-----|------|
| `always` | 所有开发任务主动记录（full） |
| `by_requirement` | 按复杂度主动记录：simple=off，medium=summary，complex=full |
| `manual` | 仅在明确提出“开始记录这次任务”后记录 |
| `off` | 不主动新建记录；可继续回放已有 session |

补充：无论上述策略如何，回放/复盘/原因解释的意图识别始终可用。

### 方案包级别

| 级别 | 文件结构 | 触发条件 |
|-----|---------|---------|
| `light` | `plan.md` 单文件 | 3-5 文件修改 |
| `standard` | `background.md` + `design.md` + `tasks.md` | >5 文件或新功能 |
| `full` | 标准 + `adr/` + `diagrams/` | 架构级变更 |

---

## 命令参考

| 命令 | 说明 |
|-----|------|
| `~go` | 全流程自动执行 |
| `~go plan` | 只规划不执行；当前仓库提供 `scripts/go_plan_runtime.py` 作为 plan-only helper |
| `~go exec` | 高级恢复/调试入口；仅在已有活动 plan 或恢复态存在时使用，不是普通主链路默认下一步 |
| `~go finalize` | 对当前 metadata-managed plan 执行收口事务：刷新 blueprint 索引、归档到 history、清理活动状态 |
| `~compare` | 按配置并发对比多个模型；运行时实现收口在 `scripts/model_compare_runtime.py`，但默认通用入口不会自动构造 compare payload |

说明：

- 当前默认 repo-local runtime 入口是 `scripts/sopify_runtime.py`，用于让原始输入直接交给 router 分流
- 若以 bundle 方式接入到其他仓库，默认入口对应 `.sopify-runtime/scripts/sopify_runtime.py`
- `scripts/go_plan_runtime.py` 只用于 plan-only slice
- vendored plan-only helper 对应 `.sopify-runtime/scripts/go_plan_runtime.py`
- 普通用户不需要记住 `~go exec`；标准链路会在 plan/gate ready 后进入 `execution_confirm_pending`，再由宿主引导自然语言确认
- `~go exec` 若没有活动 plan 或恢复态，只会返回高级恢复提示，不会产出 develop handoff
- `~go finalize` 没有单独 helper，仍走默认 runtime 入口；第一版仅支持 metadata-managed plan，旧遗留 plan 会被拒绝而不是自动迁移
- `~compare` 仍依赖宿主侧专用桥接，通用入口不会自动接通

---

## 多模型对比（MVP）

**触发条件（仅两种）：**
- `~compare <问题>`
- `对比分析：<问题>`

**环境变量（仅此方式）：**

```bash
# 当前终端会话生效
export GLM_API_KEY="your_glm_key"
export DASHSCOPE_API_KEY="your_qwen_key"
```

```bash
# zsh 永久生效（追加到 ~/.zshrc）
echo 'export GLM_API_KEY="your_glm_key"' >> ~/.zshrc
echo 'export DASHSCOPE_API_KEY="your_qwen_key"' >> ~/.zshrc
source ~/.zshrc
```

**行为说明：**
- `multi_model.enabled` 控制“是否启用对比功能”；`candidates[*].enabled` 控制“候选是否参与”
- 默认会纳入“当前会话默认模型”（`include_default_model` 默认 `true`，未配置也生效）
- 默认启用上下文桥接（`context_bridge=true`）：存在扩展模型候选时，会将“问题 + context_pack”统一发送；`false` 时仅发送问题文本（应急旁路）
- `~compare` 执行实现已收口到 `scripts/model_compare_runtime.py`（入口调用 `run_model_compare_runtime`）
- 至少产生 2 个成功结果时，handoff 会附带 `artifacts.compare_decision_contract`，提供 shortlist 版 `DecisionCheckpoint` facade 与推荐项，宿主可复用 decision bridge UI；当前不会自动创建 `current_decision.json`
- 执行层细节（抽取/脱敏/截断链路、预算、空包保护）统一以 `scripts/model_compare_runtime.py` 与子技能 `model-compare` 文档为准
- 可用模型数达到 2 才进入并发对比（该阈值为内置规则，无需配置）
- 降级原因建议使用统一 reason code（如 `MISSING_API_KEY`、`INSUFFICIENT_USABLE_MODELS`），避免中英文口径漂移
- 先返回的模型会先标记完成，但会继续等待其他模型直到超时或全部完成
- 单模型失败不影响其他模型；有可用结果就进入人工选择
- 若未进入对比（如总开关关闭、缺 key、可用模型数不足 2），不会报错，会自动单模型执行并输出“降级原因明细”

**上下文桥接案例（简版）：**

```text
~compare 这个 bug 为什么只在 prod 出现？

context_pack:
- 关键文件: src/api/auth.ts:42, src/config/env.ts:10
- 运行现象: 仅 prod 缺少 X-Trace-Id
- 脱敏: Authorization/Cookie 已替换为 <REDACTED>
- 截断: 仅保留命中函数前后 80 行
```

**降级原因明细（真实示例）：**

```text
[sopify-agent-ai] 咨询问答 !

未进入多模型并发，已按单模型执行。
降级原因:
- MISSING_API_KEY: candidate_id=glm
- INSUFFICIENT_USABLE_MODELS: 1<2
结果: 我是 Sopify 的 AI 编程助手，可帮你分析需求、设计方案与实现代码。

---
Changes: 0 files
Next: 可调整 multi_model.enabled / candidates[*].enabled / include_default_model / context_bridge 或补齐环境变量
```

---

## 子 Skills（扩展能力）

`skills/sopify` 下包含核心技能与子技能。总 README 仅提供导航，详细说明与使用指南请查看子技能文档。

| 子 Skill | 用途 | 文档 |
|---------|------|------|
| `model-compare` | 多模型并发对比（配置驱动、失败隔离、人工选择） | [中文说明](./Codex/Skills/CN/skills/sopify/model-compare/SKILL.md) / [English Guide](./Codex/Skills/EN/skills/sopify/model-compare/SKILL.md) |
| `workflow-learning` | 任务链路完整记录、回放与逐步讲解 | [中文说明](./Codex/Skills/CN/skills/sopify/workflow-learning/SKILL.md) / [English Guide](./Codex/Skills/EN/skills/sopify/workflow-learning/SKILL.md) |

子技能独立变更记录（与仓库总变更分离）：

- [workflow-learning Changelog (CN)](./Codex/Skills/CN/skills/sopify/workflow-learning/CHANGELOG.md)
- [workflow-learning Changelog (EN)](./Codex/Skills/EN/skills/sopify/workflow-learning/CHANGELOG.md)

## Skill Authoring（分层规范）

从 `2026-03-19` 起，Sopify skill 采用分层 package 规范。当前仓库中，`analyze/design/develop` 已在 Codex CN/EN 完成 prompt-layer 试点，Claude 侧由同步脚本镜像。

当前仓库实现（逻辑 package）：

```text
Codex/Skills/{CN,EN}/skills/sopify/<skill>/
├── SKILL.md        # 入口文档（触发 + 骨架 + 边界）
├── references/     # 长规则
├── assets/         # 模板与示例
└── scripts/        # 确定性逻辑

runtime/builtin_skill_packages/<skill>/
└── skill.yaml      # builtin machine metadata（routes/permissions/host_support）
```

关键约束：

- `Codex/Skills/{CN,EN}` 是 prompt-layer 真源，`Claude/Skills/{CN,EN}` 仅镜像
- `runtime/builtin_skill_packages/*/skill.yaml` 是 builtin machine metadata 真源
- route 绑定优先使用 `supports_routes`（声明式 resolver）
- `skill.yaml` 统一经 `runtime/skill_schema.py` 校验
- 当前仅对非法 `skill.yaml` schema / 不支持的 `host_support` / 非法 runtime `permission_mode` 执行 fail-closed
- `tools / disallowed_tools / allowed_paths / requires_network` 当前仅做声明字段，不做 runtime 强执行
- builtin catalog 由 `runtime/builtin_skill_packages/*/skill.yaml` 生成，不手写维护

维护者最小检查：

```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
python3 scripts/generate-builtin-catalog.py
python3 scripts/check-skill-eval-gate.py
python3 -m unittest tests.test_runtime -v
```

详见规范文档：

- [专项蓝图收口文档](./.sopify-skills/blueprint/skill-standards-refactor.md)
- [Skill Eval Baseline](./evals/skill_eval_baseline.json)
- [Skill Eval SLO](./evals/skill_eval_slo.json)

---

## 同步机制（维护者）

为避免 Codex/Claude 与中英文规则漂移，仓库内置同步与校验脚本：

```bash
# 1) 从 Codex prompt-layer 真源同步到 Claude 镜像
bash scripts/sync-skills.sh

# 2) 校验四套文件是否一致
bash scripts/check-skills-sync.sh

# 3) 校验版本一致性（README 徽章 / SOPIFY_VERSION / CHANGELOG）
bash scripts/check-version-consistency.sh
```

脚本默认忽略 Finder/Explorer 噪音文件（`.DS_Store`、`Thumbs.db`），避免误报。
建议在提交技能规则改动前固定执行一次 `sync -> check-skills-sync -> check-version-consistency`。
CI（`.github/workflows/ci.yml`）会在 PR/Push 执行同样门禁，并用 `git diff --exit-code` 拦截“先同步才能通过”的漂移改动。
若同时修改 `runtime/builtin_skill_packages/*/skill.yaml`，还应补跑 catalog / eval / runtime test。

---

## 输出格式

Sopify (Sop AI) Skills 使用简洁的输出格式：

```
[my-app-ai] 方案设计 ✓

方案: .sopify-skills/plan/20260115_user_auth/
概要: JWT 认证 + Redis session 管理
任务: 5 项

---
Changes: 3 files
  - .sopify-skills/plan/20260115_user_auth/background.md
  - .sopify-skills/plan/20260115_user_auth/design.md
  - .sopify-skills/plan/20260115_user_auth/tasks.md

Next: 在宿主会话中继续评审或执行方案，或直接回复修改意见
```

**状态符号：**
- `✓` 成功
- `?` 等待输入
- `!` 警告
- `×` 错误

**阶段名使用：**
- `命令完成`：用于带命令前缀的流程输出（`~go/~go plan/~go exec/~compare`）
- `咨询问答`：用于无命令前缀的问答/澄清场景

---

## 目录结构

```
.sopify-skills/                # 知识库根目录
├── blueprint/                 # 项目级长期蓝图，默认进入版本管理
│   ├── README.md              # 纯索引页，只保留状态/维护方式/当前目标/当前焦点/阅读入口
│   ├── background.md          # 长期目标、范围、非目标
│   ├── design.md              # 模块/宿主/目录/消费契约
│   └── tasks.md               # 未完成长期项与明确延后项
├── project.md                 # 项目技术约定（不重复 background/design）
├── user/
│   ├── preferences.md         # 用户长期偏好
│   └── feedback.jsonl         # 原始反馈事件
├── plan/                      # 当前活动方案，默认忽略
│   └── YYYYMMDD_feature/
│       ├── background.md      # 需求背景 (原 why.md)
│       ├── design.md          # 技术设计 (原 how.md)
│       └── tasks.md           # 任务清单 (原 task.md)
├── history/                   # 收口后的方案归档，默认忽略
│   ├── index.md
│   └── YYYY-MM/
├── state/                     # 运行态状态，始终忽略
└── replay/                    # 可选回放能力，默认忽略
```

默认 Git 策略：

- `blueprint/` 默认进入版本管理
- `plan/` 与 `history/` 默认本地使用、默认忽略
- `state/` 与 `replay/` 默认忽略
- 项目可按自身需要调整 `.gitignore`，但默认建议保持以上分层

---

## 与 HelloAGENTS 的区别

| 特性 | HelloAGENTS | Sopify (Sop AI) Skills |
|-----|-------------|--------------|
| 品牌名 | 固定 "HelloAGENTS" | 由项目名生成 "{repo}-ai" |
| 输出风格 | 多 emoji | 简洁文本 |
| 工作流 | 固定 3 阶段 | 自适应 |
| 方案包 | 固定 3 文件 | 分级 (light/standard/full) |
| 文件命名 | why.md/how.md/task.md | background.md/design.md/tasks.md |
| 配置 | 分散在规则中 | 统一 sopify.config.yaml |
| 规则复杂度 | G1-G12 (12 条) | Core/Auto/Advanced 分层 |

---

## 文件说明

```
sopify-skills/
├── Claude/
│   └── Skills/
│       ├── CN/                 # 中文版
│       │   ├── CLAUDE.md       # 主配置文件
│       │   └── skills/sopify/  # 核心技能 + 子 Skills
│       └── EN/                 # 英文版
├── Codex/
│   └── Skills/                 # Codex CLI 版本
├── runtime/
│   ├── builtin_skill_packages/ # builtin skill machine metadata 真源
│   └── builtin_catalog.generated.json
├── examples/
│   └── sopify.config.yaml      # 配置示例
├── README.md                   # 中文文档
└── README_EN.md                # 英文文档
```

---

## 常见问题

### Q: 如何切换语言？

修改 `sopify.config.yaml` 中的 `language` 字段：
```yaml
language: en-US  # 或 zh-CN
```

### Q: 如何禁用自适应模式？

设置工作流模式为 strict：
```yaml
workflow:
  mode: strict
```

### Q: 方案包存放在哪里？

默认存放在项目根目录的 `.sopify-skills/` 目录下。可通过配置修改：
```yaml
plan:
  directory: .my-custom-dir
```

注意：修改 `plan.directory` 仅影响后续新生成的知识库/方案文件目录，默认不会自动迁移旧目录中的历史内容；如需迁移请手动移动目录或保持该值不变。

### Q: 如何跳过需求评分追问？

设置 `auto_decide: true`：
```yaml
workflow:
  auto_decide: true
```

### Q: 用户偏好如何重置？

删除（或清空）`.sopify-skills/user/preferences.md` 即可重置长期偏好；`feedback.jsonl` 可按需保留用于审计。

### Q: 同步脚本什么时候用？

当你修改 `Codex/Skills/{CN,EN}` 下的 prompt-layer 文档，或修改 `runtime/builtin_skill_packages/*/skill.yaml` 元数据后，建议至少运行：
```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
python3 scripts/generate-builtin-catalog.py
python3 scripts/check-skill-eval-gate.py
python3 -m unittest tests.test_runtime -v
```
若校验失败，先修复差异再提交。

---

## 版本历史

- 详细变更记录见 `CHANGELOG.md`（手工维护）

## 许可证

本仓库尝试采用双许可（以许可证文件为准）：

- 代码与配置（含示例配置）：Apache 2.0（见 `LICENSE`）
- 文档（主要为 Markdown）：CC BY 4.0（见 `LICENSE-docs`）

如果你发现某些内容的来源/署名/许可信息可能需要补充（例如有参考或改进自其他开源仓库的部分），欢迎提 Issue 或在 PR 中说明。

---

## 贡献

欢迎提交 Issue 和 PR！
