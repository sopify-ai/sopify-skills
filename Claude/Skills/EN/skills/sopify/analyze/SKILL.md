---
name: analyze
description: Requirements analysis phase rules; read when entering analysis; includes scoring, follow-up logic, code analysis steps
---

# Requirements Analysis - Detailed Rules

**Goal:** Verify requirement completeness, analyze code status, provide foundation for solution design

**Execution Flow:**
```
Phase A (steps 1-4) → Critical checkpoint: Score ≥ require_score?
  ├─ Yes → Execute Phase B (steps 5-6) → Output summary
  └─ No → Check auto_decide
       ├─ true → AI decides autonomously, continue
       └─ false → Output follow-up → Wait for user input
```

---

## Phase A: Requirement Assessment

### Step 1: Check Knowledge Base Status

```yaml
Condition: Code files exist in working directory AND requirement is not "new project"
Execution: Check if .sopify-skills/ directory exists
Issue marking: If KB doesn't exist, mark for initialization
```

### Step 2: Acquire Project Context

```yaml
Execution: Read .sopify-skills/user/preferences.md and knowledge base first → Scan codebase if insufficient
Detailed rules: Refer to kb Skill
Purpose: Provide complete project context for scoring and follow-up
```

**Preference Application Rules:**
```yaml
1. Use only explicitly stated long-term user preferences
2. Explicit requirements in the current task override historical preferences
3. If no matching preference exists, follow default rules
```

### Step 3: Requirement Type Determination

- New project initialization
- New feature development
- Feature modification/enhancement
- Bug fix
- Refactoring optimization
- Technical changes

### Step 4: Requirement Completeness Scoring

**Scoring Dimensions (Total 10 points):**

| Dimension | Points | Description |
|-----------|--------|-------------|
| Goal Clarity | 0-3 | Is the task goal clear and specific |
| Expected Results | 0-3 | Are success criteria and deliverables clear |
| Scope Boundaries | 0-2 | Are task scope and boundaries defined |
| Constraints | 0-2 | Are time, performance, business constraints explained |

**Scoring Reasoning Process (in <thinking> block):**

```
<thinking>
1. Analyze each scoring dimension:
   - Goal Clarity (0-3): [analysis] → X points
   - Expected Results (0-3): [analysis] → X points
   - Scope Boundaries (0-2): [analysis] → X points
   - Constraints (0-2): [analysis] → X points
2. List specific evidence supporting the score
3. Identify missing key information
4. Calculate total: X/10
5. Determination: [whether follow-up needed and reason]
</thinking>
```

**Post-Scoring Processing:**

```yaml
Score ≥ require_score: Continue to Phase B

Score < require_score:
  auto_decide = true: AI fills in assumptions, continues
  auto_decide = false: Output follow-up, wait for response
```

### Follow-up Output Format

```
[{BRAND_NAME}] Requirements Analysis ?

Current score {X}/10, need to clarify:

1. {question1}
2. {question2}
3. {question3}

---
Next: Please answer the questions, or type "continue" to skip
```

**Follow-up Rules:**
- Don't ask known information (tech stack, framework can be obtained from code)
- Only ask user-related information (specific requirements, business logic, expectations)
- Question count: 3-5
- Do not re-ask long-term preferences already captured in preferences.md

---

## Phase B: Code Analysis (after score threshold met)

### Step 5: Extract Key Objectives

- Refine core objectives from complete requirements
- Define verifiable success criteria

### Step 6: Code Analysis and Technical Preparation

```yaml
Execution content:
  - Determine project scale
  - Locate relevant modules
  - Quality check: Mark outdated info, scan security risks
  - Technical info gathering (if needed): Use web search for latest docs

Deliverables: Project context info for solution design
```

---

## Output Format

**When score threshold met:**

```
[{BRAND_NAME}] Requirements Analysis ✓

Requirement: {one-line description}
Type: {requirement type}
Score: {X}/10
Scope: {estimated file count}

---
Changes: 0 files

Next: Continue to solution design? (Y/n)
```

**Routing in adaptive mode:**

```yaml
Simple task (≤2 files, clear requirements):
  → Skip solution design, enter quick fix directly

Medium task (3-5 files):
  → Enter light iteration, generate light plan package

Complex task (>5 files or architectural changes):
  → Enter full solution design
```

---

## Phase Transition Rules

```yaml
Score < require_score AND auto_decide=false:
  → Loop follow-up until score met or user cancels

Score met AND workflow.mode=strict:
  → Output summary → Wait for confirmation

Score met AND workflow.mode=adaptive:
  → Determine route based on complexity → Auto-enter next phase

User inputs "cancel":
  → Output cancellation format, end workflow
```
