# Design 详细规则

## 目标

设计技术方案，拆分可执行任务，生成可回放的方案包。

## 总流程

1. 判定方案包级别（`light/standard/full`）。
2. 生成方案文件骨架。
3. 拆分任务并标注验证标准。
4. 输出摘要并等待宿主后续动作。

## 步骤 1：方案包级别判定

自动判定规则（`plan.level=auto`）：

- `light`：文件数 3-5，且无架构级变更，修改范围明确。
- `standard`：文件数 >5，或新功能开发，或跨模块改动。
- `full`：架构级变更、重大重构、新系统设计。

## 步骤 2：生成方案文件

- `light`：生成 `plan.md`。
- `standard`：生成 `background.md + design.md + tasks.md`。
- `full`：在 standard 基础上补 `adr/` 与 `diagrams/`。

模板来源统一使用 `assets/` 目录：

1. `assets/plan-light-template.md`
2. `assets/background-template.md`
3. `assets/design-template.md`
4. `assets/tasks-template.md`
5. `assets/adr-template.md`

## 步骤 3：任务拆分

任务约束：

1. 每项建议 30 分钟内可完成。
2. 每项需具备可验证完成标准。
3. 依赖关系清晰，避免隐藏前置条件。

任务分类建议：

1. 核心功能实现
2. 辅助功能
3. 安全检查
4. 测试
5. 文档更新

任务状态符号：

- `[ ]` 待执行
- `[x]` 已完成
- `[-]` 已跳过
- `[!]` 阻塞中

## 阶段转换

- `workflow.mode=strict`：输出方案摘要后等待确认。
- `workflow.mode=adaptive`：
  - `~go` 触发：进入执行前确认或后续宿主链路。
  - `~go plan` 触发：只输出方案摘要并停止。
- 用户反馈修改意见：留在本阶段，更新文件后再次输出摘要。

## runtime helper 边界

当仓库存在 `scripts/sopify_runtime.py` 且输入为原始请求时：

1. 优先交给默认 runtime 入口，不手工强制改写为 `~go plan`。
2. 明确是 `~go plan` 路径时，优先调用 `scripts/go_plan_runtime.py`。
3. `go_plan_runtime.py` 仅用于 plan-only slice。
4. `~compare` 仍依赖宿主侧专用桥接。

入口缺失时，才按本技能模板手工生成方案文件。

## 命名规则

方案目录格式：`YYYYMMDD_feature_name`

示例：

- `20260115_user_auth`
- `20260115_fix_login_bug`
- `20260115_refactor_api`
