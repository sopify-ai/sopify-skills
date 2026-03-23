# Sopify (Sop AI) Skills

<div align="center">

**配置驱动的自适应 AI 编程技能包**

[![许可证](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![文档](https://img.shields.io/badge/docs-CC%20BY%204.0-green.svg)](./LICENSE-docs)
[![版本](https://img.shields.io/badge/version-2026--03--23.185925-orange.svg)](#版本历史)
[![欢迎PR](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING_CN.md)

[English](./README_EN.md) · [简体中文](./README.md) · [快速开始](#快速开始) · [配置说明](#配置说明)

</div>

---

## 为什么选择 Sopify (Sop AI) Skills？

传统 AI 编程助手对所有任务使用同一套重流程——即使改一个 typo 也要走需求分析、方案设计、开发实施。Sopify 根据复杂度自动路由，让简单任务直接执行，复杂任务才走完整规划。

| 任务类型 | 传统方式 | Sopify 路径 |
|---------|---------|-------------|
| 简单修改（≤2 文件） | 完整三阶段 | 直接执行 |
| 中等任务（3-5 文件） | 完整三阶段 | light 方案 + 执行 |
| 复杂任务（>5 文件 / 架构变更） | 完整三阶段 | 完整三阶段 |

### 核心特性

- 一次安装，进入项目后按需自动准备 `.sopify-runtime/`
- 配置驱动的复杂度路由，减少简单任务的流程负担
- manifest-first 机器契约，宿主按 handoff 和 gate 决定下一步
- checkpoint 可恢复，clarification / decision / execution confirm 口径统一
- 支持 Codex CLI 与 Claude Code 双宿主
- 内建多模型对比与 workflow-learning 扩展能力，可按需开启

**设计来源：** Sopify 借鉴 harness engineering 思路，用结构化知识替代自由 prompt、用机器契约替代隐式约定、用可观测 checkpoint 替代盲执行。详见 [工作流说明](./docs/how-sopify-works.md)。

### 建议工作流

```text
○ 用户输入
│
◆ Runtime Gate
│
◇ 路由判定
├── ▸ 咨询 / 对比 / 回放 ───────────→ 直接输出
└── ▸ 代码任务
    │
    ◇ 复杂度判定
    ├── 简单（≤2 文件）────────────→ 直接执行
    ├── 中等（3-5 文件）──────────→ 轻量方案包
    │                               （单文件 `plan.md`）
    └── 复杂（>5 文件 / 架构变更）
        ├── 需求分析 ··· 补事实 checkpoint
        ├── 方案设计 ··· 拍板 checkpoint
        └── 标准方案包
            （`background.md` / `design.md` / `tasks.md`）
            │
            ◆ 执行确认 ··· 用户确认继续
            │
            ◆ 开发实施
            │
            ◆ 摘要输出 + Handoff
            │
            ◇ 可选：~go finalize
            ├── 刷新 blueprint 索引
            ├── 清理 state 活动态
            └── 归档 → history/
```

> ◆ = 执行节点　◇ = 判定节点　··· = checkpoint（可暂停，等用户输入后恢复）
>
> 详细流程与 checkpoint 机制见 [工作流说明](./docs/how-sopify-works.md)。

## 快速开始

### 安装

```bash
# 推荐：先安装到 Codex 中文环境
bash scripts/install-sopify.sh --target codex:zh-CN

# 可选：显式预热某个目标仓库
bash scripts/install-sopify.sh --target claude:en-US --workspace /path/to/project
```

支持的 `target`：

- `codex:zh-CN`
- `codex:en-US`
- `claude:zh-CN`
- `claude:en-US`

安装后行为：

- installer 会安装宿主提示层，并在宿主根目录安装 Sopify payload
- 传入 `--workspace` 时，会额外预热目标仓库的 `.sopify-runtime/`
- 不传 `--workspace` 时，后续首次在项目仓库触发 Sopify 会自动 bootstrap

### 首次使用

```bash
# 简单任务
"修复 src/utils.ts 第 42 行的 typo"

# 中等任务
"给登录、注册、找回密码添加错误处理"

# 复杂任务
"~go 添加用户认证功能，使用 JWT"

# 只规划
"~go plan 重构数据库层"

# 回放 / 复盘
"回放最近一次实现，重点讲为什么这么做"

# 多模型对比
"~compare 给这个重构方案做对比分析"
```

若想先理解 runtime gate、checkpoint 与 plan 生命周期，直接看 [工作流说明](./docs/how-sopify-works.md)。

## 配置说明

推荐从示例配置开始：

```bash
cp examples/sopify.config.yaml ./sopify.config.yaml
```

最常用的配置项：

```yaml
brand: auto
language: zh-CN

workflow:
  mode: adaptive
  require_score: 7

plan:
  directory: .sopify-skills

multi_model:
  enabled: false
  include_default_model: true
```

说明：

- `workflow.mode` 支持 `strict / adaptive / minimal`
- `plan.directory` 只影响后续新生成的知识库与方案目录
- `multi_model.enabled` 是总开关；候选模型可在配置中逐个启停
- `multi_model` 默认关闭；配置好模型候选与 API key 后再开启更稳
- `multi_model.include_default_model` 与 `context_bridge` 默认都生效，即使未显式写入

## 命令参考

| 命令 | 说明 |
|-----|------|
| `~go` | 自动判断并执行完整流程 |
| `~go plan` | 只规划不执行 |
| `~go exec` | 高级恢复/调试入口，不是普通主链路默认下一步 |
| `~go finalize` | 收口当前 metadata-managed plan |
| `~compare` | 对同一问题做多模型并发对比 |

普通用户只需要记住 `~go / ~go plan / ~compare`；维护者验证命令放在 [贡献指南](./CONTRIBUTING_CN.md)。

## 多模型对比

触发方式只有两种：

- `~compare <问题>`
- `对比分析：<问题>`

最小环境变量示例：

```bash
export GLM_API_KEY="your_glm_key"
export DASHSCOPE_API_KEY="your_qwen_key"
```

补充说明：

- 至少 2 个可用模型时才进入并发对比，否则自动降级为单模型
- 默认会纳入当前会话模型
- 执行细节以 `scripts/model_compare_runtime.py` 与子 Skill 文档为准

## 子 Skills

- `model-compare`：多模型并发对比
  文档：[中文](./Codex/Skills/CN/skills/sopify/model-compare/SKILL.md) / [English](./Codex/Skills/EN/skills/sopify/model-compare/SKILL.md)
- `workflow-learning`：回放、复盘与逐步讲解
  文档：[中文](./Codex/Skills/CN/skills/sopify/workflow-learning/SKILL.md) / [English](./Codex/Skills/EN/skills/sopify/workflow-learning/SKILL.md)

## 目录结构

```text
sopify-skills/
├── docs/                  # 工作流说明文档
├── .sopify-skills/        # 项目知识库
│   ├── blueprint/         # 长期蓝图
│   ├── plan/              # 活跃方案
│   └── history/           # 已归档方案
├── Codex/                 # Codex 宿主提示层
└── Claude/                # Claude 宿主提示层
```

完整工作流、checkpoint 和知识库层级说明见 [docs/how-sopify-works.md](./docs/how-sopify-works.md)。

## 常见问题

### Q: 如何切换语言？

修改 `sopify.config.yaml`：

```yaml
language: en-US  # 或 zh-CN
```

### Q: 方案包存放在哪里？

默认在项目根目录的 `.sopify-skills/`。如需修改：

```yaml
plan:
  directory: .my-custom-dir
```

修改后只影响后续新生成的目录，不会自动迁移历史内容。

### Q: 用户偏好如何重置？

删除或清空 `.sopify-skills/user/preferences.md` 即可；`feedback.jsonl` 可按需保留用于审计。

### Q: 同步脚本什么时候用？

当你修改 `Codex/Skills/{CN,EN}`、`Claude/Skills/{CN,EN}` 镜像内容，或修改 `runtime/builtin_skill_packages/*/skill.yaml` 时，按 [贡献指南](./CONTRIBUTING_CN.md) 跑同步与校验命令。

## 版本历史

- 详细变更记录见 [CHANGELOG.md](./CHANGELOG.md)

## 许可证

本仓库采用双许可：

- 代码与配置：Apache 2.0，见 [LICENSE](./LICENSE)
- 文档：CC BY 4.0，见 [LICENSE-docs](./LICENSE-docs)

## 贡献

提交用户可见行为改动时，建议同步更新 `README.md` / `README_EN.md`，并参考 [CONTRIBUTING_CN.md](./CONTRIBUTING_CN.md) 执行校验。
