# Changelog

All notable changes to Sopify (Sop AI) Skills are documented in this file.

This changelog is maintained manually (not auto-generated).

## [Unreleased]

### Added

- Sync scripts for keeping Codex/Claude skill bundles aligned:
  - `scripts/sync-skills.sh`
  - `scripts/check-skills-sync.sh`
- New sub-skill `workflow-learning` (CN/EN) for full local trace capture, replay, and step-by-step explanation.
- Separate sub-skill changelog files for `workflow-learning`:
  - `Codex/Skills/CN/skills/sopify/workflow-learning/CHANGELOG.md`
  - `Codex/Skills/EN/skills/sopify/workflow-learning/CHANGELOG.md`
- Sync/check usage guidance in `README.md`, `README_EN.md`, and `CONTRIBUTING.md`.
- Lightweight title color behavior clarification:
  - `title_color` applies to the title line only
  - Fallback to plain text when color is unsupported
- User preference layer in KB rules and templates:
  - `.sopify-skills/user/preferences.md`
  - `.sopify-skills/user/feedback.jsonl`
- Conservative learning rules (only persist explicit long-term preferences).
- New workflow-learning proactive capture config:
  - `workflow.learning.auto_capture` with `always | by_requirement | manual | off`

### Changed

- Corrected Claude Code CN install command in `README.md`.
- Clarified source-of-truth workflow: edit `Codex/Skills/{CN,EN}` then sync to `Claude/Skills/{CN,EN}`.
- Clarified branding semantics: `brand: auto` derives brand as `{repo}-ai` from project name.
- Clarified workflow-learning behavior: replay/review/why intent recognition is always enabled; `auto_capture` only controls proactive recording.

## [2026-01-15.1] - 2026-01-15

### Added

- Initial version (ruleset and skill structure).
