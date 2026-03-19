---
name: develop
description: Develop phase entry; routes task execution, state updates, KB sync, and plan close-out through references/assets/scripts.
---

# Develop (Entry)

## When to activate

- Entering the implementation phase (`workflow` / `light_iterate` / `quick_fix` / `exec_plan`).
- Need to execute the task list, update state, and converge the delivery result.

## Execution skeleton

1. Read the active plan tasks (`tasks.md` or light `plan.md`).
2. Extract pending tasks and execute them in numbered order.
3. Update task markers after each step (`[ ] -> [x] / [-] / [!]`).
4. Sync KB files and conservative preference / feedback records.
5. Move completed plans into `history/` and update the index.
6. Render the matching result template.

## Resource navigation

- Long rules: `references/develop-rules.md`
- Output templates: `assets/*.md`
- Task extraction script: `scripts/extract_pending_tasks.py`

## Deterministic logic first

Use the script when task extraction must be auditable:

```bash
python3 Codex/Skills/EN/skills/sopify/develop/scripts/extract_pending_tasks.py \
  --tasks-file .sopify-skills/plan/<plan>/tasks.md
```

The script returns JSON with pending tasks, status counts, and execution order.

## Boundaries

- This skill executes and closes out work; it does not redefine the plan structure.
- Rollback remains an explicit user action and must keep a traceable record.
