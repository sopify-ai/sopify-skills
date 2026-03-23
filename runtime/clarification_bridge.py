"""Host bridge helpers for lightweight clarification forms.

The default runtime entry stays unchanged. Hosts may optionally use these
helpers when `required_host_action == answer_questions` to:

1. read a stable clarification form contract,
2. collect missing planning facts with native UI, and
3. write the normalized response back into `current_clarification.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .cli_interactive import (
    CLI_RENDERER_INTERACTIVE,
    CliInteractiveError,
    InteractiveSessionFactory,
    resolve_cli_renderer,
)
from .clarification import (
    build_scope_clarification_form,
    clarification_submission_state_payload,
    normalize_clarification_answers,
    render_clarification_response_text,
)
from .entry_guard import (
    CLARIFICATION_BRIDGE_ENTRY as ENTRY_GUARD_CLARIFICATION_BRIDGE_ENTRY,
    CLARIFICATION_BRIDGE_HANDOFF_MISMATCH_REASON,
    DEFAULT_RUNTIME_ENTRY as ENTRY_GUARD_DEFAULT_RUNTIME_ENTRY,
)
from .models import ClarificationState, RuntimeConfig, RuntimeHandoff
from .state import StateStore

BRIDGE_SCHEMA_VERSION = "1"
DEFAULT_RUNTIME_ENTRY = ENTRY_GUARD_DEFAULT_RUNTIME_ENTRY
CLARIFICATION_BRIDGE_ENTRY = ENTRY_GUARD_CLARIFICATION_BRIDGE_ENTRY

PromptReader = Callable[[str], str]
PromptWriter = Callable[[str], None]


class ClarificationBridgeError(ValueError):
    """Raised when a host bridge cannot safely inspect or submit clarification answers."""


@dataclass(frozen=True)
class ClarificationBridgeContext:
    """Resolved host-bridge context for the active clarification."""

    state_store: StateStore
    handoff: RuntimeHandoff | None
    clarification_state: ClarificationState
    clarification_form: Mapping[str, Any]
    submission_state: Mapping[str, Any]


def load_clarification_bridge_context(
    *,
    config: RuntimeConfig,
    session_id: str | None = None,
) -> ClarificationBridgeContext:
    """Load the active clarification plus the host-facing handoff snapshot."""
    state_store = _resolve_clarification_state_store(config=config, session_id=session_id)
    clarification_state = state_store.get_current_clarification()
    if clarification_state is None:
        raise ClarificationBridgeError("No active clarification checkpoint was found")
    if clarification_state.status in {"stale"}:
        raise ClarificationBridgeError(f"Clarification checkpoint is no longer actionable: {clarification_state.status}")

    handoff = state_store.get_current_handoff()
    _validate_clarification_handoff(handoff=handoff, clarification_state=clarification_state)
    clarification_form = _resolve_clarification_form(
        handoff=handoff,
        clarification_state=clarification_state,
        language=config.language,
    )
    submission_state = _resolve_submission_state(handoff=handoff, clarification_state=clarification_state)
    return ClarificationBridgeContext(
        state_store=state_store,
        handoff=handoff,
        clarification_state=clarification_state,
        clarification_form=clarification_form,
        submission_state=submission_state,
    )


def build_cli_clarification_bridge(context: ClarificationBridgeContext, *, language: str) -> Mapping[str, Any]:
    """Build a CLI clarification bridge contract with interactive and text modes."""
    steps = tuple(_build_cli_step(field) for field in context.clarification_form.get("fields", ()))
    return _bridge_payload(
        context=context,
        steps=steps,
        language=language,
    )


def build_clarification_submission(
    clarification_state: ClarificationState,
    *,
    answers: Mapping[str, Any],
    source: str,
    language: str,
    message: str = "",
) -> Mapping[str, Any]:
    """Validate and normalize host answers into a clarification submission payload."""
    normalized_answers = normalize_clarification_answers(clarification_state, answers)
    response_text = render_clarification_response_text(
        clarification_state,
        answers=normalized_answers,
        language=language,
    )
    return {
        "response_text": response_text,
        "response_fields": dict(normalized_answers),
        "response_source": source,
        "response_message": message,
    }


def write_clarification_submission(
    *,
    config: RuntimeConfig,
    submission: Mapping[str, Any],
    session_id: str | None = None,
) -> ClarificationState:
    """Write a validated clarification response into the resolved clarification state file."""
    state_store = _resolve_clarification_state_store(config=config, session_id=session_id)
    updated = state_store.set_current_clarification_response(
        response_text=str(submission.get("response_text") or "").strip(),
        response_fields=submission.get("response_fields") if isinstance(submission.get("response_fields"), Mapping) else {},
        response_source=str(submission.get("response_source") or "").strip() or None,
        response_message=str(submission.get("response_message") or "").strip(),
    )
    if updated is None:
        raise ClarificationBridgeError("No active clarification checkpoint was found while writing submission")
    return updated


def prompt_cli_clarification_submission(
    *,
    config: RuntimeConfig,
    session_id: str | None = None,
    renderer: str = "auto",
    input_reader: PromptReader = input,
    output_writer: PromptWriter = print,
    interactive_session_factory: InteractiveSessionFactory | None = None,
) -> tuple[Mapping[str, Any], str]:
    """Collect clarification answers through the CLI interactive renderer or text fallback."""
    context = load_clarification_bridge_context(config=config, session_id=session_id)
    try:
        used_renderer, _interactive_session = resolve_cli_renderer(
            renderer=renderer,
            session_factory=interactive_session_factory,
        )
    except CliInteractiveError as exc:
        raise ClarificationBridgeError(str(exc)) from exc
    if used_renderer != CLI_RENDERER_INTERACTIVE and (renderer or "").strip().casefold() in {"interactive", "inquirer"}:
        output_writer(_message(config.language, "cli_interactive_fallback"))

    answers: dict[str, Any] = {}
    for field in context.clarification_form.get("fields", ()):
        field_id = str(field["field_id"])
        if str(field.get("field_type") or "input") == "textarea":
            answers[field_id] = _prompt_cli_textarea(field, language=config.language, input_reader=input_reader, output_writer=output_writer)
        else:
            answers[field_id] = _prompt_cli_input(field, language=config.language, input_reader=input_reader, output_writer=output_writer)

    submission = build_clarification_submission(
        context.clarification_state,
        answers=answers,
        source=f"cli_{used_renderer}",
        language=config.language,
        message=_message(config.language, "cli_submission_message"),
    )
    write_clarification_submission(config=config, submission=submission, session_id=session_id)
    return submission, used_renderer


def _bridge_payload(
    *,
    context: ClarificationBridgeContext,
    steps: tuple[Mapping[str, Any], ...],
    language: str,
) -> Mapping[str, Any]:
    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "bridge_status": "ready",
        "host_kind": "cli",
        "required_host_action": "answer_questions",
        "default_runtime_entry": DEFAULT_RUNTIME_ENTRY,
        "clarification_bridge_entry": CLARIFICATION_BRIDGE_ENTRY,
        "state_scope": context.state_store.scope,
        "session_id": context.state_store.session_id,
        "handoff_file": context.state_store.relative_path(context.state_store.current_handoff_path),
        "clarification_file": context.state_store.relative_path(context.state_store.current_clarification_path),
        "clarification_id": context.clarification_state.clarification_id,
        "clarification_status": context.clarification_state.status,
        "summary": context.clarification_state.summary,
        "entry_guard_reason_code": _handoff_reason_code(context.handoff),
        "clarification_form": context.clarification_form,
        "clarification_submission_state": dict(context.submission_state),
        "presentation": _presentation(context=context, language=language),
        "steps": list(steps),
        "text_fallback": context.clarification_form.get("text_fallback", {"allowed": True, "examples": []}),
    }


def _validate_clarification_handoff(*, handoff: RuntimeHandoff | None, clarification_state: ClarificationState) -> None:
    if handoff is None:
        raise ClarificationBridgeError(
            f"{CLARIFICATION_BRIDGE_HANDOFF_MISMATCH_REASON}: current_handoff.json is required for clarification bridge"
        )
    if handoff.required_host_action != "answer_questions":
        raise ClarificationBridgeError(
            f"{CLARIFICATION_BRIDGE_HANDOFF_MISMATCH_REASON}: expected required_host_action=answer_questions, got {handoff.required_host_action or '<missing>'}"
        )
    entry_guard = handoff.artifacts.get("entry_guard")
    if not isinstance(entry_guard, Mapping) or not bool(entry_guard.get("strict_runtime_entry", False)):
        raise ClarificationBridgeError(
            f"{CLARIFICATION_BRIDGE_HANDOFF_MISMATCH_REASON}: missing strict entry_guard contract in current_handoff.json"
        )
    handoff_clarification_id = str(handoff.artifacts.get("clarification_id") or "").strip()
    if handoff_clarification_id and handoff_clarification_id != clarification_state.clarification_id:
        raise ClarificationBridgeError(
            f"{CLARIFICATION_BRIDGE_HANDOFF_MISMATCH_REASON}: clarification_id mismatch between current_handoff.json and current_clarification.json"
        )


def _handoff_reason_code(handoff: RuntimeHandoff | None) -> str | None:
    if handoff is None:
        return None
    value = handoff.artifacts.get("entry_guard_reason_code")
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _presentation(*, context: ClarificationBridgeContext, language: str) -> Mapping[str, Any]:
    fields = tuple(context.clarification_form.get("fields", ()))
    return {
        "recommended_mode": "interactive_form",
        "fallback_mode": "text",
        "supported_modes": ["interactive_form", "prompt_serial", "text"],
        "interactive_form": {
            "field_order": [str(field["field_id"]) for field in fields],
            "submit_label": _message(language, "submit_label"),
        },
    }


def _build_cli_step(field: Mapping[str, Any]) -> Mapping[str, Any]:
    if str(field.get("field_type") or "input") == "textarea":
        return {
            "field_id": field["field_id"],
            "field_type": field["field_type"],
            "label": field["label"],
            "description": field.get("description", ""),
            "required": bool(field.get("required", False)),
            "renderer": "cli.textarea",
            "ui_kind": "textarea",
            "fallback_renderer": "text",
            "multiline": True,
        }
    return {
        "field_id": field["field_id"],
        "field_type": field["field_type"],
        "label": field["label"],
        "description": field.get("description", ""),
        "required": bool(field.get("required", False)),
        "renderer": "cli.input",
        "ui_kind": "input",
        "fallback_renderer": "text",
        "multiline": False,
    }


def _resolve_clarification_form(
    *,
    handoff: RuntimeHandoff | None,
    clarification_state: ClarificationState,
    language: str,
) -> Mapping[str, Any]:
    if handoff is not None:
        payload = handoff.artifacts.get("clarification_form")
        if isinstance(payload, Mapping):
            return dict(payload)
    return dict(build_scope_clarification_form(clarification_state, language=language))


def _resolve_submission_state(
    *,
    handoff: RuntimeHandoff | None,
    clarification_state: ClarificationState,
) -> Mapping[str, Any]:
    if handoff is not None:
        payload = handoff.artifacts.get("clarification_submission_state")
        if isinstance(payload, Mapping):
            return dict(payload)
    return dict(clarification_submission_state_payload(clarification_state))


def _resolve_clarification_state_store(*, config: RuntimeConfig, session_id: str | None) -> StateStore:
    # Review checkpoints are session-scoped, while develop-time follow-ups can
    # still be emitted from the single global execution truth.
    review_store = StateStore(config, session_id=session_id) if session_id else None
    if review_store is not None and review_store.get_current_clarification() is not None:
        return review_store
    global_store = StateStore(config)
    if global_store.get_current_clarification() is not None:
        return global_store
    return review_store or global_store


def _prompt_cli_input(
    field: Mapping[str, Any],
    *,
    language: str,
    input_reader: PromptReader,
    output_writer: PromptWriter,
) -> str:
    while True:
        output_writer(_field_header(field, language=language))
        value = str(input_reader(f"{_message(language, 'cli_input_prompt')} ") or "").strip()
        if value:
            return value
        output_writer(_message(language, "cli_retry"))


def _prompt_cli_textarea(
    field: Mapping[str, Any],
    *,
    language: str,
    input_reader: PromptReader,
    output_writer: PromptWriter,
) -> str:
    output_writer(_field_header(field, language=language))
    output_writer(_message(language, "cli_textarea_prompt"))
    while True:
        lines: list[str] = []
        while True:
            line = input_reader("")
            if line == ".":
                break
            if not line and lines:
                break
            if not line and not lines:
                break
            lines.append(line)
        value = "\n".join(lines).strip()
        if value:
            return value
        output_writer(_message(language, "cli_retry"))


def _field_header(field: Mapping[str, Any], *, language: str) -> str:
    suffix = f" ({_message(language, 'required')})" if field.get("required", False) else ""
    parts = [f"{field['label']}{suffix}"]
    if field.get("description"):
        parts.append(str(field["description"]))
    return " | ".join(parts)


def _message(language: str, key: str) -> str:
    locale = "en-US" if language == "en-US" else "zh-CN"
    messages = {
        "zh-CN": {
            "required": "必填",
            "submit_label": "提交补充信息",
            "cli_retry": "输入无效，请按提示重试。",
            "cli_input_prompt": "请输入内容",
            "cli_textarea_prompt": "请输入多行内容，单独输入 . 或空行结束。",
            "cli_interactive_fallback": "当前终端不可进入交互模式，已自动退回文本桥接。",
            "cli_submission_message": "通过 CLI bridge 收集并写回 clarification response。",
        },
        "en-US": {
            "required": "required",
            "submit_label": "Submit clarification",
            "cli_retry": "Invalid input. Please try again.",
            "cli_input_prompt": "Enter a value",
            "cli_textarea_prompt": "Enter multiple lines. Finish with a single . or an empty line.",
            "cli_interactive_fallback": "The terminal is not interactive here, so the helper fell back to the text bridge.",
            "cli_submission_message": "Collected and wrote the clarification response through the CLI bridge.",
        },
    }
    return messages[locale][key]


__all__ = [
    "BRIDGE_SCHEMA_VERSION",
    "CLARIFICATION_BRIDGE_ENTRY",
    "ClarificationBridgeContext",
    "ClarificationBridgeError",
    "build_cli_clarification_bridge",
    "build_clarification_submission",
    "load_clarification_bridge_context",
    "prompt_cli_clarification_submission",
    "write_clarification_submission",
]
