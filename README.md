# Sopify Agent

<div align="center">

**自适应 AI 编程助手 - 根据任务复杂度智能选择工作流，简洁高效**

[English](./README_EN.md) · [简体中文](./README.md) · [快速开始](#-快速开始) · [配置说明](#-配置说明)

</div>

---

## 为什么选择 Sopify Agent？

**问题：** 传统 AI 编程助手对所有任务都使用相同的重量级流程 - 简单的 typo 修复也要走完整的需求分析、方案设计流程，效率低下且输出冗余。

**解决方案：** Sopify Agent 引入**自适应工作流**，根据任务复杂度自动选择最优路径：

| 任务类型 | 传统方式 | Sopify Agent |
|---------|---------|--------------|
| 简单修改 (≤2 文件) | 完整 3 阶段流程 | 直接执行，跳过规划 |
| 中等任务 (3-5 文件) | 完整 3 阶段流程 | 轻量方案 (单文件) + 执行 |
| 复杂任务 (>5 文件) | 完整 3 阶段流程 | 完整 3 阶段流程 |

### 核心特性

- **自适应工作流** - 简单任务秒级完成，复杂任务完整规划
- **简洁输出** - 核心信息一屏可见，详情在文件里
- **配置驱动** - 通过 `sopify.config.yaml` 定制所有行为
- **动态品牌** - 自动获取仓库名作为输出标识
- **方案包分级** - light/standard/full 三级，按需生成
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

**预期输出：** Agent 列出 5 个技能 (analyze, design, develop, kb, templates)

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
```

---

## 配置说明

### 配置文件

在项目根目录创建 `sopify.config.yaml`：

```yaml
# 品牌名: auto(自动获取) 或 自定义
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

# 方案包配置
plan:
  level: auto           # auto / light / standard / full
  directory: .sopify    # 知识库目录
```

### 工作流模式

| 模式 | 说明 | 适用场景 |
|-----|------|---------|
| `strict` | 强制 3 阶段流程 | 需要完整文档的正式项目 |
| `adaptive` | 根据复杂度自动选择 (默认) | 日常开发 |
| `minimal` | 跳过规划，直接执行 | 快速原型、紧急修复 |

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

---

## 输出格式

Sopify Agent 使用简洁的输出格式：

```
[my-app-ai] 方案设计 ✓

方案: .sopify/plan/20260115_user_auth/
概要: JWT 认证 + Redis session 管理
任务: 5 项

---
Changes: 3 files
  - .sopify/plan/20260115_user_auth/background.md
  - .sopify/plan/20260115_user_auth/design.md
  - .sopify/plan/20260115_user_auth/tasks.md

Next: ~go exec 执行 或 回复修改意见
```

**状态符号：**
- `✓` 成功
- `?` 等待输入
- `!` 警告
- `×` 错误

---

## 目录结构

```
.sopify/                        # 知识库根目录
├── project.md                  # 项目技术约定
├── wiki/
│   ├── overview.md            # 项目概述
│   └── modules/               # 模块文档
├── plan/                       # 当前方案
│   └── YYYYMMDD_feature/
│       ├── background.md      # 需求背景 (原 why.md)
│       ├── design.md          # 技术设计 (原 how.md)
│       └── tasks.md           # 任务清单 (原 task.md)
└── history/                    # 历史方案
    ├── index.md
    └── YYYY-MM/
```

---

## 与 HelloAGENTS 的区别

| 特性 | HelloAGENTS | Sopify Agent |
|-----|-------------|--------------|
| 品牌名 | 固定 "HelloAGENTS" | 动态 "{repo}-ai" |
| 输出风格 | 多 emoji | 简洁文本 |
| 工作流 | 固定 3 阶段 | 自适应 |
| 方案包 | 固定 3 文件 | 分级 (light/standard/full) |
| 文件命名 | why.md/how.md/task.md | background.md/design.md/tasks.md |
| 配置 | 分散在规则中 | 统一 sopify.config.yaml |
| 规则复杂度 | G1-G12 (12 条) | Core/Auto/Advanced 分层 |

---

## 文件说明

```
sopify-agent/
├── Claude/
│   └── Skills/
│       ├── CN/                 # 中文版
│       │   ├── CLAUDE.md       # 主配置文件
│       │   └── skills/sopify/  # 技能模块
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

默认存放在项目根目录的 `.sopify/` 目录下。可通过配置修改：
```yaml
plan:
  directory: .my-custom-dir
```

### Q: 如何跳过需求评分追问？

设置 `auto_decide: true`：
```yaml
workflow:
  auto_decide: true
```

---

## 许可证

Apache 2.0

---

## 贡献

欢迎提交 Issue 和 PR！
