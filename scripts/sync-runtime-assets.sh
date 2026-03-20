#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/sync-runtime-assets.sh <target-root> [bundle-dir]

Sync the minimal Sopify runtime bundle into another repository:
  - runtime/ -> <bundle-dir>/runtime/
  - selected runtime entry scripts -> <bundle-dir>/scripts/
  - portable runtime tests -> <bundle-dir>/tests/

Arguments:
  <target-root>   target repository root, must already exist
  [bundle-dir]    bundle path under the target root
                  default: .sopify-runtime

Examples:
  bash scripts/sync-runtime-assets.sh /path/to/project
  bash scripts/sync-runtime-assets.sh /path/to/project tools/sopify-runtime
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

if [[ ! -d "$1" ]]; then
  echo "Target root does not exist: $1" >&2
  exit 1
fi
TARGET_ROOT="$(cd "$1" && pwd)"

BUNDLE_ARG="${2:-.sopify-runtime}"
if [[ "$BUNDLE_ARG" = /* ]]; then
  BUNDLE_DIR="$BUNDLE_ARG"
else
  BUNDLE_DIR="$TARGET_ROOT/$BUNDLE_ARG"
fi

RUNTIME_SRC="$ROOT_DIR/runtime"
SCRIPTS_SRC="$ROOT_DIR/scripts"
TESTS_SRC="$ROOT_DIR/tests"

required_paths=(
  "$RUNTIME_SRC"
  "$SCRIPTS_SRC/sopify_runtime.py"
  "$SCRIPTS_SRC/runtime_gate.py"
  "$SCRIPTS_SRC/go_plan_runtime.py"
  "$SCRIPTS_SRC/clarification_bridge_runtime.py"
  "$SCRIPTS_SRC/develop_checkpoint_runtime.py"
  "$SCRIPTS_SRC/decision_bridge_runtime.py"
  "$SCRIPTS_SRC/preferences_preload_runtime.py"
  "$SCRIPTS_SRC/model_compare_runtime.py"
  "$SCRIPTS_SRC/check-runtime-smoke.sh"
  "$SCRIPTS_SRC/sync-runtime-assets.sh"
  "$TESTS_SRC/test_runtime.py"
)

for path in "${required_paths[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "Missing required source asset: $path" >&2
    exit 1
  fi
done

mkdir -p "$BUNDLE_DIR"

rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' "$RUNTIME_SRC/" "$BUNDLE_DIR/runtime/"

mkdir -p "$BUNDLE_DIR/scripts" "$BUNDLE_DIR/tests"
rsync -a --delete --prune-empty-dirs \
  --include='sopify_runtime.py' \
  --include='runtime_gate.py' \
  --include='go_plan_runtime.py' \
  --include='clarification_bridge_runtime.py' \
  --include='develop_checkpoint_runtime.py' \
  --include='decision_bridge_runtime.py' \
  --include='preferences_preload_runtime.py' \
  --include='model_compare_runtime.py' \
  --include='check-runtime-smoke.sh' \
  --include='sync-runtime-assets.sh' \
  --exclude='*' \
  "$SCRIPTS_SRC/" "$BUNDLE_DIR/scripts/"

rsync -a --delete --prune-empty-dirs \
  --include='test_runtime.py' \
  --exclude='*' \
  "$TESTS_SRC/" "$BUNDLE_DIR/tests/"

# Generate the self-describing manifest after runtime assets have been copied into the bundle root.
PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m runtime.manifest \
    --source-root "$ROOT_DIR" \
    --bundle-root "$BUNDLE_DIR" \
    --output "$BUNDLE_DIR/manifest.json" >/dev/null

chmod +x \
  "$BUNDLE_DIR/scripts/sopify_runtime.py" \
  "$BUNDLE_DIR/scripts/runtime_gate.py" \
  "$BUNDLE_DIR/scripts/go_plan_runtime.py" \
  "$BUNDLE_DIR/scripts/clarification_bridge_runtime.py" \
  "$BUNDLE_DIR/scripts/develop_checkpoint_runtime.py" \
  "$BUNDLE_DIR/scripts/decision_bridge_runtime.py" \
  "$BUNDLE_DIR/scripts/preferences_preload_runtime.py" \
  "$BUNDLE_DIR/scripts/model_compare_runtime.py" \
  "$BUNDLE_DIR/scripts/check-runtime-smoke.sh" \
  "$BUNDLE_DIR/scripts/sync-runtime-assets.sh"

cat <<EOF
Synced Sopify runtime bundle:
  target root: $TARGET_ROOT
  bundle dir:  $BUNDLE_DIR
  manifest:    $BUNDLE_DIR/manifest.json

Launch examples:
  python3 $BUNDLE_DIR/scripts/sopify_runtime.py --workspace-root $TARGET_ROOT "重构数据库层"
  python3 $BUNDLE_DIR/scripts/runtime_gate.py enter --workspace-root $TARGET_ROOT --request "重构数据库层"
  python3 $BUNDLE_DIR/scripts/go_plan_runtime.py --workspace-root $TARGET_ROOT "重构数据库层"
  python3 -m unittest $BUNDLE_DIR/tests/test_runtime.py
  bash $BUNDLE_DIR/scripts/check-runtime-smoke.sh
EOF
