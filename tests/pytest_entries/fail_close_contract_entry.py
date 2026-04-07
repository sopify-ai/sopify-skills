from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.decision_tables import load_decision_tables, load_default_decision_tables
from runtime.failure_recovery import (
    evaluate_failure_recovery_case,
    load_default_failure_recovery_table,
    load_failure_recovery_case_matrix,
    load_failure_recovery_table,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASE_MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "fail_close_case_matrix.yaml"


def _get_path_from_env(key: str) -> str | None:
    value = os.environ.get(key)
    if not value:
        return None
    return str(Path(value).resolve())


def _load_decision_tables_from_env() -> dict[str, object]:
    asset_path = _get_path_from_env("FAIL_CLOSE_DECISION_ASSET")
    schema_path = _get_path_from_env("FAIL_CLOSE_DECISION_SCHEMA")
    if asset_path:
        return load_decision_tables(asset_path, schema_path=schema_path)
    return load_default_decision_tables(schema_path=schema_path)


def _load_recovery_table_from_env() -> dict[str, object]:
    recovery_asset_path = _get_path_from_env("FAIL_CLOSE_RECOVERY_ASSET")
    recovery_schema_path = _get_path_from_env("FAIL_CLOSE_RECOVERY_SCHEMA")
    decision_asset_path = _get_path_from_env("FAIL_CLOSE_DECISION_ASSET")
    if recovery_asset_path:
        return load_failure_recovery_table(
            recovery_asset_path,
            schema_path=recovery_schema_path,
            decision_tables_path=decision_asset_path,
        )
    return load_default_failure_recovery_table(
        schema_path=recovery_schema_path,
        decision_tables_path=decision_asset_path,
    )


def _load_case_matrix_from_env() -> dict[str, object]:
    case_matrix_path = _get_path_from_env("FAIL_CLOSE_CASE_MATRIX") or str(
        DEFAULT_CASE_MATRIX_PATH.resolve()
    )
    recovery_schema_path = _get_path_from_env("FAIL_CLOSE_RECOVERY_SCHEMA")
    return load_failure_recovery_case_matrix(case_matrix_path, schema_path=recovery_schema_path)


_DECISION_TABLES = _load_decision_tables_from_env()
_RECOVERY_TABLE = _load_recovery_table_from_env()
_CASE_MATRIX = _load_case_matrix_from_env()


@pytest.mark.parametrize(
    "case",
    _CASE_MATRIX["cases"],
    ids=[case["case_id"] for case in _CASE_MATRIX["cases"]],
)
def test_fail_close_case_matrix_contract(case: dict[str, object]) -> None:
    result = evaluate_failure_recovery_case(
        case,
        decision_tables=_DECISION_TABLES,
        recovery_table=_RECOVERY_TABLE,
    )
    expected = case["expected"]
    for key, expected_value in expected.items():
        assert result[key] == expected_value
