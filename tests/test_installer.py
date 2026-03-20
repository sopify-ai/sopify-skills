from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from installer.bootstrap_workspace import _REQUIRED_BUNDLE_FILES, _classify_workspace_bundle
from installer.hosts.base import install_host_assets
from installer.hosts.claude import CLAUDE_ADAPTER
from installer.hosts.codex import CODEX_ADAPTER
from installer.models import InstallPhaseResult, InstallResult, parse_install_target
from installer.payload import _REQUIRED_BUNDLE_CAPABILITIES, _payload_is_current, install_global_payload
from installer.validate import validate_bundle_install, validate_host_install
from scripts.install_sopify import render_result


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _create_incomplete_payload(*, home_root: Path, version: str) -> Path:
    payload_root = CODEX_ADAPTER.payload_root(home_root)
    bundle_root = payload_root / "bundle"

    _write_json(
        payload_root / "payload-manifest.json",
        {
            "schema_version": "1",
            "payload_version": version,
            "bundle_version": version,
            "bundle_manifest": "bundle/manifest.json",
            "bundle_template_dir": "bundle",
            "helper_entry": "helpers/bootstrap_workspace.py",
        },
    )
    _write_json(
        bundle_root / "manifest.json",
        {
            "schema_version": "1",
            "bundle_version": version,
            "capabilities": {
                "bundle_role": "control_plane",
                "manifest_first": True,
                "writes_handoff_file": True,
            },
        },
    )
    helper_path = payload_root / "helpers" / "bootstrap_workspace.py"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return payload_root


class PayloadInstallTests(unittest.TestCase):
    def test_payload_is_current_rejects_incomplete_bundle_even_when_versions_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home_root = Path(temp_dir)
            payload_root = _create_incomplete_payload(home_root=home_root, version="2026-02-13")

            self.assertFalse(_payload_is_current(payload_root, "2026-02-13"))

    def test_install_global_payload_updates_incomplete_existing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home_root = Path(temp_dir)
            payload_root = _create_incomplete_payload(home_root=home_root, version="2026-02-13")

            result = install_global_payload(
                CODEX_ADAPTER,
                repo_root=REPO_ROOT,
                home_root=home_root,
            )

            self.assertEqual(result.action, "updated")
            self.assertEqual(result.root, payload_root)
            self.assertTrue((payload_root / "bundle" / "scripts" / "clarification_bridge_runtime.py").exists())
            self.assertTrue((payload_root / "bundle" / "scripts" / "develop_checkpoint_runtime.py").exists())
            self.assertTrue((payload_root / "bundle" / "scripts" / "decision_bridge_runtime.py").exists())
            self.assertTrue((payload_root / "bundle" / "scripts" / "preferences_preload_runtime.py").exists())
            self.assertTrue((payload_root / "bundle" / "scripts" / "runtime_gate.py").exists())
            payload_manifest = json.loads((payload_root / "payload-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload_manifest["dependency_model"]["mode"], "stdlib_only")
            self.assertTrue(
                payload_manifest["minimum_workspace_manifest"]["required_capabilities"]["planning_mode_orchestrator"]
            )
            self.assertTrue(
                payload_manifest["minimum_workspace_manifest"]["required_capabilities"]["develop_checkpoint_callback"]
            )
            self.assertTrue(payload_manifest["minimum_workspace_manifest"]["required_capabilities"]["preferences_preload"])
            self.assertTrue(payload_manifest["minimum_workspace_manifest"]["required_capabilities"]["runtime_gate"])
            self.assertTrue(payload_manifest["minimum_workspace_manifest"]["required_capabilities"]["runtime_entry_guard"])


class WorkspaceBootstrapCompatibilityTests(unittest.TestCase):
    def test_same_version_bundle_missing_required_bridge_file_is_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            bundle_root = workspace_root / ".sopify-runtime"
            bundle_root.mkdir(parents=True, exist_ok=True)
            current_manifest_path = bundle_root / "manifest.json"
            current_manifest = {
                "schema_version": "1",
                "bundle_version": "2026-02-13",
                "capabilities": dict(_REQUIRED_BUNDLE_CAPABILITIES),
            }
            _write_json(current_manifest_path, current_manifest)

            for relative_path in _REQUIRED_BUNDLE_FILES:
                if relative_path == Path("scripts") / "clarification_bridge_runtime.py":
                    continue
                path = bundle_root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            state, reason_code, message, from_version = _classify_workspace_bundle(
                current_manifest=current_manifest,
                payload_manifest={
                    "minimum_workspace_manifest": {
                        "schema_version": "1",
                        "required_capabilities": dict(_REQUIRED_BUNDLE_CAPABILITIES),
                    }
                },
                bundle_manifest={"schema_version": "1", "bundle_version": "2026-02-13"},
                current_manifest_path=current_manifest_path,
                bundle_root=bundle_root,
            )

            self.assertEqual(state, "INCOMPATIBLE")
            self.assertEqual(reason_code, "MISSING_REQUIRED_FILE")
            self.assertIn("scripts/clarification_bridge_runtime.py", message)
            self.assertEqual(from_version, "2026-02-13")

    def test_same_version_bundle_missing_required_capability_is_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            bundle_root = workspace_root / ".sopify-runtime"
            bundle_root.mkdir(parents=True, exist_ok=True)
            current_manifest_path = bundle_root / "manifest.json"
            current_manifest = {
                "schema_version": "1",
                "bundle_version": "2026-02-13",
                "capabilities": {
                    "bundle_role": "control_plane",
                    "manifest_first": True,
                    "writes_handoff_file": True,
                    "clarification_bridge": True,
                },
            }
            _write_json(current_manifest_path, current_manifest)

            for relative_path in _REQUIRED_BUNDLE_FILES:
                path = bundle_root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            state, reason_code, message, from_version = _classify_workspace_bundle(
                current_manifest=current_manifest,
                payload_manifest={
                    "minimum_workspace_manifest": {
                        "schema_version": "1",
                        "required_capabilities": dict(_REQUIRED_BUNDLE_CAPABILITIES),
                    }
                },
                bundle_manifest={"schema_version": "1", "bundle_version": "2026-02-13"},
                current_manifest_path=current_manifest_path,
                bundle_root=bundle_root,
            )

            self.assertEqual(state, "INCOMPATIBLE")
            self.assertEqual(reason_code, "MISSING_REQUIRED_CAPABILITY")
            self.assertIn("decision_bridge", message)
            self.assertEqual(from_version, "2026-02-13")

    def test_validate_bundle_install_requires_runtime_bridge_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir) / ".sopify-runtime"
            bundle_root.mkdir(parents=True, exist_ok=True)

            for relative_path in _REQUIRED_BUNDLE_FILES:
                path = bundle_root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            # Match the old incomplete layout that was slipping through bootstrap.
            missing_runtime_module = bundle_root / "runtime" / "cli_interactive.py"
            missing_runtime_module.unlink()

            with self.assertRaisesRegex(Exception, "cli_interactive.py"):
                validate_bundle_install(bundle_root)


class HostPromptContractTests(unittest.TestCase):
    def test_codex_cn_prompt_install_keeps_workspace_preflight_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home_root = Path(temp_dir)

            install_host_assets(
                CODEX_ADAPTER,
                repo_root=REPO_ROOT,
                home_root=home_root,
                language_directory="CN",
            )
            validate_host_install(CODEX_ADAPTER, home_root=home_root)

            prompt = (home_root / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("~/.codex/sopify/payload-manifest.json", prompt)
            self.assertIn("~/.codex/sopify/helpers/bootstrap_workspace.py --workspace-root <cwd>", prompt)
            self.assertIn("缺少或不满足兼容要求的 `.sopify-runtime/manifest.json`", prompt)
            self.assertIn("第一步必须先执行 runtime gate", prompt)
            self.assertIn("limits.runtime_gate_entry", prompt)
            self.assertIn("scripts/runtime_gate.py enter --workspace-root <cwd> --request \"<raw user request>\"", prompt)
            self.assertIn("不得绕过 gate 直接调用 `scripts/sopify_runtime.py`", prompt)
            self.assertIn("allowed_response_mode == checkpoint_only", prompt)
            self.assertIn("allowed_response_mode == error_visible_retry", prompt)
            self.assertIn("limits.preferences_preload_entry", prompt)
            self.assertIn("scripts/preferences_preload_runtime.py inspect --workspace-root <cwd>", prompt)
            self.assertIn("fail-open with visibility", prompt)
            self.assertIn("当前任务明确要求 > `preferences.md` > 默认规则", prompt)
            self.assertIn("不得自行读取 `preferences.md` 原文做二次拼装", prompt)
            self.assertIn("scripts/develop_checkpoint_runtime.py", prompt)
            self.assertIn("resume_context", prompt)
            self.assertIn("不得自由追问", prompt)
            self.assertIn("不得手写 `current_decision.json / current_handoff.json`", prompt)
            self.assertIn("scripts/develop_checkpoint_runtime.py submit --payload-json ...", prompt)
            self.assertIn("即使用户显式输入 `~go exec`", prompt)
            self.assertIn("必须继续遵守对应 checkpoint 的机器契约", prompt)

    def test_claude_en_prompt_install_keeps_workspace_preflight_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home_root = Path(temp_dir)

            install_host_assets(
                CLAUDE_ADAPTER,
                repo_root=REPO_ROOT,
                home_root=home_root,
                language_directory="EN",
            )
            validate_host_install(CLAUDE_ADAPTER, home_root=home_root)

            prompt = (home_root / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("~/.claude/sopify/payload-manifest.json", prompt)
            self.assertIn("~/.claude/sopify/helpers/bootstrap_workspace.py --workspace-root <cwd>", prompt)
            self.assertIn("does not yet have a compatible `.sopify-runtime/manifest.json`", prompt)
            self.assertIn("first step must be the runtime gate", prompt)
            self.assertIn("limits.runtime_gate_entry", prompt)
            self.assertIn("scripts/runtime_gate.py enter --workspace-root <cwd> --request \"<raw user request>\"", prompt)
            self.assertIn("must not bypass the gate", prompt)
            self.assertIn("allowed_response_mode == checkpoint_only", prompt)
            self.assertIn("allowed_response_mode == error_visible_retry", prompt)
            self.assertIn("limits.preferences_preload_entry", prompt)
            self.assertIn("scripts/preferences_preload_runtime.py inspect --workspace-root <cwd>", prompt)
            self.assertIn("fail-open with visibility", prompt)
            self.assertIn("current explicit task > preferences.md > default rules", prompt)
            self.assertIn("never re-read `preferences.md` to rebuild the prompt block manually", prompt)
            self.assertIn("scripts/develop_checkpoint_runtime.py", prompt)
            self.assertIn("resume_context", prompt)
            self.assertIn("must not ask a free-form question", prompt)
            self.assertIn("hand-write `current_decision.json / current_handoff.json`", prompt)
            self.assertIn("scripts/develop_checkpoint_runtime.py submit --payload-json ...", prompt)
            self.assertIn("Even when the user explicitly types `~go exec`", prompt)
            self.assertIn("must still honor the machine contract", prompt)


class InstallRenderTests(unittest.TestCase):
    def test_render_result_reports_already_current_for_noop_install(self) -> None:
        result = _build_install_result(host_action="skipped", payload_action="skipped")

        rendered = render_result(result)

        self.assertTrue(rendered.startswith("Sopify already current:"))
        self.assertIn("No reinstall needed. Trigger Sopify inside any project workspace to bootstrap `.sopify-runtime/` on demand.", rendered)
        self.assertNotIn("Installed Sopify successfully:", rendered)

    def test_render_result_keeps_success_title_when_changes_applied(self) -> None:
        result = _build_install_result(host_action="updated", payload_action="skipped")

        rendered = render_result(result)

        self.assertTrue(rendered.startswith("Installed Sopify successfully:"))
        self.assertIn("Trigger Sopify inside any project workspace to bootstrap `.sopify-runtime/` on demand.", rendered)


def _build_install_result(*, host_action: str, payload_action: str) -> InstallResult:
    host_root = Path("/tmp/home/.codex")
    payload_root = host_root / "sopify"
    return InstallResult(
        target=parse_install_target("codex:zh-CN"),
        workspace_root=None,
        host_root=host_root,
        payload_root=payload_root,
        bundle_root=None,
        host_install=InstallPhaseResult(
            action=host_action,
            root=host_root,
            version="2026-02-13",
            paths=(host_root / "AGENTS.md",),
        ),
        payload_install=InstallPhaseResult(
            action=payload_action,
            root=payload_root,
            version="2026-02-13",
            paths=(payload_root / "payload-manifest.json",),
        ),
        workspace_bootstrap=None,
        smoke_output="Runtime smoke check passed",
    )


if __name__ == "__main__":
    unittest.main()
