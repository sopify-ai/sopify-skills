# Changelog

All notable changes to Sopify (Sop AI) Skills are documented in this file.

This changelog is maintained manually (not auto-generated).

## [Unreleased]

## [2026-03-20.183348] - 2026-03-20

### Added

- New prompt-level runtime gate assets:
  - `runtime/gate.py`
  - `runtime/workspace_preflight.py`
  - `scripts/runtime_gate.py`
  - `scripts/check-prompt-runtime-gate-smoke.py`

### Changed

- Host prompt contracts for Codex and Claude now require `runtime_gate.py enter` as the first Sopify hop, with `allowed_response_mode` driving fail-closed follow-up behavior.
- Bundle manifest / installer / sync validation now declare and verify the `runtime_gate` capability and the `limits.runtime_gate_*` contract.
- README docs now treat prompt-level runtime gate as Layer 1, define `current_handoff.json` as the primary machine truth, and limit `current_gate_receipt.json` to visibility-only usage.

### Tests

- Added `tests/test_runtime_gate.py` coverage for normal follow-up, checkpoint-only flows, and fail-closed behavior.
- Expanded bundle/install integration coverage to assert `runtime_gate` files, manifest fields, and vendored runtime-gate execution.

## [2026-03-20.141842] - 2026-03-20

### Added

- New `~summary` runtime route with deterministic daily recap artifacts:
  - `runtime/daily_summary.py`
  - `.sopify-skills/replay/daily/YYYY-MM/YYYY-MM-DD/summary.json`
  - `.sopify-skills/replay/daily/YYYY-MM/YYYY-MM-DD/summary.md`
- New workspace-scoped long-term preference preload helper:
  - `runtime/preferences.py`
  - `scripts/preferences_preload_runtime.py`
- New project bootstrap artifacts for long-term collaboration state:
  - `.sopify-skills/project.md`
  - `.sopify-skills/wiki/overview.md`
  - `.sopify-skills/user/preferences.md`

### Changed

- Runtime output now appends a local wall-clock timestamp to user-visible stage summaries.
- Replay events now include structured skill-activation metadata for summary and timeline reuse.
- Bundle manifest / payload / bootstrap contracts now declare and validate the `preferences_preload` capability.
- Codex / Claude host prompt assets now document `preferences-preload-v1`, including:
  - `workspace_root + plan.directory + user/preferences.md` path resolution
  - `fail-open with visibility`
  - fixed priority `current explicit task > preferences.md > default rules`
- `~summary` now:
  - includes uncommitted changes by default
  - preserves the active handoff / current run / last route
  - rebuilds invalid existing `summary.json` in place instead of failing
  - keeps state evidence refs stable when `plan.directory` is customized
  - renders fully localized English output instead of mixing Chinese templates
- Blueprint and README docs now treat “current time display + ~summary detailed recap” as the active user-facing slice.

### Tests

- Expanded `tests/test_runtime.py` with `~summary` hardening coverage for:
  - repeated same-day revision increments
  - git-unavailable fallback
  - invalid existing summary rebuild
  - active-flow preservation
  - persisted artifact / terminal render consistency
  - English-only output templates
  - dynamic state evidence refs under custom `plan.directory`
- Expanded `tests/test_installer.py` to assert host prompt / bundle wiring for `preferences_preload`.

## [2026-03-19.183617] - 2026-03-19

### Scope

- Current minimal published runtime slice: `runtime-backed ~go plan`
- Not part of this slice:
  - generic-entry auto-bridge for `~compare`
  - runtime-owned develop orchestrator
  - standalone `workflow-learning` runtime helper

### Added

- Host-local Sopify payload layout under `~/.codex/sopify/` / `~/.claude/sopify/`, including:
  - `payload-manifest.json`
  - `bundle/`
  - `helpers/bootstrap_workspace.py`
- Minimal KB bootstrap in `runtime/kb.py`, creating `project.md`, `wiki/overview.md`, `user/preferences.md`, and `history/index.md` on first runtime execution.
- New bundle manifest contract in `runtime/manifest.py`, written to `.sopify-runtime/manifest.json` during bundle sync.
- New runtime handoff contract in `runtime/handoff.py`, written to `.sopify-skills/state/current_handoff.json` for non-terminal routes.
- New sub-skill `model-compare` (CN/EN) for configuration-driven multi-model parallel comparison with manual user selection.
- New compare trigger contract:
  - Command: `~compare <question>`
  - Natural-language prefix: `对比分析：<question>`
- Multi-model MVP config block in `examples/sopify.config.yaml` with `candidates`, `timeout_sec`, and `max_parallel`.
- New GitHub Actions workflow `.github/workflows/ci.yml` to gate PR/Push with sync and version checks.
- Default repo-local raw-input runtime entry `scripts/sopify_runtime.py` and plan-only helper `scripts/go_plan_runtime.py`.
- Runtime bundle sync script `scripts/sync-runtime-assets.sh` for vendoring `.sopify-runtime/` into another repository.
- One-command installer entry `scripts/install-sopify.sh` with a Python installer core and host adapters for `codex:zh-CN`, `codex:en-US`, `claude:zh-CN`, and `claude:en-US`.
- Runtime smoke check script `scripts/check-runtime-smoke.sh`.
- Runtime behavior test coverage in `tests/test_runtime.py`, including vendored bundle validation.
- Installer test coverage in `tests/test_installer.py` for Codex/Claude sample install paths.
- Develop-first checkpoint callback support:
  - `runtime/develop_checkpoint.py`
  - `scripts/develop_checkpoint_runtime.py`
  - vendored manifest capability + helper contract for `continue_host_develop`

### Changed

- Installer semantics now split into:
  - host prompt-layer install
  - host-local payload install
  - optional current-workspace prewarm through the same bootstrap helper used later by the host
- Tightened workspace bundle compatibility checks:
  - bootstrap no longer treats a same-version `.sopify-runtime/` as `READY` when required bridge capabilities are missing
  - bootstrap now also verifies critical bridge / CLI files before skipping refresh
  - installer bundle validation now uses the same bridge / CLI file expectations as workspace bootstrap
- Extended the checkpoint contract to carry `resume_context` for develop-stage callbacks, so confirmation can safely return to `continue_host_develop` or fail back to `review_or_execute_plan`.
- Extended runtime / bundle docs and host prompts to require `develop_checkpoint_runtime.py` whenever a mid-develop user decision must re-enter runtime.
- `--workspace` is now optional prewarm input instead of an implicit current-directory sync.
- Added workspace bootstrap contract:
  - when Sopify is triggered inside a project workspace and `.sopify-runtime/manifest.json` is missing or incompatible, the host should call the installed bootstrap helper first
  - after bootstrap succeeds, execution continues through the repo-local bundle manifest
- Added no-silent-downgrade behavior for workspace bundle bootstrap:
  - if a workspace bundle is newer than the installed global payload, bootstrap skips instead of overwriting it
- Updated bundle sync, installer validation, and smoke checks to treat `.sopify-runtime/manifest.json` as a required control-plane artifact.
- Updated runtime output to render `Next:` from the structured handoff contract before falling back to route-only copy.
- Refactored runtime builtin-skill discovery to a catalog-first model via `runtime/builtin_catalog.py`, so vendored bundles no longer depend on scanning `Codex/Skills` or `Claude/Skills` trees.
- Extended `SkillMeta` and external skill manifests with forward-compatible catalog fields: `entry_kind`, `handoff_kind`, `contract_version`, and `supports_routes`.
- Added explicit builtin override policy in `runtime/skill_registry.py`: external skills can only replace builtin ids when `override_builtin: true` is declared.
- Updated CN/EN AGENTS routing and command references to include `~compare` and `model-compare`.
- Updated `README.md` and `README_EN.md` with:
  - 7-skill install verification list
  - Multi-model MVP quick start
  - Environment-variable-only API key setup (`export ...`, including `~/.zshrc` persistence guidance)
  - Recommended one-command installer usage for host prompt setup + vendored bundle sync
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
- Updated sync scripts to ignore Finder/Explorer noise files (`.DS_Store`, `Thumbs.db`) to reduce false drift reports.
- Updated maintainer docs (`README.md`, `README_EN.md`, `CONTRIBUTING.md`) to document the full gate chain:
  - `sync-skills.sh`
  - `check-skills-sync.sh`
  - `check-version-consistency.sh`
- Clarified release boundary across README, blueprint, and changelog:
  - current minimal published slice = `runtime-backed ~go plan`
  - `~compare` generic-entry bridge / `~go exec` develop bridge / `workflow-learning` runtime helper remain out of scope for this slice
- Clarified the next-stage boundary across runtime/docs/tests:
  - P1-A now lands only the minimum KB bootstrap
  - selective history recovery / history archive / task-state runtime remain for later P1 slices

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
