---
name: analyze
description: 需求分析阶段入口；聚合评分、追问与范围判定规则，按需加载 references/assets/scripts。
---

# Analyze（入口文档）

## 何时激活

- 进入需求分析阶段（`workflow` / `plan_only`）。
- 需要做需求评分、追问或复杂度路由判定。

## 执行骨架

1. 先加载 `references/analyze-rules.md`。
2. 执行 Phase A（知识库检查、上下文获取、需求类型判定、完整性评分）。
3. 若评分不足，按 `auto_decide` 处理：
   - `false`：使用 `assets/question-output.md` 追问。
   - `true`：显式补充假设后继续。
4. 评分达标后执行 Phase B（目标提炼、代码分析与技术准备）。
5. 输出阶段摘要，格式参考 `assets/success-output.md`。

## 资源导航

- 长规则：`references/analyze-rules.md`
- 追问模板：`assets/question-output.md`
- 达标输出模板：`assets/success-output.md`
- 确定性评分脚本：`scripts/score_requirement.py`

## 确定性逻辑（脚本优先）

当需要可审计评分时，优先调用：

```bash
python3 Codex/Skills/CN/skills/sopify/analyze/scripts/score_requirement.py \
  --goal-clarity 2 \
  --expected-outcome 2 \
  --scope-boundary 1 \
  --constraints 1 \
  --require-score 7
```

脚本输出 JSON，包含：总分、阈值判定、缺失维度清单。

## 边界

- 不在本技能直接生成方案包（交给 `design`）。
- 不在本技能直接执行代码修改（交给 `develop` 或 runtime 路由）。
