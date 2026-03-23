from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-readme-links.py"
VERSION = "2026-03-23.163812"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_readme_links_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _doc_with_sections(title: str, sections: tuple[str, ...], *, intro: str, links: tuple[str, ...] = ()) -> str:
    body = [f"# {title}", "", intro, ""]
    for link in links:
        body.append(link)
    if links:
        body.append("")
    for section in sections:
        body.extend((f"## {section}", "", f"Text for {section}.", ""))
    return "\n".join(body).rstrip() + "\n"


def _readme_with_sections(title: str, sections: tuple[str, ...], *, anchor: str, switch_target: str, extra_links: tuple[str, ...]) -> str:
    lines = [
        f"# {title}",
        "",
        f"[![Version](https://img.shields.io/badge/version-{VERSION.replace('-', '--')}-orange.svg)]({anchor})",
        f"[Language Switch]({switch_target})",
        "",
        "---",
        "",
    ]
    lines.extend(extra_links)
    lines.append("")
    for section in sections:
        lines.extend((f"## {section}", "", f"Text for {section}.", ""))
    return "\n".join(lines).rstrip() + "\n"


def _minimal_agents(version: str, *, claude: bool, english: bool) -> str:
    header = "CLAUDE" if claude else "AGENTS"
    body = "Note: ~/.claude/sopify/" if claude else "说明：~/.codex/sopify/"
    if english:
        body = "Note: ~/.claude/sopify/" if claude else "Note: ~/.codex/sopify/"
    return textwrap.dedent(
        f"""\
        <!-- SOPIFY_VERSION: {version} -->
        # {header}

        {body}
        """
    )


def _configure_module(module, root: Path) -> None:
    readme_sections_cn = module.EXPECTED_LEVEL2_SECTIONS[module.README_FILES[0]]
    readme_sections_en = module.EXPECTED_LEVEL2_SECTIONS[module.README_FILES[1]]
    workflow_sections_cn = module.EXPECTED_LEVEL2_SECTIONS[module.WORKFLOW_DOC_FILES[0]]
    workflow_sections_en = module.EXPECTED_LEVEL2_SECTIONS[module.WORKFLOW_DOC_FILES[1]]
    contributing_sections_cn = module.EXPECTED_LEVEL2_SECTIONS[module.CONTRIBUTING_FILES[0]]
    contributing_sections_en = module.EXPECTED_LEVEL2_SECTIONS[module.CONTRIBUTING_FILES[1]]

    module.ROOT = root
    module.README_FILES = (root / "README.md", root / "README_EN.md")
    module.WORKFLOW_DOC_FILES = (
        root / "docs/how-sopify-works.md",
        root / "docs/how-sopify-works.en.md",
    )
    module.CONTRIBUTING_FILES = (root / "CONTRIBUTING_CN.md", root / "CONTRIBUTING.md")
    module.MARKDOWN_LINK_CHECK_FILES = (
        module.README_FILES + module.WORKFLOW_DOC_FILES + module.CONTRIBUTING_FILES
    )
    module.VERSION_HEADERS = (
        root / "Codex/Skills/CN/AGENTS.md",
        root / "Codex/Skills/EN/AGENTS.md",
        root / "Claude/Skills/CN/CLAUDE.md",
        root / "Claude/Skills/EN/CLAUDE.md",
    )
    module.EXPECTED_LEVEL2_SECTIONS = {
        module.README_FILES[0]: readme_sections_cn,
        module.README_FILES[1]: readme_sections_en,
        module.WORKFLOW_DOC_FILES[0]: workflow_sections_cn,
        module.WORKFLOW_DOC_FILES[1]: workflow_sections_en,
        module.CONTRIBUTING_FILES[0]: contributing_sections_cn,
        module.CONTRIBUTING_FILES[1]: contributing_sections_en,
    }


def _init_fixture(root: Path, module, *, broken_workflow_link: bool = False, reorder_readme_en: bool = False) -> None:
    _configure_module(module, root)

    readme_cn_sections = module.EXPECTED_LEVEL2_SECTIONS[module.README_FILES[0]]
    readme_en_sections = list(module.EXPECTED_LEVEL2_SECTIONS[module.README_FILES[1]])
    workflow_cn_sections = module.EXPECTED_LEVEL2_SECTIONS[module.WORKFLOW_DOC_FILES[0]]
    workflow_en_sections = module.EXPECTED_LEVEL2_SECTIONS[module.WORKFLOW_DOC_FILES[1]]
    contributing_cn_sections = module.EXPECTED_LEVEL2_SECTIONS[module.CONTRIBUTING_FILES[0]]
    contributing_en_sections = module.EXPECTED_LEVEL2_SECTIONS[module.CONTRIBUTING_FILES[1]]

    if reorder_readme_en:
        readme_en_sections[1], readme_en_sections[2] = readme_en_sections[2], readme_en_sections[1]

    for relative in (
        "LICENSE",
        "LICENSE-docs",
        "CHANGELOG.md",
        "Codex/Skills/CN/skills/sopify/.gitkeep",
        "Codex/Skills/EN/skills/sopify/.gitkeep",
    ):
        _write(root / relative, "placeholder\n")

    _write(root / "Codex/Skills/CN/AGENTS.md", _minimal_agents(VERSION, claude=False, english=False))
    _write(root / "Codex/Skills/EN/AGENTS.md", _minimal_agents(VERSION, claude=False, english=True))
    _write(root / "Claude/Skills/CN/CLAUDE.md", _minimal_agents(VERSION, claude=True, english=False))
    _write(root / "Claude/Skills/EN/CLAUDE.md", _minimal_agents(VERSION, claude=True, english=True))

    _write(
        root / "README.md",
        _readme_with_sections(
            "Sopify 技能",
            readme_cn_sections,
            anchor="#版本历史",
            switch_target="./README_EN.md",
            extra_links=(
                "[贡献](./CONTRIBUTING_CN.md)",
                "[工作流说明](./docs/how-sopify-works.md)",
                "[许可证](./LICENSE)",
            ),
        ),
    )
    _write(
        root / "README_EN.md",
        _readme_with_sections(
            "Sopify Skills",
            tuple(readme_en_sections),
            anchor="#version-history",
            switch_target="./README.md",
            extra_links=(
                "[Contributing](./CONTRIBUTING.md)",
                "[How Sopify Works](./docs/how-sopify-works.en.md)",
                "[License](./LICENSE)",
            ),
        ),
    )

    cn_workflow_links = ("[返回 README](../README.md#版本历史)",)
    en_workflow_links = ("[Back to README](../README_EN.md#version-history)",)
    if broken_workflow_link:
        en_workflow_links = en_workflow_links + ("[Broken](../docs/missing.md)",)

    _write(
        root / "docs/how-sopify-works.md",
        _doc_with_sections(
            "Sopify 如何工作",
            workflow_cn_sections,
            intro="中文工作流说明。",
            links=cn_workflow_links,
        ),
    )
    _write(
        root / "docs/how-sopify-works.en.md",
        _doc_with_sections(
            "How Sopify Works",
            workflow_en_sections,
            intro="English workflow guide.",
            links=en_workflow_links,
        ),
    )

    _write(
        root / "CONTRIBUTING_CN.md",
        _doc_with_sections(
            "贡献指南",
            contributing_cn_sections,
            intro="中文维护者入口。",
            links=("[Codex CN](./Codex/Skills/CN/skills/sopify/)",),
        ),
    )
    _write(
        root / "CONTRIBUTING.md",
        _doc_with_sections(
            "Contributing",
            contributing_en_sections,
            intro="English maintainer entry.",
            links=("[Codex EN](./Codex/Skills/EN/skills/sopify/)",),
        ),
    )


class CheckReadmeLinksTests(unittest.TestCase):
    def test_main_passes_when_public_docs_are_aligned(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_fixture(root, module)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = module.main()

            self.assertEqual(exit_code, 0, msg=stdout.getvalue())
            self.assertIn("README validation passed:", stdout.getvalue())

    def test_main_fails_when_readme_heading_order_drifts(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_fixture(root, module, reorder_readme_en=True)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = module.main()

            self.assertEqual(exit_code, 1)
            self.assertIn("README_EN.md: level-2 section 2", stdout.getvalue())

    def test_main_checks_workflow_doc_relative_links(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_fixture(root, module, broken_workflow_link=True)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = module.main()

            self.assertEqual(exit_code, 1)
            self.assertIn(
                "docs/how-sopify-works.en.md: relative link target not found -> ../docs/missing.md",
                stdout.getvalue(),
            )


if __name__ == "__main__":
    unittest.main()
