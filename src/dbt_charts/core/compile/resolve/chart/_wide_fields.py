"""Fixed synthetic field names for the wide-measure fold transform, and the
shared resolve-time validation/channel-injection every wide-capable cartesian
family resolver (bar, area, line) uses.

The constants are used by both the resolver (to bake WIDE_VALUE_FIELD as the
resolved y column) and the render emitter (to build the VL fold transform).
They live in compile/ so the resolver can import them without creating a
compile -> render circular dependency.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.chart.normalized import _CartesianChartFields
from dbt_charts.core.compile.models.chart.resolved._channel import ResolvedStyleChannel
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_MULTI_Y_COLOR_CONFLICT,
    ERR_MULTI_Y_LAYERS_CONFLICT,
)

# Field that VL fold emits for the folded numeric value.
WIDE_VALUE_FIELD = "__dbt_charts_wide_value__"
# Human-readable measure label (the authored column name), used as the VL
# color field. Separate from the raw key field so label expressions can
# normalise the display name if needed.
WIDE_LABEL_FIELD = "__dbt_charts_wide_label__"
# Synthetic sort-order field appended when stack != 'none'.
WIDE_ORDER_FIELD = "__dbt_charts_wide_order__"


def resolve_wide_measure_channels(
    normalized: _CartesianChartFields,
    channels: dict[str, ResolvedStyleChannel],
    chart_type: str,
    *,
    has_layers: bool,
) -> tuple[dict[str, ResolvedStyleChannel], bool]:
    """Validate + inject the synthetic color channel for a wide (``y: [a, b]``)
    chart. Returns ``(channels, wide_measure_series)`` — ``channels`` is
    returned unchanged when ``normalized.y`` isn't a list.

    Raises ``ERR_MULTI_Y_COLOR_CONFLICT`` / ``ERR_MULTI_Y_LAYERS_CONFLICT``
    when a wide chart also authors ``color:`` or ``layers:`` — both already
    want the color channel (a layer can author its own ``color:``, and even
    a colorless layer's overlay-merge assumes the base's ``y`` is a real,
    single field, not the synthetic ``WIDE_VALUE_FIELD``), and merging two
    independent color scales/legends into one layered spec is unsolved
    design work, not a mechanical gap. The message points authors at the
    long-form (``color:``) equivalent, which already composes with
    ``layers:`` today.

    Shared by every wide-capable cartesian family resolver (bar, area,
    line) — one validation/injection site instead of three near-identical
    copies that could silently drift.
    """
    wide_measure_series = isinstance(normalized.y, list)
    if not wide_measure_series:
        return channels, False
    if normalized.color is not None:
        raise CompilationError.from_code(
            ERR_MULTI_Y_COLOR_CONFLICT,
            chart_id=normalized.id,
            chart_type=chart_type,
            color_field=normalized.color,
        )
    if has_layers:
        raise CompilationError.from_code(
            ERR_MULTI_Y_LAYERS_CONFLICT,
            chart_id=normalized.id,
            chart_type=chart_type,
        )
    # Inject a synthetic series-color channel so every consumer that gates on
    # resolved_channels["color"].mode == "series" (endpoint labels, grouped
    # bar spacing, legend, palette ordering, tooltip) picks up multi-y for
    # free — same path as an authored color: field.
    channels = {
        **channels,
        "color": ResolvedStyleChannel(
            channel="color", mode="series", data_field=WIDE_LABEL_FIELD
        ),
    }
    return channels, True


def bake_wide_measures_kwargs(
    normalized_y: str | list[str] | None,
    cartesian_kwargs: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Resolve ``wide_measures`` from the authored ``y:`` list, and override the
    ``_cartesian_kwargs()``-built ``"y"`` entry to the synthetic
    ``WIDE_VALUE_FIELD`` when it's non-empty (``_cartesian_kwargs`` bakes
    ``normalized.y`` verbatim, list included — this is the one place that
    narrows it to the resolved model's ``y: str | None``).

    Returns ``(cartesian_kwargs, wide_measures)``; the caller spreads both
    into the resolved chart constructor (``**_ck, wide_measures=wide_measures``).
    """
    wide_measures = tuple(normalized_y) if isinstance(normalized_y, list) else ()
    if wide_measures:
        cartesian_kwargs = {**cartesian_kwargs, "y": WIDE_VALUE_FIELD}
    return cartesian_kwargs, wide_measures
