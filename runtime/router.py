"""Deterministic route classifier for Sopify runtime."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .clarification import has_submitted_clarification, parse_clarification_response
from .decision import has_submitted_decision, parse_decision_response
from .entry_guard import DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE
from .execution_confirm import parse_execution_confirm_response
from .plan_scaffold import find_plan_by_request_reference, request_explicitly_wants_new_plan
from .plan_proposal import parse_plan_proposal_response
from .models import ClarificationState, DecisionState, RouteDecision, RuntimeConfig, SkillMeta
from .skill_resolver import resolve_route_candidate_skills, resolve_runtime_skill_id
from .state import StateStore

_COMMAND_PATTERNS = (
    (re.compile(r"^~summary(?:\s+(?P<body>.+))?$", re.IGNORECASE), "~summary"),
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
    "plan_proposal_pending",
    "execution_confirm_pending",
    "resume_active",
    "exec_plan",
    "cancel_active",
    "finalize_active",
    "decision_pending",
    "decision_resume",
    "summary",
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
    "补",
    "修",
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
    "解释",
    "说明",
    "看下",
    "看看",
    "what",
    "why",
    "how",
    "是否",
    "能否",
    "可以",
)
_FILE_REF_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:ts|tsx|js|jsx|py|md|json|yaml|yml|vue|rs|go)")
_PROCESS_FORCE_KEYWORDS_EN = ("design", "develop", "decision", "checkpoint", "handoff")
_PROCESS_FORCE_KEYWORDS_ZH = ("规划", "方案设计", "开发实施", "决策", "检查点", "交接", "门禁", "蓝图")
_PROCESS_FORCE_PATTERNS = (
    re.compile(
        rf"(?<![\w-])(?:{'|'.join(re.escape(keyword) for keyword in _PROCESS_FORCE_KEYWORDS_EN)})(?![\w-])",
        re.IGNORECASE,
    ),
    re.compile(rf"(?:{'|'.join(re.escape(keyword) for keyword in _PROCESS_FORCE_KEYWORDS_ZH)})"),
)
RUNTIME_FIRST_PROTECTED_PATH_PREFIXES = (".sopify-skills/plan/",)
_PROTECTED_PLAN_ASSET_RE = re.compile(r"(^|[\s'\"`])(?:\./)?\.sopify-skills/plan/[^\s'\"`]+", re.IGNORECASE)
_TRADEOFF_FORCE_KEYWORDS = ("tradeoff", "trade-off", "取舍", "分叉", "长期", "long-term", "contract", "契约", "策略分歧")
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
_PLAN_META_REVIEW_PATTERNS = (
    re.compile(r"(分析下|评估下|解释下|看看|review|critique|score|评分|打分|风险|risk|优化点|还需要我.*决策|还有什么.*决策)", re.IGNORECASE),
    re.compile(r"(当前状态|现在状态|状态如何|有什么问题|还有什么问题)", re.IGNORECASE),
)
_PLAN_META_REVIEW_ANCHORS = (
    re.compile(r"(这个|当前|该)\s*(方案|plan)", re.IGNORECASE),
    re.compile(r"\bplan\b", re.IGNORECASE),
    re.compile(r"方案", re.IGNORECASE),
)
_PLAN_META_REVIEW_EDIT_PATTERNS = (
    re.compile(r"(整理|更新|同步|写入|落地|修改|实现|修复|补充|重写|合并|merge|edit|change|update)", re.IGNORECASE),
)
_PLAN_MATERIALIZATION_META_DEBUG_PATTERNS = (
    re.compile(r"(为什么|为何|why).*(生成|创建|create).*(plan|方案)", re.IGNORECASE),
    re.compile(r"(不要|别再|不要再|stop|don't).*(生成|创建|create).*(plan|方案)", re.IGNORECASE),
    re.compile(r"(分析下|解释下|看看|review).*(命中|hit).*(guard|plan|方案)", re.IGNORECASE),
)
CONSULT_EXPLAIN_ONLY_OVERRIDE_REASON_CODE = "consult_explain_only_override"
_EXPLAIN_ONLY_NO_CHANGE_PATTERNS = (
    re.compile(r"(不要改|先别改|别改|不改代码|不改)", re.IGNORECASE),
    re.compile(r"(do not|don't|no need to)\s+(change|edit|modify|fix|patch)", re.IGNORECASE),
)
_EXPLAIN_ONLY_SIGNAL_PATTERNS = (
    re.compile(r"(说下原因|解释下|解释一下|说明一下|分析下原因|看看原因)", re.IGNORECASE),
    re.compile(r"(为什么|为何|原因|解释|说明|analy[sz]e|explain|why)", re.IGNORECASE),
)
_EXPLAIN_ONLY_REFERENTIAL_PATTERNS = (
    re.compile(r"(你之前说|这次又|又被|为什么这么判|怎么会这样|为什么会这样)", re.IGNORECASE),
)
_EXPLAIN_ONLY_META_DEBUG_PATTERNS = (
    re.compile(r"(误路由|路由成|proposal|plan_proposal_pending)", re.IGNORECASE),
    re.compile(r"(runtime\s*gate|gate|router|guard|contract|checkpoint|handoff)", re.IGNORECASE),
    re.compile(r"(clarification_pending|decision_pending|execution_confirm_pending)", re.IGNORECASE),
)
_EXPLICIT_PLAN_PACKAGE_PATTERNS = (
    re.compile(r"(写到|写入|落到).*(background\.md|design\.md|tasks\.md)", re.IGNORECASE),
    re.compile(r"(写到|写入|落到).*(\.sopify-skills/plan/)", re.IGNORECASE),
    re.compile(r"(create|write).*(plan package|background\.md|design\.md|tasks\.md)", re.IGNORECASE),
)
_ANALYZE_CHALLENGE_A1_PATTERNS = (
    re.compile(r"(优化|统一).*(体验|职责)", re.IGNORECASE),
    re.compile(r"(更顺一点|更顺滑|避免用户看不懂|让用户更容易理解)", re.IGNORECASE),
)
_ANALYZE_CHALLENGE_A2_PATTERNS = (
    re.compile(r"(直接|只要|就|省掉|去掉|绕过|不用).*(就行|即可|可以了|好了)", re.IGNORECASE),
    re.compile(r"(去掉|省掉|绕过).*(gate|runtime gate|execution confirm|执行确认)", re.IGNORECASE),
)
_ANALYZE_CHALLENGE_A3_PATTERNS = (
    re.compile(r"(更轻|更小|最小改法|最小方案|值不值得|有没有更轻的改法|有没有更小的改法)", re.IGNORECASE),
    re.compile(r"(重复建设|更低成本|更便宜|先不做大改)", re.IGNORECASE),
)
_ANALYZE_CHALLENGE_A4_PATTERNS = (
    re.compile(r"(统一入口|唯一机器事实源|唯一事实源|收敛成一个|收敛为一个)", re.IGNORECASE),
    re.compile(r"(runtime gate|execution gate|topic_key|current_handoff|current_run|manifest|handoff|consult 路由|consult route)", re.IGNORECASE),
    re.compile(r"(自动复用|长期契约|host contract|宿主契约|正文回答)", re.IGNORECASE),
)
_ANALYZE_CHALLENGE_A4_DECISION_PATTERNS = (
    re.compile(r"(要不要|是否|应不应该|有没有必要|是不是|而不是|直接|收敛|统一|唯一|参与)", re.IGNORECASE),
    re.compile(r"(怎么处理|如何处理|怎么收口|如何收口)", re.IGNORECASE),
)
_ANALYZE_CHALLENGE_TRIGGER_PATTERNS = (
    ("A2", _ANALYZE_CHALLENGE_A2_PATTERNS),
    ("A3", _ANALYZE_CHALLENGE_A3_PATTERNS),
    ("A4", _ANALYZE_CHALLENGE_A4_PATTERNS),
    ("A1", _ANALYZE_CHALLENGE_A1_PATTERNS),
)
_EXECUTION_CONFIRM_PLAN_FEEDBACK_PATTERNS = (
    re.compile(r"(这个|当前|该)\s*(plan|方案)", re.IGNORECASE),
    re.compile(r"(风险|任务|范围|scope|task|plan|方案).*(展开|补充|调整|更新|修改|review|评审|重写|再收口)", re.IGNORECASE),
    re.compile(r"(写进|写入|挂到|并入|回到).*(plan|方案)", re.IGNORECASE),
)
_EXECUTION_CONFIRM_REVISION_PATTERNS = (
    re.compile(r"(先把|先将|先).*(风险|任务|范围|scope|task|plan|方案)", re.IGNORECASE),
    re.compile(r"(展开一点|补充一下|再展开|再补充|再收口|再评审)", re.IGNORECASE),
    re.compile(r"(风险|任务|范围|scope|task|plan|方案).*(更具体|更清楚|再具体一点|再细一点)", re.IGNORECASE),
)
_LIGHT_EDIT_HINTS = ("readme", "注释", "comment", "typo", "文案", "assert", "断言", "路径说明")


@dataclass(frozen=True)
class _ComplexitySignal:
    level: str
    reason: str
    plan_level: str | None


def build_runtime_first_hints() -> dict[str, object]:
    """Publish stable host-facing hints for requests that should enter via the gate."""
    return {
        "force_route_name": "workflow",
        "entry_guard_reason_code": DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
        "required_entry": "scripts/runtime_gate.py",
        "required_subcommand": "enter",
        "direct_entry_block_error_code": "runtime_gate_required",
        "debug_bypass_flag": "--allow-direct-entry",
        "protected_path_prefixes": list(RUNTIME_FIRST_PROTECTED_PATH_PREFIXES),
        "process_semantic_keywords": list(_PROCESS_FORCE_KEYWORDS_EN + _PROCESS_FORCE_KEYWORDS_ZH),
        "tradeoff_keywords": list(_TRADEOFF_FORCE_KEYWORDS),
        "long_term_contract_keywords": list(_LONG_TERM_CONTRACT_HINTS),
    }


def match_runtime_first_guard(text: str) -> dict[str, str] | None:
    """Return the matched runtime-first guard, if this request should not enter direct edit paths."""
    if _is_protected_plan_asset_request(text):
        return {
            "guard_kind": "protected_plan_asset",
            "reason": "Blocked direct-edit path because the request targets protected .sopify-skills/plan assets",
        }
    if _has_process_semantic_intent(text):
        return {
            "guard_kind": "process_semantic_intent",
            "reason": "Blocked direct-edit path because process-semantic keywords require runtime-first routing",
        }
    if _has_tradeoff_or_contract_split(text):
        return {
            "guard_kind": "tradeoff_contract_split",
            "reason": "Blocked direct-edit path because tradeoff or long-term contract split requires runtime-first routing",
        }
    return None


class Router:
    """Classify user input into deterministic runtime routes."""

    def __init__(self, config: RuntimeConfig, *, state_store: StateStore, global_state_store: StateStore | None = None) -> None:
        self.config = config
        self.state_store = state_store
        self.global_state_store = global_state_store or state_store

    def classify(self, user_input: str, *, skills: Iterable[SkillMeta]) -> RouteDecision:
        text = user_input.strip()
        review_active_run = self.state_store.get_current_run()
        review_current_plan = self.state_store.get_current_plan()
        review_current_plan_proposal = self.state_store.get_current_plan_proposal()
        review_current_clarification = self.state_store.get_current_clarification()
        review_current_decision = self.state_store.get_current_decision()
        review_last_route = self.state_store.get_last_route()

        global_active_run = self.global_state_store.get_current_run()
        global_current_plan = self.global_state_store.get_current_plan()
        global_current_plan_proposal = self.global_state_store.get_current_plan_proposal()
        global_current_clarification = self.global_state_store.get_current_clarification()
        global_current_decision = self.global_state_store.get_current_decision()
        global_last_route = self.global_state_store.get_last_route()

        # Review checkpoints stay session-first; execution truth stays global-first.
        current_clarification = review_current_clarification or global_current_clarification
        current_decision = review_current_decision or global_current_decision
        current_plan_proposal = review_current_plan_proposal or global_current_plan_proposal
        execution_active_run = global_active_run or review_active_run
        execution_current_plan = global_current_plan or review_current_plan
        current_plan = review_current_plan or global_current_plan
        current_last_route = review_last_route or global_last_route

        decide_decision = _classify_decide_command(text, skills=skills)
        if decide_decision is not None:
            return self._with_capture(decide_decision)

        command_decision = _classify_command(text, skills=skills, config=self.config)
        if current_clarification is not None and current_clarification.status == "pending":
            pending_clarification = _classify_pending_clarification(
                text,
                current_clarification,
                command_decision=command_decision,
                skills=skills,
            )
            if pending_clarification is not None:
                return self._with_capture(pending_clarification)

        if current_plan_proposal is not None:
            pending_plan_proposal = _classify_pending_plan_proposal(
                text,
                command_decision=command_decision,
                skills=skills,
            )
            if pending_plan_proposal is not None:
                return self._with_capture(pending_plan_proposal)

        if _contains_intent(text, _REPLAY_KEYWORDS):
            return RouteDecision(
                route_name="replay",
                request_text=text,
                reason="Matched replay or review intent keywords",
                candidate_skill_ids=_candidate_skills("replay", skills, "workflow-learning"),
                should_recover_context=True,
                runtime_skill_id=_runtime_skill("replay", skills, "workflow-learning"),
            )

        if (global_active_run is not None or review_active_run is not None) and _normalize(text) in _CANCEL_KEYWORDS:
            return RouteDecision(
                route_name="cancel_active",
                request_text=text,
                reason="Matched active-flow cancellation intent",
                complexity="simple",
                should_recover_context=True,
                active_run_action="cancel",
                artifacts={
                    "cancel_scope": "global" if global_active_run is not None else "session",
                },
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

        if execution_active_run is not None and execution_current_plan is not None:
            pending_execution_confirm = _classify_pending_execution_confirm(
                text,
                active_run_stage=execution_active_run.stage,
                current_plan=execution_current_plan,
                command_decision=command_decision,
                skills=skills,
            )
            if pending_execution_confirm is not None:
                return self._with_capture(pending_execution_confirm)

        if command_decision is not None:
            return self._with_capture(command_decision)

        if execution_active_run is not None and _normalize(text) in _CONTINUE_KEYWORDS:
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

        meta_review_route = _classify_plan_meta_review(
            text,
            current_plan=current_plan,
            skills=skills,
        )
        if meta_review_route is not None:
            return self._with_capture(meta_review_route)

        analyze_challenge_route = _classify_analyze_challenge(
            text,
            current_plan=current_plan,
            skills=skills,
        )
        if analyze_challenge_route is not None:
            return self._with_capture(analyze_challenge_route)

        plan_meta_debug_route = _classify_plan_materialization_meta_debug(
            text,
            skills=skills,
        )
        if plan_meta_debug_route is not None:
            return self._with_capture(plan_meta_debug_route)

        explain_only_override = detect_explain_only_consult_override(
            text,
            command=command_decision.command if command_decision is not None else None,
            current_run=execution_active_run,
            current_plan=current_plan,
            current_plan_proposal=current_plan_proposal,
            last_route=current_last_route,
        )
        if explain_only_override is not None:
            return self._with_capture(
                RouteDecision(
                    route_name="consult",
                    request_text=text,
                    reason=explain_only_override["reason"],
                    complexity="simple",
                    should_recover_context=current_plan is not None or current_plan_proposal is not None,
                    candidate_skill_ids=_candidate_skills("consult", skills, "analyze"),
                    artifacts=explain_only_override["artifacts"],
                )
            )

        runtime_first_guard = match_runtime_first_guard(text)
        if runtime_first_guard is not None:
            return self._with_capture(
                RouteDecision(
                    route_name="workflow",
                    request_text=text,
                    reason=runtime_first_guard["reason"],
                    complexity="complex",
                    plan_level="standard",
                    plan_package_policy=_plan_package_policy_for_route("workflow", text, config=self.config),
                    candidate_skill_ids=_candidate_skills("workflow", skills, "analyze", "design", "develop"),
                    artifacts={
                        "entry_guard_reason_code": DIRECT_EDIT_BLOCKED_RUNTIME_REQUIRED_REASON_CODE,
                        "direct_edit_guard_kind": runtime_first_guard["guard_kind"],
                        "direct_edit_guard_trigger": runtime_first_guard["reason"],
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
                    plan_package_policy=_plan_package_policy_for_route("light_iterate", text, config=self.config),
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
                plan_package_policy=_plan_package_policy_for_route("workflow", text, config=self.config),
                candidate_skill_ids=_candidate_skills("workflow", skills, "analyze", "design", "develop"),
            )
        )

    def _with_capture(self, decision: RouteDecision) -> RouteDecision:
        if decision.route_name == "summary":
            capture_mode = "off"
        else:
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
            plan_package_policy=decision.plan_package_policy,
            should_create_plan=decision.should_create_plan,
            capture_mode=capture_mode,
            runtime_skill_id=decision.runtime_skill_id,
            active_run_action=decision.active_run_action,
            artifacts=decision.artifacts,
        )


def _classify_command(text: str, *, skills: Iterable[SkillMeta], config: RuntimeConfig) -> RouteDecision | None:
    for pattern, command in _COMMAND_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        body = (match.groupdict().get("body") or "").strip()
        request_text = body or text
        if command == "~summary":
            return RouteDecision(
                route_name="summary",
                request_text=request_text,
                reason="Matched explicit daily-summary command",
                command=command,
                complexity="simple",
                should_recover_context=True,
            )
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
                plan_package_policy="immediate",
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
                plan_package_policy=_plan_package_policy_for_route("workflow", request_text, config=config),
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


def _classify_pending_plan_proposal(
    text: str,
    *,
    command_decision: RouteDecision | None,
    skills: Iterable[SkillMeta],
) -> RouteDecision | None:
    if command_decision is not None:
        if command_decision.route_name in {"plan_only", "workflow", "light_iterate"}:
            return None
        return RouteDecision(
            route_name="plan_proposal_pending",
            request_text=text,
            reason=f"Pending proposal confirmation must be resolved before {command_decision.route_name} can continue",
            command=command_decision.command,
            complexity="medium",
            should_recover_context=True,
            candidate_skill_ids=_candidate_skills("plan_proposal_pending", skills, "design"),
            active_run_action="inspect_plan_proposal",
        )

    response = parse_plan_proposal_response(text)
    if response.action == "cancel":
        return RouteDecision(
            route_name="cancel_active",
            request_text=text,
            reason="Pending plan proposal cancelled by user",
            complexity="simple",
            should_recover_context=True,
            active_run_action="cancel",
        )
    action_to_reason = {
        "confirm": "Received confirmation to materialize the proposed plan package",
        "inspect": "Plan proposal is still waiting for package confirmation",
        "revise": "Received plan-proposal feedback before package materialization",
    }
    action_to_active_run_action = {
        "confirm": "confirm_plan_proposal",
        "inspect": "inspect_plan_proposal",
        "revise": "revise_plan_proposal",
    }
    return RouteDecision(
        route_name="plan_proposal_pending",
        request_text=text,
        reason=action_to_reason.get(response.action, "Plan proposal is still pending"),
        complexity="medium",
        should_recover_context=True,
        candidate_skill_ids=_candidate_skills("plan_proposal_pending", skills, "design"),
        active_run_action=action_to_active_run_action.get(response.action, "inspect_plan_proposal"),
    )


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
    current_plan,
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

    if not _looks_like_execution_confirm_feedback(text, current_plan=current_plan):
        return None

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

    if has_action and any(token in lowered for token in _LIGHT_EDIT_HINTS):
        return _ComplexitySignal("simple", "Detected a bounded docs/tests wording tweak", None)
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


def _classify_plan_meta_review(
    text: str,
    *,
    current_plan,
    skills: Iterable[SkillMeta],
) -> RouteDecision | None:
    if not _looks_like_plan_meta_review(text, current_plan=current_plan):
        return None
    return RouteDecision(
        route_name="consult",
        request_text=text,
        reason="Matched plan meta-review intent and bypassed new-plan scaffold creation",
        complexity="simple",
        should_recover_context=current_plan is not None,
        candidate_skill_ids=_candidate_skills("consult", skills, "analyze"),
    )


def _classify_analyze_challenge(
    text: str,
    *,
    current_plan,
    skills: Iterable[SkillMeta],
) -> RouteDecision | None:
    trigger_label = _match_analyze_challenge_label(text)
    if trigger_label is None:
        return None
    return RouteDecision(
        route_name="consult",
        request_text=text,
        reason=f"Matched first-principles analyze challenge signal {trigger_label}",
        complexity="simple",
        should_recover_context=current_plan is not None,
        candidate_skill_ids=_candidate_skills("consult", skills, "analyze"),
        artifacts={
            "consult_mode": "analyze_challenge",
            "trigger_label": trigger_label,
        },
    )


def _classify_plan_materialization_meta_debug(
    text: str,
    *,
    skills: Iterable[SkillMeta],
) -> RouteDecision | None:
    if not any(pattern.search(text) is not None for pattern in _PLAN_MATERIALIZATION_META_DEBUG_PATTERNS):
        return None
    return RouteDecision(
        route_name="consult",
        request_text=text,
        reason="Matched plan-materialization meta-debug intent and bypassed workflow routing",
        complexity="simple",
        should_recover_context=False,
        candidate_skill_ids=_candidate_skills("consult", skills, "analyze"),
    )


def detect_explain_only_consult_override(
    text: str,
    *,
    command: str | None = None,
    current_run=None,
    current_plan=None,
    current_plan_proposal=None,
    last_route: RouteDecision | None = None,
) -> dict[str, object] | None:
    normalized = text.strip()
    if not normalized or command is not None:
        return None
    lowered = normalized.lower()
    if any(keyword.lower() in lowered for keyword in _ACTION_KEYWORDS):
        return None

    has_no_change = any(pattern.search(normalized) is not None for pattern in _EXPLAIN_ONLY_NO_CHANGE_PATTERNS)
    has_explain_signal = any(pattern.search(normalized) is not None for pattern in _EXPLAIN_ONLY_SIGNAL_PATTERNS)
    if not (has_no_change and has_explain_signal):
        return None

    has_meta_debug_context = any(pattern.search(normalized) is not None for pattern in _EXPLAIN_ONLY_META_DEBUG_PATTERNS)
    has_referential_signal = any(pattern.search(normalized) is not None for pattern in _EXPLAIN_ONLY_REFERENTIAL_PATTERNS)
    has_recent_runtime_context = any(
        value is not None
        for value in (current_run, current_plan, current_plan_proposal, last_route)
    )
    if not has_meta_debug_context and not (has_referential_signal and has_recent_runtime_context):
        return None

    return {
        "reason": "Matched explain-only override and bypassed planning materialization",
        "artifacts": {
            "consult_mode": "explain_only_override",
            "consult_override_reason_code": CONSULT_EXPLAIN_ONLY_OVERRIDE_REASON_CODE,
        },
    }


def _is_consultation(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True
    if any(keyword.lower() in normalized for keyword in _ACTION_KEYWORDS):
        return False
    if text.endswith("?") or text.endswith("？"):
        return True
    return normalized.startswith(_QUESTION_PREFIXES)


def _is_protected_plan_asset_request(text: str) -> bool:
    return _PROTECTED_PLAN_ASSET_RE.search(text) is not None


def _has_process_semantic_intent(text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in _PROCESS_FORCE_PATTERNS)


def _plan_package_policy_for_route(route_name: str, request_text: str, *, config: RuntimeConfig) -> str:
    if route_name == "plan_only":
        return "immediate"
    if route_name not in {"workflow", "light_iterate"}:
        return "none"
    if _request_explicitly_materializes_plan(request_text, config=config):
        return "immediate"
    return "confirm"


def _request_explicitly_materializes_plan(request_text: str, *, config: RuntimeConfig) -> bool:
    if find_plan_by_request_reference(request_text, config=config) is not None:
        return False
    if request_explicitly_wants_new_plan(request_text):
        return True
    return any(pattern.search(request_text) is not None for pattern in _EXPLICIT_PLAN_PACKAGE_PATTERNS)


def _has_tradeoff_or_contract_split(text: str) -> bool:
    lowered = text.lower()
    if any(pattern.search(text) is not None for pattern in _TRADEOFF_FORCE_PATTERNS):
        return True
    split_signal = "还是" in text or "二选一" in text or "vs" in lowered or " or " in lowered
    if not split_signal:
        return False
    return any(token in lowered for token in _LONG_TERM_CONTRACT_HINTS)


def _looks_like_plan_meta_review(text: str, *, current_plan) -> bool:
    if not text.strip():
        return False
    has_plan_anchor = current_plan is not None or _is_protected_plan_asset_request(text)
    if not has_plan_anchor:
        return False
    if not any(pattern.search(text) is not None for pattern in _PLAN_META_REVIEW_PATTERNS):
        return False
    if any(pattern.search(text) is not None for pattern in _PLAN_META_REVIEW_EDIT_PATTERNS):
        return False
    if _is_protected_plan_asset_request(text):
        return True
    return any(pattern.search(text) is not None for pattern in _PLAN_META_REVIEW_ANCHORS)


def _match_analyze_challenge_label(text: str) -> str | None:
    normalized = text.strip()
    if not normalized:
        return None
    for label, patterns in _ANALYZE_CHALLENGE_TRIGGER_PATTERNS:
        if not any(pattern.search(normalized) is not None for pattern in patterns):
            continue
        if label == "A4" and not any(pattern.search(normalized) is not None for pattern in _ANALYZE_CHALLENGE_A4_DECISION_PATTERNS):
            continue
        return label
    return None


def _looks_like_execution_confirm_feedback(text: str, *, current_plan) -> bool:
    normalized = text.strip()
    if not normalized:
        return False

    response = parse_execution_confirm_response(normalized)
    if response.action in {"confirm", "status", "cancel"}:
        return True

    if _is_consultation(normalized):
        return False

    if any(pattern.search(normalized) is not None for pattern in _EXECUTION_CONFIRM_PLAN_FEEDBACK_PATTERNS):
        return True
    if any(pattern.search(normalized) is not None for pattern in _EXECUTION_CONFIRM_REVISION_PATTERNS):
        return True

    if current_plan is None:
        return False

    lowered = normalized.casefold()
    for anchor in (getattr(current_plan, "plan_id", ""), getattr(current_plan, "path", ""), getattr(current_plan, "title", "")):
        candidate = str(anchor or "").strip().casefold()
        if candidate and candidate in lowered:
            return True
    return False


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
