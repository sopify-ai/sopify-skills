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
