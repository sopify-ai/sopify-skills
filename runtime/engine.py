"""Top-level orchestration for Sopify runtime."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from typing import Any, Mapping, Optional

from .checkpoint_materializer import materialize_checkpoint_request
from .checkpoint_request import checkpoint_request_from_clarification_state, checkpoint_request_from_decision_state
from .clarification import build_clarification_state, has_submitted_clarification, merge_clarification_request, parse_clarification_response, stale_clarification
from .compare_decision import build_compare_decision_contract
from .config import load_runtime_config
from .context_recovery import recover_context
from .decision import (
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
from .kb import bootstrap_kb, ensure_blueprint_scaffold
from .models import ClarificationState, DecisionState, ExecutionGate, KbArtifact, PlanArtifact, ReplayEvent, RouteDecision, RunState, RuntimeHandoff, RuntimeResult, SkillMeta
from .plan_scaffold import create_plan_scaffold
from .replay import ReplayWriter, build_compare_replay_event, build_decision_replay_event
from .router import Router
from .skill_registry import SkillRegistry
from .skill_runner import SkillExecutionError, run_runtime_skill
from .state import StateStore, iso_now


def run_runtime(
    user_input: str,
    *,
    workspace_root: str | Path = ".",
    global_config_path: str | Path | None = None,
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
    state_store = StateStore(config)
    state_store.ensure()
    kb_artifact: KbArtifact | None = bootstrap_kb(config)

    skills = SkillRegistry(config, user_home=user_home).discover()
    router = Router(config, state_store=state_store)
    classified_route = router.classify(user_input, skills=skills)
    recovered = recover_context(classified_route, config=config, state_store=state_store)

    notes: list[str] = []
    plan_artifact: PlanArtifact | None = None
    skill_result: Mapping[str, Any] | None = None
    replay_session_dir: str | None = None
    handoff: RuntimeHandoff | None = None
    replay_events: list[ReplayEvent] = []
    effective_route = classified_route
    confirmed_decision_for_replay: DecisionState | None = None

    current_clarification = state_store.get_current_clarification()
    if (
        current_clarification is not None
        and effective_route.route_name in {"plan_only", "workflow", "light_iterate"}
        and effective_route.route_name not in {"clarification_pending", "clarification_resume"}
    ):
        # A new planning request supersedes the previous pending clarification.
        stale_state = stale_clarification(current_clarification)
        state_store.set_current_clarification(stale_state)
        state_store.clear_current_clarification()
        notes.append(f"Superseded pending clarification: {stale_state.clarification_id}")
        current_clarification = None

    current_decision = state_store.get_current_decision()
    if (
        current_decision is not None
        and effective_route.route_name in {"plan_only", "workflow", "light_iterate"}
        and effective_route.route_name not in {"decision_pending", "decision_resume"}
    ):
        # A new planning request supersedes the previous pending checkpoint.
        stale_state = stale_decision(current_decision)
        state_store.set_current_decision(stale_state)
        state_store.clear_current_decision()
        notes.append(f"Superseded pending decision checkpoint: {stale_state.decision_id}")
        current_decision = None

    if effective_route.route_name == "cancel_active":
        state_store.reset_active_flow()
        notes.append("Active flow cleared")
    elif effective_route.route_name == "finalize_active":
        finalized = finalize_plan(
            config=config,
            state_store=state_store,
            current_plan=state_store.get_current_plan() or recovered.current_plan,
        )
        plan_artifact = finalized.archived_plan
        if finalized.kb_artifact is not None:
            kb_artifact = finalized.kb_artifact
        notes.extend(finalized.notes)
    elif effective_route.route_name == "clarification_resume":
        effective_route, plan_artifact, clarification_notes, kb_artifact = _handle_clarification_resume(
            effective_route,
            state_store=state_store,
            config=config,
            kb_artifact=kb_artifact,
        )
        notes.extend(clarification_notes)
    elif effective_route.route_name == "decision_resume":
        effective_route, plan_artifact, decision_notes, kb_artifact, confirmed_decision_for_replay = _handle_decision_resume(
            effective_route,
            state_store=state_store,
            config=config,
            kb_artifact=kb_artifact,
        )
        notes.extend(decision_notes)
    elif effective_route.route_name == "execution_confirm_pending":
        effective_route, plan_artifact, execution_confirm_notes = _handle_execution_confirm(
            effective_route,
            state_store=state_store,
            config=config,
        )
        notes.extend(execution_confirm_notes)
    elif effective_route.should_create_plan:
        effective_route, plan_artifact, planning_notes, kb_artifact = _advance_planning_route(
            effective_route,
            state_store=state_store,
            config=config,
            kb_artifact=kb_artifact,
        )
        notes.extend(planning_notes)
    elif effective_route.route_name in {"resume_active", "exec_plan"}:
        if state_store.get_current_clarification() is not None:
            effective_route = _clarification_pending_route(
                effective_route,
                reason="Pending clarification must be answered before execution can continue",
            )
            notes.append("Blocked execution because clarification is still pending")
        else:
            current_plan = state_store.get_current_plan() or recovered.current_plan
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
                    current_decision=_confirmed_decision_context(state_store),
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
                        state_store.set_current_decision(gate_decision)
                        state_store.set_current_run(
                            RunState(
                                run_id=(state_store.get_current_run() or recovered.current_run).run_id if (state_store.get_current_run() or recovered.current_run) is not None else _make_run_id(effective_route.request_text),
                                status="active",
                                stage="decision_pending",
                                route_name=effective_route.route_name,
                                title=current_plan.title,
                                created_at=(state_store.get_current_run() or recovered.current_run).created_at if (state_store.get_current_run() or recovered.current_run) is not None else current_plan.created_at,
                                updated_at=iso_now(),
                                plan_id=current_plan.plan_id,
                                plan_path=current_plan.path,
                                execution_gate=gate,
                            )
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
                    state_store.set_current_run(
                        _make_run_state(
                            effective_route,
                            current_plan,
                            stage="plan_generated",
                            execution_gate=gate,
                        )
                    )
                    notes.extend(gate.notes)
                    notes.append("Blocked execution because the execution gate is not ready")
                else:
                    current_run = state_store.get_current_run() or recovered.current_run
                    state_store.set_current_run(
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
                        )
                    )
                    notes.extend(gate.notes)
                    notes.append("Active run resumed")

    state_store.set_last_route(effective_route)

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

    if effective_route.capture_mode != "off":
        writer = ReplayWriter(config)
        run_state = state_store.get_current_run() or recovered.current_run
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
        )
        replay_events.append(replay_event)
        current_decision = state_store.get_current_decision()
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
            run_state=state_store.get_current_run(),
            route=effective_route,
            plan_artifact=plan_artifact or recovered.current_plan,
            events=replay_events,
        )
        replay_session_dir = str(session_dir.relative_to(config.workspace_root))

    if effective_route.route_name == "cancel_active":
        handoff = None
    else:
        current_run = state_store.get_current_run() or recovered.current_run
        current_plan = plan_artifact or state_store.get_current_plan() or recovered.current_plan
        handoff = build_runtime_handoff(
            config=config,
            decision=effective_route,
            run_id=(current_run.run_id if current_run is not None else _make_run_id(effective_route.request_text)),
            current_run=current_run,
            current_plan=current_plan,
            kb_artifact=kb_artifact,
            replay_session_dir=replay_session_dir,
            skill_result=skill_result,
            current_clarification=state_store.get_current_clarification(),
            current_decision=state_store.get_current_decision(),
            notes=notes,
        )
        if handoff is not None:
            state_store.set_current_handoff(handoff)
        else:
            state_store.clear_current_handoff()

    latest_context = recover_context(effective_route, config=config, state_store=state_store)
    return RuntimeResult(
        route=effective_route,
        recovered_context=latest_context,
        discovered_skills=skills,
        kb_artifact=kb_artifact,
        plan_artifact=plan_artifact,
        skill_result=skill_result,
        replay_session_dir=replay_session_dir,
        handoff=handoff,
        notes=tuple(notes),
    )


def _default_plan_level(decision: RouteDecision) -> str:
    if decision.complexity == "medium":
        return "light"
    return "standard"


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
    )


def _make_run_id(request_text: str) -> str:
    timestamp = iso_now().replace(":", "").replace("-", "")[:15]
    digest = sha1(request_text.encode("utf-8")).hexdigest()[:6]
    return f"{timestamp}_{digest}"


def _find_skill(skills: tuple[SkillMeta, ...], skill_id: str) -> SkillMeta | None:
    for skill in skills:
        if skill.skill_id == skill_id:
            return skill
    return None


def _phase_for_route(decision: RouteDecision) -> str:
    if decision.route_name in {"plan_only", "workflow", "light_iterate", "clarification_pending", "clarification_resume", "decision_pending", "decision_resume"}:
        return "design"
    if decision.route_name in {"execution_confirm_pending", "resume_active", "exec_plan", "quick_fix"}:
        return "develop"
    if decision.route_name == "compare":
        return "analysis"
    return "analysis"


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
        should_create_plan=True,
        capture_mode=current_clarification.capture_mode,
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

    confirmed_decision = current_decision
    resumed_route = RouteDecision(
        route_name=current_decision.resume_route or "plan_only",
        request_text=current_decision.request_text,
        reason="Decision confirmed and planning resumed",
        command=None,
        complexity="complex",
        plan_level=current_decision.requested_plan_level,
        candidate_skill_ids=current_decision.candidate_skill_ids,
        should_recover_context=False,
        should_create_plan=True,
        capture_mode=current_decision.capture_mode,
    )
    current_plan = state_store.get_current_plan()
    if current_plan is not None:
        gated_route, reused_plan, gated_notes = _apply_execution_gate_to_plan(
            resumed_route,
            plan_artifact=current_plan,
            state_store=state_store,
            config=config,
            decision_context=current_decision,
        )
        notes.extend(gated_notes)
        return (gated_route, reused_plan, notes, kb_artifact, confirmed_decision)

    planning_route, plan_artifact, planning_notes, kb_artifact = _advance_planning_route(
        resumed_route,
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


def _handle_execution_confirm(
    decision: RouteDecision,
    *,
    state_store: StateStore,
    config: RuntimeConfig,
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
        state_store.set_current_run(
            _copy_run_state(
                current_run,
                stage="execution_confirm_pending",
            )
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
        state_store.set_current_run(
            _copy_run_state(
                current_run,
                stage="execution_confirm_pending",
            )
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
            state_store.set_current_run(
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
                )
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
        state_store.set_current_run(
            _copy_run_state(
                current_run,
                stage="plan_generated",
                execution_gate=gate,
            )
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

    state_store.set_current_run(
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
        )
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
    kb_artifact = _merge_kb_artifacts(kb_artifact, ensure_blueprint_scaffold(config), config=config)

    pending_clarification = _build_route_native_clarification_state(decision, config=config)
    if pending_clarification is not None:
        state_store.set_current_clarification(pending_clarification)
        state_store.clear_current_plan()
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
        pending_decision = _build_route_native_decision_state(decision, config=config)
        if pending_decision is not None:
            state_store.set_current_decision(pending_decision)
            state_store.clear_current_plan()
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
    plan_artifact = create_plan_scaffold(
        decision.request_text,
        config=config,
        level=level,
        decision_state=confirmed_decision,
    )
    state_store.set_current_plan(plan_artifact)
    notes.append(f"Plan scaffold created at {plan_artifact.path}")

    routed_decision, plan_artifact, gate_notes = _apply_execution_gate_to_plan(
        decision,
        plan_artifact=plan_artifact,
        state_store=state_store,
        config=config,
        decision_context=confirmed_decision,
    )
    notes.extend(gate_notes)
    return (routed_decision, plan_artifact, notes, kb_artifact)


def _apply_execution_gate_to_plan(
    decision: RouteDecision,
    *,
    plan_artifact: PlanArtifact,
    state_store: StateStore,
    config: RuntimeConfig,
    decision_context: DecisionState | None,
) -> tuple[RouteDecision, PlanArtifact, list[str]]:
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
            decision,
            plan_artifact,
            stage=stage,
            execution_gate=gate,
        )
    )
    if gate.gate_status == "ready":
        return (
            _execution_confirm_pending_route(
                decision,
                reason="Plan passed the execution gate and is waiting for user confirmation",
            ),
            plan_artifact,
            notes,
        )
    return (
        RouteDecision(
            route_name=decision.route_name,
            request_text=decision.request_text,
            reason="Plan materialized and execution gate evaluated",
            command=decision.command,
            complexity=decision.complexity,
            plan_level=decision.plan_level or plan_artifact.level,
            candidate_skill_ids=decision.candidate_skill_ids,
            should_recover_context=False,
            should_create_plan=False,
            capture_mode=decision.capture_mode,
            artifacts=decision.artifacts,
        ),
        plan_artifact,
        notes,
    )


def _consume_current_decision(state_store: StateStore, decision_state: DecisionState) -> None:
    consumed = consume_decision(decision_state)
    state_store.set_current_decision(consumed)
    state_store.clear_current_decision()


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
