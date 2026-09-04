"""Unit tests for spark chart SVG generation.

Tests the spark chart rendering functions in dbt-charts/render/spark.py.
"""

import re

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve.style.board import resolve_style
from dbt_charts.core.render.chart.spark import (
    _SPARK_HEIGHT,
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

    def test_spark_bar_threshold_exact_value_with_non_round_max(self) -> None:
        """A value exactly at its threshold still hits the threshold color
        under a non-round max_value. The threshold clamp must compare the
        raw value, not a value/max*max round trip — that division and
        remultiplication is not an IEEE-754 identity, and can undershoot the
        threshold by a ULP for non-round max_value/value pairs (e.g. 15/22)."""
        svg = render_spark_bar(
            15,
            max_value=22,
            normalize=True,
            thresholds={15: "#ff0000"},
            resolved_style=_EFF,
        )
        assert "#ff0000" in svg

    def test_spark_column_threshold_exact_value_with_non_round_max(self) -> None:
        """Same round-trip hazard as the bar variant, for `column`'s
        threshold clamp."""
        svg = render_spark_column(
            15,
            max_value=22,
            thresholds={15: "#ff0000"},
            resolved_style=_EFF,
        )
        assert "#ff0000" in svg


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


def _rects(svg: str) -> list[dict[str, float]]:
    """Parse every `<rect .../>` in an SVG into a dict of its numeric attrs."""
    out: list[dict[str, float]] = []
    for tag in re.findall(r"<rect[^/]*/>", svg):
        attrs = dict(re.findall(r'(\w+)="([-\d.]+)"', tag))
        out.append({k: float(v) for k, v in attrs.items()})
    return out


class TestSparkBarSigned:
    """`render_spark_bar` midline layout — positives right, negatives left."""

    def test_default_has_negative_false_matches_legacy_clamp(self) -> None:
        """Without has_negative, a negative value still clamps to nothing —
        the pre-existing behavior for callers that never opt in."""
        svg = render_spark_bar(-30, max_value=100, width=100, resolved_style=_EFF)
        assert _rects(svg) == []

    def test_positive_only_bar_unaffected_by_signed_support(self) -> None:
        """has_negative=False (the default) reproduces the exact pre-fix
        geometry for an ordinary all-positive bar: fill starts at the left
        edge, not the midline."""
        svg = render_spark_bar(50, max_value=100, width=100, resolved_style=_EFF)
        rects = _rects(svg)
        assert len(rects) == 1
        assert rects[0]["x"] == 0.0
        assert rects[0]["width"] == 50.0

    def test_negative_value_grows_left_from_midline(self) -> None:
        svg = render_spark_bar(
            -30, max_value=100, width=100, has_negative=True, resolved_style=_EFF
        )
        rects = _rects(svg)
        assert len(rects) == 1
        # 30% of the half-width (50px) = 15px, anchored so it ends at the midline.
        assert rects[0]["width"] == pytest.approx(15.0)
        assert rects[0]["x"] == pytest.approx(35.0)

    def test_positive_value_grows_right_from_midline(self) -> None:
        svg = render_spark_bar(
            30, max_value=100, width=100, has_negative=True, resolved_style=_EFF
        )
        rects = _rects(svg)
        assert len(rects) == 1
        assert rects[0]["width"] == pytest.approx(15.0)
        assert rects[0]["x"] == pytest.approx(50.0)

    def test_midline_halves_extent_for_the_largest_magnitude(self) -> None:
        """At the ceiling value, a signed bar reaches only the half-width —
        proving the anchor moved rather than the scale silently doubling."""
        svg = render_spark_bar(
            100, max_value=100, width=100, has_negative=True, resolved_style=_EFF
        )
        rects = _rects(svg)
        assert rects[0]["width"] == pytest.approx(50.0)

    def test_no_midline_rule_is_drawn(self) -> None:
        """No visible rule at the midline — only the fill rect(s)."""
        svg = render_spark_bar(
            -30, max_value=100, width=100, has_negative=True, resolved_style=_EFF
        )
        assert "<line" not in svg

    def test_negative_color_opt_in_uses_theme_negative_token(self) -> None:
        """negative_color=True paints negative bars with resolved_style.tones.negative
        — asserted by identity with the resolved token, never a hardcoded hex."""
        svg = render_spark_bar(
            -30,
            max_value=100,
            width=100,
            has_negative=True,
            negative_color=True,
            resolved_style=_EFF,
        )
        assert _EFF.tones.negative in svg

    def test_negative_color_default_off_keeps_one_color(self) -> None:
        """Without opting in, negative and positive bars share the same fill —
        one colour by default."""
        svg_neg = render_spark_bar(
            -30, max_value=100, width=100, has_negative=True, resolved_style=_EFF
        )
        svg_pos = render_spark_bar(
            30, max_value=100, width=100, has_negative=True, resolved_style=_EFF
        )
        neg_fill = re.search(r'fill="([^"]+)"', svg_neg)
        pos_fill = re.search(r'fill="([^"]+)"', svg_pos)
        assert neg_fill is not None and pos_fill is not None
        assert neg_fill.group(1) == pos_fill.group(1)


class TestSparkColumnSigned:
    """`render_spark_column` midline layout — positives up, negatives down."""

    def test_positive_only_column_unaffected_by_signed_support(self) -> None:
        svg = render_spark_column(
            50, max_value=100, width=20, height=40, resolved_style=_EFF
        )
        rects = _rects(svg)
        assert rects[0]["y"] == pytest.approx(20.0)
        assert rects[0]["height"] == pytest.approx(20.0)

    def test_negative_value_grows_down_from_midline(self) -> None:
        svg = render_spark_column(
            -30,
            max_value=100,
            width=20,
            height=40,
            has_negative=True,
            resolved_style=_EFF,
        )
        rects = _rects(svg)
        # 30% of the half-height (20px) = 6px, growing downward from y=20.
        assert rects[0]["height"] == pytest.approx(6.0)
        assert rects[0]["y"] == pytest.approx(20.0)

    def test_positive_value_grows_up_from_midline(self) -> None:
        svg = render_spark_column(
            30,
            max_value=100,
            width=20,
            height=40,
            has_negative=True,
            resolved_style=_EFF,
        )
        rects = _rects(svg)
        assert rects[0]["height"] == pytest.approx(6.0)
        assert rects[0]["y"] == pytest.approx(14.0)

    def test_negative_color_opt_in_uses_theme_negative_token(self) -> None:
        svg = render_spark_column(
            -30,
            max_value=100,
            width=20,
            height=40,
            has_negative=True,
            negative_color=True,
            resolved_style=_EFF,
        )
        assert _EFF.tones.negative in svg


class TestSparkColumnsZeroBaseline:
    """`render_spark_columns` — sign must survive normalization."""

    def test_all_positive_layout_unchanged(self) -> None:
        """Regression pin: an all-positive array keeps the existing
        min-rebased layout (no behavior change for the common case)."""
        svg = render_spark_columns([10, 20, 30, 40], resolved_style=_EFF)
        rects = _rects(svg)
        assert len(rects) == 4
        # Smallest value floors to min_bar_height; largest reaches full plot height.
        assert rects[0]["height"] < rects[-1]["height"]

    def test_all_negative_does_not_draw_identically_to_all_positive(self) -> None:
        """-40 -30 -20 -10 must not render identically to 10 20 30 40 — the
        exact pair the old min-max normalization erased sign on (see the
        `render_spark_columns` docstring): ``(val - min) / range`` gives both
        arrays the identical ascending 0, 0.33, 0.67, 1.0 height sequence."""
        svg_negative = render_spark_columns([-40, -30, -20, -10], resolved_style=_EFF)
        svg_positive = render_spark_columns([10, 20, 30, 40], resolved_style=_EFF)
        assert svg_negative != svg_positive

    def test_all_negative_bars_grow_downward_from_midline(self) -> None:
        svg = render_spark_columns([-40, -30, -20, -10], resolved_style=_EFF)
        rects = _rects(svg)
        # Every bar starts at the same y (the zero baseline) and grows down.
        ys = {r["y"] for r in rects}
        assert len(ys) == 1
        # -40 is the largest magnitude, so it must be the tallest bar.
        assert rects[0]["height"] > rects[-1]["height"]

    def test_mixed_sign_bars_split_across_the_midline(self) -> None:
        svg = render_spark_columns([-40, 40], resolved_style=_EFF)
        rects = _rects(svg)
        assert len(rects) == 2
        negative_rect, positive_rect = rects
        # Same magnitude, opposite direction: heights match, y's differ.
        assert negative_rect["height"] == pytest.approx(positive_rect["height"])
        assert negative_rect["y"] > positive_rect["y"]

    def test_all_zero_stays_on_the_legacy_path(self) -> None:
        """Zero is not negative — an all-zero column must not pay the
        midline's halved-extent cost for nothing."""
        svg = render_spark_columns([0, 0, 0, 0], resolved_style=_EFF)
        rects = _rects(svg)
        heights = {r["height"] for r in rects}
        assert len(heights) == 1
        # The legacy (min-rebased, bottom-anchored) path floors every bar to
        # half the plot height when value_range == 0. The signed/midline path
        # would instead floor to min_bar_height — a different, much smaller
        # number — so this pins which formula actually ran, not just that
        # every bar agrees with itself.
        plot_height = _SPARK_HEIGHT - (2 * _EFF.spark.columns.padding)
        assert next(iter(heights)) == pytest.approx(plot_height / 2)

    def test_negative_color_opt_in_uses_theme_negative_token(self) -> None:
        svg = render_spark_columns([-40, 40], negative_color=True, resolved_style=_EFF)
        assert _EFF.tones.negative in svg


class TestSparkNonFiniteValues:
    """NaN/±Infinity must follow the null rule every other numeric-cell
    consumer uses (`utils.coerce_numeric_cell`): no colour, no domain
    contribution — never a full-extent, wrongly-signed bar."""

    def test_bar_nan_renders_nothing(self) -> None:
        svg = render_spark_bar(
            float("nan"),
            max_value=100,
            width=100,
            has_negative=True,
            resolved_style=_EFF,
        )
        assert _rects(svg) == []

    def test_bar_negative_infinity_renders_nothing(self) -> None:
        svg = render_spark_bar(
            float("-inf"),
            max_value=100,
            width=100,
            has_negative=True,
            resolved_style=_EFF,
        )
        assert _rects(svg) == []

    def test_bar_nan_renders_nothing_even_unsigned(self) -> None:
        """Same null rule applies with has_negative=False (the default,
        legacy-clamp path) — not just the signed layout."""
        svg = render_spark_bar(
            float("nan"), max_value=100, width=100, resolved_style=_EFF
        )
        assert _rects(svg) == []

    def test_column_nan_renders_nothing(self) -> None:
        svg = render_spark_column(
            float("nan"),
            max_value=100,
            width=20,
            height=40,
            has_negative=True,
            resolved_style=_EFF,
        )
        assert _rects(svg) == []

    def test_columns_nan_element_does_not_erase_real_bars(self) -> None:
        """Before the fix: `max_abs = max(abs(v) for v in values)` is NaN
        whenever any value is NaN, so `max_value > 0` is False and every bar
        (including the real -5 and 5) collapses to a 1px stub."""
        svg = render_spark_columns([float("nan"), -5, 5], resolved_style=_EFF)
        rects = _rects(svg)
        # NaN contributes no rect; -5 and 5 each render their real height,
        # scaled against their own magnitude (5) — not the 1px min-height stub.
        assert len(rects) == 2
        assert all(r["height"] > 1.0 for r in rects)

    def test_columns_all_positive_path_nan_does_not_erase_real_bars(self) -> None:
        """Same null rule on the min-rebased (all-positive) branch."""
        svg = render_spark_columns([float("nan"), 10, 20, 30], resolved_style=_EFF)
        rects = _rects(svg)
        assert len(rects) == 3


class TestSparkColorPrecedence:
    """The three in-cell spark surfaces must agree: negative_color, when set,
    wins over an authored `color` for negative values — matching the field's
    published description ("instead of the shared spark color")."""

    def test_bar_negative_color_wins_over_authored_color(self) -> None:
        svg = render_spark_bar(
            -30,
            max_value=100,
            width=100,
            color="#0000ff",
            has_negative=True,
            negative_color=True,
            resolved_style=_EFF,
        )
        assert _EFF.tones.negative in svg
        assert "#0000ff" not in svg

    def test_column_negative_color_wins_over_authored_color(self) -> None:
        svg = render_spark_column(
            -30,
            max_value=100,
            width=20,
            height=40,
            color="#0000ff",
            has_negative=True,
            negative_color=True,
            resolved_style=_EFF,
        )
        assert _EFF.tones.negative in svg
        assert "#0000ff" not in svg

    def test_columns_negative_color_wins_over_authored_color(self) -> None:
        svg = render_spark_columns(
            [-40, 40], color="#0000ff", negative_color=True, resolved_style=_EFF
        )
        fills = re.findall(r'fill="([^"]+)"', svg)
        negative_fill, positive_fill = fills
        assert negative_fill == _EFF.tones.negative
        assert positive_fill == "#0000ff"
