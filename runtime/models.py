"""Shared runtime contracts for Sopify."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional

DECISION_CONDITION_OPERATORS = ("equals", "not_equals", "in", "not_in")
DECISION_FIELD_TYPES = ("select", "multi_select", "confirm", "input", "textarea")
DECISION_SUBMISSION_STATUSES = ("empty", "draft", "collecting", "submitted", "confirmed", "cancelled", "timed_out")
DECISION_STATE_STATUSES = ("pending", "collecting", "confirmed", "consumed", "cancelled", "timed_out", "stale")


@dataclass(frozen=True)
class RuntimeConfig:
    """Normalized runtime configuration."""

    workspace_root: Path
    project_config_path: Optional[Path]
    global_config_path: Optional[Path]
    brand: str
    language: str
    output_style: str
    title_color: str
    workflow_mode: str
    require_score: int
    auto_decide: bool
    workflow_learning_auto_capture: str
    plan_level: str
    plan_directory: str
    multi_model_enabled: bool
    multi_model_trigger: str
    multi_model_timeout_sec: int
    multi_model_max_parallel: int
    multi_model_include_default_model: bool
    ehrb_level: str
    kb_init: str
    cache_project: bool

    @property
    def runtime_root(self) -> Path:
        return self.workspace_root / self.plan_directory

    @property
    def state_dir(self) -> Path:
        return self.runtime_root / "state"

    @property
    def plan_root(self) -> Path:
        return self.runtime_root / "plan"

    @property
    def replay_root(self) -> Path:
        return self.runtime_root / "replay" / "sessions"


@dataclass(frozen=True)
class SkillMeta:
    """Minimal metadata discovered from a skill directory."""

    skill_id: str
    name: str
    description: str
    path: Path
    source: str
    mode: str = "advisory"
    runtime_entry: Optional[Path] = None
    triggers: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    entry_kind: Optional[str] = None
    handoff_kind: Optional[str] = None
    contract_version: str = "1"
    supports_routes: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    requires_network: bool = False
    host_support: tuple[str, ...] = ()
    permission_mode: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
            "source": self.source,
            "mode": self.mode,
            "runtime_entry": str(self.runtime_entry) if self.runtime_entry else None,
            "triggers": list(self.triggers),
            "metadata": dict(self.metadata),
            "entry_kind": self.entry_kind,
            "handoff_kind": self.handoff_kind,
            "contract_version": self.contract_version,
            "supports_routes": list(self.supports_routes),
            "tools": list(self.tools),
            "disallowed_tools": list(self.disallowed_tools),
            "allowed_paths": list(self.allowed_paths),
            "requires_network": self.requires_network,
            "host_support": list(self.host_support),
            "permission_mode": self.permission_mode,
        }


@dataclass(frozen=True)
class RouteDecision:
    """Deterministic route classification result."""

    route_name: str
    request_text: str
    reason: str
    command: Optional[str] = None
    complexity: str = "simple"
    plan_level: Optional[str] = None
    candidate_skill_ids: tuple[str, ...] = ()
    should_recover_context: bool = False
    should_create_plan: bool = False
    capture_mode: str = "off"
    runtime_skill_id: Optional[str] = None
    active_run_action: Optional[str] = None
    artifacts: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_name": self.route_name,
            "request_text": self.request_text,
            "reason": self.reason,
            "command": self.command,
            "complexity": self.complexity,
            "plan_level": self.plan_level,
            "candidate_skill_ids": list(self.candidate_skill_ids),
            "should_recover_context": self.should_recover_context,
            "should_create_plan": self.should_create_plan,
            "capture_mode": self.capture_mode,
            "runtime_skill_id": self.runtime_skill_id,
            "active_run_action": self.active_run_action,
            "artifacts": _json_mapping(self.artifacts),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RouteDecision":
        return cls(
            route_name=str(data.get("route_name") or "consult"),
            request_text=str(data.get("request_text") or ""),
            reason=str(data.get("reason") or ""),
            command=data.get("command") or None,
            complexity=str(data.get("complexity") or "simple"),
            plan_level=data.get("plan_level") or None,
            candidate_skill_ids=tuple(data.get("candidate_skill_ids") or ()),
            should_recover_context=bool(data.get("should_recover_context", False)),
            should_create_plan=bool(data.get("should_create_plan", False)),
            capture_mode=str(data.get("capture_mode") or "off"),
            runtime_skill_id=data.get("runtime_skill_id") or None,
            active_run_action=data.get("active_run_action") or None,
            artifacts=_json_mapping(data.get("artifacts")),
        )


@dataclass(frozen=True)
class ExecutionGate:
    """Deterministic machine contract describing whether a plan can progress."""

    gate_status: str
    blocking_reason: str
    plan_completion: str
    next_required_action: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_status": self.gate_status,
            "blocking_reason": self.blocking_reason,
            "plan_completion": self.plan_completion,
            "next_required_action": self.next_required_action,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionGate":
        return cls(
            gate_status=str(data.get("gate_status") or "blocked"),
            blocking_reason=str(data.get("blocking_reason") or "none"),
            plan_completion=str(data.get("plan_completion") or "incomplete"),
            next_required_action=str(data.get("next_required_action") or "continue_host_develop"),
            notes=tuple(data.get("notes") or ()),
        )


@dataclass(frozen=True)
class ExecutionSummary:
    """Minimum summary shown before execution confirmation."""

    plan_path: str
    summary: str
    task_count: int
    risk_level: str
    key_risk: str
    mitigation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_path": self.plan_path,
            "summary": self.summary,
            "task_count": self.task_count,
            "risk_level": self.risk_level,
            "key_risk": self.key_risk,
            "mitigation": self.mitigation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionSummary":
        return cls(
            plan_path=str(data.get("plan_path") or ""),
            summary=str(data.get("summary") or ""),
            task_count=int(data.get("task_count") or 0),
            risk_level=str(data.get("risk_level") or "medium"),
            key_risk=str(data.get("key_risk") or ""),
            mitigation=str(data.get("mitigation") or ""),
        )


@dataclass(frozen=True)
class RunState:
    """Persistent state for the active runtime flow."""

    run_id: str
    status: str
    stage: str
    route_name: str
    title: str
    created_at: str
    updated_at: str
    plan_id: Optional[str] = None
    plan_path: Optional[str] = None
    execution_gate: Optional[ExecutionGate] = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "stage": self.stage,
            "route_name": self.route_name,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan_id": self.plan_id,
            "plan_path": self.plan_path,
            "execution_gate": self.execution_gate.to_dict() if self.execution_gate else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunState":
        return cls(
            run_id=str(data.get("run_id") or ""),
            status=str(data.get("status") or "inactive"),
            stage=str(data.get("stage") or "idle"),
            route_name=str(data.get("route_name") or "consult"),
            title=str(data.get("title") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            plan_id=data.get("plan_id") or None,
            plan_path=data.get("plan_path") or None,
            execution_gate=ExecutionGate.from_dict(data["execution_gate"]) if isinstance(data.get("execution_gate"), Mapping) else None,
        )


@dataclass(frozen=True)
class DecisionCondition:
    """A minimal conditional expression used to reveal dependent fields."""

    field_id: str
    operator: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "operator": self.operator,
            "value": _json_value(self.value),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionCondition":
        return cls(
            field_id=str(data.get("field_id") or ""),
            operator=_normalize_keyword(data.get("operator"), allowed=DECISION_CONDITION_OPERATORS, default="equals"),
            value=_json_value(data.get("value")),
        )


@dataclass(frozen=True)
class DecisionValidation:
    """A lightweight validation rule descriptor for host-side decision forms."""

    rule: str
    message: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "message": self.message,
            "value": _json_value(self.value),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionValidation":
        return cls(
            rule=str(data.get("rule") or ""),
            message=str(data.get("message") or ""),
            value=_json_value(data.get("value")),
        )


@dataclass(frozen=True)
class DecisionOption:
    """A concrete option presented by a decision checkpoint."""

    option_id: str
    title: str
    summary: str
    tradeoffs: tuple[str, ...] = ()
    impacts: tuple[str, ...] = ()
    recommended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.option_id,
            "title": self.title,
            "summary": self.summary,
            "tradeoffs": list(self.tradeoffs),
            "impacts": list(self.impacts),
            "recommended": self.recommended,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionOption":
        return cls(
            option_id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            summary=str(data.get("summary") or ""),
            tradeoffs=tuple(data.get("tradeoffs") or ()),
            impacts=tuple(data.get("impacts") or ()),
            recommended=bool(data.get("recommended", False)),
        )


@dataclass(frozen=True)
class DecisionField:
    """A host-renderable field inside a decision checkpoint."""

    field_id: str
    field_type: str
    label: str
    description: str = ""
    required: bool = False
    options: tuple[DecisionOption, ...] = ()
    default_value: Any = None
    when: tuple[DecisionCondition, ...] = ()
    validations: tuple[DecisionValidation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "field_type": self.field_type,
            "label": self.label,
            "description": self.description,
            "required": self.required,
            "options": [option.to_dict() for option in self.options],
            "default_value": _json_value(self.default_value),
            "when": [condition.to_dict() for condition in self.when],
            "validations": [validation.to_dict() for validation in self.validations],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionField":
        return cls(
            field_id=str(data.get("field_id") or ""),
            field_type=_normalize_keyword(data.get("field_type") or data.get("type"), allowed=DECISION_FIELD_TYPES, default="input"),
            label=str(data.get("label") or ""),
            description=str(data.get("description") or ""),
            required=bool(data.get("required", False)),
            options=tuple(DecisionOption.from_dict(option) for option in (data.get("options") or ())),
            default_value=_json_value(data.get("default_value")),
            when=tuple(DecisionCondition.from_dict(condition) for condition in (data.get("when") or ())),
            validations=tuple(DecisionValidation.from_dict(validation) for validation in (data.get("validations") or ())),
        )


@dataclass(frozen=True)
class DecisionRecommendation:
    """The runtime's recommended path for a decision checkpoint."""

    field_id: str
    option_id: Optional[str] = None
    summary: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "option_id": self.option_id,
            "summary": self.summary,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionRecommendation":
        return cls(
            field_id=str(data.get("field_id") or ""),
            option_id=data.get("option_id") or None,
            summary=str(data.get("summary") or ""),
            reason=str(data.get("reason") or ""),
        )


@dataclass(frozen=True)
class DecisionCheckpoint:
    """A host-renderable, structured checkpoint definition."""

    checkpoint_id: str
    title: str
    message: str
    fields: tuple[DecisionField, ...]
    primary_field_id: Optional[str] = None
    recommendation: Optional[DecisionRecommendation] = None
    blocking: bool = True
    allow_text_fallback: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "title": self.title,
            "message": self.message,
            "fields": [field.to_dict() for field in self.fields],
            "primary_field_id": self.primary_field_id,
            "recommendation": self.recommendation.to_dict() if self.recommendation else None,
            "blocking": self.blocking,
            "allow_text_fallback": self.allow_text_fallback,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionCheckpoint":
        recommendation = data.get("recommendation")
        return cls(
            checkpoint_id=str(data.get("checkpoint_id") or ""),
            title=str(data.get("title") or ""),
            message=str(data.get("message") or ""),
            fields=tuple(DecisionField.from_dict(field) for field in (data.get("fields") or ())),
            primary_field_id=data.get("primary_field_id") or None,
            recommendation=DecisionRecommendation.from_dict(recommendation) if isinstance(recommendation, Mapping) else None,
            blocking=bool(data.get("blocking", True)),
            allow_text_fallback=bool(data.get("allow_text_fallback", True)),
        )


@dataclass(frozen=True)
class DecisionSelection:
    """User-confirmed selection captured by the checkpoint."""

    option_id: str
    source: str
    raw_input: str
    answers: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "source": self.source,
            "raw_input": self.raw_input,
            "answers": _json_mapping(self.answers),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionSelection":
        return cls(
            option_id=str(data.get("option_id") or ""),
            source=str(data.get("source") or "text"),
            raw_input=str(data.get("raw_input") or ""),
            answers=_json_mapping(data.get("answers")),
        )


@dataclass(frozen=True)
class DecisionSubmission:
    """Structured answers written by a host bridge before runtime resumes."""

    status: str
    source: str
    answers: Mapping[str, Any] = field(default_factory=dict)
    raw_input: str = ""
    message: str = ""
    submitted_at: Optional[str] = None
    resume_action: str = "submit"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "answers": _json_mapping(self.answers),
            "raw_input": self.raw_input,
            "message": self.message,
            "submitted_at": self.submitted_at,
            "resume_action": self.resume_action,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionSubmission":
        return cls(
            status=_normalize_keyword(data.get("status"), allowed=DECISION_SUBMISSION_STATUSES, default="empty"),
            source=str(data.get("source") or "host"),
            answers=_json_mapping(data.get("answers")),
            raw_input=str(data.get("raw_input") or ""),
            message=str(data.get("message") or ""),
            submitted_at=data.get("submitted_at") or None,
            resume_action=str(data.get("resume_action") or "submit"),
        )


@dataclass(frozen=True)
class DecisionState:
    """Filesystem-backed pending design decision."""

    schema_version: str
    decision_id: str
    feature_key: str
    phase: str
    status: str
    decision_type: str
    question: str
    summary: str
    options: tuple[DecisionOption, ...]
    checkpoint: Optional[DecisionCheckpoint] = None
    submission: Optional[DecisionSubmission] = None
    recommended_option_id: Optional[str] = None
    default_option_id: Optional[str] = None
    context_files: tuple[str, ...] = ()
    resume_route: Optional[str] = None
    request_text: str = ""
    requested_plan_level: Optional[str] = None
    capture_mode: str = "off"
    candidate_skill_ids: tuple[str, ...] = ()
    policy_id: str = ""
    trigger_reason: str = ""
    resume_context: Mapping[str, Any] = field(default_factory=dict)
    selection: Optional[DecisionSelection] = None
    created_at: str = ""
    updated_at: str = ""
    confirmed_at: Optional[str] = None
    consumed_at: Optional[str] = None

    @property
    def selected_option_id(self) -> Optional[str]:
        return self.selection.option_id if self.selection is not None else None

    @property
    def active_checkpoint(self) -> DecisionCheckpoint:
        if self.checkpoint is not None:
            return self.checkpoint
        recommendation = None
        if self.recommended_option_id:
            recommendation = DecisionRecommendation(
                field_id="selected_option_id",
                option_id=self.recommended_option_id,
                summary=self.summary,
                reason=self.summary,
            )
        return DecisionCheckpoint(
            checkpoint_id=self.decision_id,
            title=self.question or self.summary or self.decision_type,
            message=self.summary or self.question,
            fields=(
                DecisionField(
                    field_id="selected_option_id",
                    field_type="select",
                    label=self.question or "Decision",
                    description=self.summary,
                    required=True,
                    options=self.options,
                    default_value=self.default_option_id,
                ),
            ),
            primary_field_id="selected_option_id",
            recommendation=recommendation,
        )

    @property
    def primary_field_id(self) -> Optional[str]:
        checkpoint = self.active_checkpoint
        if checkpoint.primary_field_id:
            return checkpoint.primary_field_id
        for field in checkpoint.fields:
            if field.field_type:
                return field.field_id
        return None

    @property
    def has_submitted_answers(self) -> bool:
        if self.submission is None:
            return False
        return self.submission.status in {"submitted", "confirmed", "cancelled", "timed_out"}

    def with_submission(self, submission: DecisionSubmission) -> "DecisionState":
        next_status = self.status
        if submission.status in {"draft", "collecting"}:
            next_status = "collecting"
        elif submission.status in {"cancelled", "timed_out"}:
            next_status = submission.status
        elif self.status not in {"confirmed", "consumed", "stale"}:
            next_status = "pending"
        return replace(
            self,
            status=next_status,
            submission=submission,
            updated_at=submission.submitted_at or self.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "feature_key": self.feature_key,
            "phase": self.phase,
            "status": self.status,
            "decision_type": self.decision_type,
            "question": self.question,
            "summary": self.summary,
            "options": [option.to_dict() for option in self.options],
            "checkpoint": self.active_checkpoint.to_dict(),
            "submission": self.submission.to_dict() if self.submission else None,
            "recommended_option_id": self.recommended_option_id,
            "default_option_id": self.default_option_id,
            "context_files": list(self.context_files),
            "resume_route": self.resume_route,
            "request_text": self.request_text,
            "requested_plan_level": self.requested_plan_level,
            "capture_mode": self.capture_mode,
            "candidate_skill_ids": list(self.candidate_skill_ids),
            "policy_id": self.policy_id,
            "trigger_reason": self.trigger_reason,
            "resume_context": _json_mapping(self.resume_context),
            "selection": self.selection.to_dict() if self.selection else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "confirmed_at": self.confirmed_at,
            "consumed_at": self.consumed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionState":
        checkpoint = data.get("checkpoint")
        selection = data.get("selection")
        submission = data.get("submission")
        return cls(
            schema_version=str(data.get("schema_version") or "2"),
            decision_id=str(data.get("decision_id") or ""),
            feature_key=str(data.get("feature_key") or ""),
            phase=str(data.get("phase") or "design"),
            status=_normalize_keyword(data.get("status"), allowed=DECISION_STATE_STATUSES, default="pending"),
            decision_type=str(data.get("decision_type") or "design_choice"),
            question=str(data.get("question") or ""),
            summary=str(data.get("summary") or ""),
            options=tuple(DecisionOption.from_dict(option) for option in (data.get("options") or ())),
            checkpoint=DecisionCheckpoint.from_dict(checkpoint) if isinstance(checkpoint, Mapping) else None,
            submission=DecisionSubmission.from_dict(submission) if isinstance(submission, Mapping) else None,
            recommended_option_id=data.get("recommended_option_id") or None,
            default_option_id=data.get("default_option_id") or None,
            context_files=tuple(data.get("context_files") or ()),
            resume_route=data.get("resume_route") or None,
            request_text=str(data.get("request_text") or ""),
            requested_plan_level=data.get("requested_plan_level") or None,
            capture_mode=str(data.get("capture_mode") or "off"),
            candidate_skill_ids=tuple(data.get("candidate_skill_ids") or ()),
            policy_id=str(data.get("policy_id") or ""),
            trigger_reason=str(data.get("trigger_reason") or ""),
            resume_context=_json_mapping(data.get("resume_context")),
            selection=DecisionSelection.from_dict(selection) if isinstance(selection, Mapping) else None,
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            confirmed_at=data.get("confirmed_at") or None,
            consumed_at=data.get("consumed_at") or None,
        )


@dataclass(frozen=True)
class ClarificationState:
    """Filesystem-backed pending clarification checkpoint."""

    clarification_id: str
    feature_key: str
    phase: str
    status: str
    summary: str
    questions: tuple[str, ...]
    missing_facts: tuple[str, ...]
    context_files: tuple[str, ...] = ()
    resume_route: Optional[str] = None
    request_text: str = ""
    requested_plan_level: Optional[str] = None
    capture_mode: str = "off"
    candidate_skill_ids: tuple[str, ...] = ()
    resume_context: Mapping[str, Any] = field(default_factory=dict)
    response_text: Optional[str] = None
    response_fields: Mapping[str, Any] = field(default_factory=dict)
    response_source: Optional[str] = None
    response_message: str = ""
    response_submitted_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    answered_at: Optional[str] = None
    consumed_at: Optional[str] = None

    @property
    def has_response(self) -> bool:
        return bool((self.response_text or "").strip() or self.response_fields)

    def with_response(
        self,
        *,
        response_text: str,
        response_fields: Mapping[str, Any],
        response_source: str | None,
        response_message: str = "",
        submitted_at: str,
    ) -> "ClarificationState":
        return replace(
            self,
            response_text=response_text,
            response_fields=_json_mapping(response_fields),
            response_source=response_source,
            response_message=response_message,
            response_submitted_at=submitted_at,
            updated_at=submitted_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "clarification_id": self.clarification_id,
            "feature_key": self.feature_key,
            "phase": self.phase,
            "status": self.status,
            "summary": self.summary,
            "questions": list(self.questions),
            "missing_facts": list(self.missing_facts),
            "context_files": list(self.context_files),
            "resume_route": self.resume_route,
            "request_text": self.request_text,
            "requested_plan_level": self.requested_plan_level,
            "capture_mode": self.capture_mode,
            "candidate_skill_ids": list(self.candidate_skill_ids),
            "resume_context": _json_mapping(self.resume_context),
            "response_text": self.response_text,
            "response_fields": _json_mapping(self.response_fields),
            "response_source": self.response_source,
            "response_message": self.response_message,
            "response_submitted_at": self.response_submitted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "answered_at": self.answered_at,
            "consumed_at": self.consumed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClarificationState":
        return cls(
            clarification_id=str(data.get("clarification_id") or ""),
            feature_key=str(data.get("feature_key") or ""),
            phase=str(data.get("phase") or "analyze"),
            status=str(data.get("status") or "pending"),
            summary=str(data.get("summary") or ""),
            questions=tuple(data.get("questions") or ()),
            missing_facts=tuple(data.get("missing_facts") or ()),
            context_files=tuple(data.get("context_files") or ()),
            resume_route=data.get("resume_route") or None,
            request_text=str(data.get("request_text") or ""),
            requested_plan_level=data.get("requested_plan_level") or None,
            capture_mode=str(data.get("capture_mode") or "off"),
            candidate_skill_ids=tuple(data.get("candidate_skill_ids") or ()),
            resume_context=_json_mapping(data.get("resume_context")),
            response_text=data.get("response_text") or None,
            response_fields=_json_mapping(data.get("response_fields")),
            response_source=data.get("response_source") or None,
            response_message=str(data.get("response_message") or ""),
            response_submitted_at=data.get("response_submitted_at") or None,
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            answered_at=data.get("answered_at") or None,
            consumed_at=data.get("consumed_at") or None,
        )


@dataclass(frozen=True)
class PlanArtifact:
    """Generated plan package metadata."""

    plan_id: str
    title: str
    summary: str
    level: str
    path: str
    files: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "summary": self.summary,
            "level": self.level,
            "path": self.path,
            "files": list(self.files),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanArtifact":
        return cls(
            plan_id=str(data.get("plan_id") or ""),
            title=str(data.get("title") or ""),
            summary=str(data.get("summary") or ""),
            level=str(data.get("level") or "light"),
            path=str(data.get("path") or ""),
            files=tuple(data.get("files") or ()),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass(frozen=True)
class KbArtifact:
    """Minimal knowledge-base files created by the runtime."""

    mode: str
    files: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "files": list(self.files),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class RecoveredContext:
    """Minimal context recovered from filesystem state."""

    loaded_files: tuple[str, ...] = ()
    current_run: Optional[RunState] = None
    current_plan: Optional[PlanArtifact] = None
    current_clarification: Optional[ClarificationState] = None
    current_decision: Optional[DecisionState] = None
    last_route: Optional[RouteDecision] = None
    documents: Mapping[str, str] = field(default_factory=dict)

    @property
    def has_active_run(self) -> bool:
        return self.current_run is not None and self.current_run.is_active

    def to_dict(self) -> dict[str, Any]:
        return {
            "loaded_files": list(self.loaded_files),
            "current_run": self.current_run.to_dict() if self.current_run else None,
            "current_plan": self.current_plan.to_dict() if self.current_plan else None,
            "current_clarification": self.current_clarification.to_dict() if self.current_clarification else None,
            "current_decision": self.current_decision.to_dict() if self.current_decision else None,
            "last_route": self.last_route.to_dict() if self.last_route else None,
            "documents": dict(self.documents),
        }


@dataclass(frozen=True)
class RuntimeHandoff:
    """Structured machine handoff for downstream host execution."""

    schema_version: str
    route_name: str
    run_id: str
    plan_id: Optional[str] = None
    plan_path: Optional[str] = None
    handoff_kind: str = "default"
    required_host_action: str = "continue_host_workflow"
    recommended_skill_ids: tuple[str, ...] = ()
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "route_name": self.route_name,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "plan_path": self.plan_path,
            "handoff_kind": self.handoff_kind,
            "required_host_action": self.required_host_action,
            "recommended_skill_ids": list(self.recommended_skill_ids),
            "artifacts": dict(self.artifacts),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeHandoff":
        artifacts = data.get("artifacts")
        return cls(
            schema_version=str(data.get("schema_version") or "1"),
            route_name=str(data.get("route_name") or "consult"),
            run_id=str(data.get("run_id") or ""),
            plan_id=data.get("plan_id") or None,
            plan_path=data.get("plan_path") or None,
            handoff_kind=str(data.get("handoff_kind") or "default"),
            required_host_action=str(data.get("required_host_action") or "continue_host_workflow"),
            recommended_skill_ids=tuple(data.get("recommended_skill_ids") or ()),
            artifacts=dict(artifacts) if isinstance(artifacts, Mapping) else {},
            notes=tuple(data.get("notes") or ()),
        )


@dataclass(frozen=True)
class ReplayEvent:
    """Append-only replay event payload."""

    ts: str
    phase: str
    intent: str
    action: str
    key_output: str
    decision_reason: str
    result: str
    risk: str = ""
    alternatives: tuple[str, ...] = ()
    highlights: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "phase": self.phase,
            "intent": self.intent,
            "action": self.action,
            "key_output": self.key_output,
            "decision_reason": self.decision_reason,
            "result": self.result,
            "risk": self.risk,
            "alternatives": list(self.alternatives),
            "highlights": list(self.highlights),
            "artifacts": list(self.artifacts),
        }


@dataclass(frozen=True)
class RuntimeResult:
    """Top-level runtime result returned by the engine."""

    route: RouteDecision
    recovered_context: RecoveredContext
    discovered_skills: tuple[SkillMeta, ...] = ()
    kb_artifact: Optional[KbArtifact] = None
    plan_artifact: Optional[PlanArtifact] = None
    skill_result: Optional[Mapping[str, Any]] = None
    replay_session_dir: Optional[str] = None
    handoff: Optional[RuntimeHandoff] = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.to_dict(),
            "recovered_context": self.recovered_context.to_dict(),
            "discovered_skills": [skill.to_dict() for skill in self.discovered_skills],
            "kb_artifact": self.kb_artifact.to_dict() if self.kb_artifact else None,
            "plan_artifact": self.plan_artifact.to_dict() if self.plan_artifact else None,
            "skill_result": dict(self.skill_result or {}),
            "replay_session_dir": self.replay_session_dir,
            "handoff": self.handoff.to_dict() if self.handoff else None,
            "notes": list(self.notes),
        }


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _json_value(item) for key, item in value.items()}


def _normalize_keyword(value: Any, *, allowed: tuple[str, ...], default: str) -> str:
    normalized = str(value or default).strip().casefold().replace("-", "_")
    for candidate in allowed:
        if normalized == candidate.casefold():
            return candidate
    return default
