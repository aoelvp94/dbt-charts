"""Tests for cross-cutting value-classification helpers in dbt_charts.core.utils."""

from __future__ import annotations

import datetime
from decimal import Decimal

from dbt_charts.core.utils import (
    classify_date_column_align,
    is_date_like,
    is_year_shaped,
)


class TestIsYearShaped:
    def test_integer_years_in_range(self) -> None:
        assert is_year_shaped([2010, 2015, 2024]) is True

    def test_string_years_in_range(self) -> None:
        assert is_year_shaped(["2010", "2015", "2024"]) is True

    def test_integer_below_range_not_year(self) -> None:
        # counts / small integers must never read as years
        assert is_year_shaped([1, 2, 3, 4, 5]) is False

    def test_integer_above_range_not_year(self) -> None:
        assert is_year_shaped([100, 200, 300]) is False

    def test_year_boundaries_inclusive(self) -> None:
        assert is_year_shaped([1900, 2100]) is True
        assert is_year_shaped([1899]) is False
        assert is_year_shaped([2101]) is False

    def test_mixed_year_and_non_year_not_year(self) -> None:
        assert is_year_shaped([2010, 2011, 42]) is False
        assert is_year_shaped(["2010", "Q1"]) is False

    def test_float_years_not_year(self) -> None:
        # floats are not year buckets; measures never yield year x
        assert is_year_shaped([2014.0, 2015.0]) is False

    def test_booleans_not_year(self) -> None:
        assert is_year_shaped([True, False]) is False

    def test_empty_not_year(self) -> None:
        assert is_year_shaped([]) is False

    def test_non_4_digit_string_not_year(self) -> None:
        assert is_year_shaped(["201", "20100"]) is False

    def test_integral_decimal_years_in_range(self) -> None:
        # BigQuery NUMERIC / Snowflake NUMBER return year integers as Decimal.
        assert is_year_shaped([Decimal(2024), Decimal(2025)]) is True

    def test_non_integral_decimal_not_year(self) -> None:
        assert is_year_shaped([Decimal("2024.5")]) is False

    def test_integral_decimal_out_of_range_not_year(self) -> None:
        assert is_year_shaped([Decimal(42)]) is False


class TestIsDateLike:
    def test_date_object(self) -> None:
        assert is_date_like(datetime.date(2024, 1, 15)) is True

    def test_datetime_object(self) -> None:
        assert is_date_like(datetime.datetime(2024, 1, 15, 13, 30, 0)) is True

    def test_short_month_name(self) -> None:
        assert is_date_like("15 Jan 2024") is True

    def test_full_month_name_not_matched(self) -> None:
        # The known gap this detector doesn't close — full month names
        # ("January") are not in the pattern. See classify_date_column_align
        # for why a single non-matching cell should demote the whole column.
        assert is_date_like("15 January 2024") is False

    def test_bare_year(self) -> None:
        assert is_date_like("2024") is True

    def test_plain_number_not_date(self) -> None:
        assert is_date_like(42) is False

    def test_bool_not_date(self) -> None:
        assert is_date_like(True) is False

    def test_non_date_string(self) -> None:
        assert is_date_like("hello") is False


class TestClassifyDateColumnAlign:
    def test_uniform_short_month_names_right(self) -> None:
        assert classify_date_column_align(["15 Jan 2024", "3 Feb 2024"]) == "right"

    def test_mixed_month_name_length_no_verdict(self) -> None:
        # One cell spelled with the full month name breaks the unanimous
        # match — the column must not right-align on a per-cell majority.
        assert classify_date_column_align(["30 March 2024", "9 May 2024"]) is None

    def test_numeric_values_no_verdict(self) -> None:
        # Numeric columns already right-align unconditionally elsewhere;
        # this classifier only ever produces a temporal verdict.
        assert classify_date_column_align([1, 2, 3]) is None

    def test_null_values_ignored(self) -> None:
        assert (
            classify_date_column_align(["15 Jan 2024", None, "3 Feb 2024"]) == "right"
        )

    def test_blank_string_ignored(self) -> None:
        assert (
            classify_date_column_align(["15 Jan 2024", "  ", "3 Feb 2024"]) == "right"
        )

    def test_all_null_no_verdict(self) -> None:
        assert classify_date_column_align([None, None]) is None

    def test_empty_no_verdict(self) -> None:
        assert classify_date_column_align([]) is None

    def test_date_objects_right(self) -> None:
        assert (
            classify_date_column_align(
                [datetime.date(2024, 1, 15), datetime.date(2024, 2, 3)]
            )
            == "right"
        )

    def test_datetime_objects_no_verdict(self) -> None:
        # datetime.datetime always stringifies with a time component (even
        # at midnight) — normalize_scalar_for_json's str(value) fallback,
        # applied before render's own per-cell checks run. Classifying the
        # raw object as date-like here would right-align a column whose
        # cells render as plain (non-date-matching, non-tabular) text.
        assert (
            classify_date_column_align(
                [
                    datetime.datetime(2024, 1, 15, 0, 0, 0),
                    datetime.datetime(2024, 2, 3, 0, 0, 0),
                ]
            )
            is None
        )
