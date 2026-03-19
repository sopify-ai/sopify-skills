"""Deterministic route classifier for Sopify runtime."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .clarification import has_submitted_clarification, parse_clarification_response
from .decision import has_submitted_decision, parse_decision_response
from .entry_guard import DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE
from .execution_confirm import parse_execution_confirm_response
from .models import ClarificationState, DecisionState, RouteDecision, RuntimeConfig, SkillMeta
from .skill_resolver import resolve_route_candidate_skills, resolve_runtime_skill_id
from .state import StateStore

_COMMAND_PATTERNS = (
    (re.compile(r"^~go\s+finalize(?:\s+(?P<body>.+))?$", re.IGNORECASE), "~go finalize"),
    (re.compile(r"^~go\s+plan(?:\s+(?P<body>.+))?$", re.IGNORECASE), "~go plan"),
    (re.compile(r"^~go\s+exec(?:\s+(?P<body>.+))?$", re.IGNORECASE), "~go exec"),
    (re.compile(r"^~go(?:\s+(?P<body>.+))?$", re.IGNORECASE), "~go"),
    (re.compile(r"^~compare(?:\s+(?P<body>.+))?$", re.IGNORECASE), "~compare"),
)
SUPPORTED_ROUTE_NAMES = (
    "plan_only",
    "workflow",
    "light_iterate",
    "quick_fix",
    "clarification_pending",
    "clarification_resume",
    "execution_confirm_pending",
    "resume_active",
    "exec_plan",
    "cancel_active",
    "finalize_active",
    "decision_pending",
    "decision_resume",
    "compare",
    "replay",
    "consult",
)

_REPLAY_KEYWORDS = (
    "回放",
    "回看",
    "重放",
    "复盘",
    "回顾实现",
    "总结这次实现",
    "为什么这么做",
    "为什么选这个方案",
    "why did",
    "replay",
    "review the implementation",
)
_CONTINUE_KEYWORDS = {"继续", "下一步", "继续执行", "继续吧", "go on", "continue", "resume", "next"}
_CANCEL_KEYWORDS = {"取消", "停止", "终止", "abort", "cancel", "stop"}
_ARCHITECTURE_KEYWORDS = ("架构", "系统", "runtime", "workflow", "engine", "adapter", "plugin", "新功能", "重构", "refactor")
_ACTION_KEYWORDS = (
    "修复",
    "实现",
    "添加",
    "新增",
    "修改",
    "重构",
    "优化",
    "删除",
    "fix",
    "implement",
    "add",
    "update",
    "refactor",
    "remove",
    "create",
)
_QUESTION_PREFIXES = (
    "为什么",
    "如何",
    "怎么",
    "what",
    "why",
    "how",
    "是否",
    "能否",
    "可以",
)
_FILE_REF_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:ts|tsx|js|jsx|py|md|json|yaml|yml|vue|rs|go)")
_PROCESS_FORCE_PATTERNS = (
    re.compile(r"(?<![\w-])(plan|design|develop|decision|checkpoint|handoff)(?![\w-])", re.IGNORECASE),
    re.compile(r"(规划|方案设计|开发实施|决策|检查点|交接|门禁|蓝图)"),
)
_PROTECTED_PLAN_ASSET_RE = re.compile(r"(^|[\s'\"`])(?:\./)?\.sopify-skills/plan/[^\s'\"`]+", re.IGNORECASE)
_TRADEOFF_FORCE_PATTERNS = (
    re.compile(r"(trade[\s-]?off|取舍|分叉|长期|long[\s-]?term|contract|契约|策略分歧)", re.IGNORECASE),
)
_LONG_TERM_CONTRACT_HINTS = (
    "架构",
    "蓝图",
    "contract",
    "契约",
    "policy",
    "策略",
    "入口",
    "runtime",
    "权限",
    "catalog",
    "slo",
    "长期",
)


@dataclass(frozen=True)
class _ComplexitySignal:
    level: str
    reason: str
    plan_level: str | None


class Router:
    """Classify user input into deterministic runtime routes."""

    def __init__(self, config: RuntimeConfig, *, state_store: StateStore) -> None:
        self.config = config
        self.state_store = state_store

    def classify(self, user_input: str, *, skills: Iterable[SkillMeta]) -> RouteDecision:
        text = user_input.strip()
        active_run = self.state_store.get_current_run()
        current_plan = self.state_store.get_current_plan()
        current_clarification = self.state_store.get_current_clarification()
        current_decision = self.state_store.get_current_decision()

        decide_decision = _classify_decide_command(text, skills=skills)
        if decide_decision is not None:
            return self._with_capture(decide_decision)

        command_decision = _classify_command(text, skills=skills)
        if current_clarification is not None and current_clarification.status == "pending":
            pending_clarification = _classify_pending_clarification(
                text,
                current_clarification,
                command_decision=command_decision,
                skills=skills,
            )
            if pending_clarification is not None:
                return self._with_capture(pending_clarification)

        if _contains_intent(text, _REPLAY_KEYWORDS):
            return RouteDecision(
                route_name="replay",
                request_text=text,
                reason="Matched replay or review intent keywords",
                candidate_skill_ids=_candidate_skills("replay", skills, "workflow-learning"),
                should_recover_context=True,
                runtime_skill_id=_runtime_skill("replay", skills, "workflow-learning"),
            )

        if active_run is not None and _normalize(text) in _CANCEL_KEYWORDS:
            return RouteDecision(
                route_name="cancel_active",
                request_text=text,
                reason="Matched active-flow cancellation intent",
                complexity="simple",
                should_recover_context=True,
                active_run_action="cancel",
            )

        if current_decision is not None and current_decision.status in {"pending", "collecting", "confirmed", "cancelled", "timed_out"}:
            pending_decision = _classify_pending_decision(
                text,
                current_decision,
                command_decision=command_decision,
                skills=skills,
            )
            if pending_decision is not None:
                return self._with_capture(pending_decision)

        if active_run is not None and current_plan is not None:
            pending_execution_confirm = _classify_pending_execution_confirm(
                text,
                active_run_stage=active_run.stage,
                command_decision=command_decision,
                skills=skills,
            )
            if pending_execution_confirm is not None:
                return self._with_capture(pending_execution_confirm)

        if command_decision is not None:
            return self._with_capture(command_decision)

        if active_run is not None and _normalize(text) in _CONTINUE_KEYWORDS:
            return self._with_capture(
                RouteDecision(
                    route_name="resume_active",
                    request_text=text,
                    reason="Matched active-flow continuation intent",
                    complexity="medium",
                    should_recover_context=True,
                    candidate_skill_ids=_candidate_skills("resume_active", skills, "develop"),
                    active_run_action="resume",
                )
            )

        compare_intent = text.startswith("对比分析：") or text.lower().startswith("compare:")
        if compare_intent:
            body = text.split("：", 1)[1] if "：" in text else text.split(":", 1)[1]
            return RouteDecision(
                route_name="compare",
                request_text=body.strip(),
                reason="Matched explicit compare-analysis prefix",
                candidate_skill_ids=_candidate_skills("compare", skills, "model-compare"),
                should_recover_context=False,
                runtime_skill_id=_runtime_skill("compare", skills, "model-compare"),
            )

        runtime_first_reason = _runtime_first_guard_reason(text)
        if runtime_first_reason is not None:
            return self._with_capture(
                RouteDecision(
                    route_name="workflow",
                    request_text=text,
                    reason=runtime_first_reason,
                    complexity="complex",
                    plan_level="standard",
                    should_create_plan=True,
                    candidate_skill_ids=_candidate_skills("workflow", skills, "analyze", "design", "develop"),
                    artifacts={
                        "entry_guard_reason_code": DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
                        "direct_edit_guard_trigger": runtime_first_reason,
                    },
                )
            )

        if _is_consultation(text):
            return RouteDecision(
                route_name="consult",
                request_text=text,
                reason="Looks like a direct question without change intent",
                complexity="simple",
            )

        signal = _estimate_complexity(text)
        if signal.level == "simple":
            return self._with_capture(
                RouteDecision(
                    route_name="quick_fix",
                    request_text=text,
                    reason=signal.reason,
                    complexity=signal.level,
                    candidate_skill_ids=_candidate_skills("quick_fix", skills, "develop"),
                )
            )
        if signal.level == "medium":
            return self._with_capture(
                RouteDecision(
                    route_name="light_iterate",
                    request_text=text,
                    reason=signal.reason,
                    complexity=signal.level,
                    plan_level=signal.plan_level,
                    should_create_plan=True,
                    candidate_skill_ids=_candidate_skills("light_iterate", skills, "design", "develop"),
                )
            )
        return self._with_capture(
            RouteDecision(
                route_name="workflow",
                request_text=text,
                reason=signal.reason,
                complexity=signal.level,
                plan_level=signal.plan_level,
                should_create_plan=True,
                candidate_skill_ids=_candidate_skills("workflow", skills, "analyze", "design", "develop"),
            )
        )

    def _with_capture(self, decision: RouteDecision) -> RouteDecision:
        capture_mode = _decide_capture_mode(self.config.workflow_learning_auto_capture, decision.complexity)
        return RouteDecision(
            route_name=decision.route_name,
            request_text=decision.request_text,
            reason=decision.reason,
            command=decision.command,
            complexity=decision.complexity,
            plan_level=decision.plan_level,
            candidate_skill_ids=decision.candidate_skill_ids,
            should_recover_context=decision.should_recover_context,
            should_create_plan=decision.should_create_plan,
            capture_mode=capture_mode,
            runtime_skill_id=decision.runtime_skill_id,
            active_run_action=decision.active_run_action,
            artifacts=decision.artifacts,
        )


def _classify_command(text: str, *, skills: Iterable[SkillMeta]) -> RouteDecision | None:
    for pattern, command in _COMMAND_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        body = (match.groupdict().get("body") or "").strip()
        request_text = body or text
        if command == "~go finalize":
            return RouteDecision(
                route_name="finalize_active",
                request_text=request_text,
                reason="Matched explicit finalize command",
                command=command,
                complexity="medium",
                should_recover_context=True,
                candidate_skill_ids=_candidate_skills("finalize_active", skills, "develop", "kb"),
                active_run_action="finalize",
            )
        if command == "~go plan":
            return RouteDecision(
                route_name="plan_only",
                request_text=request_text,
                reason="Matched explicit planning command",
                command=command,
                complexity="complex",
                plan_level="standard",
                should_create_plan=True,
                candidate_skill_ids=_candidate_skills("plan_only", skills, "analyze", "design"),
            )
        if command == "~go exec":
            return RouteDecision(
                route_name="exec_plan",
                request_text=request_text,
                reason="Matched explicit execute-plan command",
                command=command,
                complexity="medium",
                should_recover_context=True,
                candidate_skill_ids=_candidate_skills("exec_plan", skills, "develop"),
                active_run_action="resume",
            )
        if command == "~go":
            return RouteDecision(
                route_name="workflow",
                request_text=request_text,
                reason="Matched explicit workflow command",
                command=command,
                complexity="complex",
                plan_level="standard",
                should_create_plan=True,
                candidate_skill_ids=_candidate_skills("workflow", skills, "analyze", "design", "develop"),
            )
        if command == "~compare":
            return RouteDecision(
                route_name="compare",
                request_text=request_text,
                reason="Matched explicit compare command",
                command=command,
                candidate_skill_ids=_candidate_skills("compare", skills, "model-compare"),
                runtime_skill_id=_runtime_skill("compare", skills, "model-compare"),
            )
    return None


def _classify_decide_command(text: str, *, skills: Iterable[SkillMeta]) -> RouteDecision | None:
    stripped = text.strip()
    lowered = stripped.lower()
    if not lowered.startswith("~decide"):
        return None
    if lowered.startswith("~decide status") or lowered == "~decide":
        return RouteDecision(
            route_name="decision_pending",
            request_text=stripped,
            reason="Matched explicit decision status command",
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("decision_pending", skills, "design"),
            active_run_action="inspect_decision",
        )
    return RouteDecision(
        route_name="decision_resume",
        request_text=stripped,
        reason="Matched explicit decision response command",
        complexity="medium",
        should_recover_context=True,
        candidate_skill_ids=_candidate_skills("decision_resume", skills, "design"),
        active_run_action="decision_response",
    )


def _classify_pending_decision(
    text: str,
    current_decision: DecisionState,
    *,
    command_decision: RouteDecision | None,
    skills: Iterable[SkillMeta],
) -> RouteDecision | None:
    if (
        current_decision.status in {"pending", "collecting", "cancelled", "timed_out"}
        and has_submitted_decision(current_decision)
        and (command_decision is None or command_decision.route_name != "decision_pending")
    ):
        return RouteDecision(
            route_name="decision_resume",
            request_text=text,
            reason="Structured decision submission is ready to be resumed",
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("decision_resume", skills, "design"),
            active_run_action="resume_submitted_decision",
        )

    if command_decision is not None:
        if command_decision.route_name in {"plan_only", "workflow", "light_iterate"}:
            return None
        if command_decision.route_name == "exec_plan":
            if current_decision.status == "pending":
                return RouteDecision(
                    route_name="decision_pending",
                    request_text=text,
                    reason="Pending decision checkpoint must be resolved before exec recovery can continue",
                    complexity="medium",
                    should_recover_context=True,
                    candidate_skill_ids=_candidate_skills("decision_pending", skills, "design"),
                    active_run_action="inspect_decision",
                )
            return RouteDecision(
                route_name="decision_resume",
                request_text=text,
                reason="Confirmed decision checkpoint is being materialized through the exec recovery entry",
                command=command_decision.command,
                complexity="medium",
                should_recover_context=True,
                candidate_skill_ids=_candidate_skills("decision_resume", skills, "design"),
                active_run_action="materialize_confirmed_decision",
            )

    response = parse_decision_response(current_decision, text)
    if response.action == "status":
        return RouteDecision(
            route_name="decision_pending",
            request_text=text,
            reason="Pending decision checkpoint is waiting for confirmation",
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("decision_pending", skills, "design"),
            active_run_action="inspect_decision",
        )
    if response.action in {"choose", "materialize", "cancel", "invalid"}:
        return RouteDecision(
            route_name="decision_resume",
            request_text=text,
            reason="Matched a response for the pending decision checkpoint",
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("decision_resume", skills, "design"),
            active_run_action="decision_response",
        )
    return None


def _classify_pending_clarification(
    text: str,
    current_clarification: ClarificationState,
    *,
    command_decision: RouteDecision | None,
    skills: Iterable[SkillMeta],
) -> RouteDecision | None:
    if command_decision is not None:
        if command_decision.route_name in {"plan_only", "workflow", "light_iterate"}:
            return None
        if command_decision.route_name == "exec_plan":
            return RouteDecision(
                route_name="clarification_pending",
                request_text=text,
                reason="Pending clarification must be answered before execution can continue",
                complexity="medium",
                should_recover_context=True,
                candidate_skill_ids=_candidate_skills("clarification_pending", skills, "analyze", "design"),
                active_run_action="inspect_clarification",
            )

    if has_submitted_clarification(current_clarification) and _normalize(text) in _CONTINUE_KEYWORDS:
        return RouteDecision(
            route_name="clarification_resume",
            request_text=text,
            reason="Restoring planning from structured clarification answers",
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("clarification_resume", skills, "analyze", "design"),
            active_run_action="clarification_response_from_state",
        )

    response = parse_clarification_response(current_clarification, text)
    if response.action == "status":
        return RouteDecision(
            route_name="clarification_pending",
            request_text=text,
            reason="Pending clarification is still waiting for factual details",
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("clarification_pending", skills, "analyze", "design"),
            active_run_action="inspect_clarification",
        )
    if response.action == "cancel":
        return RouteDecision(
            route_name="cancel_active",
            request_text=text,
            reason="Clarification cancelled by user",
            complexity="simple",
            should_recover_context=True,
            active_run_action="cancel",
        )
    if response.action == "answer":
        return RouteDecision(
            route_name="clarification_resume",
            request_text=text,
            reason="Received supplemental facts for the pending clarification",
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("clarification_resume", skills, "analyze", "design"),
            active_run_action="clarification_response",
        )
    return RouteDecision(
        route_name="clarification_pending",
        request_text=text,
        reason=response.message or "Clarification still needs more factual details",
        complexity="medium",
        should_recover_context=True,
        candidate_skill_ids=_candidate_skills("clarification_pending", skills, "analyze", "design"),
        active_run_action="inspect_clarification",
    )


def _classify_pending_execution_confirm(
    text: str,
    *,
    active_run_stage: str,
    command_decision: RouteDecision | None,
    skills: Iterable[SkillMeta],
) -> RouteDecision | None:
    if active_run_stage not in {"ready_for_execution", "execution_confirm_pending"}:
        return None

    if command_decision is not None:
        if command_decision.route_name in {"plan_only", "workflow", "light_iterate"}:
            return None
        if command_decision.route_name == "exec_plan":
            return RouteDecision(
                route_name="execution_confirm_pending",
                request_text=text,
                reason="Execution confirmation is still required before develop can start",
                complexity="medium",
                should_recover_context=True,
                candidate_skill_ids=_candidate_skills("execution_confirm_pending", skills, "develop"),
                active_run_action="inspect_execution_confirm",
            )

    response = parse_execution_confirm_response(text)
    if response.action == "cancel":
        return RouteDecision(
            route_name="cancel_active",
            request_text=text,
            reason="Execution confirmation cancelled by user",
            complexity="simple",
            should_recover_context=True,
            active_run_action="cancel",
        )

    action_to_reason = {
        "confirm": "Matched a natural-language execution confirmation reply",
        "status": "Execution confirmation is still waiting for user confirmation",
        "revise": "Received plan feedback before execution confirmation",
        "invalid": response.message or "Execution confirmation still requires a valid reply",
    }
    action_to_active_run_action = {
        "confirm": "confirm_execution",
        "status": "inspect_execution_confirm",
        "revise": "revise_execution",
        "invalid": "inspect_execution_confirm",
    }
    return RouteDecision(
        route_name="execution_confirm_pending",
        request_text=text,
        reason=action_to_reason.get(response.action, "Execution confirmation is still pending"),
        complexity="medium",
        should_recover_context=True,
        candidate_skill_ids=_candidate_skills("execution_confirm_pending", skills, "develop"),
        active_run_action=action_to_active_run_action.get(response.action, "inspect_execution_confirm"),
    )


def _estimate_complexity(text: str) -> _ComplexitySignal:
    lowered = text.lower()
    file_refs = len(_FILE_REF_RE.findall(text))
    has_arch = any(keyword.lower() in lowered for keyword in _ARCHITECTURE_KEYWORDS)
    has_action = any(keyword.lower() in lowered for keyword in _ACTION_KEYWORDS)

    if has_arch or file_refs > 5:
        plan_level = "full" if has_arch and any(token in lowered for token in ("架构", "system", "plugin", "adapter")) else "standard"
        return _ComplexitySignal("complex", "Detected architecture-scale or broad change intent", plan_level)
    if has_action and 3 <= file_refs <= 5:
        return _ComplexitySignal("medium", "Detected multi-file but bounded implementation request", "light")
    if has_action and file_refs == 0:
        return _ComplexitySignal("complex", "Detected change intent without bounded file scope", "standard")
    if has_action:
        return _ComplexitySignal("simple", "Detected focused implementation request with limited scope", None)
    return _ComplexitySignal("medium", "Defaulted to medium because the request is action-oriented but underspecified", "light")


def _is_consultation(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True
    if any(keyword.lower() in normalized for keyword in _ACTION_KEYWORDS):
        return False
    if text.endswith("?") or text.endswith("？"):
        return True
    return normalized.startswith(_QUESTION_PREFIXES)


def _runtime_first_guard_reason(text: str) -> str | None:
    if _is_protected_plan_asset_request(text):
        return "Blocked direct-edit path because the request targets protected .sopify-skills/plan assets"
    if _has_process_semantic_intent(text):
        return "Blocked direct-edit path because process-semantic keywords require runtime-first routing"
    if _has_tradeoff_or_contract_split(text):
        return "Blocked direct-edit path because tradeoff or long-term contract split requires runtime-first routing"
    return None


def _is_protected_plan_asset_request(text: str) -> bool:
    return _PROTECTED_PLAN_ASSET_RE.search(text) is not None


def _has_process_semantic_intent(text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in _PROCESS_FORCE_PATTERNS)


def _has_tradeoff_or_contract_split(text: str) -> bool:
    lowered = text.lower()
    if any(pattern.search(text) is not None for pattern in _TRADEOFF_FORCE_PATTERNS):
        return True
    split_signal = "还是" in text or "二选一" in text or "vs" in lowered or " or " in lowered
    if not split_signal:
        return False
    return any(token in lowered for token in _LONG_TERM_CONTRACT_HINTS)


def _contains_intent(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _candidate_skills(route_name: str, skills: Iterable[SkillMeta], *preferred: str) -> tuple[str, ...]:
    return resolve_route_candidate_skills(
        route_name,
        skills,
        fallback_preferred=tuple(preferred),
    )


def _runtime_skill(route_name: str, skills: Iterable[SkillMeta], skill_id: str) -> str | None:
    return resolve_runtime_skill_id(
        route_name,
        skills,
        fallback_preferred=skill_id,
    )


def _decide_capture_mode(policy: str, complexity: str) -> str:
    if policy == "always":
        return "full"
    if policy == "manual" or policy == "off":
        return "off"
    if complexity == "simple":
        return "off"
    if complexity == "medium":
        return "summary"
    return "full"
