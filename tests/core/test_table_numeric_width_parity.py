"""Guard tests for the equal-distribution column-width policy.

After the fix, all auto-columns receive an equal share of available_width.
Tests that verified content-floor-based sizing (format_kpi_parts width parity,
lane-gap padding, etc.) have been removed because content measurement no longer
drives column widths.

The parity invariants that remain relevant:
- All auto-columns get equal share of available_width.
- explicit width: overrides are honored.
- actual_content_width == available_width when there are auto-columns.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Test 1: equal distribution — all auto-columns get same width
# ---------------------------------------------------------------------------


class TestEqualDistributionContract:
    """All auto-columns receive available_width / n_auto_cols exactly."""

    def test_six_columns_equal_share(self):
        """Six auto-columns at 544px each get 544/6 ≈ 90.7px."""
        from dbt_charts.core.render.chart.table_support import (
            calculate_column_layout,
        )

        columns = [
            "opportunity",
            "account",
            "stage",
            "amount",
            "close_date",
            "probability",
        ]
        col_configs = {}
        available_width = 544.0

        col_widths, _, actual_w = calculate_column_layout(
            columns, col_configs, available_width
        )

        expected = available_width / len(columns)
        for col in columns:
            assert abs(col_widths[col] - expected) <= 0.5, (
                f"Column '{col}' got {col_widths[col]:.2f}px, "
                f"expected equal share {expected:.2f}px"
            )
        assert abs(actual_w - available_width) <= 0.5


# ---------------------------------------------------------------------------
# Test 2: explicit format columns still get their explicit widths
# ---------------------------------------------------------------------------


class TestExplicitWidthColumnsUnaffected:
    """Columns with explicit width: are unaffected by the auto-distribution logic."""

    def test_explicit_format_column_respects_explicit_width(self):
        """A column with both format: and width: gets the explicit width."""
        from dbt_charts.core.compile.models.chart.authored import (
            TableColumnConfig,
        )
        from dbt_charts.core.render.chart.table_support import calculate_column_layout

        col_configs = {
            "amount": TableColumnConfig(format="$,.0f", width=150),
        }

        col_widths, _, _ = calculate_column_layout(
            ["amount"],
            col_configs,
            600.0,
        )
        assert col_widths["amount"] == 150.0, (
            f"Explicit width=150 not honored; got {col_widths['amount']:.2f}px"
        )


# ---------------------------------------------------------------------------
# Test 3: non-numeric columns adjacent to numeric — all equal
# ---------------------------------------------------------------------------


class TestMixedColumnTypesEqualShare:
    """Text and numeric columns in the same table all receive equal share."""

    def test_text_and_numeric_share_equally(self):
        """A text column and a numeric column in a 600px table each get 300px."""
        from dbt_charts.core.render.chart.table_support import (
            calculate_column_layout,
        )

        col_configs = {}
        available_width = 600.0

        col_widths, _, actual_w = calculate_column_layout(
            ["label", "amount"],
            col_configs,
            available_width,
        )

        expected = available_width / 2
        assert abs(col_widths["label"] - expected) <= 0.5, (
            f"Text column got {col_widths['label']:.2f}px, expected {expected:.2f}px"
        )
        assert abs(col_widths["amount"] - expected) <= 0.5, (
            f"Numeric column got {col_widths['amount']:.2f}px, expected {expected:.2f}px"
        )
        assert abs(actual_w - available_width) <= 0.5
