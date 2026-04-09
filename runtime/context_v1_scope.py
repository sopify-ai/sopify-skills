"""Guard-rail registry for the current Plan A V1 implementation slice."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

SUPPORTED_CHECKPOINT_KINDS_V1 = (
    "confirm_decision",
    "confirm_execute",
    "confirm_plan_package",
)

ALLOWED_V1_STATE_EFFECTS = (
    "current_decision",
    "current_plan",
    "current_plan_proposal",
    "current_run",
)

FORBIDDEN_V1_SIDE_EFFECTS = (
    "advance_to_develop",
    "clear_current_decision",
    "clear_current_plan_proposal",
    "materialize_new_plan_package",
    "mutate_plan_identity",
    "recreate_execution_confirm_checkpoint",
    "rewrite_reserved_plan_id",
    "submit_decision_selection",
)

MAX_LOCAL_CONTEXT_USER_MESSAGES = 3


class ContextV1ScopeError(ValueError):
    """Raised when a runtime artifact escapes the current V1 scope."""


def assert_supported_checkpoint_kind(checkpoint_kind: str) -> str:
    """Return a normalized checkpoint kind or raise on out-of-scope values."""

    normalized = str(checkpoint_kind or "").strip()
    if normalized not in SUPPORTED_CHECKPOINT_KINDS_V1:
        raise ContextV1ScopeError(
            "Unsupported V1 checkpoint_kind "
            f"{normalized!r}; allowed={SUPPORTED_CHECKPOINT_KINDS_V1!r}"
        )
    return normalized


def assert_state_effects_within_v1_scope(
    *,
    allowed_state_effects: Sequence[str] = (),
    forbidden_state_effects: Sequence[str] = (),
) -> None:
    """Reject state effects that are outside the currently approved V1 slice."""

    normalized_allowed = _normalize_effects(allowed_state_effects)
    normalized_forbidden = _normalize_effects(forbidden_state_effects)

    overlap = sorted(set(normalized_allowed) & set(normalized_forbidden))
    if overlap:
        raise ContextV1ScopeError(
            "State effects cannot be both allowed and forbidden within V1 scope: "
            + ", ".join(overlap)
        )

    unknown_allowed = [
        effect for effect in normalized_allowed if effect not in ALLOWED_V1_STATE_EFFECTS
    ]
    if unknown_allowed:
        raise ContextV1ScopeError(
            "Unsupported allowed V1 state effect(s): " + ", ".join(sorted(unknown_allowed))
        )

    unknown_forbidden = [
        effect for effect in normalized_forbidden if effect not in FORBIDDEN_V1_SIDE_EFFECTS
    ]
    if unknown_forbidden:
        raise ContextV1ScopeError(
            "Unsupported forbidden V1 state effect(s): " + ", ".join(sorted(unknown_forbidden))
        )


def validate_side_effect_mapping_row_v1(
    row: Mapping[str, Any],
    *,
    path: str = "side_effect_mapping_table.rows[*]",
) -> None:
    """Validate one side-effect mapping row against the current V1 guard rails."""

    if not isinstance(row, Mapping):
        raise ContextV1ScopeError(f"{path} must be a mapping")

    assert_supported_checkpoint_kind(str(row.get("checkpoint_kind") or ""))

    state_mutators = row.get("state_mutators")
    if not isinstance(state_mutators, Mapping):
        raise ContextV1ScopeError(f"{path}.state_mutators must be a mapping")

    allowed_state_effects: list[str] = []
    for bucket_name in ("preserve", "clear", "update", "write"):
        bucket_value = state_mutators.get(bucket_name, ())
        bucket_effects = _coerce_effect_bucket(
            bucket_value,
            path=f"{path}.state_mutators.{bucket_name}",
        )
        allowed_state_effects.extend(bucket_effects)

    forbidden_state_effects = _coerce_effect_bucket(
        row.get("forbidden_state_effects", ()),
        path=f"{path}.forbidden_state_effects",
    )
    assert_state_effects_within_v1_scope(
        allowed_state_effects=allowed_state_effects,
        forbidden_state_effects=forbidden_state_effects,
    )


def validate_decision_tables_v1_scope(tables: Mapping[str, Any]) -> None:
    """Validate that loaded decision tables stay inside the current V1 slice."""

    if not isinstance(tables, Mapping):
        raise ContextV1ScopeError("Decision tables must be a mapping")

    side_effect_mapping = tables.get("side_effect_mapping_table")
    if not isinstance(side_effect_mapping, Mapping):
        raise ContextV1ScopeError("Decision tables missing side_effect_mapping_table")

    rows = side_effect_mapping.get("rows")
    if not isinstance(rows, list):
        raise ContextV1ScopeError("side_effect_mapping_table.rows must be a list")

    for index, row in enumerate(rows):
        validate_side_effect_mapping_row_v1(
            row,
            path=f"side_effect_mapping_table.rows[{index}]",
        )


def _coerce_effect_bucket(value: Any, *, path: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContextV1ScopeError(f"{path} must be a sequence of strings")
    normalized = []
    for item in value:
        effect = str(item or "").strip()
        if not effect:
            raise ContextV1ScopeError(f"{path} contains an empty state effect")
        normalized.append(effect)
    return normalized


def _normalize_effects(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        effect = str(raw or "").strip()
        if not effect or effect in seen:
            continue
        seen.add(effect)
        normalized.append(effect)
    return tuple(normalized)

