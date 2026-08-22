"""Render-local temporal label thinning without semantic time-unit mutation."""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _monthly_dates(n: int, start: tuple[int, int] = (2022, 1)) -> list[str]:
    year, month = start
    dates = []
    for _ in range(n):
        dates.append(f"{year:04d}-{month:02d}-01")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return dates


def _axis_x_temporal(
    label_time_unit: str | None = None,
    font_size: float = 11.0,
    fiscal_year_start_month: int = 1,
    encoding_time_unit: str | None = None,
) -> Any:
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.axis_cascade import resolved_axis_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    charts = resolve_chart_style_context(get_theme_style())
    axis_x = resolved_axis_style(
        charts, "axis_x", "temporal", chart_type="", label_authored=False
    )
    font = axis_x.labels.font.model_copy(update={"size": font_size})
    overlap = dataclasses.replace(axis_x.labels.overlap, skip=True, tilt=True)
    labels = dataclasses.replace(
        axis_x.labels,
        font=font,
        overlap=overlap,
        time_unit=label_time_unit,
        angle=None,
        tilt_increments=[-30.0, -60.0, -90.0],
    )
    return dataclasses.replace(
        axis_x,
        labels=labels,
        fiscal_year_start_month=fiscal_year_start_month,
        time_unit=encoding_time_unit or axis_x.time_unit,
    )


def _make_mock_measurer(width_per_char: float = 5.0) -> Any:
    measurer = MagicMock()
    measurer.measure = lambda text, size: width_per_char * len(text) * (size / 11.0)
    return measurer


class TestVisibilityUnitChain:
    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("yearmonthdate", "yearmonth"),
            ("yearweek", "yearmonth"),
            ("yearmonth", "yearquarter"),
            ("yearquarter", "year"),
            ("year", None),
        ],
    )
    def test_one_meaningful_skip_step(self, unit: str, expected: str | None) -> None:
        from dbt_charts.core.render.chart.time_unit_detect import (
            next_coarser_label_unit,
        )

        assert next_coarser_label_unit(unit) == expected


class TestTemporalOverlapResolution:
    def test_short_daily_domain_keeps_daily_format(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(days=offset)).isoformat()}
            for offset in range(30)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=600
            )

        assert layout.format_time_unit == "yearmonthdate"
        assert layout.visibility_time_unit is None
        assert layout.label_overlap == "allow"

    def test_short_weekly_domain_keeps_weekly_format(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(weeks=offset)).isoformat()}
            for offset in range(5)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=600
            )

        assert layout.format_time_unit == "yearweek"
        assert layout.visibility_time_unit is None
        assert layout.label_overlap == "allow"

    def test_daily_format_steps_through_monday_before_month(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(days=offset)).isoformat()}
            for offset in range(60)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            daily = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=1200
            )
            mondays = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=300
            )
            months = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=70
            )

        assert daily.format_time_unit == "yearmonthdate"
        assert mondays.format_time_unit == "yearweek"
        assert mondays.visibility_time_unit == "yearweek"
        assert months.format_time_unit == "yearmonth"

    def test_weekly_format_promotes_only_when_day_numbers_do_not_fit(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(weeks=offset)).isoformat()}
            for offset in range(8)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            weekly = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=240
            )
            monthly = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=70
            )

        assert weekly.format_time_unit == "yearweek"
        assert monthly.format_time_unit == "yearmonth"

    def test_first_visible_year_context_can_trigger_month_promotion(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 1, 29)
        data = [
            {"x": (start + datetime.timedelta(weeks=offset)).isoformat()}
            for offset in range(8)
        ]
        measurer = MagicMock()
        measurer.measure = lambda text, size: 100.0 if "'" in text else 1.0
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=80
            )

        assert layout.format_time_unit == "yearmonth"
        assert layout.anchor_index == 1

    def test_continuous_temporal_axis_keeps_existing_submonth_resolution(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(days=offset)).isoformat()}
            for offset in range(60)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis,
                "x",
                data,
                1.0,
                bucket_aligned_temporal=False,
                edge_labels_flushed=False,
                chart_width=300,
            )

        assert layout.format_time_unit == "yearmonth"

    def test_authored_continuous_daily_labels_measure_the_two_row_shape(self) -> None:
        # Regression: with an authored `labels.time_unit: yearmonthdate` on a
        # continuous axis, width measurement must reflect what _day_label
        # actually draws (two rows, mostly a bare day number) — not the
        # deleted single-row "%-d %b" vocabulary, which is wide enough to
        # wrongly promote or tilt labels that fit at their real width.
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal(label_time_unit="yearmonthdate")
        start = datetime.date(2024, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(days=offset)).isoformat()}
            for offset in range(20)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis,
                "x",
                data,
                1.0,
                bucket_aligned_temporal=False,
                edge_labels_flushed=False,
                chart_width=440,
            )

        assert layout.format_time_unit == "yearmonthdate"
        assert layout.label_overlap == "allow"
        assert layout.angle == 0.0

    def test_weekly_domain_crossing_two_months_keeps_weekly_when_it_fits(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(weeks=offset)).isoformat()}
            for offset in range(6)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=600
            )

        assert layout.format_time_unit == "yearweek"
        assert layout.visibility_time_unit is None
        assert layout.label_overlap == "allow"

    @pytest.mark.parametrize(
        ("start", "step", "count", "expected_format"),
        [
            (
                datetime.date(2024, 1, 1),
                datetime.timedelta(days=1),
                180,
                "yearweek",
            ),
            (
                datetime.date(2024, 1, 1),
                datetime.timedelta(weeks=1),
                70,
                "yearmonth",
            ),
        ],
    )
    def test_long_submonth_domain_promotes_to_month_format(
        self,
        start: datetime.date,
        step: datetime.timedelta,
        count: int,
        expected_format: str,
    ) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        data = [{"x": (start + step * offset).isoformat()} for offset in range(count)]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=600
            )

        assert layout.format_time_unit == expected_format
        assert layout.visibility_time_unit == expected_format
        assert layout.angle == 0.0

    def test_month_labels_are_not_thinned_when_their_text_does_not_overlap(
        self,
    ) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        start = datetime.date(2024, 12, 23)
        data = [
            {"x": (start + datetime.timedelta(weeks=offset)).isoformat()}
            for offset in range(72)
        ]
        measurer = _make_mock_measurer(width_per_char=7.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 0.8, edge_labels_flushed=True, chart_width=564
            )

        assert layout.format_time_unit == "yearmonth"
        assert layout.visibility_time_unit == "yearmonth"
        assert layout.angle == 0.0

    def test_cyclic_encoding_measures_its_distinct_tick_labels(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal(encoding_time_unit="monthofyear")
        start = datetime.date(2022, 1, 1)
        data = [
            {"x": (start + datetime.timedelta(days=offset)).isoformat()}
            for offset in range(365)
        ]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=300
            )

        assert layout.label_overlap == "allow"
        assert layout.angle == 0.0
        assert layout.format_time_unit == "monthofyear"
        assert layout.visibility_time_unit is None

    def test_cyclic_label_unit_uses_generic_skip_then_tilt(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal(label_time_unit="monthofyear")
        data = [{"x": value} for value in _monthly_dates(24)]
        measurer = _make_mock_measurer(width_per_char=8.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=80
            )

        assert axis.labels.time_unit == "monthofyear"
        assert layout.visibility_time_unit is None
        assert layout.label_overlap == "parity"
        assert layout.angle != 0.0

    def test_disabled_smart_time_format_still_uses_skip_then_tilt(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal(label_time_unit="none")
        data = [{"x": value} for value in _monthly_dates(24)]
        measurer = _make_mock_measurer(width_per_char=8.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=80
            )

        assert layout.visibility_time_unit is None
        assert layout.label_overlap == "parity"
        assert layout.angle != 0.0

    def test_disabled_smart_time_format_measures_raw_bucket_labels(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal(label_time_unit="none")
        data = [{"x": value} for value in _monthly_dates(24)]
        measurer = _make_mock_measurer(width_per_char=5.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=600
            )

        assert layout.label_overlap == "parity"

    def test_width_never_changes_resolved_time_units(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal(label_time_unit="yearmonth")
        data = [{"x": value} for value in _monthly_dates(24)]
        measurer = _make_mock_measurer()

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            wide = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=10_000
            )
            narrow = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=300
            )

        assert axis.labels.time_unit == "yearmonth"
        assert wide.visibility_time_unit == "yearmonth"
        assert narrow.visibility_time_unit == "yearquarter"
        assert wide.angle == 0.0

    def test_fiscal_start_phases_monthly_thinning(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )
        from dbt_charts.core.render.chart.type_inference import (
            build_cartesian_x_encoding,
        )

        axis = _axis_x_temporal(fiscal_year_start_month=3)
        data = [{"x": value} for value in _monthly_dates(12)]
        measurer = _make_mock_measurer()
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=150
            )

        _, ax_vl, _ = build_cartesian_x_encoding(
            data,
            "x",
            axis,
            {},
            "bar",
            visibility_time_unit=layout.visibility_time_unit,
            label_anchor_index=layout.anchor_index,
        )
        expr = ax_vl["labelExpr"]
        assert layout.visibility_time_unit == "yearquarter"
        assert "- 2 + 12) % 12) % 3 === 0" in expr
        assert (
            "utcFormat(toDate(datum.value), '%Y-%m') === "
            "utcFormat(toDate(\"2022-03-01\"), '%Y-%m')"
        ) in expr
        assert "datum.index" not in expr
        assert ax_vl["values"] == _monthly_dates(12)

    def test_thinning_precedes_tilt(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        data = [{"x": value} for value in _monthly_dates(24)]
        measurer = _make_mock_measurer(width_per_char=8.0)
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            thinned = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=500
            )
            tilted = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=80
            )

        assert thinned.visibility_time_unit == "yearquarter"
        assert thinned.angle == 0.0
        assert tilted.visibility_time_unit == "yearquarter"
        assert tilted.angle != 0.0

    def test_authored_quarter_format_can_thin_to_year_without_becoming_year_text(
        self,
    ) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )
        from dbt_charts.core.render.chart.time_unit_detect import default_label_expr_for

        axis = _axis_x_temporal(label_time_unit="yearquarter")
        data = [{"x": value} for value in _monthly_dates(36)]
        measurer = _make_mock_measurer()
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=90
            )

        expr = default_label_expr_for(
            "yearmonth",
            "yearquarter",
            layout.visibility_time_unit,
        )
        assert layout.visibility_time_unit == "year"
        assert "'Q'" in expr
        assert "'%b'" not in expr

    def test_year_labels_use_parity_skip_before_tilt(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal(label_time_unit="year")
        data = [{"x": f"{year}-01-01"} for year in range(2000, 2025)]
        measurer = _make_mock_measurer()
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=300
            )

        assert layout.label_overlap == "parity"
        assert layout.visibility_time_unit == "year"


class TestCategoricalOverlapResolution:
    def test_tilts_without_skipping(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        data = [{"x": f"Long category {i}"} for i in range(10)]
        measurer = _make_mock_measurer()
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=500
            )

        assert layout.label_overlap == "allow"
        assert layout.angle != 0.0

    def test_uses_steepest_tilt_without_skipping_when_labels_do_not_fit(self) -> None:
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis = _axis_x_temporal()
        data = [{"x": f"Very long category {i}"} for i in range(20)]
        measurer = _make_mock_measurer()
        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis, "x", data, 1.0, edge_labels_flushed=False, chart_width=200
            )

        assert layout.label_overlap == "allow"
        assert layout.angle == -90.0


class TestCadenceTokenWidthYearContext:
    """``_cadence_token_width`` must measure the same two-row shape
    ``_month_label``/``_quarter_label`` actually paint (a stacked year row
    under the month/quarter text), not the bare single-row string — see
    that function's own docstring. A year (4 tabular digits) is routinely
    wider than a 3-letter month abbreviation, so skipping this
    under-measures the tick and lets it collide with its neighbor.

    The function itself is now purely mechanical: it trusts the caller's
    resolved ``carries_year_row`` rather than deriving it, because the
    real labelExpr condition (``anchor || fiscal_month === 0``) needs to
    know whether a tick is the domain's literal first (leading-flush) or a
    genuine fiscal-year boundary (trailing-flush) — a distinction only
    ``_pair_clears`` has enough context to resolve (see
    ``TestPairClearsCarriesYearRow`` below for that resolution logic, and
    ``TestFiscalMonthIsYearStart`` for the boundary-detection half).
    """

    def test_yearmonth_includes_year_row_width_when_carries_year_row(self) -> None:
        import datetime

        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render.chart.time_unit_detect import (
            _cadence_token_width,
        )

        measurer = get_font_measurer(None)
        january = datetime.date(2025, 1, 6)
        width = _cadence_token_width(
            january, "yearmonth", measurer, 11.0, 0, 1, carries_year_row=True
        )
        assert width == max(
            measurer.measure("Jan", 11.0), measurer.measure("2025", 11.0)
        )
        assert width == pytest.approx(measurer.measure("2025", 11.0))

    def test_yearmonth_excludes_year_row_width_when_not_carries_year_row(
        self,
    ) -> None:
        import datetime

        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render.chart.time_unit_detect import (
            _cadence_token_width,
        )

        measurer = get_font_measurer(None)
        # Even a fiscal-year-start date must stay row-1-only when the
        # caller has resolved carries_year_row=False (a centered tick, or
        # a trailing-edge tick off the fiscal boundary) -- the function
        # never re-derives the fiscal check itself.
        january = datetime.date(2025, 1, 6)
        width = _cadence_token_width(
            january, "yearmonth", measurer, 11.0, 0, 1, carries_year_row=False
        )
        assert width == pytest.approx(measurer.measure("Jan", 11.0))

    def test_yearquarter_includes_year_row_width_when_carries_year_row(self) -> None:
        import datetime

        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render.chart.time_unit_detect import (
            _cadence_token_width,
        )

        measurer = get_font_measurer(None)
        q1_opener = datetime.date(2025, 1, 6)
        width = _cadence_token_width(
            q1_opener, "yearquarter", measurer, 11.0, 0, 1, carries_year_row=True
        )
        assert width == pytest.approx(measurer.measure("2025", 11.0))

    def test_yearquarter_excludes_year_row_width_when_not_carries_year_row(
        self,
    ) -> None:
        import datetime

        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render.chart.time_unit_detect import (
            _cadence_token_width,
        )

        measurer = get_font_measurer(None)
        q1_opener = datetime.date(2025, 1, 6)
        width = _cadence_token_width(
            q1_opener, "yearquarter", measurer, 11.0, 0, 1, carries_year_row=False
        )
        assert width == pytest.approx(measurer.measure("Q1", 11.0))


class TestFiscalMonthIsYearStart:
    """``_fiscal_month_is_year_start`` is only the ``fiscal_month === 0``
    half of the real labelExpr predicate (``anchor || fiscal_month ===
    0``) — it answers "does this date's month open the fiscal year",
    independent of whether the date is also the domain's literal first
    tick. ``_pair_clears`` combines it with the leading/trailing distinction.
    """

    def test_off_fiscal_start_is_false(self) -> None:
        import datetime

        from dbt_charts.core.render.chart.time_unit_detect import (
            _fiscal_month_is_year_start,
        )

        february = datetime.date(2025, 2, 3)
        assert _fiscal_month_is_year_start(february, 1) is False

    def test_at_calendar_fiscal_start_is_true(self) -> None:
        import datetime

        from dbt_charts.core.render.chart.time_unit_detect import (
            _fiscal_month_is_year_start,
        )

        january = datetime.date(2025, 1, 6)
        assert _fiscal_month_is_year_start(january, 1) is True

    def test_respects_authored_fiscal_year_start_month(self) -> None:
        import datetime

        from dbt_charts.core.render.chart.time_unit_detect import (
            _fiscal_month_is_year_start,
        )

        # Fiscal year starts in April: April is this axis's "January"
        # equivalent, so it -- not calendar January -- opens the fiscal year.
        april = datetime.date(2025, 4, 7)
        assert _fiscal_month_is_year_start(april, 4) is True
        january = datetime.date(2026, 1, 5)
        assert _fiscal_month_is_year_start(january, 4) is False


class TestPairClearsEdgeFlush:
    """Vega flushes a temporal axis's literal first/last rendered tick to the
    plot edge (text-anchor start/end) whenever it is genuinely at the domain
    boundary — regardless of whether that tick's date lands on a calendar
    boundary (day 1, quarter start, ...). A weekly-encoded domain that opens
    mid-month (e.g. the week of Jan 6) still has its month label flushed,
    because the flush is positional (``dates[0]``), not calendar-semantic.

    ``_pair_clears`` must reserve the tick's *full* measured width at that
    edge, matching the real render, not half — the day==1-style gate on
    ``_is_calendar_tick`` under-reserved it and let a real collision (Jan
    2025 / Feb 2025 on ``playground/editorial-stress-test``) go undetected.
    """

    def test_edge_opener_off_calendar_boundary_still_reserves_full_flush_width(
        self,
    ) -> None:
        import datetime

        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render.chart.time_unit_detect import _pair_clears

        measurer = get_font_measurer(None)
        dates = [
            datetime.date(2025, 1, 6),
            datetime.date(2025, 1, 13),
            datetime.date(2025, 1, 20),
            datetime.date(2025, 1, 27),
            datetime.date(2025, 2, 3),
        ]
        size = 11.0
        w_2025 = measurer.measure("2025", size)
        w_feb = measurer.measure("Feb", size)
        # Real Vega flushes dates[0] (Jan, day=6 — not a calendar boundary)
        # to the plot edge: it reserves the full two-row width ("2025" is
        # wider than "Jan"), not half. Pick a band whose clearance sits
        # strictly between the buggy half-width estimate and the real
        # full-width one, so the two assertions below discriminate cleanly.
        buggy_extent = w_2025 / 2 + w_feb / 2
        real_extent = w_2025 + w_feb / 2
        band = (buggy_extent + real_extent) / 2 / 4
        assert not _pair_clears(
            0,
            4,
            dates,
            "yearweek",
            "yearmonth",
            measurer,
            size,
            band,
            edge_labels_flushed=True,
            fiscal_year_start_month=1,
        )
        # A non-flushed axis (e.g. authored labels.flush: false) keeps the
        # half-width assumption and clears the same gap.
        assert _pair_clears(
            0,
            4,
            dates,
            "yearweek",
            "yearmonth",
            measurer,
            size,
            band,
            edge_labels_flushed=False,
            fiscal_year_start_month=1,
        )

    def test_trailing_opener_off_calendar_boundary_keeps_half_width(self) -> None:
        """Unlike the leading edge, a real render drops (rather than
        full-width-flushes) a trailing tick that opens off the calendar
        boundary — see ``_pair_clears``'s docstring. Reserving full width
        there would over-detect a collision the real render never has.
        """
        import datetime

        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render.chart.time_unit_detect import _pair_clears

        measurer = get_font_measurer(None)
        dates = [
            datetime.date(2025, 3, 3),
            datetime.date(2025, 4, 7),
            datetime.date(2025, 5, 5),  # trailing opener, day=5, not day=1
        ]
        size = 11.0
        w_apr = measurer.measure("Apr", size)
        w_may = measurer.measure("May", size)
        buggy_extent = w_apr / 2 + w_may / 2
        real_extent = w_apr / 2 + w_may
        band = (buggy_extent + real_extent) / 2
        assert _pair_clears(
            1,
            2,
            dates,
            "yearweek",
            "yearmonth",
            measurer,
            size,
            band,
            edge_labels_flushed=True,
            fiscal_year_start_month=1,
        )


class TestPairClearsCarriesYearRow:
    """The leading flush edge is always ``anchor`` in the real labelExpr
    (``anchor || fiscal_month === 0``) -- the domain's literal first tick
    carries the stacked year row whatever month it opens on, not only at a
    fiscal-year boundary. ``_fiscal_month_is_year_start`` alone (the
    ``fiscal_month === 0`` half) is the *trailing*-edge predicate; using it
    for the leading edge too under-measures a non-January opener.
    """

    def test_leading_flush_on_non_fiscal_boundary_month_still_carries_year_row(
        self,
    ) -> None:
        import datetime

        from dbt_charts.core.font_measure import get_font_measurer
        from dbt_charts.core.render.chart.time_unit_detect import _pair_clears

        measurer = get_font_measurer(None)
        # Domain opens in March -- not a fiscal-year-start month under the
        # default fiscal_year_start_month=1 -- so _fiscal_month_is_year_start
        # alone would (wrongly) say this tick stays row-1-only. A third date
        # keeps the Mar/Apr pair off the *trailing* edge (j == len(dates)-1
        # would trigger its own, unrelated flush reservation on Apr and
        # confound the numbers below).
        dates = [
            datetime.date(2025, 3, 1),
            datetime.date(2025, 4, 1),
            datetime.date(2025, 5, 1),
        ]
        size = 11.0
        w_mar = measurer.measure("Mar", size)
        w_2025 = measurer.measure("2025", size)
        w_apr = measurer.measure("Apr", size)
        buggy_extent = w_mar + w_apr / 2  # under-measures: bare "Mar"
        real_extent = w_2025 + w_apr / 2  # correct: stacked ["Mar", "2025"]
        band = (buggy_extent + real_extent) / 2
        assert not _pair_clears(
            0,
            1,
            dates,
            "yearmonth",
            "yearmonth",
            measurer,
            size,
            band,
            edge_labels_flushed=True,
            fiscal_year_start_month=1,
        )
