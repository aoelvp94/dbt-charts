"""Two blocks in one row agree on the inset between their box and their ink.

Block boxes are laid out correctly — what drifts is the gap between a block's
box and its first painted ink. A chart carrying a ``color:`` series wraps into
an ``hconcat`` for the endpoint-label rail, and Vega-Lite only honors
``padding`` at a spec's root: on a concat it is dropped and Vega falls back to
its own default, so the multi-series chart's ink sat 11px higher in its cell
than its single-series neighbor's.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..._svg_render import authored_boxes, render_board_to_svg

_SVG_NS = "{http://www.w3.org/2000/svg}"
_TRANSLATE = re.compile(r"translate\(\s*(-?[\d.]+)[,\s]+(-?[\d.]+)")

# Two equal-width cells, so both titles land on the same width tier and the
# typographic ladder cannot account for any difference the tests measure.
_PAIRED_ROW_BOARD = """
title: Inset Probe
queries:
  multi:
    type: values
    rows:
      - {month: Jan, revenue: 100, series: Core}
      - {month: Feb, revenue: 150, series: Core}
      - {month: Jan, revenue: 60, series: Growth}
      - {month: Feb, revenue: 90, series: Growth}
  single:
    type: values
    rows:
      - {month: Jan, revenue: 100}
      - {month: Feb, revenue: 150}
charts:
  paired:
    query: multi
    type: area
    x: month
    y: revenue
    color: series
    title: Paired Series
  lone:
    query: single
    type: area
    x: month
    y: revenue
    title: Lone Series
rows:
  - height: 320
    cols: [paired, lone]
"""

_CHART_PATHS = ("charts.paired", "charts.lone")

# render_svg_family returns a callout card full-bleed at 0,0 — the padding its
# caller was handed is never applied to it.
_FULL_BLEED_BOARD = """
title: Full Bleed Probe
charts:
  note:
    type: callout
    message: "An authored callout card."
rows:
  - cols: [note]
"""

# One dominant slice against 24 slivers, so the slivers are too small to label
# on the wheel and the pie composes a companion table for them (the `hybrid`
# mode, which is the one this heading text identifies). The composite pads the
# wheel above but leaves the table flush with its own bottom edge.
_PIE_ROWS = "\n".join(
    f"      - {{cat: Slice {i:02d}, v: {400 if i == 0 else 1}}}" for i in range(25)
)
_ATTACHED_TABLE_BOARD = f"""
title: Attached Table Probe
queries:
  q:
    type: values
    rows:
{_PIE_ROWS}
charts:
  wheel:
    query: q
    type: pie
    theta: v
    color: cat
rows:
  - height: 420
    cols: [wheel]
"""


def _title_baselines(svg: str) -> dict[str, float]:
    """Absolute y of each chart title's text baseline, by authored path.

    Vega emits the title deep inside the chart's own nested ``<svg>``, so the
    offset that places it is the whole ``translate(...)`` chain from the page
    root down to the text — walking the tree is the only way to sum exactly
    that chain and nothing else.
    """
    baselines: dict[str, float] = {}

    def walk(node: ET.Element, y: float, path: str | None, in_title: bool) -> None:
        moved = _TRANSLATE.search(node.get("transform", ""))
        if moved:
            y += float(moved.group(2))
        if node.tag == f"{_SVG_NS}svg":
            y += float(node.get("y", 0.0))
        path = node.get("data-authored-path", path)
        in_title = in_title or node.get("data-authored-kind") == "title"
        if in_title and node.tag == f"{_SVG_NS}text" and path is not None:
            baselines.setdefault(path, y + float(node.get("y", 0.0)))
        for child in node:
            walk(child, y, path, in_title)

    walk(ET.fromstring(svg), 0.0, None, False)
    return baselines


def test_charts_in_a_row_agree_on_their_title_inset() -> None:
    """The top edge of each block is the line a reader scans a board along."""
    svg = render_board_to_svg(_PAIRED_ROW_BOARD)
    outer = authored_boxes(svg, "dbt-box-outer")
    baselines = _title_baselines(svg)

    insets = {path: baselines[path] - outer[path][1] for path in _CHART_PATHS}

    assert insets["charts.paired"] == insets["charts.lone"], (
        "charts in one row disagree on the inset from their box to their title: "
        f"{insets} — a concat spec drops root padding and falls back to Vega's own"
    )


def test_the_gutter_between_two_charts_belongs_to_neither() -> None:
    """``dbt-box-inner`` insets the pointer target by the block's own padding so
    the gap between two blocks is dead space rather than belonging to whichever
    chart abuts it. Vega families were handed a zero inset, which made the inner
    box the whole cell.
    """
    svg = render_board_to_svg(_PAIRED_ROW_BOARD)
    outer = authored_boxes(svg, "dbt-box-outer")
    inner = authored_boxes(svg, "dbt-box-inner")

    for path in _CHART_PATHS:
        ox, oy, ow, oh = outer[path]
        ix, iy, iw, ih = inner[path]
        assert (ix > ox, iy > oy, ix + iw < ox + ow, iy + ih < oy + oh) == (
            True,
            True,
            True,
            True,
        ), (
            f"{path}: inner box ({ix}, {iy}, {iw}, {ih}) is not inset inside "
            f"outer ({ox}, {oy}, {ow}, {oh})"
        )


def test_a_full_bleed_card_claims_no_inset_it_does_not_have() -> None:
    """The inner box describes where the ink is, so a card that paints to its
    own edge must declare the whole cell.

    A ``callout`` is not a Vega family and is not one of the padding-shrunk SVG
    families either, so it reaches the same branch as a Vega chart while its
    card is returned full-bleed. Insetting it there put a 60px card's pointer
    target on a 4px strip of its own ink.
    """
    svg = render_board_to_svg(_FULL_BLEED_BOARD)

    assert (
        authored_boxes(svg, "dbt-box-inner")["charts.note"]
        == authored_boxes(svg, "dbt-box-outer")["charts.note"]
    )


def test_a_composed_companion_table_claims_no_inset_it_does_not_have() -> None:
    """A pie that outgrows its own slice labels composes a companion table, and
    that composite is padded above but flush below.

    The wheel is a Vega render carrying the padding; the table underneath it
    sits on the composite's own bottom edge. The block therefore has no single
    inset to claim, and claiming one puts its pointer target on the table's
    last row — the same defect a `callout` had, one composition further out.
    """
    svg = render_board_to_svg(_ATTACHED_TABLE_BOARD)

    assert "Too small to label" in svg, (
        "fixture no longer reaches the companion-table mode"
    )
    assert (
        authored_boxes(svg, "dbt-box-inner")["charts.wheel"]
        == authored_boxes(svg, "dbt-box-outer")["charts.wheel"]
    )
