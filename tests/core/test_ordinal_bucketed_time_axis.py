"""Tests for D-002: bucketed-time x-axes default to ordinal scale.

Key contracts:
- Any resolved time_unit (yearmonth, yearquarter, year, yearweek, yearmonthdate)
  → encoding.x.type == "ordinal" by default.
- axis_x.type: temporal is the escape hatch to get temporal scale.
- axis_x.type: ordinal forces ordinal even for continuous data.
- datetime.date values become ISO date strings on the ordinal path.
- No timeUnit emitted on ordinal path.
- axis.values (precomputed list) emitted on ordinal bucketed-time path.
- Time-part units (monthofyear, dayofweek, etc.) remain temporal — unchanged.
- time_unit: none stays temporal (continuous date).
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
    DimensionTicksStylePatch,
    LineChartStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())


def _bar(x: str = "month", y: str = "revenue", **kwargs: object) -> Chart:
    return BarChart(id="test_bar", type="bar", x=x, y=y, **kwargs)


def _line(x: str = "month", y: str = "revenue", **kwargs: object) -> Chart:
    return LineChart(id="test_line", type="line", x=x, y=y, **kwargs)


def _area(x: str = "month", y: str = "revenue", **kwargs: object) -> Chart:
    return AreaChart(id="test_area", type="area", x=x, y=y, **kwargs)


def _monthly_span(n_months: int = 12) -> list[dict]:
    """``n_months`` of first-of-month ISO strings starting 2024-01-01."""
    return [
        {
            "month": dt.date(2024 + (i // 12), (i % 12) + 1, 1).isoformat(),
            "revenue": i * 10,
        }
        for i in range(n_months)
    ]


class TestOrdinalDefaultForBucketedTime:
    """D-002: bucketed-time charts default to ordinal scale."""

    def test_bar_monthly_string_dates_emits_ordinal(self) -> None:
        chart = _bar()
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "ordinal", f"Expected ordinal, got: {x_enc}"

    def test_line_monthly_string_dates_emits_temporal(self) -> None:
        # Line always routes a bucketed-calendar grain to continuous temporal
        # (see value-driven-axis-type-inference task) — bar stays ordinal.
        chart = _line()
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "temporal", f"Expected temporal, got: {x_enc}"

    def test_area_monthly_string_dates_emits_temporal(self) -> None:
        chart = _area()
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "temporal", f"Expected temporal, got: {x_enc}"

    def test_line_thins_months_when_flushed_edge_labels_collide(self) -> None:
        """Calendar ticks at continuous-scale edges consume their full inner width."""
        chart = _line()
        data = [
            {
                "month": f"{2025 + (month - 1) // 12:04d}-{(month - 1) % 12 + 1:02d}-01",
                "revenue": month * 100,
            }
            for month in range(8, 21)
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)

        spec = render_resolved_chart(resolved, data, _BOARD_STYLE, width=400).payload

        x_axis = spec["encoding"]["x"]["axis"]
        assert "utcmonth(toDate(datum.value)) % 3 === 0" in x_axis["labelExpr"]

    def test_fiscal_quarter_line_keeps_centered_band_labels(self) -> None:
        """A fiscal offset routes quarters to an ordinal, unflushed x scale."""
        chart = _line(
            x="quarter",
            style=LineChartStylePatch(
                axis_x=AxisXStylePatch(fiscal_year_start_month=4)
            ),
        )
        data = [
            {
                "quarter": f"{2022 + quarter // 4:04d}-{quarter % 4 * 3 + 1:02d}-01",
                "revenue": quarter * 100,
            }
            for quarter in range(16)
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)

        spec = render_resolved_chart(resolved, data, _BOARD_STYLE, width=400).payload

        assert spec["encoding"]["x"]["type"] == "ordinal"
        # Coarsens to year cadence at this width: the stacked year-row check
        # now also catches the domain's literal first tick (Jan 2022, the
        # labelExpr's unconditional `anchor`) against the very next quarter's
        # own fiscal-year-start year row (April 2022, `fiscal_month === 0`)
        # — a real collision the old flush-only year-row check missed
        # (`_pair_clears` used to gate a tick carrying the year row on being
        # a FLUSHED edge, but the anchor tick's year row paints regardless of
        # flush). Every value actually placed on this axis is a genuine
        # fiscal-year opener, so the labelExpr's period-opener gate
        # (`fiscal_month === 0`) is always true for what renders — nothing
        # paints blank, even though the expression itself still carries a
        # defensive `: ''` fallback for values outside this set.
        values = spec["encoding"]["x"]["axis"].get("values")
        assert values, (
            "expected explicit tick values on the ordinal fiscal-quarter axis"
        )
        assert all(dt.date.fromisoformat(v).month == 4 for v in values), (
            f"every rendered tick must be a fiscal-year opener, or the "
            f"period-opener gate would blank it: {values}"
        )

    def test_ordinal_path_emits_no_timeunit(self) -> None:
        chart = _bar()
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert "timeUnit" not in x_enc, f"Ordinal path must not emit timeUnit: {x_enc}"

    def test_ordinal_path_emits_utc_format_label_expr(self) -> None:
        # Both ordinal and temporal bucketed-time paths now emit the same
        # `utcFormat(toDate(datum.value), …)` + `utcmonth(toDate(...))` shape.
        # `toDate` parses ISO strings on the ordinal path and is a no-op on
        # Dates on the temporal path; UTC components match `scale.type: utc`
        # so the cadence gate doesn't drift in non-UTC renderers.
        chart = _bar()
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        x_axis = x_enc.get("axis", {})
        label_expr = x_axis.get("labelExpr", "")
        assert "utcFormat(toDate(datum.value)" in label_expr, (
            f"Ordinal path must emit utcFormat labelExpr: {x_axis}"
        )
        assert "month(datum.value)" not in label_expr, (
            f"Ordinal path must not emit local-TZ month(): {x_axis}"
        )
        assert "timeFormat(datum.value" not in label_expr, (
            f"Ordinal path must not emit local-TZ timeFormat(): {x_axis}"
        )

    def test_ordinal_path_emits_axis_values(self) -> None:
        chart = _bar()
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        x_axis = x_enc.get("axis", {})
        assert "values" in x_axis, (
            f"Ordinal bucketed-time must emit axis.values: {x_axis}"
        )
        # All 12 monthly date strings present
        assert len(x_axis["values"]) == 12

    def test_yearquarter_data_emits_ordinal(self) -> None:
        data = [
            {"quarter": "2024-01-01", "revenue": 100},
            {"quarter": "2024-04-01", "revenue": 200},
            {"quarter": "2024-07-01", "revenue": 300},
        ]
        chart = BarChart(id="test_q", type="bar", x="quarter", y="revenue")
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "ordinal"
        assert "timeUnit" not in x_enc

    def test_year_data_emits_ordinal(self) -> None:
        data = [
            {"year": "2022-01-01", "revenue": 100},
            {"year": "2023-01-01", "revenue": 200},
            {"year": "2024-01-01", "revenue": 300},
        ]
        chart = BarChart(id="test_yr", type="bar", x="year", y="revenue")
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "ordinal"


class TestTemporalEscapeHatch:
    """axis_x.type: temporal forces temporal scale (escape hatch)."""

    def test_axis_x_type_temporal_forces_temporal(self) -> None:
        style = BarChartStylePatch(axis_x=AxisXStylePatch(type="temporal"))
        chart = _bar(style=style)
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "temporal", (
            f"axis_x.type: temporal must force temporal: {x_enc}"
        )
        assert "timeUnit" in x_enc, f"temporal path must still emit timeUnit: {x_enc}"

    def test_axis_x_type_temporal_emits_timunit_and_label_expr(self) -> None:
        style = BarChartStylePatch(axis_x=AxisXStylePatch(type="temporal"))
        chart = _bar(style=style)
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("timeUnit") == "utcyearmonth"
        x_axis = x_enc.get("axis", {})
        assert "labelExpr" in x_axis, f"temporal path must emit labelExpr: {x_axis}"

    def test_axis_x_type_auto_uses_ordinal(self) -> None:
        # "auto" is the default; behaves same as None (ordinal for bucketed time)
        style = BarChartStylePatch(axis_x=AxisXStylePatch(type="auto"))
        chart = _bar(style=style)
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "ordinal"


class TestDateObjectCoercion:
    """datetime.date objects coerce to ISO date strings on ordinal path."""

    def test_date_objects_become_iso_strings_in_spec_data(self) -> None:
        data = [
            {"month": dt.date(2024, 1, 1), "revenue": 100},
            {"month": dt.date(2024, 2, 1), "revenue": 200},
            {"month": dt.date(2024, 3, 1), "revenue": 300},
        ]
        chart = _bar()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "ordinal"

        inline_values = spec.get("data", {}).get("values", [])
        months = [row["month"] for row in inline_values]
        # All date objects coerce to ISO date strings
        assert all(isinstance(m, str) for m in months), (
            f"date objects must become strings: {months}"
        )
        assert "2024-01-01" in months

    def test_date_objects_ordinal_emits_label_expr(self) -> None:
        # On ordinal path with date-like values, a smart default labelExpr is
        # applied. formatType="time" + format silently drops every label on a
        # string-domain ordinal scale (d3-time-format gets a string, not a
        # Date), so we route through `utcFormat(toDate(datum.value), <fmt>)`
        # instead.
        data = [
            {"month": dt.date(2024, 1, 1), "revenue": 100},
            {"month": dt.date(2024, 2, 1), "revenue": 200},
        ]
        chart = _bar()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        x_axis = x_enc.get("axis", {})
        label_expr = x_axis.get("labelExpr", "")
        assert "utcFormat(toDate(datum.value)" in label_expr, (
            f"Expected utcFormat labelExpr on ordinal date axis: {x_axis}"
        )
        assert x_axis.get("formatType") != "time", (
            f"Ordinal date axis must NOT use formatType=time: {x_axis}"
        )


class TestOrdinalAxisLabelsRender:
    """End-to-end regression: ordinal bucketed-time labels must reach the SVG.

    `formatType: "time"` + d3-time-format on a string-domain ordinal scale
    silently produces empty labels because the formatter receives the raw
    string and expects a Date. This test renders all the way through
    vl-convert and asserts the year strings appear in the SVG output.
    """

    def test_year_labels_appear_in_svg(self) -> None:
        import json
        import re

        import vl_convert as vlc

        data = [
            {"date": "2018-01-01", "revenue": 82000},
            {"date": "2019-01-01", "revenue": 95000},
            {"date": "2020-01-01", "revenue": 88000},
            {"date": "2021-01-01", "revenue": 107000},
        ]
        chart = BarChart(id="yr", type="bar", x="date", y="revenue")
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        svg = vlc.vegalite_to_svg(json.dumps(spec))
        texts = re.findall(r"<text[^>]*>([^<]*)</text>", svg)
        rendered_years = {t for t in texts if t in {"2018", "2019", "2020", "2021"}}
        assert rendered_years == {"2018", "2019", "2020", "2021"}, (
            f"Expected all year labels in SVG, got: {sorted(rendered_years)}; "
            f"all texts: {texts}"
        )


class TestTimeUnitNoneStaysTemporal:
    """time_unit: none → temporal (continuous date, no bucketing)."""

    def test_time_unit_none_stays_temporal(self) -> None:
        style = BarChartStylePatch(axis_x=AxisXStylePatch(time_unit="none"))
        chart = _bar(style=style)
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "temporal", (
            f"time_unit=none must keep temporal: {x_enc}"
        )
        assert "timeUnit" not in x_enc


class TestTimePartUnitsRemainTemporal:
    """Time-part units (monthofyear, dayofweek, etc.) remain temporal."""

    def test_monthofyear_stays_temporal(self) -> None:
        style = BarChartStylePatch(axis_x=AxisXStylePatch(time_unit="monthofyear"))
        chart = _bar(style=style)
        data = _monthly_span()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "temporal", (
            f"monthofyear must remain temporal: {x_enc}"
        )
        assert x_enc.get("timeUnit") == "month"

    def test_dayofweek_stays_temporal(self) -> None:
        style = BarChartStylePatch(axis_x=AxisXStylePatch(time_unit="dayofweek"))
        chart = _bar(x="day", style=style)
        data = [
            {"day": "2024-01-01", "revenue": 100},
            {"day": "2024-01-02", "revenue": 200},
        ]
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec.get("encoding", {}).get("x", {})
        assert x_enc.get("type") == "temporal"
        assert x_enc.get("timeUnit") == "day"


class TestAxisXTypeFieldValidation:
    """AxisXStylePatch.type validates allowed values."""

    def test_invalid_axis_type_raises_validation_error(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AxisXStylePatch(type="banana")

    def test_valid_axis_types_accepted(self) -> None:
        for valid in ("auto", "ordinal", "temporal"):
            patch = AxisXStylePatch(type=valid)
            assert patch.type == valid


def _daily_data(n_days: int = 400) -> list[dict]:
    """Generate n_days of daily ISO date strings starting 2022-01-01."""
    base = dt.date(2022, 1, 1)
    return [
        {"day": (base + dt.timedelta(days=i)).isoformat(), "value": i}
        for i in range(n_days)
    ]


class TestDailyTickDensity:
    """Daily labels promoted to months, without re-graining bar's ticks.

    Bar gets the _LABEL_THINNING_TICK_MARK_TYPES restoration: a render-local
    (non-authored) promotion keeps a tick under every daily bucket (`values`
    stays every day) and turns `ticks: True` back on — only the label TEXT
    thins to monthly openers via labelExpr gating.
    """

    def test_daily_400_points_keeps_every_bucket_and_restores_ticks(self) -> None:
        chart = BarChart(id="daily_bar", type="bar", x="day", y="value")
        data = _daily_data(400)
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_axis = spec.get("encoding", {}).get("x", {}).get("axis", {})
        values = x_axis.get("values", [])
        assert len(values) == 400
        assert x_axis.get("ticks") is True

    def test_daily_400_points_labels_thin_to_monthly_openers(self) -> None:
        """Automatic monthly label TEXT thins via labelExpr, not `values`."""
        chart = BarChart(id="daily_bar2", type="bar", x="day", y="value")
        data = _daily_data(400)
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_axis = spec.get("encoding", {}).get("x", {}).get("axis", {})
        values = x_axis.get("values", [])
        assert len(values) == 400
        label_expr = x_axis.get("labelExpr", "")
        assert label_expr, "labelExpr must be present to thin label text"
        assert "utcmonth" in label_expr, (
            "labelExpr must gate on the month-opener predicate to blank "
            f"non-opener days; got {label_expr!r}"
        )

    def test_daily_short_domain_explicit_daily_label_restores_density(self) -> None:
        """Explicit daily format keeps daily ticks despite visibility thinning."""
        from dbt_charts.core.compile.models.style.authored import (
            BarChartStylePatch,
        )

        style = BarChartStylePatch(
            axis_x=AxisXStylePatch(
                labels=DimensionLabelStylePatch(time_unit="yearmonthdate")
            )
        )
        # 30-day single month
        data = _daily_data(30)
        chart = BarChart(id="daily_dense", type="bar", x="day", y="value", style=style)
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        values = spec.get("encoding", {}).get("x", {}).get("axis", {}).get("values", [])
        assert len(values) >= 28


class TestHighCardinalityTemporalBarTicks:
    """A bar past ``max_ordinal_buckets`` resolves temporal but still needs ticks.

    The ordinal branch's restoration cannot reach it, so year-cadence labels
    would otherwise sit over 137 unmarked monthly bars with nothing linking a
    label to the bar it names.
    """

    def test_137_month_bar_restores_ticks_at_the_label_cadence_grain(self) -> None:
        data = _monthly_span(137)
        chart = _bar(x="month")
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec["encoding"]["x"]
        assert x_enc["type"] == "temporal"
        x_axis = x_enc.get("axis", {})
        assert x_axis.get("ticks") is True
        values = x_axis.get("values", [])
        assert len(values) == 12, (
            "ticks must land at the year label cadence, not under every bucket; "
            f"got {len(values)} values"
        )

    def test_unthinned_bar_keeps_its_ticks_hidden(self) -> None:
        """Every bucket labeled — a tick under each would say nothing new."""
        data = _monthly_span(12)
        chart = _bar(x="month")
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec["encoding"]["x"]
        # Under the cap, so this pins the ORDINAL branch's restoration, not the
        # temporal guard above it.
        assert x_enc["type"] == "ordinal"
        x_axis = x_enc.get("axis", {})
        assert x_axis.get("ticks") is False
        assert len(x_axis.get("values", [])) == 12

    def test_thinned_line_keeps_its_ticks_the_theme_left_them(self) -> None:
        """The mark-type half of the gate: only bar/histogram get restoration.

        A line on the same thinned 137-month domain must not have its ticks
        flipped on. Without this, deleting the ``mark_type`` check would
        silently restore ticks on line/area/scatter with green CI.
        """
        data = _monthly_span(137)
        style = LineChartStylePatch(
            axis_x=AxisXStylePatch(ticks=DimensionTicksStylePatch(visible=False))
        )
        chart = _line(x="month", style=style)
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_enc = spec["encoding"]["x"]
        assert x_enc["type"] == "temporal"
        x_axis = x_enc.get("axis", {})
        assert x_axis.get("ticks") is False
        # Same thinning the bar case sees — so the gate, not the absence of
        # thinning, is what keeps these off.
        assert len(x_axis.get("values", [])) == 12

    def test_authored_tick_count_keeps_the_axis_the_authors(self) -> None:
        """An authored cadence owns the ticks; the render does not override it."""
        data = _monthly_span(137)
        style = BarChartStylePatch(
            axis_x=AxisXStylePatch(ticks=DimensionTicksStylePatch(count=6))
        )
        chart = _bar(x="month", style=style)
        resolved = resolve(chart, data, chart_style_context=_BOARD_CTX)
        spec = render_resolved_chart(resolved, data, _BOARD_STYLE).payload

        x_axis = spec["encoding"]["x"].get("axis", {})
        assert x_axis.get("ticks") is False
