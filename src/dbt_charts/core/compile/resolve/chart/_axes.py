"""Cartesian axis baking: tick math, orientation, mirroring, endpoint-label suppression."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, NamedTuple

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.format import resolve_format
from dbt_charts.core.compile.models.chart.authored import (
    CartesianLayer,
    MultiplesConfig,
)
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    Chart,
    LineChart,
)
from dbt_charts.core.compile.models.chart.normalized._base import (
    _CartesianChartFields,
)
from dbt_charts.core.compile.models.chart.resolved import ResolvedStyleChannel
from dbt_charts.core.compile.models.style.authored import EndpointLabelsConfig
from dbt_charts.core.compile.models.style.context import ChartStyleContext
from dbt_charts.core.compile.models.style.theme import (
    AxisXStyle,
    AxisYStyle,
    _CartesianChartStyle,
)
from dbt_charts.core.compile.resolve.style.axis_cascade import (
    AxisOverrides,
    _merge_axis_cascade,
    chart_type_axis_patch as _chart_type_axis_patch,
)
from dbt_charts.core.compile.resolve.style.chart_context import (
    chart_authored_axis_format,
)
from dbt_charts.core.compile.resolve.style.typography import width_tier
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_TICKS_INTERVAL_MEASURE_AXIS,
)
from dbt_charts.core.diagnostics.codes_render import (
    ERR_MULTIPLES_INDEPENDENT_SCALE_MIRROR,
)
from dbt_charts.core.text.predefined_formats import ALL_PREDEFINED_NAMES

__all__ = [
    "SeriesNaming",
    "_NO_RAIL_ENDPOINT_LABELS",
    "_author_asked_for_endpoint_labels",
    "_author_hid_legend",
    "_bake_ay_orient",
    "_bake_ay_position_left",
    "_bake_ay_position_right",
    "_bake_cartesian_axes",
    "_edge_or_none",
    "_endpoint_labels_off_for_layers",
    "_endpoint_labels_off_for_multiples",
    "_extract_axis_overrides",
    "_reject_dual_axis_layered_endpoint_labels",
    "cartesian_series_naming",
]


def _extract_axis_overrides(
    primary: _CartesianChartStyle | None,
) -> AxisOverrides:
    """Extract chart-local axis patches from a family-level primary patch.

    Mirrors the axis_overrides_* extraction in build_chart_style_context
    (layers 11-13) so the resolve path can pass them directly to
    resolved_axis_style without building a per-chart ChartStyleContext. The
    x_label/y_label title-visible default is NOT applied here — it is
    injected directly into the axis cascade (``_merge_axis_cascade``'s
    ``label_authored`` parameter), the one place that already knows the full
    chart-local layer order, so every chart-local slot (global ``axis``,
    ``axis_quantitative``/``axis_band``, ``axis_x``/``axis_y``) beats the
    forcing default with no separate guard.
    """
    if primary is None:
        return AxisOverrides()
    return AxisOverrides(
        global_=primary.axis,
        x=primary.axis_x,
        y=primary.axis_y,
        quantitative=primary.axis_quantitative,
        band=primary.axis_band,
    )


def _bake_cartesian_axes(
    chart_style_context: ChartStyleContext,
    chart: Chart,
    chart_type: str,
    x_channel_type: str,
    y_channel_type: str,
    axis_overrides: AxisOverrides,
    multiples: MultiplesConfig | None = None,
    y: str | list[str] | None = None,
) -> tuple[AxisXStyle, AxisYStyle, float | None, float | None, bool, bool]:
    """Walk the 13-layer axis cascade for axis_x and axis_y, returning the
    merged, theme-typed axis pair, each axis's band_position (None unless
    that channel classified ordinal/nominal and a band override authored it),
    and axis_y's format_authored/format_is_alias flags (see
    ``_merge_axis_cascade``) — NOT yet built into the frozen
    ``ResolvedAxisStyle``. axis_x's format_authored/format_is_alias are
    discarded — no caller threads them into ``build_resolved_axis`` today,
    since no caller passes ``tick_values`` for axis_x.

    ``ay_format_is_alias`` returned here is NOT just ``_merge_axis_cascade``'s
    own value verbatim: that function only ever sees an EXPLICITLY authored
    layer (chart-level fallback or chart-local override), so a bare axis that
    just inherits the theme's own baseline format
    (``axis_quantitative.labels.format: number_default``, itself a predefined
    name) would otherwise never count as alias-derived — the overwhelming
    common case (no format authored at all) would silently miss
    ``build_resolved_axis``'s forced-right-align treatment. This function
    ORs in a direct ``ay.labels.format in ALL_PREDEFINED_NAMES`` check
    (below, right before resolving the format) against the final winner of
    the whole cascade, which is correct regardless of which layer set it.

    axis_x = categorical axis (normalized.x column, Dataface semantics).
    axis_y = measure axis (normalized.y column, Dataface semantics).
    These semantics hold regardless of orientation — axis routing is a
    render-layer concern; the cascade slots are fixed.

    axis_overrides carries the chart-local patches (layers 11-13) extracted from
    the family patch — passed explicitly so no per-chart ChartStyleContext
    is required.

    ``chart`` supplies the per-chart format fallback (``chart.format`` /
    ``style.number_format`` / ``style.time_format``) fed into each axis's
    Layer 10 via ``chart_authored_axis_format()``. axis_x is always the
    dimension axis (never the measure, even when the channel type happens to
    be quantitative — e.g. a scatter's x column), so its fallback is
    temporal-only (``style.time_format``); the quantitative measure fallback
    (``style.number_format`` / ``chart.format``) only ever reaches axis_y.

    ``multiples`` / ``y`` are the small-multiples inputs. This is the ONE home
    for the multiples↔mirror interaction: it (a) supplies a default value for
    the shipped ``axis_y.mirror`` flag on a wide grid, and (b) rejects the
    scale-independent-plus-mirror contradiction. It never introduces a second
    mirror mechanism — explicit author/theme mirror always wins. Whether that
    default collides with an endpoint-label rail is decided later, in
    ``MirrorAxisFeature`` — the render feature that composes the rail is the
    only place that fact is actually known (see its module docstring).

    Callers must still: (1) resolve ``ay.position`` from ``auto`` via
    ``_bake_ay_orient``/``_bake_ay_position_left``/``_bake_ay_position_right``
    (2) derive each axis's final left/right edge, if any, and (3) call
    ``build_resolved_axis(merged, edge=...)`` to get the render-ready axis —
    this is what lets ``label.align``/``title.align``'s inward/outward
    resolve against a known edge in the same construction that narrows the
    type, instead of losing the directive to a premature build.
    """
    # x_label/y_label are structurally absent on some Chart union members
    # (e.g. kpi, pie), so read via getattr like chart_authored_axis_format's
    # own isinstance-guarded access — _bake_cartesian_axes is only ever
    # called with a cartesian family in practice, but its declared parameter
    # type is the full Chart union.
    ax, ax_band_position, _, _ = _merge_axis_cascade(
        chart_style_context,
        "axis_x",
        x_channel_type,
        _chart_type_axis_patch(chart_style_context, chart_type, "axis_x"),
        chart_fallback_format=(
            chart_authored_axis_format(chart, "temporal")
            if x_channel_type == "temporal"
            else None
        ),
        axis_overrides=axis_overrides,
        chart_type=chart_type,
        label_authored=bool(getattr(chart, "x_label", None)),
    )
    ay, ay_band_position, ay_format_authored, ay_format_is_alias = _merge_axis_cascade(
        chart_style_context,
        "axis_y",
        y_channel_type,
        _chart_type_axis_patch(chart_style_context, chart_type, "axis_y"),
        chart_fallback_format=chart_authored_axis_format(chart, y_channel_type),
        axis_overrides=axis_overrides,
        chart_type=chart_type,
        label_authored=bool(getattr(chart, "y_label", None)),
    )
    # labels.values (the label-cadence filter) lives only on DimensionLabelStyle,
    # used solely by AxisXStyle.labels — axis_y structurally cannot author it,
    # so no runtime check is needed here (Pydantic rejects it at the authoring
    # boundary instead). ticks.time_unit is likewise structurally x-only
    # (DimensionTicksStyle) and rejected the same way; only `step` still
    # exists on the universal AxisTicksStyle base, so it's the only field
    # left to guard here.
    if ay.ticks.step is not None:
        # Same measure-axis rationale as labels.values above — axis_y is never
        # temporal, so step-anchored cadence never applies there.
        raise CompilationError.from_code(ERR_TICKS_INTERVAL_MEASURE_AXIS)
    # time_unit+count is enforced in the model itself
    # (DimensionTicksStyle._validate_cadence) — no compile-pass check needed.
    # step-without-time_unit is not a model rule: a bare step is the
    # quantitative-axis cadence lever, so the check needs the resolved axis
    # type and lives in render (apply_x_tick_cadence).
    # Resolve any format alias (e.g. "currency_whole" → "$,.0f") at bake time
    # so axis_to_vl() emits valid d3-format strings, not internal alias names.
    # No `if fmts:` gate: resolve_format() resolves predefined names to their
    # round-aware specs (trim already baked) and aliases to native d3; fmts
    # empty/None still resolves predefined names on the first path.
    # The spec itself is already guaranteed resolvable by
    # validate/formats.py's compile()-time pass (the per-chart authored walk
    # plus the four theme-baked global axis slots) -- this function trusts
    # that guarantee rather than re-checking it, per core/AGENTS.md's
    # validation-boundary rule.
    fmts = chart_style_context.formats
    if ax.labels.format is not None:
        resolved_ax_format = resolve_format(ax.labels.format, fmts)
        ax = ax.model_copy(
            update={
                "labels": ax.labels.model_copy(update={"format": resolved_ax_format})
            }
        )
    if ay.labels.format is not None:
        # ay.labels.format is still the raw pre-resolve string here -- the
        # final winner of the whole 13-layer cascade, whichever layer set it
        # last (authored or theme-default). _merge_axis_cascade's own
        # format_is_alias only ever sees an EXPLICITLY authored layer (board
        # 6-9, chart-format fallback 10, or chart-local 11-13); a bare axis
        # inheriting the theme's own baseline
        # (axis_quantitative.labels.format: number_default, itself a
        # predefined name) never touches that tracking. Checking the final
        # raw value directly against ALL_PREDEFINED_NAMES covers both cases
        # uniformly -- it doesn't matter which layer won, only that the
        # winner is a predefined name.
        ay_format_is_alias = ay_format_is_alias or (
            ay.labels.format in ALL_PREDEFINED_NAMES
        )
        resolved_ay_format = resolve_format(ay.labels.format, fmts)
        ay = ay.model_copy(
            update={
                "labels": ay.labels.model_copy(update={"format": resolved_ay_format})
            }
        )
    ay = _apply_multiples_mirror(ay, multiples, y, y_channel_type, chart.id)
    return (
        ax,
        ay,
        ax_band_position,
        ay_band_position,
        ay_format_authored,
        ay_format_is_alias,
    )


def _edge_or_none(value: str | None) -> Literal["left", "right"] | None:
    """Narrow a free-form position/orient string to a left/right edge, or
    None when it isn't one (bottom/top/auto/unset) — the axis has no
    left/right edge to resolve inward/outward align against."""
    if value == "left":
        return "left"
    if value == "right":
        return "right"
    return None


def _endpoint_label_rail_fires(
    channels: Mapping[str, ResolvedStyleChannel],
    endpoint_labels_visible: bool,
    *,
    wide_measure_series: bool = False,
    has_layers: bool = False,
) -> bool:
    """Return True when a rail of endpoint labels will render.

    Needs a series colour channel (a folded wide area measure series, or a
    layered chart naming each layer's own endpoint — see
    ``EndpointLabelFeature._apply_layered_single_series``) to have anything
    to name, plus endpoint labels switched on. Callers must gate
    ``has_layers`` on ``dbt_charts.core.utils.layered_endpoint_rail_fires``
    themselves — this function trusts whatever it's handed.

    The layered term only fires when there is NO base colour channel at all
    (``color_ch is None``): a gradient/literal/conditional colour channel
    puts a non-series ``color`` encoding on the base spec, so
    ``emitters/_overlay.py``'s ``use_shared_scale`` never builds the shared
    colour scale the layered rail reads (``_layer_color_scale``) — this must
    agree with ``EndpointLabelFeature.applies_to()``, which returns False for
    exactly that colour-channel shape.
    """
    color_ch = channels.get("color")
    return endpoint_labels_visible and (
        wide_measure_series
        or (color_ch is not None and color_ch.mode == "series")
        or (has_layers and color_ch is None)
    )


def _suppress_legend_for_endpoint_labels(
    channels: Mapping[str, ResolvedStyleChannel],
    endpoint_labels_visible: bool,
    layered_rail_fires: bool,
    *,
    wide_measure_series: bool = False,
    has_layers: bool = False,
) -> bool:
    """Return True when endpoint labels will replace the colour legend.

    Two disjoint shapes retire the legend, each matched to what
    ``EndpointLabelFeature.apply()`` actually names — deliberately narrower
    than "the rail fires at all":

    - No base colour channel, only layers (the layered rail —
      ``_apply_layered_single_series``): ``layered_rail_fires`` (callers pass
      ``dbt_charts.core.utils.layered_endpoint_rail_fires``'s result) is
      already gated on every layer lacking its own colour field, so once
      it's True the rail names every series the legend would otherwise
      carry — nothing left for the legend to do.
    - A base colour-series channel, or a folded wide-area measure series:
      the rail (``_resolve_endpoint_label_positions`` / ``_apply_wide_area``)
      only ever names the base's own series, never an overlay layer's — see
      ``EndpointLabelFeature.apply()``'s branch on ``has_series_color``, which
      takes priority over the layered path regardless of ``chart.layers``.
      Retiring the legend here is only safe when there is no layer left
      unnamed — this must be the *raw* ``chart.layers`` fact (``has_layers``),
      not ``layered_rail_fires``: an overlay strands regardless of whether
      shape/orientation/colour gates keep the layered rail itself from
      firing.
    """
    if not endpoint_labels_visible:
        return False
    color_ch = channels.get("color")
    if layered_rail_fires and color_ch is None:
        return True
    non_layered_rail_fires = wide_measure_series or (
        color_ch is not None and color_ch.mode == "series"
    )
    return non_layered_rail_fires and not has_layers


def _reject_dual_axis_layered_endpoint_labels(
    chart_id: str,
    layers: list[CartesianLayer],
    layered_rail_fires: bool,
) -> None:
    """Refuse a layered endpoint-label rail across a dual-axis layer.

    The rail anchors on one shared y-scale (``_apply_layered_single_series``);
    a layer pinning its own ``axis_y.position`` renders on a different one.
    The trigger — an authored ``axis_y.position`` on a layer, on a chart
    whose rail would otherwise fire — is fully known at resolve, so it is
    refused here rather than at render: compile has already flipped the axis
    left and suppressed the legend for a rail that would never render.
    """
    if not layered_rail_fires:
        return
    if any(
        layer.axis_y is not None and layer.axis_y.position is not None
        for layer in layers
    ):
        raise ChartDataError(
            "endpoint_labels.visible is not supported on a layered chart "
            "whose layers pin an explicit axis_y.position — the label "
            "rail anchors on one shared y-scale, and a dual-axis layer "
            "renders on a different one. To fix: remove the per-layer "
            "axis_y.position override, or set "
            "endpoint_labels.visible: false on this chart.",
            chart_id,
        )


def _endpoint_labels_off_for_layers(
    endpoint_labels: EndpointLabelsConfig,
    normalized: BarChart | LineChart | AreaChart,
    author_opted_in: bool,
) -> EndpointLabelsConfig:
    """A layered chart's default is a legend, not the endpoint-label rail.

    Every family here defaults endpoint labels on; without this disqualifier
    an un-opted-in layered chart would flip straight to the rail and leave a
    single-series chart with an overlay looking like the multi-series case it
    isn't.

    An author who writes ``style.endpoint_labels.visible: true`` opts in: the
    rail then names the base series and every overlay layer's own endpoint
    (see ``EndpointLabelFeature._apply_layered_single_series``), and
    ``_suppress_legend_for_endpoint_labels`` retires the legend so nothing is
    named twice.
    """
    if author_opted_in or not normalized.layers:
        return endpoint_labels
    return endpoint_labels.model_copy(update={"visible": False})


def _endpoint_labels_off_for_multiples(
    endpoint_labels: EndpointLabelsConfig,
    normalized: BarChart | LineChart | AreaChart,
    author_opted_in: bool,
) -> EndpointLabelsConfig:
    """Each small multiple is its own panel; the rail names series for one panel
    and a faceted chart has no single panel for it to sit beside. The shared
    top legend takes over the naming (``_multiples_wants_top_legend``).

    Like its sibling above it steers the default only: an author who wrote
    ``endpoint_labels.visible: true`` on a faceted chart still reaches the
    render-layer refusal, with a diagnostic naming both fields.
    """
    if author_opted_in or normalized.multiples is None:
        return endpoint_labels
    return endpoint_labels.model_copy(update={"visible": False})


def _multiples_wants_top_legend(
    normalized: _CartesianChartFields,
    channels: Mapping[str, ResolvedStyleChannel],
    wide_measure_series: bool = False,
) -> bool:
    """True when a faceted chart has series the legend must name from above.

    One legend above the panels reads across the whole grid; a side rail sits
    beside whichever panel it lands next to and reads as that panel's. Shares
    ``_endpoint_label_rail_fires`` with the rail it replaces so the two can't
    disagree about what counts as a series to name — passing ``True`` for the
    rail's visibility asks it the unconditional form of that question, since
    ``_endpoint_labels_off_for_multiples`` has just switched the real rail off.
    """
    return normalized.multiples is not None and _endpoint_label_rail_fires(
        channels, True, wide_measure_series=wide_measure_series
    )


def _author_hid_legend(primary: Any) -> bool:
    """True when this chart's own style says it carries no legend.

    ``primary`` stays ``Any`` here and in its sibling below because it's
    ``Any`` at its source (``CartesianPlan.primary`` — see that field's own
    docstring in ``_plan.py`` for why it isn't narrowed) and neither function
    does anything else with it. A local ``_HasColor``-style Protocol would
    still need the same ``None`` guard below, since the value genuinely is
    ``None`` for an unstyled chart — narrowing buys nothing here.

    Read from the chart-local patch, not the merged cascade: a theme that hides
    legends board-wide (editorial does) leaves the same ``visible: False`` on
    the merged value, and the width-tier and grouped-bar policies exist
    precisely to bring a legend back where one is needed. Only the author's own
    say-so on this chart outranks them.
    """
    if primary is None:
        return False
    legend = primary.legend
    return legend is not None and legend.visible is False


def _author_asked_for_endpoint_labels(style: Any) -> bool:
    """True when this chart's own style asks for a rail of endpoint labels.

    Read from the authored patch for the same reason as ``_author_hid_legend``:
    every theme now switches the rail on, so the merged value says ``True`` for
    charts that never asked. Only this chart's own say-so overrides the
    shape-based disqualifiers. style stays Any: the patch model's
    TYPE_CHECKING stub declares this field non-optional while the runtime value
    really is None when unauthored, so a typed signature would let the type
    checker delete the None guard that every unstyled chart depends on.
    """
    if style is None:
        return False
    endpoint_labels = style.endpoint_labels
    return endpoint_labels is not None and endpoint_labels.visible is True


def _series_label_layout_for_width(
    endpoint_labels: EndpointLabelsConfig,
    width: float,
) -> tuple[EndpointLabelsConfig, bool]:
    """Make the top legend the series-naming mechanism for every tiny chart."""
    if width_tier(width) != "tiny":
        return endpoint_labels, False
    return (
        endpoint_labels.model_copy(update={"visible": False}),
        True,
    )


def _bake_ay_orient(
    ay: AxisYStyle,
    channels: Mapping[str, ResolvedStyleChannel],
    endpoint_labels_visible: bool,
    *,
    wide_measure_series: bool = False,
    has_layers: bool = False,
) -> AxisYStyle:
    """Resolve 'auto' y-axis position for line/area/bar at compile time.

    'auto' flips to 'left' when endpoint labels take the right rail (series
    colour channel present, a layered chart, or endpoint_labels.visible on a
    folded wide area); 'right' otherwise. Non-'auto' positions pass through
    unchanged so authored explicit sides win.

    Operates on the merged, pre-build ``AxisYStyle`` (not the frozen
    ``ResolvedAxisStyle``) — called before ``build_resolved_axis`` so the
    axis's final position is known in time to resolve inward/outward align
    against it in the same build call.
    """
    if ay.position != "auto":
        return ay
    fires = _endpoint_label_rail_fires(
        channels,
        endpoint_labels_visible,
        wide_measure_series=wide_measure_series,
        has_layers=has_layers,
    )
    return ay.model_copy(update={"position": "left" if fires else "right"})


def _bake_ay_position_left(ay: AxisYStyle) -> AxisYStyle:
    """Resolve 'auto' y-axis position to 'left' (VL default) for chart types
    that never placed the y-axis on the right: heatmap (categorical y) and
    histogram. Non-'auto' positions pass through unchanged.

    Operates on the merged, pre-build ``AxisYStyle`` — see ``_bake_ay_orient``.
    """
    if ay.position != "auto":
        return ay
    return ay.model_copy(update={"position": "left"})


def _bake_ay_position_right(ay: AxisYStyle) -> AxisYStyle:
    """Resolve 'auto' y-axis position to 'right' for chart types that have no
    endpoint-label rail to yield the right side to (scatter). Non-'auto'
    positions pass through unchanged.

    Operates on the merged, pre-build ``AxisYStyle`` — see ``_bake_ay_orient``.
    """
    if ay.position != "auto":
        return ay
    return ay.model_copy(update={"position": "right"})


def _apply_multiples_mirror(
    ay: AxisYStyle,
    multiples: MultiplesConfig | None,
    y: str | list[str] | None,
    y_channel_type: str,
    chart_id: str,
) -> AxisYStyle:
    """Resolve the both-edge y-axis for a small-multiples chart.

    Both-edge (mirror) reuses the single shipped ``resolved_axis_y.mirror``
    flag. ``ay.mirror is None`` means neither author nor theme set it — only
    then does the orthogonal-count>1 rule supply ``True``. An explicit True/
    False/AxisMirrorStyle (author or theme) is left untouched. ``scale:
    independent`` with mirror on — bool True or an AxisMirrorStyle
    format/expr override, both truthy — is a contradiction and raises.

    Whether this auto-default collides with an endpoint-label rail is NOT
    decided here: that fact (the rail's final visibility, after every
    render-layer disqualifier — width tier, horizontal-stack shape, ...) is
    only known once ``EndpointLabelFeature`` has run, which is after resolve
    is long done. ``MirrorAxisFeature`` decides the collision at render time
    instead, from the composed spec it already holds.

    Operates on the merged, pre-build ``AxisYStyle`` — see ``_bake_ay_orient``.
    """
    if multiples is None:
        return ay
    # The measure axis (y) spreads horizontally across panel COLUMNS, so a
    # declared `columns` field is the "orthogonal panel count > 1" signal: the
    # far columns sit away from the single left axis and want a mirrored edge.
    # A rows-only stack has one column and never auto-mirrors.
    has_columns = multiples.columns is not None
    if multiples.scale == "independent" and ay.mirror:
        raise ChartDataError.from_code(
            ERR_MULTIPLES_INDEPENDENT_SCALE_MIRROR, chart_id=chart_id
        )
    # Auto-default: multiple columns + shared scale + unset mirror + single
    # QUANTITATIVE measure axis. Mirroring is only meaningful for a shared
    # numeric scale — a categorical y (heatmap) or multi-series y has no
    # both-edge meaning, so never auto-enable there.
    if (
        has_columns
        and multiples.scale == "shared"
        and ay.mirror is None
        and y_channel_type == "quantitative"
        and not isinstance(y, list)
    ):
        return ay.model_copy(update={"mirror": True})
    return ay


class SeriesNaming(NamedTuple):
    """The legend-vs-rail decision every cartesian family resolves with.

    ``endpoint_labels`` is the tiny-width-adjusted rail config. Families with
    no rail (scatter, heatmap) pass ``_NO_RAIL_ENDPOINT_LABELS`` in and have
    no field on their own resolved style to put the output in — "no rail" is
    the explicit input, the returned copy is simply unused, never a skipped
    call to this function.
    """

    endpoint_labels: EndpointLabelsConfig
    suppress_legend: bool
    top_legend: Literal["compact", "row", "off"]


_NO_RAIL_ENDPOINT_LABELS = EndpointLabelsConfig(
    visible=False, label_offset=0.0, height=0.0
)


def cartesian_series_naming(
    normalized: _CartesianChartFields,
    channels: Mapping[str, ResolvedStyleChannel],
    author_hid_legend: bool,
    width: float,
    endpoint_labels: EndpointLabelsConfig,
    endpoint_label_has_layers: bool,
    has_layers: bool,
    rail_eligible_for_suppression: bool,
    suppress_wide_measure_series: bool,
    multiples_wide_measure_series: bool,
    layers_route_to_top_legend: bool,
    unconditional_top_legend: bool,
) -> SeriesNaming:
    """Decide how a cartesian chart's series get named: rail, top legend, or plain legend.

    Owns the composition every family previously hand-assembled: the
    tiny-width fallback to a compact top legend
    (``_series_label_layout_for_width``), whether endpoint labels retire the
    colour legend (``_suppress_legend_for_endpoint_labels``), whether a
    small-multiples grid wants one legend above the panels
    (``_multiples_wants_top_legend``), and the top_legend/off ternary that
    reads those together with the author's own ``legend.visible: false``.
    ``author_hid_legend`` is that last fact's already-read value — every
    caller passes ``_author_hid_legend(primary)`` — kept a plain ``bool``
    parameter here rather than threading ``primary`` itself through (``primary``
    is untyped at its source; this function does nothing else with it).

    ``endpoint_labels`` arrives already family-disqualified (bar's stack
    chain, or line/area's layers-then-multiples chain already applied) —
    this function only applies the tiny-width fold on top.

    ``rail_eligible_for_suppression`` ANDs into the tiny-adjusted
    ``endpoint_labels.visible`` right before the suppression check, and only
    there: bar's horizontal grouped shape never earns a rail even when
    ``endpoint_labels.visible`` is true (``_horizontal_series_rail_fires``);
    every other family passes ``True``.

    ``suppress_wide_measure_series`` and ``multiples_wide_measure_series`` are
    separate parameters because bar.py asks the two questions differently
    today: its wide-y fold (``isinstance(normalized.y, list)``) counts as a
    multiples-legend signal but never as a suppression signal (bar always
    passes False there). Area passes its own wide flag to both; line and
    scatter/heatmap pass False to both.

    ``layers_route_to_top_legend`` is line/area's policy that an unnamed
    overlay layer belongs in the top legend once the rail hasn't already
    claimed it (``has_layers and not suppress_legend``). Bar answers the same
    "does the top strip carry the legend" question from its own stacked/
    grouped shape instead, via ``unconditional_top_legend`` — so bar passes
    False here. Scatter/heatmap pass False to both: routing their overlay
    layers to a top legend is out of scope for this decision.
    """
    endpoint_labels, tiny_top_legend = _series_label_layout_for_width(
        endpoint_labels, width
    )
    suppress_legend = _suppress_legend_for_endpoint_labels(
        channels,
        endpoint_labels.visible and rail_eligible_for_suppression,
        endpoint_label_has_layers,
        wide_measure_series=suppress_wide_measure_series,
        has_layers=has_layers,
    )
    top_legend: Literal["compact", "row", "off"] = (
        "off"
        if author_hid_legend
        else (
            "compact"
            if tiny_top_legend
            else (
                "row"
                if (
                    (layers_route_to_top_legend and has_layers and not suppress_legend)
                    or unconditional_top_legend
                    or _multiples_wants_top_legend(
                        normalized, channels, multiples_wide_measure_series
                    )
                )
                else "off"
            )
        )
    )
    return SeriesNaming(endpoint_labels, suppress_legend, top_legend)
