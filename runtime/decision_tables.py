"""Loader and validator for frozen fail-close decision table assets."""

from __future__ import annotations

from copy import deepcopy
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Mapping

from ._yaml import YamlParseError, load_yaml


class DecisionTableError(ValueError):
    """Raised when the frozen decision table asset is malformed."""


DEFAULT_DECISION_TABLES_PATH = Path(__file__).resolve().parent / "contracts" / "decision_tables.yaml"
DEFAULT_DECISION_TABLES_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts" / "decision_tables.schema.json"
)


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
    raw_text = source_path.read_text(encoding="utf-8")
    data = _parse_yaml(raw_text)
    if not isinstance(data, dict):
        raise DecisionTableError(f"Decision table root must be a mapping: {source_path}")
    return _validate_decision_tables(
        deepcopy(data),
        schema=deepcopy(schema),
        source_path=source_path,
    )


def load_decision_tables_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate the independent decision table schema asset."""

    source_path = _resolve_existing_file(path, label="Decision table schema")
    raw_text = source_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except JSONDecodeError as exc:
        raise DecisionTableError(
            "Invalid decision table schema JSON "
            f"at {source_path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise DecisionTableError(f"Decision table schema root must be a mapping: {source_path}")
    return _validate_decision_table_schema(deepcopy(data), source_path=source_path)


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


def _validate_decision_tables(
    data: dict[str, Any],
    *,
    schema: dict[str, Any],
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


def _validate_const_string_list(value: Any, *, expected: list[str], path: str) -> list[str]:
    items = _expect_string_list(value, path=path)
    _assert_exact_list(items, tuple(expected), path=path)
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
