#!/usr/bin/env python3
"""Deterministic plan-level selector for design skill."""

from __future__ import annotations

import argparse
import json
from typing import List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select plan level based on explicit change signals."
    )
    parser.add_argument("--file-count", type=int, required=True)
    parser.add_argument("--architecture-change", action="store_true")
    parser.add_argument("--major-refactor", action="store_true")
    parser.add_argument("--new-system", action="store_true")
    parser.add_argument("--new-feature", action="store_true")
    parser.add_argument("--cross-module", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reasons: List[str] = []

    if args.architecture_change or args.major_refactor or args.new_system:
        level = "full"
        if args.architecture_change:
            reasons.append("architecture_change")
        if args.major_refactor:
            reasons.append("major_refactor")
        if args.new_system:
            reasons.append("new_system")
    elif args.file_count > 5 or args.new_feature or args.cross_module:
        level = "standard"
        if args.file_count > 5:
            reasons.append("file_count_gt_5")
        if args.new_feature:
            reasons.append("new_feature")
        if args.cross_module:
            reasons.append("cross_module")
    elif 3 <= args.file_count <= 5:
        level = "light"
        reasons.append("file_count_between_3_and_5")
    else:
        level = "light"
        reasons.append("default_light_for_small_scope")

    result = {
        "plan_level": level,
        "file_count": args.file_count,
        "reasons": reasons,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
