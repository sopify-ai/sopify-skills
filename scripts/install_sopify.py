#!/usr/bin/env python3
"""Install Sopify host prompts and the global payload, then optionally prewarm a workspace."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from installer.distribution import (
    DistributionError,
    DistributionRequest,
    DistributionSourceMetadata,
    render_distribution_error,
    render_distribution_result,
    run_distribution_install,
)
from installer.hosts import get_host_adapter, iter_installable_hosts
from installer.hosts.base import install_host_assets
from installer.models import BootstrapResult, InstallError, InstallResult, LANGUAGE_DIRECTORY_MAP, parse_install_target
from installer.payload import install_global_payload, run_workspace_bootstrap
from installer.validate import (
    resolve_payload_bundle_root,
    run_bundle_smoke_check,
    validate_bundle_install,
    validate_host_install,
    validate_payload_install,
    validate_workspace_stub_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    supported_targets = ", ".join(
        f"{capability.host_id}:{language}"
        for capability in iter_installable_hosts()
        for language in LANGUAGE_DIRECTORY_MAP
    )
    parser = argparse.ArgumentParser(description="Install Sopify into a target workspace and host environment.")
    parser.add_argument(
        "--target",
        default=None,
        help=f"Install target in <host:lang> format. Required in non-interactive mode. Supported: {supported_targets}",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help=(
            "Optional internal-only workspace prewarm path. Default user flow is to install the host prompt and "
            "global payload first, then let runtime gate bootstrap `.sopify-runtime/` on the first project trigger."
        ),
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Optional source ref override for remote install entrypoints. Not supported for repo-local installs.",
    )
    parser.add_argument("--source-channel", default="repo-local", help=argparse.SUPPRESS)
    parser.add_argument("--source-resolved-ref", default="working-tree", help=argparse.SUPPRESS)
    parser.add_argument("--source-asset-name", default="scripts/install_sopify.py", help=argparse.SUPPRESS)
    return parser


def run_install(*, target_value: str, workspace_value: str | None, repo_root: Path, home_root: Path | None = None) -> InstallResult:
    target = parse_install_target(target_value)
    workspace_root = Path(workspace_value).expanduser().resolve() if workspace_value is not None else None
    if workspace_root is not None and not workspace_root.exists():
        raise InstallError(f"Workspace does not exist: {workspace_root}")
    if workspace_root is not None and not workspace_root.is_dir():
        raise InstallError(f"Workspace is not a directory: {workspace_root}")

    resolved_home = (home_root or Path.home()).expanduser().resolve()
    adapter = get_host_adapter(target.host)

    host_install = install_host_assets(
        adapter,
        repo_root=repo_root,
        home_root=resolved_home,
        language_directory=target.language_directory,
    )
    payload_install = install_global_payload(adapter, repo_root=repo_root, home_root=resolved_home)
    verified_host_paths = validate_host_install(adapter, home_root=resolved_home)
    verified_payload_paths = validate_payload_install(payload_install.root)
    smoke_output = run_bundle_smoke_check(
        resolve_payload_bundle_root(payload_install.root),
        payload_manifest_path=payload_install.root / "payload-manifest.json",
    )

    workspace_bootstrap: BootstrapResult | None = None
    bundle_root: Path | None = None
    if workspace_root is not None:
        workspace_bootstrap = run_workspace_bootstrap(payload_install.root, workspace_root)
        bundle_root = workspace_bootstrap.bundle_root
        validate_workspace_stub_manifest(bundle_root)

    return InstallResult(
        target=target,
        workspace_root=workspace_root,
        host_root=adapter.destination_root(resolved_home),
        payload_root=payload_install.root,
        bundle_root=bundle_root,
        host_install=host_install.__class__(
            action=host_install.action,
            root=host_install.root,
            version=host_install.version,
            paths=tuple(dict.fromkeys((*host_install.paths, *verified_host_paths))),
        ),
        payload_install=payload_install.__class__(
            action=payload_install.action,
            root=payload_install.root,
            version=payload_install.version,
            paths=tuple(dict.fromkeys((*payload_install.paths, *verified_payload_paths))),
        ),
        workspace_bootstrap=workspace_bootstrap,
        smoke_output=smoke_output,
    )


def render_result(result: InstallResult) -> str:
    is_noop_install = (
        result.host_install.action == "skipped"
        and result.payload_install.action == "skipped"
        and result.workspace_root is None
    )
    lines = [
        "Sopify already current:" if is_noop_install else "Installed Sopify successfully:",
        f"  target: {result.target.value}",
        f"  host root: {result.host_root}",
        f"  payload root: {result.payload_root}",
        f"  workspace: {result.workspace_root if result.workspace_root is not None else '(not requested)'}",
        f"  bundle root: {result.bundle_root if result.bundle_root is not None else '(not requested)'}",
        "",
        "Host:",
        f"  action: {result.host_install.action}",
        f"  version: {result.host_install.version or 'unknown'}",
    ]
    lines.extend(f"  - {path}" for path in result.host_install.paths)
    lines.extend(
        [
            "",
            "Payload:",
            f"  action: {result.payload_install.action}",
            f"  version: {result.payload_install.version or 'unknown'}",
        ]
    )
    lines.extend(f"  - {path}" for path in result.payload_install.paths)
    lines.append("")
    lines.append("Workspace:")
    if result.workspace_bootstrap is None:
        lines.append("  action: skipped")
        lines.append("  reason: workspace bootstrap not requested")
    else:
        lines.extend(
            [
                f"  action: {result.workspace_bootstrap.action}",
                f"  state: {result.workspace_bootstrap.state}",
                f"  reason: {result.workspace_bootstrap.reason_code}",
                f"  message: {result.workspace_bootstrap.message}",
            ]
        )
        if result.workspace_bootstrap.bundle_root != Path("."):
            lines.append(f"  - {result.workspace_bootstrap.bundle_root}")
    lines.extend(
        [
            "",
            "Smoke check:",
            f"  {result.smoke_output}",
            "",
            "Next:",
        ]
    )
    if result.workspace_root is None:
        if is_noop_install:
            lines.append("  No reinstall needed. Trigger Sopify inside any project workspace to bootstrap `.sopify-runtime/` on demand.")
        else:
            lines.append("  Trigger Sopify inside any project workspace to bootstrap `.sopify-runtime/` on demand.")
    else:
        lines.append("  Reopen the workspace in the selected host and use Sopify commands or plain requests.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    source_metadata = DistributionSourceMetadata(
        resolved_ref=args.source_resolved_ref,
        asset_name=args.source_asset_name,
    )
    request = DistributionRequest(
        target=args.target,
        workspace=args.workspace,
        ref_override=args.ref,
        interactive=sys.stdin.isatty() and sys.stdout.isatty(),
        source_channel=args.source_channel,
        source_metadata=source_metadata,
    )

    try:
        report = run_distribution_install(
            request=request,
            repo_root=REPO_ROOT,
            home_root=None,
            install_executor=run_install,
        )
    except DistributionError as exc:
        print(render_distribution_error(exc), file=sys.stderr)
        return 1
    except InstallError as exc:
        print(f"Install failed: {exc}", file=sys.stderr)
        return 1

    print(render_distribution_result(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
