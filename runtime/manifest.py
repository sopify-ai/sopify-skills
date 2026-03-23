"""Bundle manifest generation for vendored Sopify runtime bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any, Mapping

from .builtin_catalog import load_builtin_skills
from .checkpoint_request import DEVELOP_RESUME_AFTER_ACTIONS, DEVELOP_RESUME_CONTEXT_REQUIRED_FIELDS
from .entry_guard import (
    DEFAULT_RUNTIME_ENTRY as ENTRY_GUARD_DEFAULT_ENTRY,
    ENTRY_GUARD_BYPASS_BLOCKED_COMMANDS,
    ENTRY_GUARD_DEVELOP_CALLBACK_REASON_CODE,
    ENTRY_GUARD_PENDING_ACTIONS,
    ENTRY_GUARD_REASON_CODES,
    PLAN_ONLY_HELPER_ENTRY as ENTRY_GUARD_PLAN_ONLY_HELPER_ENTRY,
)
from .clarification import CURRENT_CLARIFICATION_RELATIVE_PATH
from .decision import CURRENT_DECISION_RELATIVE_PATH
from .handoff import CURRENT_HANDOFF_RELATIVE_PATH
from .knowledge_layout import CONTEXT_PROFILES, KB_LAYOUT_VERSION, KNOWLEDGE_PATHS
from .preferences import PREFERENCES_PRELOAD_STATUSES
from .router import SUPPORTED_ROUTE_NAMES, build_runtime_first_hints
from .state import iso_now

MANIFEST_SCHEMA_VERSION = "1"
DEFAULT_MANIFEST_FILENAME = "manifest.json"
DEFAULT_ENTRY = ENTRY_GUARD_DEFAULT_ENTRY
PLAN_ONLY_ENTRY = ENTRY_GUARD_PLAN_ONLY_HELPER_ENTRY
DECISION_BRIDGE_ENTRY = "scripts/decision_bridge_runtime.py"
CLARIFICATION_BRIDGE_ENTRY = "scripts/clarification_bridge_runtime.py"
DEVELOP_CHECKPOINT_ENTRY = "scripts/develop_checkpoint_runtime.py"
PLAN_REGISTRY_ENTRY = "scripts/plan_registry_runtime.py"
PREFERENCES_PRELOAD_ENTRY = "scripts/preferences_preload_runtime.py"
RUNTIME_GATE_ENTRY = "scripts/runtime_gate.py"
_SOPIFY_VERSION_RE = re.compile(r"^<!--\s*SOPIFY_VERSION:\s*(?P<version>.+?)\s*-->$", re.MULTILINE)
_CHANGELOG_VERSION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]", re.MULTILINE)


class ManifestError(ValueError):
    """Raised when a bundle manifest cannot be generated safely."""


class BundleManifest:
    """Typed view of the bundle manifest written into `.sopify-runtime/`."""

    def __init__(
        self,
        *,
        schema_version: str,
        bundle_version: str,
        generated_at: str,
        kb_layout_version: str,
        knowledge_paths: Mapping[str, str],
        context_profiles: Mapping[str, tuple[str, ...] | list[str]],
        default_entry: str,
        plan_only_entry: str,
        supported_routes: tuple[str, ...],
        builtin_skills: tuple[Mapping[str, Any], ...],
        handoff_file: str,
        dependency_model: Mapping[str, Any],
        capabilities: Mapping[str, Any],
        runtime_first_hints: Mapping[str, Any],
        limits: Mapping[str, Any],
    ) -> None:
        self.schema_version = schema_version
        self.bundle_version = bundle_version
        self.generated_at = generated_at
        self.kb_layout_version = kb_layout_version
        self.knowledge_paths = dict(knowledge_paths)
        self.context_profiles = {name: tuple(entries) for name, entries in context_profiles.items()}
        self.default_entry = default_entry
        self.plan_only_entry = plan_only_entry
        self.supported_routes = supported_routes
        self.builtin_skills = builtin_skills
        self.handoff_file = handoff_file
        self.dependency_model = dependency_model
        self.capabilities = capabilities
        self.runtime_first_hints = runtime_first_hints
        self.limits = limits

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_version": self.bundle_version,
            "generated_at": self.generated_at,
            "kb_layout_version": self.kb_layout_version,
            "knowledge_paths": dict(self.knowledge_paths),
            "context_profiles": {name: list(entries) for name, entries in self.context_profiles.items()},
            "default_entry": self.default_entry,
            "plan_only_entry": self.plan_only_entry,
            "supported_routes": list(self.supported_routes),
            "builtin_skills": [dict(skill) for skill in self.builtin_skills],
            "handoff_file": self.handoff_file,
            "dependency_model": dict(self.dependency_model),
            "capabilities": dict(self.capabilities),
            "runtime_first_hints": dict(self.runtime_first_hints),
            "limits": dict(self.limits),
        }


def build_bundle_manifest(
    *,
    bundle_root: Path,
    source_root: Path | None = None,
    bundle_version: str | None = None,
) -> BundleManifest:
    """Build the machine contract for a vendored Sopify runtime bundle."""
    resolved_bundle_root = bundle_root.resolve()
    resolved_source_root = (source_root or bundle_root).resolve()
    # Entries must be bundle-relative, but the published version should come from the source repo when available.
    builtin_skills = tuple(
        _serialize_builtin_skill(skill=skill, bundle_root=resolved_bundle_root)
        for skill in load_builtin_skills(repo_root=resolved_bundle_root, language="en-US")
    )
    runtime_skill_ids = tuple(skill["skill_id"] for skill in builtin_skills if skill["runtime_entry"] is not None)

    return BundleManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        bundle_version=_resolve_bundle_version(
            source_root=resolved_source_root,
            bundle_root=resolved_bundle_root,
            explicit_version=bundle_version,
        ),
        generated_at=iso_now(),
        kb_layout_version=KB_LAYOUT_VERSION,
        knowledge_paths=_knowledge_paths(),
        context_profiles=_context_profiles(),
        default_entry=DEFAULT_ENTRY,
        plan_only_entry=PLAN_ONLY_ENTRY,
        supported_routes=SUPPORTED_ROUTE_NAMES,
        builtin_skills=builtin_skills,
        handoff_file=CURRENT_HANDOFF_RELATIVE_PATH,
        dependency_model={
            "mode": "stdlib_only",
            "python_min": "3.11",
            "host_env_dir": None,
            "runtime_dependencies": [],
        },
        capabilities={
            "bundle_role": "control_plane",
            "manifest_first": True,
            "builtin_catalog": True,
            "plan_scaffold": True,
            "kb_bootstrap": True,
            "decision_checkpoint": True,
            "decision_bridge": True,
            "clarification_checkpoint": True,
            "clarification_bridge": True,
            "develop_checkpoint_callback": True,
            "develop_resume_context": True,
            "execution_gate": True,
            "plan_registry": True,
            "plan_registry_priority_confirm": True,
            "planning_mode_orchestrator": True,
            "preferences_preload": True,
            "runtime_gate": True,
            "runtime_entry_guard": True,
            "replay_capture": True,
            "session_scoped_review_state": True,
            "soft_execution_ownership": True,
            "writes_clarification_file": True,
            "writes_handoff_file": True,
            "writes_decision_file": True,
            "runtime_skill_ids": list(runtime_skill_ids),
        },
        runtime_first_hints=build_runtime_first_hints(),
        limits={
            "host_required_routes": [
                "plan_only",
                "workflow",
                "light_iterate",
                "quick_fix",
                "clarification_pending",
                "clarification_resume",
                "execution_confirm_pending",
                "resume_active",
                "exec_plan",
                "decision_pending",
                "decision_resume",
                "compare",
                "replay",
                "consult",
            ],
            "host_bridge_status": {
                "develop": "required",
                "develop_checkpoint": "required",
                "execution_confirm": "required",
                "compare": "required",
                "replay": "required",
            },
            "entry_guard": {
                "strict_runtime_entry": True,
                "default_runtime_entry": DEFAULT_ENTRY,
                "plan_only_helper_entry": PLAN_ONLY_ENTRY,
                "pending_checkpoint_actions": list(ENTRY_GUARD_PENDING_ACTIONS),
                "bypass_blocked_commands": list(ENTRY_GUARD_BYPASS_BLOCKED_COMMANDS),
                "reason_codes": dict(ENTRY_GUARD_REASON_CODES),
                "develop_checkpoint_callback_reason_code": ENTRY_GUARD_DEVELOP_CALLBACK_REASON_CODE,
            },
            "runtime_payload_required_skill_ids": ["model-compare"],
            "session_state": {
                "review_scope": "session",
                "execution_scope": "global",
                "source": "host_supplied_or_runtime_gate_generated",
                "followup_session_id": "required_for_review_followups",
                "cleanup_days": 7,
            },
            "clarification_file": CURRENT_CLARIFICATION_RELATIVE_PATH,
            "decision_file": CURRENT_DECISION_RELATIVE_PATH,
            "clarification_bridge_entry": CLARIFICATION_BRIDGE_ENTRY,
            "clarification_bridge_hosts": {
                "cli": {
                    "preferred_mode": "interactive_form",
                    "fallback_renderer": "text",
                    "input": "line_prompt",
                    "textarea": "multiline_text",
                },
            },
            "decision_bridge_entry": DECISION_BRIDGE_ENTRY,
            "decision_bridge_hosts": {
                "cli": {
                    "preferred_mode": "interactive_form",
                    "fallback_renderer": "text",
                    "select": "interactive_select",
                    "multi_select": "interactive_multi_select",
                    "confirm": "interactive_confirm",
                    "input": "line_prompt",
                    "textarea": "multiline_text",
                },
            },
            "develop_checkpoint_entry": DEVELOP_CHECKPOINT_ENTRY,
            "develop_checkpoint_hosts": {
                "cli": {
                    "preferred_mode": "structured_callback",
                    "inspect": "json_contract",
                    "submit": "json_payload",
                },
            },
            "develop_resume_context_required_fields": list(DEVELOP_RESUME_CONTEXT_REQUIRED_FIELDS),
            "develop_resume_after_actions": list(DEVELOP_RESUME_AFTER_ACTIONS),
            "plan_registry_entry": PLAN_REGISTRY_ENTRY,
            "plan_registry_hosts": {
                "cli": {
                    "preferred_mode": "inspect_only_summary",
                    "trigger_points": [
                        "post_plan_review",
                        "manual_plan_registry_review",
                    ],
                    "mount_scope": "review_only",
                    "blocked_scopes": [
                        "develop",
                        "execute",
                    ],
                    "inspect": "json_contract",
                    "confirm_priority": "json_payload",
                    "confirm_priority_trigger": "explicit_user_action",
                    "default_surface": "inspect_contract",
                    "display_fields": [
                        "current_plan",
                        "selected_plan",
                        "recommendations",
                        "drift_notice",
                        "execution_truth",
                    ],
                    "allowed_actions": [
                        "confirm_suggested",
                        "set_p1",
                        "set_p2",
                        "set_p3",
                        "dismiss",
                    ],
                    "note_optional": True,
                    "confirm_payload_fields": [
                        "plan_id",
                        "priority",
                        "note",
                    ],
                    "success_behavior": {
                        "refresh_scope": "selected_card",
                        "stay_in_context": "review",
                        "auto_execute": False,
                        "auto_switch_current_plan": False,
                    },
                    "failure_behavior": {
                        "inspect_failure": "hide_card_non_blocking",
                        "confirm_failure": "show_retryable_error",
                    },
                    "copy": {
                        "title": "Plan 优先级建议",
                        "summary": "当前 active plan、当前评审 plan 与建议优先级",
                        "boundary_notice": "确认优先级只会更新 registry，不会切换 current_plan",
                        "success_notice": "已记录到 plan registry",
                        "pending_notice": "已保留系统建议，暂未写入最终优先级",
                    },
                    "raw_registry_visibility": "advanced_only",
                    "execution_truth": "current_plan",
                    "observe_only": True,
                },
            },
            "preferences_preload_entry": PREFERENCES_PRELOAD_ENTRY,
            "preferences_preload_contract_version": "1",
            "preferences_preload_statuses": list(PREFERENCES_PRELOAD_STATUSES),
            "runtime_gate_entry": RUNTIME_GATE_ENTRY,
            "runtime_gate_contract_version": "1",
            "runtime_gate_allowed_response_modes": [
                "normal_runtime_followup",
                "checkpoint_only",
                "error_visible_retry",
            ],
        },
    )


def _knowledge_paths() -> dict[str, str]:
    return dict(KNOWLEDGE_PATHS)


def _context_profiles() -> dict[str, list[str]]:
    return {name: list(entries) for name, entries in CONTEXT_PROFILES.items()}


def write_bundle_manifest(
    *,
    bundle_root: Path,
    output_path: Path | None = None,
    source_root: Path | None = None,
    bundle_version: str | None = None,
) -> Path:
    """Write `manifest.json` atomically and return the output path."""
    resolved_bundle_root = bundle_root.resolve()
    target_path = (output_path or (resolved_bundle_root / DEFAULT_MANIFEST_FILENAME)).resolve()
    manifest = build_bundle_manifest(
        bundle_root=resolved_bundle_root,
        source_root=source_root,
        bundle_version=bundle_version,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=target_path.parent, encoding="utf-8") as handle:
        json.dump(manifest.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target_path)
    return target_path


def build_manifest_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for manifest generation."""
    parser = argparse.ArgumentParser(description="Generate a Sopify bundle manifest.")
    parser.add_argument(
        "--bundle-root",
        required=True,
        help="Vendored bundle root, for example /path/to/project/.sopify-runtime",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Optional source repository root used to resolve the published bundle version.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional manifest output path. Defaults to <bundle-root>/manifest.json.",
    )
    parser.add_argument(
        "--bundle-version",
        default=None,
        help="Optional explicit bundle version. Overrides auto-detection.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by the sync script."""
    parser = build_manifest_parser()
    args = parser.parse_args(argv)
    bundle_root = Path(args.bundle_root).resolve()
    if not bundle_root.is_dir():
        raise SystemExit(f"Bundle root does not exist: {bundle_root}")

    output_path = Path(args.output).resolve() if args.output else None
    source_root = Path(args.source_root).resolve() if args.source_root else None
    written_path = write_bundle_manifest(
        bundle_root=bundle_root,
        output_path=output_path,
        source_root=source_root,
        bundle_version=args.bundle_version,
    )
    print(written_path)
    return 0


def _serialize_builtin_skill(*, skill: Any, bundle_root: Path) -> Mapping[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "mode": skill.mode,
        "entry_kind": skill.entry_kind,
        "runtime_entry": _to_bundle_relative(skill.runtime_entry, bundle_root=bundle_root),
        "handoff_kind": skill.handoff_kind,
        "contract_version": skill.contract_version,
        "supports_routes": list(skill.supports_routes),
        "tools": list(skill.tools),
        "disallowed_tools": list(skill.disallowed_tools),
        "allowed_paths": list(skill.allowed_paths),
        "requires_network": bool(skill.requires_network),
        "host_support": list(skill.host_support),
        "permission_mode": skill.permission_mode,
    }


def _to_bundle_relative(path: Path | None, *, bundle_root: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(bundle_root))
    except ValueError as exc:  # pragma: no cover - defensive guard for invalid inputs
        raise ManifestError(f"Manifest path escaped bundle root: {resolved}") from exc


def _resolve_bundle_version(*, source_root: Path, bundle_root: Path, explicit_version: str | None) -> str:
    if explicit_version:
        return explicit_version

    version = _read_version_header(source_root / "Codex" / "Skills" / "CN" / "AGENTS.md")
    if version is not None:
        return version

    version = _read_existing_manifest_version(bundle_root / DEFAULT_MANIFEST_FILENAME)
    if version is not None:
        return version

    version = _read_latest_changelog_version(source_root / "CHANGELOG.md")
    if version is not None:
        return version

    return "0.0.0-dev"


def _read_version_header(path: Path) -> str | None:
    if not path.is_file():
        return None
    match = _SOPIFY_VERSION_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        return None
    return match.group("version").strip()


def _read_existing_manifest_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = payload.get("bundle_version")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_latest_changelog_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    for match in _CHANGELOG_VERSION_RE.finditer(path.read_text(encoding="utf-8")):
        version = match.group("version").strip()
        if version.lower() != "unreleased":
            return version
    return None


if __name__ == "__main__":
    raise SystemExit(main())
