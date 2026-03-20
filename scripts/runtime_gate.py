#!/usr/bin/env python3
"""CLI entry for the prompt-level Sopify runtime gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.gate import enter_runtime_gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the prompt-level Sopify runtime gate.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    enter = subparsers.add_parser("enter", help="Run workspace preflight, preload, runtime dispatch, and handoff normalization.")
    enter.add_argument(
        "--workspace-root",
        default=".",
        help="Target workspace root. Defaults to the current directory.",
    )
    enter.add_argument(
        "--request",
        required=True,
        help="Raw user input to route through Sopify runtime.",
    )
    enter.add_argument(
        "--global-config-path",
        default=None,
        help="Optional override for the global sopify config path.",
    )
    enter.add_argument(
        "--payload-manifest-path",
        default=None,
        help="Optional override for the installed payload manifest used by workspace preflight.",
    )
    enter.add_argument(
        "--no-receipt",
        action="store_true",
        help="Skip writing .sopify-skills/state/current_gate_receipt.json.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "enter":
        raise ValueError(f"Unsupported command: {args.command}")

    payload = enter_runtime_gate(
        args.request,
        workspace_root=Path(args.workspace_root).resolve(),
        global_config_path=args.global_config_path,
        payload_manifest_path=args.payload_manifest_path,
        write_receipt=not args.no_receipt,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
