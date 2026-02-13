#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

README_CN="$ROOT_DIR/README.md"
README_EN="$ROOT_DIR/README_EN.md"
CHANGELOG="$ROOT_DIR/CHANGELOG.md"
CODEX_CN="$ROOT_DIR/Codex/Skills/CN/AGENTS.md"
CODEX_EN="$ROOT_DIR/Codex/Skills/EN/AGENTS.md"

usage() {
  cat <<'EOF'
Usage: scripts/release-sync.sh <version> [date]

Synchronize release version across key files:
  1) README.md / README_EN.md version badge
  2) CHANGELOG.md:
     - move current [Unreleased] content into
       ## [<version>] - <date>
  3) Codex SOPIFY_VERSION headers (CN/EN)
  4) Sync Codex -> Claude and run consistency checks

Arguments:
  <version>   release version, e.g. 2026-02-13 or 2026-01-15.1
  [date]      optional release date in YYYY-MM-DD
              default: if <version> is YYYY-MM-DD, use it; else use today

Examples:
  bash scripts/release-sync.sh 2026-02-13
  bash scripts/release-sync.sh 2026-01-15.2 2026-02-13
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage >&2
  exit 1
fi

VERSION="$1"
RELEASE_DATE="${2:-}"

if [[ ! "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]]; then
  echo "Invalid version: $VERSION" >&2
  echo "Allowed characters: letters, numbers, dot, underscore, hyphen." >&2
  exit 1
fi

if [[ -z "$RELEASE_DATE" ]]; then
  if [[ "$VERSION" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    RELEASE_DATE="$VERSION"
  else
    RELEASE_DATE="$(date +%F)"
  fi
fi

if [[ ! "$RELEASE_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Invalid date: $RELEASE_DATE (expected YYYY-MM-DD)" >&2
  exit 1
fi

required_files=(
  "$README_CN"
  "$README_EN"
  "$CHANGELOG"
  "$CODEX_CN"
  "$CODEX_EN"
  "$ROOT_DIR/scripts/sync-skills.sh"
  "$ROOT_DIR/scripts/check-skills-sync.sh"
  "$ROOT_DIR/scripts/check-version-consistency.sh"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "Missing required file: $file" >&2
    exit 1
  fi
done

badge_version="${VERSION//-/--}"

replace_once() {
  local file="$1"
  local old_pattern="$2"
  local new_line="$3"
  local tmp_file

  tmp_file="$(mktemp "${TMPDIR:-/tmp}/release-sync.XXXXXX")"
  awk -v pattern="$old_pattern" -v replacement="$new_line" '
    BEGIN { c=0 }
    {
      if ($0 ~ pattern) {
        print replacement
        c++
      } else {
        print
      }
    }
    END {
      if (c != 1) {
        exit 2
      }
    }
  ' "$file" >"$tmp_file" || {
    rm -f "$tmp_file"
    echo "Failed to update $file: expected exactly one match for pattern [$old_pattern]." >&2
    exit 1
  }

  mv "$tmp_file" "$file"
}

count_matches() {
  local file="$1"
  local pattern="$2"
  awk -v pattern="$pattern" '
    $0 ~ pattern { c++ }
    END { print c + 0 }
  ' "$file"
}

require_single_match() {
  local file="$1"
  local pattern="$2"
  local label="$3"
  local count

  count="$(count_matches "$file" "$pattern")"
  if [[ "$count" -ne 1 ]]; then
    echo "$label: expected exactly 1 match in $file, got $count." >&2
    exit 1
  fi
}

update_readme_badge() {
  local file="$1"
  local tmp_file

  tmp_file="$(mktemp "${TMPDIR:-/tmp}/release-sync.XXXXXX")"
  awk -v badge="$badge_version" '
    BEGIN { c=0 }
    {
      line=$0
      if (line ~ /img\.shields\.io\/badge\/version-/ && line ~ /-orange\.svg/) {
        if (match(line, /badge\/version-[^)]*-orange\.svg/)) {
          prefix=substr(line, 1, RSTART-1)
          suffix=substr(line, RSTART + RLENGTH)
          print prefix "badge/version-" badge "-orange.svg" suffix
          c++
          next
        }
      }
      print line
    }
    END {
      if (c != 1) {
        exit 2
      }
    }
  ' "$file" >"$tmp_file" || {
    rm -f "$tmp_file"
    echo "Failed to update version badge in $file (expected exactly one badge)." >&2
    exit 1
  }

  mv "$tmp_file" "$file"
}

trim_blank_edges() {
  awk '
    { lines[NR] = $0 }
    END {
      start = 1
      while (start <= NR && lines[start] ~ /^[[:space:]]*$/) start++
      end = NR
      while (end >= start && lines[end] ~ /^[[:space:]]*$/) end--
      for (i = start; i <= end; i++) print lines[i]
    }
  '
}

promote_unreleased_to_release() {
  local file="$1"
  local unreleased_line
  local next_section_line
  local total_lines
  local unreleased_content
  local trimmed_content
  local tmp_file

  if grep -Fq "## [$VERSION] - " "$file"; then
    echo "CHANGELOG already contains version $VERSION." >&2
    exit 1
  fi

  unreleased_line="$(grep -n '^## \[Unreleased\]$' "$file" | head -n 1 | cut -d: -f1 || true)"
  if [[ -z "$unreleased_line" ]]; then
    echo "CHANGELOG.md is missing section: ## [Unreleased]" >&2
    exit 1
  fi

  next_section_line="$(awk -v start="$unreleased_line" 'NR > start && /^## \[/ { print NR; exit }' "$file")"
  total_lines="$(wc -l < "$file")"
  if [[ -z "$next_section_line" ]]; then
    next_section_line=$((total_lines + 1))
  fi

  if (( next_section_line <= unreleased_line + 1 )); then
    echo "No content found under [Unreleased]. Add release notes before running release-sync." >&2
    exit 1
  fi

  unreleased_content="$(sed -n "$((unreleased_line + 1)),$((next_section_line - 1))p" "$file")"
  trimmed_content="$(printf '%s\n' "$unreleased_content" | trim_blank_edges)"

  if [[ -z "$trimmed_content" ]]; then
    echo "No content found under [Unreleased]. Add release notes before running release-sync." >&2
    exit 1
  fi

  tmp_file="$(mktemp "${TMPDIR:-/tmp}/release-sync.XXXXXX")"
  head -n "$unreleased_line" "$file" >"$tmp_file"
  printf '\n## [%s] - %s\n\n' "$VERSION" "$RELEASE_DATE" >>"$tmp_file"
  printf '%s\n' "$trimmed_content" >>"$tmp_file"
  printf '\n' >>"$tmp_file"
  if (( next_section_line <= total_lines )); then
    tail -n "+$next_section_line" "$file" >>"$tmp_file"
  fi

  mv "$tmp_file" "$file"
}

echo "Starting release sync..."
echo "  - Version: $VERSION"
echo "  - Date: $RELEASE_DATE"

require_single_match "$README_CN" 'img\.shields\.io/badge/version-.*-orange\.svg' "README CN version badge"
require_single_match "$README_EN" 'img\.shields\.io/badge/version-.*-orange\.svg' "README EN version badge"
require_single_match "$CODEX_CN" '^<!-- SOPIFY_VERSION: .* -->$' "Codex CN SOPIFY_VERSION"
require_single_match "$CODEX_EN" '^<!-- SOPIFY_VERSION: .* -->$' "Codex EN SOPIFY_VERSION"

if grep -Fq "## [$VERSION] - " "$CHANGELOG"; then
  echo "CHANGELOG already contains version $VERSION." >&2
  exit 1
fi

update_readme_badge "$README_CN"
update_readme_badge "$README_EN"

promote_unreleased_to_release "$CHANGELOG"

replace_once "$CODEX_CN" '^<!-- SOPIFY_VERSION: .* -->$' "<!-- SOPIFY_VERSION: $VERSION -->"
replace_once "$CODEX_EN" '^<!-- SOPIFY_VERSION: .* -->$' "<!-- SOPIFY_VERSION: $VERSION -->"

bash "$ROOT_DIR/scripts/sync-skills.sh"
bash "$ROOT_DIR/scripts/check-skills-sync.sh"
bash "$ROOT_DIR/scripts/check-version-consistency.sh"

echo "Release sync completed successfully."
