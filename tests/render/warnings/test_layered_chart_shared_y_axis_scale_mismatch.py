"""Tests for the LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH render-warning detector.

Detection rule: fires on a bar/line/area/scatter chart with typed overlay
``layers`` when the ratio of the largest absolute-median y-value (across the
base chart's own y column plus every layer's y column) to the smallest is
≥100×, AND no per-layer axis_y override is already set on the extreme-ratio
columns.

Six canonical cases from the task worksheet, adapted to the current
``chart.layers`` overlay model (no separate ``type: layered`` chart — the
base chart is a real bar/line/area/scatter chart and contributes its own y
column to the comparison alongside its layers'):
  1. Base + one layer, base median ≈ 5M, layer median ≈ 0.5, no axis_y → fires.
  2. Same as 1 but the layer has axis_y set → no warning (user opted out).
  3. Base + one layer, both medians ≈ 1M → no warning (ratio under threshold).
  4. Chart with no layers → no warning (nothing to compare against).
  5. Base + two layers, columns 1M/10/1M → fires, message names the 10-scale column.
  6. Symmetric signed data → median-of-abs still detects the scale gap.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from dbt_charts.core.compile.models.chart.authored._layer import (
    AreaLayer,
    LayerAxisYStyle,
    LineLayer,
)
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.diagnostics import (
    WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH,
    Diagnostic,
)
from dbt_charts.core.render.warnings import (
    WarningContext,
    layered_chart_shared_y_axis_scale_mismatch as detector,
)

from ...core._board_utils import (
    make_test_resolved_board,
    make_test_resolved_chart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHART_DEFAULTS: dict[str, Any] = {
    "id": "c1",
    "type": "bar",
    "query_name": "q",
    "title": "",
    "x": "month",
}


def _make_chart(**kwargs: object) -> BarChart:
    return BarChart(**{**_CHART_DEFAULTS, **kwargs})


def _make_ctx(chart: BarChart, rows: list[dict[str, Any]]) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={resolved.id: {"mark": "layered"}},
    )


# ---------------------------------------------------------------------------
# Test 1: base + one layer, base median ≈ 5M, layer median ≈ 0.5 → fires
# ---------------------------------------------------------------------------


def test_fires_base_plus_layer_large_ratio() -> None:
    """Canonical case: base revenue at 5M scale vs layer rate at 0.5 scale fires."""
    chart = _make_chart(y="revenue", layers=[LineLayer(type="line", y="rate")])
    rows = [
        {"month": "Jan", "revenue": 5_000_000.0, "rate": 0.45},
        {"month": "Feb", "revenue": 4_800_000.0, "rate": 0.55},
        {"month": "Mar", "revenue": 5_200_000.0, "rate": 0.50},
    ]
    ctx = _make_ctx(chart, rows)
    warnings = detector.detect(ctx)

    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH.code
    assert w.chart == "c1"
    assert w.field is None  # cross-column, not column-scoped
    assert "revenue" in w.message and "rate" in w.message
    assert w.fix is not None


# ---------------------------------------------------------------------------
# Test 2: same but the layer has axis_y set → no warning
# ---------------------------------------------------------------------------


def test_no_fire_when_axis_y_set_on_extreme_layer() -> None:
    """Layer with axis_y already set means user opted into split scales — no warning."""
    chart = _make_chart(
        y="revenue",
        layers=[
            LineLayer(type="line", y="rate", axis_y=LayerAxisYStyle(position="right"))
        ],
    )
    rows = [
        {"month": "Jan", "revenue": 5_000_000.0, "rate": 0.45},
        {"month": "Feb", "revenue": 4_800_000.0, "rate": 0.55},
        {"month": "Mar", "revenue": 5_200_000.0, "rate": 0.50},
    ]
    ctx = _make_ctx(chart, rows)
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# Test 3: base + one layer, both medians ≈ 1M → no warning (ratio under threshold)
# ---------------------------------------------------------------------------


def test_no_fire_when_ratio_under_threshold() -> None:
    """Base + layer at similar scale (both ~1M) must not fire."""
    chart = _make_chart(y="revenue", layers=[LineLayer(type="line", y="profit")])
    rows = [
        {"month": "Jan", "revenue": 1_000_000.0, "profit": 900_000.0},
        {"month": "Feb", "revenue": 1_100_000.0, "profit": 950_000.0},
        {"month": "Mar", "revenue": 1_050_000.0, "profit": 1_000_000.0},
    ]
    ctx = _make_ctx(chart, rows)
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# Test 4: chart with no layers → no warning
# ---------------------------------------------------------------------------


def test_no_fire_without_layers() -> None:
    """A chart with no chart.layers has nothing to compare against — skip."""
    chart = _make_chart(y="revenue")
    rows = [
        {"month": "Jan", "revenue": 5_000_000.0},
        {"month": "Feb", "revenue": 4_800_000.0},
    ]
    ctx = _make_ctx(chart, rows)
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# Test 5: base + two layers, 1M/10/1M → fires, message names the 10-scale column
# ---------------------------------------------------------------------------


def test_fires_base_plus_two_layers_one_outlier_named_in_message() -> None:
    """Base + two layers where the layer 'count' is the outlier (10 vs 1M)."""
    chart = _make_chart(
        y="revenue",
        layers=[
            LineLayer(type="line", y="count"),
            AreaLayer(type="area", y="profit"),
        ],
    )
    rows = [
        {"month": "Jan", "revenue": 1_000_000.0, "count": 10.0, "profit": 1_050_000.0},
        {"month": "Feb", "revenue": 1_100_000.0, "count": 12.0, "profit": 950_000.0},
        {"month": "Mar", "revenue": 950_000.0, "count": 8.0, "profit": 1_000_000.0},
    ]
    ctx = _make_ctx(chart, rows)
    warnings = detector.detect(ctx)

    assert len(warnings) == 1
    w = warnings[0]
    assert w.code == WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH.code
    # Message must name both ends: the outlier (count ~10) and a high-scale column.
    assert "count" in w.message
    assert "revenue" in w.message or "profit" in w.message


# ---------------------------------------------------------------------------
# Signed / symmetric data: median of abs preserves scale magnitude
# ---------------------------------------------------------------------------


def test_fires_for_symmetric_signed_data() -> None:
    """P&L deltas symmetric around zero still fire — median of abs sees ~100k scale."""
    chart = _make_chart(y="pnl", layers=[LineLayer(type="line", y="rate")])
    # pnl symmetric around 0 with magnitude ~100k; naive abs(median) would be 0
    rows = [
        {"month": "Jan", "pnl": -100_000.0, "rate": 0.5},
        {"month": "Feb", "pnl": -50_000.0, "rate": 0.4},
        {"month": "Mar", "pnl": 50_000.0, "rate": 0.6},
        {"month": "Apr", "pnl": 100_000.0, "rate": 0.5},
    ]
    ctx = _make_ctx(chart, rows)
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH.code


def test_marks_both_y_series_not_the_whole_chart_block() -> None:
    """The reported case: a 30-line chart got 30 lines of squiggle.

    The complaint is the ratio between two series, so the mark belongs on the
    two `y:` lines that disagree — the base chart's own and the layer's — not
    on the chart block that contains them.
    """
    chart = _make_chart(
        y="revenue_annual_recurring_revenue",
        layers=[LineLayer(type="line", y="arr")],
    )
    rows = [
        {
            "month": f"2026-{m:02d}",
            "revenue_annual_recurring_revenue": 1_000_000.0 * m,
            "arr": 5.0 * m,
        }
        for m in range(1, 13)
    ]
    warnings = detector.detect(_make_ctx(chart, rows))

    assert len(warnings) == 1
    w = warnings[0]
    # Anchored on one of the two y columns, never the bare chart block.
    assert w.path in {"charts.c1.y", "charts.c1.layers.0.y"}
    assert w.path != "charts.c1"
    # And the other half of the pair is named too, with a label saying why.
    assert len(w.related) == 1
    assert w.related[0].path in {"charts.c1.y", "charts.c1.layers.0.y"}
    assert w.related[0].path != w.path
    assert w.related[0].message is not None


# ---------------------------------------------------------------------------
# Regression: Decimal columns must not raise TypeError (Decimal / float)
# ---------------------------------------------------------------------------


def test_fires_with_decimal_and_float_columns_no_type_error() -> None:
    """Decimal revenue column alongside float rate column must not raise TypeError.

    Before the fix, abs_values collected Decimal values; statistics.median
    returned Decimal for the first column and float for the second.  The
    cross-column ratio (max_median / min_median) then raised
    ``TypeError: unsupported operand type(s) for /: 'decimal.Decimal' and 'float'``.
    """
    chart = _make_chart(y="revenue", layers=[LineLayer(type="line", y="rate")])
    rows = [
        {"month": "Jan", "revenue": Decimal("5000000"), "rate": 0.45},
        {"month": "Feb", "revenue": Decimal("4800000"), "rate": 0.55},
        {"month": "Mar", "revenue": Decimal("5200000"), "rate": 0.50},
    ]
    ctx = _make_ctx(chart, rows)
    # Must not raise; must still detect the ≥100× scale mismatch.
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH.code
