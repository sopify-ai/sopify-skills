"""Declarative route-to-skill resolver with deterministic fallback."""

from __future__ import annotations

from typing import Any, Iterable

from .models import SkillMeta

_SOURCE_ORDER = {
    "workspace": 0,
    "project": 1,
    "user": 2,
    "builtin": 3,
}


def resolve_route_candidate_skills(
    route_name: str,
    skills: Iterable[SkillMeta],
    *,
    fallback_preferred: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Resolve candidate skills for a route via declarative metadata first.

    Resolution order:
    1. Skills that explicitly declare `supports_routes` for the target route.
    2. Declarative candidates are ordered by metadata priority and source tier.
    3. Legacy deterministic fallback list is only used as a tie-break or when
       no declarative route metadata is available.
    """
    by_id = {skill.skill_id: skill for skill in skills}
    declarative = [
        skill
        for skill in by_id.values()
        if _supports_route(skill, route_name)
    ]
    if declarative:
        ordered = _order_candidates(declarative, fallback_preferred=fallback_preferred)
        return tuple(skill.skill_id for skill in ordered)
    return tuple(skill_id for skill_id in fallback_preferred if skill_id in by_id)


def resolve_runtime_skill_id(
    route_name: str,
    skills: Iterable[SkillMeta],
    *,
    fallback_preferred: str | None = None,
) -> str | None:
    """Resolve runtime skill id for a route via declarative metadata first."""
    by_id = {skill.skill_id: skill for skill in skills}
    declarative = [
        skill
        for skill in by_id.values()
        if skill.mode == "runtime" and _supports_route(skill, route_name)
    ]
    if declarative:
        ordered = _order_candidates(
            declarative,
            fallback_preferred=((fallback_preferred,) if fallback_preferred else ()),
        )
        return ordered[0].skill_id if ordered else None
    if not fallback_preferred:
        return None
    skill = by_id.get(fallback_preferred)
    if skill is None or skill.mode != "runtime":
        return None
    return skill.skill_id


def _supports_route(skill: SkillMeta, route_name: str) -> bool:
    if route_name in skill.supports_routes:
        return True
    metadata = skill.metadata if isinstance(skill.metadata, dict) else {}
    raw = metadata.get("supports_routes")
    if isinstance(raw, str):
        values = (raw.strip(),)
    elif isinstance(raw, (list, tuple)):
        values = tuple(str(item).strip() for item in raw if str(item).strip())
    else:
        values = ()
    return route_name in values


def _order_candidates(skills: list[SkillMeta], *, fallback_preferred: tuple[str, ...]) -> list[SkillMeta]:
    preferred_rank = {skill_id: index for index, skill_id in enumerate(fallback_preferred)}

    def sort_key(skill: SkillMeta) -> tuple[int, int, int, str]:
        priority = _skill_priority(skill.metadata)
        source_rank = _SOURCE_ORDER.get(skill.source, 999)
        if skill.skill_id in preferred_rank:
            preferred = preferred_rank[skill.skill_id]
        else:
            preferred = len(preferred_rank) + 1000
        return (priority, source_rank, preferred, skill.skill_id)

    return sorted(skills, key=sort_key)


def _skill_priority(metadata: Any) -> int:
    if not isinstance(metadata, dict):
        return 100
    raw = metadata.get("priority")
    if isinstance(raw, bool):
        return 100
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text and text.lstrip("-").isdigit():
            return int(text)
    return 100
