"""Regression tests for V2 renderer parity gaps on dashes-palette-lab.

Covers three concrete gaps:
  1. strokeDash encoding emitted when style.charts.dashes is configured.
  2. x-axis labelExpr for ordinal YYYY-MM bucketed-time data.
  3. x-axis axis.values tick array for ordinal YYYY-MM bucketed-time data.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from dbt_charts.core.render.chart.spec import RenderBox

_DEFAULT_BOX = RenderBox(width=600.0, height=300.0)

from dbt_charts.core.render.chart.session import BoardRenderSession

# ---------------------------------------------------------------------------
# Data fixture – 12 months of two series, YYYY-MM format (not YYYY-MM-DD)
# ---------------------------------------------------------------------------

_MONTH_DATA: list[dict[str, Any]] = [
    {"month": f"2025-{m:02d}", "value": v, "series": s}
    for m, v, s in [
        (1, 12, "alpha"),
        (2, 14, "alpha"),
        (3, 18, "alpha"),
        (4, 22, "alpha"),
        (5, 28, "alpha"),
        (6, 32, "alpha"),
        (7, 38, "alpha"),
        (8, 41, "alpha"),
        (9, 44, "alpha"),
        (10, 49, "alpha"),
        (11, 55, "alpha"),
        (12, 60, "alpha"),
        (1, 20, "bravo"),
        (2, 21, "bravo"),
        (3, 22, "bravo"),
        (4, 24, "bravo"),
        (5, 26, "bravo"),
        (6, 29, "bravo"),
        (7, 33, "bravo"),
        (8, 38, "bravo"),
        (9, 42, "bravo"),
        (10, 45, "bravo"),
        (11, 47, "bravo"),
        (12, 50, "bravo"),
    ]
]

_DASHES: list[list[int]] = [[12, 16], [2, 6], [12, 10, 0, 10]]


def _make_board_style(*, dashes: list[list[int]] | None = None):
    """Return (ResolvedStyle, ChartStyleContext), optionally overriding dashes.

    Uses the 'stark' theme because the 'editorial' (default) theme suppresses
    the legend (legend.visible=False), which would obscure legend-related assertions.
    The dashes-palette-lab.yml board also uses stark.
    """
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context

    rs, ctx = resolve_style_and_context(get_theme_style("stark"))
    if dashes is not None:
        ctx = dataclasses.replace(ctx, dashes=dashes)
    return rs, ctx


def _resolve_line_with_color(ctx):
    """Resolve a line chart with x=month, y=value, color=series."""
    from dbt_charts.core.compile.models.chart.normalized.line import LineChart
    from dbt_charts.core.compile.resolve import resolve

    chart = LineChart(
        id="test",
        type="line",
        query_name="q",
        x="month",
        y="value",
        color="series",
    )
    return resolve(chart, _MONTH_DATA, ctx)


# ---------------------------------------------------------------------------
# Gap 1: strokeDash encoding
# ---------------------------------------------------------------------------


def test_strokedash_encoding_absent_without_dashes() -> None:
    """With no dashes configured, V2 must NOT emit strokeDash encoding."""
    rs, ctx = _make_board_style()
    assert ctx.dashes == []
    chart = _resolve_line_with_color(ctx)
    session = BoardRenderSession.create(rs)
    spec = session.emit_chart(chart, _DEFAULT_BOX, {"q": _MONTH_DATA})
    assert "strokeDash" not in spec.encoding


def test_strokedash_encoding_present_with_dashes() -> None:
    """With dashes configured, V2 must emit encoding.strokeDash bound to the color field."""
    rs, ctx = _make_board_style(dashes=_DASHES)
    chart = _resolve_line_with_color(ctx)
    session = BoardRenderSession.create(rs)
    spec = session.emit_chart(chart, _DEFAULT_BOX, {"q": _MONTH_DATA})

    assert "strokeDash" in spec.encoding, (
        "strokeDash encoding must be emitted when dashes configured"
    )
    sd = spec.encoding["strokeDash"]
    assert sd["field"] == "series"
    assert sd["type"] in ("nominal", "ordinal")
    assert "scale" in sd
    assert sd["scale"]["range"] == _DASHES


def test_strokedash_encoding_matches_color_field() -> None:
    """strokeDash must bind to the same field as color."""
    rs, ctx = _make_board_style(dashes=_DASHES)
    chart = _resolve_line_with_color(ctx)
    session = BoardRenderSession.create(rs)
    spec = session.emit_chart(chart, _DEFAULT_BOX, {"q": _MONTH_DATA})

    color_field = spec.encoding.get("color", {}).get("field")
    dash_field = spec.encoding.get("strokeDash", {}).get("field")
    assert color_field == dash_field == "series"


def test_strokedash_legend_suppressed_when_color_legend_suppressed() -> None:
    """strokeDash must not carry its own legend once endpoint labels null color's.

    Regression: color.legend: null (set when endpoint labels replace the
    legend — stark enables endpoint_labels for line by default) does not
    apply to a sibling encoding channel. Without an explicit legend: null on
    strokeDash too, VL renders an independent, un-suppressed dash-pattern
    legend alongside the endpoint-label pane — redundant chrome the author
    never asked for.
    """
    rs, ctx = _make_board_style(dashes=_DASHES)
    chart = _resolve_line_with_color(ctx)
    assert chart.legend.visible is False, (
        "fixture must have endpoint labels suppressing the legend "
        "(stark's line.endpoint_labels.visible default) for this test to be meaningful"
    )
    session = BoardRenderSession.create(rs)
    spec = session.emit_chart(chart, _DEFAULT_BOX, {"q": _MONTH_DATA})

    assert spec.encoding["color"]["legend"] is None
    assert spec.encoding["strokeDash"]["legend"] is None


# ---------------------------------------------------------------------------
# Gap 2+3: x-axis labelExpr and axis.values for ordinal YYYY-MM data
# ---------------------------------------------------------------------------


def test_x_axis_label_expr_emitted_for_ordinal_month() -> None:
    """V2 must emit encoding.x.axis.labelExpr for YYYY-MM ordinal month data."""
    rs, ctx = _make_board_style()
    chart = _resolve_line_with_color(ctx)
    session = BoardRenderSession.create(rs)
    spec = session.emit_chart(chart, _DEFAULT_BOX, {"q": _MONTH_DATA})

    x_enc = spec.encoding.get("x", {})
    ax_dict = x_enc.get("axis", {})
    assert "labelExpr" in ax_dict, (
        "V2 must emit labelExpr for ordinal YYYY-MM time axes — "
        "the dual-line year+month label expression was missing"
    )
    expr: str = ax_dict["labelExpr"]
    # Verify it's a time-format expression
    assert "utcFormat" in expr or "Format" in expr, (
        f"labelExpr should reference a time-format function, got: {expr!r}"
    )


def test_x_axis_label_expr_emitted_for_temporal_month() -> None:
    """Line always routes a YYYY-MM bucketed grain to continuous temporal (see
    value-driven-axis-type-inference) — no axis.values tick array (that's the
    ordinal-only bar/column density mechanism); a smart-cadence labelExpr still
    applies."""
    rs, ctx = _make_board_style()
    chart = _resolve_line_with_color(ctx)
    session = BoardRenderSession.create(rs)
    spec = session.emit_chart(chart, _DEFAULT_BOX, {"q": _MONTH_DATA})

    x_enc = spec.encoding.get("x", {})
    assert x_enc.get("type") == "temporal"
    assert x_enc.get("timeUnit") == "utcyearmonth"
    ax_dict = x_enc.get("axis", {})
    assert "labelExpr" in ax_dict, "expected smart-cadence labelExpr on temporal axis"
