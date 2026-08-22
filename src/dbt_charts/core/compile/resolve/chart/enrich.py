"""Chart enrichment: data-aware column classification and scale heuristics.

Stage: COMPILE
Purpose: classify query result columns and decide the y-axis zero baseline.

Key principle: every auto-decision is overridable by explicit YAML.
Authors override the zero baseline via style.axis_y.scale.continuous.zero.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from dbt_charts.core.utils import is_year_shaped

__all__ = [
    "ColumnProfile",
    "classify_column_type",
    "first_non_null_samples",
    "is_column_discrete_for_bar_orientation",
    "_is_numeric_string",
    "_is_temporal_value",
    "_pick_scale",
]

# Chart types where zero anchoring is optional; the smart-auto heuristic applies.
# Bar always extends to zero (absolute-magnitude encoding; truncated bars mislead).
# Area returns explicit zero:True at ratio ≤ threshold (not None) so the render-side
# domainMin pin fires and prevents blank space between 0 and the first tick.
_OPTIONAL_ZERO_CHART_TYPES = frozenset({"line", "scatter", "area"})

# Threshold for smart-auto zero extension.  When data_min/data_max <= this value,
# data starts in the bottom 25% of [0, max] and extending to zero adds honest
# context without crushing the data.  Above the threshold, keep the data-fitted
# domain.
_ZERO_EXTEND_THRESHOLD = 0.25


@dataclass
class ColumnProfile:
    """Lightweight profile of a query result column for zero-baseline heuristics."""

    min_val: float | None = None
    max_val: float | None = None


def _is_temporal_value(value: Any) -> bool:
    """Return True if value looks like a date/time string or object."""
    if isinstance(
        value, (datetime, date)
    ):  # datetime is a subclass of date; both covered
        return True
    if not isinstance(value, str):
        return False
    date_patterns = [
        r"^\d{4}-\d{2}-\d{2}",
        r"^\d{2}/\d{2}/\d{4}",
        r"^\d{2}-\d{2}-\d{4}",
        r"^\d{4}/\d{2}/\d{2}",
        r"^\w{3}\s+\d{1,2},?\s+\d{4}",
        r"^\d{4}-Q[1-4]$",
        r"^Q[1-4]\s*\d{4}$",
        r"^\d{4}Q[1-4]$",
        r"^\d{4}-\d{2}$",
        r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}$",
        r"^\d{4}-W\d{2}$",  # ISO 8601 week: 2024-W01
    ]
    return any(re.match(p, value, re.IGNORECASE) for p in date_patterns)


def _is_numeric_string(value: str) -> bool:
    """Return True if value is a string representation of a number."""
    try:
        float(value.replace(",", "").replace("$", "").replace("%", ""))
        return True
    except (ValueError, AttributeError):
        return False


def classify_column_type(
    column_name: str,
    sample_values: list[Any],
) -> str:
    """Classify a column as 'numeric', 'temporal', or 'categorical'."""
    name_lower = column_name.lower()
    temporal_patterns = [
        r"date",
        r"time",
        r"timestamp",
        r"created",
        r"updated",
        r"_at$",
        r"day",
        r"week",
        r"month",
        r"year",
        r"quarter",
        r"period",
    ]
    for pattern in temporal_patterns:
        if re.search(pattern, name_lower) and any(
            _is_temporal_value(v) for v in sample_values[:5]
        ):
            return "temporal"

    numeric_count = 0
    temporal_count = 0
    for val in sample_values:
        if isinstance(val, bool):
            # bool is a subclass of int — exclude it before the numeric branch
            # so booleans are not miscounted as numeric.
            pass
        elif isinstance(val, (int, float, Decimal)):
            numeric_count += 1
        elif isinstance(val, datetime):
            temporal_count += 1
        elif isinstance(val, str):
            if _is_temporal_value(val):
                temporal_count += 1
            elif _is_numeric_string(val):
                numeric_count += 1

    total = len(sample_values)
    if total == 0:
        return "categorical"
    if numeric_count / total > 0.8:
        return "numeric"
    if temporal_count / total > 0.8:
        return "temporal"
    return "categorical"


def is_column_discrete_for_bar_orientation(
    samples: list[int | float | Decimal | str | bool | date | datetime],
) -> bool:
    """True iff the column is categorical → bar x-axis should be horizontal.

    Strict: a Python ``str`` value is discrete even if it parses as a number.
    The database returned a string (VARCHAR/TEXT), so that is the declared type.
    Coercing ``"123"`` to numeric here would be a hidden data transformation.

    Rules:
    - ``int`` / ``float`` / ``Decimal`` (not bool) → continuous → False
    - ``datetime.date`` / ``datetime.datetime`` → continuous → False
    - Temporal-looking strings (``_is_temporal_value``) → continuous → False
    - Year-shaped strings (``is_year_shaped``) → continuous → False
    - Any other ``str`` or ``bool`` → discrete → True
    - Empty → False (no data to classify)

    Callers must pre-filter None values; None is not a valid sample.
    """
    if not samples:
        return False
    if is_year_shaped(samples):
        return False
    for v in samples:
        if isinstance(v, bool):
            return True  # bool is not a numeric axis
        if isinstance(v, (int, float, Decimal, date, datetime)):
            continue  # native numeric/temporal → continuous
        if _is_temporal_value(v):
            continue  # temporal-looking string → continuous
        return True  # non-temporal string → discrete
    return False


def first_non_null_samples(
    field: str, data: list[dict[str, Any]], limit: int = 20
) -> list[Any]:
    """Return up to `limit` non-null values of `field`, scanning rows in order.

    Slicing `data[:limit]` before filtering nulls starves the sample when the
    first rows happen to be null — this walks rows until `limit` values are
    collected (or the data is exhausted).
    """
    samples: list[Any] = []
    for row in data:
        value = row.get(field)
        if value is not None:
            samples.append(value)
            if len(samples) == limit:
                break
    return samples


def _pick_scale(
    profile: ColumnProfile, chart_type: str | None = None
) -> dict[str, Any] | None:
    """Decide the explicit zero setting for the y-axis scale.

    Returns ``{"zero": False}`` to keep the domain data-fitted, ``{"zero": True}``
    to extend to zero, or ``None`` when zero is not relevant (data spans or
    touches zero, or no data profiled).

    Optional-zero chart types (line, scatter, area): smart-auto heuristic.
    Extend to zero when data_min/data_max <= 0.25 (data starts in the bottom
    quarter of [0, max]).  Return zero:False when data lives far from zero.
    Area at ratio ≤ threshold returns an explicit True (not None) so that the
    render-side domainMin pin fires and prevents a blank gap below the first
    tick when VL extends the domain to 0.

    Non-optional-zero types (bar only): always extend to zero for all-positive
    data — bar marks encode absolute magnitude and suppressing zero produces
    truncated bars (a known misleading chart pattern).

    Returning an explicit True/False here means resolved_chart.zero carries
    the full intent; the render layer does not need to know chart-type
    defaults in VL.

    All-negative data (max < 0): out of scope — skip the heuristic.
    """
    if profile.min_val is None or profile.max_val is None:
        return None
    if profile.max_val == 0:
        return None
    # Negative-spanning or all-negative: zero already in domain, or out of scope.
    if profile.min_val < 0:
        return None

    if chart_type in _OPTIONAL_ZERO_CHART_TYPES:
        # Smart-auto: keep data-fitted when data lives too far from zero.
        ratio = profile.min_val / profile.max_val
        if ratio > _ZERO_EXTEND_THRESHOLD:
            return {"zero": False}
        # Data is close to zero — extend to zero.
        # Area charts need an explicit True (not None) so that the render-side
        # domainMin pin fires and closes the blank gap between 0 and the first tick.
        # Line/scatter have no zero:true VL default so None is safe there.
        if chart_type == "area":
            return {"zero": True}
        return None

    # Non-optional-zero types (bar only) with all-positive data: return
    # explicit True so resolved_chart.zero carries the intent and the render
    # layer needs no chart-type knowledge to decide domain pinning.
    if profile.min_val > 0:
        return {"zero": True}

    return None
