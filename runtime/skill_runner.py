"""Runtime skill invocation helpers."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from .models import SkillMeta


class SkillExecutionError(RuntimeError):
    """Raised when a runtime skill cannot be executed safely."""


_PERMISSION_MODES = {"default", "host", "runtime", "dual"}


def run_runtime_skill(skill: SkillMeta, *, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Invoke a runtime skill through a strict Python entry convention.

    The runtime only supports Python modules exposing either `run_skill` or
    `run_<skill_id>_runtime`.
    """
    if skill.mode != "runtime" or skill.runtime_entry is None:
        raise SkillExecutionError(f"Skill is not executable at runtime: {skill.skill_id}")
    if skill.runtime_entry.suffix != ".py":
        raise SkillExecutionError(f"Unsupported runtime entry type: {skill.runtime_entry}")
    _validate_runtime_skill_permissions(skill)

    module = _load_module(skill.runtime_entry, skill.skill_id)
    candidate_names = ("run_skill", f"run_{skill.skill_id.replace('-', '_')}_runtime")
    for name in candidate_names:
        entry = getattr(module, name, None)
        if callable(entry):
            result = entry(**payload)
            if isinstance(result, Mapping):
                return dict(result)
            if hasattr(result, "to_dict"):
                return result.to_dict()
            return {"result": result}
    raise SkillExecutionError(
        f"Runtime entry missing supported callable for {skill.skill_id}: {', '.join(candidate_names)}"
    )


def _validate_runtime_skill_permissions(skill: SkillMeta) -> None:
    permission_mode = str(skill.permission_mode or "default").strip().lower()
    if permission_mode not in _PERMISSION_MODES:
        raise SkillExecutionError(f"Unsupported permission mode for {skill.skill_id}: {skill.permission_mode!r}")
    if not _is_host_supported(skill):
        active_host = _active_host_name()
        raise SkillExecutionError(
            f"Host `{active_host}` is not allowed to execute runtime skill `{skill.skill_id}`"
        )


def _is_host_supported(skill: SkillMeta) -> bool:
    if not skill.host_support:
        return True
    normalized = {item.strip().lower() for item in skill.host_support if item.strip()}
    if not normalized:
        return True
    if "*" in normalized or "all" in normalized:
        return True
    return _active_host_name() in normalized


def _active_host_name() -> str:
    return (os.environ.get("SOPIFY_HOST_NAME") or os.environ.get("SOPIFY_HOST") or "codex").strip().lower()


def _load_module(path: Path, skill_id: str) -> Any:
    module_name = f"sopify_runtime_{skill_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SkillExecutionError(f"Unable to load runtime entry: {path}")
    module = importlib.util.module_from_spec(spec)
    # Register the module before execution so decorators such as dataclass can
    # resolve `cls.__module__` through `sys.modules` on newer Python versions.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
