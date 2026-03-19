# Develop Detailed Rules

## Goal

Implement the task list, maintain task state, sync the knowledge base, and finish plan migration.

## Overall flow

1. Read the task list.
2. Execute tasks and update markers.
3. Sync KB and preference data.
4. Move the completed plan into `history/`.
5. Render the execution summary.

## Step 1: Read the task list

Sources:

- `.sopify-skills/plan/{current_plan}/tasks.md`
- `.sopify-skills/plan/{current_plan}/plan.md` (light)

Handling rules:

1. Extract `[ ]` pending tasks.
2. Execute by task number order.
3. Check explicit dependencies before execution.

## Step 2: Execute tasks

Execution rules for each task:

1. Locate the target file.
2. Understand the current implementation.
3. Implement the change.
4. Verify correctness.
5. Update the task marker.

State transitions:

- Success: `[ ] -> [x]`
- Skipped: `[ ] -> [-]`
- Blocked: `[ ] -> [!]`

Security baseline:

- Do not introduce common vulnerabilities (XSS / SQL injection / etc.).
- Do not break existing behavior.
- Keep the project style consistent.

## Step 3: Sync the knowledge base

Sync timing:

1. After each module-level task batch.
2. Once again during phase close-out.

Sync targets:

- `wiki/modules/{module}.md`
- `wiki/overview.md`
- `project.md`
- `user/preferences.md` (long-term preferences only)
- `user/feedback.jsonl`

Conservative preference writes:

Allowed:

- Explicit long-term user preferences such as "use this by default going forward".

Disallowed:

- One-off instructions.
- Guesses from incomplete context.
- Generalized conclusions unrelated to the task.

## Step 4: Plan migration

Migration path:

```text
.sopify-skills/plan/YYYYMMDD_feature/
  -> .sopify-skills/history/YYYY-MM/YYYYMMDD_feature/
```

Update `.sopify-skills/history/index.md` with a new record.

## Output templates

Choose the result format from `assets/`:

1. `assets/output-success.md`
2. `assets/output-partial.md`
3. `assets/output-quick-fix.md`

## Special cases

Execution interruption:

1. Mark completed tasks as `[x]`.
2. Keep the current task as `[ ]`.
3. Render the interruption summary and wait for host recovery.

Task failure:

1. Mark the task as `[!]` with the reason.
2. Continue independent tasks when possible.

Rollback request:

1. Use git rollback only when the user explicitly requests it.
2. Keep the plan package in `plan/` instead of migrating it.
3. Render rollback confirmation.
