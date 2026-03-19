# Skill Authoring Guide (Sopify)

This document defines the package contract, `skill.yaml` machine fields, permission boundaries, and pre-merge checks for Sopify skills.

## 1. Scope

Applies to:

- `Codex/Skills/{CN,EN}/skills/sopify/*` (prompt-layer source of truth)
- `Claude/Skills/{CN,EN}/skills/sopify/*` (mirrored by sync scripts)
- `runtime/builtin_skill_packages/*` (runtime machine source-of-truth)

## 2. Skill Package Contract

Current repo layout (logical package):

```text
Codex/Skills/{CN,EN}/skills/sopify/<skill>/
├── SKILL.md
├── references/
├── assets/
└── scripts/

runtime/builtin_skill_packages/<skill>/
└── skill.yaml
```

Ownership:

1. `SKILL.md`: entry doc only (activation, flow skeleton, boundaries, navigation).
2. `skill.yaml`: machine metadata (routes, permissions, host support, runtime entry); currently stored under `runtime/builtin_skill_packages/*`.
3. `references/`: long-form rules and background.
4. `assets/`: templates and output snippets.
5. `scripts/`: deterministic logic.

Anti-patterns:

- Putting long templates/rules back into `SKILL.md`.
- Duplicating `skill.yaml` machine fields in `SKILL.md`.
- Using non-deterministic logic in `scripts/`.

## 3. `skill.yaml` Fields

Schema and normalization are defined in `runtime/skill_schema.py`.

### 3.1 Common fields

```yaml
schema_version: "1"
id: analyze
mode: workflow # advisory | workflow | runtime
names:
  zh-CN: analyze
  en-US: analyze
descriptions:
  zh-CN: Analyze entry
  en-US: Analyze entry
handoff_kind: analysis
contract_version: "1"
supports_routes:
  - workflow
  - plan_only
triggers:
  - "~compare"
tools:
  - read
disallowed_tools:
  - write
allowed_paths:
  - .
requires_network: false
host_support:
  - codex
  - claude
permission_mode: default # default | host | runtime | dual
```

### 3.2 Permission semantics

1. `tools`: allowed tool set.
2. `disallowed_tools`: explicit deny list.
3. `allowed_paths`: allowed path prefixes.
4. `requires_network`: whether network is required.
5. `host_support`: supported hosts.
6. `permission_mode`: enforcement ownership mode.

Note: the current runtime only fails closed on `skill.yaml` schema, `host_support`, and runtime `permission_mode`. `tools / disallowed_tools / allowed_paths / requires_network` are declared today but are not yet runtime-enforced.

## 4. Runtime Contract Alignment

### 4.1 Declarative route binding

- Use `supports_routes` for route-to-skill declaration.
- Resolver uses declarative binding first, then legacy fallback.
- See `runtime/skill_resolver.py`.

### 4.2 Source-of-truth generation chain

```text
runtime/builtin_skill_packages/*/skill.yaml
  -> normalize/validate
  -> scripts/generate-builtin-catalog.py
  -> runtime/builtin_catalog.generated.json
  -> runtime/builtin_catalog.py (generated artifact preferred)
```

`builtin_catalog.generated.json` is generated and should not be hand-edited.

### 4.3 Fail-closed rules

1. Invalid `skill.yaml`: registry skips the skill.
2. `host_support` mismatch: registry skips or rejects execution of the skill.
3. Invalid runtime `permission_mode`: execution fails fast.
4. `tools / disallowed_tools / allowed_paths / requires_network` are not runtime-enforced yet and must not be documented as if they were.
5. Implemented permission boundaries must never be silently widened.

## 5. `SKILL.md` Entry Template

Recommended sections:

1. Activation conditions
2. Execution skeleton (3-6 steps)
3. Resource navigation (`references/assets/scripts`)
4. Deterministic script entry examples
5. Explicit non-goals / boundaries

Pilot references:

- `Codex/Skills/CN/skills/sopify/analyze/`
- `Codex/Skills/CN/skills/sopify/design/`
- `Codex/Skills/CN/skills/sopify/develop/`
- `Codex/Skills/EN/skills/sopify/analyze/`
- `Codex/Skills/EN/skills/sopify/design/`
- `Codex/Skills/EN/skills/sopify/develop/`

## 6. Maintainer Workflow

1. Edit prompt-layer source files in `Codex/Skills/{CN,EN}`.
2. Edit builtin machine metadata in `runtime/builtin_skill_packages/*/skill.yaml`.
3. Mirror to Claude: `bash scripts/sync-skills.sh`.
4. Check mirror consistency: `bash scripts/check-skills-sync.sh`.
5. Check version consistency: `bash scripts/check-version-consistency.sh`.
6. Regenerate catalog: `python3 scripts/generate-builtin-catalog.py`.
7. Run skill eval gate: `python3 scripts/check-skill-eval-gate.py`.
8. Run runtime tests: `python3 -m unittest tests.test_runtime -v`.

## 7. Pre-merge Checklist

- [ ] `SKILL.md` is entry-only
- [ ] Long rules moved to `references/`
- [ ] Templates moved to `assets/`
- [ ] Deterministic logic moved to `scripts/`
- [ ] `skill.yaml` passes schema checks
- [ ] Catalog artifact regenerated
- [ ] sync + check + eval + tests passed

## 8. Closure Traceability (5.4)

For the `skill standards refactor`, the durable closure artifacts are:

1. Closure blueprint: `../.sopify-skills/blueprint/skill-standards-refactor.md`
2. Eval baseline: `../evals/skill_eval_baseline.json`
3. Eval SLO: `../evals/skill_eval_slo.json`
