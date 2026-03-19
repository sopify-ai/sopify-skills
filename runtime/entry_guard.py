"""Shared entry-guard contracts for host/runtime checkpoint loops."""

from __future__ import annotations

from typing import Any

DEFAULT_RUNTIME_ENTRY = "scripts/sopify_runtime.py"
PLAN_ONLY_HELPER_ENTRY = "scripts/go_plan_runtime.py"
CLARIFICATION_BRIDGE_ENTRY = "scripts/clarification_bridge_runtime.py"
DECISION_BRIDGE_ENTRY = "scripts/decision_bridge_runtime.py"
DEVELOP_CHECKPOINT_ENTRY = "scripts/develop_checkpoint_runtime.py"

ENTRY_GUARD_SCHEMA_VERSION = "1"
ENTRY_GUARD_PENDING_ACTIONS = ("answer_questions", "confirm_decision", "confirm_execute")
ENTRY_GUARD_BYPASS_BLOCKED_COMMANDS = ("~go exec",)
ENTRY_GUARD_DEVELOP_CALLBACK_REASON_CODE = "develop_checkpoint_callback_required"
DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE = "direct_edit_blocked_runtime_required"
ENTRY_GUARD_REASON_CODES = {
    "answer_questions": "entry_guard_clarification_pending",
    "confirm_decision": "entry_guard_decision_pending",
    "confirm_execute": "entry_guard_execution_confirm_pending",
}

DECISION_BRIDGE_HANDOFF_MISMATCH_REASON = "decision_bridge_handoff_mismatch"
CLARIFICATION_BRIDGE_HANDOFF_MISMATCH_REASON = "clarification_bridge_handoff_mismatch"


def entry_guard_reason_code(required_host_action: str) -> str | None:
    """Return the normalized reason code for pending checkpoint guard actions."""
    return ENTRY_GUARD_REASON_CODES.get(str(required_host_action or "").strip())


def build_entry_guard_contract(*, required_host_action: str) -> dict[str, Any]:
    """Build a machine-readable host guard contract for this handoff action."""
    normalized_action = str(required_host_action or "").strip()
    reason_code = entry_guard_reason_code(normalized_action)
    pending_fail_closed = normalized_action in ENTRY_GUARD_PENDING_ACTIONS
    return {
        "schema_version": ENTRY_GUARD_SCHEMA_VERSION,
        "strict_runtime_entry": True,
        "default_runtime_entry": DEFAULT_RUNTIME_ENTRY,
        "plan_only_helper_entry": PLAN_ONLY_HELPER_ENTRY,
        "pending_checkpoint_actions": list(ENTRY_GUARD_PENDING_ACTIONS),
        "required_host_action": normalized_action,
        "pending_checkpoint_fail_closed": pending_fail_closed,
        "reason_code": reason_code,
        "bypass_blocked_commands": list(ENTRY_GUARD_BYPASS_BLOCKED_COMMANDS) if pending_fail_closed else [],
        "develop_checkpoint_callback": {
            "required_host_action": "continue_host_develop",
            "required_on_user_branch": True,
            "entry": DEVELOP_CHECKPOINT_ENTRY,
            "reason_code": ENTRY_GUARD_DEVELOP_CALLBACK_REASON_CODE,
        },
    }
