"""Tests for renderer.py's _collect_render_warnings width handling.

Regression coverage for the CONFIRMED case in
ai_notes/chart-chrome-vs-plot-dimensions-2026-07-20.md (#5): the warning-
detection pass rendered a throwaway spec with ``width=None``, which resolves
to the theme-family default width — never the chart's real, laid-out slot
width. A chart squeezed into a narrow column can render with visibly
unreadable bar bands while BAR_BAND_WIDTH_TOO_NARROW stays silent, because
the detector was checking against the wrong (too-wide) number.
"""

from __future__ import annotations

from unittest.mock import Mock

from dbt_charts.core.compile import compile
from dbt_charts.core.execute import Executor
from dbt_charts.core.render import render


def _daily_rows(n: int) -> list[dict[str, object]]:
    return [{"day": f"2026-01-{i:03d}", "val": i} for i in range(n)]


def _category_rows(n: int) -> list[dict[str, object]]:
    return [{"cat": f"c{i}", "val": i} for i in range(n)]


def _make_executor(board, query_registry, rows):
    ok = Mock()
    ok.is_success = True
    ok.data = rows
    ok.column_descriptions = None
    ok.resolved_relations = None
    ok.truncated_reason = None
    mock_registry = Mock()
    mock_registry.execute.return_value = ok
    return Executor(
        board, adapter_registry=mock_registry, query_registry=query_registry
    )


_BOARD_YAML = """
title: Narrow bar column
charts:
  narrow_chart:
    query: q
    type: bar
    x: day
    y: val
  filler:
    query: q
    type: bar
    x: day
    y: val
queries:
  q:
    sql: SELECT day, val FROM t
    source: test_source
cols:
  - id: narrow
    width: 150
    rows:
      - narrow_chart
  - filler
"""


def test_bar_band_width_warning_uses_real_layout_width_not_theme_default() -> None:
    """100 daily bars: 6px/band at the 600px theme default (no fire), 1.5px/band
    at the chart's real 150px column width (fires). The detector must see the
    real width — a chart this narrow ships genuinely unreadable ghost bands.
    """
    result = compile(_BOARD_YAML)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _daily_rows(100))

    render_result = render(result.board, executor, format="svg")

    codes = {w.code for w in render_result.warnings}
    assert "WARN-BAR-BAND-WIDTH-TOO-NARROW" in codes, (
        "narrow_chart is laid out at ~150px for 100 daily bands (~1.5px/band, "
        "well under the 4px floor) — the detector must fire using the real "
        "layout width, not the unrelated theme-default width"
    )
    narrow_warning = next(
        w
        for w in render_result.warnings
        if w.code == "WARN-BAR-BAND-WIDTH-TOO-NARROW" and w.chart == "narrow_chart"
    )
    assert narrow_warning.chart == "narrow_chart"


_SHARED_CHART_TWO_WIDTHS_YAML = """
title: Shared chart, no tabs
charts:
  s:
    query: q
    type: bar
    x: cat
    y: val
    style:
      orientation: vertical
  filler_a:
    query: q
    type: bar
    x: cat
    y: val
    style:
      orientation: vertical
  filler_b:
    query: q
    type: bar
    x: cat
    y: val
    style:
      orientation: vertical
queries:
  q:
    sql: SELECT cat, val FROM t
    source: test_source
rows:
  - cols: [s]
  - cols: [s, filler_a, filler_b]
"""


def test_bar_band_width_warning_uses_narrowest_placement_no_tabs() -> None:
    """A chart placed twice with no tabs involved at all: full-width in row 1,
    a 3-way column split (narrow) in row 2. 200 categories are unreadable at
    the narrow width but comfortably readable at the full width — the
    detector must fire, judged at the narrowest real placement. This is the
    same width-selection bug ``tabs`` scoping introduced (silencing a
    detector by picking the widest of two placements), reproduced on a board
    that never uses ``tabs`` at all.
    """
    result = compile(_SHARED_CHART_TWO_WIDTHS_YAML)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _category_rows(200))

    render_result = render(result.board, executor, format="svg")

    codes = {(w.chart, w.code) for w in render_result.warnings}
    assert ("s", "WARN-BAR-BAND-WIDTH-TOO-NARROW") in codes, (
        "chart 's' is unreadable at its narrow (3-column) placement — the "
        "detector must not be silenced by also appearing full-width "
        f"elsewhere on the same (non-tabbed) board: {render_result.warnings}"
    )
