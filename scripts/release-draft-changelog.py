#!/usr/bin/env python3
"""Auto-draft root CHANGELOG [Unreleased] notes from staged release-relevant files."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


UNRELEASED_HEADER = "## [Unreleased]"
SECTION_DEFINITIONS = (
    ("Docs", "Refined public documentation"),
    ("Runtime", "Updated runtime internals"),
    ("Scripts", "Adjusted maintenance scripts"),
    ("Skills", "Synced prompt-layer skills"),
    ("Tests", "Updated automated coverage"),
    ("Changed", "Updated project files"),
)


def _repo_matches_current_git_env(root: Path) -> bool:
    env = os.environ
    work_tree = (env.get("GIT_WORK_TREE") or "").strip()
    if work_tree:
        try:
            return Path(work_tree).resolve() == root.resolve()
        except OSError:
            return False

    git_dir = (env.get("GIT_DIR") or "").strip()
    if git_dir:
        try:
            return Path(git_dir).resolve() == (root / ".git").resolve()
        except OSError:
            return False
    return False


def git_command_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    if _repo_matches_current_git_env(root):
        return env
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Draft CHANGELOG.md [Unreleased] notes from staged files.")
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--changelog-path",
        default=None,
        help="Optional explicit changelog path. Defaults to <root>/CHANGELOG.md.",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="Explicit changed file path. Repeatable. When omitted, reads staged files from git.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    changelog_path = Path(args.changelog_path).resolve() if args.changelog_path else root / "CHANGELOG.md"

    changed_files = [path for path in args.file if str(path).strip()]
    if not changed_files:
        changed_files = staged_files(root)
    if not changed_files:
        changed_files = working_tree_files(root)

    result = draft_changelog(changelog_path, changed_files)
    print(result)
    return 0


def staged_files(root: Path) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "diff.renames=false",
            "diff",
            "--cached",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "--diff-filter=ACMRDTUXB",
            "--",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=git_command_env(root),
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or "Failed to collect staged files.")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def working_tree_files(root: Path) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "diff.renames=false",
            "diff",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "HEAD",
            "--",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=git_command_env(root),
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def draft_changelog(changelog_path: Path, changed_files: list[str]) -> str:
    if not changelog_path.is_file():
        raise SystemExit(f"Missing changelog: {changelog_path}")

    text = changelog_path.read_text(encoding="utf-8")
    start, end = unreleased_bounds(text)
    unreleased_body = text[start:end].strip()
    if unreleased_body:
        return "CHANGELOG [Unreleased] already has content. Skipped auto-draft."

    normalized_files = dedupe_paths(changed_files)
    if not normalized_files:
        return "No changed files found. Skipped auto-draft."

    draft = render_draft(normalized_files)
    updated = text[:start] + "\n\n" + draft + "\n" + text[end:]
    changelog_path.write_text(updated, encoding="utf-8")
    return f"Auto-drafted CHANGELOG [Unreleased] from {len(normalized_files)} changed files."


def unreleased_bounds(text: str) -> tuple[int, int]:
    header_start = text.find(UNRELEASED_HEADER)
    if header_start < 0:
        raise SystemExit(f"Missing section: {UNRELEASED_HEADER}")
    body_start = header_start + len(UNRELEASED_HEADER)
    next_header = text.find("\n## [", body_start)
    if next_header < 0:
        next_header = len(text)
    return body_start, next_header


def dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in paths:
        path = str(raw).strip().replace("\\", "/")
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def render_draft(changed_files: list[str]) -> str:
    grouped: dict[str, list[str]] = {title: [] for title, _ in SECTION_DEFINITIONS}
    for path in changed_files:
        grouped[classify_path(path)].append(path)

    blocks = [
        render_section(title, summary, grouped[title])
        for title, summary in SECTION_DEFINITIONS
        if grouped[title]
    ]
    return "\n\n".join(blocks)


def classify_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if normalized.startswith(("README", "CONTRIBUTING", "docs/", "LICENSE")):
        return "Docs"
    if normalized.startswith("runtime/"):
        return "Runtime"
    if normalized.startswith("scripts/"):
        return "Scripts"
    if normalized.startswith(("Codex/", "Claude/")):
        return "Skills"
    if normalized.startswith("tests/"):
        return "Tests"
    return "Changed"


def render_section(title: str, summary: str, paths: list[str]) -> str:
    lines = [f"### {title}", "", f"- {summary}:"]
    lines.extend(f"  - `{path}`" for path in paths)
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
