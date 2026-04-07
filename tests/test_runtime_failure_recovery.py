from __future__ import annotations

from tests.runtime_test_support import *

from runtime.decision_tables import load_default_decision_tables
from runtime.failure_recovery import (
    DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH,
    DEFAULT_FAILURE_RECOVERY_TABLE_PATH,
    FailureRecoveryError,
    evaluate_failure_recovery_case,
    evaluate_case_matrix,
    load_default_failure_recovery_table,
    load_failure_recovery_case_matrix,
    load_failure_recovery_table,
)

CASE_MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "fail_close_case_matrix.yaml"
REQUIRED_HOST_ACTIONS = [
    "answer_questions",
    "confirm_decision",
    "confirm_plan_package",
    "confirm_execute",
    "review_or_execute_plan",
]


def _build_base_recovery_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for action in REQUIRED_HOST_ACTIONS:
        rows.append(
            {
                "primary_failure_type": "non_stable_truth",
                "required_host_action": action,
                "fallback_action": "enter_blocking_recovery_branch",
                "prompt_mode": "request_state_recovery",
                "retry_policy": "manual_recovery_only",
                "reason_code": f"recovery.non_stable_truth.fail_closed.{action}",
                "unresolved_outcome_family": "fail_closed",
                "counts_toward_streak": True,
            }
        )

    for action in REQUIRED_HOST_ACTIONS:
        rows.append(
            {
                "primary_failure_type": "truth_layer_contract_invalid",
                "required_host_action": action,
                "fallback_action": "enter_blocking_recovery_branch",
                "prompt_mode": "request_state_recovery",
                "retry_policy": "manual_recovery_only",
                "reason_code": f"recovery.truth_layer_contract_invalid.fail_closed.{action}",
                "unresolved_outcome_family": "fail_closed",
                "counts_toward_streak": True,
            }
        )

    resolution_prompt_mode_by_action = {
        "answer_questions": "reask_answer_questions",
        "confirm_decision": "reask_confirm_decision",
        "confirm_plan_package": "reask_confirm_plan_package",
        "confirm_execute": "reask_confirm_execute",
        "review_or_execute_plan": "reask_plan_review",
    }
    for action in REQUIRED_HOST_ACTIONS:
        rows.append(
            {
                "primary_failure_type": "resolution_failure",
                "required_host_action": action,
                "fallback_action": "repeat_current_checkpoint",
                "prompt_mode": resolution_prompt_mode_by_action[action],
                "retry_policy": "allow_retry_after_user_input",
                "reason_code": f"recovery.resolution_failure.inspect_required.{action}",
                "unresolved_outcome_family": "inspect_required",
                "counts_toward_streak": True,
            }
        )

    for action in REQUIRED_HOST_ACTIONS:
        rows.append(
            {
                "primary_failure_type": "effect_contract_invalid",
                "required_host_action": action,
                "fallback_action": "block_side_effect_and_retry_when_safe",
                "prompt_mode": "safe_retry_after_contract_fix",
                "retry_policy": "retry_after_contract_fix",
                "reason_code": f"recovery.effect_contract_invalid.fail_closed.{action}",
                "unresolved_outcome_family": "fail_closed",
                "counts_toward_streak": True,
            }
        )
    return rows


def _render_recovery_yaml(rows: list[dict[str, object]]) -> str:
    lines = [
        "schema_version: failure_recovery.v1",
        "asset_version: test-fixture",
        "rows:",
    ]
    for row in rows:
        row_items = list(row.items())
        first_key, first_value = row_items[0]
        lines.append(f"  - {first_key}: {_yaml_scalar(first_value)}")
        for key, value in row_items[1:]:
            lines.append(f"    {key}: {_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_case_matrix_yaml(
    *,
    allowed_response_mode: str,
    expected_allowed_response_mode: str,
) -> str:
    return (
        f"""
schema_version: fail_close_case_matrix.v1
matrix_version: test-fixture
cases:
  - case_id: mode-validation-case
    checkpoint_id: mode-checkpoint
    required_host_action: answer_questions
    allowed_response_mode: {allowed_response_mode}
    failure_signals:
      - state_missing
    durable_identity: mode-identity
    expected:
      primary_failure_type: non_stable_truth
      primary_failure_member: state_missing
      secondary_failure_members: []
      fallback_action: enter_blocking_recovery_branch
      prompt_mode: request_state_recovery
      retry_policy: manual_recovery_only
      reason_code: recovery.non_stable_truth.fail_closed.answer_questions
      unresolved_outcome_family: fail_closed
      counts_toward_streak: true
      effective_allowed_response_mode: {expected_allowed_response_mode}
      streak_key:
        - mode-checkpoint
        - fail_closed
        - mode-identity
""".strip()
        + "\n"
    )


class FailureRecoveryTests(unittest.TestCase):
    def test_default_failure_recovery_table_loads(self) -> None:
        table = load_default_failure_recovery_table()
        self.assertEqual(table["schema_version"], "failure_recovery.v1")
        self.assertEqual(Path(table["source_path"]), DEFAULT_FAILURE_RECOVERY_TABLE_PATH.resolve())
        self.assertEqual(Path(table["schema_source_path"]), DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH.resolve())
        self.assertEqual(len(table["rows"]), 20)

    def test_case_matrix_evaluates_against_frozen_priority(self) -> None:
        decision_tables = load_default_decision_tables()
        recovery_table = load_default_failure_recovery_table()
        matrix = load_failure_recovery_case_matrix(CASE_MATRIX_PATH)
        results = evaluate_case_matrix(
            matrix,
            decision_tables=decision_tables,
            recovery_table=recovery_table,
        )
        self.assertEqual(len(results), 8)
        self.assertEqual(
            [item["case_id"] for item in results],
            [
                "A-1_explain_only_consult_guard",
                "A-2_decision_selection_with_suffix_text",
                "A-3_existing_plan_referent_analysis",
                "A-4_cancel_checkpoint_idempotent",
                "A-5_mixed_clause_conflict",
                "A-6_execution_confirm_state_conflict_abort",
                "A-7_question_like_retopic_baseline",
                "A-8_analysis_only_no_write_brake",
            ],
        )
        self.assertEqual(results[0]["primary_failure_type"], "non_stable_truth")
        self.assertEqual(results[0]["secondary_failure_members"], ["schema_mismatch"])
        self.assertEqual(results[4]["effective_allowed_response_mode"], "normal_runtime_followup")

    def test_recovery_table_rejects_allowed_response_mode_field(self) -> None:
        rows = _build_base_recovery_rows()
        first = rows[0]
        rows[0] = {
            "primary_failure_type": first["primary_failure_type"],
            "required_host_action": first["required_host_action"],
            "fallback_action": first["fallback_action"],
            "prompt_mode": first["prompt_mode"],
            "allowed_response_mode": "checkpoint_only",
            "retry_policy": first["retry_policy"],
            "reason_code": first["reason_code"],
            "unresolved_outcome_family": first["unresolved_outcome_family"],
            "counts_toward_streak": first["counts_toward_streak"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "failure_recovery_table.yaml"
            asset_path.write_text(_render_recovery_yaml(rows), encoding="utf-8")
            with self.assertRaisesRegex(
                FailureRecoveryError,
                r"failure_recovery\.rows\[0\] must contain keys in frozen order",
            ):
                load_failure_recovery_table(asset_path)

    def test_recovery_table_rejects_row_order_drift(self) -> None:
        rows = _build_base_recovery_rows()
        rows[0], rows[1] = rows[1], rows[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "failure_recovery_table.yaml"
            asset_path.write_text(_render_recovery_yaml(rows), encoding="utf-8")
            with self.assertRaisesRegex(
                FailureRecoveryError,
                r"failure_recovery\.rows must follow frozen order",
            ):
                load_failure_recovery_table(asset_path)

    def test_case_evaluator_rejects_unknown_failure_signals(self) -> None:
        decision_tables = load_default_decision_tables()
        recovery_table = load_default_failure_recovery_table()
        with self.assertRaisesRegex(FailureRecoveryError, r"unknown failure signal\(s\)"):
            evaluate_failure_recovery_case(
                {
                    "case_id": "unknown-signal",
                    "checkpoint_id": "clarification-main",
                    "required_host_action": "answer_questions",
                    "allowed_response_mode": "checkpoint_only",
                    "failure_signals": ["totally_unknown_signal"],
                    "durable_identity": "clarification-unknown",
                    "expected": {},
                },
                decision_tables=decision_tables,
                recovery_table=recovery_table,
            )

    def test_case_matrix_rejects_unknown_allowed_response_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix_path = Path(temp_dir) / "fail_close_case_matrix.yaml"
            matrix_path.write_text(
                _render_case_matrix_yaml(
                    allowed_response_mode="checkpoint_ony",
                    expected_allowed_response_mode="checkpoint_only",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                FailureRecoveryError,
                r"allowed_response_mode must be one of",
            ):
                load_failure_recovery_case_matrix(
                    matrix_path,
                    schema_path=DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH,
                )

    def test_case_matrix_rejects_unknown_expected_allowed_response_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            matrix_path = Path(temp_dir) / "fail_close_case_matrix.yaml"
            matrix_path.write_text(
                _render_case_matrix_yaml(
                    allowed_response_mode="checkpoint_only",
                    expected_allowed_response_mode="checkpoint_ony",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                FailureRecoveryError,
                r"effective_allowed_response_mode must be one of",
            ):
                load_failure_recovery_case_matrix(
                    matrix_path,
                    schema_path=DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH,
                )

    def test_offline_check_script_validates_recovery_assets_and_matrix(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check-fail-close-contract.py")],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(str(DEFAULT_FAILURE_RECOVERY_TABLE_PATH.resolve()), result.stdout)
        self.assertIn(str(CASE_MATRIX_PATH.resolve()), result.stdout)

    def test_offline_check_script_accepts_explicit_recovery_paths(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check-fail-close-contract.py"),
                "--recovery-asset",
                str(DEFAULT_FAILURE_RECOVERY_TABLE_PATH),
                "--recovery-schema",
                str(DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH),
                "--case-matrix",
                str(CASE_MATRIX_PATH),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(str(DEFAULT_FAILURE_RECOVERY_SCHEMA_PATH.resolve()), result.stdout)
