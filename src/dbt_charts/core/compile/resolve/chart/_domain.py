"""Y-domain baking and tick resolution shared across cartesian chart families."""

from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Any, Literal, NamedTuple

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.style.theme import (
    AxisYStyle,
    BaseScaleStyle,
    ScaleContinuousStyle,
    _CartesianChartStyle,
)
from dbt_charts.core.compile.resolve.chart._chart_rows import (
    CartesianChart,
    ChartDataset,
    ChartRows,
    LayerDatasets,
    fold_panels,
    restamp,
)
from dbt_charts.core.compile.resolve.chart.enrich import (
    classify_column_type,
    first_non_null_samples,
)
from dbt_charts.core.compile.resolve.chart.tick_values import (
    apply_headroom,
    numeric_domain_bounds,
    stacked_totals_max,
)
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_LOG_SCALE_REQUIRES_POSITIVE_DATA,
    ERR_TICKS_COUNT_REQUIRES_NON_LOG_SCALE,
)
from dbt_charts.core.numeric import nice_tick_values
from dbt_charts.core.utils import numeric_column_values

__all__ = [
    "_CartesianTickResolution",
    "_authored_axis_y_ticks_count",
    "_axis_headroom",
    "_bake_normalize_domain",
    "_bake_y_zero",
    "_bake_zero_flag",
    "_first_non_numeric_y",
    "_numeric_y_values",
    "_reject_non_positive_log_scale_data",
    "_resolve_cartesian_ticks",
    "_resolve_stacked_bar_ticks",
    "_shared_y_values",
    "_zero_anchor_floats",
    "resolve_y_zero",
]


def resolve_y_zero(
    primary: _CartesianChartStyle | None,
    min_val: float | None,
    max_val: float | None,
    chart_type: str,
) -> bool | None:
    """Canonical measure-axis zero decision for optional-zero chart families.

    An author-pinned ``axis_y.scale.zero`` bool wins; otherwise the smart-zero
    heuristic (``compile.enrich._pick_scale``) runs on the (min_val, max_val)
    extent. Returns None when neither the pin nor the heuristic has an opinion
    (no extent, or the data spans/touches zero).

    The single source of this decision — consumed by ``_bake_y_zero`` for
    filtered rows and by the family resolvers for a cross-filter stable extent.
    One canonical mapper keeps both paths aligned when anchor rules change.
    """
    if primary is not None:
        axis_y_scale = primary.axis_y.scale if primary.axis_y is not None else None
        cont = axis_y_scale.continuous if axis_y_scale is not None else None
        if cont is not None and isinstance(cont.zero, bool):
            return cont.zero

    if min_val is None or max_val is None:
        return None
    from dbt_charts.core.compile.resolve.chart.enrich import ColumnProfile, _pick_scale

    profile = ColumnProfile(min_val=min_val, max_val=max_val)
    picked = _pick_scale(profile, chart_type=chart_type)
    if not picked or "zero" not in picked:
        return None
    return bool(picked["zero"])


def _bake_zero_flag(ay: AxisYStyle, zero: bool) -> AxisYStyle:
    """Bake an explicit zero-anchor bool onto ``ay.scale.continuous.zero``.

    Callers must have already excluded a log-typed axis themselves — see
    ``_bake_y_zero``'s docstring for why baking ``zero`` onto one is invalid.
    """
    _existing_cont = ay.scale.continuous if ay.scale is not None else None
    new_cont = (
        _existing_cont.model_copy(update={"zero": zero})
        if _existing_cont is not None
        else ScaleContinuousStyle(zero=zero)
    )
    baked_scale = (
        ay.scale.model_copy(update={"continuous": new_cont})
        if ay.scale is not None
        else BaseScaleStyle(continuous=new_cont)
    )
    return ay.model_copy(update={"scale": baked_scale})


def _bake_y_zero(
    ay: AxisYStyle,
    primary: _CartesianChartStyle | None,
    y_values: list[float],
    chart_type: str,
) -> AxisYStyle:
    """Bake the measure-axis zero decision onto a working axis scale.

    Thin wrapper over ``resolve_y_zero`` (the canonical decision) that bakes a
    concrete outcome onto the cascaded axis; None (no opinion) leaves ``ay``
    unchanged. The caller constructs the resolved axis after every scale and
    tick decision is complete.

    Skipped entirely for a log-typed axis: ``ScaleContinuousStyle``'s own
    ``type: log`` + ``zero: true`` validator only fires on construction, not
    on the ``model_copy`` ``_bake_zero_flag`` uses — baking ``zero=True`` here
    would silently produce an internally-inconsistent, unvalidated
    ``ScaleContinuousStyle(type="log", zero=True)`` a log domain cannot
    represent. ``ay.scale.continuous.zero`` already carries whatever the
    author explicitly pinned (or None); this only skips the heuristic's own
    default.
    """
    _existing_cont = ay.scale.continuous if ay.scale is not None else None
    if _existing_cont is not None and _existing_cont.type == "log":
        return ay
    zero = resolve_y_zero(
        primary,
        min(y_values) if y_values else None,
        max(y_values) if y_values else None,
        chart_type,
    )
    if zero is None:
        return ay
    return _bake_zero_flag(ay, zero)


def _reject_non_positive_log_scale_data(
    chart_id: str,
    ay: AxisYStyle,
    y_fields: list[str],
    data: list[dict[str, Any]],
) -> None:
    """Raise when a log measure axis's data contains a value ``<= 0``.

    A log domain is undefined at and below zero. Without this check, a zero
    or negative data point silently degenerates the render instead of
    erroring: Vega-Lite's own automatic domain inference degenerates on
    non-positive data for line/scatter (no baked domain), and the area
    domain-bake (below) would compute a ``<= 0`` lower bound directly from
    the data — exactly the failure mode the authored-``zero``/no-domain
    validators guard against, but not yet for the data's own content.
    """
    _cont = ay.scale.continuous if ay.scale is not None else None
    if _cont is None or _cont.type != "log":
        return
    for field in y_fields:
        if any(v <= 0 for v in numeric_column_values(data, field)):
            raise CompilationError.from_code(
                ERR_LOG_SCALE_REQUIRES_POSITIVE_DATA,
                chart_id=chart_id,
                y_field=field,
            )


def _authored_axis_y_ticks_count(
    chart_style: _CartesianChartStyle | None,
) -> int | None:
    """The chart's OWN authored ``axis_y.ticks.count`` — pre-cascade, not the
    theme-defaulted resolved value.

    The theme always resolves ``ay.ticks.count`` to a concrete default (e.g.
    6 nice ticks) for every quantitative axis, so the resolved
    ``ResolvedAxisStyle.ticks.count`` is essentially never ``None`` in
    practice. Only a count the *chart itself* deliberately set is a real
    authoring conflict with ``type: log`` — the theme's blanket tick-count
    default is not a per-chart decision about this axis and must not trip it.
    """
    if chart_style is None or chart_style.axis_y is None:
        return None
    # AxisStylePatch.ticks: its TYPE_CHECKING stub inherits AxisYStyle's
    # non-Optional `ticks: AxisTicksStyle = Field(default_factory=...)`, but
    # build_patch_model_ext genuinely makes this field Optional at runtime —
    # getattr is the correct escape hatch for this Patch-vs-compiled-type
    # stub mismatch (mypy would otherwise flag a real `is None` check as
    # unreachable), not a defensive read of a guaranteed field.
    ticks = getattr(chart_style.axis_y, "ticks", None)
    return ticks.count if ticks is not None else None


def _axis_headroom(ay: AxisYStyle) -> float | None:
    """Read the authored (or theme-default) headroom off a cascaded axis scale."""
    return ay.scale.headroom if ay.scale is not None else None


def _numeric_y_values(data: ChartRows, y_fields: tuple[str, ...]) -> list[float]:
    """Extract finite numeric values of every column in ``y_fields`` from data rows.

    Accepts int, float, Decimal, and string representations of numbers (CSV-ingested
    data commonly arrives as strings). Skips bools, None, and non-numeric strings.
    """
    result: list[float] = []
    for row in data:
        for y_field in y_fields:
            if y_field not in row:
                continue
            v = row[y_field]
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float, Decimal)):
                result.append(float(v))
            elif isinstance(v, str):
                with contextlib.suppress(ValueError, ArithmeticError):
                    result.append(float(v))
    return result


def _zero_anchor_floats(
    normalized_y: str | list[str] | None,
    data: ChartRows,
) -> list[float]:
    """Numeric floats for the zero-anchor heuristic across all y fields.

    Multi-metric (``y: [a, b]``, area/line's wide-y): floats span every
    measure's own values so the anchor decision reads the real extent instead
    of always-anchored on empty data.
    """
    if isinstance(normalized_y, str):
        return _numeric_y_values(data, (normalized_y,))
    if isinstance(normalized_y, list):
        return _numeric_y_values(data, tuple(normalized_y))
    return []


def _shared_y_values(
    data: ChartRows,
    y_field: str,
    chart: CartesianChart,
    datasets: LayerDatasets,
) -> list[float]:
    """The numeric values drawn against the chart's primary y scale.

    A shared scale has to span every series drawn on it, or the overlay is drawn
    outside the plot: pin the domain to the base series alone and a larger goal
    line floats above the axis top — and once the base max is small enough
    relative to it, autosize-fit collapses the plot height to zero and the chart
    renders as title-plus-axis only.

    A layer pinned to ``axis_y.position: right`` has an independent scale, so it
    must not widen this one. Layers sharing the base query read from ``data``;
    own-query layers read from ``datasets`` when the caller can supply it.
    """
    values = _numeric_y_values(data, (y_field,))
    seen = {(chart.query_name, y_field)}
    for layer in chart.layers:
        if layer.y is None or (
            layer.axis_y is not None and layer.axis_y.position == "right"
        ):
            continue
        query_name = layer.query
        key = (query_name, layer.y)
        if key in seen:
            continue
        seen.add(key)
        if query_name is None or query_name == chart.query_name:
            rows = data
        else:
            if datasets is ...:
                continue
            if query_name not in datasets:
                raise ChartDataError(
                    f"Missing rows for shared-scale layer query {query_name!r}"
                )
            rows = datasets[query_name]
        values.extend(_numeric_y_values(rows, (layer.y,)))
    return values


class _CartesianTickResolution(NamedTuple):
    """Nice tick ladder + exact (non-nice-rounded) measure-axis domain bounds.

    ``domain_max`` / ``domain_min`` are None when VL should auto-fit that edge:
    authored ``scale.domain`` is in effect, no data available, or headroom is 0.
    On zero-anchored axes only ``domain_max`` is set (bottom stays at 0).
    On zoomed axes both are set via symmetric span-relative headroom.
    """

    ticks: tuple[float, ...]
    domain_max: float | None
    domain_min: float | None = None


def _authored_tick_ladder(ay: AxisYStyle) -> tuple[float, ...] | None:
    """The authored ``axis_y.scale.values`` ladder, as floats — or ``None``
    when unauthored (the caller falls through to ``nice_tick_values``).

    ``axis_to_vl`` emits this list verbatim as VL's ``values``, and
    ``bake_tick_ladder`` — which every emit path now routes through — only
    bakes a ladder when the axis carries no ``values`` already, so an
    authored list always wins over whatever ``nice_tick_values`` would
    otherwise pick. Baking THIS list —
    not a separately-computed ladder — as the axis's ``tick_values`` is what
    keeps ``quantitative_tick_labels``'s gutter measurement matched to what
    Vega actually renders: the gutter must be sized from the exact same tick
    bodies Vega paints, so the formula-based labelExpr and the Python-side
    measurement can never diverge.
    """
    if ay.scale is None or ay.scale.values is None:
        return None
    return tuple(float(v) for v in ay.scale.values)


def _resolve_cartesian_ticks(
    chart_id: str,
    ay: AxisYStyle,
    y_floats: list[float],
    zero_anchor: bool,
    authored_ticks_count: int | None,
    scale: Literal["shared", "independent"],
) -> _CartesianTickResolution:
    """Compute the nice tick ladder + domain bounds for a cartesian y-axis (non-stacked).

    Used by bar (non-stacked), line, area, and scatter.  For stacked bars use
    ``_resolve_stacked_bar_ticks`` which substitutes the stacked domain max.

    ``y_floats`` contains every series drawn against this scale. The bounds span
    all of them, because a series drawn outside the domain is outside the plot.

    A log measure axis always delegates tick placement to Vega-Lite (log
    decades), regardless of the theme's tick-count default — unless the
    chart itself explicitly authored ``ticks.count``, which is a genuine
    conflict (a target count is meaningless on a log axis) and raises.

    Two headroom formulas depending on zero-anchor:
    - Zero-anchored: top-only multiplicative — domain_max = data_max * (1+h);
      bottom stays at 0, domain_min stays None.
    - Zoomed (not zero-anchored): symmetric span-relative —
      domain_max = data_max + h * span; domain_min = data_min - h * span.

    Returns empty ticks + None bounds when ``ticks.count`` is unset or no data
    — unless ``axis_y.scale.values`` is authored, which bypasses both checks
    (see ``_authored_tick_ladder``): an explicit ladder needs no ``ticks.count``
    to be known exactly, and headroom/domain bounds stay None (VL auto-fits
    the scale range; an explicit tick list says nothing about it).

    ``scale`` mirrors ``_resolve_stacked_bar_ticks``'s own parameter: an
    authored ``axis_y.scale.continuous.domain`` wins regardless of it (explicit
    author intent, not the auto-derived ladder ``multiples: {scale:
    independent}`` suppresses); absent that, ``independent`` bakes no ladder
    and no domain bound at all — each small-multiples panel gets Vega-Lite's
    own per-panel scale instead of one shared union-of-panels ladder.
    ``y_floats`` itself stays whole-dataset even under ``independent`` (a
    column-wise union read is identical whether the chart is faceted or
    not — only an aggregate needs one panel's rows); what changes is only
    whether the result gets baked.
    """
    _cont = ay.scale.continuous if ay.scale is not None else None
    if _cont is not None and _cont.type == "log":
        if authored_ticks_count is not None:
            raise CompilationError.from_code(
                ERR_TICKS_COUNT_REQUIRES_NON_LOG_SCALE,
                chart_id=chart_id,
            )
        return _CartesianTickResolution((), None)
    authored_ladder = _authored_tick_ladder(ay)
    if authored_ladder is not None:
        return _CartesianTickResolution(authored_ladder, None)
    if ay.ticks.count is None or not y_floats:
        return _CartesianTickResolution((), None)
    authored = numeric_domain_bounds(_cont.domain if _cont is not None else None)
    domain_max: float | None = None
    domain_min: float | None = None
    if authored is not None:
        tick_min, tick_max = authored
    elif scale == "independent":
        return _CartesianTickResolution((), None)
    elif zero_anchor:
        # Zero-anchored: multiplicative top, bottom stays at 0.
        tick_min = min(0.0, min(y_floats))
        raw_max = max(y_floats)
        tick_max = apply_headroom(raw_max, _axis_headroom(ay))
        # Bake domainMax only when headroom expanded past the data max.
        # headroom=0 and non-positive maxima leave it None — VL auto-fits.
        if tick_max > raw_max:
            domain_max = tick_max
    else:
        # Zoomed (not zero-anchored): symmetric span-relative headroom.
        data_min = min(y_floats)
        raw_max = max(y_floats)
        h = _axis_headroom(ay)
        span = raw_max - data_min
        if h and span > 0:
            domain_max = raw_max + h * span
            domain_min = data_min - h * span
            tick_min = domain_min
            tick_max = domain_max
        else:
            tick_min, tick_max = data_min, raw_max
    ticks = tuple(nice_tick_values(tick_min, tick_max, ay.ticks.count))
    return _CartesianTickResolution(ticks, domain_max, domain_min)


def _resolve_stacked_bar_ticks(
    ay: AxisYStyle,
    dataset: ChartDataset,
    y_fields: list[str],
    cat_field: str,
    scale: Literal["shared", "independent"],
) -> tuple[float, ...]:
    """Compute nice tick values for a stacked bar using the stacked domain max.

    Stacked bars always zero-anchor unless an authored domain overrides both
    bounds.  The per-category positive stacked total (with headroom applied)
    replaces the raw data max so the tick ladder spans the full stacked
    height.  The emitter reads the separately-baked ``stacked_domain_max``
    (also headroom-applied — see ``_resolve_bar``) for VL ``domainMax``, not
    ``max(ay.tick_values)`` — a nice-rounded ladder rung is not the exact
    headroom bound.

    Never reached with a log measure axis — every caller must reject log+stack
    upstream. Bar rejects it in ``_resolve_bar_chart`` before stack resolution
    runs; area rejects it via ``ERR_AREA_STACKED_LOG_SCALE_NOT_SUPPORTED``.

    An authored ``axis_y.scale.values`` bypasses the stacked-total ladder
    entirely and returns that list verbatim — see ``_authored_tick_ladder``.
    An authored ``axis_y.scale.continuous.domain`` likewise wins regardless of
    ``scale`` — it is explicit author intent, not the auto-derived ladder
    ``multiples: {scale: independent}`` suppresses. Absent either override,
    ``independent`` bakes no ladder at all: each panel gets its own,
    Vega-Lite-computed scale.
    """
    authored_ladder = _authored_tick_ladder(ay)
    if authored_ladder is not None:
        return authored_ladder
    if ay.ticks.count is None:
        return ()
    data = dataset.all_rows()
    if not data:
        return ()
    y_floats = [
        value for y_field in y_fields for value in numeric_column_values(data, y_field)
    ]
    if not y_floats:
        return ()
    _cont = ay.scale.continuous if ay.scale is not None else None
    authored = numeric_domain_bounds(_cont.domain if _cont is not None else None)
    if authored is not None:
        tick_min, tick_max = authored
    elif scale == "independent":
        return ()
    else:
        # cat_field can itself be the multiples field — partition() strips a
        # panel's own partition column from its rows, so restamp it back
        # before grouping, or every row's cat_field reads as absent and the
        # stacked total silently folds to None (nothing to sum).
        sm = fold_panels(
            restamp(dataset, cat_field),
            scale,
            lambda rows: stacked_totals_max(rows, cat_field, y_fields),
        )
        raw_max = sm if sm is not None else max(y_floats)
        tick_max = apply_headroom(raw_max, _axis_headroom(ay))
        tick_min = min(0.0, min(y_floats))  # stacked bars always zero-anchor
    return tuple(nice_tick_values(tick_min, tick_max, ay.ticks.count))


def _first_non_numeric_y(
    y: str | list[str] | None,
    data: list[dict[str, Any]],
) -> str | None:
    """Return the first y field that has samples but is non-numeric, else None.

    Shared by bar and line — both hardcode y to "quantitative" in the axis
    cascade, so a categorical y silently bakes a NaN axis. This helper
    surfaces the offending field so the caller can raise the right DF code.
    Uses classify_column_type (not the stricter _classify_to_channel_type)
    so numeric-looking strings from untyped sources (CSV, Decimal-as-str)
    still count as numeric — only genuinely categorical values trip the guard.
    """
    fields: list[str] = (
        [y] if isinstance(y, str) else list(y) if isinstance(y, list) else []
    )
    for field in fields:
        samples = first_non_null_samples(field, data)
        if samples and classify_column_type(field, samples) != "numeric":
            return field
    return None


def _bake_normalize_domain(ay_merged: AxisYStyle) -> AxisYStyle:
    """Bake [0, 1] domain onto ay_merged for normalize-stack axes.

    measure_axis_to_vl estimates label widths from the resolved domain; without
    this bake it reads raw query values (e.g. 0..1000) and computes an
    over-wide label pad. Only bakes when the author has not already set a domain.
    """
    ay_sc = ay_merged.scale
    ay_cont = ay_sc.continuous if ay_sc is not None else None
    if ay_cont is not None and ay_cont.domain is not None:
        return ay_merged
    norm_cont = (
        ay_cont.model_copy(update={"domain": (0.0, 1.0)})
        if ay_cont is not None
        else ScaleContinuousStyle(domain=(0.0, 1.0))
    )
    norm_scale = (
        ay_sc.model_copy(update={"continuous": norm_cont})
        if ay_sc is not None
        else BaseScaleStyle(continuous=norm_cont)
    )
    return ay_merged.model_copy(update={"scale": norm_scale})
