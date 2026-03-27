from __future__ import annotations

import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.config import load_runtime_config
from runtime.entry_guard import DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE, build_entry_guard_contract
from runtime.execution_gate import evaluate_execution_gate
from runtime.gate import (
    CHECKPOINT_ONLY,
    CURRENT_GATE_RECEIPT_FILENAME,
    ERROR_VISIBLE_RETRY,
    NORMAL_RUNTIME_FOLLOWUP,
    enter_runtime_gate,
)
from runtime.models import PlanArtifact, RouteDecision, RunState, RuntimeHandoff
from runtime.plan_scaffold import create_plan_scaffold
from runtime.state import StateStore, iso_now, stable_request_sha1


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
    session_id: str | None = None,
) -> PlanArtifact:
    config = load_runtime_config(workspace)
    store = StateStore(config, session_id=session_id)
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


def _make_runtime_handoff(
    *,
    run_id: str = "run-test",
    route_name: str = "workflow",
    required_host_action: str = "continue_host_workflow",
    strict_runtime_entry: bool = True,
) -> RuntimeHandoff:
    entry_guard = build_entry_guard_contract(required_host_action=required_host_action)
    if not strict_runtime_entry:
        entry_guard = dict(entry_guard)
        entry_guard["strict_runtime_entry"] = False
    return RuntimeHandoff(
        schema_version="1",
        route_name=route_name,
        run_id=run_id,
        handoff_kind="workflow",
        required_host_action=required_host_action,
        artifacts={"entry_guard": entry_guard},
        observability={
            "generated_at": iso_now(),
            "request_excerpt": "test request",
            "request_sha1": stable_request_sha1("test request"),
        },
    )


def _make_runtime_result(*, request_text: str, route_name: str, handoff: object | None) -> SimpleNamespace:
    return SimpleNamespace(
        route=RouteDecision(
            route_name=route_name,
            request_text=request_text,
            reason="test",
            complexity="simple",
        ),
        handoff=handoff,
    )


def _write_gate_receipt_fixture(
    workspace: Path,
    *,
    request_text: str,
    route_name: str,
    raw_payload: dict[str, object] | None = None,
) -> None:
    receipt_path = workspace / ".sopify-skills" / "state" / CURRENT_GATE_RECEIPT_FILENAME
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    payload = raw_payload or {
        "observability": {
            "written_at": iso_now(),
            "request_sha1": stable_request_sha1(request_text),
            "runtime_route_name": route_name,
        }
    }
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
            self.assertEqual(
                result["observability"]["previous_receipt"],
                {
                    "exists": False,
                    "written_at": None,
                    "request_sha1_match": None,
                    "route_name_match": None,
                    "stale_reason": None,
                },
            )
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

    def test_gate_surfaces_consult_explain_only_override_reason_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "解释 runtime gate 为什么这么判，不要改",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["runtime"]["route_name"], "consult")
            self.assertEqual(result["allowed_response_mode"], NORMAL_RUNTIME_FOLLOWUP)
            self.assertEqual(result["handoff"]["required_host_action"], "continue_host_consult")
            self.assertEqual(result["handoff"]["consult_override_reason_code"], "consult_explain_only_override")
            self.assertEqual(result["trigger_evidence"]["consult_override_reason_code"], "consult_explain_only_override")

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

            proposal = enter_runtime_gate(
                "实现 runtime plugin bridge",
                workspace_root=workspace,
                user_home=workspace / "home",
            )
            self.assertEqual(proposal["status"], "ready")
            self.assertEqual(proposal["handoff"]["required_host_action"], "confirm_plan_package")
            session_id = proposal["session_id"]

            first = enter_runtime_gate(
                "继续",
                workspace_root=workspace,
                session_id=session_id,
                user_home=workspace / "home",
            )
            self.assertEqual(first["status"], "ready")
            self.assertEqual(first["handoff"]["required_host_action"], "review_or_execute_plan")

            result = enter_runtime_gate(
                "~go finalize",
                workspace_root=workspace,
                session_id=session_id,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["gate_passed"])
            self.assertEqual(result["runtime"]["route_name"], "finalize_active")
            self.assertEqual(result["handoff"]["required_host_action"], "review_or_execute_plan")
            self.assertTrue(result["evidence"]["handoff_found"])

            config = load_runtime_config(workspace)
            review_store = StateStore(config, session_id=session_id)
            store = StateStore(config)
            self.assertIsNotNone(review_store.get_current_plan())
            self.assertIsNone(store.get_current_plan())
            persisted_handoff = store.get_current_handoff()
            self.assertIsNotNone(persisted_handoff)
            self.assertEqual(persisted_handoff.required_host_action, "review_or_execute_plan")
            self.assertEqual(persisted_handoff.artifacts["finalize_status"], "blocked")
            self.assertEqual(persisted_handoff.artifacts["active_plan_path"], review_store.get_current_plan().path)
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
            self.assertEqual(result["runtime"]["route_name"], "plan_proposal_pending")
            self.assertEqual(result["handoff"]["required_host_action"], "confirm_plan_package")
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
            session_id = first["session_id"]

            result = enter_runtime_gate(
                "~summary",
                workspace_root=workspace,
                session_id=session_id,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["runtime"]["route_name"], "summary")
            self.assertEqual(result["evidence"]["handoff_source_kind"], "reused_prior_state")
            self.assertFalse(result["evidence"]["current_request_produced_handoff"])
            self.assertFalse(result["evidence"]["persisted_handoff_matches_current_request"])
            self.assertEqual(result["observability"]["runtime_route_name"], "summary")
            self.assertIn("补 runtime gate 骨架", result["observability"]["persisted_handoff"]["request_excerpt"])

    def test_gate_reports_previous_receipt_diagnostics(self) -> None:
        scenarios = (
            ("request_sha1_mismatch", "旧请求", "clarification_pending", False, True),
            ("route_name_mismatch", "优化一下", "workflow", True, False),
            ("both_mismatch", "旧请求", "workflow", False, False),
        )
        for stale_reason, previous_request, previous_route, request_match, route_match in scenarios:
            with self.subTest(stale_reason=stale_reason):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)
                    _write_gate_receipt_fixture(
                        workspace,
                        request_text=previous_request,
                        route_name=previous_route,
                    )

                    result = enter_runtime_gate(
                        "优化一下",
                        workspace_root=workspace,
                        user_home=workspace / "home",
                    )

                    previous_receipt = result["observability"]["previous_receipt"]
                    self.assertTrue(previous_receipt["exists"])
                    self.assertEqual(previous_receipt["request_sha1_match"], request_match)
                    self.assertEqual(previous_receipt["route_name_match"], route_match)
                    self.assertEqual(previous_receipt["stale_reason"], stale_reason)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            receipt_path = workspace / ".sopify-skills" / "state" / CURRENT_GATE_RECEIPT_FILENAME
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text("{not-json", encoding="utf-8")

            result = enter_runtime_gate(
                "优化一下",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(
                result["observability"]["previous_receipt"],
                {
                    "exists": True,
                    "written_at": None,
                    "request_sha1_match": None,
                    "route_name_match": None,
                    "stale_reason": "parse_error",
                },
            )

    def test_gate_generates_session_id_and_session_scoped_state_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertRegex(result["session_id"], r"^session-[0-9a-f]{12}$")
            self.assertEqual(result["state"]["scope"], "session")
            self.assertIn(result["session_id"], result["state"]["state_root"])
            self.assertIn(result["session_id"], result["state"]["current_plan_path"])

    def test_gate_rejects_invalid_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                session_id="../escape",
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "error")
            self.assertFalse(result["gate_passed"])
            self.assertEqual(result["error_code"], "invalid_request")

    def test_gate_cleans_expired_session_dirs_on_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            stale_store = StateStore(config, session_id="stale-session")
            stale_store.ensure()
            stale_store.last_route_path.write_text(
                json.dumps(
                    {
                        "route_name": "workflow",
                        "updated_at": "2000-01-01T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = enter_runtime_gate(
                "重构数据库层",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertFalse(stale_store.root.exists())

    def test_gate_cleanup_tolerates_invalid_last_route_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            stale_store = StateStore(config, session_id="broken-session")
            stale_store.ensure()
            stale_store.last_route_path.write_text("{not-json", encoding="utf-8")
            old_timestamp = 946684800
            os.utime(stale_store.last_route_path, (old_timestamp, old_timestamp))

            result = enter_runtime_gate(
                "重构数据库层",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertFalse(stale_store.root.exists())
            self.assertIn(
                ".sopify-skills/state/sessions/broken-session",
                result["observability"].get("cleaned_session_dirs", []),
            )

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

    def test_gate_errors_when_current_request_handoff_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            runtime_handoff = _make_runtime_handoff(run_id="run-current")

            with patch(
                "runtime.gate.run_runtime",
                return_value=_make_runtime_result(
                    request_text="补 runtime gate",
                    route_name="workflow",
                    handoff=runtime_handoff,
                ),
            ):
                result = enter_runtime_gate(
                    "补 runtime gate",
                    workspace_root=workspace,
                    session_id="session-test",
                    user_home=workspace / "home",
                )

            self.assertEqual(result["status"], "error")
            self.assertFalse(result["gate_passed"])
            self.assertEqual(result["error_code"], "current_request_not_persisted")
            self.assertEqual(result["allowed_response_mode"], ERROR_VISIBLE_RETRY)
            self.assertFalse(result["evidence"]["handoff_found"])
            self.assertTrue(result["evidence"]["current_request_produced_handoff"])
            self.assertEqual(result["evidence"]["handoff_source_kind"], "current_request_not_persisted")

    def test_gate_errors_when_persisted_handoff_mismatches_runtime_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config, session_id="session-test")
            store.set_current_handoff(_make_runtime_handoff(run_id="run-persisted"))

            with patch(
                "runtime.gate.run_runtime",
                return_value=_make_runtime_result(
                    request_text="补 runtime gate",
                    route_name="workflow",
                    handoff=_make_runtime_handoff(run_id="run-current"),
                ),
            ):
                result = enter_runtime_gate(
                    "补 runtime gate",
                    workspace_root=workspace,
                    session_id="session-test",
                    user_home=workspace / "home",
                )

            self.assertEqual(result["status"], "error")
            self.assertFalse(result["gate_passed"])
            self.assertEqual(result["error_code"], "persisted_runtime_mismatch")
            self.assertTrue(result["evidence"]["handoff_found"])
            self.assertTrue(result["evidence"]["current_request_produced_handoff"])
            self.assertFalse(result["evidence"]["persisted_handoff_matches_current_request"])
            self.assertEqual(result["evidence"]["handoff_source_kind"], "persisted_runtime_mismatch")

    def test_gate_errors_when_handoff_candidate_cannot_be_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            malformed_handoff = SimpleNamespace(
                run_id="run-current",
                route_name="workflow",
                required_host_action="continue_host_workflow",
            )

            with patch(
                "runtime.gate.run_runtime",
                return_value=_make_runtime_result(
                    request_text="补 runtime gate",
                    route_name="workflow",
                    handoff=malformed_handoff,
                ),
            ):
                result = enter_runtime_gate(
                    "补 runtime gate",
                    workspace_root=workspace,
                    session_id="session-test",
                    user_home=workspace / "home",
                )

            self.assertEqual(result["status"], "error")
            self.assertFalse(result["gate_passed"])
            self.assertEqual(result["error_code"], "handoff_normalize_failed")
            self.assertEqual(result["evidence"]["handoff_source_kind"], "current_request_not_persisted")

    def test_gate_prioritizes_strict_runtime_entry_before_source_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config, session_id="session-test")
            store.set_current_handoff(
                _make_runtime_handoff(
                    run_id="run-persisted",
                    route_name="workflow",
                    strict_runtime_entry=False,
                )
            )

            with patch(
                "runtime.gate.run_runtime",
                return_value=_make_runtime_result(
                    request_text="~summary",
                    route_name="summary",
                    handoff=None,
                ),
            ):
                result = enter_runtime_gate(
                    "~summary",
                    workspace_root=workspace,
                    session_id="session-test",
                    user_home=workspace / "home",
                )

            self.assertEqual(result["status"], "error")
            self.assertFalse(result["gate_passed"])
            self.assertEqual(result["error_code"], "strict_runtime_entry_missing")
            self.assertEqual(result["evidence"]["handoff_source_kind"], "reused_prior_state")

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
