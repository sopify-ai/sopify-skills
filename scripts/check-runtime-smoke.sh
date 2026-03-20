#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/check-runtime-smoke.sh

Run a minimal zero-config smoke test against the current Sopify runtime bundle.
This script works both in the repository root and inside a vendored .sopify-runtime/ bundle.
It validates bundle/runtime asset integrity, not first-hop host ingress ordering.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

RUNTIME_ENTRY="$BUNDLE_ROOT/scripts/sopify_runtime.py"
if [[ ! -f "$RUNTIME_ENTRY" ]]; then
  echo "Missing runtime entry: $RUNTIME_ENTRY" >&2
  exit 1
fi
RUNTIME_GATE_ENTRY="$BUNDLE_ROOT/scripts/runtime_gate.py"
if [[ ! -f "$RUNTIME_GATE_ENTRY" ]]; then
  echo "Missing runtime gate entry: $RUNTIME_GATE_ENTRY" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sopify-runtime-smoke.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

MANIFEST_FILE="$BUNDLE_ROOT/manifest.json"
if [[ ! -f "$MANIFEST_FILE" ]]; then
  # The source repository does not commit a root manifest.json; generate a
  # transient manifest so the same smoke script can validate both layouts.
  if [[ -f "$BUNDLE_ROOT/runtime/manifest.py" ]]; then
    MANIFEST_FILE="$WORK_DIR/generated-manifest.json"
    PYTHONPATH="$BUNDLE_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
      python3 -m runtime.manifest \
        --source-root "$BUNDLE_ROOT" \
        --bundle-root "$BUNDLE_ROOT" \
        --output "$MANIFEST_FILE" >/dev/null
  else
    echo "Missing bundle manifest: $MANIFEST_FILE" >&2
    exit 1
  fi
fi

# This smoke intentionally checks bundle completeness plus repo-local runtime
# behavior. Gate-first host ordering belongs to future host-bridge smoke.
OUTPUT="$(
  python3 "$RUNTIME_ENTRY" \
    --workspace-root "$WORK_DIR" \
    --no-color \
    "重构数据库层"
)"
GATE_OUTPUT="$(
  python3 "$RUNTIME_GATE_ENTRY" \
    enter \
    --workspace-root "$WORK_DIR" \
    --request "重构数据库层"
)"

PLAN_DIR="$WORK_DIR/.sopify-skills/plan"
STATE_FILE="$WORK_DIR/.sopify-skills/state/current_plan.json"
HANDOFF_FILE="$WORK_DIR/.sopify-skills/state/current_handoff.json"
GATE_RECEIPT_FILE="$WORK_DIR/.sopify-skills/state/current_gate_receipt.json"
CLARIFICATION_BRIDGE_ENTRY="$BUNDLE_ROOT/scripts/clarification_bridge_runtime.py"
DECISION_BRIDGE_ENTRY="$BUNDLE_ROOT/scripts/decision_bridge_runtime.py"
DEVELOP_CHECKPOINT_ENTRY="$BUNDLE_ROOT/scripts/develop_checkpoint_runtime.py"
REPLAY_DIR="$WORK_DIR/.sopify-skills/replay/sessions"
PROJECT_FILE="$WORK_DIR/.sopify-skills/project.md"
OVERVIEW_FILE="$WORK_DIR/.sopify-skills/wiki/overview.md"
PREFERENCES_FILE="$WORK_DIR/.sopify-skills/user/preferences.md"
HISTORY_INDEX="$WORK_DIR/.sopify-skills/history/index.md"

if [[ ! -d "$PLAN_DIR" ]]; then
  echo "Smoke check failed: missing plan directory: $PLAN_DIR" >&2
  exit 1
fi

if [[ ! -f "$STATE_FILE" ]]; then
  echo "Smoke check failed: missing state file: $STATE_FILE" >&2
  exit 1
fi

if [[ ! -f "$HANDOFF_FILE" ]]; then
  echo "Smoke check failed: missing handoff file: $HANDOFF_FILE" >&2
  exit 1
fi

if [[ ! -f "$GATE_RECEIPT_FILE" ]]; then
  echo "Smoke check failed: missing runtime gate receipt: $GATE_RECEIPT_FILE" >&2
  exit 1
fi

if ! grep -q '"entry_guard"' "$HANDOFF_FILE"; then
  echo "Smoke check failed: handoff is missing entry_guard contract: $HANDOFF_FILE" >&2
  exit 1
fi

if [[ ! -f "$CLARIFICATION_BRIDGE_ENTRY" ]]; then
  echo "Smoke check failed: missing clarification bridge helper: $CLARIFICATION_BRIDGE_ENTRY" >&2
  exit 1
fi

if [[ ! -f "$DECISION_BRIDGE_ENTRY" ]]; then
  echo "Smoke check failed: missing decision bridge helper: $DECISION_BRIDGE_ENTRY" >&2
  exit 1
fi

if [[ ! -f "$DEVELOP_CHECKPOINT_ENTRY" ]]; then
  echo "Smoke check failed: missing develop checkpoint helper: $DEVELOP_CHECKPOINT_ENTRY" >&2
  exit 1
fi

if [[ ! -d "$REPLAY_DIR" ]]; then
  echo "Smoke check failed: missing replay directory: $REPLAY_DIR" >&2
  exit 1
fi

for file in "$PROJECT_FILE" "$OVERVIEW_FILE" "$PREFERENCES_FILE" "$HISTORY_INDEX"; do
  if [[ ! -f "$file" ]]; then
    echo "Smoke check failed: missing KB bootstrap file: $file" >&2
    exit 1
  fi
done

if ! grep -q '"runtime_entry_guard": true' "$MANIFEST_FILE"; then
  echo "Smoke check failed: manifest is missing runtime_entry_guard capability: $MANIFEST_FILE" >&2
  exit 1
fi

if ! grep -q '"runtime_gate": true' "$MANIFEST_FILE"; then
  echo "Smoke check failed: manifest is missing runtime_gate capability: $MANIFEST_FILE" >&2
  exit 1
fi

if ! grep -q '"entry_guard"' "$MANIFEST_FILE"; then
  echo "Smoke check failed: manifest is missing limits.entry_guard contract: $MANIFEST_FILE" >&2
  exit 1
fi

if ! grep -q '"runtime_gate_entry": "scripts/runtime_gate.py"' "$MANIFEST_FILE"; then
  echo "Smoke check failed: manifest is missing limits.runtime_gate_entry: $MANIFEST_FILE" >&2
  exit 1
fi

if [[ "$OUTPUT" != *".sopify-skills/plan/"* ]]; then
  echo "Smoke check failed: runtime output did not include the plan path." >&2
  printf '%s\n' "$OUTPUT" >&2
  exit 1
fi

if [[ "$OUTPUT" != *".sopify-skills/project.md"* ]]; then
  echo "Smoke check failed: runtime output did not include KB bootstrap changes." >&2
  printf '%s\n' "$OUTPUT" >&2
  exit 1
fi

if [[ "$GATE_OUTPUT" != *'"status": "ready"'* ]]; then
  echo "Smoke check failed: runtime gate did not return ready status." >&2
  printf '%s\n' "$GATE_OUTPUT" >&2
  exit 1
fi

if [[ "$GATE_OUTPUT" != *'"gate_passed": true'* ]]; then
  echo "Smoke check failed: runtime gate did not pass." >&2
  printf '%s\n' "$GATE_OUTPUT" >&2
  exit 1
fi

if [[ "$GATE_OUTPUT" != *'"allowed_response_mode": "normal_runtime_followup"'* ]]; then
  echo "Smoke check failed: runtime gate returned unexpected response mode." >&2
  printf '%s\n' "$GATE_OUTPUT" >&2
  exit 1
fi

echo "Runtime smoke check passed:"
echo "  bundle root: $BUNDLE_ROOT"
echo "  manifest:    $MANIFEST_FILE"
echo "  handoff:     $HANDOFF_FILE"
echo "  gate receipt:$GATE_RECEIPT_FILE"
echo "  workspace:   $WORK_DIR"
