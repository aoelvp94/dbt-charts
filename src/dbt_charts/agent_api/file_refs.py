"""File-ref expansion for dbt charts agent surfaces.

Scans a prompt for @<path> tokens and inlines matching file contents.
Reusable from any surface: CLI, Cloud chat, AI tools, IDE clients.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_AT_REF_RE = re.compile(r"(?<![\w.])@(?P<path>[\w./-]+)")
_MAX_INLINE_BYTES = 200 * 1024
_STUB_LINES = 50
_STUB_HEAD_BYTES = 64 * 1024


class FileRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    token: str  # original @token (e.g. "@charts/foo.yml")
    path: Path  # resolved absolute path


class ExpandedPrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    references: list[FileRef]


def _has_dotdot(path_str: str) -> bool:
    return any(seg == ".." for seg in path_str.split("/"))


def _fenced(text: str) -> str:
    longest = run = 0
    for ch in text:
        if ch == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def _inline(path_str: str, project_dir: Path) -> tuple[str, Path] | None:
    """Return (replacement_text, resolved_path) or None if token is unresolvable."""
    if _has_dotdot(path_str):
        return None

    resolved = (project_dir / path_str).resolve()
    try:
        resolved.relative_to(project_dir.resolve())
    except ValueError:
        return None

    if not resolved.exists() or not resolved.is_file():
        return None

    try:
        size = resolved.stat().st_size
    except OSError:
        return None

    if size > _MAX_INLINE_BYTES:
        try:
            with resolved.open("rb") as f:
                head_bytes = f.read(_STUB_HEAD_BYTES)
        except OSError:
            return None
        try:
            head_text = head_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return None
        head_lines = head_text.splitlines()
        truncated = "\n".join(head_lines[:_STUB_LINES])
        if size <= len(head_bytes):
            line_count = len(head_lines)
        else:
            avg_line_bytes = max(1, len(head_bytes) // max(1, len(head_lines)))
            line_count = size // avg_line_bytes
        header = (
            f"(@{path_str}: {size // 1024} KB, ~{line_count} lines,"
            f" first {_STUB_LINES} lines below)"
        )
        return f"{header}\n{_fenced(truncated)}", resolved

    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    return _fenced(text), resolved


def expand_file_refs(message: str, *, project_dir: Path) -> ExpandedPrompt:
    """Replace @<path> tokens in *message* with file contents.

    Tokens that cannot be resolved (out of project_dir, non-existent, binary,
    dotdot traversal) are left as-is and not recorded in references.
    """
    references: list[FileRef] = []

    def replace(match: re.Match[str]) -> str:
        full_match = match.group(0)
        path_str = match.group("path").rstrip(".")
        if not path_str:
            return full_match
        suffix = full_match[1 + len(path_str) :]
        result = _inline(path_str, project_dir)
        if result is None:
            return full_match
        replacement, resolved_path = result
        references.append(FileRef(token=f"@{path_str}", path=resolved_path))
        return replacement + suffix

    text = _AT_REF_RE.sub(replace, message)
    return ExpandedPrompt(text=text, references=references)
