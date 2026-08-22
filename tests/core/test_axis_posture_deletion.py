"""Regression tests for posture system deletion and per-chart label.angle override fix.

TDD: written before the implementation. The override tests confirm that a
per-chart label.angle value reaches the compiled VL spec without posture
clobbering it. After posture deletion these tests continue to serve as
regression guards.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.style.authored import (
    AxisXStylePatch,
    BarChartStylePatch,
    DimensionLabelStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_STYLE = resolve_chart_style_context(get_theme_style())

# 4 short-label nominal values. Under D-019, nominal x flips bars to
# horizontal by default; these tests pin orientation="vertical" so they
# exercise the original posture-deletion bug (per-chart label.angle override
# clobbering on the categorical x-axis), not orientation routing.
_DATA = [{"x_field": f"C{i}", "y_field": i} for i in range(4)]


class TestPerChartLabelAngleOverrideBug:
    """The per-chart label.angle override must survive into the VL spec.

    Previously, get_smart_x_axis_config stamped a posture-selected angle at
    encoding level, beating any chart-cascaded axis_x.labels.angle. With posture
    deleted, only the cascade (author/theme) drives labelAngle.
    """

    def test_label_angle_authored_at_chart_level_wins(self, make_chart):
        """A per-chart style.axis_x.labels.angle:0 must produce labelAngle:0 in the
        compiled VL spec — not a posture-selected tilt.
        """
        chart = make_chart(
            "bar",
            style=BarChartStylePatch(
                orientation="vertical",
                axis_x=AxisXStylePatch(
                    labels=DimensionLabelStylePatch(angle=0),
                ),
            ),
        )
        _rc = resolve(chart, _DATA, chart_style_context=_BOARD_STYLE)
        spec = generate_vega_lite_spec(chart, _DATA)
        x_axis = spec["encoding"]["x"].get("axis", {})
        assert x_axis.get("labelAngle") == 0, (
            f"Expected labelAngle=0 from per-chart label.angle override; "
            f"got {x_axis.get('labelAngle')} — posture may still be clobbering it"
        )

    def test_label_angle_authored_at_chart_level_minus45(self, make_chart):
        """A per-chart style.axis_x.labels.angle:-45 wins over any engine default."""
        chart = make_chart(
            "bar",
            style=BarChartStylePatch(
                orientation="vertical",
                axis_x=AxisXStylePatch(
                    labels=DimensionLabelStylePatch(angle=-45),
                ),
            ),
        )
        _rc = resolve(chart, _DATA, chart_style_context=_BOARD_STYLE)
        spec = generate_vega_lite_spec(chart, _DATA)
        x_axis = spec["encoding"]["x"].get("axis", {})
        assert x_axis.get("labelAngle") == -45, (
            f"Expected labelAngle=-45; got {x_axis.get('labelAngle')}"
        )

    def test_smart_picker_stamps_angle_zero_for_short_labels(self, make_chart):
        """Without an authored angle, the m4 smart picker stamps labelAngle=0
        explicitly on short labels.

        Previously this asserted that no labelAngle reaches the spec at all
        (the post-posture-deletion, pre-m4 contract). D-021 reverses that:
        VL's adaptive ordinal default rotates labels to vertical when they
        would collide, even with labelOverlap='allow', so the picker stamps
        the chosen angle (including 0) explicitly to pin it.
        """
        chart = make_chart(
            "bar",
            style=BarChartStylePatch(orientation="vertical"),
        )
        _rc = resolve(chart, _DATA, chart_style_context=_BOARD_STYLE)
        spec = generate_vega_lite_spec(chart, _DATA)
        x_axis = spec["encoding"]["x"].get("axis", {})
        assert x_axis.get("labelAngle") == 0, (
            f"Expected labelAngle=0 from the smart picker on short labels; "
            f"got {x_axis.get('labelAngle')}"
        )
