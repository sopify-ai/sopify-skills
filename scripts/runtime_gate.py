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
        "--activation-root",
        default=None,
        help="Optional explicit activation root passed through the ingress contract; use this to recover from ROOT_CONFIRM_REQUIRED by choosing the current directory, the repository root, or another directory.",
    )
    enter.add_argument(
        "--interaction-mode",
        choices=("interactive", "non_interactive"),
        default=None,
        help="Optional host-provided interaction mode used by first-write policy.",
    )
    enter.add_argument(
        "--payload-root",
        default=None,
        help="Optional explicit payload root passed through the ingress contract. This is the only explicit field that selects a payload bundle.",
    )
    enter.add_argument(
        "--host-id",
        default=None,
        help="Optional explicit host id passed through the ingress contract. Audit-only: it validates the selected payload but does not choose one by itself.",
    )
    enter.add_argument(
        "--requested-root",
        default=None,
        help="Optional host-requested root used for observability only.",
    )
    enter.add_argument(
        "--session-id",
        default=None,
        help="Optional stable session id reused by the host across turns.",
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
        activation_root=args.activation_root,
        interaction_mode=args.interaction_mode,
        payload_root=args.payload_root,
        host_id=args.host_id,
        requested_root=args.requested_root,
        session_id=args.session_id,
        write_receipt=not args.no_receipt,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
