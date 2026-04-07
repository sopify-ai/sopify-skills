#!/usr/bin/env python3
"""Offline validation for the frozen fail-close decision table asset."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.decision_tables import DecisionTableError, load_default_decision_tables
from runtime.failure_recovery import (
    FailureRecoveryError,
    evaluate_case_matrix,
    load_default_failure_recovery_table,
    load_failure_recovery_case_matrix,
    load_failure_recovery_table,
)

DEFAULT_CASE_MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "fail_close_case_matrix.yaml"
DEFAULT_PYTEST_ENTRY_PATH = REPO_ROOT / "tests" / "pytest_entries" / "fail_close_contract_entry.py"


def _is_missing_default_case_matrix(case_matrix_arg: str, *, error_text: str) -> bool:
    if "Fail-close case matrix not found" not in error_text:
        return False
    try:
        requested_path = Path(case_matrix_arg).resolve()
    except OSError:
        return False
    return requested_path == DEFAULT_CASE_MATRIX_PATH.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a frozen fail-close decision table asset.")
    parser.add_argument(
        "--asset",
        default=None,
        help="Optional asset path. Defaults to the repository-default decision table asset.",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Optional schema path. Defaults to the repository-default decision table schema asset.",
    )
    parser.add_argument(
        "--recovery-asset",
        default=None,
        help="Optional failure recovery asset path. Defaults to the repository-default recovery asset.",
    )
    parser.add_argument(
        "--recovery-schema",
        default=None,
        help="Optional failure recovery schema path. Defaults to the repository-default recovery schema asset.",
    )
    parser.add_argument(
        "--case-matrix",
        default=str(DEFAULT_CASE_MATRIX_PATH),
        help="Optional fail-close case matrix path. Defaults to the repository-default case matrix.",
    )
    parser.add_argument(
        "--runner",
        choices=("auto", "native", "pytest"),
        default="auto",
        help="Validation runner. auto prefers pytest parametrize when available, then falls back to native.",
    )
    parser.add_argument(
        "--pytest-entry",
        default=str(DEFAULT_PYTEST_ENTRY_PATH),
        help="Pytest entry path for matrix-driven contract checks.",
    )
    return parser


def _resolve_runner(preferred: str) -> tuple[str, str | None]:
    if preferred == "native":
        return "native", None
    if preferred == "pytest":
        return "pytest", None
    if importlib.util.find_spec("pytest") is not None:
        return "pytest", None
    return "native", "pytest_not_installed"


def _load_and_evaluate_contracts(
    args: argparse.Namespace,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], list[dict[str, object]]]:
    if args.asset:
        from runtime.decision_tables import load_decision_tables

        tables = load_decision_tables(args.asset, schema_path=args.schema)
    else:
        tables = load_default_decision_tables(schema_path=args.schema)

    if args.recovery_asset:
        recovery_table = load_failure_recovery_table(
            args.recovery_asset,
            schema_path=args.recovery_schema,
            decision_tables_path=args.asset,
        )
    else:
        recovery_table = load_default_failure_recovery_table(
            schema_path=args.recovery_schema,
            decision_tables_path=args.asset,
        )

    case_matrix = load_failure_recovery_case_matrix(
        args.case_matrix,
        schema_path=args.recovery_schema,
    )
    results = evaluate_case_matrix(
        case_matrix,
        decision_tables=tables,
        recovery_table=recovery_table,
    )
    return tables, recovery_table, case_matrix, results


def _run_pytest_entry(args: argparse.Namespace) -> tuple[int, str]:
    entry_path = Path(args.pytest_entry).resolve()
    if not entry_path.is_file():
        raise FailureRecoveryError(f"Pytest entry not found: {entry_path}")

    env = os.environ.copy()
    env["FAIL_CLOSE_CASE_MATRIX"] = str(Path(args.case_matrix).resolve())
    if args.asset:
        env["FAIL_CLOSE_DECISION_ASSET"] = str(Path(args.asset).resolve())
    if args.schema:
        env["FAIL_CLOSE_DECISION_SCHEMA"] = str(Path(args.schema).resolve())
    if args.recovery_asset:
        env["FAIL_CLOSE_RECOVERY_ASSET"] = str(Path(args.recovery_asset).resolve())
    if args.recovery_schema:
        env["FAIL_CLOSE_RECOVERY_SCHEMA"] = str(Path(args.recovery_schema).resolve())

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(entry_path)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = "\n".join(
        fragment.rstrip()
        for fragment in (completed.stdout, completed.stderr)
        if fragment and fragment.strip()
    ).strip()
    return completed.returncode, combined_output


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    resolved_runner, fallback_reason = _resolve_runner(args.runner)

    try:
        if resolved_runner == "pytest":
            pytest_return_code, pytest_output = _run_pytest_entry(args)
            if pytest_return_code != 0:
                detail = f"; details: {pytest_output}" if pytest_output else ""
                raise FailureRecoveryError(
                    f"Pytest fail-close matrix entry failed at {Path(args.pytest_entry).resolve()}{detail}"
                )

        tables, recovery_table, case_matrix, results = _load_and_evaluate_contracts(args)
    except (DecisionTableError, FailureRecoveryError) as exc:
        print(f"Fail-close contract check failed: {exc}")
        if _is_missing_default_case_matrix(args.case_matrix, error_text=str(exc)):
            print(
                "Hint: default --case-matrix points to a development fixture. "
                "If this workspace is not bootstrapped yet, run bootstrap first "
                "or pass an explicit --case-matrix path."
            )
        return 1

    print(
        "Fail-close contract check passed: "
        f"decision_tables={tables['schema_version']} @ {tables['source_path']} "
        f"(schema: {tables['schema_source_path']}), "
        f"failure_recovery={recovery_table['schema_version']} @ {recovery_table['source_path']} "
        f"(schema: {recovery_table['schema_source_path']}), "
        f"case_matrix={case_matrix['source_path']} ({len(results)} cases), "
        f"runner={resolved_runner}"
    )
    if fallback_reason:
        print(f"Runner note: auto fallback to native ({fallback_reason}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
