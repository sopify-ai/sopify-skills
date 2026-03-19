---
name: design
description: Design phase entry; routes plan grading, task breakdown, and plan package output through references/assets/scripts.
---

# Design (Entry)

## When to activate

- Entering the design phase (`workflow` / `plan_only` / `light_iterate`).
- Need to convert validated requirements into a plan package and task list.

## Execution skeleton

1. Load `references/design-rules.md`.
2. Decide `light/standard/full` from explicit change signals.
3. Generate the plan files from the matching templates in `assets/`.
4. Produce the task list and validate task granularity.
5. Render the plan summary with `assets/output-summary.md`.

## Resource navigation

- Long rules: `references/design-rules.md`
- Templates: `assets/*.md`
- Deterministic level selector: `scripts/select_plan_level.py`

## Deterministic logic first

Use the selector when `plan.level=auto` must be auditable:

```bash
python3 Codex/Skills/EN/skills/sopify/design/scripts/select_plan_level.py \
  --file-count 6 \
  --new-feature \
  --cross-module
```

The script returns JSON with the suggested level and explicit reasons.

## Boundaries

- This skill does not execute code changes directly; hand off to `develop`.
- This skill does not replace runtime routing; it defines the plan structure and task contract only.
