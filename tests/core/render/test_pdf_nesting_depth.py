"""Regression test: inert wrapper `<g>`s exhaust PDF's 28-level nesting budget.

Every nested board wraps its content in a handful of `translate(...)` `<g>`s
(board margin, layout-content offset, row/col/grid item position). When a
board nests boards inside boards — a real report-style layout, not a
pathological one — most of those transforms are `(0, 0)`: the wrapper carries
no visual meaning, but it still counts against the PDF writer's hard limit on
graphics-state (`q`/`Q`) nesting. A handful of real-world reports (e.g.
`apps/evals/charts/effort-ladder.yml`) cross that limit and fail PDF export
outright, even though the same SVG rasterizes to PNG fine.

The fix is at the emitter: don't open a `<g>` for a no-op translate. That
raises how deep a board can nest before hitting the budget (a fixture nesting
6 levels deep, which fails before the fix, now succeeds); it does not remove
the budget itself — a board nested deep enough still hits it, just later.
"""

from __future__ import annotations

import re

from dbt_charts.core.render.converters.pdf import to_pdf

from .._svg_render import render_board_to_svg

_BOARD_HEADER = """
title: Nest Test
queries:
  q1:
    type: values
    rows:
      - {month: Jan, revenue: 100}
charts:
  c1:
    query: q1
    type: bar
    x: month
    y: revenue
"""


def _nested_rows_board(depth: int) -> str:
    """A board nesting a single-item `rows:` board `depth` times around `c1`.

    Each level is itself a full nested board (no title, no margin), so every
    wrapper transform it contributes is a no-op `(0, 0)` translate before the
    fix.
    """

    def build(remaining: int, indent: int) -> str:
        pad = "  " * indent
        if remaining == 0:
            return f"{pad}rows:\n{pad}  - c1"
        return f"{pad}rows:\n{pad}  -\n" + build(remaining - 1, indent + 2)

    return _BOARD_HEADER + build(depth, 0)


def test_six_levels_nested_board_exports_to_pdf() -> None:
    """Nesting six levels deep fails before the fix and must succeed after."""
    svg = render_board_to_svg(_nested_rows_board(depth=6))

    to_pdf(svg)


def test_deeply_nested_board_emits_no_inert_translate_groups() -> None:
    """No `<g>` should carry a no-op `translate(0, 0)` with nothing else on it.

    Matches our own emitters' ``", "``-separated coordinate formatting only —
    Vega-Lite's embedded chart SVG emits its own comma-only
    ``translate(0,0)`` root mark group, which is out of scope here.
    """
    svg = render_board_to_svg(_nested_rows_board(depth=6))

    inert = re.findall(r'<g transform="translate\(0, 0\)">', svg)
    assert not inert, f"found {len(inert)} inert wrapper <g> element(s)"
