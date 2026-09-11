"""A row whose date does not sit on a bucket start still plots.

``complete_ordinal_time_series`` enumerates bucket STARTS and looks each row up
by key. When the lookup key was the row's own raw date, every cadence that
reports a period by its LAST instant — ``LAST_DAY(month)`` month-ends, a fixed
day-of-month, quarter-ends, year-ends, fiscal year-ends — matched no enumerated
bucket, so every row was replaced by a synthesized null and the chart rendered
blank while the axis drew a complete, plausible ladder.

The rule pinned here is grain-general, not a month-end carve-out: a row belongs
to the bucket it falls inside, for every ``BUCKETED_CALENDAR_UNITS`` grain.
"""

from __future__ import annotations

import calendar
import datetime as dt

import pytest

from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_render import ERR_GAP_FILL_BUCKET_COLLISION
from dbt_charts.core.render.chart.time_unit_detect import complete_ordinal_time_series


def _fill(
    rows: list[dict[str, object]], time_unit: str, fiscal_year_start_month: int = 1
) -> list[dict[str, object]]:
    return complete_ordinal_time_series(
        rows, "d", time_unit, [], "null", fiscal_year_start_month
    )


def _month_ends(n: int, year: int = 2025) -> list[dict[str, object]]:
    return [
        {
            "d": f"{year}-{m:02d}-{calendar.monthrange(year, m)[1]}",
            "v": 100000 + i * 5000,
        }
        for i, m in enumerate(range(1, n + 1))
    ]


class TestNonBucketStartDatesPlot:
    def test_month_end_dates_keep_every_row(self) -> None:
        result = _fill(_month_ends(11), "yearmonth")
        assert len(result) == 11
        assert [r["v"] for r in result] == [100000 + i * 5000 for i in range(11)]
        assert result[0]["d"] == "2025-01-01"
        assert result[-1]["d"] == "2025-11-01"

    def test_month_start_dates_are_unchanged(self) -> None:
        rows: list[dict[str, object]] = [
            {"d": f"2025-{m:02d}-01", "v": m} for m in range(1, 12)
        ]
        result = _fill(rows, "yearmonth")
        assert len(result) == 11
        assert [r["v"] for r in result] == list(range(1, 12))

    def test_a_fixed_day_of_month_keeps_every_row(self) -> None:
        rows: list[dict[str, object]] = [
            {"d": f"2025-{m:02d}-15", "v": m} for m in range(1, 12)
        ]
        result = _fill(rows, "yearmonth")
        assert len(result) == 11
        assert [r["v"] for r in result] == list(range(1, 12))
        assert [r["d"] for r in result] == [f"2025-{m:02d}-01" for m in range(1, 12)]

    def test_quarter_end_dates_keep_every_row(self) -> None:
        rows: list[dict[str, object]] = [
            {"d": d, "v": i}
            for i, d in enumerate(
                ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
            )
        ]
        result = _fill(rows, "yearquarter")
        assert [r["d"] for r in result] == [
            "2025-01-01",
            "2025-04-01",
            "2025-07-01",
            "2025-10-01",
        ]
        assert [r["v"] for r in result] == [0, 1, 2, 3]

    def test_year_end_dates_keep_every_row(self) -> None:
        rows: list[dict[str, object]] = [
            {"d": f"{y}-12-31", "v": y} for y in (2023, 2024, 2025)
        ]
        result = _fill(rows, "year")
        assert [r["d"] for r in result] == ["2023-01-01", "2024-01-01", "2025-01-01"]
        assert [r["v"] for r in result] == [2023, 2024, 2025]

    def test_fiscal_year_end_dates_keep_every_row(self) -> None:
        """An April-anchored fiscal year reported at its last day (March 31)."""
        rows: list[dict[str, object]] = [
            {"d": f"{y}-03-31", "v": y} for y in (2024, 2025, 2026)
        ]
        result = _fill(rows, "year", fiscal_year_start_month=4)
        assert [r["d"] for r in result] == ["2023-04-01", "2024-04-01", "2025-04-01"]
        assert [r["v"] for r in result] == [2024, 2025, 2026]

    def test_datetime_objects_off_the_bucket_start_keep_every_row(self) -> None:
        rows: list[dict[str, object]] = [
            {"d": dt.datetime(2025, m, 28, 23, 59, 59), "v": m} for m in range(1, 6)
        ]
        result = _fill(rows, "yearmonth")
        assert [r["d"] for r in result] == [f"2025-{m:02d}-01" for m in range(1, 6)]
        assert [r["v"] for r in result] == [1, 2, 3, 4, 5]

    def test_a_missing_month_is_still_synthesized(self) -> None:
        rows: list[dict[str, object]] = [
            {"d": "2025-01-31", "v": 1},
            {"d": "2025-03-31", "v": 3},
        ]
        result = _fill(rows, "yearmonth")
        assert [r["d"] for r in result] == ["2025-01-01", "2025-02-01", "2025-03-01"]
        assert [r["v"] for r in result] == [1, None, 3]

    def test_weeks_anchored_off_monday_keep_every_row(self) -> None:
        """Sunday-anchored weekly data with a mid-week straggler.

        The week ladder has no absolute day 1, so it is anchored on the first
        bucket; a row inside a week belongs to that week either way.
        """
        rows: list[dict[str, object]] = [
            {"d": "2025-01-05", "v": 1},
            {"d": "2025-01-12", "v": 2},
            {"d": "2025-01-22", "v": 3},
        ]
        result = _fill(rows, "yearweek")
        assert [r["d"] for r in result] == ["2025-01-05", "2025-01-12", "2025-01-19"]
        assert [r["v"] for r in result] == [1, 2, 3]

    def test_two_rows_in_one_bucket_raise_instead_of_disappearing(self) -> None:
        """Daily rows under an authored monthly grain are ambiguous, not aggregable."""
        rows: list[dict[str, object]] = [
            {"d": "2025-01-05", "v": 1},
            {"d": "2025-01-19", "v": 2},
        ]
        with pytest.raises(ChartDataError) as excinfo:
            _fill(rows, "yearmonth")
        assert excinfo.value.code is ERR_GAP_FILL_BUCKET_COLLISION


class TestSeriesCrossJoinStillMatches:
    def test_month_end_dates_with_a_color_series(self) -> None:
        rows: list[dict[str, object]] = [
            {"d": "2025-01-31", "s": "a", "v": 1},
            {"d": "2025-01-31", "s": "b", "v": 2},
            {"d": "2025-02-28", "s": "a", "v": 3},
        ]
        result = complete_ordinal_time_series(rows, "d", "yearmonth", ["s"], "null", 1)
        assert [(r["d"], r["s"], r["v"]) for r in result] == [
            ("2025-01-01", "a", 1),
            ("2025-01-01", "b", 2),
            ("2025-02-01", "a", 3),
            ("2025-02-01", "b", None),
        ]
