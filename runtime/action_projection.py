"""Stable action-surface projections for the current V1 guard-rails slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .deterministic_guard import DeterministicGuardResult
from .models import RunState

_SUPPORTED_PROJECTION_ACTIONS = frozenset(
    {
        "answer_questions",
        "confirm_decision",
        "confirm_execute",
        "confirm_plan_package",
        "review_or_execute_plan",
        "continue_host_consult",
        "continue_host_develop",
    }
)


class ActionProjectionError(ValueError):
    """Raised when a guarded action surface cannot be projected safely."""


@dataclass(frozen=True)
class ActionProjection:
    """Minimal structured surface exposed to downstream local resolution."""

    required_host_action: str
    resume_target_kind: str
    checkpoint_kind: str = ""
    allowed_actions: tuple[str, ...] = ()
    fields: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "required_host_action": self.required_host_action,
            "resume_target_kind": self.resume_target_kind,
            "checkpoint_kind": self.checkpoint_kind,
            "allowed_actions": list(self.allowed_actions),
        }
        payload.update(dict(self.fields))
        return payload


def supports_action_projection(required_host_action: str) -> bool:
    """Return whether the current handoff action has a frozen projection surface."""

    return str(required_host_action or "").strip() in _SUPPORTED_PROJECTION_ACTIONS


def build_action_projection(
    guard: DeterministicGuardResult,
    *,
    plan_id: str | None = None,
    plan_path: str | None = None,
    current_run: RunState | None = None,
    artifacts: Mapping[str, Any] | None = None,
) -> ActionProjection:
    """Build the smallest safe action projection from guarded machine facts."""

    if not guard.resolution_enabled or guard.truth_status != "stable":
        raise ActionProjectionError("Action projection requires a stable deterministic guard")

    required_host_action = str(guard.required_host_action or "").strip()
    if not supports_action_projection(required_host_action):
        raise ActionProjectionError(
            f"Unsupported action projection required_host_action={required_host_action!r}"
        )

    normalized_artifacts = dict(artifacts or {})
    builder = _PROJECTION_BUILDERS[required_host_action]
    fields = MappingProxyType(
        builder(
            plan_id=plan_id,
            plan_path=plan_path,
            current_run=current_run,
            artifacts=normalized_artifacts,
        )
    )
    return ActionProjection(
        required_host_action=required_host_action,
        resume_target_kind=guard.resume_target_kind,
        checkpoint_kind=guard.checkpoint_kind,
        allowed_actions=guard.allowed_actions,
        fields=fields,
    )


def _build_answer_questions_fields(
    *,
    plan_id: str | None,
    plan_path: str | None,
    current_run: RunState | None,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "missing_facts": _coerce_string_list(artifacts.get("missing_facts")),
        "questions": _coerce_string_list(artifacts.get("questions")),
    }


def _build_confirm_decision_fields(
    *,
    plan_id: str | None,
    plan_path: str | None,
    current_run: RunState | None,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    checkpoint = _require_mapping(artifacts.get("decision_checkpoint"), label="decision_checkpoint")
    question = str(checkpoint.get("message") or checkpoint.get("title") or "").strip()
    primary_field_id = str(
        checkpoint.get("primary_field_id") or artifacts.get("decision_primary_field_id") or ""
    ).strip()
    options = _extract_decision_options(checkpoint, primary_field_id=primary_field_id)
    return {
        "question": question,
        "options": options,
        "recommended_option_id": str(artifacts.get("recommended_option_id") or "").strip(),
    }


def _build_confirm_execute_fields(
    *,
    plan_id: str | None,
    plan_path: str | None,
    current_run: RunState | None,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    summary = _require_mapping(artifacts.get("execution_summary"), label="execution_summary")
    return {
        "plan_path": str(summary.get("plan_path") or plan_path or "").strip(),
        "risk_level": str(summary.get("risk_level") or "").strip(),
        "key_risk": str(summary.get("key_risk") or "").strip(),
        "mitigation": str(summary.get("mitigation") or "").strip(),
    }


def _build_confirm_plan_package_fields(
    *,
    plan_id: str | None,
    plan_path: str | None,
    current_run: RunState | None,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    proposal = _require_mapping(artifacts.get("proposal"), label="proposal")
    return {
        "analysis_summary": str(proposal.get("analysis_summary") or "").strip(),
        "proposed_path": str(proposal.get("proposed_path") or "").strip(),
        "estimated_task_count": int(proposal.get("estimated_task_count") or 0),
    }


def _build_plan_review_fields(
    *,
    plan_id: str | None,
    plan_path: str | None,
    current_run: RunState | None,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "plan_id": str(plan_id or "").strip(),
        "plan_path": str(plan_path or "").strip(),
        "run_stage": str(getattr(current_run, "stage", "") or "").strip(),
        "next_required_action": "",
    }
    execution_gate = artifacts.get("execution_gate")
    if isinstance(execution_gate, Mapping):
        payload["next_required_action"] = str(
            execution_gate.get("next_required_action") or ""
        ).strip()
    execution_summary = artifacts.get("execution_summary")
    if isinstance(execution_summary, Mapping):
        payload["summary"] = str(execution_summary.get("summary") or "").strip()
        payload["task_count"] = int(execution_summary.get("task_count") or 0)
        payload["risk_level"] = str(execution_summary.get("risk_level") or "").strip()
        payload["key_risk"] = str(execution_summary.get("key_risk") or "").strip()
        payload["mitigation"] = str(execution_summary.get("mitigation") or "").strip()
        if not payload["plan_path"]:
            payload["plan_path"] = str(execution_summary.get("plan_path") or "").strip()
    if not payload["plan_path"]:
        raise ActionProjectionError("review_or_execute_plan projection requires plan_path")
    return payload


def _build_continue_host_consult_fields(
    *,
    plan_id: str | None,
    plan_path: str | None,
    current_run: RunState | None,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "consult_mode": str(artifacts.get("consult_mode") or "readonly").strip(),
    }


def _build_continue_host_develop_fields(
    *,
    plan_id: str | None,
    plan_path: str | None,
    current_run: RunState | None,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    resume_context = artifacts.get("develop_resume_context")
    if not isinstance(resume_context, Mapping):
        resume_context = artifacts.get("resume_context")
    if not isinstance(resume_context, Mapping):
        resume_context = {}
    active_run_stage = str(
        getattr(current_run, "stage", "") or resume_context.get("active_run_stage") or ""
    ).strip()
    return {
        "active_run_stage": active_run_stage,
        "task_refs": _coerce_string_list(resume_context.get("task_refs")),
        "changed_files": _coerce_string_list(resume_context.get("changed_files")),
        "verification_todo": _coerce_string_list(resume_context.get("verification_todo")),
    }


def _extract_decision_options(
    checkpoint: Mapping[str, Any],
    *,
    primary_field_id: str,
) -> list[dict[str, Any]]:
    raw_fields = checkpoint.get("fields")
    if not isinstance(raw_fields, list):
        return []
    selected_field: Mapping[str, Any] | None = None
    for field in raw_fields:
        if not isinstance(field, Mapping):
            continue
        field_id = str(field.get("field_id") or "").strip()
        if primary_field_id and field_id == primary_field_id:
            selected_field = field
            break
        if selected_field is None and isinstance(field.get("options"), list):
            selected_field = field
    if selected_field is None:
        return []

    options: list[dict[str, Any]] = []
    for option in selected_field.get("options", ()):
        if not isinstance(option, Mapping):
            continue
        option_id = str(option.get("id") or option.get("option_id") or "").strip()
        if not option_id:
            continue
        options.append(
            {
                "id": option_id,
                "title": str(option.get("title") or "").strip(),
                "summary": str(option.get("summary") or "").strip(),
                "recommended": bool(option.get("recommended", False)),
            }
        )
    return options


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items: list[str] = []
        for item in value:
            normalized = str(item or "").strip()
            if normalized:
                items.append(normalized)
        return items
    normalized = str(value or "").strip()
    return [normalized] if normalized else []


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ActionProjectionError(f"{label} must be a mapping")
    return value


_PROJECTION_BUILDERS = {
    "answer_questions": _build_answer_questions_fields,
    "confirm_decision": _build_confirm_decision_fields,
    "confirm_execute": _build_confirm_execute_fields,
    "confirm_plan_package": _build_confirm_plan_package_fields,
    "review_or_execute_plan": _build_plan_review_fields,
    "continue_host_consult": _build_continue_host_consult_fields,
    "continue_host_develop": _build_continue_host_develop_fields,
}
