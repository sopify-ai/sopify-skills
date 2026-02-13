---
name: templates
description: Document template collection; read when creating docs; includes all KB templates and plan file templates
---

# Document Template Collection

**Template Usage:**
1. Replace `{...}` content with actual values
2. Keep or remove optional sections as needed
3. Follow language settings in config file

---

## A1 | Knowledge Base Document Templates

### project.md

```markdown
# Project Technical Conventions

## Tech Stack
- Core: {language version} / {framework version}
- Build: {build tool}
- Testing: {test framework}

## Development Conventions
- Code style: {reference standard or brief description}
- Naming convention: {camelCase/snake_case etc.}
- Directory structure: {brief description}

## Error & Logging
- Error handling: {strategy}
- Log format: {format requirements}

## Git Standards
- Branch strategy: {strategy}
- Commit message: {format}
```

---

### wiki/overview.md

```markdown
# {Project Name}

> Core project information overview. See `modules/` for detailed module docs.

## Project Overview

### Goals & Background
{Brief project goals and background}

### Scope
- In scope: {core features}
- Out of scope: {explicitly excluded}

## Module Index

| Module Name | Responsibility | Status | Docs |
|-------------|----------------|--------|------|
| {module} | {responsibility} | {status} | [link](modules/{module}.md) |

## Quick Links
- [Technical Conventions](../project.md)
- [Change History](../history/index.md)
```

---

### wiki/modules/{module}.md

```markdown
# {Module Name}

## Purpose
{One-line module purpose}

## Module Overview
- Responsibility: {detailed responsibility}
- Status: ✅Stable / 🚧In Development / 📝Planned
- Last Updated: {YYYY-MM-DD}

## Core Features

### {Feature 1}
{Feature description}

### {Feature 2}
{Feature description}

## API Interfaces
{If applicable}

## Dependencies
- {dependency module list}

## Change History
- [{YYYYMMDD}_feature](../../history/...) - {change summary}
```

---

### history/index.md

```markdown
# Change History Index

Records all completed changes for traceability.

## Index

| Timestamp | Feature Name | Type | Status | Plan Package |
|-----------|--------------|------|--------|--------------|
| {YYYYMMDD} | {feature} | {type} | ✓ | [link](YYYY-MM/...) |

## Monthly Archive

### {YYYY-MM}
- [{YYYYMMDD}_feature](...) - {description}
```

---

### user/preferences.md

```markdown
# Long-Term User Preferences

> Record only explicitly stated long-term preferences; do not store one-off instructions.

## Preference List

| ID | Category | Preference | Scope | Source Date | Status |
|----|----------|------------|-------|-------------|--------|
| pref-001 | Output format | Keep title concise and limit core info to 3 lines | Project-wide | 2026-01-15 | active |

## Notes
- Priority: explicit requirement in current task > preference file > default rules
- Update policy: new preference must be restatable, verifiable, and reversible
```

---

### user/feedback.jsonl

```json
{"timestamp":"2026-01-15T10:30:00Z","source":"chat","message":"Use a minimal change list by default next time","scope":"planning","promote_to_preference":true,"preference_id":"pref-002"}
{"timestamp":"2026-01-15T11:10:00Z","source":"chat","message":"Make this response more detailed","scope":"current_task","promote_to_preference":false}
```

---

## A2 | Plan File Templates

### Light Level - plan.md

```markdown
# {Feature Name}

## Background
{1-2 sentences describing requirement background}

## Solution
- {technical solution point 1}
- {technical solution point 2}
- {technical solution point 3}

## Tasks
- [ ] {task 1}
- [ ] {task 2}
- [ ] {task 3}

## Changed Files
- {file1}
- {file2}
```

---

### Standard Level - background.md

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
| Risk | Impact | Mitigation |
|------|--------|------------|
| {risk description} | {impact level} | {measures} |
```

---

### Standard Level - design.md

```markdown
# Technical Design: {Feature Name}

## Technical Solution
- Core Technology: {language/framework/library}
- Implementation Points:
  - {point 1}
  - {point 2}

## Architecture Design
{If architectural changes}

## Security & Performance
- Security: {measures}
- Performance: {optimizations}

## Testing Strategy
- Unit tests: {scope}
- Integration tests: {scope}
```

---

### Standard Level - tasks.md

```markdown
# Task List: {Feature Name}

Directory: `.sopify-skills/plan/{YYYYMMDD}_{feature}/`

## 1. {Core Feature Module}
- [ ] 1.1 Implement {feature} in `{file path}`
- [ ] 1.2 Implement {feature} in `{file path}`

## 2. {Supporting Features}
- [ ] 2.1 {task description}

## 3. Testing
- [ ] 3.1 Write {test type} tests

## 4. Documentation Update
- [ ] 4.1 Update {knowledge base file}
```

---

### Full Level - adr/{NNN}-{title}.md

```markdown
# ADR-{NNN}: {Decision Title}

## Status
Accepted | Proposed | Deprecated

## Date
{YYYY-MM-DD}

## Context
{Background and problem description}

## Decision
{Core decision content}

## Rationale
{Reasons for this decision}

## Alternatives
| Option | Description | Rejection Reason |
|--------|-------------|------------------|
| {Option A} | {description} | {reason} |

## Consequences
- Pros: {list}
- Cons: {list}
- Risks: {list}
```

---

## A3 | Task Status Symbols

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Pending |
| `[x]` | Completed |
| `[-]` | Skipped |
| `[!]` | Blocked |
