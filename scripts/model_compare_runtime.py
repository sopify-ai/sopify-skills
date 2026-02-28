#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多模型对比运行时（MVP）。

本模块只做一件事：把 `~compare` 运行时的关键链路收口到一个可复用实现里，
严格按以下顺序执行：

1) 抽取（extract）
2) 脱敏（redact）
3) 截断（truncate）
4) 统一请求（shared payload）
5) 并发调用（fan-out）
6) 结果归一化（normalize）

契约要点（与文档一致）：
- `context_bridge` 默认开启；关闭时走旁路（仅发送问题文本）
- `context_bridge=true` 且存在可调用扩展候选时，才会构建 `context_pack`
- 若构建后 `facts=0` 且 `snippets=0`，触发空包降级：`context_pack empty`
- 输出必须包含元信息：`bridge/files/snippets/redactions/truncated`
- 降级原因使用统一英文 reason code，避免中英文文档口径漂移

说明：
- 网络调用通过 `model_caller` 回调注入，模块本身不耦合具体 SDK。
- 该实现优先可测试、可读性与契约稳定性，而非极限性能。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# =========================
# 固定预算（执行层硬约束）
# =========================
DEFAULT_MAX_FILES = 6
DEFAULT_MAX_SNIPPETS = 10
DEFAULT_MAX_LINES_PER_SNIPPET = 160
DEFAULT_MAX_CHARS_TOTAL = 12000

# 抽取阶段的探索上限（先宽后严，最终仍会被固定预算截断）
EXTRACT_MAX_FILES = 8
EXTRACT_SNIPPETS_PER_FILE = 2
EXTRACT_CONTEXT_WINDOW = 80
MAX_FACTS = 8

# 统一 reason code（文档与运行时共享语义）。
REASON_FEATURE_DISABLED = "FEATURE_DISABLED"
REASON_NO_ENABLED_CANDIDATES = "NO_ENABLED_CANDIDATES"
REASON_UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
REASON_MISSING_API_KEY = "MISSING_API_KEY"
REASON_DEFAULT_MODEL_UNAVAILABLE = "DEFAULT_MODEL_UNAVAILABLE"
REASON_CONTEXT_PACK_EMPTY = "CONTEXT_PACK_EMPTY"
REASON_CONTEXT_BRIDGE_BYPASSED = "CONTEXT_BRIDGE_BYPASSED"
REASON_INSUFFICIENT_USABLE_MODELS = "INSUFFICIENT_USABLE_MODELS"


def _reason(code: str, detail: str = "") -> str:
    """统一 reason 字符串格式，便于跨语言文档保持一致。"""
    if detail:
        return f"{code}: {detail}"
    return code


@dataclass(frozen=True)
class Budget:
    """上下文包预算。"""

    max_files: int = DEFAULT_MAX_FILES
    max_snippets: int = DEFAULT_MAX_SNIPPETS
    max_lines_per_snippet: int = DEFAULT_MAX_LINES_PER_SNIPPET
    max_chars_total: int = DEFAULT_MAX_CHARS_TOTAL


@dataclass(frozen=True)
class RuntimeConfig:
    """多模型对比运行时配置（只保留本模块真正需要的字段）。"""

    enabled: bool = True
    timeout_sec: int = 25
    max_parallel: int = 3
    include_default_model: bool = True
    context_bridge: bool = True
    budget: Budget = field(default_factory=Budget)


@dataclass(frozen=True)
class Candidate:
    """可调用模型候选。"""

    id: str
    provider: str
    model: str
    base_url: str = ""
    enabled: bool = True
    api_key_env: str = ""
    api_key: str = ""
    is_default: bool = False

    @property
    def is_external(self) -> bool:
        """是否为扩展候选（当前契约下扩展候选即 openai_compatible）。"""
        return self.provider == "openai_compatible" and not self.is_default


@dataclass(frozen=True)
class Snippet:
    """上下文片段。"""

    path: str
    start_line: int
    end_line: int
    content: str
    source: str
    priority: int


@dataclass
class ContextPack:
    """统一上下文包（会被同包分发到多个候选）。"""

    facts: List[str] = field(default_factory=list)
    snippets: List[Snippet] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """空包判定：facts=0 且 snippets=0。"""
        return len(self.facts) == 0 and len(self.snippets) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": list(self.facts),
            "snippets": [
                {
                    "path": snippet.path,
                    "start_line": snippet.start_line,
                    "end_line": snippet.end_line,
                    "content": snippet.content,
                }
                for snippet in self.snippets
            ],
            "meta": dict(self.meta),
        }


@dataclass
class NormalizedResult:
    """单个候选的归一化结果。"""

    candidate_id: str
    status: str
    latency_ms: int
    answer: str = ""
    error: str = ""
    payload_signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "payload_signature": self.payload_signature,
        }
        if self.answer:
            data["answer"] = self.answer
        if self.error:
            data["error"] = self.error
        return data


@dataclass
class CompareRuntimeOutput:
    """运行时总输出（面向调用方的稳定结构）。"""

    mode: str
    metadata: Dict[str, Any]
    results: List[NormalizedResult]
    fallback_reasons: List[str] = field(default_factory=list)
    context_pack: Optional[ContextPack] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "mode": self.mode,
            "metadata": dict(self.metadata),
            "results": [result.to_dict() for result in self.results],
            "fallback_reasons": list(self.fallback_reasons),
        }
        if self.context_pack is not None:
            payload["context_pack"] = self.context_pack.to_dict()
        return payload


# model_caller 约定：输入 (candidate, payload, timeout_sec) -> str 或 dict
ModelCaller = Callable[[Candidate, Mapping[str, Any], int], Any]


# =========================
# 正则与文本工具
# =========================
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
AUTH_HEADER_RE = re.compile(r"(?im)^(\s*Authorization\s*:\s*).+$")
COOKIE_HEADER_RE = re.compile(r"(?im)^(\s*(?:Cookie|Set-Cookie)\s*:\s*).+$")
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]+")
SECRET_KV_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\b\s*([:=])\s*([\"']?)[^\s\"']+\3"
)

# 问题里可能出现的路径线索，如 src/foo.py 或 config.yaml
PATH_HINT_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)"
)

# 用于关键词抽取：中英文都支持，避免过短 token 带来噪声
KEYWORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{1,}|[\u4e00-\u9fff]{2,}")


def _safe_int(value: Any, default: int) -> int:
    """把任意输入安全转成正整数，失败时回退默认值。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def load_runtime_config(raw_multi_model: Optional[Mapping[str, Any]]) -> RuntimeConfig:
    """加载配置并补齐默认值。

    注意：这里是“严格默认”实现，确保 `context_bridge=true` 与
    `include_default_model=true` 在未配置时都生效。
    """
    raw = dict(raw_multi_model or {})
    return RuntimeConfig(
        enabled=bool(raw.get("enabled", True)),
        timeout_sec=_safe_int(raw.get("timeout_sec", 25), 25),
        max_parallel=_safe_int(raw.get("max_parallel", 3), 3),
        include_default_model=bool(raw.get("include_default_model", True)),
        context_bridge=bool(raw.get("context_bridge", True)),
        budget=Budget(),
    )


def build_candidates(
    raw_multi_model: Optional[Mapping[str, Any]],
    *,
    config: RuntimeConfig,
    default_candidate: Optional[Candidate],
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[List[Candidate], List[str]]:
    """构建“可调用候选”列表，并返回降级原因增量。

    规则：
    - 仅采集 `enabled=true` 的候选。
    - `openai_compatible` 必须有可读取环境变量 key。
    - include_default_model=true 且提供 default_candidate 时，补入默认模型。
    """
    reasons: List[str] = []
    raw = dict(raw_multi_model or {})
    raw_candidates = raw.get("candidates") or []
    enabled_candidates = [item for item in raw_candidates if isinstance(item, Mapping) and item.get("enabled", False)]

    if not enabled_candidates:
        reasons.append(_reason(REASON_NO_ENABLED_CANDIDATES, "candidates[*].enabled=true count=0"))

    env_map: Mapping[str, str] = env or os.environ
    candidates: List[Candidate] = []

    for item in enabled_candidates:
        candidate = Candidate(
            id=str(item.get("id") or "unknown"),
            provider=str(item.get("provider") or "openai_compatible"),
            model=str(item.get("model") or ""),
            base_url=str(item.get("base_url") or ""),
            enabled=True,
            api_key_env=str(item.get("api_key_env") or ""),
        )

        if candidate.provider != "openai_compatible":
            reasons.append(
                _reason(
                    REASON_UNSUPPORTED_PROVIDER,
                    f"id={candidate.id}, provider={candidate.provider}",
                )
            )
            continue

        if not candidate.api_key_env:
            reasons.append(_reason(REASON_MISSING_API_KEY, f"candidate_id={candidate.id}"))
            continue

        key = (env_map.get(candidate.api_key_env) or "").strip()
        if not key:
            reasons.append(_reason(REASON_MISSING_API_KEY, f"candidate_id={candidate.id}"))
            continue

        candidates.append(
            Candidate(
                id=candidate.id,
                provider=candidate.provider,
                model=candidate.model,
                base_url=candidate.base_url,
                enabled=True,
                api_key_env=candidate.api_key_env,
                api_key=key,
                is_default=False,
            )
        )

    if config.include_default_model:
        if default_candidate is not None:
            candidates.append(default_candidate)
        else:
            reasons.append(_reason(REASON_DEFAULT_MODEL_UNAVAILABLE, "include_default_model=true"))

    return candidates, reasons


def _is_probably_text(path: Path, max_bytes: int = 512 * 1024) -> bool:
    """轻量文本文件探测：限制大小 + NUL 字节检查。"""
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return False
        with path.open("rb") as stream:
            chunk = stream.read(2048)
        return b"\x00" not in chunk
    except OSError:
        return False


def _iter_workspace_files(workspace_root: Path) -> Iterable[Path]:
    """遍历工作区文件，跳过常见噪声目录。"""
    ignored_dirs = {".git", "node_modules", ".venv", "dist", "build", "coverage", "__pycache__"}
    for path in workspace_root.rglob("*"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        if _is_probably_text(path):
            yield path


def _extract_keywords(question: str) -> List[str]:
    """从问题文本提取关键词，去重后按出现顺序返回。"""
    seen: set[str] = set()
    keywords: List[str] = []
    for token in KEYWORD_RE.findall(question):
        normalized = token.strip()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(normalized)
    return keywords[:24]


def _extract_path_hints(question: str, workspace_root: Path) -> List[Path]:
    """从问题里提取路径线索，并过滤成工作区内存在文件。"""
    paths: List[Path] = []
    seen: set[Path] = set()
    for match in PATH_HINT_RE.finditer(question):
        rel_path = match.group("path")
        candidate = (workspace_root / rel_path).resolve()
        try:
            candidate.relative_to(workspace_root.resolve())
        except ValueError:
            continue
        if candidate.is_file() and candidate not in seen and _is_probably_text(candidate):
            seen.add(candidate)
            paths.append(candidate)
    return paths


def _find_keyword_hits(lines: Sequence[str], keywords: Sequence[str]) -> List[int]:
    """返回关键词命中行号（1-based），最多前若干个。"""
    hits: List[int] = []
    lowered_keywords = [keyword.lower() for keyword in keywords if keyword]
    for index, line in enumerate(lines, start=1):
        low_line = line.lower()
        if any(keyword in low_line for keyword in lowered_keywords):
            hits.append(index)
        if len(hits) >= EXTRACT_SNIPPETS_PER_FILE:
            break
    return hits


def _read_file_lines(path: Path) -> List[str]:
    """按 UTF-8 读取文本；异常时降级为空。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return text.splitlines()


def _make_snippet(path: Path, lines: Sequence[str], hit_line: int, *, source: str, priority: int) -> Snippet:
    """按“命中行 ±80 行”生成一个片段。"""
    start_line = max(1, hit_line - EXTRACT_CONTEXT_WINDOW)
    end_line = min(len(lines), hit_line + EXTRACT_CONTEXT_WINDOW)
    content = "\n".join(lines[start_line - 1 : end_line])
    return Snippet(
        path=str(path),
        start_line=start_line,
        end_line=end_line,
        content=content,
        source=source,
        priority=priority,
    )


def extract_context_pack(
    question: str,
    *,
    workspace_root: Path,
    explicit_files: Optional[Sequence[str]] = None,
    explicit_snippets: Optional[Sequence[Mapping[str, Any]]] = None,
) -> ContextPack:
    """阶段 1：上下文抽取。

    固定优先级：
    1) 用户显式提供片段/路径
    2) 问题里的路径线索
    3) 工作区关键词检索
    """
    snippets: List[Snippet] = []

    # Step 1.1：先放入显式片段（最高优先级）。
    for raw_snippet in explicit_snippets or []:
        path = str(raw_snippet.get("path") or "")
        start_line = _safe_int(raw_snippet.get("start_line", 1), 1)
        end_line = _safe_int(raw_snippet.get("end_line", start_line), start_line)
        content = str(raw_snippet.get("content") or "").strip()

        if not path:
            continue

        # 若调用方只给了 path+行号，未给 content，则尝试本地补读。
        if not content:
            abs_path = (workspace_root / path).resolve()
            lines = _read_file_lines(abs_path)
            if lines:
                start = max(1, start_line)
                end = min(len(lines), end_line)
                content = "\n".join(lines[start - 1 : end])

        if not content:
            continue

        snippets.append(
            Snippet(
                path=path,
                start_line=start_line,
                end_line=end_line,
                content=content,
                source="explicit_snippet",
                priority=0,
            )
        )

    keywords = _extract_keywords(question)
    path_hints = _extract_path_hints(question, workspace_root)

    # Step 1.2：维护候选文件清单，并记录来源优先级。
    file_priority: Dict[Path, Tuple[int, str]] = {}

    for rel in explicit_files or []:
        path = (workspace_root / rel).resolve()
        if path.is_file() and _is_probably_text(path):
            file_priority[path] = (0, "explicit_file")

    for hint_path in path_hints:
        file_priority.setdefault(hint_path, (1, "question_path"))

    # Step 1.3：关键词检索补充文件，直到触达探索上限。
    if len(file_priority) < EXTRACT_MAX_FILES and keywords:
        for file_path in _iter_workspace_files(workspace_root):
            if file_path in file_priority:
                continue
            lines = _read_file_lines(file_path)
            if not lines:
                continue
            hits = _find_keyword_hits(lines, keywords)
            if hits:
                file_priority[file_path] = (2, "keyword_search")
            if len(file_priority) >= EXTRACT_MAX_FILES:
                break

    # Step 1.4：针对每个候选文件提取最多 2 段片段。
    for file_path, (priority, source) in sorted(file_priority.items(), key=lambda item: item[1][0]):
        lines = _read_file_lines(file_path)
        if not lines:
            continue

        hits = _find_keyword_hits(lines, keywords)
        if not hits:
            # 没命中关键词时，仍保留文件头部附近 1 段，保证显式文件不会丢失。
            hits = [1]

        for hit_line in hits[:EXTRACT_SNIPPETS_PER_FILE]:
            snippets.append(_make_snippet(file_path, lines, hit_line, source=source, priority=priority))

    # Step 1.5：产出 facts（仅保留可验证、可追溯描述）。
    facts: List[str] = []
    for snippet in snippets[:MAX_FACTS]:
        facts.append(f"{snippet.path}:{snippet.start_line}-{snippet.end_line} (source={snippet.source})")

    return ContextPack(facts=facts, snippets=snippets, meta={})


def _redact_text(text: str) -> Tuple[str, int]:
    """对单段文本执行脱敏并统计命中次数。"""
    redaction_count = 0

    text, count = PRIVATE_KEY_RE.subn("<REDACTED_PRIVATE_KEY_BLOCK>", text)
    redaction_count += count

    text, count = AUTH_HEADER_RE.subn(r"\1<REDACTED_AUTHORIZATION>", text)
    redaction_count += count

    text, count = COOKIE_HEADER_RE.subn(r"\1<REDACTED_COOKIE>", text)
    redaction_count += count

    text, count = BEARER_RE.subn("Bearer <REDACTED_BEARER>", text)
    redaction_count += count

    text, count = SECRET_KV_RE.subn(r"\1\2<REDACTED_SECRET>", text)
    redaction_count += count

    return text, redaction_count


def redact_context_pack(pack: ContextPack) -> ContextPack:
    """阶段 2：对 facts/snippets 统一脱敏。"""
    total_redactions = 0

    redacted_facts: List[str] = []
    for fact in pack.facts:
        redacted, count = _redact_text(fact)
        redacted_facts.append(redacted)
        total_redactions += count

    redacted_snippets: List[Snippet] = []
    for snippet in pack.snippets:
        redacted_content, count = _redact_text(snippet.content)
        redacted_snippets.append(
            Snippet(
                path=snippet.path,
                start_line=snippet.start_line,
                end_line=snippet.end_line,
                content=redacted_content,
                source=snippet.source,
                priority=snippet.priority,
            )
        )
        total_redactions += count

    meta = dict(pack.meta)
    meta["redaction_count"] = total_redactions
    return ContextPack(facts=redacted_facts, snippets=redacted_snippets, meta=meta)


def _trim_snippet_lines(snippet: Snippet, max_lines: int) -> Tuple[Snippet, bool]:
    """单片段按行数截断。"""
    lines = snippet.content.splitlines()
    if len(lines) <= max_lines:
        return snippet, False

    trimmed_content = "\n".join(lines[:max_lines])
    trimmed = Snippet(
        path=snippet.path,
        start_line=snippet.start_line,
        end_line=snippet.start_line + max_lines - 1,
        content=trimmed_content,
        source=snippet.source,
        priority=snippet.priority,
    )
    return trimmed, True


def truncate_context_pack(pack: ContextPack, budget: Budget) -> ContextPack:
    """阶段 3：按预算截断（files/snippets/lines/chars）。"""
    truncated = False

    # Step 3.1：先按优先级排序，确保“显式提供 > 问题命中 > 关键词补充”。
    ordered_snippets = sorted(pack.snippets, key=lambda item: (item.priority, item.path, item.start_line))

    # Step 3.2：限制文件数量（max_files）。
    selected_paths: List[str] = []
    selected_path_set: set[str] = set()
    for snippet in ordered_snippets:
        if snippet.path not in selected_path_set:
            selected_paths.append(snippet.path)
            selected_path_set.add(snippet.path)
    keep_paths = set(selected_paths[: budget.max_files])
    if len(selected_paths) > budget.max_files:
        truncated = True

    file_limited = [snippet for snippet in ordered_snippets if snippet.path in keep_paths]

    # Step 3.3：限制片段数量（max_snippets）。
    if len(file_limited) > budget.max_snippets:
        truncated = True
    snippet_limited = file_limited[: budget.max_snippets]

    # Step 3.4：限制每段行数（max_lines_per_snippet）。
    line_limited: List[Snippet] = []
    for snippet in snippet_limited:
        trimmed_snippet, changed = _trim_snippet_lines(snippet, budget.max_lines_per_snippet)
        line_limited.append(trimmed_snippet)
        if changed:
            truncated = True

    # Step 3.5：限制总字符数（max_chars_total），先放 facts 再放 snippets。
    remain = budget.max_chars_total

    final_facts: List[str] = []
    for fact in pack.facts:
        candidate = fact.strip()
        if not candidate:
            continue
        extra = len(candidate) + 1
        if extra <= remain:
            final_facts.append(candidate)
            remain -= extra
        else:
            if remain > 1:
                final_facts.append(candidate[: remain - 1] + "…")
                remain = 0
            truncated = True
            break

    final_snippets: List[Snippet] = []
    for snippet in line_limited:
        if remain <= 0:
            truncated = True
            break

        extra = len(snippet.content) + 1
        if extra <= remain:
            final_snippets.append(snippet)
            remain -= extra
            continue

        if remain <= 1:
            truncated = True
            break

        cut_content = snippet.content[: remain - 1] + "…"
        cut_lines = cut_content.splitlines() or [""]
        cut_snippet = Snippet(
            path=snippet.path,
            start_line=snippet.start_line,
            end_line=snippet.start_line + len(cut_lines) - 1,
            content=cut_content,
            source=snippet.source,
            priority=snippet.priority,
        )
        final_snippets.append(cut_snippet)
        remain = 0
        truncated = True
        break

    meta = dict(pack.meta)
    meta.update(
        {
            "files": len({snippet.path for snippet in final_snippets}),
            "snippets": len(final_snippets),
            "truncated": truncated,
        }
    )

    return ContextPack(facts=final_facts, snippets=final_snippets, meta=meta)


def build_context_pack(
    question: str,
    *,
    workspace_root: Path,
    budget: Budget,
    explicit_files: Optional[Sequence[str]] = None,
    explicit_snippets: Optional[Sequence[Mapping[str, Any]]] = None,
) -> ContextPack:
    """按“抽取 -> 脱敏 -> 截断”构建上下文包。"""
    extracted = extract_context_pack(
        question,
        workspace_root=workspace_root,
        explicit_files=explicit_files,
        explicit_snippets=explicit_snippets,
    )
    redacted = redact_context_pack(extracted)
    truncated = truncate_context_pack(redacted, budget)

    # 为下游统一补齐元信息键。
    truncated.meta.setdefault("files", len({item.path for item in truncated.snippets}))
    truncated.meta.setdefault("snippets", len(truncated.snippets))
    truncated.meta.setdefault("redaction_count", 0)
    truncated.meta.setdefault("truncated", False)
    return truncated


def _payload_signature(payload: Mapping[str, Any]) -> str:
    """对请求体做稳定签名，用于验证“同包分发一致性”."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_shared_payload(
    question: str,
    *,
    context_bridge: bool,
    context_pack: Optional[ContextPack],
) -> Mapping[str, Any]:
    """阶段 4：构建统一请求体。

    - `context_bridge=true` 且有 context_pack 时：question + context_pack
    - 否则：仅 question（旁路模式）
    """
    if context_bridge and context_pack is not None:
        return {
            "question": question,
            "context_pack": context_pack.to_dict(),
        }

    return {"question": question}


def _normalize_answer(raw_response: Any) -> str:
    """把不同返回格式统一成文本答案。"""
    if isinstance(raw_response, str):
        return raw_response

    if isinstance(raw_response, Mapping):
        for key in ("answer", "content", "text", "output"):
            if key in raw_response and raw_response[key] is not None:
                return str(raw_response[key])
        # 避免丢信息：未知结构回退为紧凑 JSON。
        return json.dumps(raw_response, ensure_ascii=False, separators=(",", ":"))

    return str(raw_response)


def _call_one_candidate(
    *,
    candidate: Candidate,
    payload: Mapping[str, Any],
    timeout_sec: int,
    model_caller: ModelCaller,
    payload_signature: str,
) -> NormalizedResult:
    """调用单个候选并归一化结果。"""
    started = time.monotonic()
    try:
        response = model_caller(candidate, payload, timeout_sec)
        answer = _normalize_answer(response)
        return NormalizedResult(
            candidate_id=candidate.id,
            status="success",
            latency_ms=int((time.monotonic() - started) * 1000),
            answer=answer,
            payload_signature=payload_signature,
        )
    except Exception as exc:  # noqa: BLE001 - 运行时容错需要吞并单模型失败
        return NormalizedResult(
            candidate_id=candidate.id,
            status="error",
            latency_ms=int((time.monotonic() - started) * 1000),
            error=str(exc),
            payload_signature=payload_signature,
        )


def fanout_call(
    *,
    candidates: Sequence[Candidate],
    payload: Mapping[str, Any],
    timeout_sec: int,
    max_parallel: int,
    model_caller: ModelCaller,
) -> List[NormalizedResult]:
    """阶段 5：并发调用候选。

    设计细节：
    - 至少 1 个模型失败不影响其他模型。
    - 到达总超时后，未完成任务标记为 timeout。
    """
    if not candidates:
        return []

    signature = _payload_signature(payload)

    if len(candidates) == 1:
        return [
            _call_one_candidate(
                candidate=candidates[0],
                payload=payload,
                timeout_sec=timeout_sec,
                model_caller=model_caller,
                payload_signature=signature,
            )
        ]

    workers = max(1, min(max_parallel, len(candidates)))
    results_by_id: Dict[str, NormalizedResult] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _call_one_candidate,
                candidate=candidate,
                payload=payload,
                timeout_sec=timeout_sec,
                model_caller=model_caller,
                payload_signature=signature,
            ): candidate
            for candidate in candidates
        }

        try:
            for future in as_completed(future_map, timeout=timeout_sec):
                candidate = future_map[future]
                try:
                    results_by_id[candidate.id] = future.result()
                except Exception as exc:  # noqa: BLE001
                    results_by_id[candidate.id] = NormalizedResult(
                        candidate_id=candidate.id,
                        status="error",
                        latency_ms=timeout_sec * 1000,
                        error=str(exc),
                        payload_signature=signature,
                    )
        except FuturesTimeoutError:
            # 整体超时后，剩余 future 统一补 timeout 状态。
            pass

        for future, candidate in future_map.items():
            if candidate.id in results_by_id:
                continue
            future.cancel()
            results_by_id[candidate.id] = NormalizedResult(
                candidate_id=candidate.id,
                status="timeout",
                latency_ms=timeout_sec * 1000,
                error="request timeout",
                payload_signature=signature,
            )

    # 输出顺序与输入候选顺序一致，方便上层映射 A/B/C。
    return [results_by_id[candidate.id] for candidate in candidates]


def _metadata_from_pack(*, context_bridge: bool, pack: Optional[ContextPack]) -> Dict[str, Any]:
    """统一生成强制元信息字段。"""
    if pack is None:
        return {
            "bridge": "on" if context_bridge else "off",
            "files": 0,
            "snippets": 0,
            "redactions": 0,
            "truncated": False,
        }

    return {
        "bridge": "on" if context_bridge else "off",
        "files": int(pack.meta.get("files", len({snippet.path for snippet in pack.snippets}))),
        "snippets": int(pack.meta.get("snippets", len(pack.snippets))),
        "redactions": int(pack.meta.get("redaction_count", 0)),
        "truncated": bool(pack.meta.get("truncated", False)),
    }


def _pick_single_candidate(candidates: Sequence[Candidate]) -> List[Candidate]:
    """降级时优先保留默认模型，否则取第一个可调用候选。"""
    if not candidates:
        return []
    for candidate in candidates:
        if candidate.is_default:
            return [candidate]
    return [candidates[0]]


def run_model_compare_runtime(
    *,
    question: str,
    multi_model_config: Optional[Mapping[str, Any]],
    model_caller: ModelCaller,
    workspace_root: str | Path = ".",
    default_candidate: Optional[Candidate] = None,
    explicit_files: Optional[Sequence[str]] = None,
    explicit_snippets: Optional[Sequence[Mapping[str, Any]]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> CompareRuntimeOutput:
    """主入口：执行完整 compare 运行时链路。"""

    # ========== Step 0：配置与候选准备 ==========
    config = load_runtime_config(multi_model_config)
    fallback_reasons: List[str] = []

    if not config.enabled:
        fallback_reasons.append(_reason(REASON_FEATURE_DISABLED, "multi_model.enabled=false"))

    candidates, candidate_reasons = build_candidates(
        multi_model_config,
        config=config,
        default_candidate=default_candidate,
        env=env,
    )
    fallback_reasons.extend(candidate_reasons)

    callable_external_exists = any(candidate.is_external for candidate in candidates)

    # ========== Step 1-3：上下文桥接链路（可旁路） ==========
    context_pack: Optional[ContextPack] = None
    empty_pack_fallback = False

    if config.context_bridge and callable_external_exists:
        context_pack = build_context_pack(
            question,
            workspace_root=Path(workspace_root),
            budget=config.budget,
            explicit_files=explicit_files,
            explicit_snippets=explicit_snippets,
        )

        if context_pack.is_empty():
            empty_pack_fallback = True
            fallback_reasons.append(_reason(REASON_CONTEXT_PACK_EMPTY, "facts=0 snippets=0"))
    elif not config.context_bridge and callable_external_exists:
        fallback_reasons.append(_reason(REASON_CONTEXT_BRIDGE_BYPASSED, "context_bridge=false"))

    # ========== Step 4：统一请求体构造 ==========
    shared_payload = build_shared_payload(
        question,
        context_bridge=config.context_bridge,
        context_pack=context_pack,
    )

    # ========== Step 5：决定 fan-out 或降级 ==========
    can_fanout = config.enabled and (len(candidates) >= 2) and (not empty_pack_fallback)

    if not can_fanout:
        if len(candidates) < 2:
            fallback_reasons.append(_reason(REASON_INSUFFICIENT_USABLE_MODELS, f"{len(candidates)}<2"))
        run_candidates = _pick_single_candidate(candidates)
        mode = "single"
    else:
        run_candidates = list(candidates)
        mode = "fanout"

    # 若一个可调用模型都没有，返回空结果但保留元信息与原因。
    if not run_candidates:
        metadata = _metadata_from_pack(context_bridge=config.context_bridge, pack=context_pack)
        return CompareRuntimeOutput(
            mode="single",
            metadata=metadata,
            results=[],
            fallback_reasons=fallback_reasons,
            context_pack=context_pack,
        )

    # ========== Step 6：并发调用 + 结果归一化 ==========
    results = fanout_call(
        candidates=run_candidates,
        payload=shared_payload,
        timeout_sec=config.timeout_sec,
        max_parallel=config.max_parallel,
        model_caller=model_caller,
    )

    metadata = _metadata_from_pack(context_bridge=config.context_bridge, pack=context_pack)

    return CompareRuntimeOutput(
        mode=mode,
        metadata=metadata,
        results=results,
        fallback_reasons=fallback_reasons,
        context_pack=context_pack,
    )


def make_default_candidate(*, candidate_id: str = "session_default", model: str = "session-default") -> Candidate:
    """构造“当前会话默认模型”占位候选。"""
    return Candidate(
        id=candidate_id,
        provider="session_default",
        model=model,
        enabled=True,
        is_default=True,
    )


__all__ = [
    "Budget",
    "Candidate",
    "CompareRuntimeOutput",
    "ContextPack",
    "ModelCaller",
    "NormalizedResult",
    "RuntimeConfig",
    "build_candidates",
    "build_context_pack",
    "build_shared_payload",
    "extract_context_pack",
    "fanout_call",
    "load_runtime_config",
    "make_default_candidate",
    "redact_context_pack",
    "run_model_compare_runtime",
    "truncate_context_pack",
]
