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
import os
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
_EXACT_BUNDLE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PRERELEASE_RANK = {"dev": -4, "alpha": -3, "beta": -2, "rc": -1}
_WORKSPACE_STUB_REQUIRED_CAPABILITIES = ("runtime_gate", "preferences_preload")
_WORKSPACE_STUB_LOCATOR_MODES = {"global_first", "global_only"}
_WORKSPACE_STUB_IGNORE_MODES = {"exclude", "gitignore", "noop"}
REASON_STUB_SELECTED = "STUB_SELECTED"
REASON_STUB_INVALID = "STUB_INVALID"
REASON_CONFIRM_BOOTSTRAP_REQUIRED = "CONFIRM_BOOTSTRAP_REQUIRED"
REASON_ROOT_CONFIRM_REQUIRED = "ROOT_CONFIRM_REQUIRED"
REASON_READONLY = "READONLY"
REASON_NON_INTERACTIVE = "NON_INTERACTIVE"
DIAGNOSTIC_NON_GIT_WORKSPACE = "NON_GIT_WORKSPACE"
DIAGNOSTIC_ROOT_REUSE_ANCESTOR_MARKER = "ROOT_REUSE_ANCESTOR_MARKER"
DIAGNOSTIC_INVALID_ANCESTOR_MARKER = "INVALID_ANCESTOR_MARKER"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap a workspace-local Sopify runtime bundle.")
    parser.add_argument("--workspace-root", required=True, help="Target project root that should receive `.sopify-runtime/`.")
    parser.add_argument("--activation-root", default=None, help="Optional explicit activation root override.")
    parser.add_argument("--request", default="", help="Raw user request routed through host ingress.")
    parser.add_argument("--requested-root", default=None, help="Optional host-requested root for observability.")
    parser.add_argument("--host-id", default=None, help="Optional host id for observability.")
    parser.add_argument(
        "--interaction-mode",
        choices=("interactive", "non_interactive"),
        default=None,
        help="Optional host-provided interaction mode for first-write policy.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = bootstrap_workspace(
            Path(args.workspace_root).expanduser().resolve(),
            activation_root=Path(args.activation_root).expanduser().resolve() if args.activation_root else None,
            request_text=args.request,
            requested_root=Path(args.requested_root).expanduser().resolve() if args.requested_root else None,
            host_id=args.host_id,
            interaction_mode=args.interaction_mode,
        )
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


def bootstrap_workspace(
    workspace_root: Path,
    *,
    activation_root: Path | None = None,
    request_text: str = "",
    requested_root: Path | None = None,
    host_id: str | None = None,
    interaction_mode: str | None = None,
) -> dict[str, Any]:
    if not workspace_root.exists():
        raise ValueError(f"Workspace does not exist: {workspace_root}")
    if not workspace_root.is_dir():
        raise ValueError(f"Workspace is not a directory: {workspace_root}")

    resolved_activation_root, root_resolution_source, fallback_reason = _resolve_activation_root(
        workspace_root=workspace_root,
        explicit_activation_root=activation_root,
    )
    requested_root = requested_root or workspace_root
    payload_root = Path(__file__).resolve().parents[1]
    payload_manifest_path = payload_root / PAYLOAD_MANIFEST_FILENAME
    payload_manifest = _read_json(payload_manifest_path)
    if not payload_manifest:
        raise ValueError(f"Missing or invalid payload manifest: {payload_manifest_path}")

    target_bundle_dir = str(payload_manifest.get("default_bundle_dir") or ".sopify-runtime")
    bundle_root = resolved_activation_root / target_bundle_dir
    current_manifest_path = bundle_root / "manifest.json"
    current_manifest = _read_json(current_manifest_path) if current_manifest_path.is_file() else {}
    (
        selected_bundle_root,
        bundle_manifest_path,
        bundle_manifest,
        global_reason_code,
        global_message,
    ) = _resolve_selected_payload_bundle(
        payload_root=payload_root,
        payload_manifest=payload_manifest,
        current_manifest=current_manifest,
    )
    if not bundle_manifest and bundle_manifest_path is None:
        raise ValueError("Workspace bootstrap could not resolve a global bundle contract")

    state, reason_code, message, from_version = _classify_workspace_bundle(
        current_manifest=current_manifest,
        payload_manifest=payload_manifest,
        bundle_manifest=bundle_manifest,
        current_manifest_path=current_manifest_path,
        bundle_root=bundle_root,
        global_bundle_root=selected_bundle_root,
        global_reason_code=global_reason_code,
        global_message=global_message,
    )
    to_version = _string_or_none(bundle_manifest.get("bundle_version"))
    current_ignore_mode = _default_ignore_mode(resolved_activation_root)
    if current_manifest_path.is_file() and current_manifest:
        try:
            normalized_manifest = _normalize_workspace_stub_contract(
                current_manifest=current_manifest,
                workspace_root=resolved_activation_root,
            )
        except ValueError:
            normalized_manifest = {}
        current_ignore_mode = str(normalized_manifest.get("ignore_mode") or current_ignore_mode)

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
            activation_root=resolved_activation_root,
            requested_root=requested_root,
            root_resolution_source=root_resolution_source,
            payload_root=payload_root,
            host_id=host_id,
            fallback_reason=fallback_reason,
            ignore_mode=current_ignore_mode,
        )

    write_authorization_mode = ""
    if state == "MISSING":
        authorization = _authorize_first_workspace_write(request_text)
        write_authorization_mode = str(authorization["mode"])
        if not authorization["allow_write"]:
            return _result(
                action="skipped",
                state=state,
                reason_code=str(authorization["reason_code"]),
                workspace_root=workspace_root,
                bundle_root=bundle_root,
                from_version=from_version,
                to_version=to_version,
                message=str(authorization["message"]),
                activation_root=resolved_activation_root,
                requested_root=requested_root,
                root_resolution_source=root_resolution_source,
                payload_root=payload_root,
                host_id=host_id,
                authorization_mode=write_authorization_mode,
                fallback_reason=fallback_reason,
                ignore_mode=current_ignore_mode,
            )
        write_barrier = _classify_first_write_barrier(
            workspace_root=workspace_root,
            activation_root=resolved_activation_root,
            explicit_activation_root=activation_root,
            bundle_root=bundle_root,
            root_resolution_source=root_resolution_source,
            fallback_reason=fallback_reason,
            interaction_mode=interaction_mode,
            ignore_mode=current_ignore_mode,
            authorization_mode=write_authorization_mode,
        )
        if write_barrier is not None:
            return _result(
                action="skipped",
                state=state,
                reason_code=str(write_barrier["reason_code"]),
                workspace_root=workspace_root,
                bundle_root=bundle_root,
                from_version=from_version,
                to_version=to_version,
                message=str(write_barrier["message"]),
                activation_root=resolved_activation_root,
                requested_root=requested_root,
                root_resolution_source=root_resolution_source,
                payload_root=payload_root,
                host_id=host_id,
                authorization_mode=write_authorization_mode,
                fallback_reason=fallback_reason,
                ignore_mode=current_ignore_mode,
                extra_evidence=tuple(str(item) for item in write_barrier.get("evidence") or ()),
                expose_activation_root=bool(write_barrier.get("expose_activation_root", True)),
                expose_ignore_mode=bool(write_barrier.get("expose_ignore_mode", True)),
            )

    if global_reason_code in {"GLOBAL_BUNDLE_MISSING", "GLOBAL_BUNDLE_INCOMPATIBLE", "GLOBAL_INDEX_CORRUPTED"}:
        return _result(
            action="failed",
            state="INCOMPATIBLE",
            reason_code=global_reason_code,
            workspace_root=workspace_root,
            bundle_root=bundle_root,
            from_version=from_version,
            to_version=to_version,
            message=global_message or message,
            activation_root=resolved_activation_root,
            requested_root=requested_root,
            root_resolution_source=root_resolution_source,
            payload_root=payload_root,
            host_id=host_id,
            fallback_reason=fallback_reason,
            ignore_mode=current_ignore_mode,
        )

    if selected_bundle_root is None:
        raise ValueError("Workspace bootstrap could not resolve a global bundle template")

    global_state, global_contract_reason_code, global_contract_message = _classify_global_bundle_contract(
        payload_manifest=payload_manifest,
        bundle_manifest=bundle_manifest,
        global_bundle_root=selected_bundle_root,
    )
    if global_state != "READY":
        return _result(
            action="failed",
            state="INCOMPATIBLE",
            reason_code=global_contract_reason_code,
            workspace_root=workspace_root,
            bundle_root=bundle_root,
            from_version=from_version,
            to_version=to_version,
            message=global_contract_message,
            activation_root=resolved_activation_root,
            requested_root=requested_root,
            root_resolution_source=root_resolution_source,
            payload_root=payload_root,
            host_id=host_id,
            fallback_reason=fallback_reason,
            ignore_mode=current_ignore_mode,
        )

    _write_workspace_stub_overlay(
        bundle_root=bundle_root,
        workspace_root=resolved_activation_root,
        bundle_manifest=bundle_manifest,
    )
    action = "bootstrapped" if state == "MISSING" else "updated"
    success_ignore_mode = _default_ignore_mode(resolved_activation_root)
    return _result(
        action=action,
        state=state,
        reason_code=REASON_STUB_SELECTED,
        workspace_root=workspace_root,
        bundle_root=bundle_root,
        from_version=from_version,
        to_version=to_version,
        message="Workspace control-plane stub is enabled and points to the selected global bundle.",
        activation_root=resolved_activation_root,
        requested_root=requested_root,
        root_resolution_source=root_resolution_source,
        payload_root=payload_root,
        host_id=host_id,
        authorization_mode=write_authorization_mode if state == "MISSING" else "",
        fallback_reason=fallback_reason,
        ignore_mode=success_ignore_mode,
    )


_BLOCKED_BOOTSTRAP_COMMAND_PATTERNS = (
    re.compile(r"^~compare(?:\s|$)", re.IGNORECASE),
    re.compile(r"^~go\s+finalize(?:\s|$)", re.IGNORECASE),
    re.compile(r"^~go\s+exec(?:\s|$)", re.IGNORECASE),
    re.compile(r"^~summary(?:\s|$)", re.IGNORECASE),
)
_CONFIRM_BOOTSTRAP_COMMAND_PATTERNS = (
    re.compile(r"^~go\s+init(?:\s|$)", re.IGNORECASE),
)
_ALLOWED_BOOTSTRAP_COMMAND_PATTERNS = (
    re.compile(r"^~go\s+plan(?:\s|$)", re.IGNORECASE),
    re.compile(r"^~go(?:\s|$)", re.IGNORECASE),
)
_BRAKE_LAYER_PATTERNS = (
    re.compile(r"(不要改|先分析|只解释|不写文件|别写文件|先别写)", re.IGNORECASE),
    re.compile(r"(do not|don't|no need to)\s+(write|edit|modify|change)", re.IGNORECASE),
    re.compile(r"(explain-only|read-only)", re.IGNORECASE),
)


def _authorize_first_workspace_write(request_text: str) -> dict[str, object]:
    text = str(request_text or "").strip()
    if not text:
        return {
            "allow_write": True,
            "mode": "host_installer_default",
            "reason_code": "WORKSPACE_BOOTSTRAP_AUTHORIZED_DEFAULT",
            "message": "Workspace bootstrap was requested explicitly by the installer flow.",
        }

    if any(pattern.search(text) for pattern in _BLOCKED_BOOTSTRAP_COMMAND_PATTERNS):
        return {
            "allow_write": False,
            "mode": "blocked_command",
            "reason_code": "COMMAND_NOT_BOOTSTRAP_AUTHORIZED",
            "message": "Workspace bootstrap is not allowed for this command on an unactivated workspace.",
        }
    if any(pattern.search(text) for pattern in _BRAKE_LAYER_PATTERNS):
        return {
            "allow_write": False,
            "mode": "brake_layer_blocked",
            "reason_code": "BRAKE_LAYER_BLOCKED",
            "message": "Workspace bootstrap was blocked by an explicit no-write or explain-only request.",
        }
    if any(pattern.search(text) for pattern in _CONFIRM_BOOTSTRAP_COMMAND_PATTERNS):
        return {
            "allow_write": True,
            "mode": "explicit_confirm",
            "reason_code": "WORKSPACE_BOOTSTRAP_AUTHORIZED_CONFIRM",
            "message": "Workspace bootstrap is authorized by the explicit `~go init` confirmation command.",
        }
    if any(pattern.search(text) for pattern in _ALLOWED_BOOTSTRAP_COMMAND_PATTERNS):
        return {
            "allow_write": True,
            "mode": "explicit_allow",
            "reason_code": "WORKSPACE_BOOTSTRAP_AUTHORIZED_EXPLICIT",
            "message": "Workspace bootstrap is authorized for this explicit command.",
        }
    return {
        "allow_write": False,
        "mode": "no_write_consult",
        "reason_code": "FIRST_WRITE_NOT_AUTHORIZED",
        "message": "Workspace bootstrap requires an explicit `~go`, `~go plan`, or `~go init` command on first write.",
    }


def _classify_first_write_barrier(
    *,
    workspace_root: Path,
    activation_root: Path,
    explicit_activation_root: Path | None,
    bundle_root: Path,
    root_resolution_source: str,
    fallback_reason: str,
    interaction_mode: str | None,
    ignore_mode: str,
    authorization_mode: str,
) -> dict[str, object] | None:
    if interaction_mode == "non_interactive":
        return {
            "reason_code": REASON_NON_INTERACTIVE,
            "message": "This is a non-interactive session. Open an interactive session before enabling Sopify here.",
        }

    if explicit_activation_root is None and root_resolution_source == "cwd" and not fallback_reason:
        repo_root = _find_git_ancestor_root(workspace_root)
        if repo_root is not None and repo_root != workspace_root:
            # Root disambiguation intentionally runs before the non-git confirm.
            # A nested package may still need a follow-up `~go init` confirm on
            # the next pass when the caller explicitly chooses a non-git target.
            return {
                "reason_code": REASON_ROOT_CONFIRM_REQUIRED,
                "message": "Sopify needs you to confirm which directory to enable in this repository. Retry with `activation_root` set to the current directory to enable only this package, or to the repository root to enable the whole repo. You may also provide another directory manually.",
                "expose_activation_root": False,
                "expose_ignore_mode": False,
                "evidence": (
                    f"repo_root={repo_root}",
                    f"recommended_activation_root={workspace_root}",
                    f"alternate_activation_root={repo_root}",
                    "manual_activation_root_allowed=true",
                ),
            }

    if not _can_write_bootstrap_target(bundle_root):
        return {
            "reason_code": REASON_READONLY,
            "message": "Sopify cannot enable this directory because it is not writable. Fix permissions and retry.",
            "evidence": (f"target_root={activation_root}",),
        }

    if ignore_mode == "noop" and authorization_mode not in {"explicit_confirm", "host_installer_default"}:
        return {
            "reason_code": REASON_CONFIRM_BOOTSTRAP_REQUIRED,
            "message": "Current directory is not a Git repository. Continuing will not add ignore rules automatically. Run `~go init` to confirm, or initialize Git and retry.",
        }
    return None


def _resolve_activation_root(
    *,
    workspace_root: Path,
    explicit_activation_root: Path | None,
) -> tuple[Path, str, str]:
    if explicit_activation_root is not None:
        if not explicit_activation_root.exists():
            raise ValueError(f"Explicit activation root does not exist: {explicit_activation_root}")
        if not explicit_activation_root.is_dir():
            raise ValueError(f"Explicit activation root is not a directory: {explicit_activation_root}")
        return (explicit_activation_root, "explicit_root", "")

    for ancestor in workspace_root.parents:
        marker_path = ancestor / ".sopify-runtime" / "manifest.json"
        if not marker_path.is_file():
            continue
        if _marker_has_minimum_validity(marker_path):
            return (ancestor, "ancestor_marker", "")
        return (workspace_root, "cwd", "invalid_ancestor_marker")

    return (workspace_root, "cwd", "")


def _find_git_ancestor_root(workspace_root: Path) -> Path | None:
    if (workspace_root / ".git").exists():
        return workspace_root
    for ancestor in workspace_root.parents:
        if (ancestor / ".git").exists():
            return ancestor
    return None


def _can_write_bootstrap_target(bundle_root: Path) -> bool:
    candidate = bundle_root if bundle_root.exists() else bundle_root.parent
    return os.access(candidate, os.W_OK | os.X_OK)


def _marker_has_minimum_validity(marker_path: Path) -> bool:
    payload = _read_json(marker_path)
    if not payload:
        return False
    return isinstance(payload.get("schema_version"), str) and bool(str(payload.get("schema_version") or "").strip())


def _classify_workspace_bundle(
    *,
    current_manifest: dict[str, Any],
    payload_manifest: dict[str, Any],
    bundle_manifest: dict[str, Any],
    current_manifest_path: Path,
    bundle_root: Path,
    global_bundle_root: Path | None,
    global_reason_code: str | None = None,
    global_message: str | None = None,
) -> tuple[str, str, str, str | None]:
    if not current_manifest_path.is_file():
        return ("MISSING", "MISSING_BUNDLE", "Workspace bundle is missing and will be bootstrapped.", None)

    if not current_manifest:
        return (
            "INCOMPATIBLE",
            REASON_STUB_INVALID,
            "Workspace stub manifest is unreadable and will be replaced.",
            None,
        )

    state, reason_code, message, normalized_manifest = _classify_workspace_stub_contract(
        current_manifest=current_manifest,
        payload_manifest=payload_manifest,
        bundle_manifest=bundle_manifest,
        workspace_root=bundle_root.parent,
    )
    if state != "READY":
        return (state, reason_code, message, _string_or_none(current_manifest.get("bundle_version")))

    from_version = _string_or_none(normalized_manifest.get("bundle_version")) or _string_or_none(bundle_manifest.get("bundle_version"))

    if global_reason_code:
        state, reason_code, message = _classify_global_failure_fallback(
            current_manifest=normalized_manifest,
            payload_manifest=payload_manifest,
            bundle_manifest=bundle_manifest,
            bundle_root=bundle_root,
            global_reason_code=global_reason_code,
            global_message=global_message or "Selected global bundle is unavailable.",
        )
        return (state, reason_code, message, from_version)

    state, reason_code, message = _classify_global_bundle_contract(
        payload_manifest=payload_manifest,
        bundle_manifest=bundle_manifest,
        global_bundle_root=global_bundle_root,
    )
    if state != "READY":
        state, reason_code, message = _classify_global_failure_fallback(
            current_manifest=normalized_manifest,
            payload_manifest=payload_manifest,
            bundle_manifest=bundle_manifest,
            bundle_root=bundle_root,
            global_reason_code=reason_code,
            global_message=message,
        )
        return (state, reason_code, message, from_version)

    return (
        "READY",
        REASON_STUB_SELECTED,
        "Workspace stub resolves to the selected global bundle.",
        from_version,
    )


def _classify_workspace_stub_contract(
    *,
    current_manifest: dict[str, Any],
    payload_manifest: dict[str, Any],
    bundle_manifest: dict[str, Any],
    workspace_root: Path,
) -> tuple[str, str, str, dict[str, Any]]:
    minimum_manifest = payload_manifest.get("minimum_workspace_manifest") or {}
    expected_schema = str(minimum_manifest.get("schema_version") or bundle_manifest.get("schema_version") or "1")
    workspace_schema = str(current_manifest.get("schema_version") or "")
    if workspace_schema != expected_schema:
        return (
            "INCOMPATIBLE",
            REASON_STUB_INVALID,
            f"Workspace bundle schema {workspace_schema or '<missing>'} is incompatible with required schema {expected_schema}.",
            {},
        )
    try:
        normalized_manifest = _normalize_workspace_stub_contract(current_manifest=current_manifest, workspace_root=workspace_root)
    except ValueError as exc:
        return (
            "INCOMPATIBLE",
            REASON_STUB_INVALID,
            str(exc),
            {},
        )
    return ("READY", REASON_STUB_SELECTED, "Sopify is enabled for this project and points to the selected global bundle.", normalized_manifest)


def _classify_global_bundle_contract(
    *,
    payload_manifest: dict[str, Any],
    bundle_manifest: dict[str, Any],
    global_bundle_root: Path | None,
) -> tuple[str, str, str]:
    if global_bundle_root is None or not bundle_manifest:
        return ("INCOMPATIBLE", "GLOBAL_BUNDLE_MISSING", "Selected global bundle is missing.")
    minimum_manifest = payload_manifest.get("minimum_workspace_manifest") or {}
    required_capabilities = minimum_manifest.get("required_capabilities") or {}
    missing_capabilities = _find_missing_capabilities(required_capabilities, bundle_manifest.get("capabilities") or {})
    if missing_capabilities:
        return (
            "INCOMPATIBLE",
            "GLOBAL_BUNDLE_INCOMPATIBLE",
            f"Selected global bundle is missing required capabilities: {', '.join(missing_capabilities)}.",
        )
    missing_files = _find_missing_required_files(global_bundle_root)
    if missing_files:
        return (
            "INCOMPATIBLE",
            "GLOBAL_BUNDLE_INCOMPATIBLE",
            f"Selected global bundle is missing required files: {', '.join(missing_files)}.",
        )
    return ("READY", "PAYLOAD_BUNDLE_READY", "Selected global bundle is available.")


def _classify_global_failure_fallback(
    *,
    current_manifest: dict[str, Any],
    payload_manifest: dict[str, Any],
    bundle_manifest: dict[str, Any],
    bundle_root: Path,
    global_reason_code: str,
    global_message: str,
) -> tuple[str, str, str]:
    locator_mode = str(current_manifest.get("locator_mode") or "global_first")
    legacy_fallback = bool(current_manifest.get("legacy_fallback", False))
    if locator_mode == "global_only" or not legacy_fallback:
        return ("INCOMPATIBLE", global_reason_code, global_message)

    legacy_state, _legacy_reason_code, _legacy_message = _classify_legacy_workspace_runtime(
        current_manifest=current_manifest,
        payload_manifest=payload_manifest,
        bundle_manifest=bundle_manifest,
        bundle_root=bundle_root,
    )
    if legacy_state == "READY":
        return (
            "READY",
            "LEGACY_FALLBACK_SELECTED",
            f"{global_message} Using compatible legacy workspace runtime fallback.",
        )
    return ("INCOMPATIBLE", global_reason_code, global_message)


def _classify_legacy_workspace_runtime(
    *,
    current_manifest: dict[str, Any],
    payload_manifest: dict[str, Any],
    bundle_manifest: dict[str, Any],
    bundle_root: Path,
) -> tuple[str, str, str]:
    if not _legacy_workspace_artifacts_present(bundle_root):
        return ("ABSENT", "LEGACY_WORKSPACE_ABSENT", "No legacy workspace runtime artifacts were found.")
    minimum_manifest = payload_manifest.get("minimum_workspace_manifest") or {}
    required_capabilities = minimum_manifest.get("required_capabilities") or {}
    legacy_capabilities = current_manifest.get("capabilities")
    if not isinstance(legacy_capabilities, dict) or not legacy_capabilities:
        if current_manifest.get("stub_version"):
            legacy_capabilities = dict(required_capabilities)
        else:
            legacy_capabilities = bundle_manifest.get("capabilities") or {}
    missing_capabilities = _find_missing_capabilities(required_capabilities, legacy_capabilities)
    if missing_capabilities:
        return (
            "INCOMPATIBLE",
            "MISSING_REQUIRED_CAPABILITY",
            f"Workspace bundle is missing required capabilities: {', '.join(missing_capabilities)}.",
        )
    missing_files = _find_missing_required_files(bundle_root)
    if missing_files:
        return (
            "INCOMPATIBLE",
            "MISSING_REQUIRED_FILE",
            f"Workspace bundle is missing required files: {', '.join(missing_files)}.",
        )
    return ("READY", "LEGACY_WORKSPACE_READY", "Legacy workspace runtime artifacts remain structurally complete.")


def _legacy_workspace_artifacts_present(bundle_root: Path) -> bool:
    return any((bundle_root / relative_path).exists() for relative_path in _REQUIRED_BUNDLE_FILES if relative_path != Path("manifest.json"))


def _normalize_workspace_stub_contract(*, current_manifest: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    normalized = dict(current_manifest)
    normalized["schema_version"] = _normalize_stub_schema_version(normalized.get("schema_version"))
    normalized["stub_version"] = _normalize_stub_version(normalized.get("stub_version"))
    normalized["locator_mode"] = _normalize_locator_mode(normalized.get("locator_mode"))
    normalized["bundle_version"] = _normalize_optional_bundle_version(normalized.get("bundle_version"), field_name="bundle_version")
    normalized["required_capabilities"] = _normalize_required_capabilities(normalized.get("required_capabilities"))
    normalized["legacy_fallback"] = bool(normalized.get("legacy_fallback", False))
    if normalized["locator_mode"] == "global_only" and normalized["legacy_fallback"]:
        raise ValueError("Workspace stub contract is invalid: legacy_fallback is not allowed when locator_mode=global_only.")
    normalized["ignore_mode"] = _normalize_ignore_mode(normalized.get("ignore_mode"), workspace_root=workspace_root)
    normalized["written_by_host"] = bool(normalized.get("written_by_host", False))
    return normalized


def _resolve_selected_payload_bundle(
    *,
    payload_root: Path,
    payload_manifest: dict[str, Any],
    current_manifest: dict[str, Any],
) -> tuple[Path | None, Path | None, dict[str, Any], str | None, str | None]:
    requested_version = _coerce_workspace_bundle_version(current_manifest.get("bundle_version"))
    try:
        bundle_manifest_path = _resolve_payload_bundle_manifest_path(
            payload_root=payload_root,
            payload_manifest=payload_manifest,
            bundle_version=requested_version,
        )
    except ValueError as exc:
        return (None, None, {}, "GLOBAL_INDEX_CORRUPTED", str(exc))
    bundle_root = bundle_manifest_path.parent
    if not bundle_manifest_path.is_file():
        return (
            bundle_root,
            bundle_manifest_path,
            {},
            "GLOBAL_BUNDLE_MISSING",
            f"Selected global bundle is missing: {bundle_manifest_path}",
        )
    bundle_manifest = _read_json(bundle_manifest_path)
    if not bundle_manifest:
        return (
            bundle_root,
            bundle_manifest_path,
            {},
            "GLOBAL_BUNDLE_INCOMPATIBLE",
            f"Selected global bundle manifest is unreadable: {bundle_manifest_path}",
        )
    return (bundle_root, bundle_manifest_path, bundle_manifest, None, None)


def _resolve_payload_bundle_manifest_path(
    *,
    payload_root: Path,
    payload_manifest: dict[str, Any],
    bundle_version: str | None,
) -> Path:
    bundles_dir = _resolve_payload_relative_path(payload_root, payload_manifest.get("bundles_dir"), field_name="bundles_dir")
    if bundles_dir is not None:
        if bundle_version is not None:
            return payload_root / bundles_dir / bundle_version / "manifest.json"
        active_version = _normalize_optional_bundle_version(payload_manifest.get("active_version"), field_name="active_version")
        if active_version is None:
            raise ValueError("Payload verification failed: active_version")
        return payload_root / bundles_dir / active_version / "manifest.json"
    if bundle_version is not None:
        legacy_version = _legacy_payload_bundle_version(payload_manifest)
        if legacy_version == bundle_version:
            return _legacy_bundle_manifest_path(payload_root, payload_manifest)
        return payload_root / "bundles" / bundle_version / "manifest.json"
    return _legacy_bundle_manifest_path(payload_root, payload_manifest)


def _legacy_payload_bundle_version(payload_manifest: dict[str, Any]) -> str | None:
    if "bundle_version" in payload_manifest:
        return _normalize_optional_bundle_version(payload_manifest.get("bundle_version"), field_name="bundle_version")
    if "active_version" in payload_manifest:
        return _normalize_optional_bundle_version(payload_manifest.get("active_version"), field_name="active_version")
    return None


def _legacy_bundle_manifest_path(payload_root: Path, payload_manifest: dict[str, Any]) -> Path:
    relative = _resolve_payload_relative_path(payload_root, payload_manifest.get("bundle_manifest"), field_name="bundle_manifest")
    if relative is not None:
        return payload_root / relative
    return payload_root / "bundle" / "manifest.json"


def _resolve_payload_relative_path(payload_root: Path, value: Any, *, field_name: str) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Payload verification failed: {field_name}")
    resolved_root = payload_root.resolve()
    resolved_candidate = (resolved_root / candidate).resolve()
    try:
        return resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Payload verification failed: {field_name}") from exc


def _normalize_stub_schema_version(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Workspace stub contract is invalid: schema_version is required.")
    return normalized


def _normalize_stub_version(value: Any) -> str:
    normalized = str(value or "1").strip()
    if not normalized:
        raise ValueError("Workspace stub contract is invalid: stub_version is required.")
    return normalized


def _normalize_locator_mode(value: Any) -> str:
    normalized = str(value or "global_first").strip() or "global_first"
    if normalized not in _WORKSPACE_STUB_LOCATOR_MODES:
        raise ValueError(f"Workspace stub contract is invalid: locator_mode={normalized!r}.")
    return normalized


def _normalize_optional_bundle_version(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"Payload verification failed: {field_name}" if field_name == "active_version" else f"Workspace stub contract is invalid: {field_name}.")
    if normalized == "latest" or not _EXACT_BUNDLE_VERSION_RE.match(normalized):
        raise ValueError(f"Payload verification failed: {field_name}" if field_name == "active_version" else f"Workspace stub contract is invalid: {field_name}.")
    return normalized


def _coerce_workspace_bundle_version(value: Any) -> str | None:
    try:
        return _normalize_optional_bundle_version(value, field_name="bundle_version")
    except ValueError:
        return None


def _normalize_required_capabilities(value: Any) -> list[str]:
    if value in (None, ""):
        return list(_WORKSPACE_STUB_REQUIRED_CAPABILITIES)
    if not isinstance(value, (list, tuple)):
        raise ValueError("Workspace stub contract is invalid: required_capabilities.")
    normalized: list[str] = []
    for item in value:
        capability = str(item or "").strip()
        if capability not in _WORKSPACE_STUB_REQUIRED_CAPABILITIES or capability in normalized:
            raise ValueError("Workspace stub contract is invalid: required_capabilities.")
        normalized.append(capability)
    return normalized or list(_WORKSPACE_STUB_REQUIRED_CAPABILITIES)


def _normalize_ignore_mode(value: Any, *, workspace_root: Path) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "exclude" if (workspace_root / ".git").exists() else "noop"
    if normalized not in _WORKSPACE_STUB_IGNORE_MODES:
        raise ValueError("Workspace stub contract is invalid: ignore_mode.")
    return normalized


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


def _write_workspace_stub_overlay(
    *,
    bundle_root: Path,
    workspace_root: Path,
    bundle_manifest: dict[str, Any] | None = None,
) -> None:
    manifest_path = bundle_root / "manifest.json"
    payload = _read_json(manifest_path)
    if not payload:
        payload = dict(bundle_manifest or {})
    if not payload:
        raise ValueError(f"Workspace bootstrap produced an unreadable manifest: {manifest_path}")
    payload = {
        # Workspace `.sopify-runtime/manifest.json` is now a thin stub only.
        # The full runtime/bundle contract remains in the selected global
        # bundle manifest under the host payload.
        "schema_version": str(payload.get("schema_version") or "1"),
        "stub_version": "1",
        "bundle_version": _string_or_none(payload.get("bundle_version")),
        "required_capabilities": list(_WORKSPACE_STUB_REQUIRED_CAPABILITIES),
        "locator_mode": "global_first",
        "legacy_fallback": False,
        "ignore_mode": _default_ignore_mode(workspace_root),
        "written_by_host": True,
    }
    bundle_root.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=manifest_path.parent, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(manifest_path)


def _default_ignore_mode(workspace_root: Path) -> str:
    if (workspace_root / ".git").exists():
        return "exclude"
    return "noop"


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
    activation_root: Path | None = None,
    requested_root: Path | None = None,
    root_resolution_source: str = "",
    payload_root: Path | None = None,
    host_id: str | None = None,
    authorization_mode: str = "",
    fallback_reason: str = "",
    ignore_mode: str = "",
    extra_evidence: tuple[str, ...] = (),
    expose_activation_root: bool = True,
    expose_ignore_mode: bool = True,
) -> dict[str, Any]:
    target_root = activation_root or workspace_root
    payload = {
        "action": action,
        "state": state,
        "reason_code": reason_code,
        "workspace_root": str(workspace_root),
        "bundle_root": str(bundle_root),
        "from_version": from_version,
        "to_version": to_version,
        "message": message,
    }
    if expose_activation_root and activation_root is not None:
        payload["activation_root"] = str(activation_root)
    if requested_root is not None:
        payload["requested_root"] = str(requested_root)
    if root_resolution_source:
        payload["root_resolution_source"] = root_resolution_source
    if payload_root is not None:
        payload["payload_root"] = str(payload_root)
    if host_id:
        payload["host_id"] = host_id
    if authorization_mode:
        payload["authorization_mode"] = authorization_mode
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    effective_ignore_mode = ignore_mode if expose_ignore_mode else ""
    if effective_ignore_mode:
        payload["ignore_mode"] = effective_ignore_mode
        if effective_ignore_mode == "exclude":
            payload["ignore_target"] = str(target_root / ".git" / "info" / "exclude")
        elif effective_ignore_mode == "gitignore":
            payload["ignore_target"] = str(target_root / ".gitignore")
    evidence = _result_evidence(
        workspace_root=target_root,
        ignore_mode=effective_ignore_mode,
        root_resolution_source=root_resolution_source,
        fallback_reason=fallback_reason,
        extra_evidence=extra_evidence,
    )
    if evidence:
        payload["evidence"] = evidence
    return payload


def _result_evidence(
    *,
    workspace_root: Path,
    ignore_mode: str,
    root_resolution_source: str,
    fallback_reason: str,
    extra_evidence: tuple[str, ...],
) -> list[str]:
    evidence: list[str] = [str(item) for item in extra_evidence if str(item or "").strip()]
    if root_resolution_source == "ancestor_marker":
        evidence.append(DIAGNOSTIC_ROOT_REUSE_ANCESTOR_MARKER)
    if fallback_reason == "invalid_ancestor_marker":
        evidence.append(DIAGNOSTIC_INVALID_ANCESTOR_MARKER)
    if ignore_mode == "noop" and not (workspace_root / ".git").exists():
        evidence.append(DIAGNOSTIC_NON_GIT_WORKSPACE)
        evidence.append("ignore_mode=noop")
    return evidence


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
