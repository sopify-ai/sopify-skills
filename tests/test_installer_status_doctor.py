from __future__ import annotations

import json
from pathlib import Path
import shutil
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
from installer.inspection import build_doctor_payload, build_status_payload, render_status_text
from installer.payload import _REQUIRED_BUNDLE_CAPABILITIES, install_global_payload, run_workspace_bootstrap
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


def _seed_quarantined_workspace_state(workspace_root: Path) -> None:
    state_root = workspace_root / ".sopify-skills" / "state"
    _write_json(
        state_root / "current_plan_proposal.json",
        {
            "request_text": "继续",
        },
    )


def _seed_execution_confirm_conflict_workspace_state(workspace_root: Path) -> None:
    state_root = workspace_root / ".sopify-skills" / "state"
    _write_json(
        state_root / "current_handoff.json",
        {
            "schema_version": "1",
            "route_name": "execution_confirm_pending",
            "run_id": "run-1",
            "handoff_kind": "checkpoint",
            "required_host_action": "confirm_execute",
        },
    )
    _write_json(
        state_root / "current_plan_proposal.json",
        {
            "schema_version": "1",
            "checkpoint_id": "proposal-1",
            "reserved_plan_id": "plan-1",
            "topic_key": "runtime",
            "proposed_level": "standard",
            "proposed_path": ".sopify-skills/plan/proposal",
            "analysis_summary": "proposal",
            "estimated_task_count": 2,
            "request_text": "继续",
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
    def test_status_payload_supports_workspace_not_requested(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home_root = Path(home_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            payload = build_status_payload(home_root=home_root, workspace_root=None)

            self.assertFalse(payload["workspace_state"]["requested"])
            self.assertEqual(payload["workspace_state"]["bootstrap_mode"], "on_first_project_trigger")
            self.assertEqual(payload["hosts"][0]["state"]["workspace_bundle_healthy"], "not_requested")
            self.assertEqual(payload["hosts"][0]["payload_bundle"]["source_kind"], "global_active")
            self.assertEqual(payload["hosts"][0]["payload_bundle"]["reason_code"], "PAYLOAD_BUNDLE_READY")
            rendered = render_status_text(payload)
            self.assertIn("requested: no", rendered)
            self.assertIn("will bootstrap on first project trigger", rendered)
            self.assertIn("payload_bundle=global_active (PAYLOAD_BUNDLE_READY)", rendered)

    def test_doctor_payload_supports_workspace_not_requested(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home_root = Path(home_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            payload = build_doctor_payload(home_root=home_root, workspace_root=None)

            workspace_check = next(
                check
                for check in payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_bundle_manifest"
            )
            self.assertEqual(workspace_check["status"], "skip")
            self.assertEqual(workspace_check["reason_code"], "WORKSPACE_NOT_REQUESTED")
            self.assertEqual(
                workspace_check["recommendation"],
                "Workspace bootstrap was not requested. Trigger Sopify in a project workspace to bootstrap on demand.",
            )
            payload_bundle_check = next(
                check
                for check in payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "payload_bundle_resolution"
            )
            self.assertEqual(payload_bundle_check["status"], "pass")
            self.assertEqual(payload_bundle_check["reason_code"], "PAYLOAD_BUNDLE_READY")
            self.assertEqual(payload_bundle_check["source_kind"], "global_active")

    def test_status_and_doctor_surface_legacy_payload_bundle_layout(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home_root = Path(home_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            payload_root = CODEX_ADAPTER.payload_root(home_root)
            payload_manifest = json.loads((payload_root / "payload-manifest.json").read_text(encoding="utf-8"))
            active_version = payload_manifest["active_version"]
            legacy_bundle_root = payload_root / "bundle"
            shutil.copytree(payload_root / "bundles" / active_version, legacy_bundle_root)
            _write_json(
                payload_root / "payload-manifest.json",
                {
                    "schema_version": "1",
                    "payload_version": active_version,
                    "bundle_version": active_version,
                    "bundle_manifest": "bundle/manifest.json",
                    "bundle_template_dir": "bundle",
                    "helper_entry": "helpers/bootstrap_workspace.py",
                },
            )

            status_payload = build_status_payload(home_root=home_root, workspace_root=None)
            self.assertEqual(status_payload["hosts"][0]["payload_bundle"]["source_kind"], "legacy_layout")
            self.assertEqual(status_payload["hosts"][0]["payload_bundle"]["reason_code"], "LEGACY_FALLBACK_SELECTED")
            rendered = render_status_text(status_payload)
            self.assertIn("payload_bundle=legacy_layout (LEGACY_FALLBACK_SELECTED)", rendered)

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=None)
            payload_bundle_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "payload_bundle_resolution"
            )
            self.assertEqual(payload_bundle_check["status"], "warn")
            self.assertEqual(payload_bundle_check["reason_code"], "LEGACY_FALLBACK_SELECTED")
            self.assertEqual(payload_bundle_check["source_kind"], "legacy_layout")

    def test_status_and_doctor_fail_closed_for_non_object_payload_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home_root = Path(home_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            payload_root = CODEX_ADAPTER.payload_root(home_root)
            (payload_root / "payload-manifest.json").write_text("[1]", encoding="utf-8")

            status_payload = build_status_payload(home_root=home_root, workspace_root=None)
            self.assertEqual(status_payload["hosts"][0]["payload_bundle"]["source_kind"], "unresolved")
            self.assertEqual(status_payload["hosts"][0]["payload_bundle"]["reason_code"], "GLOBAL_INDEX_CORRUPTED")

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=None)
            payload_bundle_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "payload_bundle_resolution"
            )
            self.assertEqual(payload_bundle_check["status"], "fail")
            self.assertEqual(payload_bundle_check["reason_code"], "GLOBAL_INDEX_CORRUPTED")
            self.assertEqual(payload_bundle_check["source_kind"], "unresolved")

    def test_status_and_doctor_fail_closed_for_versioned_layout_missing_active_version(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home_root = Path(home_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            payload_root = CODEX_ADAPTER.payload_root(home_root)
            payload_manifest = json.loads((payload_root / "payload-manifest.json").read_text(encoding="utf-8"))
            payload_manifest.pop("active_version", None)
            (payload_root / "payload-manifest.json").write_text(
                json.dumps(payload_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            status_payload = build_status_payload(home_root=home_root, workspace_root=None)
            self.assertEqual(status_payload["hosts"][0]["payload_bundle"]["source_kind"], "global_active")
            self.assertEqual(status_payload["hosts"][0]["payload_bundle"]["reason_code"], "GLOBAL_INDEX_CORRUPTED")

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=None)
            payload_bundle_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "payload_bundle_resolution"
            )
            self.assertEqual(payload_bundle_check["status"], "fail")
            self.assertEqual(payload_bundle_check["reason_code"], "GLOBAL_INDEX_CORRUPTED")
            self.assertEqual(payload_bundle_check["source_kind"], "global_active")

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
            self.assertEqual(payload["workspace_state"]["quarantine_count"], 0)
            self.assertEqual(payload["workspace_state"]["state_conflicts"], [])
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

    def test_status_and_doctor_surface_runtime_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)
            _seed_quarantined_workspace_state(workspace_root)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            status_payload = build_status_payload(home_root=home_root, workspace_root=workspace_root)
            self.assertEqual(status_payload["workspace_state"]["quarantine_count"], 1)
            self.assertEqual(status_payload["workspace_state"]["quarantined_items"][0]["reason"], "proposal_contract_missing")
            rendered = render_status_text(status_payload)
            self.assertIn("quarantine_count: 1", rendered)
            self.assertIn("proposal_contract_missing", rendered)

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)
            quarantine_check = next(
                check
                for check in doctor_payload["checks"]
                if check["check_id"] == "workspace_runtime_quarantine"
            )
            self.assertEqual(quarantine_check["status"], "warn")
            self.assertEqual(quarantine_check["reason_code"], "QUARANTINED_RUNTIME_STATE")

    def test_status_and_doctor_surface_state_conflict_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)
            _seed_execution_confirm_conflict_workspace_state(workspace_root)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            status_payload = build_status_payload(home_root=home_root, workspace_root=workspace_root)
            conflict = status_payload["workspace_state"]["state_conflicts"][0]
            self.assertEqual(conflict["code"], "execution_confirm_review_checkpoint_conflict")
            self.assertEqual(
                conflict["explanation"],
                "Execution confirmation is contaminated by residual review-checkpoint state.",
            )
            rendered = render_status_text(status_payload)
            self.assertIn("state_conflict: execution_confirm_review_checkpoint_conflict", rendered)
            self.assertIn(
                "state_conflict_explanation: Execution confirmation is contaminated by residual review-checkpoint state.",
                rendered,
            )

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)
            conflict_check = next(
                check
                for check in doctor_payload["checks"]
                if check["check_id"] == "workspace_runtime_state_conflict"
            )
            self.assertEqual(conflict_check["status"], "fail")
            self.assertEqual(conflict_check["reason_code"], "RUNTIME_STATE_CONFLICT")
            self.assertTrue(
                any(
                    "execution_confirm_review_checkpoint_conflict" in evidence
                    and "Execution confirmation is contaminated by residual review-checkpoint state." in evidence
                    for evidence in conflict_check["evidence"]
                )
            )

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

    def test_status_and_doctor_treat_stub_only_workspace_as_ready_when_global_bundle_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)
            run_workspace_bootstrap(CODEX_ADAPTER.payload_root(home_root), workspace_root)

            bundle_root = workspace_root / ".sopify-runtime"
            for name in ("runtime", "scripts", "tests"):
                target = bundle_root / name
                if target.exists():
                    import shutil

                    shutil.rmtree(target)

            status_payload = build_status_payload(home_root=home_root, workspace_root=workspace_root)
            self.assertEqual(status_payload["hosts"][0]["state"]["workspace_bundle_healthy"], "yes")

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)
            workspace_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_bundle_manifest"
            )
            self.assertEqual(workspace_check["status"], "pass")
            self.assertEqual(workspace_check["reason_code"], "STUB_SELECTED")
            self.assertIn("NON_GIT_WORKSPACE", workspace_check["evidence"])
            self.assertIn("ignore_mode=noop", workspace_check["evidence"])

    def test_doctor_resolves_workspace_capabilities_from_global_bundle_when_workspace_manifest_is_stub_only(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)
            run_workspace_bootstrap(CODEX_ADAPTER.payload_root(home_root), workspace_root)

            workspace_manifest = json.loads((workspace_root / ".sopify-runtime" / "manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("capabilities", workspace_manifest)
            self.assertNotIn("limits", workspace_manifest)

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)
            handoff_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_handoff_first"
            )
            preload_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_preferences_preload"
            )
            self.assertEqual(handoff_check["status"], "pass")
            self.assertEqual(handoff_check["reason_code"], "ok")
            self.assertEqual(preload_check["status"], "pass")
            self.assertEqual(preload_check["reason_code"], "ok")

    def test_doctor_uses_workspace_fallback_decision_when_selected_global_bundle_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)
            run_workspace_bootstrap(CODEX_ADAPTER.payload_root(home_root), workspace_root)

            payload_root = CODEX_ADAPTER.payload_root(home_root)
            payload_manifest = json.loads((payload_root / "payload-manifest.json").read_text(encoding="utf-8"))
            selected_version = str(payload_manifest["active_version"])
            selected_bundle_root = payload_root / "bundles" / selected_version
            bundle_root = workspace_root / ".sopify-runtime"

            workspace_manifest_path = bundle_root / "manifest.json"
            workspace_manifest = json.loads(workspace_manifest_path.read_text(encoding="utf-8"))
            workspace_manifest["legacy_fallback"] = True
            workspace_manifest_path.write_text(json.dumps(workspace_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for name in ("runtime", "scripts", "tests"):
                shutil.copytree(selected_bundle_root / name, bundle_root / name)

            shutil.rmtree(selected_bundle_root)

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)
            workspace_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_bundle_manifest"
            )
            handoff_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_handoff_first"
            )
            preload_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_preferences_preload"
            )
            payload_bundle_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "payload_bundle_resolution"
            )

            self.assertEqual(workspace_check["reason_code"], "LEGACY_FALLBACK_SELECTED")
            self.assertEqual(handoff_check["status"], "pass")
            self.assertEqual(handoff_check["reason_code"], "ok")
            self.assertEqual(preload_check["status"], "pass")
            self.assertEqual(preload_check["reason_code"], "ok")
            self.assertEqual(payload_bundle_check["reason_code"], "GLOBAL_BUNDLE_MISSING")

    def test_doctor_recommends_on_demand_bootstrap_without_public_workspace_flag(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)
            workspace_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_bundle_manifest"
            )

            self.assertEqual(workspace_check["reason_code"], "MISSING_BUNDLE")
            self.assertIn("Trigger Sopify there to bootstrap on demand", workspace_check["recommendation"])
            self.assertNotIn("--workspace", workspace_check["recommendation"])

    def test_status_and_doctor_surface_partial_bundle_damage_as_replace_required(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)

            install_host_assets(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root, language_directory="CN")
            install_global_payload(CODEX_ADAPTER, repo_root=REPO_ROOT, home_root=home_root)
            run_workspace_bootstrap(CODEX_ADAPTER.payload_root(home_root), workspace_root)

            payload_root = CODEX_ADAPTER.payload_root(home_root)
            payload_manifest = json.loads((payload_root / "payload-manifest.json").read_text(encoding="utf-8"))
            active_version = payload_manifest["active_version"]
            bundle_root = workspace_root / ".sopify-runtime"
            for name in ("runtime", "scripts", "tests"):
                shutil.copytree(payload_root / "bundles" / active_version / name, bundle_root / name)
            (bundle_root / "scripts" / "runtime_gate.py").unlink()

            doctor_payload = build_doctor_payload(home_root=home_root, workspace_root=workspace_root)
            workspace_check = next(
                check
                for check in doctor_payload["checks"]
                if check["host_id"] == "codex" and check["check_id"] == "workspace_bundle_manifest"
            )
            self.assertEqual(workspace_check["status"], "pass")
            self.assertEqual(workspace_check["reason_code"], "STUB_SELECTED")
            self.assertIn("NON_GIT_WORKSPACE", workspace_check["evidence"])
            self.assertNotIn("recommendation", workspace_check)

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
