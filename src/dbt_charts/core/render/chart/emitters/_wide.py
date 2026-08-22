"""Vega-Lite fold support for list-valued cartesian measures."""

from __future__ import annotations

import json
from dataclasses import dataclass

from dbt_charts.core.compile.models.style.resolved import ResolvedLegendStyle
from dbt_charts.core.compile.resolve.chart._wide_fields import (
    WIDE_LABEL_FIELD,
    WIDE_ORDER_FIELD,
    WIDE_VALUE_FIELD,
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

# Internal key field for the raw fold; only WIDE_LABEL_FIELD is exposed to VL
# encodings (it carries the human-readable measure name).
_WIDE_KEY_FIELD = "__dbt_charts_wide_key__"


def unfold_wide_rows(
    data: list[VLDict], measures: tuple[str, ...] | list[str]
) -> list[VLDict]:
    """Pre-fold wide (one-row-per-x, N measure columns) rows into long form.

    Mirrors the VL ``fold`` transform this module emits for the actual mark
    data, so Python-side code that must reason about real values (not just
    VL field references) — series ordering, endpoint-label positions,
    negative-value checks — can feed a wide chart's data through the exact
    same functions an authored ``color:`` chart's real long-form rows
    already go through. VL's own fold runs client-side, after this spec
    ships, so it never does this unpivot for us.
    """
    return [
        {**row, WIDE_LABEL_FIELD: measure, WIDE_VALUE_FIELD: row[measure]}
        for row in data
        for measure in measures
        if row.get(measure) is not None
    ]


@dataclass(frozen=True)
class FoldedMeasures:
    """VL field names and transforms for a wide-form measure fold."""

    value_field: str
    label_field: str
    transforms: list[VLDict]
    color: VLDict
    order: VLDict


def _label_expression(key_field: str, measures: list[str]) -> str:
    """Map raw fold key to itself in a Vega expression (identity relabel).

    The measure name is the color-series value, same as any authored color:
    field carries its column's raw data values verbatim — never humanized.
    """
    parts = [
        f"datum[{json.dumps(key_field)}] === {json.dumps(measure)} ? {json.dumps(measure)}"
        for measure in measures
    ]
    return " : ".join(parts) + " : ''"


def fold_wide_measures(
    measures: list[str],
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
    transforms: list[VLDict] = [
        {"fold": fold_order, "as": [_WIDE_KEY_FIELD, WIDE_VALUE_FIELD]},
        {
            "calculate": _label_expression(_WIDE_KEY_FIELD, fold_order),
            "as": WIDE_LABEL_FIELD,
        },
    ]
    color: VLDict = {"field": WIDE_LABEL_FIELD, "type": "nominal", "title": None}
    apply_color_legend(color, legend)
    if palette:
        color["scale"] = spatial_color_scale(sorted(measures), palette, display_order)
        pin_legend_display_order(color, display_order)
    order: VLDict = {}
    if baseline_order is not None:
        transforms.append(
            {
                "calculate": series_order_expression(WIDE_LABEL_FIELD, baseline_order),
                "as": WIDE_ORDER_FIELD,
            }
        )
        order = {"field": WIDE_ORDER_FIELD, "sort": "ascending"}
    return FoldedMeasures(WIDE_VALUE_FIELD, WIDE_LABEL_FIELD, transforms, color, order)
