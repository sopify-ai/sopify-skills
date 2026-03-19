---
name: develop
description: 开发实施阶段入口；聚合任务执行、状态更新、知识库同步与收尾迁移规则，按需加载 references/assets/scripts。
---

# Develop（入口文档）

## 何时激活

- 进入开发实施阶段（`workflow` / `light_iterate` / `quick_fix` / `exec_plan`）。
- 需要执行任务清单、更新状态并收敛交付结果。

## 执行骨架

1. 读取活动方案任务（`tasks.md` 或 light 的 `plan.md`）。
2. 提取待执行任务并按编号顺序执行。
3. 每完成一步更新任务状态（`[ ] -> [x] / [-] / [!]`）。
4. 同步知识库与偏好/反馈（保守写入）。
5. 方案完成后迁移到 `history/` 并更新索引。
6. 按结果输出成功/部分成功/快速修复摘要。

## 资源导航

- 长规则：`references/develop-rules.md`
- 输出模板：`assets/*.md`
- 任务提取脚本：`scripts/extract_pending_tasks.py`

## 确定性逻辑（脚本优先）

当需要可审计地提取任务状态时，优先调用：

```bash
python3 Codex/Skills/CN/skills/sopify/develop/scripts/extract_pending_tasks.py \
  --tasks-file .sopify-skills/plan/<plan>/tasks.md
```

脚本输出 JSON，包含：待执行任务、状态统计与执行顺序。

## 边界

- 本技能负责执行与收尾，不负责重新定义方案结构（交给 `design`）。
- 回滚属于显式用户动作，必须保留可追溯记录。
