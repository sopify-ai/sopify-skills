"""Shared installer models and target parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

LANGUAGE_DIRECTORY_MAP = {
    "zh-CN": "CN",
    "en-US": "EN",
}


class InstallError(RuntimeError):
    """Raised when the installer cannot complete safely."""


class SupportTier(StrEnum):
    """Stable product-support tiers for host registry declarations."""

    DEEP_VERIFIED = "deep_verified"
    BASELINE_SUPPORTED = "baseline_supported"
    DOCUMENTED_ONLY = "documented_only"
    EXPERIMENTAL = "experimental"


class EntryMode(StrEnum):
    """Stable entry modes advertised by the host registry."""

    PROMPT_ONLY = "prompt_only"
    LAUNCHER = "launcher"
    HOOKS = "hooks"
    APP_SERVER = "app_server"
    MANUAL = "manual"


class FeatureId(StrEnum):
    """Stable feature identifiers shared by registry, status, and docs."""

    PROMPT_INSTALL = "prompt_install"
    PAYLOAD_INSTALL = "payload_install"
    WORKSPACE_BOOTSTRAP = "workspace_bootstrap"
    RUNTIME_GATE = "runtime_gate"
    PREFERENCES_PRELOAD = "preferences_preload"
    HANDOFF_FIRST = "handoff_first"
    HOST_BRIDGE = "host_bridge"
    SMOKE_VERIFIED = "smoke_verified"


@dataclass(frozen=True)
class HostCapability:
    """Product-facing capability declaration for one supported host."""

    host_id: str
    support_tier: SupportTier
    install_enabled: bool
    declared_features: tuple[FeatureId, ...]
    verified_features: tuple[FeatureId, ...]
    entry_modes: tuple[EntryMode, ...]
    doctor_checks: tuple[str, ...]
    smoke_targets: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "host_id": self.host_id,
            "support_tier": self.support_tier.value,
            "install_enabled": self.install_enabled,
            "declared_features": [feature.value for feature in self.declared_features],
            "verified_features": [feature.value for feature in self.verified_features],
            "entry_modes": [mode.value for mode in self.entry_modes],
            "doctor_checks": list(self.doctor_checks),
            "smoke_targets": list(self.smoke_targets),
        }


@dataclass(frozen=True)
class InstallTarget:
    """Normalized installer target."""

    host: str
    language: str

    @property
    def value(self) -> str:
        return f"{self.host}:{self.language}"

    @property
    def language_directory(self) -> str:
        return LANGUAGE_DIRECTORY_MAP[self.language]


@dataclass(frozen=True)
class InstallResult:
    """Summary of a completed Sopify installation."""

    target: InstallTarget
    workspace_root: Path | None
    host_root: Path
    payload_root: Path
    bundle_root: Path | None
    host_install: "InstallPhaseResult"
    payload_install: "InstallPhaseResult"
    workspace_bootstrap: "BootstrapResult | None"
    smoke_output: str


@dataclass(frozen=True)
class InstallPhaseResult:
    """Result for one installer-owned phase such as host or payload setup."""

    action: str
    root: Path
    version: str | None
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class BootstrapResult:
    """Structured result returned by the workspace bootstrap helper."""

    action: str
    state: str
    reason_code: str
    workspace_root: Path
    bundle_root: Path
    from_version: str | None
    to_version: str | None
    message: str

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "BootstrapResult":
        return cls(
            action=str(data.get("action") or "failed"),
            state=str(data.get("state") or "INCOMPATIBLE"),
            reason_code=str(data.get("reason_code") or "UNKNOWN"),
            workspace_root=Path(str(data.get("workspace_root") or ".")),
            bundle_root=Path(str(data.get("bundle_root") or ".")),
            from_version=_string_or_none(data.get("from_version")),
            to_version=_string_or_none(data.get("to_version")),
            message=str(data.get("message") or ""),
        )


def parse_install_target(raw_value: str) -> InstallTarget:
    """Parse a CLI target like `codex:zh-CN`."""
    value = raw_value.strip()
    host, separator, language = value.partition(":")
    if not separator:
        raise InstallError("Target must use the format <host:lang>, for example codex:zh-CN")
    from installer.hosts import get_host_capability

    try:
        capability = get_host_capability(host)
    except ValueError as exc:
        raise InstallError(f"Unsupported host: {host}") from exc
    if not capability.install_enabled:
        raise InstallError(f"Unsupported host: {host}")
    if language not in LANGUAGE_DIRECTORY_MAP:
        raise InstallError(f"Unsupported language: {language}")
    return InstallTarget(host=host, language=language)


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None
