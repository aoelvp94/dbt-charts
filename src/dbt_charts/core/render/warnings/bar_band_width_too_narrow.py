"""Detector: WARN_BAR_BAND_WIDTH_TOO_NARROW — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule:
  chart is a (non-horizontal) ResolvedBarChart AND
  vega_specs[chart_id].encoding.x.type in {"nominal", "ordinal"} AND
  the estimated per-bar pixel width < _MIN_BAND_WIDTH_PX, where per-bar width
  is vega_specs[chart_id].width / (distinct x values), further divided by the
  series count when the emitted spec subdivides the band with an xOffset
  channel — see _grouped_series_count below.

Floor rationale: the theme's default bar border stroke is 1px
(``marks.bar.border.width``) and the fill occupies ``band_width * 0.8``
(``marks.bar.band_width``) of each band. At the floor a bar still shows a
sliver of fill wider than the two borders bracketing it; below it, the
border strokes consume the whole band and the fill reads as a hairline or
vanishes. 4px keeps a visible margin above the ~1px point where the bug
report shows fills already gone.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.diagnostics import WARN_BAR_BAND_WIDTH_TOO_NARROW, Diagnostic
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.warnings.base import WarningContext, encoding_channel_type

# Below this per-band pixel width, the bar's fill is unreadable (see rationale above).
_MIN_BAND_WIDTH_PX = 4.0

_CATEGORICAL_TYPES = frozenset({"nominal", "ordinal"})


def _grouped_series_count(
    unit: VLDict, chart: ResolvedBarChart, rows: list[VLDict]
) -> int:
    """Bars-per-band from the emitter's own offset decision, or 1 if none.

    The bar emitter (``render/chart/emitters/bar.py``) is the single source
    of truth for whether a band is subdivided — it already accounts for
    stack mode, ``overlap: full``, wide-form grouping (``y`` as a measure
    list), and suppressing the offset channel when color is 1:1 with x (that
    would draw one solo sub-band per category, not a genuine group). Reading
    its emitted ``xOffset`` channel here means this detector reports exactly
    what renders; re-deriving the same "is this grouped" predicate from
    resolved fields drifted from that decision in both directions (false
    positives on colors the emitter doesn't group by, false negatives on
    wide-form measures it does).

    Small multiples do NOT get a lower count: Vega-Lite resolves the offset
    scale shared across facet panels by default (only ``y`` ever gets
    ``resolve.scale: independent``), so a panel facing one series value still
    divides its band across the *global* series domain, occupying a single
    sub-slot — the real render measures sub-pixel bars here, not full-width
    ones. Counting the offset field's cardinality in the chart's unpartitioned
    rows is the correct domain, not an overcount.
    """
    encoding = unit.get("encoding")
    offset = encoding.get("xOffset") if isinstance(encoding, dict) else None
    if not isinstance(offset, dict):
        return 1
    # A continuous (gradient) offset field isn't a discrete grouping — guard
    # the same way the x-axis categorical check above does.
    if offset.get("type") not in _CATEGORICAL_TYPES:
        return 1
    offset_field = offset.get("field")
    if not isinstance(offset_field, str):
        return 1
    # Wide-form charts fold measures into a synthetic label field via VL's fold
    # transform (client-side, never in query rows), so cardinality = measure count.
    if chart.wide_measures:
        measures = len(chart.wide_measures)
    else:
        measures = len({row[offset_field] for row in rows if offset_field in row})
    # A zero count means no series reached this detector at all — an empty
    # result set, or an offset field absent from every row. Treat the band as
    # undivided rather than dividing by zero: this is a diagnostic, and it must
    # never be the thing that fails a render.
    if measures == 0:
        return 1
    return measures


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per bar chart whose bands are sub-readable-width."""
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        if not isinstance(chart, ResolvedBarChart):
            continue
        if chart.orientation == "horizontal":
            continue
        if chart.x is None:
            continue
        if chart_id not in ctx.vega_specs or chart_id not in ctx.chart_results:
            continue

        # Small multiples wrap the unit spec (encoding, per-panel width) under
        # "spec" — the facet root only carries facet/config/data. Unwrap it so
        # both checks below read the panel the bands actually render into.
        spec = ctx.vega_specs[chart_id]
        unit = spec["spec"] if "facet" in spec else spec

        x_type = encoding_channel_type(unit, "x")
        if x_type not in _CATEGORICAL_TYPES:
            continue

        render_width = unit.get("width")
        if not isinstance(render_width, int | float) or render_width <= 0:
            continue

        x_field: str = chart.x
        rows = ctx.chart_results[chart_id]
        distinct = len({row[x_field] for row in rows if x_field in row})
        if distinct == 0:
            continue

        band_width = render_width / distinct
        series = _grouped_series_count(unit, chart, rows)
        bar_width = band_width / series
        if bar_width >= _MIN_BAND_WIDTH_PX:
            continue

        warnings.append(
            Diagnostic.from_code(
                WARN_BAR_BAND_WIDTH_TOO_NARROW,
                chart=chart_id,
                path=f"charts.{chart_id}.x",
                field=x_field,
                message=WARN_BAR_BAND_WIDTH_TOO_NARROW.message_template.format(
                    chart_id=chart_id,
                    distinct=distinct,
                    series=series,
                    render_width=render_width,
                    bar_width=bar_width,
                    min_band_width=_MIN_BAND_WIDTH_PX,
                ),
                fix=WARN_BAR_BAND_WIDTH_TOO_NARROW.fix_template,
            )
        )

    return warnings
