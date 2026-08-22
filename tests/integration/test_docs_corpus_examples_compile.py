"""Regression: every ```yaml fenced example in DBT_CHARTS_SYNTAX.md must pass dct validate.

If this test fails, either the example is wrong (update the doc) or the
validator changed its contract (update the validator + the doc together).
Docs always follow the validator — never relax the validator to match a bad
example.
"""

from __future__ import annotations

import importlib.resources
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from dbt_charts.cli.filesystem_project import FilesystemProject

# ---------------------------------------------------------------------------
# Source path (mirrors dbt_charts.agent_api.docs._loader)
# ---------------------------------------------------------------------------

_SYNTAX_FILE = importlib.resources.files("dbt_charts") / "DBT_CHARTS_SYNTAX.md"

# ---------------------------------------------------------------------------
# Top-level keys that Board (extra="forbid") accepts.
# Source: dbt_charts.core.compile.types.Board field names.
# ---------------------------------------------------------------------------

_BOARD_KEYS = frozenset(
    {
        "title",
        "description",
        "tags",
        "aliases",
        "text",
        "source",
        "variables",
        "queries",
        "charts",
        "rows",
        "cols",
        "grid",
        "tabs",
        "card_gap",
        "chart_focus",
        "details",
        "expanded_title",
        "expanded",
        "id",
        "style",
        "width",
        "height",
        "theme",
    }
)

# ---------------------------------------------------------------------------
# Fence extraction: only ```yaml fences (not ```yaml-schema, ```bash, etc.)
# ---------------------------------------------------------------------------

# Matches ```yaml (with optional trailing whitespace) on its own line;
# does NOT match ```yaml-schema or ```yaml-anything (the \s*\n ensures the
# language tag ends immediately with optional whitespace then newline).
_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def _extract_fenced_blocks(md_text: str) -> list[tuple[int, str]]:
    """Return (start_line, body) for every ```yaml fence in md_text."""
    results: list[tuple[int, str]] = []
    for m in _FENCE_RE.finditer(md_text):
        start_line = md_text[: m.start()].count("\n") + 1
        results.append((start_line, m.group(1)))
    return results


# ---------------------------------------------------------------------------
# Scaffold: turn a fence fragment into a validatable Board dict
# ---------------------------------------------------------------------------


def _has_placeholder_key(obj: Any, depth: int = 0) -> bool:
    """Return True if obj contains '...' as a dict key (YAML placeholder syntax)."""
    if depth > 10:
        return False
    if isinstance(obj, dict):
        if "..." in obj:
            return True
        return any(_has_placeholder_key(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_placeholder_key(v, depth + 1) for v in obj)
    return False


def _collect_layout_chart_refs(layout_val: Any, depth: int = 0) -> set[str]:
    """Collect string chart IDs referenced inside a layout structure."""
    if depth > 15:
        return set()
    refs: set[str] = set()
    if isinstance(layout_val, str):
        refs.add(layout_val)
    elif isinstance(layout_val, list):
        for item in layout_val:
            refs |= _collect_layout_chart_refs(item, depth + 1)
    elif isinstance(layout_val, dict):
        # grid item: {item: chart_id, width: N}
        item_ref = layout_val.get("item")
        if isinstance(item_ref, str):
            refs.add(item_ref)
        # TabLayout wrapper: {items: [...]}
        items = layout_val.get("items")
        if items is not None:
            refs |= _collect_layout_chart_refs(items, depth + 1)
        # Nested layout keys
        for key in ("rows", "cols", "grid", "tabs"):
            if key in layout_val:
                refs |= _collect_layout_chart_refs(layout_val[key], depth + 1)
    return refs


def _scaffold_to_board(fence_body: str) -> dict[str, Any] | None:
    """Parse fence_body and return a validatable Board dict, or None to skip.

    Skips blocks that:
    - are not valid YAML
    - are not a top-level mapping (e.g. a bare scalar or list)
    - contain '...' placeholder keys (illustrative notation like {type: bar, ...})

    For blocks that look like inline chart snippets (top-level keys not in
    _BOARD_KEYS), wraps them under a synthetic charts block.

    For Board-compatible fragments, merges into a minimal scaffold and injects
    synthetic queries for any chart that references a query not in the block.
    Injects synthetic charts for any chart ID referenced in the layout structure.
    """
    try:
        data = yaml.safe_load(fence_body)
    except yaml.YAMLError:
        return None  # not valid YAML; skip

    if not isinstance(data, dict):
        return None  # bare scalar or list; skip

    if _has_placeholder_key(data):
        return None  # illustrative placeholder syntax; skip

    _LAYOUT_KEYS = frozenset({"rows", "cols", "grid", "tabs"})

    board: dict[str, Any]
    unknown_keys = set(data) - _BOARD_KEYS
    if unknown_keys:
        # Inline chart snippet, e.g. {type: area, x: date, y: value}
        board = {
            "title": "_test",
            "source": "_test",
            "queries": {"_q": {"sql": "SELECT 1"}},
            "charts": {"_example": {"query": "_q", **data}},
            "rows": [],
        }
    else:
        # source: "_test" sets default for injected synthetic queries;
        # fences that have their own source: block override it via update() below.
        board = {"title": "_test", "source": "_test"}
        board.update(data)
        # Inject synthetic queries for any chart referencing an unknown query name.
        charts = board.get("charts")
        if isinstance(charts, dict):
            existing = set((board.get("queries") or {}).keys())
            missing: set[str] = set()
            for chart_def in charts.values():
                if isinstance(chart_def, dict):
                    q_ref = chart_def.get("query")
                    if isinstance(q_ref, str) and q_ref not in existing:
                        missing.add(q_ref)
            if missing:
                board.setdefault("queries", {})
                for q_name in missing:
                    board["queries"][q_name] = {"sql": "SELECT 1"}

        # Inject synthetic charts + queries for any chart ID referenced in the
        # layout that has no entry in board["charts"].  Layout-only examples in
        # docs/layout.md name chart IDs like "rev_chart" without defining them.
        existing_charts = set((board.get("charts") or {}).keys())
        layout_refs: set[str] = set()
        for lk in _LAYOUT_KEYS:
            if lk in board:
                layout_refs |= _collect_layout_chart_refs(board[lk])
        missing_charts = layout_refs - existing_charts
        if missing_charts:
            board.setdefault("charts", {})
            board.setdefault("queries", {})
            for chart_name in missing_charts:
                q_name = f"_q_{chart_name}"
                board["queries"][q_name] = {"sql": "SELECT 1"}
                board["charts"][chart_name] = {
                    "query": q_name,
                    "type": "bar",
                    "x": "_x",
                    "y": "_y",
                }

    # Board requires at least one layout key or a non-empty text field.
    if not board.get("text") and not (_LAYOUT_KEYS & set(board)):
        board["rows"] = []

    return board


# ---------------------------------------------------------------------------
# Parametrize: walk every .md file in the corpus at collection time
# ---------------------------------------------------------------------------


def _collect_corpus_blocks() -> list[tuple[str, int, str]]:
    """Return (filename, start_line, fence_body) for every ```yaml block."""
    results: list[tuple[str, int, str]] = []
    text = _SYNTAX_FILE.read_text(encoding="utf-8")
    name = _SYNTAX_FILE.name
    for start_line, body in _extract_fenced_blocks(text):
        results.append((name, start_line, body))
    return results


_CORPUS_BLOCKS = _collect_corpus_blocks()


def test_docs_corpus_uses_runtime_jinja_variable_scope() -> None:
    """Docs should teach the same bare variable scope the SQL renderer provides."""
    offenders = []
    text = _SYNTAX_FILE.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if "{{ variables." in line:
            offenders.append(f"{_SYNTAX_FILE.name}:{line_no}: {line.strip()}")

    assert offenders == []


# ---------------------------------------------------------------------------
# Parametrized regression test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "start_line", "fence_body"),
    _CORPUS_BLOCKS,
    ids=[f"{fn}:{ln}" for fn, ln, _ in _CORPUS_BLOCKS],
)
def test_corpus_block_compiles(
    filename: str,
    start_line: int,
    fence_body: str,
    tmp_path: Path,
    local_project: Callable[..., FilesystemProject],
) -> None:
    """Every ```yaml block in the dct docs corpus must pass dct validate."""
    from dbt_charts.agent_api.validate import validate

    board_dict = _scaffold_to_board(fence_body)
    if board_dict is None:
        pytest.skip(
            f"{filename}:{start_line} — not a concrete example (placeholder/non-dict YAML)"
        )

    board_yaml = yaml.dump(board_dict, allow_unicode=True)
    board_file = tmp_path / "board.yml"
    board_file.write_text(board_yaml)

    result = validate(board_file, project=local_project(tmp_path))
    errors = "\n".join(f"  [{e.path or '?'}] {e.message}" for e in result.errors)
    assert result.success, (
        f"\n\n{filename}:{start_line} — dct validate failed with {len(result.errors)} error(s):\n"
        f"{errors}\n\n"
        f"Scaffolded board:\n{textwrap.indent(board_yaml, '  ')}"
    )


# ---------------------------------------------------------------------------
# Self-test: confirm the plumbing rejects a deliberately-broken fence
# ---------------------------------------------------------------------------


def test_self_test_detects_drift(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """Regression guard: validate() must reject the known-bad KPI title drift.

    If this test fails (validate() returned success on a broken board), the test
    plumbing is broken — _scaffold_to_board or validate() is no longer exercising
    the validator that dct validate runs.
    """
    from dbt_charts.agent_api.validate import validate

    broken_board = yaml.dump(
        {
            "title": "_test",
            "queries": {"_q": {"sql": "SELECT 1"}},
            "charts": {
                "_c": {
                    "query": "_q",
                    "type": "kpi",
                    "title": "Broken",  # known drift: kpi rejects title:, requires label:
                }
            },
        }
    )
    board_file = tmp_path / "board.yml"
    board_file.write_text(broken_board)

    result = validate(board_file, project=local_project(tmp_path))
    assert not result.success, (
        "Self-test FAILED: validate() accepted a KPI board with title: instead of label:. "
        "Either the validator no longer rejects this (update the test and the docs), "
        "or the test scaffolding is broken."
    )
