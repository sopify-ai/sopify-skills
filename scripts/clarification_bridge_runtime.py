#!/usr/bin/env python3
"""Internal helper for host-side clarification bridges.

This helper does not replace the default Sopify runtime entry. Hosts may call
it only after `current_handoff.json.required_host_action == answer_questions`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.clarification_bridge import (
    ClarificationBridgeError,
    build_cli_clarification_bridge,
    build_clarification_submission,
    load_clarification_bridge_context,
    prompt_cli_clarification_submission,
    write_clarification_submission,
)
from runtime.cli_interactive import TerminalInteractiveSession
from runtime.config import ConfigError, load_runtime_config


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the internal clarification bridge helper."""
    parser = argparse.ArgumentParser(description="Inspect or write Sopify clarification bridge state.")
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Target workspace root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--global-config-path",
        default=None,
        help="Optional override for the global sopify config path.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional session id used to resolve session-scoped review checkpoints.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("inspect", help="Build the CLI clarification bridge contract.")

    submit_parser = subparsers.add_parser("submit", help="Write a structured host clarification response.")
    submit_parser.add_argument("--answers-json", required=True, help="Structured answers as a JSON object.")
    submit_parser.add_argument("--source", default=None, help="Optional explicit submission source.")
    submit_parser.add_argument("--message", default="", help="Optional submission message.")

    prompt_parser = subparsers.add_parser("prompt", help="Collect a response through the CLI bridge.")
    prompt_parser.add_argument("--renderer", choices=("auto", "text", "interactive", "inquirer"), default="auto")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace_root = Path(args.workspace_root).resolve()

    try:
        config = load_runtime_config(workspace_root, global_config_path=args.global_config_path)
        if args.command == "inspect":
            payload = _inspect_bridge(config=config, session_id=args.session_id)
        elif args.command == "submit":
            payload = _submit_bridge(
                config=config,
                session_id=args.session_id,
                answers_json=args.answers_json,
                source=args.source,
                message=args.message,
            )
        else:
            payload = _prompt_bridge(config=config, session_id=args.session_id, renderer=args.renderer)
    except (ConfigError, ClarificationBridgeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _inspect_bridge(*, config, session_id: str | None) -> dict[str, object]:
    context = load_clarification_bridge_context(config=config, session_id=session_id)
    bridge = build_cli_clarification_bridge(context, language=config.language)
    return {
        "status": "ready",
        "bridge": bridge,
    }


def _submit_bridge(
    *,
    config,
    session_id: str | None,
    answers_json: str,
    source: str | None,
    message: str,
) -> dict[str, object]:
    context = load_clarification_bridge_context(config=config, session_id=session_id)
    answers = json.loads(answers_json)
    if not isinstance(answers, dict):
        raise ValueError("answers-json must decode to an object")

    submission = build_clarification_submission(
        context.clarification_state,
        answers=answers,
        source=source or "cli",
        language=config.language,
        message=message,
    )
    updated = write_clarification_submission(config=config, submission=submission, session_id=session_id)
    return {
        "status": "written",
        "clarification_id": updated.clarification_id,
        "clarification_status": updated.status,
        "submission": submission,
        "answer_keys": sorted(submission["response_fields"].keys()),
    }


def _prompt_bridge(*, config, session_id: str | None, renderer: str) -> dict[str, object]:
    def _stderr_reader(prompt: str) -> str:
        if prompt:
            print(prompt, end="", file=sys.stderr, flush=True)
        line = sys.stdin.readline()
        if line == "":
            return ""
        return line.rstrip("\n")

    submission, used_renderer = prompt_cli_clarification_submission(
        config=config,
        session_id=session_id,
        renderer=renderer,
        input_reader=_stderr_reader,
        output_writer=lambda message: print(message, file=sys.stderr),
        interactive_session_factory=lambda: TerminalInteractiveSession(
            input_stream=sys.stdin,
            output_stream=sys.stderr,
        ),
    )
    return {
        "status": "written",
        "used_renderer": used_renderer,
        "submission": submission,
        "answer_keys": sorted(submission["response_fields"].keys()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
