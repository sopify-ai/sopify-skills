"""Minimal YAML loader for Sopify runtime.

This fallback parser intentionally supports only the subset used by
`sopify.config.yaml` and simple skill front matter: nested mappings,
lists, booleans, integers, strings, and comments.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, List, Sequence, Tuple


class YamlParseError(ValueError):
    """Raised when a YAML document uses unsupported syntax."""


@dataclass(frozen=True)
class _Line:
    indent: int
    content: str
    line_number: int


_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")


def load_yaml(text: str) -> Any:
    """Parse a small YAML subset into Python values.

    Args:
        text: UTF-8 text content.

    Returns:
        The parsed Python object.
    """
    lines = _prepare_lines(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0].indent)
    if index != len(lines):
        line = lines[index]
        raise YamlParseError(f"Unexpected content at line {line.line_number}: {line.content}")
    return value


def _prepare_lines(text: str) -> List[_Line]:
    prepared: List[_Line] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if "\t" in raw_line:
            raise YamlParseError(f"Tabs are not supported (line {line_number})")
        stripped = _strip_comment(raw_line).rstrip()
        if not stripped:
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        prepared.append(_Line(indent=indent, content=stripped.lstrip(" "), line_number=line_number))
    return prepared


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or line[index - 1].isspace():
                return line[:index]
    return line


def _parse_block(lines: Sequence[_Line], index: int, indent: int) -> Tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    line = lines[index]
    if line.indent != indent:
        raise YamlParseError(
            f"Expected indent {indent}, found {line.indent} at line {line.line_number}"
        )
    if line.content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(lines: Sequence[_Line], index: int, indent: int) -> Tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlParseError(f"Unexpected indentation at line {line.line_number}")
        if line.content.startswith("- "):
            break
        key, remainder = _split_key_value(line)
        if remainder == "":
            index += 1
            if index < len(lines) and lines[index].indent > indent:
                value, index = _parse_block(lines, index, lines[index].indent)
            else:
                value = {}
        else:
            value = _parse_scalar(remainder)
            index += 1
        mapping[key] = value
    return mapping, index


def _parse_list(lines: Sequence[_Line], index: int, indent: int) -> Tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlParseError(f"Unexpected indentation at line {line.line_number}")
        if not line.content.startswith("- "):
            break

        item_text = line.content[2:].strip()
        index += 1
        has_child = index < len(lines) and lines[index].indent > indent

        if item_text == "":
            if not has_child:
                items.append(None)
                continue
            value, index = _parse_block(lines, index, lines[index].indent)
            items.append(value)
            continue

        if _looks_like_mapping_entry(item_text):
            key, remainder = _split_key_value(_Line(indent=indent + 2, content=item_text, line_number=line.line_number))
            item: dict[str, Any] = {}
            if remainder == "":
                if has_child:
                    value, index = _parse_block(lines, index, lines[index].indent)
                else:
                    value = {}
                item[key] = value
            else:
                item[key] = _parse_scalar(remainder)
            if has_child:
                extra, index = _parse_mapping(lines, index, lines[index].indent)
                item.update(extra)
            items.append(item)
            continue

        items.append(_parse_scalar(item_text))
        if has_child:
            raise YamlParseError(
                f"Scalar list item cannot have nested children (line {line.line_number})"
            )
    return items, index


def _looks_like_mapping_entry(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) >= 2 and (
        (stripped.startswith('"') and stripped.endswith('"'))
        or (stripped.startswith("'") and stripped.endswith("'"))
    ):
        return False
    if ":" not in text:
        return False
    key, _ = text.split(":", 1)
    return bool(key.strip())


def _split_key_value(line: _Line) -> Tuple[str, str]:
    if ":" not in line.content:
        raise YamlParseError(f"Expected key/value pair at line {line.line_number}")
    key, remainder = line.content.split(":", 1)
    key = key.strip()
    if not key:
        raise YamlParseError(f"Missing key at line {line.line_number}")
    return key, remainder.strip()


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if _INT_RE.match(value):
        return int(value)
    if _FLOAT_RE.match(value):
        return float(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        inner = value[1:-1]
        return inner.replace(r"\'", "'").replace(r'\"', '"')
    return value
