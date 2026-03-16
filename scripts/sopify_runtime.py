#!/usr/bin/env python3
"""Default repo-local entry for routing raw user input through Sopify runtime."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.cli import build_runtime_parser, execute_runtime_cli


def main(argv: list[str] | None = None) -> int:
    parser = build_runtime_parser(
        description="Run the default repo-local Sopify runtime entry for raw user input.",
        request_help="Raw user input to route through Sopify runtime.",
    )
    args = parser.parse_args(argv)
    return execute_runtime_cli(
        " ".join(args.request),
        workspace_root=Path(args.workspace_root).resolve(),
        global_config_path=args.global_config_path,
        as_json=args.json,
        no_color=args.no_color,
    )


if __name__ == "__main__":
    raise SystemExit(main())
