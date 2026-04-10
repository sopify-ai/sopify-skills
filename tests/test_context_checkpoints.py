from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-context-checkpoints.py"


class ContextCheckpointScriptTests(unittest.TestCase):
    def test_repo_mode_passes_for_current_repo(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "repo", "--root", str(REPO_ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def test_commit_msg_rejects_mismatched_checkpoint_for_scope_finalize_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            message_file = Path(temp_dir) / "COMMIT_EDITMSG"
            message_file.write_text(
                textwrap.dedent(
                    """\
                    feat: tighten scope guard

                    Context-Checkpoint: B
                    """
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "commit-msg",
                    "--root",
                    str(REPO_ROOT),
                    "--message-file",
                    str(message_file),
                    "--files",
                    "runtime/resolution_planner.py",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("does not match", completed.stderr)

    def test_pr_body_requires_checkpoint_metadata_for_relevant_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            body_file = Path(temp_dir) / "pr.md"
            body_file.write_text("## Summary\n\n- tighten guard\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "pr-body",
                    "--root",
                    str(REPO_ROOT),
                    "--body-file",
                    str(body_file),
                    "--files",
                    "runtime/context_v1_scope.py",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("missing required metadata fields", completed.stderr)

    def test_pr_body_accepts_filled_metadata_for_governance_only_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            body_file = Path(temp_dir) / "pr.md"
            body_file.write_text(
                textwrap.dedent(
                    """\
                    ## Summary

                    - tighten checkpoint governance

                    ## Checkpoint Metadata

                    Context-Checkpoint: A
                    Decision IDs: none
                    Blocked by: none
                    Out-of-scope touched: none
                    """
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "pr-body",
                    "--root",
                    str(REPO_ROOT),
                    "--body-file",
                    str(body_file),
                    "--files",
                    ".github/pull_request_template.md",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)


if __name__ == "__main__":
    unittest.main()
