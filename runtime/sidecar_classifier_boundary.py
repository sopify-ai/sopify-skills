"""Read-only boundary for future semantic sidecar classification in V1."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Mapping

from .decision_tables import load_default_decision_tables
from .deterministic_guard import DeterministicGuardResult
from .resolution_planner import ResolutionPlanner

SEMANTIC_SIGNAL_ORIGIN = "semantic_classifier"
SEMANTIC_EVIDENCE_TIER_CAP = "weak_semantic_hint"
SEMANTIC_REQUIRED_RECOVERY_DECISION = "eligible_for_semantic_escalation"
SEMANTIC_REQUIRED_CANDIDATE_FIELDS = ("signal_id", "checkpoint_kind", "target_slot")
SEMANTIC_SHARED_FAILURE_MEMBERS = ("semantic_unavailable", "context_budget_exceeded")


class SidecarClassifierBoundaryError(ValueError):
    """Raised when the semantic sidecar boundary cannot be described safely."""


@dataclass(frozen=True)
class SidecarCandidateSignal:
    """One signal row a future semantic sidecar could emit as a candidate only."""

    signal_id: str
    target_slot: str
    winner_action: str
    fallback_on_conflict: str
    reason_code: str
    evidence_tier_cap: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "target_slot": self.target_slot,
            "winner_action": self.winner_action,
            "fallback_on_conflict": self.fallback_on_conflict,
            "reason_code": self.reason_code,
            "evidence_tier_cap": self.evidence_tier_cap,
        }


@dataclass(frozen=True)
class SidecarClassifierBoundary:
    """Code-visible boundary showing that V1 does not enable semantic routing."""

    required_host_action: str
    resolution_scope: str
    v1_enabled: bool
    implementation_stage: str
    mode: str
    default_invocation: str
    required_recovery_decision: str
    allowed_signal_origin: str
    evidence_tier_cap: str
    eligible_signal_ids: tuple[str, ...] = ()
    candidate_signals: tuple[SidecarCandidateSignal, ...] = ()
    required_candidate_fields: tuple[str, ...] = ()
    can_emit_resolved_action: bool = False
    can_write_state: bool = False
    can_override_main_router: bool = False
    can_bypass_deterministic_guard: bool = False
    can_bypass_decision_tables: bool = False
    shared_failure_members: tuple[str, ...] = ()
    shared_fail_close_contract: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_host_action": self.required_host_action,
            "resolution_scope": self.resolution_scope,
            "v1_enabled": self.v1_enabled,
            "implementation_stage": self.implementation_stage,
            "mode": self.mode,
            "default_invocation": self.default_invocation,
            "required_recovery_decision": self.required_recovery_decision,
            "allowed_signal_origin": self.allowed_signal_origin,
            "evidence_tier_cap": self.evidence_tier_cap,
            "eligible_signal_ids": list(self.eligible_signal_ids),
            "candidate_signals": [signal.to_dict() for signal in self.candidate_signals],
            "required_candidate_fields": list(self.required_candidate_fields),
            "can_emit_resolved_action": self.can_emit_resolved_action,
            "can_write_state": self.can_write_state,
            "can_override_main_router": self.can_override_main_router,
            "can_bypass_deterministic_guard": self.can_bypass_deterministic_guard,
            "can_bypass_decision_tables": self.can_bypass_decision_tables,
            "shared_failure_members": list(self.shared_failure_members),
            "shared_fail_close_contract": dict(self.shared_fail_close_contract),
            "notes": list(self.notes),
        }


def supports_sidecar_classifier_boundary(required_host_action: str) -> bool:
    """Return whether the current action has semantic candidate rows in the table."""

    normalized = str(required_host_action or "").strip()
    return normalized in _load_sidecar_registry()["semantic_rows_by_action"]


def build_sidecar_classifier_boundary(
    guard: DeterministicGuardResult,
    planner: ResolutionPlanner,
) -> SidecarClassifierBoundary:
    """Describe the semantic sidecar as a disabled candidate-only boundary in V1."""

    if guard.truth_status != "stable" or not guard.resolution_enabled:
        raise SidecarClassifierBoundaryError(
            "Sidecar classifier boundary requires a stable deterministic guard"
        )

    required_host_action = str(guard.required_host_action or "").strip()
    if required_host_action != str(planner.required_host_action or "").strip():
        raise SidecarClassifierBoundaryError(
            "Sidecar classifier boundary requires matching guard/planner required_host_action"
        )

    registry = _load_sidecar_registry()
    rows = registry["semantic_rows_by_action"].get(required_host_action, ())
    candidate_signals: list[SidecarCandidateSignal] = []
    for row in rows:
        evidence_tier_cap = str(row["evidence_tier_cap"] or "").strip()
        if evidence_tier_cap != SEMANTIC_EVIDENCE_TIER_CAP:
            raise SidecarClassifierBoundaryError(
                "Semantic sidecar evidence_tier_cap escaped the frozen V1 boundary: "
                f"{evidence_tier_cap!r}"
            )
        candidate_signals.append(
            SidecarCandidateSignal(
                signal_id=str(row["signal_id"]),
                target_slot=str(row["target_slot"]),
                winner_action=str(row["winner_action"]),
                fallback_on_conflict=str(row["fallback_on_conflict"]),
                reason_code=str(row["reason_code"]),
                evidence_tier_cap=evidence_tier_cap,
            )
        )

    resolution_scope = str(guard.checkpoint_kind or guard.required_host_action or "").strip()
    return SidecarClassifierBoundary(
        required_host_action=required_host_action,
        resolution_scope=resolution_scope,
        v1_enabled=False,
        implementation_stage="vnext_only",
        mode="candidate_only",
        default_invocation="disabled_in_v1",
        required_recovery_decision=SEMANTIC_REQUIRED_RECOVERY_DECISION,
        allowed_signal_origin=SEMANTIC_SIGNAL_ORIGIN,
        evidence_tier_cap=SEMANTIC_EVIDENCE_TIER_CAP,
        eligible_signal_ids=tuple(signal.signal_id for signal in candidate_signals),
        candidate_signals=tuple(candidate_signals),
        required_candidate_fields=SEMANTIC_REQUIRED_CANDIDATE_FIELDS,
        can_emit_resolved_action=False,
        can_write_state=False,
        can_override_main_router=False,
        can_bypass_deterministic_guard=False,
        can_bypass_decision_tables=False,
        shared_failure_members=SEMANTIC_SHARED_FAILURE_MEMBERS,
        shared_fail_close_contract={
            "primary_failure_type": "resolution_failure",
            "member_failures": list(SEMANTIC_SHARED_FAILURE_MEMBERS),
            "fallback_action": planner.default_no_candidate_recovery.get("fallback_action"),
            "prompt_mode": planner.default_no_candidate_recovery.get("prompt_mode"),
            "retry_policy": planner.default_no_candidate_recovery.get("retry_policy"),
            "reason_code": planner.default_no_candidate_recovery.get("reason_code"),
            "unresolved_outcome_family": planner.default_no_candidate_recovery.get(
                "unresolved_outcome_family"
            ),
        },
        notes=(
            "Semantic sidecar is a candidate-only boundary and is not invoked by default in V1.",
            "Any candidate missing signal_id/checkpoint_kind/target_slot must fail closed.",
            "Rule and parser candidates always outrank semantic sidecar candidates.",
        ),
    )


@lru_cache(maxsize=1)
def _load_sidecar_registry() -> dict[str, Any]:
    tables = load_default_decision_tables()

    semantic_rows_by_action: dict[str, list[dict[str, Any]]] = {}
    for row in tables["signal_priority_table"]["rows"]:
        if SEMANTIC_SIGNAL_ORIGIN not in row["allowed_origins"]:
            continue
        evidence_caps = row.get("origin_evidence_cap", {})
        evidence_tier_cap = str(evidence_caps.get(SEMANTIC_SIGNAL_ORIGIN) or "").strip()
        for required_host_action in row["enabled_checkpoint_kinds"]:
            semantic_rows_by_action.setdefault(required_host_action, []).append(
                {
                    "signal_id": row["signal_id"],
                    "target_slot": row["target_slot"],
                    "winner_action": row["winner_action"],
                    "fallback_on_conflict": row["fallback_on_conflict"],
                    "reason_code": row["reason_code"],
                    "evidence_tier_cap": evidence_tier_cap,
                }
            )

    return {
        "semantic_rows_by_action": deepcopy(semantic_rows_by_action),
    }
