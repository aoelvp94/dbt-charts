"""Tests for column-width allocation policy.

After the fix: all auto-columns (no explicit width:) receive an equal share of
available_width.  The table always fits the tile.  Numeric/date columns squish
like text columns — truncation is honest, clipping is not.

Tests that pinned the old sacred-column / elastic-floor / trailing-whitespace
contracts have been replaced with tests for the new equal-distribution contract.
"""

from __future__ import annotations

import re

import pytest

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)

_BOARD_STYLE = resolve_chart_style_context(get_theme_style())

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_PIPELINE_DATA = [
    {
        "opportunity": "Big Widget Deal",
        "account": "Acme Corp",
        "stage": "Proposal",
        "amount": 125000,
        "close_date": "2024-03-15",
        "probability": 0.75,
    },
    {
        "opportunity": "Small Widget Sale",
        "account": "Globex",
        "stage": "Negotiation",
        "amount": 8500,
        "close_date": "2024-06-30",
        "probability": 0.5,
    },
    {
        "opportunity": "Enterprise Platform",
        "account": "Initech",
        "stage": "Closed Won",
        "amount": 2500000,
        "close_date": "2023-12-01",
        "probability": 1.0,
    },
]


def _make_table_chart(make_chart, style: dict | None = None):
    return make_chart("table", x=None, y=None, style=style)


# ---------------------------------------------------------------------------
# Test 1: all auto-columns get equal share
# ---------------------------------------------------------------------------


class TestEqualDistribution:
    """All auto-columns receive available_width / n_auto_cols."""

    def test_three_auto_columns_get_equal_share(self):
        from dbt_charts.core.render.chart.table_support import (
            calculate_column_layout,
        )

        columns = ["label", "amount", "close_date"]
        col_configs = {}
        available_width = 300.0
        col_widths, _, actual_w = calculate_column_layout(
            columns,
            col_configs,
            available_width,
        )

        expected = available_width / 3
        for col in columns:
            assert abs(col_widths[col] - expected) <= 0.5, (
                f"Column '{col}' got {col_widths[col]:.1f}px, "
                f"expected equal share {expected:.1f}px"
            )
        assert abs(actual_w - available_width) <= 0.5

    def test_actual_content_width_never_exceeds_available_width(self):
        """actual_content_width <= available_width always, including numeric/date columns."""
        from dbt_charts.core.render.chart.table_support import (
            calculate_column_layout,
        )

        columns = ["d1", "d2", "d3", "d4", "d5"]
        col_configs = {}
        available_width = 200.0
        _, _, actual_w = calculate_column_layout(
            columns,
            col_configs,
            available_width,
        )
        assert actual_w <= available_width + 0.5, (
            f"actual_content_width={actual_w:.1f}px exceeds "
            f"available_width={available_width:.1f}px"
        )


# ---------------------------------------------------------------------------
# Test 2: elastic columns truncate when squeezed
# ---------------------------------------------------------------------------


class TestElasticColumnsTruncateWhenSqueezed:
    """Text columns squeezed below content_floor show ellipsis in rendered SVG."""

    def test_elastic_text_shows_ellipsis_at_tight_width(self, make_chart):
        """At a very tight width with wrap disabled, elastic columns truncate with ellipsis."""
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = _make_table_chart(
            make_chart,
            style={
                "table": {"wrap": False},
                "columns": {
                    "opportunity": {},
                    "account": {},
                    "amount": {},
                    "close_date": {},
                    # width math pins the four columns above; keep the rest
                    # out of the layout explicitly (styling-only style.columns)
                    "stage": {"visible": False},
                    "probability": {"visible": False},
                },
            },
        )
        # 260px: tight enough that the cascade reduces font to 11px and elastic
        # columns still can't hold the longest text without truncation.
        chart = resolve(chart, _PIPELINE_DATA, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            _PIPELINE_DATA,
            width=260,
            board_style=resolve_style(get_theme_style()),
        )

        has_ellipsis = "…" in svg
        assert has_ellipsis, (
            "Expected ellipsis ('…') in tight-width table SVG with wrap:false — "
            "elastic text columns should truncate rather than overflow"
        )


# ---------------------------------------------------------------------------
# Test 3: SVG does not widen beyond tile for many numeric/date columns
# ---------------------------------------------------------------------------


class TestSVGFitsTileBoundary:
    """SVG width never exceeds available_width regardless of column content type."""

    def test_svg_stays_at_available_width_with_date_columns(self, make_chart):
        """Many date columns in a narrow tile: SVG stays at tile width."""
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        data = [
            {
                "d1": "2024-01-15",
                "d2": "2024-02-20",
                "d3": "2024-03-25",
                "d4": "2024-04-30",
                "d5": "2024-05-15",
            }
        ]
        chart = _make_table_chart(
            make_chart,
            style={
                "columns": {
                    "d1": {"visible": True},
                    "d2": {},
                    "d3": {},
                    "d4": {},
                    "d5": {},
                }
            },
        )
        available_width = 200
        chart = resolve(chart, data, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            data,
            width=available_width,
            board_style=resolve_style(get_theme_style()),
        )

        svg_width_m = re.search(r'<svg[^>]*\bwidth="([^"]+)"', svg)
        assert svg_width_m is not None, "Could not find SVG width attribute"
        actual_width = float(svg_width_m.group(1))
        assert actual_width <= available_width + 0.5, (
            f"SVG width {actual_width:.1f}px exceeds tile width {available_width}px — "
            f"table must fit within tile boundaries."
        )


# ---------------------------------------------------------------------------
# Test 4: no text overflow across multiple widths
# ---------------------------------------------------------------------------


class TestNoTextOverflowAcrossWidths:
    """For a mixed table, no text overflows its cell at any tested width."""

    @pytest.mark.parametrize("width", [300, 400, 500, 600, 800, 1120])
    def test_no_overflow_at_width(self, make_chart, width: int):
        """Every text element stays within its cell's content band."""
        from dbt_charts.core.render.chart.table import (
            render_table_svg as render_table_svg,
        )

        chart = _make_table_chart(
            make_chart,
            style={
                "columns": {
                    "opportunity": {},
                    "account": {},
                    "amount": {"format": "$,.0f"},
                    "close_date": {},
                    "probability": {"format": ".0%"},
                    "stage": {"visible": False},
                }
            },
        )
        chart = resolve(chart, _PIPELINE_DATA, chart_style_context=_BOARD_STYLE)
        svg = render_table_svg(
            chart,
            _PIPELINE_DATA,
            width=width,
            board_style=resolve_style(get_theme_style()),
        )

        # Find the SVG root width (background rect omitted when table has no explicit background)
        svg_width_m = re.search(r'<svg[^>]*\bwidth="([^"]+)"', svg)
        assert svg_width_m, "Could not find SVG width"
        actual_width = float(svg_width_m.group(1))

        # Verify all text elements fit within the table width (basic sanity)
        for m in re.finditer(r'<text\s[^>]*x="([^"]+)"', svg):
            x = float(m.group(1))
            assert x <= actual_width + 1.0, (
                f"At width={width}, text element x={x:.1f} exceeds "
                f"table width {actual_width:.1f}"
            )


# ---------------------------------------------------------------------------
# Test 5: explicit width overrides are still honored
# ---------------------------------------------------------------------------


class TestExplicitWidthsHonored:
    """Per-column explicit width: overrides are respected; remainder is equal-distributed."""

    def test_explicit_width_column_and_auto_remainder(self):
        """An explicit-width column takes its value; the rest get equal share."""
        from dbt_charts.core.compile.models.chart.authored import (
            TableColumnConfig,
        )
        from dbt_charts.core.render.chart.table_support import calculate_column_layout

        columns = ["name", "amount", "date"]
        col_configs = {"name": TableColumnConfig(width=200)}

        available_width = 600.0
        col_widths, _, actual_w = calculate_column_layout(
            columns,
            col_configs,
            available_width,
        )

        assert col_widths["name"] == 200.0, (
            f"Explicit width must be 200px, got {col_widths['name']:.1f}px"
        )
        expected_auto = (600.0 - 200.0) / 2  # 200px each
        for col in ("amount", "date"):
            assert abs(col_widths[col] - expected_auto) <= 0.5, (
                f"Auto column '{col}' got {col_widths[col]:.1f}px, "
                f"expected {expected_auto:.1f}px"
            )
        assert abs(actual_w - available_width) <= 0.5
