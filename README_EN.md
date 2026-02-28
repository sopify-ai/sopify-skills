# Sopify (Sop AI) Skills

<div align="center">

**Standard Sop AI Skills - Config-driven Codex/Claude skills with complexity-based workflow routing**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Docs](https://img.shields.io/badge/docs-CC%20BY%204.0-green.svg)](./LICENSE-docs)
[![Version](https://img.shields.io/badge/version-2026--02--13-orange.svg)](#version-history)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

[English](./README_EN.md) · [简体中文](./README.md) · [Quick Start](#quick-start) · [Configuration](#configuration)

</div>

---

## Why Sopify (Sop AI) Skills?

**The Problem:** Traditional AI programming assistants use the same heavyweight process for all tasks - even a simple typo fix requires full requirements analysis and solution design, resulting in low efficiency and verbose output.

**The Solution:** Sopify (Sop AI) Skills introduces **adaptive workflow**, automatically selecting the optimal path based on task complexity:

| Task Type | Traditional Approach | Sopify (Sop AI) Skills |
|-----------|---------------------|--------------|
| Simple change (≤2 files) | Full 3-phase workflow | Direct execution, skip planning |
| Medium task (3-5 files) | Full 3-phase workflow | Light plan (single file) + execution |
| Complex task (>5 files) | Full 3-phase workflow | Full 3-phase workflow |

### Key Features

- **Adaptive Workflow** - Simple tasks complete in seconds, complex tasks get full planning
- **Concise Output** - Core info visible in one screen, details in files
- **Configuration Driven** - Customize all behavior via `sopify.config.yaml`
- **Dynamic Branding** - By default, derive `{repo}-ai` from the project name as the output identifier
- **Tiered Plan Packages** - light/standard/full levels, generated as needed
- **Workflow Learning** - Replay implementation traces with retrospective and step-by-step explanation
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

**Expected:** Agent lists 7 skills (analyze, design, develop, kb, templates, model-compare, workflow-learning)

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

# 5. Replay / retrospective for the latest implementation
"Replay the latest implementation and explain why this approach was chosen"

# 6. Multi-model parallel comparison (manual choice)
"~compare Compare options for this refactor"
"对比分析：Compare options for this refactor"
```

---

## Configuration

### Configuration File

Config priority (recommended): project root (`./sopify.config.yaml`) > global (`~/.codex/sopify.config.yaml`, or `~/.claude/sopify.config.yaml` for Claude) > built-in defaults.

By default, Sopify (Sop AI) Skills will not write config files automatically. For first-time setup, copy the example config into your project root:

```bash
cp examples/sopify.config.yaml ./sopify.config.yaml
```

On Windows, copy `examples/sopify.config.yaml` into your project root and rename it to `sopify.config.yaml`.

Create (or use the copied) `sopify.config.yaml` in your project root:

```yaml
# Brand name: auto(derive {repo}-ai from project name) or custom
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
  learning:
    auto_capture: by_requirement  # always / by_requirement / manual / off

# Plan package configuration
plan:
  level: auto           # auto / light / standard / full
  directory: .sopify-skills    # Knowledge base directory

# Multi-model compare (MVP) configuration
multi_model:
  enabled: true
  trigger: manual       # trigger only for ~compare or "对比分析："
  timeout_sec: 25
  max_parallel: 3
  include_default_model: true  # optional; defaults to true even when omitted
  context_bridge: true  # optional; defaults to true (external models use context bridge; false = emergency bypass)
  candidates:
    - id: glm
      enabled: true
      provider: openai_compatible
      base_url: https://open.bigmodel.cn/api/paas/v4
      model: glm-4.7
      api_key_env: GLM_API_KEY
    - id: qwen
      enabled: true
      provider: openai_compatible
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
      model: qwen-plus
      api_key_env: DASHSCOPE_API_KEY
```

Note: `title_color` only applies lightweight styling to the output title line; if color is unsupported, output falls back to plain text automatically.
Note: `workflow.learning.auto_capture` controls proactive recording only; replay/review/why intent recognition is always enabled.
Note: `multi_model.enabled` is the feature-level gate, while `multi_model.candidates[*].enabled` is the per-candidate participation gate.
Note: `multi_model.include_default_model` defaults to `true` (the current session default model is included even if omitted).
Note: `multi_model.context_bridge` defaults to `true`; use `false` only as an emergency bypass (question-only input). Execution details are centralized in `scripts/model_compare_runtime.py`.
Note: parallel compare requires at least 2 usable models; below that, compare falls back to single-model with detailed reasons.
Note: fallback reasons should use normalized reason codes (for example `MISSING_API_KEY`, `INSUFFICIENT_USABLE_MODELS`).
Note: `multi_model.candidates[*].api_key_env` reads keys from environment variables only; avoid plaintext keys in config files.

### Workflow Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `strict` | Enforce 3-phase workflow | Formal projects requiring full documentation |
| `adaptive` | Auto-select based on complexity (default) | Daily development |
| `minimal` | Skip planning, execute directly | Quick prototypes, urgent fixes |

### workflow-learning Proactive Capture Policy

| Config Value | Behavior |
|------|----------|
| `always` | Proactively capture all development tasks (full) |
| `by_requirement` | Capture by complexity: simple=off, medium=summary, complex=full |
| `manual` | Capture only after explicit request such as "start recording this task" |
| `off` | Do not create new logs proactively; replay existing sessions remains available |

Note: intent recognition for replay/review/why-explanations remains available in all modes.

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
| `~compare` | Run parallel comparison across configured models; includes the session default model by default and falls back with reasons when usable model count is below 2 |

---

## Multi-Model Compare (MVP)

**Trigger conditions (only these two):**
- `~compare <question>`
- `对比分析：<question>`

**Environment variables (this is the only key method):**

```bash
# Effective for current shell session
export GLM_API_KEY="your_glm_key"
export DASHSCOPE_API_KEY="your_qwen_key"
```

```bash
# Persist in zsh (~/.zshrc)
echo 'export GLM_API_KEY="your_glm_key"' >> ~/.zshrc
echo 'export DASHSCOPE_API_KEY="your_qwen_key"' >> ~/.zshrc
source ~/.zshrc
```

**Behavior:**
- `multi_model.enabled` controls whether compare is enabled; `candidates[*].enabled` controls whether a candidate participates
- The current session default model is included by default (`include_default_model` defaults to true, no extra config needed)
- Context bridge is on by default (`context_bridge=true`): with external candidates, each model receives `question + context_pack`; with `false`, external models get question-only input
- `~compare` runtime implementation is converged in `scripts/model_compare_runtime.py` (entry calls `run_model_compare_runtime`)
- Execution-level details (extract/redact/truncate chain, budgets, empty-pack guard) are centralized in `scripts/model_compare_runtime.py` and the `model-compare` sub-skill doc
- Parallel compare starts only when usable models reach 2 (built-in rule, no extra config needed)
- Fallback reasons should use normalized reason codes (for example `MISSING_API_KEY`, `INSUFFICIENT_USABLE_MODELS`) to keep CN/EN wording aligned
- If one model returns first, it is marked done while waiting for others until timeout/all done
- One-model failure does not block others; any successful result can proceed to manual choice
- If compare is not entered (feature disabled/missing keys/usable model count below 2), it does not error and falls back to single-model with detailed fallback reasons

**Context bridge example (short):**

```text
~compare Why does this bug only happen in prod?

context_pack:
- Key files: src/api/auth.ts:42, src/config/env.ts:10
- Runtime signal: X-Trace-Id missing only in prod
- Redaction: Authorization/Cookie replaced with <REDACTED>
- Truncation: keep only +/- 80 lines around matched functions
```

**Fallback reasons (real example):**

```text
[sopify-agent-ai] Q&A !

Compare mode not entered; executed in single-model mode.
Fallback reasons:
- MISSING_API_KEY: candidate_id=glm
- INSUFFICIENT_USABLE_MODELS: 1<2
Result: I am Sopify's AI coding assistant for analysis, design, and implementation tasks.

---
Changes: 0 files
Next: Adjust multi_model.enabled / candidates[*].enabled / include_default_model / context_bridge or provide missing env vars
```

---

## Sub-skills (Extensions)

`skills/sopify` contains both core skills and sub-skills. This root README stays minimal; see each sub-skill doc for detailed usage.

| Sub-skill | Purpose | Docs |
|-----------|---------|------|
| `model-compare` | Config-driven multi-model parallel compare with failure isolation and manual selection | [中文说明](./Codex/Skills/CN/skills/sopify/model-compare/SKILL.md) / [English Guide](./Codex/Skills/EN/skills/sopify/model-compare/SKILL.md) |
| `workflow-learning` | Full trace capture, replay, and step-by-step explanation | [中文说明](./Codex/Skills/CN/skills/sopify/workflow-learning/SKILL.md) / [English Guide](./Codex/Skills/EN/skills/sopify/workflow-learning/SKILL.md) |

Sub-skill change history is tracked separately from the repository-level changelog:

- [workflow-learning Changelog (CN)](./Codex/Skills/CN/skills/sopify/workflow-learning/CHANGELOG.md)
- [workflow-learning Changelog (EN)](./Codex/Skills/EN/skills/sopify/workflow-learning/CHANGELOG.md)

---

## Sync Mechanism (for maintainers)

To avoid drift between Codex/Claude and CN/EN skill files, use the built-in sync/check scripts:

```bash
# 1) Sync Codex source-of-truth files to Claude mirror files
bash scripts/sync-skills.sh

# 2) Verify all four bundles are aligned
bash scripts/check-skills-sync.sh

# 3) Verify version consistency (README badge / SOPIFY_VERSION / CHANGELOG)
bash scripts/check-version-consistency.sh
```

These scripts ignore Finder/Explorer noise files (`.DS_Store`, `Thumbs.db`) to avoid false drift reports.
Before committing skill/rule updates, always run `sync -> check-skills-sync -> check-version-consistency`.
CI (`.github/workflows/ci.yml`) runs the same gate on PR/Push, and uses `git diff --exit-code` to fail drift that requires sync.

---

## Output Format

Sopify (Sop AI) Skills uses a concise output format:

```
[my-app-ai] Solution Design ✓

Plan: .sopify-skills/plan/20260115_user_auth/
Summary: JWT auth + Redis session management
Tasks: 5 items

---
Changes: 3 files
  - .sopify-skills/plan/20260115_user_auth/background.md
  - .sopify-skills/plan/20260115_user_auth/design.md
  - .sopify-skills/plan/20260115_user_auth/tasks.md

Next: ~go exec to execute or reply with feedback
```

**Status Symbols:**
- `✓` Success
- `?` Awaiting input
- `!` Warning
- `×` Error

**Phase Naming:**
- `Command Complete`: for command-prefixed flows (`~go/~go plan/~go exec/~compare`)
- `Q&A`: for non-command questions/clarifications

---

## Directory Structure

```
.sopify-skills/                        # Knowledge base root
├── project.md                  # Project technical conventions
├── wiki/
│   ├── overview.md            # Project overview
│   └── modules/               # Module documentation
├── user/
│   ├── preferences.md         # Long-term user preferences
│   └── feedback.jsonl         # Raw feedback events
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

| Feature | HelloAGENTS | Sopify (Sop AI) Skills |
|---------|-------------|--------------|
| Brand name | Fixed "HelloAGENTS" | Derived "{repo}-ai" from project name |
| Output style | Many emojis | Clean text |
| Workflow | Fixed 3-phase | Adaptive |
| Plan package | Fixed 3 files | Tiered (light/standard/full) |
| File naming | why.md/how.md/task.md | background.md/design.md/tasks.md |
| Configuration | Scattered in rules | Unified sopify.config.yaml |
| Rule complexity | G1-G12 (12 rules) | Core/Auto/Advanced layered |

---

## File Structure

```
sopify-skills/
├── Claude/
│   └── Skills/
│       ├── CN/                 # Chinese version
│       │   ├── CLAUDE.md       # Main config file
│       │   └── skills/sopify/  # Core skills + sub-skills
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

Default location is `.sopify-skills/` in your project root. Configurable via:
```yaml
plan:
  directory: .my-custom-dir
```

Note: Changing `plan.directory` only affects newly generated knowledge base/plan files. Existing history in the old directory will not be migrated automatically; move it manually if needed, or keep the value unchanged.

### Q: How to skip requirement scoring follow-ups?

Set `auto_decide: true`:
```yaml
workflow:
  auto_decide: true
```

### Q: How do I reset learned user preferences?

Delete (or clear) `.sopify-skills/user/preferences.md` to reset long-term preferences. Keep `feedback.jsonl` only if you want audit history.

### Q: When should I run sync scripts?

After editing rule files under `Codex/Skills/{CN,EN}`, run:
```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
```
If any check fails, fix the mismatch before committing.

---

## Version History

- Detailed release notes are maintained manually in `CHANGELOG.md`.

---

## License

This repository is intended to use a dual-licensing approach (see license files for details):

- Code and configs (including example configs): Apache 2.0 (see `LICENSE`)
- Documentation (mostly Markdown): CC BY 4.0 (see `LICENSE-docs`)

If you think any attribution or licensing details should be clarified (for example, if some parts were adapted from other open-source repositories), please open an issue or include details in your PR.

---

## Contributing

Issues and PRs welcome!
