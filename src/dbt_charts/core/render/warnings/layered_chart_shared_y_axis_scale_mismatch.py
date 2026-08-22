"""Detector: WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH — see its `doc`
in core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart has typed overlay ``layers`` (bar/line/area/scatter with layers: [...])
  AND at least 2 distinct y columns across the base chart + its layers
  AND no layer carries its own query: (cross-query scale comparison is out of
    scope for v1 — per-layer queries produce separate result sets that are
    only keyed by chart id, so there is no clean way to attribute column
    ownership across layers)
  AND ratio of largest absolute-median to smallest absolute-median ≥ 100×
  AND neither of the two extreme-ratio columns has axis_y set (either one
    having axis_y means the user has already opted into split scales)

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

        # Skip if any layer overrides the base chart's own query — cross-query
        # scale comparison is out of scope: chart_results is keyed by chart id
        # only. A layer with no authored override bakes query_name to the
        # base chart's own (see _resolve_one_layer), so "differs from the
        # base" — not "is not None" — is the real override signal.
        if any(layer.query_name != chart.query_name for layer in chart.layers):
            continue

        rows = ctx.chart_results[chart_id]
        if not rows:
            continue

        # Collect (column_name, absolute_median, axis_y_set) for the base
        # chart's own y column plus every layer's y column. The authored path
        # each column came from rides along so the two extremes can be marked
        # where they were actually written.
        column_axis_y: list[tuple[str, bool]] = []
        column_paths: dict[str, str] = {}
        base_y = chart.y
        if isinstance(base_y, str):
            column_axis_y.append((base_y, False))
            column_paths[base_y] = f"charts.{chart_id}.y"
        for idx, layer in enumerate(chart.layers):
            if layer.y is not None:
                column_axis_y.append((layer.y, layer.axis_y.position is not None))
                column_paths.setdefault(layer.y, f"charts.{chart_id}.layers.{idx}.y")

        layer_stats: list[tuple[str, float, bool]] = []
        seen_columns: set[str] = set()

        for col, axis_y_set in column_axis_y:
            # Columns sharing the same name share a scale by design — skip.
            if col in seen_columns:
                continue
            seen_columns.add(col)

            # Use abs of each value so symmetric distributions (e.g. P&L deltas)
            # don't cancel to a zero median and get incorrectly dropped.
            abs_values = [abs(v) for v in numeric_column_values(rows, col)]
            if not abs_values:
                continue

            abs_median = statistics.median(abs_values)
            # Skip columns whose absolute-median is 0 — dividing by zero is undefined.
            if abs_median == 0.0:
                continue

            layer_stats.append((col, abs_median, axis_y_set))

        if len(layer_stats) < 2:
            continue

        # Find the pair with the largest ratio.
        max_col, max_median, max_axis_y = max(layer_stats, key=lambda t: t[1])
        min_col, min_median, min_axis_y = min(layer_stats, key=lambda t: t[1])

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
                path=column_paths[max_col],
                related=(
                    RelatedLocation(
                        path=column_paths[min_col],
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
