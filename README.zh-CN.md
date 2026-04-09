# Sopify

<div align="center">

<img src="./assets/logo.svg" width="120" alt="Sopify Logo" />

**可恢复、可复盘、可沉淀的 AI 编程工作流**

[![许可证](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![文档](https://img.shields.io/badge/docs-CC%20BY%204.0-green.svg)](./LICENSE-docs)
[![版本](https://img.shields.io/badge/version-2026--04--09.203519-orange.svg)](#版本历史)
[![欢迎PR](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING_CN.md)

[English](./README.md) · 简体中文 · [快速开始](#快速开始) · [配置说明](#配置说明) · [贡献者](./CONTRIBUTORS.md)

</div>

---

## 为什么选择 Sopify？

随着仓库增长，AI 辅助开发会遇到一个隐性问题：决策依据散落在对话里，每次新 session 都要重新理解上下文，用户认知、AI 理解和代码现状会逐渐偏离。

Sopify 用机器可读协议把关键节点变成可见流程：缺事实时停下来补事实，需要拍板时等待你确认，中断后从当前状态恢复，而不是让 AI 自行拍板。基础过程记录会自动产生，长期复利则取决于是否持续做阶段收口和维护知识资产。

### 你会实际感受到什么

- 关键节点不会由 AI 自行拍板，缺事实或需要选路时会停下来等你确认
- 中断后可以从上次停点恢复，不必重新把背景再讲一遍
- 方案、历史和蓝图会沉淀为项目资产，而不只是一次性聊天记录
- 简单改动不会被完整流程拖慢，复杂任务再补上必要管理

### 在哪类项目里最有价值

- 在同一仓库中持续推进多阶段工作，而不是一次性改动
- 愿意用 plan / blueprint 管理进展，并在阶段完成后持续做收口

## 安装后你会得到什么

- 安装后，你的宿主已可运行 Sopify。
- 首次在项目仓库里触发 Sopify 时，才会准备本地 `.sopify-runtime/`。
- `status` 用来看当前 host / workspace 状态。
- `doctor` 用来看更深的安装与运行时诊断及修复建议。

本文只聚焦安装可见性、自检与首次使用路径，不展开仓库清理流程。

## 快速开始

### 安装

```bash
# 推荐：稳定版一行安装
curl -fsSL https://github.com/sopify-ai/sopify/releases/latest/download/install.sh | bash -s -- --target codex:zh-CN

# 两步安装：先下载，确认后再执行
curl -fsSL -o sopify-install.sh https://github.com/sopify-ai/sopify/releases/latest/download/install.sh
sed -n '1,40p' sopify-install.sh
bash sopify-install.sh --target codex:zh-CN
```

Windows PowerShell 可下载同一份 stable asset 后执行：

```powershell
iwr https://github.com/sopify-ai/sopify/releases/latest/download/install.ps1 -OutFile sopify-install.ps1
Get-Content sopify-install.ps1 -TotalCount 40
.\sopify-install.ps1 --target codex:zh-CN
```

开发者 / 源码安装路径仍保留，但不再作为首屏主入口：

```bash
bash scripts/install-sopify.sh --target codex:zh-CN
python3 scripts/install_sopify.py --target claude:zh-CN --workspace /path/to/project
```

支持的 `target`：

- `codex:zh-CN`
- `codex:en-US`
- `claude:zh-CN`
- `claude:en-US`

当前正式支持矩阵：

| 宿主 | 支持级别 | 验证范围 | 说明 |
|------|----------|----------|------|
| `codex` | 正式支持 | 已验证宿主安装链路、workspace bootstrap，且运行时包已通过 smoke 验证 | 适合日常使用 |
| `claude` | 正式支持 | 已验证宿主安装链路、workspace bootstrap，且运行时包已通过 smoke 验证 | 适合日常使用 |

说明：

- 当前正式支持只有 `codex / claude`
- README 只展示当前正式支持宿主；更细的 capability claim 与现场诊断请看 `sopify status` / `sopify doctor`
- “支持级别”表示产品承诺层级；“验证范围”表示当前已经验证到哪一层

安装后行为：

- installer 会安装宿主提示层，并在宿主根目录安装 Sopify payload
- 默认安装后，宿主已可运行 Sopify；大多数用户不需要 `--workspace`
- 首次在项目仓库里触发 Sopify 时，才会准备 `.sopify-runtime/`
- `--workspace` 适用于维护者、CI 或显式预热仓库的高级路径

### 安装后怎么确认正常

```bash
python3 scripts/sopify_status.py --format text
python3 scripts/sopify_doctor.py --format text
```

- `will bootstrap on first project trigger`：宿主安装已就绪，项目侧 runtime 还未准备，这是正常状态
- `workspace outcome: stub_selected [continue]`：workspace runtime 入口健康
- 如果 doctor 报出 payload 或 bundle 损坏类错误（例如 `global_bundle_missing`、`global_bundle_incompatible`、`global_index_corrupted`），先修复安装，再重试

### 根据任务规模选入口

| 任务类型 | Sopify 处理方式 |
|---------|----------------|
| 简单修改（≤2 文件） | 直接执行 |
| 中等任务（3-5 文件） | 轻量方案 + 执行 |
| 复杂任务（>5 文件 / 架构变更） | 完整三阶段 |

### 首次使用

安装完成后，在仓库目录中打开 Codex 或 Claude，直接粘贴下面任一条提示即可开始。

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

### 你会看到什么（示意）

```text
[my-app-ai] 方案设计 ✓

方案: .sopify-skills/plan/20260323_auth/
概要: JWT 认证 + token 刷新 + 路由守卫
任务: 5 项

---
Next: 回复“继续”进入开发实施
```

这个示意只展示风格与节奏，不代表固定字段；简单任务会更短，复杂任务会在 checkpoint 处暂停等待你确认。

若想先理解 runtime gate、checkpoint 与 plan 生命周期，直接看 [工作流说明](./docs/how-sopify-works.md)。

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

Claude 宿主使用镜像结构的 `Claude/Skills/{CN,EN}/...` 路径；上述链接以 Codex 目录作为统一文档入口。

## 目录结构

```text
sopify/
├── scripts/               # 安装、诊断与维护脚本
├── examples/              # 配置示例
├── docs/                  # 工作流说明文档
├── runtime/               # 内置 runtime / skill packages
├── .sopify-skills/        # 项目知识库
│   ├── blueprint/         # 长期蓝图
│   ├── plan/              # 活跃方案
│   └── history/           # 已归档方案
├── Codex/                 # Codex 宿主提示层
└── Claude/                # Claude 宿主提示层
```

上面是核心目录的精简视图；完整工作流、checkpoint 和知识库层级说明见 [docs/how-sopify-works.md](./docs/how-sopify-works.md)。

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

### Q: 什么时候需要 `--workspace` 预热？

大多数用户不需要。默认安装已经完整；首次在项目仓库里触发 Sopify 时，会自动 bootstrap `.sopify-runtime/`。

只有在维护者验证、CI，或你明确想提前为某个仓库准备 `.sopify-runtime/` 时，才需要 `--workspace`。这类高级场景建议走源码安装路径：

```bash
python3 scripts/install_sopify.py --target codex:zh-CN --workspace /path/to/project
```

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

提交用户可见行为改动时，建议同步更新 `README.md` / `README.zh-CN.md`，并参考 [CONTRIBUTING_CN.md](./CONTRIBUTING_CN.md) 执行校验。
