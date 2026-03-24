from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from installer.hosts import get_host_capability, iter_declared_hosts, iter_installable_hosts
from installer.hosts.base import install_host_assets
from installer.hosts.claude import CLAUDE_ADAPTER
from installer.hosts.codex import CODEX_ADAPTER
from installer.inspection import build_doctor_payload, build_status_payload
from installer.payload import install_global_payload, run_workspace_bootstrap
from installer.validate import validate_host_install, validate_payload_install
from scripts.sopify_doctor import main as doctor_main
from scripts.sopify_status import main as status_main


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_workspace_state(workspace_root: Path) -> None:
    state_root = workspace_root / ".sopify-skills" / "state"
    _write_json(
        state_root / "current_run.json",
        {
            "run_id": "run-1",
            "stage": "design",
            "status": "active",
            "plan_id": "20260320_helloagents_integration_enhancements",
            "plan_path": ".sopify-skills/plan/20260320_helloagents_integration_enhancements",
        },
    )
    _write_json(
        state_root / "current_handoff.json",
        {
            "run_id": "run-1",
            "required_host_action": "confirm_execute",
        },
    )


class HostCapabilityRegistryTests(unittest.TestCase):
    def test_registry_returns_complete_capabilities_for_declared_hosts(self) -> None:
        codex = get_host_capability("codex")
        claude = get_host_capability("claude")

        self.assertEqual(codex.support_tier.value, "deep_verified")
        self.assertEqual(claude.support_tier.value, "deep_verified")
        self.assertTrue(codex.install_enabled)
        self.assertTrue(claude.install_enabled)
        self.assertIn("runtime_gate", [feature.value for feature in codex.verified_features])
        self.assertIn("smoke_verified", [feature.value for feature in claude.verified_features])

    def test_installable_hosts_only_return_install_enabled_entries(self) -> None:
        installable = [capability.host_id for capability in iter_installable_hosts()]
        declared = [capability.host_id for capability in iter_declared_hosts()]

        self.assertEqual(set(installable), {"codex", "claude"})
        self.assertEqual(set(declared), {"codex", "claude"})


class StatusDoctorContractTests(unittest.TestCase):
    def test_status_json_contains_required_contract_and_workspace_state(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)
            _seed_workspace_state(workspace_root)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)
            validate_host_install(CODEX_ADAPTER, home_root=home_root)
            validate_payload_install(CODEX_ADAPTER.payload_root(home_root))

            payload = build_status_payload(home_root=home_root, workspace_root=workspace_root)

            self.assertEqual(payload["schema_version"], "2")
            self.assertIn("hosts", payload)
            self.assertIn("state", payload)
            self.assertIn("workspace_state", payload)
            self.assertEqual(payload["workspace_state"]["active_plan"], ".sopify-skills/plan/20260320_helloagents_integration_enhancements")
            self.assertEqual(payload["workspace_state"]["pending_checkpoint"], "confirm_execute")
            self.assertEqual(payload["state"]["overall_status"], "partial")
            self.assertEqual(payload["hosts"][0]["verified_features"], ["prompt_install", "payload_install", "workspace_bootstrap", "runtime_gate", "preferences_preload", "handoff_first", "host_bridge", "smoke_verified"])
            self.assertEqual(
                set(payload["hosts"][0]["state"].keys()),
                {"installed", "configured", "workspace_bundle_healthy"},
            )
            self.assertEqual(payload["hosts"][0]["state"]["configured"], "yes")
            self.assertEqual(payload["hosts"][0]["state"]["workspace_bundle_healthy"], "no")
            self.assertNotIn("verified", payload["hosts"][0]["state"])

    def test_doctor_json_contains_reason_codes_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)

            self.assertEqual(payload["schema_version"], "1")
            self.assertIn("checks", payload)
            self.assertIn("summary", payload)
            self.assertTrue(payload["checks"])
            check = payload["checks"][0]
            self.assertIn("check_id", check)
            self.assertIn("status", check)
            self.assertIn("reason_code", check)
            self.assertIn(check["reason_code"], {"ok", "MISSING_REQUIRED_FILE", "MISSING_BUNDLE", "UNEXPECTED_ERROR"})

    def test_status_json_reports_ready_when_workspace_bundle_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)
            run_workspace_bootstrap(CODEX_ADAPTER.payload_root(home_root), workspace_root)

            payload = build_status_payload(home_root=home_root, workspace_root=workspace_root)

            self.assertEqual(payload["schema_version"], "2")
            self.assertEqual(payload["state"]["overall_status"], "ready")
            self.assertEqual(payload["state"]["workspace_bundle_healthy_hosts"], ["codex"])
            self.assertEqual(payload["hosts"][0]["state"]["workspace_bundle_healthy"], "yes")

    def test_status_cli_json_output_contains_hosts_and_workspace_state(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)
            _seed_workspace_state(workspace_root)

            install_host_assets(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="EN")
            install_global_payload(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            completed = _run_script(
                status_main,
                [
                    "--format",
                    "json",
                    "--home-root",
                    str(home_root),
                    "--workspace-root",
                    str(workspace_root),
                ],
            )
            payload = json.loads(completed)
            self.assertEqual(payload["schema_version"], "2")
            self.assertIn("hosts", payload)
            self.assertIn("workspace_state", payload)

    def test_doctor_cli_json_output_contains_checks_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="EN")
            install_global_payload(CLAUDE_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            completed = _run_script(
                doctor_main,
                [
                    "--format",
                    "json",
                    "--home-root",
                    str(home_root),
                    "--workspace-root",
                    str(workspace_root),
                ],
            )
            payload = json.loads(completed)
            self.assertEqual(payload["schema_version"], "1")
            self.assertIn("checks", payload)
            self.assertIn("summary", payload)


def _run_script(entrypoint, argv: list[str]) -> str:
    from io import StringIO
    from contextlib import redirect_stdout

    buffer = StringIO()
    with redirect_stdout(buffer):
        exit_code = entrypoint(argv)
    if exit_code != 0:
        raise AssertionError(f"Expected exit code 0, got {exit_code}")
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
