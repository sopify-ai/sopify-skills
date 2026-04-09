"""Read-only phase and gate boundary for parser-first V1 vs guarded V2 trial."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .deterministic_guard import DeterministicGuardResult

ACTIVE_PHASE = "parser_first_v1"
ROLLOUT_PHASE = "rollout_observability"
VNEXT_PHASE = "guarded_hybrid_classifier_vnext"
READY_FOR_V1_EXECUTION = "Ready-for-V1-Execution"
READY_FOR_V2_TRIAL = "Ready-for-V2-Trial"
V1_REQUIRED_CHECKPOINTS = ("Checkpoint A", "Checkpoint B", "Checkpoint C")
V2_REQUIRED_CHECKPOINTS = ("Checkpoint D",)
V2_REQUIRED_ROLLOUT_EVIDENCE = (
    "residual_ambiguity_gain_is_auditable",
    "budget_thresholds_frozen",
    "rollback_thresholds_frozen",
    "v1_rollout_observability_complete",
)
V2_STRUCTURAL_GUARDS = (
    "candidate_signals_and_reason_code_only",
    "must_not_bypass_deterministic_guard",
    "must_not_bypass_decision_tables",
    "must_not_write_state_directly",
    "must_not_replace_main_router",
)
_SUPPORTED_PHASE_BOUNDARY_ACTIONS = frozenset(
    {
        "answer_questions",
        "confirm_decision",
        "confirm_execute",
        "confirm_plan_package",
        "review_or_execute_plan",
    }
)


class VNextPhaseBoundaryError(ValueError):
    """Raised when the current handoff cannot describe the V1/V2 boundary safely."""


@dataclass(frozen=True)
class PhaseReadinessGate:
    """One readiness gate and the checkpoints/evidence it blocks on."""

    gate_name: str
    blocks_scope: str
    required_checkpoints: tuple[str, ...]
    optional_checkpoints: tuple[str, ...] = ()
    required_rollout_evidence: tuple[str, ...] = ()
    non_blocking_for: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "blocks_scope": self.blocks_scope,
            "required_checkpoints": list(self.required_checkpoints),
            "optional_checkpoints": list(self.optional_checkpoints),
            "required_rollout_evidence": list(self.required_rollout_evidence),
            "non_blocking_for": list(self.non_blocking_for),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class VNextPhaseBoundary:
    """Code-visible roadmap showing V1 is active and V2 is still gated."""

    required_host_action: str
    resolution_scope: str
    active_phase: str
    default_resolution_strategy: str
    phase_sequence: tuple[str, ...]
    vnext_enabled: bool
    shared_failure_layer: str
    phase_catalog: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    readiness_gates: tuple[PhaseReadinessGate, ...] = ()
    transition_rules: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    forbidden_transitions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_host_action": self.required_host_action,
            "resolution_scope": self.resolution_scope,
            "active_phase": self.active_phase,
            "default_resolution_strategy": self.default_resolution_strategy,
            "phase_sequence": list(self.phase_sequence),
            "vnext_enabled": self.vnext_enabled,
            "shared_failure_layer": self.shared_failure_layer,
            "phase_catalog": {
                key: dict(value) for key, value in self.phase_catalog.items()
            },
            "readiness_gates": [gate.to_dict() for gate in self.readiness_gates],
            "transition_rules": {
                key: dict(value) for key, value in self.transition_rules.items()
            },
            "forbidden_transitions": list(self.forbidden_transitions),
            "notes": list(self.notes),
        }


def supports_vnext_phase_boundary(required_host_action: str) -> bool:
    """Return whether this host action sits on the parser-first / vNext decision surface."""

    return str(required_host_action or "").strip() in _SUPPORTED_PHASE_BOUNDARY_ACTIONS


def build_vnext_phase_boundary(guard: DeterministicGuardResult) -> VNextPhaseBoundary:
    """Build the frozen phase/gate contract for parser-first V1 and future V2 trial."""

    if guard.truth_status != "stable" or not guard.resolution_enabled:
        raise VNextPhaseBoundaryError("VNext phase boundary requires a stable deterministic guard")

    required_host_action = str(guard.required_host_action or "").strip()
    if not supports_vnext_phase_boundary(required_host_action):
        raise VNextPhaseBoundaryError(
            f"Unsupported VNext phase boundary required_host_action={required_host_action!r}"
        )

    resolution_scope = str(guard.checkpoint_kind or required_host_action or "").strip()
    readiness_gates = (
        PhaseReadinessGate(
            gate_name=READY_FOR_V1_EXECUTION,
            blocks_scope="v1_execution",
            required_checkpoints=V1_REQUIRED_CHECKPOINTS,
            optional_checkpoints=V2_REQUIRED_CHECKPOINTS,
            non_blocking_for=V2_REQUIRED_CHECKPOINTS,
            notes=(
                "Checkpoint D is not a prerequisite for Ready-for-V1-Execution.",
                "V1 remains parser-first even after Checkpoint D is defined.",
            ),
        ),
        PhaseReadinessGate(
            gate_name=READY_FOR_V2_TRIAL,
            blocks_scope="v2_trial_only",
            required_checkpoints=V2_REQUIRED_CHECKPOINTS,
            required_rollout_evidence=V2_REQUIRED_ROLLOUT_EVIDENCE,
            notes=(
                "Checkpoint D only unlocks guarded V2 trial and does not retroactively block V1.",
                "V2 trial still inherits the parser-first control plane and shared failure layer.",
            ),
        ),
    )
    return VNextPhaseBoundary(
        required_host_action=required_host_action,
        resolution_scope=resolution_scope,
        active_phase=ACTIVE_PHASE,
        default_resolution_strategy="deterministic_guard+local_context+action_projection+parser_first_closure",
        phase_sequence=(ACTIVE_PHASE, ROLLOUT_PHASE, VNEXT_PHASE),
        vnext_enabled=False,
        shared_failure_layer="shared_failure_recovery_table",
        phase_catalog={
            ACTIVE_PHASE: {
                "role": "default_mainline",
                "status": "active",
                "classifier_mode": "out_of_scope",
                "decision_path": "parser_first",
            },
            ROLLOUT_PHASE: {
                "role": "observe_only",
                "status": "required_before_vnext",
                "observation_metrics": [
                    "ambiguous_rate",
                    "fail_close_rate",
                    "manual_resolution_rate",
                    "streak_fuse_rate",
                ],
            },
            VNEXT_PHASE: {
                "role": "future_trial_only",
                "status": "blocked_by_default",
                "classifier_mode": "guarded_candidate_sidecar",
                "structural_guards": list(V2_STRUCTURAL_GUARDS),
            },
        },
        readiness_gates=readiness_gates,
        transition_rules={
            f"{ACTIVE_PHASE}->{ROLLOUT_PHASE}": {
                "transition_mode": "observe_only_no_surface_expansion",
                "required_gate": READY_FOR_V1_EXECUTION,
            },
            f"{ROLLOUT_PHASE}->{VNEXT_PHASE}": {
                "transition_mode": "blocked_until_gate_passes",
                "required_gate": READY_FOR_V2_TRIAL,
                "required_conditions": [
                    "control_plane_contract_stable",
                    "parser_first_acceptance_gate_passed",
                    "residual_ambiguity_proven_by_rollout",
                    "local_context_action_projection_failure_recovery_stable",
                ],
                "structural_guards": list(V2_STRUCTURAL_GUARDS),
            },
        },
        forbidden_transitions=(
            "treat_checkpoint_d_as_v1_prerequisite",
            "skip_rollout_observability_before_v2_trial",
            "switch_directly_from_parser_first_v1_to_guarded_hybrid_classifier_vnext",
            "allow_vnext_classifier_to_bypass_deterministic_guard",
            "allow_vnext_classifier_to_bypass_decision_tables",
            "allow_vnext_classifier_to_write_state_directly",
            "allow_vnext_classifier_to_replace_main_router",
        ),
        notes=(
            "V1 remains parser-first and is the only active default implementation path.",
            "V2 stays gated until Checkpoint D and rollout evidence are both present.",
            "Checkpoint D blocks V2 only; it must not be back-propagated into V1 readiness.",
        ),
    )
