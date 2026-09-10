"""Tests for the TOO_MANY_X_CATEGORIES render-warning detector.

Detection rule: fires when a nominal/ordinal x-axis has > 50 distinct values,
and on a bar chart's temporal x-axis too. A quantitative x-axis never trips it,
nor does a temporal axis on line/area/scatter.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
    Chart,
    LineChart,
    PieChart,
)
from dbt_charts.core.diagnostics import WARN_TOO_MANY_X_CATEGORIES, Diagnostic
from dbt_charts.core.render.warnings import (
    WarningContext,
    too_many_x_categories as detector,
)

from ...core._board_utils import make_test_resolved_board, make_test_resolved_chart


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"cat": f"c{i}", "val": i} for i in range(n)]


def _make_ctx(chart: Chart, rows: list[dict[str, Any]], x_type: str) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: {"encoding": {"x": {"type": x_type}}}},
    )


def test_fires_above_threshold_on_nominal_x() -> None:
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    warnings = detector.detect(_make_ctx(chart, _rows(51), "nominal"))
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_TOO_MANY_X_CATEGORIES.code
    assert w.field == "cat"
    assert "51" in w.message
    assert w.fix is not None


def test_no_fire_at_threshold() -> None:
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    assert detector.detect(_make_ctx(chart, _rows(50), "nominal")) == []


def test_no_fire_on_temporal_x_for_line() -> None:
    """A line chart's temporal axis is a continuous draw, not a per-x band —
    density alone is never a defect there, however many points."""
    chart = LineChart(id="c1", type="line", query_name="q", x="cat", y="val")
    assert detector.detect(_make_ctx(chart, _rows(100), "temporal")) == []


def test_fires_on_temporal_x_for_bar_above_threshold() -> None:
    """The density gate flips a bucketed temporal x-axis from ordinal to
    temporal above ~60 points — a bar still draws one band per distinct
    value regardless of the Vega-Lite encoding type, so the crowding warning
    must not go blind when that flip happens.
    """
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    warnings = detector.detect(_make_ctx(chart, _rows(200), "temporal"))
    assert len(warnings) == 1
    assert warnings[0].code == WARN_TOO_MANY_X_CATEGORIES.code
    assert "200" in warnings[0].message


def test_no_fire_on_temporal_x_for_bar_at_low_density() -> None:
    """Below the threshold, a temporal bar axis stays silent same as ordinal."""
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    assert detector.detect(_make_ctx(chart, _rows(50), "temporal")) == []


def test_no_fire_without_x() -> None:
    chart = PieChart(id="c1", type="pie", query_name="q", theta="val", color="cat")
    assert detector.detect(_make_ctx(chart, _rows(60), "nominal")) == []


def _month_rows(n: int) -> list[dict[str, Any]]:
    return [
        {"cat": date(2019 + i // 12, i % 12 + 1, 1), "val": i * 1.0} for i in range(n)
    ]


class TestTemporalBarWording:
    """The temporal arm fires for band thinning, so it must not borrow the
    categorical arm's words: no label-collision claim, no category-shaped fix.
    """

    def _warning(self) -> Diagnostic:
        chart = BarChart(id="monthly", type="bar", query_name="q", x="cat", y="val")
        rows = _month_rows(76)
        warnings = detector.detect(_make_ctx(chart, rows, "temporal"))
        assert len(warnings) == 1
        return warnings[0]

    def test_message_claims_no_label_collision(self) -> None:
        message = self._warning().message
        assert "collide" not in message
        assert "labels" not in message
        assert "76" in message

    def test_fix_drops_the_categorical_vocabulary(self) -> None:
        fix = self._warning().fix
        assert fix is not None
        assert "top N" not in fix
        assert "table" not in fix
        assert "categories" not in fix

    def test_message_is_the_temporal_template_verbatim(self) -> None:
        """Pins wording and threshold together: the only limit this detector
        applies is its own category count, so that is the only one it may name.
        """
        assert self._warning().message == (
            "Chart 'monthly': x field 'cat' has 76 distinct time buckets; "
            "a bar draws one band per bucket, so the bands are too thin to read "
            f"(limit: {detector._MAX_CATEGORIES})."
        )


def test_categorical_arm_still_reads_the_registry_templates() -> None:
    """The temporal branch must not leak into the nominal/ordinal arm, which
    keeps deriving both strings from the registry.
    """
    chart = BarChart(id="c1", type="bar", query_name="q", x="cat", y="val")
    warnings = detector.detect(_make_ctx(chart, _rows(51), "nominal"))
    assert warnings[0].message == WARN_TOO_MANY_X_CATEGORIES.message_template.format(
        chart_id="c1", field="cat", count=51, max_categories=detector._MAX_CATEGORIES
    )
    assert warnings[0].fix == WARN_TOO_MANY_X_CATEGORIES.fix_template
