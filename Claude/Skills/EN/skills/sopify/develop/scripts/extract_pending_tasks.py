#!/usr/bin/env python3
"""Extract deterministic task status summary from a plan markdown file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List

TASK_PATTERN = re.compile(r"^\s*-\s*\[(?P<status>[ x!\-])\]\s*(?P<text>.+?)\s*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract pending/completed/blocked/skipped tasks from markdown."
    )
    parser.add_argument("--tasks-file", required=True, help="Path to tasks.md or plan.md")
    return parser.parse_args()


def classify_status(raw: str) -> str:
    if raw == " ":
        return "pending"
    if raw == "x":
        return "completed"
    if raw == "!":
        return "blocked"
    if raw == "-":
        return "skipped"
    return "unknown"


def main() -> int:
    args = parse_args()
    path = Path(args.tasks_file)
    lines = path.read_text(encoding="utf-8").splitlines()

    tasks: List[Dict[str, str]] = []
    counts: Dict[str, int] = {
        "pending": 0,
        "completed": 0,
        "blocked": 0,
        "skipped": 0,
    }

    for idx, line in enumerate(lines, start=1):
        match = TASK_PATTERN.match(line)
        if not match:
            continue
        status_key = classify_status(match.group("status"))
        text = match.group("text")
        tasks.append({"line": idx, "status": status_key, "text": text})
        if status_key in counts:
            counts[status_key] += 1

    result = {
        "tasks_file": str(path),
        "counts": counts,
        "pending_tasks": [task for task in tasks if task["status"] == "pending"],
        "all_tasks": tasks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
