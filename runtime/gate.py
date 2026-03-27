"""Prompt-level runtime gate for strict Sopify ingress."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
from uuid import uuid4

from .config import ConfigError, load_runtime_config
from .engine import run_runtime
from .entry_guard import ENTRY_GUARD_PENDING_ACTIONS
from .preferences import PreferencesPreloadResult, preload_preferences
from .state import StateStore, cleanup_expired_session_state, iso_now, normalize_session_id, stable_request_sha1, summarize_request_text
from .workspace_preflight import WorkspacePreflightError, preflight_workspace_runtime

GATE_SCHEMA_VERSION = "1"
CURRENT_GATE_RECEIPT_FILENAME = "current_gate_receipt.json"
CHECKPOINT_ONLY_ACTIONS = frozenset(ENTRY_GUARD_PENDING_ACTIONS)
NORMAL_RUNTIME_FOLLOWUP = "normal_runtime_followup"
CHECKPOINT_ONLY = "checkpoint_only"
ERROR_VISIBLE_RETRY = "error_visible_retry"


def enter_runtime_gate(
    raw_request: str,
    *,
    workspace_root: str | Path = ".",
    global_config_path: str | Path | None = None,
    payload_manifest_path: str | Path | None = None,
    session_id: str | None = None,
    user_home: Path | None = None,
    write_receipt: bool = True,
) -> dict[str, Any]:
    """Run the prompt-level gate and return the compact host-facing contract."""

    workspace = Path(workspace_root).resolve()
    contract = _base_contract(workspace)
    config = None
    request = str(raw_request or "").strip()

    try:
        if not request:
            raise ValueError("Runtime gate request cannot be empty")

        contract["preflight"] = dict(
            preflight_workspace_runtime(
                workspace,
                payload_manifest_path=payload_manifest_path,
            )
        )
        config = load_runtime_config(workspace, global_config_path=global_config_path)
        resolved_session_id = _resolve_session_id(session_id)
        cleaned_session_dirs = cleanup_expired_session_state(config)
        contract["session_id"] = resolved_session_id
        contract["preferences"] = _normalize_preferences(preload_preferences(config))

        runtime_result = run_runtime(
            request,
            workspace_root=workspace,
            global_config_path=global_config_path,
            session_id=resolved_session_id,
            user_home=user_home,
        )
        contract["runtime"] = {
            "route_name": runtime_result.route.route_name,
            "reason": runtime_result.route.reason,
        }

        store = _store_for_route(
            config=config,
            route_name=runtime_result.route.route_name,
            session_id=resolved_session_id,
        )
        persisted_handoff = store.get_current_handoff()
        current_run = store.get_current_run()
        # Normalize from the in-memory runtime result when needed, but keep
        # persisted handoff as the only positive machine evidence.
        handoff_source = persisted_handoff or runtime_result.handoff
        contract["handoff"] = _normalize_handoff(handoff_source)
        contract["trigger_evidence"] = contract["handoff"].pop("_trigger_evidence", {})

        manifest_path = workspace / ".sopify-runtime" / "manifest.json"
        strict_runtime_entry = bool(contract["handoff"].pop("_strict_runtime_entry", False))
        handoff_source_kind = _handoff_source_kind(persisted_handoff=persisted_handoff, runtime_handoff=runtime_result.handoff)
        persisted_matches_current = _persisted_handoff_matches_current_request(
            persisted_handoff=persisted_handoff,
            runtime_handoff=runtime_result.handoff,
            request_sha1=stable_request_sha1(request),
        )
        contract["evidence"] = {
            "manifest_found": manifest_path.is_file(),
            "handoff_found": persisted_handoff is not None,
            "strict_runtime_entry": strict_runtime_entry,
            "handoff_source_kind": handoff_source_kind,
            "current_request_produced_handoff": runtime_result.handoff is not None,
            "persisted_handoff_matches_current_request": persisted_matches_current,
        }
        contract["observability"] = _build_gate_observability(
            request=request,
            runtime_route=runtime_result.route.route_name,
            persisted_handoff=persisted_handoff,
            runtime_handoff=runtime_result.handoff,
            current_run=current_run,
            ingress_mode="runtime_gate_enter",
            session_id=resolved_session_id,
            cleaned_session_dirs=cleaned_session_dirs,
        )
        contract["state"] = _build_state_contract(store=store)
        contract.update(
            _evaluate_gate_evidence(
                handoff=contract["handoff"],
                handoff_source_kind=handoff_source_kind,
                strict_runtime_entry=strict_runtime_entry,
            )
        )
    except (ConfigError, ValueError, WorkspacePreflightError) as exc:
        contract.update(
            {
                "status": "error",
                "gate_passed": False,
                "allowed_response_mode": ERROR_VISIBLE_RETRY,
                "error_code": _error_code_for_exception(exc),
                "message": str(exc),
            }
        )
    except Exception as exc:  # pragma: no cover - defensive guard for CLI/runtime use
        contract.update(
            {
                "status": "error",
                "gate_passed": False,
                "allowed_response_mode": ERROR_VISIBLE_RETRY,
                "error_code": "runtime_gate_unexpected_error",
                "message": str(exc),
            }
        )

    if config is not None:
        receipt_path = config.state_dir / CURRENT_GATE_RECEIPT_FILENAME
        observability = contract.get("observability")
        if not isinstance(observability, dict):
            observability = {}
            contract["observability"] = observability
        observability["previous_receipt"] = _read_previous_receipt(
            receipt_path=receipt_path,
            request_sha1=stable_request_sha1(request),
            runtime_route_name=str(contract.get("runtime", {}).get("route_name") or ""),
        )
        if write_receipt:
            contract["receipt_path"] = str(receipt_path)
            write_gate_receipt(receipt_path, contract)
    return contract


def _base_contract(workspace_root: Path) -> dict[str, Any]:
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": "error",
        "gate_passed": False,
        "workspace_root": str(workspace_root),
        "session_id": None,
        "preflight": {},
        "preferences": {
            "status": "missing",
            "injected": False,
        },
        "runtime": {},
        "handoff": {},
        "state": {},
        "trigger_evidence": {},
        "observability": {},
        "allowed_response_mode": ERROR_VISIBLE_RETRY,
        "evidence": {
            "manifest_found": False,
            "handoff_found": False,
            "strict_runtime_entry": False,
            "handoff_source_kind": "missing",
            "current_request_produced_handoff": False,
            "persisted_handoff_matches_current_request": False,
        },
    }


def _normalize_preferences(result: PreferencesPreloadResult) -> dict[str, Any]:
    payload = {
        "status": result.status,
        "injected": result.injected,
        "preferences_path": result.preferences_path,
        "feedback_path": result.feedback_path,
        "feedback_present": result.feedback_present,
        "plan_directory": result.plan_directory,
    }
    if result.error_code:
        payload["error_code"] = result.error_code
    if result.injected and result.injection_text:
        payload["injection_text"] = result.injection_text
    return payload


def _normalize_handoff(handoff: Any) -> dict[str, Any]:
    if handoff is None or not hasattr(handoff, "artifacts"):
        return {}
    artifacts = getattr(handoff, "artifacts", {})
    if not isinstance(artifacts, Mapping):
        artifacts = {}
    entry_guard = artifacts.get("entry_guard")
    if not isinstance(entry_guard, Mapping):
        entry_guard = {}
    reason_code = str(artifacts.get("entry_guard_reason_code") or entry_guard.get("reason_code") or "").strip()
    pending_fail_closed = bool(entry_guard.get("pending_checkpoint_fail_closed", False))
    required_host_action = str(getattr(handoff, "required_host_action", "") or "").strip()
    direct_edit_guard_kind = str(artifacts.get("direct_edit_guard_kind") or "").strip()
    direct_edit_guard_trigger = str(artifacts.get("direct_edit_guard_trigger") or "").strip()
    consult_override_reason_code = str(artifacts.get("consult_override_reason_code") or "").strip()
    if not pending_fail_closed and required_host_action in CHECKPOINT_ONLY_ACTIONS:
        pending_fail_closed = True
    payload = {
        "required_host_action": required_host_action,
        "pending_fail_closed": pending_fail_closed,
        "_strict_runtime_entry": bool(entry_guard.get("strict_runtime_entry", False)),
    }
    trigger_evidence: dict[str, Any] = {}
    if reason_code:
        payload["entry_guard_reason_code"] = reason_code
        trigger_evidence["entry_guard_reason_code"] = reason_code
    if direct_edit_guard_kind:
        trigger_evidence["direct_edit_guard_kind"] = direct_edit_guard_kind
    if direct_edit_guard_trigger:
        trigger_evidence["direct_edit_guard_trigger"] = direct_edit_guard_trigger
    if consult_override_reason_code:
        payload["consult_override_reason_code"] = consult_override_reason_code
        trigger_evidence["consult_override_reason_code"] = consult_override_reason_code
    if trigger_evidence:
        payload["_trigger_evidence"] = trigger_evidence
    return payload


def _evaluate_gate_evidence(
    *,
    handoff: Mapping[str, Any],
    handoff_source_kind: str,
    strict_runtime_entry: bool,
) -> dict[str, Any]:
    normalized_valid = bool(handoff)
    if not normalized_valid:
        if handoff_source_kind == "missing":
            return {
                "status": "error",
                "gate_passed": False,
                "allowed_response_mode": ERROR_VISIBLE_RETRY,
                "error_code": "handoff_missing",
                "message": "Runtime gate could not confirm a structured handoff.",
            }
        return {
            "status": "error",
            "gate_passed": False,
            "allowed_response_mode": ERROR_VISIBLE_RETRY,
            "error_code": "handoff_normalize_failed",
            "message": "Runtime gate found a handoff candidate but could not normalize it into the host contract.",
        }

    if not strict_runtime_entry:
        return {
            "status": "error",
            "gate_passed": False,
            "allowed_response_mode": ERROR_VISIBLE_RETRY,
            "error_code": "strict_runtime_entry_missing",
            "message": "Runtime gate is missing strict entry evidence from handoff.entry_guard.",
        }

    if handoff_source_kind == "current_request_not_persisted":
        return {
            "status": "error",
            "gate_passed": False,
            "allowed_response_mode": ERROR_VISIBLE_RETRY,
            "error_code": "current_request_not_persisted",
            "message": "Runtime gate found a current-request handoff, but it was not persisted to state.",
        }

    if handoff_source_kind == "persisted_runtime_mismatch":
        return {
            "status": "error",
            "gate_passed": False,
            "allowed_response_mode": ERROR_VISIBLE_RETRY,
            "error_code": "persisted_runtime_mismatch",
            "message": "Runtime gate found a persisted handoff, but it does not match the current runtime result.",
        }

    required_host_action = str(handoff.get("required_host_action") or "").strip()
    allowed_response_mode = NORMAL_RUNTIME_FOLLOWUP
    if required_host_action in CHECKPOINT_ONLY_ACTIONS:
        allowed_response_mode = CHECKPOINT_ONLY
    return {
        "status": "ready",
        "gate_passed": True,
        "allowed_response_mode": allowed_response_mode,
    }


def _handoff_source_kind(*, persisted_handoff: Any, runtime_handoff: Any) -> str:
    if persisted_handoff is None and runtime_handoff is None:
        return "missing"
    if persisted_handoff is None and runtime_handoff is not None:
        return "current_request_not_persisted"
    if persisted_handoff is not None and runtime_handoff is None:
        return "reused_prior_state"
    if getattr(persisted_handoff, "run_id", "") == getattr(runtime_handoff, "run_id", ""):
        return "current_request_persisted"
    return "persisted_runtime_mismatch"


def _persisted_handoff_matches_current_request(*, persisted_handoff: Any, runtime_handoff: Any, request_sha1: str) -> bool:
    if persisted_handoff is None:
        return False
    if runtime_handoff is not None:
        return getattr(persisted_handoff, "run_id", "") == getattr(runtime_handoff, "run_id", "")
    observability = getattr(persisted_handoff, "observability", {})
    if not isinstance(observability, Mapping):
        return False
    return str(observability.get("request_sha1") or "") == request_sha1 and bool(request_sha1)


def _build_gate_observability(
    *,
    request: str,
    runtime_route: str,
    persisted_handoff: Any,
    runtime_handoff: Any,
    current_run: Any,
    ingress_mode: str,
    session_id: str,
    cleaned_session_dirs: tuple[str, ...],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "receipt_kind": "runtime_gate",
        "ingress_mode": ingress_mode,
        "written_at": iso_now(),
        "session_id": session_id,
        "request_excerpt": summarize_request_text(request),
        "request_sha1": stable_request_sha1(request),
        "runtime_route_name": runtime_route,
        "handoff_source_kind": _handoff_source_kind(persisted_handoff=persisted_handoff, runtime_handoff=runtime_handoff),
    }
    if cleaned_session_dirs:
        payload["cleaned_session_dirs"] = list(cleaned_session_dirs)
    if current_run is not None:
        payload["current_run"] = {
            "run_id": getattr(current_run, "run_id", ""),
            "route_name": getattr(current_run, "route_name", ""),
            "stage": getattr(current_run, "stage", ""),
            "updated_at": getattr(current_run, "updated_at", ""),
            "request_excerpt": getattr(current_run, "request_excerpt", ""),
            "request_sha1": getattr(current_run, "request_sha1", ""),
        }
    if persisted_handoff is not None:
        handoff_observability = getattr(persisted_handoff, "observability", {})
        if not isinstance(handoff_observability, Mapping):
            handoff_observability = {}
        payload["persisted_handoff"] = {
            "run_id": getattr(persisted_handoff, "run_id", ""),
            "route_name": getattr(persisted_handoff, "route_name", ""),
            "required_host_action": getattr(persisted_handoff, "required_host_action", ""),
            "generated_at": str(handoff_observability.get("generated_at") or ""),
            "written_at": str(handoff_observability.get("written_at") or ""),
            "request_excerpt": str(handoff_observability.get("request_excerpt") or ""),
            "request_sha1": str(handoff_observability.get("request_sha1") or ""),
        }
    if runtime_handoff is not None:
        payload["current_request_handoff"] = {
            "run_id": getattr(runtime_handoff, "run_id", ""),
            "route_name": getattr(runtime_handoff, "route_name", ""),
            "required_host_action": getattr(runtime_handoff, "required_host_action", ""),
        }
    return payload


def _read_previous_receipt(*, receipt_path: Path, request_sha1: str, runtime_route_name: str) -> dict[str, Any]:
    missing_payload = {
        "exists": False,
        "written_at": None,
        "request_sha1_match": None,
        "route_name_match": None,
        "stale_reason": None,
    }
    if not receipt_path.exists():
        return missing_payload

    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "exists": True,
            "written_at": None,
            "request_sha1_match": None,
            "route_name_match": None,
            "stale_reason": "parse_error",
        }

    if not isinstance(payload, Mapping):
        return {
            "exists": True,
            "written_at": None,
            "request_sha1_match": None,
            "route_name_match": None,
            "stale_reason": "parse_error",
        }

    observability = payload.get("observability")
    if not isinstance(observability, Mapping):
        observability = {}
    previous_runtime = payload.get("runtime")
    if not isinstance(previous_runtime, Mapping):
        previous_runtime = {}

    previous_request_sha1 = str(observability.get("request_sha1") or "")
    previous_route_name = str(observability.get("runtime_route_name") or previous_runtime.get("route_name") or "")
    request_sha1_match = bool(previous_request_sha1 and request_sha1 and previous_request_sha1 == request_sha1)
    route_name_match = bool(previous_route_name and runtime_route_name and previous_route_name == runtime_route_name)
    return {
        "exists": True,
        "written_at": str(observability.get("written_at") or "") or None,
        "request_sha1_match": request_sha1_match,
        "route_name_match": route_name_match,
        "stale_reason": _previous_receipt_stale_reason(
            request_sha1_match=request_sha1_match,
            route_name_match=route_name_match,
        ),
    }


def _previous_receipt_stale_reason(*, request_sha1_match: bool, route_name_match: bool) -> str:
    if request_sha1_match and route_name_match:
        return "not_stale"
    if request_sha1_match:
        return "route_name_mismatch"
    if route_name_match:
        return "request_sha1_mismatch"
    return "both_mismatch"


def _build_state_contract(*, store: StateStore) -> dict[str, Any]:
    return {
        "scope": store.scope,
        "state_root": store.relative_path(store.root),
        "current_plan_path": store.relative_path(store.current_plan_path),
        "current_plan_proposal_path": store.relative_path(store.current_plan_proposal_path),
        "current_run_path": store.relative_path(store.current_run_path),
        "current_handoff_path": store.relative_path(store.current_handoff_path),
        "current_clarification_path": store.relative_path(store.current_clarification_path),
        "current_decision_path": store.relative_path(store.current_decision_path),
        "last_route_path": store.relative_path(store.last_route_path),
    }


def _resolve_session_id(session_id: str | None) -> str:
    normalized = normalize_session_id(session_id)
    if normalized:
        return normalized
    return f"session-{uuid4().hex[:12]}"


def _store_for_route(
    *,
    config,
    route_name: str,
    session_id: str,
) -> StateStore:
    if route_name in {"execution_confirm_pending", "resume_active", "exec_plan", "finalize_active"}:
        return StateStore(config)
    return StateStore(config, session_id=session_id)


def write_gate_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _error_code_for_exception(exc: Exception) -> str:
    if isinstance(exc, WorkspacePreflightError):
        return "workspace_preflight_failed"
    if isinstance(exc, ConfigError):
        return "config_error"
    if isinstance(exc, ValueError):
        return "invalid_request"
    return "runtime_gate_error"


__all__ = [
    "CHECKPOINT_ONLY",
    "CURRENT_GATE_RECEIPT_FILENAME",
    "ERROR_VISIBLE_RETRY",
    "GATE_SCHEMA_VERSION",
    "NORMAL_RUNTIME_FOLLOWUP",
    "enter_runtime_gate",
    "write_gate_receipt",
]
