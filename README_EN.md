# Sopify (Sop AI) Skills

<div align="center">

**Standard Sop AI Skills - Config-driven Codex/Claude skills with complexity-based workflow routing**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Docs](https://img.shields.io/badge/docs-CC%20BY%204.0-green.svg)](./LICENSE-docs)
[![Version](https://img.shields.io/badge/version-2026--03--23.143454-orange.svg)](#version-history)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

[English](./README_EN.md) · [简体中文](./README.md) · [Quick Start](#quick-start) · [Configuration](#configuration)

</div>

---

## Why Sopify (Sop AI) Skills?

**The Problem:** Traditional AI programming assistants use the same heavyweight process for all tasks - even a simple typo fix requires full requirements analysis and solution design, resulting in low efficiency and verbose output.

**The Solution:** Sopify (Sop AI) Skills introduces **adaptive workflow**, automatically selecting the optimal path based on task complexity:

| Task Type | Traditional Approach | Sopify (Sop AI) Skills |
|-----------|---------------------|--------------|
| Simple change (≤2 files) | Full 3-phase workflow | Direct execution, skip planning |
| Medium task (3-5 files) | Full 3-phase workflow | Light plan (single file) + execution |
| Complex task (>5 files) | Full 3-phase workflow | Full 3-phase workflow |

### Key Features

- **Install Once, Bootstrap Runtime On Demand** - after the host payload is installed, entering any project and triggering Sopify bootstraps or updates `.sopify-runtime/` automatically
- **Manifest-First Machine Contract** - hosts are expected to read `.sopify-runtime/manifest.json` and `.sopify-skills/state/current_handoff.json` before guessing what to do next
- **Planning-Mode Auto Loop** - `go_plan_runtime.py` is now a planning-mode orchestrator that auto-consumes clarification and decision checkpoints, then stops cleanly at `review_or_execute_plan` or `confirm_execute`
- **Unified Checkpoint Contract** - handoff now prefers a standardized `checkpoint_request` artifact; the develop-first callback path is now live, so hosts must re-enter runtime before asking users to resolve a branch during `continue_host_develop`
- **No Per-Project Extra Dependencies** - the current runtime remains `stdlib_only`, so each workspace does not need its own extra Python packages
- **Adaptive Workflow and Tiered Plans** - simple tasks execute directly, medium tasks use a light plan, and complex work gets the full planning flow
- **Workflow Learning and Cross-Platform Support** - replay/retrospective is built in, with support for both Claude Code and Codex CLI

---

## Quick Start

### Prerequisites

- CLI environment (Claude Code or Codex CLI)
- File system access

### Installation

**One-command setup (recommended):**

```bash
# Install the host prompt layer and global payload only
bash scripts/install-sopify.sh --target codex:zh-CN

# Optionally prewarm a specific workspace
bash scripts/install-sopify.sh --target claude:en-US --workspace /path/to/project
```

Supported `target` values:

- `codex:zh-CN`
- `codex:en-US`
- `claude:zh-CN`
- `claude:en-US`

Notes:

- The installer sets up the selected host prompt layer and installs a host-local Sopify payload
- When `--workspace` is provided, the installer also prewarms `.sopify-runtime/` in that workspace
- When `--workspace` is omitted, Sopify bootstraps `.sopify-runtime/` on demand the first time it is triggered inside a project workspace
- This is the recommended entry point for end users

### Verify Installation

Restart your terminal and type:
```
Show skills list
```

**Expected:** Agent lists 7 skills (analyze, design, develop, kb, templates, model-compare, workflow-learning)

### Vendored Runtime Bundle

If you need maintainer-level control over bundle sync, run:

```bash
# 1. Sync the runtime bundle from this repository
bash scripts/sync-runtime-assets.sh /path/to/project

# 2. Validate the raw-input entry in the target repository
python3 /path/to/project/.sopify-runtime/scripts/sopify_runtime.py --workspace-root /path/to/project "Refactor the database layer"

# 3. Optional: run the portable tests and smoke check
python3 -m unittest /path/to/project/.sopify-runtime/tests/test_runtime.py
bash /path/to/project/.sopify-runtime/scripts/check-runtime-smoke.sh
```

Notes:

- The selected host keeps a global payload under `~/.codex/sopify/` or `~/.claude/sopify/`
- The global payload uses a `payload-manifest.json + bundle/ + helpers/` layout
- When Sopify is triggered inside a project workspace, the host checks the global payload first and bootstraps `.sopify-runtime/` only when needed
- If the workspace `.sopify-runtime/` is missing manifest-required bridge capabilities or missing bridge / CLI runtime files, the host must treat it as incompatible and refresh it instead of skipping on version equality alone
- `.sopify-runtime/` keeps a self-contained `runtime/` + `scripts/` + `tests/` layout
- `.sopify-runtime/manifest.json` is the machine contract for the bundle; host integrations must read the manifest first and only fall back to fixed script paths if needed
- the default vendored entry is `.sopify-runtime/scripts/sopify_runtime.py`
- once Sopify is triggered, the host's first hop must switch to `.sopify-runtime/scripts/runtime_gate.py enter`; the actual helper path and contract version are published through `manifest.json -> limits.runtime_gate_entry / limits.runtime_gate_contract_version`
- the host may only claim "runtime entered" and continue into normal stages when the gate returns `status=ready`, `gate_passed=true`, `evidence.handoff_found=true`, and `evidence.strict_runtime_entry=true`
- `evidence.handoff_found` is fixed to mean `current_handoff.json` has been persisted successfully; the in-memory handoff returned by runtime may only be used as a normalization fallback, not as standalone pass evidence
- `.sopify-skills/state/current_gate_receipt.json` is visibility for smoke / debug / doctor only, not the machine truth of the main host loop; the primary machine truth remains `current_handoff.json`
- the vendored plan-only orchestrator is `.sopify-runtime/scripts/go_plan_runtime.py`
- after `answer_questions`, hosts may optionally use the internal helper `.sopify-runtime/scripts/clarification_bridge_runtime.py` to inspect or write the lightweight clarification form; it is not a new main entry
- the manifest exposes this helper through `limits.clarification_bridge_entry` and `limits.clarification_bridge_hosts`
- after `confirm_decision`, hosts may optionally use the internal helper `.sopify-runtime/scripts/decision_bridge_runtime.py` to inspect or write the bridge contract; it is not a new main entry
- the manifest exposes this helper through `limits.decision_bridge_entry` and `limits.decision_bridge_hosts`
- after `continue_host_develop`, if the host hits another user-facing branch during implementation, it must call the internal helper `.sopify-runtime/scripts/develop_checkpoint_runtime.py submit --payload-json ...` to emit a standardized develop checkpoint; it is not a new main entry
- the manifest exposes this helper and its resume contract through `limits.develop_checkpoint_entry / limits.develop_checkpoint_hosts / limits.develop_resume_context_required_fields / limits.develop_resume_after_actions`
- when `answer_questions / confirm_decision / confirm_execute` is active, handoff now also carries a standardized `checkpoint_request`
- builtin skill discovery is owned by `runtime/builtin_catalog.py`, so the bundle does not depend on shipping `Codex/Skills` or `Claude/Skills` directories
- non-terminal routes now write `.sopify-skills/state/current_handoff.json`, and `Next:` is rendered from the handoff contract first
- future `codex/claude` host bridges and the Cursor plugin are expected to reuse the same runtime gate core instead of copying ingress logic per host

### Long-Term Preference Preload

Before each Sopify invocation, the host should attempt to read the current workspace preference file using:

```text
<workspace_root>/<plan.directory>/user/preferences.md
```

Minimum contract:

- path resolution must follow the same config priority as runtime; the host must not hardcode `.sopify-skills/user/preferences.md`
- missing or unreadable `preferences.md` must not block the main flow; v1 uses `fail-open with visibility`
- when loading succeeds, the host should inject it into the LLM as durable collaboration rules for the current workspace
- the fixed priority is: current explicit task > `preferences.md` > default rules
- "current explicit task" means the temporary execution instruction the user states explicitly in the current task; when it conflicts with `preferences.md`, it takes precedence, when it does not conflict, both apply together, and it is not written back as a long-term preference by default
- this is a host-side preflight capability, not a new runtime stage, and it does not change the semantics of `RecoveredContext`

### Hard-Constraint Recheck (2026-03-19)

The following constraints were revalidated through an isolated smoke run:

- the install flow still uses a single installer command, without a second manual runtime-prep step
- the first project trigger still bootstraps `.sopify-runtime/` from the installed payload
- the default main entry remains `scripts/sopify_runtime.py` / `.sopify-runtime/scripts/sopify_runtime.py`

Verification command:

```bash
python3 scripts/check-install-payload-bundle-smoke.py \
  --output-json /tmp/sopify-install-payload-bundle-smoke.json
```

Verification record:

- [Closure Blueprint](./.sopify-skills/blueprint/skill-standards-refactor.md)

### First Use

```bash
# After the initial install, enter any project workspace and trigger Sopify directly.
# If `.sopify-runtime/` is missing, the host bootstraps it first and then continues.
# Under the documentation contract, the first real-project trigger should at least create `.sopify-skills/blueprint/README.md` as the project index.

# 1. Simple task → Direct execution
"Fix the typo on line 42 in src/utils.ts"

# 2. Medium task → Light plan + execution
"Add error handling to login, signup, and password reset"

# 3. Complex task → Full workflow
"~go Add user authentication with JWT"

# 4. Plan only, no execution
"~go plan Refactor the database layer"

# 5. Replay / retrospective for the latest implementation
"Replay the latest implementation and explain why this approach was chosen"

# 6. Multi-model parallel comparison (manual choice)
"~compare Compare options for this refactor"
"对比分析：Compare options for this refactor"
```

### Minimal Repo-Local Validation

This repository now provides a minimal runtime validation path:

```bash
# Default raw-input entry
python3 scripts/sopify_runtime.py "Refactor the database layer"

# Prompt-level runtime gate entry
python3 scripts/runtime_gate.py enter --workspace-root . --request "Refactor the database layer"

# Explicit command through the same generic entry
python3 scripts/sopify_runtime.py "~go plan Refactor the database layer"

# Explicitly close out the current metadata-managed plan
python3 scripts/sopify_runtime.py "~go finalize"

# Validate the plan-only orchestrator
python3 scripts/go_plan_runtime.py "Refactor the database layer"

# Validate against another workspace
python3 scripts/sopify_runtime.py --workspace-root /path/to/project "Refactor the database layer"

# Self-check the current runtime bundle
bash scripts/check-runtime-smoke.sh
```

Expected result:

- on the first real-project trigger, only the minimum long-lived KB skeleton is created:
  - `.sopify-skills/project.md`
  - `.sopify-skills/user/preferences.md`
  - `.sopify-skills/blueprint/README.md`
- on the first plan lifecycle, Sopify materializes on demand:
  - `.sopify-skills/blueprint/background.md`
  - `.sopify-skills/blueprint/design.md`
  - `.sopify-skills/blueprint/tasks.md`
  - `.sopify-skills/plan/YYYYMMDD_feature/`
- on the first explicit `~go finalize`, Sopify materializes on demand:
  - `.sopify-skills/history/index.md`
  - `.sopify-skills/history/YYYY-MM/...`
- update `.sopify-skills/state/`
- write `.sopify-skills/replay/` only when proactive capture applies
- print the unified Sopify summary instead of a raw structured object
- `runtime_gate.py` returns the structured gate contract and may emit `.sopify-skills/state/current_gate_receipt.json` for visibility

Current boundary:

- Current minimal published runtime slice: `runtime-backed ~go plan + develop-first checkpoint callback`
- closed repo-local runtime helpers:
  - `scripts/sopify_runtime.py`: default raw-input entry
  - `scripts/go_plan_runtime.py`: plan-only orchestrator
  - `scripts/clarification_bridge_runtime.py`: internal host bridge helper for `answer_questions`, with `inspect / submit / prompt`, without replacing the default entry
  - `scripts/decision_bridge_runtime.py`: internal host bridge helper for `confirm_decision`, with `inspect / submit / prompt`, without replacing the default entry
  - `scripts/develop_checkpoint_runtime.py`: internal callback helper for user-facing branches encountered during `continue_host_develop`, with `inspect / submit`, without replacing the default entry
- `scripts/sync-runtime-assets.sh` can now sync the runtime bundle into `.sopify-runtime/` in another repository
- bundle sync now generates `.sopify-runtime/manifest.json` to describe entries, supported routes, builtin catalog, and the future handoff file location
- the workspace bootstrap `READY` state now requires both:
  - the payload-declared required capabilities
  - the critical bridge / CLI files to be present locally (for example `runtime/cli_interactive.py`, `scripts/clarification_bridge_runtime.py`, and `scripts/decision_bridge_runtime.py`)
- runtime now writes `.sopify-skills/state/current_handoff.json` so the host can read the structured next action directly
- the runtime now creates the minimum `blueprint/README.md` on the first real-project trigger and populates the full `blueprint/` skeleton on the first plan lifecycle
- the runtime now supports an enhanced clarification slice: when planning still lacks the minimum factual anchors, it writes `.sopify-skills/state/current_clarification.json` and attaches `clarification_form / clarification_submission_state` to handoff so hosts can collect structured answers through `runtime/clarification_bridge.py + scripts/clarification_bridge_runtime.py`
- the runtime now supports an enhanced decision-checkpoint slice: beyond explicit design splits, it can also consume structured candidates from `RouteDecision.artifacts.decision_candidates`; when at least 2 valid candidates with meaningful tradeoffs are present, `runtime/decision_templates.py + runtime/decision_policy.py` builds the checkpoint, writes both handoff artifacts and `.sopify-skills/state/current_decision.json`, and waits for confirmation before materializing the formal plan
- handoff now also carries `checkpoint_request` as the standardized upstream contract for clarification / decision / execution-confirm
- when a runtime skill or develop callback exposes a structured tradeoff signal but fails to provide a usable `checkpoint_request`, runtime now emits reason code `checkpoint_request_missing_but_tradeoff_detected` and fail-closes the loop to avoid a fake “decision-ready” state
- the runtime now supports the first develop-first callback slice: the host still owns code changes, but any mid-develop user decision must first flow through `runtime/develop_checkpoint.py + scripts/develop_checkpoint_runtime.py`, then reuse the existing clarification / decision / resume chain
- when `~compare` returns at least 2 successful results, `current_handoff.json.artifacts.compare_decision_contract` now carries a shortlist facade so hosts can reuse a `DecisionCheckpoint`-style picker; it does not automatically become the main `current_decision.json` flow
- `go_plan_runtime.py` now auto-consumes planning clarification / decision checkpoints by default; when input or bridge recovery is unavailable, it exits fail-closed instead of pretending planning already completed; `--no-bridge-loop` preserves the single-pass debug path
- replay summaries now persist checkpoint creation, recommendation, final selection, and key constraints; raw `input / textarea` text is omitted by default
- the runtime now supports the first `~go finalize` slice: metadata-managed active plans can refresh blueprint managed sections, archive into `history/`, and clear active runtime state
- the `.sopify-runtime/` bundle already includes portable `tests/test_runtime.py` and `scripts/check-runtime-smoke.sh`
- `P1-A/P1-B` are now landed: the first runtime execution bootstraps the minimum KB skeleton, and explicit `~go finalize` closes out metadata-managed plans into `history/`
- legacy plans are not auto-migrated; first-version finalize only supports plans generated by the new runtime with metadata front matter
- the prompt-level runtime gate is now the stabilized Layer 1 contract; it forces hosts to consume the gate contract first, but it is still not the same thing as a hard host-level ingress
- `scripts/check-prompt-runtime-gate-smoke.py` validates the Layer 1 gate contract and fail-closed behavior; `scripts/check-runtime-smoke.sh` still validates bundle/runtime asset integrity only and does not prove first-hop host ordering
- host-level first-hop ingress proof plus doctor/smoke remains part of the later host-bridge layer, not this release slice
- not part of this release slice: having `~compare` automatically create/resume `current_decision.json` through the generic entry, a standalone `workflow-learning` runtime helper, and a runtime-owned develop orchestrator
- the current shape now fits self-use and secondary integration, but it is still not a full host-side installer flow

### Documentation Governance Contract

This section defines the outward-facing documentation contract; runtime automation will align to it incrementally.

Projects integrated with Sopify follow this default documentation model:

- `blueprint/README.md` is a pure index page and keeps only `status / maintenance / current goal / current focus / read next`
- `blueprint/` is the project-level long-lived blueprint and is tracked by default
- if extra long-lived topic docs exist at the `blueprint/` root, `blueprint/README.md` must list them explicitly
- `plan/` stores working plan packages and is local-only by default; only the plan bound by `current_plan.path + current_plan.files` is machine-active
- `history/` is the finalized archive and is local-only by default
- `state/` is runtime checkpoint / handoff state and is always ignored
- `replay/` is an optional capability and is not part of the baseline documentation contract
- the first Sopify trigger in a real project repository should at least land `.sopify-skills/blueprint/README.md`
- the first plan lifecycle should then populate `blueprint/background.md / design.md / tasks.md`
- the active plan is archived into `history/` only when explicit `~go finalize` runs the close-out transaction
- first-version finalize only supports metadata-managed plans; legacy plans are rejected instead of being auto-migrated
- the formal `active_plan` resolution is `current_plan.path + current_plan.files`
- `knowledge_sync` is the only formal sync contract; `blueprint_obligation` remains legacy-only for reject / projection behavior
- `blueprint/tasks.md` keeps only unfinished long-term items and explicit deferrals; completed items should not remain in this file

### KB Responsibility Matrix

| Path | Layer | Responsibility | Created When | Default Consumer | Git Default |
|-----|------|------|------|------|------|
| `.sopify-skills/blueprint/README.md` | L0 index | Project entry index and stage status | First real-project trigger | host, LLM, humans | tracked |
| `.sopify-skills/project.md` | L1 stable | Reusable technical conventions | First bootstrap | runtime, planning, humans | tracked |
| `.sopify-skills/blueprint/background.md` | L1 stable | Long-term goals, scope, non-goals | First plan lifecycle or `kb_init: full` | planning, humans | tracked |
| `.sopify-skills/blueprint/design.md` | L1 stable | Module, host, directory, and consumption contracts | First plan lifecycle or `kb_init: full` | planning, develop, humans | tracked |
| `.sopify-skills/blueprint/tasks.md` | L1 stable | Unfinished long-term items and explicit deferrals | First plan lifecycle or `kb_init: full` | finalize, humans | tracked |
| `.sopify-skills/plan/YYYYMMDD_feature/` | L2 active | Working plan package; only the plan bound by `current_plan` is machine-active | Every formal planning run | host, develop, execution gate | ignored |
| `.sopify-skills/history/index.md` | L3 archive | Archive lookup index only | First explicit `~go finalize` | humans | ignored |
| `.sopify-skills/history/YYYY-MM/...` | L3 archive | Finalized plan archive | Every explicit `~go finalize` | humans, audit | ignored |
| `.sopify-skills/state/*.json` | runtime | Handoff, checkpoint, and gate machine truth | During runtime execution | host, runtime | ignored |
| `.sopify-skills/replay/` | optional | Replay summaries and learning records | When proactive capture applies | humans | ignored |

First decision-checkpoint slice:

- it only applies on planning routes such as `~go plan`, `~go`, or equivalent planner-selected routes
- the current auto-trigger is isolated in `runtime/decision_policy.py`: the baseline still reacts to explicit architecture alternatives such as `还是`, `vs`, or `or`, while structured `RouteDecision.artifacts.decision_candidates` are preferred when they provide at least 2 valid candidates with significant tradeoffs; suppression flags such as `decision_suppress`, `decision_preference_locked`, `decision_single_obvious`, and `decision_information_only` are supported
- when triggered, the host must prefer `current_handoff.json.artifacts.decision_checkpoint / decision_submission_state`; `.sopify-skills/state/current_decision.json` remains the state fallback
- the first template revision lives in `runtime/decision_templates.py::strategy_pick`, and the runtime still prints a text fallback so the user can reply with `1/2` or `~decide choose <option_id>`
- handoff now also carries `decision_policy_id / decision_trigger_reason` so hosts and replay summaries can explain why the checkpoint exists
- handoff also prefers a standardized `checkpoint_request`; hosts that already support it must consume that first and only fall back to route-specific artifacts when needed
- in the current documented scope, hosts may call the internal helper `scripts/decision_bridge_runtime.py inspect` and then write the normalized submission through `submit` or `prompt --renderer interactive|text|auto`; the default resume entry remains `scripts/sopify_runtime.py`
- vendored bundles expose this helper and the host hints through `.sopify-runtime/manifest.json -> limits.decision_bridge_entry / limits.decision_bridge_hosts`
- the current primary interaction host is a CLI host (for example, Codex CLI or Claude Code); the documented decision flow currently only commits to the CLI terminal bridge
- `go_plan_runtime.py` now enters the decision bridge by default; if user input or bridge recovery is unavailable, it exits non-zero in fail-closed mode; only `--no-bridge-loop` keeps the single-pass debug semantics

First clarification-checkpoint slice:

- it only applies on planning routes such as `~go plan`, `~go`, or equivalent planner-selected routes
- the current auto-trigger remains deterministic: it fires only when the request still lacks minimum factual anchors such as target scope or expected outcome
- when triggered, the host must prefer `current_handoff.json.artifacts.clarification_form / clarification_submission_state`; `.sopify-skills/state/current_clarification.json` remains the state fallback
- handoff also prefers a standardized `checkpoint_request`; hosts that already support it must consume that first and only fall back to clarification-specific artifacts when needed
- in the current documented scope, hosts may call `scripts/clarification_bridge_runtime.py inspect` and then write the normalized response through `submit` or `prompt --renderer interactive|text|auto`; the default resume entry remains `scripts/sopify_runtime.py`
- vendored bundles expose this helper and the host hints through `.sopify-runtime/manifest.json -> limits.clarification_bridge_entry / limits.clarification_bridge_hosts`
- the current clarification flow also assumes a CLI host bridge; editor-side or graphical form surfaces are not part of the current scope
- `go_plan_runtime.py` now enters the clarification bridge by default; if user input or bridge recovery is unavailable, it exits non-zero in fail-closed mode; only `--no-bridge-loop` keeps the single-pass debug semantics

First develop-first callback slice:

- it only applies after `current_handoff.json.required_host_action == continue_host_develop`
- the host still owns real code changes, tests, and verification; runtime does not take over the develop executor
- when implementation hits another user-facing branch, the host must not ask free-form questions or hand-write `current_decision.json / current_handoff.json`
- in the current documented scope, the host must call `scripts/develop_checkpoint_runtime.py inspect` first and then submit a structured payload through `submit --payload-json <json>`; the vendored equivalent is `.sopify-runtime/scripts/develop_checkpoint_runtime.py`
- the payload must include `checkpoint_kind` plus `resume_context`; the current minimum `resume_context` contract requires `active_run_stage / current_plan_path / task_refs / changed_files / working_summary / verification_todo`
- the helper normalizes the payload into a standard `checkpoint_request`, writes `.sopify-skills/state/current_decision.json` or `.sopify-skills/state/current_clarification.json`, and refreshes `.sopify-skills/state/current_handoff.json`
- handoff now also carries `checkpoint_request / resume_context / develop_resume_context`; the host must keep using the existing clarification / decision bridges to collect the user answer
- after the answer is confirmed, runtime returns either `continue_host_develop` or `review_or_execute_plan` based on `resume_context.resume_after`

First replay-summary slice:

- replay now records checkpoint creation, recommendation, recommendation reason, final selection, and key constraint summaries
- when `~compare` yields at least 2 successful results, replay also records shortlist size, the recommended compare result, and its recommendation basis
- raw free-form `input / textarea` content is summarized as provided guidance and omitted by default

---

## Configuration

### Configuration File

Config priority (recommended): project root (`./sopify.config.yaml`) > global (`~/.codex/sopify.config.yaml`, or `~/.claude/sopify.config.yaml` for Claude) > built-in defaults.

By default, Sopify (Sop AI) Skills will not write config files automatically. For first-time setup, copy the example config into your project root:

```bash
cp examples/sopify.config.yaml ./sopify.config.yaml
```

On Windows, copy `examples/sopify.config.yaml` into your project root and rename it to `sopify.config.yaml`.

Create (or use the copied) `sopify.config.yaml` in your project root:

```yaml
# Brand name: auto(derive {repo}-ai from project name) or custom
brand: auto

# Language: zh-CN / en-US
language: en-US

# Output style: minimal(clean) / classic(with emoji)
output_style: minimal

# Title color: green/blue/yellow/cyan/none
title_color: green

# Workflow configuration
workflow:
  mode: adaptive        # strict / adaptive / minimal
  require_score: 7      # Requirement score threshold
  auto_decide: false    # AI auto-decision
  learning:
    auto_capture: by_requirement  # always / by_requirement / manual / off

# Plan package configuration
plan:
  level: auto           # auto / light / standard / full
  directory: .sopify-skills    # Knowledge base directory

# Multi-model compare (MVP) configuration
multi_model:
  enabled: true
  trigger: manual       # trigger only for ~compare or "对比分析："
  timeout_sec: 25
  max_parallel: 3
  include_default_model: true  # optional; defaults to true even when omitted
  context_bridge: true  # optional; defaults to true (external models use context bridge; false = emergency bypass)
  candidates:
    - id: glm
      enabled: true
      provider: openai_compatible
      base_url: https://open.bigmodel.cn/api/paas/v4
      model: glm-4.7
      api_key_env: GLM_API_KEY
    - id: qwen
      enabled: true
      provider: openai_compatible
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
      model: qwen-plus
      api_key_env: DASHSCOPE_API_KEY
```

Note: `title_color` only applies lightweight styling to the output title line; if color is unsupported, output falls back to plain text automatically.
Note: `workflow.learning.auto_capture` controls proactive recording only; replay/review/why intent recognition is always enabled.
Note: `multi_model.enabled` is the feature-level gate, while `multi_model.candidates[*].enabled` is the per-candidate participation gate.
Note: `multi_model.include_default_model` defaults to `true` (the current session default model is included even if omitted).
Note: `multi_model.context_bridge` defaults to `true`; use `false` only as an emergency bypass (question-only input). Execution details are centralized in `scripts/model_compare_runtime.py`.
Note: parallel compare requires at least 2 usable models; below that, compare falls back to single-model with detailed reasons.
Note: fallback reasons should use normalized reason codes (for example `MISSING_API_KEY`, `INSUFFICIENT_USABLE_MODELS`).
Note: `multi_model.candidates[*].api_key_env` reads keys from environment variables only; avoid plaintext keys in config files.

### Workflow Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `strict` | Enforce 3-phase workflow | Formal projects requiring full documentation |
| `adaptive` | Auto-select based on complexity (default) | Daily development |
| `minimal` | Skip planning, execute directly | Quick prototypes, urgent fixes |

### workflow-learning Proactive Capture Policy

| Config Value | Behavior |
|------|----------|
| `always` | Proactively capture all development tasks (full) |
| `by_requirement` | Capture by complexity: simple=off, medium=summary, complex=full |
| `manual` | Capture only after explicit request such as "start recording this task" |
| `off` | Do not create new logs proactively; replay existing sessions remains available |

Note: intent recognition for replay/review/why-explanations remains available in all modes.

### Plan Package Levels

| Level | File Structure | Trigger |
|-------|---------------|---------|
| `light` | Single `plan.md` | 3-5 file changes |
| `standard` | `background.md` + `design.md` + `tasks.md` | >5 files or new features |
| `full` | Standard + `adr/` + `diagrams/` | Architectural changes |

---

## Command Reference

| Command | Description |
|---------|-------------|
| `~go` | Full workflow auto-execution |
| `~go plan` | Plan only, no execution; this repo provides `scripts/go_plan_runtime.py` as the plan-only helper |
| `~go exec` | Execute existing plan |
| `~go finalize` | Run the close-out transaction for the active metadata-managed plan: refresh blueprint index, archive to history, clear active state |
| `~compare` | Run parallel comparison across configured models; the runtime implementation lives in `scripts/model_compare_runtime.py`, but the generic entry does not auto-construct compare payloads |

Notes:

- The default repo-local runtime entry is `scripts/sopify_runtime.py`, which passes raw input to the router
- When vendored into another repository, the default entry becomes `.sopify-runtime/scripts/sopify_runtime.py`
- `scripts/go_plan_runtime.py` is reserved for the plan-only slice
- The vendored plan-only helper is `.sopify-runtime/scripts/go_plan_runtime.py`
- `~go finalize` has no dedicated helper and still goes through the default runtime entry; first version only supports metadata-managed plans and rejects legacy plans
- `~compare` still relies on a host-side dedicated bridge, rather than the generic entry

---

## Multi-Model Compare (MVP)

**Trigger conditions (only these two):**
- `~compare <question>`
- `对比分析：<question>`

**Environment variables (this is the only key method):**

```bash
# Effective for current shell session
export GLM_API_KEY="your_glm_key"
export DASHSCOPE_API_KEY="your_qwen_key"
```

```bash
# Persist in zsh (~/.zshrc)
echo 'export GLM_API_KEY="your_glm_key"' >> ~/.zshrc
echo 'export DASHSCOPE_API_KEY="your_qwen_key"' >> ~/.zshrc
source ~/.zshrc
```

**Behavior:**
- `multi_model.enabled` controls whether compare is enabled; `candidates[*].enabled` controls whether a candidate participates
- The current session default model is included by default (`include_default_model` defaults to true, no extra config needed)
- Context bridge is on by default (`context_bridge=true`): with external candidates, each model receives `question + context_pack`; with `false`, external models get question-only input
- `~compare` runtime implementation is converged in `scripts/model_compare_runtime.py` (entry calls `run_model_compare_runtime`)
- when at least 2 successful results are produced, handoff now includes `artifacts.compare_decision_contract`, a shortlist `DecisionCheckpoint` facade that hosts may render with the same decision-bridge UI; it does not automatically create `current_decision.json`
- Execution-level details (extract/redact/truncate chain, budgets, empty-pack guard) are centralized in `scripts/model_compare_runtime.py` and the `model-compare` sub-skill doc
- Parallel compare starts only when usable models reach 2 (built-in rule, no extra config needed)
- Fallback reasons should use normalized reason codes (for example `MISSING_API_KEY`, `INSUFFICIENT_USABLE_MODELS`) to keep CN/EN wording aligned
- If one model returns first, it is marked done while waiting for others until timeout/all done
- One-model failure does not block others; any successful result can proceed to manual choice
- If compare is not entered (feature disabled/missing keys/usable model count below 2), it does not error and falls back to single-model with detailed fallback reasons

**Context bridge example (short):**

```text
~compare Why does this bug only happen in prod?

context_pack:
- Key files: src/api/auth.ts:42, src/config/env.ts:10
- Runtime signal: X-Trace-Id missing only in prod
- Redaction: Authorization/Cookie replaced with <REDACTED>
- Truncation: keep only +/- 80 lines around matched functions
```

**Fallback reasons (real example):**

```text
[sopify-agent-ai] Q&A !

Compare mode not entered; executed in single-model mode.
Fallback reasons:
- MISSING_API_KEY: candidate_id=glm
- INSUFFICIENT_USABLE_MODELS: 1<2
Result: I am Sopify's AI coding assistant for analysis, design, and implementation tasks.

---
Changes: 0 files
Next: Adjust multi_model.enabled / candidates[*].enabled / include_default_model / context_bridge or provide missing env vars
```

---

## Sub-skills (Extensions)

`skills/sopify` contains both core skills and sub-skills. This root README stays minimal; see each sub-skill doc for detailed usage.

| Sub-skill | Purpose | Docs |
|-----------|---------|------|
| `model-compare` | Config-driven multi-model parallel compare with failure isolation and manual selection | [中文说明](./Codex/Skills/CN/skills/sopify/model-compare/SKILL.md) / [English Guide](./Codex/Skills/EN/skills/sopify/model-compare/SKILL.md) |
| `workflow-learning` | Full trace capture, replay, and step-by-step explanation | [中文说明](./Codex/Skills/CN/skills/sopify/workflow-learning/SKILL.md) / [English Guide](./Codex/Skills/EN/skills/sopify/workflow-learning/SKILL.md) |

Sub-skill change history is tracked separately from the repository-level changelog:

- [workflow-learning Changelog (CN)](./Codex/Skills/CN/skills/sopify/workflow-learning/CHANGELOG.md)
- [workflow-learning Changelog (EN)](./Codex/Skills/EN/skills/sopify/workflow-learning/CHANGELOG.md)

## Skill Authoring (Layered Standard)

Starting from `2026-03-19`, Sopify skills follow a layered package standard. In the current repo, `analyze/design/develop` have finished the prompt-layer pilot in Codex CN/EN, and Claude mirrors are produced by sync.

Current repo layout (logical package):

```text
Codex/Skills/{CN,EN}/skills/sopify/<skill>/
├── SKILL.md        # entry doc (activation + skeleton + boundaries)
├── references/     # long-form rules
├── assets/         # templates and examples
└── scripts/        # deterministic logic

runtime/builtin_skill_packages/<skill>/
└── skill.yaml      # builtin machine metadata (routes/permissions/host_support)
```

Contract requirements:

- `Codex/Skills/{CN,EN}` are the prompt-layer source of truth; `Claude/Skills/{CN,EN}` are mirrors only
- `runtime/builtin_skill_packages/*/skill.yaml` is the builtin machine-metadata source of truth
- Use `supports_routes` for declarative route binding first
- Validate `skill.yaml` through `runtime/skill_schema.py`
- Fail closed only on invalid `skill.yaml` schema / unsupported `host_support` / invalid runtime `permission_mode`
- `tools / disallowed_tools / allowed_paths / requires_network` are declared today, but are not yet runtime-enforced
- Treat builtin catalog as generated from `runtime/builtin_skill_packages/*/skill.yaml`, not manually edited

Maintainer minimum checks:

```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
python3 scripts/generate-builtin-catalog.py
python3 scripts/check-skill-eval-gate.py
python3 -m unittest tests.test_runtime -v
```

See full specs:

- [Closure Blueprint](./.sopify-skills/blueprint/skill-standards-refactor.md)
- [Skill Eval Baseline](./evals/skill_eval_baseline.json)
- [Skill Eval SLO](./evals/skill_eval_slo.json)

### First-Principles Pilot Artifacts (2026-03)

The active plan now carries the minimum evaluation artifacts for the first promotion-gate pilot:

- [Sample Matrix](./.sopify-skills/plan/20260321_go-plan/pilot_sample_matrix.md)
- [Trigger Matrix](./.sopify-skills/plan/20260321_go-plan/trigger_matrix.md)
- [Human Review Rubric](./.sopify-skills/plan/20260321_go-plan/pilot_review_rubric.md)

Layering matrix:

- `preferences.md`: workspace-local collaboration-style pilot, including first-principles correction and the local "two-phase collaboration" preference.
- `analyze`: only the 4 stable subset rules move down here: goal/path separation, clarify fuzzy goals first, suggest a lower-cost alternative when the path is suboptimal, and close success criteria in SMART form.
- `consult/runtime`: still phase-2 output-layer scope; "two-phase output for all Q&A" has not moved into the default runtime / consult contract.

The completion scope for `v1 implementation complete` is now fixed as: workspace pilot + `analyze` subset + docs/tests closure. `Batch 2/3` remain post-v1 optimization and do not block this round.

The promotion-gate thresholds `80% / 10% / 20% / <=1` are frozen only as the current `round-1 pilot target`. They should be reconsidered as a final promotion threshold only after the full `45`-sample run across `3` environment classes is complete.

---

## Sync Mechanism (for maintainers)

To avoid drift between Codex/Claude and CN/EN skill files, use the built-in sync/check scripts:

```bash
# 1) Sync Codex prompt-layer source files to Claude mirror files
bash scripts/sync-skills.sh

# 2) Verify all four bundles are aligned
bash scripts/check-skills-sync.sh

# 3) Verify version consistency (README badge / SOPIFY_VERSION / CHANGELOG)
bash scripts/check-version-consistency.sh
```

These scripts ignore Finder/Explorer noise files (`.DS_Store`, `Thumbs.db`) to avoid false drift reports.
Before committing skill/rule updates, always run `sync -> check-skills-sync -> check-version-consistency`.
CI (`.github/workflows/ci.yml`) runs the same gate on PR/Push, and uses `git diff --exit-code` to fail drift that requires sync.
If you also changed `runtime/builtin_skill_packages/*/skill.yaml`, rerun catalog / eval / runtime tests as part of the same check path.

---

## Output Format

Sopify (Sop AI) Skills uses a concise output format:

```
[my-app-ai] Solution Design ✓

Plan: .sopify-skills/plan/20260115_user_auth/
Summary: JWT auth + Redis session management
Tasks: 5 items

---
Changes: 3 files
  - .sopify-skills/plan/20260115_user_auth/background.md
  - .sopify-skills/plan/20260115_user_auth/design.md
  - .sopify-skills/plan/20260115_user_auth/tasks.md

Next: ~go exec to execute or reply with feedback
```

**Status Symbols:**
- `✓` Success
- `?` Awaiting input
- `!` Warning
- `×` Error

**Phase Naming:**
- `Command Complete`: for command-prefixed flows (`~go/~go plan/~go exec/~compare`)
- `Q&A`: for non-command questions/clarifications

---

## Directory Structure

```
.sopify-skills/                        # Knowledge base root
├── blueprint/                 # Project-level long-lived blueprint, tracked by default
│   ├── README.md              # Pure index page with status/maintenance/current-goal/current-focus/read-next only
│   ├── background.md          # Long-term goals, scope, non-goals
│   ├── design.md              # Module / host / directory / consumption contracts
│   └── tasks.md               # Unfinished long-term items and explicit deferrals
├── project.md                 # Project technical conventions (not a duplicate of background/design)
├── user/
│   ├── preferences.md         # Long-term user preferences
│   └── feedback.jsonl         # Raw feedback events
├── plan/                      # Current active plans, ignored by default
│   └── YYYYMMDD_feature/
│       ├── background.md      # Requirement background (formerly why.md)
│       ├── design.md          # Technical design (formerly how.md)
│       └── tasks.md           # Task list (formerly task.md)
├── history/                   # Finalized archives, ignored by default
│   ├── index.md
│   └── YYYY-MM/
├── state/                     # Runtime state, always ignored
└── replay/                    # Optional replay capability, ignored by default
```

Default Git strategy:

- `blueprint/` is tracked by default
- `plan/` and `history/` stay local by default
- `state/` and `replay/` stay ignored by default
- projects may still customize `.gitignore`, but the layered default above is the recommended baseline

---

## Comparison with HelloAGENTS

| Feature | HelloAGENTS | Sopify (Sop AI) Skills |
|---------|-------------|--------------|
| Brand name | Fixed "HelloAGENTS" | Derived "{repo}-ai" from project name |
| Output style | Many emojis | Clean text |
| Workflow | Fixed 3-phase | Adaptive |
| Plan package | Fixed 3 files | Tiered (light/standard/full) |
| File naming | why.md/how.md/task.md | background.md/design.md/tasks.md |
| Configuration | Scattered in rules | Unified sopify.config.yaml |
| Rule complexity | G1-G12 (12 rules) | Core/Auto/Advanced layered |

---

## File Structure

```
sopify-skills/
├── Claude/
│   └── Skills/
│       ├── CN/                 # Chinese version
│       │   ├── CLAUDE.md       # Main config file
│       │   └── skills/sopify/  # Core skills + sub-skills
│       └── EN/                 # English version
├── Codex/
│   └── Skills/                 # Codex CLI version
├── runtime/
│   ├── builtin_skill_packages/ # builtin skill machine metadata source
│   └── builtin_catalog.generated.json
├── examples/
│   └── sopify.config.yaml      # Config example
├── README.md                   # Chinese docs
└── README_EN.md                # English docs
```

---

## FAQ

### Q: How to switch language?

Modify the `language` field in `sopify.config.yaml`:
```yaml
language: zh-CN  # or en-US
```

### Q: How to disable adaptive mode?

Set workflow mode to strict:
```yaml
workflow:
  mode: strict
```

### Q: Where are plan packages stored?

Default location is `.sopify-skills/` in your project root. Configurable via:
```yaml
plan:
  directory: .my-custom-dir
```

Note: Changing `plan.directory` only affects newly generated knowledge base/plan files. Existing history in the old directory will not be migrated automatically; move it manually if needed, or keep the value unchanged.

### Q: How to skip requirement scoring follow-ups?

Set `auto_decide: true`:
```yaml
workflow:
  auto_decide: true
```

### Q: How do I reset learned user preferences?

Delete (or clear) `.sopify-skills/user/preferences.md` to reset long-term preferences. Keep `feedback.jsonl` only if you want audit history.

### Q: When should I run sync scripts?

After editing prompt-layer files under `Codex/Skills/{CN,EN}` or machine metadata under `runtime/builtin_skill_packages/*/skill.yaml`, the safe minimum is:
```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
python3 scripts/generate-builtin-catalog.py
python3 scripts/check-skill-eval-gate.py
python3 -m unittest tests.test_runtime -v
```
If any check fails, fix the mismatch before committing.

---

## Version History

- Detailed release notes are maintained manually in `CHANGELOG.md`.

---

## License

This repository is intended to use a dual-licensing approach (see license files for details):

- Code and configs (including example configs): Apache 2.0 (see `LICENSE`)
- Documentation (mostly Markdown): CC BY 4.0 (see `LICENSE-docs`)

If you think any attribution or licensing details should be clarified (for example, if some parts were adapted from other open-source repositories), please open an issue or include details in your PR.

---

## Contributing

Issues and PRs welcome!
