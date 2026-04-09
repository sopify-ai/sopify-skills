"""Resolution-planner facade for V1 standard actions and side-effect boundaries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Mapping

from .decision_tables import load_default_decision_tables
from .deterministic_guard import DeterministicGuardResult


class ResolutionPlannerError(ValueError):
    """Raised when a guarded action cannot build a stable resolution plan."""


@dataclass(frozen=True)
class ResolutionActionProfile:
    """Normalized action profile available to the current checkpoint."""

    resolved_action: str
    signal_ids: tuple[str, ...] = ()
    target_slots: tuple[str, ...] = ()
    signal_reason_codes: tuple[str, ...] = ()
    fallback_on_conflicts: tuple[str, ...] = ()
    effect_contract_status: str = "blocked"
    forbidden_state_effects: tuple[str, ...] = ()
    preserved_identity: tuple[str, ...] = ()
    terminality: str = ""
    state_mutators: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    handoff_protocol: Mapping[str, Any] = field(default_factory=dict)
    effect_reason_code: str = ""
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolved_action": self.resolved_action,
            "signal_ids": list(self.signal_ids),
            "target_slots": list(self.target_slots),
            "signal_reason_codes": list(self.signal_reason_codes),
            "fallback_on_conflicts": list(self.fallback_on_conflicts),
            "effect_contract_status": self.effect_contract_status,
            "forbidden_state_effects": list(self.forbidden_state_effects),
            "preserved_identity": list(self.preserved_identity),
            "terminality": self.terminality,
            "state_mutators": {key: list(values) for key, values in self.state_mutators.items()},
            "handoff_protocol": dict(self.handoff_protocol),
            "effect_reason_code": self.effect_reason_code,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ResolutionPlanner:
    """Stable standard-action catalog for one guarded checkpoint."""

    required_host_action: str
    resolution_enabled: bool
    standard_resolved_actions: tuple[str, ...] = ()
    supported_resolved_actions: tuple[str, ...] = ()
    blocked_resolved_actions: tuple[str, ...] = ()
    profiles: tuple[ResolutionActionProfile, ...] = ()
    default_no_candidate_recovery: Mapping[str, Any] = field(default_factory=dict)
    default_effect_contract_recovery: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_host_action": self.required_host_action,
            "resolution_enabled": self.resolution_enabled,
            "standard_resolved_actions": list(self.standard_resolved_actions),
            "supported_resolved_actions": list(self.supported_resolved_actions),
            "blocked_resolved_actions": list(self.blocked_resolved_actions),
            "profiles": [profile.to_dict() for profile in self.profiles],
            "default_no_candidate_recovery": dict(self.default_no_candidate_recovery),
            "default_effect_contract_recovery": dict(self.default_effect_contract_recovery),
        }


def supports_resolution_planner(required_host_action: str) -> bool:
    """Return whether the current host action participates in signal resolution."""

    registry = _load_resolution_registry()
    normalized = str(required_host_action or "").strip()
    return normalized in registry["signal_rows_by_action"]


def build_resolution_planner(
    guard: DeterministicGuardResult,
) -> ResolutionPlanner:
    """Build a V1 resolution-action catalog from frozen decision tables."""

    if guard.truth_status != "stable" or not guard.resolution_enabled:
        raise ResolutionPlannerError("Resolution planner requires a stable deterministic guard")

    required_host_action = str(guard.required_host_action or "").strip()
    registry = _load_resolution_registry()
    signal_rows = registry["signal_rows_by_action"].get(required_host_action, ())
    if not signal_rows:
        raise ResolutionPlannerError(
            f"No signal-priority rows defined for required_host_action={required_host_action!r}"
        )

    profiles: list[ResolutionActionProfile] = []
    seen_actions: set[str] = set()
    supported_resolved_actions: list[str] = []
    blocked_resolved_actions: list[str] = []
    standard_resolved_actions: list[str] = []
    for row in signal_rows:
        resolved_action = str(row["winner_action"])
        if resolved_action in seen_actions:
            continue
        seen_actions.add(resolved_action)
        standard_resolved_actions.append(resolved_action)
        effect_row = registry["side_effect_rows_by_key"].get((required_host_action, resolved_action))
        if effect_row is None:
            blocked_resolved_actions.append(resolved_action)
            profiles.append(
                ResolutionActionProfile(
                    resolved_action=resolved_action,
                    signal_ids=(str(row["signal_id"]),),
                    target_slots=(str(row["target_slot"]),),
                    signal_reason_codes=(str(row["reason_code"]),),
                    fallback_on_conflicts=(str(row["fallback_on_conflict"]),),
                    effect_contract_status="blocked",
                    notes=(
                        "No side_effect_mapping_table row for this required_host_action in the current V1 slice.",
                    ),
                )
            )
            continue

        supported_resolved_actions.append(resolved_action)
        profiles.append(
            ResolutionActionProfile(
                resolved_action=resolved_action,
                signal_ids=(str(row["signal_id"]),),
                target_slots=(str(row["target_slot"]),),
                signal_reason_codes=(str(row["reason_code"]),),
                fallback_on_conflicts=(str(row["fallback_on_conflict"]),),
                effect_contract_status="supported",
                forbidden_state_effects=tuple(effect_row["forbidden_state_effects"]),
                preserved_identity=tuple(effect_row["preserved_identity"]),
                terminality=str(effect_row["terminality"]),
                state_mutators={
                    key: tuple(values)
                    for key, values in effect_row["state_mutators"].items()
                },
                handoff_protocol=deepcopy(effect_row["handoff_protocol"]),
                effect_reason_code=str(effect_row["reason_code"]),
            )
        )

    return ResolutionPlanner(
        required_host_action=required_host_action,
        resolution_enabled=True,
        standard_resolved_actions=tuple(standard_resolved_actions),
        supported_resolved_actions=tuple(supported_resolved_actions),
        blocked_resolved_actions=tuple(blocked_resolved_actions),
        profiles=tuple(profiles),
        default_no_candidate_recovery=deepcopy(
            registry["failure_recovery_by_key"][("resolution_failure", required_host_action)]
        ),
        default_effect_contract_recovery=deepcopy(
            registry["failure_recovery_by_key"][("effect_contract_invalid", required_host_action)]
        ),
    )


@lru_cache(maxsize=1)
def _load_resolution_registry() -> dict[str, Any]:
    tables = load_default_decision_tables()

    signal_rows_by_action: dict[str, list[dict[str, Any]]] = {}
    for row in tables["signal_priority_table"]["rows"]:
        for required_host_action in row["enabled_checkpoint_kinds"]:
            signal_rows_by_action.setdefault(required_host_action, []).append(
                {
                    "signal_id": row["signal_id"],
                    "target_slot": row["target_slot"],
                    "winner_action": row["winner_action"],
                    "fallback_on_conflict": row["fallback_on_conflict"],
                    "reason_code": row["reason_code"],
                }
            )

    side_effect_rows_by_key = {
        (row["checkpoint_kind"], row["resolved_action"]): {
            "forbidden_state_effects": tuple(row["forbidden_state_effects"]),
            "preserved_identity": tuple(row["preserved_identity"]),
            "state_mutators": {
                key: tuple(values) for key, values in row["state_mutators"].items()
            },
            "handoff_protocol": deepcopy(row["handoff_protocol"]),
            "terminality": row["terminality"],
            "reason_code": row["reason_code"],
        }
        for row in tables["side_effect_mapping_table"]["rows"]
    }

    failure_recovery_by_key = {
        (row["primary_failure_type"], row["required_host_action"]): {
            "fallback_action": row["fallback_action"],
            "prompt_mode": row["prompt_mode"],
            "retry_policy": row["retry_policy"],
            "reason_code": row["reason_code"],
            "unresolved_outcome_family": row["unresolved_outcome_family"],
            "counts_toward_streak": row["counts_toward_streak"],
        }
        for row in tables["failure_recovery_table"]["rows"]
    }
    return {
        "signal_rows_by_action": signal_rows_by_action,
        "side_effect_rows_by_key": side_effect_rows_by_key,
        "failure_recovery_by_key": failure_recovery_by_key,
    }
