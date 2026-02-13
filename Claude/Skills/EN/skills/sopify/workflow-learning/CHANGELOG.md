# workflow-learning Changelog (EN)

## [Unreleased]

### Added

- Initial release of the `workflow-learning` sub-skill.
- Support for three modes: `capture / replay / breakdown`.
- Local trace artifacts:
  - `.sopify-skills/replay/sessions/{session_id}/session.md`
  - `.sopify-skills/replay/sessions/{session_id}/events.jsonl`
  - `.sopify-skills/replay/sessions/{session_id}/breakdown.md`
- Usage contract for "replay latest" and "replay by session_id".
- Sensitive-data redaction and boundary rules.

### Changed

- Added `workflow.learning.auto_capture` policy docs: `always | by_requirement | manual | off`.
- Clarified boundary: intent recognition is always enabled; `auto_capture` controls proactive recording only.
- Clarified `by_requirement` granularity: `simple=off`, `medium=summary`, `complex=full`.
