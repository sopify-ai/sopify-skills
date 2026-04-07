from __future__ import annotations

from tests.runtime_test_support import *

from runtime.decision_tables import (
    DEFAULT_DECISION_TABLES_PATH,
    DEFAULT_DECISION_TABLES_SCHEMA_PATH,
    DecisionTableError,
    load_decision_tables,
    load_default_decision_tables,
)

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "context_fail_close_contract.yaml"


class DecisionTablesTests(unittest.TestCase):
    def test_default_asset_loads(self) -> None:
        tables = load_default_decision_tables()
        self.assertEqual(tables["schema_version"], "decision_tables.v1")
        self.assertEqual(
            tables["primary_failure_priority"],
            [
                "non_stable_truth",
                "truth_layer_contract_invalid",
                "resolution_failure",
                "effect_contract_invalid",
            ],
        )
        self.assertEqual(
            tables["best_proven_resume_target"]["kinds"],
            ["checkpoint", "plan_review", "workflow_safe_start"],
        )
        self.assertEqual(Path(tables["source_path"]), DEFAULT_DECISION_TABLES_PATH.resolve())
        self.assertEqual(Path(tables["schema_source_path"]), DEFAULT_DECISION_TABLES_SCHEMA_PATH.resolve())

    def test_fixture_asset_loads(self) -> None:
        tables = load_decision_tables(FIXTURE_PATH)
        self.assertEqual(Path(tables["source_path"]), FIXTURE_PATH.resolve())

    def test_reordered_resume_target_proof_is_rejected(self) -> None:
        original = FIXTURE_PATH.read_text(encoding="utf-8")
        reordered = original.replace(
            """    - kind: checkpoint
      proof:
        - current_handoff.required_host_action
        - matching_checkpoint_state
        - durable_identity
    - kind: checkpoint
      proof:
        - current_run.stage
        - matching_durable_identities
""",
            """    - kind: checkpoint
      proof:
        - current_run.stage
        - matching_durable_identities
    - kind: checkpoint
      proof:
        - current_handoff.required_host_action
        - matching_checkpoint_state
        - durable_identity
""",
            1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asset = Path(temp_dir) / "decision_tables.yaml"
            asset.write_text(reordered, encoding="utf-8")
            with self.assertRaisesRegex(
                DecisionTableError,
                r"best_proven_resume_target\.proof_order\[0\]\.proof",
            ):
                load_decision_tables(asset)

    def test_custom_schema_drift_is_rejected(self) -> None:
        schema = json.loads(DEFAULT_DECISION_TABLES_SCHEMA_PATH.read_text(encoding="utf-8"))
        schema["best_proven_resume_target"]["proof_order"][0]["proof"] = [
            "matching_checkpoint_state",
            "current_handoff.required_host_action",
            "durable_identity",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            schema_path = Path(temp_dir) / "decision_tables.schema.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(
                DecisionTableError,
                r"best_proven_resume_target\.proof_order\[0\]\.proof",
            ):
                load_decision_tables(FIXTURE_PATH, schema_path=schema_path)

    def test_missing_truth_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset = Path(temp_dir) / "decision_tables.yaml"
            asset.write_text(
                """
schema_version: decision_tables.v1
asset_version: test
invariants:
  stable_truth_required_for_resolution: true
  consult_readonly_default_deny: true
  transcript_recovery_forbidden: true
truth_statuses:
  stable:
    resolution_enabled: true
    default_host_path: continue_current_machine_contract
  state_missing:
    resolution_enabled: false
    default_host_path: failure_recovery_or_blocking_branch
  contract_invalid:
    resolution_enabled: false
    default_host_path: failure_recovery_or_blocking_branch
quarantine_annotation_fields:
  - state_kind
  - path
  - scope
  - active_chain_relevance
  - promotion_decision
  - reason_code
  - durable_identity_ref
primary_failure_priority:
  - non_stable_truth
  - truth_layer_contract_invalid
  - resolution_failure
  - effect_contract_invalid
primary_failure_families:
  non_stable_truth:
    members:
      - state_missing
      - state_conflicted
  truth_layer_contract_invalid:
    members:
      - gate_contract_invalid
      - handoff_contract_invalid
      - checkpoint_contract_invalid
      - action_projection_contract_invalid
  resolution_failure:
    members:
      - no_match
      - ambiguous
      - malformed_input
      - semantic_unavailable
      - context_budget_exceeded
  effect_contract_invalid:
    members:
      - schema_mismatch
      - version_mismatch
      - missing_required_field
      - unsupported_transition
consult_readonly_contract:
  required_when:
    - side_effect_mapping_routes_to_continue_host_consult
    - consult_exit_is_under_validation
  ignored_required_host_actions:
    - confirm_decision
    - confirm_plan_package
    - confirm_execute
    - answer_questions
    - review_or_execute_plan
  required_fields:
    required_host_action:
      role: echoed_assertion
      equals: continue_host_consult
    allowed_response_mode:
      role: echoed_assertion
      equals: normal_runtime_followup
    resume_route:
      role: echoed_assertion
    preserved_identity:
      role: echoed_assertion
    context_sufficiency:
      role: consult_local_constraint
      equals: sufficient
    forbidden_effects:
      role: consult_local_constraint
      includes:
        - checkpoint_submission
        - run_stage_advance
        - plan_materialization
        - execution
best_proven_resume_target:
  kinds:
    - checkpoint
    - plan_review
    - workflow_safe_start
  proof_order:
    - kind: checkpoint
      proof:
        - current_handoff.required_host_action
        - matching_checkpoint_state
        - durable_identity
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(DecisionTableError):
                load_decision_tables(asset)

    def test_consult_contract_requires_forbidden_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset = Path(temp_dir) / "decision_tables.yaml"
            asset.write_text(
                """
schema_version: decision_tables.v1
asset_version: test
invariants:
  stable_truth_required_for_resolution: true
  consult_readonly_default_deny: true
  transcript_recovery_forbidden: true
truth_statuses:
  stable:
    resolution_enabled: true
    default_host_path: continue_current_machine_contract
  state_missing:
    resolution_enabled: false
    default_host_path: failure_recovery_or_blocking_branch
  state_conflicted:
    resolution_enabled: false
    default_host_path: failure_recovery_or_blocking_branch
  contract_invalid:
    resolution_enabled: false
    default_host_path: failure_recovery_or_blocking_branch
quarantine_annotation_fields:
  - state_kind
  - path
  - scope
  - active_chain_relevance
  - promotion_decision
  - reason_code
  - durable_identity_ref
primary_failure_priority:
  - non_stable_truth
  - truth_layer_contract_invalid
  - resolution_failure
  - effect_contract_invalid
primary_failure_families:
  non_stable_truth:
    members:
      - state_missing
      - state_conflicted
  truth_layer_contract_invalid:
    members:
      - gate_contract_invalid
      - handoff_contract_invalid
      - checkpoint_contract_invalid
      - action_projection_contract_invalid
  resolution_failure:
    members:
      - no_match
      - ambiguous
      - malformed_input
      - semantic_unavailable
      - context_budget_exceeded
  effect_contract_invalid:
    members:
      - schema_mismatch
      - version_mismatch
      - missing_required_field
      - unsupported_transition
consult_readonly_contract:
  required_when:
    - side_effect_mapping_routes_to_continue_host_consult
    - consult_exit_is_under_validation
  ignored_required_host_actions:
    - confirm_decision
    - confirm_plan_package
    - confirm_execute
    - answer_questions
    - review_or_execute_plan
  required_fields:
    required_host_action:
      role: echoed_assertion
      equals: continue_host_consult
    allowed_response_mode:
      role: echoed_assertion
      equals: normal_runtime_followup
    resume_route:
      role: echoed_assertion
    preserved_identity:
      role: echoed_assertion
    context_sufficiency:
      role: consult_local_constraint
      equals: sufficient
    forbidden_effects:
      role: consult_local_constraint
      includes:
        - checkpoint_submission
        - run_stage_advance
best_proven_resume_target:
  kinds:
    - checkpoint
    - plan_review
    - workflow_safe_start
  proof_order:
    - kind: checkpoint
      proof:
        - current_handoff.required_host_action
        - matching_checkpoint_state
        - durable_identity
""".strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(DecisionTableError):
                load_decision_tables(asset)

    def test_offline_check_script_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check-fail-close-contract.py")],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Fail-close contract check passed:", result.stdout)
        self.assertIn(str(DEFAULT_DECISION_TABLES_SCHEMA_PATH.resolve()), result.stdout)

    def test_offline_check_script_accepts_fixture_asset(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check-fail-close-contract.py"),
                "--asset",
                str(FIXTURE_PATH),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(str(FIXTURE_PATH), result.stdout)

    def test_offline_check_script_accepts_explicit_schema(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check-fail-close-contract.py"),
                "--asset",
                str(FIXTURE_PATH),
                "--schema",
                str(DEFAULT_DECISION_TABLES_SCHEMA_PATH),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(str(DEFAULT_DECISION_TABLES_SCHEMA_PATH.resolve()), result.stdout)
