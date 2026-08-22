"""Tests for scale.zero: auto sentinel and theme-wired zero inference.

Replaces test_inference_via_style.py's zero-gate tests. The inference flags
(infer_zero_when_missing, infer_fields_when_missing) are gone; behavior is now
driven by axis_y.scale.continuous.zero: auto|bool|null in board/theme style.
"""

from __future__ import annotations

import dataclasses

from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.style.authored import (
    AxisYStylePatch,
    BarChartStylePatch,
    LineChartStylePatch,
)
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.resolved import ResolvedStyle
from dbt_charts.core.compile.models.style.theme import (
    ScaleContinuousStyle,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec


def _default_board() -> tuple[ResolvedStyle, ChartStyleContext]:
    return resolve_style_and_context(get_theme_style())


def _chart(
    type: str = "bar",
    x: str | None = None,
    y: str | None = None,
    style: BarChartStylePatch | LineChartStylePatch | None = None,
) -> Chart:
    return TypeAdapter(Chart).validate_python(
        {"id": "test", "type": type, "x": x, "y": y, "style": style}
    )


def _bar_style(zero: bool | str | None) -> BarChartStylePatch:
    """Return a BarChartStylePatch with axis_y.scale.continuous.zero set to the given value."""
    return BarChartStylePatch.model_validate(
        {"axis_y": {"scale": {"continuous": {"zero": zero}}}}
    )


def _line_style(zero: bool | str | None) -> LineChartStylePatch:
    """Return a LineChartStylePatch with axis_y.scale.continuous.zero set to the given value."""
    return LineChartStylePatch.model_validate(
        {"axis_y": {"scale": {"continuous": {"zero": zero}}}}
    )


# Data whose narrow range triggers smart-zero=False on line/scatter charts
# (min/max ratio > _ZERO_EXTEND_THRESHOLD=0.25).
NARROW_RANGE_DATA = [
    {"month": "Jan", "csat": 88},
    {"month": "Feb", "csat": 92},
    {"month": "Mar", "csat": 96},
]

# Data that triggers smart-zero=True on bar (always-zero chart type with positive data).
ALL_POSITIVE_DATA = [
    {"category": "A", "revenue": 1_200_000},
    {"category": "B", "revenue": 1_400_000},
]


def _bar_spec_y_scale_zero(
    chart: Chart,
    data: list[dict],
    board_rs: ResolvedStyle,
    board_ctx: ChartStyleContext,
) -> object:
    """Return the VL scale zero value for the quantitative encoding of a bar chart.

    Searches both x and y so horizontal bars (value axis on x) are handled.
    """
    spec = generate_vega_lite_spec(
        chart, data, board_style=board_rs, chart_style_context=board_ctx
    )
    for key in ("x", "y"):
        enc = spec.get("encoding", {}).get(key, {})
        if enc.get("type") == "quantitative":
            return enc.get("scale", {}).get("zero")
    return None


def _line_resolved_zero(
    chart: Chart, data: list[dict], board_ctx: ChartStyleContext
) -> object:
    """Return the resolved axis_y.scale.continuous.zero for a line chart."""
    resolved = resolve(chart, data, chart_style_context=board_ctx)
    scale = resolved.style.axis_y.scale
    if scale is None or scale.continuous is None:
        return None
    return scale.continuous.zero


class TestScaleZeroType:
    """ScaleContinuousStyle.zero accepts bool | 'auto' | None."""

    def test_scale_style_accepts_auto_sentinel(self) -> None:
        scale = ScaleContinuousStyle.model_validate({"zero": "auto"})
        assert scale.zero == "auto"

    def test_scale_style_accepts_bool_true(self) -> None:
        scale = ScaleContinuousStyle(zero=True)
        assert scale.zero is True

    def test_scale_style_accepts_bool_false(self) -> None:
        scale = ScaleContinuousStyle(zero=False)
        assert scale.zero is False

    def test_scale_style_accepts_none(self) -> None:
        scale = ScaleContinuousStyle(zero=None)
        assert scale.zero is None


class TestZeroAutoSentinelBehavior:
    """scale.zero: auto triggers the smart zero-picker (same as not authoring zero)."""

    def test_no_authored_zero_triggers_picker_for_bar(self) -> None:
        """Bar with positive data: picker always emits zero=True."""
        board_rs, board_ctx = _default_board()
        zero = _bar_spec_y_scale_zero(
            _chart(x="category", y="revenue"),
            ALL_POSITIVE_DATA,
            board_rs,
            board_ctx,
        )
        assert zero is True

    def test_explicit_auto_triggers_picker_same_as_no_authored(self) -> None:
        """Explicit scale.zero: auto behaves identically to not authoring zero."""
        board_rs, board_ctx = _default_board()
        zero = _bar_spec_y_scale_zero(
            _chart(x="category", y="revenue", style=_bar_style("auto")),
            ALL_POSITIVE_DATA,
            board_rs,
            board_ctx,
        )
        assert zero is True

    def test_narrow_range_no_authored_zero_triggers_picker_on_line(self) -> None:
        """Line chart with narrow range: picker emits zero=False."""
        _, board_ctx = _default_board()
        zero = _line_resolved_zero(
            _chart(type="line", x="month", y="csat"),
            NARROW_RANGE_DATA,
            board_ctx,
        )
        assert zero is False

    def test_narrow_range_explicit_auto_triggers_picker_on_line(self) -> None:
        """Explicit auto on line chart still defers to the picker."""
        _, board_ctx = _default_board()
        zero = _line_resolved_zero(
            _chart(type="line", x="month", y="csat", style=_line_style("auto")),
            NARROW_RANGE_DATA,
            board_ctx,
        )
        assert zero is False


class TestZeroExplicitBoolOverride:
    """Explicit bool suppresses the picker."""

    def test_zero_false_suppresses_picker(self) -> None:
        """scale.zero: false → picker skipped; bar y-scale zero is False."""
        board_rs, board_ctx = _default_board()
        zero = _bar_spec_y_scale_zero(
            _chart(x="category", y="revenue", style=_bar_style(False)),
            ALL_POSITIVE_DATA,
            board_rs,
            board_ctx,
        )
        assert zero is False

    def test_zero_true_suppresses_picker(self) -> None:
        """scale.zero: true → picker skipped; line resolved zero is True."""
        # Line with narrow range would produce zero=False from picker; override to True.
        _, board_ctx = _default_board()
        zero = _line_resolved_zero(
            _chart(type="line", x="month", y="csat", style=_line_style(True)),
            NARROW_RANGE_DATA,
            board_ctx,
        )
        assert zero is True


class TestThemeZeroWiredUp:
    """Theme-level bar.axis_y.scale.continuous.zero is respected by the inference pipeline."""

    def _board_with_bar_zero(
        self, zero_value: bool | str | None
    ) -> tuple[ResolvedStyle, ChartStyleContext]:
        base_rs, base_ctx = _default_board()
        axis_y_override = AxisYStylePatch.model_validate(
            {"scale": {"continuous": {"zero": zero_value}}}
        )
        updated_bar = base_ctx.bar.model_copy(update={"axis_y": axis_y_override})
        updated_ctx = dataclasses.replace(base_ctx, bar=updated_bar)
        return base_rs, updated_ctx

    def test_theme_zero_false_suppresses_picker_for_bar(self) -> None:
        """When theme sets bar.axis_y.scale.continuous.zero: false, picker is skipped."""
        board_rs, board_ctx = self._board_with_bar_zero(False)
        zero = _bar_spec_y_scale_zero(
            _chart(x="category", y="revenue"),
            ALL_POSITIVE_DATA,
            board_rs,
            board_ctx,
        )
        assert zero is False

    def test_theme_zero_auto_triggers_picker_for_bar(self) -> None:
        """When theme sets bar.axis_y.scale.continuous.zero: auto, picker still runs."""
        board_rs, board_ctx = self._board_with_bar_zero("auto")
        zero = _bar_spec_y_scale_zero(
            _chart(x="category", y="revenue"),
            ALL_POSITIVE_DATA,
            board_rs,
            board_ctx,
        )
        assert zero is True

    def test_board_zero_wins_over_theme_zero(self) -> None:
        """Board-authored axis_y.scale.continuous.zero: false wins over theme's auto."""
        board_rs, board_ctx = self._board_with_bar_zero("auto")
        zero = _bar_spec_y_scale_zero(
            _chart(x="category", y="revenue", style=_bar_style(False)),
            ALL_POSITIVE_DATA,
            board_rs,
            board_ctx,
        )
        assert zero is False


class TestAuthoredFieldsRespected:
    """V2 does not infer x/y from data columns — authored fields pass through unchanged."""

    def test_authored_fields_not_overridden(self) -> None:
        """When x/y explicitly authored, resolve does not override them."""
        _, board_ctx = _default_board()
        chart = _chart(type="bar", x="category", y="revenue")
        resolved = resolve(chart, ALL_POSITIVE_DATA, chart_style_context=board_ctx)
        assert resolved.x == "category"
        assert resolved.y == "revenue"
