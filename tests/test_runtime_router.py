from __future__ import annotations

from tests.runtime_test_support import *


class RouterTests(unittest.TestCase):
    def test_route_classification_and_active_flow_intents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            plan_route = router.classify("~go plan 补 runtime 骨架", skills=skills)
            finalize_route = router.classify("~go finalize", skills=skills)
            self.assertEqual(plan_route.route_name, "plan_only")
            self.assertTrue(plan_route.should_create_plan)
            self.assertEqual(finalize_route.route_name, "finalize_active")
            self.assertTrue(finalize_route.should_recover_context)

            run_state = RunState(
                run_id="run-1",
                status="active",
                stage="plan_ready",
                route_name="workflow",
                title="Runtime",
                created_at=iso_now(),
                updated_at=iso_now(),
            )
            store.set_current_run(run_state)
            resume_route = router.classify("继续", skills=skills)
            cancel_route = router.classify("取消", skills=skills)
            replay_route = router.classify("回放最近一次实现", skills=skills)
            compare_route = router.classify("~compare 方案对比", skills=skills)
            summary_route = router.classify("~summary", skills=skills)
            consult_route = router.classify("这个方案为什么要这样拆？", skills=skills)

            self.assertEqual(resume_route.route_name, "resume_active")
            self.assertTrue(resume_route.should_recover_context)
            self.assertEqual(cancel_route.route_name, "cancel_active")
            self.assertEqual(replay_route.route_name, "replay")
            self.assertEqual(compare_route.route_name, "compare")
            self.assertEqual(summary_route.route_name, "summary")
            self.assertEqual(summary_route.capture_mode, "off")
            self.assertEqual(consult_route.route_name, "consult")

    def test_consult_guard_for_process_semantics_forces_runtime_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("design 阶段现在怎么收口？", skills=skills)

            self.assertEqual(route.route_name, "workflow")
            self.assertEqual(route.plan_package_policy, "confirm")
            self.assertFalse(route.should_create_plan)
            self.assertEqual(
                route.artifacts.get("entry_guard_reason_code"),
                DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
            )

    def test_negated_new_plan_phrase_does_not_force_immediate_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("~go 不要新建新的 plan 包，直接在当前 plan 上细化 tasks", skills=skills)

            self.assertEqual(route.route_name, "workflow")
            self.assertEqual(route.plan_package_policy, "confirm")
            self.assertFalse(route.should_create_plan)

    def test_plan_meta_review_for_protected_plan_assets_prefers_consult(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify(
                "你能解释下 .sopify-skills/plan/20260319_skill_standards_refactor/tasks.md 的当前状态吗？",
                skills=skills,
            )

            self.assertEqual(route.route_name, "consult")
            self.assertFalse(route.should_create_plan)
            self.assertIn("meta-review", route.reason)

    def test_consult_guard_falls_back_when_tradeoff_or_long_term_split_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("长期契约上是继续手写 catalog 还是改成生成链？", skills=skills)

            self.assertEqual(route.route_name, "workflow")
            self.assertIn("tradeoff or long-term contract split", route.reason)
            self.assertEqual(
                route.artifacts.get("entry_guard_reason_code"),
                DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
            )

    def test_active_plan_meta_review_bypasses_runtime_first_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            plan_artifact = create_plan_scaffold("第一性原理协作规则分层落地", config=config, level="standard")
            store.set_current_plan(plan_artifact)
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("分析下这个方案的评分、风险和还有什么需要我决策", skills=skills)

            self.assertEqual(route.route_name, "consult")
            self.assertTrue(route.should_recover_context)
            self.assertFalse(route.should_create_plan)

    def test_plan_materialization_meta_debug_does_not_hijack_normal_issue_fix_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("这是一个性能问题，需要优化数据库查询", skills=skills)

            self.assertEqual(route.route_name, "workflow")
            self.assertNotIn("meta-debug", route.reason)

    def test_explain_only_override_prefers_consult_before_runtime_first_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("解释 runtime gate 为什么这么判，不要改", skills=skills)

            self.assertEqual(route.route_name, "consult")
            self.assertEqual(route.artifacts.get("consult_mode"), "explain_only_override")
            self.assertEqual(route.artifacts.get("consult_override_reason_code"), "consult_explain_only_override")

    def test_explain_only_override_does_not_hijack_explicit_change_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("解释原因并修复 router 的这个误判", skills=skills)

            self.assertNotEqual(route.route_name, "consult")
            self.assertNotEqual(route.artifacts.get("consult_override_reason_code"), "consult_explain_only_override")

    def test_explain_only_override_does_not_override_explicit_workflow_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify("~go 解释 runtime gate 为什么这么判，不要改", skills=skills)

            self.assertEqual(route.route_name, "workflow")
            self.assertEqual(route.command, "~go")

    def test_pending_plan_proposal_blocks_compare_and_finalize_as_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")

            compare_route = router.classify("~compare 方案对比", skills=skills)
            finalize_route = router.classify("~go finalize", skills=skills)

            self.assertEqual(compare_route.route_name, "plan_proposal_pending")
            self.assertEqual(compare_route.command, "~compare")
            self.assertEqual(compare_route.active_run_action, "inspect_plan_proposal")
            self.assertIn("before compare can continue", compare_route.reason)
            self.assertEqual(finalize_route.route_name, "plan_proposal_pending")
            self.assertEqual(finalize_route.command, "~go finalize")
            self.assertEqual(finalize_route.active_run_action, "inspect_plan_proposal")
            self.assertIn("before finalize_active can continue", finalize_route.reason)

    def test_pending_plan_proposal_defaults_questions_to_inspect_and_explicit_edits_to_revise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")

            question_route = router.classify("为什么是这个方案？", skills=skills)
            revise_route = router.classify("把 level 改成 standard", skills=skills)

            self.assertEqual(question_route.route_name, "plan_proposal_pending")
            self.assertEqual(question_route.active_run_action, "inspect_plan_proposal")
            self.assertIn("waiting for package confirmation", question_route.reason)
            self.assertEqual(revise_route.route_name, "plan_proposal_pending")
            self.assertEqual(revise_route.active_run_action, "revise_plan_proposal")
            self.assertIn("feedback", revise_route.reason)

    def test_ready_plan_routes_continue_and_exec_into_execution_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, store, _ = _prepare_ready_plan_state(workspace)
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            continue_route = router.classify("继续", skills=skills)
            exec_route = router.classify("~go exec", skills=skills)
            revise_route = router.classify("先把风险部分再展开一点", skills=skills)

            self.assertEqual(continue_route.route_name, "execution_confirm_pending")
            self.assertEqual(continue_route.active_run_action, "confirm_execution")
            self.assertEqual(exec_route.route_name, "execution_confirm_pending")
            self.assertEqual(exec_route.active_run_action, "inspect_execution_confirm")
            self.assertEqual(revise_route.route_name, "execution_confirm_pending")
            self.assertEqual(revise_route.active_run_action, "revise_execution")

    def test_ready_plan_does_not_hijack_unrelated_requests_into_execution_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, store, _ = _prepare_ready_plan_state(workspace)
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            quick_fix_route = router.classify("修改 README 里的 helper 路径说明", skills=skills)
            consult_route = router.classify("解释一下 execution_confirm_pending 和 decision_pending 的区别", skills=skills)

            self.assertEqual(quick_fix_route.route_name, "quick_fix")
            self.assertIsNone(quick_fix_route.active_run_action)
            self.assertEqual(consult_route.route_name, "consult")
            self.assertIsNone(consult_route.active_run_action)

    def test_question_form_a4_prefers_analyze_challenge_consult(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config, store, _ = _prepare_ready_plan_state(workspace)
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            route = router.classify(
                "current_handoff.json 和 current_run.json 里都有 execution gate，是否应该收敛成一个唯一机器事实源？",
                skills=skills,
            )

            self.assertEqual(route.route_name, "consult")
            self.assertEqual(route.artifacts.get("consult_mode"), "analyze_challenge")
            self.assertEqual(route.artifacts.get("trigger_label"), "A4")
            self.assertIn("analyze", route.candidate_skill_ids)
            self.assertTrue(route.should_recover_context)

    def test_pending_clarification_intercepts_exec_and_accepts_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")

            blocked_exec = router.classify("~go exec", skills=skills)
            answer = router.classify("目标是 runtime/router.py，预期结果是补状态骨架", skills=skills)

            self.assertEqual(blocked_exec.route_name, "clarification_pending")
            self.assertEqual(answer.route_name, "clarification_resume")

    def test_pending_clarification_submission_routes_to_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")

            store = StateStore(load_runtime_config(workspace))
            store.set_current_clarification_response(
                response_text="目标范围：runtime/router.py\n预期结果：补结构化 clarification bridge。",
                response_fields={
                    "target_scope": "runtime/router.py",
                    "expected_outcome": "补结构化 clarification bridge。",
                },
                response_source="cli",
                response_message="host form submitted",
            )

            resumed = router.classify("继续", skills=skills)

            self.assertEqual(resumed.route_name, "clarification_resume")
            self.assertEqual(resumed.active_run_action, "clarification_response_from_state")

    def test_pending_decision_intercepts_exec_until_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            blocked_exec = router.classify("~go exec", skills=skills)
            self.assertEqual(blocked_exec.route_name, "decision_pending")
            self.assertEqual(blocked_exec.active_run_action, "inspect_decision")

    def test_pending_decision_submission_routes_to_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()

            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            store.set_current_decision_submission(
                DecisionSubmission(
                    status="submitted",
                    source="cli",
                    answers={"selected_option_id": "option_1"},
                    submitted_at=iso_now(),
                    resume_action="submit",
                )
            )

            resumed = router.classify("继续", skills=skills)

            self.assertEqual(resumed.route_name, "decision_resume")
            self.assertEqual(resumed.active_run_action, "resume_submitted_decision")

    def test_route_skill_resolution_prefers_declarative_supports_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_home = workspace / "home"
            custom_skill = workspace / "skills" / "decision-helper"
            custom_skill.mkdir(parents=True)
            (custom_skill / "SKILL.md").write_text(
                "---\nname: decision-helper\ndescription: custom pending decision helper\n---\n\n# decision-helper\n",
                encoding="utf-8",
            )
            (custom_skill / "skill.yaml").write_text(
                "id: decision-helper\n"
                "mode: advisory\n"
                "supports_routes:\n"
                "  - decision_pending\n"
                "  - decision_resume\n"
                "metadata:\n"
                "  priority: 1\n",
                encoding="utf-8",
            )

            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=user_home,
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=user_home).discover()

            blocked_exec = router.classify("~go exec", skills=skills)

            self.assertEqual(blocked_exec.route_name, "decision_pending")
            self.assertEqual(blocked_exec.candidate_skill_ids, ("decision-helper",))

    def test_route_skill_resolution_falls_back_when_supports_routes_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_home = workspace / "home"
            custom_skill = workspace / "skills" / "decision-helper"
            custom_skill.mkdir(parents=True)
            (custom_skill / "SKILL.md").write_text(
                "---\nname: decision-helper\ndescription: custom helper without route metadata\n---\n\n# decision-helper\n",
                encoding="utf-8",
            )
            (custom_skill / "skill.yaml").write_text(
                "id: decision-helper\n"
                "mode: advisory\n",
                encoding="utf-8",
            )

            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=user_home,
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=user_home).discover()

            blocked_exec = router.classify("~go exec", skills=skills)

            self.assertEqual(blocked_exec.route_name, "decision_pending")
            self.assertEqual(blocked_exec.candidate_skill_ids, ("design",))

    def test_route_skill_resolution_prefers_workspace_declarative_workflow_over_builtin_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_home = workspace / "home"
            custom_skill = workspace / ".agents" / "skills" / "custom-workflow"
            custom_skill.mkdir(parents=True)
            (custom_skill / "SKILL.md").write_text(
                "---\nname: custom-workflow\ndescription: custom workflow helper\n---\n\n# custom-workflow\n",
                encoding="utf-8",
            )
            (custom_skill / "skill.yaml").write_text(
                "id: custom-workflow\n"
                "mode: workflow\n"
                "supports_routes:\n"
                "  - workflow\n"
                "metadata:\n"
                "  priority: 1\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=user_home).discover()

            decision = router.classify("重构 runtime adapter 和 workflow 引擎", skills=skills)

            self.assertEqual(decision.route_name, "workflow")
            self.assertEqual(decision.candidate_skill_ids, ("custom-workflow", "analyze", "design", "develop"))

    def test_runtime_skill_resolution_prefers_workspace_runtime_skill_over_builtin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_home = workspace / "home"
            custom_skill = workspace / ".agents" / "skills" / "custom-compare"
            custom_skill.mkdir(parents=True)
            (custom_skill / "SKILL.md").write_text(
                "---\nname: custom-compare\ndescription: custom compare helper\n---\n\n# custom-compare\n",
                encoding="utf-8",
            )
            (custom_skill / "skill.yaml").write_text(
                "id: custom-compare\n"
                "mode: runtime\n"
                "runtime_entry: custom_runtime.py\n"
                "supports_routes:\n"
                "  - compare\n"
                "host_support:\n"
                "  - codex\n"
                "permission_mode: dual\n"
                "metadata:\n"
                "  priority: 1\n",
                encoding="utf-8",
            )
            (custom_skill / "custom_runtime.py").write_text(
                "def run_skill(**kwargs):\n    return {'ok': True}\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            router = Router(config, state_store=store)
            skills = SkillRegistry(config, user_home=user_home).discover()

            decision = router.classify("~compare 对比 runtime 策略", skills=skills)

            self.assertEqual(decision.route_name, "compare")
            self.assertEqual(decision.candidate_skill_ids, ("custom-compare", "model-compare"))
            self.assertEqual(decision.runtime_skill_id, "custom-compare")

    def test_runtime_handoff_preserves_direct_edit_runtime_required_reason_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = run_runtime(
                "design 阶段现在怎么收口？",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertIsNotNone(result.handoff)
            assert result.handoff is not None
            self.assertEqual(
                result.handoff.artifacts.get("entry_guard_reason_code"),
                DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
            )

    def test_runtime_state_files_expose_request_observability(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            run_runtime(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            current_run_payload = json.loads((workspace / ".sopify-skills" / "state" / "current_run.json").read_text(encoding="utf-8"))
            current_handoff_payload = json.loads((workspace / ".sopify-skills" / "state" / "current_handoff.json").read_text(encoding="utf-8"))

            self.assertIn("补 runtime gate 骨架", current_run_payload["request_excerpt"])
            self.assertTrue(current_run_payload["request_sha1"])
            self.assertEqual(current_run_payload["observability"]["state_kind"], "current_run")
            self.assertIn("补 runtime gate 骨架", current_handoff_payload["observability"]["request_excerpt"])
            self.assertTrue(current_handoff_payload["observability"]["request_sha1"])
            self.assertEqual(current_handoff_payload["observability"]["state_kind"], "current_handoff")
