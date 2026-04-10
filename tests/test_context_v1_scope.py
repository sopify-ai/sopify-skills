from __future__ import annotations

from unittest.mock import patch

from tests.runtime_test_support import *
from tests.runtime_test_support import _prepare_ready_plan_state

from runtime.action_projection import ActionProjectionError, build_action_projection
from runtime.context_builder import build_local_context
from runtime.context_v1_scope import (
    ALLOWED_V1_STATE_EFFECTS,
    CHECKPOINT_C_LOCK_PREREQUISITES,
    FORBIDDEN_V1_SIDE_EFFECTS,
    MAX_LOCAL_CONTEXT_USER_MESSAGES,
    ContextV1ScopeError,
    SUPPORTED_CHECKPOINT_KINDS_V1,
    V1_COMPATIBILITY_RULES,
    V1_IMPLEMENTATION_CANDIDATE_FILES,
    V1_IMPLEMENTATION_RUNTIME_FILES,
    V1_IMPLEMENTATION_TEST_FILES,
    V1_OBSERVE_ONLY_FILES,
    V1_READY_TO_START_LOCAL_REQUIREMENTS,
    V1_READY_TO_START_REQUIRED_CHECKPOINTS,
    V1_ROLLBACK_POLICY,
    V1_ROLLOUT_POLICY,
    assert_v1_implementation_file_map,
    assert_v1_ready_to_start,
    classify_v1_scope_path,
    validate_decision_tables_v1_scope,
)
from runtime.deterministic_guard import (
    CHECKPOINT_ONLY,
    NORMAL_RUNTIME_FOLLOWUP,
    evaluate_deterministic_guard,
    expected_allowed_response_mode,
)
from runtime.decision_tables import (
    DEFAULT_DECISION_TABLES_PATH,
    DecisionTableError,
    load_decision_tables,
    load_default_decision_tables,
)
from runtime.resolution_planner import (
    ResolutionPlanner,
    ResolutionPlannerError,
    build_resolution_planner,
    supports_resolution_planner,
)
from runtime.sidecar_classifier_boundary import (
    SidecarClassifierBoundaryError,
    build_sidecar_classifier_boundary,
    supports_sidecar_classifier_boundary,
)
from runtime.vnext_phase_boundary import (
    VNextPhaseBoundaryError,
    build_vnext_phase_boundary,
    supports_vnext_phase_boundary,
)


class ContextV1ScopeTests(unittest.TestCase):
    def test_default_decision_tables_fit_current_v1_scope(self) -> None:
        tables = load_default_decision_tables()
        validate_decision_tables_v1_scope(tables)

        rows = tables["side_effect_mapping_table"]["rows"]
        checkpoint_kinds = sorted({row["checkpoint_kind"] for row in rows})
        allowed_effects = sorted(
            {
                effect
                for row in rows
                for bucket in row["state_mutators"].values()
                for effect in bucket
            }
        )
        forbidden_effects = sorted(
            {
                effect
                for row in rows
                for effect in row["forbidden_state_effects"]
            }
        )

        self.assertEqual(checkpoint_kinds, sorted(SUPPORTED_CHECKPOINT_KINDS_V1))
        self.assertEqual(allowed_effects, sorted(ALLOWED_V1_STATE_EFFECTS))
        self.assertEqual(forbidden_effects, sorted(FORBIDDEN_V1_SIDE_EFFECTS))

    def test_unknown_checkpoint_kind_is_rejected(self) -> None:
        tables = load_default_decision_tables()
        tables["side_effect_mapping_table"]["rows"][0]["checkpoint_kind"] = "answer_questions"

        with self.assertRaisesRegex(ContextV1ScopeError, r"Unsupported V1 checkpoint_kind"):
            validate_decision_tables_v1_scope(tables)

    def test_unknown_allowed_state_effect_is_rejected(self) -> None:
        tables = load_default_decision_tables()
        tables["side_effect_mapping_table"]["rows"][0]["state_mutators"]["update"] = ["current_handoff"]

        with self.assertRaisesRegex(ContextV1ScopeError, r"Unsupported allowed V1 state effect"):
            validate_decision_tables_v1_scope(tables)

    def test_unknown_forbidden_state_effect_is_rejected(self) -> None:
        tables = load_default_decision_tables()
        tables["side_effect_mapping_table"]["rows"][0]["forbidden_state_effects"].append(
            "delete_plan_history"
        )

        with self.assertRaisesRegex(ContextV1ScopeError, r"Unsupported forbidden V1 state effect"):
            validate_decision_tables_v1_scope(tables)

    def test_checkpoint_c_file_map_is_frozen_into_candidate_and_observe_only_sets(self) -> None:
        self.assertEqual(
            V1_IMPLEMENTATION_RUNTIME_FILES,
            (
                "runtime/action_projection.py",
                "runtime/context_builder.py",
                "runtime/context_v1_scope.py",
                "runtime/deterministic_guard.py",
                "runtime/handoff.py",
                "runtime/resolution_planner.py",
            ),
        )
        self.assertEqual(
            V1_IMPLEMENTATION_TEST_FILES,
            (
                "tests/test_context_v1_scope.py",
                "tests/test_runtime_engine.py",
            ),
        )
        self.assertEqual(
            V1_OBSERVE_ONLY_FILES,
            (
                "runtime/contracts/decision_tables.schema.json",
                "runtime/contracts/decision_tables.yaml",
                "runtime/engine.py",
                "runtime/failure_recovery.py",
                "runtime/sidecar_classifier_boundary.py",
                "runtime/vnext_phase_boundary.py",
                "tests/fixtures/sample_invariant_gate_matrix.yaml",
                "tests/test_runtime_sample_invariant_gate.py",
            ),
        )
        self.assertEqual(
            V1_IMPLEMENTATION_CANDIDATE_FILES,
            (*V1_IMPLEMENTATION_RUNTIME_FILES, *V1_IMPLEMENTATION_TEST_FILES),
        )
        self.assertEqual(CHECKPOINT_C_LOCK_PREREQUISITES, ("Checkpoint B",))
        self.assertEqual(V1_READY_TO_START_REQUIRED_CHECKPOINTS, ("Checkpoint A", "Checkpoint B"))
        self.assertEqual(
            V1_READY_TO_START_LOCAL_REQUIREMENTS,
            ("file_map_frozen", "scope_guard_tests_green", "compatibility_rules_frozen"),
        )
        self.assertEqual(
            V1_COMPATIBILITY_RULES,
            (
                "required_host_action_contract_additive_only",
                "execution_gate_core_fields_and_gate_status_stable",
                "decision_tables_v1_assets_readonly_during_scope_finalize",
                "sample_invariant_gate_assets_readonly_after_checkpoint_b",
            ),
        )
        self.assertEqual(
            V1_ROLLOUT_POLICY,
            (
                "lock_file_map_after_checkpoint_b",
                "limit_runtime_edits_to_candidate_file_map",
                "treat_observe_only_files_as_readonly_reference_surfaces",
            ),
        )
        self.assertEqual(
            V1_ROLLBACK_POLICY,
            (
                "revert_candidate_file_changes_to_checkpoint_b_guardrail_baseline_on_scope_violation",
                "do_not_reopen_observe_only_contract_assets_in_scope_finalize",
                "move_out_of_scope_contract_expansion_to_followup_branch",
            ),
        )

    def test_classify_v1_scope_path_marks_candidate_and_observe_only_surfaces(self) -> None:
        self.assertEqual(classify_v1_scope_path("runtime/handoff.py"), "candidate_runtime")
        self.assertEqual(classify_v1_scope_path("./tests/test_runtime_engine.py"), "candidate_test")
        self.assertEqual(
            classify_v1_scope_path("tests/fixtures/sample_invariant_gate_matrix.yaml"),
            "observe_only",
        )
        self.assertEqual(classify_v1_scope_path("runtime/decision.py"), "out_of_scope")

    def test_v1_file_map_requires_checkpoint_b_before_allowlist_lock(self) -> None:
        with self.assertRaisesRegex(ContextV1ScopeError, r"Checkpoint B must pass"):
            assert_v1_implementation_file_map(
                ["runtime/handoff.py"],
                checkpoint_b_passed=False,
            )

    def test_v1_file_map_rejects_observe_only_files_after_checkpoint_b(self) -> None:
        with self.assertRaisesRegex(ContextV1ScopeError, r"Observe-only files cannot be edited"):
            assert_v1_implementation_file_map(
                ["tests/fixtures/sample_invariant_gate_matrix.yaml"],
                checkpoint_b_passed=True,
            )

    def test_v1_file_map_rejects_out_of_scope_runtime_files_after_checkpoint_b(self) -> None:
        with self.assertRaisesRegex(ContextV1ScopeError, r"Out-of-scope implementation files"):
            assert_v1_implementation_file_map(
                ["runtime/decision.py"],
                checkpoint_b_passed=True,
            )

    def test_v1_file_map_normalizes_repo_internal_absolute_paths(self) -> None:
        accepted = assert_v1_implementation_file_map(
            [str(REPO_ROOT / "runtime" / "handoff.py")],
            checkpoint_b_passed=True,
        )

        self.assertEqual(accepted, ("runtime/handoff.py",))

    def test_v1_file_map_rejects_absolute_paths_outside_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ContextV1ScopeError, r"workspace root"):
                assert_v1_implementation_file_map(
                    [str(Path(temp_dir) / "outside.py")],
                    checkpoint_b_passed=True,
                )

    def test_v1_ready_to_start_requires_checkpoint_a_b_and_local_freeze(self) -> None:
        with self.assertRaisesRegex(ContextV1ScopeError, r"Checkpoint A"):
            assert_v1_ready_to_start(
                completed_checkpoints=("Checkpoint B",),
                changed_files=("runtime/handoff.py",),
                scope_guard_tests_green=True,
                compatibility_rules_frozen=True,
            )

        with self.assertRaisesRegex(ContextV1ScopeError, r"scope guard tests are green"):
            assert_v1_ready_to_start(
                completed_checkpoints=("Checkpoint A", "Checkpoint B"),
                changed_files=("runtime/handoff.py",),
                scope_guard_tests_green=False,
                compatibility_rules_frozen=True,
            )

        with self.assertRaisesRegex(ContextV1ScopeError, r"compatibility rules are frozen"):
            assert_v1_ready_to_start(
                completed_checkpoints=("Checkpoint A", "Checkpoint B"),
                changed_files=("runtime/handoff.py",),
                scope_guard_tests_green=True,
                compatibility_rules_frozen=False,
            )

    def test_v1_ready_to_start_accepts_checkpoint_c_scope_finalize_working_set(self) -> None:
        accepted = assert_v1_ready_to_start(
            completed_checkpoints=("Checkpoint A", "Checkpoint B"),
            changed_files=("runtime/handoff.py", "tests/test_context_v1_scope.py"),
            scope_guard_tests_green=True,
            compatibility_rules_frozen=True,
        )

        self.assertEqual(
            accepted,
            ("runtime/handoff.py", "tests/test_context_v1_scope.py"),
        )


class LocalContextBuilderTests(unittest.TestCase):
    def test_build_local_context_filters_assistant_messages_and_windows_user_history(self) -> None:
        local_context = build_local_context(
            "最新输入",
            recent_messages=[
                {"role": "assistant", "content": "这里是解释型 prose"},
                {"role": "user", "content": "第一条用户消息"},
                {"role": "user", "content": "第二条用户消息"},
                {"role": "user", "content": ["第三条", {"text": "补充"}]},
                {"role": "assistant", "content": "继续解释"},
                {"role": "user", "content": "最新输入"},
            ],
            checkpoint_summary={
                "checkpoint_kind": "confirm_execute",
                "required_host_action": "continue_host_develop",
            },
            allowed_actions=["continue", "checkpoint", "continue"],
            runtime_constraints={"allowed_response_mode": "normal_runtime_followup"},
        )

        self.assertEqual(local_context.current_user_input, "最新输入")
        self.assertEqual(
            local_context.recent_user_messages,
            ("第一条用户消息", "第二条用户消息", "第三条 补充"),
        )
        self.assertEqual(local_context.allowed_actions, ("continue", "checkpoint"))
        self.assertEqual(
            dict(local_context.checkpoint_summary),
            {
                "checkpoint_kind": "confirm_execute",
                "required_host_action": "continue_host_develop",
            },
        )
        self.assertEqual(
            dict(local_context.runtime_constraints),
            {"allowed_response_mode": "normal_runtime_followup"},
        )

    def test_build_local_context_uses_default_window_size(self) -> None:
        messages = [
            {"role": "user", "content": f"msg-{index}"}
            for index in range(MAX_LOCAL_CONTEXT_USER_MESSAGES + 2)
        ]
        local_context = build_local_context("current", recent_messages=messages)
        self.assertEqual(
            local_context.recent_user_messages,
            tuple(f"msg-{index}" for index in range(2, 5)),
        )

    def test_build_local_context_rejects_negative_window(self) -> None:
        with self.assertRaisesRegex(ValueError, r"max_user_messages"):
            build_local_context("current", max_user_messages=-1)


class DeterministicGuardTests(unittest.TestCase):
    def test_plan_review_guard_stays_plan_review_even_when_execution_gate_points_to_confirm_execute(self) -> None:
        current_plan = PlanArtifact(
            plan_id="plan-1",
            title="Plan 1",
            summary="review current plan",
            level="standard",
            path=".sopify-skills/plan/20260409_plan_1",
            files=("background.md", "design.md", "tasks.md"),
            created_at="2026-04-09T00:00:00+00:00",
            topic_key="plan-1",
        )
        current_run = RunState(
            run_id="run-1",
            status="active",
            stage="ready_for_execution",
            route_name="workflow",
            title="Plan 1",
            created_at="2026-04-09T00:00:00+00:00",
            updated_at="2026-04-09T00:00:00+00:00",
            plan_id=current_plan.plan_id,
            plan_path=current_plan.path,
            execution_gate=ExecutionGate(
                gate_status="ready",
                blocking_reason="none",
                plan_completion="complete",
                next_required_action="confirm_execute",
                notes=("ready",),
            ),
        )

        guard = evaluate_deterministic_guard(
            allowed_response_mode=expected_allowed_response_mode("review_or_execute_plan") or "",
            required_host_action="review_or_execute_plan",
            current_run=current_run,
            current_plan=current_plan,
            plan_id=current_plan.plan_id,
            plan_path=current_plan.path,
            execution_gate=current_run.execution_gate,
        )

        self.assertEqual(guard.truth_status, "stable")
        self.assertTrue(guard.resolution_enabled)
        self.assertEqual(guard.resume_target_kind, "plan_review")
        self.assertEqual(guard.checkpoint_kind, "")
        self.assertEqual(guard.allowed_actions, ("continue", "inspect", "revise", "cancel"))
        self.assertIn(
            "execution_gate.next_required_action=confirm_execute",
            guard.proofs,
        )

    def test_checkpoint_guard_fails_closed_when_allowed_mode_conflicts_with_required_action(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=NORMAL_RUNTIME_FOLLOWUP,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        self.assertEqual(guard.truth_status, "contract_invalid")
        self.assertFalse(guard.resolution_enabled)
        self.assertEqual(guard.primary_failure_type, "truth_layer_contract_invalid")
        self.assertEqual(guard.fallback_action, "enter_blocking_recovery_branch")
        self.assertEqual(guard.prompt_mode, "request_state_recovery")
        self.assertEqual(
            guard.reason_code,
            "recovery.truth_layer_contract_invalid.fail_closed.confirm_execute",
        )

    def test_checkpoint_guard_fails_closed_when_checkpoint_kind_mismatches_required_action(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "decision-1", "checkpoint_kind": "decision"},
        )

        self.assertEqual(guard.truth_status, "contract_invalid")
        self.assertFalse(guard.resolution_enabled)
        self.assertEqual(guard.primary_failure_type, "truth_layer_contract_invalid")
        self.assertEqual(guard.prompt_mode, "request_state_recovery")
        self.assertEqual(
            guard.reason_code,
            "recovery.truth_layer_contract_invalid.fail_closed.confirm_execute",
        )
        self.assertIn("checkpoint_kind=execution_confirm", guard.notes[0])


class ActionProjectionTests(unittest.TestCase):
    def test_confirm_execute_projection_uses_execution_summary_surface(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        projection = build_action_projection(
            guard,
            plan_path=".sopify-skills/plan/20260409_plan_1",
            artifacts={
                "execution_summary": {
                    "plan_path": ".sopify-skills/plan/20260409_plan_1",
                    "risk_level": "medium",
                    "key_risk": "需要复核执行前确认",
                    "mitigation": "继续前先核对风险摘要",
                }
            },
        )
        payload = projection.to_dict()

        self.assertEqual(payload["required_host_action"], "confirm_execute")
        self.assertEqual(payload["checkpoint_kind"], "confirm_execute")
        self.assertEqual(payload["plan_path"], ".sopify-skills/plan/20260409_plan_1")
        self.assertEqual(payload["risk_level"], "medium")
        self.assertEqual(payload["allowed_actions"], ["confirm", "inspect", "revise", "cancel"])

    def test_confirm_decision_projection_extracts_primary_question_and_options(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_decision",
            checkpoint_request={"checkpoint_id": "decision-1", "checkpoint_kind": "decision"},
        )

        projection = build_action_projection(
            guard,
            artifacts={
                "recommended_option_id": "option_1",
                "decision_checkpoint": {
                    "checkpoint_id": "decision-1",
                    "message": "选择最终方案",
                    "primary_field_id": "selected_option_id",
                    "fields": [
                        {
                            "field_id": "selected_option_id",
                            "options": [
                                {"id": "option_1", "title": "方案一", "recommended": True},
                                {"id": "option_2", "title": "方案二", "recommended": False},
                            ],
                        }
                    ],
                },
            },
        )
        payload = projection.to_dict()

        self.assertEqual(payload["question"], "选择最终方案")
        self.assertEqual(payload["recommended_option_id"], "option_1")
        self.assertEqual([option["id"] for option in payload["options"]], ["option_1", "option_2"])
        self.assertEqual(payload["allowed_actions"], ["choose", "status", "cancel"])

    def test_action_projection_requires_stable_guard(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=NORMAL_RUNTIME_FOLLOWUP,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        with self.assertRaisesRegex(ActionProjectionError, r"stable deterministic guard"):
            build_action_projection(guard, artifacts={})


class ResolutionPlannerTests(unittest.TestCase):
    def test_resolution_planner_exposes_supported_and_blocked_actions_for_confirm_execute(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        planner = build_resolution_planner(guard).to_dict()

        self.assertTrue(planner["resolution_enabled"])
        self.assertEqual(
            planner["standard_resolved_actions"],
            [
                "stay_in_checkpoint_and_inspect",
                "switch_to_consult_readonly",
                "continue_checkpoint_confirmation",
                "cancel_current_checkpoint",
            ],
        )
        self.assertEqual(planner["supported_resolved_actions"], ["continue_checkpoint_confirmation"])
        self.assertEqual(
            planner["blocked_resolved_actions"],
            [
                "stay_in_checkpoint_and_inspect",
                "switch_to_consult_readonly",
                "cancel_current_checkpoint",
            ],
        )
        supported = next(
            profile
            for profile in planner["profiles"]
            if profile["resolved_action"] == "continue_checkpoint_confirmation"
        )
        self.assertEqual(supported["effect_contract_status"], "supported")
        self.assertEqual(
            supported["forbidden_state_effects"],
            ["recreate_execution_confirm_checkpoint", "mutate_plan_identity"],
        )
        self.assertEqual(
            planner["default_effect_contract_recovery"]["reason_code"],
            "recovery.effect_contract_invalid.fail_closed.confirm_execute",
        )

    def test_resolution_planner_makes_plan_review_boundary_explicit(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=NORMAL_RUNTIME_FOLLOWUP,
            required_host_action="review_or_execute_plan",
            plan_id="plan-1",
            plan_path=".sopify-skills/plan/20260409_plan_1",
            current_plan=PlanArtifact(
                plan_id="plan-1",
                title="Plan 1",
                summary="review current plan",
                level="standard",
                path=".sopify-skills/plan/20260409_plan_1",
                files=("background.md", "design.md", "tasks.md"),
                created_at="2026-04-09T00:00:00+00:00",
                topic_key="plan-1",
            ),
            current_run=RunState(
                run_id="run-1",
                status="active",
                stage="plan_generated",
                route_name="plan_only",
                title="Plan 1",
                created_at="2026-04-09T00:00:00+00:00",
                updated_at="2026-04-09T00:00:00+00:00",
                plan_id="plan-1",
                plan_path=".sopify-skills/plan/20260409_plan_1",
            ),
        )

        planner = build_resolution_planner(guard).to_dict()

        self.assertEqual(planner["supported_resolved_actions"], [])
        self.assertEqual(
            planner["blocked_resolved_actions"],
            [
                "stay_in_checkpoint_and_inspect",
                "switch_to_consult_readonly",
                "continue_checkpoint_confirmation",
                "cancel_current_checkpoint",
                "retopic_with_current_machine_truth",
            ],
        )
        self.assertEqual(
            planner["default_no_candidate_recovery"]["prompt_mode"],
            "reask_plan_review",
        )

    def test_resolution_planner_requires_stable_guard(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=NORMAL_RUNTIME_FOLLOWUP,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )
        with self.assertRaisesRegex(ResolutionPlannerError, r"stable deterministic guard"):
            build_resolution_planner(guard)

    def test_resolution_planner_only_applies_to_signal_resolution_actions(self) -> None:
        self.assertTrue(supports_resolution_planner("confirm_execute"))
        self.assertFalse(supports_resolution_planner("continue_host_develop"))

    def test_resolution_planner_fails_closed_when_default_tables_escape_v1_scope(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )
        mutated_asset = DEFAULT_DECISION_TABLES_PATH.read_text(encoding="utf-8").replace(
            "        update:\n          - current_run\n",
            "        update:\n          - current_handoff\n",
            1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "decision_tables.yaml"
            asset_path.write_text(mutated_asset, encoding="utf-8")

            with patch(
                "runtime.resolution_planner.load_default_decision_tables",
                side_effect=lambda: load_decision_tables(asset_path),
            ):
                import runtime.resolution_planner as resolution_planner

                resolution_planner._load_resolution_registry.cache_clear()
                try:
                    with self.assertRaisesRegex(DecisionTableError, r"exceed current V1 scope"):
                        build_resolution_planner(guard)
                finally:
                    resolution_planner._load_resolution_registry.cache_clear()


class SidecarClassifierBoundaryTests(unittest.TestCase):
    def test_sidecar_classifier_boundary_keeps_v1_disabled_and_candidate_only(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        planner = build_resolution_planner(guard)
        boundary = build_sidecar_classifier_boundary(guard, planner).to_dict()

        self.assertFalse(boundary["v1_enabled"])
        self.assertEqual(boundary["implementation_stage"], "vnext_only")
        self.assertEqual(boundary["mode"], "candidate_only")
        self.assertEqual(boundary["default_invocation"], "disabled_in_v1")
        self.assertEqual(boundary["required_recovery_decision"], "eligible_for_semantic_escalation")
        self.assertEqual(boundary["allowed_signal_origin"], "semantic_classifier")
        self.assertEqual(boundary["evidence_tier_cap"], "weak_semantic_hint")
        self.assertEqual(
            boundary["eligible_signal_ids"],
            ["analysis_only_no_write_brake", "continue_current_checkpoint"],
        )
        self.assertFalse(boundary["can_emit_resolved_action"])
        self.assertFalse(boundary["can_write_state"])
        self.assertFalse(boundary["can_override_main_router"])
        self.assertFalse(boundary["can_bypass_deterministic_guard"])
        self.assertFalse(boundary["can_bypass_decision_tables"])
        self.assertEqual(
            boundary["required_candidate_fields"],
            ["signal_id", "checkpoint_kind", "target_slot"],
        )
        self.assertEqual(
            boundary["shared_failure_members"],
            ["semantic_unavailable", "context_budget_exceeded"],
        )
        self.assertEqual(
            boundary["shared_fail_close_contract"]["primary_failure_type"],
            "resolution_failure",
        )
        self.assertEqual(
            boundary["shared_fail_close_contract"]["reason_code"],
            "recovery.resolution_failure.inspect_required.confirm_execute",
        )

    def test_sidecar_classifier_boundary_requires_stable_guard(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=NORMAL_RUNTIME_FOLLOWUP,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )
        planner = ResolutionPlanner(
            required_host_action="confirm_execute",
            resolution_enabled=False,
        )

        with self.assertRaisesRegex(
            SidecarClassifierBoundaryError,
            r"stable deterministic guard",
        ):
            build_sidecar_classifier_boundary(guard, planner)

    def test_sidecar_classifier_boundary_only_applies_to_signal_resolution_actions(self) -> None:
        self.assertTrue(supports_sidecar_classifier_boundary("confirm_execute"))
        self.assertFalse(supports_sidecar_classifier_boundary("continue_host_develop"))


class VNextPhaseBoundaryTests(unittest.TestCase):
    def test_vnext_phase_boundary_keeps_parser_first_v1_as_the_only_active_path(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        boundary = build_vnext_phase_boundary(guard).to_dict()

        self.assertEqual(boundary["active_phase"], "parser_first_v1")
        self.assertEqual(
            boundary["default_resolution_strategy"],
            "deterministic_guard+local_context+action_projection+parser_first_closure",
        )
        self.assertEqual(
            boundary["phase_sequence"],
            ["parser_first_v1", "rollout_observability", "guarded_hybrid_classifier_vnext"],
        )
        self.assertFalse(boundary["vnext_enabled"])
        self.assertEqual(boundary["shared_failure_layer"], "shared_failure_recovery_table")
        self.assertEqual(boundary["phase_catalog"]["parser_first_v1"]["classifier_mode"], "out_of_scope")
        self.assertEqual(
            boundary["phase_catalog"]["guarded_hybrid_classifier_vnext"]["classifier_mode"],
            "guarded_candidate_sidecar",
        )

    def test_vnext_phase_boundary_splits_v1_and_v2_readiness_gates(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=CHECKPOINT_ONLY,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        boundary = build_vnext_phase_boundary(guard).to_dict()
        gates = {gate["gate_name"]: gate for gate in boundary["readiness_gates"]}

        self.assertEqual(
            gates["Ready-for-V1-Execution"]["required_checkpoints"],
            ["Checkpoint A", "Checkpoint B", "Checkpoint C"],
        )
        self.assertEqual(
            gates["Ready-for-V1-Execution"]["optional_checkpoints"],
            ["Checkpoint D"],
        )
        self.assertEqual(
            gates["Ready-for-V2-Trial"]["required_checkpoints"],
            ["Checkpoint D"],
        )
        self.assertEqual(
            gates["Ready-for-V2-Trial"]["required_rollout_evidence"],
            [
                "residual_ambiguity_gain_is_auditable",
                "budget_thresholds_frozen",
                "rollback_thresholds_frozen",
                "v1_rollout_observability_complete",
            ],
        )
        self.assertIn(
            "treat_checkpoint_d_as_v1_prerequisite",
            boundary["forbidden_transitions"],
        )

    def test_vnext_phase_boundary_requires_stable_guard(self) -> None:
        guard = evaluate_deterministic_guard(
            allowed_response_mode=NORMAL_RUNTIME_FOLLOWUP,
            required_host_action="confirm_execute",
            checkpoint_request={"checkpoint_id": "exec-1", "checkpoint_kind": "execution_confirm"},
        )

        with self.assertRaisesRegex(VNextPhaseBoundaryError, r"stable deterministic guard"):
            build_vnext_phase_boundary(guard)

    def test_vnext_phase_boundary_only_applies_to_signal_resolution_actions(self) -> None:
        self.assertTrue(supports_vnext_phase_boundary("confirm_execute"))
        self.assertFalse(supports_vnext_phase_boundary("continue_host_develop"))

    def test_sidecar_supported_actions_remain_subset_of_vnext_supported_actions(self) -> None:
        tables = load_default_decision_tables()
        semantic_enabled_actions = {
            required_host_action
            for row in tables["signal_priority_table"]["rows"]
            if "semantic_classifier" in row["allowed_origins"]
            for required_host_action in row["enabled_checkpoint_kinds"]
        }

        unsupported = sorted(
            action
            for action in semantic_enabled_actions
            if supports_sidecar_classifier_boundary(action)
            and not supports_vnext_phase_boundary(action)
        )
        self.assertEqual(unsupported, [])


class GuardrailIntegrationTests(unittest.TestCase):
    def test_plan_review_handoff_exposes_guard_and_projection_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = run_runtime(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            guard = result.handoff.artifacts["deterministic_guard"]
            projection = result.handoff.artifacts["action_projection"]
            planner = result.handoff.artifacts["resolution_planner"]
            boundary = result.handoff.artifacts["sidecar_classifier_boundary"]
            phase_boundary = result.handoff.artifacts["vnext_phase_boundary"]
            self.assertEqual(guard["resume_target_kind"], "plan_review")
            self.assertEqual(projection["required_host_action"], "review_or_execute_plan")
            self.assertEqual(projection["plan_path"], result.plan_artifact.path)
            self.assertEqual(planner["supported_resolved_actions"], [])
            self.assertFalse(boundary["v1_enabled"])
            self.assertEqual(boundary["resolution_scope"], "review_or_execute_plan")
            self.assertIn("retopic_current_subject", boundary["eligible_signal_ids"])
            self.assertEqual(phase_boundary["active_phase"], "parser_first_v1")
            self.assertFalse(phase_boundary["vnext_enabled"])

    def test_execution_confirm_handoff_exposes_guard_and_projection_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)

            result = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            guard = result.handoff.artifacts["deterministic_guard"]
            projection = result.handoff.artifacts["action_projection"]
            planner = result.handoff.artifacts["resolution_planner"]
            boundary = result.handoff.artifacts["sidecar_classifier_boundary"]
            phase_boundary = result.handoff.artifacts["vnext_phase_boundary"]
            self.assertEqual(guard["checkpoint_kind"], "confirm_execute")
            self.assertEqual(guard["allowed_response_mode"], CHECKPOINT_ONLY)
            self.assertEqual(projection["plan_path"], result.recovered_context.current_plan.path)
            self.assertEqual(projection["required_host_action"], "confirm_execute")
            self.assertEqual(
                planner["supported_resolved_actions"],
                ["continue_checkpoint_confirmation"],
            )
            self.assertFalse(boundary["v1_enabled"])
            self.assertEqual(boundary["allowed_signal_origin"], "semantic_classifier")
            self.assertEqual(
                phase_boundary["readiness_gates"][0]["gate_name"],
                "Ready-for-V1-Execution",
            )
            self.assertEqual(
                phase_boundary["readiness_gates"][1]["gate_name"],
                "Ready-for-V2-Trial",
            )

    def test_vnext_phase_boundary_survives_resolution_planner_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)

            with patch(
                "runtime.handoff.build_resolution_planner",
                side_effect=ResolutionPlannerError("planner unavailable"),
            ):
                result = run_runtime(
                    "~go exec",
                    workspace_root=workspace,
                    user_home=workspace / "home",
                )

            artifacts = result.handoff.artifacts
            self.assertEqual(artifacts["resolution_planner_error"], "planner unavailable")
            self.assertNotIn("resolution_planner", artifacts)
            self.assertEqual(
                artifacts["sidecar_classifier_boundary_error"],
                "Resolution planner unavailable for sidecar boundary",
            )
            self.assertEqual(
                artifacts["vnext_phase_boundary"]["active_phase"],
                "parser_first_v1",
            )
