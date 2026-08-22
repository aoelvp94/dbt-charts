"""Small-multiples partition axis — baked at resolve, read by render.

One ``PartitionAxis`` per ``multiples.rows`` / ``multiples.columns`` field
actually authored. A non-faceted chart carries no axes at all (``axes: ()``
on the resolved chart) — the N=1 case, not a special one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PartitionAxis:
    """One small-multiples partition dimension: field + observed values.

    ``values`` is the canonical string form of each distinct value observed
    in the query rows, in panel render order (see
    ``compile.resolve.chart._chart_rows.canonical_key``). The panels
    themselves (``compile.resolve.chart._chart_rows.Panel.key``) hold the
    original, non-canonicalized values — ``values`` here is for the
    generated schema and the VL facet header label only.
    """

    field: str
    values: tuple[str, ...]
