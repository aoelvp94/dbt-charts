"""Dataface-shaped helpers for axis tick computation — compile boundary.

The generic "nice step" tick algorithm lives in the neutral
``dbt_charts.core.numeric`` leaf (both compile and render need it); this module
holds the Dataface-typed helpers built on top of it (domain parsing, stacked-
bar totals) that stay compile-owned.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from dbt_charts.core.compile.resolve.chart._chart_rows import PanelRows

ChartValue = str | int | float | Decimal
# stacked_bar_totals's row shape -- a named alias so the type-state gate
# counts its `Any` once. Its PanelRows-typed callers (stacked_bar_totals_max,
# stacked_bar_multi_measure_totals_max) don't use this: PanelRows already
# satisfies this wider shape structurally, no separate alias needed for them.
_RowData = list[dict[str, Any]]


def apply_headroom(value: float, headroom: float | None) -> float:
    """Multiply a positive domain top by ``1 + headroom``, exact (no rounding).

    ``headroom`` of ``None`` or ``0`` is a no-op. Negative headroom is rejected
    by the ``ScaleStyle.headroom`` ``ge=0`` constraint, never reaches here.

    Only applies to a positive ``value`` — a non-positive measure-axis max (all
    data at or below zero) has no well-defined multiplicative "top", so it
    passes through unchanged rather than growing more negative.
    """
    if not headroom or value <= 0:
        return value
    return value * (1.0 + headroom)


def numeric_domain_bounds(domain: object) -> tuple[float, float] | None:
    """Return ``(lo, hi)`` when ``domain`` is a 2-element list/tuple of reals.

    An authored quantitative ``scale.domain`` feeds these bounds into
    ``nice_tick_values`` so the tick ladder spans the authored range, not just
    the data extent. Returns ``None`` for an unset, non-numeric (categorical /
    ordinal), or malformed domain — the caller then falls back to the data
    extent unchanged.
    """
    if not isinstance(domain, (list, tuple)) or len(domain) != 2:
        return None
    lo, hi = domain
    if (
        isinstance(lo, (int, float))
        and not isinstance(lo, bool)
        and isinstance(hi, (int, float))
        and not isinstance(hi, bool)
    ):
        return float(lo), float(hi)
    return None


def stacked_bar_totals(
    data: _RowData,
    x_field: str,
    y_field: str,
) -> dict[ChartValue, float]:
    """Return each category's positive stacked total, keyed by its ``x_field`` value.

    Sums only positive y values per category, matching VL's behaviour of stacking
    positives upward and negatives downward independently.

    ``data`` stays the wide ``_RowData`` type, not ``PanelRows``: render's
    ``bar_hover_band.py`` calls this directly against its own flat rows, with
    no panel concept of its own. ``stacked_bar_totals_max`` below is the one
    ``PanelRows``-typed caller — a ``PanelRows`` argument satisfies this wider
    parameter type for free (``PanelRows`` is a ``NewType`` over this same
    ``list[dict[str, Any]]`` shape).
    """
    totals: dict[ChartValue, float] = {}
    for row in data:
        x = row.get(x_field)
        y = row.get(y_field)
        if x is None or y is None:
            continue
        totals[x] = totals.get(x, 0.0) + max(0.0, float(y))
    return totals


def stacked_bar_totals_max(
    data: PanelRows,
    x_field: str,
    y_field: str,
) -> float | None:
    """Return the max per-category positive stacked total, or None if no valid rows.

    Caller must guard against stack_mode "normalize" (domain is always [0, 1] there).

    ``data`` is one panel's rows (``PanelRows``), never the whole dataset —
    summing across every small-multiples panel inflates the shared-scale
    domain by the panel count. Fold across panels via
    ``fold_panels``/``reduce_panels``, never by widening this signature.
    """
    totals = stacked_bar_totals(data, x_field, y_field)
    return max(totals.values()) if totals else None


def stacked_bar_multi_measure_totals_max(
    data: PanelRows,
    x_field: str,
    y_fields: list[str],
) -> tuple[float, ...]:
    """Return the max positive stacked total for wide-form measures.

    ``data`` is one panel's rows — see ``stacked_bar_totals_max``.
    """
    totals: defaultdict[str | int | float | Decimal, float] = defaultdict(float)
    for row in data:
        x = row.get(x_field)
        if x is None:
            continue
        totals[x] += sum(
            max(0.0, float(row[y])) for y in y_fields if row.get(y) is not None
        )
    return (max(totals.values()),) if totals else ()


def stacked_totals_max(
    data: PanelRows, x_field: str, y_fields: list[str]
) -> float | None:
    """One-panel stacked total max, single- or multi-measure — for ``fold_panels``.

    Thin dispatcher over ``stacked_bar_totals_max`` /
    ``stacked_bar_multi_measure_totals_max`` so a caller folding across panels
    (``fold_panels(dataset, scale, lambda rows: stacked_totals_max(rows, x, y_fields))``)
    doesn't need its own single-vs-multi branch.
    """
    if len(y_fields) == 1:
        return stacked_bar_totals_max(data, x_field, y_fields[0])
    totals = stacked_bar_multi_measure_totals_max(data, x_field, y_fields)
    return totals[0] if totals else None
