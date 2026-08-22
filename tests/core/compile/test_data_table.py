"""Tests for the data_table compiler leaf (compile/data_table.py).

Covers sizing/style resolution knowable before any query runs: row height,
axis offset, style-cascade resolution. Strip height (data-aware — depends on
series_count derived from query rows) and data-aware validation
(validate_data_table_against_data) live at the render boundary — see
tests/core/render/chart/test_data_table_attachment.py.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context


def _charts_style():
    return resolve_chart_style_context(get_theme_style())


def _dt_style(**overrides):
    """Build a DataTableStyle from the default theme with optional overrides."""
    return get_theme_style().charts.data_table.model_copy(update=overrides)


def test_default_theme_cascade_drops_divider():
    # Pin the actual user-facing defaults — resolved through the default
    # theme cascade, not the bare Pydantic model. The theme YAML used to
    # override divider.width to 1, silently negating the model default.
    cs = _charts_style()
    assert cs.data_table.divider.width == 0, (
        f"default theme should not draw a divider; got width="
        f"{cs.data_table.divider.width}"
    )


def test_axis_offset_reserves_two_label_lines_by_default():
    # Regression: axis_offset previously computed 1× label height, so the strip
    # would overlap two-line labels (e.g. ['Jan', '2024']).  The fix: always
    # reserve style.label_max_lines × label height so layout is stable
    # regardless of which x-tick produces two lines.
    from dbt_charts.core.compile.data_table import axis_offset
    from dbt_charts.core.compile.resolve.style.axis_cascade import resolved_axis_style

    cs = _charts_style()
    style = _dt_style()

    offset_two_line = axis_offset(cs, style, x_label_authored=False, chart_type="")
    # Build a style with label_max_lines=1 so we can compare.
    style_one_line = style.model_copy(update={"label_max_lines": 1})
    offset_one_line = axis_offset(
        cs, style_one_line, x_label_authored=False, chart_type=""
    )

    label_size = resolved_axis_style(
        cs, "axis_x", "band", chart_type="", label_authored=False
    ).labels.font.size
    assert offset_two_line == offset_one_line + label_size, (
        f"two-line reservation must add exactly one extra label-line height "
        f"({label_size}px) vs single-line; got two_line={offset_two_line:.1f}, "
        f"one_line={offset_one_line:.1f}"
    )


def test_label_position_field_rejected_by_validation():
    """YAML that authors the deleted label.position field raises ValidationError at compile time.

    Providing align alongside position ensures the error is for the forbidden
    `position` key (extra="forbid"), not for a missing required field.
    """
    import pytest
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.style.theme import DataTableLabelStyle

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DataTableLabelStyle.model_validate({"position": "right"})


def test_axis_offset_uses_merged_visibility_for_authored_label():
    """axis_offset must read the merged axis (Layer 5) not the base (Layer 1+2).

    When the caller passes x_label_authored=True, resolved_axis_style forces
    title.visible=True as a Layer-5 default beneath the base theme's
    title.visible: False (Layers 1+2). Without it, the strip must reserve no
    title space (title_h==0); with it, a positive title_h so the data-table
    strip is positioned below the title rather than colliding with it.

    Regression: before the fix, axis_offset read charts_style.axis_x directly
    (Layers 1+2 only), so the authored-label override was invisible and title_h
    was always 0, causing the strip to overlap the axis title.
    """
    from dbt_charts.core.compile.data_table import axis_offset
    from dbt_charts.core.compile.resolve.style.chart_context import (
        build_chart_style_context,
    )

    base_resolved = resolve_chart_style_context(get_theme_style())
    dt_style = _dt_style()

    from dbt_charts.core.compile.models.chart.normalized import BarChart

    cs = build_chart_style_context(base_resolved, BarChart(id="t", type="bar"))

    # Without authored label: base theme has title.visible=False → title_h==0
    offset_without = axis_offset(cs, dt_style, x_label_authored=False, chart_type="")

    # With authored label: Layer-6 default sets title.visible=True
    offset_with = axis_offset(cs, dt_style, x_label_authored=True, chart_type="")

    assert offset_with > offset_without, (
        f"axis_offset must reserve more space when axis title is visible "
        f"(authored x_label); got without={offset_without}, with={offset_with}"
    )


def test_resolved_axis_offset_reflects_authored_x_label() -> None:
    """Offset tracks whether an axis title is actually drawn.

    Covers the wire, not the leaf: axis_offset only reserves title space if
    the resolve path actually threads the chart's x_label into it. The pair
    above pins the leaf's behavior given the flag; this pins that production
    computes the flag at all, so deleting that one line fails a test rather
    than silently under-reserving the axis title's height.

    The third case is the reclaimed-space outcome: suppressing the title on
    a labelled chart must hand the pixels back, not merely hide the glyphs
    (the whole point of preferring this over ``title.font.size: 0``). It also
    pins ordering on the v1 cascade route that ``axis_offset`` takes
    (``axis_overrides=None``), which the spec-side tests cannot reach — they
    all go through the v2 route. Re-introducing label forcing above the
    chart-local layers would over-reserve here while every spec test stayed
    green.
    """
    from dbt_charts.core.compile.models.chart.authored import (
        ChartDataTable,
        ChartDataTableSource,
    )
    from dbt_charts.core.compile.models.chart.normalized import BarChart
    from dbt_charts.core.compile.models.query.normalized import SqlQuery
    from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
    from dbt_charts.core.compile.resolve import resolve

    data = [{"seg": "Alpha", "rev": 100.0}, {"seg": "Beta", "rev": 200.0}]
    board_style = resolve_chart_style_context(get_theme_style())
    hide_title = BarChartStylePatch.model_validate(
        {"axis_x": {"title": {"visible": False}}}
    )

    def _offset(
        x_label: str | None, style: BarChartStylePatch | None = None
    ) -> float | None:
        chart = BarChart(
            id="t",
            type="bar",
            x="seg",
            y="rev",
            x_label=x_label,
            style=style,
            data_table=ChartDataTable.model_validate(
                {"entries": [ChartDataTableSource(source="rev")]}
            ),
            query=SqlQuery(sql="SELECT 1", source="src"),
            query_name="q",
        )
        return resolve(
            chart, data, chart_style_context=board_style
        ).data_table_axis_offset

    without = _offset(None)
    with_label = _offset("Segment")
    assert without is not None and with_label is not None
    suppressed = _offset("Segment", hide_title)
    assert suppressed is not None
    assert with_label > without, (
        "an authored x_label must widen the data-table axis offset — the "
        f"resolve path is not threading it; got {without} vs {with_label}"
    )
    assert suppressed == without, (
        "an explicit title.visible:false must give the title's pixels back, "
        "leaving the same offset as a chart with no title at all; got "
        f"{suppressed} vs {without}"
    )


def test_axis_offset_honors_axis_band_title_suppression() -> None:
    """axis_offset reserves title space through the same slots emission uses.

    ``axis_offset`` asks the cascade for ``channel_type="band"``, which the
    chart-local walks must treat as a band channel — otherwise a chart
    suppressing its title via ``style.axis_band`` gets no title in the spec
    while the strip still reserves room for one, leaving a phantom gap
    between the axis and the table.
    """
    from dbt_charts.core.compile.data_table import axis_offset
    from dbt_charts.core.compile.models.chart.normalized import BarChart
    from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
    from dbt_charts.core.compile.resolve.style.chart_context import (
        build_chart_style_context,
    )

    base_resolved = resolve_chart_style_context(get_theme_style())
    dt_style = _dt_style()
    hide_band = BarChartStylePatch.model_validate(
        {"axis_band": {"title": {"visible": False}}}
    )

    plain = build_chart_style_context(base_resolved, BarChart(id="t", type="bar"))
    suppressed = build_chart_style_context(
        base_resolved, BarChart(id="t", type="bar", style=hide_band)
    )

    assert axis_offset(
        plain, dt_style, x_label_authored=True, chart_type=""
    ) > axis_offset(suppressed, dt_style, x_label_authored=True, chart_type=""), (
        "style.axis_band.title.visible:false must give the title's pixels back "
        "in the data-table offset, same as it does in the emitted spec"
    )


def test_data_table_offset_reflects_board_family_axis_override() -> None:
    """The data-table axis-offset path must thread chart_type so a board-level
    style.charts.<family>.axis* key reaches it.

    axis_offset resolves through resolved_axis_style; _data_table_geometry
    passes the chart's type so the board family scope (layer 9) applies. If
    that thread is dropped (chart_type="" reaches the geometry path), the
    family override is skipped and the strip reserves height against a
    cascade that differs from what the render path emits — the collision this
    fix prevents. Pins the wire, not the leaf.
    """
    from dbt_charts.core.compile.models.chart.authored import (
        ChartDataTable,
        ChartDataTableSource,
    )
    from dbt_charts.core.compile.models.chart.normalized import BarChart
    from dbt_charts.core.compile.models.query.normalized import SqlQuery
    from dbt_charts.core.compile.models.style.authored import StylePatch
    from dbt_charts.core.compile.resolve import resolve

    data = [{"seg": "Alpha", "rev": 100.0}, {"seg": "Beta", "rev": 200.0}]

    def _offset(board_patch: StylePatch | None) -> float | None:
        ctx = (
            resolve_chart_style_context(get_theme_style(), board_patch)
            if board_patch is not None
            else resolve_chart_style_context(get_theme_style())
        )
        chart = BarChart(
            id="t",
            type="bar",
            x="seg",
            y="rev",
            data_table=ChartDataTable.model_validate(
                {"entries": [ChartDataTableSource(source="rev")]}
            ),
            query=SqlQuery(sql="SELECT 1", source="src"),
            query_name="q",
        )
        return resolve(chart, data, chart_style_context=ctx).data_table_axis_offset

    baseline = _offset(None)
    overridden = _offset(
        StylePatch.model_validate(
            {"charts": {"bar": {"axis": {"labels": {"padding": 40}}}}}
        )
    )
    assert baseline is not None and overridden is not None
    assert overridden != baseline, (
        "a board style.charts.bar.axis.labels.padding must change the "
        "data-table axis offset — the geometry path is not threading chart_type; "
        f"got {baseline} (baseline) vs {overridden} (with board family override)"
    )
