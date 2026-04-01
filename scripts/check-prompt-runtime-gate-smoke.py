#!/usr/bin/env python3
"""Run a focused smoke check for the prompt-level Sopify runtime gate.

This validates the Layer 1 gate contract and fail-closed behavior only. It
does not prove that a real host enforced gate-first ordering at turn ingress.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.config import load_runtime_config
from runtime.entry_guard import DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE
from runtime.execution_gate import evaluate_execution_gate
from runtime.gate import CURRENT_GATE_RECEIPT_FILENAME
from runtime.models import PlanArtifact, RouteDecision, RunState
from runtime.plan_scaffold import create_plan_scaffold
from runtime.state import StateStore, iso_now
from installer.hosts.codex import CODEX_ADAPTER
from installer.payload import install_global_payload

_SKIP_ASSERTION = object()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a focused smoke check for the prompt-level Sopify runtime gate.")
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write the structured smoke result as JSON.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary directories for inspection instead of deleting them.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    temp_root = Path(tempfile.mkdtemp(prefix="sopify-prompt-runtime-gate."))
    try:
        result = run_smoke(temp_root=temp_root)
        _write_optional_json(args.output_json, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (RuntimeError, ValueError) as exc:
        failure = {
            "passed": False,
            "error": str(exc),
            "temp_root": str(temp_root),
        }
        _write_optional_json(args.output_json, failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if args.keep_temp:
            print(f"Kept temp root: {temp_root}", file=sys.stderr)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def run_smoke(*, temp_root: Path) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    smoke_home = temp_root / "home"
    smoke_home.mkdir(parents=True, exist_ok=True)

    normal_workspace = temp_root / "normal"
    scenarios.append(
        _run_gate_scenario(
            scenario_id="normal_runtime_followup",
            workspace=normal_workspace,
            home_root=smoke_home,
            request="~go plan 重构数据库层",
            expected_exit_code=0,
            expected_status="ready",
            expected_mode="normal_runtime_followup",
            expected_action="review_or_execute_plan",
            expected_error_code=None,
            expected_state_files=("current_handoff.json", "current_plan.json", CURRENT_GATE_RECEIPT_FILENAME),
        )
    )

    root_confirm_home = temp_root / "root-confirm-home"
    CODEX_ADAPTER.destination_root(root_confirm_home).mkdir(parents=True, exist_ok=True)
    install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=root_confirm_home)
    root_confirm_workspace = temp_root / "root-confirm" / "repo" / "packages" / "feature"
    (root_confirm_workspace.parents[1] / ".git").mkdir(parents=True, exist_ok=True)
    scenarios.append(
        _run_gate_scenario(
            scenario_id="root_confirm_checkpoint_only",
            workspace=root_confirm_workspace,
            home_root=root_confirm_home,
            request="~go plan monorepo root 选择",
            expected_exit_code=1,
            expected_status="error",
            expected_mode="checkpoint_only",
            expected_action=None,
            expected_error_code="workspace_first_write_blocked",
            expected_state_files=(CURRENT_GATE_RECEIPT_FILENAME,),
            expected_runtime_route="preflight_blocked",
        )
    )

    protected_plan_workspace = temp_root / "protected-plan-asset"
    scenarios.append(
        _run_gate_scenario(
            scenario_id="protected_plan_asset_runtime_first",
            workspace=protected_plan_workspace,
            home_root=smoke_home,
            request="分析下 .sopify-skills/plan/20260320_kb_layout_v2/tasks.md 的当前任务，并整理 README 职责表边界",
            expected_exit_code=0,
            expected_status="ready",
            expected_mode="checkpoint_only",
            expected_action="confirm_plan_package",
            expected_error_code=None,
            expected_state_files=("current_handoff.json", "current_plan_proposal.json", CURRENT_GATE_RECEIPT_FILENAME),
            expected_runtime_route="plan_proposal_pending",
            expected_entry_guard_reason_code=DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
            expected_direct_edit_guard_kind="protected_plan_asset",
        )
    )

    clarification_workspace = temp_root / "clarification"
    scenarios.append(
        _run_gate_scenario(
            scenario_id="clarification_checkpoint_only",
            workspace=clarification_workspace,
            home_root=smoke_home,
            request="优化一下",
            expected_exit_code=0,
            expected_status="ready",
            expected_mode="checkpoint_only",
            expected_action="answer_questions",
            expected_error_code=None,
            expected_state_files=("current_clarification.json", "current_handoff.json", CURRENT_GATE_RECEIPT_FILENAME),
        )
    )

    decision_workspace = temp_root / "decision"
    scenarios.append(
        _run_gate_scenario(
            scenario_id="decision_checkpoint_only",
            workspace=decision_workspace,
            home_root=smoke_home,
            request="~go plan payload 放 host root 还是 workspace/.sopify-runtime",
            expected_exit_code=0,
            expected_status="ready",
            expected_mode="checkpoint_only",
            expected_action="confirm_decision",
            expected_error_code=None,
            expected_state_files=("current_decision.json", "current_handoff.json", CURRENT_GATE_RECEIPT_FILENAME),
        )
    )

    execution_confirm_workspace = temp_root / "execution-confirm"
    _prepare_ready_plan_state(execution_confirm_workspace)
    scenarios.append(
        _run_gate_scenario(
            scenario_id="execution_confirm_checkpoint_only",
            workspace=execution_confirm_workspace,
            home_root=smoke_home,
            request="~go exec",
            expected_exit_code=0,
            expected_status="ready",
            expected_mode="checkpoint_only",
            expected_action="confirm_execute",
            expected_error_code=None,
            expected_state_files=("current_handoff.json", "current_plan.json", CURRENT_GATE_RECEIPT_FILENAME),
        )
    )

    fail_closed_workspace = temp_root / "fail-closed"
    scenarios.append(
        _run_gate_scenario(
            scenario_id="fail_closed_missing_handoff",
            workspace=fail_closed_workspace,
            home_root=smoke_home,
            request="~go exec",
            expected_exit_code=1,
            expected_status="error",
            expected_mode="error_visible_retry",
            expected_action=None,
            expected_error_code="handoff_missing",
            expected_state_files=(CURRENT_GATE_RECEIPT_FILENAME,),
        )
    )

    failures = [scenario for scenario in scenarios if not scenario["passed"]]
    return {
        "passed": not failures,
        "script": "scripts/check-prompt-runtime-gate-smoke.py",
        "temp_root": str(temp_root),
        "scenarios": scenarios,
    }


def _run_gate_scenario(
    *,
    scenario_id: str,
    workspace: Path,
    home_root: Path,
    request: str,
    expected_exit_code: int,
    expected_status: str,
    expected_mode: str,
    expected_action: str | None,
    expected_error_code: str | None,
    expected_state_files: tuple[str, ...],
    expected_runtime_route: str | None = None,
    expected_entry_guard_reason_code: object = _SKIP_ASSERTION,
    expected_direct_edit_guard_kind: object = _SKIP_ASSERTION,
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    payload, exit_code = _run_gate_cli(workspace=workspace, home_root=home_root, request=request)

    state_dir = workspace / ".sopify-skills" / "state"
    receipt_path = state_dir / CURRENT_GATE_RECEIPT_FILENAME
    receipt = _load_json(receipt_path) if receipt_path.exists() else {}
    handoff = _load_gate_handoff(workspace=workspace, payload=payload)

    failures: list[str] = []
    if exit_code != expected_exit_code:
        failures.append(f"exit_code expected {expected_exit_code}, got {exit_code}")
    if str(payload.get("status")) != expected_status:
        failures.append(f"status expected {expected_status}, got {payload.get('status')}")
    if str(payload.get("allowed_response_mode")) != expected_mode:
        failures.append(
            f"allowed_response_mode expected {expected_mode}, got {payload.get('allowed_response_mode')}"
        )
    actual_action = payload.get("handoff", {}).get("required_host_action")
    actual_runtime_route = payload.get("runtime", {}).get("route_name")
    actual_entry_guard_reason_code = payload.get("handoff", {}).get("entry_guard_reason_code")
    actual_direct_edit_guard_kind = payload.get("trigger_evidence", {}).get("direct_edit_guard_kind")
    if expected_action is None:
        if actual_action is not None:
            failures.append(f"required_host_action expected None, got {actual_action}")
    elif actual_action != expected_action:
        failures.append(f"required_host_action expected {expected_action}, got {actual_action}")
    if expected_runtime_route is not None and actual_runtime_route != expected_runtime_route:
        failures.append(f"runtime.route_name expected {expected_runtime_route}, got {actual_runtime_route}")
    if expected_entry_guard_reason_code is not _SKIP_ASSERTION and actual_entry_guard_reason_code != expected_entry_guard_reason_code:
        failures.append(
            f"entry_guard_reason_code expected {expected_entry_guard_reason_code}, got {actual_entry_guard_reason_code}"
        )
    if expected_direct_edit_guard_kind is not _SKIP_ASSERTION and actual_direct_edit_guard_kind != expected_direct_edit_guard_kind:
        failures.append(
            f"trigger_evidence.direct_edit_guard_kind expected {expected_direct_edit_guard_kind}, got {actual_direct_edit_guard_kind}"
        )
    actual_error_code = payload.get("error_code")
    if expected_error_code is None:
        if actual_error_code is not None:
            failures.append(f"unexpected error_code={actual_error_code}")
    elif actual_error_code != expected_error_code:
        failures.append(f"error_code expected {expected_error_code}, got {actual_error_code}")

    for filename in expected_state_files:
        path = _resolve_expected_state_path(workspace=workspace, payload=payload, filename=filename)
        if path is None or not path.exists():
            failures.append(f"missing state file: {filename}")

    if not receipt:
        failures.append("missing or unreadable current_gate_receipt.json")
    else:
        if receipt.get("allowed_response_mode") != payload.get("allowed_response_mode"):
            failures.append("receipt.allowed_response_mode drifted from gate payload")
        if receipt.get("status") != payload.get("status"):
            failures.append("receipt.status drifted from gate payload")
        if receipt.get("evidence", {}).get("strict_runtime_entry") != payload.get("evidence", {}).get("strict_runtime_entry"):
            failures.append("receipt.evidence.strict_runtime_entry drifted from gate payload")

    if expected_action in {"answer_questions", "confirm_decision", "confirm_plan_package", "confirm_execute"}:
        if payload.get("allowed_response_mode") == "normal_runtime_followup":
            failures.append("pending checkpoint unexpectedly escaped to normal_runtime_followup")
        if not payload.get("handoff", {}).get("pending_fail_closed"):
            failures.append("pending checkpoint is missing pending_fail_closed=true")

    if expected_error_code is not None and payload.get("gate_passed"):
        failures.append("fail-closed scenario unexpectedly returned gate_passed=true")

    if handoff and payload.get("handoff", {}).get("required_host_action") != handoff.get("required_host_action"):
        failures.append("handoff file required_host_action drifted from gate payload")

    return {
        "id": scenario_id,
        "request": request,
        "workspace": str(workspace),
        "exit_code": exit_code,
        "passed": not failures,
        "failures": failures,
        "status": payload.get("status"),
        "allowed_response_mode": payload.get("allowed_response_mode"),
        "runtime_route_name": actual_runtime_route,
        "required_host_action": actual_action,
        "entry_guard_reason_code": actual_entry_guard_reason_code,
        "direct_edit_guard_kind": actual_direct_edit_guard_kind,
        "error_code": actual_error_code,
        "receipt_path": str(receipt_path),
    }


def _run_gate_cli(*, workspace: Path, home_root: Path, request: str) -> tuple[dict[str, Any], int]:
    script_path = REPO_ROOT / "scripts" / "runtime_gate.py"
    env = dict(os.environ)
    env["HOME"] = str(home_root)
    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "enter",
            "--workspace-root",
            str(workspace),
            "--request",
            request,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError(f"runtime_gate.py produced no stdout for request={request!r}: {completed.stderr.strip()}")
    payload = json.loads(stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"runtime_gate.py returned non-object JSON for request={request!r}")
    return payload, completed.returncode


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _resolve_expected_state_path(*, workspace: Path, payload: Mapping[str, Any], filename: str) -> Path | None:
    if filename == CURRENT_GATE_RECEIPT_FILENAME:
        return workspace / ".sopify-skills" / "state" / CURRENT_GATE_RECEIPT_FILENAME

    state_contract = payload.get("state")
    if not isinstance(state_contract, Mapping):
        return None
    relative_path = {
        "current_plan.json": state_contract.get("current_plan_path"),
        "current_plan_proposal.json": state_contract.get("current_plan_proposal_path"),
        "current_run.json": state_contract.get("current_run_path"),
        "current_handoff.json": state_contract.get("current_handoff_path"),
        "current_clarification.json": state_contract.get("current_clarification_path"),
        "current_decision.json": state_contract.get("current_decision_path"),
        "last_route.json": state_contract.get("last_route_path"),
    }.get(filename)
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    return workspace / relative_path


def _load_gate_handoff(*, workspace: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    handoff_path = _resolve_expected_state_path(
        workspace=workspace,
        payload=payload,
        filename="current_handoff.json",
    )
    if handoff_path is None or not handoff_path.exists():
        return {}
    return _load_json(handoff_path)


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


def _prepare_ready_plan_state(workspace: Path, *, request_text: str = "补 prompt runtime gate smoke") -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    config = load_runtime_config(workspace)
    store = StateStore(config)
    store.ensure()
    plan_artifact = create_plan_scaffold(request_text, config=config, level="standard")
    _rewrite_background_scope(
        workspace,
        plan_artifact,
        scope_lines=("runtime/gate.py, scripts/runtime_gate.py", "runtime/gate.py, scripts/runtime_gate.py, scripts/check-prompt-runtime-gate-smoke.py"),
        risk_lines=("需要确保执行前确认不会误触发 develop", "统一通过 execution_confirm_pending 与 gate ready 再进入执行"),
    )
    gate = evaluate_execution_gate(
        decision=RouteDecision(
            route_name="workflow",
            request_text=request_text,
            reason="smoke",
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


def _write_optional_json(path_value: str | None, payload: dict[str, Any]) -> None:
    if not path_value:
        return
    output_path = Path(path_value).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
