"""Deterministic decision-checkpoint helpers for design-stage branching."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha1
import re
from typing import Any, Optional

from .decision_policy import match_decision_policy, should_trigger_decision_policy
from .decision_templates import PRIMARY_OPTION_FIELD_ID, build_strategy_pick_template
from .knowledge_layout import resolve_context_profile
from .models import (
    DecisionOption,
    DecisionSelection,
    DecisionState,
    DecisionSubmission,
    ExecutionGate,
    PlanArtifact,
    RouteDecision,
    RuntimeConfig,
)

CURRENT_DECISION_FILENAME = "current_decision.json"
CURRENT_DECISION_RELATIVE_PATH = f".sopify-skills/state/{CURRENT_DECISION_FILENAME}"
ACTIVE_PLAN_BINDING_DECISION_TYPE = "active_plan_binding_choice"
ACTIVE_PLAN_ATTACH_OPTION_ID = "attach_current_plan"
ACTIVE_PLAN_NEW_OPTION_ID = "create_new_plan"

_DECIDE_COMMAND_RE = re.compile(r"^~decide(?:\s+(?P<verb>status|cancel|choose))?(?:\s+(?P<body>.+))?$", re.IGNORECASE)
_STATUS_ALIASES = {"status", "查看决策", "查看当前决策", "decision status"}
_CONTINUE_ALIASES = {"继续", "继续执行", "下一步", "resume", "continue", "next"}
_CANCEL_ALIASES = {"取消", "停止", "终止", "abort", "cancel", "stop"}
_PUNCTUATION_RE = re.compile(r"[\s`'\"“”‘’.,:;!?(){}\[\]<>/\\|_-]+")


@dataclass(frozen=True)
class DecisionResponse:
    """Normalized interpretation of a user response to a pending decision."""

    action: str
    option_id: Optional[str] = None
    source: str = "text"
    message: str = ""


def should_trigger_decision_checkpoint(route: RouteDecision) -> bool:
    """Return True when the current planning route should pause for a decision."""
    return should_trigger_decision_policy(route)


def build_decision_state(route: RouteDecision, *, config: RuntimeConfig) -> DecisionState | None:
    """Create a deterministic decision packet from a planning request."""
    match = match_decision_policy(route)
    if match is None:
        return None

    created_at = iso_now()
    feature_key = _feature_key(route.request_text)
    options = match.options or tuple(
        _build_option(
            f"option_{index}",
            raw_text,
            recommended=(index - 1) == match.recommended_option_index,
            language=config.language,
        )
        for index, raw_text in enumerate(match.option_texts, start=1)
    )
    summary = match.summary or _summary_for_language(config.language)
    recommended_option_id = (
        options[match.recommended_option_index].option_id
        if 0 <= match.recommended_option_index < len(options)
        else None
    )
    default_option_id = (
        options[match.default_option_index].option_id
        if 0 <= match.default_option_index < len(options)
        else recommended_option_id
    )
    rendered = build_strategy_pick_template(
        checkpoint_id=_decision_id(route.request_text),
        question=match.question,
        summary=summary,
        options=options,
        language=config.language,
        recommended_option_id=recommended_option_id,
        default_option_id=default_option_id,
    )
    selection = resolve_context_profile(config=config, profile="decision")
    context_files = tuple(dict.fromkeys((*selection.files, *match.context_files)))

    return DecisionState(
        schema_version="2",
        decision_id=_decision_id(route.request_text),
        feature_key=feature_key,
        phase="design",
        status="pending",
        decision_type=match.decision_type,
        question=match.question,
        summary=summary,
        options=rendered.options,
        checkpoint=rendered.checkpoint,
        recommended_option_id=rendered.recommended_option_id,
        default_option_id=rendered.default_option_id,
        context_files=context_files,
        resume_route=route.route_name,
        request_text=route.request_text,
        requested_plan_level=route.plan_level,
        capture_mode=route.capture_mode,
        candidate_skill_ids=route.candidate_skill_ids,
        policy_id=match.policy_id,
        trigger_reason=match.trigger_reason,
        created_at=created_at,
        updated_at=created_at,
    )


def build_execution_gate_decision_state(
    route: RouteDecision,
    *,
    gate: ExecutionGate,
    current_plan: PlanArtifact,
    config: RuntimeConfig,
) -> DecisionState | None:
    """Create a follow-up decision checkpoint for gate-detected blocking risks."""
    if gate.gate_status != "decision_required" or gate.blocking_reason in {"none", "unresolved_decision"}:
        return None

    created_at = iso_now()
    decision_type = f"execution_gate_{gate.blocking_reason}"
    question, summary, options = _gate_decision_payload(
        gate.blocking_reason,
        plan_path=current_plan.path,
        language=config.language,
    )
    rendered = build_strategy_pick_template(
        checkpoint_id=_execution_gate_decision_id(current_plan.plan_id, gate.blocking_reason),
        question=question,
        summary=summary,
        options=options,
        language=config.language,
        recommended_option_id=options[0].option_id,
        default_option_id=options[0].option_id,
    )
    return DecisionState(
        schema_version="2",
        decision_id=_execution_gate_decision_id(current_plan.plan_id, gate.blocking_reason),
        feature_key=current_plan.plan_id,
        phase="design",
        status="pending",
        decision_type=decision_type,
        question=question,
        summary=summary,
        options=rendered.options,
        checkpoint=rendered.checkpoint,
        recommended_option_id=rendered.recommended_option_id,
        default_option_id=rendered.default_option_id,
        context_files=resolve_context_profile(
            config=config,
            profile="decision",
            current_plan=current_plan,
        ).files,
        resume_route=route.route_name,
        request_text=route.request_text,
        requested_plan_level=current_plan.level,
        capture_mode=route.capture_mode,
        candidate_skill_ids=route.candidate_skill_ids,
        policy_id="execution_gate_blocking_risk",
        trigger_reason=gate.blocking_reason,
        created_at=created_at,
        updated_at=created_at,
    )


def build_active_plan_binding_decision_state(
    route: RouteDecision,
    *,
    current_plan: PlanArtifact,
    config: RuntimeConfig,
) -> DecisionState:
    """Ask whether a new non-anchored request should attach to the active plan or branch into a new one."""
    created_at = iso_now()
    question, summary, options = _active_plan_binding_payload(
        current_plan=current_plan,
        request_text=route.request_text,
        language=config.language,
    )
    rendered = build_strategy_pick_template(
        checkpoint_id=_active_plan_binding_decision_id(current_plan.plan_id, route.request_text),
        question=question,
        summary=summary,
        options=options,
        language=config.language,
        recommended_option_id=None,
        default_option_id=None,
    )
    return DecisionState(
        schema_version="2",
        decision_id=_active_plan_binding_decision_id(current_plan.plan_id, route.request_text),
        feature_key=current_plan.plan_id,
        phase="design",
        status="pending",
        decision_type=ACTIVE_PLAN_BINDING_DECISION_TYPE,
        question=question,
        summary=summary,
        options=rendered.options,
        checkpoint=rendered.checkpoint,
        recommended_option_id=rendered.recommended_option_id,
        default_option_id=rendered.default_option_id,
        context_files=resolve_context_profile(
            config=config,
            profile="decision",
            current_plan=current_plan,
        ).files,
        resume_route=route.route_name,
        request_text=route.request_text,
        requested_plan_level=route.plan_level or current_plan.level,
        capture_mode=route.capture_mode,
        candidate_skill_ids=route.candidate_skill_ids,
        policy_id="active_plan_routing_choice",
        trigger_reason="non_anchored_complex_request_with_active_plan",
        resume_context={
            "active_plan_id": current_plan.plan_id,
            "active_plan_path": current_plan.path,
        },
        created_at=created_at,
        updated_at=created_at,
    )


def parse_decision_response(decision_state: DecisionState, user_input: str) -> DecisionResponse:
    """Interpret a raw user response against the current decision packet."""
    text = user_input.strip()
    if not text:
        return DecisionResponse(action="invalid", message="Empty decision response")

    command_match = _DECIDE_COMMAND_RE.match(text)
    if command_match:
        verb = (command_match.group("verb") or "status").lower()
        body = (command_match.group("body") or "").strip()
        if verb == "status":
            return DecisionResponse(action="status", source="debug_override")
        if verb == "cancel":
            return DecisionResponse(action="cancel", source="debug_override")
        if verb == "choose":
            option_id = _match_option(decision_state, body)
            if option_id is None:
                return DecisionResponse(action="invalid", source="debug_override", message=f"Unknown option: {body or '<empty>'}")
            return DecisionResponse(action="choose", option_id=option_id, source="debug_override")

    normalized = text.casefold()
    if normalized in {alias.casefold() for alias in _STATUS_ALIASES}:
        return DecisionResponse(action="status")
    if normalized in {alias.casefold() for alias in _CANCEL_ALIASES}:
        return DecisionResponse(action="cancel")
    if decision_state.status == "confirmed" and normalized in {alias.casefold() for alias in _CONTINUE_ALIASES}:
        return DecisionResponse(action="materialize")

    option_id = _match_option(decision_state, text)
    if option_id is not None:
        return DecisionResponse(action="choose", option_id=option_id, source="text")

    return DecisionResponse(action="invalid", message=f"Unrecognized decision response: {text}")


def update_decision_submission(
    decision_state: DecisionState,
    *,
    answers: dict[str, Any],
    source: str,
    resume_action: str = "submit",
    raw_input: str = "",
    message: str = "",
    status: str = "submitted",
) -> DecisionState:
    """Persist a structured submission before runtime resumes the checkpoint."""
    submission = DecisionSubmission(
        status=status,
        source=source,
        answers=answers,
        raw_input=raw_input,
        message=message,
        submitted_at=iso_now(),
        resume_action=resume_action,
    )
    return decision_state.with_submission(submission)


def has_submitted_decision(decision_state: DecisionState) -> bool:
    """Return True when a host bridge already collected structured answers."""
    return decision_state.has_submitted_answers


def response_from_submission(decision_state: DecisionState) -> DecisionResponse | None:
    """Interpret a structured submission written by the host bridge."""
    submission = decision_state.submission
    if submission is None or submission.status not in {"submitted", "confirmed", "cancelled", "timed_out"}:
        return None

    normalized_action = submission.resume_action.strip().casefold()
    if normalized_action in {"cancel", "cancelled"} or submission.status == "cancelled":
        return DecisionResponse(action="cancel", source=submission.source)
    if normalized_action in {"status", "inspect"}:
        return DecisionResponse(action="status", source=submission.source)
    if submission.status == "timed_out":
        return DecisionResponse(action="invalid", source=submission.source, message=submission.message or "Decision submission timed out")

    option_id = _option_id_from_submission(decision_state, submission)
    if option_id is None:
        return DecisionResponse(
            action="invalid",
            source=submission.source,
            message=submission.message or "Structured decision submission did not contain a valid option",
        )
    return DecisionResponse(action="choose", option_id=option_id, source=submission.source)


def confirm_decision(decision_state: DecisionState, *, option_id: str, source: str, raw_input: str) -> DecisionState:
    """Mark a decision as confirmed while preserving recovery data."""
    now = iso_now()
    answers = _selection_answers(decision_state, option_id)
    previous_submission = decision_state.submission
    submission = DecisionSubmission(
        status="confirmed",
        source=source or (previous_submission.source if previous_submission is not None else "text"),
        answers=answers,
        raw_input=raw_input or (previous_submission.raw_input if previous_submission is not None else ""),
        message=previous_submission.message if previous_submission is not None else "",
        submitted_at=(previous_submission.submitted_at if previous_submission is not None else None) or now,
        resume_action="submit",
    )
    return replace(
        decision_state,
        status="confirmed",
        submission=submission,
        selection=DecisionSelection(
            option_id=option_id,
            source=source,
            raw_input=raw_input,
            answers=answers,
        ),
        updated_at=now,
        confirmed_at=now,
        consumed_at=None,
    )


def consume_decision(decision_state: DecisionState) -> DecisionState:
    """Mark a decision as consumed before clearing it from current state."""
    now = iso_now()
    return replace(decision_state, status="consumed", updated_at=now, consumed_at=now)


def stale_decision(decision_state: DecisionState) -> DecisionState:
    """Return a stale copy when a pending checkpoint is superseded."""
    now = iso_now()
    return replace(decision_state, status="stale", updated_at=now)


def option_by_id(decision_state: DecisionState, option_id: str) -> DecisionOption | None:
    """Return the option matching the given id."""
    for option in decision_state.options:
        if option.option_id == option_id:
            return option
    return None

def _build_option(option_id: str, raw_text: str, *, recommended: bool, language: str) -> DecisionOption:
    summary = raw_text
    if language == "en-US":
        tradeoffs = ("Will change the downstream plan shape and long-lived docs.",)
        impacts = ("Requires explicit confirmation before a formal plan is generated.",)
    else:
        tradeoffs = ("会改变后续 plan 结构与长期蓝图写入。",)
        impacts = ("需要先确认，再生成唯一正式 plan。",)
    return DecisionOption(option_id=option_id, title=raw_text, summary=summary, tradeoffs=tradeoffs, impacts=impacts, recommended=recommended)


def _decision_id(request_text: str) -> str:
    digest = sha1(request_text.encode("utf-8")).hexdigest()[:8]
    return f"decision_{digest}"


def _execution_gate_decision_id(plan_id: str, blocking_reason: str) -> str:
    digest = sha1(f"{plan_id}:{blocking_reason}".encode("utf-8")).hexdigest()[:8]
    return f"decision_gate_{digest}"


def _active_plan_binding_decision_id(plan_id: str, request_text: str) -> str:
    digest = sha1(f"{plan_id}:{request_text}".encode("utf-8")).hexdigest()[:8]
    return f"decision_plan_bind_{digest}"


def _feature_key(request_text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", request_text.casefold()).strip("-")
    if not normalized:
        return "decision"
    return normalized[:48].rstrip("-")


def _summary_for_language(language: str) -> str:
    if language == "en-US":
        return "Detected an explicit design split that should be confirmed before creating the formal plan."
    return "检测到会影响正式 plan 与长期契约的设计分叉，需要先确认再继续。"


def _gate_decision_payload(
    blocking_reason: str,
    *,
    plan_path: str,
    language: str,
) -> tuple[str, str, tuple[DecisionOption, ...]]:
    if language == "en-US":
        mapping = {
            "destructive_change": (
                f"The plan at `{plan_path}` still includes a destructive change. Which path should runtime treat as approved?",
                "A destructive change still needs explicit approval before the plan may progress.",
                (
                    _gate_option("option_1", "Narrow to a reversible rollout", "Keep the change reversible with backups or staged fallback.", recommended=True),
                    _gate_option("option_2", "Proceed with the destructive change", "Allow the risky destructive step in this round.", recommended=False),
                ),
            ),
            "auth_boundary": (
                f"The plan at `{plan_path}` still touches auth or permission boundaries. Which path is approved?",
                "The current auth boundary impact still needs an explicit decision.",
                (
                    _gate_option("option_1", "Preserve the current auth boundary", "Reuse the current auth model and narrow the implementation scope.", recommended=True),
                    _gate_option("option_2", "Change auth behavior in this round", "Allow auth or permission behavior to change as part of this round.", recommended=False),
                ),
            ),
            "schema_change": (
                f"The plan at `{plan_path}` still implies a schema-level change. Which path is approved?",
                "A schema-level change still needs an explicit rollout decision.",
                (
                    _gate_option("option_1", "Use a compatible migration path", "Keep the schema change compatible and reversible.", recommended=True),
                    _gate_option("option_2", "Allow the direct schema change", "Permit the direct schema change in this round.", recommended=False),
                ),
            ),
            "scope_tradeoff": (
                f"The plan at `{plan_path}` still contains an unresolved scope tradeoff. Which path is approved?",
                "The plan still contains an unresolved scope tradeoff that should be confirmed first.",
                (
                    _gate_option("option_1", "Narrow the scope", "Pick the smallest stable path and postpone the rest.", recommended=True),
                    _gate_option("option_2", "Expand the scope now", "Absorb the coupled changes in the current round.", recommended=False),
                ),
            ),
        }
    else:
        mapping = {
            "destructive_change": (
                f"`{plan_path}` 里仍包含破坏性变更，当前需要拍板这轮到底按哪条路径执行。",
                "当前 plan 仍包含破坏性变更，需要先明确批准的执行路径。",
                (
                    _gate_option("option_1", "收敛为可回滚方案", "保留备份、回滚或渐进切换，优先走可逆路径。", recommended=True),
                    _gate_option("option_2", "接受这轮直接执行破坏性变更", "允许本轮直接落破坏性步骤。", recommended=False),
                ),
            ),
            "auth_boundary": (
                f"`{plan_path}` 仍触及认证或权限边界，当前需要拍板本轮是否允许修改这条边界。",
                "当前 plan 仍触及认证或权限边界，需要先明确批准路径。",
                (
                    _gate_option("option_1", "保持现有认证边界", "沿用现有权限模型，收窄本轮实现范围。", recommended=True),
                    _gate_option("option_2", "本轮允许改认证或权限行为", "允许本轮一并修改认证或权限行为。", recommended=False),
                ),
            ),
            "schema_change": (
                f"`{plan_path}` 仍包含 schema 级改动，当前需要拍板采用哪条迁移路径。",
                "当前 plan 仍包含 schema 级改动，需要先明确批准的迁移路径。",
                (
                    _gate_option("option_1", "走兼容迁移路径", "优先采用兼容、可回滚的 schema 迁移方案。", recommended=True),
                    _gate_option("option_2", "接受这轮直接改 schema", "允许本轮直接落 schema 级变更。", recommended=False),
                ),
            ),
            "scope_tradeoff": (
                f"`{plan_path}` 仍存在范围取舍，当前需要拍板本轮到底收敛还是扩展。",
                "当前 plan 仍存在范围取舍，需要先确认正式执行路径。",
                (
                    _gate_option("option_1", "收窄范围", "优先选择最小稳定路径，其余部分后续再做。", recommended=True),
                    _gate_option("option_2", "扩大范围一并处理", "接受耦合改动，本轮一并推进。", recommended=False),
                ),
            ),
        }

    return mapping.get(blocking_reason, mapping["scope_tradeoff"])


def _gate_option(option_id: str, title: str, summary: str, *, recommended: bool) -> DecisionOption:
    return DecisionOption(
        option_id=option_id,
        title=title,
        summary=summary,
        tradeoffs=(summary,),
        impacts=("Will immediately feed back into the execution gate.",),
        recommended=recommended,
    )


def _active_plan_binding_payload(
    *,
    current_plan: PlanArtifact,
    request_text: str,
    language: str,
) -> tuple[str, str, tuple[DecisionOption, ...]]:
    if language == "en-US":
        return (
            f"An active plan already exists at `{current_plan.path}`. Should this new request attach to that plan or start a new plan?",
            "A non-anchored complex request arrived while another plan is still active. Confirm the planning container before runtime continues.",
            (
                DecisionOption(
                    option_id=ACTIVE_PLAN_ATTACH_OPTION_ID,
                    title="Attach to current plan",
                    summary="Keep a single plan thread and review the current plan before execution continues.",
                    tradeoffs=("The current plan must be revised before execution may continue.",),
                    impacts=("Runtime will reopen the active plan for review.",),
                    recommended=False,
                ),
                DecisionOption(
                    option_id=ACTIVE_PLAN_NEW_OPTION_ID,
                    title="Create a new plan",
                    summary="Open a separate plan scaffold for the new request and keep the current plan untouched.",
                    tradeoffs=("Adds another plan package that will need its own review and execution decision.",),
                    impacts=("Runtime will create a new plan scaffold for this request.",),
                    recommended=False,
                ),
            ),
        )
    return (
        f"当前已有活动 plan `{current_plan.path}`。这次新请求要挂到当前 plan，还是新开一个 plan？",
        "检测到一个未明确锚定到当前 plan 的复杂新请求。为避免静默复用活动 plan，需要先确认这轮要挂载到哪里。",
        (
            DecisionOption(
                option_id=ACTIVE_PLAN_ATTACH_OPTION_ID,
                title="挂到当前 plan",
                summary="保持单条 plan 主线，但需要先回到当前 plan 做评审/更新，再继续执行。",
                tradeoffs=("当前 plan 需要重新收口，不能直接沿用现有 execution-confirm 状态。",),
                impacts=("runtime 会把当前 plan 退回评审态。",),
                recommended=False,
            ),
            DecisionOption(
                option_id=ACTIVE_PLAN_NEW_OPTION_ID,
                title="新开一个 plan",
                summary="为这次新请求单独建立 plan scaffold，当前 plan 保持不动。",
                tradeoffs=("会新增一个需要单独评审和执行确认的 plan 包。",),
                impacts=("runtime 会为当前请求生成新的正式 plan。",),
                recommended=False,
            ),
        ),
    )


def _match_option(decision_state: DecisionState, raw_text: str) -> str | None:
    text = raw_text.strip()
    if not text:
        return None

    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(decision_state.options):
            return decision_state.options[index].option_id

    normalized = _normalize_text(text)
    for option in decision_state.options:
        if text.casefold() == option.option_id.casefold():
            return option.option_id
        if normalized == _normalize_text(option.option_id):
            return option.option_id
        if normalized == _normalize_text(option.title):
            return option.option_id
        if normalized == _normalize_text(option.summary):
            return option.option_id
    return None


def _option_id_from_submission(decision_state: DecisionState, submission: DecisionSubmission) -> str | None:
    # Hosts may submit against a renamed primary field or the legacy
    # `selected_option_id` key during the transition.
    field_id = decision_state.primary_field_id or PRIMARY_OPTION_FIELD_ID
    candidate = submission.answers.get(field_id)
    if candidate is None and field_id != PRIMARY_OPTION_FIELD_ID:
        candidate = submission.answers.get(PRIMARY_OPTION_FIELD_ID)
    if isinstance(candidate, list):
        candidate = candidate[0] if candidate else None
    if isinstance(candidate, bool):
        return None
    if candidate is None:
        return None
    return _match_option(decision_state, str(candidate))


def _selection_answers(decision_state: DecisionState, option_id: str) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    if decision_state.submission is not None:
        answers.update(decision_state.submission.answers)
    field_id = decision_state.primary_field_id or PRIMARY_OPTION_FIELD_ID
    answers[field_id] = option_id
    return answers


def _normalize_text(value: str) -> str:
    return _PUNCTUATION_RE.sub("", value.casefold())


def iso_now() -> str:
    """Return a stable UTC timestamp without importing the state module."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
