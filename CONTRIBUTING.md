# Contributing

Thanks for your interest in contributing!

## How to contribute

- Please open an issue first for non-trivial changes so we can align on scope.
- Keep changes focused and easy to review (one feature/fix per PR when possible).
- Prefer updating both `README.md` and `README_EN.md` when user-facing behavior changes.
- Update `CHANGELOG.md` manually for user-facing/rule behavior changes.
- Use `Codex/Skills/{CN,EN}` as the source of truth. After edits, run `bash scripts/sync-skills.sh` then `bash scripts/check-skills-sync.sh`.
- Include the sync/check results in your PR description if you changed skills/rules.

## License note (informal)

This repository describes a dual-licensing intent:

- Code / configs: Apache-2.0 (see `LICENSE`)
- Documentation (mostly Markdown): CC BY 4.0 (see `LICENSE-docs`)

By submitting a contribution, you agree that your contribution can be distributed
under the license applicable to the files you change.

If you believe any attribution or licensing information is missing (for example,
because some content was adapted from other open-source projects), please open an
issue or include details in your PR.
