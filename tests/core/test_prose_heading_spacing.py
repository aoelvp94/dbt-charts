"""Characterisation tests for prose-heading leading space, pre-fix.

These pin *today's* rendered behaviour so a future fix has a documented
baseline to diff against -- they are not expected to fail, and they do not
assert what the behaviour *should* be. There is an open design question
(should a heading opening a text column sit flush with the row top, matching
a sibling chart's title, or keep its margin) that blocks turning this into a
fix and is not this module's concern.

Mechanism, traced through ``mdsvg.renderer.SVGRenderer`` and
``dbt_charts.core.render.prose``:

- ``_inter_block_gap`` returns 0 whenever either side of a block transition
  is a ``Heading`` -- a heading never gets ``paragraph_spacing`` stacked on
  top of its own margin.
- The renderer picks a column count for *every* prose blob, authored
  ``columns:`` or not (see ``test_prose_columns.py``). When its initial pick
  is <=1 column (a narrow slot, e.g. prose sharing a row with a chart),
  rendering goes through ``render_content``, which applies a heading's own
  ``margin_top`` in full with no suppression -- regardless of whether the
  heading is the blob's first block or appears after a paragraph.
- When the initial pick is >1 columns (a wide slot with room to spare, even
  if the actual text is short enough that only one column ends up used),
  rendering goes through the packed multi-column path. There, a block that
  opens a column (``position == 0`` in ``windows[ci]``) has its own
  ``leading_margin`` subtracted before placement -- rendering it flush
  against the column top, "exactly as they do at the top of the board" (the
  comment in ``prose.py``).

So a heading's leading space is placement-*independent* within each of those
two paths (no double counting on either), but the two paths disagree with
each other: the same heading, in the same document, gets the full margin in
a narrow column and (near) none in a wide one.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.compiler import compile as compile_board
from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.style.theme import TextColumnStyle
from dbt_charts.core.compile.resolve.style.board import resolve_style
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.render.board_resolve import build_resolved_board
from dbt_charts.core.render.boards import render_board_svg
from dbt_charts.core.render.prose import render_prose_svg
from dbt_charts.core.render.sizing import get_compact_style

# A heading's rendered baseline sits ``font_size`` px below its own line-box
# top in mdsvg's layout (confirmed empirically below by pinning that this
# holds identically for two different heading levels) -- so
# ``baseline - font_size`` recovers "space above the heading" without
# depending on true glyph-ascent metrics.
_HEADING_RE = re.compile(
    r'(?:<g transform="translate\(0, ([\-\d.]+)\)">)?\s*'
    r'<text[^>]*y="([\-\d.]+)"[^>]*font-size="(\d+)"[^>]*class="md-heading"'
)


def _heading_top(svg: str) -> float:
    """Distance from the block's own top to the top of the heading's glyphs."""
    m = _HEADING_RE.search(svg)
    assert m, svg
    wrap = float(m.group(1)) if m.group(1) is not None else 0.0
    baseline, font_size = float(m.group(2)), float(m.group(3))
    return wrap + baseline - font_size


def _prose_column_svg(svg: str) -> str:
    """Slice a full board render down to just its prose column's own content.

    A board's own ``title:`` is *also* an ``md-heading`` and renders before any
    row content, so searching the whole board SVG for ``class="md-heading"``
    finds the board title, not the prose column's heading. Bound the search to
    between the prose block's own marker and the next chart's.
    """
    start = svg.index('data-authored-kind="text"')
    end = svg.index('data-authored-kind="chart"', start)
    return svg[start:end]


def _render(markdown: str, width: float, n_cols: int | None) -> str:
    resolved = resolve_style(get_theme_style("editorial"))
    col = (
        TextColumnStyle(max_number=n_cols) if n_cols is not None else TextColumnStyle()
    )
    text_style = resolved.text.model_copy(update={"column": col})
    svg, _ = render_prose_svg(markdown, width, text_style, resolved)
    return svg


ISOLATED = "## Heading text\n\nBody paragraph text that follows the heading."
ONE_PARAGRAPH = "First paragraph of body text that runs on for a bit."
MID_BLOB = f"{ONE_PARAGRAPH}\n\n## Heading text\n\nSecond paragraph after the heading."


def test_mid_blob_heading_adds_no_gap_beyond_the_paragraphs_own_height() -> None:
    """No double counting: mid-blob leading space == the heading's own margin.

    ``paragraph_height`` is the paragraph's full rendered footprint (it has no
    margin of its own). If the heading's leading space in the mid-blob case
    were anything other than exactly its own margin_top, this delta would be
    nonzero.
    """
    resolved = resolve_style(get_theme_style("editorial"))
    text_style = resolved.text.model_copy(
        update={"column": TextColumnStyle(max_number=1)}
    )
    _, paragraph_height = render_prose_svg(ONE_PARAGRAPH, 1128.0, text_style, resolved)

    isolated_top = _heading_top(_render(ISOLATED, 1128.0, n_cols=1))
    mid_blob_top = _heading_top(_render(MID_BLOB, 1128.0, n_cols=1))

    assert mid_blob_top == isolated_top + paragraph_height


def test_narrow_column_heading_keeps_its_full_margin_not_flush() -> None:
    """A heading sharing a row with a chart (narrow slot) gets the full margin.

    A ~550px slot -- what a prose column gets next to a chart in a two-up row
    on a 1128-unit board -- is narrow enough that mdsvg's column planner picks
    a single column outright, taking the ``render_content`` path. That path
    never suppresses a heading's own margin_top, first block or not.
    """
    resolved = resolve_style(get_theme_style("editorial"))
    style = get_compact_style(resolved)

    narrow_top = _heading_top(_render(ISOLATED, 550.0, n_cols=None))

    assert narrow_top == pytest.approx(style.heading_margin_top_px)


def test_wide_row_heading_opener_sits_much_closer_to_flush() -> None:
    """The exact same markdown, given a whole wide row, is far less indented.

    At 1128px the column planner's initial pick is already more than one
    column -- even for this short passage -- so rendering goes through the
    packed path, which subtracts a column-opening block's own leading margin
    before placing it -- flush, or nearly so, against the column top. This is
    the placement-dependence the task is about: identical markdown, and
    whether it gets a narrow or a wide slot changes its leading space from
    the full margin (``test_narrow_column_heading_keeps_its_full_margin_not_flush``,
    same ``ISOLATED`` markdown) to (near) none.
    """
    resolved = resolve_style(get_theme_style("editorial"))
    style = get_compact_style(resolved)

    wide_top = _heading_top(_render(ISOLATED, 1128.0, n_cols=None))

    assert wide_top < style.heading_margin_top_px * 0.5


def test_heading_margin_top_is_identical_across_heading_levels() -> None:
    """h1 and h3 get the same leading space -- margins don't scale with level.

    ``compact_style_kwargs`` derives ``heading_margin_top_px`` from the body
    font's line box, not from ``get_heading_size(level)``, and mdsvg's
    px-override path always prefers it over the level-scaled em fallback. A
    24px h1 and a 14px h3 (the same size as body text) should visually earn
    different leading space; today they don't.
    """
    h1_top = _heading_top(_render("# H1 heading", 1128.0, n_cols=1))
    h3_top = _heading_top(_render("### H3 heading", 1128.0, n_cols=1))

    assert h1_top == h3_top


def _render_board(yaml_text: str) -> tuple[str, float]:
    """Returns (svg, card_padding) -- the padding a chart's title band sits inside."""
    with tempfile.TemporaryDirectory() as tmp:
        result = compile_board(yaml_text)
        assert result.success, result.errors
        assert result.board is not None
        executor = Executor(
            result.board,
            build_adapter_registry(FilesystemProject(Path(tmp))),
            query_registry=result.query_registry,
        )
        variables: dict[str, object] = {}
        resolved, render_cache = build_resolved_board(result.board, executor, variables)
        background = resolved.style.background
        svg = render_board_svg(
            resolved,
            executor,
            variables,
            background=None if background == "transparent" else background,
            render_cache=render_cache,
        )
        assert resolved.card_padding is not None
        return svg, resolved.card_padding


_CHART_TITLE_RE = re.compile(
    r'class="mark-text role-title-text"[^>]*>'
    r'<text[^>]*transform="translate\(([\d.]+),([\d.]+)\)"[^>]*font-size="(\d+)px"'
)

_BOARD_YAML = """
title: Chart title alignment probe
queries:
  q:
    columns: [month, revenue]
    values:
      - ["2026-01-01", 100]
      - ["2026-02-01", 150]
      - ["2026-03-01", 120]
charts:
  bar1:
    query: q
    type: bar
    x: month
    y: revenue
    title: Revenue by month
rows:
  - cols:
      - text: "## Key takeaways\\n\\nNorth region is leading this quarter."
      - bar1
"""


def test_chart_title_paints_higher_than_a_narrow_column_heading_today() -> None:
    """The alignment target: where a chart actually paints its title.

    Reproduces the parent task's blocking unknown: a chart column shares a
    row with a prose column, both the same width. This pins that today the
    chart's title sits measurably higher (closer to the row top) than the
    same-width prose column's heading -- the actual, current version of the
    "don't line up" complaint.
    """
    resolved = resolve_style(get_theme_style("editorial"))
    style = get_compact_style(resolved)

    svg, card_padding = _render_board(_BOARD_YAML)

    heading_top = _heading_top(_prose_column_svg(svg))
    # This row's prose column is narrow (shared with a chart), so it should
    # show the same full-margin behaviour as the direct render_prose_svg
    # call in test_narrow_column_heading_keeps_its_full_margin_not_flush --
    # confirming the mechanism holds through the real board pipeline, not
    # just the lower-level entry point.
    assert heading_top == pytest.approx(style.heading_margin_top_px)

    m = _CHART_TITLE_RE.search(svg)
    assert m, svg
    text_dy = float(m.group(2))
    font_size = float(m.group(3))
    # Vega's autosize insets the whole plot (marks-group) by card_padding plus
    # the title band's own reserved height; the title's role-group transform
    # is that reserved height, negated, so the two cancel algebraically and
    # the title text's top is card_padding + its own offset within the band.
    chart_title_top = card_padding + text_dy - font_size

    assert chart_title_top < heading_top
