"""Tests for fill: engine fills missing time buckets on ordinal time-unit x-axes.

All triggering conditions tested here produce ordinal bucketed-time charts.
The gap-fill helper complete_ordinal_time_series is tested directly in
test_detect_time_unit.py; these tests verify integration through profile /
render_standard_vega_spec.
"""

from __future__ import annotations

import datetime as dt

import pytest

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
    DimensionLabelStylePatch,
    LineChartStylePatch,
    XScaleStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_render import ERR_GAP_FILL_BUCKET_COLLISION
from dbt_charts.core.render.chart.time_unit_detect import complete_ordinal_time_series
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_RS, _BOARD_CTX = resolve_style_and_context(get_theme_style())

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _jan_feb_may_data() -> list[dict]:
    """Single series, three months with Mar/Apr missing."""
    return [
        {"month": "2024-01-01", "revenue": 100},
        {"month": "2024-02-01", "revenue": 200},
        {"month": "2024-05-01", "revenue": 500},
    ]


def _weekly_data_with_gap() -> list[dict]:
    """Week 1 and week 3; week 2 missing."""
    return [
        {"week": "2024-01-01", "signups": 10},  # 2024-W01
        {"week": "2024-01-15", "signups": 30},  # 2024-W03
    ]


def _stacked_weekly_data() -> list[dict]:
    """Two sources; week 2 completely missing for source B."""
    return [
        {"week": "2024-01-01", "source": "A", "signups": 10},
        {"week": "2024-01-01", "source": "B", "signups": 5},
        {"week": "2024-01-08", "source": "A", "signups": 20},
        # 2024-01-08 / source B intentionally absent
        {"week": "2024-01-15", "source": "A", "signups": 15},
        {"week": "2024-01-15", "source": "B", "signups": 8},
    ]


def _grouped_weekly_data() -> list[dict]:
    """Same shape as _stacked_weekly_data — week 2 / source B missing."""
    return _stacked_weekly_data()


def _chart_bar(
    x: str = "month",
    y: str = "revenue",
    color: str | None = None,
    style: BarChartStylePatch | None = None,
    **kwargs: object,
) -> Chart:
    return BarChart(
        id="gap_test_bar", type="bar", x=x, y=y, color=color, style=style, **kwargs
    )


def _chart_line(
    x: str = "week",
    y: str = "signups",
    style: LineChartStylePatch | None = None,
) -> Chart:
    return LineChart(id="gap_test_line", type="line", x=x, y=y, style=style)


def _resolve_and_render(chart: Chart, data: list[dict]) -> dict:
    resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
    return render_resolved_chart(resolved, data, _BOARD_RS).payload


# ── Unit tests for complete_ordinal_time_series ────────────────────────────────


class TestCompleteOrdinalTimeSeries:
    """Direct tests of the gap-fill helper function."""

    def test_single_series_yearmonth_fills_missing(self) -> None:
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "null", fiscal_year_start_month=1
        )
        months = [r["month"] for r in result]
        assert "2024-03-01" in months, f"Mar missing from {months}"
        assert "2024-04-01" in months, f"Apr missing from {months}"

    def test_single_series_yearmonth_null_synthetic_measures(self) -> None:
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "null", fiscal_year_start_month=1
        )
        mar_row = next(r for r in result if r["month"] == "2024-03-01")
        assert mar_row["revenue"] is None, (
            f"Expected null fill, got {mar_row['revenue']}"
        )

    def test_single_series_yearmonth_zero_fill_for_zero(self) -> None:
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "zero", fiscal_year_start_month=1
        )
        mar_row = next(r for r in result if r["month"] == "2024-03-01")
        assert mar_row["revenue"] == 0, f"Expected zero fill, got {mar_row['revenue']}"

    def test_existing_rows_preserved(self) -> None:
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "null", fiscal_year_start_month=1
        )
        jan = next(r for r in result if r["month"] == "2024-01-01")
        assert jan["revenue"] == 100

    def test_empty_dataset_returns_unchanged(self) -> None:
        result = complete_ordinal_time_series(
            [], "month", "yearmonth", [], "null", fiscal_year_start_month=1
        )
        assert result == []

    def test_multi_series_cross_join(self) -> None:
        data = _stacked_weekly_data()
        result = complete_ordinal_time_series(
            data, "week", "yearweek", ["source"], "null", fiscal_year_start_month=1
        )
        weeks = sorted({r["week"] for r in result})
        sources = sorted({r["source"] for r in result})
        # Every (week, source) combination must be present
        for w in weeks:
            for s in sources:
                rows = [r for r in result if r["week"] == w and r["source"] == s]
                assert len(rows) == 1, (
                    f"Expected exactly 1 row for ({w}, {s}), got {rows}"
                )

    def test_multi_series_missing_row_has_null_measure(self) -> None:
        data = _stacked_weekly_data()
        result = complete_ordinal_time_series(
            data, "week", "yearweek", ["source"], "null", fiscal_year_start_month=1
        )
        # 2024-01-08 / source B was absent in source data
        missing = next(
            (r for r in result if r["week"] == "2024-01-08" and r["source"] == "B"),
            None,
        )
        assert missing is not None, "Synthesized row for (week2, B) not found"
        assert missing["signups"] is None

    def test_determinism_order(self) -> None:
        """Synthesized rows ordered (bucket asc, dim asc)."""
        data = _stacked_weekly_data()
        r1 = complete_ordinal_time_series(
            data, "week", "yearweek", ["source"], "null", fiscal_year_start_month=1
        )
        r2 = complete_ordinal_time_series(
            data, "week", "yearweek", ["source"], "null", fiscal_year_start_month=1
        )
        assert [row["week"] for row in r1] == [row["week"] for row in r2]
        assert [row.get("source") for row in r1] == [row.get("source") for row in r2]

    def test_categories_not_invented(self) -> None:
        """Only dim values appearing in the data are cross-joined."""
        data = [
            {"week": "2024-01-01", "source": "A", "signups": 10},
            {"week": "2024-01-15", "source": "A", "signups": 15},
        ]
        result = complete_ordinal_time_series(
            data, "week", "yearweek", ["source"], "null", fiscal_year_start_month=1
        )
        sources = {r.get("source") for r in result}
        assert sources == {"A"}, f"Unexpected sources: {sources}"

    def test_yearquarter_step(self) -> None:
        data = [
            {"quarter": "2024-01-01", "revenue": 100},
            {"quarter": "2024-10-01", "revenue": 400},
        ]
        result = complete_ordinal_time_series(
            data, "quarter", "yearquarter", [], "null", fiscal_year_start_month=1
        )
        quarters = [r["quarter"] for r in result]
        assert "2024-04-01" in quarters, "Q2 missing"
        assert "2024-07-01" in quarters, "Q3 missing"

    def test_year_step(self) -> None:
        data = [
            {"yr": "2022-01-01", "revenue": 100},
            {"yr": "2024-01-01", "revenue": 300},
        ]
        result = complete_ordinal_time_series(
            data, "yr", "year", [], "null", fiscal_year_start_month=1
        )
        years = [r["yr"] for r in result]
        assert "2023-01-01" in years, "2023 missing"

    def test_yearmonthdate_step(self) -> None:
        data = [
            {"day": "2024-01-01", "revenue": 1},
            {"day": "2024-01-03", "revenue": 3},
        ]
        result = complete_ordinal_time_series(
            data, "day", "yearmonthdate", [], "null", fiscal_year_start_month=1
        )
        days = [r["day"] for r in result]
        assert "2024-01-02" in days, "2024-01-02 missing"


class TestGapFillBucketCollision:
    """Two rows differing only by time-of-day collapse to the same
    `_ordinal_bucket_key` and collide in `complete_ordinal_time_series`'s
    `existing` lookup. `validate_preaggregated_data` cannot catch this: it
    runs before gap-fill, on the still-distinct raw x values. A collision
    cannot happen on legitimately grain-aligned data, so raising here costs
    nothing on valid input.
    """

    def test_datetime_objects_same_day_raise(self) -> None:
        rows = [
            {"day": dt.datetime(2024, 1, 1, 9, 0, 0), "revenue": 100},
            {"day": dt.datetime(2024, 1, 1, 15, 0, 0), "revenue": 500},
            {"day": dt.datetime(2024, 1, 2, 9, 0, 0), "revenue": 200},
        ]
        with pytest.raises(ChartDataError) as exc_info:
            complete_ordinal_time_series(
                rows, "day", "yearmonthdate", [], "null", fiscal_year_start_month=1
            )
        assert exc_info.value.code is ERR_GAP_FILL_BUCKET_COLLISION, (
            f"Expected ERR-GAP-FILL-BUCKET-COLLISION but got {exc_info.value.code!r}"
        )

    def test_iso_datetime_strings_same_day_raise(self) -> None:
        rows = [
            {"day": "2024-01-01T09:00:00", "revenue": 100},
            {"day": "2024-01-01T15:00:00", "revenue": 500},
            {"day": "2024-01-02T09:00:00", "revenue": 200},
        ]
        with pytest.raises(ChartDataError) as exc_info:
            complete_ordinal_time_series(
                rows, "day", "yearmonthdate", [], "null", fiscal_year_start_month=1
            )
        assert exc_info.value.code is ERR_GAP_FILL_BUCKET_COLLISION, (
            f"Expected ERR-GAP-FILL-BUCKET-COLLISION but got {exc_info.value.code!r}"
        )

    def test_dim_field_collision_names_the_dim_in_message(self) -> None:
        """`dim_fields = [color_field]` (`_channels.py`) is the production-common
        shape — two rows sharing both bucket and dim value must still raise, and
        the message must name the colliding dim, not just the bucket.
        """
        rows = [
            {
                "day": dt.datetime(2024, 1, 1, 9, 0, 0),
                "region": "west",
                "revenue": 100,
            },
            {
                "day": dt.datetime(2024, 1, 1, 15, 0, 0),
                "region": "west",
                "revenue": 500,
            },
            {"day": dt.datetime(2024, 1, 2, 9, 0, 0), "region": "west", "revenue": 200},
        ]
        with pytest.raises(ChartDataError) as exc_info:
            complete_ordinal_time_series(
                rows,
                "day",
                "yearmonthdate",
                ["region"],
                "null",
                fiscal_year_start_month=1,
            )
        assert exc_info.value.code is ERR_GAP_FILL_BUCKET_COLLISION, (
            f"Expected ERR-GAP-FILL-BUCKET-COLLISION but got {exc_info.value.code!r}"
        )
        assert "region='west'" in str(exc_info.value), (
            f"Expected the colliding dim in the message, got: {exc_info.value}"
        )


# ── Integration tests through render pipeline ──────────────────────────────────


class TestGapFillIntegration:
    """Gap-fill wires into render_resolved_chart; verify via rendered VL spec data."""

    def test_column_chart_has_five_slots_in_vl_data(self) -> None:
        """Jan/Feb/May data → 5 rows in VL dataset (Mar/Apr filled)."""
        chart = BarChart(id="t", type="bar", x="month", y="revenue")
        data = _jan_feb_may_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        months = [r["month"] for r in vl_data]
        assert len(vl_data) == 5, f"Expected 5 rows, got {len(vl_data)}: {months}"
        assert "2024-03-01" in months, f"Mar absent: {months}"
        assert "2024-04-01" in months, f"Apr absent: {months}"

    def test_wide_bar_chart_has_five_slots_in_vl_data(self) -> None:
        """Wide (y: [a, b]) bar chart gets the same bucket gap-fill as long-form.

        Regression: BarEmitter.emit() used to dispatch wide charts to
        _emit_wide_bar and return before the gap_fill_ordinal_time call,
        so a wide chart with a missing month silently dropped that bucket
        while an equivalent color-series chart on the same data would not.
        """
        chart = BarChart(id="t", type="bar", x="month", y=["revenue", "cost"])
        data = [
            {"month": "2024-01-01", "revenue": 100, "cost": 80},
            {"month": "2024-02-01", "revenue": 200, "cost": 90},
            {"month": "2024-05-01", "revenue": 500, "cost": 150},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        months = [r["month"] for r in vl_data]
        assert len(vl_data) == 5, f"Expected 5 rows, got {len(vl_data)}: {months}"
        assert "2024-03-01" in months, f"Mar absent: {months}"
        assert "2024-04-01" in months, f"Apr absent: {months}"

    def test_line_chart_no_gap_fill_for_default_temporal_scale(self) -> None:
        """Line chart, no style override → default temporal scale; no synthetic rows.

        Line/area default to a continuous temporal x-scale for a bucketed
        calendar grain (any grain, per build_cartesian_x_encoding), which
        already draws real data points at their true positions — VL needs no
        synthesized rows to "fill" a gap on a continuous scale. Regression for
        the disconnected-dots bug: gap-fill used to run before the mark-type
        default was known and always injected null-valued rows, which broke
        the line path at every synthetic gap.
        """
        chart = LineChart(id="t", type="line", x="week", y="signups")
        data = _weekly_data_with_gap()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        # 2 real weeks only (W01, W03) — week 2 is not synthesized.
        assert len(vl_data) == 2, f"Expected 2 rows (no synthesis), got {vl_data}"
        assert all(r["signups"] is not None for r in vl_data)

    def test_line_chart_year_grain_gap_no_synthetic_rows(self) -> None:
        """Plain line chart, year-grain data with a gap → zero synthesized rows.

        Reproduces the reported bug directly: 2010/2015/2020 (5yr gaps), no
        style override. Before the fix, gap_fill_ordinal_time fired
        unconditionally for any BUCKETED_CALENDAR_UNITS grain regardless of
        mark type, injecting null rows that broke the line into disconnected
        dots even though the axis correctly resolves to continuous temporal.
        """
        chart = LineChart(id="t", type="line", x="year", y="revenue")
        data = [
            {"year": "2010-01-01", "revenue": 100},
            {"year": "2015-01-01", "revenue": 150},
            {"year": "2020-01-01", "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3, f"Expected 3 rows (no synthesis), got {vl_data}"
        assert all(r["revenue"] is not None for r in vl_data)

    def test_area_chart_year_grain_gap_no_synthetic_rows(self) -> None:
        """Plain area chart, year-grain data with a gap → zero synthesized rows."""
        chart = AreaChart(id="t", type="area", x="year", y="revenue")
        data = [
            {"year": "2010-01-01", "revenue": 100},
            {"year": "2015-01-01", "revenue": 150},
            {"year": "2020-01-01", "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3, f"Expected 3 rows (no synthesis), got {vl_data}"
        assert all(r["revenue"] is not None for r in vl_data)

    def test_line_chart_labeled_quarter_x_normalizes_without_gap_fill(self) -> None:
        """Labeled quarter buckets ("Q1 2020"), no gap → still ISO-normalized in spec.data.

        Regression for a second bug the gap-fill fix uncovered: normalization
        stamping onto spec.data was previously piggybacking on gap-fill always
        firing for any bucketed-calendar grain. With gap-fill now skipped for
        this fully-implicit, no-gap case, normalize_labeled_temporal's output
        must still be stamped onto spec.data on its own, or the raw
        "Q1 2020"-style labels leak into a temporal encoding and the chart
        renders nothing.
        """
        chart = LineChart(id="t", type="line", x="quarter", y="revenue")
        data = [
            {"quarter": "Q1 2020", "revenue": 100},
            {"quarter": "Q2 2020", "revenue": 150},
            {"quarter": "Q3 2020", "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        assert spec.get("encoding", {}).get("x", {}).get("type") == "temporal"
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3
        for row in vl_data:
            assert row["quarter"] != "Q1 2020", (
                f"raw label leaked into spec.data unnormalized: {row}"
            )

    def test_area_chart_labeled_quarter_x_normalizes_without_gap_fill(self) -> None:
        """Area equivalent of the labeled-quarter normalization regression above."""
        chart = AreaChart(id="t", type="area", x="quarter", y="revenue")
        data = [
            {"quarter": "Q1 2020", "revenue": 100},
            {"quarter": "Q2 2020", "revenue": 150},
            {"quarter": "Q3 2020", "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        assert spec.get("encoding", {}).get("x", {}).get("type") == "temporal"
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3
        for row in vl_data:
            assert row["quarter"] != "Q1 2020", (
                f"raw label leaked into spec.data unnormalized: {row}"
            )

    def test_line_chart_datetime_x_no_gap_canonicalized_to_date_only_iso(self) -> None:
        """Naive datetime.datetime x (no gap) must canonicalize to date-only ISO.

        Regression for a second CRITICAL: complete_ordinal_time_series always
        rewrote x to a date-only ISO string (e.g. "2024-01-01"), even for real
        (non-synthetic) rows. The gap-fill skip branch reproduced its sort but
        not its canonicalization, so a naive datetime like
        datetime(2024, 1, 1, 0, 0, 0) reached spec.data unchanged and later
        stringified as "2024-01-01 00:00:00" — not ISO-8601, which Vega's JS
        Date parser reads as LOCAL time, shifting every point by the runtime's
        UTC offset (a year-grain chart shifts by a full year in some zones).
        """
        chart = LineChart(id="t", type="line", x="month", y="revenue")
        data = [
            {"month": dt.datetime(2024, 1, 1, 0, 0, 0), "revenue": 100},
            {"month": dt.datetime(2024, 3, 1, 0, 0, 0), "revenue": 150},
            {"month": dt.datetime(2024, 6, 1, 0, 0, 0), "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        assert spec.get("encoding", {}).get("x", {}).get("type") == "temporal"
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3
        months = sorted(str(r["month"]) for r in vl_data)
        assert months == [
            "2024-01-01",
            "2024-03-01",
            "2024-06-01",
        ], f"expected date-only ISO strings, got {months}"

    def test_line_chart_iso_datetime_string_x_no_gap_canonicalized(self) -> None:
        """ISO datetime *strings* with a "T" time component (no gap) must also
        canonicalize to date-only ISO — not just date/datetime objects.

        Same class of bug as the datetime-object case above, for the string
        shape a warehouse-cached query result can carry (DATE_LIKE_PATTERNS
        explicitly documents this format).
        """
        chart = LineChart(id="t", type="line", x="month", y="revenue")
        data = [
            {"month": "2024-01-01T00:00:00", "revenue": 100},
            {"month": "2024-03-01T00:00:00", "revenue": 150},
            {"month": "2024-06-01T00:00:00", "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        assert spec.get("encoding", {}).get("x", {}).get("type") == "temporal"
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3
        months = sorted(str(r["month"]) for r in vl_data)
        assert months == [
            "2024-01-01",
            "2024-03-01",
            "2024-06-01",
        ], f"expected date-only ISO strings, got {months}"

    def test_line_chart_missing_month_opener_week_still_gets_label_tick(self) -> None:
        """A month label tick must survive even when that month's exact
        opening week has no data row.

        Regression for a third CRITICAL: skipping gap-fill synthesis on the
        temporal path also silently dropped calendar label ticks, because
        label-cadence "opener" derivation used to rely on
        complete_ordinal_time_series always scaffolding a row for every
        bucket (so an opener week always existed even with no real data).
        2024-02-05 (the only week whose start falls within February's first
        7 days) is intentionally absent below.
        """
        mondays = [
            "2024-01-01",
            "2024-01-08",
            "2024-01-15",
            "2024-01-22",
            "2024-01-29",
            # "2024-02-05" intentionally absent — the only Feb opener week
            "2024-02-12",
            "2024-02-19",
            "2024-02-26",
            "2024-03-04",
            "2024-03-11",
            "2024-03-18",
            "2024-03-25",
        ]
        data = [{"week": d, "signups": i} for i, d in enumerate(mondays)]
        style = LineChartStylePatch(
            axis_x=AxisXStylePatch(
                labels=DimensionLabelStylePatch(time_unit="yearmonth")
            )
        )
        chart = LineChart(id="t", type="line", x="week", y="signups", style=style)
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        axis_values = (
            spec.get("encoding", {}).get("x", {}).get("axis", {}).get("values", [])
        )
        assert any(str(v).startswith("2024-02") for v in axis_values), (
            f"February must still get a label tick despite its opener week "
            f"being absent from the data: {axis_values}"
        )

    def test_horizontal_bar_dense_monthly_grain_still_gets_missing_bucket(self) -> None:
        """Horizontal bar with >60 monthly buckets must still gap-fill a gap.

        Regression for a fourth CRITICAL: gap_fill_ordinal_time's temporal
        skip is decided by resolve_cartesian_x_type, which only describes the
        axis _emit_vertical/build_cartesian_x_encoding actually resolve.
        _emit_horizontal renders chart.x as a plain nominal category y-axis
        that never goes through that resolution and can never become a
        continuous temporal scale — so it always needs the full ordinal
        scaffold, regardless of what the vertical-path density gate (>60
        distinct buckets forces "temporal" there) would say for the same
        data. Without resolves_cartesian_x=False for horizontal bar, a
        missing month silently vanishes instead of rendering as an empty
        band.
        """
        months = [f"{2018 + i // 12}-{(i % 12) + 1:02d}-01" for i in range(70)]
        missing = months[42]
        months = [m for m in months if m != missing]
        data = [{"month": m, "revenue": i} for i, m in enumerate(months)]
        style = BarChartStylePatch(orientation="horizontal")
        chart = BarChart(id="t", type="bar", x="month", y="revenue", style=style)
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 70, f"Expected 70 rows (gap-filled), got {len(vl_data)}"
        assert any(r.get("month") == missing for r in vl_data), (
            f"Missing month {missing} must still get a synthesized row on a "
            f"horizontal bar's nominal category axis: {vl_data}"
        )

    def test_stacked_column_all_source_week_combos_present(self) -> None:
        """Stacked column with color=source → every (week, source) tuple present."""
        chart = BarChart(id="t", type="bar", x="week", y="signups", color="source")
        data = _stacked_weekly_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        weeks = sorted({r["week"] for r in vl_data})
        sources = sorted({r["source"] for r in vl_data})
        for w in weeks:
            for s in sources:
                matching = [r for r in vl_data if r["week"] == w and r["source"] == s]
                assert len(matching) == 1, f"Missing ({w}, {s})"

    def test_grouped_column_all_source_week_combos_present(self) -> None:
        """Grouped column (stack: none) → every (week, source) combo present."""
        chart = BarChart(
            id="t", type="bar", x="week", y="signups", color="source", stack="none"
        )
        data = _grouped_weekly_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        weeks = sorted({r["week"] for r in vl_data})
        sources = sorted({r["source"] for r in vl_data})
        for w in weeks:
            for s in sources:
                matching = [r for r in vl_data if r["week"] == w and r["source"] == s]
                assert len(matching) == 1, f"Missing ({w}, {s})"

    def test_empty_dataset_does_not_fire(self) -> None:
        """Empty dataset → no synthesized rows; chart renders the empty-data path."""
        chart = BarChart(id="t", type="bar", x="month", y="revenue")
        data: list[dict] = []
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert vl_data == [], f"Empty dataset should produce empty spec data: {vl_data}"

    def test_gap_handling_zero_produces_zero_rows(self) -> None:
        """`fill: zero` → zero-valued rows at missing buckets."""
        style = BarChartStylePatch(axis_x=AxisXStylePatch(fill="zero"))
        chart = BarChart(id="t", type="bar", x="month", y="revenue", style=style)
        data = _jan_feb_may_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        mar = next(r for r in vl_data if r["month"] == "2024-03-01")
        assert mar["revenue"] == 0, f"Expected zero fill, got {mar['revenue']}"

    def test_complete_ordinal_time_series_normalizes_existing_date_rows(self) -> None:
        """Existing date-object rows use the same ISO key as synthesized rows."""
        data = [
            {"month": dt.date(2024, 1, 1), "series": "A", "revenue": 100},
            {"month": "2024-03-01", "series": "A", "revenue": 300},
        ]

        filled = complete_ordinal_time_series(
            data, "month", "yearmonth", ["series"], "zero", fiscal_year_start_month=1
        )

        assert [row["month"] for row in filled] == [
            "2024-01-01",
            "2024-02-01",
            "2024-03-01",
        ]
        assert [row["revenue"] for row in filled] == [100, 0, 300]

    def test_complete_ordinal_time_series_normalizes_existing_datetime_rows(
        self,
    ) -> None:
        """Existing datetime rows use calendar-bucket keys for gap-fill lookup."""
        data = [
            {"month": dt.datetime(2024, 1, 1), "series": "A", "revenue": 100},
            {"month": "2024-03-01", "series": "A", "revenue": 300},
        ]

        filled = complete_ordinal_time_series(
            data, "month", "yearmonth", ["series"], "zero", fiscal_year_start_month=1
        )

        assert [row["month"] for row in filled] == [
            "2024-01-01",
            "2024-02-01",
            "2024-03-01",
        ]
        assert [row["revenue"] for row in filled] == [100, 0, 300]

    def test_temporal_escape_hatch_no_gap_fill(self) -> None:
        """axis_x.type: temporal → trigger does NOT fire; data unchanged."""
        style = BarChartStylePatch(axis_x=AxisXStylePatch(type="temporal"))
        chart = BarChart(id="t", type="bar", x="month", y="revenue", style=style)
        data = _jan_feb_may_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        # Temporal path: data flows through unchanged (3 rows)
        assert len(vl_data) == 3, f"Temporal escape hatch must not gap-fill: {vl_data}"

    def test_scale_type_temporal_escape_hatch_no_gap_fill(self) -> None:
        """axis_x.scale.type: temporal is a second authored-temporal escape
        hatch build_cartesian_x_encoding honors (type_inference.py) alongside
        axis_x.type: temporal — gap_fill_ordinal_time must agree, or an author
        reaching for scale.type instead of type still gets null-filled rows on
        a scale that already renders continuous."""
        style = BarChartStylePatch(
            axis_x=AxisXStylePatch(
                scale=XScaleStylePatch(continuous={"type": "temporal"})
            )
        )
        chart = BarChart(id="t", type="bar", x="month", y="revenue", style=style)
        data = _jan_feb_may_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3, (
            f"scale.type escape hatch must not gap-fill: {vl_data}"
        )

    def test_non_bucketed_time_unit_no_gap_fill(self) -> None:
        """time_unit: none / absent → trigger does NOT fire."""
        style = BarChartStylePatch(axis_x=AxisXStylePatch(time_unit="none"))
        chart = BarChart(id="t", type="bar", x="month", y="revenue", style=style)
        data = _jan_feb_may_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 3, f"time_unit:none must not gap-fill: {vl_data}"

    def test_authored_time_unit_survives_mostly_unparseable_x_tail(self) -> None:
        """Authored ``time_unit`` must skip auto-detection entirely, even
        when >=10% of x values are unparseable (``detect_time_unit``'s own
        raise threshold). ``infer_vega_type_from_data`` only samples the
        first 10 rows, so 10 clean leading dates + 2 unparseable trailing
        values is exactly the "head looks like dates, tail doesn't" shape
        that used to reach ``detect_time_unit`` and raise despite the
        author having named the remedy (``style.axis_x.time_unit``)
        explicitly. Regression for a hoist that gated the auto-detect call
        on ``if x_field and data`` only, dropping the "author already set
        time_unit" gate ``gap_fill_ordinal_time`` itself still honors."""
        style = BarChartStylePatch(axis_x=AxisXStylePatch(time_unit="yearmonth"))
        chart = BarChart(id="t", type="bar", x="m", y="v", style=style)
        data = [{"m": f"2024-{i:02d}-01", "v": i} for i in range(1, 11)] + [
            {"m": "n/a", "v": 11},
            {"m": "unknown", "v": 12},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        # Must not raise.
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 10, (
            f"authored yearmonth must gap-fill the 10 parseable rows only "
            f"(unparseable rows are dropped, not synthesized): {vl_data}"
        )

    def test_non_time_series_no_gap_fill(self) -> None:
        """Categorical bar chart → trigger does NOT fire."""
        chart = BarChart(id="t", type="bar", x="category", y="revenue")
        data = [
            {"category": "A", "revenue": 100},
            {"category": "B", "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        assert len(vl_data) == 2


# ── Regression: categories-not-in-data caveat ─────────────────────────────────


class TestCategoryNotInDataCaveat:
    """Engine only cross-joins over categories that appear in the data window."""

    def test_synthetic_rows_use_only_observed_categories(self) -> None:
        data = [
            {"week": "2024-01-01", "source": "organic", "signups": 10},
            {"week": "2024-01-15", "source": "organic", "signups": 15},
            # "paid" source has zero rows in the data window
        ]
        result = complete_ordinal_time_series(
            data, "week", "yearweek", ["source"], "null", fiscal_year_start_month=1
        )
        sources = {r.get("source") for r in result}
        assert "paid" not in sources, "Engine must not invent unseen categories"
        assert sources == {"organic"}


# ── Tests for fill: interpolate-* ─────────────────────────────────────


class TestInterpolateGapHandling:
    """complete_ordinal_time_series with fill interpolate-* modes."""

    def test_single_series_interior_gap_linearly_interpolated(self) -> None:
        """Jan=100, Feb=200, May=500 → Mar and Apr linearly interpolated."""
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "linear", fiscal_year_start_month=1
        )
        # Mar is bucket index 2 out of 5 (0-based: Jan=0, Feb=1, Mar=2, Apr=3, May=4)
        # Feb=200, May=500; gap spans Mar and Apr (2 synthetic buckets).
        # Linear interpolation between bucket index 1 (Feb, 200) and bucket index 4 (May, 500):
        # step = (500 - 200) / (4 - 1) = 100
        # Mar = 200 + 1*100 = 300
        # Apr = 200 + 2*100 = 400
        rows_by_month = {r["month"]: r for r in result}
        assert "2024-03-01" in rows_by_month, "Mar should be synthesized"
        assert "2024-04-01" in rows_by_month, "Apr should be synthesized"
        assert rows_by_month["2024-03-01"]["revenue"] == pytest.approx(300.0)
        assert rows_by_month["2024-04-01"]["revenue"] == pytest.approx(400.0)

    def test_interpolate_preserves_existing_rows(self) -> None:
        """Original data rows are unchanged by interpolation."""
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "linear", fiscal_year_start_month=1
        )
        rows_by_month = {r["month"]: r for r in result}
        assert rows_by_month["2024-01-01"]["revenue"] == 100
        assert rows_by_month["2024-02-01"]["revenue"] == 200
        assert rows_by_month["2024-05-01"]["revenue"] == 500

    def test_leading_trailing_synthetic_buckets_stay_null(self) -> None:
        """Multi-series: synth rows before a series' first real point stay null.

        Series A spans Jan–Apr; series B only starts in Mar. The engine
        cross-joins the full [Jan, Apr] window with both series, so B gets
        Jan and Feb synthesized. Those lack a left anchor, so 'linear' must
        leave them null. Mar–Apr interior gap would be interpolated, but here
        B has real data in Mar and Apr so no interior null to fill.
        """
        data = [
            {"month": "2024-01-01", "series": "A", "revenue": 100},
            {"month": "2024-02-01", "series": "A", "revenue": 200},
            {"month": "2024-03-01", "series": "A", "revenue": 300},
            {"month": "2024-04-01", "series": "A", "revenue": 400},
            # B only starts in March — Jan and Feb will be synthetic leading rows
            {"month": "2024-03-01", "series": "B", "revenue": 30},
            {"month": "2024-04-01", "series": "B", "revenue": 40},
        ]
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", ["series"], "linear", fiscal_year_start_month=1
        )
        rows = {(r["month"], r["series"]): r for r in result}
        # Leading synthetic rows for B (no left anchor) must stay null
        assert rows[("2024-01-01", "B")]["revenue"] is None
        assert rows[("2024-02-01", "B")]["revenue"] is None
        # Real B rows are preserved
        assert rows[("2024-03-01", "B")]["revenue"] == 30
        assert rows[("2024-04-01", "B")]["revenue"] == 40

    def test_multi_series_interpolated_independently(self) -> None:
        """Each series group is interpolated independently (not across groups)."""
        # Two series: Core (100, ?, 400) and Growth (200, ?, 500)
        # The ? is Feb = the middle month. Core: Jan=100, Mar=400; Growth: Jan=200, Mar=500.
        data = [
            {"month": "2024-01-01", "segment": "Core", "revenue": 100},
            {"month": "2024-03-01", "segment": "Core", "revenue": 400},
            {"month": "2024-01-01", "segment": "Growth", "revenue": 200},
            {"month": "2024-03-01", "segment": "Growth", "revenue": 500},
        ]
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", ["segment"], "linear", fiscal_year_start_month=1
        )
        rows = {(r["month"], r["segment"]): r for r in result}
        # Core: Feb should be midpoint(100, 400) = 250
        core_feb = rows[("2024-02-01", "Core")]
        assert core_feb["revenue"] == pytest.approx(250.0)
        # Growth: Feb should be midpoint(200, 500) = 350
        growth_feb = rows[("2024-02-01", "Growth")]
        assert growth_feb["revenue"] == pytest.approx(350.0)

    def test_regression_zero_still_zero(self) -> None:
        """Regression: 'zero' mode still fills with 0 after interpolate is added."""
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "zero", fiscal_year_start_month=1
        )
        rows_by_month = {r["month"]: r for r in result}
        assert rows_by_month["2024-03-01"]["revenue"] == 0
        assert rows_by_month["2024-04-01"]["revenue"] == 0

    def test_step_after_forward_fill(self) -> None:
        """step-after (Looker): hold last observed value across interior gaps."""
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "step-after", fiscal_year_start_month=1
        )
        rows_by_month = {r["month"]: r for r in result}
        assert rows_by_month["2024-03-01"]["revenue"] == 200
        assert rows_by_month["2024-04-01"]["revenue"] == 200

    def test_step_before_uses_next_observed(self) -> None:
        """step-before (Looker): interior gaps take the upcoming observed value."""
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "step-before", fiscal_year_start_month=1
        )
        rows_by_month = {r["month"]: r for r in result}
        assert rows_by_month["2024-03-01"]["revenue"] == 500
        assert rows_by_month["2024-04-01"]["revenue"] == 500

    def test_step_after_leading_synthetic_stays_null(self) -> None:
        """step-after does not back-fill from a future anchor before the first observation."""
        data = [
            {"month": "2024-01-01", "series": "A", "revenue": 100},
            {"month": "2024-02-01", "series": "A", "revenue": 200},
            {"month": "2024-03-01", "series": "B", "revenue": 300},
            {"month": "2024-04-01", "series": "B", "revenue": 400},
        ]
        result = complete_ordinal_time_series(
            data,
            "month",
            "yearmonth",
            ["series"],
            "step-after",
            fiscal_year_start_month=1,
        )
        rows = {(r["month"], r["series"]): r for r in result}
        assert rows[("2024-01-01", "B")]["revenue"] is None
        assert rows[("2024-02-01", "B")]["revenue"] is None

    def test_step_before_trailing_synthetic_stays_null(self) -> None:
        """step-before does not forward-fill from a past anchor after the last observation."""
        data = [
            {"month": "2024-01-01", "series": "A", "revenue": 100},
            {"month": "2024-02-01", "series": "A", "revenue": 200},
            {"month": "2024-03-01", "series": "B", "revenue": 300},
            {"month": "2024-04-01", "series": "A", "revenue": 400},
        ]
        result = complete_ordinal_time_series(
            data,
            "month",
            "yearmonth",
            ["series"],
            "step-before",
            fiscal_year_start_month=1,
        )
        rows = {(r["month"], r["series"]): r for r in result}
        assert rows[("2024-04-01", "B")]["revenue"] is None

    def test_step_center_switches_at_midpoint(self) -> None:
        """step-center (Looker): switch to the right anchor at the gap midpoint."""
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "step-center", fiscal_year_start_month=1
        )
        rows_by_month = {r["month"]: r for r in result}
        assert rows_by_month["2024-03-01"]["revenue"] == 200
        assert rows_by_month["2024-04-01"]["revenue"] == 500

    def test_curve_smoothstep_between_anchors(self) -> None:
        """curve: smoothstep easing between left and right observed values."""
        data = _jan_feb_may_data()
        result = complete_ordinal_time_series(
            data, "month", "yearmonth", [], "curve", fiscal_year_start_month=1
        )
        rows_by_month = {r["month"]: r for r in result}
        assert rows_by_month["2024-03-01"]["revenue"] == pytest.approx(
            200 + 300 * 7 / 27
        )
        assert rows_by_month["2024-04-01"]["revenue"] == pytest.approx(
            200 + 300 * 20 / 27
        )

    def test_schema_fill_accepts_fill_modes(self) -> None:
        """AxisXStylePatch accepts all gap-fill fill values."""
        for mode in (
            "linear",
            "step-after",
            "step-before",
            "step-center",
            "curve",
        ):
            patch = AxisXStylePatch(fill=mode)
            assert patch.fill == mode

    def test_schema_fill_rejects_unknown(self) -> None:
        """AxisXStylePatch rejects an unknown fill value."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AxisXStylePatch(fill="sprinkles")

    def test_interpolate_integration_via_render(self) -> None:
        """Integration: fill:interpolate in chart style → interpolated VL data."""
        style = LineChartStylePatch(axis_x=AxisXStylePatch(fill="linear"))
        chart = LineChart(id="t", type="line", x="month", y="revenue", style=style)
        data = _jan_feb_may_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_RS).payload
        vl_data = spec.get("data", {}).get("values", [])
        rows_by_month = {r["month"]: r for r in vl_data}
        assert rows_by_month["2024-03-01"]["revenue"] == pytest.approx(300.0)
        assert rows_by_month["2024-04-01"]["revenue"] == pytest.approx(400.0)
