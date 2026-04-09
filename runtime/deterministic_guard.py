"""Deterministic machine-fact guard for the current V1 action surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import ExecutionGate, PlanArtifact, RunState

CHECKPOINT_ONLY = "checkpoint_only"
NORMAL_RUNTIME_FOLLOWUP = "normal_runtime_followup"

_SUPPORTED_ALLOWED_RESPONSE_MODES = (CHECKPOINT_ONLY, NORMAL_RUNTIME_FOLLOWUP)
_CHECKPOINT_ACTIONS = frozenset(
    {
        "answer_questions",
        "confirm_decision",
        "confirm_execute",
        "confirm_plan_package",
    }
)
_CHECKPOINT_REQUEST_KIND_BY_ACTION = {
    "answer_questions": "clarification",
    "confirm_decision": "decision",
    "confirm_execute": "execution_confirm",
    "confirm_plan_package": "plan_proposal",
}
_PLAN_REVIEW_STAGES = frozenset(
    {
        "plan_generated",
        "ready_for_execution",
        "execution_confirm_pending",
        "develop_pending",
    }
)
_HOST_ACTION_ALLOWED_ACTIONS = {
    "answer_questions": ("answer", "inspect", "cancel"),
    "confirm_decision": ("choose", "status", "cancel"),
    "confirm_execute": ("confirm", "inspect", "revise", "cancel"),
    "confirm_plan_package": ("confirm", "inspect", "revise", "cancel", "retopic"),
    "review_or_execute_plan": ("continue", "inspect", "revise", "cancel"),
    "continue_host_consult": ("consult", "block"),
    "continue_host_develop": ("continue", "checkpoint", "consult", "block"),
    "continue_host_workflow": ("continue", "inspect", "block"),
}
_HOST_ACTION_EXPECTED_RESPONSE_MODE = {
    "answer_questions": CHECKPOINT_ONLY,
    "confirm_decision": CHECKPOINT_ONLY,
    "confirm_execute": CHECKPOINT_ONLY,
    "confirm_plan_package": CHECKPOINT_ONLY,
    "review_or_execute_plan": NORMAL_RUNTIME_FOLLOWUP,
    "continue_host_consult": NORMAL_RUNTIME_FOLLOWUP,
    "continue_host_develop": NORMAL_RUNTIME_FOLLOWUP,
    "continue_host_workflow": NORMAL_RUNTIME_FOLLOWUP,
}


@dataclass(frozen=True)
class DeterministicGuardResult:
    """Fail-close summary of the current machine-fact action surface."""

    truth_status: str
    resolution_enabled: bool
    allowed_response_mode: str
    required_host_action: str
    resume_target_kind: str
    checkpoint_kind: str = ""
    allowed_actions: tuple[str, ...] = ()
    primary_failure_type: str | None = None
    fallback_action: str | None = None
    prompt_mode: str | None = None
    retry_policy: str | None = None
    unresolved_outcome_family: str | None = None
    reason_code: str = ""
    proofs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "truth_status": self.truth_status,
            "resolution_enabled": self.resolution_enabled,
            "allowed_response_mode": self.allowed_response_mode,
            "required_host_action": self.required_host_action,
            "resume_target_kind": self.resume_target_kind,
            "checkpoint_kind": self.checkpoint_kind,
            "allowed_actions": list(self.allowed_actions),
            "primary_failure_type": self.primary_failure_type,
            "fallback_action": self.fallback_action,
            "prompt_mode": self.prompt_mode,
            "retry_policy": self.retry_policy,
            "unresolved_outcome_family": self.unresolved_outcome_family,
            "reason_code": self.reason_code,
            "proofs": list(self.proofs),
            "notes": list(self.notes),
        }


def supports_deterministic_guard(required_host_action: str) -> bool:
    """Return whether the current action participates in the V1 guard rail."""

    return str(required_host_action or "").strip() in _HOST_ACTION_EXPECTED_RESPONSE_MODE


def expected_allowed_response_mode(required_host_action: str) -> str | None:
    """Return the expected host response mode for a guarded action."""

    normalized = str(required_host_action or "").strip()
    return _HOST_ACTION_EXPECTED_RESPONSE_MODE.get(normalized)


def evaluate_deterministic_guard(
    *,
    allowed_response_mode: str,
    required_host_action: str,
    current_run: RunState | None = None,
    current_plan: PlanArtifact | None = None,
    plan_id: str | None = None,
    plan_path: str | None = None,
    checkpoint_request: Mapping[str, Any] | None = None,
    execution_gate: ExecutionGate | Mapping[str, Any] | None = None,
) -> DeterministicGuardResult:
    """Project the smallest safe action surface from existing machine facts."""

    normalized_mode = str(allowed_response_mode or "").strip()
    normalized_action = str(required_host_action or "").strip()
    expected_mode = expected_allowed_response_mode(normalized_action)
    allowed_actions = _HOST_ACTION_ALLOWED_ACTIONS.get(normalized_action, ())

    if normalized_mode not in _SUPPORTED_ALLOWED_RESPONSE_MODES:
        return _contract_invalid(
            required_host_action=normalized_action,
            allowed_response_mode=normalized_mode,
            note=f"Unsupported allowed_response_mode={normalized_mode or '<empty>'}",
        )

    if expected_mode is None:
        return _contract_invalid(
            required_host_action=normalized_action,
            allowed_response_mode=normalized_mode,
            note=f"Unsupported required_host_action={normalized_action or '<empty>'}",
        )

    if normalized_mode != expected_mode:
        return _contract_invalid(
            required_host_action=normalized_action,
            allowed_response_mode=normalized_mode,
            note=(
                f"required_host_action={normalized_action} expects "
                f"allowed_response_mode={expected_mode}"
            ),
        )

    if normalized_action in _CHECKPOINT_ACTIONS:
        expected_checkpoint_kind = _CHECKPOINT_REQUEST_KIND_BY_ACTION.get(normalized_action, "")
        if not _has_checkpoint_request(
            checkpoint_request,
            expected_checkpoint_kind=expected_checkpoint_kind,
        ):
            return _contract_invalid(
                required_host_action=normalized_action,
                allowed_response_mode=normalized_mode,
                note=(
                    f"Checkpoint action {normalized_action} requires checkpoint_request proof "
                    f"for checkpoint_kind={expected_checkpoint_kind or '<missing>'}"
                ),
            )
        proofs = [
            f"required_host_action={normalized_action}",
            "checkpoint_request",
            f"checkpoint_request.checkpoint_kind={expected_checkpoint_kind}",
        ]
        run_stage = _run_stage(current_run)
        if run_stage:
            proofs.append(f"current_run.stage={run_stage}")
        gate_next_action = _execution_gate_next_required_action(execution_gate)
        if gate_next_action:
            proofs.append(f"execution_gate.next_required_action={gate_next_action}")
        return DeterministicGuardResult(
            truth_status="stable",
            resolution_enabled=True,
            allowed_response_mode=normalized_mode,
            required_host_action=normalized_action,
            resume_target_kind="checkpoint",
            checkpoint_kind=normalized_action,
            allowed_actions=allowed_actions,
            reason_code=f"guard.checkpoint.stable.{normalized_action}",
            proofs=tuple(proofs),
            notes=(),
        )

    if normalized_action == "review_or_execute_plan":
        return _evaluate_plan_review_guard(
            allowed_response_mode=normalized_mode,
            required_host_action=normalized_action,
            current_run=current_run,
            current_plan=current_plan,
            plan_id=plan_id,
            plan_path=plan_path,
            execution_gate=execution_gate,
            allowed_actions=allowed_actions,
        )

    proofs = [f"required_host_action={normalized_action}"]
    run_stage = _run_stage(current_run)
    if run_stage:
        proofs.append(f"current_run.stage={run_stage}")
    return DeterministicGuardResult(
        truth_status="stable",
        resolution_enabled=True,
        allowed_response_mode=normalized_mode,
        required_host_action=normalized_action,
        resume_target_kind="workflow_safe_start",
        checkpoint_kind="",
        allowed_actions=allowed_actions,
        reason_code=f"guard.workflow.stable.{normalized_action}",
        proofs=tuple(proofs),
        notes=(),
    )


def _evaluate_plan_review_guard(
    *,
    allowed_response_mode: str,
    required_host_action: str,
    current_run: RunState | None,
    current_plan: PlanArtifact | None,
    plan_id: str | None,
    plan_path: str | None,
    execution_gate: ExecutionGate | Mapping[str, Any] | None,
    allowed_actions: tuple[str, ...],
) -> DeterministicGuardResult:
    proofs = [f"required_host_action={required_host_action}"]
    notes: list[str] = []

    identity_matches = False
    if current_plan is not None:
        if plan_id and plan_id == current_plan.plan_id:
            proofs.append("plan_id=current_plan.plan_id")
            identity_matches = True
        if plan_path and plan_path == current_plan.path:
            proofs.append("plan_path=current_plan.path")
            identity_matches = True
    if not identity_matches:
        notes.append("Plan identity proof unavailable; degrading to workflow_safe_start.")

    run_stage = _run_stage(current_run)
    if run_stage:
        proofs.append(f"current_run.stage={run_stage}")

    gate_next_action = _execution_gate_next_required_action(execution_gate)
    if gate_next_action:
        proofs.append(f"execution_gate.next_required_action={gate_next_action}")

    if identity_matches and run_stage in _PLAN_REVIEW_STAGES:
        return DeterministicGuardResult(
            truth_status="stable",
            resolution_enabled=True,
            allowed_response_mode=allowed_response_mode,
            required_host_action=required_host_action,
            resume_target_kind="plan_review",
            checkpoint_kind="",
            allowed_actions=allowed_actions,
            reason_code="guard.plan_review.stable.review_or_execute_plan",
            proofs=tuple(proofs),
            notes=tuple(notes),
        )

    return DeterministicGuardResult(
        truth_status="stable",
        resolution_enabled=True,
        allowed_response_mode=allowed_response_mode,
        required_host_action=required_host_action,
        resume_target_kind="workflow_safe_start",
        checkpoint_kind="",
        allowed_actions=allowed_actions,
        reason_code="guard.plan_review.workflow_safe_start.review_or_execute_plan",
        proofs=tuple(proofs),
        notes=tuple(notes),
    )


def _contract_invalid(
    *,
    required_host_action: str,
    allowed_response_mode: str,
    note: str,
) -> DeterministicGuardResult:
    normalized_action = str(required_host_action or "").strip() or "unknown_host_action"
    return DeterministicGuardResult(
        truth_status="contract_invalid",
        resolution_enabled=False,
        allowed_response_mode=str(allowed_response_mode or "").strip(),
        required_host_action=str(required_host_action or "").strip(),
        resume_target_kind="",
        checkpoint_kind="",
        allowed_actions=(),
        primary_failure_type="truth_layer_contract_invalid",
        fallback_action="enter_blocking_recovery_branch",
        prompt_mode="request_state_recovery",
        retry_policy="manual_recovery_only",
        unresolved_outcome_family="fail_closed",
        reason_code=f"recovery.truth_layer_contract_invalid.fail_closed.{normalized_action}",
        proofs=(),
        notes=(note,),
    )


def _has_checkpoint_request(
    checkpoint_request: Mapping[str, Any] | None,
    *,
    expected_checkpoint_kind: str = "",
) -> bool:
    if not isinstance(checkpoint_request, Mapping):
        return False
    checkpoint_id = str(checkpoint_request.get("checkpoint_id") or "").strip()
    checkpoint_kind = str(checkpoint_request.get("checkpoint_kind") or "").strip()
    if expected_checkpoint_kind:
        return bool(checkpoint_id) and checkpoint_kind == expected_checkpoint_kind
    return bool(checkpoint_id or checkpoint_kind)


def _execution_gate_next_required_action(
    execution_gate: ExecutionGate | Mapping[str, Any] | None,
) -> str:
    if isinstance(execution_gate, ExecutionGate):
        return str(execution_gate.next_required_action or "").strip()
    if isinstance(execution_gate, Mapping):
        return str(execution_gate.get("next_required_action") or "").strip()
    return ""


def _run_stage(current_run: RunState | None) -> str:
    if current_run is None:
        return ""
    return str(current_run.stage or "").strip()
