from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.config import load_runtime_config
from runtime.entry_guard import DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE
from runtime.execution_gate import evaluate_execution_gate
from runtime.gate import (
    CHECKPOINT_ONLY,
    CURRENT_GATE_RECEIPT_FILENAME,
    ERROR_VISIBLE_RETRY,
    NORMAL_RUNTIME_FOLLOWUP,
    enter_runtime_gate,
)
from runtime.models import PlanArtifact, RouteDecision, RunState
from runtime.plan_scaffold import create_plan_scaffold
from runtime.state import StateStore, iso_now


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
    request_text: str = "补 runtime gate 骨架",
) -> PlanArtifact:
    config = load_runtime_config(workspace)
    store = StateStore(config)
    store.ensure()
    plan_artifact = create_plan_scaffold(request_text, config=config, level="standard")
    _rewrite_background_scope(
        workspace,
        plan_artifact,
        scope_lines=("runtime/gate.py, scripts/runtime_gate.py", "runtime/gate.py, scripts/runtime_gate.py, tests/test_runtime_gate.py"),
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
    return plan_artifact


class RuntimeGateTests(unittest.TestCase):
    def test_gate_returns_normal_runtime_followup_for_plan_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["gate_passed"])
            self.assertEqual(result["allowed_response_mode"], NORMAL_RUNTIME_FOLLOWUP)
            self.assertEqual(result["handoff"]["required_host_action"], "review_or_execute_plan")
            self.assertTrue(result["evidence"]["handoff_found"])
            self.assertTrue(result["evidence"]["strict_runtime_entry"])
            self.assertEqual(result["evidence"]["handoff_source_kind"], "current_request_persisted")
            self.assertTrue(result["evidence"]["current_request_produced_handoff"])
            self.assertTrue(result["evidence"]["persisted_handoff_matches_current_request"])
            self.assertIn("补 runtime gate 骨架", result["observability"]["request_excerpt"])
            self.assertTrue((workspace / ".sopify-skills" / "state" / CURRENT_GATE_RECEIPT_FILENAME).exists())

    def test_gate_maps_clarification_pending_to_checkpoint_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "优化一下",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["runtime"]["route_name"], "clarification_pending")
            self.assertEqual(result["handoff"]["required_host_action"], "answer_questions")
            self.assertEqual(result["allowed_response_mode"], CHECKPOINT_ONLY)
            self.assertTrue(result["handoff"]["pending_fail_closed"])

    def test_gate_maps_decision_pending_to_checkpoint_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "~go plan payload 放 host root 还是 workspace/.sopify-runtime",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["runtime"]["route_name"], "decision_pending")
            self.assertEqual(result["handoff"]["required_host_action"], "confirm_decision")
            self.assertEqual(result["handoff"]["entry_guard_reason_code"], "entry_guard_decision_pending")
            self.assertEqual(result["allowed_response_mode"], CHECKPOINT_ONLY)

    def test_gate_maps_execution_confirm_pending_to_checkpoint_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            _prepare_ready_plan_state(workspace)

            result = enter_runtime_gate(
                "~go exec",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["runtime"]["route_name"], "execution_confirm_pending")
            self.assertEqual(result["handoff"]["required_host_action"], "confirm_execute")
            self.assertEqual(result["handoff"]["entry_guard_reason_code"], "entry_guard_execution_confirm_pending")
            self.assertEqual(result["allowed_response_mode"], CHECKPOINT_ONLY)

    def test_gate_returns_ready_for_finalize_completion_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            active_plan = _prepare_ready_plan_state(workspace)

            result = enter_runtime_gate(
                "~go finalize",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["gate_passed"])
            self.assertEqual(result["runtime"]["route_name"], "finalize_active")
            self.assertEqual(result["allowed_response_mode"], NORMAL_RUNTIME_FOLLOWUP)
            self.assertEqual(result["handoff"]["required_host_action"], "finalize_completed")
            self.assertTrue(result["evidence"]["handoff_found"])
            self.assertEqual(result["evidence"]["handoff_source_kind"], "current_request_persisted")
            self.assertTrue(result["evidence"]["persisted_handoff_matches_current_request"])

            config = load_runtime_config(workspace)
            store = StateStore(config)
            self.assertIsNone(store.get_current_plan())
            self.assertIsNone(store.get_current_run())
            persisted_handoff = store.get_current_handoff()
            self.assertIsNotNone(persisted_handoff)
            self.assertEqual(persisted_handoff.required_host_action, "finalize_completed")
            self.assertTrue(persisted_handoff.artifacts["archived_plan_path"].endswith(f"/{active_plan.plan_id}"))
            self.assertEqual(persisted_handoff.artifacts["history_index_path"], ".sopify-skills/history/index.md")
            self.assertTrue(persisted_handoff.artifacts["state_cleared"])
            self.assertIn(".sopify-skills/history/index.md", persisted_handoff.artifacts["kb_files"])
            archived_plan_dir = workspace / persisted_handoff.artifacts["archived_plan_path"]
            self.assertTrue(archived_plan_dir.exists())
            self.assertTrue((workspace / ".sopify-skills" / "history" / "index.md").exists())

    def test_gate_returns_structured_blocked_handoff_for_finalize_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            first = enter_runtime_gate(
                "实现 runtime plugin bridge",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(first["status"], "ready")

            result = enter_runtime_gate(
                "~go finalize",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["gate_passed"])
            self.assertEqual(result["runtime"]["route_name"], "finalize_active")
            self.assertEqual(result["handoff"]["required_host_action"], "review_or_execute_plan")
            self.assertTrue(result["evidence"]["handoff_found"])

            config = load_runtime_config(workspace)
            store = StateStore(config)
            self.assertIsNotNone(store.get_current_plan())
            persisted_handoff = store.get_current_handoff()
            self.assertIsNotNone(persisted_handoff)
            self.assertEqual(persisted_handoff.required_host_action, "review_or_execute_plan")
            self.assertEqual(persisted_handoff.artifacts["finalize_status"], "blocked")
            self.assertEqual(persisted_handoff.artifacts["active_plan_path"], store.get_current_plan().path)
            self.assertFalse(persisted_handoff.artifacts["state_cleared"])

    def test_gate_surfaces_trigger_evidence_for_protected_plan_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "分析下 .sopify-skills/plan/20260320_kb_layout_v2/tasks.md 的当前任务，并整理 README 职责表边界",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["runtime"]["route_name"], "workflow")
            self.assertEqual(
                result["trigger_evidence"]["entry_guard_reason_code"],
                DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
            )
            self.assertEqual(result["trigger_evidence"]["direct_edit_guard_kind"], "protected_plan_asset")
            self.assertIn(
                "protected .sopify-skills/plan assets",
                result["trigger_evidence"]["direct_edit_guard_trigger"],
            )

    def test_gate_marks_reused_prior_handoff_observability(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            first = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(first["status"], "ready")

            result = enter_runtime_gate(
                "~summary",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["runtime"]["route_name"], "summary")
            self.assertEqual(result["evidence"]["handoff_source_kind"], "reused_prior_state")
            self.assertFalse(result["evidence"]["current_request_produced_handoff"])
            self.assertFalse(result["evidence"]["persisted_handoff_matches_current_request"])
            self.assertEqual(result["observability"]["runtime_route_name"], "summary")
            self.assertIn("补 runtime gate 骨架", result["observability"]["persisted_handoff"]["request_excerpt"])

    def test_gate_fail_closes_when_handoff_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "~go exec",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "error")
            self.assertFalse(result["gate_passed"])
            self.assertEqual(result["allowed_response_mode"], ERROR_VISIBLE_RETRY)
            self.assertEqual(result["error_code"], "handoff_missing")
            self.assertFalse(result["evidence"]["handoff_found"])

    def test_runtime_gate_cli_prints_compact_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            script_path = REPO_ROOT / "scripts" / "runtime_gate.py"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "enter",
                    "--workspace-root",
                    str(workspace),
                    "--request",
                    "~go plan 补 runtime gate 骨架",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = __import__("json").loads(completed.stdout)
            self.assertEqual(payload["status"], "ready")
            self.assertEqual(payload["allowed_response_mode"], NORMAL_RUNTIME_FOLLOWUP)
            self.assertIn("handoff", payload)

    def test_prompt_runtime_gate_smoke_script_passes(self) -> None:
        script_path = REPO_ROOT / "scripts" / "check-prompt-runtime-gate-smoke.py"

        completed = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = __import__("json").loads(completed.stdout)
        self.assertTrue(payload["passed"])
        scenario_ids = {item["id"] for item in payload["scenarios"]}
        self.assertIn("normal_runtime_followup", scenario_ids)
        self.assertIn("protected_plan_asset_runtime_first", scenario_ids)
        self.assertIn("clarification_checkpoint_only", scenario_ids)
        self.assertIn("decision_checkpoint_only", scenario_ids)
        self.assertIn("execution_confirm_checkpoint_only", scenario_ids)
        self.assertIn("fail_closed_missing_handoff", scenario_ids)


if __name__ == "__main__":
    unittest.main()
