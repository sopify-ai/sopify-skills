# Develop 详细规则

## 目标

按任务清单实施开发，维护任务状态，同步知识库并完成方案迁移。

## 总流程

1. 读取任务清单。
2. 执行任务并更新状态。
3. 同步知识库与偏好信息。
4. 迁移方案包到 `history/`。
5. 输出执行结果摘要。

## 步骤 1：读取任务清单

来源：

- `.sopify-skills/plan/{current_plan}/tasks.md`
- `.sopify-skills/plan/{current_plan}/plan.md`（light）

处理规则：

1. 提取 `[ ]` 待执行任务。
2. 按任务编号顺序执行。
3. 先检查显式依赖再执行。

## 步骤 2：执行任务

每个任务执行原则：

1. 定位目标文件。
2. 理解当前实现。
3. 实施修改。
4. 验证修改正确性。
5. 更新状态。

状态迁移：

- 成功：`[ ] -> [x]`
- 跳过：`[ ] -> [-]`
- 阻塞：`[ ] -> [!]`

安全底线：

- 不引入常见漏洞（XSS / SQL 注入等）。
- 不破坏既有功能。
- 保持项目代码风格一致。

## 步骤 3：知识库同步

同步时机：

1. 每完成一个模块任务后。
2. 阶段收尾时做统一复核。

同步目标：

- `wiki/modules/{module}.md`
- `wiki/overview.md`
- `project.md`
- `user/preferences.md`（仅长期偏好）
- `user/feedback.jsonl`

偏好写入（保守策略）：

允许写入：

- 用户明确表达长期偏好（如“以后默认...”）。

禁止写入：

- 一次性指令。
- 上下文不完整的猜测。
- 与任务无关的泛化结论。

## 步骤 4：方案迁移

迁移路径：

```text
.sopify-skills/plan/YYYYMMDD_feature/
  -> .sopify-skills/history/YYYY-MM/YYYYMMDD_feature/
```

索引更新：在 `.sopify-skills/history/index.md` 新增一行记录。

## 输出模板

按结果类型选择 `assets/`：

1. `assets/output-success.md`
2. `assets/output-partial.md`
3. `assets/output-quick-fix.md`

## 特殊情况

执行中断：

1. 已完成任务标记 `[x]`。
2. 当前任务保持 `[ ]`。
3. 输出中断摘要，等待宿主恢复。

任务失败：

1. 标记 `[!]` 并注明原因。
2. 尝试继续可独立任务。

回滚请求：

1. 使用 git 回滚（仅在用户明确要求时）。
2. 保留方案包在 `plan/`，不迁移。
3. 输出回滚确认。
