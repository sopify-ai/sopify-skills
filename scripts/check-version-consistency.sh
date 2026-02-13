#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

README_CN="$ROOT_DIR/README.md"
README_EN="$ROOT_DIR/README_EN.md"
CHANGELOG="$ROOT_DIR/CHANGELOG.md"
CODEX_CN="$ROOT_DIR/Codex/Skills/CN/AGENTS.md"
CODEX_EN="$ROOT_DIR/Codex/Skills/EN/AGENTS.md"
CLAUDE_CN="$ROOT_DIR/Claude/Skills/CN/CLAUDE.md"
CLAUDE_EN="$ROOT_DIR/Claude/Skills/EN/CLAUDE.md"

usage() {
  cat <<'EOF'
Usage: scripts/check-version-consistency.sh

Validate version consistency across:
  - README.md / README_EN.md version badges
  - Latest released version in CHANGELOG.md
  - SOPIFY_VERSION headers in Codex/Claude CN/EN files

Exit codes:
  0: all checks passed
  1: one or more mismatches found
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

required_files=(
  "$README_CN"
  "$README_EN"
  "$CHANGELOG"
  "$CODEX_CN"
  "$CODEX_EN"
  "$CLAUDE_CN"
  "$CLAUDE_EN"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "Missing required file: $file" >&2
    exit 1
  fi
done

errors=()

add_error() {
  errors+=("$1")
}

extract_badge_version() {
  local file="$1"
  local encoded

  encoded="$(sed -n 's#.*badge/version-\([^)]*\)-orange\.svg.*#\1#p' "$file" | head -n 1)"
  if [[ -z "$encoded" ]]; then
    return 1
  fi

  # shields.io uses double hyphens in badges to represent literal '-' characters
  echo "${encoded//--/-}"
}

extract_sopify_version() {
  local file="$1"
  sed -n 's/^<!-- SOPIFY_VERSION: \(.*\) -->$/\1/p' "$file" | head -n 1
}

extract_latest_release_line() {
  awk '
    /^## \[Unreleased\]$/ { after_unreleased=1; next }
    after_unreleased && /^## \[/ { print; exit }
  ' "$CHANGELOG"
}

parse_release_line() {
  local line="$1"
  local version=""
  local date=""
  local regex='^## \[([^]]+)\] - ([0-9]{4}-[0-9]{2}-[0-9]{2})$'

  if [[ "$line" =~ $regex ]]; then
    version="${BASH_REMATCH[1]}"
    date="${BASH_REMATCH[2]}"
    printf '%s\n%s\n' "$version" "$date"
    return 0
  fi

  return 1
}

readme_cn_version="$(extract_badge_version "$README_CN" || true)"
readme_en_version="$(extract_badge_version "$README_EN" || true)"

if [[ -z "$readme_cn_version" ]]; then
  add_error "README.md: failed to parse version badge."
fi

if [[ -z "$readme_en_version" ]]; then
  add_error "README_EN.md: failed to parse version badge."
fi

if [[ -n "$readme_cn_version" && -n "$readme_en_version" && "$readme_cn_version" != "$readme_en_version" ]]; then
  add_error "README badge mismatch: README.md=$readme_cn_version, README_EN.md=$readme_en_version."
fi

latest_release_line="$(extract_latest_release_line)"
if [[ -z "$latest_release_line" ]]; then
  add_error "CHANGELOG.md: missing released section after [Unreleased]."
else
  parsed_release="$(parse_release_line "$latest_release_line" || true)"
  if [[ -z "$parsed_release" ]]; then
    add_error "CHANGELOG.md: latest release line has invalid format: $latest_release_line"
  else
    changelog_version="$(echo "$parsed_release" | sed -n '1p')"
    changelog_date="$(echo "$parsed_release" | sed -n '2p')"
    release_count="$(awk -v header="## [$changelog_version] - " 'index($0, header) == 1 { c++ } END { print c + 0 }' "$CHANGELOG")"
    if [[ "$release_count" -ne 1 ]]; then
      add_error "CHANGELOG.md: version $changelog_version appears $release_count times (expected 1)."
    fi
  fi
fi

codex_cn_version="$(extract_sopify_version "$CODEX_CN")"
codex_en_version="$(extract_sopify_version "$CODEX_EN")"
claude_cn_version="$(extract_sopify_version "$CLAUDE_CN")"
claude_en_version="$(extract_sopify_version "$CLAUDE_EN")"

if [[ -z "$codex_cn_version" ]]; then
  add_error "Codex/Skills/CN/AGENTS.md: missing SOPIFY_VERSION header."
fi
if [[ -z "$codex_en_version" ]]; then
  add_error "Codex/Skills/EN/AGENTS.md: missing SOPIFY_VERSION header."
fi
if [[ -z "$claude_cn_version" ]]; then
  add_error "Claude/Skills/CN/CLAUDE.md: missing SOPIFY_VERSION header."
fi
if [[ -z "$claude_en_version" ]]; then
  add_error "Claude/Skills/EN/CLAUDE.md: missing SOPIFY_VERSION header."
fi

header_versions=("$codex_cn_version" "$codex_en_version" "$claude_cn_version" "$claude_en_version")
first_header_version="${header_versions[0]}"
for version in "${header_versions[@]}"; do
  if [[ -n "$version" && "$version" != "$first_header_version" ]]; then
    add_error "Header SOPIFY_VERSION mismatch: $codex_cn_version / $codex_en_version / $claude_cn_version / $claude_en_version."
    break
  fi
done

if [[ -n "${changelog_version:-}" && -n "$readme_cn_version" && "$changelog_version" != "$readme_cn_version" ]]; then
  add_error "Version mismatch: CHANGELOG latest=$changelog_version, README badge=$readme_cn_version."
fi

if [[ -n "${changelog_version:-}" && -n "$first_header_version" && "$changelog_version" != "$first_header_version" ]]; then
  add_error "Version mismatch: CHANGELOG latest=$changelog_version, SOPIFY_VERSION=$first_header_version."
fi

if [[ "${#errors[@]}" -gt 0 ]]; then
  echo "Version consistency check failed:"
  for err in "${errors[@]}"; do
    echo "  - $err"
  done
  exit 1
fi

echo "Version consistency check passed:"
echo "  - Version: ${changelog_version:-$first_header_version}"
echo "  - Date: ${changelog_date:-N/A}"
echo "  - README badge: $readme_cn_version"
echo "  - SOPIFY_VERSION: $first_header_version"
