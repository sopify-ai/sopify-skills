"""Post-install validation helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess

from installer.hosts.base import HostAdapter
from installer.models import InstallError


def validate_host_install(adapter: HostAdapter, *, home_root: Path) -> tuple[Path, ...]:
    """Ensure the expected host-side files exist after installation."""
    expected_paths = adapter.expected_paths(home_root)
    missing = [path for path in expected_paths if not path.exists()]
    if missing:
        raise InstallError(f"Host install verification failed: {missing[0]}")
    return expected_paths


def validate_bundle_install(bundle_root: Path) -> tuple[Path, ...]:
    """Ensure the synced bundle contains the minimum required assets."""
    expected_paths = expected_bundle_paths(bundle_root)
    missing = [path for path in expected_paths if not path.exists()]
    if missing:
        raise InstallError(f"Bundle verification failed: {missing[0]}")
    return expected_paths


def validate_payload_install(payload_root: Path) -> tuple[Path, ...]:
    """Ensure the host-local Sopify payload contains its manifest, helper, and bundle template."""
    expected_paths = (
        payload_root / "payload-manifest.json",
        payload_root / "helpers" / "bootstrap_workspace.py",
        *expected_bundle_paths(payload_root / "bundle"),
    )
    missing = [path for path in expected_paths if not path.exists()]
    if missing:
        raise InstallError(f"Payload verification failed: {missing[0]}")
    return expected_paths


def run_bundle_smoke_check(bundle_root: Path) -> str:
    """Run the vendored bundle smoke check and return its stdout."""
    smoke_script = bundle_root / "scripts" / "check-runtime-smoke.sh"
    if not smoke_script.is_file():
        raise InstallError(f"Missing bundle smoke script: {smoke_script}")

    completed = subprocess.run(
        ["bash", str(smoke_script)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown smoke failure"
        raise InstallError(f"Bundle smoke check failed: {details}")
    return completed.stdout.strip()


def expected_bundle_paths(bundle_root: Path) -> tuple[Path, ...]:
    """Return the stable set of files every Sopify bundle must contain."""
    return (
        bundle_root / "manifest.json",
        bundle_root / "runtime" / "__init__.py",
        bundle_root / "runtime" / "clarification_bridge.py",
        bundle_root / "runtime" / "cli_interactive.py",
        bundle_root / "runtime" / "develop_checkpoint.py",
        bundle_root / "runtime" / "decision_bridge.py",
        bundle_root / "runtime" / "gate.py",
        bundle_root / "runtime" / "preferences.py",
        bundle_root / "runtime" / "workspace_preflight.py",
        bundle_root / "scripts" / "sopify_runtime.py",
        bundle_root / "scripts" / "runtime_gate.py",
        bundle_root / "scripts" / "clarification_bridge_runtime.py",
        bundle_root / "scripts" / "develop_checkpoint_runtime.py",
        bundle_root / "scripts" / "decision_bridge_runtime.py",
        bundle_root / "scripts" / "preferences_preload_runtime.py",
        bundle_root / "scripts" / "check-runtime-smoke.sh",
        bundle_root / "tests" / "test_runtime.py",
    )
