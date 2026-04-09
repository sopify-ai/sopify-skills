from __future__ import annotations

from tests.runtime_test_support import *
from tests.runtime_test_support import _plan_dir_count, _prepare_ready_plan_state

from runtime.context_v1_scope import FORBIDDEN_V1_SIDE_EFFECTS
from runtime.decision_tables import load_default_decision_tables
from runtime.failure_recovery import load_failure_recovery_case_matrix

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample_invariant_gate_matrix.yaml"
FAIL_CLOSE_MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "fail_close_case_matrix.yaml"


def _load_sample_gate_matrix() -> dict[str, object]:
    payload = load_yaml(FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("sample invariant gate fixture must be a mapping")
    return payload


def _cases_by_id() -> dict[str, dict[str, object]]:
    matrix = _load_sample_gate_matrix()
    cases = matrix.get("cases")
    if not isinstance(cases, list):
        raise AssertionError("sample invariant gate fixture must contain cases")
    return {str(case["case_id"]): case for case in cases}


def _failure_cases_by_id() -> dict[str, dict[str, object]]:
    matrix = load_failure_recovery_case_matrix(FAIL_CLOSE_MATRIX_PATH)
    return {str(case["case_id"]): case for case in matrix["cases"]}


def _side_effect_rows_by_key() -> dict[tuple[str, str], dict[str, object]]:
    tables = load_default_decision_tables()
    rows = tables["side_effect_mapping_table"]["rows"]
    return {
        (str(row["checkpoint_kind"]), str(row["resolved_action"])): row
        for row in rows
    }


def _router_for_workspace(workspace: Path, *, active_plan: bool = False) -> Router:
    config = load_runtime_config(workspace)
    store = StateStore(config)
    store.ensure()
    if active_plan:
        plan_artifact = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
        store.set_current_plan(plan_artifact)
    return Router(config, state_store=store)


def _skills_for_workspace(workspace: Path) -> SkillRegistry:
    config = load_runtime_config(workspace)
    return SkillRegistry(config, user_home=workspace / "home").discover()


def _enter_plan_proposal_pending(workspace: Path):
    result = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
    assert result.handoff.required_host_action == "confirm_plan_package"
    return result


def _enter_decision_pending(workspace: Path):
    result = run_runtime(
        "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
        workspace_root=workspace,
        user_home=workspace / "home",
    )
    assert result.handoff.required_host_action == "confirm_decision"
    return result


class SampleInvariantAssetTests(unittest.TestCase):
    def test_fixture_covers_a1_to_a8_with_required_columns(self) -> None:
        matrix = _load_sample_gate_matrix()
        self.assertEqual(matrix["schema_version"], "sample_invariant_gate.v1")
        self.assertEqual(
            matrix["v1_gate_cases"],
            [
                "A-1_explain_only",
                "A-3_existing_plan_referent",
                "A-4_cancel_checkpoint",
                "A-5_mixed_clause_after_comma",
                "A-6_execution_confirm_state_conflict_evidence_gate",
                "A-8_analysis_only_no_write_process_semantic",
            ],
        )

        cases = list(_cases_by_id().values())
        self.assertEqual(
            [case["case_id"] for case in cases],
            [
                "A-1_explain_only",
                "A-2_decision_selection_with_suffix_text",
                "A-3_existing_plan_referent",
                "A-4_cancel_checkpoint",
                "A-5_mixed_clause_after_comma",
                "A-6_execution_confirm_state_conflict_evidence_gate",
                "A-7_question_like_retopic_baseline",
                "A-8_analysis_only_no_write_process_semantic",
            ],
        )

        replay_required = {
            "A-1_explain_only",
            "A-3_existing_plan_referent",
            "A-4_cancel_checkpoint",
            "A-5_mixed_clause_after_comma",
            "A-8_analysis_only_no_write_process_semantic",
        }
        for case in cases:
            self.assertTrue(case["positive_examples"], msg=case["case_id"])
            self.assertTrue(case["negative_examples"], msg=case["case_id"])
            self.assertTrue(case["boundary_examples"], msg=case["case_id"])
            self.assertTrue(case["forbidden_side_effects"], msg=case["case_id"])
            if case["case_id"] in replay_required:
                self.assertTrue(case.get("replay_examples"), msg=case["case_id"])

        a6 = _cases_by_id()["A-6_execution_confirm_state_conflict_evidence_gate"]
        self.assertIn("evidence_chain", a6)
        self.assertFalse(a6.get("replay_examples"))
        self.assertEqual(a6["evidence_chain"]["conflict_code"], "execution_confirm_review_checkpoint_conflict")

    def test_fixture_aligns_with_fail_close_matrix_and_effect_profiles(self) -> None:
        failure_cases = _failure_cases_by_id()
        rows_by_key = _side_effect_rows_by_key()

        for case in _cases_by_id().values():
            contract_ref = case["contract_ref"]
            failure_case = failure_cases[contract_ref["fail_close_case_id"]]
            self.assertEqual(failure_case["required_host_action"], contract_ref["required_host_action"])
            self.assertEqual(failure_case["allowed_response_mode"], contract_ref["allowed_response_mode"])

            effect_profile = case.get("effect_profile")
            if effect_profile is None:
                continue
            row = rows_by_key[(effect_profile["checkpoint_kind"], effect_profile["resolved_action"])]
            self.assertEqual(
                row["forbidden_state_effects"],
                effect_profile["forbidden_state_effects"],
            )
            self.assertTrue(set(effect_profile["forbidden_state_effects"]).issubset(FORBIDDEN_V1_SIDE_EFFECTS))


class SampleInvariantReplayTests(unittest.TestCase):
    def test_a1_explain_only_examples_hold_no_write_invariant(self) -> None:
        case = _cases_by_id()["A-1_explain_only"]

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            router = _router_for_workspace(workspace)
            skills = _skills_for_workspace(workspace)
            route = router.classify(case["positive_examples"][0]["utterance"], skills=skills)
            self.assertEqual(route.route_name, "consult")
            self.assertEqual(route.artifacts.get("consult_override_reason_code"), "consult_explain_only_override")

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            result = run_runtime(
                case["positive_examples"][1]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(result.route.route_name, "consult")
            self.assertEqual(result.handoff.required_host_action, "continue_host_consult")
            self.assertEqual(result.handoff.artifacts.get("consult_override_reason_code"), "consult_explain_only_override")
            self.assertIsNone(result.recovered_context.current_plan_proposal)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan_proposal.json").exists())
            self.assertEqual(_plan_dir_count(workspace), 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            router = _router_for_workspace(workspace)
            skills = _skills_for_workspace(workspace)
            negative = router.classify(case["negative_examples"][0]["utterance"], skills=skills)
            boundary = router.classify(case["boundary_examples"][0]["utterance"], skills=skills)
            self.assertNotEqual(negative.route_name, "consult")
            self.assertNotEqual(boundary.route_name, "consult")

    def test_a3_existing_plan_referent_examples_preserve_checkpoint_identity(self) -> None:
        case = _cases_by_id()["A-3_existing_plan_referent"]

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = _enter_plan_proposal_pending(workspace)
            original = pending.recovered_context.current_plan_proposal

            inspected = run_runtime(
                case["positive_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            assert original is not None
            updated = inspected.recovered_context.current_plan_proposal

            self.assertEqual(inspected.route.route_name, "plan_proposal_pending")
            self.assertEqual(inspected.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(inspected.handoff.required_host_action, "confirm_plan_package")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)
            self.assertEqual(_plan_dir_count(workspace), 0)

            boundary = run_runtime(
                case["boundary_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(boundary.route.route_name, "plan_proposal_pending")
            self.assertEqual(boundary.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(_plan_dir_count(workspace), 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = _enter_plan_proposal_pending(workspace)
            original = pending.recovered_context.current_plan_proposal

            revised = run_runtime(
                case["negative_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            revised_proposal = revised.recovered_context.current_plan_proposal
            assert original is not None
            self.assertEqual(revised.route.route_name, "plan_proposal_pending")
            self.assertNotEqual(revised_proposal.checkpoint_id, original.checkpoint_id)
            self.assertNotEqual(revised_proposal.reserved_plan_id, original.reserved_plan_id)
            self.assertNotEqual(revised_proposal.proposed_path, original.proposed_path)
            self.assertEqual(revised_proposal.request_text, "runtime gate receipt compaction")
            self.assertEqual(_plan_dir_count(workspace), 0)

    def test_a4_cancel_checkpoint_examples_clear_only_current_decision(self) -> None:
        case = _cases_by_id()["A-4_cancel_checkpoint"]

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_decision_pending(workspace)
            cancelled = run_runtime(
                case["positive_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            state_root = workspace / ".sopify-skills" / "state"

            self.assertEqual(cancelled.route.route_name, "cancel_active")
            self.assertFalse((state_root / "current_decision.json").exists())
            self.assertFalse((state_root / "current_plan_proposal.json").exists())
            self.assertFalse((state_root / "current_clarification.json").exists())
            self.assertEqual(_plan_dir_count(workspace), 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_decision_pending(workspace)
            negative = run_runtime(
                case["negative_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(negative.route.route_name, "decision_pending")
            self.assertEqual(negative.handoff.required_host_action, "confirm_decision")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_decision_pending(workspace)
            boundary = run_runtime(
                case["boundary_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(boundary.route.route_name, "decision_pending")
            self.assertEqual(boundary.handoff.required_host_action, "confirm_decision")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_a5_mixed_clause_examples_freeze_local_action_surface(self) -> None:
        case = _cases_by_id()["A-5_mixed_clause_after_comma"]

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = _enter_plan_proposal_pending(workspace)
            original = pending.recovered_context.current_plan_proposal

            revised = run_runtime(
                case["positive_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            revised_proposal = revised.recovered_context.current_plan_proposal
            assert original is not None

            self.assertEqual(revised.route.route_name, "plan_proposal_pending")
            self.assertEqual(revised.route.active_run_action, "revise_plan_proposal")
            self.assertEqual(revised_proposal.checkpoint_id, original.checkpoint_id)
            self.assertEqual(revised_proposal.proposed_path, original.proposed_path)
            self.assertIn("修订意见", revised_proposal.request_text)
            self.assertEqual(_plan_dir_count(workspace), 0)

            inspected = run_runtime(
                case["negative_examples"][0]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(inspected.route.active_run_action, "inspect_plan_proposal")

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_decision_pending(workspace)
            cancelled = run_runtime(
                case["positive_examples"][1]["utterance"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(cancelled.route.route_name, "cancel_active")
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_a8_analysis_only_process_semantic_routes_to_consult_without_write(self) -> None:
        case = _cases_by_id()["A-8_analysis_only_no_write_process_semantic"]

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            router = _router_for_workspace(workspace, active_plan=True)
            skills = _skills_for_workspace(workspace)
            positive = router.classify(case["positive_examples"][0]["utterance"], skills=skills)
            negative = router.classify(case["negative_examples"][0]["utterance"], skills=skills)

            self.assertEqual(positive.route_name, "consult")
            self.assertTrue(positive.should_recover_context)
            self.assertFalse(positive.should_create_plan)
            self.assertNotEqual(negative.route_name, "consult")


class SampleInvariantStateGateTests(unittest.TestCase):
    def test_confirm_path_materializes_plan_without_drifting_checkpoint_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = _enter_plan_proposal_pending(workspace)
            original = pending.recovered_context.current_plan_proposal

            confirmed = run_runtime(
                "继续",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            after_store = StateStore(load_runtime_config(workspace))
            current_plan = after_store.get_current_plan()

            assert original is not None
            self.assertEqual(confirmed.route.route_name, "plan_only")
            self.assertEqual(confirmed.handoff.required_host_action, "review_or_execute_plan")
            self.assertIsNotNone(confirmed.plan_artifact)
            self.assertIsNotNone(current_plan)
            self.assertIsNone(after_store.get_current_plan_proposal())
            self.assertEqual(current_plan.plan_id, original.reserved_plan_id)
            self.assertEqual(current_plan.path, confirmed.plan_artifact.path)
            self.assertEqual(_plan_dir_count(workspace), 1)
            self.assertTrue((workspace / current_plan.path / "tasks.md").exists())

    def test_a6_state_conflict_abort_converges_once_and_preserves_ready_plan(self) -> None:
        case = _cases_by_id()["A-6_execution_confirm_state_conflict_evidence_gate"]
        evidence = case["evidence_chain"]

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _, store, _ = _prepare_ready_plan_state(workspace)
            store.set_current_plan_proposal(
                PlanProposalState(
                    schema_version="1",
                    checkpoint_id="proposal-1",
                    request_text="继续",
                    analysis_summary="proposal",
                    proposed_level="standard",
                    proposed_path=".sopify-skills/plan/proposal",
                    estimated_task_count=2,
                    candidate_files=(),
                    topic_key="runtime",
                    reserved_plan_id="proposal-1",
                    resume_route="workflow",
                    capture_mode="off",
                    candidate_skill_ids=(),
                )
            )

            conflicted = run_runtime(
                evidence["inspect_input"],
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(conflicted.route.route_name, "state_conflict")
            self.assertEqual(conflicted.handoff.required_host_action, "resolve_state_conflict")
            self.assertEqual(conflicted.recovered_context.state_conflict["code"], evidence["conflict_code"])

        for abort_input in evidence["abort_inputs"]:
            with self.subTest(abort_input=abort_input):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)
                    _, store, _ = _prepare_ready_plan_state(workspace)
                    store.set_current_plan_proposal(
                        PlanProposalState(
                            schema_version="1",
                            checkpoint_id="proposal-1",
                            request_text="继续",
                            analysis_summary="proposal",
                            proposed_level="standard",
                            proposed_path=".sopify-skills/plan/proposal",
                            estimated_task_count=2,
                            candidate_files=(),
                            topic_key="runtime",
                            reserved_plan_id="proposal-1",
                            resume_route="workflow",
                            capture_mode="off",
                            candidate_skill_ids=(),
                        )
                    )

                    run_runtime("status", workspace_root=workspace, user_home=workspace / "home")
                    cleared = run_runtime(
                        abort_input,
                        workspace_root=workspace,
                        user_home=workspace / "home",
                    )
                    after_store = StateStore(load_runtime_config(workspace))
                    current_run = after_store.get_current_run()

                    self.assertEqual(cleared.route.route_name, "state_conflict")
                    self.assertEqual(cleared.route.active_run_action, "abort_conflict")
                    self.assertEqual(cleared.handoff.required_host_action, "confirm_execute")
                    self.assertFalse(cleared.recovered_context.state_conflict)
                    self.assertIsNone(after_store.get_current_plan_proposal())
                    self.assertIsNotNone(after_store.get_current_plan())
                    self.assertIsNotNone(current_run)
                    self.assertEqual(current_run.stage, evidence["post_abort_invariants"]["stable_stage"])
                    self.assertTrue(any("Conflict cleanup started via explicit abort" in note for note in cleared.notes))
                    self.assertTrue(any("Conflict cleanup completed" in note for note in cleared.notes))

                    followup = run_runtime(
                        evidence["post_abort_invariants"]["followup_input"],
                        workspace_root=workspace,
                        user_home=workspace / "home",
                    )
                    self.assertNotEqual(followup.route.route_name, "state_conflict")
                    self.assertFalse(followup.recovered_context.state_conflict)

    def test_legacy_pending_state_is_quarantined_with_reason_code_and_does_not_block_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            store.set_current_plan_proposal(
                PlanProposalState(
                    schema_version="1",
                    checkpoint_id="proposal-1",
                    request_text="继续",
                    analysis_summary="proposal",
                    proposed_level="standard",
                    proposed_path=".sopify-skills/plan/proposal",
                    estimated_task_count=2,
                    candidate_files=(),
                    topic_key="runtime",
                    reserved_plan_id="proposal-1",
                    resume_route="workflow",
                    capture_mode="off",
                    candidate_skill_ids=(),
                )
            )
            store.current_decision_path.write_text(
                '{\n'
                '  "schema_version": "2",\n'
                '  "decision_id": "decision-1",\n'
                '  "feature_key": "runtime",\n'
                '  "phase": "legacy_phase",\n'
                '  "status": "pending",\n'
                '  "decision_type": "design_choice",\n'
                '  "question": "继续哪个方案？",\n'
                '  "summary": "legacy phase should not block proposal",\n'
                '  "options": [{"option_id": "option_1", "title": "option 1", "summary": "summary"}]\n'
                '}\n',
                encoding="utf-8",
            )

            result = run_runtime(
                "为什么是这个方案？",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "plan_proposal_pending")
            self.assertEqual(result.handoff.required_host_action, "confirm_plan_package")
            self.assertIsNotNone(result.recovered_context.current_plan_proposal)
            self.assertIsNone(result.recovered_context.current_decision)
            self.assertTrue(result.recovered_context.quarantined_items)
            quarantined = result.recovered_context.quarantined_items[0]
            self.assertEqual(quarantined["state_kind"], "current_decision")
            self.assertEqual(quarantined["reason"], "phase_unsupported")
            self.assertIn("current_decision.json", quarantined["path"])
