"""Offline loader and evaluator for frozen fail-close recovery assets."""

from __future__ import annotations

from copy import deepcopy
import json
from json import JSONDecodeError
from pathlib import Path
import re
from typing import Any, Mapping

from ._yaml import YamlParseError, load_yaml
from .decision_tables import (
    load_decision_tables,
    load_default_decision_tables,
)

DEFAULT_FAILURE_RECOVERY_TABLE_PATH = (
    Path(__file__).resolve().parent / "contracts" / "failure_recovery_table.yaml"
)
DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH = (
    Path(__file__).resolve().parent / "contracts" / "failure_recovery_table.schema.json"
)

_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}$")


class FailureRecoveryError(ValueError):
    """Raised when fail-close recovery assets or cases are malformed."""


def load_default_failure_recovery_table(
    *,
    schema_path: str | Path | None = None,
    decision_tables_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the repository-default failure recovery table asset."""

    return load_failure_recovery_table(
        DEFAULT_FAILURE_RECOVERY_TABLE_PATH,
        schema_path=schema_path,
        decision_tables_path=decision_tables_path,
    )


def load_failure_recovery_table(
    path: str | Path,
    *,
    schema_path: str | Path | None = None,
    decision_tables_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and validate a failure recovery asset against frozen schemas."""

    source_path = _resolve_existing_file(path, label="Failure recovery asset")
    schema = load_failure_recovery_schema(schema_path or DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH)
    decision_tables = (
        load_decision_tables(decision_tables_path)
        if decision_tables_path is not None
        else load_default_decision_tables()
    )
    raw_text = source_path.read_text(encoding="utf-8")
    data = _parse_yaml(raw_text)
    if not isinstance(data, dict):
        raise FailureRecoveryError(f"Failure recovery root must be a mapping: {source_path}")
    return _validate_failure_recovery_table(
        deepcopy(data),
        schema=deepcopy(schema),
        decision_tables=deepcopy(decision_tables),
        source_path=source_path,
    )


def load_failure_recovery_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate the independent failure recovery schema asset."""

    source_path = _resolve_existing_file(path, label="Failure recovery schema")
    raw_text = source_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except JSONDecodeError as exc:
        raise FailureRecoveryError(
            "Invalid failure recovery schema JSON "
            f"at {source_path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise FailureRecoveryError(f"Failure recovery schema root must be a mapping: {source_path}")
    return _validate_failure_recovery_schema(deepcopy(data), source_path=source_path)


def load_failure_recovery_case_matrix(
    path: str | Path,
    *,
    schema_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and validate a fail-close case matrix fixture."""

    source_path = _resolve_existing_file(path, label="Fail-close case matrix")
    schema = load_failure_recovery_schema(schema_path or DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH)
    raw_text = source_path.read_text(encoding="utf-8")
    data = _parse_yaml(raw_text)
    if not isinstance(data, dict):
        raise FailureRecoveryError(f"Fail-close case matrix root must be a mapping: {source_path}")
    return _validate_case_matrix(
        deepcopy(data),
        source_path=source_path,
        allowed_response_modes=schema["allowed_response_modes"],
    )


def evaluate_case_matrix(
    matrix: Mapping[str, Any],
    *,
    decision_tables: Mapping[str, Any],
    recovery_table: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate every fail-close case against frozen contracts."""

    results: list[dict[str, Any]] = []
    for case in matrix["cases"]:
        results.append(
            evaluate_failure_recovery_case(
                case,
                decision_tables=decision_tables,
                recovery_table=recovery_table,
            )
        )
    return results


def evaluate_failure_recovery_case(
    case: Mapping[str, Any],
    *,
    decision_tables: Mapping[str, Any],
    recovery_table: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate one fail-close case without reading runtime state."""

    failure_signals = list(case["failure_signals"])
    family_priority = list(decision_tables["primary_failure_priority"])
    family_members = {
        family: set(decision_tables["primary_failure_families"][family]["members"])
        for family in family_priority
    }
    known_failure_signals = _all_members(family_members)
    unknown_failure_signals = [member for member in failure_signals if member not in known_failure_signals]
    if unknown_failure_signals:
        raise FailureRecoveryError(
            f"Fail-close case {case['case_id']} contains unknown failure signal(s): "
            f"{', '.join(unknown_failure_signals)}"
        )

    family_hits: list[tuple[str, str]] = []
    secondary_failure_members: list[str] = []
    for family in family_priority:
        matching_members = [member for member in failure_signals if member in family_members[family]]
        if len(matching_members) > 1:
            raise FailureRecoveryError(
                "Fail-close case "
                f"{case['case_id']} contains multiple failure members in family {family}: "
                f"{', '.join(matching_members)}"
            )
        if not matching_members:
            continue
        selected = matching_members[0]
        family_hits.append((family, selected))

    if not family_hits:
        raise FailureRecoveryError(
            f"Fail-close case {case['case_id']} does not contain any known failure signal"
        )

    primary_failure_type, primary_failure_member = family_hits[0]
    for family, member in family_hits[1:]:
        secondary_failure_members.append(member)

    row = recovery_table["rows_by_key"].get((primary_failure_type, case["required_host_action"]))
    if row is None:
        raise FailureRecoveryError(
            "No recovery row for "
            f"primary_failure_type={primary_failure_type}, "
            f"required_host_action={case['required_host_action']}"
        )

    result = {
        "case_id": case["case_id"],
        "checkpoint_id": case["checkpoint_id"],
        "required_host_action": case["required_host_action"],
        "primary_failure_type": primary_failure_type,
        "primary_failure_member": primary_failure_member,
        "secondary_failure_members": secondary_failure_members,
        "fallback_action": row["fallback_action"],
        "prompt_mode": row["prompt_mode"],
        "retry_policy": row["retry_policy"],
        "reason_code": row["reason_code"],
        "unresolved_outcome_family": row["unresolved_outcome_family"],
        "counts_toward_streak": row["counts_toward_streak"],
        "effective_allowed_response_mode": case["allowed_response_mode"],
        "streak_key": (
            case["checkpoint_id"],
            row["unresolved_outcome_family"],
            case["durable_identity"],
        ),
    }

    expected = case["expected"]
    mismatches: list[str] = []
    for key, expected_value in expected.items():
        if result.get(key) != expected_value:
            mismatches.append(
                f"{key}: expected {expected_value!r}, got {result.get(key)!r}"
            )
    if mismatches:
        raise FailureRecoveryError(
            f"Fail-close case {case['case_id']} mismatched frozen recovery expectation: "
            + "; ".join(mismatches)
        )
    return result


def _resolve_existing_file(path: str | Path, *, label: str) -> Path:
    source_path = Path(path).resolve()
    if not source_path.exists():
        raise FailureRecoveryError(f"{label} not found: {source_path}")
    if not source_path.is_file():
        raise FailureRecoveryError(f"{label} is not a file: {source_path}")
    return source_path


def _parse_yaml(text: str) -> Any:
    try:
        return load_yaml(text)
    except YamlParseError as exc:
        raise FailureRecoveryError(str(exc)) from exc


def _validate_failure_recovery_schema(schema: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    _assert_exact_keys(
        schema,
        (
            "schema_file_version",
            "asset_schema_version",
            "root_order",
            "row_order",
            "required_host_actions",
            "fallback_actions",
            "prompt_modes",
            "allowed_response_modes",
            "retry_policies",
            "unresolved_outcome_families",
        ),
        path="failure_recovery.schema",
    )
    if schema.get("schema_file_version") != "1":
        raise FailureRecoveryError(
            f"Unsupported failure recovery schema_file_version: {schema.get('schema_file_version')!r}"
        )
    if not isinstance(schema.get("asset_schema_version"), str) or not str(
        schema["asset_schema_version"]
    ).strip():
        raise FailureRecoveryError("failure_recovery.schema.asset_schema_version must be a non-empty string")
    schema["root_order"] = _expect_string_list(schema.get("root_order"), path="failure_recovery.schema.root_order")
    schema["row_order"] = _expect_string_list(schema.get("row_order"), path="failure_recovery.schema.row_order")
    schema["required_host_actions"] = _expect_string_list(
        schema.get("required_host_actions"),
        path="failure_recovery.schema.required_host_actions",
    )
    schema["fallback_actions"] = _expect_string_list(
        schema.get("fallback_actions"),
        path="failure_recovery.schema.fallback_actions",
    )
    schema["prompt_modes"] = _expect_string_list(
        schema.get("prompt_modes"),
        path="failure_recovery.schema.prompt_modes",
    )
    schema["allowed_response_modes"] = _expect_string_list(
        schema.get("allowed_response_modes"),
        path="failure_recovery.schema.allowed_response_modes",
    )
    schema["retry_policies"] = _expect_string_list(
        schema.get("retry_policies"),
        path="failure_recovery.schema.retry_policies",
    )
    schema["unresolved_outcome_families"] = _expect_string_list(
        schema.get("unresolved_outcome_families"),
        path="failure_recovery.schema.unresolved_outcome_families",
    )
    schema["source_path"] = str(source_path)
    return schema


def _validate_failure_recovery_table(
    data: dict[str, Any],
    *,
    schema: dict[str, Any],
    decision_tables: dict[str, Any],
    source_path: Path,
) -> dict[str, Any]:
    _assert_exact_keys(data, tuple(schema["root_order"]), path="failure_recovery.root")
    if data.get("schema_version") != schema["asset_schema_version"]:
        raise FailureRecoveryError(
            f"Unsupported failure recovery schema_version: {data.get('schema_version')!r}"
        )
    if not isinstance(data.get("asset_version"), str) or not str(data["asset_version"]).strip():
        raise FailureRecoveryError("failure_recovery.asset_version must be a non-empty string")

    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise FailureRecoveryError("failure_recovery.rows must be a non-empty list")

    expected_failure_types = list(decision_tables["primary_failure_priority"])
    expected_row_count = len(expected_failure_types) * len(schema["required_host_actions"])
    if len(rows) != expected_row_count:
        raise FailureRecoveryError(
            f"failure_recovery.rows must contain {expected_row_count} rows; got {len(rows)}"
        )

    allowed_keys = tuple(schema["row_order"])
    expected_order = [
        (failure_type, action)
        for failure_type in expected_failure_types
        for action in schema["required_host_actions"]
    ]
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    normalized_rows: list[dict[str, Any]] = []

    for index, entry in enumerate(rows):
        row = _expect_mapping(entry, path=f"failure_recovery.rows[{index}]")
        _assert_exact_keys(row, allowed_keys, path=f"failure_recovery.rows[{index}]")
        primary_failure_type = _expect_enum(
            row.get("primary_failure_type"),
            expected_failure_types,
            path=f"failure_recovery.rows[{index}].primary_failure_type",
        )
        required_host_action = _expect_enum(
            row.get("required_host_action"),
            schema["required_host_actions"],
            path=f"failure_recovery.rows[{index}].required_host_action",
        )
        expected_failure_type, expected_action = expected_order[index]
        if (primary_failure_type, required_host_action) != (expected_failure_type, expected_action):
            raise FailureRecoveryError(
                "failure_recovery.rows must follow frozen order "
                f"{expected_failure_type}/{expected_action} at index {index}; got "
                f"{primary_failure_type}/{required_host_action}"
            )
        key = (primary_failure_type, required_host_action)
        if key in rows_by_key:
            raise FailureRecoveryError(
                "Duplicate recovery row for "
                f"primary_failure_type={primary_failure_type}, required_host_action={required_host_action}"
            )

        fallback_action = _expect_enum(
            row.get("fallback_action"),
            schema["fallback_actions"],
            path=f"failure_recovery.rows[{index}].fallback_action",
        )
        prompt_mode = _expect_enum(
            row.get("prompt_mode"),
            schema["prompt_modes"],
            path=f"failure_recovery.rows[{index}].prompt_mode",
        )
        retry_policy = _expect_enum(
            row.get("retry_policy"),
            schema["retry_policies"],
            path=f"failure_recovery.rows[{index}].retry_policy",
        )
        reason_code = row.get("reason_code")
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise FailureRecoveryError(f"failure_recovery.rows[{index}].reason_code must be a non-empty string")
        if not _REASON_CODE_RE.match(reason_code):
            raise FailureRecoveryError(
                f"failure_recovery.rows[{index}].reason_code must match frozen lexical form: {reason_code!r}"
            )
        unresolved_outcome_family = _expect_enum(
            row.get("unresolved_outcome_family"),
            schema["unresolved_outcome_families"],
            path=f"failure_recovery.rows[{index}].unresolved_outcome_family",
        )
        counts_toward_streak = row.get("counts_toward_streak")
        if not isinstance(counts_toward_streak, bool):
            raise FailureRecoveryError(
                f"failure_recovery.rows[{index}].counts_toward_streak must be boolean"
            )

        normalized_row = {
            "primary_failure_type": primary_failure_type,
            "required_host_action": required_host_action,
            "fallback_action": fallback_action,
            "prompt_mode": prompt_mode,
            "retry_policy": retry_policy,
            "reason_code": reason_code,
            "unresolved_outcome_family": unresolved_outcome_family,
            "counts_toward_streak": counts_toward_streak,
        }
        rows_by_key[key] = normalized_row
        normalized_rows.append(normalized_row)

    data["rows"] = normalized_rows
    data["rows_by_key"] = rows_by_key
    data["source_path"] = str(source_path)
    data["schema_source_path"] = schema["source_path"]
    data["decision_tables_source_path"] = decision_tables["source_path"]
    return data


def _validate_case_matrix(
    data: dict[str, Any],
    *,
    source_path: Path,
    allowed_response_modes: list[str],
) -> dict[str, Any]:
    _assert_exact_keys(
        data,
        ("schema_version", "matrix_version", "cases"),
        path="fail_close_case_matrix.root",
    )
    if data.get("schema_version") != "fail_close_case_matrix.v1":
        raise FailureRecoveryError(
            f"Unsupported fail_close_case_matrix.schema_version: {data.get('schema_version')!r}"
        )
    if not isinstance(data.get("matrix_version"), str) or not str(data["matrix_version"]).strip():
        raise FailureRecoveryError("fail_close_case_matrix.matrix_version must be a non-empty string")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise FailureRecoveryError("fail_close_case_matrix.cases must be a non-empty list")

    normalized_cases: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for index, entry in enumerate(cases):
        case = _expect_mapping(entry, path=f"fail_close_case_matrix.cases[{index}]")
        _assert_exact_keys(
            case,
            (
                "case_id",
                "checkpoint_id",
                "required_host_action",
                "allowed_response_mode",
                "failure_signals",
                "durable_identity",
                "expected",
            ),
            path=f"fail_close_case_matrix.cases[{index}]",
        )
        case_id = _expect_non_empty_string(case.get("case_id"), path=f"fail_close_case_matrix.cases[{index}].case_id")
        if case_id in seen_case_ids:
            raise FailureRecoveryError(f"Duplicate fail-close case id: {case_id}")
        seen_case_ids.add(case_id)
        checkpoint_id = _expect_non_empty_string(
            case.get("checkpoint_id"),
            path=f"fail_close_case_matrix.cases[{index}].checkpoint_id",
        )
        required_host_action = _expect_non_empty_string(
            case.get("required_host_action"),
            path=f"fail_close_case_matrix.cases[{index}].required_host_action",
        )
        allowed_response_mode = _expect_enum(
            case.get("allowed_response_mode"),
            allowed_response_modes,
            path=f"fail_close_case_matrix.cases[{index}].allowed_response_mode",
        )
        failure_signals = _expect_string_list(
            case.get("failure_signals"),
            path=f"fail_close_case_matrix.cases[{index}].failure_signals",
        )
        durable_identity = _expect_non_empty_string(
            case.get("durable_identity"),
            path=f"fail_close_case_matrix.cases[{index}].durable_identity",
        )
        expected = _expect_mapping(case.get("expected"), path=f"fail_close_case_matrix.cases[{index}].expected")
        _assert_exact_keys(
            expected,
            (
                "primary_failure_type",
                "primary_failure_member",
                "secondary_failure_members",
                "fallback_action",
                "prompt_mode",
                "retry_policy",
                "reason_code",
                "unresolved_outcome_family",
                "counts_toward_streak",
                "effective_allowed_response_mode",
                "streak_key",
            ),
            path=f"fail_close_case_matrix.cases[{index}].expected",
        )
        expected_streak_key = expected.get("streak_key")
        if not isinstance(expected_streak_key, list) or len(expected_streak_key) != 3:
            raise FailureRecoveryError(
                f"fail_close_case_matrix.cases[{index}].expected.streak_key must be a 3-item list"
            )
        normalized_expected = {
            "primary_failure_type": _expect_non_empty_string(
                expected.get("primary_failure_type"),
                path=f"fail_close_case_matrix.cases[{index}].expected.primary_failure_type",
            ),
            "primary_failure_member": _expect_non_empty_string(
                expected.get("primary_failure_member"),
                path=f"fail_close_case_matrix.cases[{index}].expected.primary_failure_member",
            ),
            "secondary_failure_members": _expect_string_list(
                _normalize_yaml_empty_list(expected.get("secondary_failure_members")),
                path=f"fail_close_case_matrix.cases[{index}].expected.secondary_failure_members",
            ),
            "fallback_action": _expect_non_empty_string(
                expected.get("fallback_action"),
                path=f"fail_close_case_matrix.cases[{index}].expected.fallback_action",
            ),
            "prompt_mode": _expect_non_empty_string(
                expected.get("prompt_mode"),
                path=f"fail_close_case_matrix.cases[{index}].expected.prompt_mode",
            ),
            "retry_policy": _expect_non_empty_string(
                expected.get("retry_policy"),
                path=f"fail_close_case_matrix.cases[{index}].expected.retry_policy",
            ),
            "reason_code": _expect_non_empty_string(
                expected.get("reason_code"),
                path=f"fail_close_case_matrix.cases[{index}].expected.reason_code",
            ),
            "unresolved_outcome_family": _expect_non_empty_string(
                expected.get("unresolved_outcome_family"),
                path=f"fail_close_case_matrix.cases[{index}].expected.unresolved_outcome_family",
            ),
            "counts_toward_streak": _expect_bool(
                expected.get("counts_toward_streak"),
                path=f"fail_close_case_matrix.cases[{index}].expected.counts_toward_streak",
            ),
            "effective_allowed_response_mode": _expect_enum(
                expected.get("effective_allowed_response_mode"),
                allowed_response_modes,
                path=(
                    "fail_close_case_matrix.cases"
                    f"[{index}].expected.effective_allowed_response_mode"
                ),
            ),
            "streak_key": tuple(_expect_string_list(expected_streak_key, path=f"fail_close_case_matrix.cases[{index}].expected.streak_key")),
        }
        normalized_cases.append(
            {
                "case_id": case_id,
                "checkpoint_id": checkpoint_id,
                "required_host_action": required_host_action,
                "allowed_response_mode": allowed_response_mode,
                "failure_signals": failure_signals,
                "durable_identity": durable_identity,
                "expected": normalized_expected,
            }
        )

    data["cases"] = normalized_cases
    data["source_path"] = str(source_path)
    return data


def _all_members(family_members: Mapping[str, set[str]]) -> set[str]:
    combined: set[str] = set()
    for members in family_members.values():
        combined.update(members)
    return combined


def _expect_mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FailureRecoveryError(f"Expected mapping at {path}")
    return value


def _expect_string_list(value: Any, *, path: str) -> list[str]:
    if not isinstance(value, list):
        raise FailureRecoveryError(f"Expected list at {path}")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise FailureRecoveryError(f"Expected non-empty string at {path}[{index}]")
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise FailureRecoveryError(f"Duplicate values are not allowed at {path}")
    return normalized


def _expect_non_empty_string(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FailureRecoveryError(f"Expected non-empty string at {path}")
    return value


def _normalize_yaml_empty_list(value: Any) -> Any:
    # runtime._yaml currently parses flow-style [] as the string "[]".
    # Normalize that parser artifact before applying strict list validation.
    if value == "[]":
        return []
    return value


def _expect_bool(value: Any, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise FailureRecoveryError(f"Expected boolean at {path}")
    return value


def _expect_enum(value: Any, allowed: list[str], *, path: str) -> str:
    if value not in allowed:
        raise FailureRecoveryError(f"{path} must be one of: {', '.join(allowed)}")
    return str(value)


def _assert_exact_keys(data: Mapping[str, Any], expected: tuple[str, ...], *, path: str) -> None:
    actual = tuple(data.keys())
    if actual != expected:
        wanted = ", ".join(expected)
        current = ", ".join(actual)
        raise FailureRecoveryError(f"{path} must contain keys in frozen order: {wanted}; got: {current}")
