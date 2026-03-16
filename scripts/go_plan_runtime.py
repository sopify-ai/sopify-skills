#!/usr/bin/env python3
"""Plan-only helper for repo-local Sopify runtime."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.cli import build_runtime_parser, execute_runtime_cli


def normalize_request(raw_text: str) -> str:
    """Normalize bare planning text into a `~go plan` request."""
    text = raw_text.strip()
    if not text:
        raise ValueError("Planning request cannot be empty")
    lowered = text.lower()
    if lowered.startswith("~go plan"):
        return text
    if text.startswith("~"):
        raise ValueError("go_plan_runtime only accepts bare planning text or `~go plan ...`")
    return f"~go plan {text}"


def main(argv: list[str] | None = None) -> int:
    parser = build_runtime_parser(
        description="Run the repo-local Sopify runtime for the `~go plan` path.",
        request_help="Planning request text, with or without the `~go plan` prefix.",
    )
    args = parser.parse_args(argv)
    return execute_runtime_cli(
        " ".join(args.request),
        workspace_root=Path(args.workspace_root).resolve(),
        global_config_path=args.global_config_path,
        as_json=args.json,
        no_color=args.no_color,
        request_transform=normalize_request,
        require_plan_artifact=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
