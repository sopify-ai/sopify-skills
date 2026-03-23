# Sopify (Sop AI) Skills

<div align="center">

**Config-driven adaptive AI coding skills**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Docs](https://img.shields.io/badge/docs-CC%20BY%204.0-green.svg)](./LICENSE-docs)
[![Version](https://img.shields.io/badge/version-2026--03--23.185925-orange.svg)](#version-history)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

[English](./README_EN.md) · [简体中文](./README.md) · [Quick Start](#quick-start) · [Configuration](#configuration)

</div>

---

## Why Sopify (Sop AI) Skills?

Traditional AI coding assistants run the same heavyweight process for every task — even a one-line typo fix goes through full requirements analysis, solution design, and implementation. Sopify routes by complexity: simple tasks execute directly, and only complex work gets the full planning treatment.

| Task Type | Traditional | Sopify Path |
|-----------|------------|-------------|
| Simple change (≤2 files) | Full three-phase | Direct execution |
| Medium task (3-5 files) | Full three-phase | Light plan + execution |
| Complex work (>5 files / architecture change) | Full three-phase | Full three-phase workflow |

### Key Features

- Install once, then bootstrap `.sopify-runtime/` on demand inside project workspaces
- Config-driven complexity routing to reduce overhead on small tasks
- Manifest-first machine contracts so hosts follow handoff and gate state
- Recoverable checkpoints for clarification, decision, and execution confirmation
- Dual-host support for Codex CLI and Claude Code
- Built-in multi-model comparison and workflow-learning extensions, enabled on demand

**Design rationale:** Sopify applies harness engineering thinking: structured knowledge over free-form prompts, machine contracts over implicit conventions, and observable checkpoints over blind execution. See [How Sopify Works](./docs/how-sopify-works.en.md).

### Recommended Workflow

```text
○ User Input
│
◆ Runtime Gate
│
◇ Routing Decision
├── ▸ Q&A / compare / replay ─────────→ Direct output
└── ▸ Code task
    │
    ◇ Complexity Decision
    ├── Simple (≤2 files) ────────────→ Direct execution
    ├── Medium (3-5 files) ───────────→ Light plan package
    │                                   (single-file `plan.md`)
    └── Complex (>5 files / architecture change)
        ├── Requirements ··· Fact checkpoint
        ├── Design ··· Decision checkpoint
        └── Standard plan package
            (`background.md` / `design.md` / `tasks.md`)
            │
            ◆ Execution confirmation ··· User confirms
            │
            ◆ Implementation
            │
            ◆ Summary + handoff
            │
            ◇ Optional: ~go finalize
            ├── Refresh blueprint index
            ├── Clean active state
            └── Archive → history/
```

> ◆ = execution node　◇ = decision node　··· = checkpoint (pauses, then resumes after user input)
>
> See [How Sopify Works](./docs/how-sopify-works.en.md) for full details on checkpoints and plan lifecycle.

## Quick Start

### Installation

```bash
# Recommended: install into Codex zh-CN first
bash scripts/install-sopify.sh --target codex:zh-CN

# Optional: prewarm a specific workspace
bash scripts/install-sopify.sh --target claude:en-US --workspace /path/to/project
```

Supported `target` values:

- `codex:zh-CN`
- `codex:en-US`
- `claude:zh-CN`
- `claude:en-US`

Installer behavior:

- Installs the selected host prompt layer and the Sopify payload
- Prewarms `.sopify-runtime/` when `--workspace` is provided
- Bootstraps `.sopify-runtime/` on first trigger when `--workspace` is omitted

### First Use

```bash
# Simple task
"Fix the typo on line 42 in src/utils.ts"

# Medium task
"Add error handling to login, signup, and password reset"

# Complex task
"~go Add user authentication with JWT"

# Plan only
"~go plan Refactor the database layer"

# Replay / retrospective
"Replay the latest implementation and explain why this approach was chosen"

# Multi-model comparison
"~compare Compare options for this refactor"
```

For runtime gate, checkpoints, and plan lifecycle details, see [How Sopify Works](./docs/how-sopify-works.en.md).

## Configuration

Start from the example config:

```bash
cp examples/sopify.config.yaml ./sopify.config.yaml
```

Most commonly used settings:

```yaml
brand: auto
language: en-US

workflow:
  mode: adaptive
  require_score: 7

plan:
  directory: .sopify-skills

multi_model:
  enabled: false
  include_default_model: true
```

Notes:

- `workflow.mode` supports `strict / adaptive / minimal`
- `plan.directory` only affects newly created knowledge and plan directories
- `multi_model.enabled` is the global switch; candidates can still be toggled individually
- `multi_model` is off by default; enable it after model candidates and API keys are configured
- `multi_model.include_default_model` and `context_bridge` apply by default even when omitted

## Command Reference

| Command | Description |
|---------|-------------|
| `~go` | Automatically route and run the full workflow |
| `~go plan` | Plan only |
| `~go exec` | Advanced restore/debug entry, not the default user path |
| `~go finalize` | Close out the current metadata-managed plan |
| `~compare` | Run multi-model comparison for the same question |

Most users only need `~go`, `~go plan`, and `~compare`; maintainer validation commands live in [CONTRIBUTING.md](./CONTRIBUTING.md).

## Multi-Model Compare

There are only two supported triggers:

- `~compare <question>`
- `对比分析：<question>`

Minimum environment variable example:

```bash
export GLM_API_KEY="your_glm_key"
export DASHSCOPE_API_KEY="your_qwen_key"
```

Additional notes:

- Parallel compare requires at least two usable models, otherwise it degrades to single-model mode
- The current session model is included by default
- Execution details are defined by `scripts/model_compare_runtime.py` and the sub-skill docs

## Sub-skills

- `model-compare`: multi-model parallel comparison
  Docs: [CN](./Codex/Skills/CN/skills/sopify/model-compare/SKILL.md) / [EN](./Codex/Skills/EN/skills/sopify/model-compare/SKILL.md)
- `workflow-learning`: replay, retrospective, and step-by-step explanation
  Docs: [CN](./Codex/Skills/CN/skills/sopify/workflow-learning/SKILL.md) / [EN](./Codex/Skills/EN/skills/sopify/workflow-learning/SKILL.md)

## Directory Structure

```text
sopify-skills/
├── docs/                  # workflow documentation
├── .sopify-skills/        # project knowledge base
│   ├── blueprint/         # long-lived blueprint
│   ├── plan/              # active plans
│   └── history/           # archived plans
├── Codex/                 # Codex host prompt layer
└── Claude/                # Claude host prompt layer
```

See [docs/how-sopify-works.en.md](./docs/how-sopify-works.en.md) for the full workflow, checkpoints, and knowledge layout.

## FAQ

### Q: How do I switch language?

Update `sopify.config.yaml`:

```yaml
language: zh-CN  # or en-US
```

### Q: Where are plan packages stored?

By default they live under `.sopify-skills/` in the project root. To change that:

```yaml
plan:
  directory: .my-custom-dir
```

This only affects newly created directories; existing history is not migrated automatically.

### Q: How do I reset learned preferences?

Delete or clear `.sopify-skills/user/preferences.md`; keep `feedback.jsonl` only if you still want the audit trail.

### Q: When should I run sync scripts?

When you change `Codex/Skills/{CN,EN}`, the mirrored `Claude/Skills/{CN,EN}` content, or `runtime/builtin_skill_packages/*/skill.yaml`, follow the validation steps in [CONTRIBUTING.md](./CONTRIBUTING.md).

## Version History

- See [CHANGELOG.md](./CHANGELOG.md) for the detailed history

## License

This repository uses dual licensing:

- Code and config: Apache 2.0, see [LICENSE](./LICENSE)
- Documentation: CC BY 4.0, see [LICENSE-docs](./LICENSE-docs)

## Contributing

For user-visible behavior changes, update both `README.md` and `README_EN.md` when needed, then follow [CONTRIBUTING.md](./CONTRIBUTING.md) for validation.
