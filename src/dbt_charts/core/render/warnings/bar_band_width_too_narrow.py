"""Detector: WARN_BAR_BAND_WIDTH_TOO_NARROW — see its `doc` in
core/diagnostics/codes_render.py for what this fires on.

Detection rule, categorical x (nominal/ordinal — a genuine band scale):
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

Detection rule, continuous x (quantitative — no band, see
``continuous_bar_size_prop``): the bar's effective width (authored
``bar.size``, or the computed ``gap``/``min_size``/``max_size`` ladder)
exceeds the minimum pixel gap between adjacent distinct x values — bars will
visually overlap. This is a DIFFERENT failure mode than the categorical
case's readability floor (collision, not unreadable fill — the comparison
direction is inverted: ``bar_width`` crosses ``min_band_width`` from above
here, from below in the categorical case), so it gets its own comparison in
``_detect_continuous_overlap`` — the SAME diagnostic code as the categorical
case, per this repo's inform-don't-intervene policy (a bound ``min_size``
clamp, or an author's own oversized ``bar.size``, is never silently squeezed
to fit, only reported), but its OWN message wording
(``_CONTINUOUS_MESSAGE_TEMPLATE`` below): there is no band scale here at all
(``distinct`` counting "bands" is a categorical-only concept), and the two
branches' numbers don't share a printable shape — ``codes_render.py``'s
shared ``message_template`` prints one rounded number into both the bar
width and the threshold slots, which reads self-contradictory once
``min_band_width`` carries a live measured ``step_px`` instead of the
categorical branch's fixed floor constant.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.resolve.chart._wide_fields import wide_series_names
from dbt_charts.core.diagnostics import WARN_BAR_BAND_WIDTH_TOO_NARROW, Diagnostic
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters._cartesian import widest_panel_distinct_count
from dbt_charts.core.render.chart.vl_field_maps import effective_bar_size
from dbt_charts.core.render.warnings.base import (
    WarningContext,
    encoding_channel_type,
    facet_channel_is_independent,
)
from dbt_charts.core.utils import coerce_numeric_cell

# Below this per-band pixel width, the bar's fill is unreadable (see rationale above).
_MIN_BAND_WIDTH_PX = 4.0

_CATEGORICAL_TYPES = frozenset({"nominal", "ordinal"})

# Own wording for the continuous-x branch — see the module docstring for why
# this doesn't reuse WARN_BAR_BAND_WIDTH_TOO_NARROW.message_template (the
# categorical branch's "N bands" framing doesn't apply to a scale with no
# band, and printing bar_width/min_band_width through the same rounded shape
# reads self-contradictory once min_band_width carries a live step_px).
_CONTINUOUS_MESSAGE_TEMPLATE = (
    "Chart {chart_id!r} draws {distinct} bars ~{bar_width:.2f}px wide across "
    "{render_width:.0f}px, but the closest two x values are only "
    "~{step_px:.2f}px apart — bars will overlap their neighbors."
)


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

    Small multiples do NOT get a lower count here: the offset/colour scale is
    never one of the channels ``facet_bound_position_channels``
    (``emitters/_cartesian.py``) can narrow — only a position channel (``x``/
    ``y``) resolves independently, when a panel's own rows carry a proper
    subset of that channel's domain, and colour stays shared across panels
    by design (cross-panel colour identity) regardless. So a panel facing
    one series value still divides its band across the *global* series
    domain, occupying a single sub-slot — the real render measures
    sub-pixel bars here, not full-width ones. Counting the offset field's
    cardinality in the chart's unpartitioned rows is the correct domain, not
    an overcount.

    The outer x-axis band count is a different story — see ``detect()``'s own
    check of the emitted ``resolve.scale.x``.
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
    # transform (client-side, never in query rows): cardinality = measures ×
    # the authored dimension's values.
    if chart.wide_measures:
        measures = len(wide_series_names(chart.wide_measures, chart.color, rows))
    else:
        measures = len({row[offset_field] for row in rows if offset_field in row})
    # A zero count means no series reached this detector at all — an empty
    # result set, or an offset field absent from every row. Treat the band as
    # undivided rather than dividing by zero: this is a diagnostic, and it must
    # never be the thing that fails a render.
    if measures == 0:
        return 1
    return measures


def _detect_continuous_overlap(
    chart_id: str,
    chart: ResolvedBarChart,
    render_width: float,
    rows: list[VLDict],
    x_field: str,
) -> Diagnostic | None:
    """Continuous (quantitative) x: warn when the bar's effective width
    would overlap its neighbor — see the module docstring's continuous-x
    rule for why this is a different comparison, and message, than the
    categorical readability floor above.

    ``render_width`` is the chart's whole plot width, but the emitter
    installs ``padding = effective_bar_size / 2`` on each side of a
    quantitative x scale (``bar.py``'s ``_emit_vertical``, so the min/max
    bars stay fully on-plot), for one ``effective_bar_size`` of chrome in
    total — a plain ``render_width / domain_span`` treats
    that reserved chrome as usable domain span and systematically
    overestimates the real per-value pixel step, which can miss an overlap
    the live scale would actually render (the estimate never models VL's own
    ``nice`` domain rounding either — this narrows, not closes, that gap).
    """
    xs = sorted(
        {
            coerced
            for row in rows
            if x_field in row
            and (coerced := coerce_numeric_cell(row[x_field])) is not None
        }
    )
    if len(xs) < 2:
        return None
    domain_span = xs[-1] - xs[0]
    if domain_span <= 0:
        return None

    bar = chart.style.mark
    reserved = effective_bar_size(bar)
    assert reserved is not None, (
        "marks.bar.size and marks.bar.max_size both unset — "
        "theme cascade must populate at least one"
    )
    # padding is effective_bar_size / 2 on EACH side, so the total reserved
    # chrome is one effective_bar_size, not two. Subtracting twice understates
    # every step this warning prints and fires it on charts that do not overlap.
    usable_width = render_width - reserved
    if usable_width <= 0:
        return None
    px_per_unit = usable_width / domain_span
    step_px = min(b - a for a, b in zip(xs, xs[1:], strict=False)) * px_per_unit

    if bar.size is not None:
        effective_width = bar.size
    else:
        assert bar.gap is not None, (
            "marks.bar.gap unset — theme cascade must populate it when marks.bar.size is unset"
        )
        assert bar.min_size is not None, (
            "marks.bar.min_size unset — theme cascade must populate it "
            "when marks.bar.size is unset"
        )
        assert bar.max_size is not None, (
            "marks.bar.max_size unset — theme cascade must populate it "
            "when marks.bar.size is unset"
        )
        effective_width = min(max(step_px - bar.gap, bar.min_size), bar.max_size)
    if effective_width <= step_px:
        return None

    return Diagnostic.from_code(
        WARN_BAR_BAND_WIDTH_TOO_NARROW,
        chart=chart_id,
        path=f"charts.{chart_id}.x",
        field=x_field,
        message=_CONTINUOUS_MESSAGE_TEMPLATE.format(
            chart_id=chart_id,
            distinct=len(xs),
            render_width=render_width,
            bar_width=effective_width,
            step_px=step_px,
        ),
        fix=WARN_BAR_BAND_WIDTH_TOO_NARROW.fix_template,
    )


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per bar chart whose bars are too wide for their x spacing."""
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
        render_width = unit.get("width")
        if not isinstance(render_width, int | float) or render_width <= 0:
            continue

        x_field: str = chart.x
        rows = ctx.chart_results[chart_id]

        if x_type == "quantitative":
            # A histogram's x is quantitative but BINNED: _emit_histogram sizes
            # its mark as a band fraction of the bin span and installs no
            # scale.padding, so neither premise of the continuous ladder holds.
            # Running it over the raw, unbinned rows reports the row spacing as
            # a bar gap and the row count as a bar count — every number in the
            # message fictional. Same carve-out, same reason, as the bucketed
            # -axis detector's own histogram guard.
            if chart.chart_type == "histogram":
                continue
            diagnostic = _detect_continuous_overlap(
                chart_id, chart, render_width, rows, x_field
            )
            if diagnostic is not None:
                warnings.append(diagnostic)
            continue
        if x_type not in _CATEGORICAL_TYPES:
            continue

        whole_dataset_distinct = len({row[x_field] for row in rows if x_field in row})
        # facet_bound_position_channels (emitters/_cartesian.py) can resolve
        # x independently for a panel holding any proper subset of the x
        # domain, not only the single-value case a name-matched facet field
        # used to guarantee by construction — read the WIDEST panel's own
        # count, not the whole-dataset union `rows` would give (and not a
        # flat 1, which only ever held for that one degenerate shape).
        if facet_channel_is_independent(spec, "x"):
            distinct = (
                widest_panel_distinct_count(x_field, chart.panel_axes, rows)
                or whole_dataset_distinct
            )
        else:
            distinct = whole_dataset_distinct
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
