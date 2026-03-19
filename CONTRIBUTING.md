# Contributing

Thanks for your interest in contributing!

## How to contribute

- Please open an issue first for non-trivial changes so we can align on scope.
- Keep changes focused and easy to review (one feature/fix per PR when possible).
- Prefer updating both `README.md` and `README_EN.md` when user-facing behavior changes.
- Update `CHANGELOG.md` manually for user-facing/rule behavior changes.
- Use `Codex/Skills/{CN,EN}` as the prompt-layer source of truth, and `runtime/builtin_skill_packages/*/skill.yaml` as the builtin machine-metadata source of truth. After edits, run `bash scripts/sync-skills.sh`, `bash scripts/check-skills-sync.sh`, and `bash scripts/check-version-consistency.sh`.
- For skill package changes, follow [docs/skill-authoring.md](./docs/skill-authoring.md) / [docs/skill-authoring.en.md](./docs/skill-authoring.en.md), then run `python3 scripts/generate-builtin-catalog.py`, `python3 scripts/check-skill-eval-gate.py`, and `python3 -m unittest tests.test_runtime -v`.
- CI runs the same checks plus `git diff --exit-code`; include local results in your PR description if you changed skills/rules.

## Commit Hook Version Sync

- This repo ships a `commit-msg` hook at `.githooks/commit-msg`.
- Enable it once per clone:
  - `git config core.hooksPath .githooks`
- After that, every `git commit` checks the staged files and enters version-sync automation when release-relevant paths are touched (runtime/installer/release scripts/skills/readme/changelog).
- The commit path runs `scripts/release-preflight.sh` first, then `scripts/release-sync.sh` with a timestamp version in `Asia/Shanghai`:
  - Version format: `YYYY-MM-DD.HHMMSS`
  - Date used for changelog section: `YYYY-MM-DD`
- Version updates happen inside that commit path only after preflight passes; there is no separate manual release-hook workflow.
- Common env toggles:
  - `SOPIFY_DISABLE_RELEASE_HOOK=1`: disable hook behavior for one commit
  - `SOPIFY_SKIP_RELEASE_PREFLIGHT=1`: skip preflight checks (emergency only)
  - `SOPIFY_RELEASE_HOOK_DRY_RUN=1`: print what would happen without changing files
  - `SOPIFY_FORCE_RELEASE_SYNC=1`: force release-sync even when staged paths are not release-relevant

## License note (informal)

This repository describes a dual-licensing intent:

- Code / configs: Apache-2.0 (see `LICENSE`)
- Documentation (mostly Markdown): CC BY 4.0 (see `LICENSE-docs`)

By submitting a contribution, you agree that your contribution can be distributed
under the license applicable to the files you change.

If you believe any attribution or licensing information is missing (for example,
because some content was adapted from other open-source projects), please open an
issue or include details in your PR.
