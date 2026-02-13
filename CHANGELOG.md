# Changelog

All notable changes to Sopify (Sop AI) Skills are documented in this file.

This changelog is maintained manually (not auto-generated).

## [Unreleased]

### Added

- Sync scripts for keeping Codex/Claude skill bundles aligned:
  - `scripts/sync-skills.sh`
  - `scripts/check-skills-sync.sh`
- Sync/check usage guidance in `README.md`, `README_EN.md`, and `CONTRIBUTING.md`.
- Lightweight title color behavior clarification:
  - `title_color` applies to the title line only
  - Fallback to plain text when color is unsupported
- User preference layer in KB rules and templates:
  - `.sopify-skills/user/preferences.md`
  - `.sopify-skills/user/feedback.jsonl`
- Conservative learning rules (only persist explicit long-term preferences).

### Changed

- Corrected Claude Code CN install command in `README.md`.
- Clarified source-of-truth workflow: edit `Codex/Skills/{CN,EN}` then sync to `Claude/Skills/{CN,EN}`.

## [2026-01-15.1] - 2026-01-15

### Added

- Initial version (ruleset and skill structure).
