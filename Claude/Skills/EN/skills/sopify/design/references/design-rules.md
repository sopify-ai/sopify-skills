# Design Detailed Rules

## Goal

Design the technical solution, break work into executable tasks, and generate a replayable plan package.

## Overall flow

1. Decide the plan level (`light/standard/full`).
2. Generate the plan file scaffold.
3. Break down tasks and mark verification criteria.
4. Render the summary and wait for the next host action.

## Step 1: Decide the plan level

Auto-detection rules (`plan.level=auto`):

- `light`: 3-5 files, no architectural change, scope is explicit.
- `standard`: more than 5 files, or a new feature, or a cross-module change.
- `full`: architectural change, major refactor, or new system design.

## Step 2: Generate plan files

- `light`: generate `plan.md`.
- `standard`: generate `background.md + design.md + tasks.md`.
- `full`: extend standard with `adr/` and `diagrams/`.

Template sources live in `assets/`:

1. `assets/plan-light-template.md`
2. `assets/background-template.md`
3. `assets/design-template.md`
4. `assets/tasks-template.md`
5. `assets/adr-template.md`

## Step 3: Break down tasks

Task constraints:

1. Each task should fit within about 30 minutes.
2. Each task must have a verifiable completion criterion.
3. Dependencies must be explicit.

Suggested categories:

1. Core feature work
2. Supporting work
3. Security checks
4. Testing
5. Documentation updates

Task markers:

- `[ ]` pending
- `[x]` completed
- `[-]` skipped
- `[!]` blocked

## Phase transitions

- `workflow.mode=strict`: render the summary and wait for confirmation.
- `workflow.mode=adaptive`:
  - `~go`: continue into execution confirmation or the downstream host flow.
  - `~go plan`: stop after rendering the plan summary.
- If the user gives plan feedback, stay in this phase, update the files, and render again.

## Runtime helper boundaries

When the repo contains `scripts/sopify_runtime.py` and the input is the raw request:

1. Prefer the default runtime entry; do not rewrite it manually into `~go plan`.
2. When the intent is explicitly `~go plan`, prefer `scripts/go_plan_runtime.py`.
3. `go_plan_runtime.py` is plan-only and not a generic default entry.
4. `~compare` still depends on a host-side bridge.

Generate plan files manually only when the runtime helpers are absent.

## Naming rules

Plan directory format: `YYYYMMDD_feature_name`

Examples:

- `20260115_user_auth`
- `20260115_fix_login_bug`
- `20260115_refactor_api`
