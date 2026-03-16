"""Shared CLI helpers for repo-local Sopify runtime entry scripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Mapping, Optional

from .config import ConfigError, load_runtime_config
from .engine import run_runtime
from .output import render_runtime_error, render_runtime_output

RequestTransform = Callable[[str], str]


def build_runtime_parser(*, description: str, request_help: str) -> argparse.ArgumentParser:
    """Build a standard argument parser for repo-local runtime scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "request",
        nargs="+",
        help=request_help,
    )
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
        "--json",
        action="store_true",
        help="Print the raw runtime result as JSON.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable title coloring in rendered output.",
    )
    return parser


def execute_runtime_cli(
    raw_request: str,
    *,
    workspace_root: str | Path = ".",
    global_config_path: str | Path | None = None,
    as_json: bool = False,
    no_color: bool = False,
    request_transform: RequestTransform | None = None,
    require_plan_artifact: bool = False,
    runtime_payloads: Optional[Mapping[str, Mapping[str, object]]] = None,
) -> int:
    """Execute a repo-local runtime request and print the rendered result."""
    config = None

    try:
        request = raw_request.strip()
        if not request:
            raise ValueError("Runtime request cannot be empty")
        if request_transform is not None:
            request = request_transform(request)
        config = load_runtime_config(workspace_root, global_config_path=global_config_path)
        result = run_runtime(
            request,
            workspace_root=workspace_root,
            global_config_path=global_config_path,
            runtime_payloads=runtime_payloads,
        )
    except (ConfigError, ValueError) as exc:
        print(
            render_runtime_error(
                str(exc),
                brand=config.brand if config is not None else "sopify-ai",
                language=config.language if config is not None else "zh-CN",
                title_color=config.title_color if config is not None else "none",
                use_color=not no_color,
            )
        )
        return 1
    except Exception as exc:  # pragma: no cover - safety net for manual CLI use
        print(
            render_runtime_error(
                f"Unexpected runtime failure: {exc}",
                brand=config.brand if config is not None else "sopify-ai",
                language=config.language if config is not None else "zh-CN",
                title_color=config.title_color if config is not None else "none",
                use_color=not no_color,
            )
        )
        return 1

    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(
            render_runtime_output(
                result,
                brand=config.brand,
                language=config.language,
                title_color=config.title_color,
                use_color=not no_color,
            )
        )

    if require_plan_artifact and result.plan_artifact is None:
        return 1
    return 0
