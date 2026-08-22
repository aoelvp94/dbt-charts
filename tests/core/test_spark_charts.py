"""Unit tests for spark chart SVG generation.

Tests the spark chart rendering functions in dbt-charts/render/spark.py.
"""

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve.style.board import resolve_style
from dbt_charts.core.render.chart.spark import (
    render_spark,
    render_spark_area,
    render_spark_bar,
    render_spark_column,
    render_spark_columns,
    render_spark_line,
)

# Resolve against `stark` so the threshold test below can pin the
# theme-accent fallback color (stark uses dbt-grays.accent #3b82f6). The
# shipped editorial `default` overrides the accent and would emit a
# different fallback colour.
_EFF = resolve_style(get_theme_style("stark")).chart_defaults


class TestSparkLineBasic:
    """Tests for basic line sparkline rendering."""

    def test_spark_line_basic(self) -> None:
        """Simple array renders correctly."""
        values = [10, 20, 15, 30, 25]
        svg = render_spark_line(values, resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg
        assert "<polyline" in svg
        assert "points=" in svg

    def test_spark_line_with_dimensions(self) -> None:
        """Custom dimensions are applied."""
        values = [10, 20, 15, 30, 25]
        svg = render_spark_line(values, width=100, height=30, resolved_style=_EFF)

        assert 'width="100"' in svg
        assert 'height="30"' in svg

    def test_spark_line_with_color(self) -> None:
        """Custom color is applied."""
        values = [10, 20, 15, 30, 25]
        svg = render_spark_line(values, color="#ff0000", resolved_style=_EFF)

        assert 'stroke="#ff0000"' in svg


class TestSparkLineEmpty:
    """Tests for empty/edge case handling."""

    def test_spark_line_empty(self) -> None:
        """Empty array handled gracefully."""
        svg = render_spark_line([], resolved_style=_EFF)

        assert svg.startswith("<svg")
        # Should render a placeholder dashed line
        assert "stroke-dasharray" in svg

    def test_spark_line_none(self) -> None:
        """None values handled gracefully."""
        svg = render_spark(None, "line", resolved_style=_EFF)

        assert svg.startswith("<svg")


class TestSparkLineSingleValue:
    """Tests for single value edge case."""

    def test_spark_line_single_value(self) -> None:
        """Single value edge case renders horizontal line with dot."""
        svg = render_spark_line([42], resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert "<line" in svg
        assert "<circle" in svg


class TestSparkLineWithOptions:
    """Tests for line sparkline options."""

    def test_spark_line_last_visible(self) -> None:
        """last_visible option adds dot on last value."""
        values = [10, 20, 15, 30, 25]
        svg = render_spark_line(values, last_visible=True, resolved_style=_EFF)

        assert "<circle" in svg

    def test_spark_line_min_max_visible(self) -> None:
        """min_max_visible option adds dots on min/max values."""
        values = [10, 20, 5, 30, 25]  # min=5, max=30
        svg = render_spark_line(values, min_max_visible=True, resolved_style=_EFF)

        # Should have circles for min and max
        assert svg.count("<circle") >= 2


class TestSparkBarNormalizeBasic:
    """Tests for `bar-normalize` (single bar with background track) rendering."""

    def test_spark_bar_normalize_basic(self) -> None:
        """Percentage renders with background track + fill."""
        svg = render_spark_bar(75, normalize=True, resolved_style=_EFF)

        assert svg.startswith("<svg")
        # background + fill = 2 rects
        assert svg.count("<rect") == 2

    def test_spark_bar_normalize_zero(self) -> None:
        """Zero value renders background only."""
        svg = render_spark_bar(0, normalize=True, resolved_style=_EFF)

        assert svg.startswith("<svg")
        # Only background rect (fill width is 0)
        assert "<rect" in svg

    def test_spark_bar_normalize_full(self) -> None:
        """100% value renders full bar."""
        svg = render_spark_bar(100, normalize=True, resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert svg.count("<rect") == 2


class TestSparkBarThresholds:
    """Tests for `bar-normalize` threshold colors."""

    def test_spark_bar_thresholds(self) -> None:
        """Color changes at thresholds; below the lowest threshold the bar
        falls back to the theme's single-series ink (the resolved
        spark.bar.color, which the cascade fills from single_series_palette[0])."""
        thresholds = {30: "#ff0000", 70: "#ffff00", 90: "#00ff00"}
        default_color = _EFF.spark.bar.color
        assert default_color is not None

        svg_low = render_spark_bar(
            25, normalize=True, thresholds=thresholds, resolved_style=_EFF
        )
        assert default_color in svg_low

        svg_mid = render_spark_bar(
            75, normalize=True, thresholds=thresholds, resolved_style=_EFF
        )
        assert "#ffff00" in svg_mid

        svg_high = render_spark_bar(
            95, normalize=True, thresholds=thresholds, resolved_style=_EFF
        )
        assert "#00ff00" in svg_high


class TestSparkBarOverMax:
    """Tests for bar capping behavior."""

    def test_spark_bar_normalize_over_max(self) -> None:
        """Value over max caps at 100%."""
        svg = render_spark_bar(
            150, max_value=100, width=100, normalize=True, resolved_style=_EFF
        )

        assert svg.startswith("<svg")
        # Fill width should equal total width (capped)
        assert 'width="100.0"' in svg or 'width="100"' in svg

    def test_spark_bar_normalize_custom_max(self) -> None:
        """Custom max value works correctly."""
        svg = render_spark_bar(
            50, max_value=200, width=100, normalize=True, resolved_style=_EFF
        )

        # 50/200 = 25% of width = 25px
        assert 'width="25.0"' in svg


class TestSparkArea:
    """Tests for area sparkline rendering."""

    def test_spark_area_basic(self) -> None:
        """Area sparkline renders with polygon and polyline."""
        values = [10, 20, 15, 30, 25]
        svg = render_spark_area(values, resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert "<polygon" in svg
        assert "<polyline" in svg

    def test_spark_area_fill_opacity(self) -> None:
        """Custom fill opacity is applied."""
        values = [10, 20, 15, 30, 25]
        svg = render_spark_area(values, fill_opacity=0.5, resolved_style=_EFF)

        assert 'fill-opacity="0.5"' in svg


class TestSparkColumns:
    """Tests for the `columns` (multi-value vertical bars) variant."""

    def test_spark_columns_basic(self) -> None:
        """columns sparkline renders correctly."""
        values = [10, 20, 15, 30, 25]
        svg = render_spark_columns(values, resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert svg.count("<rect") == 5  # One bar per value

    def test_spark_columns_single_value(self) -> None:
        """Single value renders one bar."""
        svg = render_spark_columns([42], resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert svg.count("<rect") == 1


class TestSparkColumn:
    """Tests for `column` (single vertical bar, bottom-anchored) rendering."""

    def test_spark_column_basic(self) -> None:
        """Scalar value renders one rect, no background track."""
        svg = render_spark_column(75, resolved_style=_EFF)

        assert svg.startswith("<svg")
        # column = no background track, single fill rect
        assert svg.count("<rect") == 1

    def test_spark_column_bottom_anchored(self) -> None:
        """Rect grows from the bottom upward — y + height equals total svg height."""
        # 50/100 = 50% of 40 = 20px tall, y = 40 - 20 = 20
        svg = render_spark_column(
            50, max_value=100, width=20, height=40, resolved_style=_EFF
        )
        assert 'y="20.0"' in svg
        assert 'height="20.0"' in svg

    def test_spark_column_zero_renders_no_fill(self) -> None:
        """Zero value renders no fill rect."""
        svg = render_spark_column(0, max_value=100, resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert svg.count("<rect") == 0

    def test_spark_column_over_max_caps(self) -> None:
        """Value over max caps at full height."""
        svg = render_spark_column(
            150, max_value=100, width=20, height=40, resolved_style=_EFF
        )

        # Full height, anchored at top of cell (y=0)
        assert 'height="40.0"' in svg
        assert 'y="0.0"' in svg

    def test_spark_column_with_color(self) -> None:
        """Custom color is applied."""
        svg = render_spark_column(50, color="#ff0000", resolved_style=_EFF)

        assert 'fill="#ff0000"' in svg


class TestRenderSpark:
    """Tests for the main render_spark dispatcher."""

    def test_render_spark_line(self) -> None:
        """Dispatcher routes to line correctly."""
        svg = render_spark([10, 20, 30], "line", resolved_style=_EFF)

        assert "<polyline" in svg

    def test_render_spark_area(self) -> None:
        """Dispatcher routes to area correctly."""
        svg = render_spark([10, 20, 30], "area", resolved_style=_EFF)

        assert "<polygon" in svg

    def test_render_spark_columns(self) -> None:
        """Dispatcher routes to columns correctly."""
        svg = render_spark([10, 20, 30], "columns", resolved_style=_EFF)

        assert svg.count("<rect") == 3

    def test_render_spark_bar(self) -> None:
        """Dispatcher routes to bar (no track) correctly."""
        svg = render_spark(75, "bar", resolved_style=_EFF)

        # bar = no background track, single fill rect
        assert svg.count("<rect") == 1

    def test_render_spark_bar_normalize(self) -> None:
        """Dispatcher routes to bar-normalize (with track) correctly."""
        svg = render_spark(75, "bar-normalize", resolved_style=_EFF)

        # bar-normalize = background track + fill rect
        assert svg.count("<rect") == 2

    def test_render_spark_column(self) -> None:
        """Dispatcher routes to column (no track) correctly."""
        svg = render_spark(75, "column", resolved_style=_EFF)

        # column = no background track, single fill rect
        assert svg.count("<rect") == 1

    def test_render_spark_unknown_type(self) -> None:
        """Unknown type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown spark type"):
            render_spark([10, 20, 30], "unknown", resolved_style=_EFF)

    def test_render_spark_with_options(self) -> None:
        """Options are passed through correctly."""
        svg = render_spark(
            [10, 20, 30],
            "line",
            color="#ff0000",
            last_visible=True,
            resolved_style=_EFF,
        )

        assert 'stroke="#ff0000"' in svg
        assert "<circle" in svg


class TestSparkDataTypes:
    """Tests for handling various data types."""

    def test_spark_line_float_values(self) -> None:
        """Float values work correctly."""
        values = [1.5, 2.7, 3.2, 4.8]
        svg = render_spark_line(values, resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert "<polyline" in svg

    def test_spark_bar_float_value(self) -> None:
        """Float bar value works correctly."""
        svg = render_spark_bar(75.5, normalize=True, resolved_style=_EFF)

        assert svg.startswith("<svg")

    def test_spark_with_negative_values(self) -> None:
        """Negative values are handled (scaled correctly)."""
        values = [-10, -5, 0, 5, 10]
        svg = render_spark_line(values, resolved_style=_EFF)

        assert svg.startswith("<svg")
        assert "<polyline" in svg

    def test_spark_bar_with_array_input(self) -> None:
        """bar/bar-normalize accept array (uses first value)."""
        svg = render_spark([75, 80, 85], "bar-normalize", resolved_style=_EFF)

        assert svg.startswith("<svg")


class TestSparkColorResolution:
    """Tests for `_resolve_spark_color` — the color-cascade contract.

    The anti-slop contract: if neither the caller nor the theme resolves a
    color, we refuse to render (raise) instead of silently emitting SVG with
    no fill. This test guards that invariant so a future "clever" default
    doesn't sneak in.
    """

    def test_raises_when_neither_caller_nor_theme_sets_color(self) -> None:
        """Both color=None and spark_cfg.color=None must raise ValueError."""
        from dbt_charts.core.compile.config import (
            get_theme_style,
        )
        from dbt_charts.core.render.chart.spark import _resolve_spark_color

        eff = resolve_style(get_theme_style()).chart_defaults
        spark_cfg = eff.spark.model_copy(update={"color": None})

        with pytest.raises(ValueError, match="spark color is unset"):
            _resolve_spark_color(None, spark_cfg)

    def test_prefers_call_site_color_over_theme(self) -> None:
        """Call-site color wins over whatever the theme set."""
        from dbt_charts.core.compile.config import (
            get_theme_style,
        )
        from dbt_charts.core.render.chart.spark import _resolve_spark_color

        eff = resolve_style(get_theme_style()).chart_defaults
        spark_cfg = eff.spark.model_copy(update={"color": "#000000"})

        resolved = _resolve_spark_color("#ff0000", spark_cfg)
        assert resolved == "#ff0000"

    def test_falls_back_to_theme_color_when_caller_unset(self) -> None:
        """If the caller passes None, spark_cfg.color is used."""
        from dbt_charts.core.compile.config import (
            get_theme_style,
        )
        from dbt_charts.core.render.chart.spark import _resolve_spark_color

        eff = resolve_style(get_theme_style()).chart_defaults
        spark_cfg = eff.spark.model_copy(update={"color": "#00ff00"})

        resolved = _resolve_spark_color(None, spark_cfg)
        assert resolved == "#00ff00"
