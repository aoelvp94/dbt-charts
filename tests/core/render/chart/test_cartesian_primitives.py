"""Tests for shared cartesian primitives in v2/emitters/_cartesian.py.

Covers the structural contract of the extracted primitives: the VLDict
typedef boundary and the named-tuple return shapes (replacing opaque
positional tuples). Vega-Lite output parity across the refactor
is covered separately by the render-v2 emitter parity suite.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
from dbt_charts.core.compile.models.chart.authored._annotations import ChartSort
from dbt_charts.core.compile.models.style.resolved._base import ResolvedAxisStyle
from dbt_charts.core.compile.resolve.chart._axes import _bake_cartesian_axes
from dbt_charts.core.compile.resolve.style.axis_cascade import (
    AxisOverrides,
    build_resolved_axis,
)
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.render.chart.emitters._cartesian import (
    CartesianXResolution,
    XYTitles,
    build_palette_config,
    build_x_enc,
    chart_sort_to_vl,
    resolve_cartesian_x,
    resolve_xy_titles,
)
from dbt_charts.core.render.chart.spec import RenderBox

from ...conftest import fixture_chart_for_type


def _axes() -> tuple[ResolvedAxisStyle, ResolvedAxisStyle]:
    chart_style_context = resolve_chart_style_context(
        get_theme_style(get_default_theme_name())
    )
    ax_merged, ay_merged, ax_band_position, ay_band_position, _, _ = (
        _bake_cartesian_axes(
            chart_style_context,
            fixture_chart_for_type("line"),
            "line",
            "temporal",
            "quantitative",
            AxisOverrides(),
        )
    )
    return (
        build_resolved_axis(
            ax_merged,
            band_position=ax_band_position,
            chart_id="test",
            format_authored=True,
            format_is_alias=False,
        ),
        build_resolved_axis(
            ay_merged,
            band_position=ay_band_position,
            chart_id="test",
            format_authored=True,
            format_is_alias=False,
        ),
    )


def test_build_palette_config_with_palette() -> None:
    assert build_palette_config(("#fff", "#000")) == {
        "range": {"category": ["#fff", "#000"]}
    }


def test_build_palette_config_without_palette() -> None:
    assert build_palette_config(None) == {}


def test_resolve_cartesian_x_returns_named_fields() -> None:
    ax, _ay = _axes()
    data = [{"date": "2025-01-01"}, {"date": "2025-02-01"}]
    result = resolve_cartesian_x(
        "date",
        data,
        ax,
        label_usable_ratio=1.0,
        chart_width=600.0,
        chart_id="c1",
        mark_type="line",
    )
    assert isinstance(result, CartesianXResolution)
    assert result.vl_type
    assert isinstance(result.axis, dict)
    assert isinstance(result.scale, dict)


def test_resolve_xy_titles_returns_named_fields() -> None:
    ax, ay = _axes()
    result = resolve_xy_titles(
        "date", "revenue", None, None, ax, ay, RenderBox(width=600.0, height=300.0), ""
    )
    assert isinstance(result, XYTitles)
    assert result.x_title == "Date"
    assert result.y_title == "Revenue"


def test_build_x_enc_uses_resolved_fields() -> None:
    enc = build_x_enc("date", "temporal", "Date", {"grid": True}, {"padding": 1})
    assert enc == {
        "field": "date",
        "type": "temporal",
        "title": "Date",
        "axis": {"grid": True},
        "sort": None,
        "scale": {"padding": 1},
    }


def test_chart_sort_to_vl_does_not_pin_op() -> None:
    """chart_sort_to_vl stays unopinionated about VL's own sort ``op`` default.

    It's a shared helper: bar's grouped-vertical x-sort sometimes sits beside
    an unstacked ``y.stack: null`` (which flips VL's inferred default from
    ``sum`` to ``min``), but scatter's categorical-y sort never carries a
    stack concept at all. Pinning ``op`` here to solve bar's problem would
    silently change scatter's VL-inferred default too — the fix belongs at
    the point that actually needs it (bar suppressing ``y.stack`` only when
    the x scale is genuinely continuous), not in this shared mapper.
    """
    vl_sort = chart_sort_to_vl(ChartSort(by="val", order="desc"))
    assert vl_sort == {"field": "val", "order": "descending"}, (
        f"chart_sort_to_vl must not add an 'op' key, got {vl_sort!r}"
    )
