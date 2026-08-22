"""Shared cartesian encoding primitives for render-v2 emitters.

These helpers extract verbatim-identical logic from the line and area emitters.
Each primitive is genuinely shared (2+ call sites), accepts explicit args, and
never takes board_style — preserving the no-board_style emitter invariant.

Convention: every primitive here is a pure builder — it returns a value and
never mutates an argument in place.
"""

from __future__ import annotations

import json
from typing import Any, Literal, NamedTuple

from dbt_charts.core.compile.models.chart.authored._annotations import ChartSort
from dbt_charts.core.compile.models.primitives import ResolvedFontStyle
from dbt_charts.core.compile.models.style.resolved._base import (
    ResolvedAxisStyle,
    ResolvedScaleStyle,
)
from dbt_charts.core.compile.resolve.chart.tick_values import numeric_domain_bounds
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_render import (
    ERR_SCALE_DOMAIN_REQUIRES_CONTINUOUS_X,
)
from dbt_charts.core.font_measure import get_font_measurer
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.artifacts import ChartRenderData
from dbt_charts.core.render.chart.emitters._label_overlap import resolve_axis_x_overlap
from dbt_charts.core.render.chart.spec import RenderBox
from dbt_charts.core.render.chart.text_truncation import record_text_truncation
from dbt_charts.core.render.chart.time_unit_detect import (
    BUCKETED_CALENDAR_UNITS,
    canonicalize_and_sort_ordinal_x,
    detect_time_unit,
    normalize_labeled_temporal,
    vl_time_unit,
)
from dbt_charts.core.render.chart.type_inference import (
    build_cartesian_x_encoding,
    infer_vega_type_from_data,
    is_zero_anchored,
    resolve_cartesian_x_type,
    temporal_edge_labels_flushed,
    y_zero_scale,
)
from dbt_charts.core.render.chart.vl_field_maps import (
    axis_to_vl,
    bake_tick_ladder,
    emit_resolved_scale_vl,
)
from dbt_charts.core.text.case import format_display_text
from mdsvg.fonts import wrap_text_precise

# Dataface ChartSort.order ("asc"/"desc") → Vega-Lite sort.order. VL silently
# falls back to ascending on the raw Dataface form, so translate at emit (mirrors
# V1 profile._SORT_ORDER_VL).
_SORT_ORDER_VL = {"asc": "ascending", "desc": "descending"}

# VL scale types on which an explicit [low, high] domain is a valid continuous
# range override. Every other cartesian-x type (ordinal/nominal band scales)
# reads a 2-element domain as exactly two category values instead.
_CONTINUOUS_VL_TYPES = frozenset({"temporal", "quantitative"})

# The complement: cartesian-x types that resolve to a discrete band scale.
_BAND_X_TYPES = frozenset({"ordinal", "nominal"})


# Smallest outer padding that lifts a band scale's first tick off the exact
# range start. Expressed as a fraction of the step, so at any realistic plot
# width it moves a band edge by well under a thousandth of a pixel (measured:
# 0.0001px at 480px across 7/13/31 bands) — below the SVG coordinate precision
# we emit, and orders of magnitude below anything visible.
_FIRST_BAND_TICK_EPSILON = 1e-6


def nudge_band_scale_off_range_start(
    x_scale: VLDict, vl_type: str, ax_vl: VLDict, band_doubled: bool
) -> None:
    """Keep Vega from culling a band scale's FIRST axis label.

    Vega drops the label on the first band at isolated plot widths whenever
    the axis carries an explicit ``values`` list and the scale's range starts
    at exactly zero — present at one width, gone half a pixel later, present
    again half a pixel after that. Verified against vl_convert 1.9.0 across
    band counts and thousands of half-pixel widths: it is always the first
    band and never any other, it fires for any ``values`` list containing that
    band (a full-domain list and a thinned cadence list alike), and it is
    unaffected by ``labelOverlap``, ``labelBound``, ``labelFlush``,
    ``labelLimit``, ``labelSeparation``, or the label's own text. Omitting
    ``values`` avoids it, but ``values`` carries the label cadence ladder and
    cannot be dropped. It is a rounding fault at the range start, so an
    epsilon of outer padding is enough to clear it.

    ``band_doubled`` suppresses the nudge for the band-aware ``step`` curve
    (``step_band.py``), whose geometry depends on band *k*'s right edge and
    band *k+1*'s left edge being the same float: it doubles each row onto both
    edges and lets ``step-after`` put the riser on the shared boundary. Outer
    padding separates those two coordinates, so the pairing breaks and risers
    land on the wrong edge — measured as 41.56px plateau shifts on
    ``quick-guide_5``. The epsilon is tiny in displacement but an exact
    equality is load-bearing there, so "too small to see" is not the relevant
    question. A band-step chart therefore keeps the cull; its plateau geometry
    is the larger visual contract.

    Deliberately NOT ``align``: pinning ``align: 0`` also clears the cull, and
    is inert only when the scale has no slack to distribute. Band scales here
    do sometimes carry slack, and against it ``align: 0`` shoves every band to
    one side — it moved a chart's whole plot area 47px (0.75 of a band). This
    nudge's effect is bounded by ``_FIRST_BAND_TICK_EPSILON`` regardless of
    how much slack exists.

    Only fires where dbt charts asked for flush-to-edge bands
    (``padding: 0``); an authored outer padding is already off the range start
    and is left exactly as authored. Scatter is out of scope either way — it
    rebuilds its own scale from ``x_res`` rather than carrying this one, so
    the mutation never reaches its spec.
    """
    if band_doubled or vl_type not in _BAND_X_TYPES or "values" not in ax_vl:
        return
    if x_scale.get("padding") != 0:
        return
    x_scale["paddingOuter"] = _FIRST_BAND_TICK_EPSILON


def cartesian_x_scale_domain(
    scale: ResolvedScaleStyle | None, vl_type: str, chart_id: str
) -> VLDict:
    """Return the VL x-scale ``domain`` entry for an authored cartesian x scale.

    Empty dict when no domain is authored. Raises ``ERR-SCALE-DOMAIN-
    REQUIRES-CONTINUOUS-X`` when a domain is authored but the x-axis resolved
    to an ordinal/nominal (band) type: Vega-Lite reads a 2-element domain on
    a band scale as exactly two categories, collapsing every mark onto the
    first one, rather than extending a continuous range.
    """
    _sc_cont = scale.continuous if scale is not None else None
    if _sc_cont is None or _sc_cont.domain is None:
        return {}
    if vl_type not in _CONTINUOUS_VL_TYPES:
        raise ChartDataError.from_code(
            ERR_SCALE_DOMAIN_REQUIRES_CONTINUOUS_X,
            chart_id=chart_id,
            vl_type=vl_type,
        )
    return {"domain": list(_sc_cont.domain)}


def chart_sort_to_vl(sort: ChartSort | None) -> VLDict | None:
    """Map an authored ``ChartSort`` to a field-based VL sort dict.

    Returns ``None`` when no sort is authored — callers spread that straight
    into an encoding's ``sort`` (VL treats ``None`` as "no explicit order").
    """
    if sort is None:
        return None
    return {"field": sort.by, "order": _SORT_ORDER_VL[sort.order]}


def build_palette_config(palette: tuple[str, ...] | None) -> VLDict:
    """Build config.range.category from a resolved palette.

    Returns an empty dict when palette is absent — the emitter can safely
    spread this into the ChartSpec config without special-casing.
    """
    if palette:
        return {"range": {"category": list(palette)}}
    return {}


def canonicalize_cartesian_x_data(
    data: ChartRenderData,
    x_field: str,
    authored_time_unit: str | None,
    *,
    skip_bucket_collapse: bool = False,
) -> tuple[ChartRenderData, bool]:
    """Normalize labeled-temporal x values and canonicalize date-like ones.

    ``build_cartesian_x_encoding`` emits ``axis.values``/``labelExpr``/
    ``timeUnit`` against the raw domain value, so the caller owns making that
    value JS-``Date``-parseable first — bar/line/area establish this via
    ``normalize_labeled_temporal`` (rewrites a labeled bucket string like
    "Q1 2024" to its ISO date) plus, for line/area, ``canonicalize_and_sort_
    ordinal_x`` (collapses a ``datetime.datetime``/non-date-only ISO value to
    date-only ISO — see ``_ordinal_bucket_key``'s docstring for the exact
    hazard: an ISO datetime string left as-is never matches its band-scale
    peers). Heatmap and scatter have no gap-fill scaffold of their own, so
    this is the minimal precondition pair for them.

    ``authored_time_unit`` is the axis's own authored ``time_unit`` FOR
    ``x_field`` — pass ``None`` when ``x_field`` isn't the axis's own field
    (e.g. an overlay layer's independently-authored ``x`` column), so the
    bucket grain is auto-detected from that field's own rows instead of a
    grain authored for a different column collapsing it wholesale.

    ``skip_bucket_collapse`` mirrors ``gap_fill_ordinal_time``'s own
    ``resolve_authored_x_type(ax) == "temporal"`` early return (see
    ``_channels.py``): an authored continuous-temporal x axis never bucket-
    collapses at all, so a value sharing that axis's scale must skip it too,
    or the two land on different JS-``Date``-parseable string forms (a raw
    naive ``datetime`` vs. a date-only ISO string).

    Gated on the same authored-or-detected bucketed calendar grain
    (``BUCKETED_CALENDAR_UNITS``) that ``resolve_cartesian_x_type`` resolves
    for ``build_cartesian_x_encoding`` — detecting alone (the pre-fix gate)
    disagreed with that authored-or-detected resolution: an authored
    ``axis_x.time_unit`` on a non-midnight ``datetime`` reached
    ``build_cartesian_x_encoding``'s ``axis.values`` (stringified via
    ``.isoformat()``) uncanonicalized here, while the row itself stringified
    via ``str()`` — the two never matched, so a nominal/ordinal band scale
    painted zero labels. A plain numeric or nominal x — heatmap's hour-of-day
    grid, a genuinely categorical scatter x — never resolves "temporal" and
    so never reaches this gate. A *sub-daily* temporal x (any nonzero
    hour/minute/second) with no authored bucketing resolves "temporal" but
    ``detect_time_unit`` returns ``None`` for it (its own explicit sub-daily
    fallthrough) — that value is a continuous timestamp, not a date, and
    truncating it to ``.date().isoformat()`` would silently collapse distinct
    rows onto the same day.

    Returns ``(data, transformed)``; when True the caller must stamp the
    returned rows onto ``ChartSpec.data`` (mirrors ``line.py``'s
    ``_normalize_line_data``) so the render session does not overwrite the
    spec with the original, uncanonicalized rows.
    """
    if not data or not x_field:
        return data, False
    normalized = normalize_labeled_temporal(data, x_field)
    transformed = normalized is not data
    data = normalized
    if (
        not skip_bucket_collapse
        and infer_vega_type_from_data(data, x_field) == "temporal"
    ):
        time_unit: str | None
        if authored_time_unit is not None:
            time_unit = authored_time_unit
        else:
            x_values = [row.get(x_field) for row in data if x_field in row]
            time_unit = detect_time_unit(x_values)
        if time_unit in BUCKETED_CALENDAR_UNITS:
            data = canonicalize_and_sort_ordinal_x(data, x_field)
            transformed = True
    return data, transformed


class CartesianXResolution(NamedTuple):
    """Resolved x encoding type, axis VL dict, x scale, and optional VL timeUnit."""

    vl_type: str
    axis: VLDict
    scale: VLDict
    time_unit: str | None = None  # utc-prefixed timeUnit for temporal escape-hatch


def resolve_cartesian_x(
    x_field: str,
    data: list[dict[str, Any]],
    ax: ResolvedAxisStyle,
    label_usable_ratio: float,
    chart_width: float,
    chart_id: str,
    mark_type: str,
    curve: str | None = None,
    band_doubled: bool = False,
) -> CartesianXResolution:
    """Resolve x encoding type, axis VL dict, and x scale for a cartesian x field.

    Mirrors the identical block in the line and area emitters: overlap
    resolution → axis_to_vl → build_cartesian_x_encoding, plus extracting
    scale.padding/domain from the authored axis style. Caller guards
    ``x_field is not None`` before calling. ``chart_id`` names the chart in
    the error raised by ``cartesian_x_scale_domain`` when an authored domain
    doesn't fit the resolved scale type. ``mark_type`` ("line"/"area") and
    ``curve`` (the authored line/area curve style) are forwarded to
    ``build_cartesian_x_encoding`` for the bucketed-grain type split.
    ``band_doubled`` reports whether any overlay LAYER band-doubles this same
    scale; the base's own ``curve`` cannot see that, and either side is enough
    to make adjacent band edges load-bearing.
    """
    from dbt_charts.core.render.chart.step_band import BAND_STEP_CURVE

    vl_type, _, _ = resolve_cartesian_x_type(
        data, x_field, ax, mark_type, curve == BAND_STEP_CURVE
    )
    label_layout = resolve_axis_x_overlap(
        ax,
        x_field,
        data,
        label_usable_ratio,
        bucket_aligned_temporal=curve == "step",
        edge_labels_flushed=temporal_edge_labels_flushed(vl_type, ax),
        chart_width=chart_width,
    )
    ax_vl_raw = axis_to_vl(
        ax,
        label_overlap=label_layout.label_overlap,
        label_angle=label_layout.angle,
    )
    x_scale: VLDict = {}
    if ax.scale is not None and ax.scale.padding is not None:
        x_scale["padding"] = ax.scale.padding
    vl_type, ax_vl, detected_tu = build_cartesian_x_encoding(
        data,
        x_field,
        ax,
        ax_vl_raw,
        mark_type,
        curve,
        format_time_unit=label_layout.format_time_unit,
        visibility_time_unit=label_layout.visibility_time_unit,
        label_anchor_index=label_layout.anchor_index,
    )
    x_scale.update(cartesian_x_scale_domain(ax.scale, vl_type, chart_id))
    nudge_band_scale_off_range_start(
        x_scale, vl_type, ax_vl, band_doubled or curve == BAND_STEP_CURVE
    )
    # Temporal path: emit utc-prefixed timeUnit when a bucketed unit was detected
    # (either authored or auto-detected). Skip "none" (continuous temporal) and
    # time-part units like monthofyear that vl_time_unit handles via _TIME_UNIT_TO_VL.
    enc_time_unit: str | None = None
    if vl_type == "temporal" and detected_tu is not None and detected_tu != "none":
        enc_time_unit = vl_time_unit(detected_tu)
    return CartesianXResolution(vl_type, ax_vl, x_scale, enc_time_unit)


# An axis title Vega-Lite will render: a plain string, or one entry per line
# when Dataface pre-wrapped it to fit the axis (VL renders a list as lines but
# never computes the breaks itself).
AxisTitle = str | list[str] | None


class XYTitles(NamedTuple):
    """Resolved x/y axis titles for a cartesian chart.

    ``x_title`` / ``y_title`` are what Vega-Lite renders: a ``list[str]`` when
    the title had to be wrapped to fit its axis (VL draws one line per entry).
    ``y_plain`` is the y title before wrapping — the value to use anywhere the
    title is *data* rather than layout, such as the base-series legend label a
    layered chart builds its color scale domain from. Wrapping is a display
    concern and must not leak into a datum. (There is no ``x_plain``: no data
    label is derived from the x title.)
    """

    x_title: AxisTitle
    y_title: AxisTitle
    y_plain: str | None


def axis_title_budget(extent: float) -> int:
    """Pixels an axis title may occupy along the axis it labels.

    ``extent`` is the chart's size in the title's own direction: height for a
    left/right axis (whose title renders rotated), width for top/bottom. The
    layout chrome outside the plot is subtracted so the title competes for the
    space it can actually have.
    """
    return max(int(extent - _LAYOUT_CHROME_PX), 1)


def wrap_axis_title(
    text: str, extent: float, font: ResolvedFontStyle
) -> tuple[str | list[str], bool]:
    """Wrap an axis title to at most two lines that fit ``extent``.

    Vega-Lite renders ``axis.title`` as a list of lines but never computes the
    breaks itself, and it caps nothing by default — an over-long title is drawn
    at full length and ``autosize: fit`` shrinks the plot to make room, to the
    point of collapsing it entirely. Wrapping here is what bounds it.

    Returns ``(title, truncated)`` where ``title`` is the wrapped value passed
    to Vega-Lite (a single string or a list of lines) and ``truncated`` is
    ``True`` when the ellipsis fired — i.e. authored text was cut. A single
    string is returned when the text already fits, so charts that render
    correctly today are unaffected. That string is whitespace-normalized by
    the wrapper (runs of spaces collapse), not byte-identical to the input.
    """
    budget = axis_title_budget(extent)
    lines, truncated = wrap_text_precise(
        text,
        budget,
        font.size,
        get_font_measurer(font.family),
        max_lines=2,
        ellipsis=True,
    )
    # wrap_text_precise strips and normalizes whitespace, so a blank label
    # (``x_label: " "`` — how an author blanks an axis title without deleting
    # the key) wraps to no lines at all. Hand that text straight back: a blank
    # title stays blank, as it rendered before any wrapping existed.
    if not lines:
        return text, False
    return (lines if len(lines) > 1 else lines[0]), truncated


def wide_measures_title(measures: tuple[str, ...], font: ResolvedFontStyle) -> str:
    """Y-axis title for a folded multi-measure (wide ``y: [...]``) chart.

    Joins each measure's own humanized name — the same ``format_display_text``
    derivation a single ``y:`` field's title already uses, generalized to the
    list case, since the measure names ARE real authored fields (unlike the
    synthetic fold-key/color field, which has no name to derive a legend
    title from). An authored ``y_label`` always overrides this — callers pass
    it through ``resolve_xy_titles``'s ``y_label`` param, not this function.
    """
    return ", ".join(
        format_display_text(m, from_slug=True, font=font) for m in measures
    )


def resolve_xy_titles(
    x_field: str | None,
    y_field: str | None,
    x_label: str | None,
    y_label: str | None,
    ax: ResolvedAxisStyle,
    ay: ResolvedAxisStyle,
    box: RenderBox,
    chart_id: str,
    x_authored_field: Literal["x_label", "y_label"] = "x_label",
    y_authored_field: Literal["x_label", "y_label"] = "y_label",
) -> XYTitles:
    """Resolve x/y axis titles: explicit authored label, else title-cased field slug.

    Titles are in Vega-Lite channel space, not authored space: a horizontal bar
    passes its authored ``y_label`` as ``x_label`` here, because that is the
    channel it renders on. Each title is then wrapped against the extent of the
    channel it lands on — width for x, height for the rotated y.

    ``x_authored_field`` and ``y_authored_field`` name which authored YAML field
    maps to each VL channel.  For vertical bars and lines, the defaults ("x_label"
    and "y_label") are correct.  Horizontal bars pass ``x_authored_field="y_label"``
    because the authored y_label renders on the VL x channel after the flip.

    When a title has to be truncated, the truncation is recorded into the active
    ``axis_title_truncation`` ContextVar sink using the authored field name so
    the ``WARN_AXIS_TITLE_TRUNCATED`` detector can emit a path that points at the
    right YAML line.  Pass ``chart_id=""`` to skip recording (e.g. in tests that
    only care about the wrapped value, not the warning).

    Handles None x/y gracefully. ``y_field`` must already be narrowed to
    ``str | None`` (callers that receive ``str | list[str]`` must narrow
    before calling). Tooltip *content* is a separate concern — built by
    ``features/structured_tooltip.py`` from the chart-axes LUT, not here.
    """
    x_text: str | None = x_label or (
        format_display_text(x_field, from_slug=True, font=ax.title.font)
        if x_field
        else None
    )
    y_text: str | None = y_label or (
        format_display_text(y_field, from_slug=True, font=ay.title.font)
        if y_field
        else None
    )
    x_title: AxisTitle
    y_title: AxisTitle
    if x_text:
        x_title, x_truncated = wrap_axis_title(x_text, box.width, ax.title.font)
        if x_truncated and chart_id:
            record_text_truncation(chart_id, "axis_title", x_text, x_authored_field)
    else:
        x_title = x_text
    if y_text:
        y_title, y_truncated = wrap_axis_title(y_text, box.height, ay.title.font)
        if y_truncated and chart_id:
            record_text_truncation(chart_id, "axis_title", y_text, y_authored_field)
    else:
        y_title = y_text
    return XYTitles(x_title, y_title, y_text)


def build_x_enc(
    x_field: str,
    vl_type: str,
    x_title: AxisTitle,
    ax_vl: VLDict,
    x_scale: VLDict,
    time_unit: str | None = None,
) -> VLDict:
    """Build the VL x encoding dict for a cartesian time/nominal x field.

    ``sort: None`` disables VL's default alphabetical ordering so the query's
    row order is preserved — matching the oracle. Scale is omitted when empty.
    ``time_unit`` is the utc-prefixed VL timeUnit for temporal escape-hatch
    (e.g. "utcyearmonth") — omitted when None.
    """
    enc: VLDict = {
        "field": x_field,
        "type": vl_type,
        "title": x_title,
        "axis": ax_vl,
        "sort": None,
    }
    if time_unit:
        enc["timeUnit"] = time_unit
    if x_scale:
        enc["scale"] = x_scale
    return enc


# Title block + view padding outside the plot along one axis. Used to size
# horizontal bars, and to budget how much of an axis its own title may occupy.
# Deliberately a little larger than the chrome actually measures (~66px), so
# the budget it leaves is under the real space rather than over it.
_LAYOUT_CHROME_PX = 72.0


def count_horizontal_bar_categories(
    category_field: str | None,
    data: list[dict[str, Any]],
) -> int:
    """Distinct category values on the authored ``x`` field (VL y after flip)."""
    if not category_field or not data:
        return 0
    return len(
        {
            str(row[category_field])
            for row in data
            if category_field in row and row[category_field] is not None
        }
    )


def min_height_for_horizontal_bar_categories(
    n_categories: int,
    axis_x: ResolvedAxisStyle,
    bar_size: float | None,
) -> float:
    """Minimum chart height so every categorical band can show a flat y label.

    axis_x and bar_size are the caller's already-resolved
    ``resolved_chart.style.axis_x`` / ``.mark.size`` — the fully
    chart-local-cascaded values (theme chart-type patch and any chart-local
    override both baked in at resolve time). Both stay ``| None``-typed here
    only because the underlying theme model shares its type with the
    resolved usage; the cascade guarantees them concrete by this point.
    """
    if n_categories <= 0:
        return 0.0
    label = axis_x.labels
    font_size = label.font.size
    min_gap = label.min_gap
    padding = label.padding
    assert font_size is not None, (
        "axis_x.labels.font.size unset — theme cascade must populate it"
    )
    assert min_gap is not None, (
        "axis_x.labels.min_gap unset — theme cascade must populate it"
    )
    assert padding is not None, (
        "axis_x.labels.padding unset — theme cascade must populate it"
    )
    assert bar_size is not None, "marks.bar.size unset — theme cascade must populate it"
    label_line = font_size + 2 * padding
    band_step = max(bar_size, label_line) + min_gap
    return _LAYOUT_CHROME_PX + n_categories * band_step


def apply_domain_headroom_bounds(
    scale: VLDict,
    domain_max: float | None,
    domain_min: float | None,
) -> VLDict:
    """Bake resolve()-time headroom bounds onto a VL scale dict.

    Both bounds are exact (never nice-rounded). ``domain_max`` is the
    headroom-applied top; ``domain_min`` is only set for zoomed (non-zero-anchored)
    axes (symmetric span-relative bottom). None on either means VL auto-fits
    that edge. Callers must have already confirmed no authored domain is set.
    """
    if domain_max is None and domain_min is None:
        return scale
    result = dict(scale)
    if domain_max is not None:
        result["domainMax"] = domain_max
    if domain_min is not None:
        result["domainMin"] = domain_min
    return result


def authored_measure_domain(ay: ResolvedAxisStyle) -> tuple[float, float] | None:
    """The authored numeric ``scale.continuous.domain`` on *ay*, or None.

    The single spelling of "did the author pin this axis's domain", so the
    consumers below — the VL scale emitter and the baseline gate — cannot
    disagree about what counts as authored.
    """
    cont = ay.scale.continuous if ay.scale is not None else None
    return numeric_domain_bounds(cont.domain if cont is not None else None)


def effective_measure_domain(
    ay: ResolvedAxisStyle, data_extent: tuple[float, float] | None
) -> tuple[float, float] | None:
    """The ``(lo, hi)`` this measure axis actually renders.

    Mirrors ``resolve_measure_y_scale``'s branches in the same order, so the
    gate that reads this and the emitter that builds the scale cannot disagree
    about where the axis starts and ends:

    1. **Authored domain** wins outright, and suppresses everything below it by
       design — resolve leaves the baked bounds None whenever one is set.
    2. **Baked ``domain_min`` / ``domain_max``** — the headroom-expanded edges,
       taken per-edge, because None means "auto-fit THIS edge" and the two are
       decided separately (a zero-anchored axis bakes only the top).
    3. **The zero-anchor floor**, for a low edge resolve left unbaked:
       ``ladder[0]`` else ``0.0``, byte for byte what ``y_zero_scale`` pins as
       ``domainMin`` on such an axis. The ladder is filtered through
       ``zero_anchor_domain_floor`` for the same reason the emitter filters it —
       an authored ``scale.values`` list may not source a domain bound.
    4. **The data extent**, which is what Vega-Lite auto-fits from.

    **Every value here is one the emitter actually pins, or the extent VL fits
    to — never a prediction of where VL's ``nice`` will land.** An earlier
    revision read the whole tick ladder as if it were the domain, and it does
    not hold: on a ``headroom: 0.05`` percent axis the engine pins
    ``domainMax 0.9785`` while the ladder's top rung is ``1.0``, so the rung
    sits outside the rendered domain and VL clips it. Reading it made this
    function non-monotonic in headroom — a *tighter* fit reported more range —
    and let a parity rule paint on a chart whose domain excluded it, where the
    rule's own datum then stretched the domain to cover the mark that should
    never have been drawn. A tick list is not a domain; keep this function
    reading only pinned facts.

    A consequence worth naming: a ``headroom: 0`` axis whose ladder rounds out
    past ``value`` still reports False here, because nothing pins that edge.
    Making that case work needs the domain pinned at resolve — which is what
    the one-ended/bounded-domain task's ``include`` field is for.

    ``data_extent`` is None when the measure column carries no numeric rows
    under the field the caller asked about — including a synthetic folded field
    that is absent from unfolded rows, where resolve may still have baked real
    bounds. Returns None when nothing pins the axis at all.
    """
    authored = authored_measure_domain(ay)
    if authored is not None:
        return min(authored), max(authored)

    if data_extent is None:
        return None
    data_lo, data_hi = data_extent
    hi = ay.domain_max if ay.domain_max is not None else data_hi
    if ay.domain_min is not None:
        lo = ay.domain_min
    elif is_zero_anchored(ay.scale):
        # Exactly what y_zero_scale pins as domainMin for this axis — a value
        # the emitter really writes, not a guess at where VL will land.
        # Today's sole caller cannot tell ladder[0] from 0.0: it asks about
        # 1.0, and a computed zero-anchored ladder always floors at or below 0.
        # Keep the rung anyway — with `zero: true` and negative data the
        # emitter really does pin a domainMin below 0, and collapsing this to a
        # literal would make the stated parity false on that shape.
        ladder = zero_anchor_domain_floor(
            ay, list(ay.tick_values) if ay.tick_values else []
        )
        lo = ladder[0] if ladder else 0.0
    else:
        lo = data_lo
    return lo, hi


def zero_anchor_domain_floor(
    ay: ResolvedAxisStyle, tick_values: list[float]
) -> list[float]:
    """*tick_values*, or ``[]`` when they may not pin a zero-anchored scale's
    domain floor.

    A computed zero-anchored ladder is a matched set whose bottom rung is
    always <= the data floor, so pinning ``domainMin`` from it can never
    exclude data. An authored ``scale.values`` list carries no such
    guarantee — it's a statement about tick positions, not the domain — so
    an authored list must never source a floor pin. The single place this
    provenance distinction is spelled, so a caller filters through it rather
    than re-deriving the condition inline: ``resolve_measure_y_scale`` below,
    and horizontal bar's own measure-axis scale in ``bar.py``.

    One ``domainMin``-from-ticks site is deliberately NOT converted:
    ``_emit_vertical``'s ``bar_zero`` branch in ``bar.py``, which pins
    ``y_ticks[0]`` unfiltered. Vertical bar has the same authored-ladder
    exposure, but it predates this function and fixing it moves goldens, so
    it is its own task rather than a rider here. The ``domainMax`` pins from
    ``ay.tick_values[-1]`` are the mirror image and equally unconverted.
    """
    if ay.scale is not None and ay.scale.values is not None:
        return []
    return tick_values


def resolve_measure_y_scale(ay: ResolvedAxisStyle) -> VLDict:
    """Build the VL y-scale dict for a resolved measure axis.

    Authored domain replaces the data-driven zero/domainMin computation, but
    still carries type/base/exponent/constant (etc.) via emit_resolved_scale_vl
    — a domain and a scale type are not mutually exclusive (e.g. log needs
    both). Every measure-channel emitter (vertical bar, horizontal bar,
    single- and multi-metric line, area, scatter) must route through this one
    branch: a zero-anchored "zero: true" flag left standing next to an
    authored domain lets VL's domainMin companion silently override the
    authored lower edge with the tick ladder's own rounded-down bottom rung.
    """
    authored_domain = authored_measure_domain(ay)
    if authored_domain is not None:
        y_scale: VLDict = {"domain": list(authored_domain)}
        if ay.scale is not None:
            y_scale.update(emit_resolved_scale_vl(ay.scale))
            # An authored domain already IS the exact bounds — "zero" is a
            # domain-inference hint (VL's "extend the domain to include 0"),
            # meaningless once the domain is pinned explicitly, and its
            # domainMin companion would leak a rounded-down tick bound below
            # the authored lower edge.
            y_scale.pop("zero", None)
        return y_scale
    y_ticks: list[float] = list(ay.tick_values) if ay.tick_values else []
    y_scale = y_zero_scale(ay, tick_values=zero_anchor_domain_floor(ay, y_ticks))
    return apply_domain_headroom_bounds(y_scale, ay.domain_max, ay.domain_min)


def build_cartesian_y_encoding(
    y_field: str | list[str] | None,
    ay: ResolvedAxisStyle,
    ay_vl: VLDict,
    y_title: AxisTitle,
    tooltip_format: str,
) -> VLDict:
    """Build the VL y encoding dict from a resolved axis style.

    Tick values from ay.tick_values are baked into ay_vl["values"] when present.

    Callers that need a VL ``stack`` key (area charts) mutate the returned dict.
    """
    bake_tick_ladder(ay_vl, ay.tick_values)
    return {
        "field": y_field,
        "type": "quantitative",
        "title": y_title,
        "axis": ay_vl,
        "scale": resolve_measure_y_scale(ay),
        "format": tooltip_format,
    }


# Sentinel for families with no authored stack_order override (e.g. area):
# reproduces Vega-Lite's OWN default stack sort — descending on the raw color
# field value — used when a chart's emitter wires no explicit `order` encoding
# to override it. Not a user-facing value; bar's authored stack_order Literal
# ("value" / "data" / "alphabetical") never carries this string.
NATIVE_STACK_ORDER = "native"


def sorted_series_by_stack_order(
    series: list[str],
    data: list[dict[str, Any]],
    series_field: str,
    stack_order: str | None,
    *,
    y_field: str = "",
) -> list[str]:
    """Return *series* sorted for stacked chart rendering by stack_order.

    Baseline = cumulative zero (the series placed first paints at the bottom).
    - None / "value": largest global sum at baseline (matches VL's joinaggregate default).
      Requires *y_field* to be set.
    - "alphabetical": alphabetically first series at baseline.
    - "data": globally first-encountered series at baseline (first-encounter in *data*).
    - ``NATIVE_STACK_ORDER``: Vega-Lite's own default (no order-channel override) —
      descending string sort of the raw field value, alphabetically-last at baseline.
    """
    if stack_order == NATIVE_STACK_ORDER:
        return sorted(series, reverse=True)
    if stack_order == "alphabetical":
        return sorted(series)
    if stack_order == "data":
        encounter: dict[str, int] = {}
        for row in data:
            s = row.get(series_field)
            if s is not None:
                key = str(s)
                if key not in encounter:
                    encounter[key] = len(encounter)
        return sorted(series, key=lambda s: (encounter.get(s, len(encounter)), s))
    # None / "value": sort by descending global sum.
    global_sums: dict[str, float] = {}
    for row in data:
        s = row.get(series_field)
        y = row.get(y_field)
        if s is None or y is None:
            continue
        key = str(s)
        global_sums[key] = global_sums.get(key, 0.0) + float(y)
    return sorted(series, key=lambda s: (-global_sums.get(s, 0.0), s))


def series_order_expression(color_field: str, order: list[str]) -> str:
    """Build a VL calculate expression mapping each series value to its index in *order*.

    Bakes a precomputed Python order (the SAME list driving the legend/label
    display order) into a mark's own paint order or tooltip rank, so that
    consumer and display order can never drift apart. ``order`` entries are
    always ``str`` (``distinct_series_values`` str-casts the raw column), but
    the color field's actual row values keep their native type (numeric year,
    boolean flag, etc.) — comparing with a bare ``===`` would silently never
    match a non-string field, so both sides are coerced through ``toString``
    first. Example for color_field="status" with order=["new", "solved"]:
    ``toString(datum["status"]) === "new" ? 0 : toString(datum["status"]) === "solved" ? 1 : -1``
    """
    field_ref = f"toString(datum[{json.dumps(color_field)}])"
    parts = [f"{field_ref} === {json.dumps(v)} ? {i}" for i, v in enumerate(order)]
    return " : ".join(parts) + " : -1"


def distinct_series_values(data: list[dict[str, Any]], series_field: str) -> list[str]:
    """Alphabetically sorted distinct non-null values of *series_field*.

    This is the ground-truth series set for palette assignment: Vega-Lite's
    own default color-scale domain, matching ``config.range.category`` slot
    *i* to the *i*-th alphabetically-sorted series.

    Nulls stay filtered here. Admitting them would put the string ``"None"`` in
    the scale domain while the rows themselves hold ``null`` — a phantom legend
    entry for a series that paints nothing, which is worse than omitting it.
    Callers that must not silently lose a series run ``validate_color_series``
    first; families that don't yet (scatter, pie/arc, overlay layers) keep the
    quiet drop until that guard is extended to them.
    """
    return sorted(
        {str(row[series_field]) for row in data if row.get(series_field) is not None}
    )


def spatial_color_scale(
    series: list[str], palette: tuple[str, ...], order: list[str]
) -> VLDict:
    """Explicit VL color ``{domain, range}`` reordering DISPLAY only.

    ``order`` becomes the legend/tooltip/label DISPLAY sequence, but each
    series keeps the color Vega-Lite's own alphabetical default would have
    assigned it — computed here from *series* (alphabetical) and *palette* —
    never a color derived from the new display position.
    """
    color_of = {s: palette[i % len(palette)] for i, s in enumerate(series)}
    return {"domain": list(order), "range": [color_of[s] for s in order]}


def last_nonnull_value_per_series(
    data: list[dict[str, Any]], x_field: str, y_field: str, series_field: str
) -> dict[str, float]:
    """Each series' value at its own most-recent non-null (x, y) pair.

    A trailing null, or a series that ends early, never collapses its
    position — this tracks the last ACTUAL value per series independently,
    not the value at the single global-last x row.
    """
    latest_x: dict[str, Any] = {}
    latest_y: dict[str, float] = {}
    for row in data:
        s, x, y = row.get(series_field), row.get(x_field), row.get(y_field)
        if s is None or x is None or y is None:
            continue
        key = str(s)
        if key not in latest_x or x >= latest_x[key]:
            latest_x[key] = x
            latest_y[key] = float(y)
    return latest_y


def sorted_series_by_last_value(
    series: list[str],
    data: list[dict[str, Any]],
    x_field: str,
    y_field: str,
    series_field: str,
) -> list[str]:
    """Stable order for multi-line/overlap-area.

    Descending by each series' most-recent non-null value; ties broken
    alphabetically for determinism. A series with no non-null value anywhere
    carries no ordering signal, so it sorts last (alphabetically among
    itself). This is a single static order computed once at render time —
    never a live re-sort as the hover cursor moves.
    """
    values = last_nonnull_value_per_series(data, x_field, y_field, series_field)
    with_value = sorted(
        (s for s in series if s in values), key=lambda s: (-values[s], s)
    )
    without_value = sorted(s for s in series if s not in values)
    return with_value + without_value


__all__ = [
    "CartesianXResolution",
    "XYTitles",
    "apply_domain_headroom_bounds",
    "build_cartesian_y_encoding",
    "build_palette_config",
    "build_x_enc",
    "cartesian_x_scale_domain",
    "chart_sort_to_vl",
    "distinct_series_values",
    "resolve_xy_titles",
    "wide_measures_title",
    "count_horizontal_bar_categories",
    "last_nonnull_value_per_series",
    "min_height_for_horizontal_bar_categories",
    "resolve_cartesian_x",
    "resolve_measure_y_scale",
    "series_order_expression",
    "sorted_series_by_last_value",
    "sorted_series_by_stack_order",
    "spatial_color_scale",
    "zero_anchor_domain_floor",
]
