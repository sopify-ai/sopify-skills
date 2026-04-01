"""Global Sopify payload installation and workspace bootstrap helpers."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
from typing import Any

from installer.hosts.base import HostAdapter, read_sopify_version
from installer.models import BootstrapResult, InstallError, InstallPhaseResult
from installer.runtime_bundle import sync_runtime_bundle
from installer.validate import _normalize_payload_bundle_version, resolve_payload_bundle_root, validate_payload_install
from runtime.state import iso_now

PAYLOAD_MANIFEST_FILENAME = "payload-manifest.json"
PAYLOAD_DIRNAME = "sopify"
PAYLOAD_BUNDLES_RELATIVE_PATH = Path("bundles")
PAYLOAD_HELPER_RELATIVE_PATH = Path("helpers") / "bootstrap_workspace.py"
_REQUIRED_BUNDLE_CAPABILITIES = {
    "bundle_role": "control_plane",
    "manifest_first": True,
    "writes_handoff_file": True,
    "clarification_bridge": True,
    "decision_bridge": True,
    "develop_checkpoint_callback": True,
    "develop_resume_context": True,
    "planning_mode_orchestrator": True,
    "preferences_preload": True,
    "runtime_gate": True,
    "runtime_entry_guard": True,
}


def install_global_payload(
    adapter: HostAdapter,
    *,
    repo_root: Path,
    home_root: Path,
) -> InstallPhaseResult:
    """Install or update the host-local Sopify payload used for workspace bootstrap."""
    host_root = adapter.destination_root(home_root)
    payload_root = adapter.payload_root(home_root)
    desired_version = _normalize_payload_bundle_version(_source_payload_version(adapter, repo_root))

    if _payload_is_current(payload_root, desired_version):
        return InstallPhaseResult(
            action="skipped",
            root=payload_root,
            version=desired_version,
            paths=validate_payload_install(payload_root),
        )

    action = "updated" if payload_root.exists() else "installed"
    bundle_root = _install_versioned_runtime_bundle(
        repo_root=repo_root,
        host_root=host_root,
        desired_bundle_version=desired_version,
    )
    _install_bootstrap_helper(repo_root=repo_root, payload_root=payload_root)
    _write_payload_manifest(payload_root=payload_root, bundle_root=bundle_root, payload_version=desired_version)
    return InstallPhaseResult(
        action=action,
        root=payload_root,
        version=desired_version,
        paths=validate_payload_install(payload_root),
    )


def run_workspace_bootstrap(payload_root: Path, workspace_root: Path) -> BootstrapResult:
    """Run the installed helper that prepares a workspace bundle from the global payload."""
    helper_path = payload_root / PAYLOAD_HELPER_RELATIVE_PATH
    if not helper_path.is_file():
        raise InstallError(f"Missing workspace bootstrap helper: {helper_path}")

    completed = subprocess.run(
        [sys.executable, str(helper_path), "--workspace-root", str(workspace_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        details = completed.stderr.strip() or stdout or "invalid helper output"
        raise InstallError(f"Workspace bootstrap produced invalid output: {details}") from exc

    result = BootstrapResult.from_dict(payload)
    if result.reason_code == "ROOT_CONFIRM_REQUIRED":
        raise InstallError(
            "Workspace prewarm requires explicit activation-root selection for this nested repository path. "
            "The internal installer `--workspace` flow does not handle that choice; omit `--workspace` and let "
            "runtime gate ask whether to enable the current directory or the repository root on first project trigger."
        )
    if completed.returncode != 0 or result.action == "failed":
        details = result.message or completed.stderr.strip() or stdout or "unknown bootstrap failure"
        raise InstallError(f"Workspace bootstrap failed: {details}")
    return result


def _payload_is_current(payload_root: Path, desired_version: str | None) -> bool:
    # A payload is current only when the whole vendored bundle still passes the
    # same structural verification used after installation. This prevents an
    # older, partial bundle from being skipped just because the top-level
    # manifest files still exist and their versions happen to match.
    try:
        validate_payload_install(payload_root)
    except InstallError:
        return False

    payload_manifest = _read_json(payload_root / PAYLOAD_MANIFEST_FILENAME)
    try:
        bundle_root = resolve_payload_bundle_root(payload_root)
    except InstallError:
        return False
    bundle_manifest = _read_json(bundle_root / "manifest.json")
    if not payload_manifest or not bundle_manifest:
        return False

    try:
        resolved_bundle_version = _resolved_payload_bundle_version(
            payload_manifest=payload_manifest,
            bundle_manifest=bundle_manifest,
        )
    except InstallError:
        return False

    return payload_manifest.get("payload_version") == desired_version and resolved_bundle_version == bundle_manifest.get(
        "bundle_version"
    )


def _source_payload_version(adapter: HostAdapter, repo_root: Path) -> str | None:
    language_directory = "CN"
    header_path = adapter.source_root(repo_root, language_directory) / adapter.header_filename
    return read_sopify_version(header_path)


def _install_bootstrap_helper(*, repo_root: Path, payload_root: Path) -> Path:
    helper_source = repo_root / "installer" / "bootstrap_workspace.py"
    if not helper_source.is_file():
        raise InstallError(f"Missing bootstrap helper source: {helper_source}")
    helper_target = payload_root / PAYLOAD_HELPER_RELATIVE_PATH
    helper_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(helper_source, helper_target)
    helper_target.chmod(0o755)
    return helper_target


def _install_versioned_runtime_bundle(
    *,
    repo_root: Path,
    host_root: Path,
    desired_bundle_version: str | None,
) -> Path:
    initial_version = _normalize_payload_bundle_version(desired_bundle_version) or "0.0.0-dev"
    bundle_root = sync_runtime_bundle(
        repo_root,
        host_root,
        bundle_dirname=str(Path(PAYLOAD_DIRNAME) / PAYLOAD_BUNDLES_RELATIVE_PATH / initial_version),
    )
    bundle_manifest = _read_json(bundle_root / "manifest.json")
    actual_version = _payload_bundle_version_or_default(bundle_manifest.get("bundle_version"), default=initial_version)
    if actual_version == bundle_root.name:
        return bundle_root

    target_root = bundle_root.parent / actual_version
    if target_root.exists():
        shutil.rmtree(target_root)
    bundle_root.replace(target_root)
    return target_root


def _write_payload_manifest(*, payload_root: Path, bundle_root: Path, payload_version: str | None) -> Path:
    bundle_manifest = _read_json(bundle_root / "manifest.json")
    if not bundle_manifest:
        raise InstallError(f"Missing bundle manifest for payload generation: {bundle_root / 'manifest.json'}")
    bundle_version = _payload_bundle_version_or_default(bundle_manifest.get("bundle_version"), default=bundle_root.name or "0.0.0-dev")
    normalized_payload_version = _normalize_payload_bundle_version(payload_version)
    bundle_manifest_path = PAYLOAD_BUNDLES_RELATIVE_PATH / bundle_version / "manifest.json"

    payload = {
        "schema_version": "1",
        "payload_version": normalized_payload_version or bundle_version,
        "bundle_version": bundle_version,
        "active_version": bundle_version,
        "generated_at": iso_now(),
        "bundles_dir": str(PAYLOAD_BUNDLES_RELATIVE_PATH),
        "default_bundle_dir": ".sopify-runtime",
        "bundle_manifest": str(bundle_manifest_path),
        "bundle_template_dir": str(bundle_manifest_path.parent),
        "helper_entry": str(PAYLOAD_HELPER_RELATIVE_PATH),
        "dependency_model": bundle_manifest.get("dependency_model")
        or {
            "mode": "stdlib_only",
            "python_min": "3.11",
            "host_env_dir": None,
            "runtime_dependencies": [],
        },
        "capabilities": {
            "manifest_first": True,
            "auto_workspace_bootstrap": True,
            "no_silent_downgrade": True,
        },
        # The helper compares only the stable capabilities the host actually depends on.
        "minimum_workspace_manifest": {
            "schema_version": str(bundle_manifest.get("schema_version") or "1"),
            "required_capabilities": dict(_REQUIRED_BUNDLE_CAPABILITIES),
        },
    }

    manifest_path = payload_root / PAYLOAD_MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=manifest_path.parent, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(manifest_path)
    return manifest_path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _payload_bundle_version_or_default(value: Any, *, default: str) -> str:
    normalized = _normalize_payload_bundle_version(value)
    if normalized is not None:
        return normalized
    fallback = _normalize_payload_bundle_version(default)
    if fallback is None:
        raise InstallError("Payload verification failed: bundle_version")
    return fallback


def _resolved_payload_bundle_version(
    *,
    payload_manifest: dict[str, Any],
    bundle_manifest: dict[str, Any],
) -> str | None:
    if str(payload_manifest.get("bundles_dir") or "").strip():
        return _normalize_payload_bundle_version(payload_manifest.get("active_version"))
    for value in (
        payload_manifest.get("bundle_version"),
        payload_manifest.get("active_version"),
        bundle_manifest.get("bundle_version"),
    ):
        normalized = _normalize_payload_bundle_version(value)
        if normalized is not None:
            return normalized
    return None
