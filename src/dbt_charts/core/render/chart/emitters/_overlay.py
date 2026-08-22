"""Shared overlay rendering for cartesian chart.layers.

When a bar/line/area/scatter chart carries authored ``layers``, the base chart
emits its base spec as usual; then this module wraps both into an outer
``mark="layered"`` spec with the overlay sublayers appended in authored order
(paint order: base first / bottom, each overlay on top).

Dual-axis, mixed-mark legend symbols, and step-band xOffset resolution are
handled here.
"""

from __future__ import annotations

import json as _json
from typing import Any

from dbt_charts.core.compile.models.chart.resolved._layer import (
    ResolvedAreaLayer,
    ResolvedBarLayer,
    ResolvedLayer,
    ResolvedLineLayer,
    ResolvedScatterLayer,
)
from dbt_charts.core.compile.models.style.resolved import ResolvedLegendStyle
from dbt_charts.core.compile.models.style.resolved._base import ResolvedAxisStyle
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters._cartesian import (
    canonicalize_cartesian_x_data,
    distinct_series_values,
    spatial_color_scale,
)
from dbt_charts.core.render.chart.emitters._channels import apply_color_legend
from dbt_charts.core.render.chart.emitters._layers import (
    emit_area_layer,
    emit_bar_layer,
    emit_line_layer,
    emit_scatter_layer,
)
from dbt_charts.core.render.chart.emitters._tooltip import (
    TooltipField,
    build_structured_tooltip_expr,
    header_tooltip_field,
)
from dbt_charts.core.render.chart.features.value_labels import (
    BandLabelAnchor,
    _build_bar_text_layer,
    _build_point_text_layer,
    band_label_anchor,
    build_line_text_layers,
    labels_draw_text,
    text_layer_spec,
)
from dbt_charts.core.render.chart.spec import ChartSpec
from dbt_charts.core.render.chart.step_band import (
    BAND_STEP_CURVE,
    apply_step_band,
    is_band_step,
)
from dbt_charts.core.render.chart.time_unit_detect import (
    calendar_bucket_key,
    ordinal_axis_values,
)
from dbt_charts.core.render.chart.type_inference import (
    infer_vega_type_from_data,
    is_date_like_string,
)
from dbt_charts.core.render.chart.vl_field_maps import axis_to_vl, bar_mark_radius
from dbt_charts.core.render.chart.x_domain import rendered_x_domain
from dbt_charts.core.render.utils import (
    normalize_data_types,
    ordered_distinct_values,
)
from dbt_charts.core.text.case import format_display_text

# VL scale types where the domain is an ordered list of discrete categories
# (as opposed to a continuous [min, max] range). Union-domain reconciliation
# below is scoped to this case only — a continuous (temporal/quantitative)
# shared x scale already gets a correct min/max union natively from Vega-Lite
# across sub-layers, ordering never matters, so no explicit reconciliation
# is needed there.
_CATEGORICAL_X_TYPES = ("nominal", "ordinal")

# A data row: same shape as VLDict (str-keyed, untyped values) — aliased under
# its own name so row-of-query-results reads distinctly from a VL fragment.
_Row = VLDict

# Combo tooltip unification (StructuredTooltipFeature) covers bar/line/area
# bases only -- matches applies_to()'s own gate in
# features/structured_tooltip.py. A scatter base has no natural x "header"
# identity for the x-unified bubble (scatter's own role model carries no
# header row at all; x/y are two peer VALUE rows instead), so a scatter base
# stays on the plain VL auto-tooltip. Overlay layers atop a scatter base get
# no structured description either -- keeping both sides on the SAME (old,
# unmodified) behavior, rather than a half-migrated state where only the
# overlay is role-marked and can never unify with its own base.
_STRUCTURED_TOOLTIP_BASE_FAMILIES = frozenset({"bar", "line", "area"})


def _base_domain_is_date_shaped(base_data: list[_Row], base_field: str) -> bool:
    """True when every distinct value of the base's own x column is date-like.

    Drives the one deliberate exception in _resolve_layer_x_encoding: a
    layer classifying "temporal" standalone is only union-compatible with a
    categorical base when the base's OWN labels are also dates (just
    density-gated to ordinal/nominal by the bar/line x-encoding builder) —
    never with a base whose categories are plain non-date labels.
    """
    values = ordered_distinct_values(base_data, base_field)
    return bool(values) and all(
        isinstance(v, str) and is_date_like_string(v) for v in values
    )


def _resolve_layer_x_encoding(
    x_field: str,
    rows: list[_Row],
    base_x_enc: VLDict,
    base_domain_is_date_shaped: bool,
    chart_id: str,
) -> VLDict:
    """Build a layer's own x encoding, its type resolved against the base's
    x type at construction time — not classified standalone and patched
    afterward.

    A layer authoring its own x column is classified independently via
    infer_vega_type_from_data. Sharing a scale with a categorical
    (nominal/ordinal) base works whenever the layer ALSO classifies as
    categorical (nominal or ordinal) — both are discrete-label types, and
    the two independent per-field classifications routinely disagree on
    which one (e.g. a bucket-gated date base reads "ordinal" while a plain-
    label goal/target layer reads "nominal") without the underlying data
    being incompatible. The one further exception is a layer classifying
    "temporal" (well-formed dates) against a base whose own domain is ALSO
    date-shaped (see _base_domain_is_date_shaped) — that's the same
    date-shaped labels on both sides, just density-gated differently. Either
    way the layer's type is pinned to the base's before ANY downstream
    consumer (step-band curve detection, the union domain) ever sees the
    standalone classification. A layer resolving to a genuinely incompatible
    type — quantitative, or non-date-shaped temporal against a non-date-
    shaped base — raises; this never silently accepts a mismatch.

    A quantitative base additionally rejects a layer resolving to anything
    other than "quantitative" — sharing a numeric scale with a string field
    gives Vega-Lite no pixel positions at all (NaN), and sharing it with a
    temporal field forces the base's plain-number tick format onto the
    layer's epoch-ms values (garbled labels, not a correct union) — neither
    is the "continuous shared x scale gets a correct min/max union natively"
    case the categorical-base check exists to make an exception for. This
    only runs when the layer's classification is data-backed (rows present
    and the field is actually in them): infer_vega_type_from_data returns
    "nominal" as an absence sentinel for empty data, which is not a real
    classification and must not be treated as a genuine string-vs-number
    mismatch — an ordinary empty-query overlay layer is unremarkable, not an
    error.

    base_x_enc carries no "type" key (or a temporal one) when the base x
    isn't nominal/ordinal/quantitative at all — no validation runs there,
    returning the layer's own standalone classification unchanged. That
    temporal-base gap is a separate, out-of-scope follow-up. Callers pass {}
    (never None) when the base has no x encoding.
    """
    layer_type = infer_vega_type_from_data(rows, x_field)
    base_type = base_x_enc.get("type")
    if (
        base_type == "quantitative"
        and rows
        and x_field in rows[0]
        and layer_type != "quantitative"
    ):
        raise ChartDataError(
            f"chart '{chart_id}': layer x '{x_field}' resolved to a "
            f"{layer_type} scale, but the base x '{base_x_enc.get('field')}' is "
            f"{base_type} — a layer sharing the x axis with a quantitative "
            "base must itself resolve to a quantitative type.",
            chart_id=chart_id,
        )
    if base_type not in _CATEGORICAL_X_TYPES:
        return {"field": x_field, "type": layer_type}
    if layer_type in _CATEGORICAL_X_TYPES:
        return {"field": x_field, "type": base_type}
    if layer_type == "temporal" and base_domain_is_date_shaped:
        return {"field": x_field, "type": base_type}
    raise ChartDataError(
        f"chart '{chart_id}': layer x '{x_field}' resolved to a "
        f"{layer_type} scale, but the base x '{base_x_enc.get('field')}' is "
        f"{base_type} — layers sharing the x axis with the base must "
        "resolve to the same discrete-label domain.",
        chart_id=chart_id,
    )


def _reconcile_x_domain(
    x_enc: VLDict,
    base_data: list[_Row],
    layer_x_columns: list[tuple[str, list[_Row]]],
    force: bool = False,
) -> None:
    """Set an explicit ordered-union domain on the shared categorical x scale
    when a layer's rows genuinely diverge from the base's, or when ``force``
    is True (an overlay layer's own label sublayer carries a calculate
    transform — house-register formatting or a position transform like
    ``middle``/``middle_aligned``/``bottom``).

    Vega-Lite's default domain union across sub-layers sharing an x scale is
    unordered (alphabetical), so a layer whose rows diverge from the base's
    needs an explicit domain to preserve the base's own row order and to
    guarantee its categories — which may not be a subset of the base's own —
    aren't dropped from the shared scale. The base's order comes first,
    exactly as its query returned it.

    An authored ``chart.sort`` is NOT "reordered upstream of this function"
    — ``chart_sort_to_vl`` only builds a Vega-Lite ``sort:`` dict applied at
    render time, the row order this function reads is never touched by it —
    so pinning an *unsorted* explicit domain would silently defeat that sort
    (an explicit ``scale.domain`` always wins over ``sort`` in Vega-Lite).
    For the rows-diverge trigger this function bails out entirely when
    ``x_enc`` carries a truthy ``sort`` (mirroring the same guard in
    ``pin_categorical_domain_order``, ``emitters/_layers.py``) and lets
    Vega-Lite's own native sort-by-field apply — verified empirically to
    resolve correctly for that trigger.

    The ``force=True`` trigger cannot rely on the same bail-out: verified
    empirically that Vega-Lite's native sort-by-field does NOT correctly
    resolve a shared categorical scale when one of the sharing sublayers
    (a label's own calculate-transform sublayer) carries no
    x encoding of its own — it silently falls back to alphabetical order
    regardless of whether a domain is pinned. So when ``force`` fired and a
    sort is authored, this function pins an EXPLICIT domain sorted the same
    way Vega-Lite's own field-based sort would (see
    ``rendered_x_domain``), rather than bailing out — an unsorted pin
    would defeat the sort exactly as badly as no pin does for this trigger.

    Any layer-only categories are appended after, in the layer's own
    first-seen order. No-op when the base x scale isn't categorical
    (nominal/ordinal) or when neither trigger fires. Every layer's own x
    type has already been resolved against the base's (see
    _resolve_layer_x_encoding) by the time this runs — this function only
    unions and orders values, it never classifies or raises.
    """
    if not layer_x_columns and not force:
        return
    if x_enc.get("type") not in _CATEGORICAL_X_TYPES:
        return
    if x_enc.get("sort") and not force:
        return
    if not isinstance(x_enc.get("field"), str):
        return
    x_enc.setdefault("scale", {})["domain"] = rendered_x_domain(
        x_enc, base_data, layer_x_columns
    )


def _resolve_layer_rows(
    layer: ResolvedLayer,
    base_x_field: str | None,
    axis_x: ResolvedAxisStyle,
    base_x_authored_temporal: bool,
    datasets: dict[str | None, list[_Row]] | None,
    base_query_name: str | None,
) -> tuple[str | None, list[_Row] | None]:
    """Return this layer's effective x field and its OWN rows (None → shares base's).

    A layer's rows genuinely diverge from the base's only when its resolved
    query name differs from the base's own — an unauthored layer's query_name
    defaults to ``base_query_name`` (see ``render_cartesian_overlay``'s
    docstring), so ``layer.query_name is not None`` is true for nearly every
    layer and is NOT a divergence signal. A non-diverging layer reads the
    base's own ``data`` (already gap-filled/bucket-normalized by the family
    emitter), never the raw ``datasets`` lookup — using ``datasets`` there
    would read pre-normalization rows and mismatch what the base renders.

    Own-query rows are canonicalized through the same
    ``canonicalize_cartesian_x_data`` the base ran, so every layer shares one
    x domain in the same JS-``Date``-parseable string form rather than
    splitting onto two (which halves the marks across the axis, or — for a
    datetime split — buckets the overlay off the base outside UTC).
    ``skip_bucket_collapse`` inherits the base's OWN verdict
    (``base_x_authored_temporal``) rather than re-deriving it from ``axis_x``.
    The authored ``time_unit`` only carries over when the layer shares the
    base's own field; a layer with its own DIFFERENT x column gets None
    (auto-detect), since the base's authored grain was never chosen for it.

    Shared by ``render_cartesian_overlay``'s own loop and by
    ``overlay_x_domain_values`` so the x domain the axis labels is derived
    from exactly the rows the layers render.
    """
    effective_x_field = layer.x if layer.x is not None else base_x_field
    layer_diverges = layer.query_name != base_query_name
    own_data: list[_Row] | None = (
        datasets.get(layer.query_name)
        if layer_diverges and datasets is not None
        else None
    )
    if own_data is not None and effective_x_field is not None:
        layer_authored_time_unit = (
            axis_x.time_unit if effective_x_field == base_x_field else None
        )
        own_data, _ = canonicalize_cartesian_x_data(
            own_data,
            effective_x_field,
            layer_authored_time_unit,
            skip_bucket_collapse=base_x_authored_temporal,
        )
    return effective_x_field, own_data


def _orderable_axis_values(rows: list[_Row], field: str) -> list[Any] | None:
    """``ordinal_axis_values``, or None when the column has no orderable domain.

    Query results are not guaranteed homogeneous, and ``ordinal_axis_values``
    sorts internally — a column mixing ints and strings raises ``'<' not
    supported between instances of 'str' and 'int'`` inside it, before any
    caller can inspect the values. A column with no total order simply has no
    tick domain to derive, which is a fact about the data rather than a
    failure: the axis keeps deriving its own ticks exactly as it did before
    this function existed. Catching is the only way to learn it here.
    """
    try:
        return ordinal_axis_values(rows, field)
    except TypeError:  # unsortable or unhashable column — no total order
        return None


def _band_identity(value: Any) -> Any:
    """The band ``value`` occupies — its instant, else the value itself.

    Non-calendar columns have no parse to key on and are already one band per
    distinct value, so they key on themselves.
    """
    key = calendar_bucket_key(value)
    return value if key is None else key


def _same_x_vocabulary(base_values: list[Any], layer_values: list[Any]) -> bool:
    """True when two x columns hold the same KIND of value, not just the same name.

    Two gates. Types must match, or the merged list cannot even be sorted
    (``'<' not supported between 'str' and 'int'``). Then calendar-membership
    must match **in both directions**: a plain-label column of strings passes
    the type gate but is not a bucket of the base's calendar grain, and merging
    either way round makes grain detection raise. Asking only "is the BASE a
    calendar column" let a base this module failed to recognise fall through to
    the bare type comparison and admit a plain-label layer.

    Membership is decided by the same parser the downstream consumers use, not
    by a date-shaped pattern: a pattern disagrees with the parser in both
    directions — accepting the unparseable half-year forms (``2024-H1``) and
    rejecting parseable timezone-aware ones — and either disagreement admits a
    value that raises later.

    The two sides must be wholly calendar or wholly not. ``all(base) ==
    all(layer)`` is not equivalent: a base carrying a few unparseable strays is
    not "all calendar", so it matches a plain-label layer on both-are-false.
    ``any`` fails the other way, admitting a layer that mixes one real date
    into labels.
    """
    if {type(v) for v in layer_values} != {type(v) for v in base_values}:
        return False
    base_calendar = [calendar_bucket_key(v) is not None for v in base_values]
    layer_calendar = [calendar_bucket_key(v) is not None for v in layer_values]
    if all(base_calendar) and all(layer_calendar):
        return True
    return not any(base_calendar) and not any(layer_calendar)


def overlay_uses_band_step(layers: tuple[ResolvedLayer, ...]) -> bool:
    """True when any overlay layer draws the band-aware ``step`` curve.

    Such a layer shares the base's x scale and doubles its rows onto each
    band's two edges, so it depends on adjacent band edges being the same
    float (``step_band.py``). Anything that perturbs the band scale — even
    sub-pixel — breaks that pairing, so the base emitter must know before it
    builds the scale, not after the overlay wrap.
    """
    for layer in layers:
        # A y-less layer is skipped entirely by render_cartesian_overlay, so
        # it doubles nothing and has no shared edge to protect — exempting on
        # it would silently reinstate the cull this fix exists to remove.
        if layer.y is None:
            continue
        if isinstance(layer, ResolvedLineLayer):
            if layer.line_mark.curve == BAND_STEP_CURVE:
                return True
        elif isinstance(layer, ResolvedAreaLayer) and (
            layer.area_mark.curve == BAND_STEP_CURVE
        ):
            return True
    return False


def overlay_x_domain_values(
    layers: tuple[ResolvedLayer, ...],
    data: list[_Row],
    base_x_field: str | None,
    axis_x: ResolvedAxisStyle,
    base_x_authored_temporal: bool,
    datasets: dict[str | None, list[_Row]] | None,
    base_query_name: str | None,
) -> list[Any] | None:
    """Sorted distinct x values across the base series and every overlay layer.

    Vega-Lite unions the sub-layer domains of a shared x scale, so an overlay
    running past the base (a forward goal ramp against actuals, say) grows the
    band scale beyond the base's own rows. The axis tick values and the label
    overlap measurement must both be derived from THAT domain — deriving
    either from the base's rows alone leaves the extra bands unlabelled and
    measures crowding against a band count that isn't the one being rendered.

    A layer contributes only when its column speaks the base's own vocabulary
    — same field name AND same value shape. Sharing a field *name* is not
    enough: a layer's own query can return a column of the same name holding
    something else entirely (plain labels against monthly bars, integers
    against string SKUs). Merging those would corrupt the tick ladder, and
    would also fail outright — mixed types are unsortable, and plain labels
    make calendar-grain detection raise against a remedy pointing at the axis
    style rather than at the layer's query. Those layers keep exactly their
    pre-existing treatment: ``_reconcile_x_domain``'s categorical union still
    puts their categories on the shared scale, and the base's own rows still
    govern the calendar ticks.

    Returns None when no x values exist, matching ``ordinal_axis_values``.
    """
    if base_x_field is None:
        return None
    # Runs for every layered chart — including ones whose x never resolves to
    # a bucketed calendar grain, where nothing read these values before. So
    # adding a layer to a working chart must never be what breaks it.
    base_values = _orderable_axis_values(data, base_x_field)
    if base_values is None:
        return None
    # Keyed by the band each value denotes, not by its spelling. A layer whose
    # own query returns datetimes isoformats to "2023-01-01T00:00:00+00:00"
    # where the base spells the same band "2023-01-01" — one band, two strings.
    # Counting both measures a scale wider than the one rendering, which
    # rotates labels that fit flat. The base is inserted first so its spelling
    # wins wherever the two disagree.
    by_band: dict[Any, Any] = {}
    for value in base_values:
        by_band.setdefault(_band_identity(value), value)
    for layer in layers:
        if layer.y is None:
            continue
        x_field, own_data = _resolve_layer_rows(
            layer,
            base_x_field,
            axis_x,
            base_x_authored_temporal,
            datasets,
            base_query_name,
        )
        if own_data is None or x_field != base_x_field:
            continue
        layer_values = _orderable_axis_values(own_data, base_x_field)
        if layer_values is not None and _same_x_vocabulary(base_values, layer_values):
            for value in layer_values:
                by_band.setdefault(_band_identity(value), value)
    return sorted(by_band.values())


def _build_layer_label_specs(
    layer: ResolvedLayer,
    y_field: str,
    background: str,
    rows: list[_Row],
    band: BandLabelAnchor | None,
) -> list[ChartSpec]:
    """Build this overlay layer's OWN value-label text layers, or [] when unset.

    Mirrors ``ValueLabelFeature``'s per-family dispatch but reads the layer's
    OWN mark style (``layer.bar_mark.labels`` / ``layer.line_mark.labels`` /
    ``layer.point_mark.labels``) instead of the base chart's — each typed
    overlay layer carries its own full resolved mark style, so its labels are
    independent of the base chart's. Callers stamp ``.data`` onto the returned
    specs when the layer authored its own ``query:`` (own_data is not None).

    ``band`` is this layer's own band verdict (its ``curve`` already applied
    the band transform above), non-None only for a line/area layer drawing a
    full-band-width plateau. It can split a horizontal position into two
    layers — see ``build_line_text_layers``.
    """
    if isinstance(layer, ResolvedBarLayer):
        bar_labels = layer.bar_mark.labels
        if bar_labels.visible is not True:
            return []
        text_layer = _build_bar_text_layer(
            bar_labels,
            y_field,
            is_horizontal=False,
            is_stacked=False,
            background=background,
            is_house=layer.label_is_house,
            label_is_text=labels_draw_text(bar_labels, rows),
            # An overlay bar layer never stacks (is_stacked=False above), so
            # the segment-midpoint path these feed is unreachable from here.
            category_field=None,
            stack_offset=None,
            stack_sort=None,
        )
    elif isinstance(layer, ResolvedLineLayer):
        # marks.point.labels is an alias for marks.line.labels — same fallback
        # ValueLabelFeature._apply_line uses for the base chart.
        line_labels = layer.line_mark.labels
        point_labels = (
            line_labels if line_labels.visible is True else layer.point_mark.labels
        )
        if point_labels.visible is not True:
            return []
        return [
            text_layer_spec(built)
            for built in build_line_text_layers(
                point_labels,
                y_field,
                layer.label_is_house,
                labels_draw_text(point_labels, rows),
                band,
            )
        ]
    elif isinstance(layer, ResolvedAreaLayer):
        area_line_labels = layer.line_mark.labels
        if area_line_labels.visible is not True:
            return []
        return [
            text_layer_spec(built)
            for built in build_line_text_layers(
                area_line_labels,
                y_field,
                layer.label_is_house,
                labels_draw_text(area_line_labels, rows),
                band,
            )
        ]
    else:  # ResolvedScatterLayer
        point_labels = layer.point_mark.labels
        if point_labels.visible is not True:
            return []
        text_layer = _build_point_text_layer(
            point_labels,
            y_field,
            is_house=layer.label_is_house,
            label_is_text=labels_draw_text(point_labels, rows),
        )

    return [text_layer_spec(text_layer)]


def _resolved_layer_y_orients(layers: tuple[ResolvedLayer, ...]) -> list[str] | None:
    """Per-layer resolved y-axis orient for typed overlay layers.

    A layer pins its side via ``axis_y.position``.  Returns ``None`` when no
    layer pins a side.
    """
    positions = [layer.axis_y.position for layer in layers]
    pinned = {p for p in positions if p in ("left", "right")}
    if not pinned:
        return None
    fill: str = (
        "left" if pinned == {"right"} else "right" if pinned == {"left"} else "left"
    )
    return [(p if p in ("left", "right") else fill) for p in positions]


def _mixed_mark_legend_symbols(
    vl_layers: list[ChartSpec],
    stroke_datums: set[str],
    circle_datums: set[str],
    square_datums: set[str],
    area_opacity: float,
    base_symbol: str,
) -> None:
    """Patch symbolType/Size/StrokeWidth/Opacity exprs for mixed-mark legends.

    Gives each legend entry the glyph of its source mark — stroke for line,
    circle for area, square for bar.  Base-chart entries fall through to
    ``base_symbol`` (the glyph matching the base mark type: 'square' for bar,
    'stroke' for line, 'circle' for area/scatter).  Only patches layers whose
    color encoding already carries a non-None legend dict.
    """

    def _pred(datums: set[str]) -> str:
        return f"indexof({_json.dumps(sorted(datums))}, toString(datum.value)) >= 0"

    # Build type expression as a chain of ternaries; base_symbol is the fallback.
    type_expr = f"'{base_symbol}'"
    if square_datums:
        type_expr = f"{_pred(square_datums)} ? 'square' : {type_expr}"
    if circle_datums:
        type_expr = f"{_pred(circle_datums)} ? 'circle' : {type_expr}"
    if stroke_datums:
        type_expr = f"{_pred(stroke_datums)} ? 'stroke' : {type_expr}"

    symbol_props: dict[str, Any] = {"symbolType": {"expr": type_expr}}
    if stroke_datums:
        line_pred = _pred(stroke_datums)
        symbol_props["symbolStrokeWidth"] = {"expr": f"{line_pred} ? 2 : 1.5"}
        symbol_props["symbolSize"] = {"expr": f"{line_pred} ? 400 : 100"}
    if circle_datums:
        area_pred = _pred(circle_datums)
        symbol_props["symbolOpacity"] = {
            "expr": f"{area_pred} ? {_json.dumps(area_opacity)} : 1"
        }

    for layer in vl_layers:
        color_enc = layer.encoding.get("color")
        if isinstance(color_enc, dict) and isinstance(color_enc.get("legend"), dict):
            color_enc["legend"].update(symbol_props)


def _layer_series_color(layer: ResolvedLayer) -> str | None:
    """Authored constant series color for a layer, or None to use a palette slot.

    Only line (stroke color) and scatter (point color) carry an authored series
    color; area/bar fill always comes from the palette.
    """
    if isinstance(layer, ResolvedLineLayer):
        return layer.line_mark.stroke.color
    if isinstance(layer, ResolvedScatterLayer):
        return layer.point_mark.color
    return None


def _layer_tooltip_description(
    x_enc: VLDict, rows: list[_Row], y_field: str, label: str, tooltip_format: str
) -> str:
    """Build this overlay layer's own structured-tooltip description expr.

    A combo overlay layer joins the SAME x-unified
    bubble ``chart_interactivity.js``'s ``collectMatchingMarks`` already
    builds for the base chart's own marks (stacked segments, etc.) — no JS
    change needed, only role-marked ``description`` content on this layer's
    own mark(s), mirroring what the base already gets from
    ``StructuredTooltipFeature``.

    Header: the layer's own x field (its own authored ``x``, or the base
    chart's x encoding when unset — resolved by the caller), using the SAME
    friendly-date detection the base's own header uses
    (``header_tooltip_field``) — the rendered string must match the base's
    header EXACTLY, since the JS groups marks by header-string equality.
    Absent entirely when the base has no x at all (every x-encoding builder
    in this module always pairs "field" with "type", so a bare `"field" in
    x_enc` check is sufficient to know both keys are present) -- the header's
    own ``title`` is never rendered (bare-value header rows drop the field
    label), so an absent x carries no title to look up either.

    Series: the layer's own label (``literal=True`` — a Python-side label
    cascade result, not a query column) as a bare, swatched identity row. This
    is what makes the overlay row's own (header, series) dedup key DISTINCT
    from the base's own mark(s) — without it, a single-series base (no series
    row of its own) and this overlay would collide on the same dedup key and
    ``collectMatchingMarks`` would silently drop one of them.

    No total: an overlay reference (a different unit/series than the base's
    own commensurable parts) is never folded into the base's own group-total
    — that footer is built solely from the base's own
    ``StructuredTooltipFeature`` role computation.
    """
    header: tuple[TooltipField, ...] = ()
    if "field" in x_enc:
        header = (header_tooltip_field(x_enc["field"], "", rows),)
    series = (TooltipField(label, label, literal=True),)
    values = [TooltipField(y_field, label, kind="quantitative", format=tooltip_format)]
    return build_structured_tooltip_expr("line", header, series, values)


def _fix_bar_band_width(spec: ChartSpec) -> None:
    """Recursively pin any bar mark's width to its categorical bandwidth.

    Undoes VL's degraded-shorthand quirk (see the ``step_band_present`` call
    site in ``render_cartesian_overlay``) for every bar mark reachable from
    ``spec`` — the base chart, an overlay layer, or a mixed-sign bar's nested
    positive/negative split — however deep the layered wrapping goes. Grouped
    bars size against their ``xOffset`` sub-band; other bars use the outer
    ``x`` band.
    """
    if spec.mark == "bar":
        width_prop = spec.mark_props.get("width")
        band_frac = width_prop.get("band") if isinstance(width_prop, dict) else None
        bandwidth_scale = "xOffset" if "xOffset" in spec.encoding else "x"
        bandwidth = f"bandwidth('{bandwidth_scale}')"
        width_expr = (
            f"{band_frac} * {bandwidth}" if band_frac is not None else bandwidth
        )
        spec.mark_props["width"] = {"expr": width_expr}
    elif spec.mark == "layered":
        for sub in spec.layers:
            _fix_bar_band_width(sub)


def _apply_layer_step_band(
    curve: str | None,
    connect: bool,
    layer_encoding: VLDict,
    base_x: Any,
    data: list[dict[str, Any]],
    chart_id: str,
) -> list[dict[str, Any]] | None:
    """Apply the band-aware step transform to an overlay line/area layer,
    mirroring the base emitters. Doubles rows to the band edges and adds
    ``xOffset`` (+ a ``detail`` channel when ``connect`` is False) to
    ``layer_encoding``; returns the doubled rows to attach as the layer's own
    data, or None when not band-aware step. When the layer authored its own
    ``x``, ``layer_encoding["x"]`` is already set to that field's own encoding
    and is left alone; otherwise it inherits the base spec's x encoding,
    copied in here — ``apply_step_band`` needs the band x-channel present to
    validate and offset against.
    """
    # Not a `.get(k, default)` config fallback (SIM401) — deliberately written
    # as an if/else so the type-state counter's silent_fallback detector
    # (scripts/type_state_counter.py), which flags exactly that call shape,
    # doesn't mistake this real either/or for one.
    x_enc = layer_encoding["x"] if "x" in layer_encoding else base_x  # noqa: SIM401
    if not isinstance(x_enc, dict):
        return None
    if not is_band_step(curve, x_enc.get("type")):
        return None
    layer_encoding["x"] = x_enc
    return apply_step_band(data, layer_encoding, chart_id=chart_id, connect=connect)


def _layer_band_anchor(
    label_x_field: str,
    union_x_field: str,
    y_field: str,
    base_x_enc: VLDict,
    base_rows: list[_Row],
    layer_rows: list[_Row],
) -> BandLabelAnchor:
    """Band geometry for one overlay layer's own value labels.

    Called only when the layer's curve actually applied the band transform.
    The domain comes from ``rendered_x_domain`` — the same union-and-sort
    ``_reconcile_x_domain`` pins below, so an authored ``sort:`` moves the
    leading/trailing band here exactly as it moves it on the rendered axis.
    Reading query order instead would fire the fallback on the wrong band and
    paint the real trailing caption outside the plot.

    Only this layer's own column joins the union. A THIRD layer contributing a
    category neither the base nor this layer draws can still widen the real
    domain, but it can only push a band this layer captions AWAY from the edge
    — never onto it — so the fallback stays conservative rather than wrong.

    The two x fields differ only when the layer authors its own ``x:``:
    ``union_x_field`` is the column whose values widen the shared domain, while
    ``label_x_field`` is the base's — the label sublayer carries no x encoding
    of its own, so the base's is the column its caption is actually positioned
    by, and therefore the one the edge filter has to test.

    Both are narrowed at the call site rather than here: absorbing the narrows
    would make three more signature members optional, which costs more against
    the type-state gate than the duplicated guard costs in lines.
    """
    return band_label_anchor(
        label_x_field,
        y_field,
        rendered_x_domain(base_x_enc, base_rows, [(union_x_field, layer_rows)]),
        layer_rows,
        rows_are_doubled=False,
    )


def render_cartesian_overlay(
    base_spec: ChartSpec,
    layers: tuple[ResolvedLayer, ...],
    data: list[dict[str, Any]],
    *,
    chart_id: str,
    axis_x: ResolvedAxisStyle,
    axis_y: ResolvedAxisStyle,
    base_y_title_suppressed: bool,
    base_x_authored_temporal: bool,
    tooltip_format: str,
    background: str,
    single_series_fill: str,
    legend: ResolvedLegendStyle,
    config: VLDict,
    layered_rail_may_fire: bool,
    base_mark_type: str = "bar",
    base_label: str | None = None,
    datasets: dict[str | None, list[dict[str, Any]]] | None = None,
    base_query_name: str | None,
) -> ChartSpec:
    """Wrap ``base_spec`` + typed overlay layers into an outer layered VL spec.

    Called from each family emitter when ``chart.layers`` is non-empty.
    Paint order contract: base first (bottom), layers in authored order on top.
    Dual-axis, mixed-mark legend symbols, and per-layer y encodings are applied.
    The ``config`` (palette) is moved to the outer spec so it is not duplicated.
    ``datasets`` maps query_name → rows for layers that authored their own
    ``query:`` (overriding the base chart's query). ``base_query_name`` is
    the base chart's own resolved query name (``chart.query_name``) — every
    layer's resolved ``query_name`` defaults to it when unauthored
    (``compile/resolve/_layers.py``), so ``layer.query_name is not None`` is
    true for nearly every layer and cannot distinguish "reads its own rows"
    from "shares the base's". A layer's rows genuinely diverge from the
    base's only when ``layer.query_name != base_query_name`` — that layer
    then reads from ``datasets``; every other layer shares the base's own
    ``data`` (already gap-filled/bucket-normalized by the family emitter),
    never the raw ``datasets`` lookup, which predates that normalization.
    ``axis_x`` is the BASE chart's x axis style, passed through to
    ``canonicalize_cartesian_x_data`` so a layer that genuinely overrides
    the query (``own_data``) canonicalizes its x rows the same way the base
    did — both land on one shared x scale, so leaving ``own_data`` on a
    different JS-``Date``-parseable string form than the base (e.g. a naive
    "2024-01-01 00:00:00" next to the base's date-only "2024-01-01") paints
    the overlay a bucket off the base under any non-UTC timezone. The base's
    own verdict is threaded, not re-derived: ``base_x_authored_temporal`` is
    the caller's own ``resolve_authored_x_type(axis_x) == "temporal"`` check
    for the families whose base path actually honors that escape hatch
    (bar/line/area's ``gap_fill_ordinal_time``, gated in ``_channels.py``) —
    scatter's own base canonicalizes unconditionally regardless of authored
    type, so a scatter caller always passes ``False``. Re-deriving this
    check locally, against the wrong family's gate, produced the exact
    string-form split this parameter closes: recomputing "should this axis
    canonicalize" from ``axis_x`` alone (ignoring which family's base path
    actually consulted it) fired canonicalization on an authored-temporal
    bar/line/area axis whose own base path had just skipped it. A layer
    sharing the base's OWN x field additionally gets the base's authored
    ``time_unit``; a layer authoring a genuinely different ``x`` gets
    ``None`` (auto-detects its own grain) — the base's authored grain was
    chosen for the base's field, not an unrelated column, and forcing it
    onto one silently collapses that column's own bucketing (see the
    ``own_data`` call site below).
    ``layered_rail_may_fire`` is the caller's own
    ``dbt_charts.core.utils.layered_endpoint_rail_fires(...) and
    chart.style.endpoint_labels.visible`` (further ANDed with "not
    horizontal" on bar) — required, not defaulted, so a caller that forgets
    to compute it fails loudly rather than silently reverting to the widest
    (or narrowest) collision check.
    ``base_y_title_suppressed`` says the author explicitly suppressed the
    title of whichever axis the BASE chart draws on VL ``y`` — required, not
    defaulted, for the same reason. Only the dual-axis title restore below
    reads it, and only to split two cases the resolved axis alone cannot tell
    apart: an axis with no label is suppressed by the theme's blanket
    default, and dual-axis overrides that (both sides need labelling to tell
    the scales apart), whereas a labelled axis can only be suppressed by the
    author saying so — the Layer 5 default would otherwise have forced it
    visible — so that one is honored and left alone.

    The caller computes it, rather than this function deriving it from
    ``axis_y``, because which axis lands on VL ``y`` is the caller's business:
    a horizontal bar puts its *category* axis there (governed by ``axis_x`` /
    ``x_label``), while ``axis_y`` here is always the layers' measure axis.
    Reading ``axis_y`` for this would delete a horizontal bar's category-axis
    title whenever its measure-axis title was suppressed.
    """
    # Deliberately no compose_axis_label_expr here: axis_y is the BASE
    # chart's measure axis, and its ruler (if any) was baked for the base's
    # own tick ladder. In the shared-scale case the base's axis dict already
    # carries that labelExpr (vl_layers[0]), so this dict doesn't need its
    # own copy; in the dual-axis case a layer's y-axis is a different scale
    # entirely, and applying the base's ruler to it would paint the wrong
    # magnitude. Every emitter's OWN measure axis still routes through
    # compose_axis_label_expr (see bar.py's comment on the same convention);
    # this is the one call site that must not.
    ay_vl = axis_to_vl(axis_y)
    _ay_font = axis_y.title.font

    # #12: chart-level tick count → tickCount hint on all overlay layer axes.
    # (Base chart's axis is built by build_cartesian_y_encoding using tick_values.)
    if axis_y.ticks.count is not None:
        ay_vl["tickCount"] = axis_y.ticks.count

    # Dual-axis placement. When any overlay pins a side, the base occupies the
    # OPPOSITE side. The base emitter used the theme-default orient (which may be
    # "right"), so we must re-pin the base to the free side here — otherwise a
    # right-pinned overlay collides with a right-defaulting base. Independent y
    # scales are needed whenever base and overlays don't all share one side.
    layer_orients = _resolved_layer_y_orients(layers)
    independent_y = False
    if layer_orients is not None:
        pinned = set(layer_orients)
        base_side = (
            "left" if pinned == {"right"} else "right" if pinned == {"left"} else "left"
        )
        independent_y = len({base_side} | pinned) > 1
        base_y = base_spec.encoding.get("y") if base_spec.encoding else None
        if isinstance(base_y, dict) and isinstance(base_y.get("axis"), dict):
            prior_orient = base_y["axis"].get("orient")
            base_y["axis"]["orient"] = base_side
            if prior_orient != base_side:
                # Strip labelAlign and labelPadding only when the base axis
                # actually moves to a different edge: a house-format alias may
                # have forced labelAlign="right" and computed a right-side
                # labelPadding — those values are wrong on the opposite side.
                # When the base stays on the same edge (e.g. a left-pinned
                # overlay leaves a right-default base on the right), they
                # remain valid and must not be stripped.
                base_y["axis"].pop("labelAlign", None)
                base_y["axis"].pop("labelPadding", None)
            # Single bar/line charts suppress the y-axis title (axis.title=null);
            # a dual-axis chart needs both sides labelled to tell the scales
            # apart, so restore the base title from its encoding title —
            # unless the author explicitly suppressed the title of the
            # axis that actually lands here (see base_y_title_suppressed
            # above), which must not be overwritten.
            if (
                base_y["axis"].get("title") is None
                and base_y.get("title")
                and not base_y_title_suppressed
            ):
                base_y["axis"]["title"] = base_y["title"]

    # Move config from base to outer (avoids duplication in nested VL specs).
    outer_config = config or dict(base_spec.config)
    base_spec.config = {}

    # Extract the shared x encoding from the base for the outer spec.
    x_enc = base_spec.encoding.get("x") if base_spec.encoding else None
    outer_encoding: dict[str, Any] = {}
    if x_enc is not None:
        outer_encoding["x"] = x_enc

    # If the base carries a stack-ordering encoding (stacked-bar nominal series),
    # hoist it and its calculate transform to the outer spec so bar and text-label
    # sublayers inherit one shared stack ordering. Without this the text sublayer
    # computes its own independent stack and mismatches labels with segments.
    # Overlay line/area layers explicitly opt out via order=None below (on a line,
    # 'order' controls point-connection order, not z-order).
    outer_transforms: list[dict[str, Any]] = []
    order_hoisted = False
    order_enc = base_spec.encoding.pop("order", None)
    if order_enc is not None:
        outer_encoding["order"] = order_enc
        order_field = order_enc["field"]  # always a str; KeyError signals a bug
        if base_spec.mark == "layered":
            # Mixed-sign split (_layers.py): order is on the outer encoding but the
            # calculate lives inside each sign-filtered sub-layer. Hoist from the
            # first sub-layer (all carry identical copies) and clear from every sub.
            moved = [
                t for t in base_spec.layers[0].transforms if t.get("as") == order_field
            ]
            if not moved:
                raise ChartDataError(
                    f"bar spec carries order encoding for field {order_field!r} "
                    "but no matching calculate transform found in sign-split sub-layers"
                )
            outer_transforms.extend(moved)
            for sub in base_spec.layers:
                sub.transforms = [
                    t for t in sub.transforms if t.get("as") != order_field
                ]
        else:
            moved = [t for t in base_spec.transforms if t.get("as") == order_field]
            if not moved:
                raise ChartDataError(
                    f"bar spec carries order encoding for field {order_field!r} "
                    "but no matching calculate transform was found"
                )
            outer_transforms.extend(moved)
            base_spec.transforms = [
                t for t in base_spec.transforms if t.get("as") != order_field
            ]
        # The outer spec carries the same rows (data= on the ChartSpec returned
        # below). Clear base_spec.data so the bar sublayer inherits outer
        # transforms; a sublayer with its own .data skips the outer transform
        # cascade (gap_fill stamps .data on the bar before this function is called).
        base_spec.data = None
        order_hoisted = True

    vl_layers: list[ChartSpec] = [base_spec]

    # One shared color scale drives BOTH the painted series and the legend
    # swatches, so an authored per-layer color and its legend entry can never
    # diverge, and the base series always gets a legend entry. Slot 0 is the
    # single-series base (painted with its own fill), or the base field's existing
    # domain/range; each layer contributes its authored color, else the next
    # unclaimed palette slot.
    # Overlays assume a vertical base (measure on y, shared with the layers). Only
    # then is the base's y title its series name; on a horizontal base y is the
    # category, so we leave that case on the pre-shared-scale path.
    palette: list[str] = list((outer_config.get("range") or {}).get("category") or [])
    y_enc_base = base_spec.encoding.get("y", {}) if base_spec.encoding else {}
    base_color_enc = base_spec.encoding.get("color") if base_spec.encoding else None
    field_color_base = (
        isinstance(base_color_enc, dict)
        and isinstance(base_color_enc.get("field"), str)
        and base_color_enc.get("type") in ("nominal", "ordinal")
    )
    use_shared_scale = (
        bool(base_spec.encoding)
        and ("color" not in base_spec.encoding or field_color_base)
        and y_enc_base.get("type") == "quantitative"
    )
    # The caller supplies the base series' legend label as plain text. Reading
    # it off ``y_enc_base["title"]`` would pick up the display title, which is
    # a ``list[str]`` once wrapped — not a value VL accepts in ``color.datum``
    # or a scale domain.
    base_label = base_label if use_shared_scale and not field_color_base else None
    scale_domain: list[str] = []
    scale_range: list[str] = []
    shared_scale: VLDict = {"domain": scale_domain, "range": scale_range}
    if field_color_base:
        assert isinstance(base_color_enc, dict)
        color_field = base_color_enc["field"]
        assert isinstance(color_field, str)
        base_series = distinct_series_values(data, color_field)
        existing_scale = base_color_enc.get("scale")
        existing_domain = (
            existing_scale.get("domain") if isinstance(existing_scale, dict) else None
        )
        existing_range = (
            existing_scale.get("range") if isinstance(existing_scale, dict) else None
        )
        scale_domain.extend(
            existing_domain if isinstance(existing_domain, list) else base_series
        )
        if isinstance(existing_range, list):
            scale_range.extend(existing_range)
        elif scale_domain:
            if not palette:
                raise ChartDataError(
                    "layered chart has no color palette", chart_id=chart_id
                )
            scale_range.extend(
                spatial_color_scale(base_series, tuple(palette), scale_domain)["range"]
            )
        base_color_enc["scale"] = shared_scale
    elif base_label is not None:
        scale_domain.append(base_label)
        scale_range.append(single_series_fill)

    stroke_datums: set[str] = set()  # line overlays
    circle_datums: set[str] = set()  # area overlays
    square_datums: set[str] = set()  # bar overlays
    field_color_legend_symbols: list[tuple[ChartSpec, str]] = []
    independent_color_scale = False
    last_area_opacity: float = 1.0
    # Resolved once, up front, so every layer's own x is validated/typed
    # against the base BEFORE that layer's encoding is built (not classified
    # standalone and repaired after the loop) — see _resolve_layer_x_encoding.
    base_x_enc: VLDict = x_enc if isinstance(x_enc, dict) else {}
    base_x_field = base_x_enc.get("field")
    # A full pass over base_data to check date-shapedness is only ever
    # consulted when a layer authors its own x (_resolve_layer_x_encoding's
    # temporal-vs-date-shaped-base branch) -- skip it for the common case of
    # an overlay chart where no layer does.
    any_layer_has_own_x = any(layer.x is not None for layer in layers)
    base_domain_is_date_shaped = (
        any_layer_has_own_x
        and isinstance(base_x_field, str)
        and _base_domain_is_date_shaped(data, base_x_field)
    )
    # Every layer that authors its own x, paired with the rows it resolves
    # against — fed to the union-domain reconciliation after the loop.
    layer_x_columns: list[tuple[str, list[_Row]]] = []
    # True when any layer's label sublayer carries a calculate transform (house
    # register OR a position transform like middle/middle_aligned/bottom) — any
    # of these forks the sublayer's dataflow, so it has no x encoding of its
    # own and VL's native sort-by-field breaks across the shared scale.
    # Used to force x-domain pinning so VL preserves the base's query sort order.
    any_label_transform = False
    # Any sibling in the outer `layer:` array added an xOffset scale — this
    # base spec's own curve counts too (a base area/line applying step-band to
    # itself puts xOffset on base_spec.encoding, and a bar OVERLAY layer is
    # then the sibling whose band-width shorthand degrades).
    step_band_present = "xOffset" in base_spec.encoding

    for layer_idx, layer in enumerate(layers):
        y_field = layer.y
        if y_field is None:
            # No y field on this layer — skip.
            continue

        label: str = layer.label or format_display_text(
            y_field, from_slug=True, font=_ay_font
        )

        layer_diverges = layer.query_name != base_query_name
        effective_x_field, own_data = _resolve_layer_rows(
            layer,
            base_x_field,
            axis_x,
            base_x_authored_temporal,
            datasets,
            base_query_name,
        )
        rows_for_layer = own_data if own_data is not None else data

        # The layer's own x encoding when authored, else the base's (or {}
        # when the base has no x at all) — tooltip must reflect whichever x
        # field the layer actually renders against. An authored layer.x is
        # resolved against the base's type NOW (construction time), so every
        # downstream consumer in this loop (step-band curve detection below,
        # tooltips) sees the final type, never a standalone classification
        # that gets patched after the fact.
        layer_x_enc: VLDict = (
            _resolve_layer_x_encoding(
                layer.x,
                rows_for_layer,
                base_x_enc,
                base_domain_is_date_shaped,
                chart_id,
            )
            if layer.x is not None
            else base_x_enc
        )
        # Per-layer y axis: dual-axis layers get their own orient + title.
        layer_axis_y = layer.axis_y
        if layer_orients is not None:
            # Drop labelAlign from the dual-axis layer template: ay_vl was built
            # from the base axis whose forced labelAlign (e.g. from a house-format
            # alias) is valid only for the base's own edge.  A layer re-oriented to
            # the opposite edge would inherit an invading labelAlign otherwise.
            layer_ay_vl: dict[str, Any] = {
                k: v for k, v in ay_vl.items() if k != "labelAlign"
            }
            layer_ay_vl["orient"] = layer_orients[layer_idx]
            axis_title = layer_axis_y.title or label
            layer_ay_vl["title"] = axis_title
        else:
            # Shared scale: the layer stays on the base's own edge, so the
            # base's OWN already-emitted axis dict (built by the family
            # emitter via measure_axis_to_vl) is the correct template --
            # unlike the bare `ay_vl` above (axis_to_vl only), it already
            # went through measure_axis_to_vl's own-side-invasion safety net
            # (drops labelAlign when the axis can't be safely measured --
            # an authored labelExpr, upper/lower font.case -- else keeps it
            # with a real measured labelPadding). A layer axis seeded from
            # the unsafe `ay_vl` instead can inherit an own-side labelAlign
            # (e.g. from a house-format alias's force-right) with only the
            # theme's flat labels.padding reserved, right-anchoring the
            # layer's own tick labels with no gutter -- the mark then draws
            # over them.
            base_y_enc = base_spec.encoding.get("y") if base_spec.encoding else None
            base_y_axis = (
                base_y_enc.get("axis") if isinstance(base_y_enc, dict) else None
            )
            layer_ay_vl = (
                dict(base_y_axis) if isinstance(base_y_axis, dict) else dict(ay_vl)
            )
            if "tickCount" in ay_vl:
                layer_ay_vl["tickCount"] = ay_vl["tickCount"]

        # #11: apply per-layer axis_y chrome overrides.
        if layer_axis_y.ticks is not None and layer_axis_y.ticks.count is not None:
            layer_ay_vl["tickCount"] = layer_axis_y.ticks.count
        if layer_axis_y.grid is not None and layer_axis_y.grid.visible is not None:
            layer_ay_vl["grid"] = layer_axis_y.grid.visible
        # The layer's own authored number format (e.g. a percent d3-format on a
        # conversion-rate overlay), else the base chart's tooltip_format — used
        # for the VALUE (tooltip row + encoding.y.format), not the axis ticks
        # (layer_ay_vl["format"] below stays conditional: an un-authored axis
        # keeps VL's own default tick format, unrelated to the base's unit).
        layer_value_format = (
            layer_axis_y.label.format
            if layer_axis_y.label is not None and layer_axis_y.label.format is not None
            else tooltip_format
        )
        if layer_axis_y.label is not None and layer_axis_y.label.format is not None:
            layer_ay_vl["format"] = layer_axis_y.label.format

        # #11: per-layer scale.domain sets the VL y encoding scale.
        layer_y_scale: VLDict | None = None
        if layer_axis_y.scale is not None and layer_axis_y.scale.domain is not None:
            layer_y_scale = {"domain": list(layer_axis_y.scale.domain)}

        # "" (not a real description -- same empty-string-means-unset
        # convention as TooltipField.format) when the base family doesn't
        # support structured tooltips; every assignment site below only
        # stamps `.tooltip_description` when this is truthy.
        layer_tooltip_description = (
            _layer_tooltip_description(
                layer_x_enc, rows_for_layer, y_field, label, layer_value_format
            )
            if base_mark_type in _STRUCTURED_TOOLTIP_BASE_FAMILIES
            else ""
        )

        y_enc: VLDict = {
            "field": y_field,
            "type": "quantitative",
            "title": label,
            "axis": layer_ay_vl,
            "format": layer_value_format,
        }
        if layer_y_scale is not None:
            y_enc["scale"] = layer_y_scale
        layer_color_field = layer.color
        if layer_color_field is None:
            layer_color_type: str | None = None
            color_enc: VLDict = {"datum": label}
        else:
            layer_color_type = infer_vega_type_from_data(
                rows_for_layer, layer_color_field
            )
            color_enc = {"field": layer_color_field, "type": layer_color_type}
        has_color_encoding = layer_color_field is not None
        if (
            has_color_encoding
            and layer_color_type not in ("nominal", "ordinal")
            and use_shared_scale
        ):
            independent_color_scale = True
        apply_color_legend(color_enc, legend)
        # The series' color: authored constant if present, else the next palette
        # slot. It paints the mark (as the emitter's single-series color) AND is
        # the legend swatch (shared-scale range) — one value, so they can't
        # diverge.
        layer_color_values: list[str] = []
        layer_series_fill: str
        if layer_color_field is not None and layer_color_type in ("nominal", "ordinal"):
            layer_color_values = distinct_series_values(
                rows_for_layer, layer_color_field
            )
            if use_shared_scale:
                if not palette:
                    raise ChartDataError(
                        "layered chart has no color palette", chart_id=chart_id
                    )
                for value in layer_color_values:
                    if value in scale_domain:
                        continue
                    scale_domain.append(value)
                    scale_range.append(palette[len(scale_range) % len(palette)])
                color_enc["scale"] = shared_scale
            layer_series_fill = single_series_fill
        elif use_shared_scale:
            # Collision only matters where it's load-bearing: the layered
            # endpoint-label rail's anchors dict (_apply_layered_single_series)
            # is keyed by label, so two entries sharing one silently collapse
            # to a single anchor. field_color_base's own painted domain/range
            # has the same silent-collapse risk independent of the rail. An
            # ordinary layered chart with no rail (endpoint_labels off, or a
            # non-firing shape) authoring the same label as its base y title
            # or another layer is unremarkable — VL just reuses that color
            # scale slot — so it must not raise.
            if (field_color_base or layered_rail_may_fire) and label in scale_domain:
                raise ChartDataError(
                    f"layer label {label!r} collides with an existing color "
                    "scale entry. To fix: give this layer (or the colliding "
                    "series) a distinct label:.",
                    chart_id=chart_id,
                )
            authored_fill = _layer_series_color(layer)
            if authored_fill is None:
                layer_ord = len(
                    scale_domain
                )  # slots already taken by base + prior layers
                if field_color_base and layer_ord >= len(palette):
                    raise ChartDataError(
                        f"layer {label!r} has no available color palette slot",
                        chart_id=chart_id,
                    )
                authored_fill = (
                    palette[layer_ord]
                    if field_color_base
                    else (
                        palette[layer_ord % len(palette)]
                        if palette
                        else single_series_fill
                    )
                )
            layer_series_fill = authored_fill
            scale_domain.append(label)
            scale_range.append(layer_series_fill)
            color_enc["scale"] = shared_scale
        else:
            layer_series_fill = single_series_fill
        layer_encoding: VLDict = {"y": y_enc, "color": color_enc}
        # Overlay layers must not inherit the outer stacked-bar ordering: on
        # line/trail/area 'order' controls point-connection order, not z-order,
        # so inheriting __df_series_order disconnects line segments.
        if order_hoisted:
            layer_encoding["order"] = None
        # A layer authoring its own `x` gets its own x encoding (field +
        # inferred VL type from its own rows) instead of silently inheriting
        # the base chart's x channel. Unset (the common case) leaves "x"
        # absent here, so the sub-layer keeps inheriting the base's x
        # encoding verbatim, unchanged from prior behavior.
        if layer.x is not None:
            layer_encoding["x"] = layer_x_enc
        # Feed the union-domain reconciliation whenever this layer's rows
        # can genuinely differ from the base's — an authored own `x` field,
        # or a genuinely diverging own `query:` sharing the base's x field
        # name (effective_x_field). A non-diverging, x-unauthored layer
        # shares the base's own rows exactly, so it contributes nothing new
        # to the union and is correctly left out.
        if (layer.x is not None or layer_diverges) and effective_x_field is not None:
            layer_x_columns.append((effective_x_field, rows_for_layer))

        # Non-None only for a line/area layer whose curve actually applied the
        # band transform below — the layer's own labels then resolve against
        # the band it draws, not against the datum at its center.
        layer_band: BandLabelAnchor | None = None

        if isinstance(layer, ResolvedLineLayer):
            step_data = _apply_layer_step_band(
                layer.line_mark.curve,
                layer.line_mark.connect is not False,
                layer_encoding,
                base_spec.encoding.get("x"),
                rows_for_layer,
                chart_id,
            )
            if (
                step_data is not None
                and isinstance(base_x_field, str)
                and isinstance(effective_x_field, str)
            ):
                layer_band = _layer_band_anchor(
                    base_x_field,
                    effective_x_field,
                    y_field,
                    base_x_enc,
                    data,
                    rows_for_layer,
                )
            sub_layers = emit_line_layer(
                line_mark=layer.line_mark,
                point_mark=layer.point_mark,
                halo_color=background,
                single_series_color=layer_series_fill,
                has_color_encoding=has_color_encoding,
                tooltip=[],
                suppress_halo=True,
                band_step=step_data is not None,
                pin_child_colors=True,
                inherit_parent_color=use_shared_scale,
                series_encoding=color_enc if has_color_encoding else {},
            )
            wrapper = ChartSpec(
                mark="layered", encoding=layer_encoding, layers=sub_layers
            )
            if layer_tooltip_description:
                wrapper.tooltip_description = layer_tooltip_description
            if step_data is not None:
                wrapper.data = step_data
                step_band_present = True
            elif own_data is not None:
                wrapper.data = own_data
            vl_layers.append(wrapper)
            if layer_color_values:
                stroke_datums.update(layer_color_values)
            else:
                stroke_datums.add(label)
            if has_color_encoding and not layer_color_values:
                field_color_legend_symbols.append((wrapper, "stroke"))

        elif isinstance(layer, ResolvedAreaLayer):
            # Area always renders as a continuous silhouette — connect=True.
            step_data = _apply_layer_step_band(
                layer.area_mark.curve,
                True,
                layer_encoding,
                base_spec.encoding.get("x"),
                rows_for_layer,
                chart_id,
            )
            if (
                step_data is not None
                and isinstance(base_x_field, str)
                and isinstance(effective_x_field, str)
            ):
                layer_band = _layer_band_anchor(
                    base_x_field,
                    effective_x_field,
                    y_field,
                    base_x_enc,
                    data,
                    rows_for_layer,
                )
            sub_layers = emit_area_layer(
                area_mark=layer.area_mark,
                line_mark=layer.line_mark,
                point_mark=layer.point_mark,
                background=background,
                single_series_fill=layer_series_fill,
                has_color_encoding=has_color_encoding,
                tooltip=[],
                is_stacked=False,
                # Overlay layers never stack (is_stacked=False below), so they
                # want no sparse-band transforms.
                band_transforms=[],
                suppress_halo=True,
                band_step=step_data is not None,
                pin_child_colors=True,
                inherit_parent_color=use_shared_scale,
                series_encoding=color_enc if has_color_encoding else {},
            )
            last_area_opacity = layer.area_mark.opacity
            wrapper = ChartSpec(
                mark="layered", encoding=layer_encoding, layers=sub_layers
            )
            if layer_tooltip_description:
                wrapper.tooltip_description = layer_tooltip_description
            if step_data is not None:
                wrapper.data = step_data
                step_band_present = True
            elif own_data is not None:
                wrapper.data = own_data
            vl_layers.append(wrapper)
            if layer_color_values:
                circle_datums.update(layer_color_values)
            else:
                circle_datums.add(label)
            if has_color_encoding and not layer_color_values:
                field_color_legend_symbols.append((wrapper, "circle"))

        elif isinstance(layer, ResolvedBarLayer):
            bar_spec = emit_bar_layer(
                bar_mark=layer.bar_mark,
                orientation="vertical",
                has_color_encoding=has_color_encoding,
                single_series_color=layer_series_fill,
                radius=bar_mark_radius(layer.bar_mark),
                encoding=layer_encoding,
                data=rows_for_layer,
                measure_field=y_field,
                config={},
                transforms=[],
            )
            if layer_tooltip_description:
                bar_spec.tooltip_description = layer_tooltip_description
            if own_data is not None:
                bar_spec.data = own_data
            vl_layers.append(bar_spec)
            if layer_color_values:
                square_datums.update(layer_color_values)
            else:
                square_datums.add(label)
            if has_color_encoding and not layer_color_values:
                field_color_legend_symbols.append((bar_spec, "square"))

        else:  # ResolvedScatterLayer
            mark_props = emit_scatter_layer(
                point_mark=layer.point_mark,
                has_color_encoding=has_color_encoding,
                single_series_fill=layer_series_fill,
            )
            scatter_spec = ChartSpec(
                mark="point", mark_props=mark_props, encoding=layer_encoding
            )
            if layer_tooltip_description:
                scatter_spec.tooltip_description = layer_tooltip_description
            if own_data is not None:
                scatter_spec.data = own_data
            vl_layers.append(scatter_spec)
            circle_datums.update(layer_color_values)
            if has_color_encoding and not layer_color_values:
                field_color_legend_symbols.append((scatter_spec, "circle"))

        # This layer's OWN value-label text layer, from its OWN mark style —
        # independent of the base chart's labels (dispatched separately by
        # ValueLabelFeature). Reads from the layer's own dataset when it
        # genuinely diverges from the base's (own_data), else inherits the
        # outer spec's top-level data — this function's own `data=` stamp
        # below, the same already-normalized rows the base renders against —
        # same fallback contract as the wrapper specs above.
        for label_spec in _build_layer_label_specs(
            layer, y_field, background, rows_for_layer, layer_band
        ):
            if own_data is not None:
                label_spec.data = own_data
            if label_spec.transforms:
                any_label_transform = True
            vl_layers.append(label_spec)

    # A step-band curve's xOffset scale — whether on an overlay line/area
    # layer or on the base's own curve — is a sibling of any bar mark's band
    # scale inside the outer `layer:` array (a bar can be the base OR an
    # overlay layer here). Vega-Lite's mark.width `{"band": v}` shorthand
    # degrades to a static default step (not bandwidth('x')) once ANY sibling
    # layer in the same layer array carries a discrete xOffset scale — a VL
    # compiler quirk, confirmed empirically (bars render at a fixed ~18px
    # regardless of the actual band width). Pin every bar mark's width to an
    # explicit bandwidth('x') expression so it keeps tracking the real band
    # width VL would have given it without the sibling xOffset.
    if step_band_present:
        for vl_spec in vl_layers:
            _fix_bar_band_width(vl_spec)

    if isinstance(x_enc, dict):
        _reconcile_x_domain(
            x_enc,
            data,
            layer_x_columns,
            force=any_label_transform,
        )

    # Give the single-series base its own legend entry via the shared scale, so
    # a bar+line combo shows both series (not just the overlay). Its glyph is the
    # base mark's symbol (below), since base_label is in no overlay datum set.
    if base_label is not None:
        base_color: VLDict = {"datum": base_label, "scale": shared_scale}
        apply_color_legend(base_color, legend)
        base_spec.encoding["color"] = base_color
    elif field_color_base:
        assert isinstance(base_color_enc, dict)
        base_legend = base_color_enc.get("legend")
        if isinstance(base_legend, dict) and isinstance(
            base_legend.get("values"), list
        ):
            base_legend["values"] = scale_domain

    # Mark-aware legend glyphs: patch symbolType exprs when any typed overlay
    # is present and the legend is visible. Skip when the author pinned a
    # constant shape (symbol_shape) — legend_to_vl already emitted it.
    _base_symbols = {
        "bar": "square",
        "line": "stroke",
        "area": "circle",
        "scatter": "circle",
    }
    if (
        (stroke_datums or circle_datums or square_datums or base_label is not None)
        and legend.visible
        and legend.symbol_shape is None
    ):
        _mixed_mark_legend_symbols(
            vl_layers,
            stroke_datums,
            circle_datums,
            square_datums,
            last_area_opacity,
            _base_symbols.get(base_mark_type, "square"),
        )
    if legend.symbol_shape is None:
        for field_spec, symbol_type in field_color_legend_symbols:
            field_color = field_spec.encoding.get("color")
            if isinstance(field_color, dict) and isinstance(
                field_color.get("legend"), dict
            ):
                field_color["legend"]["symbolType"] = symbol_type

    resolve_scale: dict[str, Any] = {}
    if independent_y:
        resolve_scale["y"] = "independent"
    if independent_color_scale:
        resolve_scale["color"] = "independent"
    resolve = {"scale": resolve_scale} if resolve_scale else {}

    # A non-diverging layer (see layer_diverges above) carries no explicit
    # .data of its own and inherits this outer spec's — which must be the
    # SAME already gap-filled/bucket-normalized `data` the base renders
    # against, not BoardRenderSession's own later fallback (chart_rows(),
    # the raw pre-normalization query rows) that would otherwise apply once
    # this spec reaches it, since that fallback only fires when .data is
    # still None.
    return ChartSpec(
        mark="layered",
        encoding=outer_encoding,
        transforms=outer_transforms,
        layers=vl_layers,
        config=outer_config,
        resolve=resolve,
        data=normalize_data_types(data),
    )
