# Changelog

All notable changes to Sopify (Sop AI) Skills are documented in this file.

This changelog is maintained manually (not auto-generated).

## [Unreleased]

### Added

- New sub-skill `model-compare` (CN/EN) for configuration-driven multi-model parallel comparison with manual user selection.
- New compare trigger contract:
  - Command: `~compare <question>`
  - Natural-language prefix: `对比分析：<question>`
- Multi-model MVP config block in `examples/sopify.config.yaml` with `candidates`, `timeout_sec`, and `max_parallel`.

### Changed

- Updated CN/EN AGENTS routing and command references to include `~compare` and `model-compare`.
- Updated `README.md` and `README_EN.md` with:
  - 7-skill install verification list
  - Multi-model MVP quick start
  - Environment-variable-only API key setup (`export ...`, including `~/.zshrc` persistence guidance)
- Added MVP fallback rule: when no usable multi-model config exists, `~compare` / `对比分析：` should not fail and must fallback to single-model with a clear notice.
- Clarified two-layer compare switches:
  - `multi_model.enabled` = feature-level gate
  - `multi_model.candidates[*].enabled` = per-candidate participation gate
- Added compare defaults and built-in entry rule:
  - `multi_model.include_default_model` defaults to `true` (session default model joins compare without extra config)
  - Parallel compare starts only when usable model count is at least 2 (fallback to single-model below that)
- Updated compare fallback output contract to include detailed fallback reasons.
- Added default-on context bridge for compare with a single bypass switch:
  - `multi_model.context_bridge` defaults to `true`
  - When external candidates are present, compare builds one shared context pack (`extract -> redact -> truncate`) before fan-out
  - `context_bridge=false` keeps a question-only emergency bypass path
- Added execution-level context-pack contract for compare:
  - Fixed extraction/redaction/truncation budgets
  - Unified request payload (`question + context_pack`) across candidates
  - Empty-pack safeguard (`context_pack empty` -> single-model fallback)
- Wired `~compare` entry to runtime module `scripts/model_compare_runtime.py` (`run_model_compare_runtime`) and converged compare docs to this runtime as SSOT.
- Unified fallback wording across CN/EN using normalized reason-code format (e.g., `MISSING_API_KEY`, `INSUFFICIENT_USABLE_MODELS`) and reduced duplicated execution-detail text in docs.

## [2026-02-13] - 2026-02-13

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
