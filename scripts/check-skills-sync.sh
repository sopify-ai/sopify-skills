#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sopify-sync-check.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

usage() {
  cat <<'EOF'
Usage: scripts/check-skills-sync.sh

Check whether Claude/* mirrors Codex/* for Sopify skills.
For header files, ~/.codex/sopify.config.yaml is expected to be rewritten as ~/.claude/sopify.config.yaml.
On mismatch, run:
  bash scripts/sync-skills.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

status=0

render_expected_claude_header() {
  local source_file="$1"
  local target_file="$2"
  sed 's#~/.codex/sopify\.config\.yaml#~/.claude/sopify.config.yaml#g' "$source_file" >"$target_file"
}

check_lang() {
  local lang="$1"
  local codex_dir="$ROOT_DIR/Codex/Skills/$lang"
  local claude_dir="$ROOT_DIR/Claude/Skills/$lang"
  local diff_file="$TMP_DIR/$lang.diff"

  render_expected_claude_header "$codex_dir/AGENTS.md" "$TMP_DIR/$lang.expected.md"

  if ! diff -u "$TMP_DIR/$lang.expected.md" "$claude_dir/CLAUDE.md" >"$diff_file"; then
    echo "[$lang] Header file mismatch: Codex/Skills/$lang/AGENTS.md != Claude/Skills/$lang/CLAUDE.md"
    head -n 40 "$diff_file"
    status=1
  fi

  if ! diff -ru "$codex_dir/skills/sopify" "$claude_dir/skills/sopify" >"$diff_file"; then
    echo "[$lang] Skill directory mismatch: Codex/Skills/$lang/skills/sopify != Claude/Skills/$lang/skills/sopify"
    head -n 60 "$diff_file"
    status=1
  fi
}

check_lang "CN"
check_lang "EN"

if [[ "$status" -ne 0 ]]; then
  echo
  echo "Sync check failed. Run: bash scripts/sync-skills.sh"
  exit 1
fi

echo "Sync check passed: Claude/* is aligned with Codex/*."
