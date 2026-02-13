---
name: workflow-learning
description: Workflow learning sub-skill for full execution-trace capture plus replay/review/why-this-choice explanations. Use when users ask to replay work, run a retrospective, explain decisions, or learn the implementation path.
---

# Workflow Learning - Replay, Review, and Explanation

## Goal

- Capture key implementation trace (input, actions, outcomes, decision reasons).
- Support both "replay the latest session" and "replay by session_id".
- Produce teachable step-by-step explanations for learning.

---

## Trigger Conditions

This skill has two trigger sources:

1. **Intent trigger (always enabled):** activate when user intent includes replay/review/why questions.
2. **Proactive capture trigger (config controlled):** activate automatically based on `workflow.learning.auto_capture`.

Intent trigger examples:

- Replay: `replay`, `play back`, `show the process`
- Retrospective: `review`, `retrospective`, `summarize this run`
- Decision explanation: `why this choice`, `how did you think about this step`

Default usage is after implementation completes. If asked mid-task, generate a partial replay for completed steps.

---

## Proactive Capture Policy (auto_capture)

Config path:

```yaml
workflow:
  learning:
    auto_capture: by_requirement # always | by_requirement | manual | off
```

Policy definitions:

| Value | Behavior |
|------|----------|
| `always` | Proactively capture all development tasks with full-granularity logging |
| `by_requirement` | Capture by complexity: simple=off, medium=summary, complex=full |
| `manual` | Capture only after explicit user request such as "start recording this task" |
| `off` | Do not create new logs; intent-triggered replay still works with existing sessions |

`by_requirement` granularity:

- simple: no proactive capture
- medium: write summary-level records at task completion (minimal event set)
- complex: full phase-level capture (analysis/design/develop/qa)

Important: `auto_capture` controls proactive recording only. It does not disable replay/review/why intent recognition.

---

## Execution Modes

### Mode A: capture

Create/update local session files:

```
.sopify-skills/replay/
└── sessions/
    └── {session_id}/
        ├── session.md
        ├── events.jsonl
        └── breakdown.md
```

Recommended `session_id` format: `YYYYMMDD_HHMMSS_{topic}` (short English topic).

Recommended event schema for each line in `events.jsonl`:

```json
{
  "ts": "2026-02-13T16:30:00Z",
  "phase": "analysis|design|develop|qa",
  "intent": "Goal of this step",
  "action": "Command/tool/edit action",
  "key_output": "Key result summary",
  "decision_reason": "Why this action was chosen",
  "alternatives": ["Option A", "Option B"],
  "result": "success|warning|failed",
  "risk": "Main risk or empty string",
  "artifacts": ["path/to/file"]
}
```

### Mode B: replay

Replay output structure:

1. Task goal and scope
2. Timeline of key steps
3. Key decisions (what, why, outcome)
4. Final deliverables and verification status

### Mode C: breakdown

Explain each step with:

1. Problem to solve
2. Why this approach was selected
3. Alternatives considered
4. Risks and boundaries
5. Impact on the next step

---

## Safety and Boundaries

- Log observable execution traces only; do not output hidden internal chain-of-thought text.
- Redact sensitive values before writing logs (token, api key, cookie, password, secret connection strings).
- Do not record unrelated personal/private data.

---

## Common Prompts

- `Replay the latest implementation`
- `Replay session 20260213_163000_auth-refactor`
- `Review this run and explain why these choices were made`
- `Walk me through this implementation step by step`

---

## Output Contract (Short)

```
[${BRAND_NAME}] Q&A ✓

Replay summary: .sopify-skills/replay/sessions/{session_id}/session.md
Event log: .sopify-skills/replay/sessions/{session_id}/events.jsonl
Step-by-step: .sopify-skills/replay/sessions/{session_id}/breakdown.md

---
Changes: 3 files
Next: Ask "replay latest" or "replay by session_id ..."
```

---

## Change Log

This sub-skill keeps a separate changelog:

- `CHANGELOG.md` (maintained separately from repository root `CHANGELOG.md`)
