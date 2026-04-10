from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_script(relative_path: str, target_root: Path) -> Path:
    source = REPO_ROOT / relative_path
    target = target_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(0o755)
    return target


def _git_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
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


def _run_git(root: Path, *args: str, capture_output: bool = True, text: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=capture_output,
        text=text,
        env=_git_subprocess_env(),
    )


def _minimal_readme(version: str, *, english: bool) -> str:
    anchor = "#version-history" if english else "#版本历史"
    return textwrap.dedent(
        f"""\
        # {'Sopify Skills' if english else 'Sopify 技能'}

        [![Version](https://img.shields.io/badge/version-{version.replace('-', '--')}-orange.svg)]({anchor})
        """
    )


def _minimal_changelog(version: str, date: str) -> str:
    return textwrap.dedent(
        f"""\
        # Changelog

        ## [Unreleased]

        ## [{version}] - {date}

        ### Changed

        - Baseline release.
        """
    )


def _minimal_agents(version: str, *, claude: bool, english: bool) -> str:
    header = "CLAUDE" if claude else "AGENTS"
    body = "Note: ~/.claude/sopify/" if claude else "说明：~/.codex/sopify/"
    if english:
        body = "Note: ~/.claude/sopify/" if claude else "Note: ~/.codex/sopify/"
    return textwrap.dedent(
        f"""\
        <!-- SOPIFY_VERSION: {version} -->
        # {header}

        {body}
        """
    )


def _unreleased_body(changelog_text: str) -> str:
    start = changelog_text.index("## [Unreleased]") + len("## [Unreleased]")
    end = changelog_text.find("\n## [", start)
    if end < 0:
        end = len(changelog_text)
    return changelog_text[start:end]


def _release_body(changelog_text: str, version: str) -> str:
    header = f"## [{version}] - "
    start = changelog_text.index(header)
    body_start = changelog_text.find("\n", start) + 1
    end = changelog_text.find("\n## [", body_start)
    if end < 0:
        end = len(changelog_text)
    return changelog_text[body_start:end]


def _init_release_hook_fixture(root: Path, *, missing_claude_targets: bool = False) -> None:
    for relative in (
        "scripts/release-sync.sh",
        "scripts/release-draft-changelog.py",
        "scripts/release-preflight.sh",
        "scripts/check-context-checkpoints.py",
        "scripts/sync-skills.sh",
        "scripts/check-skills-sync.sh",
        "scripts/check-version-consistency.sh",
        ".githooks/pre-commit",
        ".githooks/commit-msg",
    ):
        _copy_script(relative, root)

    old_version = "2026-03-20.183348"
    old_date = "2026-03-20"
    _write(root / "README.md", _minimal_readme(old_version, english=True))
    _write(root / "README.zh-CN.md", _minimal_readme(old_version, english=False))
    _write(root / "CHANGELOG.md", _minimal_changelog(old_version, old_date))

    _write(root / "Codex/Skills/CN/AGENTS.md", _minimal_agents(old_version, claude=False, english=False))
    _write(root / "Codex/Skills/EN/AGENTS.md", _minimal_agents(old_version, claude=False, english=True))
    _write(root / "Codex/Skills/CN/skills/sopify/SKILL.md", "# skill\n")
    _write(root / "Codex/Skills/EN/skills/sopify/SKILL.md", "# skill\n")

    if not missing_claude_targets:
        _write(root / "Claude/Skills/CN/CLAUDE.md", _minimal_agents(old_version, claude=True, english=False))
        _write(root / "Claude/Skills/EN/CLAUDE.md", _minimal_agents(old_version, claude=True, english=True))
        _write(root / "Claude/Skills/CN/skills/sopify/SKILL.md", "# skill\n")
        _write(root / "Claude/Skills/EN/skills/sopify/SKILL.md", "# skill\n")

    _write(root / "runtime/gate.py", "print('baseline')\n")
    _write(root / "tests/test_runtime_gate.py", "print('baseline test')\n")

    _run_git(root, "init")
    _run_git(root, "config", "user.name", "Test User", capture_output=False, text=False)
    _run_git(root, "config", "user.email", "test@example.com", capture_output=False, text=False)
    _run_git(root, "add", ".", capture_output=False, text=False)
    _run_git(root, "commit", "-m", "baseline")

    _write(root / "runtime/gate.py", "print('changed')\n")
    _write(root / "tests/test_runtime_gate.py", "print('changed test')\n")
    _run_git(root, "add", "runtime/gate.py", "tests/test_runtime_gate.py", capture_output=False, text=False)


class ReleaseHookTests(unittest.TestCase):
    def test_commit_msg_leaves_message_unchanged_without_release_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_release_hook_fixture(root)

            message_file = root / "COMMIT_EDITMSG"
            _write(message_file, "docs: update contribution guide\n")

            completed = subprocess.run(
                ["bash", str(root / ".githooks" / "commit-msg"), str(message_file)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=_git_subprocess_env(),
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            message = message_file.read_text(encoding="utf-8")
            self.assertEqual(message, "docs: update contribution guide\n")
            self.assertNotIn("Release-Sync:", message)

    def test_commit_msg_preserves_manual_coauthor_trailers_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_release_hook_fixture(root)

            message_file = root / "COMMIT_EDITMSG"
            _write(
                message_file,
                textwrap.dedent(
                    """\
                    docs: update contribution guide

                    Co-authored-by: Claude <claude@anthropic.com>
                    Co-authored-by: ChatGPT <chatgpt@openai.com>
                    """
                ),
            )

            completed = subprocess.run(
                ["bash", str(root / ".githooks" / "commit-msg"), str(message_file)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=_git_subprocess_env(),
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            message = message_file.read_text(encoding="utf-8")
            self.assertEqual(message.count("Co-authored-by: Claude <claude@anthropic.com>"), 1)
            self.assertEqual(message.count("Co-authored-by: ChatGPT <chatgpt@openai.com>"), 1)

    def test_commit_msg_requires_context_checkpoint_for_plan_a_scoped_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_release_hook_fixture(root)

            _write(root / "runtime/resolution_planner.py", "print('scope change')\n")
            _run_git(root, "add", "runtime/resolution_planner.py", capture_output=False, text=False)

            message_file = root / "COMMIT_EDITMSG"
            _write(message_file, "feat: tighten scope guard\n")

            completed = subprocess.run(
                ["bash", str(root / ".githooks" / "commit-msg"), str(message_file)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=_git_subprocess_env(),
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Context-Checkpoint", completed.stderr)

    def test_commit_msg_accepts_context_checkpoint_for_plan_a_scoped_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_release_hook_fixture(root)

            _write(root / "runtime/resolution_planner.py", "print('scope change')\n")
            _run_git(root, "add", "runtime/resolution_planner.py", capture_output=False, text=False)

            message_file = root / "COMMIT_EDITMSG"
            _write(
                message_file,
                textwrap.dedent(
                    """\
                    feat: tighten scope guard

                    Context-Checkpoint: C
                    """
                ),
            )

            completed = subprocess.run(
                ["bash", str(root / ".githooks" / "commit-msg"), str(message_file)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=_git_subprocess_env(),
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def test_release_draft_changelog_populates_empty_unreleased(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            changelog = root / "CHANGELOG.md"
            _write(changelog, _minimal_changelog("2026-03-20.183348", "2026-03-20"))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "release-draft-changelog.py"),
                    "--root",
                    str(root),
                    "--file",
                    "runtime/gate.py",
                    "--file",
                    "scripts/release-sync.sh",
                    "--file",
                    "tests/test_runtime_gate.py",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            text = changelog.read_text(encoding="utf-8")
            unreleased = _unreleased_body(text)
            self.assertIn("### Runtime", unreleased)
            self.assertIn("- Updated runtime internals:", unreleased)
            self.assertIn("`runtime/gate.py`", unreleased)
            self.assertIn("### Scripts", unreleased)
            self.assertIn("- Adjusted maintenance scripts:", unreleased)
            self.assertIn("`scripts/release-sync.sh`", unreleased)
            self.assertIn("### Tests", unreleased)
            self.assertIn("- Updated automated coverage:", unreleased)
            self.assertIn("`tests/test_runtime_gate.py`", unreleased)

    def test_release_sync_auto_drafts_unreleased_before_version_bump(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_release_hook_fixture(root)

            completed = subprocess.run(
                ["bash", str(root / "scripts" / "release-sync.sh"), "2026-03-21.010203", "2026-03-21"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=_git_subprocess_env(),
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            release_body = _release_body(changelog, "2026-03-21.010203")
            self.assertIn("## [2026-03-21.010203] - 2026-03-21", changelog)
            self.assertIn("### Runtime", release_body)
            self.assertIn("`runtime/gate.py`", release_body)
            self.assertIn("### Tests", release_body)
            self.assertIn("`tests/test_runtime_gate.py`", release_body)
            self.assertNotIn("### Changed", release_body)
            self.assertIn("badge/version-2026--03--21.010203-orange.svg", (root / "README.md").read_text(encoding="utf-8"))
            self.assertIn("<!-- SOPIFY_VERSION: 2026-03-21.010203 -->", (root / "Codex/Skills/CN/AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("<!-- SOPIFY_VERSION: 2026-03-21.010203 -->", (root / "Claude/Skills/CN/CLAUDE.md").read_text(encoding="utf-8"))

    def test_release_draft_only_renders_non_empty_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            changelog = root / "CHANGELOG.md"
            _write(changelog, _minimal_changelog("2026-03-20.183348", "2026-03-20"))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "release-draft-changelog.py"),
                    "--root",
                    str(root),
                    "--file",
                    "README.md",
                    "--file",
                    "tests/test_runtime_gate.py",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            text = changelog.read_text(encoding="utf-8")
            unreleased = _unreleased_body(text)
            self.assertIn("### Docs", unreleased)
            self.assertIn("### Tests", unreleased)
            self.assertNotIn("### Runtime", unreleased)
            self.assertNotIn("### Scripts", unreleased)
            self.assertNotIn("### Skills", unreleased)
            self.assertNotIn("### Changed", unreleased)

    def test_release_draft_ignores_sopify_kb_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            changelog = root / "CHANGELOG.md"
            _write(changelog, _minimal_changelog("2026-03-20.183348", "2026-03-20"))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "release-draft-changelog.py"),
                    "--root",
                    str(root),
                    "--file",
                    ".sopify-skills/history/index.md",
                    "--file",
                    ".sopify-skills/plan/20260324_task/tasks.md",
                    "--file",
                    "runtime/gate.py",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Auto-drafted CHANGELOG [Unreleased] from 1 changed files.", completed.stdout)
            unreleased = _unreleased_body(changelog.read_text(encoding="utf-8"))
            self.assertIn("### Runtime", unreleased)
            self.assertIn("`runtime/gate.py`", unreleased)
            self.assertNotIn(".sopify-skills/history/index.md", unreleased)
            self.assertNotIn(".sopify-skills/plan/20260324_task/tasks.md", unreleased)
            self.assertNotIn("### Changed", unreleased)

    def test_release_draft_skips_when_only_sopify_kb_paths_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            changelog = root / "CHANGELOG.md"
            original = _minimal_changelog("2026-03-20.183348", "2026-03-20")
            _write(changelog, original)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "release-draft-changelog.py"),
                    "--root",
                    str(root),
                    "--file",
                    ".sopify-skills/history/index.md",
                    "--file",
                    ".sopify-skills/plan/20260324_task/tasks.md",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("No release-note-eligible changed files found. Skipped auto-draft.", completed.stdout)
            self.assertEqual(changelog.read_text(encoding="utf-8"), original)

    def test_pre_commit_restores_release_managed_files_when_release_sync_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_release_hook_fixture(root, missing_claude_targets=True)

            original_readme = (root / "README.md").read_text(encoding="utf-8")
            original_changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            original_agents = (root / "Codex/Skills/CN/AGENTS.md").read_text(encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(root / ".githooks" / "pre-commit")],
                cwd=root,
                env={**_git_subprocess_env(), "SOPIFY_SKIP_RELEASE_PREFLIGHT": "1"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), original_readme)
            self.assertEqual((root / "CHANGELOG.md").read_text(encoding="utf-8"), original_changelog)
            self.assertEqual((root / "Codex/Skills/CN/AGENTS.md").read_text(encoding="utf-8"), original_agents)
            self.assertFalse((root / ".git" / ".sopify-release-sync-state").exists())


if __name__ == "__main__":
    unittest.main()
