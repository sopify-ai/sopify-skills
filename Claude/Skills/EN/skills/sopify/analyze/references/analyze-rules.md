# Analyze Detailed Rules

## Goal

Verify requirement completeness, analyze the current codebase, and provide stable input for downstream design.

## Overall flow

```text
Phase A (steps 1-4) -> check score >= require_score?
  ├─ yes  -> Phase B (steps 5-6) -> render summary
  └─ no   -> check auto_decide
       ├─ true  -> continue with explicit assumptions
       └─ false -> ask follow-up questions and wait for user input
```

## Phase A: Requirement assessment

### Step 1: Check knowledge-base status

- Condition: project code exists and the task is not "new project bootstrap".
- Action: check whether `.sopify-skills/` exists.
- Mark the KB as missing when the directory does not exist.

### Step 2: Acquire project context

- Read `.sopify-skills/user/preferences.md` and KB files first.
- Scan the codebase only when KB context is insufficient.
- Follow the `kb` skill for KB-specific rules.

Preference rules:

1. Use only explicit long-term user preferences.
2. Current-task instructions override historical preferences.
3. Fall back to defaults when no preference matches.

### Step 3: Determine requirement type

Candidate types:

1. New project bootstrap
2. New feature development
3. Feature modification / enhancement
4. Bug fix
5. Refactor / optimization
6. Technical change

### Step 4: Score requirement completeness

Scoring dimensions (10 total):

- Goal clarity: 0-3
- Expected outcome: 0-3
- Scope boundary: 0-2
- Constraints: 0-2

Scoring rules:

- `score >= require_score`: continue to Phase B.
- `score < require_score` and `auto_decide=true`: continue with explicit assumptions.
- `score < require_score` and `auto_decide=false`: ask follow-up questions with `assets/question-output.md`.

Follow-up rules:

1. Do not ask for information that code can already provide.
2. Ask only for user-facing gaps: business logic, target behavior, constraints.
3. Ask 3-5 questions.
4. Do not re-ask preferences that are already captured as long-term preferences.

## Phase B: Code analysis

### Step 5: Extract key objectives

- Compress the request into one core objective sentence.
- Define verifiable success criteria.

### Step 6: Code analysis and technical preparation

- Estimate project and change scale.
- Locate related modules and key files.
- Run baseline quality checks (stale information, security risks).
- Pull external documentation only when necessary.

## Adaptive routing

- Simple task (`<=2` files and clear scope): go straight to quick fix.
- Medium task (`3-5` files): enter the light plan path.
- Complex task (`>5` files or architectural change): enter full design.

## Phase transitions

- Score below threshold and no auto-decide: keep asking until the score passes or the user cancels.
- `workflow.mode=strict`: render summary and wait for confirmation.
- `workflow.mode=adaptive`: continue automatically according to complexity.
- User says `cancel`: terminate with the cancellation path.
