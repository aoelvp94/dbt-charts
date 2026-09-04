"""Tests for the chart hover runtime: raw JS source vs SVG-embedded script.

The raw source exists so an embedding host (Cloud chat embeds) can ship the
runtime as a plain HTML <script> next to sanitized SVG output; the SVG variant
wraps the same source for inline execution inside rendered boards.

Behavioral coverage of the runtime's own logic (grouping, dedup, legend
ordering, row-cap/remainder, cross-chart scoping) lives in
libs/playground/tests/js/chart-interactivity-runtime.test.js, which evaluates
the theme-substituted script in jsdom against real DOM fixtures and asserts on
rendered tooltip content -- not on the generated source text. This file keeps
only what a JS harness can't check: the Python-side placeholder substitution,
the SVG-wrapping mechanism, the `_build_tooltip_style_dict` value mapping, the
emitted aria-label wire format the JS suite's hand-built fixtures assume, and
the render-precondition the JS suite's cross-chart isolation test relies on.
"""

from __future__ import annotations

from typing import Any


def _resolved_style() -> Any:
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_style

    return resolve_style(get_theme_style("stark"))


def test_source_substitutes_theme_placeholders() -> None:
    """Both injection placeholders must be replaced with resolved theme values."""
    from dbt_charts.core.render.chart_interactivity import (
        generate_chart_interactivity_source,
    )

    source = generate_chart_interactivity_source(_resolved_style())

    assert "__DCT_FONT_FAMILY__" not in source
    assert "__DCT_TOOLTIP_STYLE__" not in source
    assert "__DCT_NULL_DISPLAY__" not in source
    # The runtime's own declarations survive substitution.
    assert "DCT_TOOLTIP_STYLE" in source
    assert "__dbtChartsChartHoverState" in source


def test_null_display_is_the_shared_constant_not_a_js_literal() -> None:
    """formatValue()'s null case must read the substituted NULL_DISPLAY value,
    not a hardcoded JS literal — the tooltip surface is the one place a null
    could still diverge from every other surface by editing only one side."""
    import json

    from dbt_charts.core.render.chart_interactivity import (
        generate_chart_interactivity_source,
    )
    from dbt_charts.core.text.format_d3 import NULL_DISPLAY

    source = generate_chart_interactivity_source(_resolved_style())

    assert f"return '{NULL_DISPLAY}';" not in source
    assert f"return {json.dumps(NULL_DISPLAY)};" in source


def test_source_is_raw_javascript_without_markup() -> None:
    """The source form carries no <script> wrapper or CDATA markers."""
    from dbt_charts.core.render.chart_interactivity import (
        generate_chart_interactivity_source,
    )

    source = generate_chart_interactivity_source(_resolved_style())

    assert "<script" not in source
    assert "CDATA" not in source


def test_svg_script_wraps_the_same_source() -> None:
    """The SVG variant wraps the same source, fenced comments stripped for
    embedding."""
    from dbt_charts.core.render.chart_interactivity import (
        generate_chart_interactivity_source,
        generate_svg_chart_interactivity_script,
    )
    from dbt_charts.core.render.comment_stripping import strip_js_comments

    resolved = _resolved_style()
    source = generate_chart_interactivity_source(resolved)
    svg_script = generate_svg_chart_interactivity_script(resolved)

    assert strip_js_comments(source) in svg_script
    assert svg_script.lstrip().startswith("<script")
    assert "CDATA" in svg_script


def test_tooltip_style_blob_carries_swatch() -> None:
    """The swatch size/shape is a cascade value in the JS style blob, not a
    hardcoded literal in the runtime."""
    from dbt_charts.core.render.chart_interactivity import _build_tooltip_style_dict

    blob = _build_tooltip_style_dict(_resolved_style())

    assert "swatch" in blob
    assert blob["swatch"]["size"] > 0
    assert "radius" in blob["swatch"]


def test_tooltip_style_blob_carries_active_marker() -> None:
    """active_marker is a cascade value in the JS style blob (stark -> 'triangle')."""
    from dbt_charts.core.render.chart_interactivity import _build_tooltip_style_dict

    blob = _build_tooltip_style_dict(_resolved_style())

    assert blob["activeMarker"] == "triangle"


def test_multi_chart_board_isolates_shared_x_marks_per_chart() -> None:
    """Render precondition the ``.dbt-chart`` grouping scope relies on: two
    charts that share an x value render into SEPARATE ``.dbt-chart`` subtrees,
    each carrying its own marks for the shared identity.

    Two ``x: month`` bar charts with the same months are the cross-chart
    contamination case: a board-wide mark query on a "Jan" hover would collect
    both charts' Jan marks. This asserts each chart's Jan/Feb marks live in its
    own ``id="chart-*"`` subtree, so ``closest('.dbt-chart')`` isolates them. If
    a render change ever merged charts into one container, this fails first --
    the scope fix would otherwise silently regress to board-wide grouping.
    """
    import re

    from .._svg_render import render_board_to_svg

    board = """
title: Two charts sharing x
queries:
  q:
    type: values
    rows:
      - {month: Jan, region: North, revenue: 100}
      - {month: Jan, region: South, revenue: 40}
      - {month: Feb, region: North, revenue: 150}
      - {month: Feb, region: South, revenue: 60}
charts:
  a: {query: q, type: bar, x: month, y: revenue, color: region}
  b: {query: q, type: bar, x: month, y: revenue, color: region}
rows: [a, b]
"""
    svg = render_board_to_svg(board)
    ia, ib = svg.index('id="chart-a"'), svg.index('id="chart-b"')
    assert ia < ib, "expected two distinct .dbt-chart subtrees on the board"
    # The runtime scopes grouping by `.closest('.dbt-chart')` -- pin the class
    # itself, not just the id, so a render-side rename of that scope class
    # fails here instead of silently regressing to board-wide grouping while
    # this precondition (id-only) and the JS cross-chart test (which hard-
    # codes the class name in its fixture) both stay green.
    assert 'class="dbt-chart" id="chart-a"' in svg
    assert 'class="dbt-chart" id="chart-b"' in svg

    def data_mark_labels(chunk: str) -> list[str]:
        return [
            label
            for label in re.findall(r'aria-label="([^"]*)"', chunk)
            if "revenue" in label and ("Jan" in label or "Feb" in label)
        ]

    chart_a, chart_b = data_mark_labels(svg[ia:ib]), data_mark_labels(svg[ib:])
    # Each chart's own subtree carries the shared identity independently.
    assert any("Jan" in m for m in chart_a) and any("Feb" in m for m in chart_a)
    assert any("Jan" in m for m in chart_b) and any("Feb" in m for m in chart_b)


def test_aria_label_wire_format_matches_runtime_parser_contract() -> None:
    """Pins the emitted aria-label's separator/prefix conventions the JS
    runtime's parseAriaLabel depends on (ROLE_HEADER-prefixed header, '; '
    row separator, 'Label: value' dependent rows).

    The JS behavioral suite (chart-interactivity-runtime.test.js) hand-builds
    its own aria-labels using these same conventions to drive the runtime --
    a wire-format drift there wouldn't fail that suite, since it round-trips
    its own encoding through the same parser rather than the real emitter.
    This test renders a real chart and asserts the format the emitter
    actually produces, so a wire-format change fails here even when the JS
    suite's hand-built fixtures would silently keep passing.
    """
    import re

    from dbt_charts.core.render.chart.emitters._tooltip import ROLE_HEADER

    from .._svg_render import render_board_to_svg

    board = """
title: Aria label wire format
queries:
  q:
    type: values
    rows:
      - {month: Jan, revenue: 100}
charts:
  a: {query: q, type: bar, x: month, y: revenue}
"""
    svg = render_board_to_svg(board)
    header_labels = [
        label
        for label in re.findall(r'aria-label="([^"]*)"', svg)
        if label.startswith(ROLE_HEADER)
    ]

    # A single row's own value always defines the axis domain, so it's never
    # "tiny" relative to it -- BarHoverBandFeature's hover band correctly adds
    # no layer here (see bar_hover_band.py's module docstring). Only the real
    # bar's aria-label is present; this test pins its wire FORMAT.
    assert header_labels == [f"{ROLE_HEADER}Jan; revenue: 100"]
