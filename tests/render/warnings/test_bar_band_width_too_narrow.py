"""Tests for the BAR_BAND_WIDTH_TOO_NARROW render-warning detector.

Detection rule: fires on a (vertical) bar chart when the estimated per-band
pixel width (the actual rendered spec width / distinct x categories) drops
below the readability floor — the scenario is daily-granularity bars where
hundreds of bands are squeezed into one chart width and the fill disappears
under the bar's own stroke, leaving "ghost bands".
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.authored import MultiplesConfig
from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
    LineChart,
    PieChart,
)
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.diagnostics import WARN_BAR_BAND_WIDTH_TOO_NARROW, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    bar_band_width_too_narrow as detector,
)

from ...core._board_utils import (
    _default_chart_style_context,
    make_test_resolved_board,
    make_test_resolved_chart,
)


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"day": f"2026-01-{i:02d}", "val": i} for i in range(n)]


def _grouped_rows(n_x: int, n_series: int) -> list[dict[str, Any]]:
    """n_x distinct x categories x n_series distinct series — a grouped bar's shape."""
    return [
        {"month": f"m{x}", "series": f"s{s}", "val": x + s}
        for x in range(n_x)
        for s in range(n_series)
    ]


def _make_ctx(
    chart: Any, rows: list[dict[str, Any]], x_type: str = "ordinal"
) -> WarningContext:
    from dbt_charts.core.compile.resolve import preferred_chart_width

    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    width = preferred_chart_width(chart, _default_chart_style_context())
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: {"encoding": {"x": {"type": x_type}}, "width": width}},
    )


def test_fires_on_daily_bars_in_narrow_chart() -> None:
    """~500 daily bars in a 580px chart -> ~1.16px/band, well under the floor."""
    chart = BarChart(id="c1", type="bar", query_name="q", x="day", y="val", width=580)
    warnings = detector.detect(_make_ctx(chart, _rows(500)))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_BAR_BAND_WIDTH_TOO_NARROW.code
    assert w.field == "day"
    # The grain of the x channel is what is wrong, so the mark belongs on `x:`
    # rather than on the whole chart block.
    assert w.path == "charts.c1.x"
    assert "500" in w.message
    assert "1.16px" in w.message
    assert w.fix is not None


def test_no_fire_on_normal_chart() -> None:
    """A typical 12-bar chart at the default 600px width is nowhere near the floor."""
    chart = BarChart(id="c1", type="bar", query_name="q", x="day", y="val")
    assert detector.detect(_make_ctx(chart, _rows(12))) == []


def test_no_fire_at_floor_boundary() -> None:
    """600px / 150 bands = 4.0px/band exactly at the floor -> does not fire."""
    chart = BarChart(id="c1", type="bar", query_name="q", x="day", y="val", width=600)
    assert detector.detect(_make_ctx(chart, _rows(150))) == []


def test_fires_just_below_floor_boundary() -> None:
    """600px / 151 bands = 3.97px/band, just under the floor -> fires."""
    chart = BarChart(id="c1", type="bar", query_name="q", x="day", y="val", width=600)
    warnings = detector.detect(_make_ctx(chart, _rows(151)))
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_BAND_WIDTH_TOO_NARROW.code


def test_no_fire_on_horizontal_bar() -> None:
    """Horizontal bars band along height, not width — out of scope for this detector."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="day",
        y="val",
        width=580,
        # model_construct, not the normal constructor: BarChartStylePatch's
        # TYPE_CHECKING stub aliases the full (non-optional) BarChartStyle, so
        # pyright demands every theme field here in this strictly-swept dir.
        # model_construct's **values: Any signature sidesteps that while
        # producing the identical runtime patch (all unset fields -> None).
        style=BarChartStylePatch.model_construct(orientation="horizontal"),
    )
    assert detector.detect(_make_ctx(chart, _rows(500))) == []


def test_no_fire_on_temporal_x_encoding() -> None:
    """A dense temporal x-axis (hundreds of time points) is normal, not a defect.

    This pins the load-bearing _CATEGORICAL_TYPES guard: the detector must
    never fire when the Vega x-encoding type is 'temporal', even if the band
    count exceeds the floor on a narrow chart.
    """
    chart = BarChart(id="c1", type="bar", query_name="q", x="day", y="val", width=580)
    resolved = make_test_resolved_chart(chart, _rows(500))
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: _rows(500)},
        vega_specs={resolved.id: {"encoding": {"x": {"type": "temporal"}}}},
    )
    assert detector.detect(ctx) == []


def test_fires_on_narrow_facet_panel() -> None:
    """Small multiples: the per-panel width lives on vega_specs[...]['spec']['width'],
    not the top level. The detector must read the panel width, not skip faceted charts.
    """
    chart = BarChart(id="c1", type="bar", query_name="q", x="day", y="val", width=580)
    resolved = make_test_resolved_chart(chart, _rows(500))
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: _rows(500)},
        vega_specs={
            resolved.id: {
                "facet": {"column": {"field": "day"}},
                "spec": {"encoding": {"x": {"type": "ordinal"}}, "width": 100},
            }
        },
    )
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_BAND_WIDTH_TOO_NARROW.code


def test_no_fire_on_non_bar_chart() -> None:
    chart = LineChart(id="c1", type="line", query_name="q", x="day", y="val")
    assert detector.detect(_make_ctx(chart, _rows(500))) == []


def test_no_fire_without_x() -> None:
    chart = PieChart(id="c1", type="pie", query_name="q", theta="val", color="day")
    assert detector.detect(_make_ctx(chart, _rows(500))) == []


def _grouped_ctx(
    chart: Any,
    rows: list[dict[str, Any]],
    width: float,
    *,
    offset_field: str | None = "series",
    offset_type: str = "nominal",
    facet_field: str | None = None,
) -> WarningContext:
    """Build a ctx whose vega_specs mirrors what render_resolved_chart would
    actually emit for a grouped bar: an xOffset channel present only when the
    band is genuinely subdivided (offset_field is not None).
    """
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    encoding: dict[str, Any] = {"x": {"type": "ordinal"}}
    if offset_field is not None:
        encoding["xOffset"] = {"field": offset_field, "type": offset_type}
    unit = {"encoding": encoding, "width": width}
    spec = (
        {"facet": {"column": {"field": facet_field}}, "spec": unit}
        if facet_field
        else unit
    )
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: spec},
    )


def test_fires_on_grouped_bar_subdivided_below_floor() -> None:
    """30 x-categories x 6 series, unauthored stack (defaults to grouped).

    600/30 = 20px per band clears the floor comfortably, but the emitted
    xOffset channel subdivides each band by series count: 20/6 = 3.33px per
    bar, under the floor. The detector must judge the bar, not the band.
    """
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y="val",
        color="series",
        width=600,
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _grouped_rows(n_x=30, n_series=6)
    resolved = make_test_resolved_chart(chart, rows)
    assert isinstance(resolved, ResolvedBarChart)
    assert resolved.stack == "none"  # grouped is bar's unauthored default
    ctx = _grouped_ctx(chart, rows, width=600)
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_BAND_WIDTH_TOO_NARROW.code
    assert "3.33px" in warnings[0].message
    assert "6 series" in warnings[0].message


def test_no_fire_on_stacked_control_same_data_and_width() -> None:
    """Same 30x6 shape and width, but stacked: the emitter never assigns an
    xOffset channel for a stacked bar, so no encoding key means no subdivision.

    600/30 = 20px per band, comfortably above the floor -> no warning. This is
    the sibling control proving the fix judges the emitted offset channel, not
    just series count in the data.
    """
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y="val",
        color="series",
        width=600,
        style=BarChartStylePatch.model_construct(orientation="vertical", stack="zero"),
    )
    rows = _grouped_rows(n_x=30, n_series=6)
    resolved = make_test_resolved_chart(chart, rows)
    assert isinstance(resolved, ResolvedBarChart)
    assert resolved.stack == "zero"
    # A real stacked emitter never sets xOffset — mirror that (offset_field=None).
    ctx = _grouped_ctx(chart, rows, width=600, offset_field=None)
    assert detector.detect(ctx) == []


def test_no_fire_on_full_overlap_grouped_bar() -> None:
    """overlap: full coincides the series into one visual column per x — the
    real emitter drops the xOffset channel entirely in this case, even though
    the chart is still 'grouped' (stack: none). Same 30x6 shape that fires
    without the override.
    """
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y="val",
        color="series",
        width=600,
        style=BarChartStylePatch.model_construct(
            orientation="vertical", overlap="full"
        ),
    )
    rows = _grouped_rows(n_x=30, n_series=6)
    resolved = make_test_resolved_chart(chart, rows)
    assert isinstance(resolved, ResolvedBarChart)
    assert resolved.style.overlap == "full"
    # The real emitter pops the offset channel for overlap: full — mirror that.
    ctx = _grouped_ctx(chart, rows, width=600, offset_field=None)
    assert detector.detect(ctx) == []


def test_fires_when_faceted_by_the_color_field() -> None:
    """Small multiples partitioned on the same field bound to color.

    `multiples: {columns: series}` splits the *data* before it reaches a
    panel, but Vega-Lite resolves the xOffset scale SHARED across facet
    panels by default (only `y` ever gets `resolve.scale: independent`) — so
    each panel's band still divides across the full, global series domain,
    with a single sub-slot occupied. Real render measurement: 1.18px bars at
    this exact shape. The detector must fire, not stay silent because the
    data looks partitioned.
    """
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y="val",
        color="series",
        width=120,
        style=BarChartStylePatch.model_construct(orientation="vertical"),
        multiples=MultiplesConfig(columns="series"),
    )
    rows = _grouped_rows(n_x=12, n_series=6)
    resolved = make_test_resolved_chart(chart, rows)
    assert isinstance(resolved, ResolvedBarChart)
    assert resolved.stack == "none"
    ctx = _grouped_ctx(chart, rows, width=120, facet_field="series")
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_BAND_WIDTH_TOO_NARROW.code
    assert "1.67px" in warnings[0].message
    assert "6 series" in warnings[0].message


def test_no_fire_on_comfortable_grouped_bar() -> None:
    """12 x-categories x 3 series at 600px: 50px/band, 16.67px/bar — fine."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y="val",
        color="series",
        width=600,
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _grouped_rows(n_x=12, n_series=3)
    ctx = _grouped_ctx(chart, rows, width=600)
    assert detector.detect(ctx) == []


def test_fires_on_wide_form_grouped_measures_below_floor() -> None:
    """y: [a, b, c] folds into a wide-form grouped bar — the emitter's own
    synthetic label field (never present in query rows) subdivides the band
    by len(chart.y), not by a color channel. 60 x-categories x 3 measures at
    600px: 10px/band, 3.33px/bar under the floor.
    """
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y=["a", "b", "c"],
        width=600,
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = [{"month": f"m{x}", "a": x, "b": x, "c": x} for x in range(60)]
    from dbt_charts.core.compile.resolve.chart._wide_fields import (
        WIDE_LABEL_FIELD,
        WIDE_VALUE_FIELD,
    )

    resolved = make_test_resolved_chart(chart, rows)
    assert isinstance(resolved, ResolvedBarChart)
    # After normalization, y is narrowed to the synthetic value field and
    # wide_measures holds the original authored measure names.
    assert resolved.y == WIDE_VALUE_FIELD
    assert resolved.wide_measures == ("a", "b", "c")
    # Real emitter: xOffset field is the synthetic fold label, never in query rows.
    ctx = _grouped_ctx(chart, rows, width=600, offset_field=WIDE_LABEL_FIELD)
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_BAR_BAND_WIDTH_TOO_NARROW.code
    assert "3.33px" in warnings[0].message
    assert "3 series" in warnings[0].message


def test_no_fire_on_gradient_offset_type() -> None:
    """A continuous (gradient) offset channel isn't a discrete grouping —

    the offset type guard must treat 'quantitative' the same as absent.
    """
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="month",
        y="val",
        width=600,
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _grouped_rows(n_x=30, n_series=6)
    ctx = _grouped_ctx(
        chart, rows, width=600, offset_field="val", offset_type="quantitative"
    )
    assert detector.detect(ctx) == []


class TestDetectorReadsThePreEmitPanelWidth:
    """The panel width the bar emitter measures band-overlap against
    (``box.width``, set before the emitter runs) must be the exact same
    number this detector later reads off the stamped spec
    (``vega_specs[...]["spec"]["width"]``, set after emit by
    ``_apply_facet_layout``). If the two disagree, the emitter judges
    crowding against the full card width while the spec is stamped with the
    narrower panel width, so the detector's verdict would not be judging the
    width the emitter actually used. Proven against a real render of a real
    faceted chart, not a hand-built ``WarningContext``.
    """

    def test_emitter_box_width_matches_the_detectors_stamped_width(self) -> None:
        from dbt_charts.core.compile.resolve import resolve
        from dbt_charts.core.render.chart.emitters import bar as bar_emitter
        from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

        chart = BarChart(
            id="c1",
            type="bar",
            query_name="q",
            x="month",
            y="val",
            multiples=MultiplesConfig(columns="grp"),
        )
        rows = [
            {"grp": f"g{g}", "month": f"m{i:02d}", "val": i + 1}
            for g in range(3)
            for i in range(30)
        ]

        captured_box_widths: list[float] = []
        real_resolve_axis_x_overlap = bar_emitter.resolve_axis_x_overlap

        def _spy(*args: Any, **kwargs: Any) -> Any:
            captured_box_widths.append(kwargs["chart_width"])
            return real_resolve_axis_x_overlap(*args, **kwargs)

        import unittest.mock as mock_mod

        with mock_mod.patch.object(
            bar_emitter, "resolve_axis_x_overlap", side_effect=_spy
        ):
            vl = generate_vega_lite_spec(chart, rows, width=300.0)

        assert captured_box_widths, "resolve_axis_x_overlap was never called"
        emitter_panel_width = captured_box_widths[0]

        assert "facet" in vl
        stamped_panel_width = vl["spec"]["width"]
        assert emitter_panel_width == stamped_panel_width

        # The detector reads this exact dict path — run it against the real
        # emitted spec to confirm it sees the same number, not just that the
        # two producers agree in isolation.
        resolved = resolve(
            chart, rows, chart_style_context=_default_chart_style_context()
        )
        board = make_test_resolved_board(charts={resolved.id: resolved})
        ctx = WarningContext(
            board_spec=board,
            chart_results={resolved.id: rows},
            vega_specs={resolved.id: vl},
        )
        detector.detect(ctx)  # must not raise; exercises the real unwrap path
        assert vl["spec"]["width"] == emitter_panel_width
