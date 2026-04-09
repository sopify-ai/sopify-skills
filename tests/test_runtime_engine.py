from __future__ import annotations

from dataclasses import replace

from tests.runtime_test_support import *
from runtime.engine import _advance_planning_route, _handle_execution_confirm, _handle_plan_proposal_pending


class EngineIntegrationTests(unittest.TestCase):
    def test_session_review_state_is_isolated_between_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            run_runtime(
                "实现 runtime plugin bridge",
                workspace_root=workspace,
                session_id="session-a",
                user_home=workspace / "home",
            )
            run_runtime(
                "实现 runtime gate receipt compaction",
                workspace_root=workspace,
                session_id="session-b",
                user_home=workspace / "home",
            )

            config = load_runtime_config(workspace)
            session_a_store = StateStore(config, session_id="session-a")
            session_b_store = StateStore(config, session_id="session-b")
            global_store = StateStore(config)

            self.assertIsNotNone(session_a_store.get_current_plan_proposal())
            self.assertIsNotNone(session_b_store.get_current_plan_proposal())
            self.assertNotEqual(
                session_a_store.get_current_plan_proposal().reserved_plan_id,
                session_b_store.get_current_plan_proposal().reserved_plan_id,
            )
            self.assertTrue(session_a_store.current_plan_proposal_path.exists())
            self.assertTrue(session_b_store.current_plan_proposal_path.exists())
            self.assertIsNone(session_a_store.get_current_plan())
            self.assertIsNone(session_b_store.get_current_plan())
            self.assertIsNone(global_store.get_current_plan())

    def test_engine_enters_clarification_before_plan_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "clarification_pending")
            self.assertIsNone(result.plan_artifact)
            self.assertIsNotNone(result.recovered_context.current_clarification)
            self.assertEqual(result.handoff.handoff_kind, "clarification")
            self.assertEqual(result.handoff.required_host_action, "answer_questions")
            self.assertIn("clarification_form", result.handoff.artifacts)
            self.assertEqual(result.handoff.artifacts["clarification_form"]["template_id"], "scope_clarify")
            self.assertEqual(result.handoff.artifacts["clarification_submission_state"]["status"], "empty")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())

    def test_engine_resumes_planning_after_clarification_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")

            result = run_runtime(
                "目标是 runtime/router.py 和 runtime/engine.py，预期结果是接入 clarification_pending 状态骨架。",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertIsNotNone(result.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())
            self.assertTrue((workspace / result.plan_artifact.path / "tasks.md").exists())

    def test_non_explicit_complex_request_enters_proposal_first_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("那你执行吧 逻辑严谨", workspace_root=workspace, user_home=workspace / "home")
            store = StateStore(load_runtime_config(workspace))
            persisted_run = store.get_current_run()
            persisted_handoff = store.get_current_handoff()

            self.assertEqual(proposal.route.route_name, "plan_proposal_pending")
            self.assertIsNone(proposal.plan_artifact)
            self.assertIsNotNone(proposal.recovered_context.current_plan_proposal)
            self.assertIsNotNone(persisted_run)
            self.assertIsNotNone(persisted_handoff)
            self.assertTrue(persisted_run.resolution_id)
            self.assertEqual(persisted_run.resolution_id, persisted_handoff.resolution_id)
            self.assertNotEqual(
                proposal.recovered_context.current_plan_proposal.analysis_summary,
                proposal.recovered_context.current_plan_proposal.request_text,
            )
            self.assertIn("方案包", proposal.recovered_context.current_plan_proposal.analysis_summary)
            self.assertEqual(proposal.handoff.required_host_action, "confirm_plan_package")
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())
            self.assertEqual(_plan_dir_count(workspace), 0)

            confirmed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(confirmed.route.route_name, "plan_only")
            self.assertIsNotNone(confirmed.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan_proposal.json").exists())
            self.assertEqual(_plan_dir_count(workspace), 1)
            self.assertEqual(confirmed.handoff.required_host_action, "review_or_execute_plan")

    def test_proposal_pending_natural_confirm_phrase_materializes_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(proposal.handoff.required_host_action, "confirm_plan_package")

            confirmed = run_runtime("继续按这个方案走", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(confirmed.route.route_name, "plan_only")
            self.assertIsNotNone(confirmed.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan_proposal.json").exists())
            self.assertEqual(_plan_dir_count(workspace), 1)
            self.assertEqual(confirmed.handoff.required_host_action, "review_or_execute_plan")

    def test_proposal_pending_natural_confirm_phrase_with_plan_materializes_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(proposal.handoff.required_host_action, "confirm_plan_package")

            confirmed = run_runtime("continue with this plan", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(confirmed.route.route_name, "plan_only")
            self.assertIsNotNone(confirmed.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan_proposal.json").exists())
            self.assertEqual(_plan_dir_count(workspace), 1)
            self.assertEqual(confirmed.handoff.required_host_action, "review_or_execute_plan")

    def test_proposal_pending_natural_confirm_question_does_not_mutate_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("继续按这个方案吗？", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_constraint_followup_question_does_not_mutate_request_text(self) -> None:
        cases = (
            "继续按这个方案会有什么风险",
            "继续按这个方案会有什么风险？",
            "按这个最小范围会有什么风险",
            "按这个最小范围会有什么风险？",
        )
        for feedback in cases:
            with self.subTest(feedback=feedback):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)

                    proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
                    original = proposal.recovered_context.current_plan_proposal

                    followup = run_runtime(feedback, workspace_root=workspace, user_home=workspace / "home")
                    updated = followup.recovered_context.current_plan_proposal

                    self.assertEqual(followup.route.route_name, "plan_proposal_pending")
                    self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
                    self.assertEqual(updated.request_text, original.request_text)
                    self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
                    self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_keeps_finalize_and_compare_at_confirmation_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            checkpoint_id = proposal.recovered_context.current_plan_proposal.checkpoint_id

            compare = run_runtime("~compare 方案对比", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(compare.route.route_name, "plan_proposal_pending")
            self.assertIsNone(compare.plan_artifact)
            self.assertEqual(compare.handoff.required_host_action, "confirm_plan_package")
            self.assertEqual(compare.recovered_context.current_plan_proposal.checkpoint_id, checkpoint_id)

            finalize = run_runtime("~go finalize", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(finalize.route.route_name, "plan_proposal_pending")
            self.assertIsNone(finalize.plan_artifact)
            self.assertEqual(finalize.handoff.required_host_action, "confirm_plan_package")
            self.assertEqual(finalize.recovered_context.current_plan_proposal.checkpoint_id, checkpoint_id)
            self.assertEqual(_plan_dir_count(workspace), 0)

    def test_proposal_pending_go_plan_does_not_materialize_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            checkpoint_id = proposal.recovered_context.current_plan_proposal.checkpoint_id

            followup = run_runtime(
                "~go plan 按这个最小范围直接进 3.1 -> 3.6 注意不要过度设计",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertIsNone(followup.plan_artifact)
            self.assertEqual(followup.handoff.required_host_action, "confirm_plan_package")
            self.assertEqual(followup.recovered_context.current_plan_proposal.checkpoint_id, checkpoint_id)
            self.assertEqual(_plan_dir_count(workspace), 0)

    def test_proposal_pending_question_does_not_mutate_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("为什么是这个方案？", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_question_with_constraint_cue_does_not_mutate_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("为什么先做这个？", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_implicit_question_like_constraint_without_question_mark_does_not_mutate_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("按这个最小范围能不能直接进", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_english_question_like_constraint_does_not_mutate_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("continue with this?", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_implicit_question_like_retopic_does_not_mutate_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("能不能把这个方案改成 runtime gate receipt compaction", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_question_like_retopic_with_followup_revision_refreshes_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("是否把这个方案改成 runtime gate receipt compaction 并补一下风险", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "revise_plan_proposal")
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)
            self.assertIn("修订意见", updated.request_text)
            self.assertIn("是否把这个方案改成 runtime gate receipt compaction 并补一下风险", updated.request_text)

    def test_proposal_pending_start_with_this_question_fail_closes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            followup = run_runtime("start with this?", workspace_root=workspace, user_home=workspace / "home")
            updated = followup.recovered_context.current_plan_proposal

            self.assertEqual(followup.route.route_name, "plan_proposal_pending")
            self.assertEqual(followup.route.active_run_action, "inspect_plan_proposal")
            self.assertEqual(updated.request_text, original.request_text)
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)

    def test_proposal_pending_mixed_revision_and_question_refreshes_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            revised = run_runtime(
                "实现 runtime plugin bridge",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            mixed = run_runtime(
                "按这个最小范围直接进 3.1 -> 3.6 确认是否覆盖风险并补一下",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            updated = mixed.recovered_context.current_plan_proposal

            self.assertEqual(revised.route.route_name, "plan_proposal_pending")
            self.assertEqual(mixed.route.route_name, "plan_proposal_pending")
            self.assertIn("修订意见", updated.request_text)
            self.assertIn("按这个最小范围直接进 3.1 -> 3.6 确认是否覆盖风险并补一下", updated.request_text)

    def test_proposal_pending_mixed_question_and_revision_refreshes_request_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime(
                "实现 runtime plugin bridge",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            original = proposal.recovered_context.current_plan_proposal

            mixed = run_runtime(
                "为什么先做这个？按这个最小范围直接进 3.1 -> 3.6",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            updated = mixed.recovered_context.current_plan_proposal

            self.assertEqual(mixed.route.route_name, "plan_proposal_pending")
            self.assertEqual(mixed.route.active_run_action, "revise_plan_proposal")
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)
            self.assertIn("修订意见", updated.request_text)
            self.assertIn("为什么先做这个？按这个最小范围直接进 3.1 -> 3.6", updated.request_text)

    def test_proposal_pending_explicit_revision_refreshes_request_text_without_drifting_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            revised = run_runtime("把风险再展开一点", workspace_root=workspace, user_home=workspace / "home")
            updated = revised.recovered_context.current_plan_proposal

            self.assertEqual(revised.route.route_name, "plan_proposal_pending")
            self.assertEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertEqual(updated.proposed_path, original.proposed_path)
            self.assertIn("修订意见", updated.request_text)
            self.assertIn("把风险再展开一点", updated.request_text)

    def test_proposal_pending_retopic_revision_restarts_with_new_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            revised = run_runtime("方案改成 runtime gate receipt compaction", workspace_root=workspace, user_home=workspace / "home")
            updated = revised.recovered_context.current_plan_proposal

            self.assertEqual(revised.route.route_name, "plan_proposal_pending")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertNotEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertNotEqual(updated.reserved_plan_id, original.reserved_plan_id)
            self.assertNotEqual(updated.proposed_path, original.proposed_path)
            self.assertEqual(updated.request_text, "runtime gate receipt compaction")

            confirmed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(confirmed.route.route_name, "plan_only")
            self.assertIsNotNone(confirmed.plan_artifact)
            assert confirmed.plan_artifact is not None
            self.assertEqual(confirmed.plan_artifact.plan_id, updated.reserved_plan_id)
            self.assertEqual(confirmed.plan_artifact.path, updated.proposed_path)

    def test_proposal_pending_retopic_revision_with_referential_phrase_restarts_with_new_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            revised = run_runtime("这个方案改成 runtime gate receipt compaction", workspace_root=workspace, user_home=workspace / "home")
            updated = revised.recovered_context.current_plan_proposal

            self.assertEqual(revised.route.route_name, "plan_proposal_pending")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertNotEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertNotEqual(updated.reserved_plan_id, original.reserved_plan_id)
            self.assertNotEqual(updated.proposed_path, original.proposed_path)
            self.assertEqual(updated.request_text, "runtime gate receipt compaction")

            confirmed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(confirmed.route.route_name, "plan_only")
            self.assertIsNotNone(confirmed.plan_artifact)
            assert confirmed.plan_artifact is not None
            self.assertEqual(confirmed.plan_artifact.plan_id, updated.reserved_plan_id)
            self.assertEqual(confirmed.plan_artifact.path, updated.proposed_path)

    def test_proposal_pending_english_retopic_revision_restarts_with_new_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            original = proposal.recovered_context.current_plan_proposal

            revised = run_runtime("change the plan to runtime gate receipt compaction", workspace_root=workspace, user_home=workspace / "home")
            updated = revised.recovered_context.current_plan_proposal

            self.assertEqual(revised.route.route_name, "plan_proposal_pending")
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertNotEqual(updated.checkpoint_id, original.checkpoint_id)
            self.assertNotEqual(updated.reserved_plan_id, original.reserved_plan_id)
            self.assertNotEqual(updated.proposed_path, original.proposed_path)
            self.assertEqual(updated.request_text, "runtime gate receipt compaction")

            confirmed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(confirmed.route.route_name, "plan_only")
            self.assertIsNotNone(confirmed.plan_artifact)
            assert confirmed.plan_artifact is not None
            self.assertEqual(confirmed.plan_artifact.plan_id, updated.reserved_plan_id)
            self.assertEqual(confirmed.plan_artifact.path, updated.proposed_path)

    def test_plan_proposal_handler_can_confirm_from_resolved_snapshot_without_live_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            pending = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            resolved_proposal = pending.recovered_context.current_plan_proposal
            self.assertIsNotNone(resolved_proposal)

            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.reset_active_flow()

            routed, plan_artifact, notes, _ = _handle_plan_proposal_pending(
                RouteDecision(
                    route_name="plan_proposal_pending",
                    request_text=resolved_proposal.request_text,
                    reason="test resolved proposal confirm",
                    complexity="complex" if resolved_proposal.proposed_level != "light" else "medium",
                    plan_level=resolved_proposal.proposed_level,
                    candidate_skill_ids=resolved_proposal.candidate_skill_ids,
                    capture_mode=resolved_proposal.capture_mode,
                    active_run_action="confirm_plan_proposal",
                ),
                state_store=store,
                resolved_proposal=resolved_proposal,
                config=config,
                kb_artifact=None,
            )

            self.assertEqual(routed.route_name, "plan_only")
            self.assertIsNotNone(plan_artifact)
            self.assertEqual(plan_artifact.plan_id, resolved_proposal.reserved_plan_id)
            self.assertIsNone(store.get_current_plan_proposal())
            self.assertTrue(any("after proposal confirmation" in note for note in notes))

    def test_explain_only_request_routes_to_consult_without_creating_plan_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = run_runtime(
                "你之前说：这次又被误路由成 proposal 了。说下原因，不要改。",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "consult")
            self.assertIsNone(result.plan_artifact)
            self.assertIsNone(result.recovered_context.current_plan_proposal)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan_proposal.json").exists())
            self.assertEqual(result.handoff.required_host_action, "continue_host_consult")
            self.assertEqual(result.handoff.artifacts.get("consult_mode"), "explain_only_override")
            self.assertEqual(result.handoff.artifacts.get("consult_override_reason_code"), "consult_explain_only_override")

    def test_engine_proposal_fuse_blocks_explain_only_route_even_when_router_missed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            routed, plan_artifact, notes, _ = _advance_planning_route(
                RouteDecision(
                    route_name="light_iterate",
                    request_text="你之前说：这次又被误路由成 proposal 了。说下原因，不要改。",
                    reason="forced test path",
                    complexity="medium",
                    plan_level="light",
                    plan_package_policy="confirm",
                ),
                state_store=store,
                config=config,
                kb_artifact=None,
            )

            self.assertEqual(routed.route_name, "consult")
            self.assertIsNone(plan_artifact)
            self.assertIsNone(store.get_current_plan_proposal())
            self.assertTrue(any("Bypassed plan proposal materialization" in note for note in notes))

    def test_engine_proposal_fuse_consumes_matching_confirmed_decision_on_explain_only_return(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            confirmed = confirm_decision(
                pending.recovered_context.current_decision,
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            store.set_current_decision(confirmed)

            routed, plan_artifact, notes, _ = _advance_planning_route(
                RouteDecision(
                    route_name="light_iterate",
                    request_text="你之前说：这次又被误路由成 proposal 了。说下原因，不要改。",
                    reason="forced test path",
                    complexity="medium",
                    plan_level="light",
                    plan_package_policy="confirm",
                ),
                state_store=store,
                config=config,
                kb_artifact=None,
                confirmed_decision=confirmed,
            )

            self.assertEqual(routed.route_name, "consult")
            self.assertIsNone(plan_artifact)
            self.assertIsNone(store.get_current_decision())
            self.assertTrue(any(f"Decision consumed: {confirmed.decision_id}" in note for note in notes))

    def test_engine_proposal_fuse_keeps_nonmatching_confirmed_decision_state_on_explain_only_return(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            confirmed = confirm_decision(
                pending.recovered_context.current_decision,
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            mismatched_current = replace(confirmed, decision_id="decision-mismatch")
            store.set_current_decision(mismatched_current)

            routed, plan_artifact, notes, _ = _advance_planning_route(
                RouteDecision(
                    route_name="light_iterate",
                    request_text="你之前说：这次又被误路由成 proposal 了。说下原因，不要改。",
                    reason="forced test path",
                    complexity="medium",
                    plan_level="light",
                    plan_package_policy="confirm",
                ),
                state_store=store,
                config=config,
                kb_artifact=None,
                confirmed_decision=confirmed,
            )

            self.assertEqual(routed.route_name, "consult")
            self.assertIsNone(plan_artifact)
            current_decision = store.get_current_decision()
            self.assertIsNotNone(current_decision)
            self.assertEqual(current_decision.decision_id, "decision-mismatch")
            self.assertFalse(any(f"Decision consumed: {confirmed.decision_id}" in note for note in notes))

    def test_advance_planning_route_fail_closed_when_workflow_policy_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            routed, plan_artifact, notes, _ = _advance_planning_route(
                RouteDecision(
                    route_name="workflow",
                    request_text="实现 runtime plugin bridge",
                    reason="legacy route payload without plan_package_policy",
                    complexity="complex",
                    plan_level="standard",
                ),
                state_store=store,
                config=config,
                kb_artifact=None,
            )

            self.assertEqual(routed.route_name, "plan_proposal_pending")
            self.assertIsNone(plan_artifact)
            self.assertIsNotNone(store.get_current_plan_proposal())
            self.assertEqual(_plan_dir_count(workspace), 0)
            self.assertTrue(any("Plan proposal staged at" in note for note in notes))

    def test_exec_plan_is_blocked_while_clarification_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")

            result = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "clarification_pending")
            self.assertIsNone(result.plan_artifact)
            self.assertEqual(result.handoff.required_host_action, "answer_questions")
            self.assertEqual(result.recovered_context.current_run.stage, "clarification_pending")

    def test_exec_plan_is_unavailable_without_active_recovery_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "exec_plan")
            self.assertIsNone(result.recovered_context.current_plan)
            self.assertIsNone(result.handoff)
            self.assertTrue(any("~go exec" in note for note in result.notes))
            rendered = render_runtime_output(
                result,
                brand="demo-ai",
                language="zh-CN",
                title_color="none",
                use_color=False,
            )
            self.assertIn("高级恢复入口", rendered)
            self.assertIn("Next: 仅在已有活动 plan 或恢复态时使用 ~go exec", rendered)

    def test_exec_plan_respects_execution_gate_before_develop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            run_runtime("1", workspace_root=workspace, user_home=workspace / "home")

            result = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "exec_plan")
            self.assertEqual(result.recovered_context.current_run.stage, "plan_generated")
            self.assertEqual(result.recovered_context.current_run.execution_gate.gate_status, "blocked")
            self.assertEqual(result.recovered_context.current_run.execution_gate.blocking_reason, "missing_info")
            self.assertIsNone(result.handoff)

    def test_ready_plan_enters_execution_confirm_flow_before_develop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)

            result = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "execution_confirm_pending")
            self.assertEqual(result.recovered_context.current_run.stage, "execution_confirm_pending")
            self.assertEqual(result.handoff.required_host_action, "confirm_execute")
            summary = result.handoff.artifacts["execution_summary"]
            self.assertEqual(summary["plan_path"], result.recovered_context.current_plan.path)
            self.assertEqual(summary["task_count"], 5)
            self.assertIn("执行前确认", summary["key_risk"])
            self.assertIn("execution_confirm_pending", summary["mitigation"])
            rendered = render_runtime_output(
                result,
                brand="demo-ai",
                language="zh-CN",
                title_color="none",
                use_color=False,
            )
            self.assertIn("任务数: 5", rendered)
            self.assertIn("关键风险:", rendered)
            self.assertIn("Next: 回复 继续 / next / 开始 确认执行", rendered)

    def test_session_review_plan_promotes_to_global_execution_truth_on_exec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, _, _ = _prepare_ready_plan_state(workspace, session_id="session-a")

            result = run_runtime(
                "~go exec",
                workspace_root=workspace,
                session_id="session-a",
                user_home=workspace / "home",
            )

            global_store = StateStore(config)
            global_run = global_store.get_current_run()
            self.assertEqual(result.route.route_name, "execution_confirm_pending")
            self.assertIsNotNone(global_store.get_current_plan())
            self.assertIsNotNone(global_run)
            self.assertEqual(global_run.owner_session_id, "session-a")
            self.assertEqual(global_run.owner_host, "runtime")
            self.assertEqual(global_run.owner_run_id, global_run.run_id)
            self.assertTrue(any("Promoted session review state to global execution truth" in note for note in result.notes))

    def test_soft_ownership_warning_is_emitted_when_promotion_replaces_existing_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, _, _ = _prepare_ready_plan_state(workspace, session_id="session-a")
            run_runtime(
                "~go exec",
                workspace_root=workspace,
                session_id="session-a",
                user_home=workspace / "home",
            )
            global_store = StateStore(config)
            global_store.clear_current_plan()
            _prepare_ready_plan_state(
                workspace,
                request_text="实现 runtime plugin bridge",
                session_id="session-b",
            )

            result = run_runtime(
                "~go exec",
                workspace_root=workspace,
                session_id="session-b",
                user_home=workspace / "home",
            )

            global_run = global_store.get_current_run()
            self.assertEqual(result.route.route_name, "execution_confirm_pending")
            self.assertTrue(any("Soft ownership warning" in note for note in result.notes))
            self.assertIsNotNone(global_run)
            self.assertEqual(global_run.owner_session_id, "session-b")

    def test_execution_gate_promotion_warns_when_replacing_other_session_global_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, _, _ = _prepare_ready_plan_state(workspace, request_text="session-a plan", session_id="session-a")
            run_runtime(
                "~go exec",
                workspace_root=workspace,
                session_id="session-a",
                user_home=workspace / "home",
            )

            session_b_store = StateStore(config, session_id="session-b")
            plan_artifact = create_plan_scaffold("调整 auth boundary", config=config, level="standard")
            _rewrite_background_scope(
                workspace,
                plan_artifact,
                scope_lines=("runtime/engine.py", "runtime/engine.py, runtime/router.py"),
                risk_lines=("本轮会调整认证与权限边界", "需要先明确批准路径"),
            )
            gate = evaluate_execution_gate(
                decision=RouteDecision(
                    route_name="workflow",
                    request_text="调整 auth boundary",
                    reason="test",
                    complexity="complex",
                    plan_level="standard",
                    candidate_skill_ids=("develop",),
                ),
                plan_artifact=plan_artifact,
                current_clarification=None,
                current_decision=None,
                config=config,
            )
            session_b_store.set_current_plan(plan_artifact)
            session_b_store.set_current_run(
                RunState(
                    run_id="run-b",
                    status="active",
                    stage="ready_for_execution",
                    route_name="workflow",
                    title=plan_artifact.title,
                    created_at=iso_now(),
                    updated_at=iso_now(),
                    plan_id=plan_artifact.plan_id,
                    plan_path=plan_artifact.path,
                    execution_gate=gate,
                )
            )

            routed, resolved_plan, notes, _ = _advance_planning_route(
                RouteDecision(
                    route_name="workflow",
                    request_text=f"分析下 {plan_artifact.plan_id} 是否可以执行",
                    reason="test",
                    complexity="medium",
                    plan_package_policy="confirm",
                    capture_mode="summary",
                ),
                state_store=session_b_store,
                config=config,
                kb_artifact=None,
            )

            global_run = StateStore(config).get_current_run()
            self.assertEqual(routed.route_name, "decision_pending")
            self.assertIsNotNone(resolved_plan)
            self.assertTrue(any("Soft ownership warning" in note for note in notes))
            self.assertIsNotNone(global_run)
            self.assertEqual(global_run.owner_session_id, "session-b")

    def test_cancel_active_clears_session_active_plan_binding_checkpoint_without_touching_global_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, _, _ = _prepare_ready_plan_state(workspace, session_id="session-a")
            run_runtime(
                "~go exec",
                workspace_root=workspace,
                session_id="session-a",
                user_home=workspace / "home",
            )
            run_runtime(
                "实现 runtime plugin bridge",
                workspace_root=workspace,
                session_id="session-b",
                user_home=workspace / "home",
            )

            result = run_runtime(
                "取消",
                workspace_root=workspace,
                session_id="session-b",
                user_home=workspace / "home",
            )

            global_store = StateStore(config)
            review_store = StateStore(config, session_id="session-b")
            self.assertEqual(result.route.route_name, "cancel_active")
            self.assertIsNotNone(global_store.get_current_run())
            self.assertIsNotNone(global_store.get_current_plan())
            self.assertIsNone(review_store.get_current_run())
            self.assertIsNone(review_store.get_current_decision())
            self.assertTrue(any("Decision checkpoint cancelled" in note for note in result.notes))

    def test_cancel_active_clears_only_session_review_when_global_execution_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, _, _ = _prepare_ready_plan_state(workspace, session_id="session-a")

            result = run_runtime(
                "取消",
                workspace_root=workspace,
                session_id="session-a",
                user_home=workspace / "home",
            )

            global_store = StateStore(config)
            review_store = StateStore(config, session_id="session-a")
            self.assertEqual(result.route.route_name, "cancel_active")
            self.assertIsNone(global_store.get_current_run())
            self.assertIsNone(global_store.get_current_plan())
            self.assertIsNone(review_store.get_current_run())
            self.assertIsNone(review_store.get_current_plan())
            self.assertTrue(any("Session review flow cleared" in note for note in result.notes))

    def test_state_conflict_is_visible_and_cancel_can_clear_negotiation_state(self) -> None:
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
            store.set_current_decision(
                DecisionState(
                    schema_version="2",
                    decision_id="decision-1",
                    feature_key="runtime",
                    phase="design",
                    status="pending",
                    decision_type="design_choice",
                    question="继续哪个选项？",
                    summary="pending decision",
                    options=(DecisionOption(option_id="option_1", title="option 1", summary="summary"),),
                    created_at=iso_now(),
                    updated_at=iso_now(),
                )
            )

            conflicted = run_runtime("看看状态", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(conflicted.route.route_name, "state_conflict")
            self.assertEqual(conflicted.handoff.required_host_action, "resolve_state_conflict")
            self.assertEqual(conflicted.recovered_context.state_conflict["code"], "multiple_pending_checkpoints")
            rendered_conflict = render_runtime_output(
                conflicted,
                brand="demo-ai",
                language="zh-CN",
                title_color="none",
                use_color=False,
            )
            self.assertIn("状态冲突", rendered_conflict)
            self.assertIn("取消 / 强制取消", rendered_conflict)
            self.assertNotIn("~go abort", rendered_conflict)

            cleared = run_runtime("取消", workspace_root=workspace, user_home=workspace / "home")
            after_store = StateStore(load_runtime_config(workspace))

            self.assertEqual(cleared.route.route_name, "state_conflict")
            self.assertEqual(cleared.route.active_run_action, "abort_conflict")
            self.assertEqual(cleared.handoff.required_host_action, "continue_host_workflow")
            self.assertFalse(cleared.recovered_context.state_conflict)
            self.assertIsNone(after_store.get_current_plan_proposal())
            self.assertIsNone(after_store.get_current_decision())
            rendered_cleared = render_runtime_output(
                cleared,
                brand="demo-ai",
                language="zh-CN",
                title_color="none",
                use_color=False,
            )
            self.assertIn("已放弃当前协商并恢复到稳定主线", rendered_cleared)
            self.assertIn("Next: 在宿主会话中继续执行后续阶段", rendered_cleared)
            self.assertNotIn("~go abort", rendered_cleared)

    def test_state_conflict_surfaces_handoff_pending_kind_mismatch_before_generic_multiple_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            store.set_current_handoff(
                RuntimeHandoff(
                    schema_version="1",
                    route_name="decision_pending",
                    run_id="run-1",
                    handoff_kind="checkpoint",
                    required_host_action="confirm_decision",
                    artifacts={},
                )
            )
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
            store.set_current_decision(
                DecisionState(
                    schema_version="2",
                    decision_id="decision-1",
                    feature_key="runtime",
                    phase="design",
                    status="pending",
                    decision_type="design_choice",
                    question="继续哪个选项？",
                    summary="pending decision",
                    options=(DecisionOption(option_id="option_1", title="option 1", summary="summary"),),
                    created_at=iso_now(),
                    updated_at=iso_now(),
                )
            )

            conflicted = run_runtime("看看状态", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(conflicted.route.route_name, "state_conflict")
            self.assertEqual(conflicted.handoff.required_host_action, "resolve_state_conflict")
            self.assertEqual(conflicted.recovered_context.state_conflict["code"], "pending_checkpoint_handoff_mismatch")

    def test_state_conflict_abort_preserves_confirmed_decision_and_stable_plan_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            plan_artifact = create_plan_scaffold("补 runtime 状态机 hotfix", config=config, level="standard")
            store.set_current_plan(plan_artifact)
            store.set_current_run(
                RunState(
                    run_id="run-1",
                    status="active",
                    stage="plan_proposal_pending",
                    route_name="workflow",
                    title=plan_artifact.title,
                    created_at=iso_now(),
                    updated_at=iso_now(),
                    plan_id=plan_artifact.plan_id,
                    plan_path=plan_artifact.path,
                )
            )
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
            confirmed_decision = confirm_decision(
                DecisionState(
                    schema_version="2",
                    decision_id="decision-1",
                    feature_key="runtime",
                    phase="design",
                    status="pending",
                    decision_type="design_choice",
                    question="继续哪个选项？",
                    summary="confirmed decision should survive abort cleanup",
                    options=(DecisionOption(option_id="option_1", title="option 1", summary="summary"),),
                    created_at=iso_now(),
                    updated_at=iso_now(),
                ),
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            store.set_current_decision(confirmed_decision)

            conflicted = run_runtime("看看状态", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(conflicted.route.route_name, "state_conflict")
            self.assertEqual(conflicted.recovered_context.state_conflict["code"], "multiple_pending_checkpoints")

            cleared = run_runtime("取消", workspace_root=workspace, user_home=workspace / "home")
            after_store = StateStore(load_runtime_config(workspace))
            surviving_decision = after_store.get_current_decision()
            surviving_run = after_store.get_current_run()

            self.assertEqual(cleared.route.route_name, "state_conflict")
            self.assertEqual(cleared.route.active_run_action, "abort_conflict")
            self.assertFalse(cleared.recovered_context.state_conflict)
            self.assertIsNone(after_store.get_current_plan_proposal())
            self.assertIsNotNone(surviving_decision)
            self.assertEqual(surviving_decision.status, "confirmed")
            self.assertEqual(surviving_decision.selected_option_id, "option_1")
            self.assertIsNotNone(after_store.get_current_plan())
            self.assertIsNotNone(surviving_run)
            self.assertEqual(surviving_run.stage, "plan_generated")

    def test_state_conflict_abort_tombstones_conflicting_handoff_without_resetting_plan_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            plan_artifact = create_plan_scaffold("补 runtime 状态机 hotfix", config=config, level="standard")
            store.set_current_plan(plan_artifact)
            store.set_current_run(
                RunState(
                    run_id="run-1",
                    status="active",
                    stage="plan_generated",
                    route_name="plan_only",
                    title=plan_artifact.title,
                    created_at=iso_now(),
                    updated_at=iso_now(),
                    plan_id=plan_artifact.plan_id,
                    plan_path=plan_artifact.path,
                    resolution_id="run-resolution",
                )
            )
            store.set_current_handoff(
                RuntimeHandoff(
                    schema_version="1",
                    route_name="plan_only",
                    run_id="run-1",
                    plan_id=plan_artifact.plan_id,
                    plan_path=plan_artifact.path,
                    handoff_kind="plan_only",
                    required_host_action="review_or_execute_plan",
                    resolution_id="handoff-resolution",
                )
            )

            conflicted = run_runtime("看看状态", workspace_root=workspace, user_home=workspace / "home")
            inspected_store = StateStore(load_runtime_config(workspace))
            self.assertEqual(conflicted.route.route_name, "state_conflict")
            self.assertEqual(conflicted.recovered_context.state_conflict["code"], "resolution_id_mismatch")
            self.assertEqual(inspected_store.get_current_handoff().resolution_id, "handoff-resolution")
            self.assertEqual(inspected_store.get_current_run().resolution_id, "run-resolution")
            self.assertIsNone(inspected_store.get_last_route())

            cleared = run_runtime("强制取消", workspace_root=workspace, user_home=workspace / "home")
            after_store = StateStore(load_runtime_config(workspace))
            current_run = after_store.get_current_run()
            current_handoff = after_store.get_current_handoff()
            current_plan = after_store.get_current_plan()

            self.assertEqual(cleared.route.route_name, "state_conflict")
            self.assertEqual(cleared.route.active_run_action, "abort_conflict")
            self.assertFalse(cleared.recovered_context.state_conflict)
            self.assertIsNotNone(current_plan)
            self.assertIsNotNone(current_run)
            self.assertIsNotNone(current_handoff)
            self.assertEqual(current_run.run_id, "run-1")
            self.assertEqual(current_handoff.run_id, "run-1")
            self.assertTrue(current_run.resolution_id)
            self.assertEqual(current_run.resolution_id, current_handoff.resolution_id)

    def test_state_conflict_abort_restores_develop_handoff_for_executing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)

            store = StateStore(load_runtime_config(workspace))
            current_handoff = store.get_current_handoff()
            assert current_handoff is not None

            stale_handoff = current_handoff.to_dict()
            stale_handoff["resolution_id"] = "stale-resolution-id"
            store.current_handoff_path.write_text(
                json.dumps(stale_handoff, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            conflicted = run_runtime("看看状态", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(conflicted.route.route_name, "state_conflict")
            self.assertEqual(conflicted.recovered_context.state_conflict["code"], "resolution_id_mismatch")

            cleared = run_runtime("取消", workspace_root=workspace, user_home=workspace / "home")
            after_store = StateStore(load_runtime_config(workspace))
            current_run = after_store.get_current_run()
            restored_handoff = after_store.get_current_handoff()

            self.assertEqual(cleared.route.route_name, "state_conflict")
            self.assertEqual(cleared.route.active_run_action, "abort_conflict")
            self.assertFalse(cleared.recovered_context.state_conflict)
            self.assertIsNotNone(current_run)
            self.assertEqual(current_run.stage, "executing")
            self.assertIsNotNone(restored_handoff)
            self.assertEqual(restored_handoff.required_host_action, "continue_host_develop")

    def test_cross_session_owner_bound_confirmed_decision_survives_conflict_abort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            global_store = StateStore(config)
            review_store = StateStore(config, session_id="session-b")
            global_store.ensure()
            review_store.ensure()

            plan_artifact = create_plan_scaffold("补 runtime 状态机 hotfix", config=config, level="standard")
            global_store.set_current_plan(plan_artifact)
            global_store.set_current_run(
                RunState(
                    run_id="run-1",
                    status="active",
                    stage="decision_pending",
                    route_name="resume_active",
                    title=plan_artifact.title,
                    created_at=iso_now(),
                    updated_at=iso_now(),
                    plan_id=plan_artifact.plan_id,
                    plan_path=plan_artifact.path,
                    owner_session_id="session-a",
                    owner_run_id="owner-run-1",
                )
            )
            confirmed_decision = confirm_decision(
                DecisionState(
                    schema_version="2",
                    decision_id="decision-1",
                    feature_key="runtime",
                    phase="develop",
                    status="pending",
                    decision_type="develop_choice",
                    question="继续哪个开发方案？",
                    summary="owner-bound confirmed develop decision should survive conflict cleanup",
                    options=(DecisionOption(option_id="option_1", title="option 1", summary="summary"),),
                    resume_context={
                        "resume_after": "continue_host_develop",
                        "active_run_stage": "executing",
                        "current_plan_path": plan_artifact.path,
                        "task_refs": ["5.3", "6.9"],
                        "changed_files": ["runtime/engine.py"],
                        "working_summary": "cross-session develop decision remains valid after resume",
                        "verification_todo": ["补 cross-session recoverable decision 回归"],
                    },
                    created_at=iso_now(),
                    updated_at=iso_now(),
                ),
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            global_store.set_current_decision(confirmed_decision)

            review_store.set_current_plan_proposal(
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
                "看看状态",
                workspace_root=workspace,
                session_id="session-b",
                user_home=workspace / "home",
            )
            self.assertEqual(conflicted.route.route_name, "state_conflict")

            cleared = run_runtime(
                "取消",
                workspace_root=workspace,
                session_id="session-b",
                user_home=workspace / "home",
            )

            surviving_decision = StateStore(load_runtime_config(workspace)).get_current_decision()
            self.assertEqual(cleared.route.route_name, "state_conflict")
            self.assertFalse(cleared.recovered_context.state_conflict)
            self.assertIsNone(StateStore(load_runtime_config(workspace), session_id="session-b").get_current_plan_proposal())
            self.assertIsNotNone(surviving_decision)
            self.assertEqual(surviving_decision.status, "confirmed")
            self.assertEqual(surviving_decision.phase, "develop")
            self.assertEqual(surviving_decision.selected_option_id, "option_1")

    def test_natural_language_execution_confirmation_starts_executing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)
            run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            result = run_runtime("开始", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "resume_active")
            self.assertEqual(result.recovered_context.current_run.stage, "executing")
            self.assertEqual(result.handoff.required_host_action, "continue_host_develop")
            self.assertEqual(
                result.handoff.artifacts["develop_quality_contract"]["verification_discovery_order"],
                ["project_contract", "project_native", "not_configured"],
            )

    def test_execution_confirm_helper_uses_explicit_confirmed_decision_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, store, plan_artifact = _prepare_ready_plan_state(workspace)
            _rewrite_background_scope(
                workspace,
                plan_artifact,
                scope_lines=("runtime/router.py, runtime/engine.py", "runtime/router.py, runtime/engine.py"),
                risk_lines=("范围取舍仍待拍板", "继续推进前需要先明确最终选项"),
            )

            current_run = store.get_current_run()
            self.assertIsNotNone(current_run)
            gate = evaluate_execution_gate(
                decision=RouteDecision(
                    route_name="resume_active",
                    request_text="开始",
                    reason="test",
                    complexity="medium",
                    candidate_skill_ids=("develop",),
                ),
                plan_artifact=plan_artifact,
                current_clarification=None,
                current_decision=None,
                config=config,
            )
            self.assertEqual(gate.gate_status, "decision_required")
            self.assertEqual(gate.blocking_reason, "scope_tradeoff")

            pending_decision = build_execution_gate_decision_state(
                RouteDecision(
                    route_name="resume_active",
                    request_text="开始",
                    reason="test",
                    complexity="medium",
                    candidate_skill_ids=("develop",),
                ),
                gate=gate,
                current_plan=plan_artifact,
                config=config,
            )
            self.assertIsNotNone(pending_decision)
            confirmed = confirm_decision(
                pending_decision,
                option_id=pending_decision.options[0].option_id,
                source="text",
                raw_input="1",
            )

            routed, routed_plan, notes = _handle_execution_confirm(
                RouteDecision(
                    route_name="execution_confirm_pending",
                    request_text="开始",
                    reason="test",
                    complexity="medium",
                    should_recover_context=True,
                    candidate_skill_ids=("develop",),
                    active_run_action="confirm_execution",
                ),
                state_store=store,
                current_plan=plan_artifact,
                current_run=current_run,
                current_clarification=None,
                current_decision=confirmed,
                config=config,
                session_id=None,
            )

            self.assertEqual(routed.route_name, "resume_active")
            self.assertIsNotNone(routed_plan)
            self.assertEqual(routed_plan.plan_id, plan_artifact.plan_id)
            self.assertEqual(store.get_current_run().stage, "executing")
            self.assertIsNone(store.get_current_decision())
            self.assertTrue(any("Execution confirmed by user" in note for note in notes))

    def test_execution_confirm_surfaces_new_gate_decision_in_same_round_result_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            current_plan = store.get_current_plan()
            self.assertIsNotNone(current_plan)
            _rewrite_background_scope(
                workspace,
                current_plan,
                scope_lines=("runtime/router.py, runtime/engine.py", "runtime/router.py, runtime/engine.py"),
                risk_lines=("范围取舍仍待拍板", "继续推进前需要先明确最终选项"),
            )

            run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")
            result = run_runtime("开始", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "decision_pending")
            self.assertIsNotNone(result.recovered_context.current_decision)
            self.assertEqual(result.recovered_context.current_decision.phase, "execution_gate")
            self.assertEqual(result.recovered_context.current_run.stage, "decision_pending")
            self.assertEqual(result.handoff.required_host_action, "confirm_decision")
            persisted_decision = StateStore(config).get_current_decision()
            self.assertIsNotNone(persisted_decision)
            self.assertEqual(persisted_decision.phase, "execution_gate")

    def test_session_plan_reference_persists_execution_gate_decision_in_global_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            session_id = "session-a"
            config, store, plan_artifact = _prepare_ready_plan_state(
                workspace,
                request_text="调整 auth boundary",
                session_id=session_id,
            )
            _rewrite_background_scope(
                workspace,
                plan_artifact,
                scope_lines=("runtime/engine.py", "runtime/engine.py, runtime/router.py"),
                risk_lines=("本轮会调整认证与权限边界", "需要先明确批准路径"),
            )

            routed, resolved_plan, notes, _ = _advance_planning_route(
                RouteDecision(
                    route_name="workflow",
                    request_text=f"分析下 {plan_artifact.plan_id} 是否可以执行",
                    reason="test",
                    complexity="medium",
                    plan_package_policy="confirm",
                    capture_mode="summary",
                ),
                state_store=store,
                config=config,
                kb_artifact=None,
            )

            self.assertEqual(routed.route_name, "decision_pending")
            self.assertIsNotNone(resolved_plan)
            self.assertEqual(resolved_plan.plan_id, plan_artifact.plan_id)
            self.assertTrue(any("Promoted execution gate checkpoint to global execution truth" in note for note in notes))

            session_store = StateStore(config, session_id=session_id)
            global_store = StateStore(config)
            self.assertIsNone(session_store.get_current_decision())
            self.assertIsNone(session_store.get_current_run())
            self.assertIsNone(session_store.get_current_handoff())

            persisted_decision = global_store.get_current_decision()
            self.assertIsNotNone(persisted_decision)
            self.assertEqual(persisted_decision.phase, "execution_gate")
            self.assertEqual(global_store.get_current_run().stage, "decision_pending")

    def test_session_plan_reference_followup_runtime_turn_does_not_conflict_after_global_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            session_id = "session-a"
            config, store, plan_artifact = _prepare_ready_plan_state(
                workspace,
                request_text="调整 auth boundary",
                session_id=session_id,
            )
            _rewrite_background_scope(
                workspace,
                plan_artifact,
                scope_lines=("runtime/engine.py", "runtime/engine.py, runtime/router.py"),
                risk_lines=("本轮会调整认证与权限边界", "需要先明确批准路径"),
            )

            _advance_planning_route(
                RouteDecision(
                    route_name="workflow",
                    request_text=f"分析下 {plan_artifact.plan_id} 是否可以执行",
                    reason="test",
                    complexity="medium",
                    plan_package_policy="confirm",
                    capture_mode="summary",
                ),
                state_store=store,
                config=config,
                kb_artifact=None,
            )

            followup = run_runtime(
                "继续",
                workspace_root=workspace,
                session_id=session_id,
                user_home=workspace / "home",
            )

            self.assertNotEqual(followup.route.route_name, "state_conflict")
            self.assertFalse(followup.recovered_context.state_conflict)
            self.assertEqual(followup.route.route_name, "decision_pending")
            self.assertEqual(followup.handoff.required_host_action, "confirm_decision")

    def test_develop_checkpoint_helper_writes_decision_checkpoint_and_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            inspected = inspect_develop_checkpoint_context(config=config)
            self.assertEqual(inspected["status"], "ready")
            self.assertEqual(inspected["required_host_action"], "continue_host_develop")
            self.assertEqual(inspected["quality_contract"]["max_retry_count"], 1)

            submission = submit_develop_checkpoint(
                {
                    "schema_version": "1",
                    "checkpoint_kind": "decision",
                    "question": "认证边界是否移动到 adapter 层？",
                    "summary": "开发中已经形成两条可执行路径，需要用户拍板。",
                    "options": [
                        {"id": "option_1", "title": "保持现状", "summary": "边界继续留在当前层", "recommended": True},
                        {"id": "option_2", "title": "移动边界", "summary": "把认证边界下推到 adapter 层"},
                    ],
                    "resume_context": {
                        "active_run_stage": "executing",
                        "current_plan_path": ".sopify-skills/plan/20260319_feature",
                        "task_refs": ["2.1", "2.2"],
                        "changed_files": ["runtime/engine.py", "runtime/handoff.py"],
                        "working_summary": "develop callback 已接入，需要确认认证边界。",
                        "verification_todo": ["补 develop checkpoint contract 测试"],
                        "resume_after": "continue_host_develop",
                    },
                },
                config=config,
            )

            self.assertEqual(submission.handoff.required_host_action, "confirm_decision")
            self.assertEqual(submission.route.route_name, "decision_pending")
            store = StateStore(config)
            current_run = store.get_current_run()
            current_decision = store.get_current_decision()
            current_handoff = store.get_current_handoff()
            self.assertIsNotNone(current_decision)
            self.assertIsNotNone(current_run)
            self.assertIsNotNone(current_handoff)
            self.assertEqual(current_decision.phase, "develop")
            self.assertEqual(current_decision.resume_context["resume_after"], "continue_host_develop")
            self.assertTrue(submission.run_state.resolution_id)
            self.assertEqual(submission.run_state.resolution_id, submission.handoff.resolution_id)
            self.assertEqual(current_run.resolution_id, current_handoff.resolution_id)
            self.assertEqual(current_handoff.artifacts["resume_context"]["working_summary"], "develop callback 已接入，需要确认认证边界。")

    def test_develop_quality_report_updates_handoff_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            submission = submit_develop_quality_report(
                {
                    "schema_version": "1",
                    "task_refs": ["2.1"],
                    "changed_files": ["runtime/engine.py", "runtime/handoff.py"],
                    "working_summary": "已把 develop 质量 contract 接到继续开发 handoff。",
                    "verification_todo": ["补 develop replay 断言"],
                    "quality_result": {
                        "schema_version": "1",
                        "verification_source": "project_native",
                        "command": "python -m unittest tests.test_runtime_engine -v",
                        "scope": "runtime/engine.py, runtime/handoff.py",
                        "result": "passed",
                        "retry_count": 0,
                        "review_result": {
                            "spec_compliance": {"status": "passed", "summary": "满足当前任务范围"},
                            "code_quality": {"status": "passed", "summary": "修改面与任务规模匹配"},
                        },
                    },
                },
                config=config,
            )

            self.assertIsNone(submission.delegated_checkpoint)
            self.assertEqual(submission.handoff.required_host_action, "continue_host_develop")
            store = StateStore(config)
            handoff = store.get_current_handoff()
            self.assertEqual(handoff.artifacts["task_refs"], ["2.1"])
            self.assertEqual(handoff.artifacts["verification_source"], "project_native")
            self.assertEqual(handoff.artifacts["result"], "passed")
            self.assertEqual(handoff.artifacts["retry_count"], 0)
            self.assertEqual(handoff.artifacts["review_result"]["spec_compliance"]["status"], "passed")
            self.assertIn("develop_quality_contract", handoff.artifacts)
            session_text = (workspace / submission.replay_session_dir / "session.md").read_text(encoding="utf-8")
            breakdown_text = (workspace / submission.replay_session_dir / "breakdown.md").read_text(encoding="utf-8")
            self.assertIn("质量结果=passed", session_text)
            self.assertIn("任务: 2.1", breakdown_text)

    def test_develop_quality_report_requires_checkpoint_for_scope_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            with self.assertRaisesRegex(DevelopCheckpointError, "requires checkpoint_kind"):
                submit_develop_quality_report(
                    {
                        "schema_version": "1",
                        "task_refs": ["3.1"],
                        "changed_files": ["runtime/engine.py"],
                        "working_summary": "当前改动已经超出原始范围。",
                        "verification_todo": ["回到 plan review 重新整理任务"],
                        "quality_result": {
                            "schema_version": "1",
                            "verification_source": "project_native",
                            "command": "python -m unittest tests.test_runtime_engine -v",
                            "scope": "runtime/engine.py",
                            "result": "replan_required",
                            "reason_code": "scope_changed",
                            "retry_count": 1,
                            "root_cause": "scope_or_design_mismatch",
                            "review_result": {
                                "spec_compliance": {"status": "failed", "summary": "用户反馈已超出当前 plan 边界"},
                                "code_quality": {"status": "not_run", "summary": "等待新的范围决策"},
                            },
                        },
                    },
                    config=config,
                )

    def test_develop_quality_report_can_delegate_to_plan_review_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            submission = submit_develop_quality_report(
                {
                    "schema_version": "1",
                    "task_refs": ["3.1"],
                    "changed_files": ["runtime/engine.py", "README.md"],
                    "working_summary": "质量闭环确认当前改动已经超出原始范围。",
                    "verification_todo": ["回到 plan review 重新整理任务"],
                    "quality_result": {
                        "schema_version": "1",
                        "verification_source": "project_native",
                        "command": "python -m unittest tests.test_runtime_engine -v",
                        "scope": "runtime/engine.py, README.md",
                        "result": "replan_required",
                        "reason_code": "scope_changed",
                        "retry_count": 1,
                        "root_cause": "scope_or_design_mismatch",
                        "review_result": {
                            "spec_compliance": {"status": "failed", "summary": "已超出当前 plan 边界"},
                            "code_quality": {"status": "not_run", "summary": "等待新的范围确认"},
                        },
                    },
                    "checkpoint_kind": "decision",
                    "question": "是否扩大本轮改动范围？",
                    "summary": "质量闭环识别出 scope_or_design_mismatch，需要用户拍板。",
                    "options": [
                        {"id": "option_1", "title": "维持原范围", "summary": "回到 plan review", "recommended": True},
                        {"id": "option_2", "title": "扩大范围", "summary": "进入新范围评审"},
                    ],
                },
                config=config,
            )

            self.assertIsNotNone(submission.delegated_checkpoint)
            self.assertEqual(submission.handoff.required_host_action, "confirm_decision")
            store = StateStore(config)
            handoff = store.get_current_handoff()
            self.assertEqual(handoff.artifacts["result"], "replan_required")
            self.assertEqual(handoff.artifacts["root_cause"], "scope_or_design_mismatch")
            self.assertEqual(handoff.artifacts["resume_context"]["resume_after"], "review_or_execute_plan")
            self.assertEqual(
                handoff.artifacts["resume_context"]["develop_quality_result"]["result"],
                "replan_required",
            )

    def test_develop_quality_result_is_carried_forward_after_decision_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            submit_develop_quality_report(
                {
                    "schema_version": "1",
                    "task_refs": ["2.2"],
                    "changed_files": ["runtime/engine.py"],
                    "working_summary": "最近一次 develop task 已通过质量闭环。",
                    "verification_todo": [],
                    "quality_result": {
                        "schema_version": "1",
                        "verification_source": "project_native",
                        "command": "python -m unittest tests.test_runtime_engine -v",
                        "scope": "runtime/engine.py",
                        "result": "passed",
                        "retry_count": 0,
                        "review_result": {
                            "spec_compliance": {"status": "passed", "summary": "满足任务目标"},
                            "code_quality": {"status": "passed", "summary": "代码风格一致"},
                        },
                    },
                },
                config=config,
            )
            submit_develop_checkpoint(
                {
                    "schema_version": "1",
                    "checkpoint_kind": "decision",
                    "question": "认证边界是否移动到 adapter 层？",
                    "summary": "开发中已经形成两条可执行路径，需要用户拍板。",
                    "options": [
                        {"id": "option_1", "title": "保持现状", "summary": "边界继续留在当前层", "recommended": True},
                        {"id": "option_2", "title": "移动边界", "summary": "把认证边界下推到 adapter 层"},
                    ],
                    "resume_context": {
                        "active_run_stage": "executing",
                        "current_plan_path": ".sopify-skills/plan/20260319_feature",
                        "task_refs": ["2.2"],
                        "changed_files": ["runtime/engine.py"],
                        "working_summary": "认证边界待确认。",
                        "verification_todo": [],
                        "resume_after": "continue_host_develop",
                    },
                },
                config=config,
            )

            resumed = run_runtime("1", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.handoff.required_host_action, "continue_host_develop")
            self.assertEqual(resumed.handoff.artifacts["result"], "passed")
            self.assertEqual(resumed.handoff.artifacts["task_refs"], ["2.2"])

    def test_develop_checkpoint_missing_kind_with_tradeoff_payload_emits_reason_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            with self.assertRaisesRegex(DevelopCheckpointError, CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED):
                submit_develop_checkpoint(
                    {
                        "schema_version": "1",
                        "question": "认证边界是否移动到 adapter 层？",
                        "summary": "开发中已经形成两条可执行路径，需要用户拍板。",
                        "options": [
                            {"id": "option_1", "title": "保持现状", "summary": "边界继续留在当前层"},
                            {"id": "option_2", "title": "移动边界", "summary": "把认证边界下推到 adapter 层"},
                        ],
                        "resume_context": {
                            "active_run_stage": "executing",
                            "current_plan_path": ".sopify-skills/plan/20260319_feature",
                            "task_refs": ["2.1"],
                            "changed_files": ["runtime/develop_checkpoint.py"],
                            "working_summary": "发现开发中分叉但 payload 未声明 checkpoint_kind。",
                            "verification_todo": ["补 develop callback payload 校验"],
                            "resume_after": "continue_host_develop",
                        },
                    },
                    config=config,
                )

    def test_develop_decision_resume_returns_continue_host_develop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            submit_develop_checkpoint(
                {
                    "schema_version": "1",
                    "checkpoint_kind": "decision",
                    "question": "认证边界是否移动到 adapter 层？",
                    "summary": "开发中已经形成两条可执行路径，需要用户拍板。",
                    "options": [
                        {"id": "option_1", "title": "保持现状", "summary": "边界继续留在当前层", "recommended": True},
                        {"id": "option_2", "title": "移动边界", "summary": "把认证边界下推到 adapter 层"},
                    ],
                    "resume_context": {
                        "active_run_stage": "executing",
                        "current_plan_path": ".sopify-skills/plan/20260319_feature",
                        "task_refs": ["2.1"],
                        "changed_files": ["runtime/engine.py"],
                        "working_summary": "认证边界待确认。",
                        "verification_todo": ["补 bundle contract 测试"],
                        "resume_after": "continue_host_develop",
                    },
                },
                config=config,
            )

            resumed = run_runtime("1", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "resume_active")
            self.assertEqual(resumed.handoff.required_host_action, "continue_host_develop")
            self.assertEqual(resumed.recovered_context.current_run.stage, "executing")
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_develop_decision_resume_can_fallback_to_plan_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            submit_develop_checkpoint(
                {
                    "schema_version": "1",
                    "checkpoint_kind": "decision",
                    "question": "是否扩大本轮改动范围？",
                    "summary": "用户反馈已经改变本轮 plan 范围，需要退回 plan review。",
                    "options": [
                        {"id": "option_1", "title": "维持原范围", "summary": "继续当前 plan", "recommended": True},
                        {"id": "option_2", "title": "扩大范围", "summary": "回退到 plan review 重新评审"},
                    ],
                    "resume_context": {
                        "active_run_stage": "executing",
                        "current_plan_path": ".sopify-skills/plan/20260319_feature",
                        "task_refs": ["3.1"],
                        "changed_files": ["runtime/engine.py", "README.md"],
                        "working_summary": "用户反馈超出了当前 plan 边界。",
                        "verification_todo": ["回到 plan review 后重新整理任务"],
                        "resume_after": "review_or_execute_plan",
                    },
                },
                config=config,
            )

            resumed = run_runtime("2", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "plan_only")
            self.assertEqual(resumed.handoff.required_host_action, "review_or_execute_plan")
            self.assertEqual(resumed.recovered_context.current_run.stage, "plan_generated")
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_develop_clarification_resume_returns_continue_host_develop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            submit_develop_checkpoint(
                {
                    "schema_version": "1",
                    "checkpoint_kind": "clarification",
                    "summary": "需要补齐验收口径后才能继续开发。",
                    "missing_facts": ["acceptance_scope"],
                    "questions": ["本轮是否需要兼容旧版 adapter？"],
                    "resume_context": {
                        "active_run_stage": "executing",
                        "current_plan_path": ".sopify-skills/plan/20260319_feature",
                        "task_refs": ["4.2"],
                        "changed_files": ["runtime/develop_checkpoint.py"],
                        "working_summary": "缺少 adapter 兼容性口径。",
                        "verification_todo": ["补 compatibility case"],
                        "resume_after": "continue_host_develop",
                    },
                },
                config=config,
            )

            resumed = run_runtime("需要兼容旧版 adapter。", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "resume_active")
            self.assertEqual(resumed.handoff.required_host_action, "continue_host_develop")
            self.assertEqual(resumed.recovered_context.current_run.stage, "executing")
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())

    def test_develop_pending_decision_does_not_bypass_checkpoint_when_resume_bridge_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            submit_develop_checkpoint(
                {
                    "schema_version": "1",
                    "checkpoint_kind": "decision",
                    "question": "是否扩大本轮改动范围？",
                    "summary": "开发中命中范围分叉，需要用户拍板。",
                    "options": [
                        {"id": "option_1", "title": "维持范围", "summary": "继续当前改动", "recommended": True},
                        {"id": "option_2", "title": "扩大范围", "summary": "回退到 plan review"},
                    ],
                    "resume_context": {
                        "active_run_stage": "executing",
                        "current_plan_path": ".sopify-skills/plan/20260319_feature",
                        "task_refs": ["3.6"],
                        "changed_files": ["runtime/engine.py"],
                        "working_summary": "decision checkpoint 已创建，等待桥接提交。",
                        "verification_todo": ["确认缺失 bridge 时 fail-closed"],
                        "resume_after": "continue_host_develop",
                    },
                },
                config=config,
            )

            still_pending = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")
            blocked_exec = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(still_pending.route.route_name, "decision_pending")
            self.assertEqual(still_pending.handoff.required_host_action, "confirm_decision")
            self.assertEqual(blocked_exec.route.route_name, "decision_pending")
            self.assertEqual(blocked_exec.handoff.required_host_action, "confirm_decision")
            self.assertEqual(blocked_exec.recovered_context.current_run.stage, "decision_pending")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_decision_pending_cancel_prefix_cancels_checkpoint_with_negation_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            cancelled = run_runtime("取消这个 checkpoint", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(cancelled.route.route_name, "cancel_active")
            self.assertTrue(any("Decision checkpoint cancelled" in note for note in cancelled.notes))
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            negated = run_runtime("不要取消这个 checkpoint", workspace_root=workspace, user_home=workspace / "home")
            soft_negated = run_runtime("先别取消", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(negated.route.route_name, "decision_pending")
            self.assertEqual(negated.handoff.required_host_action, "confirm_decision")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())
            self.assertEqual(soft_negated.route.route_name, "decision_pending")
            self.assertEqual(soft_negated.handoff.required_host_action, "confirm_decision")

    def test_decision_pending_cancel_prefix_without_boundary_does_not_cancel_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            result = run_runtime("取消后为什么还会回到 pending", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "decision_pending")
            self.assertEqual(result.handoff.required_host_action, "confirm_decision")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_decision_pending_question_mark_cancel_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            state_root = workspace / ".sopify-skills" / "state"
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            bare_question = run_runtime("取消这个 checkpoint?", workspace_root=workspace, user_home=workspace / "home")
            trailing_question = run_runtime(
                "取消这个 checkpoint？为什么还会回到 pending",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            emphatic = run_runtime("取消这个 checkpoint！", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(bare_question.route.route_name, "decision_pending")
            self.assertEqual(bare_question.handoff.required_host_action, "confirm_decision")
            self.assertEqual(trailing_question.route.route_name, "decision_pending")
            self.assertEqual(trailing_question.handoff.required_host_action, "confirm_decision")
            self.assertEqual(emphatic.route.route_name, "cancel_active")
            self.assertFalse((state_root / "current_decision.json").exists())

    def test_decision_pending_period_and_clause_punctuation_are_fail_closed_when_text_follows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            state_root = workspace / ".sopify-skills" / "state"
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            period_route = run_runtime(
                "取消这个 checkpoint。为什么还会回到 pending",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            colon_route = run_runtime(
                "取消这个 checkpoint: 为什么还会回到 pending",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            semicolon_route = run_runtime(
                "取消这个 checkpoint；为什么还会回到 pending",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            bare_period_route = run_runtime(
                "取消这个 checkpoint。",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(period_route.route.route_name, "decision_pending")
            self.assertEqual(period_route.handoff.required_host_action, "confirm_decision")
            self.assertEqual(colon_route.route.route_name, "decision_pending")
            self.assertEqual(colon_route.handoff.required_host_action, "confirm_decision")
            self.assertEqual(semicolon_route.route.route_name, "decision_pending")
            self.assertEqual(semicolon_route.handoff.required_host_action, "confirm_decision")
            self.assertEqual(bare_period_route.route.route_name, "cancel_active")
            self.assertFalse((state_root / "current_decision.json").exists())

    def test_plan_proposal_cancel_does_not_derive_new_pending_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            state_root = workspace / ".sopify-skills" / "state"
            run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")

            cancelled = run_runtime("取消这个 checkpoint", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(cancelled.route.route_name, "cancel_active")
            self.assertFalse((state_root / "current_plan_proposal.json").exists())
            self.assertFalse((state_root / "current_decision.json").exists())
            self.assertFalse((state_root / "current_clarification.json").exists())

    def test_mixed_sentence_cancel_keeps_local_cancel_intent_for_both_pending_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            state_root = workspace / ".sopify-skills" / "state"

            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            decision_cancelled = run_runtime(
                "取消这个 checkpoint，不要取消全部",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(decision_cancelled.route.route_name, "cancel_active")
            self.assertFalse((state_root / "current_decision.json").exists())

            run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            proposal_cancelled = run_runtime(
                "取消这个 checkpoint，不要取消全部",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(proposal_cancelled.route.route_name, "cancel_active")
            self.assertFalse((state_root / "current_plan_proposal.json").exists())

    def test_ready_plan_with_residual_review_checkpoint_enters_execution_confirm_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, store, _ = _prepare_ready_plan_state(workspace)
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

            conflicted = run_runtime("status", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(conflicted.route.route_name, "state_conflict")
            self.assertEqual(conflicted.handoff.required_host_action, "resolve_state_conflict")
            self.assertEqual(conflicted.recovered_context.state_conflict["code"], "execution_confirm_review_checkpoint_conflict")

    def test_execution_confirmation_feedback_routes_back_to_plan_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)

            result = run_runtime("风险描述再具体一点", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "execution_confirm_pending")
            self.assertEqual(result.recovered_context.current_run.stage, "execution_confirm_pending")
            self.assertEqual(result.handoff.required_host_action, "review_or_execute_plan")
            self.assertEqual(result.handoff.artifacts["execution_feedback"], "风险描述再具体一点")

    def test_engine_handles_plan_resume_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            first = run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(first.route.route_name, "plan_only")
            self.assertIsNotNone(first.plan_artifact)
            self.assertIsNotNone(first.replay_session_dir)
            self.assertTrue((workspace / ".sopify-skills" / "project.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "README.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "background.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "design.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "tasks.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "user" / "preferences.md").exists())
            self.assertFalse((workspace / ".sopify-skills" / "history" / "index.md").exists())
            self.assertFalse((workspace / ".sopify-skills" / "wiki").exists())
            self.assertEqual(first.handoff.required_host_action, "review_or_execute_plan")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())

            resumed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(resumed.route.route_name, "resume_active")
            self.assertTrue(resumed.recovered_context.has_active_run)
            self.assertTrue(resumed.recovered_context.loaded_files)
            self.assertIsNotNone(resumed.handoff)
            self.assertEqual(resumed.handoff.handoff_kind, "develop")
            self.assertEqual(resumed.handoff.required_host_action, "continue_host_develop")

            canceled = run_runtime("取消", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(canceled.route.route_name, "cancel_active")
            store = StateStore(load_runtime_config(workspace))
            self.assertFalse(store.has_active_flow())
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())

    def test_engine_populates_blueprint_scaffold_on_first_plan_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "README.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "background.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "design.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "tasks.md").exists())
            blueprint_readme = (workspace / ".sopify-skills" / "blueprint" / "README.md").read_text(encoding="utf-8")
            self.assertIn("状态: L2 plan-active", blueprint_readme)
            self.assertIn("当前活动方案目录：`../plan/`", blueprint_readme)
            self.assertNotIn("../history/index.md", blueprint_readme)

    def test_engine_finalizes_metadata_managed_plan_into_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            first = run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")
            self.assertIsNotNone(first.plan_artifact)

            result = run_runtime("~go finalize", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "finalize_active")
            self.assertIsNotNone(result.plan_artifact)
            self.assertTrue(result.plan_artifact.path.startswith(".sopify-skills/history/"))
            self.assertFalse((workspace / first.plan_artifact.path).exists())
            self.assertTrue((workspace / result.plan_artifact.path).exists())
            self.assertTrue(any("knowledge_sync" in note for note in result.notes))
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_run.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())
            self.assertIsNotNone(result.handoff)
            self.assertEqual(result.handoff.required_host_action, "finalize_completed")
            self.assertEqual(result.handoff.handoff_kind, "finalize")
            self.assertEqual(result.handoff.artifacts["archived_plan_path"], result.plan_artifact.path)
            self.assertEqual(result.handoff.artifacts["history_index_path"], ".sopify-skills/history/index.md")
            self.assertTrue(result.handoff.artifacts["state_cleared"])

            history_index = (workspace / ".sopify-skills" / "history" / "index.md").read_text(encoding="utf-8")
            self.assertIn(first.plan_artifact.plan_id, history_index)
            self.assertNotIn("当前暂无已归档方案。", history_index)

            blueprint_readme = (workspace / ".sopify-skills" / "blueprint" / "README.md").read_text(encoding="utf-8")
            self.assertIn("状态: L3 history-ready", blueprint_readme)
            self.assertIn("../history/index.md", blueprint_readme)
            self.assertIn("最近归档", blueprint_readme)
            self.assertIn("当前活动 plan：暂无", blueprint_readme)

    def test_finalize_blocks_full_plan_without_deep_blueprint_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            proposal = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            self.assertEqual(proposal.route.route_name, "plan_proposal_pending")
            first = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")
            self.assertIsNotNone(first.plan_artifact)
            self.assertEqual(first.plan_artifact.level, "full")

            result = run_runtime("~go finalize", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "finalize_active")
            self.assertIsNone(result.plan_artifact)
            self.assertTrue(any("knowledge_sync.required" in note for note in result.notes))
            self.assertTrue((workspace / first.plan_artifact.path).exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())
            self.assertIsNotNone(result.handoff)
            self.assertEqual(result.handoff.required_host_action, "review_or_execute_plan")
            self.assertEqual(result.handoff.handoff_kind, "finalize")
            self.assertEqual(result.handoff.artifacts["finalize_status"], "blocked")
            self.assertEqual(result.handoff.artifacts["active_plan_path"], first.plan_artifact.path)
            self.assertFalse(result.handoff.artifacts["state_cleared"])

    def test_finalize_allows_review_and_blocks_required_by_knowledge_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            review_plan = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            store.set_current_plan(review_plan)
            review_result = run_runtime("~go finalize", workspace_root=workspace, user_home=workspace / "home")
            self.assertIsNotNone(review_result.plan_artifact)
            self.assertTrue(any("knowledge_sync" in note for note in review_result.notes))
            self.assertTrue((workspace / ".sopify-skills" / "history" / "index.md").exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            required_plan = create_plan_scaffold("设计 runtime architecture plugin bridge", config=config, level="full")
            store.set_current_plan(required_plan)
            required_result = run_runtime("~go finalize", workspace_root=workspace, user_home=workspace / "home")
            self.assertIsNone(required_result.plan_artifact)
            self.assertTrue(any("knowledge_sync.required" in note for note in required_result.notes))

    def test_finalize_rejects_legacy_plan_without_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()

            legacy_dir = workspace / ".sopify-skills" / "plan" / "legacy_plan"
            legacy_dir.mkdir(parents=True)
            legacy_tasks = legacy_dir / "tasks.md"
            legacy_tasks.write_text("# legacy plan\n", encoding="utf-8")

            store.set_current_plan(
                PlanArtifact(
                    plan_id="legacy_plan",
                    title="Legacy Plan",
                    summary="legacy",
                    level="standard",
                    path=".sopify-skills/plan/legacy_plan",
                    files=(".sopify-skills/plan/legacy_plan/tasks.md",),
                    created_at=iso_now(),
                )
            )
            store.set_current_run(
                RunState(
                    run_id="legacy-run",
                    status="active",
                    stage="plan_ready",
                    route_name="workflow",
                    title="Legacy Plan",
                    created_at=iso_now(),
                    updated_at=iso_now(),
                    plan_id="legacy_plan",
                    plan_path=".sopify-skills/plan/legacy_plan",
                )
            )

            result = run_runtime("~go finalize", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "finalize_active")
            self.assertIsNone(result.plan_artifact)
            self.assertTrue(any("metadata-managed" in note for note in result.notes))
            self.assertTrue(legacy_tasks.exists())

    def test_engine_creates_decision_checkpoint_before_materializing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "decision_pending")
            self.assertIsNone(result.plan_artifact)
            self.assertIsNotNone(result.recovered_context.current_decision)
            self.assertEqual(result.handoff.handoff_kind, "decision")
            self.assertEqual(result.handoff.required_host_action, "confirm_decision")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "design.md").exists())

    def test_engine_materializes_plan_after_decision_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            result = run_runtime("1", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertIsNotNone(result.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())
            self.assertEqual(result.recovered_context.current_run.stage, "plan_generated")
            self.assertEqual(result.recovered_context.current_run.execution_gate.gate_status, "blocked")
            self.assertEqual(result.handoff.artifacts["execution_gate"]["blocking_reason"], "missing_info")
            tasks_path = workspace / result.plan_artifact.path / "tasks.md"
            design_path = workspace / result.plan_artifact.path / "design.md"
            self.assertIn("decision_checkpoint:", tasks_path.read_text(encoding="utf-8"))
            self.assertIn("## 决策确认", design_path.read_text(encoding="utf-8"))

    def test_engine_accepts_explicit_option_id_command_for_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            result = run_runtime("~decide choose option_1", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertIsNotNone(result.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_engine_materializes_plan_after_structured_decision_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            store = StateStore(load_runtime_config(workspace))
            store.set_current_decision_submission(
                DecisionSubmission(
                    status="submitted",
                    source="cli",
                    answers={
                        "selected_option_id": "option_1",
                        "implementation_notes": "继续保持 manifest-first 与默认入口不变",
                    },
                    submitted_at=iso_now(),
                    resume_action="submit",
                )
            )

            result = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertIsNotNone(result.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())
            self.assertEqual(result.recovered_context.current_run.stage, "plan_generated")
            self.assertTrue(any("structured submission" in note for note in result.notes))

    def test_confirmed_decision_can_resume_after_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            confirmed = confirm_decision(
                pending.recovered_context.current_decision,
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            store.set_current_decision(confirmed)

            resumed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "plan_only")
            self.assertIsNotNone(resumed.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_confirmed_decision_can_materialize_through_exec_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            confirmed = confirm_decision(
                pending.recovered_context.current_decision,
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            store.set_current_decision(confirmed)

            resumed = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "plan_only")
            self.assertIsNotNone(resumed.plan_artifact)
            self.assertEqual(resumed.recovered_context.current_run.stage, "plan_generated")
            self.assertEqual(resumed.recovered_context.current_run.execution_gate.blocking_reason, "missing_info")
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_confirmed_gate_decision_reenters_execution_gate_on_existing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            plan_artifact = create_plan_scaffold("调整 auth boundary", config=config, level="standard")
            _rewrite_background_scope(
                workspace,
                plan_artifact,
                scope_lines=("runtime/engine.py", "runtime/engine.py, runtime/router.py"),
                risk_lines=("本轮会调整认证与权限边界", "需要先明确批准路径"),
            )
            route = RouteDecision(
                route_name="workflow",
                request_text="调整 auth boundary",
                reason="test",
                complexity="complex",
                plan_level="standard",
                candidate_skill_ids=("design", "develop"),
            )
            gate = evaluate_execution_gate(
                decision=route,
                plan_artifact=plan_artifact,
                current_clarification=None,
                current_decision=None,
                config=config,
            )
            gate_decision = build_execution_gate_decision_state(
                route,
                gate=gate,
                current_plan=plan_artifact,
                config=config,
            )
            self.assertIsNotNone(gate_decision)
            self.assertEqual(gate_decision.phase, "execution_gate")
            store.set_current_plan(plan_artifact)
            store.set_current_run(
                RunState(
                    run_id="run-1",
                    status="active",
                    stage="decision_pending",
                    route_name="workflow",
                    title=plan_artifact.title,
                    created_at=iso_now(),
                    updated_at=iso_now(),
                    plan_id=plan_artifact.plan_id,
                    plan_path=plan_artifact.path,
                    execution_gate=gate,
                )
            )
            confirmed = confirm_decision(
                replace(
                    gate_decision,
                    resume_context={
                        "resume_after": "continue_host_develop",
                        "active_run_stage": "decision_pending",
                        "current_plan_path": plan_artifact.path,
                        "task_refs": [],
                        "changed_files": [],
                        "working_summary": "Execution gate decision was confirmed on the existing plan",
                        "verification_todo": [],
                    },
                ),
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            store.set_current_decision(confirmed)

            resumed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "plan_only")
            self.assertIsNotNone(resumed.plan_artifact)
            self.assertEqual(resumed.plan_artifact.path, plan_artifact.path)
            self.assertEqual(resumed.recovered_context.current_run.stage, "ready_for_execution")
            self.assertEqual(resumed.recovered_context.current_run.execution_gate.gate_status, "ready")
            self.assertEqual(resumed.handoff.required_host_action, "review_or_execute_plan")
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_engine_handoff_contracts_cover_compare_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            compare = run_runtime("~compare 方案对比", workspace_root=workspace, user_home=workspace / "home")
            self.assertIsNotNone(compare.handoff)
            self.assertEqual(compare.handoff.handoff_kind, "compare")
            self.assertEqual(compare.handoff.required_host_action, "host_compare_bridge_required")

            replay = run_runtime("回放最近一次实现", workspace_root=workspace, user_home=workspace / "home")
            self.assertIsNotNone(replay.handoff)
            self.assertEqual(replay.handoff.handoff_kind, "replay")
            self.assertEqual(replay.handoff.required_host_action, "host_replay_bridge_required")

    def test_compare_handoff_attaches_decision_facade_when_runtime_returns_results(self) -> None:
        def model_caller(candidate, payload, timeout_sec):
            return {"answer": f"{candidate.id} suggests using an adapter boundary for {payload['question']}"}

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            compare = run_runtime(
                "~compare adapter boundary vs direct host coupling",
                workspace_root=workspace,
                user_home=workspace / "home",
                runtime_payloads={
                    "model-compare": {
                        "question": "adapter boundary vs direct host coupling",
                        "multi_model_config": {
                            "enabled": True,
                            "include_default_model": True,
                            "context_bridge": False,
                            "candidates": [
                                {
                                    "id": "external_a",
                                    "provider": "openai_compatible",
                                    "model": "demo-a",
                                    "enabled": True,
                                    "api_key_env": "TEST_COMPARE_KEY",
                                }
                            ],
                        },
                        "model_caller": model_caller,
                        "default_candidate": make_default_candidate(),
                        "env": {"TEST_COMPARE_KEY": "sk-demo"},
                    }
                },
            )

            self.assertIsNotNone(compare.handoff)
            self.assertEqual(compare.handoff.required_host_action, "review_compare_results")
            contract = compare.handoff.artifacts.get("compare_decision_contract")
            self.assertIsInstance(contract, dict)
            self.assertEqual(contract["decision_type"], "compare_result_choice")
            self.assertIn("checkpoint", contract)
            self.assertEqual(contract["recommended_option_id"], "session_default")

    def test_rendered_plan_output_and_repo_local_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            result = run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")
            rendered = render_runtime_output(
                result,
                brand="demo-ai",
                language="zh-CN",
                title_color="none",
                use_color=False,
            )

            self.assertIn("[demo-ai] 方案设计 ✓", rendered)
            self.assertIn("方案: .sopify-skills/plan/", rendered)
            self.assertIn("交接: .sopify-skills/state/current_handoff.json", rendered)
            self.assertIn("Next: 在宿主会话中继续评审或执行方案，或直接回复修改意见", rendered)
            _assert_rendered_footer_contract(
                self,
                rendered,
                next_prefix="Next:",
            )

            events_path = workspace / result.replay_session_dir / "events.jsonl"
            event_payload = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(event_payload["metadata"]["activation"]["skill_id"], "design")
            self.assertEqual(event_payload["metadata"]["activation"]["route_name"], "plan_only")
            self.assertIn("display_time", event_payload["metadata"]["activation"])

            script_path = REPO_ROOT / "scripts" / "go_plan_runtime.py"
            completed = subprocess.run(
                [sys.executable, str(script_path), "--workspace-root", str(workspace), "--no-color", "补 runtime 骨架"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("[tmp", completed.stdout)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "replay" / "sessions").exists())
            self.assertTrue((workspace / ".sopify-skills" / "project.md").exists())
            self.assertIn(".sopify-skills/project.md", rendered)

    def test_summary_route_generates_daily_artifacts_and_preserves_active_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")
            store = StateStore(load_runtime_config(workspace))
            before_handoff = store.get_current_handoff()
            self.assertIsNotNone(before_handoff)
            assert before_handoff is not None

            result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "summary")
            self.assertIsNone(result.handoff)
            self.assertIsNotNone(result.skill_result)
            summary_payload = result.skill_result["summary"]
            self.assertEqual(summary_payload["scope"]["workspace_root"], str(workspace.resolve()))
            self.assertEqual(len(result.generated_files), 2)
            for path in result.generated_files:
                self.assertTrue((workspace / path).exists())

            after_handoff = store.get_current_handoff()
            self.assertIsNotNone(after_handoff)
            assert after_handoff is not None
            self.assertEqual(after_handoff.to_dict(), before_handoff.to_dict())

            rendered = render_runtime_output(
                result,
                brand="demo-ai",
                language="zh-CN",
                title_color="none",
                use_color=False,
            )
            self.assertIn("[demo-ai] 今日详细摘要 ✓", rendered)
            self.assertIn("范围:", rendered)
            self.assertIn("## 代码变更详解", rendered)
            self.assertIn("Next: 可再次运行 ~summary 刷新，或继续当前开发流", rendered)
            _assert_rendered_footer_contract(
                self,
                rendered,
                next_prefix="Next:",
            )

    def test_summary_route_includes_uncommitted_git_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _init_git_workspace(workspace)
            tracked_file = workspace / "notes.md"
            tracked_file.write_text("# Notes\n\ninitial\n", encoding="utf-8")
            _run_git(workspace, "add", "notes.md")
            _run_git(workspace, "commit", "-m", "initial notes")
            tracked_file.write_text("# Notes\n\nupdated today\n", encoding="utf-8")

            result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "summary")
            summary_payload = result.skill_result["summary"]
            self.assertIn("notes.md", summary_payload["source_refs"]["git_refs"]["changed_files"])
            code_change_paths = [item["path"] for item in summary_payload["facts"]["code_changes"]]
            self.assertIn("notes.md", code_change_paths)
            markdown = result.skill_result["summary_markdown"]
            self.assertIn("[modified] notes.md", markdown)

    def test_summary_route_ignores_inherited_git_repo_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _init_git_workspace(workspace)
            tracked_file = workspace / "notes.md"
            tracked_file.write_text("# Notes\n\ninitial\n", encoding="utf-8")
            _run_git(workspace, "add", "notes.md")
            _run_git(workspace, "commit", "-m", "initial notes")
            tracked_file.write_text("# Notes\n\nupdated today\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(REPO_ROOT / ".git"),
                    "GIT_WORK_TREE": str(REPO_ROOT),
                    "GIT_INDEX_FILE": str(REPO_ROOT / ".git" / "index"),
                },
                clear=False,
            ):
                result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            summary_payload = result.skill_result["summary"]
            self.assertIn("notes.md", summary_payload["source_refs"]["git_refs"]["changed_files"])
            markdown = result.skill_result["summary_markdown"]
            self.assertIn("[modified] notes.md", markdown)

    def test_summary_route_increments_revision_when_rerun_same_day(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")

            first = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")
            second = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            first_payload = first.skill_result["summary"]
            second_payload = second.skill_result["summary"]
            self.assertEqual(first_payload["revision"], 1)
            self.assertEqual(second_payload["revision"], 2)
            self.assertEqual(first_payload["summary_key"], second_payload["summary_key"])

            summary_json_path = workspace / next(path for path in second.generated_files if path.endswith("summary.json"))
            persisted = json.loads(summary_json_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["revision"], 2)
            self.assertEqual(persisted["summary_key"], second_payload["summary_key"])

    def test_summary_route_rebuilds_invalid_existing_summary_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")

            day = local_day_now()
            summary_dir = workspace / ".sopify-skills" / "replay" / "daily" / day[:7] / day
            summary_dir.mkdir(parents=True, exist_ok=True)
            summary_json_path = summary_dir / "summary.json"
            summary_json_path.write_text("{broken", encoding="utf-8")

            result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            summary_payload = result.skill_result["summary"]
            self.assertEqual(summary_payload["revision"], 1)
            self.assertIn("existing_summary_invalid", summary_payload["quality_checks"]["fallback_used"])
            self.assertIn("已直接重建当前版本", result.skill_result["summary_markdown"])

            persisted = json.loads(summary_json_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, summary_payload)

    def test_summary_route_falls_back_when_git_binary_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")

            with mock.patch("runtime.daily_summary.subprocess.run", side_effect=FileNotFoundError("git")):
                result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            summary_payload = result.skill_result["summary"]
            quality_checks = summary_payload["quality_checks"]
            self.assertEqual(quality_checks["fallback_used"], ["git_unavailable"])
            self.assertIn("git_refs.changed_files", quality_checks["missing_inputs"])
            self.assertNotIn("plan_files", quality_checks["missing_inputs"])
            self.assertNotIn("state_files", quality_checks["missing_inputs"])
            self.assertEqual(summary_payload["source_refs"]["git_refs"]["changed_files"], [])

    def test_summary_route_preserves_active_run_and_last_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")
            store = StateStore(load_runtime_config(workspace))

            before_run = store.get_current_run()
            before_last_route = store.get_last_route()
            self.assertIsNotNone(before_run)
            self.assertIsNotNone(before_last_route)
            assert before_run is not None
            assert before_last_route is not None

            run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            after_run = store.get_current_run()
            after_last_route = store.get_last_route()
            self.assertIsNotNone(after_run)
            self.assertIsNotNone(after_last_route)
            assert after_run is not None
            assert after_last_route is not None
            self.assertEqual(after_run.to_dict(), before_run.to_dict())
            self.assertEqual(after_last_route.to_dict(), before_last_route.to_dict())
            self.assertEqual(after_last_route.route_name, "plan_only")

    def test_summary_route_en_us_output_uses_english_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("language: en-US\n", encoding="utf-8")
            _init_git_workspace(workspace)
            tracked_file = workspace / "notes.md"
            tracked_file.write_text("# Notes\n\ninitial\n", encoding="utf-8")
            _run_git(workspace, "add", "notes.md")
            _run_git(workspace, "commit", "-m", "initial notes")
            tracked_file.write_text("# Notes\n\nupdated today\n", encoding="utf-8")

            result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            markdown = result.skill_result["summary_markdown"]
            self.assertIn("## Daily Overview", markdown)
            self.assertIn("## Code Changes", markdown)
            self.assertIn("Change:", markdown)
            self.assertNotRegex(markdown, r"[\u4e00-\u9fff]")

    def test_summary_route_uses_dynamic_state_evidence_paths_for_custom_plan_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("plan:\n  directory: .runtime\n", encoding="utf-8")
            run_runtime("~go plan add summary route", workspace_root=workspace, user_home=workspace / "home")

            result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")

            summary_payload = result.skill_result["summary"]
            state_files = summary_payload["source_refs"]["state_files"]
            state_index_by_path = {entry["path"]: index for index, entry in enumerate(state_files)}
            current_run_ref = f"state_files[{state_index_by_path['.runtime/state/current_run.json']}]"

            issue = next(item for item in summary_payload["facts"]["issues"] if item["id"] == "gate-missing_info")
            next_step = next(item for item in summary_payload["facts"]["next_steps"] if item["id"] == "next-run-stage")

            self.assertEqual(issue["evidence_refs"], [current_run_ref])
            self.assertEqual(next_step["evidence_refs"], [current_run_ref])

    def test_summary_route_render_matches_persisted_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 补 runtime 骨架", workspace_root=workspace, user_home=workspace / "home")

            result = run_runtime("~summary", workspace_root=workspace, user_home=workspace / "home")
            summary_payload = result.skill_result["summary"]
            summary_markdown = result.skill_result["summary_markdown"]
            summary_json_path = workspace / next(path for path in result.generated_files if path.endswith("summary.json"))
            summary_md_path = workspace / next(path for path in result.generated_files if path.endswith("summary.md"))

            persisted_json = json.loads(summary_json_path.read_text(encoding="utf-8"))
            persisted_markdown = summary_md_path.read_text(encoding="utf-8")
            rendered = render_runtime_output(
                result,
                brand="demo-ai",
                language="zh-CN",
                title_color="none",
                use_color=False,
            )

            self.assertEqual(persisted_json, summary_payload)
            self.assertEqual(persisted_markdown, summary_markdown)
            self.assertIn(summary_markdown.rstrip(), rendered)
            self.assertIn(summary_payload["facts"]["headline"], persisted_markdown)
            self.assertIn(summary_payload["facts"]["headline"], rendered)

    def test_run_plan_loop_auto_resolves_decision_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            orchestrated = run_plan_loop(
                "payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                input_reader=lambda _prompt: "1",
                output_writer=lambda _message: None,
                interactive_session_factory=lambda: None,
            )

            self.assertEqual(orchestrated.exit_code, 0)
            self.assertEqual(orchestrated.runtime_result.route.route_name, "plan_only")
            self.assertIsNotNone(orchestrated.runtime_result.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_run_plan_loop_auto_resolves_clarification_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            answers = iter(("runtime/router.py", "补结构化 clarification bridge。", "."))

            orchestrated = run_plan_loop(
                "优化一下",
                workspace_root=workspace,
                input_reader=lambda _prompt: next(answers),
                output_writer=lambda _message: None,
                interactive_session_factory=lambda: None,
            )

            self.assertEqual(orchestrated.exit_code, 0)
            self.assertEqual(orchestrated.runtime_result.route.route_name, "plan_only")
            self.assertIsNotNone(orchestrated.runtime_result.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())

    def test_run_plan_loop_fail_closes_repeated_checkpoint_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            checkpoint_result = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(checkpoint_result.handoff.required_host_action, "confirm_decision")

            with mock.patch("runtime.plan_orchestrator.run_runtime", return_value=checkpoint_result), mock.patch(
                "runtime.plan_orchestrator._consume_planning_handoff",
                return_value=None,
            ):
                orchestrated = run_plan_loop(
                    "payload 放 host root 还是 workspace/.sopify-runtime",
                    workspace_root=workspace,
                    input_reader=lambda _prompt: "1",
                    output_writer=lambda _message: None,
                    interactive_session_factory=lambda: None,
                )

            self.assertEqual(orchestrated.exit_code, PLAN_ORCHESTRATOR_PENDING_EXIT)
            self.assertEqual(orchestrated.stopped_reason, "repeated_checkpoint")
            self.assertEqual(orchestrated.loop_count, 3)

    def test_run_plan_loop_fail_closes_when_bridge_cannot_complete_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            checkpoint_result = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            with mock.patch("runtime.plan_orchestrator.run_runtime", return_value=checkpoint_result), mock.patch(
                "runtime.plan_orchestrator._consume_planning_handoff",
                side_effect=PlanOrchestratorError("bridge missing submit/resume"),
            ):
                orchestrated = run_plan_loop(
                    "payload 放 host root 还是 workspace/.sopify-runtime",
                    workspace_root=workspace,
                    input_reader=lambda _prompt: "1",
                    output_writer=lambda _message: None,
                    interactive_session_factory=lambda: None,
                )

            self.assertEqual(orchestrated.exit_code, PLAN_ORCHESTRATOR_CANCELLED_EXIT)
            self.assertEqual(orchestrated.stopped_reason, "bridge_cancelled")
            self.assertEqual(orchestrated.runtime_result.handoff.required_host_action, "confirm_decision")

    def test_run_plan_loop_stops_with_max_loops_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            checkpoint_result = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            counter = iter(range(1, 10))

            with mock.patch("runtime.plan_orchestrator.run_runtime", return_value=checkpoint_result), mock.patch(
                "runtime.plan_orchestrator._consume_planning_handoff",
                return_value=None,
            ), mock.patch(
                "runtime.plan_orchestrator._handoff_signature",
                side_effect=lambda _handoff: f"sig-{next(counter)}",
            ):
                orchestrated = run_plan_loop(
                    "payload 放 host root 还是 workspace/.sopify-runtime",
                    workspace_root=workspace,
                    max_loops=2,
                    input_reader=lambda _prompt: "1",
                    output_writer=lambda _message: None,
                    interactive_session_factory=lambda: None,
                )

            self.assertEqual(orchestrated.exit_code, PLAN_ORCHESTRATOR_PENDING_EXIT)
            self.assertEqual(orchestrated.stopped_reason, "max_loops_exceeded")
            self.assertEqual(orchestrated.loop_count, 2)

    def test_go_plan_helper_fail_closes_pending_decision_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            script_path = REPO_ROOT / "scripts" / "go_plan_runtime.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "payload",
                    "放",
                    "host",
                    "root",
                    "还是",
                    "workspace/.sopify-runtime",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, PLAN_ORCHESTRATOR_PENDING_EXIT, msg=completed.stderr)
            self.assertIn("方案设计 ?", completed.stdout)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_go_plan_helper_debug_bypass_keeps_single_pass_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            script_path = REPO_ROOT / "scripts" / "go_plan_runtime.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--workspace-root",
                    str(workspace),
                    "--no-bridge-loop",
                    "--no-color",
                    "优化一下",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("需求分析 ?", completed.stdout)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())

    def test_synced_runtime_bundle_runs_in_another_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target_root = temp_root / "target"
            workspace = temp_root / "workspace"
            target_root.mkdir()
            workspace.mkdir()
            git_init = subprocess.run(
                ["git", "init", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(git_init.returncode, 0, msg=git_init.stderr)

            sync_script = REPO_ROOT / "scripts" / "sync-runtime-assets.sh"
            sync_completed = subprocess.run(
                ["bash", str(sync_script), str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sync_completed.returncode, 0, msg=sync_completed.stderr)

            bundle_root = target_root / ".sopify-runtime"
            manifest_path = bundle_root / "manifest.json"
            self.assertTrue((bundle_root / "runtime" / "__init__.py").exists())
            self.assertTrue((bundle_root / "runtime" / "clarification_bridge.py").exists())
            self.assertTrue((bundle_root / "runtime" / "cli_interactive.py").exists())
            self.assertTrue((bundle_root / "runtime" / "develop_checkpoint.py").exists())
            self.assertTrue((bundle_root / "runtime" / "execution_confirm.py").exists())
            self.assertTrue((bundle_root / "runtime" / "decision_bridge.py").exists())
            self.assertTrue((bundle_root / "runtime" / "gate.py").exists())
            self.assertTrue((bundle_root / "runtime" / "workspace_preflight.py").exists())
            self.assertTrue((bundle_root / "scripts" / "check-runtime-smoke.sh").exists())
            self.assertTrue((bundle_root / "scripts" / "clarification_bridge_runtime.py").exists())
            self.assertTrue((bundle_root / "scripts" / "develop_checkpoint_runtime.py").exists())
            self.assertTrue((bundle_root / "scripts" / "decision_bridge_runtime.py").exists())
            self.assertTrue((bundle_root / "scripts" / "plan_registry_runtime.py").exists())
            self.assertTrue((bundle_root / "scripts" / "preferences_preload_runtime.py").exists())
            self.assertTrue((bundle_root / "scripts" / "runtime_gate.py").exists())
            self.assertTrue((bundle_root / "tests" / "test_runtime.py").exists())
            self.assertTrue(manifest_path.exists())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "1")
            self.assertEqual(manifest["kb_layout_version"], "2")
            self.assertEqual(
                manifest["knowledge_paths"],
                {
                    "project": ".sopify-skills/project.md",
                    "blueprint_index": ".sopify-skills/blueprint/README.md",
                    "blueprint_background": ".sopify-skills/blueprint/background.md",
                    "blueprint_design": ".sopify-skills/blueprint/design.md",
                    "blueprint_tasks": ".sopify-skills/blueprint/tasks.md",
                    "plan_root": ".sopify-skills/plan",
                    "history_root": ".sopify-skills/history",
                },
            )
            self.assertEqual(
                manifest["context_profiles"]["consult"],
                ["project", "blueprint_index"],
            )
            self.assertEqual(
                manifest["context_profiles"]["plan"],
                ["project", "blueprint_index", "blueprint_background", "blueprint_design"],
            )
            self.assertEqual(
                manifest["context_profiles"]["clarification"],
                ["project", "blueprint_index", "blueprint_tasks"],
            )
            self.assertEqual(
                manifest["context_profiles"]["decision"],
                ["project", "blueprint_design", "active_plan"],
            )
            self.assertEqual(
                manifest["context_profiles"]["develop"],
                ["active_plan", "project", "blueprint_design"],
            )
            self.assertEqual(
                manifest["context_profiles"]["finalize"],
                [
                    "active_plan",
                    "project",
                    "blueprint_index",
                    "blueprint_background",
                    "blueprint_design",
                    "blueprint_tasks",
                ],
            )
            self.assertEqual(manifest["context_profiles"]["history_lookup"], ["history_root"])
            self.assertNotIn("history_root", manifest["context_profiles"]["plan"])
            self.assertNotIn("history_root", manifest["context_profiles"]["develop"])
            self.assertEqual(manifest["default_entry"], "scripts/sopify_runtime.py")
            self.assertEqual(manifest["plan_only_entry"], "scripts/go_plan_runtime.py")
            self.assertEqual(manifest["handoff_file"], ".sopify-skills/state/current_handoff.json")
            self.assertEqual(manifest["dependency_model"]["mode"], "stdlib_only")
            self.assertEqual(manifest["dependency_model"]["runtime_dependencies"], [])
            self.assertEqual(manifest["capabilities"]["bundle_role"], "control_plane")
            self.assertTrue(manifest["capabilities"]["writes_handoff_file"])
            self.assertTrue(manifest["capabilities"]["clarification_checkpoint"])
            self.assertTrue(manifest["capabilities"]["clarification_bridge"])
            self.assertTrue(manifest["capabilities"]["writes_clarification_file"])
            self.assertTrue(manifest["capabilities"]["decision_checkpoint"])
            self.assertTrue(manifest["capabilities"]["decision_bridge"])
            self.assertTrue(manifest["capabilities"]["develop_checkpoint_callback"])
            self.assertTrue(manifest["capabilities"]["develop_quality_feedback"])
            self.assertTrue(manifest["capabilities"]["develop_resume_context"])
            self.assertTrue(manifest["capabilities"]["execution_gate"])
            self.assertTrue(manifest["capabilities"]["plan_registry"])
            self.assertTrue(manifest["capabilities"]["plan_registry_priority_confirm"])
            self.assertTrue(manifest["capabilities"]["planning_mode_orchestrator"])
            self.assertTrue(manifest["capabilities"]["preferences_preload"])
            self.assertTrue(manifest["capabilities"]["runtime_gate"])
            self.assertTrue(manifest["capabilities"]["runtime_entry_guard"])
            self.assertTrue(manifest["capabilities"]["session_scoped_review_state"])
            self.assertTrue(manifest["capabilities"]["soft_execution_ownership"])
            self.assertTrue(manifest["capabilities"]["writes_decision_file"])
            self.assertEqual(manifest["runtime_first_hints"]["force_route_name"], "workflow")
            self.assertEqual(
                manifest["runtime_first_hints"]["entry_guard_reason_code"],
                "direct_edit_blocked_runtime_required",
            )
            self.assertEqual(manifest["runtime_first_hints"]["required_entry"], "scripts/runtime_gate.py")
            self.assertEqual(manifest["runtime_first_hints"]["required_subcommand"], "enter")
            self.assertEqual(manifest["runtime_first_hints"]["direct_entry_block_error_code"], "runtime_gate_required")
            self.assertEqual(manifest["runtime_first_hints"]["debug_bypass_flag"], "--allow-direct-entry")
            self.assertIn(".sopify-skills/plan/", manifest["runtime_first_hints"]["protected_path_prefixes"])
            self.assertIn("蓝图", manifest["runtime_first_hints"]["process_semantic_keywords"])
            self.assertIn("contract", manifest["runtime_first_hints"]["tradeoff_keywords"])
            self.assertIn("runtime", manifest["runtime_first_hints"]["long_term_contract_keywords"])
            self.assertIn("plan_only", manifest["limits"]["host_required_routes"])
            self.assertIn("clarification_pending", manifest["limits"]["host_required_routes"])
            self.assertIn("clarification_resume", manifest["limits"]["host_required_routes"])
            self.assertIn("execution_confirm_pending", manifest["limits"]["host_required_routes"])
            self.assertIn("decision_pending", manifest["limits"]["host_required_routes"])
            self.assertTrue(manifest["limits"]["entry_guard"]["strict_runtime_entry"])
            self.assertEqual(manifest["limits"]["entry_guard"]["default_runtime_entry"], "scripts/sopify_runtime.py")
            self.assertIn("confirm_execute", manifest["limits"]["entry_guard"]["pending_checkpoint_actions"])
            self.assertIn("~go exec", manifest["limits"]["entry_guard"]["bypass_blocked_commands"])
            self.assertEqual(manifest["limits"]["session_state"]["review_scope"], "session")
            self.assertEqual(manifest["limits"]["session_state"]["execution_scope"], "global")
            self.assertEqual(manifest["limits"]["session_state"]["source"], "host_supplied_or_runtime_gate_generated")
            self.assertEqual(manifest["limits"]["session_state"]["followup_session_id"], "required_for_review_followups")
            self.assertEqual(manifest["limits"]["session_state"]["cleanup_days"], 7)
            self.assertIn("finalize_active", manifest["supported_routes"])
            self.assertIn("compare", manifest["supported_routes"])
            self.assertIn("exec_plan", manifest["limits"]["host_required_routes"])
            self.assertEqual(manifest["limits"]["clarification_file"], ".sopify-skills/state/current_clarification.json")
            self.assertEqual(manifest["limits"]["clarification_bridge_entry"], "scripts/clarification_bridge_runtime.py")
            self.assertEqual(manifest["limits"]["clarification_bridge_hosts"]["cli"]["preferred_mode"], "interactive_form")
            self.assertEqual(manifest["limits"]["decision_file"], ".sopify-skills/state/current_decision.json")
            self.assertEqual(manifest["limits"]["decision_bridge_entry"], "scripts/decision_bridge_runtime.py")
            self.assertEqual(manifest["limits"]["decision_bridge_hosts"]["cli"]["preferred_mode"], "interactive_form")
            self.assertEqual(manifest["limits"]["decision_bridge_hosts"]["cli"]["select"], "interactive_select")
            self.assertEqual(manifest["limits"]["develop_checkpoint_entry"], "scripts/develop_checkpoint_runtime.py")
            self.assertEqual(manifest["limits"]["develop_checkpoint_hosts"]["cli"]["preferred_mode"], "structured_callback")
            self.assertEqual(manifest["limits"]["develop_checkpoint_hosts"]["cli"]["submit_quality"], "json_payload")
            self.assertIn("working_summary", manifest["limits"]["develop_resume_context_required_fields"])
            self.assertIn("continue_host_develop", manifest["limits"]["develop_resume_after_actions"])
            self.assertEqual(manifest["limits"]["develop_quality_contract_version"], "1")
            self.assertEqual(manifest["limits"]["plan_registry_entry"], "scripts/plan_registry_runtime.py")
            self.assertEqual(manifest["limits"]["plan_registry_hosts"]["cli"]["preferred_mode"], "inspect_only_summary")
            self.assertEqual(
                manifest["limits"]["plan_registry_hosts"]["cli"]["trigger_points"],
                ["post_plan_review", "manual_plan_registry_review"],
            )
            self.assertEqual(manifest["limits"]["plan_registry_hosts"]["cli"]["mount_scope"], "review_only")
            self.assertEqual(manifest["limits"]["plan_registry_hosts"]["cli"]["blocked_scopes"], ["develop", "execute"])
            self.assertEqual(manifest["limits"]["plan_registry_hosts"]["cli"]["default_surface"], "inspect_contract")
            self.assertEqual(manifest["limits"]["plan_registry_hosts"]["cli"]["confirm_priority_trigger"], "explicit_user_action")
            self.assertEqual(
                manifest["limits"]["plan_registry_hosts"]["cli"]["display_fields"],
                ["current_plan", "selected_plan", "recommendations", "drift_notice", "execution_truth"],
            )
            self.assertEqual(
                manifest["limits"]["plan_registry_hosts"]["cli"]["allowed_actions"],
                ["confirm_suggested", "set_p1", "set_p2", "set_p3", "dismiss"],
            )
            self.assertTrue(manifest["limits"]["plan_registry_hosts"]["cli"]["note_optional"])
            self.assertEqual(
                manifest["limits"]["plan_registry_hosts"]["cli"]["confirm_payload_fields"],
                ["plan_id", "priority", "note"],
            )
            self.assertEqual(
                manifest["limits"]["plan_registry_hosts"]["cli"]["success_behavior"],
                {
                    "refresh_scope": "selected_card",
                    "stay_in_context": "review",
                    "auto_execute": False,
                    "auto_switch_current_plan": False,
                },
            )
            self.assertEqual(
                manifest["limits"]["plan_registry_hosts"]["cli"]["failure_behavior"],
                {
                    "inspect_failure": "hide_card_non_blocking",
                    "confirm_failure": "show_retryable_error",
                },
            )
            self.assertEqual(
                manifest["limits"]["plan_registry_hosts"]["cli"]["copy"],
                {
                    "title": "Plan 优先级建议",
                    "summary": "当前 active plan、当前评审 plan 与建议优先级",
                    "boundary_notice": "确认优先级只会更新 registry，不会切换 current_plan",
                    "success_notice": "已记录到 plan registry",
                    "pending_notice": "已保留系统建议，暂未写入最终优先级",
                },
            )
            self.assertEqual(manifest["limits"]["plan_registry_hosts"]["cli"]["raw_registry_visibility"], "advanced_only")
            self.assertTrue(manifest["limits"]["plan_registry_hosts"]["cli"]["observe_only"])
            self.assertEqual(manifest["limits"]["plan_registry_hosts"]["cli"]["execution_truth"], "current_plan")
            self.assertEqual(manifest["limits"]["preferences_preload_entry"], "scripts/preferences_preload_runtime.py")
            self.assertEqual(manifest["limits"]["preferences_preload_contract_version"], "1")
            self.assertEqual(
                manifest["limits"]["preferences_preload_statuses"],
                ["loaded", "missing", "invalid", "read_error"],
            )
            self.assertEqual(manifest["limits"]["runtime_gate_entry"], "scripts/runtime_gate.py")
            self.assertEqual(manifest["limits"]["runtime_gate_contract_version"], "1")
            self.assertEqual(
                manifest["limits"]["runtime_gate_allowed_response_modes"],
                ["normal_runtime_followup", "checkpoint_only", "error_visible_retry"],
            )
            self.assertIn("model-compare", manifest["limits"]["runtime_payload_required_skill_ids"])
            self.assertEqual(len(manifest["builtin_skills"]), 7)
            model_compare = next(skill for skill in manifest["builtin_skills"] if skill["skill_id"] == "model-compare")
            self.assertEqual(model_compare["runtime_entry"], "scripts/model_compare_runtime.py")
            self.assertEqual(model_compare["entry_kind"], "python")
            self.assertEqual(model_compare["supports_routes"], ["compare"])
            self.assertEqual(model_compare["permission_mode"], "dual")
            self.assertTrue(model_compare["requires_network"])
            self.assertIn("codex", model_compare["host_support"])
            self.assertIn("network", model_compare["tools"])

            runtime_script = bundle_root / "scripts" / "sopify_runtime.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "重构数据库层",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)

            preferences_script = bundle_root / "scripts" / "preferences_preload_runtime.py"
            preferences_workspace = temp_root / "preferences-workspace"
            preferences_workspace.mkdir()
            preference_file = preferences_workspace / ".sopify-skills" / "user" / "preferences.md"
            preference_file.parent.mkdir(parents=True, exist_ok=True)
            preference_file.write_text("# 用户长期偏好\n\n- 严谨输出。\n", encoding="utf-8")
            preloaded = subprocess.run(
                [sys.executable, str(preferences_script), "--workspace-root", str(preferences_workspace), "inspect"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(preloaded.returncode, 0, msg=preloaded.stderr)
            preload_payload = json.loads(preloaded.stdout)
            self.assertEqual(preload_payload["status"], "ready")
            self.assertEqual(preload_payload["preferences"]["status"], "loaded")
            self.assertIn("严谨输出。", preload_payload["preferences"]["injection_text"])

            runtime_gate_script = bundle_root / "scripts" / "runtime_gate.py"
            gated = subprocess.run(
                [
                    sys.executable,
                    str(runtime_gate_script),
                    "enter",
                    "--workspace-root",
                    str(workspace),
                    "--request",
                    "~go plan 重构数据库层",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(gated.returncode, 0, msg=gated.stderr)
            gate_payload = json.loads(gated.stdout)
            self.assertEqual(gate_payload["status"], "ready")
            self.assertTrue(gate_payload["gate_passed"])
            self.assertEqual(gate_payload["allowed_response_mode"], "normal_runtime_followup")
            self.assertEqual(gate_payload["handoff"]["required_host_action"], "review_or_execute_plan")
            self.assertIn(".sopify-skills/plan/", completed.stdout)
            self.assertTrue((workspace / gate_payload["state"]["current_handoff_path"]).exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_gate_receipt.json").exists())
            self.assertTrue((workspace / gate_payload["state"]["current_plan_path"]).exists())
            self.assertTrue((workspace / ".sopify-skills" / "replay" / "sessions").exists())
            self.assertTrue((workspace / ".sopify-skills" / "project.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "README.md").exists())
            self.assertFalse((workspace / ".sopify-skills" / "history" / "index.md").exists())
            bundle_blueprint_readme = (workspace / ".sopify-skills" / "blueprint" / "README.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("状态: L1 blueprint-ready", bundle_blueprint_readme)
            self.assertIn("当前活动 plan：暂无", bundle_blueprint_readme)
            self.assertNotIn("../history/index.md", bundle_blueprint_readme)

    def test_synced_runtime_bundle_supports_decision_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target_root = temp_root / "target"
            workspace = temp_root / "workspace"
            target_root.mkdir()
            workspace.mkdir()

            sync_script = REPO_ROOT / "scripts" / "sync-runtime-assets.sh"
            sync_completed = subprocess.run(
                ["bash", str(sync_script), str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sync_completed.returncode, 0, msg=sync_completed.stderr)

            runtime_script = target_root / ".sopify-runtime" / "scripts" / "sopify_runtime.py"
            bridge_script = target_root / ".sopify-runtime" / "scripts" / "decision_bridge_runtime.py"
            pending = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "~go",
                    "plan",
                    "payload",
                    "放",
                    "host",
                    "root",
                    "还是",
                    "workspace/.sopify-runtime",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(pending.returncode, 0, msg=pending.stderr)
            self.assertIn("方案设计 ?", pending.stdout)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

            inspected = subprocess.run(
                [
                    sys.executable,
                    str(bridge_script),
                    "--workspace-root",
                    str(workspace),
                    "inspect",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(inspected.returncode, 0, msg=inspected.stderr)
            inspect_payload = json.loads(inspected.stdout)
            self.assertEqual(inspect_payload["bridge"]["host_kind"], "cli")
            self.assertEqual(inspect_payload["bridge"]["steps"][0]["renderer"], "cli.select")

            confirmed = subprocess.run(
                [
                    sys.executable,
                    str(bridge_script),
                    "--workspace-root",
                    str(workspace),
                    "submit",
                    "--answers-json",
                    '{"selected_option_id":"option_1"}',
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(confirmed.returncode, 0, msg=confirmed.stderr)
            confirmed_payload = json.loads(confirmed.stdout)
            self.assertEqual(confirmed_payload["status"], "written")

            resumed = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "继续",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(resumed.returncode, 0, msg=resumed.stderr)
            self.assertIn(".sopify-skills/plan/", resumed.stdout)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())

    def test_synced_runtime_bundle_supports_develop_checkpoint_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target_root = temp_root / "target"
            workspace = temp_root / "workspace"
            target_root.mkdir()
            workspace.mkdir()

            sync_script = REPO_ROOT / "scripts" / "sync-runtime-assets.sh"
            sync_completed = subprocess.run(
                ["bash", str(sync_script), str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sync_completed.returncode, 0, msg=sync_completed.stderr)

            runtime_script = target_root / ".sopify-runtime" / "scripts" / "sopify_runtime.py"
            helper_script = target_root / ".sopify-runtime" / "scripts" / "develop_checkpoint_runtime.py"

            _prepare_ready_plan_state(workspace)
            exec_pending = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "~go",
                    "exec",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(exec_pending.returncode, 0, msg=exec_pending.stderr)
            started = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "开始",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(started.returncode, 0, msg=started.stderr)
            self.assertIn("continue_host_develop", (workspace / ".sopify-skills" / "state" / "current_handoff.json").read_text(encoding="utf-8"))

            inspected = subprocess.run(
                [sys.executable, str(helper_script), "--workspace-root", str(workspace), "inspect"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(inspected.returncode, 0, msg=inspected.stderr)
            inspect_payload = json.loads(inspected.stdout)
            self.assertEqual(inspect_payload["status"], "ready")
            self.assertEqual(inspect_payload["required_host_action"], "continue_host_develop")
            self.assertEqual(inspect_payload["quality_contract"]["max_retry_count"], 1)

            quality_submitted = subprocess.run(
                [
                    sys.executable,
                    str(helper_script),
                    "--workspace-root",
                    str(workspace),
                    "submit-quality",
                    "--payload-json",
                    json.dumps(
                        {
                            "schema_version": "1",
                            "task_refs": ["5.1"],
                            "changed_files": ["runtime/develop_checkpoint.py"],
                            "working_summary": "已记录 develop 质量结果。",
                            "verification_todo": ["补 bundle helper 测试"],
                            "quality_result": {
                                "schema_version": "1",
                                "verification_source": "project_native",
                                "command": "python -m unittest tests.test_runtime_engine -v",
                                "scope": "runtime/develop_checkpoint.py",
                                "result": "passed",
                                "retry_count": 0,
                                "review_result": {
                                    "spec_compliance": {"status": "passed", "summary": "满足当前任务范围"},
                                    "code_quality": {"status": "passed", "summary": "修改面合理"},
                                },
                            },
                        }
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(quality_submitted.returncode, 0, msg=quality_submitted.stderr)
            quality_payload = json.loads(quality_submitted.stdout)
            self.assertEqual(quality_payload["result"], "passed")
            self.assertEqual(quality_payload["required_host_action"], "continue_host_develop")

            submitted = subprocess.run(
                [
                    sys.executable,
                    str(helper_script),
                    "--workspace-root",
                    str(workspace),
                    "submit",
                    "--payload-json",
                    json.dumps(
                        {
                            "schema_version": "1",
                            "checkpoint_kind": "decision",
                            "question": "认证边界是否移动到 adapter 层？",
                            "summary": "开发中已经形成两条可执行路径，需要用户拍板。",
                            "options": [
                                {"id": "option_1", "title": "保持现状", "summary": "边界继续留在当前层", "recommended": True},
                                {"id": "option_2", "title": "移动边界", "summary": "把认证边界下推到 adapter 层"},
                            ],
                            "resume_context": {
                                "active_run_stage": "executing",
                                "current_plan_path": ".sopify-skills/plan/20260319_feature",
                                "task_refs": ["5.1"],
                                "changed_files": ["runtime/develop_checkpoint.py"],
                                "working_summary": "需要确认认证边界。",
                                "verification_todo": ["补 bundle helper 测试"],
                                "resume_after": "continue_host_develop",
                            },
                        }
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(submitted.returncode, 0, msg=submitted.stderr)
            submit_payload = json.loads(submitted.stdout)
            self.assertEqual(submit_payload["status"], "written")
            self.assertEqual(submit_payload["required_host_action"], "confirm_decision")
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_synced_runtime_bundle_supports_cli_decision_bridge_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target_root = temp_root / "target"
            workspace = temp_root / "workspace"
            target_root.mkdir()
            workspace.mkdir()

            sync_script = REPO_ROOT / "scripts" / "sync-runtime-assets.sh"
            sync_completed = subprocess.run(
                ["bash", str(sync_script), str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sync_completed.returncode, 0, msg=sync_completed.stderr)

            runtime_script = target_root / ".sopify-runtime" / "scripts" / "sopify_runtime.py"
            bridge_script = target_root / ".sopify-runtime" / "scripts" / "decision_bridge_runtime.py"
            pending = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "~go",
                    "plan",
                    "payload",
                    "放",
                    "host",
                    "root",
                    "还是",
                    "workspace/.sopify-runtime",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(pending.returncode, 0, msg=pending.stderr)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

            prompted = subprocess.run(
                [
                    sys.executable,
                    str(bridge_script),
                    "--workspace-root",
                    str(workspace),
                    "prompt",
                    "--renderer",
                    "text",
                ],
                input="1\n",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(prompted.returncode, 0, msg=prompted.stderr)
            prompted_payload = json.loads(prompted.stdout)
            self.assertEqual(prompted_payload["status"], "written")
            self.assertEqual(prompted_payload["used_renderer"], "text")
            self.assertEqual(prompted_payload["submission"]["answers"]["selected_option_id"], "option_1")

            resumed = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "继续",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(resumed.returncode, 0, msg=resumed.stderr)
            self.assertIn(".sopify-skills/plan/", resumed.stdout)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_synced_runtime_bundle_supports_clarification_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target_root = temp_root / "target"
            workspace = temp_root / "workspace"
            target_root.mkdir()
            workspace.mkdir()

            sync_script = REPO_ROOT / "scripts" / "sync-runtime-assets.sh"
            sync_completed = subprocess.run(
                ["bash", str(sync_script), str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sync_completed.returncode, 0, msg=sync_completed.stderr)

            runtime_script = target_root / ".sopify-runtime" / "scripts" / "sopify_runtime.py"
            pending = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "~go",
                    "plan",
                    "优化一下",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(pending.returncode, 0, msg=pending.stderr)
            self.assertIn("需求分析 ?", pending.stdout)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())

            answered = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    "目标是 runtime/router.py，预期结果是补 clarification_pending 状态骨架",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(answered.returncode, 0, msg=answered.stderr)
            self.assertIn(".sopify-skills/plan/", answered.stdout)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())

    def test_repo_local_runtime_entry_blocks_runtime_first_requests_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            runtime_script = REPO_ROOT / "scripts" / "sopify_runtime.py"
            request = "分析下 .sopify-skills/plan/20260320_kb_layout_v2/tasks.md 的当前任务，并整理 README 职责表边界"

            blocked = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    request,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(blocked.returncode, 2, msg=blocked.stderr)
            self.assertIn("scripts/runtime_gate.py enter", blocked.stdout)
            self.assertIn("direct_edit_blocked_runtime_required", blocked.stdout)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())
            receipt_payload = json.loads((workspace / ".sopify-skills" / "state" / "current_gate_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt_payload["error_code"], "runtime_gate_required")
            self.assertEqual(receipt_payload["required_entry"], "scripts/runtime_gate.py")
            self.assertEqual(receipt_payload["required_subcommand"], "enter")
            self.assertEqual(receipt_payload["observability"]["ingress_mode"], "default_runtime_entry_blocked")
            self.assertEqual(receipt_payload["trigger_evidence"]["direct_edit_guard_kind"], "protected_plan_asset")

            allowed = subprocess.run(
                [
                    sys.executable,
                    str(runtime_script),
                    "--allow-direct-entry",
                    "--workspace-root",
                    str(workspace),
                    "--no-color",
                    request,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(allowed.returncode, 0, msg=allowed.stderr)
            self.assertIn(".sopify-skills/plan/", allowed.stdout)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())
