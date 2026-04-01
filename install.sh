#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="sopify-ai"
REPO_NAME="sopify"
ASSET_NAME="install.sh"
SOURCE_CHANNEL="dev"
SOURCE_REF="main"

usage() {
  cat <<'EOF'
Usage: install.sh [--target <host:lang>] [--ref <tag-or-branch>]

Thin Sopify installer entrypoint.

Options:
  --target <host:lang>   Install target. Required in non-interactive mode.
  --ref <tag-or-branch>  Optional source override. Expert / maintainer use only.
  --workspace <path>     Internal-only project prewarm path. Default user flow bootstraps on first project trigger.
  -h, --help             Show this help message.
EOF
}

fail() {
  local phase="$1"
  local reason_code="$2"
  local detail="$3"
  local next_step="$4"
  {
    echo "Sopify install failed:"
    echo "  phase: $phase"
    echo "  reason_code: $reason_code"
    echo "  detail: $detail"
    echo "  next_step: $next_step"
  } >&2
  exit 1
}

require_command() {
  local command_name="$1"
  local reason_code="$2"
  local next_step="$3"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "preflight" "$reason_code" "Missing required command: $command_name" "$next_step"
  fi
}

FORWARDED_ARGS=()
REF_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --ref)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        fail "input" "MISSING_REF_VALUE" '`--ref` requires a value.' "Pass --ref <tag-or-branch>, or omit the flag."
      fi
      REF_OVERRIDE="$2"
      FORWARDED_ARGS+=("$1" "$2")
      shift 2
      ;;
    --ref=*)
      REF_OVERRIDE="${1#*=}"
      if [[ -z "$REF_OVERRIDE" ]]; then
        fail "input" "MISSING_REF_VALUE" '`--ref` requires a value.' "Pass --ref <tag-or-branch>, or omit the flag."
      fi
      FORWARDED_ARGS+=("$1")
      shift
      ;;
    *)
      FORWARDED_ARGS+=("$1")
      shift
      ;;
  esac
done

RESOLVED_REF="${REF_OVERRIDE:-$SOURCE_REF}"
if [[ -z "$RESOLVED_REF" ]]; then
  fail "input" "MISSING_SOURCE_REF" "No source ref was resolved for the installer." "Retry with --ref <tag-or-branch>, or inspect the release asset rendering."
fi

require_command "curl" "MISSING_CURL" "Install curl, or use the inspect-first flow to download the release asset manually."
require_command "tar" "MISSING_TAR" "Install tar, or use a machine with basic archive support."
require_command "python3" "MISSING_PYTHON3" "Install python3, then rerun the installer."

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sopify-install.XXXXXX")"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ARCHIVE_URL="https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/${RESOLVED_REF}"
ARCHIVE_PATH="$TMP_DIR/source.tar.gz"

if ! curl -fsSL "$ARCHIVE_URL" -o "$ARCHIVE_PATH"; then
  fail "download" "SOURCE_FETCH_FAILED" "Failed to download source archive: $ARCHIVE_URL" "Check network access, verify the ref exists, or use the inspect-first path."
fi

if ! tar -xzf "$ARCHIVE_PATH" -C "$TMP_DIR"; then
  fail "unpack" "SOURCE_EXTRACT_FAILED" "Failed to extract source archive: $ARCHIVE_PATH" "Retry the installer or inspect the downloaded archive locally."
fi

SOURCE_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [[ -z "$SOURCE_DIR" || ! -d "$SOURCE_DIR" ]]; then
  fail "unpack" "SOURCE_ROOT_MISSING" "The extracted source archive did not contain a repository root directory." "Retry the installer or inspect the downloaded archive locally."
fi

ENTRYPOINT="$SOURCE_DIR/scripts/install_sopify.py"
if [[ ! -f "$ENTRYPOINT" ]]; then
  fail "unpack" "INSTALL_ENTRYPOINT_MISSING" "Missing install entrypoint inside source archive: $ENTRYPOINT" "Retry the installer or inspect the downloaded archive locally."
fi

python3 "$ENTRYPOINT" \
  --source-channel "$SOURCE_CHANNEL" \
  --source-resolved-ref "$RESOLVED_REF" \
  --source-asset-name "$ASSET_NAME" \
  "${FORWARDED_ARGS[@]}"
exit $?
