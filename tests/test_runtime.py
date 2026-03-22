from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.config import ConfigError, load_runtime_config
from runtime._yaml import load_yaml
from runtime.checkpoint_materializer import materialize_checkpoint_request
from runtime.checkpoint_request import (
    CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED,
    CheckpointRequestError,
    DEVELOP_RESUME_CONTEXT_REQUIRED_FIELDS,
    checkpoint_request_from_clarification_state,
    checkpoint_request_from_decision_state,
)
from runtime.clarification import build_clarification_state
from runtime.clarification_bridge import (
    ClarificationBridgeError,
    build_cli_clarification_bridge,
    load_clarification_bridge_context,
    prompt_cli_clarification_submission,
)
from runtime.compare_decision import build_compare_decision_contract
from runtime.develop_checkpoint import DevelopCheckpointError, inspect_develop_checkpoint_context, submit_develop_checkpoint
from runtime.decision import build_decision_state, build_execution_gate_decision_state, confirm_decision, response_from_submission
from runtime.decision_bridge import (
    DecisionBridgeError,
    DecisionBridgeContext,
    build_cli_decision_bridge,
    load_decision_bridge_context,
    prompt_cli_decision_submission,
)
from runtime.decision_policy import match_decision_policy
from runtime.decision_templates import CUSTOM_OPTION_ID, PRIMARY_OPTION_FIELD_ID, build_strategy_pick_template
from runtime.daily_summary import render_daily_summary_markdown
from runtime.engine import run_runtime
from runtime.entry_guard import DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE
from runtime.execution_gate import evaluate_execution_gate
from runtime.handoff import build_runtime_handoff
from runtime.kb import bootstrap_kb, ensure_blueprint_index
from runtime.knowledge_layout import materialization_stage, resolve_context_profile
from runtime.plan_scaffold import create_plan_scaffold, request_explicitly_wants_new_plan
from runtime.output import render_runtime_output
from runtime.plan_orchestrator import (
    PLAN_ORCHESTRATOR_CANCELLED_EXIT,
    PLAN_ORCHESTRATOR_PENDING_EXIT,
    PlanOrchestratorError,
    run_plan_loop,
)
from runtime.preferences import preload_preferences, preload_preferences_for_workspace
from runtime.replay import ReplayWriter, build_decision_replay_event
from runtime.router import Router
from runtime.skill_registry import SkillRegistry
from runtime.skill_runner import SkillExecutionError, run_runtime_skill
from runtime.state import StateStore, iso_now, local_day_now
from runtime.models import (
    DailySummaryArtifact,
    DecisionCheckpoint,
    DecisionCondition,
    DecisionField,
    DecisionOption,
    DecisionRecommendation,
    DecisionSelection,
    DecisionState,
    DecisionSubmission,
    DecisionValidation,
    PlanArtifact,
    ReplayEvent,
    RouteDecision,
    RuntimeHandoff,
    RunState,
    SkillMeta,
    SummaryCodeChangeFact,
    SummaryDecisionFact,
    SummaryFacts,
    SummaryGitCommitRef,
    SummaryGitRefs,
    SummaryGoalFact,
    SummaryIssueFact,
    SummaryLessonFact,
    SummaryNextStepFact,
    SummaryQualityChecks,
    SummaryReplaySessionRef,
    SummaryScope,
    SummarySourceRefFile,
    SummarySourceRefs,
    SummarySourceWindow,
)
from scripts.model_compare_runtime import make_default_candidate


class _FakeInteractiveSession:
    def __init__(self, *, single_choice: object = None, multi_choice: list[object] | None = None, confirm_value: bool = True) -> None:
        self.single_choice = single_choice
        self.multi_choice = list(multi_choice or [])
        self.confirm_value = confirm_value

    def is_available(self) -> bool:
        return True

    def select(self, *, title: str, items, instructions: str, initial_value=None):
        return self.single_choice if self.single_choice is not None else list(items)[0]["value"]

    def multi_select(self, *, title: str, items, instructions: str, initial_values=(), required: bool = False):
        if self.multi_choice:
            return list(self.multi_choice)
        if required:
            return [list(items)[0]["value"]]
        return list(initial_values)

    def confirm(self, *, title: str, yes_label: str, no_label: str, default_value=None, instructions: str) -> bool:
        return self.confirm_value


def _rewrite_background_scope(
    workspace: Path,
    plan_artifact: PlanArtifact,
    *,
    scope_lines: tuple[str, str],
    risk_lines: tuple[str, str] | None = None,
) -> None:
    background_path = workspace / plan_artifact.path / "background.md"
    text = background_path.read_text(encoding="utf-8")
    text = text.replace(
        "- 模块: 待分析\n- 文件: 待分析",
        f"- 模块: {scope_lines[0]}\n- 文件: {scope_lines[1]}",
    )
    if risk_lines is not None:
        text = re.sub(
            r"- 风险: .+\n- 缓解: .+",
            f"- 风险: {risk_lines[0]}\n- 缓解: {risk_lines[1]}",
            text,
        )
    background_path.write_text(text, encoding="utf-8")


def _prepare_ready_plan_state(
    workspace: Path,
    *,
    request_text: str = "补 runtime 骨架",
) -> tuple[object, StateStore, PlanArtifact]:
    config = load_runtime_config(workspace)
    store = StateStore(config)
    store.ensure()
    plan_artifact = create_plan_scaffold(request_text, config=config, level="standard")
    _rewrite_background_scope(
        workspace,
        plan_artifact,
        scope_lines=("runtime/router.py, runtime/engine.py", "runtime/router.py, runtime/engine.py, tests/test_runtime.py"),
        risk_lines=("需要确保执行前确认不会误触发 develop", "统一通过 execution_confirm_pending 与 gate ready 再进入执行"),
    )
    gate = evaluate_execution_gate(
        decision=RouteDecision(
            route_name="workflow",
            request_text=request_text,
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
    store.set_current_plan(plan_artifact)
    store.set_current_run(
        RunState(
            run_id="run-ready",
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
    return config, store, plan_artifact


def _enter_active_develop_context(workspace: Path) -> None:
    _prepare_ready_plan_state(workspace)
    run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")
    result = run_runtime("开始", workspace_root=workspace, user_home=workspace / "home")
    assert result.handoff is not None
    assert result.handoff.required_host_action == "continue_host_develop"


def _git_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    # Git hooks export repo-local environment variables. Clear them so tests
    # that create foreign temp repos do not get redirected back to this repo.
    for key in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_GRAFT_FILE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_SUPER_PREFIX",
        "GIT_WORK_TREE",
    ):
        env.pop(key, None)
    return env


def _run_git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        check=True,
        env=_git_subprocess_env(),
    )


def _init_git_workspace(workspace: Path) -> None:
    _run_git(workspace, "init")
    _run_git(workspace, "config", "user.name", "Test User")
    _run_git(workspace, "config", "user.email", "test@example.com")


def _assert_rendered_footer_contract(
    testcase: unittest.TestCase,
    rendered: str,
    *,
    next_prefix: str,
    generated_at_prefix: str,
) -> None:
    lines = rendered.rstrip().splitlines()
    testcase.assertGreaterEqual(len(lines), 2)
    testcase.assertTrue(lines[-2].startswith(next_prefix), msg=rendered)
    testcase.assertRegex(
        lines[-1],
        rf"^{re.escape(generated_at_prefix)} \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}}$",
    )


class RuntimeConfigTests(unittest.TestCase):
    def test_zero_config_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_runtime_config(temp_dir, global_config_path=Path(temp_dir) / "missing.yaml")
            self.assertEqual(config.language, "zh-CN")
            self.assertEqual(config.workflow_mode, "adaptive")
            self.assertEqual(config.plan_directory, ".sopify-skills")
            self.assertFalse(config.multi_model_enabled)
            self.assertTrue(config.brand.endswith("-ai"))

    def test_project_config_overrides_global(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            global_path = workspace / "global.yaml"
            project_path = workspace / "sopify.config.yaml"
            global_path.write_text(
                "language: en-US\nworkflow:\n  require_score: 5\nplan:\n  level: light\n",
                encoding="utf-8",
            )
            project_path.write_text(
                "workflow:\n  require_score: 9\nplan:\n  directory: .runtime\n",
                encoding="utf-8",
            )
            config = load_runtime_config(workspace, global_config_path=global_path)
            self.assertEqual(config.language, "en-US")
            self.assertEqual(config.require_score, 9)
            self.assertEqual(config.plan_level, "light")
            self.assertEqual(config.plan_directory, ".runtime")

    def test_invalid_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("workflow:\n  mode: unsupported\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_runtime_config(workspace)

    def test_brand_auto_prefers_package_name_over_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-workspace"}', encoding="utf-8")
            config = load_runtime_config(workspace, global_config_path=workspace / "missing.yaml")
            self.assertEqual(config.brand, "sample-workspace-ai")


class YamlLoaderTests(unittest.TestCase):
    def test_quoted_list_item_with_colon_is_parsed_as_string(self) -> None:
        payload = load_yaml('triggers:\n  - "~compare"\n  - "compare:"\n')
        self.assertEqual(payload["triggers"], ["~compare", "compare:"])


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
            self.assertTrue(route.should_create_plan)
            self.assertEqual(
                route.artifacts.get("entry_guard_reason_code"),
                DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
            )

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


class DecisionContractTests(unittest.TestCase):
    def test_decision_policy_keeps_current_planning_semantic_baseline(self) -> None:
        route = RouteDecision(
            route_name="plan_only",
            request_text="payload 放 host root 还是 workspace/.sopify-runtime",
            reason="test",
            complexity="complex",
            plan_level="standard",
        )

        match = match_decision_policy(route)

        self.assertIsNotNone(match)
        self.assertEqual(match.template_id, "strategy_pick")
        self.assertEqual(match.decision_type, "architecture_choice")
        self.assertEqual(match.option_texts, ("payload 放 host root", "workspace/.sopify-runtime"))

    def test_decision_policy_ignores_non_architecture_alternatives(self) -> None:
        route = RouteDecision(
            route_name="workflow",
            request_text="按钮改红色还是蓝色",
            reason="test",
            complexity="complex",
            plan_level="standard",
        )

        self.assertIsNone(match_decision_policy(route))

    def test_decision_policy_prefers_structured_tradeoff_candidates(self) -> None:
        route = RouteDecision(
            route_name="workflow",
            request_text="重构支付模块",
            reason="test",
            complexity="complex",
            plan_level="standard",
            artifacts={
                "decision_question": "确认支付模块改造路径",
                "decision_summary": "存在两个可执行方案，需要先确认长期方向。",
                "decision_context_files": [
                    ".sopify-skills/blueprint/design.md",
                    ".sopify-skills/project.md",
                ],
                "decision_candidates": [
                    {
                        "id": "incremental",
                        "title": "渐进改造",
                        "summary": "低风险拆分现有支付链路。",
                        "tradeoffs": ["迁移周期更长"],
                        "impacts": ["兼容当前发布节奏"],
                    },
                    {
                        "id": "rewrite",
                        "title": "整体重写",
                        "summary": "统一支付边界与数据模型。",
                        "tradeoffs": ["一次性变更面更大"],
                        "impacts": ["长期一致性更强"],
                        "recommended": True,
                    },
                ],
            },
        )

        match = match_decision_policy(route)

        self.assertIsNotNone(match)
        self.assertEqual(match.policy_id, "design_tradeoff_candidates")
        self.assertEqual(match.question, "确认支付模块改造路径")
        self.assertEqual(match.context_files, (".sopify-skills/blueprint/design.md", ".sopify-skills/project.md"))
        self.assertEqual(match.options[1].option_id, "rewrite")
        self.assertEqual(match.recommended_option_index, 1)

    def test_decision_policy_suppresses_structured_tradeoff_when_preference_locked(self) -> None:
        route = RouteDecision(
            route_name="workflow",
            request_text="重构支付模块",
            reason="test",
            complexity="complex",
            plan_level="standard",
            artifacts={
                "decision_preference_locked": True,
                "decision_candidates": [
                    {"id": "option_1", "title": "方案一", "summary": "低风险", "tradeoffs": ["慢"]},
                    {"id": "option_2", "title": "方案二", "summary": "高一致性", "tradeoffs": ["快但风险高"]},
                ],
            },
        )

        self.assertIsNone(match_decision_policy(route))

    def test_decision_policy_matches_four_standard_policy_choices(self) -> None:
        cases = (
            ("route->skill 声明式 resolver 还是继续硬编码 skill 绑定？", "skill_selection_policy_choice"),
            ("权限执行主体走 host + runtime 双保险还是仅 runtime 自验？", "permission_enforcement_mode_choice"),
            ("catalog 生成时机选构建期静态生成还是运行期动态生成？", "catalog_generation_timing_choice"),
            ("eval SLO 阈值走严格阻断还是仅告警提示？", "eval_slo_threshold_choice"),
        )
        for request_text, expected_policy_id in cases:
            with self.subTest(policy_id=expected_policy_id):
                route = RouteDecision(
                    route_name="workflow",
                    request_text=request_text,
                    reason="test",
                    complexity="complex",
                    plan_level="standard",
                )

                match = match_decision_policy(route)

                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.policy_id, expected_policy_id)
                self.assertEqual(match.template_id, "strategy_pick")
                self.assertEqual(len(match.option_texts), 2)

    def test_decision_policy_does_not_trigger_standard_policy_without_tradeoff_split(self) -> None:
        cases = (
            "请说明当前 skill 选择策略",
            "请说明权限执行策略",
            "请说明 catalog 生成策略",
            "请说明 eval SLO 阈值策略",
        )
        for request_text in cases:
            with self.subTest(request_text=request_text):
                route = RouteDecision(
                    route_name="workflow",
                    request_text=request_text,
                    reason="test",
                    complexity="complex",
                    plan_level="standard",
                )
                self.assertIsNone(match_decision_policy(route))

    def test_decision_policy_honors_explicit_standard_policy_id_from_artifacts(self) -> None:
        route = RouteDecision(
            route_name="workflow",
            request_text="请确认策略方向",
            reason="test",
            complexity="complex",
            plan_level="standard",
            artifacts={
                "decision_policy_id": "catalog_generation_timing_choice",
                "decision_candidates": [
                    {
                        "id": "build_time",
                        "title": "构建期静态生成",
                        "summary": "发布时生成 catalog。",
                        "tradeoffs": ["发布流水线增加一次生成步骤"],
                    },
                    {
                        "id": "runtime_time",
                        "title": "运行期动态生成",
                        "summary": "按需动态构建 catalog。",
                        "tradeoffs": ["运行期开销更高"],
                    },
                ],
            },
        )

        match = match_decision_policy(route)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.policy_id, "catalog_generation_timing_choice")
        self.assertEqual(match.trigger_reason, "explicit_standard_policy_id")
        self.assertEqual(match.option_texts, ("构建期静态生成", "运行期动态生成"))

    def test_strategy_pick_template_supports_custom_and_constraint_fields(self) -> None:
        rendered = build_strategy_pick_template(
            checkpoint_id="decision_template_1",
            question="确认方案",
            summary="请选择本轮方向",
            options=(
                DecisionOption(option_id="option_1", title="方案一", summary="保守路径", recommended=True),
                DecisionOption(option_id="option_2", title="方案二", summary="激进路径"),
            ),
            language="zh-CN",
            recommended_option_id="option_1",
            default_option_id="option_1",
            allow_custom_option=True,
            constraint_field_type="input",
        )

        self.assertEqual(len(rendered.options), 3)
        self.assertEqual(rendered.options[-1].option_id, CUSTOM_OPTION_ID)
        self.assertEqual(len(rendered.checkpoint.fields), 3)
        self.assertEqual(rendered.checkpoint.fields[0].field_id, PRIMARY_OPTION_FIELD_ID)
        self.assertEqual(rendered.checkpoint.fields[1].field_type, "textarea")
        self.assertEqual(rendered.checkpoint.fields[1].when[0].value, CUSTOM_OPTION_ID)
        self.assertEqual(rendered.checkpoint.fields[2].field_type, "input")

    def test_compare_decision_contract_shortlists_successful_results(self) -> None:
        contract = build_compare_decision_contract(
            question="比较支付模块重构方案",
            language="zh-CN",
            skill_result={
                "results": [
                    {"candidate_id": "session_default", "status": "ok", "answer": "建议先做渐进拆分。", "latency_ms": 120},
                    {"candidate_id": "external_a", "status": "ok", "answer": "建议整体重写，但要补迁移预案。", "latency_ms": 220},
                    {"candidate_id": "external_b", "status": "error", "error": "boom", "latency_ms": 10},
                    {"candidate_id": "external_c", "status": "ok", "answer": "建议先统一接口，再逐步迁移数据。", "latency_ms": 180},
                ]
            },
        )

        self.assertIsNotNone(contract)
        self.assertEqual(contract["decision_type"], "compare_result_choice")
        self.assertEqual(contract["recommended_option_id"], "session_default")
        self.assertEqual(contract["result_count"], 3)
        self.assertEqual(contract["shortlisted_result_count"], 3)
        checkpoint = contract["checkpoint"]
        self.assertEqual(checkpoint["primary_field_id"], PRIMARY_OPTION_FIELD_ID)
        self.assertEqual(checkpoint["recommendation"]["option_id"], "session_default")
        self.assertIn("session_default", [item["id"] for item in checkpoint["fields"][0]["options"]])

    def test_cli_decision_bridge_exposes_interactive_contract_and_text_fallback(self) -> None:
        rendered = build_strategy_pick_template(
            checkpoint_id="decision_template_cli",
            question="确认方案",
            summary="请选择本轮方向",
            options=(
                DecisionOption(option_id="option_1", title="方案一", summary="保守路径", recommended=True),
                DecisionOption(option_id="option_2", title="方案二", summary="激进路径"),
            ),
            language="zh-CN",
            recommended_option_id="option_1",
            default_option_id="option_1",
            allow_custom_option=True,
            constraint_field_type="confirm",
        )
        context = DecisionBridgeContext(
            handoff=None,
            decision_state=DecisionState(
                schema_version="2",
                decision_id="decision_template_cli",
                feature_key="decision",
                phase="design",
                status="pending",
                decision_type="architecture_choice",
                question="确认方案",
                summary="请选择本轮方向",
                options=rendered.options,
                checkpoint=rendered.checkpoint,
                recommended_option_id=rendered.recommended_option_id,
                default_option_id=rendered.default_option_id,
            ),
            checkpoint=rendered.checkpoint,
            submission_state={"status": "empty", "has_answers": False, "answer_keys": []},
        )

        bridge = build_cli_decision_bridge(context, language="zh-CN")

        self.assertEqual(bridge["host_kind"], "cli")
        self.assertEqual(bridge["presentation"]["recommended_mode"], "interactive_form")
        self.assertEqual(bridge["steps"][0]["renderer"], "cli.select")
        self.assertEqual(bridge["steps"][0]["fallback_renderer"], "text")
        self.assertEqual(bridge["steps"][1]["ui_kind"], "textarea")
        self.assertEqual(bridge["steps"][1]["fallback_renderer"], "text")
        self.assertEqual(bridge["steps"][2]["ui_kind"], "confirm")

    def test_decision_checkpoint_roundtrip_normalizes_contract_fields(self) -> None:
        checkpoint = DecisionCheckpoint(
            checkpoint_id="decision_contract_1",
            title="选择方案",
            message="请选择最终执行路径",
            fields=(
                DecisionField(
                    field_id="selected_option_id",
                    field_type="select",
                    label="方案",
                    required=True,
                    options=(
                        DecisionOption(option_id="option_1", title="方案一", summary="保守路径", recommended=True),
                        DecisionOption(option_id="option_2", title="方案二", summary="激进路径"),
                    ),
                    validations=(DecisionValidation(rule="required", message="必须选择一个方案"),),
                ),
                DecisionField(
                    field_id="custom_reason",
                    field_type="textarea",
                    label="补充说明",
                    when=(DecisionCondition(field_id="selected_option_id", operator="not_in", value=["option_1"]),),
                ),
            ),
            primary_field_id="selected_option_id",
            recommendation=DecisionRecommendation(
                field_id="selected_option_id",
                option_id="option_1",
                summary="默认推荐方案一",
                reason="风险最低",
            ),
        )

        payload = checkpoint.to_dict()
        payload["fields"][0]["field_type"] = "SELECT"
        payload["fields"][1]["field_type"] = "TEXTAREA"
        payload["fields"][1]["when"][0]["operator"] = "NOT-IN"
        restored = DecisionCheckpoint.from_dict(payload)

        self.assertEqual(restored.fields[0].field_type, "select")
        self.assertEqual(restored.fields[1].field_type, "textarea")
        self.assertEqual(restored.fields[1].when[0].operator, "not_in")
        self.assertEqual(restored.recommendation.option_id, "option_1")

    def test_checkpoint_request_roundtrip_materializes_decision_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            rendered = build_strategy_pick_template(
                checkpoint_id="decision_request_1",
                question="确认方案",
                summary="请选择本轮方向",
                options=(
                    DecisionOption(option_id="option_1", title="方案一", summary="保守路径", recommended=True),
                    DecisionOption(option_id="option_2", title="方案二", summary="激进路径"),
                ),
                language="zh-CN",
                recommended_option_id="option_1",
                default_option_id="option_1",
            )
            decision_state = DecisionState(
                schema_version="2",
                decision_id="decision_request_1",
                feature_key="runtime",
                phase="design",
                status="pending",
                decision_type="architecture_choice",
                question="确认方案",
                summary="请选择本轮方向",
                options=rendered.options,
                checkpoint=rendered.checkpoint,
                recommended_option_id="option_1",
                default_option_id="option_1",
                context_files=("runtime/engine.py",),
                resume_route="workflow",
                request_text="确认方案",
                requested_plan_level="standard",
                capture_mode="summary",
                candidate_skill_ids=("design",),
                policy_id="planning_semantic_split",
                trigger_reason="explicit_architecture_split",
                created_at=iso_now(),
                updated_at=iso_now(),
            )

            request = checkpoint_request_from_decision_state(decision_state)
            materialized = materialize_checkpoint_request(request.to_dict(), config=config)

            self.assertEqual(materialized.required_host_action, "confirm_decision")
            self.assertEqual(materialized.decision_state.decision_id, "decision_request_1")
            self.assertEqual(materialized.decision_state.active_checkpoint.primary_field_id, "selected_option_id")
            self.assertEqual(materialized.decision_state.options[0].option_id, "option_1")

    def test_checkpoint_request_roundtrip_materializes_clarification_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            result = run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")
            clarification_state = StateStore(load_runtime_config(workspace)).get_current_clarification()

            self.assertEqual(result.route.route_name, "clarification_pending")
            self.assertIsNotNone(clarification_state)

            request = checkpoint_request_from_clarification_state(clarification_state, config=config)
            materialized = materialize_checkpoint_request(request.to_dict(), config=config)

            self.assertEqual(materialized.required_host_action, "answer_questions")
            self.assertEqual(materialized.clarification_state.clarification_id, clarification_state.clarification_id)
            self.assertEqual(materialized.clarification_state.missing_facts, clarification_state.missing_facts)

    def test_materialize_checkpoint_request_rejects_invalid_decision_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            with self.assertRaises(CheckpointRequestError):
                materialize_checkpoint_request(
                    {
                        "schema_version": "1",
                        "checkpoint_kind": "decision",
                        "checkpoint_id": "broken_decision",
                        "source_stage": "design",
                        "source_route": "workflow",
                        "question": "确认方案",
                        "summary": "缺少 options 和 checkpoint。",
                    },
                    config=config,
                )

    def test_materialize_checkpoint_request_rejects_develop_checkpoint_without_resume_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            with self.assertRaisesRegex(CheckpointRequestError, "resume_context"):
                materialize_checkpoint_request(
                    {
                        "schema_version": "1",
                        "checkpoint_kind": "decision",
                        "checkpoint_id": "develop_decision_missing_resume",
                        "source_stage": "develop",
                        "source_route": "resume_active",
                        "question": "继续怎么改？",
                        "summary": "开发中需要用户确认。",
                        "options": [
                            {"id": "option_1", "title": "方案一", "summary": "保守"},
                            {"id": "option_2", "title": "方案二", "summary": "激进"},
                        ],
                    },
                    config=config,
                )

    def test_checkpoint_request_roundtrip_preserves_develop_resume_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            rendered = build_strategy_pick_template(
                checkpoint_id="develop_decision_1",
                question="认证边界是否移动到 adapter 层？",
                summary="开发中已经命中实现分叉，需要用户拍板。",
                options=(
                    DecisionOption(option_id="option_1", title="保持现状", summary="边界不动", recommended=True),
                    DecisionOption(option_id="option_2", title="移动边界", summary="改到 adapter 层"),
                ),
                language="zh-CN",
                recommended_option_id="option_1",
                default_option_id="option_1",
            )
            resume_context = {
                "active_run_stage": "executing",
                "current_plan_path": ".sopify-skills/plan/20260319_feature",
                "task_refs": ["2.1", "2.2"],
                "changed_files": ["runtime/engine.py"],
                "working_summary": "已经接上 develop callback，需要确认认证边界。",
                "verification_todo": ["补 checkpoint contract 测试"],
                "resume_after": "continue_host_develop",
            }
            decision_state = DecisionState(
                schema_version="2",
                decision_id="develop_decision_1",
                feature_key="runtime",
                phase="develop",
                status="pending",
                decision_type="develop_choice",
                question="认证边界是否移动到 adapter 层？",
                summary="开发中已经命中实现分叉，需要用户拍板。",
                options=rendered.options,
                checkpoint=rendered.checkpoint,
                recommended_option_id="option_1",
                default_option_id="option_1",
                context_files=("runtime/engine.py",),
                resume_route="resume_active",
                request_text="继续 develop callback",
                requested_plan_level="standard",
                capture_mode="summary",
                candidate_skill_ids=("develop",),
                policy_id="develop_checkpoint_callback",
                trigger_reason="host_callback",
                resume_context=resume_context,
                created_at=iso_now(),
                updated_at=iso_now(),
            )

            request = checkpoint_request_from_decision_state(decision_state)
            materialized = materialize_checkpoint_request(request.to_dict(), config=config)

            self.assertEqual(materialized.required_host_action, "confirm_decision")
            self.assertEqual(materialized.decision_state.phase, "develop")
            self.assertEqual(materialized.decision_state.resume_context["working_summary"], resume_context["working_summary"])
            self.assertEqual(
                set(DEVELOP_RESUME_CONTEXT_REQUIRED_FIELDS),
                set(materialized.decision_state.resume_context.keys()) & set(DEVELOP_RESUME_CONTEXT_REQUIRED_FIELDS),
            )

    def test_state_store_persists_structured_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            store = StateStore(load_runtime_config(workspace))
            updated = store.set_current_decision_submission(
                DecisionSubmission(
                    status="collecting",
                    source="cli",
                    answers={"selected_option_id": "option_2"},
                    submitted_at=iso_now(),
                    resume_action="submit",
                )
            )

            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, "collecting")
            reloaded = store.get_current_decision()
            self.assertEqual(reloaded.status, "collecting")
            self.assertEqual(reloaded.submission.answers["selected_option_id"], "option_2")

    def test_response_from_submission_uses_legacy_answer_key_fallback(self) -> None:
        decision_state = DecisionState(
            schema_version="2",
            decision_id="decision_submission_1",
            feature_key="decision",
            phase="design",
            status="pending",
            decision_type="architecture_choice",
            question="确认方案",
            summary="请选择方向",
            options=(
                DecisionOption(option_id="option_1", title="方案一", summary="保守路径", recommended=True),
                DecisionOption(option_id="option_2", title="方案二", summary="激进路径"),
            ),
            checkpoint=DecisionCheckpoint(
                checkpoint_id="decision_submission_1",
                title="确认方案",
                message="请选择方向",
                fields=(),
                primary_field_id=None,
            ),
            submission=DecisionSubmission(
                status="submitted",
                source="cli",
                answers={"selected_option_id": "option_2"},
                submitted_at=iso_now(),
                resume_action="submit",
            ),
        )

        response = response_from_submission(decision_state)

        self.assertIsNotNone(response)
        self.assertEqual(response.action, "choose")
        self.assertEqual(response.option_id, "option_2")

    def test_handoff_includes_decision_checkpoint_and_submission_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            pending = run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertIn("decision_checkpoint", pending.handoff.artifacts)
            self.assertEqual(pending.handoff.artifacts["checkpoint_request"]["checkpoint_kind"], "decision")
            self.assertEqual(pending.handoff.artifacts["decision_submission_state"]["status"], "empty")
            self.assertTrue(pending.handoff.artifacts["entry_guard"]["strict_runtime_entry"])
            self.assertEqual(pending.handoff.artifacts["entry_guard_reason_code"], "entry_guard_decision_pending")

            store = StateStore(load_runtime_config(workspace))
            store.set_current_decision_submission(
                DecisionSubmission(
                    status="submitted",
                    source="cli",
                    answers={"selected_option_id": "option_1"},
                    submitted_at=iso_now(),
                    resume_action="submit",
                )
            )

            inspected = run_runtime("~decide status", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(inspected.route.route_name, "decision_pending")
            self.assertEqual(inspected.handoff.artifacts["decision_checkpoint"]["primary_field_id"], "selected_option_id")
            self.assertEqual(inspected.handoff.artifacts["checkpoint_request"]["checkpoint_id"], inspected.handoff.artifacts["decision_id"])
            self.assertEqual(inspected.handoff.artifacts["decision_submission_state"]["status"], "submitted")
            self.assertEqual(inspected.handoff.artifacts["decision_submission_state"]["answer_keys"], ["selected_option_id"])

    def test_handoff_includes_execution_confirm_checkpoint_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)

            result = run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "execution_confirm_pending")
            self.assertEqual(result.handoff.required_host_action, "confirm_execute")
            self.assertEqual(result.handoff.artifacts["checkpoint_request"]["checkpoint_kind"], "execution_confirm")
            self.assertEqual(result.handoff.artifacts["entry_guard_reason_code"], "entry_guard_execution_confirm_pending")
            self.assertEqual(
                result.handoff.artifacts["checkpoint_request"]["execution_summary"]["plan_path"],
                result.handoff.artifacts["execution_summary"]["plan_path"],
            )

    def test_handoff_marks_missing_checkpoint_request_when_tradeoff_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            decision = RouteDecision(
                route_name="workflow",
                request_text="确认支付模块改造路径",
                reason="test",
                complexity="complex",
                plan_level="standard",
            )

            handoff = build_runtime_handoff(
                config=config,
                decision=decision,
                run_id="run-missing-checkpoint",
                current_run=None,
                current_plan=None,
                kb_artifact=None,
                replay_session_dir=None,
                skill_result={
                    "decision_candidates": [
                        {
                            "id": "incremental",
                            "title": "渐进改造",
                            "summary": "低风险拆分现有支付链路。",
                            "tradeoffs": ["迁移周期更长"],
                        },
                        {
                            "id": "rewrite",
                            "title": "整体重写",
                            "summary": "统一支付边界与数据模型。",
                            "tradeoffs": ["一次性变更面更大"],
                        },
                    ]
                },
                current_clarification=None,
                current_decision=None,
                notes=("test",),
            )

            self.assertIsNotNone(handoff)
            self.assertEqual(
                handoff.artifacts.get("checkpoint_request_reason_code"),
                CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED,
            )
            self.assertEqual(
                handoff.artifacts.get("checkpoint_request_error"),
                CHECKPOINT_REASON_MISSING_BUT_TRADEOFF_DETECTED,
            )

    def test_cli_text_bridge_collects_submission_and_runtime_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            config = load_runtime_config(workspace)
            answers = iter(("1",))

            submission, used_renderer = prompt_cli_decision_submission(
                config=config,
                renderer="auto",
                input_reader=lambda _prompt: next(answers),
                output_writer=lambda _message: None,
            )

            self.assertEqual(used_renderer, "text")
            self.assertEqual(submission.answers["selected_option_id"], "option_1")
            store = StateStore(config)
            updated = store.get_current_decision()
            self.assertIsNotNone(updated)
            self.assertEqual(updated.submission.status, "submitted")
            self.assertEqual(updated.submission.answers["selected_option_id"], "option_1")

            resumed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "plan_only")
            self.assertIsNotNone(resumed.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_decision.json").exists())

    def test_cli_interactive_bridge_collects_submission_without_text_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            config = load_runtime_config(workspace)

            submission, used_renderer = prompt_cli_decision_submission(
                config=config,
                renderer="interactive",
                input_reader=lambda _prompt: "",
                output_writer=lambda _message: None,
                interactive_session_factory=lambda: _FakeInteractiveSession(single_choice="option_2"),
            )

            self.assertEqual(used_renderer, "interactive")
            self.assertEqual(submission.answers["selected_option_id"], "option_2")
            self.assertEqual(submission.source, "cli_interactive")

    def test_decision_bridge_script_inspect_and_submit_for_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            script_path = REPO_ROOT / "scripts" / "decision_bridge_runtime.py"

            inspected = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
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
            self.assertEqual(inspect_payload["status"], "ready")
            self.assertEqual(inspect_payload["bridge"]["host_kind"], "cli")
            self.assertEqual(inspect_payload["bridge"]["steps"][0]["renderer"], "cli.select")

            submitted = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
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

            self.assertEqual(submitted.returncode, 0, msg=submitted.stderr)
            submit_payload = json.loads(submitted.stdout)
            self.assertEqual(submit_payload["status"], "written")
            self.assertEqual(submit_payload["submission"]["answers"]["selected_option_id"], "option_1")

            store = StateStore(load_runtime_config(workspace))
            updated = store.get_current_decision()
            self.assertIsNotNone(updated)
            self.assertEqual(updated.submission.status, "submitted")
            self.assertEqual(updated.submission.answers["selected_option_id"], "option_1")

    def test_decision_bridge_rejects_handoff_without_strict_entry_guard_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            config = load_runtime_config(workspace)
            store = StateStore(config)
            handoff = store.get_current_handoff()
            self.assertIsNotNone(handoff)

            payload = handoff.to_dict()
            artifacts = dict(payload.get("artifacts") or {})
            artifacts.pop("entry_guard", None)
            payload["artifacts"] = artifacts
            store.current_handoff_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(DecisionBridgeError, "decision_bridge_handoff_mismatch"):
                load_decision_bridge_context(config=config)

    def test_clarification_bridge_rejects_handoff_with_mismatched_clarification_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")
            config = load_runtime_config(workspace)
            store = StateStore(config)
            handoff = store.get_current_handoff()
            self.assertIsNotNone(handoff)

            payload = handoff.to_dict()
            artifacts = dict(payload.get("artifacts") or {})
            artifacts["clarification_id"] = "clarification_fake_001"
            payload["artifacts"] = artifacts
            store.current_handoff_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ClarificationBridgeError, "clarification_bridge_handoff_mismatch"):
                load_clarification_bridge_context(config=config)

    def test_cli_clarification_bridge_exposes_interactive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")
            config = load_runtime_config(workspace)

            context = load_clarification_bridge_context(config=config)
            bridge = build_cli_clarification_bridge(context, language="zh-CN")

            self.assertEqual(bridge["host_kind"], "cli")
            self.assertEqual(bridge["required_host_action"], "answer_questions")
            self.assertEqual(bridge["presentation"]["recommended_mode"], "interactive_form")
            self.assertEqual([step["field_id"] for step in bridge["steps"]], ["target_scope", "expected_outcome"])
            self.assertEqual(bridge["steps"][0]["renderer"], "cli.input")
            self.assertEqual(bridge["steps"][1]["fallback_renderer"], "text")

    def test_cli_clarification_bridge_collects_submission_and_runtime_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")
            config = load_runtime_config(workspace)
            answers = iter(("runtime/router.py", "补结构化 clarification bridge。", "."))

            submission, used_renderer = prompt_cli_clarification_submission(
                config=config,
                renderer="auto",
                input_reader=lambda _prompt: next(answers),
                output_writer=lambda _message: None,
            )

            self.assertEqual(used_renderer, "text")
            self.assertEqual(submission["response_fields"]["target_scope"], "runtime/router.py")
            self.assertIn("预期结果", submission["response_text"])
            store = StateStore(config)
            updated = store.get_current_clarification()
            self.assertIsNotNone(updated)
            self.assertEqual(updated.response_source, "cli_text")
            self.assertEqual(updated.response_fields["expected_outcome"], "补结构化 clarification bridge。")

            resumed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "plan_only")
            self.assertIsNotNone(resumed.plan_artifact)
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_clarification.json").exists())

    def test_clarification_bridge_script_inspect_and_submit_for_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            run_runtime("~go plan 优化一下", workspace_root=workspace, user_home=workspace / "home")
            script_path = REPO_ROOT / "scripts" / "clarification_bridge_runtime.py"

            inspected = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
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
            self.assertEqual(inspect_payload["status"], "ready")
            self.assertEqual(inspect_payload["bridge"]["host_kind"], "cli")
            self.assertEqual(inspect_payload["bridge"]["presentation"]["recommended_mode"], "interactive_form")

            submitted = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--workspace-root",
                    str(workspace),
                    "submit",
                    "--answers-json",
                    '{"target_scope":"runtime/router.py","expected_outcome":"补结构化 clarification bridge。"}',
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(submitted.returncode, 0, msg=submitted.stderr)
            submit_payload = json.loads(submitted.stdout)
            self.assertEqual(submit_payload["status"], "written")
            self.assertEqual(submit_payload["submission"]["response_fields"]["target_scope"], "runtime/router.py")

            store = StateStore(load_runtime_config(workspace))
            updated = store.get_current_clarification()
            self.assertIsNotNone(updated)
            self.assertEqual(updated.response_source, "cli")
            self.assertEqual(updated.response_fields["expected_outcome"], "补结构化 clarification bridge。")


class SummaryContractTests(unittest.TestCase):
    def test_daily_summary_artifact_roundtrip_preserves_nested_contract(self) -> None:
        artifact = DailySummaryArtifact(
            summary_key="2026-03-19::/Users/weixin.li/Desktop/vs-code-extension/sopify-skills",
            scope=SummaryScope(
                local_day="2026-03-19",
                workspace_root="/Users/weixin.li/Desktop/vs-code-extension/sopify-skills",
                workspace_label="当前工作区",
                timezone="Asia/Shanghai",
            ),
            revision=2,
            generated_at="2026-03-19T21:21:41+08:00",
            source_window=SummarySourceWindow(
                from_ts="2026-03-19T00:00:00+08:00",
                to_ts="2026-03-19T21:21:41+08:00",
            ),
            source_refs=SummarySourceRefs(
                plan_files=(
                    SummarySourceRefFile(
                        path=".sopify-skills/plan/20260319_task-168cb6/design.md",
                        kind="plan",
                        updated_at="2026-03-19T20:58:00+08:00",
                    ),
                ),
                state_files=(
                    SummarySourceRefFile(
                        path=".sopify-skills/state/current_plan.json",
                        kind="state",
                        updated_at="2026-03-19T21:10:00+08:00",
                    ),
                ),
                handoff_files=(
                    SummarySourceRefFile(
                        path=".sopify-skills/state/current_handoff.json",
                        kind="handoff",
                        updated_at="2026-03-19T21:10:00+08:00",
                    ),
                ),
                git_refs=SummaryGitRefs(
                    base_ref="HEAD",
                    changed_files=(".sopify-skills/plan/20260319_task-168cb6/design.md",),
                    commits=(
                        SummaryGitCommitRef(
                            sha="abc1234",
                            title="Refine summary contract",
                            authored_at="2026-03-19T20:45:00+08:00",
                        ),
                    ),
                ),
                replay_sessions=(
                    SummaryReplaySessionRef(
                        run_id="20260319T132141_14a099",
                        path=".sopify-skills/replay/sessions/20260319T132141_14a099",
                        used_for="timeline",
                    ),
                ),
            ),
            facts=SummaryFacts(
                headline="今天完成了当前时间显示与 ~summary 主线收敛。",
                goals=(
                    SummaryGoalFact(
                        fact_id="goal-1",
                        summary="收窄当前切片，优先满足可复盘摘要需求。",
                        evidence_refs=("plan_files[0]",),
                    ),
                ),
                decisions=(
                    SummaryDecisionFact(
                        fact_id="decision-1",
                        summary="本期不先做 daily index。",
                        reason="~summary 一天通常只运行 1-2 次，现算现出更轻。",
                        status="confirmed",
                        evidence_refs=("plan_files[0]", "handoff_files[0]"),
                    ),
                ),
                code_changes=(
                    SummaryCodeChangeFact(
                        path=".sopify-skills/plan/20260319_task-168cb6/design.md",
                        change_type="modified",
                        summary="把 ~summary 数据契约收敛到可编码 schema。",
                        reason="让后续实现不依赖聊天回忆。",
                        verification="not_run",
                        evidence_refs=("git_refs.changed_files[0]",),
                    ),
                ),
                issues=(
                    SummaryIssueFact(
                        fact_id="issue-1",
                        summary="replay events 当前使用率不高。",
                        status="open",
                        resolution="",
                        evidence_refs=("replay_sessions[0]",),
                    ),
                ),
                lessons=(
                    SummaryLessonFact(
                        fact_id="lesson-1",
                        summary="摘要应优先绑定机器事实源，而不是自由聊天文本。",
                        reusable_pattern="先确定性收集，再模板渲染。",
                        evidence_refs=("state_files[0]", "handoff_files[0]"),
                    ),
                ),
                next_steps=(
                    SummaryNextStepFact(
                        fact_id="next-1",
                        summary="把 summary schema 映射到实际运行时实现。",
                        priority="medium",
                        evidence_refs=("plan_files[0]",),
                    ),
                ),
            ),
            quality_checks=SummaryQualityChecks(
                replay_optional=True,
                summary_runs_per_day="1-2",
                required_sections_present=True,
                missing_inputs=(),
                fallback_used=(),
            ),
        )

        payload = artifact.to_dict()
        restored = DailySummaryArtifact.from_dict(payload)

        self.assertEqual(payload["source_window"]["from"], "2026-03-19T00:00:00+08:00")
        self.assertEqual(restored.summary_key, artifact.summary_key)
        self.assertEqual(restored.scope.workspace_root, artifact.scope.workspace_root)
        self.assertEqual(restored.revision, 2)
        self.assertEqual(restored.source_refs.git_refs.commits[0].sha, "abc1234")
        self.assertEqual(restored.facts.decisions[0].status, "confirmed")
        self.assertTrue(restored.quality_checks.replay_optional)
        self.assertEqual(restored.to_dict(), payload)

    def test_daily_summary_markdown_preserves_iso_timestamp_for_internal_artifact(self) -> None:
        artifact = DailySummaryArtifact(
            summary_key="2026-03-19::/tmp/demo",
            scope=SummaryScope(
                local_day="2026-03-19",
                workspace_root="/tmp/demo",
                workspace_label="当前工作区",
                timezone="Asia/Shanghai",
            ),
            revision=1,
            generated_at="2026-03-19T21:21:41+08:00",
            source_window=SummarySourceWindow(
                from_ts="2026-03-19T00:00:00+08:00",
                to_ts="2026-03-19T21:21:41+08:00",
            ),
            source_refs=SummarySourceRefs(),
            facts=SummaryFacts(
                headline="今天围绕当前方案推进了关键实现。",
                goals=(),
                decisions=(),
                code_changes=(),
                issues=(),
                lessons=(),
                next_steps=(),
            ),
            quality_checks=SummaryQualityChecks(
                replay_optional=True,
                summary_runs_per_day="1-2",
                required_sections_present=True,
                missing_inputs=(),
                fallback_used=(),
            ),
        )

        markdown = render_daily_summary_markdown(artifact=artifact, language="zh-CN")

        self.assertIn("生成于: 2026-03-19T21:21:41+08:00", markdown)
        self.assertNotIn("生成于: 2026-03-19 21:21:41", markdown)


class PlanScaffoldTests(unittest.TestCase):
    def test_plan_scaffold_creates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            light = create_plan_scaffold("修复登录错误提示", config=config, level="light")
            standard = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            full = create_plan_scaffold("设计 runtime architecture plugin bridge", config=config, level="full")

            self.assertTrue((workspace / light.path / "plan.md").exists())
            self.assertTrue((workspace / standard.path / "background.md").exists())
            self.assertTrue((workspace / standard.path / "design.md").exists())
            self.assertTrue((workspace / standard.path / "tasks.md").exists())
            self.assertTrue((workspace / full.path / "adr").is_dir())
            self.assertTrue((workspace / full.path / "diagrams").is_dir())

    def test_plan_scaffold_writes_knowledge_sync_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            light = create_plan_scaffold("修复登录错误提示", config=config, level="light")
            standard = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            full = create_plan_scaffold("设计 runtime architecture plugin bridge", config=config, level="full")

            light_text = (workspace / light.path / "plan.md").read_text(encoding="utf-8")
            standard_text = (workspace / standard.path / "tasks.md").read_text(encoding="utf-8")
            full_text = (workspace / full.path / "tasks.md").read_text(encoding="utf-8")

            self.assertIn("knowledge_sync:", light_text)
            self.assertIn("  project: skip", light_text)
            self.assertIn("  design: review", light_text)
            self.assertNotIn("blueprint_obligation:", light_text)

            self.assertIn("knowledge_sync:", standard_text)
            self.assertIn("  project: review", standard_text)
            self.assertIn("  background: review", standard_text)
            self.assertIn("  design: review", standard_text)
            self.assertIn("  tasks: review", standard_text)
            self.assertNotIn("blueprint_obligation:", standard_text)

            self.assertIn("knowledge_sync:", full_text)
            self.assertIn("  background: required", full_text)
            self.assertIn("  design: required", full_text)
            self.assertIn("  tasks: review", full_text)
            self.assertNotIn("blueprint_obligation:", full_text)

    def test_plan_scaffold_avoids_directory_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            first = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")
            second = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")

            self.assertNotEqual(first.path, second.path)
            self.assertTrue(second.path.endswith("-2"))

    def test_plan_scaffold_persists_topic_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            artifact = create_plan_scaffold("补 runtime 骨架", config=config, level="standard")
            tasks_text = (workspace / artifact.path / "tasks.md").read_text(encoding="utf-8")

            self.assertEqual(artifact.topic_key, "runtime")
            self.assertIn("feature_key: runtime", tasks_text)

    def test_explicit_new_plan_patterns_ignore_ambiguous_other_plan_phrase(self) -> None:
        self.assertFalse(request_explicitly_wants_new_plan("分析这个方案和其他 plan 的差异"))
        self.assertTrue(request_explicitly_wants_new_plan("请新建一个 plan 处理这个问题"))


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
            self.assertTrue(any("strict single-active-plan policy" in note for note in result.notes))
            self.assertEqual(len(list((workspace / ".sopify-skills" / "plan").iterdir())), 1)

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
            self.assertEqual(len(list((workspace / ".sopify-skills" / "plan").iterdir())), 2)

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
            self.assertEqual(len(list((workspace / ".sopify-skills" / "plan").iterdir())), 1)
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
            self.assertEqual(len(list((workspace / ".sopify-skills" / "plan").iterdir())), 1)
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
            self.assertEqual(len(list((workspace / ".sopify-skills" / "plan").iterdir())), 1)
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
            self.assertEqual(len(list((workspace / ".sopify-skills" / "plan").iterdir())), 2)

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
            self.assertIsNotNone(second.plan_artifact)
            assert second.plan_artifact is not None
            self.assertEqual(second.plan_artifact.plan_id, current_plan.plan_id)
            self.assertEqual(len(list((workspace / ".sopify-skills" / "plan").iterdir())), 1)
            rebound = StateStore(load_runtime_config(workspace)).get_current_plan()
            self.assertIsNotNone(rebound)
            assert rebound is not None
            self.assertEqual(rebound.plan_id, current_plan.plan_id)


class ExecutionGateTests(unittest.TestCase):
    def test_execution_gate_blocks_scaffold_until_scope_is_concrete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            plan_artifact = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            route = RouteDecision(
                route_name="workflow",
                request_text="实现 runtime skeleton",
                reason="test",
                complexity="complex",
                plan_level="standard",
            )

            gate = evaluate_execution_gate(
                decision=route,
                plan_artifact=plan_artifact,
                current_clarification=None,
                current_decision=None,
                config=config,
            )

            self.assertEqual(gate.gate_status, "blocked")
            self.assertEqual(gate.blocking_reason, "missing_info")
            self.assertEqual(gate.plan_completion, "incomplete")
            self.assertEqual(gate.next_required_action, "continue_host_develop")

    def test_execution_gate_marks_complete_plan_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            plan_artifact = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            _rewrite_background_scope(
                workspace,
                plan_artifact,
                scope_lines=("runtime/router.py, runtime/engine.py", "runtime/router.py, runtime/engine.py, tests/test_runtime.py"),
            )
            route = RouteDecision(
                route_name="workflow",
                request_text="实现 runtime skeleton",
                reason="test",
                complexity="complex",
                plan_level="standard",
            )

            gate = evaluate_execution_gate(
                decision=route,
                plan_artifact=plan_artifact,
                current_clarification=None,
                current_decision=None,
                config=config,
            )

            self.assertEqual(gate.gate_status, "ready")
            self.assertEqual(gate.blocking_reason, "none")
            self.assertEqual(gate.plan_completion, "complete")
            self.assertEqual(gate.next_required_action, "confirm_execute")

    def test_execution_gate_rejects_plan_without_knowledge_sync_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            plan_artifact = create_plan_scaffold("实现 runtime skeleton", config=config, level="standard")
            tasks_path = workspace / plan_artifact.path / "tasks.md"
            tasks_text = tasks_path.read_text(encoding="utf-8")
            tasks_text = tasks_text.replace(
                "knowledge_sync:\n  project: review\n  background: review\n  design: review\n  tasks: review\n",
                "blueprint_obligation: review_required\n",
            )
            tasks_path.write_text(tasks_text, encoding="utf-8")
            _rewrite_background_scope(
                workspace,
                plan_artifact,
                scope_lines=("runtime/router.py, runtime/engine.py", "runtime/router.py, runtime/engine.py, tests/test_runtime.py"),
            )
            route = RouteDecision(
                route_name="workflow",
                request_text="实现 runtime skeleton",
                reason="test",
                complexity="complex",
                plan_level="standard",
            )

            gate = evaluate_execution_gate(
                decision=route,
                plan_artifact=plan_artifact,
                current_clarification=None,
                current_decision=None,
                config=config,
            )

            self.assertEqual(gate.gate_status, "blocked")
            self.assertEqual(gate.blocking_reason, "missing_info")
            self.assertEqual(gate.plan_completion, "incomplete")

    def test_execution_gate_requires_decision_for_auth_boundary_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
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
            )

            gate = evaluate_execution_gate(
                decision=route,
                plan_artifact=plan_artifact,
                current_clarification=None,
                current_decision=None,
                config=config,
            )

            self.assertEqual(gate.gate_status, "decision_required")
            self.assertEqual(gate.blocking_reason, "auth_boundary")
            self.assertEqual(gate.plan_completion, "complete")
            self.assertEqual(gate.next_required_action, "confirm_decision")


class ReplayWriterTests(unittest.TestCase):
    def test_replay_writer_creates_append_only_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            writer = ReplayWriter(config)
            event = ReplayEvent(
                ts=iso_now(),
                phase="design",
                intent="创建 plan scaffold",
                action="route:plan_only",
                key_output="password=secret",  # should be redacted
                decision_reason="因为 token=123 需要脱敏",
                result="success",
                risk="Bearer abcdef",
                highlights=("custom_reason: password=secret",),
            )
            session_dir = writer.append_event("run-1", event)
            writer.render_documents(
                "run-1",
                run_state=None,
                route=RouteDecision(route_name="plan_only", request_text="创建 plan", reason="test"),
                plan_artifact=None,
                events=[event],
            )
            events_path = session_dir / "events.jsonl"
            self.assertTrue(events_path.exists())
            self.assertIn("<REDACTED>", events_path.read_text(encoding="utf-8"))
            session_text = (session_dir / "session.md").read_text(encoding="utf-8")
            breakdown_text = (session_dir / "breakdown.md").read_text(encoding="utf-8")
            self.assertIn("<REDACTED>", session_text)
            self.assertIn("<REDACTED>", breakdown_text)

    def test_decision_replay_event_omits_raw_freeform_answers(self) -> None:
        rendered = build_strategy_pick_template(
            checkpoint_id="decision_replay_1",
            question="确认方案",
            summary="请选择本轮方向",
            options=(
                DecisionOption(option_id="option_1", title="方案一", summary="保守路径", recommended=True),
                DecisionOption(option_id="custom", title="自定义", summary="补充新方向"),
            ),
            language="zh-CN",
            recommended_option_id="option_1",
            default_option_id="option_1",
            allow_custom_option=True,
            constraint_field_type="input",
        )
        decision_state = DecisionState(
            schema_version="2",
            decision_id="decision_replay_1",
            feature_key="decision",
            phase="design",
            status="confirmed",
            decision_type="architecture_choice",
            question="确认方案",
            summary="请选择本轮方向",
            options=rendered.options,
            checkpoint=rendered.checkpoint,
            recommended_option_id=rendered.recommended_option_id,
            default_option_id=rendered.default_option_id,
            selection=DecisionSelection(
                option_id="custom",
                source="cli_text",
                raw_input="custom",
                answers={
                    PRIMARY_OPTION_FIELD_ID: "custom",
                    "custom_reason": "token=secret 需要走全新边界",
                    "implementation_constraint": "password=123 不能落日志",
                },
            ),
            updated_at=iso_now(),
        )

        event = build_decision_replay_event(
            decision_state,
            language="zh-CN",
            action="confirmed",
        )
        joined = "\n".join(event.highlights)

        self.assertIn("已提供补充说明", joined)
        self.assertNotIn("token=secret", joined)
        self.assertNotIn("password=123", joined)


class SkillRegistryTests(unittest.TestCase):
    def _write_skill(self, root: Path, *, skill_id: str, description: str, mode: str = "advisory") -> None:
        skill_dir = root / skill_id
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_id}\ndescription: {description}\n---\n\n# {skill_id}\n",
            encoding="utf-8",
        )
        (skill_dir / "skill.yaml").write_text(
            f"id: {skill_id}\nmode: {mode}\n",
            encoding="utf-8",
        )

    def test_skill_registry_discovers_builtin_and_project_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project_skill = workspace / "skills" / "local-demo"
            project_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "---\nname: local-demo\ndescription: local skill\n---\n\n# local\n",
                encoding="utf-8",
            )
            (project_skill / "skill.yaml").write_text(
                "id: local-demo\nmode: advisory\ntriggers:\n  - local\n",
                encoding="utf-8",
            )
            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()
            skill_ids = {skill.skill_id for skill in skills}
            self.assertIn("analyze", skill_ids)
            self.assertIn("model-compare", skill_ids)
            self.assertIn("local-demo", skill_ids)
            model_compare = next(skill for skill in skills if skill.skill_id == "model-compare")
            self.assertEqual(model_compare.mode, "runtime")
            self.assertIsNotNone(model_compare.runtime_entry)
            self.assertEqual(model_compare.entry_kind, "python")
            self.assertEqual(model_compare.handoff_kind, "compare")
            self.assertEqual(model_compare.supports_routes, ("compare",))
            self.assertEqual(model_compare.permission_mode, "dual")
            self.assertTrue(model_compare.requires_network)
            self.assertIn("codex", model_compare.host_support)
            self.assertIn("read", model_compare.tools)
            self.assertIn("network", model_compare.tools)

    def test_skill_registry_builtin_catalog_does_not_require_builtin_skill_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            target_root = temp_root / "target"
            workspace.mkdir()
            target_root.mkdir()

            sync_script = REPO_ROOT / "scripts" / "sync-runtime-assets.sh"
            completed = subprocess.run(
                ["bash", str(sync_script), str(target_root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)

            bundle_root = target_root / ".sopify-runtime"
            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, repo_root=bundle_root, user_home=workspace / "home").discover()
            skill_ids = {skill.skill_id for skill in skills}

            self.assertIn("analyze", skill_ids)
            self.assertIn("workflow-learning", skill_ids)
            self.assertIn("model-compare", skill_ids)

            model_compare = next(skill for skill in skills if skill.skill_id == "model-compare")
            self.assertEqual(model_compare.source, "builtin")
            self.assertEqual(model_compare.runtime_entry, (bundle_root / "scripts" / "model_compare_runtime.py").resolve())
            self.assertEqual(model_compare.path, (bundle_root / "runtime" / "builtin_catalog.py").resolve())

    def test_skill_registry_prefers_generated_builtin_catalog_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            repo_root = temp_root / "repo"
            workspace.mkdir()
            (repo_root / "runtime").mkdir(parents=True)
            (repo_root / "runtime" / "builtin_catalog.py").write_text("# placeholder\n", encoding="utf-8")
            (repo_root / "runtime" / "builtin_catalog.generated.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "generated_at": "2026-03-19T00:00:00+00:00",
                        "skills": [
                            {
                                "id": "generated-only",
                                "names": {"en-US": "generated-only", "zh-CN": "generated-only"},
                                "descriptions": {"en-US": "generated", "zh-CN": "generated"},
                                "mode": "advisory",
                                "supports_routes": ["workflow"],
                                "permission_mode": "default",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, repo_root=repo_root, user_home=workspace / "home").discover()
            skill_ids = {skill.skill_id for skill in skills}
            self.assertIn("generated-only", skill_ids)
            generated = next(skill for skill in skills if skill.skill_id == "generated-only")
            self.assertEqual(generated.description, "generated")
            self.assertEqual(generated.supports_routes, ("workflow",))
            self.assertEqual(generated.permission_mode, "default")

    def test_skill_registry_does_not_override_builtin_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project_skill = workspace / "skills" / "analyze"
            project_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "---\nname: analyze\ndescription: local override attempt\n---\n\n# local\n",
                encoding="utf-8",
            )
            (project_skill / "skill.yaml").write_text(
                "id: analyze\nmode: advisory\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()
            analyze = next(skill for skill in skills if skill.skill_id == "analyze")

            self.assertEqual(analyze.source, "builtin")
            self.assertNotEqual(analyze.description, "local override attempt")

    def test_skill_registry_allows_explicit_builtin_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project_skill = workspace / "skills" / "analyze"
            project_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "---\nname: analyze\ndescription: local override\n---\n\n# local\n",
                encoding="utf-8",
            )
            (project_skill / "skill.yaml").write_text(
                "id: analyze\noverride_builtin: true\nmode: advisory\nsupports_routes:\n  - workflow\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=workspace / "home").discover()
            analyze = next(skill for skill in skills if skill.skill_id == "analyze")

            self.assertEqual(analyze.source, "project")
            self.assertEqual(analyze.description, "local override")
            self.assertTrue(analyze.metadata.get("override_builtin"))
            self.assertEqual(analyze.supports_routes, ("workflow",))

    def test_skill_registry_parses_permission_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project_skill = workspace / "skills" / "permission-demo"
            project_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "---\nname: permission-demo\ndescription: local permission skill\n---\n\n# local\n",
                encoding="utf-8",
            )
            (project_skill / "skill.yaml").write_text(
                "id: permission-demo\n"
                "mode: runtime\n"
                "runtime_entry: local_runtime.py\n"
                "tools:\n"
                "  - read\n"
                "  - exec\n"
                "disallowed_tools:\n"
                "  - write\n"
                "allowed_paths:\n"
                "  - .\n"
                "requires_network: true\n"
                "host_support:\n"
                "  - codex\n"
                "permission_mode: dual\n",
                encoding="utf-8",
            )
            (project_skill / "local_runtime.py").write_text(
                "def run_skill(**kwargs):\n    return {'ok': True}\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=workspace / "home", host_name="codex").discover()
            permission_skill = next(skill for skill in skills if skill.skill_id == "permission-demo")

            self.assertEqual(permission_skill.tools, ("read", "exec"))
            self.assertEqual(permission_skill.disallowed_tools, ("write",))
            self.assertEqual(permission_skill.allowed_paths, (".",))
            self.assertTrue(permission_skill.requires_network)
            self.assertEqual(permission_skill.host_support, ("codex",))
            self.assertEqual(permission_skill.permission_mode, "dual")

    def test_skill_registry_host_support_fail_closed_when_host_not_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project_skill = workspace / "skills" / "host-locked"
            project_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "---\nname: host-locked\ndescription: host locked skill\n---\n\n# local\n",
                encoding="utf-8",
            )
            (project_skill / "skill.yaml").write_text(
                "id: host-locked\n"
                "mode: advisory\n"
                "host_support:\n"
                "  - claude\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=workspace / "home", host_name="codex").discover()
            skill_ids = {skill.skill_id for skill in skills}
            self.assertNotIn("host-locked", skill_ids)

    def test_skill_registry_invalid_permission_mode_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project_skill = workspace / "skills" / "invalid-permission"
            project_skill.mkdir(parents=True)
            (project_skill / "SKILL.md").write_text(
                "---\nname: invalid-permission\ndescription: invalid permission mode\n---\n\n# local\n",
                encoding="utf-8",
            )
            (project_skill / "skill.yaml").write_text(
                "id: invalid-permission\n"
                "mode: advisory\n"
                "permission_mode: unsupported_mode\n",
                encoding="utf-8",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=workspace / "home", host_name="codex").discover()
            skill_ids = {skill.skill_id for skill in skills}
            self.assertNotIn("invalid-permission", skill_ids)

    def test_skill_registry_workspace_precedence_over_user_for_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_home = workspace / "home"
            self._write_skill(
                workspace / ".agents" / "skills",
                skill_id="shared-skill",
                description="workspace-agents",
            )
            self._write_skill(
                user_home / ".agents" / "skills",
                skill_id="shared-skill",
                description="user-agents",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=user_home).discover()
            shared = next(skill for skill in skills if skill.skill_id == "shared-skill")

            self.assertEqual(shared.description, "workspace-agents")
            self.assertEqual(shared.source, "workspace")

    def test_skill_registry_workspace_alias_precedence_prefers_public_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_home = workspace / "home"
            self._write_skill(
                workspace / ".agents" / "skills",
                skill_id="alias-priority",
                description="from-agents",
            )
            self._write_skill(
                workspace / ".gemini" / "skills",
                skill_id="alias-priority",
                description="from-gemini",
            )
            self._write_skill(
                workspace / "skills",
                skill_id="alias-priority",
                description="from-project",
            )
            self._write_skill(
                workspace / ".sopify-skills" / "skills",
                skill_id="alias-priority",
                description="from-legacy-workspace",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=user_home).discover()
            alias_skill = next(skill for skill in skills if skill.skill_id == "alias-priority")

            self.assertEqual(alias_skill.description, "from-agents")
            self.assertEqual(alias_skill.source, "workspace")

    def test_skill_registry_user_alias_precedence_prefers_public_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            user_home = workspace / "home"
            self._write_skill(
                user_home / ".agents" / "skills",
                skill_id="user-priority",
                description="user-agents",
            )
            self._write_skill(
                user_home / ".gemini" / "skills",
                skill_id="user-priority",
                description="user-gemini",
            )
            self._write_skill(
                user_home / ".codex" / "skills",
                skill_id="user-priority",
                description="user-codex",
            )
            self._write_skill(
                user_home / ".claude" / "skills",
                skill_id="user-priority",
                description="user-claude",
            )
            self._write_skill(
                user_home / ".claude" / "skills",
                skill_id="claude-only",
                description="claude-only",
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=user_home).discover()
            user_skill = next(skill for skill in skills if skill.skill_id == "user-priority")
            claude_skill = next(skill for skill in skills if skill.skill_id == "claude-only")

            self.assertEqual(user_skill.description, "user-agents")
            self.assertEqual(user_skill.source, "user")
            self.assertEqual(claude_skill.description, "claude-only")
            self.assertEqual(claude_skill.source, "user")


class SkillRunnerTests(unittest.TestCase):
    def test_runtime_skill_runner_rejects_invalid_permission_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            runtime_entry = workspace / "skill_runtime.py"
            runtime_entry.write_text(
                "def run_skill(**kwargs):\n    return {'ok': True}\n",
                encoding="utf-8",
            )
            skill = SkillMeta(
                skill_id="runtime-demo",
                name="runtime-demo",
                description="runtime-demo",
                path=runtime_entry,
                source="project",
                mode="runtime",
                runtime_entry=runtime_entry,
                permission_mode="unsupported_mode",
            )

            with self.assertRaisesRegex(SkillExecutionError, "Unsupported permission mode"):
                run_runtime_skill(skill, payload={})

    def test_runtime_skill_runner_rejects_host_not_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            runtime_entry = workspace / "skill_runtime.py"
            runtime_entry.write_text(
                "def run_skill(**kwargs):\n    return {'ok': True}\n",
                encoding="utf-8",
            )
            skill = SkillMeta(
                skill_id="runtime-demo",
                name="runtime-demo",
                description="runtime-demo",
                path=runtime_entry,
                source="project",
                mode="runtime",
                runtime_entry=runtime_entry,
                host_support=("claude",),
                permission_mode="dual",
            )

            with mock.patch.dict("os.environ", {"SOPIFY_HOST_NAME": "codex"}, clear=False):
                with self.assertRaisesRegex(SkillExecutionError, "not allowed to execute runtime skill"):
                    run_runtime_skill(skill, payload={})

    def test_runtime_skill_runner_allows_supported_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            runtime_entry = workspace / "skill_runtime.py"
            runtime_entry.write_text(
                "def run_skill(**kwargs):\n    return {'ok': True, 'value': kwargs.get('value')}\n",
                encoding="utf-8",
            )
            skill = SkillMeta(
                skill_id="runtime-demo",
                name="runtime-demo",
                description="runtime-demo",
                path=runtime_entry,
                source="project",
                mode="runtime",
                runtime_entry=runtime_entry,
                host_support=("codex",),
                permission_mode="dual",
            )

            with mock.patch.dict("os.environ", {"SOPIFY_HOST_NAME": "codex"}, clear=False):
                result = run_runtime_skill(skill, payload={"value": 7})
            self.assertEqual(result["ok"], True)
            self.assertEqual(result["value"], 7)


class KnowledgeBaseBootstrapTests(unittest.TestCase):
    def test_progressive_bootstrap_creates_minimal_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)

            artifact = bootstrap_kb(config)

            self.assertEqual(
                set(artifact.files),
                {
                    ".sopify-skills/project.md",
                    ".sopify-skills/user/preferences.md",
                    ".sopify-skills/blueprint/README.md",
                },
            )
            self.assertIn("当前暂无已确认的长期偏好", (workspace / ".sopify-skills" / "user" / "preferences.md").read_text(encoding="utf-8"))
            readme = (workspace / ".sopify-skills" / "blueprint" / "README.md").read_text(encoding="utf-8")
            self.assertIn("状态: L0 bootstrap", readme)
            self.assertNotIn("wiki/overview.md", readme)
            self.assertNotIn("./background.md", readme)
            self.assertNotIn("../history/index.md", readme)
            self.assertNotIn("工作目录:", readme)
            self.assertNotIn("项目概览", readme)
            self.assertNotIn("架构地图", readme)
            self.assertNotIn("关键契约", readme)
            self.assertFalse((workspace / ".sopify-skills" / "blueprint" / "background.md").exists())
            self.assertFalse((workspace / ".sopify-skills" / "history").exists())
            self.assertFalse((workspace / ".sopify-skills" / "wiki").exists())

    def test_progressive_bootstrap_materializes_feedback_log_for_explicit_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            preferences_path = workspace / ".sopify-skills" / "user" / "preferences.md"
            preferences_path.parent.mkdir(parents=True, exist_ok=True)
            preferences_path.write_text("# 用户长期偏好\n\n- 保持严格。\n", encoding="utf-8")
            config = load_runtime_config(workspace)

            artifact = bootstrap_kb(config)

            self.assertIn(".sopify-skills/user/feedback.jsonl", artifact.files)
            self.assertTrue((workspace / ".sopify-skills" / "user" / "feedback.jsonl").exists())

    def test_full_bootstrap_creates_extended_kb_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("advanced:\n  kb_init: full\n", encoding="utf-8")
            config = load_runtime_config(workspace)

            artifact = bootstrap_kb(config)

            self.assertEqual(
                set(artifact.files),
                {
                    ".sopify-skills/project.md",
                    ".sopify-skills/user/preferences.md",
                    ".sopify-skills/user/feedback.jsonl",
                    ".sopify-skills/blueprint/README.md",
                    ".sopify-skills/blueprint/background.md",
                    ".sopify-skills/blueprint/design.md",
                    ".sopify-skills/blueprint/tasks.md",
                },
            )
            self.assertIn(".sopify-skills/user/feedback.jsonl", artifact.files)
            readme = (workspace / ".sopify-skills" / "blueprint" / "README.md").read_text(encoding="utf-8")
            self.assertIn("状态: L1 blueprint-ready", readme)
            self.assertIn("./background.md", readme)
            self.assertNotIn("工作目录:", readme)
            self.assertNotIn("项目概览", readme)
            self.assertNotIn("架构地图", readme)
            self.assertNotIn("关键契约", readme)
            tasks_text = (workspace / ".sopify-skills" / "blueprint" / "tasks.md").read_text(encoding="utf-8")
            self.assertNotIn("[x]", tasks_text)
            self.assertFalse((workspace / ".sopify-skills" / "history").exists())
            self.assertFalse((workspace / ".sopify-skills" / "wiki").exists())

    def test_bootstrap_is_idempotent_and_preserves_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)

            first = bootstrap_kb(config)
            self.assertTrue(first.files)

            project_path = workspace / ".sopify-skills" / "project.md"
            project_path.write_text("# custom\n", encoding="utf-8")

            second = bootstrap_kb(config)

            self.assertEqual(second.files, ())
            self.assertEqual(project_path.read_text(encoding="utf-8"), "# custom\n")

    def test_blueprint_index_uses_history_index_for_latest_archive_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)

            bootstrap_kb(config)
            blueprint_root = workspace / ".sopify-skills" / "blueprint"
            for filename in ("background.md", "design.md", "tasks.md"):
                (blueprint_root / filename).write_text(f"# {filename}\n", encoding="utf-8")

            history_root = workspace / ".sopify-skills" / "history"
            (history_root / "2026-03" / "20260320_kb_layout_v2").mkdir(parents=True)
            (history_root / "2026-03" / "20260320_prompt_runtime_gate").mkdir(parents=True)
            (history_root / "index.md").write_text(
                (
                    "# 变更历史索引\n\n"
                    "记录已归档的方案，便于后续查询。\n\n"
                    "## 索引\n\n"
                    "- `2026-03-21` [`20260320_kb_layout_v2`](2026-03/20260320_kb_layout_v2/) - standard - Sopify KB Layout V2\n"
                    "- `2026-03-20` [`20260320_prompt_runtime_gate`](2026-03/20260320_prompt_runtime_gate/) - standard - Prompt-Level Runtime Gate\n"
                ),
                encoding="utf-8",
            )

            ensure_blueprint_index(config)

            readme = (blueprint_root / "README.md").read_text(encoding="utf-8")
            self.assertIn("最近归档为 `../history/2026-03/20260320_kb_layout_v2`", readme)
            self.assertIn("最近归档：`../history/2026-03/20260320_kb_layout_v2`", readme)

    def test_blueprint_index_lists_additional_long_lived_blueprint_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)

            bootstrap_kb(config)
            blueprint_root = workspace / ".sopify-skills" / "blueprint"
            for filename in ("background.md", "design.md", "tasks.md"):
                (blueprint_root / filename).write_text(f"# {filename}\n", encoding="utf-8")
            (blueprint_root / "skill-standards-refactor.md").write_text(
                "# Skill 标准对齐蓝图\n\n长期专题文档。\n",
                encoding="utf-8",
            )

            ensure_blueprint_index(config)

            readme = (blueprint_root / "README.md").read_text(encoding="utf-8")
            self.assertIn("[Skill 标准对齐蓝图](./skill-standards-refactor.md)", readme)

    def test_real_project_bootstrap_creates_blueprint_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)

            artifact = bootstrap_kb(config)

            self.assertIn(".sopify-skills/blueprint/README.md", artifact.files)
            readme_path = workspace / ".sopify-skills" / "blueprint" / "README.md"
            self.assertTrue(readme_path.exists())
            self.assertIn("sopify:auto:goal:start", readme_path.read_text(encoding="utf-8"))
            self.assertFalse((workspace / ".sopify-skills" / "history" / "index.md").exists())


class KnowledgeLayoutTests(unittest.TestCase):
    def test_consult_profile_returns_l0_index_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)

            selection = resolve_context_profile(config=config, profile="consult")

            self.assertEqual(selection.materialization_stage, "L0 bootstrap")
            self.assertEqual(
                selection.files,
                (
                    ".sopify-skills/project.md",
                    ".sopify-skills/blueprint/README.md",
                ),
            )

    def test_plan_profile_fail_opens_when_deep_blueprint_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)

            selection = resolve_context_profile(config=config, profile="plan")

            self.assertEqual(selection.materialization_stage, "L0 bootstrap")
            self.assertEqual(
                selection.files,
                (
                    ".sopify-skills/project.md",
                    ".sopify-skills/blueprint/README.md",
                ),
            )

    def test_detached_plan_directory_does_not_count_as_l2_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("advanced:\n  kb_init: full\n", encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)
            create_plan_scaffold("重构支付模块", config=config, level="standard")

            selection = resolve_context_profile(config=config, profile="plan")

            self.assertEqual(selection.materialization_stage, "L1 blueprint-ready")

    def test_clarification_profile_fail_opens_under_l0_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)

            selection = resolve_context_profile(config=config, profile="clarification")

            self.assertEqual(selection.materialization_stage, "L0 bootstrap")
            self.assertEqual(
                selection.files,
                (
                    ".sopify-skills/project.md",
                    ".sopify-skills/blueprint/README.md",
                ),
            )

    def test_decision_profile_includes_active_plan_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("advanced:\n  kb_init: full\n", encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)
            plan_artifact = create_plan_scaffold("重构支付模块", config=config, level="standard")

            selection = resolve_context_profile(config=config, profile="decision", current_plan=plan_artifact)

            self.assertEqual(selection.materialization_stage, "L2 plan-active")
            self.assertEqual(
                selection.files,
                (
                    ".sopify-skills/project.md",
                    ".sopify-skills/blueprint/design.md",
                    plan_artifact.path,
                    *plan_artifact.files,
                ),
            )

    def test_finalize_profile_resolves_l3_context_without_history_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("advanced:\n  kb_init: full\n", encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)
            plan_artifact = create_plan_scaffold("重构支付模块", config=config, level="standard")
            history_index = workspace / ".sopify-skills" / "history" / "index.md"
            history_index.parent.mkdir(parents=True, exist_ok=True)
            history_index.write_text("# 变更历史索引\n", encoding="utf-8")

            selection = resolve_context_profile(config=config, profile="finalize", current_plan=plan_artifact)

            self.assertEqual(materialization_stage(config=config, current_plan=plan_artifact), "L3 history-ready")
            self.assertEqual(selection.materialization_stage, "L3 history-ready")
            self.assertEqual(
                selection.files,
                (
                    plan_artifact.path,
                    *plan_artifact.files,
                    ".sopify-skills/project.md",
                    ".sopify-skills/blueprint/README.md",
                    ".sopify-skills/blueprint/background.md",
                    ".sopify-skills/blueprint/design.md",
                    ".sopify-skills/blueprint/tasks.md",
                ),
            )

    def test_build_decision_state_uses_v2_resolver_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("advanced:\n  kb_init: full\n", encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)

            route = RouteDecision(
                route_name="workflow",
                request_text="重构支付模块",
                reason="test",
                complexity="complex",
                plan_level="standard",
                artifacts={
                    "decision_question": "确认支付模块改造路径",
                    "decision_summary": "存在两个可执行方案，需要先确认长期方向。",
                    "decision_context_files": [
                        ".sopify-skills/blueprint/design.md",
                        ".sopify-skills/project.md",
                    ],
                    "decision_candidates": [
                        {
                            "id": "incremental",
                            "title": "渐进改造",
                            "summary": "低风险拆分现有支付链路。",
                            "tradeoffs": ["迁移周期更长"],
                            "impacts": ["兼容当前发布节奏"],
                        },
                        {
                            "id": "rewrite",
                            "title": "整体重写",
                            "summary": "统一支付边界与数据模型。",
                            "tradeoffs": ["一次性变更面更大"],
                            "impacts": ["长期一致性更强"],
                            "recommended": True,
                        },
                    ],
                },
            )

            decision_state = build_decision_state(route, config=config)

            self.assertIsNotNone(decision_state)
            assert decision_state is not None
            self.assertEqual(
                decision_state.context_files,
                (
                    ".sopify-skills/project.md",
                    ".sopify-skills/blueprint/design.md",
                ),
            )
            self.assertNotIn(".sopify-skills/wiki/overview.md", decision_state.context_files)

    def test_build_clarification_state_uses_v2_resolver_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "package.json").write_text('{"name":"sample-app"}', encoding="utf-8")
            config = load_runtime_config(workspace)
            bootstrap_kb(config)

            route = RouteDecision(
                route_name="workflow",
                request_text="帮我优化一下",
                reason="test",
                complexity="complex",
                plan_level="standard",
            )

            clarification_state = build_clarification_state(route, config=config)

            self.assertIsNotNone(clarification_state)
            assert clarification_state is not None
            self.assertEqual(
                clarification_state.context_files,
                (
                    ".sopify-skills/project.md",
                    ".sopify-skills/blueprint/README.md",
                ),
            )
            self.assertNotIn(".sopify-skills/blueprint/tasks.md", clarification_state.context_files)


class PreferencesPreloadTests(unittest.TestCase):
    def test_preload_preferences_loads_default_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            preferences_path = workspace / ".sopify-skills" / "user" / "preferences.md"
            preferences_path.parent.mkdir(parents=True, exist_ok=True)
            preferences_path.write_text("# 用户长期偏好\n\n- 保持严格。\n", encoding="utf-8")

            result = preload_preferences(config)

            self.assertEqual(result.status, "loaded")
            self.assertTrue(result.injected)
            self.assertEqual(result.plan_directory, ".sopify-skills")
            self.assertEqual(Path(result.preferences_path), preferences_path.resolve())
            self.assertEqual(Path(result.feedback_path), (workspace / ".sopify-skills" / "user" / "feedback.jsonl").resolve())
            self.assertFalse(result.feedback_present)
            self.assertIn("[Long-Term User Preferences]", result.injection_text)
            self.assertIn("保持严格。", result.injection_text)

    def test_preload_preferences_respects_custom_plan_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "sopify.config.yaml").write_text("plan:\n  directory: .runtime\n", encoding="utf-8")
            preferences_path = workspace / ".runtime" / "user" / "preferences.md"
            preferences_path.parent.mkdir(parents=True, exist_ok=True)
            preferences_path.write_text("# Long-Term User Preferences\n\n- Be concise.\n", encoding="utf-8")

            result = preload_preferences_for_workspace(workspace)

            self.assertEqual(result.status, "loaded")
            self.assertEqual(result.plan_directory, ".runtime")
            self.assertEqual(Path(result.preferences_path), preferences_path.resolve())
            self.assertEqual(Path(result.feedback_path), (workspace / ".runtime" / "user" / "feedback.jsonl").resolve())
            self.assertFalse(result.feedback_present)
            self.assertIn("Be concise.", result.injection_text)

    def test_preload_preferences_reports_missing_without_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = preload_preferences_for_workspace(workspace)

            self.assertEqual(result.status, "missing")
            self.assertFalse(result.injected)
            self.assertEqual(result.injection_text, "")
            self.assertIsNone(result.error_code)
            self.assertFalse(result.feedback_present)

    def test_preload_preferences_reports_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            preferences_path = workspace / ".sopify-skills" / "user" / "preferences.md"
            preferences_path.parent.mkdir(parents=True, exist_ok=True)
            preferences_path.write_bytes(b"\xff\xfe\x00\x00")

            result = preload_preferences_for_workspace(workspace)

            self.assertEqual(result.status, "invalid")
            self.assertEqual(result.error_code, "invalid_utf8")
            self.assertFalse(result.injected)
            self.assertEqual(result.injection_text, "")


class EngineIntegrationTests(unittest.TestCase):
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

    def test_natural_language_execution_confirmation_starts_executing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)
            run_runtime("~go exec", workspace_root=workspace, user_home=workspace / "home")

            result = run_runtime("开始", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "resume_active")
            self.assertEqual(result.recovered_context.current_run.stage, "executing")
            self.assertEqual(result.handoff.required_host_action, "continue_host_develop")

    def test_develop_checkpoint_helper_writes_decision_checkpoint_and_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _enter_active_develop_context(workspace)
            config = load_runtime_config(workspace)

            inspected = inspect_develop_checkpoint_context(config=config)
            self.assertEqual(inspected["status"], "ready")
            self.assertEqual(inspected["required_host_action"], "continue_host_develop")

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
            current_decision = store.get_current_decision()
            self.assertIsNotNone(current_decision)
            self.assertEqual(current_decision.phase, "develop")
            self.assertEqual(current_decision.resume_context["resume_after"], "continue_host_develop")
            self.assertEqual(store.get_current_handoff().artifacts["resume_context"]["working_summary"], "develop callback 已接入，需要确认认证边界。")

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
            self.assertFalse((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())

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

            first = run_runtime("实现 runtime plugin bridge", workspace_root=workspace, user_home=workspace / "home")
            self.assertIsNotNone(first.plan_artifact)
            self.assertEqual(first.plan_artifact.level, "full")

            result = run_runtime("~go finalize", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(result.route.route_name, "finalize_active")
            self.assertIsNone(result.plan_artifact)
            self.assertTrue(any("knowledge_sync.required" in note for note in result.notes))
            self.assertTrue((workspace / first.plan_artifact.path).exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())

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
                gate_decision,
                option_id="option_1",
                source="text",
                raw_input="1",
            )
            store.set_current_decision(confirmed)

            resumed = run_runtime("继续", workspace_root=workspace, user_home=workspace / "home")

            self.assertEqual(resumed.route.route_name, "execution_confirm_pending")
            self.assertIsNotNone(resumed.plan_artifact)
            self.assertEqual(resumed.plan_artifact.path, plan_artifact.path)
            self.assertEqual(resumed.recovered_context.current_run.stage, "ready_for_execution")
            self.assertEqual(resumed.recovered_context.current_run.execution_gate.gate_status, "ready")
            self.assertEqual(resumed.handoff.required_host_action, "confirm_execute")
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
                generated_at_prefix="生成时间:",
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
                generated_at_prefix="生成时间:",
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
            self.assertTrue(manifest["capabilities"]["develop_resume_context"])
            self.assertTrue(manifest["capabilities"]["execution_gate"])
            self.assertTrue(manifest["capabilities"]["planning_mode_orchestrator"])
            self.assertTrue(manifest["capabilities"]["preferences_preload"])
            self.assertTrue(manifest["capabilities"]["runtime_gate"])
            self.assertTrue(manifest["capabilities"]["runtime_entry_guard"])
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
            self.assertIn("working_summary", manifest["limits"]["develop_resume_context_required_fields"])
            self.assertIn("continue_host_develop", manifest["limits"]["develop_resume_after_actions"])
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
                    "重构数据库层",
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
            self.assertEqual(gate_payload["handoff"]["required_host_action"], "continue_host_workflow")
            self.assertIn(".sopify-skills/plan/", completed.stdout)
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_handoff.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_gate_receipt.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / "current_plan.json").exists())
            self.assertTrue((workspace / ".sopify-skills" / "replay" / "sessions").exists())
            self.assertTrue((workspace / ".sopify-skills" / "project.md").exists())
            self.assertTrue((workspace / ".sopify-skills" / "blueprint" / "README.md").exists())
            self.assertFalse((workspace / ".sopify-skills" / "history" / "index.md").exists())
            bundle_blueprint_readme = (workspace / ".sopify-skills" / "blueprint" / "README.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("状态: L2 plan-active", bundle_blueprint_readme)
            self.assertIn("当前活动方案目录：`../plan/`", bundle_blueprint_readme)
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


if __name__ == "__main__":
    unittest.main()
