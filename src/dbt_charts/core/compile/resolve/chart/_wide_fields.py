"""Fixed synthetic field names for the wide-measure fold transform, the
shared resolve-time validation/channel-injection every wide-capable cartesian
family resolver (bar, area, line) uses, and the Python mirror of the fold.

The constants are used by both the resolver (to bake WIDE_VALUE_FIELD as the
resolved y column) and the render emitter (to build the VL fold transform).
They live in compile/ so the resolver can import them without creating a
compile -> render circular dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.chart.normalized import _CartesianChartFields
from dbt_charts.core.compile.models.chart.resolved._channel import ResolvedStyleChannel
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_MULTI_Y_COLOR_CONFLICT,
    ERR_MULTI_Y_LAYERS_CONFLICT,
)
from dbt_charts.core.utils import Rows

# Field that VL fold emits for the folded numeric value.
WIDE_VALUE_FIELD = "__dbt_charts_wide_value__"
# Human-readable series label used as the VL color field: the authored
# measure column name, prefixed by the dimension value when the chart also
# authors ``color:``. Separate from the raw key field so label expressions
# can compose the display name.
WIDE_LABEL_FIELD = "__dbt_charts_wide_label__"
# Synthetic sort-order field appended when stack != 'none'.
WIDE_ORDER_FIELD = "__dbt_charts_wide_order__"
WIDE_SERIES_SEPARATOR = " — "


def unfold_wide_rows(
    data: Rows, measures: Sequence[str], dimension: str | None
) -> Rows:
    """Pre-fold wide (one row per x[, dimension], N measure columns) rows into
    long form.

    Mirrors the VL ``fold`` + ``calculate`` pair ``render/chart/emitters/_wide.py``
    emits for the actual mark data, so Python-side code that must reason about
    real values can feed a wide chart's data through the same functions an
    authored ``color:`` chart's long-form rows already go through. VL's own
    fold runs client-side, after this spec ships, so it never does this
    unpivot for us; the two must stay in lockstep with ``_label_expression``.

    ``dimension`` is the authored ``color:`` column when the measures are
    grouped by one: the series label is then ``<dimension value> — <measure>``,
    and ``_wide._label_expression`` must produce the identical string. A row
    whose dimension is null names no series, same as ``distinct_series_values``.
    """
    return [
        {
            **row,
            WIDE_LABEL_FIELD: (
                measure
                if dimension is None
                else f"{row[dimension]}{WIDE_SERIES_SEPARATOR}{measure}"
            ),
            WIDE_VALUE_FIELD: row[measure],
        }
        for row in data
        if dimension is None or row.get(dimension) is not None
        for measure in measures
        if row.get(measure) is not None
    ]


def wide_dimension_values(data: Rows, dimension: str) -> list[Any]:  # type-state: explicit_any — raw dimension cells  # fmt: skip
    """Distinct non-null values of the ``dimension`` column, in first-seen order.

    Raw values, not their ``str()`` — the VL label expression compares the
    datum against each one as a JSON literal, so it must see the value the
    row actually carries — but deduplicated by the ``str()`` that names the
    series, so a column mixing ``True`` and ``1`` pins one domain entry per
    label. A null never names a series.
    """
    labels: set[str] = set()
    values = []
    for row in data:
        value = row.get(dimension)
        if value is not None and str(value) not in labels:
            labels.add(str(value))
            values.append(value)
    return values


def wide_series_names(
    measures: Sequence[str], dimension: str | None, data: Rows
) -> list[str]:
    """Sorted color-scale domain of a wide chart: the authored measures,
    crossed with every observed ``dimension`` value when one is authored.

    Measures come from the authored list, not observed rows — a measure that
    is null on every row would otherwise drop out of the domain and desync
    palette slots from the chart's own scale. Dimension values come from the
    rows, as an authored ``color:`` chart's do; a null never names a series.
    """
    if dimension is None:
        return sorted(measures)
    return sorted(
        f"{v}{WIDE_SERIES_SEPARATOR}{m}"
        for v in wide_dimension_values(data, dimension)
        for m in measures
    )


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

    An authored ``color:`` column composes with the fold: it stays on the
    resolved chart's ``color`` field as the dimension the measures are grouped
    by, and the fold's series become ``<value> — <measure>`` composites. Any
    other ``color:`` (a literal hue, a gradient, a conditional scale) names
    nothing to cross the measures with and raises
    ``ERR_MULTI_Y_COLOR_CONFLICT``. ``ERR_MULTI_Y_LAYERS_CONFLICT`` covers
    ``layers:`` — a layer can author its own ``color:``, and even a colorless
    layer's overlay-merge assumes the base's ``y`` is a real, single field,
    not the synthetic ``WIDE_VALUE_FIELD``.

    Shared by every wide-capable cartesian family resolver (bar, area,
    line) — one validation/injection site instead of three near-identical
    copies that could silently drift.
    """
    wide_measure_series = isinstance(normalized.y, list)
    if not wide_measure_series:
        return channels, False
    if normalized.color is not None and channels["color"].mode != "series":
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
