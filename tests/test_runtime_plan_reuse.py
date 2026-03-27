from __future__ import annotations

from tests.runtime_test_support import *


class PlanReuseRuntimeTests(unittest.TestCase):
    def test_planning_reuses_active_plan_under_single_active_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                "~go plan 把 promotion gate 写进 plan",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertIsNotNone(result.plan_artifact)
            assert result.plan_artifact is not None
            self.assertEqual(result.plan_artifact.plan_id, current_plan.plan_id)
            self.assertTrue(any("implicit current-plan anchor" in note for note in result.notes))
            self.assertEqual(_plan_dir_count(workspace), 1)

    def test_explicit_plan_reference_rebinds_current_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            target_plan = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                f"~go plan 切到 {target_plan.plan_id} 继续评审",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertIsNotNone(result.plan_artifact)
            assert result.plan_artifact is not None
            self.assertEqual(result.plan_artifact.plan_id, target_plan.plan_id)
            rebound = StateStore(load_runtime_config(workspace)).get_current_plan()
            self.assertIsNotNone(rebound)
            assert rebound is not None
            self.assertEqual(rebound.plan_id, target_plan.plan_id)

    def test_no_active_plan_does_not_auto_reuse_topic_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            create_plan_scaffold("补 runtime 骨架", config=config, level="standard")
            store = StateStore(config)
            store.ensure()
            store.clear_current_plan()

            result = run_runtime(
                "~go plan 补 runtime 骨架",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertIsNotNone(result.plan_artifact)
            assert result.plan_artifact is not None
            self.assertEqual(result.plan_artifact.topic_key, "runtime")
            self.assertFalse(any("topic_key=runtime" in note for note in result.notes))
            self.assertEqual(_plan_dir_count(workspace), 2)

    def test_meta_review_request_does_not_create_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                "分析下这个方案的评分、风险和还有什么优化点",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "consult")
            self.assertIsNone(result.plan_artifact)
            self.assertEqual(_plan_dir_count(workspace), 1)
            rebound = StateStore(load_runtime_config(workspace)).get_current_plan()
            self.assertIsNotNone(rebound)
            assert rebound is not None
            self.assertEqual(rebound.plan_id, current_plan.plan_id)

    def test_meta_review_with_other_plan_phrase_does_not_create_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                "分析这个方案和其他 plan 的差异、风险和优化点",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "consult")
            self.assertIsNone(result.plan_artifact)
            self.assertEqual(_plan_dir_count(workspace), 1)
            rebound = StateStore(load_runtime_config(workspace)).get_current_plan()
            self.assertIsNotNone(rebound)
            assert rebound is not None
            self.assertEqual(rebound.plan_id, current_plan.plan_id)

    def test_clarification_answer_reuses_existing_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            first = run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")
            second = run_runtime(
                "目标是 runtime/router.py，预期结果是补结构化 clarification bridge。",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(first.route.route_name, "clarification_pending")
            self.assertIsNotNone(second.plan_artifact)
            assert second.plan_artifact is not None
            self.assertEqual(second.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(_plan_dir_count(workspace), 1)
            rebound = StateStore(load_runtime_config(workspace)).get_current_plan()
            self.assertIsNotNone(rebound)
            assert rebound is not None
            self.assertEqual(rebound.plan_id, current_plan.plan_id)

    def test_explicit_new_plan_creates_new_scaffold_even_with_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            first = run_runtime("~go plan 新建一个 plan 处理这个问题", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(first.route.route_name, "plan_only")
            self.assertIsNotNone(first.plan_artifact)
            assert first.plan_artifact is not None
            self.assertNotEqual(first.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(_plan_dir_count(workspace), 2)

    def test_negated_new_plan_phrase_reuses_active_plan_instead_of_creating_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                "~go plan 不要新建新的 plan 包，直接在当前 plan 上继续细化 tasks",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertIsNotNone(result.plan_artifact)
            assert result.plan_artifact is not None
            self.assertEqual(result.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(_plan_dir_count(workspace), 1)

    def test_explicit_plan_reference_wins_over_positive_new_plan_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            target_plan = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                f"~go plan 切到 {target_plan.plan_id} 继续评审，不要复用当前 plan，直接新建 plan",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertIsNotNone(result.plan_artifact)
            assert result.plan_artifact is not None
            self.assertEqual(result.plan_artifact.plan_id, target_plan.plan_id)
            self.assertEqual(_plan_dir_count(workspace), 2)

    def test_trailing_positive_new_plan_phrase_overrides_earlier_negated_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                "~go plan 不是不要新建 plan，而是要新建 plan",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "plan_only")
            self.assertIsNotNone(result.plan_artifact)
            assert result.plan_artifact is not None
            self.assertNotEqual(result.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(_plan_dir_count(workspace), 2)

    def test_decision_resume_reuses_existing_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold(
                "payload 放 host root 还是 workspace/.sopify-runtime",
                config=config,
                level="standard",
            )
            store.set_current_plan(current_plan)

            first = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            second = run_runtime(
                "1",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(first.route.route_name, "decision_pending")
            self.assertEqual(first.recovered_context.current_decision.decision_type, "architecture_choice")
            self.assertIsNotNone(second.plan_artifact)
            assert second.plan_artifact is not None
            self.assertEqual(second.plan_artifact.plan_id, current_plan.plan_id)

    def test_nonanchored_complex_request_with_active_plan_requires_binding_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            result = run_runtime(
                "~go plan 重做 runtime contract 并调整 blueprint/project 边界",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result.route.route_name, "decision_pending")
            self.assertIsNone(result.plan_artifact)
            self.assertEqual(result.recovered_context.current_decision.decision_type, "active_plan_binding_choice")
            self.assertEqual(
                {option.option_id for option in result.recovered_context.current_decision.options},
                {"attach_current_plan", "create_new_plan"},
            )
            self.assertEqual(result.handoff.required_host_action, "confirm_decision")

    def test_attach_current_plan_selection_reopens_current_plan_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            first = run_runtime(
                "~go plan 重做 runtime contract 并调整 blueprint/project 边界",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            second = run_runtime(
                "1",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(first.route.route_name, "decision_pending")
            self.assertEqual(second.route.route_name, "plan_only")
            self.assertIsNotNone(second.plan_artifact)
            assert second.plan_artifact is not None
            self.assertEqual(second.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(second.recovered_context.current_run.stage, "plan_generated")
            self.assertEqual(second.recovered_context.current_run.execution_gate.gate_status, "blocked")
            self.assertEqual(second.handoff.required_host_action, "review_or_execute_plan")

    def test_new_plan_selection_creates_new_scaffold_for_nonanchored_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            first = run_runtime(
                "~go plan 重做 runtime contract 并调整 blueprint/project 边界",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            second = run_runtime(
                "2",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(first.route.route_name, "decision_pending")
            self.assertEqual(second.route.route_name, "plan_only")
            self.assertIsNotNone(second.plan_artifact)
            assert second.plan_artifact is not None
            self.assertNotEqual(second.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(_plan_dir_count(workspace), 2)
            rebound = StateStore(load_runtime_config(workspace)).get_current_plan()
            self.assertIsNotNone(rebound)
            assert rebound is not None
            self.assertEqual(rebound.plan_id, second.plan_artifact.plan_id)

    def test_new_plan_selection_preserves_workflow_resume_route_after_binding_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            current_plan = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(current_plan)

            first = run_runtime(
                "~go 实现 runtime plugin bridge",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            second = run_runtime(
                "2",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            third = run_runtime(
                "继续",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(first.route.route_name, "decision_pending")
            self.assertEqual(second.route.route_name, "plan_proposal_pending")
            self.assertIsNone(second.plan_artifact)
            self.assertIsNotNone(second.recovered_context.current_plan_proposal)
            assert second.recovered_context.current_plan_proposal is not None
            self.assertEqual(second.recovered_context.current_plan_proposal.resume_route, "workflow")
            self.assertEqual(second.handoff.required_host_action, "confirm_plan_package")

            self.assertEqual(third.route.route_name, "plan_only")
            self.assertIsNotNone(third.plan_artifact)
            assert third.plan_artifact is not None
            self.assertNotEqual(third.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(third.handoff.required_host_action, "review_or_execute_plan")
