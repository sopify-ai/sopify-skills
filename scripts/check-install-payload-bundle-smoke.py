#!/usr/bin/env python3
"""Smoke-check installer, global payload, and vendored bundle in isolation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from installer.hosts import get_host_adapter
from installer.models import InstallError, parse_install_target
from installer.validate import run_bundle_smoke_check, validate_bundle_install, validate_host_install, validate_payload_install


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an isolated smoke check for install -> payload -> bundle bootstrap."
    )
    parser.add_argument(
        "--target",
        default="codex:zh-CN",
        help="Install target in <host:lang> format. Default: codex:zh-CN",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write the structured smoke result as JSON.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary home/workspace for inspection instead of deleting it.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    temp_root = Path(tempfile.mkdtemp(prefix="sopify-install-payload-bundle."))
    try:
        result = run_smoke(target_value=args.target, temp_root=temp_root)
        if args.output_json:
            output_path = Path(args.output_json).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (InstallError, RuntimeError, ValueError) as exc:
        failure = {
            "passed": False,
            "target": args.target,
            "error": str(exc),
            "temp_root": str(temp_root),
        }
        if args.output_json:
            output_path = Path(args.output_json).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if args.keep_temp:
            print(f"Kept temp root: {temp_root}", file=sys.stderr)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def run_smoke(*, target_value: str, temp_root: Path) -> dict[str, Any]:
    target = parse_install_target(target_value)
    adapter = get_host_adapter(target.host)
    temp_home = temp_root / "home"
    workspace_root = temp_root / "workspace"
    temp_home.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    install_stdout = _run_install_cli(target_value=target.value, temp_home=temp_home)
    host_root = adapter.destination_root(temp_home)
    payload_root = adapter.payload_root(temp_home)
    bundle_root = workspace_root / ".sopify-runtime"
    helper_path = payload_root / "helpers" / "bootstrap_workspace.py"

    host_paths = validate_host_install(adapter, home_root=temp_home)
    payload_paths = validate_payload_install(payload_root)

    if bundle_root.exists():
        raise RuntimeError("Workspace bundle should not exist before trigger-time bootstrap.")

    bootstrap_stdout = _run_workspace_bootstrap(helper_path=helper_path, workspace_root=workspace_root)
    bundle_paths = validate_bundle_install(bundle_root)
    smoke_stdout = run_bundle_smoke_check(bundle_root)
    bundle_manifest = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
    default_entry = str(bundle_manifest.get("default_entry") or "")
    plan_only_entry = str(bundle_manifest.get("plan_only_entry") or "")
    entry_guard = bundle_manifest.get("limits", {}).get("entry_guard", {})

    if default_entry != "scripts/sopify_runtime.py":
        raise RuntimeError(f"Unexpected default_entry: {default_entry!r}")
    if plan_only_entry != "scripts/go_plan_runtime.py":
        raise RuntimeError(f"Unexpected plan_only_entry: {plan_only_entry!r}")
    if entry_guard.get("default_runtime_entry") != default_entry:
        raise RuntimeError("Manifest limits.entry_guard.default_runtime_entry drifted from default_entry.")

    return {
        "passed": True,
        "target": target.value,
        "temp_root": str(temp_root),
        "temp_home": str(temp_home),
        "workspace_root": str(workspace_root),
        "host_root": str(host_root),
        "payload_root": str(payload_root),
        "bundle_root": str(bundle_root),
        "checks": {
            "single_install_command_only": True,
            "workspace_bundle_absent_before_trigger": True,
            "runtime_bootstrap_on_project_trigger": True,
            "default_runtime_entry_preserved": True,
            "plan_only_helper_preserved": True,
            "bundle_smoke_passed": True,
        },
        "manifest": {
            "default_entry": default_entry,
            "plan_only_entry": plan_only_entry,
            "entry_guard_default_runtime_entry": entry_guard.get("default_runtime_entry"),
        },
        "install_stdout": install_stdout,
        "bootstrap_stdout": bootstrap_stdout,
        "bundle_smoke_stdout": smoke_stdout,
        "verified_paths": {
            "host": [str(path) for path in host_paths],
            "payload": [str(path) for path in payload_paths],
            "bundle": [str(path) for path in bundle_paths],
        },
    }


def _run_install_cli(*, target_value: str, temp_home: Path) -> str:
    env = dict(os.environ)
    env["HOME"] = str(temp_home)
    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install-sopify.sh"), "--target", target_value],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown install failure"
        raise InstallError(f"Installer CLI failed: {details}")
    return completed.stdout.strip()


def _run_workspace_bootstrap(*, helper_path: Path, workspace_root: Path) -> str:
    if not helper_path.is_file():
        raise InstallError(f"Missing installed workspace helper: {helper_path}")
    completed = subprocess.run(
        [sys.executable, str(helper_path), "--workspace-root", str(workspace_root)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown bootstrap failure"
        raise InstallError(f"Workspace bootstrap helper failed: {details}")
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
