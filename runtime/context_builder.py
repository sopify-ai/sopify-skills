"""Local context compression helpers for V1 action-in-context resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .context_v1_scope import MAX_LOCAL_CONTEXT_USER_MESSAGES


@dataclass(frozen=True)
class LocalContext:
    """Minimal, prose-resistant context for guarded local resolution."""

    current_user_input: str
    recent_user_messages: tuple[str, ...] = ()
    checkpoint_summary: Mapping[str, Any] = field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    runtime_constraints: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_user_input": self.current_user_input,
            "recent_user_messages": list(self.recent_user_messages),
            "checkpoint_summary": dict(self.checkpoint_summary),
            "allowed_actions": list(self.allowed_actions),
            "runtime_constraints": dict(self.runtime_constraints),
        }


def build_local_context(
    current_user_input: str,
    *,
    recent_messages: Sequence[Mapping[str, Any]] = (),
    checkpoint_summary: Mapping[str, Any] | None = None,
    allowed_actions: Sequence[str] = (),
    runtime_constraints: Mapping[str, Any] | None = None,
    max_user_messages: int = MAX_LOCAL_CONTEXT_USER_MESSAGES,
) -> LocalContext:
    """Build the smallest context block needed for the current guarded slice."""

    if max_user_messages < 0:
        raise ValueError("max_user_messages must be >= 0")

    normalized_input = str(current_user_input or "").strip()
    recent_user_messages = _extract_recent_user_messages(
        recent_messages,
        current_user_input=normalized_input,
        max_user_messages=max_user_messages,
    )
    normalized_allowed_actions = _normalize_string_sequence(allowed_actions)
    normalized_checkpoint_summary = MappingProxyType(dict(checkpoint_summary or {}))
    normalized_runtime_constraints = MappingProxyType(dict(runtime_constraints or {}))

    return LocalContext(
        current_user_input=normalized_input,
        recent_user_messages=recent_user_messages,
        checkpoint_summary=normalized_checkpoint_summary,
        allowed_actions=normalized_allowed_actions,
        runtime_constraints=normalized_runtime_constraints,
    )


def _extract_recent_user_messages(
    recent_messages: Sequence[Mapping[str, Any]],
    *,
    current_user_input: str,
    max_user_messages: int,
) -> tuple[str, ...]:
    user_messages: list[str] = []
    for message in recent_messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role != "user":
            continue
        content = _coerce_message_text(message.get("content"))
        if not content or content == current_user_input:
            continue
        user_messages.append(content)
    if max_user_messages == 0:
        return ()
    return tuple(user_messages[-max_user_messages:])


def _coerce_message_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return str(value.get("text") or "").strip()
    if isinstance(value, Sequence):
        parts: list[str] = []
        for item in value:
            text = _coerce_message_text(item)
            if text:
                parts.append(text)
        return " ".join(parts).strip()
    return str(value or "").strip()


def _normalize_string_sequence(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)

