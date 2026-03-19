#!/usr/bin/env python3
"""Deterministic requirement score calculator for analyze skill."""

from __future__ import annotations

import argparse
import json
from typing import Dict

MAX_BY_DIMENSION: Dict[str, int] = {
    "goal_clarity": 3,
    "expected_outcome": 3,
    "scope_boundary": 2,
    "constraints": 2,
}


def _bounded_int(name: str, value: int) -> int:
    max_score = MAX_BY_DIMENSION[name]
    if value < 0 or value > max_score:
        raise ValueError(f"{name} must be in [0, {max_score}], got {value}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute requirement completeness score in a deterministic way."
    )
    parser.add_argument("--goal-clarity", type=int, required=True)
    parser.add_argument("--expected-outcome", type=int, required=True)
    parser.add_argument("--scope-boundary", type=int, required=True)
    parser.add_argument("--constraints", type=int, required=True)
    parser.add_argument("--require-score", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scores = {
        "goal_clarity": _bounded_int("goal_clarity", args.goal_clarity),
        "expected_outcome": _bounded_int("expected_outcome", args.expected_outcome),
        "scope_boundary": _bounded_int("scope_boundary", args.scope_boundary),
        "constraints": _bounded_int("constraints", args.constraints),
    }

    total = sum(scores.values())
    missing_dimensions = [name for name, score in scores.items() if score == 0]

    result = {
        "scores": scores,
        "total": total,
        "max_total": sum(MAX_BY_DIMENSION.values()),
        "require_score": args.require_score,
        "pass": total >= args.require_score,
        "missing_dimensions": missing_dimensions,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
