#!/usr/bin/env python3
"""Validate public-document links, structure, and README line-budget rules."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_FILES = (ROOT / "README.md", ROOT / "README_EN.md")
WORKFLOW_DOC_FILES = (
    ROOT / "docs/how-sopify-works.md",
    ROOT / "docs/how-sopify-works.en.md",
)
CONTRIBUTING_FILES = (ROOT / "CONTRIBUTING_CN.md", ROOT / "CONTRIBUTING.md")
MARKDOWN_LINK_CHECK_FILES = README_FILES + WORKFLOW_DOC_FILES + CONTRIBUTING_FILES
VERSION_HEADERS = (
    ROOT / "Codex/Skills/CN/AGENTS.md",
    ROOT / "Codex/Skills/EN/AGENTS.md",
    ROOT / "Claude/Skills/CN/CLAUDE.md",
    ROOT / "Claude/Skills/EN/CLAUDE.md",
)
LINK_PATTERN = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
VERSION_PATTERN = re.compile(r"badge/version-([^-][^)]*)-orange\.svg")
HEADER_PATTERN = re.compile(r"^<!-- SOPIFY_VERSION: (.+) -->$", re.MULTILINE)
MAX_README_BODY_LINES = 250
MARKDOWN_SUFFIXES = {".md", ".markdown"}

# Lock public-doc structure so CN/EN drift is caught by CI instead of by readers.
EXPECTED_LEVEL2_SECTIONS = {
    README_FILES[0]: (
        "为什么选择 Sopify (Sop AI) Skills？",
        "快速开始",
        "配置说明",
        "命令参考",
        "多模型对比",
        "子 Skills",
        "目录结构",
        "常见问题",
        "版本历史",
        "许可证",
        "贡献",
    ),
    README_FILES[1]: (
        "Why Sopify (Sop AI) Skills?",
        "Quick Start",
        "Configuration",
        "Command Reference",
        "Multi-Model Compare",
        "Sub-skills",
        "Directory Structure",
        "FAQ",
        "Version History",
        "License",
        "Contributing",
    ),
    WORKFLOW_DOC_FILES[0]: (
        "设计来源：Harness Engineering",
        "主工作流",
        "Checkpoint 暂停与恢复",
        "目录结构与层级",
        "附录：Plan 生命周期",
    ),
    WORKFLOW_DOC_FILES[1]: (
        "Design Rationale: Harness Engineering",
        "Main Workflow",
        "Checkpoint Pause and Resume",
        "Directory Structure and Layers",
        "Appendix: Plan Lifecycle",
    ),
    CONTRIBUTING_FILES[0]: (
        "如何贡献",
        "Prompt 层与 Skill Authoring",
        "Runtime Bundle 与宿主接入",
        "校验命令",
        "Release Hook 与 CHANGELOG",
        "许可说明",
    ),
    CONTRIBUTING_FILES[1]: (
        "How to contribute",
        "Prompt-layer and Skill Authoring",
        "Runtime Bundle and Host Integration",
        "Validation Commands",
        "Release Hook and CHANGELOG",
        "License Note",
    ),
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_sopify_version() -> tuple[str | None, list[str]]:
    versions: list[str] = []
    for path in VERSION_HEADERS:
        match = HEADER_PATTERN.search(read_text(path))
        if not match:
            return None, [f"{path.relative_to(ROOT)}: missing SOPIFY_VERSION header"]
        versions.append(match.group(1).strip())
    if len(set(versions)) != 1:
        return None, [f"SOPIFY_VERSION headers mismatch: {' / '.join(versions)}"]
    return versions[0], []


def extract_badge_version(path: Path) -> str | None:
    match = VERSION_PATTERN.search(read_text(path))
    if not match:
        return None
    # shields.io doubles hyphens to encode literal '-'
    return match.group(1).replace("--", "-")


def strip_heading_markup(text: str) -> str:
    cleaned = re.sub(r"`([^`]*)`", r"\1", text)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_~]", "", cleaned)
    return cleaned.strip()


def slugify_heading(text: str) -> str:
    # This mirrors GitHub anchor generation closely enough for the repo's headings.
    cleaned = strip_heading_markup(text).lower()
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-\s]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned


def extract_headings(path: Path, *, level: int | None = None) -> list[str]:
    headings: list[str] = []
    in_fence = False
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_PATTERN.match(stripped)
        if not match:
            continue
        current_level = len(match.group(1))
        if level is None or current_level == level:
            headings.append(match.group(2).strip())
    return headings


def extract_anchor_set(path: Path) -> set[str]:
    return {slugify_heading(heading) for heading in extract_headings(path)}


def iter_links(path: Path) -> list[str]:
    return LINK_PATTERN.findall(read_text(path))


def check_badge_versions(expected_version: str) -> list[str]:
    errors: list[str] = []
    for path in README_FILES:
        version = extract_badge_version(path)
        if version is None:
            errors.append(f"{path.relative_to(ROOT)}: failed to parse version badge")
        elif version != expected_version:
            errors.append(
                f"{path.relative_to(ROOT)}: version badge {version} != SOPIFY_VERSION {expected_version}"
            )
    return errors


def check_internal_anchor_links(path: Path) -> list[str]:
    anchors = extract_anchor_set(path)
    errors: list[str] = []
    for target in iter_links(path):
        if not target.startswith("#"):
            continue
        anchor = target[1:]
        if anchor not in anchors:
            errors.append(f"{path.relative_to(ROOT)}: missing heading anchor #{anchor}")
    return errors


def check_language_switch_links() -> list[str]:
    errors: list[str] = []
    cn_links = iter_links(README_FILES[0])
    en_links = iter_links(README_FILES[1])
    if "./README_EN.md" not in cn_links:
        errors.append("README.md: missing language switch link to ./README_EN.md")
    if "./README.md" not in en_links:
        errors.append("README_EN.md: missing language switch link to ./README.md")
    return errors


def check_expected_level2_sections() -> list[str]:
    errors: list[str] = []
    for path, expected_sections in EXPECTED_LEVEL2_SECTIONS.items():
        actual_sections = extract_headings(path, level=2)
        if len(actual_sections) != len(expected_sections):
            errors.append(
                f"{path.relative_to(ROOT)}: level-2 section count {len(actual_sections)} "
                f"!= expected {len(expected_sections)}"
            )
            continue
        for index, (actual, expected) in enumerate(zip(actual_sections, expected_sections), start=1):
            if actual != expected:
                errors.append(
                    f"{path.relative_to(ROOT)}: level-2 section {index} is {actual!r}, "
                    f"expected {expected!r}"
                )
                break
    return errors


def split_link_target(target: str) -> tuple[str, str | None]:
    if "#" not in target:
        return target, None
    path_part, anchor = target.split("#", 1)
    return path_part, anchor or None


def check_relative_file_links(path: Path) -> list[str]:
    errors: list[str] = []
    for target in iter_links(path):
        normalized, anchor = split_link_target(target)
        if not normalized.startswith(("./", "../")):
            continue
        if not normalized:
            continue
        resolved = (path.parent / normalized).resolve()
        if not resolved.exists():
            errors.append(
                f"{path.relative_to(ROOT)}: relative link target not found -> {target}"
            )
            continue
        if anchor and resolved.is_file() and resolved.suffix.lower() in MARKDOWN_SUFFIXES:
            target_anchors = extract_anchor_set(resolved)
            if anchor not in target_anchors:
                errors.append(
                    f"{path.relative_to(ROOT)}: missing anchor #{anchor} in "
                    f"{resolved.relative_to(ROOT)}"
                )
    return errors


def count_readme_body_lines(path: Path) -> int:
    lines = read_text(path).splitlines()
    in_fence = False
    after_header = False
    count = 0
    for raw in lines:
        stripped = raw.strip()
        if not after_header:
            if stripped == "---":
                after_header = True
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # The body budget ignores the badge header and fenced snippets only.
        count += 1
    return count


def check_readme_body_budget() -> list[str]:
    errors: list[str] = []
    for path in README_FILES:
        body_lines = count_readme_body_lines(path)
        if body_lines > MAX_README_BODY_LINES:
            errors.append(
                f"{path.relative_to(ROOT)}: body line count {body_lines} exceeds {MAX_README_BODY_LINES}"
            )
    return errors


def main() -> int:
    errors: list[str] = []
    expected_version, version_errors = extract_sopify_version()
    errors.extend(version_errors)

    if expected_version is not None:
        errors.extend(check_badge_versions(expected_version))

    for path in MARKDOWN_LINK_CHECK_FILES:
        errors.extend(check_internal_anchor_links(path))
        errors.extend(check_relative_file_links(path))

    errors.extend(check_language_switch_links())
    errors.extend(check_expected_level2_sections())
    errors.extend(check_readme_body_budget())

    if errors:
        print("README validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("README validation passed:")
    print(f"  - SOPIFY_VERSION: {expected_version}")
    for path in README_FILES:
        print(f"  - {path.relative_to(ROOT)} body lines: {count_readme_body_lines(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
