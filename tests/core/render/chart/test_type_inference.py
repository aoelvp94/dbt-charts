"""Tests for is_lex_sortable_date_like and the drift guard in type_inference.py."""

from decimal import Decimal
from typing import Any

from dbt_charts.core.render.chart.type_inference import (
    _LEX_SORTABLE_DATE_LIKE_PATTERNS,
    DATE_LIKE_PATTERNS,
    infer_vega_type_from_data,
    is_date_like_string,
    is_lex_sortable_date_like,
)


class TestInferVegaTypeFromData:
    """infer_vega_type_from_data should not mistake model names for dates."""

    def _data(self, values: list[Any]) -> list[dict[str, Any]]:
        return [{"model": v} for v in values]

    def test_claude_model_names_are_nominal_not_temporal(self):
        # "claude-opus-4-7" has 3 hyphens — was wrongly inferred as temporal
        # because the old check used `value.count("-") >= 2`.
        data = self._data(
            ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
        )
        assert infer_vega_type_from_data(data, "model") == "nominal"

    def test_hyphenated_non_date_strings_are_nominal(self):
        data = self._data(["foo-bar-baz", "a-b-c-d", "x-1-2"])
        assert infer_vega_type_from_data(data, "model") == "nominal"

    def test_iso_dates_are_temporal(self):
        data = self._data(["2024-01-15", "2024-02-20", "2024-03-10"])
        assert infer_vega_type_from_data(data, "model") == "temporal"

    def test_iso_timestamps_are_temporal(self):
        data = self._data(["2024-01-15T10:30:00", "2024-02-20T09:00:00"])
        assert infer_vega_type_from_data(data, "model") == "temporal"

    def test_space_separated_timestamps_are_temporal(self):
        # Canonical SQL / str(datetime) form returned via the dbt adapter for
        # Snowflake (Postgres/DuckDB/BigQuery stringify the same way). The
        # space separator must be recognized just like the T separator, or the
        # x-axis falls back to nominal and renders raw timestamp labels.
        data = self._data(
            ["2025-03-01 00:00:00", "2025-04-01 00:00:00", "2025-05-01 00:00:00"]
        )
        assert infer_vega_type_from_data(data, "model") == "temporal"

    def test_space_separated_timestamp_is_date_like(self):
        assert is_date_like_string("2025-03-01 00:00:00") is True

    def test_decimal_values_are_quantitative(self):
        # BigQuery NUMERIC/BIGNUMERIC and DuckDB DECIMAL columns arrive as
        # Python Decimal. They are genuinely numeric, so a histogram over them
        # must infer quantitative — not nominal (ERR-HISTOGRAM-NON-NUMERIC).
        data = self._data([Decimal("12.50"), Decimal("34.00"), Decimal("7.25")])
        assert infer_vega_type_from_data(data, "model") == "quantitative"

    def test_bool_values_are_quantitative(self):
        # bool is an int subclass and is intentionally treated as quantitative
        # here so a boolean series field reaches the "no reorder" skip path
        # (test_shared_spatial_series_order). Adding Decimal must not disturb
        # this — pin it so the bool branch is not "helpfully" excluded later.
        data = self._data([True, False, True])
        assert infer_vega_type_from_data(data, "model") == "quantitative"

    def test_string_values_stay_nominal(self):
        # Genuinely non-numeric columns must NOT become quantitative — the
        # histogram guard stays intact.
        data = self._data(["alpha", "beta", "gamma"])
        assert infer_vega_type_from_data(data, "model") == "nominal"


class TestIsLexSortableDateLike:
    def test_daily_yyyy_mm_dd_returns_true(self):
        assert is_lex_sortable_date_like("2025-04-15") is True

    def test_iso_timestamp_hh_mm_returns_true(self):
        assert is_lex_sortable_date_like("2025-04-15T13:30") is True

    def test_iso_timestamp_hh_mm_ss_returns_true(self):
        assert is_lex_sortable_date_like("2025-04-15T13:30:00") is True

    def test_space_separated_naive_timestamp_returns_true(self):
        # Space-separated naive timestamps are lex==chron just like the T form.
        assert is_lex_sortable_date_like("2025-04-15 13:30:00") is True

    def test_space_separated_timestamp_with_offset_returns_false(self):
        # tz offsets break lex==chron regardless of separator
        assert is_lex_sortable_date_like("2025-04-15 13:30:00+05:00") is False

    def test_iso_timestamp_with_fractional_seconds_returns_true(self):
        assert is_lex_sortable_date_like("2025-04-15T13:30:00.123") is True

    def test_iso_timestamp_with_z_suffix_returns_false(self):
        # Mixed offsets would break lex==chron invariant
        assert is_lex_sortable_date_like("2025-04-15T13:30:00Z") is False

    def test_iso_timestamp_with_offset_returns_false(self):
        assert is_lex_sortable_date_like("2025-04-15T13:30:00+05:00") is False

    def test_garbage_T_tail_returns_false(self):
        # T must be followed by HH:MM digits
        assert is_lex_sortable_date_like("2025-04-15Tfoobar") is False

    def test_incomplete_time_component_returns_false(self):
        # T followed by only hours — no minute component
        assert is_lex_sortable_date_like("2025-04-15T13") is False

    def test_month_name_format_returns_false(self):
        assert is_lex_sortable_date_like("April 15, 2025") is False

    def test_mm_dd_yyyy_slash_format_returns_false(self):
        # Year-last formats don't sort lex==chron
        assert is_lex_sortable_date_like("01/15/2025") is False

    # Existing patterns still work
    def test_year_month_returns_true(self):
        assert is_lex_sortable_date_like("2024-01") is True

    def test_quarter_returns_true(self):
        assert is_lex_sortable_date_like("2024-Q1") is True

    def test_iso_week_returns_true(self):
        assert is_lex_sortable_date_like("2024-W01") is True


def test_drift_guard_passes():
    """Every _LEX_SORTABLE pattern must appear in DATE_LIKE_PATTERNS."""
    assert set(_LEX_SORTABLE_DATE_LIKE_PATTERNS) <= set(DATE_LIKE_PATTERNS)
