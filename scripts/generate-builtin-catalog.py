#!/usr/bin/env python3
"""Generate runtime/builtin_catalog.generated.json from skill packages."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime._yaml import load_yaml  # noqa: E402
from runtime.skill_schema import SkillManifestError, normalize_skill_manifest  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate builtin catalog artifact from skill packages.")
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root path (defaults to current repository).",
    )
    parser.add_argument(
        "--package-root",
        default="runtime/builtin_skill_packages",
        help="Relative package root under repo root.",
    )
    parser.add_argument(
        "--output",
        default="runtime/builtin_catalog.generated.json",
        help="Relative output path under repo root.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    package_root = (repo_root / args.package_root).resolve()
    output_path = (repo_root / args.output).resolve()

    if not package_root.is_dir():
        raise SystemExit(f"Package root does not exist: {package_root}")

    skills = _collect_skill_specs(package_root)
    payload = {
        "schema_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(package_root.relative_to(repo_root)),
        "skills": skills,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0


def _collect_skill_specs(package_root: Path) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for manifest_path in sorted(package_root.glob("*/skill.yaml")):
        raw = _load_yaml_mapping(manifest_path)
        try:
            manifest = normalize_skill_manifest(raw)
        except SkillManifestError as exc:
            raise SystemExit(f"{manifest_path}: {exc}") from exc

        skill_id = str(manifest.get("id") or "").strip()
        if not skill_id:
            raise SystemExit(f"{manifest_path}: missing required `id`")
        names = dict(manifest.get("names") or {})
        descriptions = dict(manifest.get("descriptions") or {})
        if not names:
            fallback_name = str(manifest.get("name") or skill_id).strip()
            names = {"en-US": fallback_name, "zh-CN": fallback_name}
        if not descriptions:
            fallback_desc = str(manifest.get("description") or "").strip()
            descriptions = {"en-US": fallback_desc, "zh-CN": fallback_desc}

        specs.append(
            {
                "id": skill_id,
                "names": names,
                "descriptions": descriptions,
                "mode": manifest.get("mode") or "advisory",
                "runtime_entry": manifest.get("runtime_entry"),
                "entry_kind": manifest.get("entry_kind"),
                "handoff_kind": manifest.get("handoff_kind"),
                "contract_version": manifest.get("contract_version") or "1",
                "supports_routes": list(manifest.get("supports_routes") or ()),
                "triggers": list(manifest.get("triggers") or ()),
                "metadata": dict(manifest.get("metadata") or {}),
                "tools": list(manifest.get("tools") or ()),
                "disallowed_tools": list(manifest.get("disallowed_tools") or ()),
                "allowed_paths": list(manifest.get("allowed_paths") or ()),
                "requires_network": bool(manifest.get("requires_network", False)),
                "host_support": list(manifest.get("host_support") or ()),
                "permission_mode": manifest.get("permission_mode") or "default",
            }
        )
    return specs


def _load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    payload = load_yaml(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit(f"{path}: expected mapping payload")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
