# workflow-learning Changelog (CN)

## [Unreleased]

### Added

- 初始版本：`workflow-learning` 子技能。
- 支持 `capture / replay / breakdown` 三种模式。
- 定义本地记录目录：
  - `.sopify-skills/replay/sessions/{session_id}/session.md`
  - `.sopify-skills/replay/sessions/{session_id}/events.jsonl`
  - `.sopify-skills/replay/sessions/{session_id}/breakdown.md`
- 增加“回放最近一次 / 按 session_id 回放”的调用约定。
- 增加敏感信息脱敏与边界规则。

### Changed

- 新增 `workflow.learning.auto_capture` 策略说明：`always | by_requirement | manual | off`。
- 明确策略边界：意图识别始终开启，`auto_capture` 仅控制主动记录。
- 明确 `by_requirement` 粒度：`simple=off`、`medium=summary`、`complex=full`。
