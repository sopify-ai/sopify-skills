"""Structured handoff contract for downstream host execution."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping, Sequence

from .checkpoint_request import (
    CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED,
    checkpoint_request_from_clarification_state,
    checkpoint_request_from_decision_state,
    checkpoint_request_from_execution_confirm,
    normalize_checkpoint_request,
)
from .clarification import CURRENT_CLARIFICATION_RELATIVE_PATH, build_scope_clarification_form, clarification_submission_state_payload
from .compare_decision import build_compare_decision_contract
from .decision_policy import has_tradeoff_checkpoint_signal
from .decision import CURRENT_DECISION_RELATIVE_PATH
from .entry_guard import build_entry_guard_contract
from .execution_confirm import build_execution_summary
from .models import KbArtifact, PlanArtifact, RouteDecision, RunState, RuntimeConfig, RuntimeHandoff

HANDOFF_SCHEMA_VERSION = "1"
CURRENT_HANDOFF_FILENAME = "current_handoff.json"
CURRENT_HANDOFF_RELATIVE_PATH = f".sopify-skills/state/{CURRENT_HANDOFF_FILENAME}"

_ROUTE_HANDOFF_KIND = {
    "plan_only": "plan",
    "workflow": "workflow",
    "light_iterate": "light_iterate",
    "quick_fix": "quick_fix",
    "finalize_active": "finalize",
    "clarification_pending": "clarification",
    "clarification_resume": "clarification",
    "execution_confirm_pending": "execution_confirm",
    "resume_active": "develop",
    "exec_plan": "develop",
    "decision_pending": "decision",
    "decision_resume": "decision",
    "compare": "compare",
    "replay": "replay",
    "consult": "consult",
}


def build_runtime_handoff(
    *,
    config: RuntimeConfig,
    decision: RouteDecision,
    run_id: str,
    current_run: RunState | None,
    current_plan: PlanArtifact | None,
    kb_artifact: KbArtifact | None,
    replay_session_dir: str | None,
    skill_result: Mapping[str, Any] | None,
    current_clarification: Any | None,
    current_decision: Any | None,
    notes: Sequence[str],
) -> RuntimeHandoff | None:
    """Build the structured host handoff for an actionable route."""
    handoff_kind = _ROUTE_HANDOFF_KIND.get(decision.route_name)
    if handoff_kind is None:
        return None
    if not _should_emit_handoff(decision=decision, current_run=current_run, current_plan=current_plan):
        return None

    normalized_notes = tuple(note.strip() for note in notes if note and note.strip())
    if not normalized_notes and decision.reason:
        normalized_notes = (decision.reason,)
    finalize_completed = _is_finalize_completed(
        config=config,
        decision=decision,
        current_plan=current_plan,
    )
    required_host_action = _required_host_action(
        decision,
        skill_result_present=bool(skill_result),
        finalize_completed=finalize_completed,
    )
    artifacts = _collect_handoff_artifacts(
        config=config,
        decision=decision,
        current_run=current_run,
        current_plan=current_plan,
        kb_artifact=kb_artifact,
        replay_session_dir=replay_session_dir,
        skill_result=skill_result,
        current_clarification=current_clarification,
        current_decision=current_decision,
        required_host_action=required_host_action,
    )
    guard_reason_code = str(artifacts.get("entry_guard_reason_code") or "").strip()
    if guard_reason_code:
        note = f"entry_guard_reason_code={guard_reason_code}"
        if note not in normalized_notes:
            normalized_notes = (*normalized_notes, note)

    return RuntimeHandoff(
        schema_version=HANDOFF_SCHEMA_VERSION,
        route_name=decision.route_name,
        run_id=run_id,
        plan_id=current_plan.plan_id if current_plan is not None else None,
        plan_path=current_plan.path if current_plan is not None else None,
        handoff_kind=handoff_kind,
        required_host_action=required_host_action,
        recommended_skill_ids=tuple(decision.candidate_skill_ids),
        artifacts=artifacts,
        notes=normalized_notes,
        observability={
            "source": "runtime_handoff",
            "generated_at": _iso_now(),
            "request_excerpt": _summarize_request_text(decision.request_text),
            "request_sha1": _stable_request_sha1(decision.request_text),
            "decision_reason": decision.reason,
            "required_host_action": required_host_action,
        },
    )


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_request_sha1(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    return sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _summarize_request_text(text: str, *, limit: int = 120) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    if limit <= 3:
        return compact[:limit]
    return compact[: limit - 3].rstrip() + "..."


def read_runtime_handoff(path: Path) -> RuntimeHandoff | None:
    """Read a handoff file if it exists."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    return RuntimeHandoff.from_dict(payload)


def write_runtime_handoff(path: Path, handoff: RuntimeHandoff) -> None:
    """Persist a handoff file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        json.dump(handoff.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _required_host_action(
    decision: RouteDecision,
    *,
    skill_result_present: bool,
    finalize_completed: bool = False,
) -> str:
    route_name = decision.route_name
    if route_name == "plan_only":
        return "review_or_execute_plan"
    if route_name in {"workflow", "light_iterate"}:
        return "continue_host_workflow"
    if route_name == "finalize_active":
        return "finalize_completed" if finalize_completed else "review_or_execute_plan"
    if route_name in {"clarification_pending", "clarification_resume"}:
        return "answer_questions"
    if route_name == "execution_confirm_pending":
        if decision.active_run_action == "revise_execution":
            return "review_or_execute_plan"
        return "confirm_execute"
    if route_name in {"resume_active", "exec_plan"}:
        return "continue_host_develop"
    if route_name == "quick_fix":
        return "continue_host_quick_fix"
    if route_name in {"decision_pending", "decision_resume"}:
        return "confirm_decision"
    if route_name == "compare":
        return "review_compare_results" if skill_result_present else "host_compare_bridge_required"
    if route_name == "replay":
        return "host_replay_bridge_required"
    if route_name == "consult":
        return "continue_host_consult"
    return "continue_host_workflow"


def _collect_handoff_artifacts(
    *,
    config: RuntimeConfig,
    decision: RouteDecision,
    current_run: RunState | None,
    current_plan: PlanArtifact | None,
    kb_artifact: KbArtifact | None,
    replay_session_dir: str | None,
    skill_result: Mapping[str, Any] | None,
    current_clarification: Any | None,
    current_decision: Any | None,
    required_host_action: str,
) -> Mapping[str, Any]:
    artifacts: dict[str, Any] = {}
    entry_guard = build_entry_guard_contract(required_host_action=required_host_action)
    artifacts["entry_guard"] = entry_guard
    explicit_guard_reason_code = str(decision.artifacts.get("entry_guard_reason_code") or "").strip()
    guard_reason_code = str(entry_guard.get("reason_code") or "").strip()
    if explicit_guard_reason_code:
        artifacts["entry_guard_reason_code"] = explicit_guard_reason_code
    elif guard_reason_code:
        artifacts["entry_guard_reason_code"] = guard_reason_code
    direct_edit_guard_kind = str(decision.artifacts.get("direct_edit_guard_kind") or "").strip()
    if direct_edit_guard_kind:
        artifacts["direct_edit_guard_kind"] = direct_edit_guard_kind
    direct_edit_guard_trigger = str(decision.artifacts.get("direct_edit_guard_trigger") or "").strip()
    if direct_edit_guard_trigger:
        artifacts["direct_edit_guard_trigger"] = direct_edit_guard_trigger
    execution_summary_payload = None
    if current_run is not None:
        artifacts["run_stage"] = current_run.stage
        if current_run.execution_gate is not None:
            artifacts["execution_gate"] = current_run.execution_gate.to_dict()
    if current_plan is not None and _should_attach_execution_summary(decision=decision, current_run=current_run):
        execution_summary_payload = build_execution_summary(
            plan_artifact=current_plan,
            config=config,
        )
        artifacts["execution_summary"] = execution_summary_payload.to_dict()
    if current_plan is not None and current_plan.files:
        artifacts["plan_files"] = list(current_plan.files)
    if decision.route_name == "finalize_active" and current_plan is not None:
        if _is_plan_archived(config=config, plan_path=current_plan.path):
            artifacts["finalize_status"] = "completed"
            artifacts["archived_plan_path"] = current_plan.path
            artifacts["state_cleared"] = True
        else:
            artifacts["finalize_status"] = "blocked"
            artifacts["active_plan_path"] = current_plan.path
            artifacts["state_cleared"] = False
    if kb_artifact is not None and kb_artifact.files:
        artifacts["kb_files"] = list(kb_artifact.files)
        if decision.route_name == "finalize_active" and artifacts.get("finalize_status") == "completed":
            history_index = next((path for path in kb_artifact.files if path.endswith("history/index.md")), None)
            if history_index:
                artifacts["history_index_path"] = history_index
    if replay_session_dir:
        artifacts["replay_session_dir"] = replay_session_dir
    if skill_result:
        artifacts["skill_result_keys"] = sorted(skill_result.keys())
        if decision.route_name == "compare":
            compare_contract = build_compare_decision_contract(
                question=decision.request_text,
                skill_result=skill_result,
                language=config.language,
            )
            if compare_contract is not None:
                artifacts["compare_decision_contract"] = compare_contract
        tradeoff_signal = has_tradeoff_checkpoint_signal(skill_result)
        raw_checkpoint_request = skill_result.get("checkpoint_request")
        if isinstance(raw_checkpoint_request, Mapping):
            try:
                normalized_request = normalize_checkpoint_request(raw_checkpoint_request)
                artifacts["checkpoint_request"] = normalized_request.to_dict()
                _attach_resume_context_artifacts(
                    artifacts,
                    resume_context=normalized_request.resume_context,
                    phase=normalized_request.source_stage,
                )
            except ValueError:
                # Keep the handoff stable even when a skill emits malformed data.
                error_code = "invalid_skill_checkpoint_request"
                if tradeoff_signal:
                    error_code = CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED
                    artifacts["checkpoint_request_reason_code"] = CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED
                artifacts["checkpoint_request_error"] = error_code
        elif tradeoff_signal:
            artifacts["checkpoint_request_error"] = CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED
            artifacts["checkpoint_request_reason_code"] = CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED
    if current_clarification is not None:
        artifacts["clarification_file"] = CURRENT_CLARIFICATION_RELATIVE_PATH
        artifacts["clarification_id"] = getattr(current_clarification, "clarification_id", None)
        artifacts["clarification_status"] = getattr(current_clarification, "status", None)
        artifacts["missing_facts"] = list(getattr(current_clarification, "missing_facts", ()))
        artifacts["questions"] = list(getattr(current_clarification, "questions", ()))
        artifacts["clarification_form"] = build_scope_clarification_form(
            current_clarification,
            language=config.language,
        )
        artifacts["clarification_submission_state"] = clarification_submission_state_payload(current_clarification)
        artifacts["checkpoint_request"] = checkpoint_request_from_clarification_state(
            current_clarification,
            config=config,
            source_route=decision.route_name,
        ).to_dict()
        _attach_resume_context_artifacts(
            artifacts,
            resume_context=getattr(current_clarification, "resume_context", None),
            phase=getattr(current_clarification, "phase", None),
        )
    if current_decision is not None:
        artifacts["decision_file"] = CURRENT_DECISION_RELATIVE_PATH
        artifacts["decision_id"] = getattr(current_decision, "decision_id", None)
        artifacts["decision_status"] = getattr(current_decision, "status", None)
        artifacts["decision_option_ids"] = [getattr(option, "option_id", "") for option in getattr(current_decision, "options", ())]
        artifacts["recommended_option_id"] = getattr(current_decision, "recommended_option_id", None)
        artifacts["decision_primary_field_id"] = getattr(current_decision, "primary_field_id", None)
        artifacts["selected_option_id"] = getattr(current_decision, "selected_option_id", None)
        artifacts["decision_policy_id"] = getattr(current_decision, "policy_id", None)
        artifacts["decision_trigger_reason"] = getattr(current_decision, "trigger_reason", None)
        checkpoint = getattr(current_decision, "active_checkpoint", None)
        if checkpoint is not None and hasattr(checkpoint, "to_dict"):
            artifacts["decision_checkpoint"] = checkpoint.to_dict()
        artifacts["decision_submission_state"] = _decision_submission_state(current_decision)
        artifacts["checkpoint_request"] = checkpoint_request_from_decision_state(
            current_decision,
            source_route=decision.route_name,
        ).to_dict()
        _attach_resume_context_artifacts(
            artifacts,
            resume_context=getattr(current_decision, "resume_context", None),
            phase=getattr(current_decision, "phase", None),
        )
    elif decision.route_name == "execution_confirm_pending" and current_plan is not None and execution_summary_payload is not None:
        artifacts["checkpoint_request"] = checkpoint_request_from_execution_confirm(
            config=config,
            decision=decision,
            current_plan=current_plan,
        ).to_dict()
    if decision.route_name == "execution_confirm_pending" and decision.active_run_action == "revise_execution":
        artifacts["execution_feedback"] = decision.request_text.strip()
    return artifacts


def _decision_submission_state(current_decision: Any) -> Mapping[str, Any]:
    submission = getattr(current_decision, "submission", None)
    if submission is None:
        return {
            "status": "empty",
            "source": None,
            "resume_action": None,
            "submitted_at": None,
            "has_answers": False,
            "answer_keys": [],
        }

    answers = getattr(submission, "answers", {})
    answer_keys = sorted(str(key) for key in answers.keys()) if isinstance(answers, Mapping) else []
    payload: dict[str, Any] = {
        "status": getattr(submission, "status", "empty"),
        "source": getattr(submission, "source", None),
        "resume_action": getattr(submission, "resume_action", None),
        "submitted_at": getattr(submission, "submitted_at", None),
        "has_answers": bool(answer_keys),
        "answer_keys": answer_keys,
    }
    message = str(getattr(submission, "message", "") or "").strip()
    if message:
        payload["message"] = message
    return payload


def _attach_resume_context_artifacts(
    artifacts: dict[str, Any],
    *,
    resume_context: Any,
    phase: Any,
) -> None:
    if not isinstance(resume_context, Mapping) or not resume_context:
        return
    normalized = dict(resume_context)
    artifacts["resume_context"] = normalized
    if str(phase or "").strip() == "develop":
        artifacts["develop_resume_context"] = normalized


def _should_attach_execution_summary(*, decision: RouteDecision, current_run: RunState | None) -> bool:
    if decision.route_name == "execution_confirm_pending":
        return True
    if current_run is None:
        return False
    if current_run.stage in {"ready_for_execution", "execution_confirm_pending", "executing"}:
        return True
    execution_gate = current_run.execution_gate
    return execution_gate is not None and execution_gate.gate_status == "ready"


def _should_emit_handoff(*, decision: RouteDecision, current_run: RunState | None, current_plan: PlanArtifact | None) -> bool:
    if decision.route_name == "finalize_active":
        return current_plan is not None
    if decision.route_name != "exec_plan":
        return True
    # ~go exec is an advanced recovery/debug entry; when it does not converge
    # back into the standard checkpoints, avoid emitting a misleading develop handoff.
    return False


def _is_finalize_completed(*, config: RuntimeConfig, decision: RouteDecision, current_plan: PlanArtifact | None) -> bool:
    if decision.route_name != "finalize_active" or current_plan is None:
        return False
    return _is_plan_archived(config=config, plan_path=current_plan.path)


def _is_plan_archived(*, config: RuntimeConfig, plan_path: str) -> bool:
    history_prefix = f"{config.plan_directory}/history/"
    return str(plan_path or "").startswith(history_prefix)
