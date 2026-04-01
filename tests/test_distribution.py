from __future__ import annotations

from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from installer.distribution import (
    DistributionError,
    DistributionRequest,
    DistributionSourceMetadata,
    render_distribution_result,
    run_distribution_install,
)
from scripts.install_sopify import run_install


class DistributionFacadeTests(unittest.TestCase):
    def test_repo_local_and_stable_channels_share_install_truth(self) -> None:
        with tempfile.TemporaryDirectory() as repo_local_home, tempfile.TemporaryDirectory() as stable_home:
            repo_local_request = DistributionRequest(
                target="codex:zh-CN",
                workspace=None,
                ref_override=None,
                interactive=False,
                source_channel="repo-local",
                source_metadata=DistributionSourceMetadata(
                    resolved_ref="working-tree",
                    asset_name="scripts/install_sopify.py",
                ),
            )
            stable_request = DistributionRequest(
                target="codex:zh-CN",
                workspace=None,
                ref_override=None,
                interactive=False,
                source_channel="stable",
                source_metadata=DistributionSourceMetadata(
                    resolved_ref="2026-03-25.101956",
                    asset_name="install.sh",
                ),
            )

            repo_local_report = run_distribution_install(
                request=repo_local_request,
                repo_root=REPO_ROOT,
                home_root=Path(repo_local_home),
                install_executor=run_install,
            )
            stable_report = run_distribution_install(
                request=stable_request,
                repo_root=REPO_ROOT,
                home_root=Path(stable_home),
                install_executor=run_install,
            )

            self.assertEqual(repo_local_report.install_result.target.value, stable_report.install_result.target.value)
            self.assertEqual(repo_local_report.install_result.host_install.version, stable_report.install_result.host_install.version)
            self.assertEqual(repo_local_report.install_result.payload_install.version, stable_report.install_result.payload_install.version)
            self.assertEqual(repo_local_report.status_payload["state"], stable_report.status_payload["state"])
            self.assertEqual(
                repo_local_report.status_payload["hosts"][0]["state"],
                stable_report.status_payload["hosts"][0]["state"],
            )
            self.assertEqual(
                [check["status"] for check in repo_local_report.doctor_payload["checks"] if check.get("host_id") == "codex"],
                [check["status"] for check in stable_report.doctor_payload["checks"] if check.get("host_id") == "codex"],
            )

    def test_distribution_install_without_workspace_marks_bootstrap_on_first_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home_root = Path(home_dir)
            request = DistributionRequest(
                target="codex:zh-CN",
                workspace=None,
                ref_override=None,
                interactive=False,
                source_channel="repo-local",
                source_metadata=DistributionSourceMetadata(
                    resolved_ref="working-tree",
                    asset_name="scripts/install_sopify.py",
                ),
            )

            report = run_distribution_install(
                request=request,
                repo_root=REPO_ROOT,
                home_root=home_root,
                install_executor=run_install,
            )

            self.assertFalse(report.status_payload["workspace_state"]["requested"])
            self.assertEqual(report.status_payload["workspace_state"]["bootstrap_mode"], "on_first_project_trigger")
            self.assertEqual(report.status_payload["hosts"][0]["state"]["workspace_bundle_healthy"], "not_requested")
            self.assertEqual(report.status_payload["hosts"][0]["payload_bundle"]["source_kind"], "global_active")
            self.assertEqual(report.status_payload["hosts"][0]["payload_bundle"]["reason_code"], "PAYLOAD_BUNDLE_READY")
            rendered = render_distribution_result(report)
            self.assertIn("source channel: repo-local", rendered)
            self.assertIn("payload bundle: source_kind=global_active, reason_code=PAYLOAD_BUNDLE_READY", rendered)
            self.assertIn("workspace: will bootstrap on first project trigger", rendered)
            self.assertIn("workspace bundle: skip (WORKSPACE_NOT_REQUESTED)", rendered)

    def test_distribution_install_with_workspace_reports_prewarmed_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as workspace_dir:
            home_root = Path(home_dir)
            workspace_root = Path(workspace_dir)
            request = DistributionRequest(
                target="codex:zh-CN",
                workspace=str(workspace_root),
                ref_override=None,
                interactive=False,
                source_channel="repo-local",
                source_metadata=DistributionSourceMetadata(
                    resolved_ref="working-tree",
                    asset_name="scripts/install_sopify.py",
                ),
            )

            report = run_distribution_install(
                request=request,
                repo_root=REPO_ROOT,
                home_root=home_root,
                install_executor=run_install,
            )

            self.assertTrue(report.status_payload["workspace_state"]["requested"])
            self.assertEqual(report.status_payload["workspace_state"]["root"], str(workspace_root.resolve()))
            self.assertEqual(report.status_payload["hosts"][0]["state"]["workspace_bundle_healthy"], "yes")
            rendered = render_distribution_result(report)
            self.assertIn(f"workspace: pre-warmed at {workspace_root.resolve()}", rendered)
            self.assertIn("workspace bundle: pass (STUB_SELECTED)", rendered)

    def test_distribution_install_rejects_ambiguous_nested_workspace_prewarm(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as repo_dir:
            home_root = Path(home_dir)
            repo_root = Path(repo_dir)
            workspace_root = repo_root / "packages" / "feature"
            workspace_root.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)
            request = DistributionRequest(
                target="codex:zh-CN",
                workspace=str(workspace_root),
                ref_override=None,
                interactive=False,
                source_channel="repo-local",
                source_metadata=DistributionSourceMetadata(
                    resolved_ref="working-tree",
                    asset_name="scripts/install_sopify.py",
                ),
            )

            with self.assertRaises(DistributionError) as context:
                run_distribution_install(
                    request=request,
                    repo_root=REPO_ROOT,
                    home_root=home_root,
                    install_executor=run_install,
                )

            self.assertEqual(context.exception.reason_code, "WORKSPACE_PREWARM_ROOT_AMBIGUOUS")
            self.assertIn("omit `--workspace`", context.exception.detail.lower())
            self.assertIn("choose whether to enable the current directory or the repository root", context.exception.next_step)

    def test_non_interactive_distribution_install_requires_target(self) -> None:
        request = DistributionRequest(
            target=None,
            workspace=None,
            ref_override=None,
            interactive=False,
            source_channel="stable",
            source_metadata=DistributionSourceMetadata(
                resolved_ref="2026-03-25.101956",
                asset_name="install.sh",
            ),
        )

        with self.assertRaises(DistributionError) as context:
            run_distribution_install(
                request=request,
                repo_root=REPO_ROOT,
                home_root=Path(tempfile.gettempdir()),
                install_executor=run_install,
            )

        self.assertEqual(context.exception.reason_code, "TARGET_REQUIRED")

    def test_distribution_install_rejects_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.NamedTemporaryFile() as workspace_file:
            request = DistributionRequest(
                target="codex:zh-CN",
                workspace=workspace_file.name,
                ref_override=None,
                interactive=False,
                source_channel="stable",
                source_metadata=DistributionSourceMetadata(
                    resolved_ref="2026-03-25.101956",
                    asset_name="install.sh",
                ),
            )

            with self.assertRaises(DistributionError) as context:
                run_distribution_install(
                    request=request,
                    repo_root=REPO_ROOT,
                    home_root=Path(home_dir),
                    install_executor=run_install,
                )

            self.assertEqual(context.exception.reason_code, "WORKSPACE_NOT_DIRECTORY")
            self.assertIn("internal prewarm flag", context.exception.next_step)

    def test_interactive_distribution_install_selects_registry_target(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            request = DistributionRequest(
                target=None,
                workspace=None,
                ref_override=None,
                interactive=True,
                source_channel="stable",
                source_metadata=DistributionSourceMetadata(
                    resolved_ref="2026-03-25.101956",
                    asset_name="install.sh",
                ),
            )
            prompt_output = StringIO()

            report = run_distribution_install(
                request=request,
                repo_root=REPO_ROOT,
                home_root=Path(home_dir),
                install_executor=run_install,
                input_func=lambda _prompt: "1",
                output_stream=prompt_output,
            )

            self.assertEqual(report.install_result.target.value, "codex:zh-CN")
            self.assertIn("1. codex:zh-CN", prompt_output.getvalue())

    def test_repo_local_ref_override_is_rejected(self) -> None:
        request = DistributionRequest(
            target="codex:zh-CN",
            workspace=None,
            ref_override="main",
            interactive=False,
            source_channel="repo-local",
            source_metadata=DistributionSourceMetadata(
                resolved_ref="working-tree",
                asset_name="scripts/install_sopify.py",
            ),
        )

        with self.assertRaises(DistributionError) as context:
            run_distribution_install(
                request=request,
                repo_root=REPO_ROOT,
                home_root=Path(tempfile.gettempdir()),
                install_executor=run_install,
            )

        self.assertEqual(context.exception.reason_code, "REF_OVERRIDE_UNSUPPORTED_FOR_REPO_LOCAL")


class ReleaseAssetRenderingTests(unittest.TestCase):
    def test_root_install_scripts_keep_internal_workspace_flag_out_of_primary_usage(self) -> None:
        install_sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
        install_ps1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")

        for flag in ("--target", "--ref"):
            self.assertIn(flag, install_sh)
            self.assertIn(flag, install_ps1)
        self.assertIn("--workspace", install_sh)
        self.assertIn("--workspace", install_ps1)
        self.assertIn("scripts/install_sopify.py", install_sh)
        self.assertIn("scripts/install_sopify.py", install_ps1)
        self.assertIn("--source-channel", install_sh)
        self.assertIn("--source-channel", install_ps1)
        self.assertIn("Usage: install.sh [--target <host:lang>] [--ref <tag-or-branch>]", install_sh)
        self.assertIn("Usage: install.ps1 [--target <host:lang>] [--ref <tag-or-branch>]", install_ps1)
        self.assertIn("Internal-only project prewarm path", install_sh)
        self.assertIn("Internal-only project prewarm path", install_ps1)
        self.assertIn("first project trigger", install_sh)
        self.assertIn("first project trigger", install_ps1)

    def test_powershell_installer_prefers_python3_probe(self) -> None:
        install_ps1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
        lines = install_ps1.splitlines()

        python3_index = next(index for index, line in enumerate(lines) if "Get-Command python3 " in line)
        python_index = next(index for index, line in enumerate(lines) if "Get-Command python " in line)
        py_index = next(index for index, line in enumerate(lines) if "Get-Command py " in line)

        self.assertLess(python3_index, python_index)
        self.assertLess(python_index, py_index)
        self.assertIn("None of `python3`, `python`, or `py -3` is available.", install_ps1)

    def test_render_release_installers_renders_stable_assets(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "render-release-installers.py"),
                    "--release-tag",
                    "2026-03-25.101956",
                    "--output-dir",
                    output_dir,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            install_sh = (Path(output_dir) / "install.sh").read_text(encoding="utf-8")
            install_ps1 = (Path(output_dir) / "install.ps1").read_text(encoding="utf-8")
            self.assertIn('SOURCE_CHANNEL="stable"', install_sh)
            self.assertIn('SOURCE_REF="2026-03-25.101956"', install_sh)
            self.assertNotIn('SOURCE_CHANNEL="dev"', install_sh)
            self.assertIn('$SourceChannel = "stable"', install_ps1)
            self.assertIn('$SourceRef = "2026-03-25.101956"', install_ps1)

    def test_stable_channel_does_not_use_main(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "render-release-installers.py"),
                    "--release-tag",
                    "2026-03-25.101956",
                    "--output-dir",
                    output_dir,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            install_sh = (Path(output_dir) / "install.sh").read_text(encoding="utf-8")
            install_ps1 = (Path(output_dir) / "install.ps1").read_text(encoding="utf-8")
            self.assertNotIn('SOURCE_REF="main"', install_sh)
            self.assertNotIn('$SourceRef = "main"', install_ps1)

    def test_root_install_shell_help_returns_usage_without_network(self) -> None:
        completed = subprocess.run(
            ["bash", str(REPO_ROOT / "install.sh"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("Usage: install.sh", completed.stdout)


if __name__ == "__main__":
    unittest.main()
