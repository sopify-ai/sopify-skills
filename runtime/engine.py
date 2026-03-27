"""Top-level orchestration for Sopify runtime."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
import re
from typing import Any, Mapping, Optional

from .checkpoint_materializer import materialize_checkpoint_request
from .checkpoint_request import checkpoint_request_from_clarification_state, checkpoint_request_from_decision_state
from .clarification import build_clarification_state, has_submitted_clarification, merge_clarification_request, parse_clarification_response, stale_clarification
from .compare_decision import build_compare_decision_contract
from .config import load_runtime_config
from .context_recovery import recover_context
from .daily_summary import build_daily_summary
from .decision import (
    ACTIVE_PLAN_ATTACH_OPTION_ID,
    ACTIVE_PLAN_BINDING_DECISION_TYPE,
    ACTIVE_PLAN_NEW_OPTION_ID,
    build_active_plan_binding_decision_state,
    build_decision_state,
    build_execution_gate_decision_state,
    confirm_decision,
    consume_decision,
    has_submitted_decision,
    parse_decision_response,
    response_from_submission,
    stale_decision,
)
from .develop_checkpoint import develop_resume_after, is_develop_checkpoint_state
from .execution_confirm import parse_execution_confirm_response
from .execution_gate import evaluate_execution_gate
from .finalize import finalize_plan
from .handoff import build_runtime_handoff
from .kb import bootstrap_kb, ensure_blueprint_index, ensure_blueprint_scaffold
from .models import ClarificationState, DecisionState, ExecutionGate, KbArtifact, PlanArtifact, ReplayEvent, RouteDecision, RunState, RuntimeConfig, RuntimeHandoff, RuntimeResult, SkillActivation, SkillMeta
from .plan_registry import (
    PlanRegistryError,
    encode_priority_note_event,
    get_plan_entry,
    priority_note_for_plan,
    registry_relative_path,
)
from .plan_scaffold import (
    create_plan_scaffold,
    find_plan_by_request_reference,
    reserve_plan_identity,
    request_explicitly_wants_new_plan,
)
from .plan_proposal import (
    build_plan_proposal_state,
    confirmed_decision_from_proposal,
    merge_plan_proposal_request,
    refresh_plan_proposal_state,
)
from .replay import ReplayWriter, build_compare_replay_event, build_decision_replay_event
from .router import (
    Router,
    detect_explain_only_consult_override,
)
from .skill_registry import SkillRegistry
from .skill_runner import SkillExecutionError, run_runtime_skill
from .state import (
    StateStore,
    iso_now,
    local_day_now,
    local_display_now,
    local_iso_now,
    local_timezone_name,
    stable_request_sha1,
    summarize_request_text,
)

_CURRENT_PLAN_ANCHOR_PATTERNS = (
    re.compile(r"(当前|这个|该)\s*(plan|方案)", re.IGNORECASE),
    re.compile(r"(current|active)\s+plan", re.IGNORECASE),
    re.compile(r"(继续|回到|基于|沿用|挂到|并入|写进|写入).*(plan|方案)", re.IGNORECASE),
)
# These routes operate on the single root-scoped execution truth once review
# state is explicitly promoted out of a session.
_GLOBAL_EXECUTION_ROUTES = frozenset({"execution_confirm_pending", "resume_active", "exec_plan", "finalize_active"})
# Only stable review checkpoints may be promoted into the global execution
# truth consumed by execution-confirm, resume, and finalize.
_PROMOTABLE_REVIEW_STAGES = frozenset({"plan_generated", "ready_for_execution", "execution_confirm_pending", "develop_pending"})


@dataclass(frozen=True)
class _PlanSelection:
    """Describe whether planning should reuse an existing plan or create a new one."""

    action: str
    plan_artifact: PlanArtifact | None = None
    reason_note: str = ""


def _recovery_store_for_route(
    decision: RouteDecision,
    *,
    review_store: StateStore,
    global_store: StateStore,
) -> StateStore:
    if decision.route_name in _GLOBAL_EXECUTION_ROUTES and global_store.get_current_run() is not None:
        return global_store
    return review_store


def _handle_cancel_active(
    decision: RouteDecision,
    *,
    review_store: StateStore,
    global_store: StateStore,
) -> tuple[StateStore, list[str]]:
    cancel_scope = str(decision.artifacts.get("cancel_scope") or "").strip()
    global_run = global_store.get_current_run()
    if cancel_scope != "session" and global_run is not None:
        global_store.reset_active_flow()
        if review_store is global_store or review_store.get_current_run() is None:
            return (global_store, ["Global execution flow cleared"])
        return (global_store, ["Global execution flow cleared; session review state preserved"])
    review_store.reset_active_flow()
    return (review_store, ["Session review flow cleared"])


def _resolve_execution_state_store(
    decision: RouteDecision,
    *,
    config: RuntimeConfig,
    review_store: StateStore,
    global_store: StateStore,
    session_id: str | None,
) -> tuple[StateStore, Any, list[str]]:
    if global_store.get_current_run() is not None and global_store.get_current_plan() is not None:
        recovered = recover_context(decision, config=config, state_store=global_store)
        return (global_store, recovered, [])

    promotion_notes = _promote_review_state_to_global_execution(
        review_store=review_store,
        global_store=global_store,
        session_id=session_id,
    )
    recovered = recover_context(
        decision,
        config=config,
        state_store=global_store if global_store.get_current_run() is not None else review_store,
    )
    return (global_store, recovered, promotion_notes)


def _promote_review_state_to_global_execution(
    *,
    review_store: StateStore,
    global_store: StateStore,
    session_id: str | None,
) -> list[str]:
    if review_store is global_store:
        return []
    review_plan = review_store.get_current_plan()
    review_run = review_store.get_current_run()
    if review_plan is None or review_run is None:
        return []
    if review_run.stage not in _PROMOTABLE_REVIEW_STAGES:
        return []

    notes: list[str] = []
    existing_owner = global_store.get_current_run()
    if (
        existing_owner is not None
        and existing_owner.owner_session_id
        and session_id
        and existing_owner.owner_session_id != session_id
    ):
        notes.append(
            f"Soft ownership warning: overwriting global execution context owned by session {existing_owner.owner_session_id}"
        )

    # Promotion is the explicit handoff point from session review state into the
    # single global execution truth used by execution-confirm / resume / finalize.
    global_store.set_current_plan(review_plan)
    _set_execution_run_state(global_store, review_run, session_id=session_id)
    review_handoff = review_store.get_current_handoff()
    if review_handoff is not None:
        global_store.set_current_handoff(
            _with_global_handoff_ownership(
                review_handoff,
                current_run=review_run,
                session_id=session_id,
            )
        )
    notes.append(f"Promoted session review state to global execution truth from {review_store.root.name}")
    return notes


def _set_execution_run_state(
    state_store: StateStore,
    run_state: RunState,
    *,
    session_id: str | None,
) -> None:
    if state_store.session_id is not None:
        state_store.set_current_run(run_state)
        return
    state_store.set_current_run(_with_global_run_ownership(run_state, session_id=session_id))


def _with_global_run_ownership(run_state: RunState, *, session_id: str | None) -> RunState:
    owner_session_id = str(session_id or run_state.owner_session_id or "").strip()
    return RunState(
        run_id=run_state.run_id,
        status=run_state.status,
        stage=run_state.stage,
        route_name=run_state.route_name,
        title=run_state.title,
        created_at=run_state.created_at,
        updated_at=run_state.updated_at,
        plan_id=run_state.plan_id,
        plan_path=run_state.plan_path,
        execution_gate=run_state.execution_gate,
        request_excerpt=run_state.request_excerpt,
        request_sha1=run_state.request_sha1,
        owner_session_id=owner_session_id,
        owner_host=run_state.owner_host or "runtime",
        owner_run_id=run_state.owner_run_id or run_state.run_id,
    )


def _with_global_handoff_ownership(
    handoff: RuntimeHandoff,
    *,
    current_run: RunState | None,
    session_id: str | None,
) -> RuntimeHandoff:
    observability = dict(handoff.observability)
    owner_session_id = ""
    if current_run is not None:
        owner_session_id = current_run.owner_session_id
    if not owner_session_id:
        owner_session_id = str(session_id or "").strip()
    if owner_session_id:
        observability["owner_session_id"] = owner_session_id
    if current_run is not None:
        if current_run.owner_host:
            observability["owner_host"] = current_run.owner_host
        if current_run.owner_run_id:
            observability["owner_run_id"] = current_run.owner_run_id
    return RuntimeHandoff(
        schema_version=handoff.schema_version,
        route_name=handoff.route_name,
        run_id=handoff.run_id,
        plan_id=handoff.plan_id,
        plan_path=handoff.plan_path,
        handoff_kind=handoff.handoff_kind,
        required_host_action=handoff.required_host_action,
        recommended_skill_ids=handoff.recommended_skill_ids,
        artifacts=handoff.artifacts,
        notes=handoff.notes,
        observability=observability,
    )


def _result_state_store_for_route(
    decision: RouteDecision,
    *,
    review_store: StateStore,
    global_store: StateStore,
    canceled_store: StateStore | None,
) -> StateStore:
    if canceled_store is not None:
        if canceled_store is global_store and review_store.get_current_run() is not None:
            return review_store
        return canceled_store
    if decision.route_name in _GLOBAL_EXECUTION_ROUTES:
        return global_store
    if decision.route_name in {"decision_pending", "decision_resume"}:
        if review_store.get_current_decision() is not None:
            return review_store
        return global_store
    if decision.route_name in {"clarification_pending", "clarification_resume"}:
        if review_store.get_current_clarification() is not None:
            return review_store
        return global_store
    return review_store


def run_runtime(
    user_input: str,
    *,
    workspace_root: str | Path = ".",
    global_config_path: str | Path | None = None,
    session_id: str | None = None,
    user_home: Path | None = None,
    runtime_payloads: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> RuntimeResult:
    """Run the Sopify runtime pipeline for a single input.

    Args:
        user_input: Raw user input.
        workspace_root: Project root.
        global_config_path: Optional global config override.
        user_home: Optional home override for tests.
        runtime_payloads: Optional runtime-skill payload map keyed by skill id.

    Returns:
        Standardized runtime result.
    """
    config = load_runtime_config(workspace_root, global_config_path=global_config_path)
    review_store = StateStore(config, session_id=session_id)
    global_store = StateStore(config)
    review_store.ensure()
    global_store.ensure()
    kb_artifact: KbArtifact | None = bootstrap_kb(config)

    skills = SkillRegistry(config, user_home=user_home).discover()
    router = Router(config, state_store=review_store, global_state_store=global_store)
    classified_route = router.classify(user_input, skills=skills)
    recovered = recover_context(
        classified_route,
        config=config,
        state_store=_recovery_store_for_route(
            classified_route,
            review_store=review_store,
            global_store=global_store,
        ),
    )

    notes: list[str] = []
    plan_artifact: PlanArtifact | None = None
    skill_result: Mapping[str, Any] | None = None
    replay_session_dir: str | None = None
    handoff: RuntimeHandoff | None = None
    activation: SkillActivation | None = None
    generated_files: tuple[str, ...] = ()
    replay_events: list[ReplayEvent] = []
    effective_route = classified_route
    confirmed_decision_for_replay: DecisionState | None = None
    registry_changed_hint = False

    current_clarification = review_store.get_current_clarification()
    if (
        current_clarification is not None
        and effective_route.route_name in {"plan_only", "workflow", "light_iterate"}
        and effective_route.route_name not in {"clarification_pending", "clarification_resume"}
    ):
        # A new planning request supersedes the previous pending clarification.
        stale_state = stale_clarification(current_clarification)
        review_store.set_current_clarification(stale_state)
        review_store.clear_current_clarification()
        notes.append(f"Superseded pending clarification: {stale_state.clarification_id}")
        current_clarification = None

    current_decision = review_store.get_current_decision()
    if (
        current_decision is not None
        and effective_route.route_name in {"plan_only", "workflow", "light_iterate"}
        and effective_route.route_name not in {"decision_pending", "decision_resume"}
    ):
        # A new planning request supersedes the previous pending checkpoint.
        stale_state = stale_decision(current_decision)
        review_store.set_current_decision(stale_state)
        review_store.clear_current_decision()
        notes.append(f"Superseded pending decision checkpoint: {stale_state.decision_id}")
        current_decision = None

    current_plan_proposal = review_store.get_current_plan_proposal()
    if (
        current_plan_proposal is not None
        and effective_route.route_name in {"plan_only", "workflow", "light_iterate"}
        and effective_route.route_name != "plan_proposal_pending"
    ):
        review_store.clear_current_plan_proposal()
        notes.append(f"Superseded pending plan proposal: {current_plan_proposal.checkpoint_id}")
        current_plan_proposal = None

    canceled_store: StateStore | None = None
    if effective_route.route_name == "cancel_active":
        canceled_store, cancel_notes = _handle_cancel_active(
            effective_route,
            review_store=review_store,
            global_store=global_store,
        )
        notes.extend(cancel_notes)
    elif effective_route.route_name == "finalize_active":
        finalized = finalize_plan(
            config=config,
            state_store=global_store,
            current_plan=global_store.get_current_plan() or recovered.current_plan,
        )
        plan_artifact = finalized.archived_plan
        registry_changed_hint = finalized.registry_updated
        if finalized.kb_artifact is not None:
            kb_artifact = finalized.kb_artifact
        notes.extend(finalized.notes)
    elif effective_route.route_name == "clarification_resume":
        effective_route, plan_artifact, clarification_notes, kb_artifact = _handle_clarification_resume(
            effective_route,
            state_store=review_store,
            config=config,
            kb_artifact=kb_artifact,
        )
        notes.extend(clarification_notes)
    elif effective_route.route_name == "decision_resume":
        effective_route, plan_artifact, decision_notes, kb_artifact, confirmed_decision_for_replay = _handle_decision_resume(
            effective_route,
            state_store=review_store,
            config=config,
            kb_artifact=kb_artifact,
        )
        notes.extend(decision_notes)
    elif effective_route.route_name == "plan_proposal_pending":
        effective_route, plan_artifact, proposal_notes, kb_artifact = _handle_plan_proposal_pending(
            effective_route,
            state_store=review_store,
            config=config,
            kb_artifact=kb_artifact,
        )
        notes.extend(proposal_notes)
    elif effective_route.route_name == "execution_confirm_pending":
        execution_store, execution_recovered, promotion_notes = _resolve_execution_state_store(
            effective_route,
            config=config,
            review_store=review_store,
            global_store=global_store,
            session_id=session_id,
        )
        notes.extend(promotion_notes)
        effective_route, plan_artifact, execution_confirm_notes = _handle_execution_confirm(
            effective_route,
            state_store=execution_store,
            config=config,
            session_id=session_id,
        )
        recovered = execution_recovered
        notes.extend(execution_confirm_notes)
    elif effective_route.route_name in {"plan_only", "workflow", "light_iterate"}:
        effective_route, plan_artifact, planning_notes, kb_artifact = _advance_planning_route(
            effective_route,
            state_store=review_store,
            config=config,
            kb_artifact=kb_artifact,
        )
        notes.extend(planning_notes)
    elif effective_route.route_name in {"resume_active", "exec_plan"}:
        execution_store, execution_recovered, promotion_notes = _resolve_execution_state_store(
            effective_route,
            config=config,
            review_store=review_store,
            global_store=global_store,
            session_id=session_id,
        )
        notes.extend(promotion_notes)
        if execution_store.get_current_clarification() is not None:
            effective_route = _clarification_pending_route(
                effective_route,
                reason="Pending clarification must be answered before execution can continue",
            )
            notes.append("Blocked execution because clarification is still pending")
        else:
            current_plan = execution_store.get_current_plan() or execution_recovered.current_plan
            if current_plan is None:
                if effective_route.route_name == "exec_plan":
                    effective_route = _exec_plan_unavailable_route(
                        effective_route,
                        reason="Advanced exec recovery is unavailable because no active plan or confirmed recovery state exists",
                    )
                    notes.append("Rejected ~go exec because no active plan or confirmed recovery state is available")
                else:
                    notes.append("No active plan available to resume")
            else:
                gate = evaluate_execution_gate(
                    decision=effective_route,
                    plan_artifact=current_plan,
                    current_clarification=None,
                    current_decision=_confirmed_decision_context(execution_store),
                    config=config,
                )
                if gate.gate_status == "decision_required" and gate.blocking_reason != "unresolved_decision":
                    gate_decision = _build_route_native_gate_decision_state(
                        effective_route,
                        gate=gate,
                        current_plan=current_plan,
                        config=config,
                    )
                    if gate_decision is not None:
                        execution_store.set_current_decision(gate_decision)
                        _set_execution_run_state(
                            execution_store,
                            RunState(
                                run_id=(execution_store.get_current_run() or execution_recovered.current_run).run_id if (execution_store.get_current_run() or execution_recovered.current_run) is not None else _make_run_id(effective_route.request_text),
                                status="active",
                                stage="decision_pending",
                                route_name=effective_route.route_name,
                                title=current_plan.title,
                                created_at=(execution_store.get_current_run() or execution_recovered.current_run).created_at if (execution_store.get_current_run() or execution_recovered.current_run) is not None else current_plan.created_at,
                                updated_at=iso_now(),
                                plan_id=current_plan.plan_id,
                                plan_path=current_plan.path,
                                execution_gate=gate,
                                request_excerpt=summarize_request_text(effective_route.request_text),
                                request_sha1=stable_request_sha1(effective_route.request_text),
                            ),
                            session_id=session_id,
                        )
                        effective_route = _decision_pending_route(
                            effective_route,
                            reason="Execution gate found a blocking risk that still requires confirmation",
                        )
                        notes.extend(gate.notes)
                        notes.append(f"Execution gate requested a new decision: {gate_decision.decision_id}")
                    else:
                        notes.append("Execution gate requires a decision before develop can continue")
                elif gate.gate_status != "ready":
                    _set_execution_run_state(
                        execution_store,
                        _make_run_state(
                            effective_route,
                            current_plan,
                            stage="plan_generated",
                            execution_gate=gate,
                        ),
                        session_id=session_id,
                    )
                    notes.extend(gate.notes)
                    notes.append("Blocked execution because the execution gate is not ready")
                else:
                    current_run = execution_store.get_current_run() or execution_recovered.current_run
                    _set_execution_run_state(
                        execution_store,
                        RunState(
                            run_id=current_run.run_id if current_run is not None else _make_run_id(effective_route.request_text),
                            status="active",
                            stage="develop_pending",
                            route_name=effective_route.route_name,
                            title=current_plan.title,
                            created_at=current_run.created_at if current_run is not None else current_plan.created_at,
                            updated_at=iso_now(),
                            plan_id=current_plan.plan_id,
                            plan_path=current_plan.path,
                            execution_gate=gate,
                            request_excerpt=current_run.request_excerpt if current_run is not None else summarize_request_text(effective_route.request_text),
                            request_sha1=current_run.request_sha1 if current_run is not None else stable_request_sha1(effective_route.request_text),
                        ),
                        session_id=session_id,
                    )
                    notes.extend(gate.notes)
                    notes.append("Active run resumed")
        recovered = execution_recovered

    if effective_route.route_name != "summary":
        review_store.set_last_route(effective_route)

    result_store = _result_state_store_for_route(
        effective_route,
        review_store=review_store,
        global_store=global_store,
        canceled_store=canceled_store,
    )

    if effective_route.runtime_skill_id is not None:
        skill = _find_skill(skills, effective_route.runtime_skill_id)
        payload = dict((runtime_payloads or {}).get(effective_route.runtime_skill_id, {}))
        if skill is None:
            notes.append(f"Runtime skill not found: {effective_route.runtime_skill_id}")
        elif not payload:
            notes.append(f"Runtime payload missing for skill: {effective_route.runtime_skill_id}")
        else:
            try:
                skill_result = run_runtime_skill(skill, payload=payload)
            except SkillExecutionError as exc:
                notes.append(str(exc))

    activation = _build_skill_activation(
        decision=effective_route,
        run_state=result_store.get_current_run() or recovered.current_run,
        current_clarification=result_store.get_current_clarification(),
        current_decision=result_store.get_current_decision(),
    )

    if effective_route.route_name == "summary" and activation is not None:
        # Keep `~summary` read-only so users can inspect the day without disturbing an active handoff.
        summary_result = build_daily_summary(
            config=config,
            state_store=result_store,
            activation=activation,
        )
        skill_result = {
            "summary": summary_result.artifact.to_dict(),
            "summary_markdown": summary_result.markdown,
        }
        generated_files = summary_result.generated_files
        notes.extend(summary_result.notes)

    if effective_route.capture_mode != "off":
        writer = ReplayWriter(config)
        run_state = result_store.get_current_run() or recovered.current_run
        run_id = run_state.run_id if run_state is not None else _make_run_id(effective_route.request_text)
        replay_event = ReplayEvent(
            ts=iso_now(),
            phase=_phase_for_route(effective_route),
            intent=effective_route.request_text or effective_route.route_name,
            action=f"route:{effective_route.route_name}",
            key_output=(plan_artifact.summary if plan_artifact is not None else effective_route.reason),
            decision_reason=effective_route.reason,
            result="success",
            artifacts=tuple(plan_artifact.files if plan_artifact is not None else ()),
            metadata={"activation": activation.to_dict()} if activation is not None else {},
        )
        replay_events.append(replay_event)
        current_decision = result_store.get_current_decision()
        if current_decision is not None and effective_route.route_name == "decision_pending":
            replay_events.append(
                build_decision_replay_event(
                    current_decision,
                    language=config.language,
                    action="checkpoint_created",
                )
            )
        if confirmed_decision_for_replay is not None:
            replay_events.append(
                build_decision_replay_event(
                    confirmed_decision_for_replay,
                    language=config.language,
                    action="confirmed",
                )
            )
        if effective_route.route_name == "compare" and skill_result:
            compare_contract = build_compare_decision_contract(
                question=effective_route.request_text,
                skill_result=skill_result,
                language=config.language,
            )
            if compare_contract is not None:
                replay_events.append(
                    build_compare_replay_event(
                        ts=iso_now(),
                        question=effective_route.request_text,
                        contract=compare_contract,
                        language=config.language,
                    )
                )
        session_dir = writer.append_event(run_id, replay_event)
        for extra_event in replay_events[1:]:
            writer.append_event(run_id, extra_event)
        writer.render_documents(
            run_id,
            run_state=result_store.get_current_run(),
            route=effective_route,
            plan_artifact=plan_artifact or recovered.current_plan,
            events=replay_events,
        )
        replay_session_dir = str(session_dir.relative_to(config.workspace_root))

    if effective_route.route_name == "cancel_active":
        handoff = None
    elif effective_route.route_name == "summary":
        # Preserve the current handoff on disk; `~summary` should not consume or overwrite active flow state.
        handoff = None
    else:
        current_run = result_store.get_current_run() or recovered.current_run
        current_plan = plan_artifact or result_store.get_current_plan() or recovered.current_plan
        previous_handoff = result_store.get_current_handoff()
        if effective_route.route_name == "finalize_active" and plan_artifact is not None:
            # Finalize clears active-flow state; only persist a completion handoff
            # when the archive transaction actually succeeded.
            current_run = None
            current_plan = plan_artifact
        handoff = build_runtime_handoff(
            config=config,
            decision=effective_route,
            run_id=(current_run.run_id if current_run is not None else _make_run_id(effective_route.request_text)),
            current_run=current_run,
            current_plan=current_plan,
            current_plan_proposal=result_store.get_current_plan_proposal(),
            kb_artifact=kb_artifact,
            replay_session_dir=replay_session_dir,
            skill_result=skill_result,
            current_clarification=result_store.get_current_clarification(),
            current_decision=result_store.get_current_decision(),
            notes=notes,
            previous_handoff=previous_handoff,
        )
        if handoff is not None:
            if result_store is global_store:
                handoff = _with_global_handoff_ownership(
                    handoff,
                    current_run=current_run,
                    session_id=session_id,
                )
            result_store.set_current_handoff(handoff)
        else:
            result_store.clear_current_handoff()

    generated_files = _augment_generated_files(
        generated_files,
        config=config,
        route_name=effective_route.route_name,
        plan_artifact=plan_artifact,
        notes=tuple(notes),
        registry_changed_hint=registry_changed_hint,
    )
    latest_context = recover_context(effective_route, config=config, state_store=result_store)
    return RuntimeResult(
        route=effective_route,
        recovered_context=latest_context,
        discovered_skills=skills,
        kb_artifact=kb_artifact,
        plan_artifact=plan_artifact,
        skill_result=skill_result,
        replay_session_dir=replay_session_dir,
        handoff=handoff,
        activation=activation,
        generated_files=generated_files,
        notes=tuple(notes),
    )


def _default_plan_level(decision: RouteDecision) -> str:
    if decision.complexity == "medium":
        return "light"
    return "standard"


def _augment_generated_files(
    generated_files: tuple[str, ...],
    *,
    config: RuntimeConfig,
    route_name: str,
    plan_artifact: PlanArtifact | None,
    notes: tuple[str, ...],
    registry_changed_hint: bool = False,
) -> tuple[str, ...]:
    items = list(generated_files)
    if _registry_file_should_be_reported(
        config=config,
        route_name=route_name,
        plan_artifact=plan_artifact,
        notes=notes,
        registry_changed_hint=registry_changed_hint,
    ):
        registry_file = registry_relative_path(config)
        if registry_file not in items:
            items.append(registry_file)
    return tuple(items)


def _registry_file_should_be_reported(
    *,
    config: RuntimeConfig,
    route_name: str,
    plan_artifact: PlanArtifact | None,
    notes: tuple[str, ...],
    registry_changed_hint: bool,
) -> bool:
    if route_name == "finalize_active":
        return registry_changed_hint
    if plan_artifact is None:
        return False
    if not any(note.startswith("Plan scaffold created at ") for note in notes):
        return False
    try:
        # Only surface the registry as a changed artifact when the new plan entry
        # is actually observable after the scaffold step.
        entry_result = get_plan_entry(config=config, plan_id=plan_artifact.plan_id)
    except PlanRegistryError:
        return False
    return entry_result.entry is not None


def _make_run_state(
    decision: RouteDecision,
    plan_artifact: PlanArtifact,
    *,
    stage: str = "plan_generated",
    execution_gate: ExecutionGate | None = None,
) -> RunState:
    now = iso_now()
    return RunState(
        run_id=_make_run_id(decision.request_text),
        status="active",
        stage=stage,
        route_name=decision.route_name,
        title=plan_artifact.title,
        created_at=now,
        updated_at=now,
        plan_id=plan_artifact.plan_id,
        plan_path=plan_artifact.path,
        execution_gate=execution_gate,
        request_excerpt=summarize_request_text(decision.request_text),
        request_sha1=stable_request_sha1(decision.request_text),
        owner_session_id="",
        owner_host="",
        owner_run_id="",
    )


def _make_decision_run_state(decision: RouteDecision, decision_state: DecisionState, *, execution_gate: ExecutionGate | None = None) -> RunState:
    now = iso_now()
    return RunState(
        run_id=_make_run_id(decision.request_text),
        status="active",
        stage="decision_pending",
        route_name=decision_state.resume_route or decision.route_name,
        title=decision_state.question,
        created_at=now,
        updated_at=now,
        plan_id=None,
        plan_path=None,
        execution_gate=execution_gate,
        request_excerpt=summarize_request_text(decision.request_text),
        request_sha1=stable_request_sha1(decision.request_text),
        owner_session_id="",
        owner_host="",
        owner_run_id="",
    )


def _make_clarification_run_state(
    decision: RouteDecision,
    clarification_state: ClarificationState,
    *,
    execution_gate: ExecutionGate | None = None,
) -> RunState:
    now = iso_now()
    return RunState(
        run_id=_make_run_id(decision.request_text),
        status="active",
        stage="clarification_pending",
        route_name=clarification_state.resume_route or decision.route_name,
        title=clarification_state.summary,
        created_at=now,
        updated_at=now,
        plan_id=None,
        plan_path=None,
        execution_gate=execution_gate,
        request_excerpt=summarize_request_text(decision.request_text),
        request_sha1=stable_request_sha1(decision.request_text),
        owner_session_id="",
        owner_host="",
        owner_run_id="",
    )


def _make_plan_proposal_run_state(
    decision: RouteDecision,
    proposal_state,
) -> RunState:
    now = iso_now()
    return RunState(
        run_id=_make_run_id(proposal_state.request_text or decision.request_text),
        status="active",
        stage="plan_proposal_pending",
        route_name=proposal_state.resume_route or decision.route_name,
        title=proposal_state.analysis_summary or proposal_state.proposed_path,
        created_at=proposal_state.created_at or now,
        updated_at=now,
        plan_id=proposal_state.reserved_plan_id,
        plan_path=proposal_state.proposed_path,
        execution_gate=None,
        request_excerpt=summarize_request_text(proposal_state.request_text or decision.request_text),
        request_sha1=stable_request_sha1(proposal_state.request_text or decision.request_text),
        owner_session_id="",
        owner_host="",
        owner_run_id="",
    )


def _make_run_id(request_text: str) -> str:
    timestamp = iso_now().replace(":", "").replace("-", "")[:15]
    digest = sha1(request_text.encode("utf-8")).hexdigest()[:6]
    return f"{timestamp}_{digest}"


def _make_plan_proposal_id(request_text: str) -> str:
    digest = sha1(request_text.encode("utf-8")).hexdigest()[:8]
    return f"plan_proposal_{digest}"


def _find_skill(skills: tuple[SkillMeta, ...], skill_id: str) -> SkillMeta | None:
    for skill in skills:
        if skill.skill_id == skill_id:
            return skill
    return None


def _phase_for_route(decision: RouteDecision) -> str:
    if decision.route_name in {"plan_only", "workflow", "light_iterate", "plan_proposal_pending", "clarification_pending", "clarification_resume", "decision_pending", "decision_resume"}:
        return "design"
    if decision.route_name in {"execution_confirm_pending", "resume_active", "exec_plan", "quick_fix"}:
        return "develop"
    if decision.route_name == "compare":
        return "analysis"
    return "analysis"


def _build_skill_activation(
    *,
    decision: RouteDecision,
    run_state: RunState | None,
    current_clarification: ClarificationState | None,
    current_decision: DecisionState | None,
) -> SkillActivation:
    skill_id, skill_name = _activation_target(
        decision=decision,
        current_clarification=current_clarification,
        current_decision=current_decision,
    )
    return SkillActivation(
        skill_id=skill_id,
        skill_name=skill_name,
        activated_at=local_iso_now(),
        activated_local_day=local_day_now(),
        display_time=local_display_now(),
        activation_source="runtime_skill" if decision.runtime_skill_id else "route_phase",
        run_id=run_state.run_id if run_state is not None else _make_run_id(decision.request_text),
        route_name=decision.route_name,
        timezone=local_timezone_name(),
    )


def _activation_target(
    *,
    decision: RouteDecision,
    current_clarification: ClarificationState | None,
    current_decision: DecisionState | None,
) -> tuple[str, str]:
    if decision.runtime_skill_id == "model-compare" or decision.route_name == "compare":
        return ("model-compare", "模型对比")
    if decision.runtime_skill_id == "workflow-learning" or decision.route_name == "replay":
        return ("workflow-learning", "复盘学习")
    if decision.route_name == "summary":
        return ("summary", "今日详细摘要")
    if decision.route_name in {"resume_active", "exec_plan", "execution_confirm_pending", "quick_fix", "finalize_active"}:
        return ("develop", "开发实施")
    if decision.route_name in {"clarification_pending", "clarification_resume"}:
        if current_clarification is not None and current_clarification.phase == "develop":
            return ("develop", "开发实施")
        return ("analyze", "需求分析")
    if decision.route_name in {"decision_pending", "decision_resume"}:
        if current_decision is not None and current_decision.phase == "develop":
            return ("develop", "开发实施")
        return ("design", "方案设计")
    if decision.route_name in {"plan_only", "workflow", "light_iterate", "plan_proposal_pending"}:
        return ("design", "方案设计")
    return ("consult", "咨询问答")


def _handle_clarification_resume(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
    kb_artifact: KbArtifact | None,
) -> tuple[RouteDecision, PlanArtifact | None, list[str], KbArtifact | None]:
    current_clarification = state_store.get_current_clarification()
    notes: list[str] = []
    if current_clarification is None:
        return (
            _clarification_pending_route(decision, reason="No pending clarification was found"),
            None,
            ["No pending clarification to resume"],
            kb_artifact,
        )

    if decision.active_run_action == "clarification_response_from_state" and has_submitted_clarification(current_clarification):
        resumed_request = merge_clarification_request(current_clarification, current_clarification.response_text or "")
        notes.append("Clarification response restored from structured submission")
    else:
        response = parse_clarification_response(current_clarification, decision.request_text)
        if response.action == "status":
            return (_clarification_pending_route(decision, reason="Clarification is still waiting for factual details"), None, notes, kb_artifact)

        if response.action == "cancel":
            state_store.reset_active_flow()
            return (
                RouteDecision(
                    route_name="cancel_active",
                    request_text=decision.request_text,
                    reason="Clarification cancelled by user",
                    complexity="simple",
                    should_recover_context=True,
                ),
                None,
                ["Clarification cancelled"],
                kb_artifact,
            )

        if response.action != "answer":
            notes.append(response.message or "Invalid clarification response")
            return (_clarification_pending_route(decision, reason="Clarification still requires factual details"), None, notes, kb_artifact)

        resumed_request = merge_clarification_request(current_clarification, response.text)
    if is_develop_checkpoint_state(current_clarification):
        return _resume_from_develop_clarification(
            state_store=state_store,
            current_clarification=current_clarification,
            resumed_request=resumed_request,
            notes=notes,
            kb_artifact=kb_artifact,
        )

    resumed_route = RouteDecision(
        route_name=current_clarification.resume_route or "plan_only",
        request_text=resumed_request,
        reason="Clarification answered and planning resumed",
        command=None,
        complexity="complex",
        plan_level=current_clarification.requested_plan_level,
        candidate_skill_ids=current_clarification.candidate_skill_ids,
        should_recover_context=False,
        plan_package_policy=current_clarification.plan_package_policy,
        capture_mode=current_clarification.capture_mode,
        artifacts={"planning_resume_source": "clarification"},
    )
    state_store.clear_current_clarification()
    planning_route, plan_artifact, planning_notes, kb_artifact = _advance_planning_route(
        resumed_route,
        state_store=state_store,
        config=config,
        kb_artifact=kb_artifact,
        confirmed_decision=_confirmed_decision_context(state_store),
    )
    notes.extend(planning_notes)
    return (planning_route, plan_artifact, notes, kb_artifact)


def _handle_decision_resume(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
    kb_artifact: KbArtifact | None,
) -> tuple[RouteDecision, PlanArtifact | None, list[str], KbArtifact | None, DecisionState | None]:
    current_decision = state_store.get_current_decision()
    notes: list[str] = []
    if current_decision is None:
        return (
            _decision_pending_route(decision, reason="No pending decision checkpoint was found"),
            None,
            ["No pending decision checkpoint to resume"],
            kb_artifact,
            None,
        )

    if decision.active_run_action == "materialize_confirmed_decision":
        response_action = "materialize"
        response_option_id = None
        response_source = "command_override"
        response_message = ""
    else:
        response = None
        if current_decision.status in {"pending", "collecting", "cancelled", "timed_out"} and has_submitted_decision(current_decision):
            response = response_from_submission(current_decision)
            if response is not None:
                notes.append("Decision response restored from structured submission")
        if response is None:
            response = parse_decision_response(current_decision, decision.request_text)
        response_action = response.action
        response_option_id = response.option_id
        response_source = response.source
        response_message = response.message

    if response_action == "status":
        return (_decision_pending_route(decision, reason="Decision checkpoint is still waiting for confirmation"), None, notes, kb_artifact, None)

    if response_action == "cancel":
        state_store.reset_active_flow()
        return (
            RouteDecision(
                route_name="cancel_active",
                request_text=decision.request_text,
                reason="Decision checkpoint cancelled by user",
                complexity="simple",
                should_recover_context=True,
            ),
            None,
            ["Decision checkpoint cancelled"],
            kb_artifact,
            None,
        )

    if response_action == "invalid":
        notes.append(response_message or "Invalid decision response")
        return (_decision_pending_route(decision, reason="Decision checkpoint still requires a valid selection"), None, notes, kb_artifact, None)

    if response_action == "choose":
        raw_input = decision.request_text
        if current_decision.submission is not None and response_source == current_decision.submission.source:
            raw_input = current_decision.submission.raw_input or raw_input
        current_decision = confirm_decision(
            current_decision,
            option_id=response_option_id or "",
            source=response_source,
            raw_input=raw_input,
        )
        state_store.set_current_decision(current_decision)
        notes.append(f"Decision confirmed: {current_decision.selected_option_id}")

    if current_decision.status != "confirmed" or current_decision.selection is None:
        notes.append("Decision checkpoint has not reached a confirmed state yet")
        return (_decision_pending_route(decision, reason="Decision checkpoint is still pending"), None, notes, kb_artifact, None)

    if is_develop_checkpoint_state(current_decision):
        return _resume_from_develop_decision(
            state_store=state_store,
            current_decision=current_decision,
            notes=notes,
            kb_artifact=kb_artifact,
        )

    if current_decision.decision_type == ACTIVE_PLAN_BINDING_DECISION_TYPE:
        return _resume_from_active_plan_binding_decision(
            state_store=state_store,
            current_decision=current_decision,
            notes=notes,
            kb_artifact=kb_artifact,
            config=config,
        )

    confirmed_decision = current_decision
    planning_route, plan_artifact, planning_notes, kb_artifact = _advance_planning_route(
        RouteDecision(
            route_name=current_decision.resume_route or "plan_only",
            request_text=current_decision.request_text,
            reason="Decision confirmed and planning resumed",
            command=None,
            complexity="complex",
            plan_level=current_decision.requested_plan_level,
            candidate_skill_ids=current_decision.candidate_skill_ids,
            should_recover_context=False,
            plan_package_policy=current_decision.plan_package_policy,
            capture_mode=current_decision.capture_mode,
        ),
        state_store=state_store,
        config=config,
        kb_artifact=kb_artifact,
        confirmed_decision=current_decision,
    )
    notes.extend(planning_notes)
    return (planning_route, plan_artifact, notes, kb_artifact, confirmed_decision)


def _resume_from_develop_clarification(
    *,
    state_store: StateStore,
    current_clarification: ClarificationState,
    resumed_request: str,
    notes: list[str],
    kb_artifact: KbArtifact | None,
) -> tuple[RouteDecision, PlanArtifact | None, list[str], KbArtifact | None]:
    current_plan = state_store.get_current_plan()
    current_run = state_store.get_current_run()
    if current_plan is None or current_run is None:
        notes.append("Develop clarification could not resume because the active run context is missing")
        return (_clarification_pending_route(RouteDecision(route_name="clarification_resume", request_text=resumed_request, reason="missing develop context"), reason="Develop clarification still requires an active plan context"), None, notes, kb_artifact)

    resume_after = develop_resume_after(current_clarification.resume_context)
    state_store.clear_current_clarification()
    if resume_after == "review_or_execute_plan":
        run_state = _copy_run_state(current_run, stage="plan_generated")
        state_store.set_current_run(run_state)
        notes.append("Develop clarification answered; host must review the plan before continuing")
        return (
            RouteDecision(
                route_name="plan_only",
                request_text=resumed_request,
                reason="Develop clarification changed scope and returned the flow to plan review",
                complexity="complex",
                plan_level=current_plan.level,
                candidate_skill_ids=("design", "develop"),
                should_recover_context=False,
                should_create_plan=False,
                capture_mode=current_clarification.capture_mode,
            ),
            current_plan,
            notes,
            kb_artifact,
        )

    run_state = _copy_run_state(
        current_run,
        stage=str(current_clarification.resume_context.get("active_run_stage") or "executing"),
    )
    state_store.set_current_run(run_state)
    notes.append("Develop clarification answered; host-side implementation may continue")
    return (
        RouteDecision(
            route_name="resume_active",
            request_text=resumed_request,
            reason="Develop clarification answered and host-side implementation may continue",
            complexity="medium",
            plan_level=current_plan.level,
            candidate_skill_ids=current_clarification.candidate_skill_ids or ("develop",),
            should_recover_context=True,
            should_create_plan=False,
            capture_mode=current_clarification.capture_mode,
            active_run_action="resume",
        ),
        current_plan,
        notes,
        kb_artifact,
    )


def _handle_plan_proposal_pending(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
    kb_artifact: KbArtifact | None,
) -> tuple[RouteDecision, PlanArtifact | None, list[str], KbArtifact | None]:
    proposal_state = state_store.get_current_plan_proposal()
    notes: list[str] = []
    if proposal_state is None:
        return (
            _plan_proposal_pending_route(
                decision,
                reason="No pending plan proposal was found",
            ),
            None,
            ["No pending plan proposal to resume"],
            kb_artifact,
        )

    action = decision.active_run_action or "inspect_plan_proposal"
    if action == "inspect_plan_proposal":
        state_store.set_current_run(_make_plan_proposal_run_state(decision, proposal_state))
        notes.append("Plan proposal remains pending")
        return (
            _plan_proposal_pending_route(
                decision,
                reason="Plan proposal is still waiting for package confirmation",
                active_run_action="inspect_plan_proposal",
            ),
            None,
            notes,
            kb_artifact,
        )

    if action == "confirm_plan_proposal":
        confirmed_decision = confirmed_decision_from_proposal(proposal_state)
        created = create_plan_scaffold(
            proposal_state.request_text,
            config=config,
            level=proposal_state.proposed_level,
            decision_state=confirmed_decision,
            topic_key=proposal_state.topic_key,
            plan_id=proposal_state.reserved_plan_id,
        )
        state_store.clear_current_plan_proposal()
        state_store.set_current_plan(created)
        kb_artifact = _merge_kb_artifacts(kb_artifact, ensure_blueprint_index(config), config=config)
        notes.extend(
            _created_plan_notes(
                created,
                config=config,
                base_note=_created_plan_base_note(created.path, "after proposal confirmation"),
            )
        )
        review_route, plan_artifact, gate_notes = _apply_execution_gate_to_plan(
            _plan_review_route(
                RouteDecision(
                    route_name=proposal_state.resume_route or "workflow",
                    request_text=proposal_state.request_text,
                    reason="Plan proposal confirmed and materialized",
                    complexity="complex" if proposal_state.proposed_level != "light" else "medium",
                    plan_level=proposal_state.proposed_level,
                    candidate_skill_ids=proposal_state.candidate_skill_ids,
                    capture_mode=proposal_state.capture_mode,
                ),
                reason="Plan proposal confirmed and materialized for review",
                plan_level=proposal_state.proposed_level,
            ),
            plan_artifact=created,
            state_store=state_store,
            config=config,
            decision_context=confirmed_decision,
        )
        notes.extend(gate_notes)
        return (review_route, plan_artifact, notes, kb_artifact)

    if action == "revise_plan_proposal":
        merged_request = merge_plan_proposal_request(proposal_state, decision.request_text)
        next_topic_key, next_plan_id, next_path = reserve_plan_identity(
            merged_request,
            config=config,
        )
        if next_topic_key != proposal_state.topic_key or next_plan_id != proposal_state.reserved_plan_id or next_path != proposal_state.proposed_path:
            state_store.clear_current_plan_proposal()
            notes.append(f"Exited proposal {proposal_state.checkpoint_id} because revision requires a new proposal identity")
            resumed_route = RouteDecision(
                route_name=proposal_state.resume_route or "workflow",
                request_text=merged_request,
                reason="Revision feedback requires a new proposal identity, so planning restarted",
                complexity="complex" if proposal_state.proposed_level != "light" else "medium",
                plan_level=proposal_state.proposed_level,
                candidate_skill_ids=proposal_state.candidate_skill_ids,
                should_recover_context=False,
                plan_package_policy="confirm",
                capture_mode=proposal_state.capture_mode,
            )
            routed_decision, plan_artifact, planning_notes, kb_artifact = _advance_planning_route(
                resumed_route,
                state_store=state_store,
                config=config,
                kb_artifact=kb_artifact,
                confirmed_decision=confirmed_decision_from_proposal(proposal_state),
            )
            notes.extend(planning_notes)
            return (routed_decision, plan_artifact, notes, kb_artifact)

        refreshed = refresh_plan_proposal_state(
            proposal_state,
            request_text=merged_request,
            proposed_level=proposal_state.proposed_level,
        )
        state_store.set_current_plan_proposal(refreshed)
        state_store.set_current_run(_make_plan_proposal_run_state(decision, refreshed))
        notes.append(f"Refreshed plan proposal {refreshed.checkpoint_id} without drifting path or identity")
        return (
            _plan_proposal_pending_route(
                RouteDecision(
                    route_name=proposal_state.resume_route or "workflow",
                    request_text=merged_request,
                    reason="Plan proposal revised and is waiting for package confirmation",
                    complexity="complex" if proposal_state.proposed_level != "light" else "medium",
                    plan_level=proposal_state.proposed_level,
                    candidate_skill_ids=proposal_state.candidate_skill_ids,
                    capture_mode=proposal_state.capture_mode,
                ),
                reason="Plan proposal revised and is waiting for package confirmation",
                active_run_action="inspect_plan_proposal",
            ),
            None,
            notes,
            kb_artifact,
        )

    state_store.set_current_run(_make_plan_proposal_run_state(decision, proposal_state))
    notes.append(f"Unsupported proposal action fell back to inspect: {action}")
    return (
        _plan_proposal_pending_route(
            decision,
            reason="Plan proposal is still waiting for package confirmation",
        ),
        None,
        notes,
        kb_artifact,
    )


def _resume_from_develop_decision(
    *,
    state_store: StateStore,
    current_decision: DecisionState,
    notes: list[str],
    kb_artifact: KbArtifact | None,
) -> tuple[RouteDecision, PlanArtifact | None, list[str], KbArtifact | None, DecisionState | None]:
    current_plan = state_store.get_current_plan()
    current_run = state_store.get_current_run()
    if current_plan is None or current_run is None:
        notes.append("Develop decision could not resume because the active run context is missing")
        return (_decision_pending_route(RouteDecision(route_name="decision_resume", request_text=current_decision.request_text, reason="missing develop context"), reason="Develop decision still requires an active plan context"), None, notes, kb_artifact, None)

    resume_after = develop_resume_after(current_decision.resume_context)
    _consume_current_decision(state_store, current_decision)
    if resume_after == "review_or_execute_plan":
        run_state = _copy_run_state(current_run, stage="plan_generated")
        state_store.set_current_run(run_state)
        notes.append("Develop decision confirmed; host must review the plan before continuing")
        return (
            RouteDecision(
                route_name="plan_only",
                request_text=current_decision.request_text,
                reason="Develop decision changed scope and returned the flow to plan review",
                complexity="complex",
                plan_level=current_plan.level,
                candidate_skill_ids=("design", "develop"),
                should_recover_context=False,
                should_create_plan=False,
                capture_mode=current_decision.capture_mode,
            ),
            current_plan,
            notes,
            kb_artifact,
            current_decision,
        )

    run_state = _copy_run_state(
        current_run,
        stage=str(current_decision.resume_context.get("active_run_stage") or "executing"),
    )
    state_store.set_current_run(run_state)
    notes.append("Develop decision confirmed; host-side implementation may continue")
    return (
        RouteDecision(
            route_name="resume_active",
            request_text=current_decision.request_text,
            reason="Develop decision confirmed and host-side implementation may continue",
            complexity="medium",
            plan_level=current_plan.level,
            candidate_skill_ids=current_decision.candidate_skill_ids or ("develop",),
            should_recover_context=True,
            should_create_plan=False,
            capture_mode=current_decision.capture_mode,
            active_run_action="resume",
        ),
        current_plan,
        notes,
        kb_artifact,
        current_decision,
    )


def _resume_from_active_plan_binding_decision(
    *,
    state_store: StateStore,
    current_decision: DecisionState,
    notes: list[str],
    kb_artifact: KbArtifact | None,
    config: RuntimeConfig,
) -> tuple[RouteDecision, PlanArtifact | None, list[str], KbArtifact | None, DecisionState | None]:
    selected_option_id = current_decision.selected_option_id or ""
    resume_route = current_decision.resume_route or "plan_only"
    _consume_current_decision(state_store, current_decision)
    notes.append(f"Active-plan routing decision confirmed: {selected_option_id or '<unknown>'}")

    resumed_route = RouteDecision(
        route_name=resume_route,
        request_text=current_decision.request_text,
        reason="Active-plan routing decision confirmed and planning resumed",
        complexity="complex",
        plan_level=current_decision.requested_plan_level,
        candidate_skill_ids=current_decision.candidate_skill_ids or ("design", "develop"),
        should_recover_context=False,
        plan_package_policy=current_decision.plan_package_policy,
        capture_mode=current_decision.capture_mode,
        artifacts={
            "active_plan_binding_selection": selected_option_id,
        },
    )
    planning_route, plan_artifact, planning_notes, kb_artifact = _advance_planning_route(
        resumed_route,
        state_store=state_store,
        config=config,
        kb_artifact=kb_artifact,
    )
    notes.extend(planning_notes)
    return (planning_route, plan_artifact, notes, kb_artifact, current_decision)


def _handle_execution_confirm(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
    session_id: str | None,
) -> tuple[RouteDecision, PlanArtifact | None, list[str]]:
    current_plan = state_store.get_current_plan()
    current_run = state_store.get_current_run()
    notes: list[str] = []
    if current_plan is None or current_run is None:
        return (
            _execution_confirm_pending_route(
                decision,
                reason="No active plan is available for execution confirmation",
            ),
            None,
            ["No active plan available for execution confirmation"],
        )

    routed_action = decision.active_run_action
    if routed_action == "inspect_execution_confirm":
        response_action = "status"
        response_message = ""
    elif routed_action == "confirm_execution":
        response_action = "confirm"
        response_message = ""
    elif routed_action == "revise_execution":
        response_action = "revise"
        response_message = ""
    else:
        response = parse_execution_confirm_response(decision.request_text)
        response_action = response.action
        response_message = response.message

    if response_action == "cancel":
        state_store.reset_active_flow()
        return (
            RouteDecision(
                route_name="cancel_active",
                request_text=decision.request_text,
                reason="Execution confirmation cancelled by user",
                complexity="simple",
                should_recover_context=True,
            ),
            None,
            ["Execution confirmation cancelled"],
        )

    if response_action in {"status", "invalid"}:
        _set_execution_run_state(
            state_store,
            _copy_run_state(
                current_run,
                stage="execution_confirm_pending",
            ),
            session_id=session_id,
        )
        if response_message:
            notes.append(response_message)
        notes.append("Execution confirmation is pending")
        return (
            _execution_confirm_pending_route(
                decision,
                reason="Execution confirmation is still waiting for user input",
                active_run_action="inspect_execution_confirm",
            ),
            current_plan,
            notes,
        )

    if response_action == "revise":
        _set_execution_run_state(
            state_store,
            _copy_run_state(
                current_run,
                stage="execution_confirm_pending",
            ),
            session_id=session_id,
        )
        notes.append("Execution confirmation deferred because plan feedback was received")
        return (
            _execution_confirm_pending_route(
                decision,
                reason="Execution confirmation deferred until the plan feedback is reviewed",
                active_run_action="revise_execution",
            ),
            current_plan,
            notes,
        )

    gate_route = _resume_active_route(
        request_text=current_plan.summary or decision.request_text,
        candidate_skill_ids=decision.candidate_skill_ids or ("develop",),
    )
    gate = evaluate_execution_gate(
        decision=gate_route,
        plan_artifact=current_plan,
        current_clarification=state_store.get_current_clarification(),
        current_decision=_confirmed_decision_context(state_store),
        config=config,
    )
    if gate.gate_status == "decision_required" and gate.blocking_reason != "unresolved_decision":
        gate_decision = _build_route_native_gate_decision_state(
            gate_route,
            gate=gate,
            current_plan=current_plan,
            config=config,
        )
        if gate_decision is not None:
            state_store.set_current_decision(gate_decision)
            _set_execution_run_state(
                state_store,
                RunState(
                    run_id=current_run.run_id,
                    status="active",
                    stage="decision_pending",
                    route_name=current_run.route_name,
                    title=current_plan.title,
                    created_at=current_run.created_at,
                    updated_at=iso_now(),
                    plan_id=current_plan.plan_id,
                    plan_path=current_plan.path,
                    execution_gate=gate,
                    request_excerpt=current_run.request_excerpt,
                    request_sha1=current_run.request_sha1,
                    owner_session_id=current_run.owner_session_id,
                    owner_host=current_run.owner_host,
                    owner_run_id=current_run.owner_run_id,
                ),
                session_id=session_id,
            )
            notes.extend(gate.notes)
            notes.append(f"Execution gate requested a new decision: {gate_decision.decision_id}")
            return (
                _decision_pending_route(
                    decision,
                    reason="Execution gate found a blocking risk that still requires confirmation",
                ),
                current_plan,
                notes,
            )

    if gate.gate_status != "ready":
        _set_execution_run_state(
            state_store,
            _copy_run_state(
                current_run,
                stage="plan_generated",
                execution_gate=gate,
            ),
            session_id=session_id,
        )
        notes.extend(gate.notes)
        notes.append("Execution confirmation could not proceed because the execution gate is not ready")
        return (
            _execution_confirm_pending_route(
                decision,
                reason="Execution gate is no longer ready; review the plan before execution",
                active_run_action="revise_execution",
            ),
            current_plan,
            notes,
        )

    _set_execution_run_state(
        state_store,
        RunState(
            run_id=current_run.run_id,
            status="active",
            stage="executing",
            route_name="resume_active",
            title=current_plan.title,
            created_at=current_run.created_at,
            updated_at=iso_now(),
            plan_id=current_plan.plan_id,
            plan_path=current_plan.path,
            execution_gate=gate,
            request_excerpt=current_run.request_excerpt,
            request_sha1=current_run.request_sha1,
            owner_session_id=current_run.owner_session_id,
            owner_host=current_run.owner_host,
            owner_run_id=current_run.owner_run_id,
        ),
        session_id=session_id,
    )
    notes.extend(gate.notes)
    notes.append("Execution confirmed by user")
    return (
        _resume_active_route(
            request_text=decision.request_text,
            candidate_skill_ids=decision.candidate_skill_ids or ("develop",),
        ),
        current_plan,
        notes,
    )


def _decision_pending_route(decision: RouteDecision, *, reason: str) -> RouteDecision:
    return RouteDecision(
        route_name="decision_pending",
        request_text=decision.request_text,
        reason=reason,
        command=decision.command,
        complexity=decision.complexity,
        plan_level=decision.plan_level,
        candidate_skill_ids=decision.candidate_skill_ids,
        should_recover_context=True,
        should_create_plan=False,
        capture_mode=decision.capture_mode,
        runtime_skill_id=None,
        active_run_action="inspect_decision",
        artifacts=decision.artifacts,
    )


def _plan_proposal_pending_route(
    decision: RouteDecision,
    *,
    reason: str,
    active_run_action: str = "inspect_plan_proposal",
) -> RouteDecision:
    return RouteDecision(
        route_name="plan_proposal_pending",
        request_text=decision.request_text,
        reason=reason,
        command=decision.command,
        complexity=decision.complexity,
        plan_level=decision.plan_level,
        candidate_skill_ids=decision.candidate_skill_ids or ("design",),
        should_recover_context=True,
        plan_package_policy="confirm",
        should_create_plan=False,
        capture_mode=decision.capture_mode,
        runtime_skill_id=None,
        active_run_action=active_run_action,
        artifacts=decision.artifacts,
    )


def _execution_confirm_pending_route(
    decision: RouteDecision,
    *,
    reason: str,
    active_run_action: str = "inspect_execution_confirm",
) -> RouteDecision:
    return RouteDecision(
        route_name="execution_confirm_pending",
        request_text=decision.request_text,
        reason=reason,
        command=decision.command,
        complexity=decision.complexity,
        plan_level=decision.plan_level,
        candidate_skill_ids=decision.candidate_skill_ids or ("develop",),
        should_recover_context=True,
        should_create_plan=False,
        capture_mode=decision.capture_mode,
        runtime_skill_id=None,
        active_run_action=active_run_action,
        artifacts=decision.artifacts,
    )


def _exec_plan_unavailable_route(decision: RouteDecision, *, reason: str) -> RouteDecision:
    return RouteDecision(
        route_name="exec_plan",
        request_text=decision.request_text,
        reason=reason,
        command=decision.command,
        complexity=decision.complexity,
        plan_level=decision.plan_level,
        candidate_skill_ids=decision.candidate_skill_ids or ("develop",),
        should_recover_context=True,
        should_create_plan=False,
        capture_mode=decision.capture_mode,
        runtime_skill_id=None,
        active_run_action="inspect_exec_recovery",
        artifacts=decision.artifacts,
    )


def _clarification_pending_route(decision: RouteDecision, *, reason: str) -> RouteDecision:
    return RouteDecision(
        route_name="clarification_pending",
        request_text=decision.request_text,
        reason=reason,
        command=decision.command,
        complexity=decision.complexity,
        plan_level=decision.plan_level,
        candidate_skill_ids=decision.candidate_skill_ids,
        should_recover_context=True,
        should_create_plan=False,
        capture_mode=decision.capture_mode,
        runtime_skill_id=None,
        active_run_action="inspect_clarification",
        artifacts=decision.artifacts,
    )


def _plan_review_route(
    decision: RouteDecision,
    *,
    reason: str,
    plan_level: str | None,
) -> RouteDecision:
    return RouteDecision(
        route_name="plan_only",
        request_text=decision.request_text,
        reason=reason,
        command=decision.command,
        complexity=decision.complexity,
        plan_level=plan_level,
        candidate_skill_ids=decision.candidate_skill_ids or ("design", "develop"),
        should_recover_context=False,
        plan_package_policy="none",
        should_create_plan=False,
        capture_mode=decision.capture_mode,
        runtime_skill_id=None,
        artifacts=decision.artifacts,
    )


def _normalized_plan_package_policy(decision: RouteDecision, *, config: RuntimeConfig) -> str:
    """Fail closed for legacy or malformed planning routes that omit the new policy."""
    policy = str(decision.plan_package_policy or "none").strip() or "none"
    if policy != "none":
        return policy
    if decision.route_name == "plan_only":
        return "immediate"
    if decision.route_name in {"workflow", "light_iterate"}:
        if find_plan_by_request_reference(decision.request_text, config=config) is not None:
            return "confirm"
        if request_explicitly_wants_new_plan(decision.request_text):
            return "immediate"
        return "confirm"
    return policy


def _resume_active_route(*, request_text: str, candidate_skill_ids: tuple[str, ...]) -> RouteDecision:
    return RouteDecision(
        route_name="resume_active",
        request_text=request_text,
        reason="Execution confirmed and develop may start",
        complexity="medium",
        should_recover_context=True,
        candidate_skill_ids=candidate_skill_ids,
        active_run_action="resume",
    )


def _copy_run_state(
    current_run: RunState,
    *,
    stage: str,
    execution_gate: ExecutionGate | None | object = None,
) -> RunState:
    next_execution_gate = current_run.execution_gate if execution_gate is None else execution_gate
    return RunState(
        run_id=current_run.run_id,
        status=current_run.status,
        stage=stage,
        route_name=current_run.route_name,
        title=current_run.title,
        created_at=current_run.created_at,
        updated_at=iso_now(),
        plan_id=current_run.plan_id,
        plan_path=current_run.plan_path,
        execution_gate=next_execution_gate,
        request_excerpt=current_run.request_excerpt,
        request_sha1=current_run.request_sha1,
        owner_session_id=current_run.owner_session_id,
        owner_host=current_run.owner_host,
        owner_run_id=current_run.owner_run_id,
    )


def _advance_planning_route(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
    kb_artifact: KbArtifact | None,
    confirmed_decision: DecisionState | None = None,
) -> tuple[RouteDecision, PlanArtifact | None, list[str], KbArtifact | None]:
    notes: list[str] = []
    plan_package_policy = _normalized_plan_package_policy(decision, config=config)
    kb_artifact = _merge_kb_artifacts(kb_artifact, ensure_blueprint_scaffold(config), config=config)

    pending_clarification = _build_route_native_clarification_state(decision, config=config)
    if pending_clarification is not None:
        state_store.set_current_clarification(pending_clarification)
        _preserve_or_clear_current_plan_for_pending_planning_checkpoint(
            decision,
            state_store=state_store,
            config=config,
        )
        clarification_gate = evaluate_execution_gate(
            decision=decision,
            plan_artifact=None,
            current_clarification=pending_clarification,
            current_decision=None,
            config=config,
        )
        state_store.set_current_run(
            _make_clarification_run_state(
                decision,
                pending_clarification,
                execution_gate=clarification_gate,
            )
        )
        if confirmed_decision is not None and confirmed_decision.status == "confirmed":
            state_store.set_current_decision(confirmed_decision)
        notes.append(f"Clarification created: {pending_clarification.clarification_id}")
        return (
            _clarification_pending_route(
                decision,
                reason="Detected missing factual details that must be clarified before planning can continue",
            ),
            None,
            notes,
            kb_artifact,
        )

    if confirmed_decision is None:
        current_plan = state_store.get_current_plan()
        if current_plan is not None and _should_create_active_plan_binding_decision(
            decision,
            current_plan=current_plan,
            config=config,
        ):
            pending_decision = build_active_plan_binding_decision_state(
                decision,
                current_plan=current_plan,
                config=config,
            )
            state_store.set_current_decision(pending_decision)
            current_run = state_store.get_current_run()
            state_store.set_current_run(
                RunState(
                    run_id=current_run.run_id if current_run is not None else _make_run_id(decision.request_text),
                    status="active",
                    stage="decision_pending",
                    route_name=decision.route_name,
                    title=pending_decision.question,
                    created_at=current_run.created_at if current_run is not None else iso_now(),
                    updated_at=iso_now(),
                    plan_id=current_plan.plan_id,
                    plan_path=current_plan.path,
                    execution_gate=current_run.execution_gate if current_run is not None else None,
                    request_excerpt=summarize_request_text(decision.request_text),
                    request_sha1=stable_request_sha1(decision.request_text),
                )
            )
            notes.append(f"Decision checkpoint created: {pending_decision.decision_id}")
            return (
                _decision_pending_route(
                    decision,
                    reason="A non-anchored complex request arrived while another plan is active",
                ),
                None,
                notes,
                kb_artifact,
            )

        pending_decision = _build_route_native_decision_state(decision, config=config)
        if pending_decision is not None:
            state_store.set_current_decision(pending_decision)
            _preserve_or_clear_current_plan_for_pending_planning_checkpoint(
                decision,
                state_store=state_store,
                config=config,
            )
            decision_gate = evaluate_execution_gate(
                decision=decision,
                plan_artifact=None,
                current_clarification=None,
                current_decision=pending_decision,
                config=config,
            )
            state_store.set_current_run(
                _make_decision_run_state(
                    decision,
                    pending_decision,
                    execution_gate=decision_gate,
                )
            )
            notes.append(f"Decision checkpoint created: {pending_decision.decision_id}")
            return (
                _decision_pending_route(decision, reason="Detected an explicit design split that requires confirmation"),
                None,
            notes,
            kb_artifact,
        )

    level = decision.plan_level or _default_plan_level(decision)
    selection = _resolve_plan_for_request(
        decision,
        state_store=state_store,
        config=config,
        confirmed_decision=confirmed_decision,
    )
    if selection.action == "reuse_existing":
        plan_artifact = selection.plan_artifact
        if plan_artifact is None:
            raise RuntimeError("Plan selection resolved to reuse_existing without an artifact")
        state_store.clear_current_plan_proposal()
        state_store.set_current_plan(plan_artifact)
        if selection.reason_note:
            notes.append(selection.reason_note)
        routed_decision, plan_artifact, gate_notes = _apply_execution_gate_to_plan(
            decision,
            plan_artifact=plan_artifact,
            state_store=state_store,
            config=config,
            decision_context=confirmed_decision,
        )
        notes.extend(gate_notes)
        return (routed_decision, plan_artifact, notes, kb_artifact)

    explain_only_override = detect_explain_only_consult_override(
        decision.request_text,
        command=decision.command,
        current_run=state_store.get_current_run(),
        current_plan=state_store.get_current_plan(),
        current_plan_proposal=state_store.get_current_plan_proposal(),
        last_route=state_store.get_last_route(),
    )
    if explain_only_override is not None and plan_package_policy == "confirm":
        notes.append("Bypassed plan proposal materialization for explain-only request")
        if _consume_current_decision_if_confirmed_match(state_store, confirmed_decision):
            notes.append(f"Decision consumed: {confirmed_decision.decision_id}")
        return (
            RouteDecision(
                route_name="consult",
                request_text=decision.request_text,
                reason=str(explain_only_override["reason"]),
                complexity="simple",
                should_recover_context=True,
                candidate_skill_ids=("analyze",),
                artifacts=dict(explain_only_override["artifacts"]),
            ),
            None,
            notes,
            kb_artifact,
        )

    if plan_package_policy == "confirm":
        topic_key, reserved_plan_id, proposed_path = reserve_plan_identity(
            decision.request_text,
            config=config,
        )
        proposal_state = build_plan_proposal_state(
            decision,
            request_text=decision.request_text,
            proposed_level=level,
            checkpoint_id=_make_plan_proposal_id(decision.request_text),
            reserved_plan_id=reserved_plan_id,
            topic_key=topic_key,
            proposed_path=proposed_path,
            confirmed_decision=confirmed_decision,
        )
        state_store.clear_current_plan()
        state_store.set_current_plan_proposal(proposal_state)
        state_store.set_current_run(_make_plan_proposal_run_state(decision, proposal_state))
        if confirmed_decision is not None and confirmed_decision.status == "confirmed" and confirmed_decision.selection is not None:
            _consume_current_decision(state_store, confirmed_decision)
            notes.append(f"Decision consumed: {confirmed_decision.decision_id}")
        staged_note = f"Plan proposal staged at {proposal_state.proposed_path}"
        if selection.reason_note:
            staged_note = f"{staged_note} {selection.reason_note}"
        notes.append(staged_note)
        return (
            _plan_proposal_pending_route(
                decision,
                reason="Planning converged to a stable proposal and is waiting for package confirmation",
            ),
            None,
            notes,
            kb_artifact,
        )

    created = create_plan_scaffold(
        decision.request_text,
        config=config,
        level=level,
        decision_state=confirmed_decision,
    )
    state_store.clear_current_plan_proposal()
    state_store.set_current_plan(created)
    kb_artifact = _merge_kb_artifacts(kb_artifact, ensure_blueprint_index(config), config=config)
    notes.extend(
        _created_plan_notes(
            created,
            config=config,
            base_note=_created_plan_base_note(created.path, selection.reason_note),
        )
    )

    routed_decision, plan_artifact, gate_notes = _apply_execution_gate_to_plan(
        decision,
        plan_artifact=created,
        state_store=state_store,
        config=config,
        decision_context=confirmed_decision,
    )
    notes.extend(gate_notes)
    return (routed_decision, plan_artifact, notes, kb_artifact)


def _resolve_plan_for_request(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
    confirmed_decision: DecisionState | None,
) -> _PlanSelection:
    current_plan = state_store.get_current_plan()
    active_plan_binding_selection = str(decision.artifacts.get("active_plan_binding_selection") or "").strip()

    if confirmed_decision is not None:
        if confirmed_decision.decision_type == ACTIVE_PLAN_BINDING_DECISION_TYPE:
            selected_option_id = confirmed_decision.selected_option_id or ""
            if selected_option_id == ACTIVE_PLAN_ATTACH_OPTION_ID and current_plan is not None:
                return _PlanSelection(
                    action="reuse_existing",
                    plan_artifact=current_plan,
                    reason_note=f"Attached the request back to active plan {current_plan.path} after decision confirmation",
                )
            if selected_option_id == ACTIVE_PLAN_NEW_OPTION_ID or current_plan is None:
                return _PlanSelection(
                    action="create_new",
                    reason_note="after active-plan routing confirmation",
                )

        if current_plan is not None:
            return _PlanSelection(
                action="reuse_existing",
                plan_artifact=current_plan,
                reason_note=f"Reused active plan {current_plan.path} after decision confirmation",
            )
        return _PlanSelection(
            action="create_new",
            reason_note="after decision confirmation",
        )

    explicit_plan = find_plan_by_request_reference(decision.request_text, config=config)
    explicit_new_plan = request_explicitly_wants_new_plan(decision.request_text)

    if active_plan_binding_selection == ACTIVE_PLAN_NEW_OPTION_ID:
        return _PlanSelection(
            action="create_new",
            reason_note="(selected new-plan routing)",
        )

    if explicit_plan is not None:
        if current_plan is not None and explicit_plan.plan_id == current_plan.plan_id:
            return _PlanSelection(
                action="reuse_existing",
                plan_artifact=current_plan,
                reason_note=f"Reused active plan {current_plan.path} (explicit self-reference)",
            )
        return _PlanSelection(
            action="reuse_existing",
            plan_artifact=explicit_plan,
            reason_note=f"Rebound planning context to existing plan {explicit_plan.path} (explicit plan reference)",
        )

    if explicit_new_plan:
        return _PlanSelection(
            action="create_new",
            reason_note="(explicit new-plan request)",
        )

    if current_plan is not None:
        if active_plan_binding_selection == ACTIVE_PLAN_ATTACH_OPTION_ID:
            return _PlanSelection(
                action="reuse_existing",
                plan_artifact=current_plan,
                reason_note=f"Reused active plan {current_plan.path} (selected current-plan routing)",
            )
        if _request_anchors_current_plan(decision.request_text, current_plan=current_plan):
            return _PlanSelection(
                action="reuse_existing",
                plan_artifact=current_plan,
                reason_note=f"Reused active plan {current_plan.path} (implicit current-plan anchor)",
            )
        return _PlanSelection(
            action="reuse_existing",
            plan_artifact=current_plan,
            reason_note=f"Reused active plan {current_plan.path} under strict single-active-plan policy",
        )

    return _PlanSelection(
        action="create_new",
        reason_note="",
    )


def _created_plan_notes(created: PlanArtifact, *, config: RuntimeConfig, base_note: str) -> list[str]:
    notes = [base_note]
    priority_note = priority_note_for_plan(
        config=config,
        plan_id=created.plan_id,
        language=config.language,
    )
    if priority_note:
        notes.append(encode_priority_note_event(priority_note))
    return notes


def _created_plan_base_note(plan_path: str, reason_note: str) -> str:
    base = f"Plan scaffold created at {plan_path}"
    if reason_note:
        return f"{base} {reason_note}"
    return base


def _should_create_active_plan_binding_decision(
    decision: RouteDecision,
    *,
    current_plan: PlanArtifact,
    config: RuntimeConfig,
) -> bool:
    if decision.route_name not in {"plan_only", "workflow", "light_iterate"}:
        return False
    if decision.complexity != "complex":
        return False
    if str(decision.artifacts.get("active_plan_binding_selection") or "").strip():
        return False
    if str(decision.artifacts.get("planning_resume_source") or "").strip():
        return False
    if find_plan_by_request_reference(decision.request_text, config=config) is not None:
        return False
    if request_explicitly_wants_new_plan(decision.request_text):
        return False
    return not _request_anchors_current_plan(decision.request_text, current_plan=current_plan)


def _request_anchors_current_plan(request_text: str, *, current_plan: PlanArtifact) -> bool:
    text = request_text.strip()
    if not text:
        return False

    lowered = text.casefold()
    for anchor in (current_plan.plan_id, current_plan.path, current_plan.title):
        candidate = str(anchor or "").strip().casefold()
        if candidate and candidate in lowered:
            return True

    compact = lowered.replace(" ", "")
    if any(token in compact for token in ("当前plan", "这个plan", "该plan", "activeplan", "currentplan")):
        return True
    if any(token in compact for token in ("当前方案", "这个方案", "该方案")):
        return True
    return any(pattern.search(text) is not None for pattern in _CURRENT_PLAN_ANCHOR_PATTERNS)


def _preserve_or_clear_current_plan_for_pending_planning_checkpoint(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
) -> None:
    current_plan = state_store.get_current_plan()
    if current_plan is None:
        return

    explicit_plan = find_plan_by_request_reference(decision.request_text, config=config)
    if explicit_plan is not None and explicit_plan.plan_id != current_plan.plan_id:
        state_store.set_current_plan(explicit_plan)
        return

    if request_explicitly_wants_new_plan(decision.request_text):
        state_store.clear_current_plan()
        return


def _apply_execution_gate_to_plan(
    decision: RouteDecision,
    *,
    plan_artifact: PlanArtifact,
    state_store: StateStore,
    config: RuntimeConfig,
    decision_context: DecisionState | None,
) -> tuple[RouteDecision, PlanArtifact, list[str]]:
    review_route = _plan_review_route(
        decision,
        reason="Plan materialized and is waiting for review before execution",
        plan_level=plan_artifact.level,
    )
    if str(decision.artifacts.get("active_plan_binding_selection") or "").strip() == ACTIVE_PLAN_ATTACH_OPTION_ID:
        gate = ExecutionGate(
            gate_status="blocked",
            blocking_reason="missing_info",
            plan_completion="incomplete",
            next_required_action="review_or_execute_plan",
            notes=("Attached the new request to the current plan; review and update that plan before execution continues.",),
        )
        state_store.set_current_run(
            _make_run_state(
                _plan_review_route(
                    decision,
                    reason="Attached request to the current plan and returned it to plan review",
                    plan_level=decision.plan_level or plan_artifact.level,
                ),
                plan_artifact,
                stage="plan_generated",
                execution_gate=gate,
            )
        )
        return (
            _plan_review_route(
                decision,
                reason="Attached request to the current plan and returned it to plan review",
                plan_level=decision.plan_level or plan_artifact.level,
            ),
            plan_artifact,
            list(gate.notes),
        )

    gate = evaluate_execution_gate(
        decision=decision,
        plan_artifact=plan_artifact,
        current_clarification=None,
        current_decision=decision_context,
        config=config,
    )
    notes = list(gate.notes)

    if decision_context is not None and decision_context.status == "confirmed" and decision_context.selection is not None:
        _consume_current_decision(state_store, decision_context)
        notes.append(f"Decision consumed: {decision_context.decision_id}")

    if gate.gate_status == "decision_required" and gate.blocking_reason != "unresolved_decision":
        gate_decision = _build_route_native_gate_decision_state(
            decision,
            gate=gate,
            current_plan=plan_artifact,
            config=config,
        )
        if gate_decision is not None:
            state_store.set_current_decision(gate_decision)
            state_store.set_current_run(
                RunState(
                    run_id=_make_run_id(decision.request_text),
                    status="active",
                    stage="decision_pending",
                    route_name=decision.route_name,
                    title=plan_artifact.title,
                    created_at=plan_artifact.created_at,
                    updated_at=iso_now(),
                    plan_id=plan_artifact.plan_id,
                    plan_path=plan_artifact.path,
                    execution_gate=gate,
                    request_excerpt=summarize_request_text(decision.request_text),
                    request_sha1=stable_request_sha1(decision.request_text),
                )
            )
            notes.append(f"Execution gate requested a new decision: {gate_decision.decision_id}")
            return (
                _decision_pending_route(decision, reason="Execution gate found a blocking risk that still requires confirmation"),
                plan_artifact,
                notes,
            )

    stage = "ready_for_execution" if gate.gate_status == "ready" else "plan_generated"
    state_store.set_current_run(
        _make_run_state(
            review_route,
            plan_artifact,
            stage=stage,
            execution_gate=gate,
        )
    )
    return (
        review_route,
        plan_artifact,
        notes,
    )


def _consume_current_decision(state_store: StateStore, decision_state: DecisionState) -> None:
    consumed = consume_decision(decision_state)
    state_store.set_current_decision(consumed)
    state_store.clear_current_decision()


def _consume_current_decision_if_confirmed_match(
    state_store: StateStore,
    decision_state: DecisionState | None,
) -> bool:
    if decision_state is None or decision_state.status != "confirmed" or decision_state.selection is None:
        return False
    current_decision = state_store.get_current_decision()
    if current_decision is None:
        return False
    if current_decision.decision_id != decision_state.decision_id:
        return False
    if current_decision.status != "confirmed" or current_decision.selection is None:
        return False
    _consume_current_decision(state_store, current_decision)
    return True


def _confirmed_decision_context(state_store: StateStore) -> DecisionState | None:
    current_decision = state_store.get_current_decision()
    if current_decision is None or current_decision.status != "confirmed" or current_decision.selection is None:
        return None
    return current_decision


def _merge_kb_artifacts(kb_artifact: KbArtifact | None, extra_files: tuple[str, ...], *, config: RuntimeConfig) -> KbArtifact | None:
    if kb_artifact is None and not extra_files:
        return None
    base_files = kb_artifact.files if kb_artifact is not None else ()
    merged_files = tuple(dict.fromkeys((*base_files, *extra_files)))
    return KbArtifact(
        mode=config.kb_init,
        files=merged_files,
        created_at=kb_artifact.created_at if kb_artifact is not None else iso_now(),
    )


def _build_route_native_clarification_state(
    decision: RouteDecision,
    *,
    config: RuntimeConfig,
) -> ClarificationState | None:
    """Route planning-mode clarification through the generic checkpoint contract."""
    clarification_state = build_clarification_state(decision, config=config)
    if clarification_state is None:
        return None
    request = checkpoint_request_from_clarification_state(
        clarification_state,
        config=config,
        source_route=decision.route_name,
    )
    materialized = materialize_checkpoint_request(request.to_dict(), config=config)
    return materialized.clarification_state


def _build_route_native_decision_state(
    decision: RouteDecision,
    *,
    config: RuntimeConfig,
) -> DecisionState | None:
    """Route planning-mode design decisions through the generic checkpoint contract."""
    decision_state = build_decision_state(decision, config=config)
    if decision_state is None:
        return None
    request = checkpoint_request_from_decision_state(
        decision_state,
        source_route=decision.route_name,
    )
    materialized = materialize_checkpoint_request(request.to_dict(), config=config)
    return materialized.decision_state


def _build_route_native_gate_decision_state(
    decision: RouteDecision,
    *,
    gate: ExecutionGate,
    current_plan: PlanArtifact,
    config: RuntimeConfig,
) -> DecisionState | None:
    """Normalize execution-gate follow-up decisions through the same contract."""
    decision_state = build_execution_gate_decision_state(
        decision,
        gate=gate,
        current_plan=current_plan,
        config=config,
    )
    if decision_state is None:
        return None
    request = checkpoint_request_from_decision_state(
        decision_state,
        source_route=decision.route_name,
    )
    materialized = materialize_checkpoint_request(request.to_dict(), config=config)
    return materialized.decision_state
