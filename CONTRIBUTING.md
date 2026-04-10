# Contributing

Thanks for your interest in contributing to Sopify.

## How to contribute

- Open an issue first for non-trivial changes so scope and ownership are clear.
- Keep pull requests focused; one feature or fix per PR is preferred.
- Update both `README.md` and `README.zh-CN.md` when user-facing behavior changes.
- Update `CHANGELOG.md` manually when user-visible behavior or maintainer rules change.

## Prompt-layer and Skill Authoring

- `Codex/Skills/{CN,EN}` is the prompt-layer source of truth.
- `Claude/Skills/{CN,EN}` is the mirrored host layer and should be synced, not hand-maintained independently.
- `runtime/builtin_skill_packages/*/skill.yaml` is the source of truth for builtin machine metadata.
- For skill package changes, follow the `SKILL.md` files under [Codex/Skills/CN/skills/sopify/](./Codex/Skills/CN/skills/sopify/) / [Codex/Skills/EN/skills/sopify/](./Codex/Skills/EN/skills/sopify/).

Key constraints:

- Prefer `supports_routes` for route binding.
- Validate `skill.yaml` through `runtime/skill_schema.py`.
- `tools / disallowed_tools / allowed_paths / requires_network` are currently declarative fields unless runtime explicitly enforces them.
- Regenerate the builtin catalog instead of editing generated metadata manually.

## Runtime Bundle and Host Integration

Use these commands when you need maintainer-level control over the vendored runtime bundle:

```bash
# Sync runtime assets into a target workspace
bash scripts/sync-runtime-assets.sh /path/to/project

# Validate the raw input entry in the target workspace
python3 /path/to/project/.sopify-runtime/scripts/sopify_runtime.py \
  --workspace-root /path/to/project "Refactor the database layer"

# Optional: portable smoke checks in the target workspace
python3 -m unittest discover \
  -s /path/to/project/.sopify-runtime/tests \
  -p 'test_runtime.py' -v
bash /path/to/project/.sopify-runtime/scripts/check-runtime-smoke.sh
```

Bundle rules:

- The global payload lives under `~/.codex/sopify/` or `~/.claude/sopify/`.
- Hosts must read `.sopify-runtime/manifest.json` before falling back to fixed helper paths.
- The first host hop goes through `.sopify-runtime/scripts/runtime_gate.py enter`.
- Clarification, decision, and develop checkpoint helpers are internal bridge helpers, not replacement main entries.

### Installer Entry Points and Release Assets

Current installer entry points are intentionally split by audience:

- Repo-local / source install:

```bash
bash scripts/install-sopify.sh --target codex:zh-CN
python3 scripts/install_sopify.py --target claude:en-US --workspace /path/to/project
```

- Dev / maintainer remote entry (`raw/main`, not for README first screen):

```bash
curl -fsSL https://raw.githubusercontent.com/sopify-ai/sopify/main/install.sh | \
  bash -s -- --target codex:zh-CN
```

- Public stable entry (only after a public GitHub Release exists):

```bash
curl -fsSL https://github.com/sopify-ai/sopify/releases/latest/download/install.sh | \
  bash -s -- --target codex:zh-CN
```

Contract:

- Root `install.sh` / `install.ps1` stay thin. They only fetch the same-ref GitHub source archive and call `scripts/install_sopify.py`.
- `main` branch root scripts keep dev defaults (`SOURCE_CHANNEL=dev`, `SOURCE_REF=main`).
- Stable release assets are rendered from the root scripts for the selected release tag; do not hand-edit or upload the raw `main` files.
- Distribution logic stays host-registry driven. README may keep the current supported host surface, but the installer entrypoint must not hardcode `codex` / `claude` branching.

Release asset checklist:

```bash
TAG="2026-03-25.142231"
OUT_DIR="$(mktemp -d)"
python3 scripts/render-release-installers.py --release-tag "$TAG" --output-dir "$OUT_DIR"
```

Then:

- Upload `$OUT_DIR/install.sh` and `$OUT_DIR/install.ps1` to the GitHub Release with the same tag.
- Keep `README` first-screen install commands unchanged until that public stable release is visible at `releases/latest/download/install.sh`.
- Post-release manual smoke is maintainer-only: confirm the latest release assets exist, the stable installer resolves the same tag, and the install output prints `source channel`, `resolved source ref`, and `asset name`.

## Validation Commands

Run the minimum checks that match your change scope.

Prompt-layer and metadata sync:

```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
python3 scripts/generate-builtin-catalog.py
python3 scripts/check-skill-eval-gate.py
python3 -m unittest discover tests -v
```

Repo-local runtime validation:

```bash
python3 scripts/sopify_runtime.py "Refactor the database layer"
python3 scripts/runtime_gate.py enter --workspace-root . --request "Refactor the database layer"
python3 scripts/sopify_runtime.py "~go plan Refactor the database layer"
python3 scripts/sopify_runtime.py "~go finalize"
python3 scripts/go_plan_runtime.py "Refactor the database layer"
bash scripts/check-runtime-smoke.sh
```

Documentation and release validation:

```bash
python3 scripts/check-readme-links.py
python3 -m unittest tests/test_release_hooks.py -v
python3 -m unittest tests/test_distribution.py tests/test_installer_status_doctor.py -v
bash scripts/check-version-consistency.sh
```

## Release Hook and CHANGELOG

This repository ships coordinated `.githooks/pre-commit` and `commit-msg` automation.

Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

Behavior summary:

- `pre-commit` runs `scripts/release-preflight.sh` and then `scripts/release-sync.sh`.
- Release-managed files are re-staged into the same commit when checks pass.
- When `CHANGELOG.md -> [Unreleased]` is empty, `release-sync` auto-drafts grouped notes from the current staged files.
- `commit-msg` only appends `Release-Sync`, `Release-Version`, and `Release-Date` when the pre-commit handoff exists.
- Plan A scoped commits must include `Context-Checkpoint: A|B|C|D`; the hook only enforces this when staged files touch Plan A runtime/test surfaces or the checkpoint governance assets themselves.
- Scoped Plan A pull requests must keep `Context-Checkpoint`, `Decision IDs`, `Blocked by`, and `Out-of-scope touched` filled in `.github/pull_request_template.md`; CI validates the template plus PR body metadata on matching diffs.

AI attribution:

- AI collaboration is acknowledged at the repository level in [CONTRIBUTORS.md](./CONTRIBUTORS.md).
- The repository no longer appends standard `Co-authored-by` trailers for AI assistants by default, so GitHub contributor attribution remains tied to human commit authors unless you add co-author trailers manually.
- `SOPIFY_DISABLE_RELEASE_HOOK=1` disables the entire release hook chain; use it only for maintainer/debug flows.

Common environment toggles:

- `SOPIFY_DISABLE_RELEASE_HOOK=1`
- `SOPIFY_SKIP_RELEASE_PREFLIGHT=1`
- `SOPIFY_AUTO_DRAFT_CHANGELOG=0`
- `SOPIFY_RELEASE_HOOK_DRY_RUN=1`
- `SOPIFY_FORCE_RELEASE_SYNC=1`

## License Note

By contributing, you agree that your changes may be distributed under the license that applies to the files you modify:

- Code and config: Apache 2.0
- Documentation: CC BY 4.0
