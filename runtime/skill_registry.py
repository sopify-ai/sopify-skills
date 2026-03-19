"""Catalog-first skill discovery for Sopify runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence
import re

from ._yaml import load_yaml
from .builtin_catalog import load_builtin_skills
from .models import RuntimeConfig, SkillMeta
from .skill_schema import SkillManifestError, normalize_skill_manifest

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillRegistry:
    """Discover runtime-owned builtin skills and external extensions."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        repo_root: Path | None = None,
        user_home: Path | None = None,
        host_name: str | None = None,
    ) -> None:
        self.config = config
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.user_home = user_home or Path.home()
        self.host_name = (host_name or os.environ.get("SOPIFY_HOST_NAME") or os.environ.get("SOPIFY_HOST") or "codex").strip().lower()

    def discover(self) -> tuple[SkillMeta, ...]:
        discovered: Dict[str, SkillMeta] = {}
        for skill in load_builtin_skills(repo_root=self.repo_root, language=self.config.language):
            discovered[skill.skill_id] = skill

        for root, source in self._search_roots():
            if not root.exists():
                continue
            for skill in self._discover_under_root(root, source):
                existing = discovered.get(skill.skill_id)
                if existing is None:
                    discovered[skill.skill_id] = skill
                    continue
                # External skills may only replace builtin ids through an explicit manifest opt-in.
                if existing.source == "builtin" and _should_override_builtin(skill):
                    discovered[skill.skill_id] = skill
        return tuple(discovered.values())

    def _search_roots(self) -> list[tuple[Path, str]]:
        workspace_roots = [
            # Public aliases first (same-tier precedence).
            (self.config.workspace_root / ".agents" / "skills", "workspace"),
            (self.config.workspace_root / ".gemini" / "skills", "workspace"),
            # Generic project-level skills directory.
            (self.config.workspace_root / "skills", "project"),
            # Legacy Sopify private path kept for compatibility.
            (self.config.workspace_root / self.config.plan_directory / "skills", "workspace"),
        ]
        user_roots = [
            # Public aliases first (same-tier precedence).
            (self.user_home / ".agents" / "skills", "user"),
            (self.user_home / ".gemini" / "skills", "user"),
            # Host-private legacy paths.
            (self.user_home / ".codex" / "skills", "user"),
            (self.user_home / ".claude" / "skills", "user"),
        ]
        return [*workspace_roots, *user_roots]

    def _discover_under_root(self, root: Path, source: str) -> Iterable[SkillMeta]:
        for skill_file in sorted(root.rglob("SKILL.md")):
            skill = self._read_skill(skill_file, source)
            if skill is not None:
                yield skill

    def _read_skill(self, skill_file: Path, source: str) -> Optional[SkillMeta]:
        text = skill_file.read_text(encoding="utf-8")
        front_matter = _parse_front_matter(text)
        skill_dir = skill_file.parent
        raw_manifest = _load_manifest(skill_dir / "skill.yaml")
        try:
            manifest = normalize_skill_manifest(raw_manifest)
        except SkillManifestError:
            return None
        skill_id = str(
            manifest.get("id")
            or front_matter.get("name")
            or skill_dir.name
        )
        name = str(front_matter.get("name") or manifest.get("name") or skill_id)
        description = str(front_matter.get("description") or manifest.get("description") or "")
        runtime_entry = _resolve_runtime_entry(skill_dir, manifest, skill_id, self.repo_root)
        mode = _resolve_mode(raw_manifest, manifest, skill_file=skill_file, runtime_entry=runtime_entry)
        triggers = _string_tuple(manifest.get("triggers"))
        metadata = _load_metadata(raw_manifest, manifest)
        entry_kind = _resolve_entry_kind(manifest, runtime_entry)
        handoff_kind = _string_or_none(manifest.get("handoff_kind"))
        contract_version = _string_or_default(manifest.get("contract_version"), default="1")
        supports_routes = _string_tuple(manifest.get("supports_routes"))
        tools = _string_tuple(manifest.get("tools"))
        disallowed_tools = _string_tuple(manifest.get("disallowed_tools"))
        allowed_paths = _string_tuple(manifest.get("allowed_paths"))
        requires_network = bool(manifest.get("requires_network", False))
        host_support = _string_tuple(manifest.get("host_support"))
        permission_mode = _string_or_default(manifest.get("permission_mode"), default="default")
        if host_support and not _is_host_supported(host_support=host_support, active_host=self.host_name):
            return None

        return SkillMeta(
            skill_id=skill_id,
            name=name,
            description=description,
            path=skill_file,
            source=source,
            mode=mode,
            runtime_entry=runtime_entry,
            triggers=triggers,
            metadata=metadata,
            entry_kind=entry_kind,
            handoff_kind=handoff_kind,
            contract_version=contract_version,
            supports_routes=supports_routes,
            tools=tools,
            disallowed_tools=disallowed_tools,
            allowed_paths=allowed_paths,
            requires_network=requires_network,
            host_support=host_support,
            permission_mode=permission_mode,
        )


def _parse_front_matter(text: str) -> dict[str, object]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    data = load_yaml(match.group(1))
    return data if isinstance(data, dict) else {}


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    data = load_yaml(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _resolve_runtime_entry(
    skill_dir: Path,
    manifest: Mapping[str, object],
    skill_id: str,
    repo_root: Path,
) -> Path | None:
    raw_entry = manifest.get("runtime_entry")
    if isinstance(raw_entry, str) and raw_entry:
        candidate = (skill_dir / raw_entry).resolve()
        if candidate.exists():
            return candidate
    for filename in (f"{skill_id.replace('-', '_')}_runtime.py", f"{skill_id.replace('-', '_')}.py"):
        candidate = repo_root / "scripts" / filename
        if candidate.exists():
            return candidate.resolve()
    return None


def _infer_mode(skill_file: Path, runtime_entry: Path | None) -> str:
    if runtime_entry is not None:
        return "runtime"
    parts = {part.lower() for part in skill_file.parts}
    if "sopify" in parts:
        return "workflow"
    return "advisory"


def _load_metadata(raw_manifest: Mapping[str, object], manifest: Mapping[str, object]) -> dict[str, object]:
    metadata = dict(manifest.get("metadata") or {})
    if "override_builtin" in raw_manifest and "override_builtin" not in metadata:
        metadata["override_builtin"] = raw_manifest.get("override_builtin")
    return metadata


def _resolve_mode(
    raw_manifest: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    skill_file: Path,
    runtime_entry: Path | None,
) -> str:
    if "mode" in raw_manifest:
        return str(manifest.get("mode") or "advisory")
    return _infer_mode(skill_file, runtime_entry)


def _resolve_entry_kind(manifest: Mapping[str, object], runtime_entry: Path | None) -> str | None:
    raw_entry_kind = _string_or_none(manifest.get("entry_kind"))
    if runtime_entry is None:
        return raw_entry_kind
    if raw_entry_kind:
        return raw_entry_kind
    if runtime_entry.suffix == ".py":
        return "python"
    return None


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _string_or_default(value: object, *, default: str) -> str:
    normalized = _string_or_none(value)
    return normalized or default


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    result.append(normalized)
        return tuple(result)
    return ()


def _should_override_builtin(skill: SkillMeta) -> bool:
    raw_value = skill.metadata.get("override_builtin")
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _is_host_supported(*, host_support: tuple[str, ...], active_host: str) -> bool:
    if not host_support:
        return True
    normalized = {item.strip().lower() for item in host_support if item.strip()}
    if not normalized:
        return True
    if "*" in normalized or "all" in normalized:
        return True
    return active_host in normalized
