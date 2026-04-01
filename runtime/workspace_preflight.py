"""Shared workspace preflight/bootstrap helpers for Sopify host entries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator, Mapping

try:
    from installer.hosts import iter_host_payload_manifest_candidates, resolve_host_payload_root
    from installer.models import InstallError
    from installer.validate import resolve_payload_bundle_manifest_path, validate_workspace_stub_manifest
except ModuleNotFoundError as exc:
    if not str(exc.name or "").startswith("installer"):
        raise

    class InstallError(RuntimeError):
        """Vendored runtime fallback when installer package is unavailable."""

    _FALLBACK_HOST_PAYLOAD_ROOTS = {
        "codex": (".codex", "sopify"),
        "claude": (".claude", "sopify"),
    }
    _FALLBACK_STUB_LOCATOR_MODES = {"global_first", "global_only"}
    _FALLBACK_STUB_IGNORE_MODES = {"exclude", "gitignore", "noop"}
    _FALLBACK_STUB_REQUIRED_CAPABILITIES = {"runtime_gate", "preferences_preload"}
    _FALLBACK_EXACT_BUNDLE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    _FALLBACK_DEFAULT_VERSIONED_BUNDLES_DIR = Path("bundles")
    _FALLBACK_LEGACY_BUNDLE_MANIFEST_PATH = Path("bundle") / "manifest.json"

    def resolve_host_payload_root(*, home_root: Path, host_id: str) -> Path:
        try:
            relative_parts = _FALLBACK_HOST_PAYLOAD_ROOTS[host_id]
        except KeyError as error:
            raise ValueError(f"Unsupported host payload root: {host_id}") from error
        return home_root.joinpath(*relative_parts)

    def iter_host_payload_manifest_candidates(*, home_root: Path) -> Iterator[tuple[str, Path]]:
        for host_id, relative_parts in _FALLBACK_HOST_PAYLOAD_ROOTS.items():
            yield (host_id, home_root.joinpath(*relative_parts) / "payload-manifest.json")

    def resolve_payload_bundle_manifest_path(
        payload_root: Path,
        payload_manifest: Mapping[str, Any],
        *,
        bundle_version: str | None = None,
    ) -> Path:
        requested_version = _fallback_normalize_payload_bundle_version(bundle_version) if bundle_version is not None else None
        bundles_dir = _fallback_resolve_payload_relative_path(payload_root, payload_manifest.get("bundles_dir"), field_name="bundles_dir")
        if bundles_dir is not None:
            if requested_version is not None:
                return payload_root / bundles_dir / requested_version / "manifest.json"
            active_version = _fallback_normalize_payload_bundle_version(payload_manifest.get("active_version"))
            if active_version is None:
                raise InstallError("Payload verification failed: active_version")
            return payload_root / bundles_dir / active_version / "manifest.json"
        if requested_version is not None:
            legacy_bundle_version = _fallback_legacy_payload_bundle_version(dict(payload_manifest))
            if legacy_bundle_version == requested_version:
                return _fallback_legacy_bundle_manifest_path(payload_root, dict(payload_manifest))
            return payload_root / _FALLBACK_DEFAULT_VERSIONED_BUNDLES_DIR / requested_version / "manifest.json"
        return _fallback_legacy_bundle_manifest_path(payload_root, dict(payload_manifest))

    def validate_workspace_stub_manifest(bundle_root: Path) -> tuple[Path, dict[str, Any]]:
        manifest_path = bundle_root / "manifest.json"
        manifest = _fallback_read_json_object(manifest_path)
        workspace_root = bundle_root.parent
        normalized = dict(manifest)
        normalized["schema_version"] = _fallback_normalize_stub_schema_version(normalized.get("schema_version"))
        normalized["stub_version"] = _fallback_normalize_stub_version(normalized.get("stub_version"))
        normalized["locator_mode"] = _fallback_normalize_locator_mode(normalized.get("locator_mode"))
        normalized["bundle_version"] = _fallback_normalize_bundle_version(normalized.get("bundle_version"))
        normalized["required_capabilities"] = _fallback_normalize_required_capabilities(normalized.get("required_capabilities"))
        normalized["legacy_fallback"] = bool(normalized.get("legacy_fallback", False))
        if normalized["locator_mode"] == "global_only" and normalized["legacy_fallback"]:
            raise InstallError(f"Stub verification failed: {manifest_path}")
        normalized["ignore_mode"] = _fallback_normalize_ignore_mode(normalized.get("ignore_mode"), workspace_root=workspace_root)
        normalized["written_by_host"] = bool(normalized.get("written_by_host", False))
        return (manifest_path, normalized)

    def _fallback_read_json_object(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise InstallError(f"Payload verification failed: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InstallError(f"JSON verification failed: {path}") from error
        if not isinstance(payload, dict):
            raise InstallError(f"JSON verification failed: {path}")
        return payload

    def _fallback_resolve_payload_relative_path(payload_root: Path, value: Any, *, field_name: str) -> Path | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        candidate = Path(normalized)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise InstallError(f"Payload verification failed: {field_name}")
        resolved_root = payload_root.resolve()
        resolved_candidate = (resolved_root / candidate).resolve()
        try:
            return resolved_candidate.relative_to(resolved_root)
        except ValueError as error:
            raise InstallError(f"Payload verification failed: {field_name}") from error

    def _fallback_normalize_payload_bundle_version(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if normalized == "latest" or not _FALLBACK_EXACT_BUNDLE_VERSION_RE.match(normalized):
            raise InstallError("Payload verification failed: bundle_version")
        return normalized

    def _fallback_legacy_payload_bundle_version(payload_manifest: dict[str, Any]) -> str | None:
        if "bundle_version" in payload_manifest:
            return _fallback_normalize_payload_bundle_version(payload_manifest.get("bundle_version"))
        if "active_version" in payload_manifest:
            return _fallback_normalize_payload_bundle_version(payload_manifest.get("active_version"))
        return None

    def _fallback_legacy_bundle_manifest_path(payload_root: Path, payload_manifest: dict[str, Any]) -> Path:
        relative = _fallback_resolve_payload_relative_path(payload_root, payload_manifest.get("bundle_manifest"), field_name="bundle_manifest")
        if relative is not None:
            return payload_root / relative
        return payload_root / _FALLBACK_LEGACY_BUNDLE_MANIFEST_PATH

    def _fallback_normalize_locator_mode(value: Any) -> str:
        normalized = str(value or "global_first").strip() or "global_first"
        if normalized not in _FALLBACK_STUB_LOCATOR_MODES:
            raise InstallError("Stub verification failed: locator_mode")
        return normalized

    def _fallback_normalize_stub_schema_version(value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise InstallError("Stub verification failed: schema_version")
        return normalized

    def _fallback_normalize_stub_version(value: Any) -> str:
        normalized = str(value or "1").strip()
        if not normalized:
            raise InstallError("Stub verification failed: stub_version")
        return normalized

    def _fallback_normalize_bundle_version(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise InstallError("Stub verification failed: bundle_version")
        if normalized == "latest" or not _FALLBACK_EXACT_BUNDLE_VERSION_RE.match(normalized):
            raise InstallError("Stub verification failed: bundle_version")
        return normalized

    def _fallback_normalize_required_capabilities(value: Any) -> list[str]:
        if value in (None, ""):
            return ["runtime_gate", "preferences_preload"]
        if not isinstance(value, (list, tuple)):
            raise InstallError("Stub verification failed: required_capabilities")
        normalized: list[str] = []
        for item in value:
            capability = str(item or "").strip()
            if capability not in _FALLBACK_STUB_REQUIRED_CAPABILITIES or capability in normalized:
                raise InstallError("Stub verification failed: required_capabilities")
            normalized.append(capability)
        return normalized or ["runtime_gate", "preferences_preload"]

    def _fallback_normalize_ignore_mode(value: Any, *, workspace_root: Path) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return "exclude" if (workspace_root / ".git").exists() else "noop"
        if normalized not in _FALLBACK_STUB_IGNORE_MODES:
            raise InstallError("Stub verification failed: ignore_mode")
        return normalized

_LEGACY_WORKSPACE_RUNTIME_GATE_ENTRY = "scripts/runtime_gate.py"
_LEGACY_WORKSPACE_PREFERENCES_PRELOAD_ENTRY = "scripts/preferences_preload_runtime.py"


class WorkspacePreflightError(RuntimeError):
    """Raised when workspace runtime preflight cannot complete safely."""


def preflight_workspace_runtime(
    workspace_root: Path,
    *,
    request_text: str = "",
    payload_manifest_path: str | Path | None = None,
    activation_root: str | Path | None = None,
    interaction_mode: str | None = None,
    payload_root: str | Path | None = None,
    host_id: str | None = None,
    requested_root: str | Path | None = None,
    user_home: Path | None = None,
) -> Mapping[str, Any]:
    """Best-effort repo-local workspace preflight using the installed payload helper.

    The vendored bundle flow should already have been selected by the host via
    manifest-first preflight, so a bundle-local entry intentionally skips
    self-updating the workspace bundle it is currently executing from.
    """

    resolved_workspace_root = workspace_root.resolve()
    activation_root_path = Path(activation_root).expanduser().resolve() if activation_root is not None else resolved_workspace_root
    repo_root = Path(__file__).resolve().parents[1]
    bundle_root = resolved_workspace_root / ".sopify-runtime"
    requested_root_path = Path(requested_root).expanduser().resolve() if requested_root is not None else resolved_workspace_root
    root_resolution_source = "cwd"
    if repo_root == bundle_root:
        return {
            "action": "skipped",
            "reason_code": "RUNNING_FROM_WORKSPACE_BUNDLE",
            "message": "Current entry is already running from the workspace bundle; host preflight remains authoritative.",
            "activation_root": str(activation_root_path),
            "requested_root": str(requested_root_path),
            "root_resolution_source": root_resolution_source,
        }

    detected_host_id = str(host_id or "").strip() or None
    home_root = Path(user_home).expanduser().resolve() if user_home is not None else Path.home()
    payload_resolution = _resolve_payload_contract(
        payload_manifest_path=payload_manifest_path,
        payload_root=payload_root,
        host_id=detected_host_id,
        home_root=home_root,
    )
    if payload_resolution is None:
        return {
            "action": "skipped",
            "reason_code": "PAYLOAD_MANIFEST_NOT_FOUND",
            "message": "No installed host payload was found; continuing with repo-local entry.",
            "activation_root": str(activation_root_path),
            "requested_root": str(requested_root_path),
            "root_resolution_source": root_resolution_source,
        }

    payload_manifest = payload_resolution["payload_manifest"]
    payload_manifest_file = payload_resolution["payload_manifest_file"]
    detected_host_id = payload_resolution["host_id"]
    payload_root = payload_resolution["payload_root"]

    if payload_manifest is None or payload_manifest_file is None:
        raise WorkspacePreflightError("Payload manifest resolution failed unexpectedly")
    helper_entry = str(payload_manifest.get("helper_entry") or "").strip()
    if not helper_entry:
        raise WorkspacePreflightError(f"Payload manifest is missing helper_entry: {payload_manifest_file}")
    preflight_bundle_version = _workspace_selected_bundle_version(bundle_root)
    try:
        resolve_payload_bundle_manifest_path(payload_root, payload_manifest, bundle_version=preflight_bundle_version)
    except InstallError as exc:
        raise WorkspacePreflightError(str(exc)) from exc
    helper_path = _resolve_helper_path(payload_root=payload_root, helper_entry=helper_entry)
    if not helper_path.is_file():
        raise WorkspacePreflightError(f"Workspace bootstrap helper is missing: {helper_path}")

    command = [sys.executable, str(helper_path), "--workspace-root", str(resolved_workspace_root), "--request", request_text]
    if activation_root is not None:
        command.extend(["--activation-root", str(activation_root_path)])
    if interaction_mode is not None:
        command.extend(["--interaction-mode", str(interaction_mode)])
    if detected_host_id:
        command.extend(["--host-id", detected_host_id])
    if requested_root is not None:
        command.extend(["--requested-root", str(requested_root_path)])
    completed, helper_argv_mode = _run_bootstrap_helper_with_compatibility(
        helper_path=helper_path,
        workspace_root=resolved_workspace_root,
        command=command,
        interaction_mode=interaction_mode,
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
    payload = dict(result)
    # Root disambiguation must stay purely about picking a directory. If the
    # helper is still asking the host to choose a root, do not backfill the
    # default cwd activation root here or we leak a fake selection.
    if str(payload.get("reason_code") or "").strip() != "ROOT_CONFIRM_REQUIRED":
        payload.setdefault("activation_root", str(activation_root_path))
    payload.setdefault("requested_root", str(requested_root_path))
    payload.setdefault("root_resolution_source", root_resolution_source)
    payload.setdefault("payload_root", str(payload_root))
    selected_bundle_manifest_path = _selected_bundle_manifest_path(
        payload_root=payload_root,
        payload_manifest=payload_manifest,
        workspace_bundle_root=bundle_root,
    )
    if selected_bundle_manifest_path is not None:
        payload.setdefault("bundle_manifest_path", str(selected_bundle_manifest_path))
        payload.setdefault("global_bundle_root", str(selected_bundle_manifest_path.parent))
        if str(payload.get("reason_code") or "").strip() == "LEGACY_FALLBACK_SELECTED":
            runtime_gate_entry = _legacy_workspace_entry(bundle_root, _LEGACY_WORKSPACE_RUNTIME_GATE_ENTRY)
            if runtime_gate_entry is not None:
                payload.setdefault("runtime_gate_entry", runtime_gate_entry)
            preferences_preload_entry = _legacy_workspace_entry(bundle_root, _LEGACY_WORKSPACE_PREFERENCES_PRELOAD_ENTRY)
            if preferences_preload_entry is not None:
                payload.setdefault("preferences_preload_entry", preferences_preload_entry)
        else:
            selected_bundle_manifest = _read_json_object(selected_bundle_manifest_path, error_prefix="Invalid bundle manifest")
            runtime_gate_entry = _bundle_limit_entry(selected_bundle_manifest, "runtime_gate_entry")
            if runtime_gate_entry is not None:
                payload.setdefault("runtime_gate_entry", runtime_gate_entry)
            preferences_preload_entry = _bundle_limit_entry(selected_bundle_manifest, "preferences_preload_entry")
            if preferences_preload_entry is not None:
                payload.setdefault("preferences_preload_entry", preferences_preload_entry)
    payload.setdefault("helper_path", str(helper_path))
    payload.setdefault("helper_argv_mode", helper_argv_mode)
    if detected_host_id:
        payload.setdefault("host_id", detected_host_id)
    return payload


def _infer_host_id_from_manifest_path(path: Path) -> str | None:
    normalized_parts = {part.lower() for part in path.parts}
    if ".codex" in normalized_parts:
        return "codex"
    if ".claude" in normalized_parts:
        return "claude"
    return None


def _ensure_supported_host_id(*, requested_host_id: str | None, home_root: Path) -> None:
    if requested_host_id is None:
        return
    try:
        resolve_host_payload_root(home_root=home_root, host_id=requested_host_id)
    except ValueError as exc:
        raise WorkspacePreflightError(f"Unsupported host_id: {requested_host_id}") from exc


def _validate_host_id_alignment(
    *,
    requested_host_id: str | None,
    selected_host_id: str | None,
    selection_source: str,
) -> None:
    if requested_host_id is None or selected_host_id is None or requested_host_id == selected_host_id:
        return
    raise WorkspacePreflightError(
        "Ingress host_id '{}' does not match the payload selected from {} (resolved host '{}'). "
        "Pass the matching payload_root or omit host_id.".format(
            requested_host_id,
            selection_source,
            selected_host_id,
        )
    )


def _load_explicit_payload_manifest(path: Path) -> tuple[dict[str, Any], Path, str | None]:
    if not path.exists() or not path.is_file():
        raise WorkspacePreflightError(f"Explicit payload manifest not found: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspacePreflightError(f"Explicit payload manifest not found: {path}") from exc
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise WorkspacePreflightError(f"Explicit payload manifest is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise WorkspacePreflightError(f"Explicit payload manifest must be a JSON object: {path}")
    helper_entry = payload.get("helper_entry")
    if not isinstance(helper_entry, str) or not helper_entry.strip():
        raise WorkspacePreflightError(f"Explicit payload manifest is missing helper_entry: {path}")
    return (payload, path, _infer_host_id_from_manifest_path(path))


def _load_payload_manifest_from_root(payload_root: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = payload_root / "payload-manifest.json"
    payload = _read_json_object(manifest_path, error_prefix="Invalid payload manifest")
    helper_entry = payload.get("helper_entry")
    if not isinstance(helper_entry, str) or not helper_entry.strip():
        raise WorkspacePreflightError(f"Payload manifest is missing helper_entry: {manifest_path}")
    return (payload, manifest_path)


def _discover_payload_manifest(
    manifest_candidates: list[tuple[Path, str | None]],
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    payload_manifest = None
    payload_manifest_file = None
    detected_host_id = None
    for candidate, host_id in manifest_candidates:
        if not candidate.is_file():
            continue
        try:
            payload_manifest = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkspacePreflightError(f"Invalid payload manifest: {candidate}") from exc
        if isinstance(payload_manifest, dict):
            payload_manifest_file = candidate
            detected_host_id = host_id
            break
    return (payload_manifest, payload_manifest_file, detected_host_id)


def _resolve_payload_contract(
    *,
    payload_manifest_path: str | Path | None,
    payload_root: str | Path | None,
    host_id: str | None,
    home_root: Path,
) -> dict[str, Any] | None:
    requested_host_id = str(host_id or "").strip() or None
    _ensure_supported_host_id(requested_host_id=requested_host_id, home_root=home_root)
    if payload_manifest_path is not None:
        explicit_path = Path(payload_manifest_path).expanduser().resolve()
        payload_manifest, payload_manifest_file, inferred_host_id = _load_explicit_payload_manifest(explicit_path)
        _validate_host_id_alignment(
            requested_host_id=requested_host_id,
            selected_host_id=inferred_host_id,
            selection_source=f"explicit payload manifest {payload_manifest_file}",
        )
        return {
            "payload_manifest": payload_manifest,
            "payload_manifest_file": payload_manifest_file,
            "payload_root": payload_manifest_file.parent,
            "host_id": inferred_host_id or requested_host_id,
        }
    if payload_root is not None:
        explicit_payload_root = Path(payload_root).expanduser().resolve()
        payload_manifest, payload_manifest_file = _load_payload_manifest_from_root(explicit_payload_root)
        inferred_host_id = _infer_host_id_from_manifest_path(payload_manifest_file)
        _validate_host_id_alignment(
            requested_host_id=requested_host_id,
            selected_host_id=inferred_host_id,
            selection_source=f"explicit payload_root {explicit_payload_root}",
        )
        return {
            "payload_manifest": payload_manifest,
            "payload_manifest_file": payload_manifest_file,
            "payload_root": explicit_payload_root,
            "host_id": inferred_host_id or requested_host_id,
        }

    env_manifest = (os.environ.get("SOPIFY_PAYLOAD_MANIFEST") or "").strip()
    if env_manifest:
        env_path = Path(env_manifest).expanduser().resolve()
        payload_manifest, payload_manifest_file, inferred_host_id = _load_explicit_payload_manifest(env_path)
        _validate_host_id_alignment(
            requested_host_id=requested_host_id,
            selected_host_id=inferred_host_id,
            selection_source=f"SOPIFY_PAYLOAD_MANIFEST {payload_manifest_file}",
        )
        return {
            "payload_manifest": payload_manifest,
            "payload_manifest_file": payload_manifest_file,
            "payload_root": payload_manifest_file.parent,
            "host_id": inferred_host_id or requested_host_id,
        }

    current_host_id = _detect_current_host_id_from_env()
    if current_host_id is not None:
        _validate_host_id_alignment(
            requested_host_id=requested_host_id,
            selected_host_id=current_host_id,
            selection_source=f"current host environment '{current_host_id}'",
        )
        current_payload_root = resolve_host_payload_root(home_root=home_root, host_id=current_host_id)
        current_manifest_path = current_payload_root / "payload-manifest.json"
        if current_manifest_path.is_file():
            payload_manifest, payload_manifest_file = _load_payload_manifest_from_root(current_payload_root)
            return {
                "payload_manifest": payload_manifest,
                "payload_manifest_file": payload_manifest_file,
                "payload_root": current_payload_root,
                "host_id": current_host_id,
            }
        for candidate_host_id, manifest_path in iter_host_payload_manifest_candidates(home_root=home_root):
            if candidate_host_id == current_host_id:
                continue
            if manifest_path.is_file():
                raise WorkspacePreflightError(
                    f"Installed payload for current host '{current_host_id}' was not found; refusing to use another host payload."
                )
        return None

    installed_candidates: list[tuple[str, Path]] = []
    for candidate_host_id, manifest_path in iter_host_payload_manifest_candidates(home_root=home_root):
        if not manifest_path.is_file():
            continue
        installed_candidates.append((candidate_host_id, manifest_path))
    if not installed_candidates:
        return None
    if len(installed_candidates) > 1:
        host_list = ", ".join(sorted(candidate_host_id for candidate_host_id, _path in installed_candidates))
        if requested_host_id is not None:
            raise WorkspacePreflightError(
                "Multiple installed host payloads found ({}); pass payload_root explicitly. "
                "host_id='{}' is audit-only and does not select a payload.".format(
                    host_list,
                    requested_host_id,
                )
            )
        raise WorkspacePreflightError(f"Multiple installed host payloads found ({host_list}); pass payload_root explicitly.")
    candidate_host_id, manifest_path = installed_candidates[0]
    _validate_host_id_alignment(
        requested_host_id=requested_host_id,
        selected_host_id=candidate_host_id,
        selection_source=f"the only installed payload {manifest_path.parent}",
    )
    payload_manifest, payload_manifest_file = _load_payload_manifest_from_root(manifest_path.parent)
    return {
        "payload_manifest": payload_manifest,
        "payload_manifest_file": payload_manifest_file,
        "payload_root": payload_manifest_file.parent,
        "host_id": candidate_host_id,
    }


def _detect_current_host_id_from_env() -> str | None:
    if any(key.startswith("CODEX_") for key in os.environ):
        return "codex"
    if any(key.startswith("CLAUDE_") for key in os.environ):
        return "claude"
    return None


def _resolve_helper_path(*, payload_root: Path, helper_entry: str) -> Path:
    normalized_entry = str(helper_entry or "").strip()
    if not normalized_entry:
        raise WorkspacePreflightError(f"Invalid helper_entry: helper_entry=<empty>, payload_root={payload_root}")
    helper_candidate = Path(normalized_entry)
    if helper_candidate.is_absolute():
        resolved = helper_candidate.resolve()
        raise WorkspacePreflightError(
            f"Invalid helper_entry: helper_entry={normalized_entry}, resolved_helper_path={resolved}, payload_root={payload_root}"
        )
    resolved = (payload_root / helper_candidate).resolve()
    try:
        resolved.relative_to(payload_root.resolve())
    except ValueError as exc:
        raise WorkspacePreflightError(
            f"Invalid helper_entry: helper_entry={normalized_entry}, resolved_helper_path={resolved}, payload_root={payload_root}"
        ) from exc
    return resolved


def _bundle_limit_entry(bundle_manifest: Mapping[str, Any], field_name: str) -> str | None:
    limits = bundle_manifest.get("limits")
    if not isinstance(limits, Mapping):
        return None
    value = limits.get(field_name)
    normalized = str(value or "").strip()
    return normalized or None


def _legacy_workspace_entry(bundle_root: Path, relative_path: str) -> str | None:
    normalized = str(relative_path or "").strip()
    if not normalized:
        return None
    if not (bundle_root / normalized).is_file():
        return None
    return normalized


def _read_json_object(path: Path, *, error_prefix: str) -> dict[str, Any]:
    if not path.is_file():
        raise WorkspacePreflightError(f"{error_prefix}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspacePreflightError(f"{error_prefix}: {path}") from exc
    if not isinstance(payload, dict):
        raise WorkspacePreflightError(f"{error_prefix}: {path}")
    return payload


def _workspace_selected_bundle_version(bundle_root: Path) -> str | None:
    manifest_path = bundle_root / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        _resolved_path, workspace_manifest = validate_workspace_stub_manifest(bundle_root)
    except InstallError:
        return None
    return workspace_manifest.get("bundle_version")


def _selected_bundle_manifest_path(
    *,
    payload_root: Path,
    payload_manifest: Mapping[str, Any],
    workspace_bundle_root: Path,
) -> Path | None:
    selected_bundle_version = _workspace_selected_bundle_version(workspace_bundle_root)
    try:
        return resolve_payload_bundle_manifest_path(
            payload_root,
            payload_manifest,
            bundle_version=selected_bundle_version,
        )
    except InstallError as exc:
        raise WorkspacePreflightError(str(exc)) from exc


def _run_bootstrap_helper_with_compatibility(
    *,
    helper_path: Path,
    workspace_root: Path,
    command: list[str],
    interaction_mode: str | None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if not _looks_like_legacy_argparse_error(completed):
        return (completed, "contract_v2")

    if interaction_mode == "non_interactive" and _stderr_mentions_unrecognized_argument(completed, "--interaction-mode"):
        # Non-interactive first-write protection must not silently degrade to a
        # legacy helper that ignores the session mode and may write anyway.
        raise WorkspacePreflightError(
            "Current local Sopify helper is too old to safely handle non-interactive bootstrap. "
            "Refresh the local Sopify install and retry."
        )

    unsupported_args = {"--host-id", "--requested-root"}
    if _stderr_mentions_unrecognized_argument(completed, "--interaction-mode"):
        unsupported_args.add("--interaction-mode")

    request_preserving_command = _drop_cli_arg_pairs(command, unsupported_args)
    if request_preserving_command != command:
        request_preserving_completed = subprocess.run(
            request_preserving_command,
            capture_output=True,
            text=True,
            check=False,
        )
        if not _looks_like_legacy_argparse_error(request_preserving_completed):
            return (request_preserving_completed, "legacy_request_preserved")
        if not _stderr_mentions_unrecognized_argument(request_preserving_completed, "--request"):
            return (request_preserving_completed, "legacy_request_preserved")

    legacy_command = [sys.executable, str(helper_path), "--workspace-root", str(workspace_root)]
    legacy_completed = subprocess.run(
        legacy_command,
        capture_output=True,
        text=True,
        check=False,
    )
    return (legacy_completed, "legacy_fallback")


def _looks_like_legacy_argparse_error(completed: subprocess.CompletedProcess[str]) -> bool:
    if completed.returncode == 0:
        return False
    stderr = (completed.stderr or "").strip()
    return "unrecognized arguments:" in stderr and (
        _stderr_mentions_unrecognized_argument(completed, "--request")
        or _stderr_mentions_unrecognized_argument(completed, "--host-id")
        or _stderr_mentions_unrecognized_argument(completed, "--requested-root")
        or _stderr_mentions_unrecognized_argument(completed, "--interaction-mode")
    )


def _stderr_mentions_unrecognized_argument(completed: subprocess.CompletedProcess[str], argument: str) -> bool:
    stderr = (completed.stderr or "").strip()
    return "unrecognized arguments:" in stderr and argument in stderr


def _drop_cli_arg_pairs(command: list[str], unsupported_args: set[str]) -> list[str]:
    if len(command) <= 2:
        return list(command)

    arg_tokens = command[2:]
    if len(arg_tokens) % 2 != 0:
        return list(command)

    trimmed_command = list(command[:2])
    for index in range(0, len(arg_tokens), 2):
        flag = arg_tokens[index]
        value = arg_tokens[index + 1]
        if flag in unsupported_args:
            continue
        trimmed_command.extend([flag, value])
    return trimmed_command


__all__ = ["WorkspacePreflightError", "preflight_workspace_runtime"]
