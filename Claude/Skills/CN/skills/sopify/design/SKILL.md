---
name: design
description: 方案设计阶段入口；聚合方案分级、任务拆分与方案包输出规则，按需加载 references/assets/scripts。
---

# Design（入口文档）

## 何时激活

- 进入方案设计阶段（`workflow` / `plan_only` / `light_iterate`）。
- 需要把需求转换为可执行方案包与任务清单。

## 执行骨架

1. 加载 `references/design-rules.md`。
2. 基于变更信号判定 `light/standard/full`。
3. 按级别选取 `assets/` 中对应模板生成方案文件。
4. 产出任务清单并做粒度检查（每项可验证、依赖明确）。
5. 输出方案摘要，格式参考 `assets/output-summary.md`。

## 资源导航

- 长规则：`references/design-rules.md`
- 模板：`assets/*.md`
- 确定性分级脚本：`scripts/select_plan_level.py`

## 确定性逻辑（脚本优先）

当 `plan.level=auto` 时，优先调用：

```bash
python3 Codex/Skills/CN/skills/sopify/design/scripts/select_plan_level.py \
  --file-count 6 \
  --new-feature \
  --cross-module
```

脚本输出 JSON，包含：建议级别与触发原因。

## 边界

- 不直接执行代码任务（交给 `develop`）。
- 不替代 runtime 的路由决策，仅提供方案结构与任务拆分契约。
