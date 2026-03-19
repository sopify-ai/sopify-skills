"""Skill package schema helpers for manifest normalization and validation."""

from __future__ import annotations

from typing import Any, Mapping

SKILL_SCHEMA_VERSION = "1"
SKILL_MODES = ("advisory", "workflow", "runtime")
SKILL_PERMISSION_MODES = ("default", "host", "runtime", "dual")


class SkillManifestError(ValueError):
    """Raised when `skill.yaml` does not satisfy the minimum schema."""


def normalize_skill_manifest(raw_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and validate a `skill.yaml` payload."""
    manifest = dict(raw_manifest)

    normalized: dict[str, Any] = {
        "schema_version": str(manifest.get("schema_version") or SKILL_SCHEMA_VERSION),
        "id": _optional_string(manifest.get("id")),
        "name": _optional_string(manifest.get("name")),
        "description": _optional_string(manifest.get("description")),
        "mode": _normalize_mode(manifest.get("mode")),
        "runtime_entry": _optional_string(manifest.get("runtime_entry")),
        "entry_kind": _optional_string(manifest.get("entry_kind")),
        "handoff_kind": _optional_string(manifest.get("handoff_kind")),
        "contract_version": _normalize_contract_version(manifest.get("contract_version")),
        "supports_routes": _normalize_string_list(manifest.get("supports_routes"), field_name="supports_routes"),
        "triggers": _normalize_string_list(manifest.get("triggers"), field_name="triggers"),
        "tools": _normalize_string_list(manifest.get("tools"), field_name="tools"),
        "disallowed_tools": _normalize_string_list(manifest.get("disallowed_tools"), field_name="disallowed_tools"),
        "allowed_paths": _normalize_string_list(manifest.get("allowed_paths"), field_name="allowed_paths"),
        "requires_network": _normalize_bool(manifest.get("requires_network"), field_name="requires_network"),
        "host_support": _normalize_string_list(manifest.get("host_support"), field_name="host_support"),
        "permission_mode": _normalize_permission_mode(manifest.get("permission_mode")),
        "metadata": _normalize_mapping(manifest.get("metadata"), field_name="metadata"),
        "override_builtin": _normalize_optional_bool(manifest.get("override_builtin"), field_name="override_builtin"),
        "names": _normalize_localized_mapping(manifest.get("names"), field_name="names"),
        "descriptions": _normalize_localized_mapping(manifest.get("descriptions"), field_name="descriptions"),
    }
    return normalized


def _normalize_mode(raw_value: Any) -> str:
    value = _optional_string(raw_value) or "advisory"
    if value not in SKILL_MODES:
        raise SkillManifestError(f"Invalid mode: {value!r}")
    return value


def _normalize_permission_mode(raw_value: Any) -> str:
    value = _optional_string(raw_value) or "default"
    if value not in SKILL_PERMISSION_MODES:
        raise SkillManifestError(f"Invalid permission_mode: {value!r}")
    return value


def _normalize_contract_version(raw_value: Any) -> str:
    value = _optional_string(raw_value)
    return value or "1"


def _normalize_string_list(raw_value: Any, *, field_name: str) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if isinstance(raw_value, str):
        value = raw_value.strip()
        return (value,) if value else ()
    if not isinstance(raw_value, (list, tuple)):
        raise SkillManifestError(f"{field_name} must be a string or list of strings")
    values: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise SkillManifestError(f"{field_name} must contain only strings")
        value = _optional_string(item)
        if value:
            values.append(value)
    return tuple(values)


def _normalize_mapping(raw_value: Any, *, field_name: str) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, Mapping):
        raise SkillManifestError(f"{field_name} must be a mapping")
    return dict(raw_value)


def _normalize_localized_mapping(raw_value: Any, *, field_name: str) -> dict[str, str]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, Mapping):
        raise SkillManifestError(f"{field_name} must be a mapping of language to string")
    result: dict[str, str] = {}
    for key, value in raw_value.items():
        lang = _optional_string(key)
        text = _optional_string(value)
        if not lang or not text:
            continue
        result[lang] = text
    return result


def _normalize_bool(raw_value: Any, *, field_name: str) -> bool:
    if raw_value is None:
        return False
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        value = raw_value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    raise SkillManifestError(f"{field_name} must be a boolean")


def _normalize_optional_bool(raw_value: Any, *, field_name: str) -> bool | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        value = raw_value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    raise SkillManifestError(f"{field_name} must be a boolean when provided")


def _optional_string(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        return None
    value = raw_value.strip()
    return value or None
