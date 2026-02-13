---
name: kb
description: 知识库管理技能；知识库操作时读取；包含初始化、更新、同步策略
---

# 知识库管理 - 详细规则

**目标：** 管理项目知识库，保持文档与代码同步

**知识库目录：** `.sopify-skills/`

---

## 知识库结构

```
.sopify-skills/
├── project.md              # 项目技术约定
├── wiki/
│   ├── overview.md         # 项目概述
│   ├── arch.md             # 架构设计 (可选)
│   ├── api.md              # API 手册 (可选)
│   ├── data.md             # 数据模型 (可选)
│   └── modules/            # 模块文档
│       └── {module}.md
├── user/
│   ├── preferences.md      # 用户长期偏好
│   └── feedback.jsonl      # 原始反馈事件
├── plan/                   # 当前方案
│   └── YYYYMMDD_feature/
└── history/                # 历史方案
    ├── index.md            # 索引
    └── YYYY-MM/
        └── YYYYMMDD_feature/
```

---

## 初始化策略

### Full 模式 (kb_init: full)

一次性创建所有模板文件：
```yaml
创建文件:
  - .sopify-skills/project.md
  - .sopify-skills/wiki/overview.md
  - .sopify-skills/wiki/arch.md
  - .sopify-skills/wiki/api.md
  - .sopify-skills/wiki/data.md
  - .sopify-skills/user/preferences.md
  - .sopify-skills/user/feedback.jsonl
  - .sopify-skills/wiki/modules/.gitkeep
  - .sopify-skills/plan/.gitkeep
  - .sopify-skills/history/index.md
```

### Progressive 模式 (kb_init: progressive) [默认]

按需创建文件：
```yaml
首次初始化:
  - .sopify-skills/project.md (必须)

首个方案时:
  - .sopify-skills/plan/ 目录
  - .sopify-skills/history/index.md

首次涉及模块文档时:
  - .sopify-skills/wiki/overview.md
  - .sopify-skills/wiki/modules/{module}.md

首次涉及 API 时:
  - .sopify-skills/wiki/api.md

首次涉及数据模型时:
  - .sopify-skills/wiki/data.md

首次出现"明确长期偏好"时:
  - .sopify-skills/user/preferences.md
  - .sopify-skills/user/feedback.jsonl
```

---

## 项目上下文获取

**获取流程：**
```
1. 检查 .sopify-skills/ 是否存在
2. 存在 → 读取知识库文件
3. 不存在或信息不足 → 扫描代码获取
```

**代码扫描策略：**
```yaml
技术栈识别:
  - package.json → Node/前端项目
  - requirements.txt / pyproject.toml → Python 项目
  - go.mod → Go 项目
  - Cargo.toml → Rust 项目
  - pom.xml / build.gradle → Java 项目

项目结构:
  - src/ 目录结构
  - 配置文件位置
  - 测试目录位置

关键模块:
  - 入口文件
  - 核心业务模块
  - 公共工具模块
```

---

## 更新规则

### 何时更新知识库

```yaml
必须更新:
  - 新增模块
  - 模块职责变更
  - API 接口变更
  - 数据模型变更
  - 技术约定变更
  - 用户明确声明长期偏好 (如 "以后默认...")

无需更新:
  - Bug 修复 (不改变接口)
  - 内部实现优化
  - 代码格式调整
  - 用户一次性临时要求 (非长期偏好)
```

### 更新优先级

```yaml
1. tasks.md 中标记的文档任务
2. 代码变更涉及的模块文档
3. 整体架构描述 (如有架构变更)
```

---

## 冲突处理

**代码与文档冲突时：**
```yaml
原则: 代码是唯一真实来源
处理:
  1. 以代码实际行为为准
  2. 更新文档以匹配代码
  3. 标记更新时间
```

**任务与偏好冲突时：**
```yaml
优先级:
  1. 当前任务明确要求
  2. user/preferences.md 中的长期偏好
  3. 默认规则
```

---

## 输出格式

**初始化完成：**
```
[{BRAND_NAME}] 知识库初始化 ✓

创建: {N} 文件
策略: {full/progressive}

---
Changes: {N} files
  - .sopify-skills/project.md
  - .sopify-skills/wiki/overview.md
  - ...

Next: 知识库已就绪
```

**同步完成：**
```
[{BRAND_NAME}] 知识库同步 ✓

更新: {N} 文件

---
Changes: {N} files
  - .sopify-skills/wiki/modules/xxx.md
  - ...

Next: 文档已更新
```

---

## 快速决策树

```
需要获取项目上下文?
    │
    ├─ .sopify-skills/ 存在?
    │   ├─ 是 → 读取知识库文件
    │   └─ 否 → 扫描代码 + 询问是否初始化
    │
    └─ 信息足够?
        ├─ 是 → 返回上下文
        └─ 否 → 补充扫描代码
```
