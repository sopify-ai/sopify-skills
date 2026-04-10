#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/release-preflight.sh

Run release preflight checks before bumping Sopify version:
  1) Sync Codex -> Claude skills mirrors
  2) Verify mirrors and version consistency
  3) Run runtime unit tests + installer/runtime smoke checks
  4) Run skill eval quality gate
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

run_step() {
  local title="$1"
  shift
  echo "[release-preflight] $title"
  "$@"
}

check_builtin_catalog_drift() {
  local tmp
  tmp="$(mktemp)"
  python3 "$ROOT_DIR/scripts/generate-builtin-catalog.py" --output "$tmp" >/dev/null
  if ! python3 - "$ROOT_DIR/runtime/builtin_catalog.generated.json" "$tmp" <<'PY'; then
import difflib
import json
from pathlib import Path
import sys


def normalize(path_str: str) -> list[str]:
    payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
    payload.pop("generated_at", None)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).splitlines()


left_path, right_path = sys.argv[1], sys.argv[2]
left = normalize(left_path)
right = normalize(right_path)
if left != right:
    for line in difflib.unified_diff(left, right, fromfile=left_path, tofile=right_path, lineterm=""):
        print(line)
    raise SystemExit(1)
PY
    rm -f "$tmp"
    return 1
  fi
  rm -f "$tmp"
}

run_step "Sync skills" bash "$ROOT_DIR/scripts/sync-skills.sh"
run_step "Check skills sync" bash "$ROOT_DIR/scripts/check-skills-sync.sh"
run_step "Check version consistency" bash "$ROOT_DIR/scripts/check-version-consistency.sh"
run_step "Check builtin catalog drift" check_builtin_catalog_drift
run_step "Check fail-close contract" python3 "$ROOT_DIR/scripts/check-fail-close-contract.py"
run_step "Check context checkpoints" python3 "$ROOT_DIR/scripts/check-context-checkpoints.py" repo --root "$ROOT_DIR"
run_step "Run runtime unit tests" python3 -m unittest discover "$ROOT_DIR/tests" -v
run_step "Run install/payload bootstrap smoke" python3 "$ROOT_DIR/scripts/check-install-payload-bundle-smoke.py"
run_step "Run prompt runtime gate smoke" python3 "$ROOT_DIR/scripts/check-prompt-runtime-gate-smoke.py"
run_step "Run bundle runtime smoke check" bash "$ROOT_DIR/scripts/check-runtime-smoke.sh"

if [[ -f "$ROOT_DIR/scripts/check-skill-eval-gate.py" ]]; then
  run_step "Run skill eval quality gate" python3 "$ROOT_DIR/scripts/check-skill-eval-gate.py"
fi

echo "[release-preflight] All checks passed."
