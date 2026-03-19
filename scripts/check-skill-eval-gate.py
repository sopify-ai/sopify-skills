#!/usr/bin/env python3
"""Run deterministic skill-eval baselines and enforce SLO quality gates."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.config import load_runtime_config
from runtime.router import Router
from runtime.skill_registry import SkillRegistry
from runtime.state import StateStore
from scripts.model_compare_runtime import make_default_candidate, run_model_compare_runtime


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _dump_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _render_manifest(skill_id: str, manifest: Mapping[str, Any]) -> str:
    merged: dict[str, Any] = {"id": skill_id}
    merged.update(dict(manifest))
    lines: list[str] = []
    for key, value in merged.items():
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_dump_scalar(item)}")
            continue
        lines.append(f"{key}: {_dump_scalar(value)}")
    return "\n".join(lines) + "\n"


def _write_skill(
    *,
    root: Path,
    skill_id: str,
    description: str,
    manifest: Mapping[str, Any] | None = None,
    required_paths: Sequence[str] = (),
) -> Path:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: {description}\n---\n\n# {skill_id}\n",
        encoding="utf-8",
    )
    (skill_dir / "skill.yaml").write_text(
        _render_manifest(skill_id, manifest or {"mode": "advisory"}),
        encoding="utf-8",
    )
    for relative in required_paths:
        path = skill_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {skill_id}: {relative}\n", encoding="utf-8")
    return skill_dir


def _evaluate_discovery(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    passed = 0

    for case in cases:
        case_id = str(case.get("id") or "unknown_discovery_case")
        case_ok = True
        failures: list[str] = []

        with tempfile.TemporaryDirectory(prefix="skill-eval-discovery-") as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            user_home = Path(temp_dir) / "home"
            workspace.mkdir(parents=True, exist_ok=True)
            user_home.mkdir(parents=True, exist_ok=True)

            for spec in case.get("workspace_skills", []):
                _write_skill(
                    root=workspace / str(spec.get("root") or "skills"),
                    skill_id=str(spec.get("skill_id") or "unknown"),
                    description=str(spec.get("description") or ""),
                    manifest=dict(spec.get("manifest") or {}),
                    required_paths=tuple(spec.get("required_paths") or ()),
                )

            for spec in case.get("user_skills", []):
                _write_skill(
                    root=user_home / str(spec.get("root") or ".codex/skills"),
                    skill_id=str(spec.get("skill_id") or "unknown"),
                    description=str(spec.get("description") or ""),
                    manifest=dict(spec.get("manifest") or {}),
                    required_paths=tuple(spec.get("required_paths") or ()),
                )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=user_home).discover()
            by_id = {skill.skill_id: skill for skill in skills}

            for assertion in case.get("assertions", []):
                skill_id = str(assertion.get("skill_id") or "")
                skill = by_id.get(skill_id)
                if skill is None:
                    case_ok = False
                    failures.append(f"missing skill_id={skill_id}")
                    continue

                expected_source = assertion.get("source")
                if isinstance(expected_source, str) and expected_source and skill.source != expected_source:
                    case_ok = False
                    failures.append(
                        f"skill_id={skill_id} source mismatch: expected={expected_source}, actual={skill.source}"
                    )

                expected_description = assertion.get("description")
                if isinstance(expected_description, str) and expected_description and skill.description != expected_description:
                    case_ok = False
                    failures.append(
                        "skill_id="
                        f"{skill_id} description mismatch: expected={expected_description}, actual={skill.description}"
                    )

        if case_ok:
            passed += 1
        results.append(
            {
                "id": case_id,
                "passed": case_ok,
                "failures": failures,
            }
        )

    total = len(results)
    pass_rate = (passed / total) if total else 1.0
    return {
        "cases_total": total,
        "cases_passed": passed,
        "pass_rate": pass_rate,
        "cases": results,
    }


def _evaluate_selection(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="skill-eval-selection-") as temp_dir:
        workspace = Path(temp_dir) / "workspace"
        user_home = Path(temp_dir) / "home"
        workspace.mkdir(parents=True, exist_ok=True)
        user_home.mkdir(parents=True, exist_ok=True)

        config = load_runtime_config(workspace)
        store = StateStore(config)
        store.ensure()
        skills = SkillRegistry(config, user_home=user_home).discover()
        router = Router(config, state_store=store)

        case_results: list[dict[str, Any]] = []
        positive_total = 0
        positive_miss = 0
        negative_total = 0
        negative_false_trigger = 0
        hits = 0

        for case in cases:
            case_id = str(case.get("id") or "unknown_selection_case")
            request = str(case.get("request") or "")
            expected_route = str(case.get("expected_route") or "")
            expected_candidates = tuple(str(item) for item in (case.get("expected_candidate_skills") or ()) if str(item))
            expectation = str(case.get("expectation") or "positive").lower()
            target_skill = str(case.get("target_skill") or "")

            decision = router.classify(request, skills=skills)
            route_ok = decision.route_name == expected_route
            candidate_ok = set(expected_candidates).issubset(set(decision.candidate_skill_ids))
            case_hit = route_ok and candidate_ok

            if case_hit:
                hits += 1

            if expectation == "negative":
                negative_total += 1
                is_false_trigger = (not route_ok) or (target_skill in decision.candidate_skill_ids)
                if is_false_trigger:
                    negative_false_trigger += 1
            else:
                positive_total += 1
                if not case_hit:
                    positive_miss += 1

            case_results.append(
                {
                    "id": case_id,
                    "request": request,
                    "expectation": expectation,
                    "expected_route": expected_route,
                    "actual_route": decision.route_name,
                    "expected_candidate_skills": list(expected_candidates),
                    "actual_candidate_skills": list(decision.candidate_skill_ids),
                    "hit": case_hit,
                }
            )

    total = len(case_results)
    hit_rate = (hits / total) if total else 1.0
    miss_trigger_rate = (positive_miss / positive_total) if positive_total else 0.0
    false_trigger_rate = (negative_false_trigger / negative_total) if negative_total else 0.0

    return {
        "cases_total": total,
        "cases_hit": hits,
        "hit_rate": hit_rate,
        "positive_total": positive_total,
        "positive_miss": positive_miss,
        "miss_trigger_rate": miss_trigger_rate,
        "negative_total": negative_total,
        "negative_false_trigger": negative_false_trigger,
        "false_trigger_rate": false_trigger_rate,
        "cases": case_results,
    }


def _evaluate_navigation(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    passed = 0

    for case in cases:
        case_id = str(case.get("id") or "unknown_navigation_case")
        case_ok = True
        failures: list[str] = []

        with tempfile.TemporaryDirectory(prefix="skill-eval-navigation-") as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            user_home = Path(temp_dir) / "home"
            workspace.mkdir(parents=True, exist_ok=True)
            user_home.mkdir(parents=True, exist_ok=True)

            root = workspace / str(case.get("root") or ".agents/skills")
            skill_id = str(case.get("skill_id") or "nav-skill")
            description = str(case.get("description") or "navigation case")
            manifest = dict(case.get("manifest") or {})
            required_paths = tuple(str(item) for item in (case.get("required_paths") or ()) if str(item))
            skill_dir = _write_skill(
                root=root,
                skill_id=skill_id,
                description=description,
                manifest=manifest,
                required_paths=required_paths,
            )

            config = load_runtime_config(workspace)
            skills = SkillRegistry(config, user_home=user_home).discover()
            skill = next((item for item in skills if item.skill_id == skill_id), None)
            if skill is None:
                case_ok = False
                failures.append(f"missing skill_id={skill_id}")
            else:
                assertions = dict(case.get("assertions") or {})
                expected_source = assertions.get("source")
                if isinstance(expected_source, str) and expected_source and skill.source != expected_source:
                    case_ok = False
                    failures.append(
                        f"source mismatch: expected={expected_source}, actual={skill.source}"
                    )

                runtime_entry_required = bool(assertions.get("runtime_entry_required", False))
                if runtime_entry_required and skill.runtime_entry is None:
                    case_ok = False
                    failures.append("runtime_entry is required but missing")
                if not runtime_entry_required and skill.runtime_entry is not None:
                    case_ok = False
                    failures.append("runtime_entry is not expected but present")

                if skill.path.resolve() != (skill_dir / "SKILL.md").resolve():
                    case_ok = False
                    failures.append("SKILL.md path mismatch")

            for relative in required_paths:
                if not (skill_dir / relative).exists():
                    case_ok = False
                    failures.append(f"missing required path: {relative}")

        if case_ok:
            passed += 1
        case_results.append(
            {
                "id": case_id,
                "passed": case_ok,
                "failures": failures,
            }
        )

    total = len(case_results)
    pass_rate = (passed / total) if total else 1.0
    return {
        "cases_total": total,
        "cases_passed": passed,
        "pass_rate": pass_rate,
        "cases": case_results,
    }


def _reason_code_set(reasons: Sequence[str]) -> set[str]:
    codes: set[str] = set()
    for reason in reasons:
        head = reason.split(":", 1)[0].strip()
        if head:
            codes.add(head)
    return codes


def _evaluate_cross_model(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    total_results = 0
    total_success = 0
    drift_numerator = 0
    drift_denominator = 0

    for case in cases:
        case_id = str(case.get("id") or "unknown_cross_model_case")
        question = str(case.get("question") or "compare baseline")
        config = dict(case.get("config") or {})
        env_map = {str(key): str(value) for key, value in dict(case.get("env") or {}).items()}
        answers = {str(key): str(value) for key, value in dict(case.get("answers") or {}).items()}
        min_results = int(case.get("min_results") or 1)
        required_reason_codes = {str(item) for item in (case.get("required_reason_codes") or ()) if str(item)}
        default_id = str(case.get("default_candidate_id") or "session_default")
        default_model = str(case.get("default_model") or "session-default")

        def model_caller(candidate: Any, payload: Mapping[str, Any], timeout_sec: int) -> str:
            _ = payload
            _ = timeout_sec
            return answers.get(candidate.id, f"fallback-answer:{candidate.id}")

        output = run_model_compare_runtime(
            question=question,
            multi_model_config=config,
            model_caller=model_caller,
            workspace_root=REPO_ROOT,
            default_candidate=make_default_candidate(candidate_id=default_id, model=default_model),
            env=env_map,
        )

        successful = [result for result in output.results if result.status == "success"]
        total_results += len(output.results)
        total_success += len(successful)

        default_result = next((result for result in successful if result.candidate_id == default_id), None)
        non_default_success = [result for result in successful if result.candidate_id != default_id]
        if default_result is not None and non_default_success:
            mismatch = sum(
                1
                for result in non_default_success
                if result.answer.strip() != default_result.answer.strip()
            )
            drift_numerator += mismatch
            drift_denominator += len(non_default_success)

        reason_codes = _reason_code_set(output.fallback_reasons)
        missing_reasons = sorted(required_reason_codes - reason_codes)
        case_passed = (len(output.results) >= min_results) and (not missing_reasons)

        case_results.append(
            {
                "id": case_id,
                "passed": case_passed,
                "results": [result.to_dict() for result in output.results],
                "fallback_reasons": list(output.fallback_reasons),
                "required_reason_codes": sorted(required_reason_codes),
                "missing_reason_codes": missing_reasons,
            }
        )

    success_rate = (total_success / total_results) if total_results else 0.0
    drift_rate = (drift_numerator / drift_denominator) if drift_denominator else 0.0
    return {
        "cases_total": len(case_results),
        "success_rate": success_rate,
        "drift_rate": drift_rate,
        "cases": case_results,
    }


def _apply_quality_gate(
    *,
    report: Mapping[str, Any],
    slo: Mapping[str, Any],
) -> list[str]:
    violations: list[str] = []

    discovery_metrics = dict(report.get("discovery") or {})
    selection_metrics = dict(report.get("selection") or {})
    navigation_metrics = dict(report.get("navigation") or {})
    cross_model_metrics = dict(report.get("cross_model") or {})

    discovery_slo = dict(slo.get("discovery") or {})
    selection_slo = dict(slo.get("selection") or {})
    navigation_slo = dict(slo.get("navigation") or {})
    cross_model_slo = dict(slo.get("cross_model") or {})

    def check_min(metric_name: str, value: float, required: float) -> None:
        if value < required:
            violations.append(f"{metric_name}={value:.4f} < min={required:.4f}")

    def check_max(metric_name: str, value: float, required: float) -> None:
        if value > required:
            violations.append(f"{metric_name}={value:.4f} > max={required:.4f}")

    if "min_pass_rate" in discovery_slo:
        check_min("discovery.pass_rate", float(discovery_metrics.get("pass_rate", 0.0)), float(discovery_slo["min_pass_rate"]))
    if "min_hit_rate" in selection_slo:
        check_min("selection.hit_rate", float(selection_metrics.get("hit_rate", 0.0)), float(selection_slo["min_hit_rate"]))
    if "max_false_trigger_rate" in selection_slo:
        check_max(
            "selection.false_trigger_rate",
            float(selection_metrics.get("false_trigger_rate", 0.0)),
            float(selection_slo["max_false_trigger_rate"]),
        )
    if "max_miss_trigger_rate" in selection_slo:
        check_max(
            "selection.miss_trigger_rate",
            float(selection_metrics.get("miss_trigger_rate", 0.0)),
            float(selection_slo["max_miss_trigger_rate"]),
        )
    if "min_pass_rate" in navigation_slo:
        check_min("navigation.pass_rate", float(navigation_metrics.get("pass_rate", 0.0)), float(navigation_slo["min_pass_rate"]))
    if "min_success_rate" in cross_model_slo:
        check_min(
            "cross_model.success_rate",
            float(cross_model_metrics.get("success_rate", 0.0)),
            float(cross_model_slo["min_success_rate"]),
        )
    if "max_drift_rate" in cross_model_slo:
        check_max(
            "cross_model.drift_rate",
            float(cross_model_metrics.get("drift_rate", 0.0)),
            float(cross_model_slo["max_drift_rate"]),
        )

    return violations


def _render_summary(report: Mapping[str, Any], violations: Sequence[str]) -> str:
    discovery = dict(report.get("discovery") or {})
    selection = dict(report.get("selection") or {})
    navigation = dict(report.get("navigation") or {})
    cross_model = dict(report.get("cross_model") or {})

    lines = [
        "Skill eval gate report:",
        f"  discovery.pass_rate: {float(discovery.get('pass_rate', 0.0)):.4f}",
        f"  selection.hit_rate: {float(selection.get('hit_rate', 0.0)):.4f}",
        f"  selection.false_trigger_rate: {float(selection.get('false_trigger_rate', 0.0)):.4f}",
        f"  selection.miss_trigger_rate: {float(selection.get('miss_trigger_rate', 0.0)):.4f}",
        f"  navigation.pass_rate: {float(navigation.get('pass_rate', 0.0)):.4f}",
        f"  cross_model.success_rate: {float(cross_model.get('success_rate', 0.0)):.4f}",
        f"  cross_model.drift_rate: {float(cross_model.get('drift_rate', 0.0)):.4f}",
    ]
    if violations:
        lines.append("  gate: FAILED")
        lines.extend([f"  - {item}" for item in violations])
    else:
        lines.append("  gate: PASSED")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run skill eval baselines and enforce SLO thresholds.")
    parser.add_argument(
        "--baseline",
        default=str(REPO_ROOT / "evals" / "skill_eval_baseline.json"),
        help="Path to baseline JSON cases.",
    )
    parser.add_argument(
        "--slo",
        default=str(REPO_ROOT / "evals" / "skill_eval_slo.json"),
        help="Path to SLO threshold JSON.",
    )
    parser.add_argument(
        "--report",
        default=str(REPO_ROOT / "evals" / "skill_eval_report.json"),
        help="Path to write the eval report JSON.",
    )
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline).resolve()
    slo_path = Path(args.slo).resolve()
    report_path = Path(args.report).resolve()

    baseline = _load_json(baseline_path)
    slo = _load_json(slo_path)

    report = {
        "baseline_version": baseline.get("version", "unknown"),
        "discovery": _evaluate_discovery(tuple(baseline.get("discovery_cases") or ())),
        "selection": _evaluate_selection(tuple(baseline.get("selection_cases") or ())),
        "navigation": _evaluate_navigation(tuple(baseline.get("navigation_cases") or ())),
        "cross_model": _evaluate_cross_model(tuple(baseline.get("cross_model_cases") or ())),
    }
    violations = _apply_quality_gate(report=report, slo=slo)
    report["violations"] = list(violations)
    report["gate_passed"] = not violations

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(_render_summary(report, violations))
    print(f"  report: {report_path}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
