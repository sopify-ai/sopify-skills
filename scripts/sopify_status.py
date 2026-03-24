#!/usr/bin/env python3
"""Report supported hosts plus current workspace Sopify status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from installer.inspection import build_status_payload, render_status_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show Sopify host support matrix and current workspace state.")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--workspace-root", default=".", help="Workspace root to inspect. Defaults to the current directory.")
    parser.add_argument("--home-root", default=None, help="Optional home root override used for host inspection.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    home_root = Path(args.home_root).expanduser().resolve() if args.home_root else Path.home().expanduser().resolve()
    payload = build_status_payload(home_root=home_root, workspace_root=workspace_root)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_status_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
