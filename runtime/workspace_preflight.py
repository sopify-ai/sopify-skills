"""Shared workspace preflight/bootstrap helpers for Sopify host entries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


class WorkspacePreflightError(RuntimeError):
    """Raised when workspace runtime preflight cannot complete safely."""


def preflight_workspace_runtime(
    workspace_root: Path,
    *,
    payload_manifest_path: str | Path | None = None,
) -> Mapping[str, Any]:
    """Best-effort repo-local workspace preflight using the installed payload helper.

    The vendored bundle flow should already have been selected by the host via
    manifest-first preflight, so a bundle-local entry intentionally skips
    self-updating the workspace bundle it is currently executing from.
    """

    repo_root = Path(__file__).resolve().parents[1]
    bundle_root = workspace_root / ".sopify-runtime"
    if repo_root == bundle_root:
        return {
            "action": "skipped",
            "reason_code": "RUNNING_FROM_WORKSPACE_BUNDLE",
            "message": "Current entry is already running from the workspace bundle; host preflight remains authoritative.",
        }

    manifest_candidates: list[Path] = []
    if payload_manifest_path is not None:
        manifest_candidates.append(Path(payload_manifest_path).expanduser().resolve())
    env_manifest = (os.environ.get("SOPIFY_PAYLOAD_MANIFEST") or "").strip()
    if env_manifest:
        manifest_candidates.append(Path(env_manifest).expanduser().resolve())
    home = Path.home()
    manifest_candidates.extend(
        [
            home / ".codex" / "sopify" / "payload-manifest.json",
            home / ".claude" / "sopify" / "payload-manifest.json",
        ]
    )

    payload_manifest = None
    payload_manifest_file = None
    for candidate in manifest_candidates:
        if not candidate.is_file():
            continue
        try:
            payload_manifest = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkspacePreflightError(f"Invalid payload manifest: {candidate}") from exc
        if isinstance(payload_manifest, dict):
            payload_manifest_file = candidate
            break
    if payload_manifest is None or payload_manifest_file is None:
        return {
            "action": "skipped",
            "reason_code": "PAYLOAD_MANIFEST_NOT_FOUND",
            "message": "No installed host payload was found; continuing with repo-local entry.",
        }

    helper_entry = str(payload_manifest.get("helper_entry") or "").strip()
    if not helper_entry:
        raise WorkspacePreflightError(f"Payload manifest is missing helper_entry: {payload_manifest_file}")
    payload_root = payload_manifest_file.parent
    helper_path = (payload_root / helper_entry).resolve()
    if not helper_path.is_file():
        raise WorkspacePreflightError(f"Workspace bootstrap helper is missing: {helper_path}")

    completed = subprocess.run(
        [sys.executable, str(helper_path), "--workspace-root", str(workspace_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    try:
        result = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        detail = stdout or completed.stderr.strip()
        raise WorkspacePreflightError(f"Workspace bootstrap returned invalid JSON: {detail}") from exc

    if not isinstance(result, Mapping):
        raise WorkspacePreflightError("Workspace bootstrap returned a non-object JSON payload")

    if completed.returncode != 0 or str(result.get("action") or "").strip() == "failed":
        message = str(result.get("message") or completed.stderr.strip() or stdout or "unknown bootstrap failure")
        raise WorkspacePreflightError(f"Workspace preflight failed: {message}")
    return dict(result)


__all__ = ["WorkspacePreflightError", "preflight_workspace_runtime"]
