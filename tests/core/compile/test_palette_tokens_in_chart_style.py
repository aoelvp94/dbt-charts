"""Regression tests: palette tokens resolve in chart-level style and conditional_formatting.

Chart-local style overrides (ChartStylePatch) and conditional_formatting rules can
reference palette tokens like ``dbt-creams.subtitle``. Before the fix, those tokens
leaked through to the renderer as literal strings (e.g. stroke="dbt-creams.subtitle").

Coverage:
- Axis: axis_x.ticks.color, axis_y.grid.color, axis_quantitative.label.font.color
- Top-level chart style: background, color, border.color
- Title / legend: title.font.color, legend.label.font.color
- Per-chart-type: bar.stroke, kpi.background, spark_bar.bar.color
- Borders: kpi.border.color, spark_bar.border.color
- Table: table.background, table.row.font.color, table.header.background
- Conditional formatting: rules[0].background, rules[0].font.color
- Failure case: unknown token raises UnknownColorError at compile time
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import (
    get_theme_style,
    reset_config,
)
from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
    KpiChart,
    SparkBarChart,
    TableChart,
)
from dbt_charts.core.compile.models.style.authored import (
    ChartStylePatch,
)
from dbt_charts.core.compile.resolve.style.axis_cascade import resolved_axis_style
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.compile.resolve.style.chart_context import (
    build_chart_style_context,
)

TOKEN = "dbt-creams.subtitle"
HEX = "#918878"
UNKNOWN = "dbt-creams.does-not-exist"


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_config()
    yield
    reset_config()


def _board():
    return resolve_chart_style_context(get_theme_style())


def _patch(d: dict):
    """Extract the per-family style patch from a ChartStylePatch-shape dict."""
    monolithic = ChartStylePatch.model_validate(d)
    key = next(iter(d))
    return getattr(monolithic, key)


# ── Axis fields ───────────────────────────────────────────────────────────────


class TestAxisTokenResolution:
    def test_axis_x_ticks_color(self) -> None:
        patch = _patch({"bar": {"axis_x": {"ticks": {"color": TOKEN}}}})
        effective = build_chart_style_context(
            _board(), BarChart(id="t", type="bar", style=patch)
        )
        merged = resolved_axis_style(
            effective, "axis_x", "ordinal", chart_type="", label_authored=False
        )
        assert merged.ticks.color == HEX

    def test_axis_y_grid_color(self) -> None:
        patch = _patch({"bar": {"axis_y": {"grid": {"color": TOKEN}}}})
        effective = build_chart_style_context(
            _board(), BarChart(id="t", type="bar", style=patch)
        )
        merged = resolved_axis_style(
            effective, "axis_y", "quantitative", chart_type="", label_authored=False
        )
        assert merged.grid.color == HEX

    def test_axis_quantitative_label_font_color(self) -> None:
        patch = _patch(
            {"bar": {"axis_quantitative": {"labels": {"font": {"color": TOKEN}}}}}
        )
        effective = build_chart_style_context(
            _board(), BarChart(id="t", type="bar", style=patch)
        )
        merged = resolved_axis_style(
            effective, "axis_y", "quantitative", chart_type="", label_authored=False
        )
        assert merged.labels.font.color == HEX

    def test_unknown_axis_token_raises(self) -> None:
        from dbt_charts.core.compile.resolve.style.palette import UnknownColorError

        patch = _patch({"bar": {"axis_x": {"ticks": {"color": UNKNOWN}}}})
        with pytest.raises(UnknownColorError):
            build_chart_style_context(
                _board(), BarChart(id="t", type="bar", style=patch)
            )


# ── Top-level chart style ─────────────────────────────────────────────────────


class TestTopLevelChartStyleTokenResolution:
    def test_background_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            BarChart(id="t", type="bar", style=_patch({"bar": {"background": TOKEN}})),
        )
        assert effective.background == HEX

    def test_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            BarChart(
                id="t", type="bar", style=_patch({"bar": {"color": {"static": TOKEN}}})
            ),
        )
        assert effective.color == HEX

    def test_border_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            BarChart(
                id="t", type="bar", style=_patch({"bar": {"border": {"color": TOKEN}}})
            ),
        )
        assert effective.bar.border.color == HEX


# ── Title and legend ──────────────────────────────────────────────────────────


class TestTitleLegendTokenResolution:
    def test_title_font_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            BarChart(
                id="t",
                type="bar",
                style=_patch({"bar": {"title": {"font": {"color": TOKEN}}}}),
            ),
        )
        assert effective.title.font.color == HEX

    def test_legend_label_font_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            BarChart(
                id="t",
                type="bar",
                style=_patch(
                    {"bar": {"legend": {"label": {"font": {"color": TOKEN}}}}}
                ),
            ),
        )
        assert effective.legend.label.font.color == HEX


# ── Per-chart-type overlays ───────────────────────────────────────────────────


class TestPerChartTypeTokenResolution:
    def test_bar_axis_x_ticks_color_token(self) -> None:
        # bar.axis_x.ticks.color proves per-chart-type token resolution at chart level.
        effective = build_chart_style_context(
            _board(),
            BarChart(
                id="t",
                type="bar",
                style=_patch({"bar": {"axis_x": {"ticks": {"color": TOKEN}}}}),
            ),
        )
        assert effective.bar.axis_x.ticks.color == HEX

    def test_kpi_font_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            KpiChart(
                id="t",
                type="kpi",
                value="v",
                style=_patch({"kpi": {"font": {"color": TOKEN}}}),
            ),
        )
        assert effective.kpi.font.color == HEX

    def test_spark_bar_bar_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            SparkBarChart(
                id="t",
                type="spark_bar",
                style=_patch({"spark_bar": {"bar": {"color": TOKEN}}}),
            ),
        )
        assert effective.spark_bar.bar.color == HEX


# ── Borders ───────────────────────────────────────────────────────────────────


class TestBorderColorTokenResolution:
    def test_kpi_border_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            KpiChart(
                id="t",
                type="kpi",
                value="v",
                style=_patch({"kpi": {"border": {"color": TOKEN}}}),
            ),
        )
        assert effective.kpi.border.color == HEX

    def test_spark_bar_border_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            SparkBarChart(
                id="t",
                type="spark_bar",
                style=_patch({"spark_bar": {"border": {"color": TOKEN}}}),
            ),
        )
        assert effective.spark_bar.border.color == HEX


# ── Table fields ──────────────────────────────────────────────────────────────


class TestTableTokenResolution:
    def test_table_background_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            TableChart(
                id="t", type="table", style=_patch({"table": {"background": TOKEN}})
            ),
        )
        assert effective.table.background == HEX

    def test_table_header_background_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            TableChart(
                id="t",
                type="table",
                style=_patch({"table": {"header": {"background": TOKEN}}}),
            ),
        )
        assert effective.table.header.background == HEX

    def test_table_row_stripe_color_token(self) -> None:
        effective = build_chart_style_context(
            _board(),
            TableChart(
                id="t",
                type="table",
                style=_patch({"table": {"row": {"stripe": {"color": TOKEN}}}}),
            ),
        )
        assert effective.table.row.stripe is not None
        assert effective.table.row.stripe.color == HEX


# ── Conditional formatting ────────────────────────────────────────────────────


class TestConditionalFormattingTokenResolution:
    """Tokens in conditional_formatting rules resolve at normalization time."""

    def _make_chart(self, rule: dict):
        from dbt_charts.core.compile.normalize.charts import normalize_chart

        return normalize_chart(
            chart_id="test_chart",
            chart_def={
                "type": "table",
                "query": {"columns": ["x"], "values": [["a"], ["b"]]},
                "conditional_formatting": {"x": {"when": [rule]}},
            },
            query_registry={},
            sources={},
        )

    def test_rule_background_token_resolves(self) -> None:
        chart = self._make_chart({"eq": "x", "background": TOKEN})
        assert chart.conditional_formatting is not None
        assert chart.conditional_formatting["x"].when[0].background == HEX

    def test_rule_font_color_token_resolves(self) -> None:
        chart = self._make_chart({"eq": "x", "font": {"color": TOKEN}})
        assert chart.conditional_formatting is not None
        rule = chart.conditional_formatting["x"].when[0]
        assert rule.font is not None
        assert rule.font.color == HEX

    def test_unknown_background_token_raises(self) -> None:
        from dbt_charts.core.compile.resolve.style.palette import UnknownColorError

        with pytest.raises(UnknownColorError):
            self._make_chart({"eq": "x", "background": UNKNOWN})


# ── Bracket role tokens (theme-portable) ─────────────────────────────────────


class TestBracketRoleTokensInChartStyle:
    """Bracket role tokens (1-indexed, e.g. ``category_dark[3]``) resolve in
    chart-level style through the ACTIVE theme's ``style.palettes`` role
    bindings — the theme-portable counterpart of the absolute tokens above.
    A board converted from explicit ``editorial-10-*`` stops to role tokens
    must repaint on a theme switch, including per-chart style blocks.
    """

    THEME_FAMILY = (
        ("stark", "vivid-10"),
        ("editorial", "editorial-10"),
        ("cream", "editorial-10"),
    )

    @pytest.mark.parametrize(("theme", "family"), THEME_FAMILY)
    def test_chart_palette_list_follows_theme(self, theme: str, family: str) -> None:
        from dbt_charts.core.compile.resolve.style.palette import (
            palette as resolve_palette,
        )

        board = resolve_chart_style_context(get_theme_style(theme))
        patch = _patch(
            {
                "bar": {
                    "color": {
                        "categorical": {"palette": ["category_dark[3]", "category[1]"]}
                    }
                }
            }
        )
        effective = build_chart_style_context(
            board, BarChart(id="t", type="bar", style=patch)
        )
        assert list(effective.palette) == [
            resolve_palette(family + "-dark")[2],
            resolve_palette(family)[0],
        ], f"chart-level bracket tokens must follow the {theme} theme's roles"

    @pytest.mark.parametrize(("theme", "family"), THEME_FAMILY)
    def test_chart_background_bracket_token_follows_theme(
        self, theme: str, family: str
    ) -> None:
        from dbt_charts.core.compile.resolve.style.palette import (
            palette as resolve_palette,
        )

        board = resolve_chart_style_context(get_theme_style(theme))
        patch = _patch({"bar": {"background": "category_ghost[2]"}})
        effective = build_chart_style_context(
            board, BarChart(id="t", type="bar", style=patch)
        )
        assert effective.background == resolve_palette(family + "-ghost")[1]

    def test_unknown_role_bracket_token_raises(self) -> None:
        from dbt_charts.core.compile.resolve.style.palette import UnknownColorError

        board = resolve_chart_style_context(get_theme_style("stark"))
        patch = _patch({"bar": {"background": "categry[2]"}})
        with pytest.raises(UnknownColorError):
            build_chart_style_context(board, BarChart(id="t", type="bar", style=patch))
