---
name: develop
description: Development phase rules; read when entering development; includes code execution, KB sync, plan package migration
---

# Development - Detailed Rules

**Goal:** Execute development per task list, sync knowledge base, migrate plan package

**Execution Flow:**
```
1. Read task list
2. Execute tasks in order
3. Update task status
4. Sync knowledge base
5. Migrate plan package to history/
6. Output results
```

---

## Step 1: Read Task List

```yaml
Source: .sopify-skills/plan/{current_plan}/tasks.md
        or .sopify-skills/plan/{current_plan}/plan.md (light level)

Parse: Extract all [ ] pending tasks
Order: Execute in task number order
Dependencies: Check inter-task dependencies
```

---

## Step 2: Execute Tasks

**Execution Principles:**
```yaml
For each task:
  1. Locate target file
  2. Understand current code
  3. Implement changes
  4. Verify correctness
  5. Update task status to [x]

Security checks:
  - Don't introduce vulnerabilities (XSS, SQL injection, etc.)
  - Don't break existing functionality
  - Maintain consistent code style
```

**Task Status Updates:**
```yaml
Successfully completed: [ ] → [x]
Skipped (not needed): [ ] → [-]
Blocked (needs external handling): [ ] → [!]
```

---

## Step 3: Knowledge Base Sync

**Sync Timing:**
- After completing each module's tasks
- At the end of development phase

**Sync Content:**
```yaml
wiki/modules/{module}.md:
  - Update module responsibility description (if changed)
  - Add new API interface documentation
  - Update data model descriptions

wiki/overview.md:
  - Update module index (if new modules)
  - Update quick links

project.md:
  - Update technical conventions (if changed)
```

---

## Step 4: Plan Package Migration

**Migration Path:**
```
.sopify-skills/plan/YYYYMMDD_feature/
    ↓ Move to
.sopify-skills/history/YYYY-MM/YYYYMMDD_feature/
```

**Update Index:**

Add record to `.sopify-skills/history/index.md`:

```markdown
| YYYYMMDDHHMM | {feature name} | {type} | ✓ Completed | [link](YYYY-MM/YYYYMMDD_feature/) |
```

---

## Step 5: Output Format

**Full Success:**
```
[{BRAND_NAME}] Development ✓

Completed: {N}/{N} tasks
Tests: passed

---
Changes: {N} files
  - src/xxx.vue
  - src/xxx.ts
  - .sopify-skills/wiki/modules/xxx.md
  - .sopify-skills/history/...

Next: Please verify the functionality
```

**Partial Success:**
```
[{BRAND_NAME}] Development !

Completed: {M}/{N} tasks
Blocked: {K} items

Blocked tasks:
  - [!] 2.3 {task description} - {block reason}

---
Changes: {N} files
  - ...

Next: Run ~go exec after resolving blocks
```

**Quick Fix Mode (simple tasks executed directly):**
```
[{BRAND_NAME}] Quick Fix ✓

Fixed: {one-line description}

---
Changes: {N} files
  - {file1}
  - {file2}

Next: Please verify the fix
```

---

## Special Case Handling

### Execution Interruption

```yaml
Situation: User interruption or system error
Handling:
  1. Save current progress to tasks.md
  2. Mark completed tasks as [x]
  3. Keep current task as [ ]
  4. Output interruption summary
Recovery: Run ~go exec to continue from interruption point
```

### Task Failure

```yaml
Situation: A task cannot be completed
Handling:
  1. Mark as [!] with reason
  2. Try to continue subsequent independent tasks
  3. Output failure details
```

### Rollback Request

```yaml
Situation: User requests rollback
Handling:
  1. Use git to rollback changes
  2. Keep plan package in plan/ (don't migrate)
  3. Output rollback confirmation
```

---

## Verification Checklist

**Code Quality:**
- [ ] Code style follows project conventions
- [ ] No TypeScript/ESLint errors
- [ ] No obvious performance issues

**Functional Completeness:**
- [ ] All tasks executed
- [ ] Edge cases handled
- [ ] Error handling complete

**Knowledge Base:**
- [ ] Related docs updated
- [ ] Plan package migrated
- [ ] Index updated
