"""Unit tests for time_unit_detect.detect_time_unit."""

from __future__ import annotations

import datetime as dt

import pytest

from dbt_charts.core.render.chart.time_unit_detect import (
    detect_time_unit,
    normalize_labeled_temporal,
    ordinal_axis_values,
)


class TestDetectTimeUnit:
    # ── year ────────────────────────────────────────────────────────────

    def test_year_iso_dates(self) -> None:
        values = ["2022-01-01", "2023-01-01", "2024-01-01"]
        assert detect_time_unit(values) == "year"

    def test_year_date_objects(self) -> None:
        values = [dt.date(2022, 1, 1), dt.date(2023, 1, 1), dt.date(2024, 1, 1)]
        assert detect_time_unit(values) == "year"

    # ── yearquarter ─────────────────────────────────────────────────────

    def test_yearquarter_iso_dates(self) -> None:
        values = [
            "2024-01-01",
            "2024-04-01",
            "2024-07-01",
            "2024-10-01",
            "2025-01-01",
        ]
        assert detect_time_unit(values) == "yearquarter"

    def test_yearquarter_date_objects(self) -> None:
        values = [
            dt.date(2024, 1, 1),
            dt.date(2024, 4, 1),
            dt.date(2024, 7, 1),
            dt.date(2024, 10, 1),
        ]
        assert detect_time_unit(values) == "yearquarter"

    # ── yearmonth ───────────────────────────────────────────────────────

    def test_yearmonth_iso_dates(self) -> None:
        values = [
            "2024-01-01",
            "2024-02-01",
            "2024-03-01",
            "2024-05-01",
        ]
        assert detect_time_unit(values) == "yearmonth"

    def test_yearmonth_date_objects(self) -> None:
        values = [dt.date(2024, m, 1) for m in (1, 2, 3, 5)]
        assert detect_time_unit(values) == "yearmonth"

    def test_yearmonth_sparse_gaps_detected(self) -> None:
        # Jan / Feb / May — middle months missing
        values = ["2024-01-01", "2024-02-01", "2024-05-01"]
        assert detect_time_unit(values) == "yearmonth"

    # ── yearweek ────────────────────────────────────────────────────────

    def test_yearweek_iso_dates(self) -> None:
        # Mondays only
        values = [
            "2024-01-01",  # Monday
            "2024-01-08",  # Monday
            "2024-01-15",  # Monday
        ]
        assert detect_time_unit(values) == "yearweek"

    def test_yearweek_date_objects(self) -> None:
        values = [dt.date(2024, 1, 1), dt.date(2024, 1, 8), dt.date(2024, 1, 15)]
        assert detect_time_unit(values) == "yearweek"

    def test_yearweek_sunday_aligned(self) -> None:
        # Real-world weekly reports are not always ISO-Monday-aligned —
        # Sunday-start weeks, Saturday close, mid-week pay-period reports.
        # All same-weekday + 7-day cadence still wants yearweek so the smart
        # label resolver renders monthly cadence instead of "7 Jan, 14 Jan…".
        values = ["2024-01-07", "2024-01-14", "2024-01-21", "2024-01-28"]
        assert all(dt.date.fromisoformat(v).weekday() == 6 for v in values)  # Sun
        assert detect_time_unit(values) == "yearweek"

    def test_yearweek_with_gaps_still_detects(self) -> None:
        # Missing weeks are common (holiday closures); 14-day jumps still
        # qualify since the same-weekday predicate covers any 7-day multiple.
        # Gaps: [7, 14, 14] — median = 14, within the ≤14-day gate.
        values = ["2024-01-08", "2024-01-15", "2024-01-29", "2024-02-12"]
        assert detect_time_unit(values) == "yearweek"

    def test_same_weekday_28day_spacing_not_yearweek(self) -> None:
        # 28-day spacing is 4-week intervals, not weekly. The same-weekday
        # predicate misfired on any 7-day-multiple gap; the spacing gate
        # (median > 14 days) must reject it and return None so the area/line
        # chart gets a continuous temporal scale rather than 78 ordinal weekly
        # buckets for 20 data points. Mirrors three_series.csv in area-stack-modes.
        start = dt.date(2024, 1, 7)  # Sunday
        values = [start + dt.timedelta(days=28 * i) for i in range(20)]
        assert all(v.weekday() == 6 for v in values), "fixture must be all Sundays"
        assert detect_time_unit(values) is None

    # ── yearmonthdate ───────────────────────────────────────────────────

    def test_yearmonthdate_arbitrary_dates(self) -> None:
        values = ["2024-01-01", "2024-01-15", "2024-02-07"]
        assert detect_time_unit(values) == "yearmonthdate"

    def test_yearmonthdate_date_objects(self) -> None:
        values = [dt.date(2024, 1, 15), dt.date(2024, 2, 7), dt.date(2024, 3, 22)]
        assert detect_time_unit(values) == "yearmonthdate"

    def test_yearmonthdate_midnight_datetimes(self) -> None:
        values = [
            dt.datetime(2024, 1, 15, 0, 0, 0),
            dt.datetime(2024, 2, 7, 0, 0, 0),
        ]
        assert detect_time_unit(values) == "yearmonthdate"

    # ── sub-daily → None ────────────────────────────────────────────────

    def test_subdaily_returns_none(self) -> None:
        values = [
            dt.datetime(2024, 1, 15, 9, 30, 0),
            dt.datetime(2024, 1, 15, 10, 0, 0),
        ]
        assert detect_time_unit(values) is None

    def test_subdaily_iso_string_returns_none(self) -> None:
        values = ["2024-01-15T09:30:00", "2024-01-15T10:00:00"]
        assert detect_time_unit(values) is None

    def test_subdaily_space_separator_returns_none(self) -> None:
        # DB drivers stringify datetime as "YYYY-MM-DD HH:MM:SS" (space, not T).
        # normalize_data_types calls str() on datetime objects producing this format.
        values = ["2024-01-15 09:30:00", "2024-01-15 10:00:00"]
        assert detect_time_unit(values) is None

    def test_daily_midnight_space_separator_returns_yearmonthdate(self) -> None:
        # str(datetime(2024, 1, 15, 0, 0, 0)) → "2024-01-15 00:00:00"
        # Zero hms = midnight = daily grain, not sub-daily.
        values = ["2024-01-15 00:00:00", "2024-01-16 00:00:00", "2024-01-17 00:00:00"]
        assert detect_time_unit(values) == "yearmonthdate"

    # ── edge cases ──────────────────────────────────────────────────────

    def test_fewer_than_two_distinct_returns_none(self) -> None:
        assert detect_time_unit([]) is None
        assert detect_time_unit(["2024-01-01"]) is None
        assert detect_time_unit([None]) is None

    def test_duplicate_values_counted_once(self) -> None:
        # Three rows but only 2 distinct months — still detects yearmonth
        values = ["2024-01-01", "2024-01-01", "2024-02-01", "2024-02-01"]
        assert detect_time_unit(values) == "yearmonth"

    def test_none_values_ignored(self) -> None:
        values = [None, "2024-01-01", None, "2024-02-01", None]
        assert detect_time_unit(values) == "yearmonth"

    def test_many_unparseable_raises(self) -> None:
        # ≥10% bad → fail loud
        values = ["not-a-date", "2024-01-01", "2024-02-01"]
        with pytest.raises(ValueError, match="unparseable"):
            detect_time_unit(values)

    def test_few_unparseable_ok(self) -> None:
        # <10% bad values → still detects (bad values excluded)
        # 1 bad out of 11 total distinct = 9% → ok
        values = ["bad"] + [f"2024-{m:02d}-01" for m in range(1, 12)]
        # 1/12 ≈ 8.3% → below 10% threshold
        result = detect_time_unit(values)
        assert result == "yearmonth"


class TestNormalizeLabeledTemporal:
    def test_week_labels_converted_to_mondays(self) -> None:
        data = [{"w": "2024-W01", "v": 1}, {"w": "2024-W02", "v": 2}]
        result = normalize_labeled_temporal(data, "w")
        assert result[0]["w"] == "2024-01-01"  # Monday of W01 2024
        assert result[1]["w"] == "2024-01-08"  # Monday of W02 2024

    def test_week_labels_cross_year(self) -> None:
        # ISO week W52 in 2023 (Monday) and W01 in 2024 (Monday)
        data = [{"w": "2023-W52", "v": 1}, {"w": "2024-W01", "v": 2}]
        result = normalize_labeled_temporal(data, "w")
        assert result[0]["w"] == "2023-12-25"  # Monday of W52 2023
        assert result[1]["w"] == "2024-01-01"  # Monday of W01 2024

    def test_quarter_labels_converted_to_quarter_starts(self) -> None:
        data = [
            {"q": "2024-Q1", "v": 1},
            {"q": "2024-Q2", "v": 2},
            {"q": "2024-Q3", "v": 3},
            {"q": "2024-Q4", "v": 4},
        ]
        result = normalize_labeled_temporal(data, "q")
        assert result[0]["q"] == "2024-01-01"
        assert result[1]["q"] == "2024-04-01"
        assert result[2]["q"] == "2024-07-01"
        assert result[3]["q"] == "2024-10-01"

    def test_quarter_labels_cross_year(self) -> None:
        data = [{"q": "2023-Q4", "v": 1}, {"q": "2024-Q1", "v": 2}]
        result = normalize_labeled_temporal(data, "q")
        assert result[0]["q"] == "2023-10-01"
        assert result[1]["q"] == "2024-01-01"

    def test_non_labeled_data_unchanged(self) -> None:
        data = [{"d": "2024-01-15", "v": 1}, {"d": "2024-02-01", "v": 2}]
        result = normalize_labeled_temporal(data, "d")
        # ISO dates are not labels — pass through unchanged
        assert result == data

    def test_mixed_week_labels_and_iso_dates_raises(self) -> None:
        data = [{"d": "2024-W01", "v": 1}, {"d": "2024-01-15", "v": 2}]
        with pytest.raises(ValueError, match="mixed label"):
            normalize_labeled_temporal(data, "d")

    def test_mixed_quarter_labels_and_iso_dates_raises(self) -> None:
        data = [{"d": "2024-Q1", "v": 1}, {"d": "2024-01-01", "v": 2}]
        with pytest.raises(ValueError, match="mixed label"):
            normalize_labeled_temporal(data, "d")

    def test_mixed_quarter_and_week_labels_raises(self) -> None:
        data = [{"d": "2024-Q1", "v": 1}, {"d": "2024-W01", "v": 2}]
        with pytest.raises(ValueError, match="mixed label"):
            normalize_labeled_temporal(data, "d")

    def test_invalid_week_number_raises_clear_error(self) -> None:
        # 2024 has only 52 ISO weeks; W53 is invalid for that year
        data = [{"w": "2024-W53", "v": 1}, {"w": "2024-W01", "v": 2}]
        with pytest.raises(ValueError, match="not a valid ISO week"):
            normalize_labeled_temporal(data, "w")

    def test_non_x_fields_unchanged(self) -> None:
        data = [{"x": "2024-Q1", "y": 100}]
        result = normalize_labeled_temporal(data, "x")
        assert result[0]["y"] == 100  # other fields preserved

    def test_none_values_preserved(self) -> None:
        data = [{"w": "2024-W01", "v": 1}, {"w": None, "v": 2}]
        result = normalize_labeled_temporal(data, "w")
        assert result[0]["w"] == "2024-01-01"
        assert result[1]["w"] is None

    def test_empty_data_unchanged(self) -> None:
        assert normalize_labeled_temporal([], "x") == []


class TestDetectTimeUnitLabeledFormats:
    """detect_time_unit accepts DATE_LIKE bucket string vocabulary."""

    # ── YYYY-MM → yearmonth ──────────────────────────────────────────────
    def test_yearmonth_yyyy_mm_strings(self) -> None:
        vals = [f"2024-{m:02d}" for m in range(1, 5)]
        assert detect_time_unit(vals) == "yearmonth"

    def test_yearmonth_yyyy_mm_sparse(self) -> None:
        assert detect_time_unit(["2024-01", "2024-06", "2024-12"]) == "yearmonth"

    def test_yearmonth_yyyy_mm_cross_year(self) -> None:
        assert detect_time_unit(["2023-11", "2023-12", "2024-01"]) == "yearmonth"

    # ── Mon YYYY → yearmonth ─────────────────────────────────────────────
    def test_yearmonth_mon_yyyy_strings(self) -> None:
        assert detect_time_unit(["Jan 2024", "Feb 2024", "Mar 2024"]) == "yearmonth"

    def test_yearmonth_mon_yyyy_case_insensitive(self) -> None:
        assert detect_time_unit(["jan 2024", "FEB 2024", "Mar 2024"]) == "yearmonth"

    # ── MM/YYYY → yearmonth ──────────────────────────────────────────────
    def test_yearmonth_mm_yyyy_strings(self) -> None:
        assert detect_time_unit(["01/2024", "02/2024", "03/2024"]) == "yearmonth"

    # ── Q1 YYYY / 2024Q1 alternate quarter spellings → yearquarter ───────
    def test_yearquarter_q_yyyy_strings(self) -> None:
        assert detect_time_unit(["Q1 2024", "Q2 2024", "Q3 2024"]) == "yearquarter"

    def test_yearquarter_yyyy_q_strings(self) -> None:
        assert detect_time_unit(["2024Q1", "2024Q2", "2024Q3"]) == "yearquarter"

    # ── FY2024 → year ────────────────────────────────────────────────────
    def test_year_fy_strings(self) -> None:
        assert detect_time_unit(["FY2022", "FY2023", "FY2024"]) == "year"

    # ── MM/DD/YYYY → yearmonthdate ───────────────────────────────────────
    def test_yearmonthdate_mm_dd_yyyy(self) -> None:
        assert (
            detect_time_unit(["01/15/2024", "02/20/2024", "03/05/2024"])
            == "yearmonthdate"
        )

    # ── Mon DD, YYYY → yearmonthdate ─────────────────────────────────────
    def test_yearmonthdate_mon_dd_yyyy(self) -> None:
        assert detect_time_unit(["Jan 15, 2024", "Feb 20, 2024"]) == "yearmonthdate"

    def test_yearmonthdate_mon_dd_yyyy_no_comma(self) -> None:
        assert detect_time_unit(["Jan 15 2024", "Feb 20 2024"]) == "yearmonthdate"

    # ── Week spelled (W32 2024 / Week 32 2024) → yearweek ────────────────
    def test_yearweek_w_spelled(self) -> None:
        assert detect_time_unit(["W01 2024", "W02 2024", "W03 2024"]) == "yearweek"

    def test_yearweek_week_spelled(self) -> None:
        assert detect_time_unit(["Week 1 2024", "Week 2 2024"]) == "yearweek"


class TestNormalizeLabeledTemporalNewFormats:
    """normalize_labeled_temporal converts new bucket formats to ISO dates."""

    def test_yyyy_mm_normalized_to_iso(self) -> None:
        data = [{"m": "2024-01", "v": 1}, {"m": "2024-02", "v": 2}]
        result = normalize_labeled_temporal(data, "m")
        assert result[0]["m"] == "2024-01-01"
        assert result[1]["m"] == "2024-02-01"

    def test_mon_yyyy_normalized_to_iso(self) -> None:
        data = [{"m": "Jan 2024", "v": 1}, {"m": "Feb 2024", "v": 2}]
        result = normalize_labeled_temporal(data, "m")
        assert result[0]["m"] == "2024-01-01"
        assert result[1]["m"] == "2024-02-01"

    def test_mm_yyyy_normalized_to_iso(self) -> None:
        data = [{"m": "01/2024", "v": 1}, {"m": "03/2024", "v": 2}]
        result = normalize_labeled_temporal(data, "m")
        assert result[0]["m"] == "2024-01-01"
        assert result[1]["m"] == "2024-03-01"

    def test_q_yyyy_normalized_to_iso(self) -> None:
        data = [{"m": "Q1 2024", "v": 1}, {"m": "Q2 2024", "v": 2}]
        result = normalize_labeled_temporal(data, "m")
        assert result[0]["m"] == "2024-01-01"
        assert result[1]["m"] == "2024-04-01"

    def test_yyyy_q_normalized_to_iso(self) -> None:
        data = [{"m": "2024Q1", "v": 1}, {"m": "2024Q2", "v": 2}]
        result = normalize_labeled_temporal(data, "m")
        assert result[0]["m"] == "2024-01-01"
        assert result[1]["m"] == "2024-04-01"

    def test_fy_normalized_to_iso(self) -> None:
        data = [{"m": "FY2023", "v": 1}, {"m": "FY2024", "v": 2}]
        result = normalize_labeled_temporal(data, "m")
        assert result[0]["m"] == "2023-01-01"
        assert result[1]["m"] == "2024-01-01"

    def test_mixed_yyyy_mm_and_mon_yyyy_raises(self) -> None:
        data = [{"m": "2024-01", "v": 1}, {"m": "Feb 2024", "v": 2}]
        with pytest.raises(ValueError, match="mixed label"):
            normalize_labeled_temporal(data, "m")

    def test_mixed_yyyy_mm_and_iso_date_raises(self) -> None:
        data = [{"m": "2024-01", "v": 1}, {"m": "2024-02-01", "v": 2}]
        with pytest.raises(ValueError, match="mixed label"):
            normalize_labeled_temporal(data, "m")

    def test_none_preserved_with_yyyy_mm(self) -> None:
        data = [{"m": "2024-01", "v": 1}, {"m": None, "v": 2}]
        result = normalize_labeled_temporal(data, "m")
        assert result[0]["m"] == "2024-01-01"
        assert result[1]["m"] is None


class TestNormalizeLabeledTemporalYearShaped:
    """Year-shaped x values (INTEGER or bare 4-digit VARCHAR) normalize to ISO."""

    def test_integer_years_normalized_to_iso(self) -> None:
        data = [{"y": 2014, "v": 1}, {"y": 2015, "v": 2}]
        result = normalize_labeled_temporal(data, "y")
        assert result[0]["y"] == "2014-01-01"
        assert result[1]["y"] == "2015-01-01"

    def test_string_years_normalized_to_iso(self) -> None:
        data = [{"y": "2014", "v": 1}, {"y": "2015", "v": 2}]
        result = normalize_labeled_temporal(data, "y")
        assert result[0]["y"] == "2014-01-01"
        assert result[1]["y"] == "2015-01-01"

    def test_normalized_years_detect_as_year_time_unit(self) -> None:
        data = [{"y": 2014, "v": 1}, {"y": 2015, "v": 2}]
        result = normalize_labeled_temporal(data, "y")
        assert detect_time_unit([row["y"] for row in result]) == "year"

    def test_non_year_integers_unchanged(self) -> None:
        data = [{"y": 1, "v": 1}, {"y": 2, "v": 2}]
        result = normalize_labeled_temporal(data, "y")
        assert result == data

    def test_none_preserved_with_integer_years(self) -> None:
        data = [{"y": 2014, "v": 1}, {"y": None, "v": 2}]
        result = normalize_labeled_temporal(data, "y")
        assert result[0]["y"] == "2014-01-01"
        assert result[1]["y"] is None


class TestOrdinalAxisValues:
    """ordinal_axis_values must return JSON-safe strings, not date/datetime objects."""

    def test_date_objects_return_iso_strings(self) -> None:
        rows = [{"d": dt.date(2024, 1, 1), "v": 1}, {"d": dt.date(2024, 1, 2), "v": 2}]
        result = ordinal_axis_values(rows, "d")
        assert result == ["2024-01-01", "2024-01-02"]
        assert all(isinstance(v, str) for v in result)

    def test_datetime_objects_return_iso_strings(self) -> None:
        rows = [
            {"d": dt.datetime(2024, 1, 1, 0, 0, 0), "v": 1},
            {"d": dt.datetime(2024, 1, 2, 0, 0, 0), "v": 2},
        ]
        result = ordinal_axis_values(rows, "d")
        assert result is not None
        assert all(isinstance(v, str) for v in result)
        assert "T" in result[0]

    def test_iso_strings_pass_through_unchanged(self) -> None:
        rows = [{"d": "2024-01-01", "v": 1}, {"d": "2024-01-02", "v": 2}]
        result = ordinal_axis_values(rows, "d")
        assert result == ["2024-01-01", "2024-01-02"]
