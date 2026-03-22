"""Plan scaffold generator for Sopify runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
import re
from typing import Iterable, List, Mapping, Sequence

from ._yaml import YamlParseError, load_yaml
from .decision import option_by_id
from .knowledge_sync import render_knowledge_sync_front_matter
from .models import DecisionState, PlanArtifact, RuntimeConfig
from .state import iso_now

_FRONT_MATTER_RE = re.compile(r"\A---\n(?P<front>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
_PLAN_REFERENCE_RE = re.compile(r"(?P<plan_id>\d{8}_[a-z0-9][a-z0-9_.-]*)", re.IGNORECASE)
_EXPLICIT_NEW_PLAN_PATTERNS = (
    re.compile(r"\bnew\s+plan\b", re.IGNORECASE),
    re.compile(r"\bcreate\s+(?:a\s+)?new\s+plan\b", re.IGNORECASE),
    re.compile(r"新建(?:一个)?\s*plan", re.IGNORECASE),
    re.compile(r"新\s*plan", re.IGNORECASE),
    re.compile(r"新的\s*plan", re.IGNORECASE),
    re.compile(r"另起(?:一个)?\s*plan", re.IGNORECASE),
    re.compile(r"新增(?:一个)?\s*plan", re.IGNORECASE),
)


def create_plan_scaffold(
    request_text: str,
    *,
    config: RuntimeConfig,
    level: str,
    decision_state: DecisionState | None = None,
) -> PlanArtifact:
    """Create a deterministic plan package scaffold.

    Args:
        request_text: User request without command prefix.
        config: Runtime config.
        level: One of `light`, `standard`, `full`.

    Returns:
        The generated plan artifact metadata.
    """
    if level not in {"light", "standard", "full"}:
        raise ValueError(f"Unsupported plan level: {level}")

    title = _derive_title(request_text)
    topic_key = derive_topic_key(request_text)
    plan_id = _make_plan_id(topic_key, plan_root=config.plan_root)
    plan_dir = config.plan_root / plan_id
    plan_dir.mkdir(parents=True, exist_ok=False)

    summary = request_text.strip() or title
    files: List[str] = []

    if level == "light":
        plan_path = plan_dir / "plan.md"
        plan_path.write_text(
            _render_light_plan(
                title,
                summary,
                plan_id=plan_id,
                feature_key=topic_key,
                decision_state=decision_state,
            ),
            encoding="utf-8",
        )
        files.append(str(plan_path.relative_to(config.workspace_root)))
    else:
        background = plan_dir / "background.md"
        design = plan_dir / "design.md"
        tasks = plan_dir / "tasks.md"
        background.write_text(_render_background(title, summary), encoding="utf-8")
        design.write_text(_render_design(title, summary, level, decision_state=decision_state), encoding="utf-8")
        tasks.write_text(
            _render_tasks(
                title,
                plan_id=plan_id,
                feature_key=topic_key,
                level=level,
                decision_state=decision_state,
            ),
            encoding="utf-8",
        )
        files.extend(
            str(path.relative_to(config.workspace_root))
            for path in (background, design, tasks)
        )
        if level == "full":
            adr_dir = plan_dir / "adr"
            diagrams_dir = plan_dir / "diagrams"
            adr_dir.mkdir()
            diagrams_dir.mkdir()
            files.extend(
                str(path.relative_to(config.workspace_root))
                for path in (adr_dir, diagrams_dir)
            )

    return PlanArtifact(
        plan_id=plan_id,
        title=title,
        summary=summary,
        level=level,
        path=str(plan_dir.relative_to(config.workspace_root)),
        files=tuple(files),
        created_at=iso_now(),
        topic_key=topic_key,
    )


def _derive_title(request_text: str) -> str:
    cleaned = request_text.strip()
    if not cleaned:
        return "Untitled Plan"
    first_line = cleaned.splitlines()[0].strip()
    if len(first_line) <= 48:
        return first_line
    return first_line[:45].rstrip() + "..."


def derive_topic_key(request_text: str) -> str:
    cleaned = " ".join(request_text.split())
    if not cleaned:
        return "task"
    normalized = _slugify(cleaned)[:48].rstrip("-")
    if normalized:
        return normalized
    return f"task-{sha1(cleaned.encode('utf-8')).hexdigest()[:6]}"


def request_explicitly_wants_new_plan(request_text: str) -> bool:
    return any(pattern.search(request_text) is not None for pattern in _EXPLICIT_NEW_PLAN_PATTERNS)


def find_plan_by_request_reference(request_text: str, *, config: RuntimeConfig) -> PlanArtifact | None:
    for match in _PLAN_REFERENCE_RE.finditer(request_text):
        plan_id = (match.group("plan_id") or "").strip()
        if not plan_id:
            continue
        artifact = load_plan_artifact(config.plan_root / plan_id, config=config)
        if artifact is not None:
            return artifact
    return None


def find_plan_by_topic_key(topic_key: str, *, config: RuntimeConfig) -> PlanArtifact | None:
    matches: list[PlanArtifact] = []
    plan_root = config.plan_root
    if not plan_root.exists():
        return None
    for plan_dir in sorted(plan_root.iterdir()):
        artifact = load_plan_artifact(plan_dir, config=config)
        if artifact is None:
            continue
        candidate_topic_key = artifact.topic_key or derive_topic_key(artifact.title)
        if candidate_topic_key == topic_key:
            matches.append(artifact)
            if len(matches) > 1:
                return None
    return matches[0] if len(matches) == 1 else None


def load_plan_artifact(plan_dir: Path, *, config: RuntimeConfig) -> PlanArtifact | None:
    if not plan_dir.exists() or not plan_dir.is_dir():
        return None

    metadata_path = _pick_metadata_file(plan_dir)
    if metadata_path is None:
        return None

    metadata, body = _load_plan_metadata(metadata_path)
    if metadata is None:
        return None

    plan_id = str(metadata.get("plan_id") or plan_dir.name)
    level = str(metadata.get("level") or ("light" if metadata_path.name == "plan.md" else "standard"))
    title = _extract_title(body) or plan_id
    summary = _extract_summary(body, fallback=title)
    topic_key = str(metadata.get("topic_key") or metadata.get("feature_key") or derive_topic_key(title))
    files = tuple(str(path.relative_to(config.workspace_root)) for path in _collect_plan_files(plan_dir))
    created_at = _path_created_at(metadata_path)

    return PlanArtifact(
        plan_id=plan_id,
        title=title,
        summary=summary,
        level=level,
        path=str(plan_dir.relative_to(config.workspace_root)),
        files=files,
        created_at=created_at,
        topic_key=topic_key,
    )


def _make_plan_id(topic_key: str, *, plan_root: Path) -> str:
    date_prefix = datetime.now().strftime("%Y%m%d")
    base = f"{date_prefix}_{topic_key}"
    candidate = base
    suffix = 2
    while (plan_root / candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _slugify(value: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return ascii_slug or "task"
def _render_light_plan(title: str, summary: str, *, plan_id: str, feature_key: str, decision_state: DecisionState | None) -> str:
    return (
        _render_plan_front_matter(plan_id=plan_id, feature_key=feature_key, level="light", decision_state=decision_state)
        +
        f"# {title}\n\n"
        "## 背景\n"
        f"{summary}\n\n"
        f"{_render_decision_section(decision_state)}"
        "## 方案\n"
        "- 明确改动范围与边界\n"
        "- 实现最小必要变更\n"
        "- 补充验证与回放记录\n\n"
        "## 任务\n"
        "- [ ] 梳理当前上下文与目标文件\n"
        "- [ ] 实施并验证最小改动\n"
        "- [ ] 同步状态与后续说明\n\n"
        "## 变更文件\n"
        "- 待分析\n"
    )


def _render_background(title: str, summary: str) -> str:
    return (
        f"# 变更提案: {title}\n\n"
        "## 需求背景\n"
        f"{summary}\n\n"
        "## 变更内容\n"
        "1. 收口运行时边界\n"
        "2. 明确状态与产物路径\n"
        "3. 保持主流程可恢复\n\n"
        "## 影响范围\n"
        "- 模块: 待分析\n"
        "- 文件: 待分析\n\n"
        "## 风险评估\n"
        "- 风险: 需要避免把主流程做重\n"
        "- 缓解: 先实现最小闭环，再扩展\n"
    )


def _render_design(title: str, summary: str, level: str, *, decision_state: DecisionState | None) -> str:
    extra = "\n## ADR / 图表\n仅在 full 级别下继续补充。\n" if level == "full" else ""
    return (
        f"# 技术设计: {title}\n\n"
        f"{_render_decision_section(decision_state)}"
        "## 技术方案\n"
        f"- 核心目标: {summary}\n"
        "- 实现要点:\n"
        "  - 保持模块职责清晰\n"
        "  - 以文件系统状态作为单一事实源\n"
        "  - 把可重复控制点收口到 runtime\n\n"
        "## 架构设计\n"
        "- 入口负责引导，不承载业务细节\n"
        "- 路由、状态、上下文恢复、产物生成分层实现\n\n"
        "## 安全与性能\n"
        "- 安全: 不做全量自动加载知识库\n"
        "- 性能: 只读取最小必要上下文\n"
        f"{extra}"
    )


def _render_tasks(title: str, *, plan_id: str, feature_key: str, level: str, decision_state: DecisionState | None) -> str:
    return (
        _render_plan_front_matter(plan_id=plan_id, feature_key=feature_key, level=level, decision_state=decision_state)
        +
        f"# 任务清单: {title}\n\n"
        "## 1. runtime\n"
        "- [ ] 1.1 明确模块职责与边界\n"
        "- [ ] 1.2 实现核心状态与路由逻辑\n"
        "- [ ] 1.3 验证跨会话恢复路径\n\n"
        "## 2. 测试\n"
        "- [ ] 2.1 补充行为测试\n\n"
        "## 3. 文档\n"
        "- [ ] 3.1 同步蓝图与任务状态\n"
    )


def _render_plan_front_matter(
    *,
    plan_id: str,
    feature_key: str,
    level: str,
    decision_state: DecisionState | None,
) -> str:
    lines = [
        "---",
        f"plan_id: {plan_id}",
        f"feature_key: {feature_key}",
        f"level: {level}",
        "lifecycle_state: active",
        *render_knowledge_sync_front_matter(level),
        "archive_ready: false",
    ]
    if decision_state is not None:
        selected_option = decision_state.selected_option_id or ""
        lines.extend(
            [
                "decision_checkpoint:",
                "  required: true",
                f"  decision_id: {decision_state.decision_id}",
                f"  selected_option_id: {selected_option}",
                f"  status: {decision_state.status}",
            ]
        )
    lines.extend(["---", "", ""])
    return "\n".join(lines)


def _render_decision_section(decision_state: DecisionState | None) -> str:
    if decision_state is None:
        return ""

    selected_option = option_by_id(decision_state, decision_state.selected_option_id or "")
    selected_title = selected_option.title if selected_option is not None else "待确认"
    options = "\n".join(
        f"- `{option.option_id}`: {option.title}"
        + (" (推荐)" if option.recommended else "")
        for option in decision_state.options
    )
    return (
        "## 决策确认\n"
        f"- 问题: {decision_state.question}\n"
        f"- 结果: {selected_title}\n"
        f"- 决策 ID: `{decision_state.decision_id}`\n"
        "- 候选方案:\n"
        f"{options}\n\n"
    )


def _pick_metadata_file(plan_dir: Path) -> Path | None:
    for filename in ("plan.md", "tasks.md"):
        candidate = plan_dir / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _load_plan_metadata(metadata_path: Path) -> tuple[Mapping[str, object] | None, str]:
    raw_text = metadata_path.read_text(encoding="utf-8")
    match = _FRONT_MATTER_RE.match(raw_text)
    if match is None:
        return None, raw_text
    front_matter = match.group("front")
    body = match.group("body")
    try:
        metadata = load_yaml(front_matter)
    except YamlParseError:
        return None, body
    if not isinstance(metadata, Mapping):
        return None, body
    return metadata, body


def _collect_plan_files(plan_dir: Path) -> list[Path]:
    collected: list[Path] = []
    for child in sorted(plan_dir.iterdir()):
        collected.append(child)
    return collected


def _extract_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _extract_summary(body: str, *, fallback: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return fallback
    for index, line in enumerate(lines):
        if line.startswith("# "):
            if index + 1 < len(lines):
                return lines[index + 1]
            break
    return lines[0]


def _path_created_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
