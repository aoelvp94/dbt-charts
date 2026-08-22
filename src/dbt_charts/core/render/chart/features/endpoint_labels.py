"""Endpoint label feature: sets endpoint_label_layout and pre-computes label data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from dbt_charts.core.compile.models.chart.resolved import ResolvedChart
from dbt_charts.core.compile.models.chart.resolved._base import _BaseResolvedChartFields
from dbt_charts.core.compile.models.chart.resolved.area import ResolvedAreaChart
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.chart.resolved.line import ResolvedLineChart
from dbt_charts.core.compile.models.style.resolved._base import ResolvedAxisStyle
from dbt_charts.core.compile.resolve.chart._wide_fields import (
    WIDE_LABEL_FIELD,
    WIDE_VALUE_FIELD,
)
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.artifacts import ChartRenderData
from dbt_charts.core.render.chart.emitters._cartesian import (
    NATIVE_STACK_ORDER,
    last_nonnull_value_per_series,
    sorted_series_by_stack_order,
)
from dbt_charts.core.text.case import format_display_text
from dbt_charts.core.utils import (
    layered_endpoint_rail_fires,
    layered_endpoint_rail_shape,
    numeric_column_values,
    stacked_x_domain_order,
)


def _apply_label_cascade(
    anchors: dict[str, float],
    min_data_gap: float,
    y_domain_min: float,
    y_domain_max: float,
) -> list[tuple[str, float]]:
    """Bidirectional greedy collision-avoidance over an anchor map.

    Output is ordered top-to-bottom (descending y).
    """
    if not anchors:
        return []

    domain_mid = (y_domain_min + y_domain_max) / 2.0
    anchor_mean = sum(anchors.values()) / len(anchors)

    if anchor_mean >= domain_mid:
        items = sorted(anchors.items(), key=lambda kv: kv[1], reverse=True)
        adjusted: list[tuple[str, float]] = []
        for series, y in items:
            if adjusted and adjusted[-1][1] - y < min_data_gap:
                y = adjusted[-1][1] - min_data_gap
            y = max(y_domain_min, y)
            adjusted.append((series, y))
        return adjusted

    items = sorted(anchors.items(), key=lambda kv: kv[1])
    upward: list[tuple[str, float]] = []
    for series, y in items:
        if upward and y - upward[-1][1] < min_data_gap:
            y = upward[-1][1] + min_data_gap
        y = min(y_domain_max, y)
        upward.append((series, y))
    return list(reversed(upward))


from dbt_charts.core.compile.config import get_chart_rendering
from dbt_charts.core.font_measure import get_font_measurer
from dbt_charts.core.render.chart.feature import chart_rows
from dbt_charts.core.render.chart.series_label_truncation import (
    SeriesLabelSource,
    record_series_label_truncations,
)
from dbt_charts.core.render.chart.spec import ChartSpec, EndpointLabelData, RenderBox

_LABEL_GAP_PX = 4.0  # horizontal gap between last measured char and pane edge

# Alias for the position column in the pre-computed inline data.
_Y_ALIAS = "__y"
_X_ALIAS = "__x"
# Alias for the label-text column on the layered-single-series rail (no real
# data column names a "series" there — each entry is a layer, not a row value).
_LABEL_ALIAS = "__label"


def _y_domain(
    data: list[dict[str, Any]],
    y_field: str,
    axis_y: ResolvedAxisStyle,
) -> tuple[float, float]:
    """Return (y_min, y_max) for the cascade domain.

    Prefers an explicit authored axis_y.scale.domain (2-element numeric list)
    so cascade decisions use the same bounds as VL's rendered y scale. Falls
    back to raw data range when no explicit domain is authored.
    """
    if axis_y.scale is not None:
        _ay_cont_el = axis_y.scale.continuous
        domain = _ay_cont_el.domain if _ay_cont_el is not None else None
        if domain is not None:
            try:
                lo, hi = float(domain[0]), float(domain[1])
                if hi >= lo:
                    return lo, hi
            except (TypeError, ValueError):
                pass
    ys = [
        float(row[y_field])
        for row in data
        if y_field in row and row[y_field] is not None
    ]
    if ys:
        return float(min(ys)), float(max(ys))
    return 0.0, 1.0


def _stacked_y_domain(
    data: list[dict[str, Any]],
    x_field: str,
    y_field: str,
    stack: str | None,
) -> tuple[float, float]:
    """Return the rendered (y_min, y_max) domain for a stacked bar or area chart.

    normalize → [0,1]; grouped → data range clamped at 0; stacked-zero →
    [0, max column total]. The column-sum math is identical for bar and
    area — both cumulate the same y_field per x.

    ``center`` (streamgraph) renders on this SAME [0, max column total] domain,
    not a domain symmetric around zero: Vega-Lite's own center-offset formula
    (see ``_stacked_midpoints``) floats each column up by
    ``(max_total - this_column_total) / 2``, so the column matching
    max_total sits flush at [0, max_total] and every shorter column floats
    upward but never exceeds that same ceiling — confirmed against Vega's
    compiled scenegraph output (vl-convert), not assumed.
    """
    if stack == "normalize":
        return 0.0, 1.0
    ys = [
        float(row[y_field])
        for row in data
        if y_field in row and row[y_field] is not None
    ]
    if not ys:
        return 0.0, 1.0
    if stack == "none":
        return min(0.0, min(ys)), max(0.0, max(ys))
    # "zero"/"center": column-sum math is identical for both.
    col_sums: dict[object, float] = {}
    for row in data:
        x = row.get(x_field)
        y = row.get(y_field)
        if x is not None and y is not None:
            if x not in col_sums:
                col_sums[x] = 0.0
            col_sums[x] += float(y)
    return 0.0, (max(col_sums.values()) if col_sums else max(ys))


@dataclass(frozen=True)
class RecascadeResult:
    """Final label positions plus the outcome that produced them.

    Three distinct outcomes, deliberately not one boolean: they have different
    causes and different remedies, and collapsing them made the rail report a
    height problem for a case height cannot cause or cure.

    - ``fit`` — the intended gap was honoured.
    - ``gap_did_not_fit`` — the gap is known but ``(n-1) * gap`` exceeds the
      domain span. More height (or fewer series) resolves it.
    - ``no_slope`` — no pixels-per-data-unit could be measured, because every
      label ties on one value or the scale collapsed them onto one pixel. The
      plot's height is irrelevant here; the data is.
    """

    positions: list[tuple[str, float]]
    outcome: Literal["fit", "gap_did_not_fit", "no_slope"]


def _measure_label_pane_slope(
    label_mark_leaves: list[VLDict], emitted: dict[str, float]
) -> float | None:
    """Pixels-per-data-unit slope measured off the label pane's own rendered marks.

    We place the endpoint labels ourselves, so each mark's data-space value is
    already known (``anchors``); vl-convert's probe scenegraph carries each
    mark's rendered pixel ``y`` plus its own ``text`` — the exact series/label
    name, since the pane's ``text`` encoding is ``{"field": series_field}``.
    Pairing a mark's known value with its observed pixel position gives
    px-per-data-unit directly, with no need to read (and no risk of
    misreading) the rendered y-scale's resolved domain, which
    ``vegalite_to_scenegraph`` does not expose at all.

    Matches leaves to anchors by rendered text, not list position — leaf
    order in the scenegraph is not a contract, and this is exactly as
    collision-safe: ``anchors`` is already keyed by the same series_field
    value, so two distinct anchors can never render the same text. (Vega's
    auto-generated ``description`` — ``"field: value"`` — would work too on
    the ordinary series-color path, but is silently omitted for a
    double-underscore-prefixed field name, which is exactly what the
    layered-single-series path's ``series_field`` is; ``text`` has no such
    gap.) Picks the pair with the largest known-value spread for numerical
    stability.

    Returns ``None`` when no slope is defined: fewer than two leaves matched a
    known anchor, every matched leaf ties on the same data value (real data
    produces this — a stacked series whose trailing values are all null lands
    every label on the same total), or two distinct values render at the same
    pixel (a collapsed scale, e.g. an authored ``scale.domain: [5, 5]``).

    None is not an error, and it is not the end of the story: the caller falls
    back to even distribution, which needs no slope. Raising here instead would
    blank the whole chart over a label-placement detail.
    """
    matched: list[tuple[float, float]] = []
    for leaf in label_mark_leaves:
        text = leaf.get("text")
        if not isinstance(text, str):
            continue
        value = emitted.get(text)
        if value is not None:
            matched.append((value, float(leaf["y"])))
    if len(matched) < 2:
        return None
    lo = min(matched, key=lambda pair: pair[0])
    hi = max(matched, key=lambda pair: pair[0])
    if hi[0] == lo[0] or hi[1] == lo[1]:
        return None
    return (hi[1] - lo[1]) / (hi[0] - lo[0])


def _distribute_evenly(
    anchors: dict[str, float],
    y_domain_min: float,
    y_domain_max: float,
    outcome: Literal["gap_did_not_fit", "no_slope"],
) -> RecascadeResult:
    """Spread labels evenly across the domain, preserving their relative order.

    The answer whenever the intended gap cannot be honoured — because it does
    not fit, or because no slope exists to express it in data units. It needs
    no slope: positions are assigned from the domain directly. Always reports
    a non-``fit`` outcome so the caller records the degradation; an unreported
    one would be a silent fallback.

    A zero-width domain leaves every position identical — there is nowhere to
    spread into — which is honest rather than fabricated separation.
    """
    n = len(anchors)
    step = (y_domain_max - y_domain_min) / (n - 1) if n > 1 else 0.0
    # Ascending by value, then ascending y. Python's sort is stable, so a tie
    # group keeps insertion order — which on the stacked path is baseline-first
    # (`_stacked_midpoints` accumulates from 0 upward). Assigning y upward from
    # y_domain_min therefore puts the baseline series at the bottom, matching
    # `_apply_label_cascade`. Sorting descending and mapping down from
    # y_domain_max looks equivalent but inverts every tie group, and the rail
    # replaces the color legend — its vertical order IS the series order, so an
    # inverted tie group is a wrong picture drawn from correct data.
    ordered = sorted(anchors.items(), key=lambda kv: kv[1])
    placed = [(name, y_domain_min + i * step) for i, (name, _) in enumerate(ordered)]
    placed.reverse()  # emit top-to-bottom, as `_apply_label_cascade` does
    return RecascadeResult(positions=placed, outcome=outcome)


def recascade_endpoint_labels(
    anchors: dict[str, float],
    pixel_gap: float,
    y_domain_min: float,
    y_domain_max: float,
    label_mark_leaves: list[VLDict],
    height_correction_ratio: float,
    emitted: dict[str, float],
) -> RecascadeResult:
    """Re-cascade endpoint labels against the plot geometry Vega-Lite actually resolved.

    The one entry point that turns an intended *pixel* gap into final
    data-unit label positions. Everything the pixel<->data conversion and the
    greedy nudge need lives here — the converter that calls this supplies
    only measurements (the raw anchor values, the probe's label marks, and
    the pane's height-correction ratio) and never does cascade arithmetic
    itself.

    N=1 (``anchors`` has at most one entry) is a no-op: there is no adjacent
    pair to separate, so the single anchor's position is already correct —
    skip measuring a slope (there would be no second point to measure it
    against) rather than inventing a fallback for a case with no work in it.

    Otherwise, measures px-per-data-unit off the rendered label marks
    (``_measure_label_pane_slope``) — but that measurement comes from a probe
    of the pane at its *pre-correction* declared height, while the real render
    uses the pane at its *post-correction* height (the overshoot correction
    shrinks both hconcat panes so their outer heights keep matching, per
    ``converters/chart._correct_concat_overshoot``). The label pane carries no
    axis or title (``translate.py``'s ``_wrap_hconcat_label_pane``: ``axis:
    None``, no title block), so unlike the main pane it has no chrome eating
    into its declared height — its plot rectangle *is* its declared height,
    both before and after correction. That makes the slope scale by the exact
    same ratio the pane's own height was corrected by: ``height_correction_ratio``
    (``corrected_height / pre_correction_height``, decided by the caller — 1.0
    when nothing was corrected, e.g. a chart rendered with ``height=None``),
    with no second probe needed to confirm it.

    The intended pixel gap is converted into a data-unit gap via that
    corrected slope, then run through the same bidirectional greedy cascade
    (``_apply_label_cascade``) used everywhere else, which holds each label to
    the raw data extent on the side it nudges toward. Every real endpoint
    already sits inside ``[y_domain_min, y_domain_max]`` — the extent is its
    own min and max — so no label is pushed past a bound, and none can widen
    the shared y-scale the slope was measured against (the non-circularity
    invariant this whole approach rests on).

    Two conditions make the intended gap unsatisfiable, and both take the same
    exit (``_distribute_evenly``), each tagged with its own outcome so the
    warning names the real cause:

    - ``(n - 1) * data_gap`` exceeds the domain span — the gap is known but
      does not fit.
    - No slope could be measured at all, so the gap cannot be expressed in
      data units in the first place.

    Even distribution needs no slope, so it serves both. Reporting it is what
    keeps this a defined degradation rather than a silent fallback, and the
    result stays inside ``[y_domain_min, y_domain_max]`` either way.
    """
    if len(anchors) <= 1:
        return RecascadeResult(positions=list(anchors.items()), outcome="fit")
    if height_correction_ratio <= 0:
        raise ChartDataError(
            "could not re-cascade endpoint labels: height_correction_ratio "
            f"must be positive, got {height_correction_ratio}"
        )
    domain_span = y_domain_max - y_domain_min
    n = len(anchors)
    # Measure against the values the pane actually emitted, which may have been
    # spread apart to break a tie; place against the true anchors. Pairing
    # pixels with tied anchors would measure nothing.
    raw_slope = _measure_label_pane_slope(label_mark_leaves, emitted)
    if raw_slope is None:
        # No slope exists to convert the pixel target into data units — every
        # label ties on one value, or the scale collapsed them onto one pixel.
        # Even distribution is still available and needs no slope, so take it
        # and report it: leaving the ties in place would stack every label on
        # one coordinate and say nothing about having done so.
        return _distribute_evenly(anchors, y_domain_min, y_domain_max, "no_slope")
    slope = raw_slope * height_correction_ratio
    data_gap = pixel_gap / abs(slope)
    if domain_span > 0 and (n - 1) * data_gap > domain_span:
        return _distribute_evenly(
            anchors, y_domain_min, y_domain_max, "gap_did_not_fit"
        )
    positions = _apply_label_cascade(
        anchors,
        min_data_gap=data_gap,
        y_domain_min=y_domain_min,
        y_domain_max=y_domain_max,
    )
    return RecascadeResult(positions=positions, outcome="fit")


def _refuse_unorderable_sort(
    chart_id: str, data: list[dict[str, Any]], sort: Any
) -> None:
    """Refuse a `sort:` whose column carries no numbers to total.

    ``stacked_x_domain_order`` reproduces Vega-Lite's domain order by summing
    the sort field per category, which is what VL's default ``sum`` op does.
    On a non-numeric column VL concatenates the strings instead — an order this
    cannot reproduce — so the rail would anchor on a row VL does not draw on
    top. Resolve steers the default away from this shape; an explicit opt-in
    lands here and gets told why.
    """
    if sort is None or numeric_column_values(data, sort.by):
        return
    raise ChartDataError(
        f"chart.sort by {sort.by!r} cannot be combined with stacked bar "
        "endpoint labels — the label rail reproduces Vega-Lite's domain order "
        "by totalling that column per category, and it carries no numeric "
        "values. To fix: sort by a measure, or set "
        "endpoint_labels.visible: false on this chart.",
        chart_id,
    )


def _stacked_midpoints(
    data: list[dict[str, Any]],
    x_field: str,
    y_field: str,
    series_field: str,
    series_names: list[str],
    stack_mode: str,
    max_column_total: float,
    sort_by: str,
    descending: bool,
    stack_order: str | None = None,
) -> list[tuple[str, float]]:
    """Compute cumulative segment midpoints for vertical stacked bars or areas.

    Finds the last (lexicographically greatest) x value and computes the
    y-midpoint of each series' stacked segment at that position. Returns raw,
    un-cascaded midpoints — the greedy-nudge pass runs later, once the real
    plot geometry is known (see ``recascade_endpoint_labels``). Series/x/y-field
    generic — used by both the bar and area families.

    Every name in *series_names* gets an anchor, including a series with no
    row in the anchor column: it is zero-height there, so its anchor is the
    seam between its neighbours — the place its band would begin. The rail
    replaces the colour legend, so a dropped anchor would leave that series
    painting segments in other columns under no name anywhere on the chart.

    Sort order (baseline = cumulative zero):
    - None / "value": largest global sum at baseline (VL's joinaggregate default).
    - "alphabetical": alphabetically first series at baseline.
    - "data": globally first-encountered series at baseline.
    - ``NATIVE_STACK_ORDER``: Vega-Lite's own default sort (used by area, which
      wires no explicit order-channel override) — see
      ``sorted_series_by_stack_order``.

    For ``stack_mode == "normalize"``, midpoints are divided by the column
    total so they land on the 0..1 scale that VL renders for normalize stacks.
    For ``stack_mode == "center"`` (streamgraph), each column is offset by
    ``(max_column_total - this_column_total) / 2`` — Vega-Lite's own
    center-offset formula (verified against its compiled scenegraph output,
    not the d3-style per-column ``-total/2`` silhouette one might assume) —
    so midpoints land on the [0, max_column_total] domain the area mark
    actually renders on. Callers must pass the same ``max_column_total`` that
    ``_stacked_y_domain`` computes for this data when ``stack_mode ==
    "center"``.
    """
    domain = stacked_x_domain_order(data, x_field, sort_by, descending)
    last_x = domain[-1] if domain else None

    values_at_last: dict[str, float] = dict.fromkeys(series_names, 0.0)
    for row in data:
        if row.get(x_field) != last_x:
            continue
        s = row.get(series_field)
        y = row.get(y_field)
        if s is None or y is None:
            continue
        values_at_last[str(s)] = float(y)

    if not values_at_last:
        return []

    series_order = sorted_series_by_stack_order(
        list(values_at_last), data, series_field, stack_order, y_field=y_field
    )

    total = sum(values_at_last[s] for s in series_order)
    result: list[tuple[str, float]] = []
    cum_lower = 0.0
    for s in series_order:
        v = values_at_last[s]
        mid = cum_lower + v / 2.0
        if stack_mode == "normalize" and total > 0:
            mid = mid / total
        elif stack_mode == "center":
            mid += (max_column_total - total) / 2.0
        result.append((s, mid))
        cum_lower += v
    return result


def _wide_endpoint_positions(
    data: list[VLDict],
    x_field: str,
    measures: list[str],
) -> dict[str, float]:
    """Return the most recent non-null endpoint for every wide measure."""
    endpoints: dict[str, tuple[VLDict, float]] = {}
    for row in data:
        x = row.get(x_field)
        if x is None:
            continue
        for measure in measures:
            value = row.get(measure)
            label = measure
            if value is not None and (
                label not in endpoints or x > endpoints[label][0]
            ):
                endpoints[label] = (x, float(value))
    return {label: value for label, (_, value) in endpoints.items()}


def _layer_color_scale(spec: ChartSpec, chart_id: str) -> dict[str, str]:
    """Return {label: fill} from the shared VL colour scale the overlay built.

    emitters/_overlay.py builds one shared colour scale's ``{domain, range}``
    that paints every layer's marks AND its legend swatch off the same pair
    (``render_cartesian_overlay``'s ``shared_scale``), stamped onto every
    participating layer's own ``encoding.color.scale`` — the same object, so
    reading it back off any one of them is authoritative and can't drift from
    what actually painted the marks. Searches every sub-layer rather than
    assuming ``spec.layers[0]`` is the base: an earlier feature (e.g.
    ``BaselineFeature``) may have inserted a rule layer ahead of it.
    """
    for layer_spec in spec.layers:
        color_enc = layer_spec.encoding.get("color")
        if not isinstance(color_enc, dict):
            continue
        scale = color_enc.get("scale")
        if not isinstance(scale, dict):
            continue
        domain, fill_range = scale.get("domain"), scale.get("range")
        if isinstance(domain, list) and isinstance(fill_range, list):
            return dict(zip(domain, fill_range, strict=True))
    raise ChartDataError(
        "layered chart has no shared colour scale for its endpoint-label rail",
        chart_id=chart_id,
    )


def _companion_for_fill(
    fill: str, palette: list[str], dark_companion_palette: tuple[str, ...]
) -> str:
    """This fill's dark-companion text ink, without reaching back into compile.palette.

    ``chart.palette`` and ``chart.style.series_label.dark_companion_palette``
    are parallel sequences baked at resolve time — index *i* of one is the
    dark companion of index *i* of the other (``_resolved_series_label``).
    Render is barred from compile.palette's catalog scan, so this looks the
    fill up positionally in that already-baked pair instead of assuming
    ``color_range`` is ``palette[:n]`` in slot order — true on the
    non-layered paths, not on this one (a layer's own mark colour, or the
    base's ``single_series_fill``, may not be a palette member at all). A
    fill with no match has no companion to find — falls back to the bright
    fill itself, the same graceful degrade ``resolve_dark_companion_stops``
    uses for a custom colour outside any registered palette.
    """
    try:
        idx = palette.index(fill)
    except ValueError:
        return fill
    return dark_companion_palette[idx] if idx < len(dark_companion_palette) else fill


def _layered_y_domain(
    spec: ChartSpec,
    entries: list[tuple[str, ChartRenderData, str, str]],
    axis_y: ResolvedAxisStyle,
) -> tuple[float, float]:
    """Return the shared y domain across the base rows and every layer's own rows.

    The layered rail renders on one shared VL scale (translate.py pins
    ``resolve.scale.y = "shared"``), which unions the base column with every
    overlay's y column — each entry may carry its own rows (a layer's own
    ``query:``) and its own y field name.

    Below the authored short-circuit, prefers the domain the emitter already
    baked onto a sub-layer's own ``encoding.y.scale`` — mirrors
    ``_layer_color_scale``'s read-back pattern: a bar base zero-anchors and
    stamps ``domainMin``/``domainMax`` (headroom-applied) at emit time
    (``emitters/bar.py``), and that is the domain VL actually renders;
    re-deriving raw min/max from rows would silently drift from it (a data
    floor sitting well above zero produces a materially narrower span than
    the zero-anchored one VL draws). Searches every sub-layer, not just
    ``spec.layers[0]``, for the same reason ``_layer_color_scale`` does.
    Falls back to raw row bounds only when no layer's y scale carries baked
    bounds (e.g. an un-zero-anchored line/area, which VL auto-fits).
    """
    if axis_y.scale is not None and axis_y.scale.continuous is not None:
        domain = axis_y.scale.continuous.domain
        if domain is not None:
            try:
                lo, hi = float(domain[0]), float(domain[1])
                if hi >= lo:
                    return lo, hi
            except (TypeError, ValueError):
                pass
    for layer_spec in spec.layers:
        y_enc = layer_spec.encoding.get("y")
        if not isinstance(y_enc, dict):
            continue
        scale = y_enc.get("scale")
        if not isinstance(scale, dict):
            continue
        baked_domain = scale.get("domain")
        if isinstance(baked_domain, list) and len(baked_domain) == 2:
            try:
                return float(baked_domain[0]), float(baked_domain[1])
            except (TypeError, ValueError):
                pass
        domain_min, domain_max = scale.get("domainMin"), scale.get("domainMax")
        if domain_min is not None and domain_max is not None:
            try:
                return float(domain_min), float(domain_max)
            except (TypeError, ValueError):
                pass
    values = [
        float(row[y_f])
        for _, rows, _, y_f in entries
        for row in rows
        if row.get(y_f) is not None
    ]
    return (min(values), max(values)) if values else (0.0, 1.0)


def _cumulative_midpoints(
    data: list[dict[str, Any]],
    x_field: str,
    y_field: str,
    series_field: str,
    series_names: list[str],
    sort_by: str,
    descending: bool,
    stack_mode: str = "zero",
) -> list[tuple[str, float]]:
    """Return (series, x_midpoint) for the top categorical row (un-nudged).

    The "top row" is the first value of the rendered x domain — alphabetically
    first, or first under an authored ``sort:``.  Midpoint is the
    cumulative x at the series segment's center, ordered largest-global-sum
    first — matching Vega-Lite's own default stack ordering, which it
    enforces via encoding.order + joinaggregate.  Sufficient for correct
    structure; full dodge resolution is deferred.

    A series absent from the top row is zero-width there and anchors on the
    seam between its neighbours — see ``_stacked_midpoints``.

    For ``stack_mode == "normalize"``, midpoints are divided by the top-row total
    so they land on the 0..1 scale that VL renders for normalize stacks.
    """
    x_values = stacked_x_domain_order(data, x_field, sort_by, descending)
    if not x_values:
        return []
    top_row_x = x_values[0]

    # Gather y-values per series for the top row and global sums across all rows.
    series_y: dict[str, float] = dict.fromkeys(series_names, 0.0)
    global_sums: dict[str, float] = dict.fromkeys(series_names, 0.0)
    for row in data:
        s = row.get(series_field)
        y = row.get(y_field)
        if s is None or y is None:
            continue
        key = str(s)
        global_sums[key] += float(y)
        if row.get(x_field) == top_row_x:
            series_y[key] = float(y)

    if not series_y:
        return []

    # Order: largest global sum first (baseline), ties broken alphabetically —
    # mirrors the segment stacking order so labels anchor to the right segments.
    series_order = sorted(series_y, key=lambda s: (-global_sums[s], s))

    total = sum(series_y[s] for s in series_order)
    result: list[tuple[str, float]] = []
    cumulative = 0.0
    for s in series_order:
        y = series_y[s]
        mid = cumulative + y / 2.0
        if stack_mode == "normalize" and total > 0:
            mid = mid / total
        result.append((s, mid))
        cumulative += y
    return result


def _has_negative_measure(data: list[dict[str, Any]], measure_field: str) -> bool:
    """True if any row carries a negative value in the stacked measure field.

    Negative segments push a stacked column across both signs, so the
    cumulative-midpoint anchors would float off the rendered segments.
    """
    return any(
        float(row[measure_field]) < 0
        for row in data
        if row.get(measure_field) is not None
    )


def _measure_label_pane_width(
    series_names: list[str], font_family: str, font_size: float, chart_width: float
) -> tuple[float, list[str]]:
    """Return the label pane width and the names the cap will cut.

    Natural width is the widest series name plus the edge gap.  A name wider
    than ``max_width_fraction`` of the chart's own width would make the rail
    wider than the canvas it hangs off — the concat overshoot correction then
    has no width left to give and refuses the render — so the pane is capped
    and Vega ellipsizes at the pane's mark limit, which is the cap itself.

    The cut names come back rather than being recorded here: only the caller
    knows whether the rail it is building actually honours this width (the
    vconcat top rail does not), so the caller owns the warning.
    """
    if not series_names:
        return _LABEL_GAP_PX, []
    measurer = get_font_measurer(font_family)
    widths = {name: measurer.measure(name, font_size) for name in series_names}
    cap = chart_width * get_chart_rendering().endpoint_labels.max_width_fraction
    # Vega cuts at the mark limit, which is the cap — not the cap less the gap.
    return min(max(widths.values()) + _LABEL_GAP_PX, cap), [
        name for name, w in widths.items() if w > cap
    ]


@dataclass
class EndpointLabelFeature:
    """Sets ``endpoint_label_layout`` and pre-computes label positions.

    - line/area/vertical bar with series color → ``"right_pane"`` (hconcat).
    - horizontal stacked bar with series color → ``"top_rail"`` (vconcat).

    Positions are un-nudged; full greedy-nudge pass and dark companion stops
    are deferred.
    """

    def applies_to(self, chart: ResolvedChart) -> bool:
        # ResolvedLineChart/AreaChart/BarChart all extend _BaseResolvedChartFields,
        # so resolved_channels is always accessible after this guard.
        if not isinstance(
            chart, (ResolvedLineChart, ResolvedAreaChart, ResolvedBarChart)
        ):
            return False
        # Every family gates on the author opting in via endpoint_labels.visible.
        # Without it the series names stay in the side legend.
        if not chart.style.endpoint_labels.visible:
            return False
        color_channel = chart.resolved_channels.get("color")
        has_series_color = color_channel is not None and color_channel.mode == "series"
        if isinstance(chart, ResolvedBarChart) and chart.orientation == "horizontal":
            # Top-row series rail only applies to stacked horizontals with a
            # colour-encoded series; layered horizontals have no rail path.
            return has_series_color and chart.stack not in (None, "none")
        if has_series_color:
            return True
        if color_channel is not None:
            # A gradient/literal/conditional colour channel puts a non-series
            # `color` encoding on the base spec, so emitters/_overlay.py's
            # use_shared_scale (which requires no colour encoding at all, or
            # a nominal/ordinal one) never builds the shared colour scale the
            # layered rail reads — _layer_color_scale would find nothing and
            # raise. Must agree with compile's _endpoint_label_rail_fires,
            # which gates its own has_layers term on the same condition.
            return False
        # No base colour channel at all: a layered single-series chart still
        # has one endpoint per layer (base + overlays) worth naming — see
        # _apply_layered_single_series. layered_endpoint_rail_fires is the
        # single answer to whether that rail can fire (shape + every layer
        # colourless) shared with compile's _bake_ay_orient and
        # _suppress_legend_for_endpoint_labels, which gate the same shape via
        # the same leaf.
        return layered_endpoint_rail_fires(
            layered_endpoint_rail_shape(chart.x, chart.y),
            [layer.color is None for layer in chart.layers],
        )

    def apply(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        box: RenderBox,
        datasets: dict[str | None, list[dict[str, Any]]],
    ) -> ChartSpec:
        assert isinstance(chart, _BaseResolvedChartFields)
        # Endpoint labels and multiples are mutually exclusive
        # (ERR_MULTIPLES_ENDPOINT_LABELS), but this feature is registered
        # BEFORE MirrorAxisFeature/FacetFeature (features/__init__.py) — the
        # only two raisers of that error — so a faceted chart can still
        # reach this line. .all_rows() pools every panel's rows together in
        # that case, which is fine: a later feature aborts the whole render
        # before the composed spec (built here) is ever used.
        data = chart_rows(chart, datasets).all_rows()

        color_ch = chart.resolved_channels.get("color")
        has_series_color = color_ch is not None and color_ch.mode == "series"
        if not has_series_color:
            # applies_to() only reaches here when chart.layers is non-empty.
            assert isinstance(
                chart, (ResolvedLineChart, ResolvedAreaChart, ResolvedBarChart)
            )
            return self._apply_layered_single_series(spec, chart, box, data, datasets)

        assert color_ch is not None
        if not color_ch.data_field:
            raise ValueError("series color channel must have a data_field")
        series_field = color_ch.data_field

        # For wide charts (y: [a, b, ...]), pre-fold wide rows into long form so
        # the ordinary domain/position helpers operate on (x, WIDE_LABEL_FIELD,
        # WIDE_VALUE_FIELD) triples, same as any authored-color series chart.
        # Color domain comes from wide_measures (not observed data): a measure
        # absent from every row would be missing from the observed set, desync-ing
        # the palette slot assignment from the chart's own scale domain.
        if (
            isinstance(chart, (ResolvedBarChart, ResolvedAreaChart, ResolvedLineChart))
            and chart.wide_measures
        ):
            data = [
                {**row, WIDE_LABEL_FIELD: measure, WIDE_VALUE_FIELD: row[measure]}
                for row in data
                for measure in chart.wide_measures
                if row.get(measure) is not None
            ]
            all_series = sorted(chart.wide_measures)
        else:
            # Build color domain from observed data.
            all_series = sorted(
                {
                    str(row[series_field])
                    for row in data
                    if row.get(series_field) is not None
                }
            )
        palette = list(chart.palette)
        color_domain = all_series
        color_range = (
            [palette[i % len(palette)] for i in range(len(all_series))]
            if palette
            else []
        )
        # Series-label typography + dark-companion ink, baked at compile time
        # (the v2 render layer cannot reach compile.palette). applies_to() has
        # already restricted this to the three cartesian families.
        assert isinstance(
            chart, (ResolvedLineChart, ResolvedAreaChart, ResolvedBarChart)
        )
        sl = chart.style.series_label
        dark_companion_range = list(sl.dark_companion_palette[: len(all_series)])
        label_pane_width, truncated_labels = _measure_label_pane_width(
            all_series, sl.font_family, sl.font_size, box.width
        )
        label_mark_font_props: dict[str, Any] = {
            "fontSize": sl.font_size,
            "font": sl.font_family,
            "fontWeight": sl.font_weight,
        }

        if isinstance(chart, ResolvedBarChart) and chart.orientation == "horizontal":
            x_field = chart.x
            if not isinstance(x_field, str):
                return spec
            y_field = chart.y
            if not isinstance(y_field, str):
                return spec
            _refuse_unorderable_sort(chart.id, data, chart.sort)
            if chart.stack == "center":
                raise ChartDataError(
                    "stack: 'center' is not supported for horizontal stacked bar "
                    "endpoint labels — the rail anchors on the cumulative (0..Σ) "
                    "axis, not the diverging (-Σ/2..+Σ/2) center-stack domain.",
                    chart.id,
                )
            if _has_negative_measure(data, y_field):
                raise ChartDataError(
                    "negative values are not supported for horizontal stacked bar "
                    "endpoint labels — they break the cumulative-midpoint computation.",
                    chart.id,
                )
            positions = _cumulative_midpoints(
                data,
                x_field,
                y_field,
                series_field,
                all_series,
                chart.sort.by if chart.sort else "",
                bool(chart.sort and chart.sort.order == "desc"),
                stack_mode=chart.stack or "zero",
            )
            # For normalize stacks the chart pane's x encoding must explicitly
            # pin [0, 1] so the shared vconcat x-scale propagates to the rail
            # pane correctly.  Without this, VL only auto-derives the domain
            # from stack=normalize on the main chart pane, and the rail row
            # (which has no mark) inherits an unconstrained scale.
            if chart.stack == "normalize":
                x_enc = spec.encoding.get("x")
                if isinstance(x_enc, dict):
                    x_scale = x_enc.setdefault("scale", {})
                    x_scale["domain"] = [0, 1]
            spec.endpoint_label_layout = "top_rail"
            spec.endpoint_label_data = EndpointLabelData(
                series_field=series_field,
                value_alias=_X_ALIAS,
                positions=positions,
                color_domain=color_domain,
                color_range=color_range,
                dark_companion_range=dark_companion_range,
                label_pane_width=label_pane_width,
                label_mark_font_props=label_mark_font_props,
                label_offset=chart.style.endpoint_labels.label_offset,
                height=chart.style.endpoint_labels.height,
            )
        else:
            x_field = chart.x
            if not isinstance(x_field, str):
                return spec
            y_field = chart.y
            if not isinstance(y_field, str):
                return spec

            label_gap_px = chart.style.series_label.gap_px

            # Stacked bars and areas: cumulative segment midpoints so labels
            # anchor over their rendered bands rather than at raw values.
            # Line has no stack concept (ResolvedLineChart declares no `stack`
            # field) so it never enters this branch.
            is_stacked = isinstance(
                chart, (ResolvedBarChart, ResolvedAreaChart)
            ) and chart.stack not in (None, "none")
            if is_stacked:
                assert isinstance(chart, (ResolvedBarChart, ResolvedAreaChart))
                _refuse_unorderable_sort(
                    chart.id,
                    data,
                    chart.sort if isinstance(chart, ResolvedBarChart) else None,
                )
                if _has_negative_measure(data, y_field):
                    raise ChartDataError(
                        "negative values are not supported for stacked bar/area "
                        "endpoint labels — they break the cumulative-midpoint "
                        "computation. "
                        "To fix: set endpoint_labels.visible: false on this chart.",
                        chart.id,
                    )
                stack_mode = chart.stack or "zero"
                # Bar exposes an authored stack_order override; area wires no
                # explicit order-channel, so its rendered stack always follows
                # Vega-Lite's own default sort (NATIVE_STACK_ORDER).
                stack_order = (
                    chart.style.stack_order
                    if isinstance(chart, ResolvedBarChart)
                    else NATIVE_STACK_ORDER
                )
                # Area has no authored sort; only bar carries one.
                _sort = chart.sort if isinstance(chart, ResolvedBarChart) else None
                y_domain_min, y_domain_max = _stacked_y_domain(
                    data, x_field, y_field, stack_mode
                )
                # Raw, un-cascaded midpoints — the greedy nudge is deferred
                # until the real plot geometry is known (see
                # EndpointLabelData's class docstring and
                # recascade_endpoint_labels).
                positions = _stacked_midpoints(
                    data,
                    x_field,
                    y_field,
                    series_field,
                    all_series,
                    stack_mode,
                    y_domain_max,
                    _sort.by if _sort else "",
                    bool(_sort and _sort.order == "desc"),
                    stack_order=stack_order,
                )
                # Pin the main pane's y domain so VL's shared hconcat y-scale
                # matches the label positions' basis: [0, 1] for normalize,
                # [0, max_total] for center (streamgraph, same as zero) —
                # otherwise the shared scale falls back to VL's raw-value
                # auto-domain, which doesn't match either.
                if chart.stack in ("normalize", "center"):
                    y_enc = spec.encoding.get("y")
                    if isinstance(y_enc, dict):
                        y_scale = y_enc.setdefault("scale", {})
                        y_scale["domain"] = (
                            [0.0, 1.0]
                            if chart.stack == "normalize"
                            else [y_domain_min, y_domain_max]
                        )
            else:
                y_domain_min, y_domain_max = _y_domain(
                    data,
                    y_field,
                    chart.style.axis_y,
                )
                # Raw, un-cascaded last-per-series values — see the is_stacked
                # branch above and EndpointLabelData's class docstring.
                positions = list(
                    last_nonnull_value_per_series(
                        data, x_field, y_field, series_field
                    ).items()
                )

            spec.endpoint_label_layout = "right_pane"
            # Only this layout honours label_pane_width, so only here does the
            # cap actually cut anything (the top_rail branch above ignores it).
            # Wide charts have series names from y: [...], not from color:.
            authored_field: SeriesLabelSource = "y" if chart.wide_measures else "color"
            record_series_label_truncations(chart.id, authored_field, truncated_labels)
            spec.endpoint_label_data = EndpointLabelData(
                series_field=series_field,
                value_alias=_Y_ALIAS,
                positions=positions,
                color_domain=color_domain,
                color_range=color_range,
                dark_companion_range=dark_companion_range,
                label_pane_width=label_pane_width,
                label_mark_font_props=label_mark_font_props,
                label_offset=chart.style.endpoint_labels.label_offset,
                height=chart.style.endpoint_labels.height,
                label_gap_px=label_gap_px,
                y_domain_min=y_domain_min,
                y_domain_max=y_domain_max,
            )

        return spec

    def _apply_layered_single_series(
        self,
        spec: ChartSpec,
        chart: ResolvedLineChart | ResolvedAreaChart | ResolvedBarChart,
        box: RenderBox,
        data: ChartRenderData,
        datasets: dict[str | None, ChartRenderData],
    ) -> ChartSpec:
        """Label the base series and every overlay layer's own endpoint.

        Reachable only when applies_to() has confirmed chart.layers is
        non-empty, there is no base colour-series channel to drive the
        multi-series rail above, and x/y are both plain scalar columns (see
        ``layered_endpoint_rail_fires``) — each layer stands in for a
        "series" here, named the same way emitters/_overlay.py names it for
        the legend (authored ``label:``, else the humanized column name) and
        coloured the same way it paints: read straight off the shared colour
        scale the overlay already built (``_layer_color_scale``), not
        re-derived.

        A layer pinning its own ``axis_y.position`` is refused at resolve
        time (``_reject_dual_axis_layered_endpoint_labels`` in
        compile/resolve/chart/_axes.py, called from every gated call site) — the
        rail anchors on one shared y-scale, a dual-axis layer renders on a
        different one, and the trigger is purely authored, known before
        render ever sees this chart.
        """
        x_field = chart.x
        y_field = chart.y
        assert isinstance(x_field, str) and isinstance(y_field, str)

        ay_font = chart.style.axis_y.title.font
        base_label = chart.y_label or format_display_text(
            y_field, from_slug=True, font=ay_font
        )
        entries: list[tuple[str, ChartRenderData, str, str]] = [
            (base_label, data, x_field, y_field)
        ]
        for layer in chart.layers:
            layer_y = layer.y
            # layer.color is always None here — layered_endpoint_rail_fires
            # (applies_to()'s gate) already refused entry otherwise.
            if layer_y is None:
                continue
            layer_x = layer.x if layer.x is not None else x_field
            own_data = (
                datasets.get(layer.query_name) if layer.query_name is not None else None
            )
            rows = own_data if own_data is not None else data
            label = layer.label or format_display_text(
                layer_y, from_slug=True, font=ay_font
            )
            entries.append((label, rows, layer_x, layer_y))

        anchors: dict[str, float] = {}
        for label, rows, x_f, y_f in entries:
            value = _wide_endpoint_positions(rows, x_f, [y_f]).get(y_f)
            if value is not None:
                anchors[label] = value
        if not anchors:
            return spec

        fill_by_label = _layer_color_scale(spec, chart.id)
        y_domain_min, y_domain_max = _layered_y_domain(
            spec, entries, chart.style.axis_y
        )
        # Raw, un-cascaded anchors — see EndpointLabelData's class docstring
        # and recascade_endpoint_labels.
        positions = list(anchors.items())

        color_domain = list(anchors)
        color_range = [fill_by_label[label] for label in color_domain]
        sl = chart.style.series_label
        palette = list(chart.palette)
        dark_companion_range = [
            _companion_for_fill(fill, palette, sl.dark_companion_palette)
            for fill in color_range
        ]
        label_pane_width, truncated_labels = _measure_label_pane_width(
            color_domain, sl.font_family, sl.font_size, box.width
        )
        record_series_label_truncations(chart.id, "y", truncated_labels)
        spec.endpoint_label_layout = "right_pane"
        spec.endpoint_label_data = EndpointLabelData(
            series_field=_LABEL_ALIAS,
            value_alias=_Y_ALIAS,
            positions=positions,
            color_domain=color_domain,
            color_range=color_range,
            dark_companion_range=dark_companion_range,
            label_pane_width=label_pane_width,
            label_mark_font_props={
                "fontSize": sl.font_size,
                "font": sl.font_family,
                "fontWeight": sl.font_weight,
            },
            label_offset=chart.style.endpoint_labels.label_offset,
            height=chart.style.endpoint_labels.height,
            label_gap_px=sl.gap_px,
            y_domain_min=y_domain_min,
            y_domain_max=y_domain_max,
        )
        return spec
