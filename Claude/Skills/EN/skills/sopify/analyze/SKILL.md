---
name: analyze
description: Analyze phase entry; routes scoring, follow-up, and scope checks through references/assets/scripts.
---

# Analyze (Entry)

## When to activate

- Entering the analysis phase (`workflow` / `plan_only`).
- Need requirement scoring, clarification, or complexity routing.

## Execution skeleton

1. Load `references/analyze-rules.md` first.
2. Run Phase A (KB check, context acquisition, requirement typing, completeness scoring).
3. If the score is below threshold, follow `auto_decide`:
   - `false`: ask follow-up questions with `assets/question-output.md`.
   - `true`: state explicit assumptions, then continue.
4. After the score passes, run Phase B (objective extraction, code analysis, technical prep).
5. Render the phase summary with `assets/success-output.md`.

## Resource navigation

- Long rules: `references/analyze-rules.md`
- Follow-up template: `assets/question-output.md`
- Success template: `assets/success-output.md`
- Deterministic scoring script: `scripts/score_requirement.py`

## Deterministic logic first

Use the script when the score must be auditable:

```bash
python3 Codex/Skills/EN/skills/sopify/analyze/scripts/score_requirement.py \
  --goal-clarity 2 \
  --expected-outcome 2 \
  --scope-boundary 1 \
  --constraints 1 \
  --require-score 7
```

The script returns JSON with total score, threshold result, and missing dimensions.

## Boundaries

- This skill does not generate a plan package directly; hand off to `design`.
- This skill does not execute code changes directly; hand off to `develop` or runtime routing.
