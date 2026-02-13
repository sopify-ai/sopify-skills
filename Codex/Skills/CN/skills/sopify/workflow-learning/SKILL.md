---
name: workflow-learning
description: 工作流学习子技能；用于完整记录任务执行链路并支持回放/复盘/为什么这么做的逐步讲解。用户提出回放、复盘、解释决策依据或学习实现思路时使用。
---

# Workflow Learning - 复盘学习与讲解

## 目标

- 记录任务实现的关键链路（输入、操作、结果、决策依据）。
- 支持“回放最近一次”或“按 session_id 回放”。
- 生成可教学的逐步讲解，帮助用户学习实现思路。

---

## 触发条件

当用户表达以下意图时调用本技能：

- 回放：`回放`、`回看`、`重放`、`看过程`
- 复盘：`复盘`、`总结这次实现`
- 原因解释：`为什么这么做`、`这步怎么想的`、`为什么选这个方案`

默认在“需求已实现完成后”使用；如用户中途要求，也可对当前已发生步骤进行部分回放。

---

## 执行模式

### Mode A: capture（记录）

在本地创建/更新会话记录目录：

```
.sopify-skills/replay/
└── sessions/
    └── {session_id}/
        ├── session.md
        ├── events.jsonl
        └── breakdown.md
```

`session_id` 建议格式：`YYYYMMDD_HHMMSS_{topic}`（topic 使用短英文短语）。

`events.jsonl` 每条事件字段建议：

```json
{
  "ts": "2026-02-13T16:30:00Z",
  "phase": "analysis|design|develop|qa",
  "intent": "本步目标",
  "action": "命令/工具/编辑动作",
  "key_output": "关键结果摘要",
  "decision_reason": "选择该动作的依据",
  "alternatives": ["备选方案A", "备选方案B"],
  "result": "success|warning|failed",
  "risk": "主要风险或空字符串",
  "artifacts": ["path/to/file"]
}
```

### Mode B: replay（回放）

输出结构：

1. 任务目标与范围
2. 关键步骤时间线
3. 关键决策点（做了什么、为什么、结果如何）
4. 最终交付与验证状态

### Mode C: breakdown（逐步讲解）

按步骤解释：

1. 这一步要解决什么问题
2. 为什么选当前方案
3. 有哪些替代方案
4. 风险与边界
5. 对下一步的影响

---

## 安全与边界

- 仅记录可观察执行链路，不输出不可见内部思维链原文。
- 写入日志前对敏感内容脱敏（token、api key、cookie、密码、私密连接串）。
- 不记录与任务无关的个人隐私信息。

---

## 常用调用示例

- `回放最近一次实现`
- `按 session_id 回放 20260213_163000_auth-refactor`
- `复盘这次实现，重点讲为什么这么做`
- `把这次需求实现过程逐步讲给我`

---

## 输出约定（简版）

```
[${BRAND_NAME}] 咨询问答 ✓

已生成回放记录: .sopify-skills/replay/sessions/{session_id}/session.md
已生成事件流水: .sopify-skills/replay/sessions/{session_id}/events.jsonl
已生成逐步讲解: .sopify-skills/replay/sessions/{session_id}/breakdown.md

---
Changes: 3 files
Next: 输入“回放最近一次”或“按 session_id 回放 ...”
```

---

## 变更记录

本子技能使用独立 changelog：

- `CHANGELOG.md`（与仓库根 `CHANGELOG.md` 分离维护）
