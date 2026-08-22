"""Tests for type-driven auto bar-orientation (D-019).

Auto-pick rule: bar orientation is driven by x-axis field *type*, not by
viewport fit. Discrete x (categorical/nominal) → horizontal bars; continuous
x (temporal, quantitative, date-like ordinal) → vertical bars. Author
override (`style.orientation`) always wins.

Same `_is_discrete_axis` helper that drives the smart-tilt resolver also
drives bar-flip — one canonical "is this discrete?" question across the
chart pipeline.
"""

from __future__ import annotations

import datetime

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    Chart,
    LineChart,
)
from dbt_charts.core.compile.models.style.authored import (
    AxisXStylePatch,
    BarChartStylePatch,
    ChartStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

_BOARD_STYLE = resolve_chart_style_context(get_theme_style())

LONG_LABEL_DATA = [
    {"state": state, "revenue": i * 100}
    for i, state in enumerate(
        [
            "California",
            "North Carolina",
            "South Carolina",
            "West Virginia",
            "New Hampshire",
            "Massachusetts",
            "Pennsylvania",
            "Connecticut",
            "Mississippi",
            "Washington",
        ],
        start=1,
    )
]

SHORT_LABEL_DATA = [
    {"category": c, "value": i * 10}
    for i, c in enumerate(["A", "B", "C", "D", "E"], start=1)
]

TEMPORAL_DATA = [
    {
        "month": datetime.date(2023, 1, 1) + datetime.timedelta(days=30 * i),
        "revenue": i * 100,
    }
    for i in range(20)
]

QUANTITATIVE_DATA = [{"bucket": float(i), "count": i * 5} for i in range(1, 21)]


def _bar(x: str, y: str, style: ChartStylePatch | None = None) -> Chart:
    return BarChart(id="test_bar", type="bar", x=x, y=y, style=style)


class TestNominalXFlipsHorizontal:
    """D-019: any nominal x on a bar → horizontal, regardless of label length."""

    def test_long_nominal_labels_flip_horizontal(self):
        resolved = resolve(
            _bar("state", "revenue"),
            LONG_LABEL_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation == "horizontal"

    def test_short_nominal_labels_flip_horizontal(self):
        """D-019 change: short categoricals also flip. Author can pin vertical."""
        resolved = resolve(
            _bar("category", "value"),
            SHORT_LABEL_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation == "horizontal"


class TestContinuousXStaysVertical:
    """Temporal, quantitative, and date-like ordinal x → vertical."""

    def test_temporal_x_stays_vertical(self):
        resolved = resolve(
            _bar("month", "revenue"),
            TEMPORAL_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation == "vertical"

    def test_quantitative_x_stays_vertical(self):
        resolved = resolve(
            _bar("bucket", "count"),
            QUANTITATIVE_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation == "vertical"

    def test_quarter_year_strings_stay_vertical(self):
        """28 'Q1 2018'..'Q4 2024' labels are ordinal (date-like) → vertical."""
        rows = [
            {"m": f"Q{q} {y}", "v": 1} for y in range(2018, 2025) for q in range(1, 5)
        ]
        resolved = resolve(_bar("m", "v"), rows, chart_style_context=_BOARD_STYLE)
        assert resolved.orientation == "vertical"

    def test_month_year_strings_stay_vertical(self):
        """36 'Jan 2020'..'Dec 2022' labels are ordinal (date-like) → vertical."""
        import calendar

        rows = [
            {"m": f"{calendar.month_abbr[mo]} {yr}", "v": 1}
            for yr in range(2020, 2023)
            for mo in range(1, 13)
        ]
        resolved = resolve(_bar("m", "v"), rows, chart_style_context=_BOARD_STYLE)
        assert resolved.orientation == "vertical"


class TestTimeUnitOverridesNominalType:
    """time_unit forces continuous classification → vertical."""

    def test_nominal_x_with_time_unit_stays_vertical(self):
        """Month names with time_unit=monthofyear are cyclical-temporal → vertical."""
        chart = _bar(
            "month",
            "value",
            BarChartStylePatch(
                axis_x=AxisXStylePatch.model_validate({"time_unit": "monthofyear"})
            ),
        )
        data = [
            {"month": m, "value": i} for i, m in enumerate(["Jan", "Feb", "Mar", "Apr"])
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        assert resolved.orientation == "vertical"


class TestAuthorOverrideWins:
    """Authored style.orientation always overrides the type-driven rule."""

    def test_explicit_vertical_pins_categorical_to_vertical(self):
        """Categorical x would flip horizontal — author pin keeps it vertical."""
        resolved = resolve(
            _bar(
                "state",
                "revenue",
                BarChartStylePatch(orientation="vertical"),
            ),
            LONG_LABEL_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation == "vertical"

    def test_explicit_horizontal_pins_temporal_to_horizontal(self):
        """Temporal x would stay vertical — author pin flips to horizontal."""
        resolved = resolve(
            _bar(
                "month",
                "revenue",
                BarChartStylePatch(orientation="horizontal"),
            ),
            TEMPORAL_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation == "horizontal"


class TestNonBarStaysVertical:
    """Auto-flip is bar-only — line/area never flip."""

    def test_line_chart_with_nominal_x_stays_vertical(self):
        from dbt_charts.core.compile.models.chart.resolved.line import ResolvedLineChart

        chart = LineChart(id="t", type="line", x="state", y="revenue")
        resolved = resolve(chart, LONG_LABEL_DATA, chart_style_context=_BOARD_STYLE)
        # Line charts don't have an orientation attribute — resolve returns a
        # ResolvedLineChart, not a bar. Asserting the type is sufficient.
        assert isinstance(resolved, ResolvedLineChart)

    def test_area_chart_with_nominal_x_stays_vertical(self):
        from dbt_charts.core.compile.models.chart.resolved.area import ResolvedAreaChart

        chart = AreaChart(id="t", type="area", x="state", y="revenue")
        resolved = resolve(chart, LONG_LABEL_DATA, chart_style_context=_BOARD_STYLE)
        assert isinstance(resolved, ResolvedAreaChart)


class TestDegenerateInputsStayVertical:
    """Empty data or missing x_field → can't classify → vertical or unresolved (None)."""

    def test_empty_data_stays_vertical(self):
        resolved = resolve(
            _bar("state", "revenue"), [], chart_style_context=_BOARD_STYLE
        )
        # V2 resolver may return None for orientation when data is empty.
        assert resolved.orientation in ("vertical", None)

    def test_missing_x_field_stays_vertical(self):
        data = [{"other_field": "x", "revenue": 100}]
        resolved = resolve(
            _bar("state", "revenue"), data, chart_style_context=_BOARD_STYLE
        )
        assert resolved.orientation in ("vertical", None)


class TestOrientationNeverLeaksAuto:
    """ResolvedChart.orientation is always concrete — never 'auto'."""

    def test_resolved_orientation_is_concrete(self):
        resolved = resolve(
            _bar("state", "revenue"),
            LONG_LABEL_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation in ("vertical", "horizontal")

    def test_explicit_auto_resolves_concrete(self):
        resolved = resolve(
            _bar(
                "state",
                "revenue",
                BarChartStylePatch(orientation="auto"),
            ),
            LONG_LABEL_DATA,
            chart_style_context=_BOARD_STYLE,
        )
        assert resolved.orientation in ("vertical", "horizontal")
