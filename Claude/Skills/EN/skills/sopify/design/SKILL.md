---
name: design
description: Solution design phase rules; read when entering design; includes plan generation, task breakdown, plan package creation
---

# Solution Design - Detailed Rules

**Goal:** Design technical solution, break down executable tasks, create plan package

**Execution Flow:**
```
1. Determine plan package level (light/standard/full)
2. Generate plan files
3. Break down task list
4. Output summary
```

---

## Step 1: Determine Plan Package Level

**Auto-detection logic (plan.level=auto):**

```yaml
light (single plan.md):
  - 3-5 files
  - No architectural changes
  - Clear modification scope

standard (three files):
  - Files > 5
  - Or new feature development
  - Or cross-module modifications

full (complete structure):
  - Architectural changes
  - Major refactoring
  - New system design
```

---

## Step 2: Generate Plan Files

### Light Level - plan.md

```markdown
# {Feature Name}

## Background
{1-2 sentences describing requirement background}

## Solution
{Technical solution points in list form}

## Tasks
- [ ] {task1}
- [ ] {task2}
- [ ] {task3}

## Changed Files
- {file1}
- {file2}
```

### Standard Level - Three File Structure

**background.md:**
```markdown
# Change Proposal: {Feature Name}

## Requirement Background
{Describe current state, pain points, and change drivers}

## Change Content
1. {change point 1}
2. {change point 2}

## Impact Scope
- Modules: {list}
- Files: {list}

## Risk Assessment
- Risk: {description}
- Mitigation: {measures}
```

**design.md:**
```markdown
# Technical Design: {Feature Name}

## Technical Solution
- Core Technology: {language/framework/library}
- Implementation Points:
  - {point1}
  - {point2}

## Architecture Design
{If changes, include mermaid diagram}

## Security & Performance
- Security: {measures}
- Performance: {optimizations}
```

**tasks.md:**
```markdown
# Task List: {Feature Name}

Directory: `.sopify-skills/plan/YYYYMMDD_{feature}/`

## 1. {Module Name}
- [ ] 1.1 Implement {feature} in `{file path}`
- [ ] 1.2 Implement {feature} in `{file path}`

## 2. Testing
- [ ] 2.1 {test task}

## 3. Documentation Update
- [ ] 3.1 Update {knowledge base file}
```

### Full Level - Complete Structure

Adds to Standard:

```
.sopify-skills/plan/YYYYMMDD_feature/
├── background.md
├── design.md
├── tasks.md
├── adr/
│   └── 001-{decision-title}.md
└── diagrams/
    └── {diagram-name}.mermaid
```

**adr/001-xxx.md:**
```markdown
# ADR-001: {Decision Title}

## Status
Accepted | Proposed | Deprecated

## Context
{Background and problem}

## Decision
{Core decision}

## Rationale
{Reasons}

## Alternatives
- {Option A}: Rejected because - {reason}

## Consequences
{Impacts and risks}
```

---

## Step 3: Task Breakdown Principles

**Task Granularity:**
```yaml
Each task should:
  - Be completable in 30 minutes
  - Have clear verification criteria
  - Have clear dependencies

Task categories:
  1. Core feature implementation
  2. Supporting features
  3. Security checks
  4. Testing
  5. Documentation updates
```

**Task Status Symbols:**
| Symbol | Meaning |
|--------|---------|
| `[ ]` | Pending |
| `[x]` | Completed |
| `[-]` | Skipped |
| `[!]` | Blocked |

---

## Step 4: Output Format

```
[{BRAND_NAME}] Solution Design ✓

Plan: .sopify-skills/plan/{YYYYMMDD}_{feature}/
Summary: {one-line technical solution}
Tasks: {N} items

---
Changes: {N} files
  - .sopify-skills/plan/...

Next: ~go exec to execute or reply with feedback
```

---

## Phase Transition Rules

```yaml
workflow.mode = strict:
  → Output summary → Wait for user confirmation

workflow.mode = adaptive:
  → If triggered by ~go command → Auto-enter development
  → If triggered by ~go plan command → Output summary and stop

User replies with feedback:
  → Stay in design phase → Update plan files → Re-output summary
```

---

## Plan Package Naming Rules

```
Format: YYYYMMDD_feature_name
Examples: 20260115_user_auth
          20260115_fix_login_bug
          20260115_refactor_api
```

**Naming Principles:**
- Use underscores as separators
- Feature name in lowercase English
- Concise but identifiable
