"""Guard-rail registry for the current Plan A V1 implementation slice."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

SUPPORTED_CHECKPOINT_KINDS_V1 = (
    "confirm_decision",
    "confirm_execute",
    "confirm_plan_package",
)

ALLOWED_V1_STATE_EFFECTS = (
    "current_decision",
    "current_plan",
    "current_plan_proposal",
    "current_run",
)

FORBIDDEN_V1_SIDE_EFFECTS = (
    "advance_to_develop",
    "clear_current_decision",
    "clear_current_plan_proposal",
    "materialize_new_plan_package",
    "mutate_plan_identity",
    "recreate_execution_confirm_checkpoint",
    "rewrite_reserved_plan_id",
    "submit_decision_selection",
)

MAX_LOCAL_CONTEXT_USER_MESSAGES = 3

V1_IMPLEMENTATION_RUNTIME_FILES = (
    "runtime/action_projection.py",
    "runtime/context_builder.py",
    "runtime/context_v1_scope.py",
    "runtime/deterministic_guard.py",
    "runtime/handoff.py",
    "runtime/resolution_planner.py",
)

V1_IMPLEMENTATION_TEST_FILES = (
    "tests/test_context_v1_scope.py",
    "tests/test_runtime_engine.py",
)

V1_IMPLEMENTATION_CANDIDATE_FILES = (
    *V1_IMPLEMENTATION_RUNTIME_FILES,
    *V1_IMPLEMENTATION_TEST_FILES,
)

V1_OBSERVE_ONLY_FILES = (
    "runtime/contracts/decision_tables.schema.json",
    "runtime/contracts/decision_tables.yaml",
    "runtime/engine.py",
    "runtime/failure_recovery.py",
    "runtime/sidecar_classifier_boundary.py",
    "runtime/vnext_phase_boundary.py",
    "tests/fixtures/sample_invariant_gate_matrix.yaml",
    "tests/test_runtime_sample_invariant_gate.py",
)

CHECKPOINT_C_LOCK_PREREQUISITES = ("Checkpoint B",)

V1_READY_TO_START_REQUIRED_CHECKPOINTS = ("Checkpoint A", "Checkpoint B")

V1_READY_TO_START_LOCAL_REQUIREMENTS = (
    "file_map_frozen",
    "scope_guard_tests_green",
    "compatibility_rules_frozen",
)

V1_COMPATIBILITY_RULES = (
    "required_host_action_contract_additive_only",
    "execution_gate_core_fields_and_gate_status_stable",
    "decision_tables_v1_assets_readonly_during_scope_finalize",
    "sample_invariant_gate_assets_readonly_after_checkpoint_b",
)

V1_ROLLOUT_POLICY = (
    "lock_file_map_after_checkpoint_b",
    "limit_runtime_edits_to_candidate_file_map",
    "treat_observe_only_files_as_readonly_reference_surfaces",
)

V1_ROLLBACK_POLICY = (
    "revert_candidate_file_changes_to_checkpoint_b_guardrail_baseline_on_scope_violation",
    "do_not_reopen_observe_only_contract_assets_in_scope_finalize",
    "move_out_of_scope_contract_expansion_to_followup_branch",
)


class ContextV1ScopeError(ValueError):
    """Raised when a runtime artifact escapes the current V1 scope."""


def classify_v1_scope_path(path: str) -> str:
    """Classify one repository path against the frozen Checkpoint C file map."""

    normalized = _normalize_repo_path(path)
    if normalized in V1_IMPLEMENTATION_RUNTIME_FILES:
        return "candidate_runtime"
    if normalized in V1_IMPLEMENTATION_TEST_FILES:
        return "candidate_test"
    if normalized in V1_OBSERVE_ONLY_FILES:
        return "observe_only"
    return "out_of_scope"


def assert_supported_checkpoint_kind(checkpoint_kind: str) -> str:
    """Return a normalized checkpoint kind or raise on out-of-scope values."""

    normalized = str(checkpoint_kind or "").strip()
    if normalized not in SUPPORTED_CHECKPOINT_KINDS_V1:
        raise ContextV1ScopeError(
            "Unsupported V1 checkpoint_kind "
            f"{normalized!r}; allowed={SUPPORTED_CHECKPOINT_KINDS_V1!r}"
        )
    return normalized


def assert_state_effects_within_v1_scope(
    *,
    allowed_state_effects: Sequence[str] = (),
    forbidden_state_effects: Sequence[str] = (),
) -> None:
    """Reject state effects that are outside the currently approved V1 slice."""

    normalized_allowed = _normalize_effects(allowed_state_effects)
    normalized_forbidden = _normalize_effects(forbidden_state_effects)

    overlap = sorted(set(normalized_allowed) & set(normalized_forbidden))
    if overlap:
        raise ContextV1ScopeError(
            "State effects cannot be both allowed and forbidden within V1 scope: "
            + ", ".join(overlap)
        )

    unknown_allowed = [
        effect for effect in normalized_allowed if effect not in ALLOWED_V1_STATE_EFFECTS
    ]
    if unknown_allowed:
        raise ContextV1ScopeError(
            "Unsupported allowed V1 state effect(s): " + ", ".join(sorted(unknown_allowed))
        )

    unknown_forbidden = [
        effect for effect in normalized_forbidden if effect not in FORBIDDEN_V1_SIDE_EFFECTS
    ]
    if unknown_forbidden:
        raise ContextV1ScopeError(
            "Unsupported forbidden V1 state effect(s): " + ", ".join(sorted(unknown_forbidden))
        )


def validate_side_effect_mapping_row_v1(
    row: Mapping[str, Any],
    *,
    path: str = "side_effect_mapping_table.rows[*]",
) -> None:
    """Validate one side-effect mapping row against the current V1 guard rails."""

    if not isinstance(row, Mapping):
        raise ContextV1ScopeError(f"{path} must be a mapping")

    assert_supported_checkpoint_kind(str(row.get("checkpoint_kind") or ""))

    state_mutators = row.get("state_mutators")
    if not isinstance(state_mutators, Mapping):
        raise ContextV1ScopeError(f"{path}.state_mutators must be a mapping")

    allowed_state_effects: list[str] = []
    for bucket_name in ("preserve", "clear", "update", "write"):
        bucket_value = state_mutators.get(bucket_name, ())
        bucket_effects = _coerce_effect_bucket(
            bucket_value,
            path=f"{path}.state_mutators.{bucket_name}",
        )
        allowed_state_effects.extend(bucket_effects)

    forbidden_state_effects = _coerce_effect_bucket(
        row.get("forbidden_state_effects", ()),
        path=f"{path}.forbidden_state_effects",
    )
    assert_state_effects_within_v1_scope(
        allowed_state_effects=allowed_state_effects,
        forbidden_state_effects=forbidden_state_effects,
    )


def validate_decision_tables_v1_scope(tables: Mapping[str, Any]) -> None:
    """Validate that loaded decision tables stay inside the current V1 slice."""

    if not isinstance(tables, Mapping):
        raise ContextV1ScopeError("Decision tables must be a mapping")

    side_effect_mapping = tables.get("side_effect_mapping_table")
    if not isinstance(side_effect_mapping, Mapping):
        raise ContextV1ScopeError("Decision tables missing side_effect_mapping_table")

    rows = side_effect_mapping.get("rows")
    if not isinstance(rows, list):
        raise ContextV1ScopeError("side_effect_mapping_table.rows must be a list")

    for index, row in enumerate(rows):
        validate_side_effect_mapping_row_v1(
            row,
            path=f"side_effect_mapping_table.rows[{index}]",
        )


def assert_v1_implementation_file_map(
    changed_files: Sequence[str],
    *,
    checkpoint_b_passed: bool,
) -> tuple[str, ...]:
    """Reject Checkpoint C file-map drift before development starts."""

    normalized = tuple(_normalize_repo_path(path) for path in changed_files)
    implementation_paths = tuple(
        path
        for path in normalized
        if path.startswith("runtime/") or path.startswith("tests/")
    )
    if not implementation_paths:
        return ()
    if not checkpoint_b_passed:
        raise ContextV1ScopeError(
            "Checkpoint B must pass before locking the V1 file map or blocking out-of-scope edits"
        )

    observe_only = sorted(
        path for path in implementation_paths if classify_v1_scope_path(path) == "observe_only"
    )
    if observe_only:
        raise ContextV1ScopeError(
            "Observe-only files cannot be edited during V1 scope-finalize: "
            + ", ".join(observe_only)
        )

    out_of_scope = sorted(
        path for path in implementation_paths if classify_v1_scope_path(path) == "out_of_scope"
    )
    if out_of_scope:
        raise ContextV1ScopeError(
            "Out-of-scope implementation files are blocked during V1 scope-finalize: "
            + ", ".join(out_of_scope)
        )
    return implementation_paths


def assert_v1_ready_to_start(
    *,
    completed_checkpoints: Sequence[str],
    changed_files: Sequence[str],
    scope_guard_tests_green: bool,
    compatibility_rules_frozen: bool,
) -> tuple[str, ...]:
    """Validate the minimal gate for switching from design convergence to implementation."""

    normalized_checkpoints = _normalize_named_values(completed_checkpoints)
    missing = [
        checkpoint
        for checkpoint in V1_READY_TO_START_REQUIRED_CHECKPOINTS
        if checkpoint not in normalized_checkpoints
    ]
    if missing:
        raise ContextV1ScopeError(
            "V1 implementation cannot start before prerequisite checkpoints pass: "
            + ", ".join(missing)
        )
    if not scope_guard_tests_green:
        raise ContextV1ScopeError("V1 implementation cannot start before scope guard tests are green")
    if not compatibility_rules_frozen:
        raise ContextV1ScopeError(
            "V1 implementation cannot start before compatibility rules are frozen"
        )
    return assert_v1_implementation_file_map(changed_files, checkpoint_b_passed=True)


def _coerce_effect_bucket(value: Any, *, path: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContextV1ScopeError(f"{path} must be a sequence of strings")
    normalized = []
    for item in value:
        effect = str(item or "").strip()
        if not effect:
            raise ContextV1ScopeError(f"{path} contains an empty state effect")
        normalized.append(effect)
    return normalized


def _normalize_effects(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        effect = str(raw or "").strip()
        if not effect or effect in seen:
            continue
        seen.add(effect)
        normalized.append(effect)
    return tuple(normalized)


def _normalize_named_values(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def _normalize_repo_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise ContextV1ScopeError("Repository path must be non-empty")
    collapsed = str(PurePosixPath(normalized))
    if collapsed in {".", ""} or collapsed.startswith("../"):
        raise ContextV1ScopeError(f"Repository path must stay within workspace root: {path!r}")
    return collapsed
