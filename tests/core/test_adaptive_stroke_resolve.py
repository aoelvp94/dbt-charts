"""Density-adaptive stroke baked into the resolve layer.

Tests pin BEHAVIOR under variation — monotonicity, author-pin, companion
fields, zero sentinel, fallback, and faceted per-cell width — not theme
literals (per dbt-charts/AGENTS.md).  Pure-helper tests are unit-level;
resolve-level tests construct a minimal normalized chart and call resolve().
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.chart.adaptive_stroke import (
    adaptive_stroke,
    facet_panel_width,
    max_points_per_series,
)
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

_BOARD_STYLE = resolve_chart_style_context(get_theme_style())
_QUERY = SqlQuery(sql="SELECT 1", source="src")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _line_chart(
    n_points: int,
    *,
    width: float = 600.0,
    color: str | None = None,
    stroke_width: float | None = None,
    point_size: float | None = None,
    point_stroke_width: float | None = None,
    multiples_columns: str | None = None,
) -> tuple[Chart, list[dict[str, Any]], float]:
    """Return (chart, data, width) for a simple line chart."""
    marks_patch: dict[str, Any] = {}
    if stroke_width is not None:
        marks_patch["line"] = {"stroke": {"width": stroke_width}}
    if point_size is not None or point_stroke_width is not None:
        point_patch: dict[str, Any] = {}
        if point_size is not None:
            point_patch["size"] = point_size
        if point_stroke_width is not None:
            point_patch["stroke_width"] = point_stroke_width
        marks_patch["point"] = point_patch

    style_dict: dict[str, Any] = {"marks": marks_patch} if marks_patch else {}

    multiples: dict[str, str] | None = (
        {"columns": multiples_columns} if multiples_columns is not None else None
    )

    chart_dict: dict[str, Any] = {
        "id": "t",
        "type": "line",
        "x": "x",
        "y": "y",
        "color": color,
        "query": _QUERY,
        "query_name": "q",
    }
    if style_dict:
        chart_dict["style"] = style_dict
    if multiples is not None:
        chart_dict["multiples"] = multiples

    chart = TypeAdapter(Chart).validate_python(chart_dict)

    if color is not None:
        # Two series: A and B, each with n_points distinct x values
        data: list[dict[str, Any]] = [
            {"x": i, "y": float(i), "series": "A"} for i in range(n_points)
        ] + [{"x": i, "y": float(i) * 2, "series": "B"} for i in range(n_points)]
    elif multiples_columns is not None:
        # Two facet panels: cat0 and cat1, each with n_points
        data = [{"x": i, "y": float(i), "facet": "cat0"} for i in range(n_points)] + [
            {"x": i, "y": float(i), "facet": "cat1"} for i in range(n_points)
        ]
    else:
        data = [{"x": i, "y": float(i)} for i in range(n_points)]

    return chart, data, width


def _area_chart(
    n_points: int,
    *,
    width: float = 600.0,
    color: str | None = None,
    stroke_width: float | None = None,
    multiples_columns: str | None = None,
) -> tuple[Chart, list[dict[str, Any]], float]:
    """Return (chart, data, width) for a simple area chart."""
    marks_patch: dict[str, Any] = {}
    if stroke_width is not None:
        marks_patch["line"] = {"stroke": {"width": stroke_width}}

    style_dict: dict[str, Any] = {"marks": marks_patch} if marks_patch else {}

    chart_dict: dict[str, Any] = {
        "id": "t",
        "type": "area",
        "x": "x",
        "y": "y",
        "color": color,
        "query": _QUERY,
        "query_name": "q",
    }
    if style_dict:
        chart_dict["style"] = style_dict
    if multiples_columns is not None:
        chart_dict["multiples"] = {"columns": multiples_columns}

    chart = TypeAdapter(Chart).validate_python(chart_dict)

    if color is not None:
        data: list[dict[str, Any]] = [
            {"x": i, "y": float(i), "series": "A"} for i in range(n_points)
        ] + [{"x": i, "y": float(i) * 2, "series": "B"} for i in range(n_points)]
    elif multiples_columns is not None:
        # Two facet panels each with n_points sharing the same x values — the bug
        # path (full card width) gives the same stroke as non-faceted; the fix
        # (per-panel width) gives a thinner stroke because px_per_point shrinks.
        data = [{"x": i, "y": float(i), "facet": "cat0"} for i in range(n_points)] + [
            {"x": i, "y": float(i), "facet": "cat1"} for i in range(n_points)
        ]
    else:
        data = [{"x": i, "y": float(i)} for i in range(n_points)]

    return chart, data, width


def _resolved_line_stroke(
    n_points: int, *, width: float = 600.0, color: str | None = None, **kwargs: Any
) -> float:
    chart, data, w = _line_chart(n_points, width=width, color=color, **kwargs)
    resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
    return resolved.style.line_mark.stroke.width


def _resolved_area_stroke(
    n_points: int, *, width: float = 600.0, color: str | None = None
) -> float:
    chart, data, w = _area_chart(n_points, width=width, color=color)
    resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
    return resolved.style.line_mark.stroke.width


# ---------------------------------------------------------------------------
# Unit tests: adaptive_stroke() formula
# ---------------------------------------------------------------------------


# Explicit clamp bounds for the pure-formula tests (min_w/max_w are required
# args now — no in-code defaults; production passes chart_rendering.stroke).
_MIN_W = 1.5
_MAX_W = 4.0


class TestAdaptiveStrokeFormula:
    def test_midpoint_returns_expected_value(self) -> None:
        """At px_per_point=e^1 ≈ 2.72, raw=1+1=2.0, snapped to 2.0 (within clamp)."""
        result = adaptive_stroke(math.e, _MIN_W, _MAX_W)
        assert result == 2.0

    def test_dense_end_clamps_at_floor(self) -> None:
        """Very dense (1 px/pt) → clamp floor."""
        assert adaptive_stroke(1.0, _MIN_W, _MAX_W) == _MIN_W

    def test_sparse_end_clamps_at_ceiling(self) -> None:
        """Very sparse (1000 px/pt) → clamp ceiling."""
        assert adaptive_stroke(1000.0, _MIN_W, _MAX_W) == _MAX_W

    def test_snap_to_half_integers(self) -> None:
        """Output is always a multiple of 0.5."""
        for px in [1.5, 3.0, 6.0, 15.0, 50.0, 100.0]:
            result = adaptive_stroke(px, _MIN_W, _MAX_W)
            assert result * 2 == round(result * 2), f"px={px}: {result} not half-int"

    def test_negative_px_raises(self) -> None:
        with pytest.raises(ValueError, match="px_per_point must be positive"):
            adaptive_stroke(-1.0, _MIN_W, _MAX_W)

    def test_zero_px_raises(self) -> None:
        with pytest.raises(ValueError, match="px_per_point must be positive"):
            adaptive_stroke(0.0, _MIN_W, _MAX_W)

    def test_monotonic_increasing(self) -> None:
        """More space per point → thicker stroke."""
        widths = [
            adaptive_stroke(px, _MIN_W, _MAX_W) for px in [1.0, 2.0, 5.0, 10.0, 50.0]
        ]
        assert widths == sorted(widths)


# ---------------------------------------------------------------------------
# Unit tests: max_points_per_series()
# ---------------------------------------------------------------------------


class TestFacetedDensityFoldsPerPanel:
    """``density_adaptive_stroke`` folds ``max_points_per_series`` across
    ``dataset.panels`` rather than reading the pooled rows, so a faceted
    chart's stroke is sized by its *densest panel*.

    Every other faceted fixture in this file gives both panels the same x
    range (``_line_chart``'s two panels are each ``range(n_points)``), so
    pooled and per-panel counts are identical and those tests pass under
    either implementation. This one makes the panels **disjoint**: pooling
    would see 2n distinct x values where the densest panel has n, halving
    ``effective_width / n_pts`` and baking every faceted line a full ``log``
    step too thin.
    """

    def test_disjoint_panels_size_stroke_by_the_densest_panel(self) -> None:
        n_per_panel = 10
        card_width = 600.0
        chart, _shared_range_data, width = _line_chart(
            n_per_panel, width=card_width, multiples_columns="facet"
        )
        # Disjoint ranges: cat0 over 0..9, cat1 over 10..19. Pooled distinct-x
        # is 20; the densest panel's is 10.
        data: list[dict[str, Any]] = [
            {"x": i, "y": float(i), "facet": "cat0"} for i in range(n_per_panel)
        ] + [
            {"x": i, "y": float(i), "facet": "cat1"}
            for i in range(n_per_panel, n_per_panel * 2)
        ]

        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=width)
        panel_width = facet_panel_width(
            card_width, 2, has_mirror=bool(resolved.style.axis_y.mirror)
        )
        per_panel = adaptive_stroke(panel_width / n_per_panel, _MIN_W, _MAX_W)
        pooled = adaptive_stroke(panel_width / (n_per_panel * 2), _MIN_W, _MAX_W)

        assert resolved.style.line_mark.stroke.width == per_panel
        assert per_panel != pooled, (
            "fixture no longer discriminates: pooled and per-panel counts "
            "must bake different strokes for this test to mean anything"
        )


class TestMaxPointsPerSeries:
    """One panel's rows in, densest series' point count out.

    Faceting is not this function's concern: a faceted chart folds this per
    panel via ``reduce_panels``, covered by
    ``TestFacetedDensityFoldsPerPanel`` above — which is the only faceted
    fixture here with *disjoint* panel x-ranges, and so the only one that
    can tell a per-panel fold from a pooled read.
    """

    def test_single_series_counts_distinct_x(self) -> None:
        data = [{"x": 1, "y": 0}, {"x": 2, "y": 0}, {"x": 2, "y": 1}]
        assert max_points_per_series(data, "x", "") == 2

    def test_multi_series_uses_densest(self) -> None:
        data = [{"x": i, "y": 0, "s": "A"} for i in range(5)] + [
            {"x": i, "y": 0, "s": "B"} for i in range(3)
        ]
        # A has 5 distinct x, B has 3 → densest is 5
        assert max_points_per_series(data, "x", "s") == 5

    def test_empty_data_returns_zero(self) -> None:
        assert max_points_per_series([], "x", "") == 0

    def test_null_x_values_ignored(self) -> None:
        data = [{"x": None, "y": 0}, {"x": 1, "y": 0}, {"x": 2, "y": 0}]
        assert max_points_per_series(data, "x", "") == 2


# ---------------------------------------------------------------------------
# Unit tests: facet_panel_width()
# ---------------------------------------------------------------------------


class TestFacetPanelWidth:
    def test_no_mirror_subtracts_chrome(self) -> None:
        """Without mirror, panel width = (width − chrome) / cols."""
        from dbt_charts.core.compile.config import get_chart_rendering

        cfg = get_chart_rendering().facet
        result = facet_panel_width(600.0, 3, has_mirror=False)
        expected = (600.0 - cfg.chrome_px) / 3
        assert result == pytest.approx(expected)

    def test_mirror_adds_gutter(self) -> None:
        """With mirror, extra mirror_axis_px is subtracted → narrower panels."""
        result_no_mirror = facet_panel_width(600.0, 2, has_mirror=False)
        result_mirror = facet_panel_width(600.0, 2, has_mirror=True)
        assert result_mirror < result_no_mirror

    def test_panel_shrinks_below_floor_rather_than_exceeding_card_width(self) -> None:
        """The card boundary always wins: panels shrink below min_panel_px rather
        than pushing the card wider than its declared width.

        This is the regression the panel floor used to invert — flooring
        ``usable`` at ``min_panel_px * panel_cols`` before dividing let a high
        panel count silently paint past the card's right edge. RJ's call
        (2026-08-10): the card boundary is non-negotiable, so panels below the
        legibility floor render narrower and a warning tells the author,
        rather than the floor winning and the chart overflowing its box.
        """
        from dbt_charts.core.compile.config import get_chart_rendering

        cfg = get_chart_rendering().facet
        # Very narrow width, 5 columns → panels must shrink well below the floor.
        result = facet_panel_width(10.0, 5, has_mirror=False)
        assert result < cfg.min_panel_px
        assert result == pytest.approx(0.0)

    def test_single_panel_no_facet(self) -> None:
        """1 panel, no mirror: (width − chrome) / 1."""
        from dbt_charts.core.compile.config import get_chart_rendering

        cfg = get_chart_rendering().facet
        result = facet_panel_width(600.0, 1, has_mirror=False)
        expected = 600.0 - cfg.chrome_px
        assert result == pytest.approx(expected)

    def test_panel_width_times_cols_plus_chrome_never_exceeds_card_width(self) -> None:
        """The invariant the floor used to violate: painted panels + chrome must
        fit inside the card at every panel count, not just the ones below the
        old floor's breakeven point."""
        from dbt_charts.core.compile.config import get_chart_rendering

        cfg = get_chart_rendering().facet
        width = 600.0
        for panel_cols in (1, 2, 4, 6, 10):
            panel_w = facet_panel_width(width, panel_cols, has_mirror=False)
            assert panel_w * panel_cols + cfg.chrome_px <= width + 1e-9


# ---------------------------------------------------------------------------
# Resolve-level tests: line chart baked stroke
# ---------------------------------------------------------------------------


class TestLineChartAdaptiveStroke:
    def test_monotonic_nonincreasing_as_n_rises(self) -> None:
        """More data points at same width → thinner or equal stroke."""
        strokes = [_resolved_line_stroke(n, width=600.0) for n in [5, 20, 50, 200]]
        for a, b in zip(strokes, strokes[1:], strict=False):
            assert a >= b, f"stroke should not increase as N increases: {strokes}"

    def test_monotonic_nondecreasing_as_width_rises(self) -> None:
        """More chart width at same N → thicker or equal stroke."""
        strokes = [_resolved_line_stroke(20, width=w) for w in [200, 400, 800]]
        for a, b in zip(strokes, strokes[1:], strict=False):
            assert a <= b, f"stroke should not decrease as width increases: {strokes}"

    def test_multi_series_uses_max_density(self) -> None:
        """Multi-series: adaptive uses the densest series, not total rows."""
        # Two series of 20 pts each → px_per_point = 600 / 20 (densest series)
        # Single series of 20 pts → same density
        stroke_multi = _resolved_line_stroke(20, width=600.0, color="series")
        stroke_single = _resolved_line_stroke(20, width=600.0)
        assert stroke_multi == stroke_single

    def test_author_pin_stroke_width_bypasses_adaptive(self) -> None:
        """Explicit marks.line.stroke.width → baked verbatim, no adaptive override."""
        pinned = 3.7
        chart, data, w = _line_chart(50, width=600.0, stroke_width=pinned)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        assert resolved.style.line_mark.stroke.width == pinned

    def test_companion_point_stroke_width(self) -> None:
        """When adaptive fires, baked point.stroke_width matches line stroke."""
        chart, data, w = _line_chart(20, width=600.0)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        line_stroke = resolved.style.line_mark.stroke.width
        assert resolved.style.point_mark.stroke_width == line_stroke

    def test_companion_point_size_when_visible(self) -> None:
        """When adaptive fires and points are visible (size>0), size ≈ π·stroke²."""
        # Default theme has point.size=0 (disabled). Build a board_style where
        # point.size > 0 so we exercise the companion scaling path.
        theme = get_theme_style()
        line_style = theme.charts.line
        point_with_size = line_style.marks.point.model_copy(update={"size": 16.0})
        marks_with_point = line_style.marks.model_copy(
            update={"point": point_with_size}
        )
        line_with_marks = line_style.model_copy(update={"marks": marks_with_point})
        board_style_with_points = resolve_chart_style_context(
            theme.model_copy(
                update={
                    "charts": theme.charts.model_copy(update={"line": line_with_marks})
                }
            )
        )
        chart, data, w = _line_chart(20, width=600.0)
        resolved = resolve(
            chart, data, chart_style_context=board_style_with_points, width=w
        )
        stroke = resolved.style.line_mark.stroke.width
        expected_size = math.pi * stroke**2
        assert resolved.style.point_mark.size == pytest.approx(expected_size, rel=1e-3)

    def test_default_disabled_points_stay_disabled(self) -> None:
        """Default point.size=0 (disabled) is never resurrected by adaptive."""
        chart, data, w = _line_chart(20, width=600.0)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        assert resolved.style.point_mark.size == 0.0

    def test_author_pin_point_size_preserved(self) -> None:
        """Explicit marks.point.size → baked verbatim, adaptive doesn't override."""
        pinned_size = 25.0
        chart, data, w = _line_chart(20, width=600.0, point_size=pinned_size)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        assert resolved.style.point_mark.size == pinned_size

    def test_author_pin_point_stroke_width_preserved(self) -> None:
        """Explicit marks.point.stroke_width → baked verbatim."""
        pinned_ring = 1.5
        chart, data, w = _line_chart(20, width=600.0, point_stroke_width=pinned_ring)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        assert resolved.style.point_mark.stroke_width == pinned_ring

    def test_zero_stroke_sentinel_never_resurrected(self) -> None:
        """A baked stroke width of exactly 0 must not be replaced by adaptive."""
        chart, data, w = _line_chart(20, width=600.0, stroke_width=0.0)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        assert resolved.style.line_mark.stroke.width == 0.0

    def test_zero_stroke_does_not_zero_visible_points(self) -> None:
        """Zero stroke.width in the theme (sentinel = no stroke) must not zero visible
        point companions via the adaptive companion block.

        Scenario: theme sets line.stroke.width=0.0 (the "no line" sentinel) and
        points are visible (point.size > 0) — but the author does NOT pin stroke.
        Because the cascade delivers width=0.0, the bake block is skipped correctly.
        But _adaptive_stroke > 0 is still True (computed before the bake). If the
        companion then reads resolved_line_mark.stroke.width==0.0 and applies
        π·0²=0, it silently kills the visible points.
        """
        from dbt_charts.core.compile.models.primitives import StrokeStyle

        theme = get_theme_style()
        line_style = theme.charts.line
        # Set theme-level stroke.width=0.0 (sentinel: no stroke)
        marks_with_zero_stroke = line_style.marks.model_copy(
            update={
                "line": line_style.marks.line.model_copy(
                    update={"stroke": StrokeStyle(width=0.0)}
                ),
                # Enable visible points (size > 0) at the theme level
                "point": line_style.marks.point.model_copy(update={"size": 16.0}),
            }
        )
        line_with_zero = line_style.model_copy(update={"marks": marks_with_zero_stroke})
        board_with_zero_stroke = resolve_chart_style_context(
            theme.model_copy(
                update={
                    "charts": theme.charts.model_copy(update={"line": line_with_zero})
                }
            )
        )
        # Author does NOT pin stroke — so _line_stroke_authored=False and
        # _adaptive_stroke > 0, but bake is skipped (zero sentinel).
        # Companion block must NOT then zero the visible points.
        chart, data, w = _line_chart(20, width=600.0)  # no authored stroke
        resolved = resolve(
            chart, data, chart_style_context=board_with_zero_stroke, width=w
        )
        # Line stroke remains 0.0 (sentinel respected)
        assert resolved.style.line_mark.stroke.width == 0.0
        # Points remain visible — not zeroed by the companion block
        assert resolved.style.point_mark.size > 0.0

    def test_fallback_when_no_data(self) -> None:
        """When data is empty, fallback to theme literal (no crash)."""
        chart, _, w = _line_chart(0, width=600.0)
        resolved = resolve(chart, [], chart_style_context=_BOARD_STYLE, width=w)
        # Should not raise; stroke should be the theme literal (positive)
        assert resolved.style.line_mark.stroke.width > 0.0

    def test_fallback_when_no_width(self) -> None:
        """Width of 0 cannot determine px_per_point; falls back to theme literal."""
        chart, data, _ = _line_chart(20, width=0.0)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=0.0)
        assert resolved.style.line_mark.stroke.width > 0.0


# ---------------------------------------------------------------------------
# Resolve-level tests: area chart baked stroke
# ---------------------------------------------------------------------------


class TestAreaChartAdaptiveStroke:
    def test_monotonic_nonincreasing_as_n_rises(self) -> None:
        """Same monotonicity contract as line."""
        strokes = [_resolved_area_stroke(n, width=600.0) for n in [5, 20, 100]]
        for a, b in zip(strokes, strokes[1:], strict=False):
            assert a >= b

    def test_author_pin_area_stroke_bypasses_adaptive(self) -> None:
        """Explicit area line stroke → verbatim, no adaptive override."""
        pinned = 1.0
        chart, data, w = _area_chart(50, width=600.0, stroke_width=pinned)
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        assert resolved.style.line_mark.stroke.width == pinned


class TestStreamgraphStrokeCap:
    """Stacked/streamgraph edges are band separators: never thicker, can thin."""

    @staticmethod
    def _stream_stroke(n_cats: int, width: float, stack: str | None) -> float:
        # Categorical x so stacked/streamgraph validation accepts it (a numeric
        # x with high cardinality is rejected as continuous). Two series stacked.
        chart_dict: dict[str, Any] = {
            "id": "t",
            "type": "area",
            "x": "x",
            "y": "y",
            "color": "series",
            "query": _QUERY,
            "query_name": "q",
        }
        if stack is not None:
            chart_dict["style"] = {"stack": stack}
        chart = TypeAdapter(Chart).validate_python(chart_dict)
        data = [
            {"x": f"c{i}", "y": float(i + 1), "series": s}
            for s in ("A", "B")
            for i in range(n_cats)
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=width)
        return resolved.style.line_mark.stroke.width

    def test_streamgraph_edge_not_thickened(self) -> None:
        """The sparse-end rule thickens an overlap (trend-line) edge toward the
        ceiling; the streamgraph edge is capped at its fallback, so it never
        picks up that weight — the fix for the thick-separator report."""
        sparse_overlap = self._stream_stroke(5, 600.0, stack="none")
        sparse_stream = self._stream_stroke(5, 600.0, stack="center")
        assert sparse_stream < sparse_overlap

    def test_streamgraph_edge_holds_at_thin_fallback(self) -> None:
        """The stacked-area edge default is already thinner than the adaptive
        floor, so capping holds it at that thin separator weight regardless of
        density — never thickened, and it does not ride the density curve the way
        an unstacked trend edge does."""
        stream_sparse = self._stream_stroke(5, 600.0, stack="center")
        stream_dense = self._stream_stroke(300, 600.0, stack="center")
        assert stream_sparse == stream_dense


# ---------------------------------------------------------------------------
# Resolve-level tests: faceted (multiples) area chart
# ---------------------------------------------------------------------------


class TestFacetedAreaChartAdaptiveStroke:
    def test_faceted_uses_per_panel_width(self) -> None:
        """Faceted area stroke is computed from per-panel width, not full card width.

        With 2 panels and the same n x-values in each panel, the buggy path uses
        the full card width → same px/pt as a non-faceted chart → same stroke.
        The fixed path uses the per-panel width (≈ half the card width) → smaller
        px/pt → strictly thinner stroke.  50 points at 600px stays well below the
        4.0 ceiling so the two paths produce distinct values.
        """
        n = 50
        card_width = 600.0

        # Non-faceted reference: full card_width / n → some stroke value
        stroke_nonfacet = _resolved_area_stroke(n, width=card_width)

        # Faceted (2 panels, same n x-values per panel)
        chart, data, w = _area_chart(n, width=card_width, multiples_columns="facet")
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        stroke_facet = resolved.style.line_mark.stroke.width

        # Per-panel width < full card width → smaller px/pt → strictly thinner stroke.
        # A bug that uses the full card width gives the same stroke as the non-faceted
        # path; the fix shrinks it to the per-panel value.
        assert stroke_facet < stroke_nonfacet


# ---------------------------------------------------------------------------
# Resolve-level tests: faceted (multiples) line chart
# ---------------------------------------------------------------------------


class TestFacetedLineChartAdaptiveStroke:
    def test_faceted_uses_per_cell_width(self) -> None:
        """Faceted stroke is computed from per-cell width, not full card width."""
        n = 10
        card_width = 600.0

        # Non-faceted: uses full card_width / n → wider per-point → thicker stroke
        stroke_nonfacet = _resolved_line_stroke(n, width=card_width)

        # Faceted (2 panels): per-cell width is narrower → adaptive sees less px/pt
        chart, data, w = _line_chart(n, width=card_width, multiples_columns="facet")
        resolved_facet = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        stroke_facet = resolved_facet.style.line_mark.stroke.width

        # Narrower panel → smaller px/pt → thinner or equal stroke
        assert stroke_facet <= stroke_nonfacet

    def test_faceted_stroke_matches_helper(self) -> None:
        """Faceted baked stroke agrees with facet_panel_width + adaptive_stroke."""
        n_dense = 10  # densest panel has 10 pts; other has 10 too (same data)
        card_width = 600.0

        chart, data, w = _line_chart(
            n_dense, width=card_width, multiples_columns="facet"
        )
        resolved_facet = resolve(chart, data, chart_style_context=_BOARD_STYLE, width=w)
        stroke_facet = resolved_facet.style.line_mark.stroke.width

        # 2 panels, no mirror (single column field, no mirror auto-set for columns-only
        # when chart has shared scale — but default is columns + shared scale → auto-mirror
        # may fire. Check the resolved ay.mirror to know has_mirror.)
        # We check against the formula for 2 panels, both mirror and no-mirror cases.
        panel_w_no_mirror = facet_panel_width(card_width, 2, has_mirror=False)
        panel_w_mirror = facet_panel_width(card_width, 2, has_mirror=True)
        expected_no_mirror = adaptive_stroke(
            panel_w_no_mirror / n_dense, _MIN_W, _MAX_W
        )
        expected_mirror = adaptive_stroke(panel_w_mirror / n_dense, _MIN_W, _MAX_W)

        # Baked stroke must equal one of the two, depending on mirror resolution
        assert stroke_facet in (expected_no_mirror, expected_mirror)
