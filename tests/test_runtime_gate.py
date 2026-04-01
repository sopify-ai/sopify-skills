from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
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
from installer.hosts.claude import CLAUDE_ADAPTER
from installer.hosts.codex import CODEX_ADAPTER
from installer.payload import install_global_payload
from runtime.models import DecisionOption, DecisionState, PlanArtifact, PlanProposalState, RouteDecision, RunState, RuntimeHandoff
from runtime.plan_scaffold import create_plan_scaffold
from runtime.state import StateStore, iso_now, stable_request_sha1
from runtime.workspace_preflight import _drop_cli_arg_pairs
from runtime.workspace_preflight import preflight_workspace_runtime


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


def _install_payload_manifest_for_gate(*, home_root: Path) -> Path:
    CODEX_ADAPTER.destination_root(home_root).mkdir(parents=True, exist_ok=True)
    phase = install_global_payload(
        CODEX_ADAPTER,
        repo_root=REPO_ROOT,
        home_root=home_root,
    )
    return phase.root / "payload-manifest.json"


def _write_legacy_payload_manifest_for_gate(*, home_root: Path) -> Path:
    payload_root = CODEX_ADAPTER.payload_root(home_root)
    helper_path = payload_root / "helpers" / "bootstrap_workspace.py"
    bundle_manifest_path = payload_root / "bundle" / "manifest.json"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import argparse",
                "import json",
                "from pathlib import Path",
                "",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--workspace-root', required=True)",
                "args = parser.parse_args()",
                "workspace_root = Path(args.workspace_root).resolve()",
                "print(json.dumps({",
                "  'action': 'skipped',",
                "  'state': 'READY',",
                "  'reason_code': 'WORKSPACE_BUNDLE_READY',",
                "  'workspace_root': str(workspace_root),",
                "  'bundle_root': str(workspace_root / '.sopify-runtime'),",
                "  'from_version': None,",
                "  'to_version': None,",
                "  'message': 'legacy helper fallback',",
                "}, ensure_ascii=False))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    bundle_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "bundle_version": "2026-03-28.220226",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    payload_manifest_path = payload_root / "payload-manifest.json"
    payload_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "helper_entry": "helpers/bootstrap_workspace.py",
                "bundle_manifest": "bundle/manifest.json",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload_manifest_path


def _write_host_id_legacy_payload_manifest_for_gate(*, home_root: Path) -> Path:
    payload_manifest_path = _install_payload_manifest_for_gate(home_root=home_root)
    payload_root = payload_manifest_path.parent
    helper_path = payload_root / "helpers" / "bootstrap_workspace.py"
    helper_impl_path = payload_root / "helpers" / "bootstrap_workspace_impl.py"
    helper_impl_path.write_text(helper_path.read_text(encoding="utf-8"), encoding="utf-8")
    helper_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "import argparse",
                "import json",
                "import sys",
                "from pathlib import Path",
                "",
                "HELPER_ROOT = Path(__file__).resolve().parent",
                "if str(HELPER_ROOT) not in sys.path:",
                "    sys.path.insert(0, str(HELPER_ROOT))",
                "",
                "from bootstrap_workspace_impl import bootstrap_workspace",
                "",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--workspace-root', required=True)",
                "parser.add_argument('--request', default='')",
                "args = parser.parse_args()",
                "result = bootstrap_workspace(",
                "    Path(args.workspace_root).resolve(),",
                "    request_text=args.request,",
                ")",
                "print(json.dumps(result, ensure_ascii=False))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return payload_manifest_path


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
    def test_gate_preflight_falls_back_to_legacy_helper_argv_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _write_legacy_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["action"], "skipped")
            self.assertEqual(result["preflight"]["helper_argv_mode"], "legacy_fallback")
            self.assertEqual(result["preflight"]["reason_code"], "WORKSPACE_BUNDLE_READY")

    def test_gate_preflight_skips_first_write_for_non_explicit_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "解释一下 runtime gate",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-non-explicit",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["action"], "skipped")
            self.assertEqual(result["preflight"]["reason_code"], "FIRST_WRITE_NOT_AUTHORIZED")
            self.assertEqual(result["preflight"]["root_resolution_source"], "cwd")
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())
            self.assertFalse((workspace / ".sopify-skills" / "state" / "sessions" / "session-non-explicit").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / CURRENT_GATE_RECEIPT_FILENAME).exists())

    def test_gate_preflight_requires_explicit_root_when_first_write_root_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            workspace = repo_root / "packages" / "feature"
            workspace.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-root-confirm",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["reason_code"], "ROOT_CONFIRM_REQUIRED")
            self.assertEqual(result["allowed_response_mode"], CHECKPOINT_ONLY)
            self.assertIn(f"repo_root={repo_root.resolve()}", result["preflight"]["evidence"])
            self.assertIn(f"recommended_activation_root={workspace.resolve()}", result["preflight"]["evidence"])
            self.assertIn(f"alternate_activation_root={repo_root.resolve()}", result["preflight"]["evidence"])
            self.assertIn("manual_activation_root_allowed=true", result["preflight"]["evidence"])
            self.assertIn("activation_root", result["message"])
            self.assertNotIn("activation_root", result["preflight"])
            self.assertNotIn("ignore_mode", result["preflight"])
            self.assertNotIn("NON_GIT_WORKSPACE", result["preflight"]["evidence"])
            self.assertNotIn("ignore_mode=noop", result["preflight"]["evidence"])
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_gate_preflight_root_confirm_recovers_when_repo_root_is_explicitly_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            workspace = repo_root / "packages" / "feature"
            workspace.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                activation_root=repo_root,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-root-explicit-repo",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["reason_code"], "STUB_SELECTED")
            self.assertEqual(result["preflight"]["activation_root"], str(repo_root.resolve()))
            self.assertEqual(result["preflight"]["requested_root"], str(workspace.resolve()))
            self.assertTrue((repo_root / ".sopify-runtime" / "manifest.json").exists())
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_gate_preflight_root_confirm_current_directory_flows_into_non_git_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            workspace = repo_root / "packages" / "feature"
            workspace.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                activation_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-root-explicit-cwd",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["reason_code"], "CONFIRM_BOOTSTRAP_REQUIRED")
            self.assertEqual(result["preflight"]["activation_root"], str(workspace.resolve()))
            self.assertIn("NON_GIT_WORKSPACE", result["preflight"]["evidence"])
            self.assertIn("ignore_mode=noop", result["preflight"]["evidence"])
            self.assertIn("~go init", result["message"])
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_gate_preflight_root_confirm_current_directory_recovers_after_go_init_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            workspace = repo_root / "packages" / "feature"
            workspace.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go init",
                workspace_root=workspace,
                activation_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-root-explicit-cwd-init",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["reason_code"], "STUB_SELECTED")
            self.assertEqual(result["preflight"]["activation_root"], str(workspace.resolve()))
            self.assertIn("NON_GIT_WORKSPACE", result["preflight"]["evidence"])
            self.assertIn("ignore_mode=noop", result["preflight"]["evidence"])
            self.assertTrue((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_gate_preflight_blocks_first_write_for_non_interactive_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                interaction_mode="non_interactive",
                session_id="session-non-interactive",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["reason_code"], "NON_INTERACTIVE")
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_gate_preflight_blocks_first_write_for_readonly_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            original_mode = workspace.stat().st_mode
            workspace.chmod(0o555)
            try:
                if os.access(workspace, os.W_OK):
                    self.skipTest("workspace remains writable on this platform")

                result = enter_runtime_gate(
                    "~go plan 补 runtime gate 骨架",
                    workspace_root=workspace,
                    payload_manifest_path=payload_manifest_path,
                    user_home=temp_root / "home",
                    session_id="session-readonly",
                )
            finally:
                workspace.chmod(original_mode)

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["reason_code"], "READONLY")
            self.assertIn(f"target_root={workspace.resolve()}", result["preflight"]["evidence"])
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertIn("receipt_write_error", result)
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_gate_preflight_requires_confirm_for_non_git_workspace_before_go_plan_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["action"], "skipped")
            self.assertEqual(result["preflight"]["reason_code"], "CONFIRM_BOOTSTRAP_REQUIRED")
            self.assertEqual(result["preflight"]["host_id"], "codex")
            self.assertIn("NON_GIT_WORKSPACE", result["preflight"]["evidence"])
            self.assertIn("ignore_mode=noop", result["preflight"]["evidence"])
            self.assertEqual(result["allowed_response_mode"], ERROR_VISIBLE_RETRY)
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertIn("~go init", result["message"])
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())
            self.assertFalse((workspace / ".sopify-runtime" / "scripts").exists())

    def test_gate_preflight_bootstraps_missing_git_workspace_for_go_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["action"], "bootstrapped")
            self.assertEqual(result["preflight"]["reason_code"], "STUB_SELECTED")
            self.assertEqual(result["preflight"]["host_id"], "codex")
            self.assertNotIn("NON_GIT_WORKSPACE", result["preflight"].get("evidence", ()))
            self.assertTrue((workspace / ".sopify-runtime" / "manifest.json").exists())
            self.assertFalse((workspace / ".sopify-runtime" / "scripts").exists())

    def test_gate_preflight_bootstraps_missing_workspace_for_go_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go init",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["action"], "bootstrapped")
            self.assertEqual(result["preflight"]["reason_code"], "STUB_SELECTED")
            self.assertIn("NON_GIT_WORKSPACE", result["preflight"]["evidence"])
            self.assertIn("ignore_mode=noop", result["preflight"]["evidence"])
            self.assertTrue((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_preflight_returns_selected_pinned_bundle_contract_instead_of_payload_active_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            home_root = temp_root / "home"
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=home_root)
            payload_root = payload_manifest_path.parent
            payload_manifest = json.loads(payload_manifest_path.read_text(encoding="utf-8"))
            active_version = str(payload_manifest["active_version"])
            pinned_version = f"{active_version}-pinned"

            active_bundle_root = payload_root / "bundles" / active_version
            pinned_bundle_root = payload_root / "bundles" / pinned_version
            shutil.copytree(active_bundle_root, pinned_bundle_root)
            pinned_manifest_path = pinned_bundle_root / "manifest.json"
            pinned_manifest = json.loads(pinned_manifest_path.read_text(encoding="utf-8"))
            pinned_manifest["bundle_version"] = pinned_version
            limits = dict(pinned_manifest.get("limits") or {})
            limits["runtime_gate_entry"] = "scripts/runtime_gate_pinned.py"
            limits["preferences_preload_entry"] = "scripts/preferences_preload_pinned.py"
            pinned_manifest["limits"] = limits
            pinned_manifest_path.write_text(json.dumps(pinned_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (pinned_bundle_root / "scripts" / "runtime_gate_pinned.py").write_text("", encoding="utf-8")
            (pinned_bundle_root / "scripts" / "preferences_preload_pinned.py").write_text("", encoding="utf-8")

            workspace_manifest_path = workspace / ".sopify-runtime" / "manifest.json"
            workspace_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            workspace_manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "stub_version": "1",
                        "bundle_version": pinned_version,
                        "locator_mode": "global_first",
                        "required_capabilities": ["runtime_gate", "preferences_preload"],
                        "ignore_mode": "noop",
                        "written_by_host": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = preflight_workspace_runtime(
                workspace,
                request_text="~go plan 补 runtime gate 骨架",
                payload_manifest_path=payload_manifest_path,
                user_home=home_root,
            )

            self.assertEqual(Path(result["bundle_manifest_path"]).resolve(), (pinned_bundle_root / "manifest.json").resolve())
            self.assertEqual(Path(result["global_bundle_root"]).resolve(), pinned_bundle_root.resolve())
            self.assertEqual(result["runtime_gate_entry"], "scripts/runtime_gate_pinned.py")
            self.assertEqual(result["preferences_preload_entry"], "scripts/preferences_preload_pinned.py")

    def test_preflight_exposes_legacy_workspace_entries_when_global_bundle_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            home_root = temp_root / "home"
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=home_root)
            payload_root = payload_manifest_path.parent

            install_result = subprocess.run(
                [sys.executable, str(payload_root / "helpers" / "bootstrap_workspace.py"), "--workspace-root", str(workspace)],
                capture_output=True,
                text=True,
                check=True,
            )
            bootstrap_payload = json.loads(install_result.stdout)
            self.assertEqual(bootstrap_payload["reason_code"], "STUB_SELECTED")
            self.assertIn("NON_GIT_WORKSPACE", bootstrap_payload["evidence"])

            payload_manifest = json.loads(payload_manifest_path.read_text(encoding="utf-8"))
            selected_version = str(payload_manifest["active_version"])
            selected_bundle_root = payload_root / "bundles" / selected_version
            bundle_root = workspace / ".sopify-runtime"

            workspace_manifest_path = bundle_root / "manifest.json"
            workspace_manifest = json.loads(workspace_manifest_path.read_text(encoding="utf-8"))
            workspace_manifest["legacy_fallback"] = True
            workspace_manifest_path.write_text(json.dumps(workspace_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for name in ("runtime", "scripts", "tests"):
                shutil.copytree(selected_bundle_root / name, bundle_root / name)

            shutil.rmtree(selected_bundle_root)

            result = preflight_workspace_runtime(
                workspace,
                request_text="~go plan demo",
                payload_manifest_path=payload_manifest_path,
                user_home=home_root,
            )

            self.assertEqual(result["reason_code"], "LEGACY_FALLBACK_SELECTED")
            self.assertTrue(result["bundle_manifest_path"].endswith(f"/bundles/{selected_version}/manifest.json"))
            self.assertTrue(result["global_bundle_root"].endswith(f"/bundles/{selected_version}"))
            self.assertEqual(result["runtime_gate_entry"], "scripts/runtime_gate.py")
            self.assertEqual(result["preferences_preload_entry"], "scripts/preferences_preload_runtime.py")

    def test_gate_preflight_brake_layer_blocks_first_write_even_for_go_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go 先分析一下，不写文件",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-brake",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["action"], "skipped")
            self.assertEqual(result["preflight"]["reason_code"], "BRAKE_LAYER_BLOCKED")
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())
            self.assertFalse((workspace / ".sopify-skills" / "state" / "sessions" / "session-brake").exists())
            self.assertTrue((workspace / ".sopify-skills" / "state" / CURRENT_GATE_RECEIPT_FILENAME).exists())

    def test_gate_preflight_block_takes_priority_over_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "sopify.config.yaml").write_text("unknown_key: 1\n", encoding="utf-8")
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go 先分析一下，不写文件",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-priority",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["reason_code"], "BRAKE_LAYER_BLOCKED")
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")

    def test_gate_first_write_not_authorized_takes_priority_over_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "sopify.config.yaml").write_text("language: xx-XX\n", encoding="utf-8")
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "解释一下 runtime gate",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-priority",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["reason_code"], "FIRST_WRITE_NOT_AUTHORIZED")
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")

    def test_gate_non_blocking_config_error_still_surfaces_normally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "sopify.config.yaml").write_text("unknown_key: 1\n", encoding="utf-8")

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "config_error")

    def test_gate_preflight_block_uses_pre_config_fallback_paths_even_with_custom_plan_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "sopify.config.yaml").write_text("plan:\n  directory: .custom-sopify\n", encoding="utf-8")
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go 先分析一下，不写文件",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-fallback",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertEqual(
                result["receipt_path"],
                str((workspace / ".sopify-skills" / "state" / CURRENT_GATE_RECEIPT_FILENAME).resolve()),
            )
            self.assertEqual(result["state"]["state_root"], ".sopify-skills/state/sessions/session-fallback")

    def test_gate_preflight_does_not_bootstrap_for_compare_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~compare 方案对比",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                session_id="session-compare",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["preflight"]["action"], "skipped")
            self.assertEqual(result["preflight"]["reason_code"], "COMMAND_NOT_BOOTSTRAP_AUTHORIZED")
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())
            self.assertFalse((workspace / ".sopify-skills" / "state" / "sessions" / "session-compare").exists())

    def test_gate_preflight_explicit_payload_manifest_path_fail_closes_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            home_root = temp_root / "home"
            _install_payload_manifest_for_gate(home_root=home_root)

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_manifest_path=temp_root / "missing" / "payload-manifest.json",
                user_home=home_root,
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("Explicit payload manifest not found", result["message"])

    def test_gate_preflight_explicit_payload_manifest_path_fail_closes_when_json_is_array(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            home_root = temp_root / "home"
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=home_root)
            explicit_manifest = temp_root / "explicit.json"
            explicit_manifest.write_text(json.dumps([]), encoding="utf-8")

            with patch.dict(os.environ, {"SOPIFY_PAYLOAD_MANIFEST": str(payload_manifest_path)}):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    payload_manifest_path=explicit_manifest,
                    user_home=home_root,
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("Explicit payload manifest must be a JSON object", result["message"])

    def test_gate_preflight_explicit_payload_manifest_path_fail_closes_when_helper_entry_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            home_root = temp_root / "home"
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=home_root)
            explicit_manifest = temp_root / "explicit.json"
            explicit_manifest.write_text(json.dumps({}), encoding="utf-8")

            with patch.dict(os.environ, {"SOPIFY_PAYLOAD_MANIFEST": str(payload_manifest_path)}):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    payload_manifest_path=explicit_manifest,
                    user_home=home_root,
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("Explicit payload manifest is missing helper_entry", result["message"])

    def test_gate_preflight_explicit_payload_manifest_path_wins_over_env_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            explicit_home = temp_root / "explicit-home"
            env_home = temp_root / "env-home"
            explicit_manifest_path = _install_payload_manifest_for_gate(home_root=explicit_home)
            env_manifest_path = _install_payload_manifest_for_gate(home_root=env_home)

            with patch.dict(os.environ, {"SOPIFY_PAYLOAD_MANIFEST": str(env_manifest_path)}):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    payload_manifest_path=explicit_manifest_path,
                    user_home=explicit_home,
                )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["payload_root"], str((explicit_home / ".codex" / "sopify").resolve()))

    def test_gate_preflight_explicit_payload_manifest_path_rejects_invalid_helper_entry_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            bundle_manifest_path = temp_root / "bundle" / "manifest.json"
            bundle_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "bundle_version": "2026-03-28.220226",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            explicit_manifest = temp_root / "explicit.json"
            explicit_manifest.write_text(
                json.dumps({"helper_entry": "../escape.py", "bundle_manifest": "bundle/manifest.json"}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_manifest_path=explicit_manifest,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("Invalid helper_entry", result["message"])

    def test_gate_preflight_uses_user_home_for_payload_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            real_home = temp_root / "real-home"
            embedded_home = temp_root / "embedded-home"
            _install_payload_manifest_for_gate(home_root=embedded_home)

            with patch("runtime.workspace_preflight.Path.home", return_value=real_home):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    user_home=embedded_home,
                )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["payload_root"], str((embedded_home / ".codex" / "sopify").resolve()))

    def test_gate_preflight_uses_explicit_payload_root_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            explicit_home = temp_root / "explicit-home"
            other_home = temp_root / "other-home"
            _install_payload_manifest_for_gate(home_root=explicit_home)
            _install_payload_manifest_for_gate(home_root=other_home)

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_root=(explicit_home / ".codex" / "sopify"),
                user_home=other_home,
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["payload_root"], str((explicit_home / ".codex" / "sopify").resolve()))

    def test_gate_preflight_requires_explicit_payload_root_when_multiple_payloads_exist_even_if_host_id_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            codex_home = temp_root / "home"
            claude_home = temp_root / "home"
            CODEX_ADAPTER.destination_root(codex_home).mkdir(parents=True, exist_ok=True)
            CLAUDE_ADAPTER.destination_root(claude_home).mkdir(parents=True, exist_ok=True)
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=codex_home)
            install_global_payload(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=claude_home)

            with patch.dict(os.environ, {}, clear=True):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    host_id="claude",
                    user_home=temp_root / "home",
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("pass payload_root explicitly", result["message"])
            self.assertIn("audit-only", result["message"])

    def test_gate_preflight_host_id_missing_default_payload_fail_closes_even_when_env_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CODEX_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            codex_payload = install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home).root

            with patch.dict(os.environ, {"SOPIFY_PAYLOAD_MANIFEST": str(codex_payload / "payload-manifest.json")}):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    host_id="claude",
                    user_home=home,
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("does not match", result["message"])
            self.assertIn("SOPIFY_PAYLOAD_MANIFEST", result["message"])

    def test_gate_preflight_missing_host_payload_still_allows_explicit_payload_root_escape_hatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CODEX_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            codex_payload = install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home).root

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_root=codex_payload,
                user_home=home,
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["payload_root"], str(codex_payload.resolve()))

    def test_gate_preflight_fail_closes_when_explicit_payload_root_conflicts_with_host_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CODEX_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            codex_payload = install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home).root

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                host_id="claude",
                payload_root=codex_payload,
                user_home=home,
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("explicit payload_root", result["message"])
            self.assertIn("does not match", result["message"])

    def test_gate_preflight_exposes_global_bundle_root_from_payload_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )
            payload_manifest = json.loads(payload_manifest_path.read_text(encoding="utf-8"))
            active_version = str(payload_manifest["active_version"])

            self.assertEqual(result["status"], "ready")
            self.assertTrue(
                result["preflight"]["bundle_manifest_path"].endswith(f"/bundles/{active_version}/manifest.json")
            )
            self.assertTrue(result["preflight"]["global_bundle_root"].endswith(f"/bundles/{active_version}"))
            self.assertEqual(result["preflight"]["runtime_gate_entry"], "scripts/runtime_gate.py")
            self.assertEqual(result["preflight"]["preferences_preload_entry"], "scripts/preferences_preload_runtime.py")

    def test_gate_preflight_maps_missing_active_version_to_workspace_preflight_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")
            payload_manifest = json.loads(payload_manifest_path.read_text(encoding="utf-8"))
            payload_manifest.pop("active_version", None)
            payload_manifest_path.write_text(
                json.dumps(payload_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")

    def test_gate_preflight_prefers_detected_codex_host_without_loading_broken_claude_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CODEX_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            CLAUDE_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home)
            claude_payload = install_global_payload(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home).root
            (claude_payload / "payload-manifest.json").write_text("{not-json\n", encoding="utf-8")

            with patch.dict(os.environ, {"CODEX_CI": "1"}, clear=True):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    user_home=home,
                )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["host_id"], "codex")
            self.assertEqual(result["preflight"]["payload_root"], str((home / ".codex" / "sopify").resolve()))

    def test_gate_preflight_detected_codex_host_fail_closes_when_only_claude_payload_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CLAUDE_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            install_global_payload(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home)

            with patch.dict(os.environ, {"CODEX_CI": "1"}, clear=True):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    user_home=home,
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")

    def test_gate_preflight_requires_explicit_host_selection_when_multiple_payloads_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CODEX_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            CLAUDE_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home)
            install_global_payload(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home)

            with patch.dict(os.environ, {}, clear=True):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    user_home=home,
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("Multiple installed host payloads found", result["message"])

    def test_gate_preflight_prefers_explicit_host_selection_error_before_loading_broken_manifest_when_multiple_payloads_exist(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CODEX_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            CLAUDE_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home)
            claude_payload = install_global_payload(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home).root
            (claude_payload / "payload-manifest.json").write_text("{not-json\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    user_home=home,
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("Multiple installed host payloads found", result["message"])

    def test_gate_preflight_reports_invalid_payload_manifest_for_single_installed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            home = temp_root / "home"
            CODEX_ADAPTER.destination_root(home).mkdir(parents=True, exist_ok=True)
            codex_payload = install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home).root
            (codex_payload / "payload-manifest.json").write_text("{not-json\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    user_home=home,
                )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("Invalid payload manifest", result["message"])

    def test_gate_preflight_falls_back_when_helper_rejects_host_id_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_root = temp_root / "home" / ".codex" / "sopify"
            helper_path = payload_root / "helpers" / "bootstrap_workspace.py"
            bundle_manifest_path = payload_root / "bundle" / "manifest.json"
            helper_path.parent.mkdir(parents=True, exist_ok=True)
            helper_path.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import argparse",
                        "import json",
                        "from pathlib import Path",
                        "",
                        "parser = argparse.ArgumentParser()",
                        "parser.add_argument('--workspace-root', required=True)",
                        "parser.add_argument('--request', default='')",
                        "args = parser.parse_args()",
                        "workspace_root = Path(args.workspace_root).resolve()",
                        "print(json.dumps({",
                        "  'action': 'skipped',",
                        "  'state': 'READY',",
                        "  'reason_code': 'WORKSPACE_BUNDLE_READY',",
                        "  'workspace_root': str(workspace_root),",
                        "  'bundle_root': str(workspace_root / '.sopify-runtime'),",
                        "  'from_version': None,",
                        "  'to_version': None,",
                        "  'message': 'legacy helper fallback',",
                        "}, ensure_ascii=False))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            bundle_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "bundle_version": "2026-03-28.220226",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            payload_manifest_path = payload_root / "payload-manifest.json"
            payload_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            payload_manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "helper_entry": "helpers/bootstrap_workspace.py",
                        "bundle_manifest": "bundle/manifest.json",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["helper_argv_mode"], "legacy_request_preserved")

    def test_gate_preflight_preserves_request_when_helper_only_rejects_host_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _write_host_id_legacy_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "只解释 runtime gate，不写文件",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "workspace_first_write_blocked")
            self.assertEqual(result["preflight"]["action"], "skipped")
            self.assertEqual(result["preflight"]["reason_code"], "BRAKE_LAYER_BLOCKED")
            self.assertEqual(result["preflight"]["helper_argv_mode"], "legacy_request_preserved")
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_gate_preflight_fail_closes_when_legacy_helper_cannot_honor_non_interactive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            payload_manifest_path = _write_host_id_legacy_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan demo",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
                interaction_mode="non_interactive",
            )

            self.assertEqual(result["status"], "error")
            self.assertEqual(result["allowed_response_mode"], ERROR_VISIBLE_RETRY)
            self.assertEqual(result["error_code"], "workspace_preflight_failed")
            self.assertIn("too old", result["message"])
            self.assertIn("Refresh the local Sopify install", result["message"])
            self.assertFalse((workspace / ".sopify-runtime" / "manifest.json").exists())

    def test_drop_cli_arg_pairs_preserves_request_value_that_matches_removed_flag_name(self) -> None:
        command = [
            sys.executable,
            "helper.py",
            "--workspace-root",
            "/ws",
            "--request",
            "--host-id",
            "--host-id",
            "codex",
            "--requested-root",
            "/req",
        ]

        rewritten = _drop_cli_arg_pairs(command, {"--host-id", "--requested-root"})

        self.assertEqual(
            rewritten,
            [
                sys.executable,
                "helper.py",
                "--workspace-root",
                "/ws",
                "--request",
                "--host-id",
            ],
        )

    def test_gate_preflight_uses_env_payload_manifest_when_host_id_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            user_home = temp_root / "home"
            env_home = temp_root / "env-home"
            env_manifest_path = _install_payload_manifest_for_gate(home_root=env_home)

            with patch.dict(os.environ, {"SOPIFY_PAYLOAD_MANIFEST": str(env_manifest_path)}):
                result = enter_runtime_gate(
                    "~go plan demo",
                    workspace_root=workspace,
                    user_home=user_home,
                )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["host_id"], "codex")
            self.assertEqual(result["preflight"]["payload_root"], str((env_home / ".codex" / "sopify").resolve()))

    def test_gate_preflight_reuses_nearest_valid_ancestor_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "repo" / "packages" / "feature"
            workspace.mkdir(parents=True, exist_ok=True)
            ancestor_root = temp_root / "repo"
            (ancestor_root / ".git").mkdir(parents=True, exist_ok=True)
            marker_path = ancestor_root / ".sopify-runtime" / "manifest.json"
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(json.dumps({"schema_version": "1"}, ensure_ascii=False) + "\n", encoding="utf-8")
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["activation_root"], str(ancestor_root.resolve()))
            self.assertEqual(result["preflight"]["requested_root"], str(workspace.resolve()))
            self.assertEqual(result["preflight"]["root_resolution_source"], "ancestor_marker")

    def test_gate_preflight_invalid_ancestor_marker_falls_closed_to_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "repo" / "packages" / "feature"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / ".git").mkdir(parents=True, exist_ok=True)
            ancestor_root = temp_root / "repo"
            marker_path = ancestor_root / ".sopify-runtime" / "manifest.json"
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text("{invalid json\n", encoding="utf-8")
            payload_manifest_path = _install_payload_manifest_for_gate(home_root=temp_root / "home")

            result = enter_runtime_gate(
                "~go plan 补 runtime gate 骨架",
                workspace_root=workspace,
                payload_manifest_path=payload_manifest_path,
                user_home=temp_root / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["preflight"]["activation_root"], str(workspace.resolve()))
            self.assertEqual(result["preflight"]["root_resolution_source"], "cwd")
            self.assertEqual(result["preflight"]["fallback_reason"], "invalid_ancestor_marker")
            self.assertTrue((workspace / ".sopify-runtime" / "manifest.json").exists())

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

    def test_gate_allows_runtime_only_state_conflict_inspect_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config, session_id="session-test")
            store.set_current_handoff(
                _make_runtime_handoff(
                    run_id="run-current",
                    route_name="workflow",
                    required_host_action="continue_host_workflow",
                )
            )
            runtime_handoff = RuntimeHandoff(
                schema_version="1",
                route_name="state_conflict",
                run_id="run-current",
                handoff_kind="state_conflict",
                required_host_action="resolve_state_conflict",
                artifacts={"entry_guard": build_entry_guard_contract(required_host_action="resolve_state_conflict")},
                observability={
                    "generated_at": iso_now(),
                    "request_excerpt": "看看状态",
                    "request_sha1": stable_request_sha1("看看状态"),
                },
            )

            with patch(
                "runtime.gate.run_runtime",
                return_value=_make_runtime_result(
                    request_text="看看状态",
                    route_name="state_conflict",
                    handoff=runtime_handoff,
                ),
            ):
                result = enter_runtime_gate(
                    "看看状态",
                    workspace_root=workspace,
                    session_id="session-test",
                    user_home=workspace / "home",
                )

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["gate_passed"])
            self.assertEqual(result["allowed_response_mode"], CHECKPOINT_ONLY)
            self.assertTrue(result["evidence"]["handoff_found"])
            self.assertTrue(result["evidence"]["current_request_produced_handoff"])
            self.assertFalse(result["evidence"]["persisted_handoff_matches_current_request"])
            self.assertEqual(
                result["evidence"]["handoff_source_kind"],
                "current_request_runtime_only_state_conflict",
            )
            self.assertEqual(result["handoff"]["required_host_action"], "resolve_state_conflict")

    def test_gate_reads_global_abort_conflict_handoff_from_global_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            store = StateStore(config)
            store.ensure()
            store.set_current_run(
                RunState(
                    run_id="run-1",
                    status="active",
                    stage="plan_generated",
                    route_name="plan_only",
                    title="Runtime",
                    created_at=iso_now(),
                    updated_at=iso_now(),
                    plan_id="plan-1",
                    plan_path=".sopify-skills/plan/runtime",
                    resolution_id="run-resolution",
                )
            )
            store.set_current_handoff(
                RuntimeHandoff(
                    schema_version="1",
                    route_name="plan_only",
                    run_id="run-1",
                    plan_id="plan-1",
                    plan_path=".sopify-skills/plan/runtime",
                    handoff_kind="plan",
                    required_host_action="review_or_execute_plan",
                    resolution_id="handoff-resolution",
                )
            )

            result = enter_runtime_gate(
                "取消",
                workspace_root=workspace,
                user_home=workspace / "home",
            )

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["gate_passed"])
            self.assertEqual(result["allowed_response_mode"], NORMAL_RUNTIME_FOLLOWUP)
            self.assertTrue(result["evidence"]["handoff_found"])
            self.assertEqual(result["evidence"]["handoff_source_kind"], "current_request_persisted")
            self.assertTrue(result["evidence"]["persisted_handoff_matches_current_request"])
            self.assertEqual(result["state"]["scope"], "global")
            self.assertEqual(result["handoff"]["required_host_action"], "continue_host_workflow")

    def test_gate_persists_abort_conflict_handoff_without_current_run_in_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = load_runtime_config(workspace)
            session_id = "session-conflict"
            store = StateStore(config, session_id=session_id)
            store.ensure()
            store.set_current_plan_proposal(
                PlanProposalState(
                    schema_version="1",
                    checkpoint_id="proposal-1",
                    reserved_plan_id="plan-1",
                    topic_key="runtime",
                    proposed_level="standard",
                    proposed_path=".sopify-skills/plan/proposal",
                    analysis_summary="pending proposal",
                    estimated_task_count=2,
                    request_text="继续",
                    created_at=iso_now(),
                    updated_at=iso_now(),
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
                    recommended_option_id="option_1",
                    resume_context={"checkpoint_id": "decision-1"},
                    created_at=iso_now(),
                    updated_at=iso_now(),
                )
            )

            inspect_result = enter_runtime_gate(
                "看看状态",
                workspace_root=workspace,
                session_id=session_id,
                user_home=workspace / "home",
            )
            self.assertEqual(inspect_result["status"], "ready")
            self.assertEqual(inspect_result["runtime"]["route_name"], "state_conflict")
            self.assertEqual(inspect_result["handoff"]["required_host_action"], "resolve_state_conflict")

            cancel_result = enter_runtime_gate(
                "取消",
                workspace_root=workspace,
                session_id=session_id,
                user_home=workspace / "home",
            )

            self.assertEqual(cancel_result["status"], "ready")
            self.assertTrue(cancel_result["gate_passed"])
            self.assertEqual(cancel_result["allowed_response_mode"], NORMAL_RUNTIME_FOLLOWUP)
            self.assertEqual(cancel_result["runtime"]["route_name"], "state_conflict")
            self.assertEqual(cancel_result["handoff"]["required_host_action"], "continue_host_workflow")
            self.assertEqual(cancel_result["evidence"]["handoff_source_kind"], "current_request_persisted")
            self.assertTrue(cancel_result["evidence"]["persisted_handoff_matches_current_request"])
            self.assertEqual(cancel_result["state"]["scope"], "session")
            persisted_store = StateStore(load_runtime_config(workspace), session_id=session_id)
            self.assertIsNone(persisted_store.get_current_run())
            self.assertIsNotNone(persisted_store.get_current_handoff())

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
        self.assertIn("root_confirm_checkpoint_only", scenario_ids)
        self.assertIn("protected_plan_asset_runtime_first", scenario_ids)
        self.assertIn("clarification_checkpoint_only", scenario_ids)
        self.assertIn("decision_checkpoint_only", scenario_ids)
        self.assertIn("execution_confirm_checkpoint_only", scenario_ids)
        self.assertIn("fail_closed_missing_handoff", scenario_ids)


if __name__ == "__main__":
    unittest.main()
