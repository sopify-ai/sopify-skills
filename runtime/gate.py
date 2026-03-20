"""Prompt-level runtime gate for strict Sopify ingress."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping

from .config import ConfigError, load_runtime_config
from .engine import run_runtime
from .entry_guard import ENTRY_GUARD_PENDING_ACTIONS
from .preferences import PreferencesPreloadResult, preload_preferences
from .state import StateStore
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
    user_home: Path | None = None,
    write_receipt: bool = True,
) -> dict[str, Any]:
    """Run the prompt-level gate and return the compact host-facing contract."""

    workspace = Path(workspace_root).resolve()
    contract = _base_contract(workspace)
    config = None

    try:
        request = str(raw_request or "").strip()
        if not request:
            raise ValueError("Runtime gate request cannot be empty")

        contract["preflight"] = dict(
            preflight_workspace_runtime(
                workspace,
                payload_manifest_path=payload_manifest_path,
            )
        )
        config = load_runtime_config(workspace, global_config_path=global_config_path)
        contract["preferences"] = _normalize_preferences(preload_preferences(config))

        runtime_result = run_runtime(
            request,
            workspace_root=workspace,
            global_config_path=global_config_path,
            user_home=user_home,
        )
        contract["runtime"] = {
            "route_name": runtime_result.route.route_name,
            "reason": runtime_result.route.reason,
        }

        store = StateStore(config)
        persisted_handoff = store.get_current_handoff()
        # Normalize from the in-memory runtime result when needed, but keep
        # persisted handoff as the only positive machine evidence.
        handoff_source = persisted_handoff or runtime_result.handoff
        contract["handoff"] = _normalize_handoff(handoff_source)

        manifest_path = workspace / ".sopify-runtime" / "manifest.json"
        strict_runtime_entry = bool(contract["handoff"].pop("_strict_runtime_entry", False))
        contract["evidence"] = {
            "manifest_found": manifest_path.is_file(),
            "handoff_found": persisted_handoff is not None,
            "strict_runtime_entry": strict_runtime_entry,
        }

        if not contract["handoff"]:
            contract.update(
                {
                    "status": "error",
                    "gate_passed": False,
                    "allowed_response_mode": ERROR_VISIBLE_RETRY,
                    "error_code": "handoff_missing",
                    "message": "Runtime gate could not confirm a structured handoff.",
                }
            )
        elif not strict_runtime_entry:
            contract.update(
                {
                    "status": "error",
                    "gate_passed": False,
                    "allowed_response_mode": ERROR_VISIBLE_RETRY,
                    "error_code": "strict_runtime_entry_missing",
                    "message": "Runtime gate is missing strict entry evidence from handoff.entry_guard.",
                }
            )
        else:
            required_host_action = str(contract["handoff"].get("required_host_action") or "").strip()
            allowed_response_mode = NORMAL_RUNTIME_FOLLOWUP
            if required_host_action in CHECKPOINT_ONLY_ACTIONS:
                allowed_response_mode = CHECKPOINT_ONLY
            contract.update(
                {
                    "status": "ready",
                    "gate_passed": True,
                    "allowed_response_mode": allowed_response_mode,
                }
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

    if config is not None and write_receipt:
        receipt_path = config.state_dir / CURRENT_GATE_RECEIPT_FILENAME
        contract["receipt_path"] = str(receipt_path)
        _write_receipt(receipt_path, contract)
    return contract


def _base_contract(workspace_root: Path) -> dict[str, Any]:
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": "error",
        "gate_passed": False,
        "workspace_root": str(workspace_root),
        "preflight": {},
        "preferences": {
            "status": "missing",
            "injected": False,
        },
        "runtime": {},
        "handoff": {},
        "allowed_response_mode": ERROR_VISIBLE_RETRY,
        "evidence": {
            "manifest_found": False,
            "handoff_found": False,
            "strict_runtime_entry": False,
        },
    }


def _normalize_preferences(result: PreferencesPreloadResult) -> dict[str, Any]:
    payload = {
        "status": result.status,
        "injected": result.injected,
        "preferences_path": result.preferences_path,
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
    if not pending_fail_closed and required_host_action in CHECKPOINT_ONLY_ACTIONS:
        pending_fail_closed = True
    payload = {
        "required_host_action": required_host_action,
        "pending_fail_closed": pending_fail_closed,
        "_strict_runtime_entry": bool(entry_guard.get("strict_runtime_entry", False)),
    }
    if reason_code:
        payload["entry_guard_reason_code"] = reason_code
    return payload


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
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
]
