"""Host bridge helpers for decision checkpoints.

The default runtime entry stays unchanged. Hosts may optionally use these
helpers when `required_host_action == confirm_decision` to:

1. read a stable host-specific bridge contract,
2. collect answers with native UI, and
3. write back a validated `DecisionSubmission`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable, Mapping

from .cli_interactive import (
    CLI_RENDERER_INTERACTIVE,
    CliInteractiveError,
    CliInteractiveSession,
    InteractiveSessionFactory,
    resolve_cli_renderer,
)
from .entry_guard import (
    DECISION_BRIDGE_ENTRY as ENTRY_GUARD_DECISION_BRIDGE_ENTRY,
    DECISION_BRIDGE_HANDOFF_MISMATCH_REASON,
    DEFAULT_RUNTIME_ENTRY as ENTRY_GUARD_DEFAULT_RUNTIME_ENTRY,
)
from .models import (
    DecisionCheckpoint,
    DecisionCondition,
    DecisionField,
    DecisionOption,
    DecisionState,
    DecisionSubmission,
    RuntimeConfig,
    RuntimeHandoff,
)
from .state import StateStore, iso_now

BRIDGE_SCHEMA_VERSION = "1"
DECISION_BRIDGE_ENTRY = ENTRY_GUARD_DECISION_BRIDGE_ENTRY
DEFAULT_RUNTIME_ENTRY = ENTRY_GUARD_DEFAULT_RUNTIME_ENTRY
_MULTI_SELECT_SPLIT_RE = re.compile(r"[\s,]+")
_YES_VALUES = {"y", "yes", "true", "1", "ok", "confirm", "是", "确认", "继续"}
_NO_VALUES = {"n", "no", "false", "0", "cancel", "否", "取消", "停止"}

PromptReader = Callable[[str], str]
PromptWriter = Callable[[str], None]


class DecisionBridgeError(ValueError):
    """Raised when a host bridge cannot safely inspect or submit a decision."""


@dataclass(frozen=True)
class DecisionBridgeContext:
    """Resolved host-bridge context for the active decision."""

    state_store: StateStore
    handoff: RuntimeHandoff | None
    decision_state: DecisionState
    checkpoint: DecisionCheckpoint
    submission_state: Mapping[str, Any]


def load_decision_bridge_context(
    *,
    config: RuntimeConfig,
    session_id: str | None = None,
) -> DecisionBridgeContext:
    """Load the active decision plus the host-facing handoff snapshot."""
    state_store = _resolve_decision_state_store(config=config, session_id=session_id)
    decision_state = state_store.get_current_decision()
    if decision_state is None:
        raise DecisionBridgeError("No active decision checkpoint was found")
    if decision_state.status in {"consumed", "stale"}:
        raise DecisionBridgeError(f"Decision checkpoint is no longer actionable: {decision_state.status}")

    handoff = state_store.get_current_handoff()
    _validate_decision_handoff(handoff=handoff, decision_state=decision_state)
    checkpoint = _resolve_checkpoint(handoff=handoff, decision_state=decision_state)
    submission_state = _resolve_submission_state(handoff=handoff, decision_state=decision_state)
    return DecisionBridgeContext(
        state_store=state_store,
        handoff=handoff,
        decision_state=decision_state,
        checkpoint=checkpoint,
        submission_state=submission_state,
    )


def build_cli_decision_bridge(context: DecisionBridgeContext, *, language: str) -> Mapping[str, Any]:
    """Build a CLI bridge contract with interactive and text rendering modes."""
    steps = tuple(_build_cli_step(field, context=context, language=language) for field in context.checkpoint.fields)
    return _bridge_payload(
        context=context,
        steps=steps,
        language=language,
    )


def build_decision_submission(
    checkpoint: DecisionCheckpoint,
    *,
    answers: Mapping[str, Any],
    source: str,
    raw_input: str = "",
    message: str = "",
    status: str = "submitted",
    resume_action: str = "submit",
) -> DecisionSubmission:
    """Validate and normalize host answers into a runtime submission payload."""
    normalized_answers = normalize_decision_answers(checkpoint, answers)
    return DecisionSubmission(
        status=status,
        source=source,
        answers=normalized_answers,
        raw_input=raw_input,
        message=message,
        submitted_at=iso_now(),
        resume_action=resume_action,
    )


def write_decision_submission(
    *,
    config: RuntimeConfig,
    submission: DecisionSubmission,
    session_id: str | None = None,
) -> DecisionState:
    """Write a validated submission into the resolved decision state file."""
    state_store = _resolve_decision_state_store(config=config, session_id=session_id)
    updated = state_store.set_current_decision_submission(submission)
    if updated is None:
        raise DecisionBridgeError("No active decision checkpoint was found while writing submission")
    return updated


def prompt_cli_decision_submission(
    *,
    config: RuntimeConfig,
    session_id: str | None = None,
    renderer: str = "auto",
    input_reader: PromptReader = input,
    output_writer: PromptWriter = print,
    interactive_session_factory: InteractiveSessionFactory | None = None,
) -> tuple[DecisionSubmission, str]:
    """Collect a decision through the CLI interactive renderer or text fallback."""
    context = load_decision_bridge_context(config=config, session_id=session_id)
    try:
        used_renderer, interactive_session = resolve_cli_renderer(
            renderer=renderer,
            session_factory=interactive_session_factory,
        )
    except CliInteractiveError as exc:
        raise DecisionBridgeError(str(exc)) from exc
    if used_renderer != CLI_RENDERER_INTERACTIVE and (renderer or "").strip().casefold() in {"interactive", "inquirer"}:
        output_writer(_message(config.language, "cli_interactive_fallback"))

    answers: dict[str, Any] = {}
    for field in context.checkpoint.fields:
        if not field_is_visible(field, answers):
            continue
        answers[field.field_id] = _prompt_cli_field(
            field,
            answers=answers,
            context=context,
            language=config.language,
            input_reader=input_reader,
            output_writer=output_writer,
            renderer=used_renderer,
            interactive_session=interactive_session,
        )

    submission = build_decision_submission(
        context.checkpoint,
        answers=answers,
        source=f"cli_{used_renderer}",
        message=_message(config.language, "cli_submission_message"),
    )
    write_decision_submission(config=config, submission=submission, session_id=session_id)
    return submission, used_renderer


def normalize_decision_answers(checkpoint: DecisionCheckpoint, answers: Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize a host answer payload against the checkpoint definition."""
    normalized: dict[str, Any] = {}
    errors: list[str] = []

    for field in checkpoint.fields:
        if not field_is_visible(field, normalized):
            continue
        raw_value = answers.get(field.field_id)
        if _is_missing_value(field, raw_value):
            if field.required or _has_required_validation(field):
                errors.append(f"{field.field_id}: required")
            continue
        try:
            normalized[field.field_id] = _normalize_field_value(field, raw_value)
        except DecisionBridgeError as exc:
            errors.append(f"{field.field_id}: {exc}")
            continue
        field_errors = _run_field_validations(field, normalized[field.field_id])
        errors.extend(f"{field.field_id}: {message}" for message in field_errors)

    if errors:
        raise DecisionBridgeError("; ".join(errors))
    return normalized


def field_is_visible(field: DecisionField, answers: Mapping[str, Any]) -> bool:
    """Return True when all field conditions are satisfied by the current answers."""
    if not field.when:
        return True
    return all(_condition_matches(condition, answers) for condition in field.when)


def _bridge_payload(
    *,
    context: DecisionBridgeContext,
    steps: Iterable[Mapping[str, Any]],
    language: str,
) -> Mapping[str, Any]:
    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "bridge_status": "ready",
        "host_kind": "cli",
        "required_host_action": "confirm_decision",
        "default_runtime_entry": DEFAULT_RUNTIME_ENTRY,
        "decision_bridge_entry": DECISION_BRIDGE_ENTRY,
        "state_scope": context.state_store.scope,
        "session_id": context.state_store.session_id,
        "handoff_file": context.state_store.relative_path(context.state_store.current_handoff_path),
        "decision_file": context.state_store.relative_path(context.state_store.current_decision_path),
        "decision_id": context.decision_state.decision_id,
        "decision_status": context.decision_state.status,
        "question": context.decision_state.question,
        "summary": context.decision_state.summary,
        "entry_guard_reason_code": _handoff_reason_code(context.handoff),
        "decision_checkpoint": context.checkpoint.to_dict(),
        "decision_submission_state": dict(context.submission_state),
        "presentation": _presentation(context=context, language=language),
        "steps": list(steps),
        "text_fallback": {
            "allowed": context.checkpoint.allow_text_fallback,
            "examples": _text_fallback_examples(language),
        },
    }


def _validate_decision_handoff(*, handoff: RuntimeHandoff | None, decision_state: DecisionState) -> None:
    if handoff is None:
        raise DecisionBridgeError(
            f"{DECISION_BRIDGE_HANDOFF_MISMATCH_REASON}: current_handoff.json is required for decision bridge"
        )
    if handoff.required_host_action != "confirm_decision":
        raise DecisionBridgeError(
            f"{DECISION_BRIDGE_HANDOFF_MISMATCH_REASON}: expected required_host_action=confirm_decision, got {handoff.required_host_action or '<missing>'}"
        )
    entry_guard = handoff.artifacts.get("entry_guard")
    if not isinstance(entry_guard, Mapping) or not bool(entry_guard.get("strict_runtime_entry", False)):
        raise DecisionBridgeError(
            f"{DECISION_BRIDGE_HANDOFF_MISMATCH_REASON}: missing strict entry_guard contract in current_handoff.json"
        )
    handoff_decision_id = str(handoff.artifacts.get("decision_id") or "").strip()
    if handoff_decision_id and handoff_decision_id != decision_state.decision_id:
        raise DecisionBridgeError(
            f"{DECISION_BRIDGE_HANDOFF_MISMATCH_REASON}: decision_id mismatch between current_handoff.json and current_decision.json"
        )


def _handoff_reason_code(handoff: RuntimeHandoff | None) -> str | None:
    if handoff is None:
        return None
    value = handoff.artifacts.get("entry_guard_reason_code")
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _presentation(*, context: DecisionBridgeContext, language: str) -> Mapping[str, Any]:
    return {
        "recommended_mode": "interactive_form",
        "fallback_mode": "text",
        "supported_modes": ["interactive_form", "prompt_serial", "text"],
        "interactive_form": {
            "field_order": [field.field_id for field in context.checkpoint.fields],
            "submit_label": _message(language, "submit_label"),
        },
    }


def _build_cli_step(field: DecisionField, *, context: DecisionBridgeContext, language: str) -> Mapping[str, Any]:
    step = _common_step(field)
    step["fallback_renderer"] = "text"
    if field.field_type == "select":
        step.update(
            {
                "renderer": "cli.select",
                "ui_kind": "select",
                "options": _choice_items(
                    field.options,
                    recommended_option_id=context.decision_state.recommended_option_id,
                    language=language,
                ),
            }
        )
    elif field.field_type == "multi_select":
        step.update(
            {
                "renderer": "cli.multi_select",
                "ui_kind": "multi_select",
                "options": _choice_items(
                    field.options,
                    recommended_option_id=context.decision_state.recommended_option_id,
                    language=language,
                ),
            }
        )
    elif field.field_type == "confirm":
        step.update(
            {
                "renderer": "cli.confirm",
                "ui_kind": "confirm",
                "options": _confirm_items(language),
            }
        )
    elif field.field_type == "textarea":
        step.update(
            {
                "renderer": "cli.textarea",
                "ui_kind": "textarea",
                "fallback_renderer": "text",
                "multiline": True,
            }
        )
    else:
        step.update(
            {
                "renderer": "cli.input",
                "ui_kind": "input",
            }
        )
    return step


def _common_step(field: DecisionField) -> dict[str, Any]:
    return {
        "field_id": field.field_id,
        "field_type": field.field_type,
        "label": field.label,
        "description": field.description,
        "required": field.required,
        "default_value": field.default_value,
        "visible_when": [condition.to_dict() for condition in field.when],
        "validations": [validation.to_dict() for validation in field.validations],
    }


def _choice_items(
    options: Iterable[DecisionOption],
    *,
    recommended_option_id: str | None,
    language: str,
) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    recommended_label = _message(language, "recommended")
    for index, option in enumerate(options, start=1):
        descriptions: list[str] = []
        if option.recommended or option.option_id == recommended_option_id:
            descriptions.append(recommended_label)
        descriptions.append(option.option_id)
        items.append(
            {
                "value": option.option_id,
                "index": index,
                "label": option.title,
                "detail": option.summary,
                "description": " · ".join(descriptions),
                "tradeoffs": list(option.tradeoffs),
                "impacts": list(option.impacts),
                "recommended": option.recommended or option.option_id == recommended_option_id,
            }
        )
    return items


def _confirm_items(language: str) -> list[Mapping[str, Any]]:
    return [
        {"value": True, "label": _message(language, "confirm_yes"), "description": _message(language, "confirm_yes_description")},
        {"value": False, "label": _message(language, "confirm_no"), "description": _message(language, "confirm_no_description")},
    ]


def _text_fallback_examples(language: str) -> tuple[str, ...]:
    if language == "en-US":
        return ("1", "~decide choose option_1", "cancel")
    return ("1", "~decide choose option_1", "取消")


def _resolve_checkpoint(*, handoff: RuntimeHandoff | None, decision_state: DecisionState) -> DecisionCheckpoint:
    if handoff is not None:
        checkpoint_payload = handoff.artifacts.get("decision_checkpoint")
        if isinstance(checkpoint_payload, Mapping):
            checkpoint = DecisionCheckpoint.from_dict(checkpoint_payload)
            if checkpoint.checkpoint_id:
                return checkpoint
    return decision_state.active_checkpoint


def _resolve_submission_state(*, handoff: RuntimeHandoff | None, decision_state: DecisionState) -> Mapping[str, Any]:
    if handoff is not None:
        payload = handoff.artifacts.get("decision_submission_state")
        if isinstance(payload, Mapping):
            return dict(payload)
    submission = decision_state.submission
    if submission is None:
        return {
            "status": "empty",
            "source": None,
            "resume_action": None,
            "submitted_at": None,
            "has_answers": False,
            "answer_keys": [],
        }
    return {
        "status": submission.status,
        "source": submission.source,
        "resume_action": submission.resume_action,
        "submitted_at": submission.submitted_at,
        "has_answers": bool(submission.answers),
        "answer_keys": sorted(str(key) for key in submission.answers.keys()),
    }


def _resolve_decision_state_store(*, config: RuntimeConfig, session_id: str | None) -> StateStore:
    # Prefer the caller's review session, but fall back to global execution
    # state so execution-gate decisions remain reachable through the bridge.
    review_store = StateStore(config, session_id=session_id) if session_id else None
    if review_store is not None and review_store.get_current_decision() is not None:
        return review_store
    global_store = StateStore(config)
    if global_store.get_current_decision() is not None:
        return global_store
    return review_store or global_store


def _condition_matches(condition: DecisionCondition, answers: Mapping[str, Any]) -> bool:
    actual = answers.get(condition.field_id)
    if actual is None:
        return False
    expected = condition.value
    actual_values = actual if isinstance(actual, list) else [actual]
    expected_values = expected if isinstance(expected, list) else [expected]

    if condition.operator == "equals":
        return any(value == expected for value in actual_values for expected in expected_values)
    if condition.operator == "not_equals":
        return all(value != expected for value in actual_values for expected in expected_values)
    if condition.operator == "in":
        return any(value in expected_values for value in actual_values)
    if condition.operator == "not_in":
        return all(value not in expected_values for value in actual_values)
    return False


def _has_required_validation(field: DecisionField) -> bool:
    return any(validation.rule == "required" for validation in field.validations)


def _run_field_validations(field: DecisionField, value: Any) -> list[str]:
    errors: list[str] = []
    for validation in field.validations:
        if validation.rule == "required" and _is_missing_value(field, value):
            errors.append(validation.message or "required")
        elif validation.rule == "min_length" and len(str(value)) < int(validation.value or 0):
            errors.append(validation.message or f"min_length={validation.value}")
        elif validation.rule == "max_length" and len(str(value)) > int(validation.value or 0):
            errors.append(validation.message or f"max_length={validation.value}")
    return errors


def _normalize_field_value(field: DecisionField, raw_value: Any) -> Any:
    if field.field_type == "select":
        return _normalize_single_choice(field, raw_value)
    if field.field_type == "multi_select":
        return _normalize_multi_choice(field, raw_value)
    if field.field_type == "confirm":
        return _normalize_confirm(raw_value)
    if field.field_type in {"input", "textarea"}:
        return _normalize_text(raw_value)
    raise DecisionBridgeError(f"Unsupported field type: {field.field_type}")


def _normalize_single_choice(field: DecisionField, raw_value: Any) -> str:
    if isinstance(raw_value, list):
        if len(raw_value) != 1:
            raise DecisionBridgeError("expected a single option")
        raw_value = raw_value[0]
    option_id = _match_option(raw_value, field.options)
    if option_id is None:
        raise DecisionBridgeError("unknown option")
    return option_id


def _normalize_multi_choice(field: DecisionField, raw_value: Any) -> list[str]:
    tokens: list[Any]
    if isinstance(raw_value, str):
        tokens = [token for token in _MULTI_SELECT_SPLIT_RE.split(raw_value.strip()) if token]
    elif isinstance(raw_value, (list, tuple, set)):
        tokens = list(raw_value)
    else:
        raise DecisionBridgeError("expected a list of options")

    normalized: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        option_id = _match_option(token, field.options)
        if option_id is None:
            raise DecisionBridgeError(f"unknown option: {token}")
        if option_id in seen:
            continue
        seen.add(option_id)
        normalized.append(option_id)
    return normalized


def _normalize_confirm(raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)) and raw_value in {0, 1}:
        return bool(raw_value)
    text = str(raw_value).strip().casefold()
    if text in _YES_VALUES:
        return True
    if text in _NO_VALUES:
        return False
    raise DecisionBridgeError("expected a boolean confirmation")


def _normalize_text(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    if isinstance(raw_value, str):
        return raw_value.strip()
    return str(raw_value).strip()


def _match_option(raw_value: Any, options: Iterable[DecisionOption]) -> str | None:
    text = str(raw_value).strip()
    if not text:
        return None
    option_list = tuple(options)
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(option_list):
            return option_list[index].option_id

    normalized = _normalize_option_text(text)
    for option in option_list:
        if text.casefold() == option.option_id.casefold():
            return option.option_id
        if normalized == _normalize_option_text(option.option_id):
            return option.option_id
        if normalized == _normalize_option_text(option.title):
            return option.option_id
        if normalized == _normalize_option_text(option.summary):
            return option.option_id
    return None


def _normalize_option_text(value: str) -> str:
    return re.sub(r"[\s`'\"“”‘’.,:;!?(){}\[\]<>/\\|_-]+", "", value.casefold())


def _is_missing_value(field: DecisionField, value: Any) -> bool:
    if value is None:
        return True
    if field.field_type == "confirm":
        return False
    if field.field_type == "multi_select":
        if isinstance(value, str):
            return not value.strip()
        return len(value) == 0 if isinstance(value, (list, tuple, set)) else False
    if isinstance(value, str):
        return not value.strip()
    return False


def _prompt_cli_field(
    field: DecisionField,
    *,
    answers: Mapping[str, Any],
    context: DecisionBridgeContext,
    language: str,
    input_reader: PromptReader,
    output_writer: PromptWriter,
    renderer: str,
    interactive_session: CliInteractiveSession | None,
) -> Any:
    if renderer == CLI_RENDERER_INTERACTIVE and interactive_session is not None:
        return _prompt_cli_field_interactive(
            field,
            context=context,
            language=language,
            interactive_session=interactive_session,
            input_reader=input_reader,
            output_writer=output_writer,
        )
    if field.field_type == "select":
        return _prompt_cli_select(
            field,
            language=language,
            input_reader=input_reader,
            output_writer=output_writer,
            recommended_option_id=context.decision_state.recommended_option_id,
        )
    if field.field_type == "multi_select":
        return _prompt_cli_multi_select(
            field,
            language=language,
            input_reader=input_reader,
            output_writer=output_writer,
            recommended_option_id=context.decision_state.recommended_option_id,
        )
    if field.field_type == "confirm":
        return _prompt_cli_confirm(field, language=language, input_reader=input_reader, output_writer=output_writer)
    if field.field_type == "textarea":
        return _prompt_cli_textarea(field, language=language, input_reader=input_reader, output_writer=output_writer)
    return _prompt_cli_input(field, language=language, input_reader=input_reader, output_writer=output_writer)


def _prompt_cli_field_interactive(
    field: DecisionField,
    *,
    context: DecisionBridgeContext,
    language: str,
    interactive_session: CliInteractiveSession,
    input_reader: PromptReader,
    output_writer: PromptWriter,
) -> Any:
    if field.field_type == "select":
        return interactive_session.select(
            title=_field_header(field, language=language),
            items=_choice_items(
                field.options,
                recommended_option_id=context.decision_state.recommended_option_id,
                language=language,
            ),
            instructions=_message(language, "interactive_select_instructions"),
            initial_value=_select_initial_value(field, context=context),
        )
    if field.field_type == "multi_select":
        return interactive_session.multi_select(
            title=_field_header(field, language=language),
            items=_choice_items(
                field.options,
                recommended_option_id=context.decision_state.recommended_option_id,
                language=language,
            ),
            instructions=_message(language, "interactive_multi_select_instructions"),
            initial_values=_multi_select_initial_values(field),
            required=field.required or _has_required_validation(field),
        )
    if field.field_type == "confirm":
        return interactive_session.confirm(
            title=_field_header(field, language=language),
            yes_label=_message(language, "confirm_yes"),
            no_label=_message(language, "confirm_no"),
            default_value=_confirm_default_value(field),
            instructions=_message(language, "interactive_confirm_instructions"),
        )
    if field.field_type == "textarea":
        return _prompt_cli_textarea(field, language=language, input_reader=input_reader, output_writer=output_writer)
    return _prompt_cli_input(field, language=language, input_reader=input_reader, output_writer=output_writer)


def _prompt_cli_select(
    field: DecisionField,
    *,
    language: str,
    input_reader: PromptReader,
    output_writer: PromptWriter,
    recommended_option_id: str | None,
) -> str:
    output_writer(_field_header(field, language=language))
    for item in _choice_items(field.options, recommended_option_id=recommended_option_id, language=language):
        output_writer(f"  {item['index']}. {item['label']} [{item['value']}]")
        if item["detail"]:
            output_writer(f"     {item['detail']}")
        if item["description"]:
            output_writer(f"     {item['description']}")
    while True:
        raw = input_reader(f"{_message(language, 'cli_select_prompt')} ").strip()
        try:
            return _normalize_single_choice(field, raw)
        except DecisionBridgeError:
            output_writer(_message(language, "cli_retry"))


def _prompt_cli_multi_select(
    field: DecisionField,
    *,
    language: str,
    input_reader: PromptReader,
    output_writer: PromptWriter,
    recommended_option_id: str | None,
) -> list[str]:
    output_writer(_field_header(field, language=language))
    for item in _choice_items(field.options, recommended_option_id=recommended_option_id, language=language):
        output_writer(f"  {item['index']}. {item['label']} [{item['value']}]")
        if item["description"]:
            output_writer(f"     {item['description']}")
    while True:
        raw = input_reader(f"{_message(language, 'cli_multi_select_prompt')} ").strip()
        try:
            return _normalize_multi_choice(field, raw)
        except DecisionBridgeError:
            output_writer(_message(language, "cli_retry"))


def _prompt_cli_confirm(field: DecisionField, *, language: str, input_reader: PromptReader, output_writer: PromptWriter) -> bool:
    output_writer(_field_header(field, language=language))
    output_writer(f"  {_message(language, 'confirm_yes')}/{_message(language, 'confirm_no')}")
    while True:
        raw = input_reader(f"{_message(language, 'cli_confirm_prompt')} ").strip()
        try:
            return _normalize_confirm(raw)
        except DecisionBridgeError:
            output_writer(_message(language, "cli_retry"))


def _prompt_cli_input(field: DecisionField, *, language: str, input_reader: PromptReader, output_writer: PromptWriter) -> str:
    while True:
        output_writer(_field_header(field, language=language))
        value = _normalize_text(input_reader(f"{_message(language, 'cli_input_prompt')} "))
        if not _is_missing_value(field, value):
            return value
        if not field.required and not _has_required_validation(field):
            return value
        output_writer(_message(language, "cli_retry"))


def _prompt_cli_textarea(field: DecisionField, *, language: str, input_reader: PromptReader, output_writer: PromptWriter) -> str:
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
        if value or (not field.required and not _has_required_validation(field)):
            return value
        output_writer(_message(language, "cli_retry"))


def _select_initial_value(field: DecisionField, *, context: DecisionBridgeContext) -> str | None:
    for candidate in (field.default_value, context.decision_state.default_option_id, context.decision_state.recommended_option_id):
        option_id = _match_option(candidate, field.options) if candidate is not None else None
        if option_id is not None:
            return option_id
    return None


def _multi_select_initial_values(field: DecisionField) -> list[str]:
    if isinstance(field.default_value, (list, tuple, set)):
        return _normalize_multi_choice(field, field.default_value)
    if isinstance(field.default_value, str) and field.default_value.strip():
        return _normalize_multi_choice(field, field.default_value)
    return []


def _confirm_default_value(field: DecisionField) -> bool | None:
    if field.default_value is None:
        return None
    return _normalize_confirm(field.default_value)


def _field_header(field: DecisionField, *, language: str) -> str:
    suffix = f" ({_message(language, 'required')})" if field.required or _has_required_validation(field) else ""
    parts = [f"{field.label}{suffix}"]
    if field.description:
        parts.append(field.description)
    return " | ".join(parts)


def _message(language: str, key: str) -> str:
    locale = "en-US" if language == "en-US" else "zh-CN"
    messages = {
        "zh-CN": {
            "recommended": "推荐",
            "confirm_yes": "确认",
            "confirm_yes_description": "接受当前约束并继续。",
            "confirm_no": "暂不确认",
            "confirm_no_description": "保留当前方案，先不继续。",
            "required": "必填",
            "cli_retry": "输入无效，请按提示重试。",
            "cli_select_prompt": "请选择编号或 option_id",
            "cli_multi_select_prompt": "请选择编号或 option_id，多个用逗号分隔",
            "cli_confirm_prompt": "请输入 yes/no 或 确认/取消",
            "cli_input_prompt": "请输入内容",
            "cli_textarea_prompt": "请输入多行内容，单独输入 . 或空行结束。",
            "cli_interactive_fallback": "当前终端不可进入交互模式，已自动退回文本桥接。",
            "cli_submission_message": "通过 CLI bridge 收集并写回 submission。",
            "interactive_select_instructions": "使用 Up/Down 选择，Enter 确认，或直接按数字。",
            "interactive_multi_select_instructions": "使用 Up/Down 移动，Space 勾选，Enter 提交，或直接按数字切换。",
            "interactive_confirm_instructions": "使用 Left/Right 或 Up/Down 切换，Enter 确认，也可直接按 y/n。",
            "submit_label": "提交决策",
        },
        "en-US": {
            "recommended": "Recommended",
            "confirm_yes": "Confirm",
            "confirm_yes_description": "Accept the current constraint and continue.",
            "confirm_no": "Not now",
            "confirm_no_description": "Keep the current plan without continuing yet.",
            "required": "required",
            "cli_retry": "Invalid input. Please try again.",
            "cli_select_prompt": "Choose an index or option_id",
            "cli_multi_select_prompt": "Choose indexes or option_ids separated by commas",
            "cli_confirm_prompt": "Enter yes/no",
            "cli_input_prompt": "Enter a value",
            "cli_textarea_prompt": "Enter multiple lines. Finish with a single . or an empty line.",
            "cli_interactive_fallback": "The terminal is not interactive here, so the helper fell back to the text bridge.",
            "cli_submission_message": "Collected and wrote the submission through the CLI bridge.",
            "interactive_select_instructions": "Use Up/Down to choose, Enter to confirm, or press a number.",
            "interactive_multi_select_instructions": "Use Up/Down to move, Space to toggle, Enter to submit, or press a number.",
            "interactive_confirm_instructions": "Use Left/Right or Up/Down to switch, Enter to confirm, or press y/n.",
            "submit_label": "Submit decision",
        },
    }
    return messages[locale][key]


__all__ = [
    "BRIDGE_SCHEMA_VERSION",
    "DECISION_BRIDGE_ENTRY",
    "DecisionBridgeContext",
    "DecisionBridgeError",
    "build_cli_decision_bridge",
    "build_decision_submission",
    "field_is_visible",
    "load_decision_bridge_context",
    "normalize_decision_answers",
    "prompt_cli_decision_submission",
    "write_decision_submission",
]
