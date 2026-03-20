#!/usr/bin/env python3
"""Bootstrap or update a workspace-local `.sopify-runtime/` from the global payload.

This file is copied into the host-local Sopify payload as:
`<host-root>/sopify/helpers/bootstrap_workspace.py`.

The script is intentionally self-contained so it can run after installation
without importing modules from the source repository.
"""

from __future__ import annotations

import argparse
import json
from itertools import zip_longest
from pathlib import Path
import re
import shutil
import sys
from tempfile import NamedTemporaryFile
from typing import Any

PAYLOAD_MANIFEST_FILENAME = "payload-manifest.json"
_REQUIRED_BUNDLE_FILES = (
    Path("manifest.json"),
    Path("runtime") / "__init__.py",
    Path("runtime") / "clarification_bridge.py",
    Path("runtime") / "cli_interactive.py",
    Path("runtime") / "develop_checkpoint.py",
    Path("runtime") / "decision_bridge.py",
    Path("runtime") / "gate.py",
    Path("runtime") / "preferences.py",
    Path("runtime") / "workspace_preflight.py",
    Path("scripts") / "sopify_runtime.py",
    Path("scripts") / "runtime_gate.py",
    Path("scripts") / "clarification_bridge_runtime.py",
    Path("scripts") / "develop_checkpoint_runtime.py",
    Path("scripts") / "decision_bridge_runtime.py",
    Path("scripts") / "preferences_preload_runtime.py",
    Path("scripts") / "check-runtime-smoke.sh",
    Path("tests") / "test_runtime.py",
)
_IGNORE_PATTERNS = shutil.ignore_patterns(".DS_Store", "Thumbs.db", "__pycache__")
_VERSION_TOKEN_RE = re.compile(r"[0-9]+|[A-Za-z]+")
_PRERELEASE_RANK = {"dev": -4, "alpha": -3, "beta": -2, "rc": -1}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap a workspace-local Sopify runtime bundle.")
    parser.add_argument("--workspace-root", required=True, help="Target project root that should receive `.sopify-runtime/`.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = bootstrap_workspace(Path(args.workspace_root).expanduser().resolve())
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(
            json.dumps(
                {
                    "action": "failed",
                    "state": "INCOMPATIBLE",
                    "reason_code": "UNEXPECTED_ERROR",
                    "workspace_root": str(Path(args.workspace_root).expanduser().resolve()),
                    "bundle_root": str(Path(args.workspace_root).expanduser().resolve() / ".sopify-runtime"),
                    "from_version": None,
                    "to_version": None,
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["action"] != "failed" else 1


def bootstrap_workspace(workspace_root: Path) -> dict[str, Any]:
    if not workspace_root.exists():
        raise ValueError(f"Workspace does not exist: {workspace_root}")
    if not workspace_root.is_dir():
        raise ValueError(f"Workspace is not a directory: {workspace_root}")

    payload_root = Path(__file__).resolve().parents[1]
    payload_manifest_path = payload_root / PAYLOAD_MANIFEST_FILENAME
    payload_manifest = _read_json(payload_manifest_path)
    if not payload_manifest:
        raise ValueError(f"Missing or invalid payload manifest: {payload_manifest_path}")

    bundle_template_root = payload_root / str(payload_manifest.get("bundle_template_dir") or "bundle")
    bundle_manifest_path = bundle_template_root / "manifest.json"
    bundle_manifest = _read_json(bundle_manifest_path)
    if not bundle_manifest:
        raise ValueError(f"Missing or invalid bundle manifest: {bundle_manifest_path}")

    target_bundle_dir = str(payload_manifest.get("default_bundle_dir") or ".sopify-runtime")
    bundle_root = workspace_root / target_bundle_dir
    current_manifest_path = bundle_root / "manifest.json"
    current_manifest = _read_json(current_manifest_path) if current_manifest_path.is_file() else {}

    state, reason_code, message, from_version = _classify_workspace_bundle(
        current_manifest=current_manifest,
        payload_manifest=payload_manifest,
        bundle_manifest=bundle_manifest,
        current_manifest_path=current_manifest_path,
        bundle_root=bundle_root,
    )
    to_version = _string_or_none(bundle_manifest.get("bundle_version"))

    if state in {"READY", "NEWER_THAN_GLOBAL"}:
        return _result(
            action="skipped",
            state=state,
            reason_code=reason_code,
            workspace_root=workspace_root,
            bundle_root=bundle_root,
            from_version=from_version,
            to_version=to_version,
            message=message,
        )

    _sync_bundle(bundle_template_root=bundle_template_root, bundle_root=bundle_root)
    _validate_bundle(bundle_root)
    action = "bootstrapped" if state == "MISSING" else "updated"
    return _result(
        action=action,
        state=state,
        reason_code=reason_code,
        workspace_root=workspace_root,
        bundle_root=bundle_root,
        from_version=from_version,
        to_version=to_version,
        message=message,
    )


def _classify_workspace_bundle(
    *,
    current_manifest: dict[str, Any],
    payload_manifest: dict[str, Any],
    bundle_manifest: dict[str, Any],
    current_manifest_path: Path,
    bundle_root: Path,
) -> tuple[str, str, str, str | None]:
    if not current_manifest_path.is_file():
        return ("MISSING", "MISSING_BUNDLE", "Workspace bundle is missing and will be bootstrapped.", None)

    if not current_manifest:
        return (
            "INCOMPATIBLE",
            "INVALID_WORKSPACE_MANIFEST",
            "Workspace bundle manifest is unreadable and will be replaced.",
            None,
        )

    minimum_manifest = payload_manifest.get("minimum_workspace_manifest") or {}
    expected_schema = str(minimum_manifest.get("schema_version") or bundle_manifest.get("schema_version") or "1")
    workspace_schema = str(current_manifest.get("schema_version") or "")
    from_version = _string_or_none(current_manifest.get("bundle_version"))
    if workspace_schema != expected_schema:
        return (
            "INCOMPATIBLE",
            "SCHEMA_VERSION_MISMATCH",
            f"Workspace bundle schema {workspace_schema or '<missing>'} is incompatible with required schema {expected_schema}.",
            from_version,
        )

    required_capabilities = minimum_manifest.get("required_capabilities") or {}
    missing_paths = _find_missing_capabilities(required_capabilities, current_manifest.get("capabilities") or {})
    if missing_paths:
        return (
            "INCOMPATIBLE",
            "MISSING_REQUIRED_CAPABILITY",
            f"Workspace bundle is missing required capabilities: {', '.join(missing_paths)}.",
            from_version,
        )

    missing_files = _find_missing_required_files(bundle_root)
    if missing_files:
        return (
            "INCOMPATIBLE",
            "MISSING_REQUIRED_FILE",
            f"Workspace bundle is missing required files: {', '.join(missing_files)}.",
            from_version,
        )

    workspace_version = from_version
    desired_version = _string_or_none(bundle_manifest.get("bundle_version"))
    comparison = _compare_versions(workspace_version, desired_version)
    if comparison < 0:
        return (
            "OUTDATED_COMPATIBLE",
            "WORKSPACE_BUNDLE_OUTDATED",
            "Workspace bundle is compatible but older than the installed global payload and will be updated.",
            workspace_version,
        )
    if comparison > 0:
        return (
            "NEWER_THAN_GLOBAL",
            "WORKSPACE_BUNDLE_NEWER_THAN_GLOBAL",
            "Workspace bundle is newer than the installed global payload; bootstrap will not downgrade it.",
            workspace_version,
        )
    return (
        "READY",
        "WORKSPACE_BUNDLE_READY",
        "Workspace bundle is already compatible and up to date.",
        workspace_version,
    )


def _find_missing_capabilities(required: dict[str, Any], actual: dict[str, Any], prefix: str = "") -> list[str]:
    missing: list[str] = []
    for key, value in required.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            missing.append(path)
            continue
        actual_value = actual[key]
        if isinstance(value, dict):
            if not isinstance(actual_value, dict):
                missing.append(path)
                continue
            missing.extend(_find_missing_capabilities(value, actual_value, path))
            continue
        if actual_value != value:
            missing.append(path)
    return missing


def _find_missing_required_files(bundle_root: Path) -> list[str]:
    return [str(path) for path in _REQUIRED_BUNDLE_FILES if not (bundle_root / path).exists()]


def _sync_bundle(*, bundle_template_root: Path, bundle_root: Path) -> None:
    if not bundle_template_root.is_dir():
        raise ValueError(f"Missing payload bundle template: {bundle_template_root}")
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    bundle_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle_template_root, bundle_root, ignore=_IGNORE_PATTERNS)


def _validate_bundle(bundle_root: Path) -> None:
    missing = [path for path in _REQUIRED_BUNDLE_FILES if not (bundle_root / path).exists()]
    if missing:
        raise ValueError(f"Workspace bootstrap produced an incomplete bundle: {bundle_root / missing[0]}")
    # Re-write the manifest atomically to ensure the copied bundle did not pick up a partial file.
    manifest_path = bundle_root / "manifest.json"
    payload = _read_json(manifest_path)
    with NamedTemporaryFile("w", delete=False, dir=manifest_path.parent, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(manifest_path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _compare_versions(left: str | None, right: str | None) -> int:
    if left == right:
        return 0
    if left is None:
        return -1
    if right is None:
        return 1
    left_key = _version_key(left)
    right_key = _version_key(right)
    for left_part, right_part in zip_longest(left_key, right_key, fillvalue=None):
        if left_part == right_part:
            continue
        if left_part is None:
            return _tail_comparison(right_key, from_index=len(left_key), default=-1)
        if right_part is None:
            return -_tail_comparison(left_key, from_index=len(right_key), default=-1)
        if left_part < right_part:
            return -1
        return 1
    return 0


def _version_key(value: str) -> list[tuple[int, int | str]]:
    key: list[tuple[int, int | str]] = []
    for token in _VERSION_TOKEN_RE.findall(value):
        if token.isdigit():
            key.append((0, int(token)))
            continue
        normalized = token.lower()
        rank = _PRERELEASE_RANK.get(normalized)
        if rank is not None:
            key.append((1, rank))
        else:
            key.append((2, normalized))
    return key


def _tail_comparison(parts: list[tuple[int, int | str]], *, from_index: int, default: int) -> int:
    for kind, value in parts[from_index:]:
        if kind == 1 and isinstance(value, int) and value < 0:
            return 1
        return default
    return 0


def _result(
    *,
    action: str,
    state: str,
    reason_code: str,
    workspace_root: Path,
    bundle_root: Path,
    from_version: str | None,
    to_version: str | None,
    message: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "state": state,
        "reason_code": reason_code,
        "workspace_root": str(workspace_root),
        "bundle_root": str(bundle_root),
        "from_version": from_version,
        "to_version": to_version,
        "message": message,
    }


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
