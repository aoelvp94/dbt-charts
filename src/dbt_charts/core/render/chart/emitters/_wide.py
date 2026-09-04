"""Vega-Lite fold support for list-valued cartesian measures."""

from __future__ import annotations

import json
from dataclasses import dataclass

from dbt_charts.core.compile.models.style.resolved import ResolvedLegendStyle
from dbt_charts.core.compile.resolve.chart._wide_fields import (
    WIDE_LABEL_FIELD,
    WIDE_ORDER_FIELD,
    WIDE_SERIES_SEPARATOR,
    WIDE_VALUE_FIELD,
    wide_dimension_values,
    wide_series_names,
)
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters._cartesian import (
    series_order_expression,
    spatial_color_scale,
)
from dbt_charts.core.render.chart.emitters._channels import (
    apply_color_legend,
    pin_legend_display_order,
)
from dbt_charts.core.render.utils import normalize_scalar_for_json
from dbt_charts.core.utils import Rows

# Internal key field for the raw fold; only WIDE_LABEL_FIELD is exposed to VL
# encodings (it carries the human-readable measure name).
_WIDE_KEY_FIELD = "__dbt_charts_wide_key__"


@dataclass(frozen=True)
class FoldedMeasures:
    """VL field names and transforms for a wide-form measure fold."""

    value_field: str
    label_field: str
    transforms: list[VLDict]
    color: VLDict
    order: VLDict


def _label_expression(
    key_field: str, measures: list[str], dimension: str | None, data: Rows
) -> str:
    """Map raw fold key to itself in a Vega expression (identity relabel),
    prefixed by the ``dimension`` column's value when the chart authors one.

    The measure name is the color-series value, same as any authored color:
    field carries its column's raw data values verbatim — never humanized.
    ``unfold_wide_rows`` is this expression's Python mirror, and the prefix
    is built the same way: each observed dimension value is matched as the
    JSON literal the row carries and mapped to its Python ``str()`` — never
    re-stringified by Vega, whose ``toString`` disagrees with Python on
    booleans and floats — so the label VL computes is the name Python pinned
    into the scale domain, by construction.
    """
    parts = [
        f"datum[{json.dumps(key_field)}] === {json.dumps(measure)} ? {json.dumps(measure)}"
        for measure in measures
    ]
    label = " : ".join([*parts, "''"])
    if dimension is None:
        return label
    field = f"datum[{json.dumps(dimension)}]"
    # The fallback rides inside the join: with no rows there are no arms, and
    # a bare ``( : '')`` is not a Vega expression.
    prefix = " : ".join(
        [
            *(
                f"{field} === {json.dumps(normalize_scalar_for_json(value))} ? "
                f"{json.dumps(str(value))}"
                for value in wide_dimension_values(data, dimension)
            ),
            "''",
        ]
    )
    return f"({prefix}) + {json.dumps(WIDE_SERIES_SEPARATOR)} + ({label})"


def _measure_paint_order(
    measures: list[str], dimension: str | None, data: Rows, fold_order: list[str]
) -> list[str]:
    """The VL fold list: ``fold_order`` itself on a plain wide chart, else the
    measures ranked by their earliest composite in ``fold_order``.

    ``fold_order`` is a paint order over series labels — composites on a
    chart with a dimension — or, on a stacked chart whose order channel
    governs accumulation, the authored measures themselves. Any composite
    it does not name (a measure null across one dimension value, or the
    stacked callers' measure list) ranks last, authored order breaking ties,
    so the fold never depends on the caller having enumerated the whole
    cross product.
    """
    if dimension is None:
        return fold_order
    rank = {label: index for index, label in enumerate(fold_order)}
    last = len(fold_order)
    values = wide_dimension_values(data, dimension)
    return sorted(
        measures,
        key=lambda m: min(
            (
                rank[label]
                for v in values
                if (label := f"{v}{WIDE_SERIES_SEPARATOR}{m}") in rank
            ),
            default=last,
        ),
    )


def fold_wide_measures(
    measures: list[str],
    dimension: str | None,
    data: Rows,
    palette: tuple[str, ...],
    legend: ResolvedLegendStyle,
    *,
    display_order: list[str],
    fold_order: list[str],
    baseline_order: list[str] | None = None,
) -> FoldedMeasures:
    """Return the internal VL fold and resolved series presentation for measures.

    A transform keeps the query result intact while giving Vega-Lite one unit
    spec over which its native stack and offset transforms can operate.

    ``dimension`` is the authored ``color:`` column the measures are grouped
    by, if any; ``data`` is the chart's pre-fold rows, read only for the
    dimension's observed values. The color-scale domain is
    ``wide_series_names(measures, dimension, data)`` — the measure names, or
    their ``<value> — <measure>`` composites. ``fold_order`` is the paint
    order of those series; with a dimension the fold — which only sequences
    measures *within* each source row — follows it as far as a fold can, per
    ``_measure_paint_order`` above.

    Series ordering is entirely the caller's decision, not this function's —
    ``display_order`` (color scale + legend, always) and ``baseline_order``
    (the ``WIDE_ORDER_FIELD`` mark-order channel, only when bar's explicit
    stack-segment sequence needs one) must be computed the same way the
    caller's own long-form/authored-color path already computes its
    equivalent order, typically via ``unfold_wide_rows`` feeding
    ``sorted_series_by_stack_order``/``_area_spatial_order`` — not
    reimplemented here. That is what keeps a wide chart's series order
    identical to what an authored ``color:`` chart of the same data would
    produce; this function has no data-shape opinion of its own.

    ``fold_order`` controls the VL ``fold`` transform's row-emission
    sequence, which doubles as the mark PAINT order whenever a caller has no
    other explicit position mechanism (grouped bar with no ``order``
    encoding; unstacked/overlap area, which paints series front-to-back in
    row sequence). Pass ``display_order`` there, so painting follows the
    same order the color domain/legend already display, matching what an
    authored ``color:`` chart's own paint order should be. A caller whose
    stack ACCUMULATION is already governed independently of fold sequence
    (bar's explicit ``baseline_order``/``WIDE_ORDER_FIELD`` channel; area's
    native VL stack, which reads ``color.scale.domain`` directly per
    ``_area_spatial_order``'s stacked branch) should pass the raw
    ``measures`` list instead — fold sequence is then visually inert for
    adjacent, non-overlapping stacked segments, so there's no reason to
    reorder it away from authored order.
    """
    series = wide_series_names(measures, dimension, data)
    fold = _measure_paint_order(measures, dimension, data, fold_order)
    transforms: list[VLDict] = [
        {"fold": fold, "as": [_WIDE_KEY_FIELD, WIDE_VALUE_FIELD]},
        {
            "calculate": _label_expression(_WIDE_KEY_FIELD, fold, dimension, data),
            "as": WIDE_LABEL_FIELD,
        },
    ]
    color: VLDict = {"field": WIDE_LABEL_FIELD, "type": "nominal", "title": None}
    apply_color_legend(color, legend)
    # No rows, no series: nothing to pin a domain or a stack order on, and an
    # empty order chain is not a Vega expression.
    if palette and series:
        palette_order = baseline_order if baseline_order is not None else series
        color["scale"] = spatial_color_scale(palette_order, palette, display_order)
        pin_legend_display_order(color, display_order)
    order: VLDict = {}
    if baseline_order:
        transforms.append(
            {
                "calculate": series_order_expression(WIDE_LABEL_FIELD, baseline_order),
                "as": WIDE_ORDER_FIELD,
            }
        )
        order = {"field": WIDE_ORDER_FIELD, "sort": "ascending"}
    return FoldedMeasures(WIDE_VALUE_FIELD, WIDE_LABEL_FIELD, transforms, color, order)
