---
name: kb
description: Knowledge base management skill; read during KB operations; includes init, update, sync strategies
---

# Knowledge Base Management - Detailed Rules

**Goal:** Manage project knowledge base, keep docs in sync with code

**Knowledge Base Directory:** `.sopify/`

---

## Knowledge Base Structure

```
.sopify/
├── project.md              # Project technical conventions
├── wiki/
│   ├── overview.md         # Project overview
│   ├── arch.md             # Architecture design (optional)
│   ├── api.md              # API reference (optional)
│   ├── data.md             # Data models (optional)
│   └── modules/            # Module documentation
│       └── {module}.md
├── plan/                   # Current plans
│   └── YYYYMMDD_feature/
└── history/                # Historical plans
    ├── index.md            # Index
    └── YYYY-MM/
        └── YYYYMMDD_feature/
```

---

## Initialization Strategies

### Full Mode (kb_init: full)

Create all template files at once:
```yaml
Create files:
  - .sopify/project.md
  - .sopify/wiki/overview.md
  - .sopify/wiki/arch.md
  - .sopify/wiki/api.md
  - .sopify/wiki/data.md
  - .sopify/wiki/modules/.gitkeep
  - .sopify/plan/.gitkeep
  - .sopify/history/index.md
```

### Progressive Mode (kb_init: progressive) [Default]

Create files as needed:
```yaml
Initial setup:
  - .sopify/project.md (required)

First plan:
  - .sopify/plan/ directory
  - .sopify/history/index.md

First module documentation:
  - .sopify/wiki/overview.md
  - .sopify/wiki/modules/{module}.md

First API documentation:
  - .sopify/wiki/api.md

First data model documentation:
  - .sopify/wiki/data.md
```

---

## Project Context Acquisition

**Acquisition Flow:**
```
1. Check if .sopify/ exists
2. Exists → Read knowledge base files
3. Doesn't exist or insufficient → Scan code
```

**Code Scanning Strategy:**
```yaml
Tech stack identification:
  - package.json → Node/Frontend project
  - requirements.txt / pyproject.toml → Python project
  - go.mod → Go project
  - Cargo.toml → Rust project
  - pom.xml / build.gradle → Java project

Project structure:
  - src/ directory structure
  - Config file locations
  - Test directory locations

Key modules:
  - Entry files
  - Core business modules
  - Common utility modules
```

---

## Update Rules

### When to Update Knowledge Base

```yaml
Must update:
  - New module added
  - Module responsibility changed
  - API interface changed
  - Data model changed
  - Technical convention changed

No update needed:
  - Bug fixes (no interface changes)
  - Internal implementation optimization
  - Code formatting adjustments
```

### Update Priority

```yaml
1. Documentation tasks marked in tasks.md
2. Module docs for changed code
3. Overall architecture description (if architectural changes)
```

---

## Conflict Handling

**When code conflicts with docs:**
```yaml
Principle: Code is the single source of truth
Handling:
  1. Defer to actual code behavior
  2. Update docs to match code
  3. Mark update timestamp
```

---

## Output Format

**Initialization Complete:**
```
[{BRAND_NAME}] Knowledge Base Init ✓

Created: {N} files
Strategy: {full/progressive}

---
Changes: {N} files
  - .sopify/project.md
  - .sopify/wiki/overview.md
  - ...

Next: Knowledge base ready
```

**Sync Complete:**
```
[{BRAND_NAME}] Knowledge Base Sync ✓

Updated: {N} files

---
Changes: {N} files
  - .sopify/wiki/modules/xxx.md
  - ...

Next: Documentation updated
```

---

## Quick Decision Tree

```
Need project context?
    │
    ├─ .sopify/ exists?
    │   ├─ Yes → Read knowledge base files
    │   └─ No → Scan code + Ask if init needed
    │
    └─ Sufficient info?
        ├─ Yes → Return context
        └─ No → Additional code scanning
```
