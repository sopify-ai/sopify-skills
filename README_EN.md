# Sopify Agent

<div align="center">

**Adaptive AI Programming Assistant - Intelligently selects workflow based on task complexity**

[English](./README_EN.md) · [简体中文](./README.md) · [Quick Start](#-quick-start) · [Configuration](#-configuration)

</div>

---

## Why Sopify Agent?

**The Problem:** Traditional AI programming assistants use the same heavyweight process for all tasks - even a simple typo fix requires full requirements analysis and solution design, resulting in low efficiency and verbose output.

**The Solution:** Sopify Agent introduces **adaptive workflow**, automatically selecting the optimal path based on task complexity:

| Task Type | Traditional Approach | Sopify Agent |
|-----------|---------------------|--------------|
| Simple change (≤2 files) | Full 3-phase workflow | Direct execution, skip planning |
| Medium task (3-5 files) | Full 3-phase workflow | Light plan (single file) + execution |
| Complex task (>5 files) | Full 3-phase workflow | Full 3-phase workflow |

### Key Features

- **Adaptive Workflow** - Simple tasks complete in seconds, complex tasks get full planning
- **Concise Output** - Core info visible in one screen, details in files
- **Configuration Driven** - Customize all behavior via `sopify.config.yaml`
- **Dynamic Branding** - Auto-detect repo name as output identifier
- **Tiered Plan Packages** - light/standard/full levels, generated as needed
- **Cross-Platform** - Supports both Claude Code and Codex CLI

---

## Quick Start

### Prerequisites

- CLI environment (Claude Code or Codex CLI)
- File system access

### Installation

**For Claude Code users:**

```bash
# English version
cp -r Claude/Skills/EN/* ~/.claude/

# Chinese version
cp -r Claude/Skills/CN/* ~/.claude/
```

**For Codex CLI users:**

```bash
# English version
cp -r Codex/Skills/EN/* ~/.codex/

# Chinese version
cp -r Codex/Skills/CN/* ~/.codex/
```

### Verify Installation

Restart your terminal and type:
```
Show skills list
```

**Expected:** Agent lists 5 skills (analyze, design, develop, kb, templates)

### First Use

```bash
# 1. Simple task → Direct execution
"Fix the typo on line 42 in src/utils.ts"

# 2. Medium task → Light plan + execution
"Add error handling to login, signup, and password reset"

# 3. Complex task → Full workflow
"~go Add user authentication with JWT"

# 4. Plan only, no execution
"~go plan Refactor the database layer"
```

---

## Configuration

### Configuration File

Create `sopify.config.yaml` in your project root:

```yaml
# Brand name: auto(auto-detect) or custom
brand: auto

# Language: zh-CN / en-US
language: en-US

# Output style: minimal(clean) / classic(with emoji)
output_style: minimal

# Title color: green/blue/yellow/cyan/none
title_color: green

# Workflow configuration
workflow:
  mode: adaptive        # strict / adaptive / minimal
  require_score: 7      # Requirement score threshold
  auto_decide: false    # AI auto-decision

# Plan package configuration
plan:
  level: auto           # auto / light / standard / full
  directory: .sopify    # Knowledge base directory
```

### Workflow Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `strict` | Enforce 3-phase workflow | Formal projects requiring full documentation |
| `adaptive` | Auto-select based on complexity (default) | Daily development |
| `minimal` | Skip planning, execute directly | Quick prototypes, urgent fixes |

### Plan Package Levels

| Level | File Structure | Trigger |
|-------|---------------|---------|
| `light` | Single `plan.md` | 3-5 file changes |
| `standard` | `background.md` + `design.md` + `tasks.md` | >5 files or new features |
| `full` | Standard + `adr/` + `diagrams/` | Architectural changes |

---

## Command Reference

| Command | Description |
|---------|-------------|
| `~go` | Full workflow auto-execution |
| `~go plan` | Plan only, no execution |
| `~go exec` | Execute existing plan |

---

## Output Format

Sopify Agent uses a concise output format:

```
[my-app-ai] Solution Design ✓

Plan: .sopify/plan/20260115_user_auth/
Summary: JWT auth + Redis session management
Tasks: 5 items

---
Changes: 3 files
  - .sopify/plan/20260115_user_auth/background.md
  - .sopify/plan/20260115_user_auth/design.md
  - .sopify/plan/20260115_user_auth/tasks.md

Next: ~go exec to execute or reply with feedback
```

**Status Symbols:**
- `✓` Success
- `?` Awaiting input
- `!` Warning
- `×` Error

---

## Directory Structure

```
.sopify/                        # Knowledge base root
├── project.md                  # Project technical conventions
├── wiki/
│   ├── overview.md            # Project overview
│   └── modules/               # Module documentation
├── plan/                       # Current plans
│   └── YYYYMMDD_feature/
│       ├── background.md      # Requirement background (formerly why.md)
│       ├── design.md          # Technical design (formerly how.md)
│       └── tasks.md           # Task list (formerly task.md)
└── history/                    # Historical plans
    ├── index.md
    └── YYYY-MM/
```

---

## Comparison with HelloAGENTS

| Feature | HelloAGENTS | Sopify Agent |
|---------|-------------|--------------|
| Brand name | Fixed "HelloAGENTS" | Dynamic "{repo}-ai" |
| Output style | Many emojis | Clean text |
| Workflow | Fixed 3-phase | Adaptive |
| Plan package | Fixed 3 files | Tiered (light/standard/full) |
| File naming | why.md/how.md/task.md | background.md/design.md/tasks.md |
| Configuration | Scattered in rules | Unified sopify.config.yaml |
| Rule complexity | G1-G12 (12 rules) | Core/Auto/Advanced layered |

---

## File Structure

```
sopify-agent/
├── Claude/
│   └── Skills/
│       ├── CN/                 # Chinese version
│       │   ├── CLAUDE.md       # Main config file
│       │   └── skills/sopify/  # Skill modules
│       └── EN/                 # English version
├── Codex/
│   └── Skills/                 # Codex CLI version
├── examples/
│   └── sopify.config.yaml      # Config example
├── README.md                   # Chinese docs
└── README_EN.md                # English docs
```

---

## FAQ

### Q: How to switch language?

Modify the `language` field in `sopify.config.yaml`:
```yaml
language: zh-CN  # or en-US
```

### Q: How to disable adaptive mode?

Set workflow mode to strict:
```yaml
workflow:
  mode: strict
```

### Q: Where are plan packages stored?

Default location is `.sopify/` in your project root. Configurable via:
```yaml
plan:
  directory: .my-custom-dir
```

### Q: How to skip requirement scoring follow-ups?

Set `auto_decide: true`:
```yaml
workflow:
  auto_decide: true
```

---

## License

Apache 2.0

---

## Contributing

Issues and PRs welcome!
