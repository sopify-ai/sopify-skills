"""User-facing output rendering for Sopify runtime."""

from __future__ import annotations

import os
import sys

from .models import RuntimeResult

_PHASE_LABELS = {
    "zh-CN": {
        "plan_only": "方案设计",
        "workflow": "方案设计",
        "light_iterate": "轻量迭代",
        "quick_fix": "快速修复",
        "resume_active": "开发实施",
        "exec_plan": "开发实施",
        "cancel_active": "命令完成",
        "compare": "模型对比",
        "replay": "咨询问答",
        "consult": "咨询问答",
        "default": "命令完成",
    },
    "en-US": {
        "plan_only": "Solution Design",
        "workflow": "Solution Design",
        "light_iterate": "Light Iteration",
        "quick_fix": "Quick Fix",
        "resume_active": "Development",
        "exec_plan": "Development",
        "cancel_active": "Command Complete",
        "compare": "Model Compare",
        "replay": "Q&A",
        "consult": "Q&A",
        "default": "Command Complete",
    },
}

_LABELS = {
    "zh-CN": {
        "plan": "方案",
        "summary": "概要",
        "replay": "回放",
        "route": "路由",
        "reason": "原因",
        "status": "状态",
        "current_plan": "当前方案",
        "stage": "阶段",
        "missing": "未生成",
        "none": "无",
        "cleared": "已清理当前活跃流程",
        "workflow_handoff": "已生成方案骨架，后续开发仍需宿主继续",
        "light_handoff": "已生成 light 方案，后续改动仍需宿主继续",
        "quick_fix_handoff": "已识别 quick_fix 路由，当前 repo-local runtime 未执行代码修改",
        "consult_handoff": "已识别咨询问答路由，当前 repo-local runtime 不生成正文回答",
        "compare_handoff": "已识别 compare 路由，当前通用入口未构造 compare runtime payload",
        "compare_ready": "compare runtime 已返回结构化结果",
        "replay_handoff": "已识别 replay 路由，当前仍需 workflow-learning 专用链路",
        "resume_handoff": "已恢复当前流程，当前 repo-local runtime 未执行 develop bridge",
        "exec_handoff": "已识别 exec 路由，当前 repo-local runtime 未执行 develop bridge",
        "default_handoff": "已识别路由，当前 repo-local runtime 未执行后续动作",
        "next_retry": "检查输入、配置或运行时状态后重试",
        "next_plan": "~go exec 执行 或 回复修改意见",
        "next_workflow": "在宿主会话中继续执行后续阶段，或显式使用 ~go plan 只规划",
        "next_light_iterate": "在宿主会话中继续执行轻量迭代，或回复修改意见",
        "next_resume": "在宿主会话中继续 develop 阶段",
        "next_exec": "在宿主会话中继续 develop 阶段",
        "next_cancel": "如需继续，重新发起 ~go plan 或 ~go",
        "next_compare": "人工选择候选结果并继续",
        "next_compare_bridge": "继续使用宿主侧 ~compare 专用桥接",
        "next_replay": "继续使用 workflow-learning 回放链路",
        "next_quick_fix": "在宿主会话中继续执行快速修复",
        "next_consult": "在宿主会话中继续问答，或改成明确变更请求",
    },
    "en-US": {
        "plan": "Plan",
        "summary": "Summary",
        "replay": "Replay",
        "route": "Route",
        "reason": "Reason",
        "status": "Status",
        "current_plan": "Current Plan",
        "stage": "Stage",
        "missing": "not generated",
        "none": "none",
        "cleared": "active flow cleared",
        "workflow_handoff": "Plan scaffold generated; downstream development still needs the host flow",
        "light_handoff": "Light plan generated; downstream changes still need the host flow",
        "quick_fix_handoff": "quick_fix route recognized; the repo-local runtime has not modified code",
        "consult_handoff": "Consult route recognized; the repo-local runtime does not generate full answers",
        "compare_handoff": "compare route recognized; the generic entry did not construct compare runtime payloads",
        "compare_ready": "compare runtime returned structured results",
        "replay_handoff": "replay route recognized; workflow-learning still needs its dedicated bridge",
        "resume_handoff": "Active flow restored; the repo-local runtime has not executed the develop bridge",
        "exec_handoff": "exec route recognized; the repo-local runtime has not executed the develop bridge",
        "default_handoff": "Route recognized; the repo-local runtime has not executed the downstream action",
        "next_retry": "Check the input, config, or runtime state and retry",
        "next_plan": "~go exec to execute or reply with feedback",
        "next_workflow": "Continue the downstream stages in the host session, or use ~go plan for planning only",
        "next_light_iterate": "Continue the light iteration in the host session, or reply with feedback",
        "next_resume": "Continue the develop stage in the host session",
        "next_exec": "Continue the develop stage in the host session",
        "next_cancel": "Start a new ~go plan or ~go flow when ready",
        "next_compare": "Review the candidate outputs and continue",
        "next_compare_bridge": "Use the host-side ~compare bridge for compare execution",
        "next_replay": "Use the workflow-learning replay flow",
        "next_quick_fix": "Continue the quick-fix flow in the host session",
        "next_consult": "Continue the discussion in the host session, or restate it as a change request",
    },
}

_TITLE_COLORS = {
    "green": "\033[32m",
    "blue": "\033[34m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
}
_RESET = "\033[0m"


def render_runtime_output(
    result: RuntimeResult,
    *,
    brand: str,
    language: str,
    title_color: str = "none",
    use_color: bool | None = None,
) -> str:
    """Render a runtime result into the Sopify summary format."""
    locale = _normalize_language(language)
    labels = _LABELS[locale]
    phase = _phase_label(result.route.route_name, locale)
    status = _status_symbol(result)
    title = _colorize(f"[{brand}] {phase} {status}", title_color=title_color, use_color=use_color)
    changes = _collect_changes(result)
    body = _core_lines(result, locale)
    next_hint = _next_hint(result, locale)

    lines = [title, ""]
    lines.extend(body)
    lines.extend(["", "---", f"Changes: {len(changes)} files"])
    if changes:
        lines.extend(f"  - {path}" for path in changes)
    else:
        lines.append(f"  - {labels['none']}")
    lines.extend(["", f"Next: {next_hint}"])
    return "\n".join(lines)


def render_runtime_error(
    message: str,
    *,
    brand: str,
    language: str,
    title_color: str = "none",
    use_color: bool | None = None,
) -> str:
    """Render a non-runtime exception into the same summary format."""
    locale = _normalize_language(language)
    labels = _LABELS[locale]
    phase = _PHASE_LABELS[locale]["default"]
    title = _colorize(f"[{brand}] {phase} ×", title_color=title_color, use_color=use_color)
    lines = [
        title,
        "",
        f"{labels['reason']}: {message}",
        "",
        "---",
        "Changes: 0 files",
        f"  - {labels['none']}",
        "",
        f"Next: {labels['next_retry']}",
    ]
    return "\n".join(lines)


def _core_lines(result: RuntimeResult, language: str) -> list[str]:
    labels = _LABELS[language]
    route_name = result.route.route_name

    if route_name == "plan_only" and result.plan_artifact is not None:
        replay_value = result.replay_session_dir or labels["missing"]
        return [
            f"{labels['plan']}: {result.plan_artifact.path}",
            f"{labels['summary']}: {result.plan_artifact.summary}",
            f"{labels['replay']}: {replay_value}",
        ]

    if route_name in {"workflow", "light_iterate"} and result.plan_artifact is not None:
        return [
            f"{labels['plan']}: {result.plan_artifact.path}",
            f"{labels['summary']}: {result.plan_artifact.summary}",
            f"{labels['status']}: {_route_status_message(result, language)}",
        ]

    if route_name in {"resume_active", "exec_plan"} and result.recovered_context.current_run is not None:
        current_plan = result.recovered_context.current_plan
        return [
            f"{labels['current_plan']}: {current_plan.path if current_plan is not None else labels['missing']}",
            f"{labels['stage']}: {result.recovered_context.current_run.stage}",
            f"{labels['status']}: {_route_status_message(result, language)}",
        ]

    if route_name == "cancel_active":
        return [
            f"{labels['status']}: {labels['cleared']}",
            f"{labels['route']}: {route_name}",
            f"{labels['replay']}: {result.replay_session_dir or labels['missing']}",
        ]

    return [
        f"{labels['route']}: {route_name}",
        f"{labels['status']}: {_route_status_message(result, language)}",
        f"{labels['reason']}: {_diagnostic_reason(result)}",
    ]


def _collect_changes(result: RuntimeResult) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in result.plan_artifact.files if result.plan_artifact is not None else ():
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    for path in result.recovered_context.loaded_files:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def _next_hint(result: RuntimeResult, language: str) -> str:
    labels = _LABELS[language]
    route_name = result.route.route_name
    if route_name == "plan_only" and result.plan_artifact is not None:
        return labels["next_plan"]
    if route_name == "workflow" and result.plan_artifact is not None:
        return labels["next_workflow"]
    if route_name == "light_iterate" and result.plan_artifact is not None:
        return labels["next_light_iterate"]
    if route_name == "resume_active":
        return labels["next_resume"]
    if route_name == "exec_plan":
        return labels["next_exec"]
    if route_name == "cancel_active":
        return labels["next_cancel"]
    if route_name == "compare":
        return labels["next_compare"] if result.skill_result else labels["next_compare_bridge"]
    if route_name == "replay":
        return labels["next_replay"]
    if route_name == "quick_fix":
        return labels["next_quick_fix"]
    if route_name == "consult":
        return labels["next_consult"]
    return labels["next_retry"]


def _status_symbol(result: RuntimeResult) -> str:
    route_name = result.route.route_name
    if route_name == "plan_only":
        return "✓" if result.plan_artifact is not None else "!"
    if route_name == "cancel_active":
        return "✓"
    if route_name == "compare" and result.skill_result:
        return "✓"
    if route_name in {"workflow", "light_iterate", "quick_fix", "consult", "replay", "resume_active", "exec_plan", "compare"}:
        return "!"
    if result.notes:
        return "!"
    return "✓"


def _route_status_message(result: RuntimeResult, language: str) -> str:
    labels = _LABELS[language]
    route_name = result.route.route_name
    if route_name == "workflow":
        return labels["workflow_handoff"]
    if route_name == "light_iterate":
        return labels["light_handoff"]
    if route_name == "quick_fix":
        return labels["quick_fix_handoff"]
    if route_name == "consult":
        return labels["consult_handoff"]
    if route_name == "compare":
        return labels["compare_ready"] if result.skill_result else labels["compare_handoff"]
    if route_name == "replay":
        return labels["replay_handoff"]
    if route_name == "resume_active":
        return labels["resume_handoff"]
    if route_name == "exec_plan":
        return labels["exec_handoff"]
    return labels["default_handoff"]


def _diagnostic_reason(result: RuntimeResult) -> str:
    if result.notes:
        return result.notes[0]
    if result.route.reason:
        return result.route.reason
    return result.route.route_name


def _phase_label(route_name: str, language: str) -> str:
    labels = _PHASE_LABELS[language]
    return labels.get(route_name, labels["default"])


def _normalize_language(language: str) -> str:
    return "en-US" if language == "en-US" else "zh-CN"


def _colorize(text: str, *, title_color: str, use_color: bool | None) -> str:
    if title_color == "none":
        return text
    if use_color is None:
        use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if not use_color:
        return text
    color_code = _TITLE_COLORS.get(title_color)
    if color_code is None:
        return text
    return f"{color_code}{text}{_RESET}"
