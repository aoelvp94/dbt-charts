"""The categorical x scale's rendered value order.

A band scale's domain order is not the query's row order: an authored
``sort:`` reorders it, and an overlay layer can widen it. Two consumers need
that final order — ``emitters/_overlay.py``, which pins it onto the shared x
encoding, and ``features/value_labels.py``, whose band-edge labels have to know
which category actually renders at each end. Both read it from here so there is
one definition of "the order Vega-Lite will draw".
"""

from __future__ import annotations

from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.utils import (
    DomainValue,
    normalize_scalar_for_json,
    ordered_distinct_values,
)
from dbt_charts.core.utils import Rows, domain_sort_aggregates


def _sort_domain_by_field(
    domain: list[DomainValue],
    base_data: Rows,
    x_field: str,
    sort: VLDict,
) -> list[DomainValue]:
    """Reorder domain values by sort["field"] aggregated from base_data.

    ``sort`` is the already-translated Vega-Lite sort dict (``{"field": ...,
    "order": "ascending" | "descending"}``, from ``chart_sort_to_vl``), not
    the authored ``ChartSort`` model — this reads it directly off the shared
    x encoding, the same place ``rendered_x_domain`` reads it, so there is only one
    shape to handle.

    Always uses ``sum`` — Vega-Lite's own ``EncodingSortField.op`` default.
    This function only ever runs against a categorical (nominal/ordinal) base
    x (``rendered_x_domain`` no-ops otherwise), and the bar emitter's
    unstacked ``y.stack: null`` (added to suppress VL's implicit auto-stack
    on a grouped bar) is only emitted for a genuinely continuous x — so
    ``min`` never matches what Vega-Lite actually does for any chart shape
    this function pins a domain for.

    ``domain_sort_aggregates`` handles numeric strings via ``coerce_numeric_cell``
    (some warehouse adapters return measure columns as strings). Keys are
    remapped through ``normalize_scalar_for_json`` to match ``domain``'s key
    space — ``ordered_distinct_values`` normalizes x-values (e.g.
    ``datetime.date`` → ISO string) while the raw query rows still carry the
    original type. Values absent from base_data (layer-only categories) are
    appended after in first-seen order so they never vanish.
    """
    sort_field = sort.get("field")
    if not isinstance(sort_field, str):
        return list(domain)
    sort_aggs_raw = domain_sort_aggregates(base_data, x_field, sort_field)
    sort_aggs = {normalize_scalar_for_json(k): v for k, v in sort_aggs_raw.items()}
    in_base = [v for v in domain if v in sort_aggs]
    layer_only = [v for v in domain if v not in sort_aggs]
    in_base.sort(
        key=lambda v: sort_aggs[v], reverse=(sort.get("order") == "descending")
    )
    return in_base + layer_only


def rendered_x_domain(
    x_enc: VLDict,
    base_data: Rows,
    layer_x_columns: list[tuple[str, Rows]],
) -> list[DomainValue]:
    """The categorical x scale's value order as Vega-Lite actually renders it.

    Base rows first in query order, then any layer-only categories in their own
    first-seen order, then reordered by the encoding's own field ``sort``. The
    sort is applied unconditionally because it describes the RENDERED order
    either way: when the overlay reconciler pins this domain it pins it sorted,
    and when it declines to pin, Vega-Lite's own native sort-by-field produces
    the same order.

    The one caller-side thing this does not model is a pinned
    ``scale.domain`` — an explicit domain always wins in Vega-Lite, so a caller
    holding one should read that instead of calling this.
    """
    base_field = x_enc.get("field")
    if not isinstance(base_field, str):
        return []
    union: dict[DomainValue, None] = dict.fromkeys(
        ordered_distinct_values(base_data, base_field)
    )
    for layer_field, layer_rows in layer_x_columns:
        for value in ordered_distinct_values(layer_rows, layer_field):
            union.setdefault(value, None)
    sort = x_enc.get("sort")
    if isinstance(sort, dict):
        return _sort_domain_by_field(list(union), base_data, base_field, sort)
    return list(union)
