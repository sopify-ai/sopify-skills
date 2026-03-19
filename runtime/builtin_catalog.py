"""Builtin Sopify skill catalog owned by the runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from .models import SkillMeta

_DEFAULT_CONTRACT_VERSION = "1"
_SOPIFY_DOC_ROOT = ("Codex", "Skills")
_LANGUAGE_DIRS = {
    "zh-CN": ("CN", "EN"),
    "en-US": ("EN", "CN"),
}
_GENERATED_CATALOG_PATH = Path("runtime") / "builtin_catalog.generated.json"


@dataclass(frozen=True)
class _BuiltinSkillSpec:
    skill_id: str
    names: Mapping[str, str]
    descriptions: Mapping[str, str]
    mode: str = "workflow"
    runtime_entry: str | None = None
    entry_kind: str | None = None
    handoff_kind: str | None = None
    contract_version: str = _DEFAULT_CONTRACT_VERSION
    supports_routes: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    requires_network: bool = False
    host_support: tuple[str, ...] = ()
    permission_mode: str = "default"


_BUILTIN_SPECS: tuple[_BuiltinSkillSpec, ...] = (
    _BuiltinSkillSpec(
        skill_id="analyze",
        names={"zh-CN": "analyze", "en-US": "analyze"},
        descriptions={
            "zh-CN": "需求分析阶段详细规则；用于需求评分、追问与范围判断。",
            "en-US": "Detailed requirements-analysis rules for scoring, clarification, and scope checks.",
        },
        handoff_kind="analysis",
        supports_routes=("workflow", "plan_only"),
    ),
    _BuiltinSkillSpec(
        skill_id="design",
        names={"zh-CN": "design", "en-US": "design"},
        descriptions={
            "zh-CN": "方案设计阶段详细规则；用于方案生成与任务拆分。",
            "en-US": "Detailed design-stage rules for solution generation and task breakdown.",
        },
        handoff_kind="plan",
        supports_routes=("workflow", "plan_only", "light_iterate"),
    ),
    _BuiltinSkillSpec(
        skill_id="develop",
        names={"zh-CN": "develop", "en-US": "develop"},
        descriptions={
            "zh-CN": "开发实施阶段详细规则；用于代码执行、验证与知识库同步。",
            "en-US": "Detailed implementation-stage rules for code execution, validation, and KB sync.",
        },
        handoff_kind="develop",
        supports_routes=("workflow", "light_iterate", "quick_fix", "resume_active", "exec_plan"),
    ),
    _BuiltinSkillSpec(
        skill_id="kb",
        names={"zh-CN": "kb", "en-US": "kb"},
        descriptions={
            "zh-CN": "知识库管理技能；用于初始化、更新与同步知识库。",
            "en-US": "Knowledge-base management skill for bootstrap, updates, and synchronization.",
        },
        handoff_kind="kb",
    ),
    _BuiltinSkillSpec(
        skill_id="templates",
        names={"zh-CN": "templates", "en-US": "templates"},
        descriptions={
            "zh-CN": "文档模板集合；用于生成方案与知识库文档。",
            "en-US": "Template collection for plan and knowledge-base documents.",
        },
        handoff_kind="template",
    ),
    _BuiltinSkillSpec(
        skill_id="model-compare",
        names={"zh-CN": "model-compare", "en-US": "model-compare"},
        descriptions={
            "zh-CN": "多模型并发对比子技能；由 runtime 负责 compare 路由执行。",
            "en-US": "Multi-model comparison sub-skill executed by the runtime compare route.",
        },
        mode="runtime",
        runtime_entry="scripts/model_compare_runtime.py",
        entry_kind="python",
        handoff_kind="compare",
        supports_routes=("compare",),
        triggers=("~compare", "对比分析：", "compare:"),
        tools=("read", "exec", "network"),
        disallowed_tools=("write",),
        allowed_paths=(".",),
        requires_network=True,
        host_support=("codex", "claude"),
        permission_mode="dual",
    ),
    _BuiltinSkillSpec(
        skill_id="workflow-learning",
        names={"zh-CN": "workflow-learning", "en-US": "workflow-learning"},
        descriptions={
            "zh-CN": "工作流学习子技能；用于回放、复盘与决策解释。",
            "en-US": "Workflow-learning sub-skill for replay, review, and decision explanation.",
        },
        handoff_kind="replay",
        supports_routes=("replay",),
        triggers=("回放", "复盘", "为什么这么做", "replay", "review the implementation"),
    ),
)


def load_builtin_skills(*, repo_root: Path, language: str) -> tuple[SkillMeta, ...]:
    """Build builtin skill metadata without scanning bundled skill directories."""
    specs = _load_generated_specs(repo_root) or _BUILTIN_SPECS
    skills: list[SkillMeta] = []
    for spec in specs:
        runtime_entry = _resolve_runtime_entry(repo_root, spec.runtime_entry)
        entry_kind = spec.entry_kind if runtime_entry is not None else None
        path = _resolve_instruction_path(repo_root, language, spec.skill_id)
        metadata = dict(spec.metadata)
        metadata.setdefault("catalog", "builtin")

        skills.append(
            SkillMeta(
                skill_id=spec.skill_id,
                name=_localized(spec.names, language, fallback=spec.skill_id),
                description=_localized(spec.descriptions, language, fallback=""),
                path=path,
                source="builtin",
                mode=spec.mode,
                runtime_entry=runtime_entry,
                triggers=spec.triggers,
                metadata=metadata,
                entry_kind=entry_kind,
                handoff_kind=spec.handoff_kind,
                contract_version=spec.contract_version,
                supports_routes=spec.supports_routes,
                tools=spec.tools,
                disallowed_tools=spec.disallowed_tools,
                allowed_paths=spec.allowed_paths,
                requires_network=spec.requires_network,
                host_support=spec.host_support,
                permission_mode=spec.permission_mode,
            )
        )
    return tuple(skills)


def _load_generated_specs(repo_root: Path) -> tuple[_BuiltinSkillSpec, ...] | None:
    catalog_path = repo_root / _GENERATED_CATALOG_PATH
    if not catalog_path.is_file():
        return None
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list):
        return None
    specs: list[_BuiltinSkillSpec] = []
    for raw_skill in raw_skills:
        if not isinstance(raw_skill, Mapping):
            continue
        skill_id = _string_or_none(raw_skill.get("id") or raw_skill.get("skill_id"))
        if not skill_id:
            continue
        names = _mapping_of_strings(raw_skill.get("names"))
        descriptions = _mapping_of_strings(raw_skill.get("descriptions"))
        metadata = _mapping_of_objects(raw_skill.get("metadata"))
        metadata.setdefault("catalog_generated", True)
        specs.append(
            _BuiltinSkillSpec(
                skill_id=skill_id,
                names=names or {"en-US": skill_id},
                descriptions=descriptions or {"en-US": ""},
                mode=_string_or_default(raw_skill.get("mode"), default="workflow"),
                runtime_entry=_string_or_none(raw_skill.get("runtime_entry")),
                entry_kind=_string_or_none(raw_skill.get("entry_kind")),
                handoff_kind=_string_or_none(raw_skill.get("handoff_kind")),
                contract_version=_string_or_default(raw_skill.get("contract_version"), default=_DEFAULT_CONTRACT_VERSION),
                supports_routes=_string_tuple(raw_skill.get("supports_routes")),
                triggers=_string_tuple(raw_skill.get("triggers")),
                metadata=metadata,
                tools=_string_tuple(raw_skill.get("tools")),
                disallowed_tools=_string_tuple(raw_skill.get("disallowed_tools")),
                allowed_paths=_string_tuple(raw_skill.get("allowed_paths")),
                requires_network=_bool_or_default(raw_skill.get("requires_network"), default=False),
                host_support=_string_tuple(raw_skill.get("host_support")),
                permission_mode=_string_or_default(raw_skill.get("permission_mode"), default="default"),
            )
        )
    return tuple(specs) if specs else None


def _localized(values: Mapping[str, str], language: str, *, fallback: str) -> str:
    return values.get(language) or values.get("en-US") or next(iter(values.values()), fallback)


def _resolve_runtime_entry(repo_root: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = (repo_root / relative_path).resolve()
    if candidate.exists():
        return candidate
    return None


def _resolve_instruction_path(repo_root: Path, language: str, skill_id: str) -> Path:
    language_dirs = _LANGUAGE_DIRS.get(language, _LANGUAGE_DIRS["en-US"])
    candidates: list[Path] = []
    for language_dir in language_dirs:
        candidates.append(
            repo_root / _SOPIFY_DOC_ROOT[0] / _SOPIFY_DOC_ROOT[1] / language_dir / "skills" / "sopify" / skill_id / "SKILL.md"
        )
        candidates.append(
            repo_root / "Claude" / "Skills" / language_dir / "skills" / "sopify" / skill_id / "SKILL.md"
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    # Vendored bundles do not ship the builtin prompt docs; the catalog remains the local source of truth.
    return (repo_root / "runtime" / "builtin_catalog.py").resolve()


def _mapping_of_strings(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for key, item in value.items():
        key_text = _string_or_none(key)
        item_text = _string_or_none(item)
        if key_text and item_text:
            normalized[key_text] = item_text
    return normalized


def _mapping_of_objects(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, object] = {}
    for key, item in value.items():
        key_text = _string_or_none(key)
        if key_text:
            normalized[key_text] = item
    return normalized


def _bool_or_default(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


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
    if isinstance(value, (list, tuple)):
        normalized: list[str] = []
        for item in value:
            text = _string_or_none(item)
            if text:
                normalized.append(text)
        return tuple(normalized)
    return ()
