"""Cross-cutting utilities shared across compile, execute, and render modules."""

import math
import re
from collections.abc import Hashable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import yaml
import yaml.constructor
from pydantic import BaseModel

# Query result rows, as every core layer passes them around.
Rows = list[dict[str, Any]]

_MERGE_TAG = "tag:yaml.org,2002:merge"

_YEAR_MIN = 1900
_YEAR_MAX = 2100
_YEAR_STRING_PATTERN = re.compile(r"^\d{4}$")

# Cell-scope date detector — shared by compile-time table column alignment
# (classify_date_column_align) and the render-time table cell/lane machinery
# (dbt_charts.core.render.chart.table.py and table_support.py both import
# is_date_like from here). Distinct from render/chart/type_inference.py's
# DATE_LIKE_PATTERNS (chart-scope: axis type inference), which is a
# separate, wider list — the two detectors are deliberately not unified.
_DATE_RE = re.compile(
    r"^\d{4}-\d{2}(-\d{2})?$"  # ISO: 2024-03 or 2024-03-15
    r"|^\d{2}/\d{2}/\d{4}$"  # US: 03/15/2024
    r"|^Q[1-4]\s+\d{4}$"  # Quarter: Q1 2024
    r"|^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}$"
    r"|^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}$"
    r"|^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}$"
    r"|^\d{4}$"  # Year: 2024
)


class UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML SafeLoader that raises ConstructorError on duplicate mapping keys.

    Scan runs on the raw node list before flatten_mapping so merge-key overrides
    (<<: *anchor + explicit key) are not flagged as duplicates.
    """

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            if key_node.tag == _MERGE_TAG:
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        None,
                        None,
                        f"duplicate key: {key!r}",
                        key_node.start_mark,
                    )
                seen.add(key)
            except TypeError:
                # Non-hashable key (e.g. a sequence) — can't be a duplicate, skip.
                pass
        return super().construct_mapping(node, deep=deep)


def to_plain_dict(obj: object) -> Any:
    """Recursively convert Pydantic models and nested objects to plain Python containers.

    This is the emit-boundary converter: typed Vega-Lite contract models
    (Config, Transform, etc.) are serialized to plain dicts here, just
    before they enter the final Vega-Lite spec dict for JSON emission.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(by_alias=True, exclude_unset=True)
    if isinstance(obj, dict):
        return {k: to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_plain_dict(v) for v in obj]
    return obj


_UNIT_SUFFIXES: dict[str, str] = {
    "usd": "($)",
    "eur": "(€)",
    "gbp": "(£)",
    "pct": "(%)",
    "percent": "(%)",
    "ratio": "(ratio)",
    "cnt": "(Count)",
    "num": "(#)",
    "qty": "(Qty)",
}

_ABBREVIATIONS: dict[str, str] = {
    "yoy": "YoY",
    "mom": "MoM",
    "qoq": "QoQ",
    "avg": "Avg",
    "arr": "ARR",
    "mrr": "MRR",
    "nrr": "NRR",
    "ltv": "LTV",
    "cac": "CAC",
    "roi": "ROI",
    "roas": "ROAS",
    "csat": "CSAT",
    "nps": "NPS",
    "enps": "eNPS",
    "api": "API",
    "id": "ID",
    "url": "URL",
    "sql": "SQL",
    "hr": "HR",
    "ip": "IP",
}


def slug_to_text(slug: str) -> str:
    """Tokenize a slug/ID into human-readable text — WITHOUT letter-case transforms.

    Handles common data column naming conventions:
    - snake_case and kebab-case → space-separated tokens (lowercase)
    - Unit suffixes: ``_usd`` → ``($)``, ``_pct`` → ``(%)``
    - Abbreviations: ``yoy`` → ``YoY``, ``arr`` → ``ARR``

    Letter-case (title/sentence/upper/lower) is NOT applied here — the caller
    supplies a ``font.case`` value and passes the result through
    ``apply_font_case`` (or ``format_display_text``).

    Examples:
        >>> slug_to_text("revenue_usd")
        'revenue ($)'
        >>> slug_to_text("yoy_growth_pct")
        'YoY growth (%)'
        >>> slug_to_text("logo_churn_pct")
        'logo churn (%)'
        >>> slug_to_text("avg_deal_size")
        'Avg deal size'
    """
    if not slug:
        return ""

    tokens = slug.replace("-", "_").replace(" ", "_").split("_")
    tokens = [t for t in tokens if t]

    suffix_label = ""
    if len(tokens) > 1 and tokens[-1].lower() in _UNIT_SUFFIXES:
        suffix_label = _UNIT_SUFFIXES[tokens[-1].lower()]
        tokens = tokens[:-1]

    words = []
    for token in tokens:
        lower = token.lower()
        if lower in _ABBREVIATIONS:
            words.append(_ABBREVIATIONS[lower])
        else:
            words.append(lower)

    text = " ".join(words)
    if suffix_label:
        text = f"{text} {suffix_label}".strip()
    return text


def numeric_column_values(rows: Rows, field: str) -> list[float]:
    """Extract ``field``'s numeric values from ``rows``: int/float/Decimal and
    numeric strings, matching real warehouse row shapes (some adapters return
    measure columns as strings). Shared by compile-time resolve checks and
    render-time baseline features so both agree on what counts as numeric."""
    values: list[float] = []
    for row in rows:
        cell = row.get(field)
        numeric = coerce_numeric_cell(cell)
        if numeric is not None:
            values.append(numeric)
    return values


def coerce_numeric_cell(cell: Any) -> float | None:
    """Coerce a single row cell to float, or None if it isn't numeric.

    Same numeric rule as ``numeric_column_values`` (int/float/Decimal and
    numeric strings, bool excluded) — shared so a compile-time format
    decision and the render-time formatting of the same cell agree on
    whether it's numeric. Non-finite values (NaN, ±Infinity) return None
    so all callers agree on the null rule: no colour, no domain contribution.
    """
    if isinstance(cell, (int, float, Decimal)) and not isinstance(cell, bool):
        result = float(cell)
        return result if math.isfinite(result) else None
    if isinstance(cell, str):
        try:
            result = float(cell)
            return result if math.isfinite(result) else None
        except ValueError:
            return None
    return None


def is_year_shaped(samples: list[Any]) -> bool:
    """True iff every non-null sample is a year-range value.

    Value-only heuristic (no column-name signal): an ``int`` in
    ``[1900, 2100]``, a ``str`` matching ``^\\d{4}$`` in that range, or an
    integral ``Decimal`` (``v == v.to_integral_value()``) in range — warehouses
    (BigQuery NUMERIC, Snowflake NUMBER) return year integers as ``Decimal``.
    A non-integral ``Decimal`` (e.g. ``2024.5``) is not a year. ``bool`` and
    ``float`` are excluded — bool is never a year, and float years don't occur
    in practice. Empty input is not year-shaped. Shared by compile-time bar
    orientation/axis inference and render-time time-unit detection so both
    agree on what counts as a year.
    """
    if not samples:
        return False
    for v in samples:
        if isinstance(v, bool):
            return False
        if isinstance(v, int):
            if not (_YEAR_MIN <= v <= _YEAR_MAX):
                return False
        elif isinstance(v, Decimal):
            if v != v.to_integral_value() or not (_YEAR_MIN <= v <= _YEAR_MAX):
                return False
        elif isinstance(v, str) and _YEAR_STRING_PATTERN.match(v):
            if not (_YEAR_MIN <= int(v) <= _YEAR_MAX):
                return False
        else:
            return False
    return True


def is_date_like(value: Any) -> bool:
    """Return True for date-like values: Python date/datetime objects or
    string values matching date patterns.

    Recognized string patterns: ISO (2024-03, 2024-03-15), US (03/15/2024),
    short month name (Mar 15), long form (Mar 15, 2024), euro
    (15 Mar 2024), quarter (Q1 2024), year (2024).

    Accepts datetime.date / datetime.datetime directly so that layout
    decisions (right-align, tabular font, no-wrap) apply to native Python
    temporal objects returned by DuckDB fetchall(), not just pre-formatted
    strings.

    Cell-scope date detector used by the table renderer and by
    classify_date_column_align for column-level alignment. Does not accept
    full month names ("15 January 2024") — a known gap; widening this
    pattern is a separate decision from any single caller.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (date, datetime)):
        return True
    if not isinstance(value, str) or not value:
        return False
    return bool(_DATE_RE.match(value.strip()))


def classify_date_column_align(values: Sequence[Any]) -> Literal["right"] | None:
    """Return "right" iff every non-null value in a table column is
    date-like, else None (no verdict).

    A table column is not a set of independently-aligned cells: a per-cell
    date match is not sufficient to right-align the whole column, because
    the same column can mix formats a date detector only partially
    recognizes (e.g. "9 May 2026" matches, "30 March 2026" doesn't) and a
    per-cell decision then renders one column with two different
    text-anchors. Only a unanimous match earns a verdict; anything else
    (mixed content, non-date content, an empty column) returns None and
    the caller's normal alignment default applies.

    Null/blank cells don't count against the verdict — the caller renders
    them as a placeholder regardless of column alignment.

    ``values`` are the raw executor rows resolve holds; render normalizes a
    non-JSON-native scalar (``normalize_scalar_for_json``, applied before
    any of render's own per-cell checks run) by calling ``str()`` on it. A
    bare ``datetime.date`` stringifies to a clean ISO date and still
    matches; a ``datetime.datetime`` always stringifies with a time
    component (even at midnight), which the date patterns below don't
    match. Classifying a raw ``datetime.datetime`` as date-like without
    accounting for that would right-align a column whose cells render
    non-tabular, proportional-font text — this pre-stringifies exactly the
    values render will also stringify, so the two can't disagree on a value
    that renders as plain text once normalized.
    """
    non_null = [
        v
        for v in values
        if v is not None and not (isinstance(v, str) and not v.strip())
    ]
    if not non_null:
        return None
    normalized = [str(v) if isinstance(v, datetime) else v for v in non_null]
    return "right" if all(is_date_like(v) for v in normalized) else None


def format_error_summary(errors: list[str]) -> str:
    """Format a list of errors into a human-readable summary (first 5 shown)."""
    error_summary = f"Found {len(errors)} error(s):\n"
    for i, error in enumerate(errors[:5], 1):
        error_summary += f"{i}. {error}\n"
    if len(errors) > 5:
        error_summary += f"... and {len(errors) - 5} more errors\n"
    return error_summary


def normalize_data_for_json(data: Rows) -> Rows:
    """Normalize data types for JSON serialization.

    Converts dates, datetimes, Decimals, and other non-JSON-serializable types
    to JSON-compatible formats.
    """
    normalized: Rows = []
    for row in data:
        normalized_row: dict[str, Any] = {}
        for key, value in row.items():
            if value is None:
                normalized_row[key] = None
            elif isinstance(value, (int, float, str, bool)):
                normalized_row[key] = value
            elif isinstance(value, Decimal):
                normalized_row[key] = float(value)
            elif isinstance(value, (date, datetime)):
                normalized_row[key] = value.isoformat()
            else:
                normalized_row[key] = str(value)
        normalized.append(normalized_row)
    return normalized


def domain_sort_aggregates(
    rows: Rows,
    x_field: str,
    sort_field: str,
) -> dict[Hashable, float]:
    """Per-x-category sum of ``sort_field`` for domain ordering.

    Shared by ``stacked_x_domain_order`` (every caller is a genuinely stacked
    plot, where Vega-Lite's ``EncodingSortField.op`` defaults to ``sum``) and
    the render layer's ``x_domain._sort_domain_by_field``. The latter is only ever
    reached with a truthy x-encoding sort, which only the bar emitter's
    vertical x ever carries — the bar emitter's measure (y) channel never
    emits ``stack: null`` for a categorical x (stacked bars set an explicit
    ``stack: "zero"``; grouped bars on a categorical x use ``xOffset``
    instead, not an unstacked ``y`` — the unstacked case is reserved for a
    genuinely continuous x, which never reaches this sort-domain path), so
    ``sum`` is correct there too.

    Uses ``coerce_numeric_cell`` for type-safe coercion: handles int/float/
    Decimal and numeric strings (the real shape warehouse rows arrive in —
    some adapters return measure columns as strings). Returns only x values
    that have at least one finite numeric ``sort_field`` value.
    """
    by_category: dict[Hashable, list[float]] = {}
    for row in rows:
        x = row.get(x_field)
        if x is None:
            continue
        val = coerce_numeric_cell(row.get(sort_field))
        if val is not None:
            by_category.setdefault(x, []).append(val)
    return {x: sum(vals) for x, vals in by_category.items()}


def stacked_x_domain_order(
    rows: Rows, x_field: str, sort_by: str, descending: bool
) -> list[Hashable]:
    """The categorical x domain of a *stacked* plot, in Vega-Lite's render order.

    Shared by the resolve-time labelling predicate and the render-time label
    anchors, which must agree on which column is first and last or the labels
    name a bar the reader is not looking at.

    An empty ``sort_by`` means no authored sort, and VL orders a discrete
    domain by its own values. Otherwise VL sorts by the named field, and
    ``EncodingSortField.op`` defaults to ``sum`` — so this totals the field
    per category. Every caller here is a genuinely stacked path; a caller
    whose plot sets ``stack: null`` would need Vega-Lite's ``min`` default
    instead, which this function does not compute.

    A category with no value for the sort field keeps its domain-value
    position at the end, which is where VL puts it.
    """
    xs = sorted({row[x_field] for row in rows if row.get(x_field) is not None})
    if not sort_by:
        return xs
    totals = domain_sort_aggregates(rows, x_field, sort_by)
    ranked = [x for x in xs if x in totals]
    ranked.sort(key=lambda x: totals[x], reverse=descending)
    return ranked + [x for x in xs if x not in totals]


def layered_endpoint_rail_shape(
    x: str | list[str] | None, y: str | list[str] | None
) -> bool:
    """True when x/y are both plain scalar columns.

    Shared by the resolve-time y-axis auto-orient (``_bake_ay_orient`` in
    compile/resolve/chart/_axes.py) and the render-time firing gate
    (``EndpointLabelFeature.applies_to`` in
    render/chart/features/endpoint_labels.py), which must agree on whether a
    layered chart's endpoint-label rail can fire at all — otherwise the axis
    flips left for a pane that never renders. The layered rail
    (``EndpointLabelFeature._apply_layered_single_series``) anchors one shared
    y-scale off a single base x/y pair; a folded wide y (list) or an absent
    x/y has no single endpoint to draw the base series' own anchor from.
    """
    return isinstance(x, str) and isinstance(y, str)


def layered_endpoint_rail_fires(
    shape_ok: bool, layer_is_colorless: Sequence[bool]
) -> bool:
    """True when the layered single-series endpoint-label rail can fire.

    The single answer to "which series will the rail actually name?",
    shared by compile's resolve-time gates (``_bake_ay_orient``,
    ``_suppress_legend_for_endpoint_labels`` in compile/resolve/chart/_axes.py)
    and render's firing gate (``EndpointLabelFeature.applies_to`` in
    render/chart/features/endpoint_labels.py) — each call site must reach
    the same verdict, or the axis flips/legend suppresses for a rail that
    renders differently than assumed.

    ``shape_ok`` is the caller's own ``layered_endpoint_rail_shape(x, y)``.
    ``layer_is_colorless`` is one ``layer.color is None`` per layer, in any
    order — this function owns the "at least one, and every one" combination
    so that fact isn't re-approximated three different ways at three call
    sites (the exact drift that caused two prior review rounds: a layer
    with its own colour field splits into several sub-series with no single
    endpoint to anchor one label on, ``_apply_layered_single_series`` skips
    it — so rather than naming only the colourless layers on the rail and
    leaving that one sub-series to the legend, the whole rail falls back to
    legend-only).
    """
    return shape_ok and bool(layer_is_colorless) and all(layer_is_colorless)
