# Sopify (Sop AI) Skills

<div align="center">

**标准 Sop AI Skills - 配置驱动的 Codex/Claude 技能包：按任务复杂度自动路由执行流程**

[![许可证](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![文档](https://img.shields.io/badge/docs-CC%20BY%204.0-green.svg)](./LICENSE-docs)
[![版本](https://img.shields.io/badge/version-2026--02--13-orange.svg)](#版本历史)
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

- **自适应工作流** - 简单任务秒级完成，复杂任务完整规划
- **简洁输出** - 核心信息一屏可见，详情在文件里
- **配置驱动** - 通过 `sopify.config.yaml` 定制所有行为
- **动态品牌** - 默认由项目名生成 `{repo}-ai` 作为输出标识
- **方案包分级** - light/standard/full 三级，按需生成
- **工作流学习** - 支持实现链路回放、复盘与逐步讲解
- **跨平台支持** - Claude Code 和 Codex CLI 双平台

---

## 快速开始

### 前置条件

- CLI 环境 (Claude Code 或 Codex CLI)
- 文件系统访问权限

### 安装

**Claude Code 用户：**

```bash
# 中文版
cp -r Claude/Skills/CN/* ~/.claude/

# 英文版
cp -r Claude/Skills/EN/* ~/.claude/
```

**Codex CLI 用户：**

```bash
# 中文版
cp -r Codex/Skills/CN/* ~/.codex/

# 英文版
cp -r Codex/Skills/EN/* ~/.codex/
```

### 验证安装

重启终端，输入：
```
显示技能列表
```

**预期输出：** Agent 列出 7 个技能 (analyze, design, develop, kb, templates, model-compare, workflow-learning)

### 首次使用

```bash
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
| `~go plan` | 只规划不执行 |
| `~go exec` | 执行已有方案 |
| `~compare` | 按配置并发对比多个模型；默认纳入当前会话模型，可用模型数不足 2 时单模型降级并说明原因 |

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

---

## 同步机制（维护者）

为避免 Codex/Claude 与中英文规则漂移，仓库内置同步与校验脚本：

```bash
# 1) 从 Codex 真源同步到 Claude 镜像
bash scripts/sync-skills.sh

# 2) 校验四套文件是否一致
bash scripts/check-skills-sync.sh

# 3) 校验版本一致性（README 徽章 / SOPIFY_VERSION / CHANGELOG）
bash scripts/check-version-consistency.sh
```

脚本默认忽略 Finder/Explorer 噪音文件（`.DS_Store`、`Thumbs.db`），避免误报。
建议在提交技能规则改动前固定执行一次 `sync -> check-skills-sync -> check-version-consistency`。
CI（`.github/workflows/ci.yml`）会在 PR/Push 执行同样门禁，并用 `git diff --exit-code` 拦截“先同步才能通过”的漂移改动。

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

Next: ~go exec 执行 或 回复修改意见
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
├── project.md                 # 项目技术约定
├── wiki/
│   ├── overview.md            # 项目概述
│   └── modules/               # 模块文档
├── user/
│   ├── preferences.md         # 用户长期偏好
│   └── feedback.jsonl         # 原始反馈事件
├── plan/                      # 当前方案
│   └── YYYYMMDD_feature/
│       ├── background.md      # 需求背景 (原 why.md)
│       ├── design.md          # 技术设计 (原 how.md)
│       └── tasks.md           # 任务清单 (原 task.md)
└── history/                   # 历史方案
    ├── index.md
    └── YYYY-MM/
```

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

当你修改 `Codex/Skills/{CN,EN}` 下的规则文件后，运行：
```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
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
