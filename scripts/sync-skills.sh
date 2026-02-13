#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/sync-skills.sh

Sync Sopify skill content from Codex/* to Claude/*:
  - Codex/Skills/CN/AGENTS.md -> Claude/Skills/CN/CLAUDE.md
    (auto-rewrite ~/.codex/sopify.config.yaml -> ~/.claude/sopify.config.yaml)
  - Codex/Skills/EN/AGENTS.md -> Claude/Skills/EN/CLAUDE.md
    (auto-rewrite ~/.codex/sopify.config.yaml -> ~/.claude/sopify.config.yaml)
  - Codex/Skills/{CN,EN}/skills/sopify/* -> Claude/Skills/{CN,EN}/skills/sopify/*
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

render_claude_header() {
  local source_file="$1"
  local target_file="$2"

  sed 's#~/.codex/sopify\.config\.yaml#~/.claude/sopify.config.yaml#g' "$source_file" >"$target_file"
}

sync_lang() {
  local lang="$1"
  local codex_dir="$ROOT_DIR/Codex/Skills/$lang"
  local claude_dir="$ROOT_DIR/Claude/Skills/$lang"

  if [[ ! -f "$codex_dir/AGENTS.md" ]]; then
    echo "Missing source file: $codex_dir/AGENTS.md" >&2
    exit 1
  fi

  if [[ ! -f "$claude_dir/CLAUDE.md" ]]; then
    echo "Missing target file: $claude_dir/CLAUDE.md" >&2
    exit 1
  fi

  if [[ ! -d "$codex_dir/skills/sopify" ]]; then
    echo "Missing source directory: $codex_dir/skills/sopify" >&2
    exit 1
  fi

  if [[ ! -d "$claude_dir/skills/sopify" ]]; then
    echo "Missing target directory: $claude_dir/skills/sopify" >&2
    exit 1
  fi

  render_claude_header "$codex_dir/AGENTS.md" "$claude_dir/CLAUDE.md"
  rsync -a --delete "$codex_dir/skills/sopify/" "$claude_dir/skills/sopify/"
}

sync_lang "CN"
sync_lang "EN"

echo "Synced Codex -> Claude for CN and EN skill bundles."
