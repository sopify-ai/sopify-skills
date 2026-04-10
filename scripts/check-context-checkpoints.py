#!/usr/bin/env python3
"""Validate Plan A checkpoint governance metadata and freeze contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Iterable


PLAN_A_TASKS_PATH = Path(
    ".sopify-skills/plan/20260403_plan-a-risk-adaptive-interruption/tasks.md"
)
PR_TEMPLATE_PATH = Path(".github/pull_request_template.md")
CI_WORKFLOW_PATH = Path(".github/workflows/ci.yml")
COMMIT_HOOK_PATH = Path(".githooks/commit-msg")
PREFLIGHT_PATH = Path("scripts/release-preflight.sh")

ALLOWED_CONTEXT_CHECKPOINTS = ("A", "B", "C", "D")
REQUIRED_PR_LABELS = (
    "Context-Checkpoint:",
    "Decision IDs:",
    "Blocked by:",
    "Out-of-scope touched:",
)

CHECKPOINT_TASK_REQUIREMENTS = {
    "A": ("15.4", "15.8", "15.9", "18.6", "19.5"),
    "B": ("5.1", "5.2", "5.3", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "14.8", "15.5", "15.10"),
    "C": ("7.1", "7.2", "7.3", "7.4", "15.6", "15.11", "17.4"),
    "D": ("12.1", "12.2", "12.3", "12.4", "13.1", "13.2", "13.3", "13.4", "15.7"),
}

CHECKPOINT_FILE_REQUIREMENTS = {
    "A": (
        "runtime/contracts/decision_tables.yaml",
        "runtime/contracts/decision_tables.schema.json",
        "runtime/contracts/failure_recovery_table.schema.json",
        "runtime/contracts/host_message_templates.schema.json",
        "runtime/decision_tables.py",
        "runtime/failure_recovery.py",
        "runtime/message_templates.py",
        "runtime/state.py",
        "scripts/check-fail-close-contract.py",
        "tests/fixtures/context_fail_close_contract.yaml",
        "tests/fixtures/fail_close_case_matrix.yaml",
        "tests/test_runtime_decision_tables.py",
        "tests/test_runtime_failure_recovery.py",
    ),
    "B": (
        "runtime/context_v1_scope.py",
        "tests/fixtures/sample_invariant_gate_matrix.yaml",
        "tests/test_context_v1_scope.py",
        "tests/test_runtime_engine.py",
        "tests/test_runtime_sample_invariant_gate.py",
    ),
    "C": (
        "runtime/action_projection.py",
        "runtime/context_builder.py",
        "runtime/context_v1_scope.py",
        "runtime/deterministic_guard.py",
        "runtime/handoff.py",
        "runtime/resolution_planner.py",
        "tests/test_context_v1_scope.py",
        "tests/test_runtime_engine.py",
    ),
    "D": (
        "runtime/sidecar_classifier_boundary.py",
        "runtime/vnext_phase_boundary.py",
    ),
}

CHECKPOINT_SCOPE_PATTERNS = {
    "A": (
        ".sopify-skills/plan/20260403_plan-a-risk-adaptive-interruption/",
        "runtime/contracts/",
        "runtime/decision_tables.py",
        "runtime/failure_recovery.py",
        "runtime/message_templates.py",
        "runtime/state.py",
        "scripts/check-fail-close-contract.py",
        "tests/fixtures/context_fail_close_contract.yaml",
        "tests/fixtures/fail_close_case_matrix.yaml",
        "tests/test_runtime_decision_tables.py",
        "tests/test_runtime_failure_recovery.py",
    ),
    "B": (
        ".sopify-skills/plan/20260403_plan-a-risk-adaptive-interruption/",
        "runtime/handoff.py",
        "runtime/context_v1_scope.py",
        "tests/fixtures/sample_invariant_gate_matrix.yaml",
        "tests/test_context_v1_scope.py",
        "tests/test_runtime_engine.py",
        "tests/test_runtime_sample_invariant_gate.py",
    ),
    "C": (
        ".sopify-skills/plan/20260403_plan-a-risk-adaptive-interruption/",
        "runtime/action_projection.py",
        "runtime/context_builder.py",
        "runtime/context_v1_scope.py",
        "runtime/deterministic_guard.py",
        "runtime/handoff.py",
        "runtime/resolution_planner.py",
        "tests/test_context_v1_scope.py",
        "tests/test_runtime_engine.py",
    ),
    "D": (
        ".sopify-skills/plan/20260403_plan-a-risk-adaptive-interruption/",
        "runtime/sidecar_classifier_boundary.py",
        "runtime/vnext_phase_boundary.py",
    ),
}

GOVERNANCE_SCOPE_PATTERNS = (
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    ".githooks/commit-msg",
    "scripts/check-context-checkpoints.py",
    "tests/test_context_checkpoints.py",
    "tests/test_release_hooks.py",
    "CONTRIBUTING.md",
    "CONTRIBUTING_CN.md",
)

PR_FIELD_PATTERN = re.compile(
    r"(?mi)^(Context-Checkpoint|Decision IDs|Blocked by|Out-of-scope touched):\s*(.*?)\s*$"
)
TASK_STATUS_PATTERN = re.compile(r"^- \[(?P<status>[ x!~-])\] (?P<task_id>\d+\.\d+)\b", re.MULTILINE)


class ValidationError(RuntimeError):
    """Raised when checkpoint governance validation fails."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    repo = subparsers.add_parser("repo", help="Validate repository-level checkpoint governance wiring.")
    repo.add_argument("--root", default=".", help="Repository root")
    repo.add_argument(
        "--checkpoints",
        default="A,B,C",
        help="Comma-separated checkpoints to validate in repo mode (default: A,B,C)",
    )

    commit_msg = subparsers.add_parser("commit-msg", help="Validate Context-Checkpoint trailer for scoped commits.")
    commit_msg.add_argument("--root", default=".", help="Repository root")
    commit_msg.add_argument("--message-file", required=True, help="Path to the commit message file")
    add_files_args(commit_msg)

    pr_body = subparsers.add_parser("pr-body", help="Validate PR metadata for scoped changes.")
    pr_body.add_argument("--root", default=".", help="Repository root")
    pr_body.add_argument("--body-file", help="Path to a PR body file")
    pr_body.add_argument("--event-path", help="Path to a GitHub event payload")
    pr_body.add_argument("--base-sha", help="Base revision used to compute changed files")
    pr_body.add_argument("--head-sha", help="Head revision used to compute changed files")
    add_files_args(pr_body)

    return parser.parse_args(argv)


def add_files_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--files", action="append", default=[], help="Changed file path")
    parser.add_argument("--files-file", help="File containing newline-delimited changed file paths")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "repo":
            checkpoints = tuple(
                checkpoint.strip().upper()
                for checkpoint in str(args.checkpoints or "").split(",")
                if checkpoint.strip()
            )
            validate_repo(root, checkpoints)
        elif args.command == "commit-msg":
            validate_commit_message(
                root=root,
                message_file=Path(args.message_file),
                changed_files=collect_changed_files(
                    root,
                    explicit_files=args.files,
                    files_file=args.files_file,
                    staged_fallback=True,
                ),
            )
        elif args.command == "pr-body":
            validate_pr_body(
                root=root,
                body=_load_pr_body(args),
                changed_files=collect_changed_files(
                    root,
                    explicit_files=args.files,
                    files_file=args.files_file,
                    base_sha=args.base_sha,
                    head_sha=args.head_sha,
                ),
            )
        else:
            raise ValidationError(f"Unsupported command: {args.command}")
    except ValidationError as exc:
        print(f"[context-checkpoints] {exc}", file=sys.stderr)
        return 1
    return 0


def validate_repo(root: Path, checkpoints: tuple[str, ...]) -> None:
    tasks_path = root / PLAN_A_TASKS_PATH
    if not tasks_path.exists():
        print(
            "[context-checkpoints] Plan A tasks file not found; skipping repo checkpoint validation.",
            file=sys.stderr,
        )
        return

    _require_file_with_labels(root / PR_TEMPLATE_PATH, REQUIRED_PR_LABELS, "PR template")
    _require_file_contains(root / COMMIT_HOOK_PATH, "check-context-checkpoints.py", "commit-msg hook")
    _require_file_contains(root / COMMIT_HOOK_PATH, "commit-msg --root", "commit-msg hook")
    _require_file_contains(root / PREFLIGHT_PATH, "check-context-checkpoints.py", "release preflight")
    _require_file_contains(root / PREFLIGHT_PATH, "repo --root", "release preflight")
    _require_file_contains(root / CI_WORKFLOW_PATH, "check-context-checkpoints.py repo", "CI workflow")
    _require_file_contains(root / CI_WORKFLOW_PATH, "check-context-checkpoints.py pr-body", "CI workflow")

    task_status = parse_task_statuses(tasks_path)
    for checkpoint in checkpoints:
        if checkpoint not in ALLOWED_CONTEXT_CHECKPOINTS:
            raise ValidationError(f"Unsupported checkpoint selector {checkpoint!r}")
        missing_tasks = [
            task_id for task_id in CHECKPOINT_TASK_REQUIREMENTS[checkpoint] if task_status.get(task_id) != "x"
        ]
        if missing_tasks:
            raise ValidationError(
                f"Checkpoint {checkpoint} is not frozen in tasks.md; missing completed tasks: {', '.join(missing_tasks)}"
            )
        missing_files = [
            path for path in CHECKPOINT_FILE_REQUIREMENTS[checkpoint] if not (root / path).exists()
        ]
        if missing_files:
            raise ValidationError(
                f"Checkpoint {checkpoint} is missing required repo assets: {', '.join(missing_files)}"
            )


def validate_commit_message(*, root: Path, message_file: Path, changed_files: tuple[str, ...]) -> None:
    relevant, allowed_candidates = resolve_checkpoint_scope(changed_files)
    if not relevant:
        return

    message_text = message_file.read_text(encoding="utf-8")
    checkpoint = extract_context_checkpoint(message_text)
    if checkpoint is None:
        hint = _allowed_checkpoint_hint(allowed_candidates)
        raise ValidationError(
            f"Scoped Plan A commit requires a Context-Checkpoint trailer ({hint})"
        )
    if checkpoint not in allowed_candidates:
        hint = _allowed_checkpoint_hint(allowed_candidates)
        raise ValidationError(
            f"Context-Checkpoint {checkpoint!r} does not match the touched Plan A scope ({hint})"
        )


def validate_pr_body(*, root: Path, body: str, changed_files: tuple[str, ...]) -> None:
    relevant, allowed_candidates = resolve_checkpoint_scope(changed_files)
    if not relevant:
        return
    if not body.strip():
        raise ValidationError("Scoped Plan A pull request must include checkpoint metadata in the PR body")

    fields = parse_pr_fields(body)
    missing = [label.rstrip(":") for label in REQUIRED_PR_LABELS if label.rstrip(":") not in fields]
    if missing:
        raise ValidationError(
            "Scoped Plan A pull request is missing required metadata fields: " + ", ".join(missing)
        )

    checkpoint = normalize_context_checkpoint(fields["Context-Checkpoint"])
    if checkpoint is None:
        hint = _allowed_checkpoint_hint(allowed_candidates)
        raise ValidationError(
            f"PR field Context-Checkpoint must be one of {hint}"
        )
    if checkpoint not in allowed_candidates:
        hint = _allowed_checkpoint_hint(allowed_candidates)
        raise ValidationError(
            f"PR field Context-Checkpoint {checkpoint!r} does not match touched Plan A scope ({hint})"
        )

    for key in ("Decision IDs", "Blocked by", "Out-of-scope touched"):
        value = fields[key].strip()
        if not value or value.lower() in {"<required>", "<fill>", "todo", "tbd"}:
            raise ValidationError(f"PR field {key} must be filled")


def collect_changed_files(
    root: Path,
    *,
    explicit_files: Iterable[str],
    files_file: str | None,
    staged_fallback: bool = False,
    base_sha: str | None = None,
    head_sha: str | None = None,
) -> tuple[str, ...]:
    normalized: list[str] = []
    for path in explicit_files:
        normalized.append(normalize_repo_path(path))

    if files_file:
        for line in Path(files_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                normalized.append(normalize_repo_path(line))

    if not normalized and base_sha and head_sha:
        normalized.extend(git_changed_files(root, base_sha, head_sha))

    if not normalized and staged_fallback:
        normalized.extend(git_staged_files(root))

    deduped: list[str] = []
    seen: set[str] = set()
    for path in normalized:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return tuple(deduped)


def git_staged_files(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRDTUXB", "--"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [normalize_repo_path(line) for line in completed.stdout.splitlines() if line.strip()]


def git_changed_files(root: Path, base_sha: str, head_sha: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", base_sha, head_sha, "--"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [normalize_repo_path(line) for line in completed.stdout.splitlines() if line.strip()]


def resolve_checkpoint_scope(changed_files: Iterable[str]) -> tuple[bool, set[str]]:
    matched_relevant = False
    matched_governance = False
    inferred: set[str] = set()
    for path in changed_files:
        normalized = normalize_repo_path(path)
        for checkpoint, patterns in CHECKPOINT_SCOPE_PATTERNS.items():
            if any(path_matches(normalized, pattern) for pattern in patterns):
                inferred.add(checkpoint)
                matched_relevant = True
        if any(path_matches(normalized, pattern) for pattern in GOVERNANCE_SCOPE_PATTERNS):
            matched_governance = True
            matched_relevant = True
    if inferred:
        return True, inferred
    if matched_governance:
        return True, set(ALLOWED_CONTEXT_CHECKPOINTS)
    return False, set()


def parse_task_statuses(tasks_path: Path) -> dict[str, str]:
    text = tasks_path.read_text(encoding="utf-8")
    statuses: dict[str, str] = {}
    for match in TASK_STATUS_PATTERN.finditer(text):
        statuses[match.group("task_id")] = match.group("status")
    return statuses


def parse_pr_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in PR_FIELD_PATTERN.findall(body):
        fields[key] = value.strip()
    return fields


def extract_context_checkpoint(message_text: str) -> str | None:
    matches = re.findall(r"(?mi)^Context-Checkpoint:\s*(.+?)\s*$", message_text)
    if not matches:
        return None
    return normalize_context_checkpoint(matches[-1])


def normalize_context_checkpoint(raw_value: str) -> str | None:
    normalized = str(raw_value or "").strip().upper()
    if normalized not in ALLOWED_CONTEXT_CHECKPOINTS:
        return None
    return normalized


def normalize_repo_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise ValidationError("Changed file path must be non-empty")
    collapsed = str(PurePosixPath(normalized))
    if collapsed in {"", "."} or collapsed.startswith("../"):
        raise ValidationError(f"Changed file path escapes workspace root: {path!r}")
    return collapsed


def path_matches(path: str, pattern: str) -> bool:
    normalized_pattern = normalize_repo_path(pattern)
    if normalized_pattern.endswith("/"):
        return path.startswith(normalized_pattern)
    return path == normalized_pattern or path.startswith(normalized_pattern + "/")


def _require_file_with_labels(path: Path, labels: tuple[str, ...], label: str) -> None:
    if not path.exists():
        raise ValidationError(f"Missing {label}: {path}")
    text = path.read_text(encoding="utf-8")
    missing = [item for item in labels if item not in text]
    if missing:
        raise ValidationError(f"{label} is missing required labels: {', '.join(missing)}")


def _require_file_contains(path: Path, snippet: str, label: str) -> None:
    if not path.exists():
        raise ValidationError(f"Missing {label}: {path}")
    text = path.read_text(encoding="utf-8")
    if snippet not in text:
        raise ValidationError(f"{label} is missing required snippet: {snippet}")


def _allowed_checkpoint_hint(candidates: set[str]) -> str:
    ordered = [checkpoint for checkpoint in ALLOWED_CONTEXT_CHECKPOINTS if checkpoint in candidates]
    if not ordered:
        ordered = list(ALLOWED_CONTEXT_CHECKPOINTS)
    return " / ".join(ordered)


def _load_pr_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    if args.event_path:
        payload = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
        pull_request = payload.get("pull_request") if isinstance(payload, dict) else None
        if isinstance(pull_request, dict):
            return str(pull_request.get("body") or "")
    return ""


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
