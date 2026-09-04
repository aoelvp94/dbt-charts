"""Detector: WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH — see its `doc`
in core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart has typed overlay ``layers`` (bar/line/area/scatter with layers: [...])
  AND at least 2 distinct y series across the base chart + its layers
  AND ratio of largest absolute-median to smallest absolute-median ≥ 100×
  AND neither of the two extreme-ratio series has axis_y set (either one
    having axis_y means the user has already opted into split scales)

A layer carrying its own ``query:`` is compared like any other — its rows come
from ``ctx.layer_results`` rather than the chart's own result set. That shape
(one query per layer) is what the deterministic migrator emits, so excluding it
would blind the detector to the corpus it helps most. A series is therefore
identified by (query, column), not column alone: two queries both selecting
``value`` are two series on one axis, not one shared scale.

Diagnostic.field is None — the issue is cross-column, not column-scoped.
The message names the two columns with the widest ratio, and the diagnostic
marks where each was authored: `path` on the larger series, `related` on the
smaller one that gets crushed.
"""

from __future__ import annotations

import statistics

from dbt_charts.core.compile.models.chart.resolved._layer import LayeredResolvedChart
from dbt_charts.core.diagnostics import (
    WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH,
    Diagnostic,
    RelatedLocation,
)
from dbt_charts.core.render.warnings.base import WarningContext
from dbt_charts.core.utils import numeric_column_values

# Ratio threshold: fire when largest-median / smallest-median ≥ this value.
_RATIO_THRESHOLD = 100.0


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per chart+layers with a ≥100× y-scale mismatch."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, LayeredResolvedChart) or not chart.layers:
            continue
        if chart_id not in ctx.chart_results:
            continue

        base_rows = ctx.chart_results[chart_id]
        layer_rows = ctx.layer_results.get(
            chart_id, {}
        )  # type-state: silent_fallback — sparse: no per-layer query, no entry

        # One entry per authored y series: (query, column, authored path,
        # axis_y_set). A layer with no authored override bakes query_name to
        # the base chart's own (see _resolve_one_layer), so comparing against
        # chart.query_name — not "is not None" — is what tells a real override
        # from an inherited one. The authored path rides along so the two
        # extremes can be marked where they were actually written.
        series: list[tuple[str | None, str, str, bool]] = []
        base_y = chart.y
        if isinstance(base_y, str):
            series.append((chart.query_name, base_y, f"charts.{chart_id}.y", False))
        for idx, layer in enumerate(chart.layers):
            if layer.y is not None:
                series.append(
                    (
                        layer.query_name,
                        layer.y,
                        f"charts.{chart_id}.layers.{idx}.y",
                        layer.axis_y.position is not None,
                    )
                )

        layer_stats: list[tuple[str, str, float, bool]] = []
        seen_series: set[tuple[str | None, str]] = set()

        for query_name, col, path, axis_y_set in series:
            # Same query and same column name is literally the same values —
            # one scale, nothing to compare.
            if (query_name, col) in seen_series:
                continue
            seen_series.add((query_name, col))

            # An override reads its own result set; a layer that inherited the
            # base chart's query reads the chart's own rows.
            if query_name == chart.query_name:
                rows = base_rows
            elif query_name in layer_rows:
                rows = layer_rows[query_name]
            else:
                # The layer's own query failed to execute — nothing to judge.
                continue

            # Use abs of each value so symmetric distributions (e.g. P&L deltas)
            # don't cancel to a zero median and get incorrectly dropped.
            abs_values = [abs(v) for v in numeric_column_values(rows, col)]
            if not abs_values:
                continue

            abs_median = statistics.median(abs_values)
            # Skip columns whose absolute-median is 0 — dividing by zero is undefined.
            if abs_median == 0.0:
                continue

            layer_stats.append((path, col, abs_median, axis_y_set))

        if len(layer_stats) < 2:
            continue

        # Find the pair with the largest ratio.
        max_path, max_col, max_median, max_axis_y = max(layer_stats, key=lambda t: t[2])
        min_path, min_col, min_median, min_axis_y = min(layer_stats, key=lambda t: t[2])

        ratio = max_median / min_median
        if ratio < _RATIO_THRESHOLD:
            continue

        # If either extreme column already carries an axis_y override, the user
        # has explicitly opted in to split scales — do not fire.
        if max_axis_y or min_axis_y:
            continue

        # The complaint is the *ratio between two series*, so it is anchored on
        # the larger one and carries the smaller — the one being crushed to a
        # flat line — as a related location. Marking only one of the pair, or
        # the whole chart block, loses which two columns are at odds.
        warnings.append(
            Diagnostic.from_code(
                WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH,
                chart=chart_id,
                field=None,
                path=max_path,
                related=(
                    RelatedLocation(
                        path=min_path,
                        message=(
                            f"{min_col!r} is ~{ratio:.0f}x smaller — this is the "
                            "series that flattens"
                        ),
                    ),
                ),
                message=WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH.message_template.format(
                    chart_id=chart_id, col_a=max_col, col_b=min_col, ratio=ratio
                ),
                fix=WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH.fix_template,
            )
        )

    return warnings
