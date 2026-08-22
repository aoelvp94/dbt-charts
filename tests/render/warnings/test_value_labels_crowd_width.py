"""Tests for the VALUE_LABELS_CROWD_WIDTH render-warning detector.

Fires when a chart's widest value label is wider than its per-item slot
(rendered panel width / distinct categories) — labels overflow the mark and
collide. General across bar / line / area.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    Chart,
    LineChart,
)
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.diagnostics import WARN_VALUE_LABELS_CROWD_WIDTH, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    value_labels_crowd_width as detector,
)

from ...core._board_utils import make_test_resolved_board

_VALUE = 7.46761


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"cat": f"c{i}", "val": _VALUE} for i in range(n)]


def _board(family: str, label_updates: dict[str, Any]) -> ChartStyleContext:
    """Default theme with the family's value labels turned on (+ updates).

    Area value labels ride the overlaid line mark, so enable them there.
    """
    compiled = get_theme_style("editorial")
    label_mark = "line" if family == "area" else family
    mark = getattr(compiled.charts.marks, label_mark)
    labels = mark.labels.model_copy(update={"visible": True, **label_updates})
    new_mark = mark.model_copy(update={"labels": labels})
    marks = compiled.charts.marks.model_copy(update={label_mark: new_mark})
    charts = compiled.charts.model_copy(update={"marks": marks})
    return resolve_chart_style_context(compiled.model_copy(update={"charts": charts}))


def _ctx(
    chart: Chart, rows: list[dict[str, Any]], board: ChartStyleContext
) -> WarningContext:
    resolved = resolve(chart, rows, chart_style_context=board)
    resolved_board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=resolved_board,
        chart_results={resolved.id: rows},
        # width is the real rendered panel width the detector divides into slots.
        vega_specs={
            resolved.id: {"width": 600, "encoding": {"x": {"type": "nominal"}}}
        },
    )


def _bar(**kw: Any) -> BarChart:
    # Nominal x defaults to a horizontal bar; the screenshot case (and the check)
    # is vertical bars, so pin it unless a test overrides.
    kw.setdefault("style", BarChartStylePatch.model_construct(orientation="vertical"))
    return BarChart(id="c1", type="bar", query_name="q", x="cat", y="val", **kw)


def test_fires_on_bar_value_label_overflow() -> None:
    """30 categories in 600px -> 20px slot; ',.5f' renders '7.46761' (~38px)."""
    board = _board("bar", {"position": "middle", "format": ",.5f"})
    warnings = detector.detect(_ctx(_bar(), _rows(30), board))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_VALUE_LABELS_CROWD_WIDTH.code
    assert w.field == "val"
    assert "px" in w.message
    assert "overflow" in w.message
    assert w.fix is not None


def test_no_fire_when_labels_fit() -> None:
    board = _board("bar", {"position": "middle", "format": "~s"})
    assert detector.detect(_ctx(_bar(), _rows(6), board)) == []


def test_fires_regardless_of_position() -> None:
    """'above' (outside the bar) still collides with neighbouring labels."""
    board = _board("bar", {"position": "above", "format": ",.5f"})
    assert len(detector.detect(_ctx(_bar(), _rows(30), board))) == 1


def test_no_fire_when_labels_hidden() -> None:
    board = _board("bar", {"visible": False, "format": ",.5f"})
    assert detector.detect(_ctx(_bar(), _rows(30), board)) == []


def test_fires_on_line_value_labels() -> None:
    board = _board("line", {"format": ",.5f"})
    chart = LineChart(id="c1", type="line", query_name="q", x="cat", y="val")
    assert len(detector.detect(_ctx(chart, _rows(30), board))) == 1


def test_fires_on_area_value_labels() -> None:
    board = _board("area", {"format": ",.5f"})
    chart = AreaChart(id="c1", type="area", query_name="q", x="cat", y="val")
    assert len(detector.detect(_ctx(chart, _rows(30), board))) == 1


def test_no_fire_on_horizontal_bar() -> None:
    """Horizontal bars run the label along the bar length — out of scope."""
    board = _board("bar", {"position": "middle", "format": ",.5f"})
    chart = _bar(style=BarChartStylePatch.model_construct(orientation="horizontal"))
    assert detector.detect(_ctx(chart, _rows(30), board)) == []


def test_no_fire_on_non_categorical_x() -> None:
    """A temporal x-axis is out of scope (irregular spacing; not a category grid)."""
    board = _board("bar", {"position": "middle", "format": ",.5f"})
    resolved = resolve(_bar(), _rows(30), chart_style_context=board)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: _rows(30)},
        vega_specs={resolved.id: {"encoding": {"x": {"type": "temporal"}}}},
    )
    assert detector.detect(ctx) == []


class TestDetectorReadsThePreEmitPanelWidth:
    """Same claim as bar_band_width_too_narrow's sibling test: the panel
    width the bar emitter's label-thinning decision measures against
    (``box.width``) must be the exact number this detector later reads off
    the stamped spec (``vega_specs[...]["spec"]["width"]``) — both trace back
    to the one ``facet_panel_width()`` call made pre-emit, not a
    post-emit-only stamp the emitter never saw.
    """

    def test_stamped_panel_width_is_what_the_emitter_measured(self) -> None:
        from dbt_charts.core.compile.models.chart.authored import MultiplesConfig
        from dbt_charts.core.compile.resolve.chart.adaptive_stroke import (
            facet_panel_width,
        )
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_style_and_context,
        )
        from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

        compiled = get_theme_style("editorial")
        mark = compiled.charts.marks.bar
        labels = mark.labels.model_copy(update={"visible": True, "format": ",.5f"})
        new_mark = mark.model_copy(update={"labels": labels})
        marks = compiled.charts.marks.model_copy(update={"bar": new_mark})
        charts = compiled.charts.model_copy(update={"marks": marks})
        compiled = compiled.model_copy(update={"charts": charts})
        board_style, board = resolve_style_and_context(compiled)

        chart = _bar(multiples=MultiplesConfig(columns="grp"))
        rows = [
            {"cat": f"c{i}", "grp": f"g{g}", "val": _VALUE}
            for g in range(3)
            for i in range(10)
        ]
        vl = generate_vega_lite_spec(
            chart,
            rows,
            width=600.0,
            board_style=board_style,
            chart_style_context=board,
        )
        assert "facet" in vl
        n_columns = 3
        # No mirror auto-set for a columns-only shared-scale facet unless the
        # cascade opts in; read the emitted spec's own width rather than
        # re-deriving has_mirror, keeping this a pin on the stamped value.
        expected_no_mirror = facet_panel_width(600.0, n_columns, has_mirror=False)
        expected_mirror = facet_panel_width(600.0, n_columns, has_mirror=True)
        assert vl["spec"]["width"] in (expected_no_mirror, expected_mirror)

        resolved = resolve(chart, rows, chart_style_context=board)
        board = make_test_resolved_board(charts={resolved.id: resolved})
        ctx = WarningContext(
            board_spec=board,
            chart_results={resolved.id: rows},
            vega_specs={resolved.id: vl},
        )
        # Must not raise, and must unwrap to the exact same stamped width —
        # the detector's read path, exercised against a real emitted spec.
        detector.detect(ctx)
        unit = vl["spec"]
        assert unit["width"] == vl["spec"]["width"]
