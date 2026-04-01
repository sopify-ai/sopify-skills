"""Shared distribution facade for repo-local and one-liner installer entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, TextIO

from installer.hosts import iter_installable_hosts
from installer.inspection import build_doctor_payload, build_status_payload
from installer.models import InstallError, InstallResult, InstallTarget, LANGUAGE_DIRECTORY_MAP

SOURCE_CHANNEL_REPO_LOCAL = "repo-local"
DEFAULT_REPO_LOCAL_REF = "working-tree"
DEFAULT_REPO_LOCAL_ASSET = "scripts/install_sopify.py"
WORKSPACE_NOT_REQUESTED_REASON = "WORKSPACE_NOT_REQUESTED"

_CHECK_LABELS = {
    "host_prompt_present": "host prompt",
    "payload_present": "payload",
    "payload_bundle_resolution": "payload bundle",
    "workspace_bundle_manifest": "workspace bundle",
    "workspace_handoff_first": "handoff-first runtime",
    "workspace_preferences_preload": "preferences preload",
    "bundle_smoke": "smoke",
}


@dataclass(frozen=True)
class DistributionSourceMetadata:
    """Resolved source metadata surfaced by distribution entrypoints."""

    resolved_ref: str
    asset_name: str


@dataclass(frozen=True)
class DistributionRequest:
    """Minimal input contract shared by repo-local and remote entrypoints."""

    target: str | None
    workspace: str | None
    ref_override: str | None
    interactive: bool
    source_channel: str
    source_metadata: DistributionSourceMetadata


@dataclass(frozen=True)
class DistributionInstallReport:
    """Public-facing install report produced by the shared distribution facade."""

    request: DistributionRequest
    install_result: InstallResult
    status_payload: dict[str, object]
    doctor_payload: dict[str, object]
    next_step: str


class DistributionError(RuntimeError):
    """Raised when distribution entrypoints cannot complete safely."""

    def __init__(self, *, phase: str, reason_code: str, detail: str, next_step: str) -> None:
        super().__init__(detail)
        self.phase = phase
        self.reason_code = reason_code
        self.detail = detail
        self.next_step = next_step


InstallExecutor = Callable[..., InstallResult]


def default_source_metadata(
    *,
    source_channel: str = SOURCE_CHANNEL_REPO_LOCAL,
    resolved_ref: str = DEFAULT_REPO_LOCAL_REF,
    asset_name: str = DEFAULT_REPO_LOCAL_ASSET,
) -> DistributionSourceMetadata:
    """Return the default repo-local metadata used by local installer entrypoints."""
    return DistributionSourceMetadata(resolved_ref=resolved_ref, asset_name=asset_name)


def run_distribution_install(
    *,
    request: DistributionRequest,
    repo_root: Path,
    home_root: Path | None,
    install_executor: InstallExecutor,
    input_func: Callable[[str], str] = input,
    output_stream: TextIO | None = None,
) -> DistributionInstallReport:
    """Execute the shared install flow and attach post-install verification output."""
    if request.source_channel == SOURCE_CHANNEL_REPO_LOCAL and request.ref_override is not None:
        raise DistributionError(
            phase="input",
            reason_code="REF_OVERRIDE_UNSUPPORTED_FOR_REPO_LOCAL",
            detail="`--ref` is only supported for remote install entrypoints.",
            next_step="Drop `--ref` for repo-local installs, or use root `install.sh` / `install.ps1` for ref-pinned installs.",
        )

    target_value = _resolve_target_value(
        request=request,
        input_func=input_func,
        output_stream=output_stream or sys.stderr,
    )
    resolved_home = (home_root or Path.home()).expanduser().resolve()

    try:
        install_result = install_executor(
            target_value=target_value,
            workspace_value=request.workspace,
            repo_root=repo_root,
            home_root=resolved_home,
        )
    except InstallError as exc:
        raise _map_install_error(exc) from exc

    try:
        status_payload = build_status_payload(home_root=resolved_home, workspace_root=install_result.workspace_root)
        doctor_payload = build_doctor_payload(home_root=resolved_home, workspace_root=install_result.workspace_root)
    except Exception as exc:  # pragma: no cover - defensive wrapper for unexpected verification regressions.
        raise DistributionError(
            phase="verification",
            reason_code="POST_INSTALL_VERIFICATION_FAILED",
            detail=f"Post-install verification failed unexpectedly: {exc}",
            next_step="Rerun the installer. If the failure persists, use the inspect-first path and review the local source snapshot.",
        ) from exc

    return DistributionInstallReport(
        request=request,
        install_result=install_result,
        status_payload=status_payload,
        doctor_payload=doctor_payload,
        next_step=_build_next_step(install_result.target, install_result.workspace_root),
    )


def render_distribution_result(report: DistributionInstallReport) -> str:
    """Render a concise install summary for repo-local and remote entrypoints."""
    install_result = report.install_result
    selected_host = _select_host_status(report.status_payload, install_result.target)
    selected_checks = _select_host_checks(report.doctor_payload, install_result.target)
    workspace_line = _render_workspace_line(install_result)
    lines = [
        "Sopify already current:" if _is_noop_install(install_result) else "Installed Sopify successfully:",
        f"  target: {install_result.target.value}",
        f"  source channel: {report.request.source_channel}",
        f"  resolved source ref: {report.request.source_metadata.resolved_ref}",
        f"  asset name: {report.request.source_metadata.asset_name}",
        f"  host root: {install_result.host_root}",
        f"  payload root: {install_result.payload_root}",
        f"  workspace: {workspace_line}",
        f"  bundle root: {install_result.bundle_root if install_result.bundle_root is not None else '(not requested)'}",
        "",
        "Install actions:",
        f"  host prompt: {install_result.host_install.action}",
        f"  payload: {install_result.payload_install.action}",
        f"  workspace bootstrap: {_workspace_bootstrap_action(install_result)}",
        "",
        "Verification:",
        (
            "  payload bundle: source_kind={source_kind}, reason_code={reason_code}".format(
                source_kind=(selected_host.get("payload_bundle") or {}).get("source_kind", "unresolved"),
                reason_code=(selected_host.get("payload_bundle") or {}).get("reason_code", "GLOBAL_INDEX_CORRUPTED"),
            )
        ),
        (
            "  host state: installed={installed}, configured={configured}, workspace_bundle_healthy={workspace_bundle_healthy}".format(
                installed=selected_host["state"]["installed"],
                configured=selected_host["state"]["configured"],
                workspace_bundle_healthy=selected_host["state"]["workspace_bundle_healthy"],
            )
        ),
    ]
    lines.extend(
        f"  - {_CHECK_LABELS.get(check['check_id'], check['check_id'])}: {check['status']} ({check['reason_code']})"
        for check in selected_checks
    )
    lines.extend(
        [
            "",
            f"  smoke output: {_first_smoke_line(install_result.smoke_output)}",
            f"  overall status: {report.status_payload['state']['overall_status']}",
            "",
            f"Next: {report.next_step}",
        ]
    )
    return "\n".join(lines)


def render_distribution_error(exc: DistributionError) -> str:
    """Render a stable error surface for shell, PowerShell, and repo-local installs."""
    return "\n".join(
        [
            "Sopify install failed:",
            f"  phase: {exc.phase}",
            f"  reason_code: {exc.reason_code}",
            f"  detail: {exc.detail}",
            f"  next_step: {exc.next_step}",
        ]
    )


def _resolve_target_value(
    *,
    request: DistributionRequest,
    input_func: Callable[[str], str],
    output_stream: TextIO,
) -> str:
    if request.target:
        return request.target
    if not request.interactive:
        first_option = _target_options()[0]
        raise DistributionError(
            phase="input",
            reason_code="TARGET_REQUIRED",
            detail="Non-interactive installs must provide `--target <host:lang>`.",
            next_step=f"Re-run the installer with `--target {first_option}`.",
        )
    options = _target_options()
    output_stream.write("Select Sopify install target:\n")
    for index, option in enumerate(options, start=1):
        output_stream.write(f"  {index}. {option}\n")
    answer = input_func("Target number: ").strip()
    if not answer.isdigit():
        raise DistributionError(
            phase="input",
            reason_code="INVALID_TARGET_SELECTION",
            detail=f"Expected a numeric target selection, got: {answer or '(empty)'}",
            next_step=f"Choose one of the numbered options above, or pass `--target {options[0]}` directly.",
        )
    selected_index = int(answer) - 1
    if selected_index < 0 or selected_index >= len(options):
        raise DistributionError(
            phase="input",
            reason_code="INVALID_TARGET_SELECTION",
            detail=f"Target selection {answer} is out of range.",
            next_step=f"Choose a number between 1 and {len(options)}, or pass `--target {options[0]}` directly.",
        )
    return options[selected_index]


def _target_options() -> tuple[str, ...]:
    return tuple(
        f"{capability.host_id}:{language}"
        for capability in iter_installable_hosts()
        for language in LANGUAGE_DIRECTORY_MAP
    )


def _map_install_error(exc: InstallError) -> DistributionError:
    detail = str(exc)
    if detail.startswith("Target must use the format"):
        return DistributionError(
            phase="input",
            reason_code="INVALID_TARGET_FORMAT",
            detail=detail,
            next_step=f"Use one of the supported targets: {', '.join(_target_options())}.",
        )
    if detail.startswith("Unsupported host:"):
        return DistributionError(
            phase="input",
            reason_code="UNSUPPORTED_HOST",
            detail=detail,
            next_step=f"Use one of the supported targets: {', '.join(_target_options())}.",
        )
    if detail.startswith("Unsupported language:"):
        return DistributionError(
            phase="input",
            reason_code="UNSUPPORTED_LANGUAGE",
            detail=detail,
            next_step="Use one of the supported language codes: zh-CN, en-US.",
        )
    if detail.startswith("Workspace does not exist:"):
        return DistributionError(
            phase="input",
            reason_code="WORKSPACE_NOT_FOUND",
            detail=detail,
            next_step="Pass an existing project directory to `--workspace`, or omit the internal prewarm flag and bootstrap on first project trigger instead.",
        )
    if detail.startswith("Workspace is not a directory:"):
        return DistributionError(
            phase="input",
            reason_code="WORKSPACE_NOT_DIRECTORY",
            detail=detail,
            next_step="Pass a project directory to `--workspace`, or omit the internal prewarm flag and bootstrap on first project trigger instead.",
        )
    if detail.startswith("Workspace prewarm requires explicit activation-root selection"):
        return DistributionError(
            phase="install",
            reason_code="WORKSPACE_PREWARM_ROOT_AMBIGUOUS",
            detail=detail,
            next_step="Omit `--workspace` and trigger Sopify inside that project instead. On first activation, choose whether to enable the current directory or the repository root.",
        )
    if detail.startswith("Missing source"):
        return DistributionError(
            phase="install",
            reason_code="INSTALLER_SOURCE_INCOMPLETE",
            detail=detail,
            next_step="Retry from a clean source snapshot or stable release asset.",
        )
    if detail.startswith("Host install verification failed:"):
        return DistributionError(
            phase="install",
            reason_code="HOST_VERIFICATION_FAILED",
            detail=detail,
            next_step="Rerun the installer. If it still fails, inspect the downloaded source snapshot and host home directory permissions.",
        )
    if detail.startswith("Payload verification failed:"):
        return DistributionError(
            phase="install",
            reason_code="PAYLOAD_VERIFICATION_FAILED",
            detail=detail,
            next_step="Rerun the installer. If it still fails, inspect the payload directory under the selected host home root.",
        )
    if detail.startswith("Bundle verification failed:"):
        return DistributionError(
            phase="install",
            reason_code="WORKSPACE_BUNDLE_VERIFICATION_FAILED",
            detail=detail,
            next_step="Trigger Sopify in that project to bootstrap on demand. If the issue persists, refresh the local install and retry.",
        )
    if detail.startswith("Missing bundle smoke script:"):
        return DistributionError(
            phase="verification",
            reason_code="BUNDLE_SMOKE_SCRIPT_MISSING",
            detail=detail,
            next_step="Refresh the payload from a clean release asset or repo-local installer snapshot.",
        )
    if detail.startswith("Bundle smoke check failed:"):
        return DistributionError(
            phase="verification",
            reason_code="BUNDLE_SMOKE_FAILED",
            detail=detail,
            next_step="Rerun the installer. If the failure persists, use the inspect-first path and review the bundle smoke output.",
        )
    return DistributionError(
        phase="install",
        reason_code="INSTALLER_FAILED",
        detail=detail,
        next_step="Rerun the installer. If the failure persists, switch to the inspect-first path and review the source snapshot locally.",
    )


def _build_next_step(target: InstallTarget, workspace_root: Path | None) -> str:
    if workspace_root is None:
        return (
            f"Open {target.host} in any project workspace and trigger Sopify. "
            "Workspace bootstrap will run on first project trigger."
        )
    return f"Open {target.host} in {workspace_root} and trigger Sopify."


def _select_host_status(payload: dict[str, object], target: InstallTarget) -> dict[str, object]:
    for host in payload["hosts"]:
        if host["host_id"] == target.host:
            return host
    raise DistributionError(
        phase="verification",
        reason_code="TARGET_HOST_STATUS_MISSING",
        detail=f"Status payload did not include the selected host: {target.host}",
        next_step="Rerun the installer and verify the host registry declarations are still in sync.",
    )


def _select_host_checks(payload: dict[str, object], target: InstallTarget) -> tuple[dict[str, object], ...]:
    checks = []
    for check in payload["checks"]:
        if check.get("host_id") == target.host:
            checks.append(check)
    return tuple(checks)


def _render_workspace_line(install_result: InstallResult) -> str:
    if install_result.workspace_root is None:
        return "will bootstrap on first project trigger"
    return f"pre-warmed at {install_result.workspace_root}"


def _workspace_bootstrap_action(install_result: InstallResult) -> str:
    if install_result.workspace_bootstrap is None:
        return "not requested"
    return (
        f"{install_result.workspace_bootstrap.action}"
        f" ({install_result.workspace_bootstrap.reason_code})"
    )


def _is_noop_install(install_result: InstallResult) -> bool:
    return (
        install_result.host_install.action == "skipped"
        and install_result.payload_install.action == "skipped"
        and install_result.workspace_root is None
    )


def _first_smoke_line(smoke_output: str) -> str:
    first_line = smoke_output.splitlines()[0].strip() if smoke_output else ""
    return first_line or "(no smoke output)"
