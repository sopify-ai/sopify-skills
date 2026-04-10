"""Loader and validator for frozen fail-close decision table assets."""

from __future__ import annotations

from copy import deepcopy
import json
from json import JSONDecodeError
from pathlib import Path
import re
from string import Formatter
from typing import Any, Mapping

from ._yaml import YamlParseError, load_yaml


class DecisionTableError(ValueError):
    """Raised when the frozen decision table asset is malformed."""


DEFAULT_DECISION_TABLES_PATH = Path(__file__).resolve().parent / "contracts" / "decision_tables.yaml"
DEFAULT_DECISION_TABLES_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts" / "decision_tables.schema.json"
)
DEFAULT_SIGNAL_PRIORITY_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts" / "signal_priority_table.schema.json"
)
DEFAULT_SIDE_EFFECT_MAPPING_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts" / "side_effect_mapping_table.schema.json"
)
DEFAULT_HOST_MESSAGE_TEMPLATES_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts" / "host_message_templates.schema.json"
)

_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}$")
_FORMATTER = Formatter()


def load_default_decision_tables(*, schema_path: str | Path | None = None) -> dict[str, Any]:
    """Load the repository-default frozen decision table asset."""

    return load_decision_tables(DEFAULT_DECISION_TABLES_PATH, schema_path=schema_path)


def load_default_decision_tables_schema() -> dict[str, Any]:
    """Load the repository-default decision table schema asset."""

    return load_decision_tables_schema(DEFAULT_DECISION_TABLES_SCHEMA_PATH)


def load_decision_tables(path: str | Path, *, schema_path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate a decision table asset against the frozen schema asset."""

    source_path = _resolve_existing_file(path, label="Decision table asset")
    schema = load_decision_tables_schema(schema_path or DEFAULT_DECISION_TABLES_SCHEMA_PATH)
    signal_priority_schema = load_signal_priority_table_schema(DEFAULT_SIGNAL_PRIORITY_SCHEMA_PATH)
    side_effect_mapping_schema = load_side_effect_mapping_table_schema(
        DEFAULT_SIDE_EFFECT_MAPPING_SCHEMA_PATH
    )
    host_message_templates_schema = load_host_message_templates_schema(
        DEFAULT_HOST_MESSAGE_TEMPLATES_SCHEMA_PATH
    )
    raw_text = source_path.read_text(encoding="utf-8")
    data = _parse_yaml(raw_text)
    if not isinstance(data, dict):
        raise DecisionTableError(f"Decision table root must be a mapping: {source_path}")
    tables = _validate_decision_tables(
        deepcopy(data),
        schema=deepcopy(schema),
        signal_priority_schema=deepcopy(signal_priority_schema),
        side_effect_mapping_schema=deepcopy(side_effect_mapping_schema),
        host_message_templates_schema=deepcopy(host_message_templates_schema),
        source_path=source_path,
    )
    _validate_context_v1_scope(tables)
    return tables


def load_decision_tables_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate the independent decision table schema asset."""

    data, source_path = _load_json_mapping(path, label="Decision table schema")
    return _validate_decision_table_schema(deepcopy(data), source_path=source_path)


def load_signal_priority_table_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate the signal-priority schema asset."""

    data, source_path = _load_json_mapping(path, label="Signal priority schema")
    return _validate_signal_priority_table_schema(deepcopy(data), source_path=source_path)


def load_side_effect_mapping_table_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate the side-effect mapping schema asset."""

    data, source_path = _load_json_mapping(path, label="Side-effect mapping schema")
    return _validate_side_effect_mapping_table_schema(deepcopy(data), source_path=source_path)


def load_host_message_templates_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate the host-facing message template schema asset."""

    data, source_path = _load_json_mapping(path, label="Host message template schema")
    return _validate_host_message_templates_schema(deepcopy(data), source_path=source_path)


def _load_json_mapping(path: str | Path, *, label: str) -> tuple[dict[str, Any], Path]:
    source_path = _resolve_existing_file(path, label=label)
    raw_text = source_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except JSONDecodeError as exc:
        raise DecisionTableError(
            f"Invalid {label.lower()} JSON at {source_path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise DecisionTableError(f"{label} root must be a mapping: {source_path}")
    return data, source_path


def _resolve_existing_file(path: str | Path, *, label: str) -> Path:
    source_path = Path(path).resolve()
    if not source_path.exists():
        raise DecisionTableError(f"{label} not found: {source_path}")
    if not source_path.is_file():
        raise DecisionTableError(f"{label} is not a file: {source_path}")
    return source_path


def _parse_yaml(text: str) -> Any:
    try:
        return load_yaml(text)
    except YamlParseError as exc:
        raise DecisionTableError(str(exc)) from exc


def _validate_context_v1_scope(tables: dict[str, Any]) -> None:
    from .context_v1_scope import ContextV1ScopeError, validate_decision_tables_v1_scope

    try:
        validate_decision_tables_v1_scope(tables)
    except ContextV1ScopeError as exc:
        raise DecisionTableError(f"Decision tables exceed current V1 scope: {exc}") from exc


def _validate_decision_table_schema(schema: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    _assert_exact_keys(
        schema,
        (
            "schema_file_version",
            "asset_schema_version",
            "root_order",
            "invariants_required_true",
            "truth_statuses",
            "quarantine_annotation_fields",
            "primary_failure_priority",
            "primary_failure_families",
            "consult_readonly_contract",
            "best_proven_resume_target",
        ),
        path="schema",
    )
    if schema.get("schema_file_version") != "1":
        raise DecisionTableError(
            f"Unsupported decision table schema_file_version: {schema.get('schema_file_version')!r}"
        )
    asset_schema_version = schema.get("asset_schema_version")
    if not isinstance(asset_schema_version, str) or not asset_schema_version.strip():
        raise DecisionTableError("schema.asset_schema_version must be a non-empty string")

    root_order = _expect_string_list(schema.get("root_order"), path="schema.root_order")
    invariants_required_true = _expect_string_list(
        schema.get("invariants_required_true"),
        path="schema.invariants_required_true",
    )
    truth_statuses = _validate_truth_statuses_schema(schema.get("truth_statuses"))
    quarantine_annotation_fields = _expect_string_list(
        schema.get("quarantine_annotation_fields"),
        path="schema.quarantine_annotation_fields",
    )
    primary_failure_priority = _expect_string_list(
        schema.get("primary_failure_priority"),
        path="schema.primary_failure_priority",
    )
    primary_failure_families = _validate_primary_failure_families_schema(
        schema.get("primary_failure_families"),
        priority_order=primary_failure_priority,
    )
    consult_contract = _validate_consult_contract_schema(schema.get("consult_readonly_contract"))
    best_resume_target = _validate_best_resume_target_schema(
        schema.get("best_proven_resume_target")
    )

    schema["root_order"] = root_order
    schema["invariants_required_true"] = invariants_required_true
    schema["truth_statuses"] = truth_statuses
    schema["quarantine_annotation_fields"] = quarantine_annotation_fields
    schema["primary_failure_priority"] = primary_failure_priority
    schema["primary_failure_families"] = primary_failure_families
    schema["consult_readonly_contract"] = consult_contract
    schema["best_proven_resume_target"] = best_resume_target
    schema["source_path"] = str(source_path)
    return schema


def _validate_truth_statuses_schema(value: Any) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="schema.truth_statuses")
    _assert_exact_keys(
        mapping,
        ("ordered_statuses", "row_order", "resolution_enabled_by_status"),
        path="schema.truth_statuses",
    )
    ordered_statuses = _expect_string_list(
        mapping.get("ordered_statuses"),
        path="schema.truth_statuses.ordered_statuses",
    )
    row_order = _expect_string_list(mapping.get("row_order"), path="schema.truth_statuses.row_order")
    _assert_exact_list(
        row_order,
        ("resolution_enabled", "default_host_path"),
        path="schema.truth_statuses.row_order",
    )
    resolution_enabled_by_status = _expect_mapping(
        mapping.get("resolution_enabled_by_status"),
        path="schema.truth_statuses.resolution_enabled_by_status",
    )
    _assert_exact_keys(
        resolution_enabled_by_status,
        tuple(ordered_statuses),
        path="schema.truth_statuses.resolution_enabled_by_status",
    )
    normalized_resolution_enabled: dict[str, bool] = {}
    for status in ordered_statuses:
        enabled = resolution_enabled_by_status.get(status)
        if not isinstance(enabled, bool):
            raise DecisionTableError(
                f"schema.truth_statuses.resolution_enabled_by_status.{status} must be boolean"
            )
        normalized_resolution_enabled[status] = enabled
    return {
        "ordered_statuses": ordered_statuses,
        "row_order": row_order,
        "resolution_enabled_by_status": normalized_resolution_enabled,
    }


def _validate_primary_failure_families_schema(
    value: Any,
    *,
    priority_order: list[str],
) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="schema.primary_failure_families")
    _assert_exact_keys(
        mapping,
        ("ordered_families", "row_order", "members_by_family"),
        path="schema.primary_failure_families",
    )
    ordered_families = _expect_string_list(
        mapping.get("ordered_families"),
        path="schema.primary_failure_families.ordered_families",
    )
    _assert_exact_list(
        ordered_families,
        tuple(priority_order),
        path="schema.primary_failure_families.ordered_families",
    )
    row_order = _expect_string_list(
        mapping.get("row_order"),
        path="schema.primary_failure_families.row_order",
    )
    _assert_exact_list(
        row_order,
        ("members",),
        path="schema.primary_failure_families.row_order",
    )
    members_by_family = _expect_mapping(
        mapping.get("members_by_family"),
        path="schema.primary_failure_families.members_by_family",
    )
    _assert_exact_keys(
        members_by_family,
        tuple(ordered_families),
        path="schema.primary_failure_families.members_by_family",
    )
    normalized_members_by_family: dict[str, list[str]] = {}
    for family in ordered_families:
        normalized_members_by_family[family] = _expect_string_list(
            members_by_family.get(family),
            path=f"schema.primary_failure_families.members_by_family.{family}",
        )
    return {
        "ordered_families": ordered_families,
        "row_order": row_order,
        "members_by_family": normalized_members_by_family,
    }


def _validate_consult_contract_schema(value: Any) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="schema.consult_readonly_contract")
    _assert_exact_keys(
        mapping,
        (
            "ordered_keys",
            "required_when",
            "ignored_required_host_actions",
            "required_fields_order",
            "required_field_specs",
        ),
        path="schema.consult_readonly_contract",
    )
    ordered_keys = _expect_string_list(
        mapping.get("ordered_keys"),
        path="schema.consult_readonly_contract.ordered_keys",
    )
    _assert_exact_list(
        ordered_keys,
        ("required_when", "ignored_required_host_actions", "required_fields"),
        path="schema.consult_readonly_contract.ordered_keys",
    )
    required_when = _expect_string_list(
        mapping.get("required_when"),
        path="schema.consult_readonly_contract.required_when",
    )
    ignored_required_host_actions = _expect_string_list(
        mapping.get("ignored_required_host_actions"),
        path="schema.consult_readonly_contract.ignored_required_host_actions",
    )
    required_fields_order = _expect_string_list(
        mapping.get("required_fields_order"),
        path="schema.consult_readonly_contract.required_fields_order",
    )
    required_field_specs = _expect_mapping(
        mapping.get("required_field_specs"),
        path="schema.consult_readonly_contract.required_field_specs",
    )
    _assert_exact_keys(
        required_field_specs,
        tuple(required_fields_order),
        path="schema.consult_readonly_contract.required_field_specs",
    )

    normalized_specs: dict[str, dict[str, Any]] = {}
    for field_name in required_fields_order:
        spec = _expect_mapping(
            required_field_specs.get(field_name),
            path=f"schema.consult_readonly_contract.required_field_specs.{field_name}",
        )
        ordered_field_keys = _expect_string_list(
            spec.get("ordered_keys"),
            path=(
                "schema.consult_readonly_contract.required_field_specs."
                f"{field_name}.ordered_keys"
            ),
        )
        _assert_exact_keys(
            spec,
            ("ordered_keys", *ordered_field_keys),
            path=f"schema.consult_readonly_contract.required_field_specs.{field_name}",
        )
        normalized_spec: dict[str, Any] = {"ordered_keys": ordered_field_keys}
        for key in ordered_field_keys:
            raw_value = spec.get(key)
            if key in {"role", "equals"}:
                if not isinstance(raw_value, str) or not raw_value.strip():
                    raise DecisionTableError(
                        "schema.consult_readonly_contract.required_field_specs."
                        f"{field_name}.{key} must be a non-empty string"
                    )
                normalized_spec[key] = raw_value
            elif key == "includes":
                normalized_spec[key] = _expect_string_list(
                    raw_value,
                    path=(
                        "schema.consult_readonly_contract.required_field_specs."
                        f"{field_name}.includes"
                    ),
                )
            else:
                raise DecisionTableError(
                    "Unsupported schema.consult_readonly_contract.required_field_specs "
                    f"field: {field_name}.{key}"
                )
        normalized_specs[field_name] = normalized_spec

    return {
        "ordered_keys": ordered_keys,
        "required_when": required_when,
        "ignored_required_host_actions": ignored_required_host_actions,
        "required_fields_order": required_fields_order,
        "required_field_specs": normalized_specs,
    }


def _validate_best_resume_target_schema(value: Any) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="schema.best_proven_resume_target")
    _assert_exact_keys(
        mapping,
        ("ordered_keys", "proof_entry_order", "kinds", "proof_order"),
        path="schema.best_proven_resume_target",
    )
    ordered_keys = _expect_string_list(
        mapping.get("ordered_keys"),
        path="schema.best_proven_resume_target.ordered_keys",
    )
    _assert_exact_list(
        ordered_keys,
        ("kinds", "proof_order"),
        path="schema.best_proven_resume_target.ordered_keys",
    )
    proof_entry_order = _expect_string_list(
        mapping.get("proof_entry_order"),
        path="schema.best_proven_resume_target.proof_entry_order",
    )
    _assert_exact_list(
        proof_entry_order,
        ("kind", "proof"),
        path="schema.best_proven_resume_target.proof_entry_order",
    )
    kinds = _expect_string_list(
        mapping.get("kinds"),
        path="schema.best_proven_resume_target.kinds",
    )
    proof_order = mapping.get("proof_order")
    if not isinstance(proof_order, list) or not proof_order:
        raise DecisionTableError("schema.best_proven_resume_target.proof_order must be a non-empty list")

    normalized_proof_order: list[dict[str, Any]] = []
    for index, entry in enumerate(proof_order):
        row = _expect_mapping(
            entry,
            path=f"schema.best_proven_resume_target.proof_order[{index}]",
        )
        _assert_exact_keys(
            row,
            tuple(proof_entry_order),
            path=f"schema.best_proven_resume_target.proof_order[{index}]",
        )
        kind = row.get("kind")
        if kind not in kinds:
            raise DecisionTableError(
                "schema.best_proven_resume_target.proof_order"
                f"[{index}].kind must be one of: {', '.join(kinds)}"
            )
        proof = _expect_string_list(
            row.get("proof"),
            path=f"schema.best_proven_resume_target.proof_order[{index}].proof",
        )
        normalized_proof_order.append({"kind": kind, "proof": proof})

    return {
        "ordered_keys": ordered_keys,
        "proof_entry_order": proof_entry_order,
        "kinds": kinds,
        "proof_order": normalized_proof_order,
    }


def _validate_signal_priority_table_schema(schema: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    _assert_exact_keys(
        schema,
        (
            "schema_file_version",
            "asset_schema_version",
            "root_order",
            "ordered_origins",
            "origin_precedence",
            "ordered_evidence_ranks",
            "evidence_rank",
            "row_order",
            "ordered_signal_ids",
            "allowed_checkpoint_kinds",
            "signal_groups",
            "target_kinds",
            "winner_actions",
            "fallback_on_conflicts",
        ),
        path="schema.signal_priority_table",
    )
    if schema.get("schema_file_version") != "1":
        raise DecisionTableError(
            "Unsupported signal priority schema_file_version: "
            f"{schema.get('schema_file_version')!r}"
        )
    ordered_origins = _expect_string_list(
        schema.get("ordered_origins"),
        path="schema.signal_priority_table.ordered_origins",
    )
    origin_precedence = _expect_int_mapping(
        schema.get("origin_precedence"),
        expected_keys=ordered_origins,
        path="schema.signal_priority_table.origin_precedence",
    )
    ordered_evidence_ranks = _expect_string_list(
        schema.get("ordered_evidence_ranks"),
        path="schema.signal_priority_table.ordered_evidence_ranks",
    )
    evidence_rank = _expect_int_mapping(
        schema.get("evidence_rank"),
        expected_keys=ordered_evidence_ranks,
        path="schema.signal_priority_table.evidence_rank",
    )
    row_order = _expect_string_list(
        schema.get("row_order"),
        path="schema.signal_priority_table.row_order",
    )
    _assert_exact_list(
        row_order,
        (
            "signal_id",
            "enabled_checkpoint_kinds",
            "signal_group",
            "target_kind",
            "target_slot",
            "allowed_origins",
            "origin_evidence_cap",
            "mutually_exclusive_with",
            "can_coexist_with",
            "suppresses",
            "priority",
            "winner_action",
            "fallback_on_conflict",
            "reason_code",
        ),
        path="schema.signal_priority_table.row_order",
    )
    schema["root_order"] = _expect_string_list(
        schema.get("root_order"),
        path="schema.signal_priority_table.root_order",
    )
    schema["ordered_origins"] = ordered_origins
    schema["origin_precedence"] = origin_precedence
    schema["ordered_evidence_ranks"] = ordered_evidence_ranks
    schema["evidence_rank"] = evidence_rank
    schema["row_order"] = row_order
    schema["ordered_signal_ids"] = _expect_string_list(
        schema.get("ordered_signal_ids"),
        path="schema.signal_priority_table.ordered_signal_ids",
    )
    schema["allowed_checkpoint_kinds"] = _expect_string_list(
        schema.get("allowed_checkpoint_kinds"),
        path="schema.signal_priority_table.allowed_checkpoint_kinds",
    )
    schema["signal_groups"] = _expect_string_list(
        schema.get("signal_groups"),
        path="schema.signal_priority_table.signal_groups",
    )
    schema["target_kinds"] = _expect_string_list(
        schema.get("target_kinds"),
        path="schema.signal_priority_table.target_kinds",
    )
    schema["winner_actions"] = _expect_string_list(
        schema.get("winner_actions"),
        path="schema.signal_priority_table.winner_actions",
    )
    schema["fallback_on_conflicts"] = _expect_string_list(
        schema.get("fallback_on_conflicts"),
        path="schema.signal_priority_table.fallback_on_conflicts",
    )
    schema["source_path"] = str(source_path)
    return schema


def _validate_side_effect_mapping_table_schema(
    schema: dict[str, Any],
    *,
    source_path: Path,
) -> dict[str, Any]:
    _assert_exact_keys(
        schema,
        (
            "schema_file_version",
            "asset_schema_version",
            "root_order",
            "row_order",
            "ordered_resolved_actions",
            "checkpoint_kinds",
            "state_mutators",
            "handoff_protocol",
            "terminalities",
        ),
        path="schema.side_effect_mapping_table",
    )
    if schema.get("schema_file_version") != "1":
        raise DecisionTableError(
            "Unsupported side-effect mapping schema_file_version: "
            f"{schema.get('schema_file_version')!r}"
        )
    root_order = _expect_string_list(
        schema.get("root_order"),
        path="schema.side_effect_mapping_table.root_order",
    )
    row_order = _expect_string_list(
        schema.get("row_order"),
        path="schema.side_effect_mapping_table.row_order",
    )
    _assert_exact_list(
        row_order,
        (
            "resolved_action",
            "checkpoint_kind",
            "state_mutators",
            "forbidden_state_effects",
            "preserved_identity",
            "handoff_protocol",
            "terminality",
            "reason_code",
        ),
        path="schema.side_effect_mapping_table.row_order",
    )
    ordered_resolved_actions = _expect_string_list(
        schema.get("ordered_resolved_actions"),
        path="schema.side_effect_mapping_table.ordered_resolved_actions",
    )
    checkpoint_kinds = _expect_string_list(
        schema.get("checkpoint_kinds"),
        path="schema.side_effect_mapping_table.checkpoint_kinds",
    )
    state_mutators = _expect_mapping(
        schema.get("state_mutators"),
        path="schema.side_effect_mapping_table.state_mutators",
    )
    _assert_exact_keys(
        state_mutators,
        ("ordered_keys",),
        path="schema.side_effect_mapping_table.state_mutators",
    )
    state_mutator_keys = _expect_string_list(
        state_mutators.get("ordered_keys"),
        path="schema.side_effect_mapping_table.state_mutators.ordered_keys",
    )
    _assert_exact_list(
        state_mutator_keys,
        ("preserve", "clear", "update", "write"),
        path="schema.side_effect_mapping_table.state_mutators.ordered_keys",
    )
    handoff_protocol = _expect_mapping(
        schema.get("handoff_protocol"),
        path="schema.side_effect_mapping_table.handoff_protocol",
    )
    _assert_exact_keys(
        handoff_protocol,
        ("ordered_keys", "required_host_actions", "output_modes"),
        path="schema.side_effect_mapping_table.handoff_protocol",
    )
    handoff_protocol_keys = _expect_string_list(
        handoff_protocol.get("ordered_keys"),
        path="schema.side_effect_mapping_table.handoff_protocol.ordered_keys",
    )
    _assert_exact_list(
        handoff_protocol_keys,
        ("required_host_action", "artifact_keys", "resume_route", "output_mode"),
        path="schema.side_effect_mapping_table.handoff_protocol.ordered_keys",
    )
    schema["root_order"] = root_order
    schema["row_order"] = row_order
    schema["ordered_resolved_actions"] = ordered_resolved_actions
    schema["checkpoint_kinds"] = checkpoint_kinds
    schema["state_mutators"] = {"ordered_keys": state_mutator_keys}
    schema["handoff_protocol"] = {
        "ordered_keys": handoff_protocol_keys,
        "required_host_actions": _expect_string_list(
            handoff_protocol.get("required_host_actions"),
            path="schema.side_effect_mapping_table.handoff_protocol.required_host_actions",
        ),
        "output_modes": _expect_string_list(
            handoff_protocol.get("output_modes"),
            path="schema.side_effect_mapping_table.handoff_protocol.output_modes",
        ),
    }
    schema["terminalities"] = _expect_string_list(
        schema.get("terminalities"),
        path="schema.side_effect_mapping_table.terminalities",
    )
    schema["source_path"] = str(source_path)
    return schema


def _validate_host_message_templates_schema(
    schema: dict[str, Any],
    *,
    source_path: Path,
) -> dict[str, Any]:
    _assert_exact_keys(
        schema,
        (
            "schema_file_version",
            "asset_schema_version",
            "root_order",
            "default_locale",
            "locales",
            "lookup_order",
            "allowed_variables",
            "template_order",
            "match_kinds",
            "prompt_modes",
        ),
        path="schema.host_message_templates",
    )
    if schema.get("schema_file_version") != "1":
        raise DecisionTableError(
            "Unsupported host message templates schema_file_version: "
            f"{schema.get('schema_file_version')!r}"
        )
    default_locale = _expect_non_empty_string(
        schema.get("default_locale"),
        path="schema.host_message_templates.default_locale",
    )
    locales = _expect_string_list(
        schema.get("locales"),
        path="schema.host_message_templates.locales",
    )
    if default_locale not in locales:
        raise DecisionTableError("schema.host_message_templates.default_locale must exist in locales")
    root_order = _expect_string_list(
        schema.get("root_order"),
        path="schema.host_message_templates.root_order",
    )
    lookup_order = _expect_string_list(
        schema.get("lookup_order"),
        path="schema.host_message_templates.lookup_order",
    )
    _assert_exact_list(
        lookup_order,
        ("exact_reason_code", "reason_code_family_prefix", "prompt_mode_fallback"),
        path="schema.host_message_templates.lookup_order",
    )
    template_order = _expect_string_list(
        schema.get("template_order"),
        path="schema.host_message_templates.template_order",
    )
    _assert_exact_list(
        template_order,
        ("match_kind", "match_value", "prompt_modes", "locales"),
        path="schema.host_message_templates.template_order",
    )
    schema["default_locale"] = default_locale
    schema["locales"] = locales
    schema["root_order"] = root_order
    schema["lookup_order"] = lookup_order
    schema["allowed_variables"] = _expect_string_list(
        schema.get("allowed_variables"),
        path="schema.host_message_templates.allowed_variables",
    )
    schema["template_order"] = template_order
    schema["match_kinds"] = _expect_string_list(
        schema.get("match_kinds"),
        path="schema.host_message_templates.match_kinds",
    )
    schema["prompt_modes"] = _expect_string_list(
        schema.get("prompt_modes"),
        path="schema.host_message_templates.prompt_modes",
    )
    schema["source_path"] = str(source_path)
    return schema


def _validate_decision_tables(
    data: dict[str, Any],
    *,
    schema: dict[str, Any],
    signal_priority_schema: dict[str, Any],
    side_effect_mapping_schema: dict[str, Any],
    host_message_templates_schema: dict[str, Any],
    source_path: Path,
) -> dict[str, Any]:
    _assert_exact_keys(data, tuple(schema["root_order"]), path="root")
    if data.get("schema_version") != schema["asset_schema_version"]:
        raise DecisionTableError(
            f"Unsupported decision table schema_version: {data.get('schema_version')!r}"
        )
    if not isinstance(data.get("asset_version"), str) or not str(data["asset_version"]).strip():
        raise DecisionTableError("asset_version must be a non-empty string")

    invariants = _expect_mapping(data.get("invariants"), path="invariants")
    _assert_exact_keys(
        invariants,
        tuple(schema["invariants_required_true"]),
        path="invariants",
    )
    for key in schema["invariants_required_true"]:
        if invariants.get(key) is not True:
            raise DecisionTableError(f"{key} must be true")

    data["truth_statuses"] = _validate_truth_statuses(
        data.get("truth_statuses"),
        schema=schema["truth_statuses"],
    )
    data["quarantine_annotation_fields"] = _validate_const_string_list(
        data.get("quarantine_annotation_fields"),
        expected=schema["quarantine_annotation_fields"],
        path="quarantine_annotation_fields",
    )
    data["primary_failure_priority"] = _validate_const_string_list(
        data.get("primary_failure_priority"),
        expected=schema["primary_failure_priority"],
        path="primary_failure_priority",
    )
    data["primary_failure_families"] = _validate_primary_failure_families(
        data.get("primary_failure_families"),
        schema=schema["primary_failure_families"],
    )
    data["consult_readonly_contract"] = _validate_consult_contract(
        data.get("consult_readonly_contract"),
        schema=schema["consult_readonly_contract"],
    )
    data["best_proven_resume_target"] = _validate_best_proven_resume_target(
        data.get("best_proven_resume_target"),
        schema=schema["best_proven_resume_target"],
    )
    data["signal_priority_table"] = _validate_signal_priority_table(
        data.get("signal_priority_table"),
        schema=signal_priority_schema,
        source_path=source_path,
    )

    from .failure_recovery import (
        DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH,
        _validate_failure_recovery_table,
        load_failure_recovery_schema,
    )

    recovery_schema = load_failure_recovery_schema(DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH)
    embedded_recovery = _expect_mapping(
        data.get("failure_recovery_table"),
        path="failure_recovery_table",
    )
    data["failure_recovery_table"] = _validate_failure_recovery_table(
        deepcopy(dict(embedded_recovery)),
        schema=deepcopy(recovery_schema),
        decision_tables={
            "primary_failure_priority": data["primary_failure_priority"],
            "source_path": str(source_path),
        },
        source_path=source_path,
    )
    data["side_effect_mapping_table"] = _validate_side_effect_mapping_table(
        data.get("side_effect_mapping_table"),
        schema=side_effect_mapping_schema,
        source_path=source_path,
    )
    data["host_message_templates"] = _validate_host_message_templates(
        data.get("host_message_templates"),
        schema=host_message_templates_schema,
        source_path=source_path,
    )
    data["source_path"] = str(source_path)
    data["schema_source_path"] = schema["source_path"]
    return data


def _validate_truth_statuses(value: Any, *, schema: dict[str, Any]) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="truth_statuses")
    _assert_exact_keys(mapping, tuple(schema["ordered_statuses"]), path="truth_statuses")
    normalized: dict[str, Any] = {}
    for status in schema["ordered_statuses"]:
        row = _expect_mapping(mapping.get(status), path=f"truth_statuses.{status}")
        _assert_exact_keys(row, tuple(schema["row_order"]), path=f"truth_statuses.{status}")
        resolution_enabled = row.get("resolution_enabled")
        if not isinstance(resolution_enabled, bool):
            raise DecisionTableError(f"truth_statuses.{status}.resolution_enabled must be boolean")
        if resolution_enabled is not schema["resolution_enabled_by_status"][status]:
            raise DecisionTableError(
                "truth_statuses."
                f"{status}.resolution_enabled must be {schema['resolution_enabled_by_status'][status]}"
            )
        default_host_path = row.get("default_host_path")
        if not isinstance(default_host_path, str) or not default_host_path.strip():
            raise DecisionTableError(f"truth_statuses.{status}.default_host_path must be a non-empty string")
        normalized[status] = {
            "resolution_enabled": resolution_enabled,
            "default_host_path": default_host_path,
        }
    return normalized


def _validate_primary_failure_families(
    value: Any,
    *,
    schema: dict[str, Any],
) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="primary_failure_families")
    _assert_exact_keys(
        mapping,
        tuple(schema["ordered_families"]),
        path="primary_failure_families",
    )
    normalized: dict[str, Any] = {}
    for family in schema["ordered_families"]:
        row = _expect_mapping(mapping.get(family), path=f"primary_failure_families.{family}")
        _assert_exact_keys(
            row,
            tuple(schema["row_order"]),
            path=f"primary_failure_families.{family}",
        )
        members = _validate_const_string_list(
            row.get("members"),
            expected=schema["members_by_family"][family],
            path=f"primary_failure_families.{family}.members",
        )
        normalized[family] = {"members": members}
    return normalized


def _validate_consult_contract(value: Any, *, schema: dict[str, Any]) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="consult_readonly_contract")
    _assert_exact_keys(
        mapping,
        tuple(schema["ordered_keys"]),
        path="consult_readonly_contract",
    )
    required_when = _validate_const_string_list(
        mapping.get("required_when"),
        expected=schema["required_when"],
        path="consult_readonly_contract.required_when",
    )
    ignored_required_host_actions = _validate_const_string_list(
        mapping.get("ignored_required_host_actions"),
        expected=schema["ignored_required_host_actions"],
        path="consult_readonly_contract.ignored_required_host_actions",
    )

    required_fields = _expect_mapping(
        mapping.get("required_fields"),
        path="consult_readonly_contract.required_fields",
    )
    _assert_exact_keys(
        required_fields,
        tuple(schema["required_fields_order"]),
        path="consult_readonly_contract.required_fields",
    )

    normalized_fields: dict[str, Any] = {}
    for field_name in schema["required_fields_order"]:
        spec = schema["required_field_specs"][field_name]
        row = _expect_mapping(
            required_fields.get(field_name),
            path=f"consult_readonly_contract.required_fields.{field_name}",
        )
        _assert_exact_keys(
            row,
            tuple(spec["ordered_keys"]),
            path=f"consult_readonly_contract.required_fields.{field_name}",
        )
        normalized_field: dict[str, Any] = {}
        for key in spec["ordered_keys"]:
            if key in {"role", "equals"}:
                actual = row.get(key)
                expected = spec[key]
                if actual != expected:
                    raise DecisionTableError(
                        "consult_readonly_contract.required_fields."
                        f"{field_name}.{key} must be {expected}"
                    )
                normalized_field[key] = actual
            elif key == "includes":
                normalized_field[key] = _validate_const_string_list(
                    row.get("includes"),
                    expected=spec["includes"],
                    path=(
                        "consult_readonly_contract.required_fields."
                        f"{field_name}.includes"
                    ),
                )
            else:
                raise DecisionTableError(
                    "Unsupported consult_readonly_contract.required_fields schema key: "
                    f"{field_name}.{key}"
                )
        normalized_fields[field_name] = normalized_field

    return {
        "required_when": required_when,
        "ignored_required_host_actions": ignored_required_host_actions,
        "required_fields": normalized_fields,
    }


def _validate_best_proven_resume_target(
    value: Any,
    *,
    schema: dict[str, Any],
) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="best_proven_resume_target")
    _assert_exact_keys(
        mapping,
        tuple(schema["ordered_keys"]),
        path="best_proven_resume_target",
    )
    kinds = _validate_const_string_list(
        mapping.get("kinds"),
        expected=schema["kinds"],
        path="best_proven_resume_target.kinds",
    )
    proof_order = mapping.get("proof_order")
    if not isinstance(proof_order, list) or not proof_order:
        raise DecisionTableError("best_proven_resume_target.proof_order must be a non-empty list")
    if len(proof_order) != len(schema["proof_order"]):
        raise DecisionTableError(
            "best_proven_resume_target.proof_order must contain "
            f"{len(schema['proof_order'])} entries; got {len(proof_order)}"
        )

    normalized_proof_order: list[dict[str, Any]] = []
    for index, entry in enumerate(proof_order):
        row = _expect_mapping(entry, path=f"best_proven_resume_target.proof_order[{index}]")
        _assert_exact_keys(
            row,
            tuple(schema["proof_entry_order"]),
            path=f"best_proven_resume_target.proof_order[{index}]",
        )
        expected_entry = schema["proof_order"][index]
        kind = row.get("kind")
        if kind != expected_entry["kind"]:
            raise DecisionTableError(
                "best_proven_resume_target.proof_order"
                f"[{index}].kind must be {expected_entry['kind']}"
            )
        proof = _validate_const_string_list(
            row.get("proof"),
            expected=expected_entry["proof"],
            path=f"best_proven_resume_target.proof_order[{index}].proof",
        )
        normalized_proof_order.append({"kind": kind, "proof": proof})

    return {"kinds": kinds, "proof_order": normalized_proof_order}


def _validate_signal_priority_table(
    value: Any,
    *,
    schema: dict[str, Any],
    source_path: Path,
) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="signal_priority_table")
    _assert_exact_keys(mapping, tuple(schema["root_order"]), path="signal_priority_table")
    if mapping.get("schema_version") != schema["asset_schema_version"]:
        raise DecisionTableError(
            "Unsupported signal_priority_table.schema_version: "
            f"{mapping.get('schema_version')!r}"
        )
    asset_version = _expect_non_empty_string(
        mapping.get("asset_version"),
        path="signal_priority_table.asset_version",
    )
    origin_precedence = _validate_const_int_mapping(
        mapping.get("origin_precedence"),
        expected=schema["origin_precedence"],
        path="signal_priority_table.origin_precedence",
    )
    evidence_rank = _validate_const_int_mapping(
        mapping.get("evidence_rank"),
        expected=schema["evidence_rank"],
        path="signal_priority_table.evidence_rank",
    )
    rows = mapping.get("rows")
    if not isinstance(rows, list) or not rows:
        raise DecisionTableError("signal_priority_table.rows must be a non-empty list")
    if len(rows) != len(schema["ordered_signal_ids"]):
        raise DecisionTableError(
            "signal_priority_table.rows must contain "
            f"{len(schema['ordered_signal_ids'])} rows; got {len(rows)}"
        )

    normalized_rows: list[dict[str, Any]] = []
    for index, signal_id in enumerate(schema["ordered_signal_ids"]):
        row = _expect_mapping(rows[index], path=f"signal_priority_table.rows[{index}]")
        _assert_exact_keys(
            row,
            tuple(schema["row_order"]),
            path=f"signal_priority_table.rows[{index}]",
        )
        actual_signal_id = _expect_non_empty_string(
            row.get("signal_id"),
            path=f"signal_priority_table.rows[{index}].signal_id",
        )
        if actual_signal_id != signal_id:
            raise DecisionTableError(
                "signal_priority_table.rows must follow frozen order "
                f"{signal_id} at index {index}; got {actual_signal_id}"
            )
        enabled_checkpoint_kinds = _validate_ordered_subset_list(
            row.get("enabled_checkpoint_kinds"),
            allowed=schema["allowed_checkpoint_kinds"],
            path=f"signal_priority_table.rows[{index}].enabled_checkpoint_kinds",
        )
        signal_group = _expect_enum(
            row.get("signal_group"),
            schema["signal_groups"],
            path=f"signal_priority_table.rows[{index}].signal_group",
        )
        target_kind = _expect_enum(
            row.get("target_kind"),
            schema["target_kinds"],
            path=f"signal_priority_table.rows[{index}].target_kind",
        )
        target_slot = _expect_non_empty_string(
            row.get("target_slot"),
            path=f"signal_priority_table.rows[{index}].target_slot",
        )
        allowed_origins = _validate_ordered_subset_list(
            row.get("allowed_origins"),
            allowed=schema["ordered_origins"],
            path=f"signal_priority_table.rows[{index}].allowed_origins",
        )
        origin_evidence_cap = _validate_origin_evidence_cap(
            row.get("origin_evidence_cap"),
            allowed_origins=allowed_origins,
            allowed_evidence_ranks=schema["ordered_evidence_ranks"],
            path=f"signal_priority_table.rows[{index}].origin_evidence_cap",
        )
        mutually_exclusive_with = _validate_ordered_subset_list(
            _normalize_yaml_empty_list(row.get("mutually_exclusive_with")),
            allowed=schema["ordered_signal_ids"],
            path=f"signal_priority_table.rows[{index}].mutually_exclusive_with",
            allow_empty=True,
        )
        can_coexist_with = _validate_ordered_subset_list(
            _normalize_yaml_empty_list(row.get("can_coexist_with")),
            allowed=schema["ordered_signal_ids"],
            path=f"signal_priority_table.rows[{index}].can_coexist_with",
            allow_empty=True,
        )
        suppresses = _expect_string_list(
            _normalize_yaml_empty_list(row.get("suppresses")),
            path=f"signal_priority_table.rows[{index}].suppresses",
        )
        priority = _expect_positive_int(
            row.get("priority"),
            path=f"signal_priority_table.rows[{index}].priority",
        )
        winner_action = _expect_enum(
            row.get("winner_action"),
            schema["winner_actions"],
            path=f"signal_priority_table.rows[{index}].winner_action",
        )
        fallback_on_conflict = _expect_enum(
            row.get("fallback_on_conflict"),
            schema["fallback_on_conflicts"],
            path=f"signal_priority_table.rows[{index}].fallback_on_conflict",
        )
        reason_code = _expect_reason_code(
            row.get("reason_code"),
            path=f"signal_priority_table.rows[{index}].reason_code",
        )
        normalized_rows.append(
            {
                "signal_id": actual_signal_id,
                "enabled_checkpoint_kinds": enabled_checkpoint_kinds,
                "signal_group": signal_group,
                "target_kind": target_kind,
                "target_slot": target_slot,
                "allowed_origins": allowed_origins,
                "origin_evidence_cap": origin_evidence_cap,
                "mutually_exclusive_with": mutually_exclusive_with,
                "can_coexist_with": can_coexist_with,
                "suppresses": suppresses,
                "priority": priority,
                "winner_action": winner_action,
                "fallback_on_conflict": fallback_on_conflict,
                "reason_code": reason_code,
            }
        )

    return {
        "schema_version": mapping.get("schema_version"),
        "asset_version": asset_version,
        "origin_precedence": origin_precedence,
        "evidence_rank": evidence_rank,
        "rows": normalized_rows,
        "source_path": str(source_path),
        "schema_source_path": schema["source_path"],
    }


def _validate_side_effect_mapping_table(
    value: Any,
    *,
    schema: dict[str, Any],
    source_path: Path,
) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="side_effect_mapping_table")
    _assert_exact_keys(
        mapping,
        tuple(schema["root_order"]),
        path="side_effect_mapping_table",
    )
    if mapping.get("schema_version") != schema["asset_schema_version"]:
        raise DecisionTableError(
            "Unsupported side_effect_mapping_table.schema_version: "
            f"{mapping.get('schema_version')!r}"
        )
    asset_version = _expect_non_empty_string(
        mapping.get("asset_version"),
        path="side_effect_mapping_table.asset_version",
    )
    rows = mapping.get("rows")
    if not isinstance(rows, list) or not rows:
        raise DecisionTableError("side_effect_mapping_table.rows must be a non-empty list")
    if len(rows) != len(schema["ordered_resolved_actions"]):
        raise DecisionTableError(
            "side_effect_mapping_table.rows must contain "
            f"{len(schema['ordered_resolved_actions'])} rows; got {len(rows)}"
        )

    normalized_rows: list[dict[str, Any]] = []
    for index, resolved_action in enumerate(schema["ordered_resolved_actions"]):
        row = _expect_mapping(rows[index], path=f"side_effect_mapping_table.rows[{index}]")
        _assert_exact_keys(
            row,
            tuple(schema["row_order"]),
            path=f"side_effect_mapping_table.rows[{index}]",
        )
        actual_resolved_action = _expect_non_empty_string(
            row.get("resolved_action"),
            path=f"side_effect_mapping_table.rows[{index}].resolved_action",
        )
        if actual_resolved_action != resolved_action:
            raise DecisionTableError(
                "side_effect_mapping_table.rows must follow frozen order "
                f"{resolved_action} at index {index}; got {actual_resolved_action}"
            )
        checkpoint_kind = _expect_enum(
            row.get("checkpoint_kind"),
            schema["checkpoint_kinds"],
            path=f"side_effect_mapping_table.rows[{index}].checkpoint_kind",
        )
        state_mutators = _validate_state_mutators(
            row.get("state_mutators"),
            schema=schema["state_mutators"],
            path=f"side_effect_mapping_table.rows[{index}].state_mutators",
        )
        forbidden_state_effects = _expect_string_list(
            row.get("forbidden_state_effects"),
            path=f"side_effect_mapping_table.rows[{index}].forbidden_state_effects",
        )
        preserved_identity = _expect_string_list(
            row.get("preserved_identity"),
            path=f"side_effect_mapping_table.rows[{index}].preserved_identity",
        )
        handoff_protocol = _validate_side_effect_handoff_protocol(
            row.get("handoff_protocol"),
            schema=schema["handoff_protocol"],
            path=f"side_effect_mapping_table.rows[{index}].handoff_protocol",
        )
        terminality = _expect_enum(
            row.get("terminality"),
            schema["terminalities"],
            path=f"side_effect_mapping_table.rows[{index}].terminality",
        )
        reason_code = _expect_reason_code(
            row.get("reason_code"),
            path=f"side_effect_mapping_table.rows[{index}].reason_code",
        )
        normalized_rows.append(
            {
                "resolved_action": actual_resolved_action,
                "checkpoint_kind": checkpoint_kind,
                "state_mutators": state_mutators,
                "forbidden_state_effects": forbidden_state_effects,
                "preserved_identity": preserved_identity,
                "handoff_protocol": handoff_protocol,
                "terminality": terminality,
                "reason_code": reason_code,
            }
        )

    return {
        "schema_version": mapping.get("schema_version"),
        "asset_version": asset_version,
        "rows": normalized_rows,
        "source_path": str(source_path),
        "schema_source_path": schema["source_path"],
    }


def _validate_host_message_templates(
    value: Any,
    *,
    schema: dict[str, Any],
    source_path: Path,
) -> dict[str, Any]:
    mapping = _expect_mapping(value, path="host_message_templates")
    _assert_exact_keys(
        mapping,
        tuple(schema["root_order"]),
        path="host_message_templates",
    )
    if mapping.get("schema_version") != schema["asset_schema_version"]:
        raise DecisionTableError(
            "Unsupported host_message_templates.schema_version: "
            f"{mapping.get('schema_version')!r}"
        )
    asset_version = _expect_non_empty_string(
        mapping.get("asset_version"),
        path="host_message_templates.asset_version",
    )
    default_locale = _expect_enum(
        mapping.get("default_locale"),
        schema["locales"],
        path="host_message_templates.default_locale",
    )
    if default_locale != schema["default_locale"]:
        raise DecisionTableError(
            f"host_message_templates.default_locale must be {schema['default_locale']}"
        )
    lookup_order = _validate_const_string_list(
        mapping.get("lookup_order"),
        expected=schema["lookup_order"],
        path="host_message_templates.lookup_order",
    )
    allowed_variables = _validate_const_string_list(
        mapping.get("allowed_variables"),
        expected=schema["allowed_variables"],
        path="host_message_templates.allowed_variables",
    )
    templates = mapping.get("templates")
    if not isinstance(templates, list) or not templates:
        raise DecisionTableError("host_message_templates.templates must be a non-empty list")
    normalized_templates: list[dict[str, Any]] = []
    seen_matchers: set[tuple[str, str]] = set()
    for index, entry in enumerate(templates):
        row = _expect_mapping(entry, path=f"host_message_templates.templates[{index}]")
        _assert_exact_keys(
            row,
            tuple(schema["template_order"]),
            path=f"host_message_templates.templates[{index}]",
        )
        match_kind = _expect_enum(
            row.get("match_kind"),
            schema["match_kinds"],
            path=f"host_message_templates.templates[{index}].match_kind",
        )
        match_value = _expect_non_empty_string(
            row.get("match_value"),
            path=f"host_message_templates.templates[{index}].match_value",
        )
        matcher_key = (match_kind, match_value)
        if matcher_key in seen_matchers:
            raise DecisionTableError(
                f"Duplicate host_message_templates matcher: {match_kind}/{match_value}"
            )
        seen_matchers.add(matcher_key)
        prompt_modes = _validate_ordered_subset_list(
            row.get("prompt_modes"),
            allowed=schema["prompt_modes"],
            path=f"host_message_templates.templates[{index}].prompt_modes",
        )
        locales = _validate_localized_template_mapping(
            row.get("locales"),
            locales=schema["locales"],
            allowed_variables=allowed_variables,
            path=f"host_message_templates.templates[{index}].locales",
        )
        normalized_templates.append(
            {
                "match_kind": match_kind,
                "match_value": match_value,
                "prompt_modes": prompt_modes,
                "locales": locales,
            }
        )

    prompt_mode_fallbacks = _expect_mapping(
        mapping.get("prompt_mode_fallbacks"),
        path="host_message_templates.prompt_mode_fallbacks",
    )
    _assert_exact_keys(
        prompt_mode_fallbacks,
        tuple(schema["prompt_modes"]),
        path="host_message_templates.prompt_mode_fallbacks",
    )
    normalized_fallbacks: dict[str, dict[str, str]] = {}
    for prompt_mode in schema["prompt_modes"]:
        normalized_fallbacks[prompt_mode] = _validate_localized_template_mapping(
            prompt_mode_fallbacks.get(prompt_mode),
            locales=schema["locales"],
            allowed_variables=allowed_variables,
            path=f"host_message_templates.prompt_mode_fallbacks.{prompt_mode}",
        )

    return {
        "schema_version": mapping.get("schema_version"),
        "asset_version": asset_version,
        "default_locale": default_locale,
        "lookup_order": lookup_order,
        "allowed_variables": allowed_variables,
        "templates": normalized_templates,
        "prompt_mode_fallbacks": normalized_fallbacks,
        "source_path": str(source_path),
        "schema_source_path": schema["source_path"],
    }


def _validate_state_mutators(value: Any, *, schema: dict[str, Any], path: str) -> dict[str, list[str]]:
    mapping = _expect_mapping(value, path=path)
    _assert_exact_keys(mapping, tuple(schema["ordered_keys"]), path=path)
    normalized: dict[str, list[str]] = {}
    for key in schema["ordered_keys"]:
        normalized[key] = _expect_string_list(
            _normalize_yaml_empty_list(mapping.get(key)),
            path=f"{path}.{key}",
        )
    return normalized


def _validate_side_effect_handoff_protocol(
    value: Any,
    *,
    schema: dict[str, Any],
    path: str,
) -> dict[str, Any]:
    mapping = _expect_mapping(value, path=path)
    _assert_exact_keys(mapping, tuple(schema["ordered_keys"]), path=path)
    return {
        "required_host_action": _expect_enum(
            mapping.get("required_host_action"),
            schema["required_host_actions"],
            path=f"{path}.required_host_action",
        ),
        "artifact_keys": _expect_string_list(
            mapping.get("artifact_keys"),
            path=f"{path}.artifact_keys",
        ),
        "resume_route": _expect_non_empty_string(
            mapping.get("resume_route"),
            path=f"{path}.resume_route",
        ),
        "output_mode": _expect_enum(
            mapping.get("output_mode"),
            schema["output_modes"],
            path=f"{path}.output_mode",
        ),
    }


def _validate_localized_template_mapping(
    value: Any,
    *,
    locales: list[str],
    allowed_variables: list[str],
    path: str,
) -> dict[str, str]:
    mapping = _expect_mapping(value, path=path)
    _assert_exact_keys(mapping, tuple(locales), path=path)
    normalized: dict[str, str] = {}
    for locale in locales:
        text = _expect_non_empty_string(mapping.get(locale), path=f"{path}.{locale}")
        _validate_template_placeholders(
            text,
            allowed_variables=allowed_variables,
            path=f"{path}.{locale}",
        )
        normalized[locale] = text
    return normalized


def _validate_template_placeholders(
    template: str,
    *,
    allowed_variables: list[str],
    path: str,
) -> None:
    try:
        parsed = list(_FORMATTER.parse(template))
    except ValueError as exc:
        raise DecisionTableError(f"{path} contains invalid format syntax: {exc}") from exc
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if conversion is not None:
            raise DecisionTableError(f"{path} does not allow format conversion syntax")
        if format_spec:
            raise DecisionTableError(f"{path} does not allow format specifiers")
        if field_name not in allowed_variables:
            raise DecisionTableError(
                f"{path} contains unsupported placeholder: {field_name}"
            )


def _validate_origin_evidence_cap(
    value: Any,
    *,
    allowed_origins: list[str],
    allowed_evidence_ranks: list[str],
    path: str,
) -> dict[str, str]:
    mapping = _expect_mapping(value, path=path)
    _assert_exact_keys(mapping, tuple(allowed_origins), path=path)
    normalized: dict[str, str] = {}
    for origin in allowed_origins:
        normalized[origin] = _expect_enum(
            mapping.get(origin),
            allowed_evidence_ranks,
            path=f"{path}.{origin}",
        )
    return normalized


def _validate_const_string_list(value: Any, *, expected: list[str], path: str) -> list[str]:
    items = _expect_string_list(value, path=path)
    _assert_exact_list(items, tuple(expected), path=path)
    return items


def _validate_const_int_mapping(
    value: Any,
    *,
    expected: Mapping[str, int],
    path: str,
) -> dict[str, int]:
    mapping = _expect_mapping(value, path=path)
    _assert_exact_keys(mapping, tuple(expected.keys()), path=path)
    normalized: dict[str, int] = {}
    for key, expected_value in expected.items():
        actual_value = _expect_positive_int(mapping.get(key), path=f"{path}.{key}")
        if actual_value != expected_value:
            raise DecisionTableError(f"{path}.{key} must be {expected_value}")
        normalized[key] = actual_value
    return normalized


def _validate_ordered_subset_list(
    value: Any,
    *,
    allowed: list[str],
    path: str,
    allow_empty: bool = False,
) -> list[str]:
    items = _expect_string_list(value, path=path)
    if not items and not allow_empty:
        raise DecisionTableError(f"{path} must not be empty")
    for item in items:
        if item not in allowed:
            raise DecisionTableError(f"{path} contains unsupported value: {item}")
    expected_order = [candidate for candidate in allowed if candidate in items]
    if items != expected_order:
        wanted = ", ".join(expected_order)
        current = ", ".join(items)
        raise DecisionTableError(
            f"{path} must follow frozen subset order: {wanted}; got: {current}"
        )
    return items


def _expect_mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionTableError(f"Expected mapping at {path}")
    return value


def _expect_string_list(value: Any, *, path: str) -> list[str]:
    if not isinstance(value, list):
        raise DecisionTableError(f"Expected list at {path}")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise DecisionTableError(f"Expected non-empty string at {path}[{index}]")
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise DecisionTableError(f"Duplicate values are not allowed at {path}")
    return normalized


def _expect_non_empty_string(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionTableError(f"Expected non-empty string at {path}")
    return value


def _expect_int_mapping(value: Any, *, expected_keys: list[str], path: str) -> dict[str, int]:
    mapping = _expect_mapping(value, path=path)
    _assert_exact_keys(mapping, tuple(expected_keys), path=path)
    normalized: dict[str, int] = {}
    for key in expected_keys:
        normalized[key] = _expect_positive_int(mapping.get(key), path=f"{path}.{key}")
    return normalized


def _normalize_yaml_empty_list(value: Any) -> Any:
    if value == "[]":
        return []
    return value


def _expect_positive_int(value: Any, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DecisionTableError(f"Expected positive integer at {path}")
    return value


def _expect_reason_code(value: Any, *, path: str) -> str:
    text = _expect_non_empty_string(value, path=path)
    if not _REASON_CODE_RE.match(text):
        raise DecisionTableError(f"{path} must match frozen lexical form: {text!r}")
    return text


def _expect_enum(value: Any, allowed: list[str], *, path: str) -> str:
    if value not in allowed:
        raise DecisionTableError(f"{path} must be one of: {', '.join(allowed)}")
    return str(value)


def _assert_exact_keys(data: Mapping[str, Any], expected: tuple[str, ...], *, path: str) -> None:
    actual = tuple(data.keys())
    if actual != expected:
        wanted = ", ".join(expected)
        current = ", ".join(actual)
        raise DecisionTableError(f"{path} must contain keys in frozen order: {wanted}; got: {current}")


def _assert_exact_list(values: list[str], expected: tuple[str, ...], *, path: str) -> None:
    actual = tuple(values)
    if actual != expected:
        wanted = ", ".join(expected)
        current = ", ".join(actual)
        raise DecisionTableError(f"{path} must match frozen order: {wanted}; got: {current}")
