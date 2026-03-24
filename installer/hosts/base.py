"""Base host adapter and shared install helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil

from installer.models import HostCapability, InstallError, InstallPhaseResult

_IGNORE_PATTERNS = shutil.ignore_patterns(".DS_Store", "Thumbs.db", "__pycache__")
_SOPIFY_VERSION_RE = re.compile(r"^<!--\s*SOPIFY_VERSION:\s*(?P<version>.+?)\s*-->$", re.MULTILINE)


@dataclass(frozen=True)
class HostAdapter:
    """Host-specific layout for Sopify prompt-layer assets."""

    host_name: str
    source_dirname: str
    destination_dirname: str
    header_filename: str

    def source_root(self, repo_root: Path, language_directory: str) -> Path:
        return repo_root / self.source_dirname / "Skills" / language_directory

    def destination_root(self, home_root: Path) -> Path:
        return home_root / self.destination_dirname

    def payload_root(self, home_root: Path) -> Path:
        return self.destination_root(home_root) / "sopify"

    def expected_paths(self, home_root: Path) -> tuple[Path, ...]:
        root = self.destination_root(home_root)
        return (
            root / self.header_filename,
            root / "skills" / "sopify" / "analyze" / "SKILL.md",
            root / "skills" / "sopify" / "design" / "SKILL.md",
        )

    def expected_payload_paths(self, home_root: Path) -> tuple[Path, ...]:
        payload_root = self.payload_root(home_root)
        return (
            payload_root / "payload-manifest.json",
            payload_root / "bundle" / "manifest.json",
            payload_root / "helpers" / "bootstrap_workspace.py",
        )


@dataclass(frozen=True)
class HostRegistration:
    """Registry entry combining layout adapter and product capability metadata."""

    adapter: HostAdapter
    capability: HostCapability

    def __post_init__(self) -> None:
        if self.adapter.host_name != self.capability.host_id:
            raise ValueError(
                f"Host registration mismatch: adapter={self.adapter.host_name}, capability={self.capability.host_id}"
            )


def install_host_assets(
    adapter: HostAdapter,
    *,
    repo_root: Path,
    home_root: Path,
    language_directory: str,
) -> InstallPhaseResult:
    """Install or update Sopify prompt-layer assets for one host."""
    source_root = adapter.source_root(repo_root, language_directory)
    header_source = source_root / adapter.header_filename
    skills_source = source_root / "skills" / "sopify"
    if not header_source.is_file():
        raise InstallError(f"Missing source header file: {header_source}")
    if not skills_source.is_dir():
        raise InstallError(f"Missing source skills directory: {skills_source}")

    destination_root = adapter.destination_root(home_root)
    expected_paths = adapter.expected_paths(home_root)
    source_version = read_sopify_version(header_source)
    destination_header = destination_root / adapter.header_filename
    destination_version = read_sopify_version(destination_header)
    if source_version is not None and source_version == destination_version and all(path.exists() for path in expected_paths):
        return InstallPhaseResult(
            action="skipped",
            root=destination_root,
            version=source_version,
            paths=expected_paths,
        )

    action = "updated" if destination_root.exists() else "installed"
    destination_root.mkdir(parents=True, exist_ok=True)

    header_destination = destination_root / adapter.header_filename
    shutil.copy2(header_source, header_destination)

    skills_destination = destination_root / "skills" / "sopify"
    if skills_destination.exists():
        shutil.rmtree(skills_destination)
    skills_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skills_source, skills_destination, ignore=_IGNORE_PATTERNS)

    return InstallPhaseResult(
        action=action,
        root=destination_root,
        version=source_version,
        paths=adapter.expected_paths(home_root),
    )


def read_sopify_version(path: Path) -> str | None:
    """Read the Sopify version header from a host prompt file when present."""
    if not path.is_file():
        return None
    match = _SOPIFY_VERSION_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        return None
    return match.group("version").strip()
