"""Predicate-based time-unit detection and smart-default labelExpr for temporal axes.

detect_time_unit: pure function; given distinct non-null x-field values,
returns the VL timeUnit string or None (continuous/sub-daily).

default_label_expr_for: returns a Vega expression for an
encoding time unit + label time unit pair.

Bucket string vocabulary (pattern → VL timeUnit):
  YYYY-MM         → yearmonth   (2024-01)
  Mon YYYY        → yearmonth   (Jan 2024)
  MM/YYYY         → yearmonth   (01/2024, US-only)
  YYYY-Qn         → yearquarter (2024-Q1, canonical ISO quarter)
  Qn YYYY         → yearquarter (Q1 2024)
  YYYYQn          → yearquarter (2024Q1)
  FYnnnn          → year        (FY2024 → Jan 1)
  MM/DD/YYYY      → yearmonthdate (01/15/2024, US-only)
  Mon DD[,] YYYY  → yearmonthdate (Jan 15, 2024)
  YYYY-Www        → yearweek    (2024-W01, canonical ISO week)
  W[eek ]N YYYY   → yearweek    (W32 2024, Week 32 2024)
  Half-year (H1 YYYY, YYYY-H1): not supported; treated as unparseable.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import re
import statistics
from collections.abc import Iterable
from typing import Any

from dbt_charts.core.font_measure import FontMeasurer
from dbt_charts.core.render.chart.artifacts import ChartRenderData
from dbt_charts.core.text.format_d3 import portable_strftime
from dbt_charts.core.utils import is_year_shaped

# ISO date: "2024-01-15"
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ISO datetime with T separator ("2024-01-15T14:30:00") or space from DB driver str()
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")
# ISO week-year: "2024-W32" (weeks 01–53)
_ISO_WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")
# Calendar quarter: "2024-Q3"
_ISO_QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")

# ── Bucket-string patterns ──────────────────────────────────────────────────
# YYYY-MM: 2024-01 (valid month 01-12)
_YEARMONTH_STR_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# Mon YYYY: Jan 2024
_MON_YYYY_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$", re.IGNORECASE
)
# MM/YYYY: 01/2024 (US month/year)
_MM_YYYY_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{4})$")
# Qn YYYY: Q1 2024 (space optional)
_Q_YYYY_RE = re.compile(r"^Q([1-4])\s*(\d{4})$", re.IGNORECASE)
# YYYYQn: 2024Q1
_YYYY_Q_RE = re.compile(r"^(\d{4})Q([1-4])$", re.IGNORECASE)
# FYnnnn: FY2024
_FY_RE = re.compile(r"^FY(\d{4})$", re.IGNORECASE)
# MM/DD/YYYY: 01/15/2024 (US month/day/year)
_MM_DD_YYYY_RE = re.compile(r"^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(\d{4})$")
# Mon DD[,] YYYY: Jan 15, 2024 or Jan 15 2024
_MON_DD_YYYY_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})$",
    re.IGNORECASE,
)
# W[eek ]N YYYY: W32 2024, Week 32 2024
_WEEK_SPELLED_RE = re.compile(r"^W(?:eek\s*)?(\d{1,2})\s+(\d{4})$", re.IGNORECASE)

_MONTH_ABBR: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_QUARTER_FIRST_MONTH_LOOKUP: dict[int, int] = {1: 1, 2: 4, 3: 7, 4: 10}

# Ordered family list: (name, regex).  First match wins in _classify_bucket.
_BUCKET_FAMILIES: list[tuple[str, re.Pattern[str]]] = [
    ("iso_week", _ISO_WEEK_RE),
    ("iso_quarter", _ISO_QUARTER_RE),
    ("yearmonth_str", _YEARMONTH_STR_RE),
    ("mon_yyyy", _MON_YYYY_RE),
    ("mm_yyyy", _MM_YYYY_RE),
    ("q_yyyy", _Q_YYYY_RE),
    ("yyyy_q", _YYYY_Q_RE),
    ("fy", _FY_RE),
    ("mm_dd_yyyy", _MM_DD_YYYY_RE),
    ("mon_dd_yyyy", _MON_DD_YYYY_RE),
    ("week_spelled", _WEEK_SPELLED_RE),
]


def _classify_bucket(v: str) -> str | None:
    """Return the format-family name for a bucket string, or None."""
    for name, pattern in _BUCKET_FAMILIES:
        if pattern.match(v):
            return name
    return None


def _parse_bucket_string(value: str) -> dt.date | None:
    """Return the anchor date (first instant of bucket) for a labeled format.

    Returns None for unrecognized strings. Does NOT raise — invalid ISO weeks
    that pass the regex (e.g. W53 in a 52-week year) return None here; the
    error is raised only by the explicit ``_week_to_iso`` converter used in
    ``normalize_labeled_temporal``.
    """
    if _YEARMONTH_STR_RE.match(value):
        return dt.date(int(value[:4]), int(value[5:7]), 1)
    m = _MON_YYYY_RE.match(value)
    if m:
        month = _MONTH_ABBR[m.group(1).lower()]
        return dt.date(int(m.group(2)), month, 1)
    m = _MM_YYYY_RE.match(value)
    if m:
        return dt.date(int(m.group(2)), int(m.group(1)), 1)
    m = _Q_YYYY_RE.match(value)
    if m:
        return dt.date(int(m.group(2)), _QUARTER_FIRST_MONTH_LOOKUP[int(m.group(1))], 1)
    m = _YYYY_Q_RE.match(value)
    if m:
        return dt.date(int(m.group(1)), _QUARTER_FIRST_MONTH_LOOKUP[int(m.group(2))], 1)
    m = _FY_RE.match(value)
    if m:
        return dt.date(int(m.group(1)), 1, 1)
    m = _MM_DD_YYYY_RE.match(value)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = _MON_DD_YYYY_RE.match(value)
    if m:
        month = _MONTH_ABBR[m.group(1).lower()]
        try:
            return dt.date(int(m.group(3)), month, int(m.group(2)))
        except ValueError:
            return None
    m = _WEEK_SPELLED_RE.match(value)
    if m:
        week, year = int(m.group(1)), int(m.group(2))
        try:
            return dt.date.fromisocalendar(year, week, 1)
        except ValueError:
            return None
    # ISO week/quarter: delegate to existing helpers (avoid duplication);
    # return None on invalid week numbers (the convert path raises separately).
    if _ISO_WEEK_RE.match(value):
        year, week = int(value[:4]), int(value[6:])
        try:
            return dt.date.fromisocalendar(year, week, 1)
        except ValueError:
            return None
    if _ISO_QUARTER_RE.match(value):
        q = int(value[6])
        return dt.date(int(value[:4]), _QUARTER_FIRST_MONTH_LOOKUP[q], 1)
    return None


_TIME_UNIT_TO_VL: dict[str, str] = {
    "monthofyear": "month",
    "dayofweek": "day",
    "dayofmonth": "date",
    "dayofyear": "dayofyear",
    "hourofday": "hours",
}

# Calendar-bucketed units → default ordinal scale.
# Distinct from time-part units (monthofyear etc.) which stay temporal.
BUCKETED_CALENDAR_UNITS: frozenset[str] = frozenset(
    {"year", "yearquarter", "yearmonth", "yearweek", "yearmonthdate"}
)

# Cyclic time-part units that remain temporal (not ordinal).
TIME_PART_UNITS: frozenset[str] = frozenset(_TIME_UNIT_TO_VL.keys())

# Label-cadence coarsening chain: when labels don't fit at the current grain,
# the overlap resolver steps one rung coarser and re-measures. day/week collapse
# to month, then quarter, then year. ``year`` is terminal.
_COARSER_LABEL_UNIT: dict[str, str | None] = {
    "yearmonthdate": "yearmonth",
    "yearweek": "yearmonth",
    "yearmonth": "yearquarter",
    "yearquarter": "year",
    "year": None,
}


def next_coarser_label_unit(label_unit: str) -> str | None:
    """Return the next-coarser bucketed label grain, or None if already coarsest.

    Drives the cadence ladder: day/week → month → quarter → year. ``year`` is
    terminal (None). Raises ValueError for any non-bucketed grain — cadence
    stepping only applies to BUCKETED_CALENDAR_UNITS, so a cyclic time-part unit
    (monthofyear, dayofweek, …) reaching here is a caller bug, not a no-op.
    """
    if label_unit not in _COARSER_LABEL_UNIT:
        raise ValueError(
            f"next_coarser_label_unit: {label_unit!r} is not a bucketed calendar "
            f"grain; cadence stepping applies only to "
            f"{sorted(BUCKETED_CALENDAR_UNITS)}"
        )
    return _COARSER_LABEL_UNIT[label_unit]


def _fiscal_month_is_year_start(d: dt.date, fiscal_year_start_month: int) -> bool:
    """True when ``d`` falls in the fiscal year's first month.

    Mirrors ``_fiscal_month_expr``'s ``fiscal_month === 0`` condition — only
    half of the real predicate ``_month_label``/``_quarter_label`` use to
    decide whether a tick's labelExpr stacks a year-context row under the
    month/quarter text. The full predicate is ``anchor || fiscal_month ===
    0``; ``anchor`` (true only for the domain's literal first tick) is the
    caller's responsibility — see ``_pair_clears``, which is the one place
    that knows whether a given tick is the leading or trailing flush edge.
    """
    return (d.month - fiscal_year_start_month) % 12 == 0


def _cadence_token_width(
    d: dt.date,
    format_tu: str,
    measurer: FontMeasurer,
    size: float,
    position: int,
    fiscal_year_start_month: int,
    *,
    carries_year_row: bool,
) -> float:
    """Rendered width of one label in its stable format vocabulary.

    ``carries_year_row`` says whether *this specific tick* paints the
    stacked year-context row under its month/quarter text — the real
    labelExpr condition is ``anchor || fiscal_month === 0``
    (``_month_label``/``_quarter_label``), where ``anchor`` is true only
    for the domain's literal first tick, regardless of what month it
    opens on. That condition can't be recomputed from ``d`` and
    ``fiscal_year_start_month`` alone, so the caller resolves it and
    passes the answer directly — see ``_pair_clears``, which knows
    whether a tick is the leading edge (``anchor`` always true when
    flushed) or the trailing edge (only ``fiscal_month === 0`` can apply).

    The row only ever widens the tick's *reach from a flush-anchored
    edge* — both rows share the edge's x position, so the wider row is
    what actually extends furthest from it. A centered (non-flushed)
    tick's year row sits one line below its neighbor's single-row label;
    it never overlaps horizontally with anything, so a centered width
    must stay row-1-only. Confirmed against a real render (a centered
    fiscal-boundary "Jan"/"2024" tick forced to stay at month cadence
    shows zero collision with the next month) — passing the wider width
    for the centered case produces a false positive collision and
    over-thins a chart no real render would thin.
    """
    if format_tu == "year":
        return measurer.measure(str(d.year), size)
    if format_tu == "yearquarter":
        width = measurer.measure(f"Q{(d.month - 1) // 3 + 1}", size)
        if carries_year_row:
            width = max(width, measurer.measure(str(d.year), size))
        return width
    if format_tu == "yearmonth":
        width = measurer.measure(d.strftime("%b"), size)
        if carries_year_row:
            width = max(width, measurer.measure(str(d.year), size))
        return width
    if format_tu == "yearweek":
        return measurer.measure(portable_strftime(d, "W%V"), size)
    if format_tu == "yearmonthdate":
        # _day_label renders two rows ("%-d" over a possibly-blank
        # month/year row) — measure that shape, not a single-row string
        # nothing draws.
        return max(
            measurer.measure(str(d.day), size),
            measurer.measure(
                day_week_context(d, format_tu, position, fiscal_year_start_month), size
            ),
        )
    raise ValueError(
        f"_cadence_token_width: {format_tu!r} is not a bucketed calendar grain"
    )


def _pair_clears(
    i: int,
    j: int,
    dates: list[dt.date],
    encoding_tu: str,
    format_tu: str,
    measurer: FontMeasurer,
    size: float,
    band: float,
    edge_labels_flushed: bool,
    fiscal_year_start_month: int,
) -> bool:
    """True when labeled buckets *i* and *j* (i < j) do not overlap.

    Vega flushes a temporal axis's literal first rendered tick (``dates[0]``)
    to the plot's left edge whenever the axis is flush-enabled — this is
    positional, not calendar-semantic. A weekly source value that opens a
    month label without landing on the calendar's day-1 boundary (e.g. the
    week of Jan 6) still gets flushed when it is genuinely the domain's
    first bucket, so it must reserve its full measured width there, not
    half (confirmed against a real render: ``playground/editorial-stress-test``'s
    ``line_pipeline`` chart flushes its "Jan" tick to ``text-anchor: start``
    even though the underlying date is Jan 6, not Jan 1).

    The trailing edge does not mirror this: a real render of a domain whose
    last bucket opens a label off the calendar boundary (e.g. a week
    landing on May 4) does not flush that tick full-width — Vega drops it
    from the axis entirely rather than widen it. Reserving full width there
    would over-detect collisions the real render never has, so the last
    tick keeps the calendar-boundary gate.

    The two flushed edges also disagree on the year-context row
    (``_cadence_token_width``'s ``carries_year_row``): the labelExpr's real
    condition is ``anchor || fiscal_month === 0``, and ``anchor`` is true
    only for the domain's literal first tick. The leading edge is always
    ``anchor`` when flushed — it carries the year row whatever month it
    opens on, so ``carries_year_row`` is unconditional there. The trailing
    edge is never ``anchor``; only a genuine fiscal-year-boundary date
    triggers the row there.
    """
    clearance = (j - i) * band
    left_flush = edge_labels_flushed and i == 0
    wi = _cadence_token_width(
        dates[i],
        format_tu,
        measurer,
        size,
        i,
        fiscal_year_start_month,
        carries_year_row=left_flush,
    )
    left_extent = wi if left_flush else wi / 2
    right_flush = (
        edge_labels_flushed
        and j == len(dates) - 1
        and _is_calendar_tick(dates[j], encoding_tu, format_tu, fiscal_year_start_month)
    )
    wj = _cadence_token_width(
        dates[j],
        format_tu,
        measurer,
        size,
        j,
        fiscal_year_start_month,
        carries_year_row=right_flush
        and _fiscal_month_is_year_start(dates[j], fiscal_year_start_month),
    )
    right_extent = wj if right_flush else wj / 2
    return left_extent + right_extent <= clearance


def _is_calendar_tick(
    date: dt.date,
    encoding_tu: str,
    format_tu: str,
    fiscal_year_start_month: int,
) -> bool:
    """Whether a labeled source value falls on Vega's calendar tick.

    Only the trailing edge in ``_pair_clears`` still needs this — see that
    function's docstring for why the leading edge no longer does.
    """
    if format_tu == "year":
        return date.day == 1 and (date.month - fiscal_year_start_month) % 12 == 0
    if format_tu == "yearquarter":
        return date.day == 1 and (date.month - fiscal_year_start_month) % 3 == 0
    if format_tu == "yearmonth":
        return date.day == 1
    if format_tu == "yearweek":
        return date.weekday() == 0
    return format_tu == encoding_tu


def temporal_visibility_fits(
    labeled: list[int],
    dates: list[dt.date],
    encoding_tu: str,
    format_tu: str,
    measurer: FontMeasurer,
    size: float,
    band: float,
    *,
    edge_labels_flushed: bool,
    fiscal_year_start_month: int,
) -> bool:
    """True when every consecutive pair of labeled buckets clears the gap.

    ``labeled`` is the opener set at this visibility grain.
    """
    if len(labeled) < 2:
        return True
    for k in range(len(labeled) - 1):
        i, j = labeled[k], labeled[k + 1]
        if not _pair_clears(
            i,
            j,
            dates,
            encoding_tu,
            format_tu,
            measurer,
            size,
            band,
            edge_labels_flushed,
            fiscal_year_start_month,
        ):
            return False
    return True


def resolve_temporal_label_visibility(
    dates: list[dt.date],
    encoding_time_unit: str,
    format_time_unit: str,
    measurer: FontMeasurer,
    font_size: float,
    band: float,
    fiscal_year_start_month: int = 1,
    allow_skip: bool = True,
    *,
    edge_labels_flushed: bool,
) -> tuple[str, bool]:
    """Return one render-local visibility step and whether its labels fit flat."""
    labeled = [
        i
        for i, d in enumerate(dates)
        if is_label_opener(
            d, encoding_time_unit, format_time_unit, fiscal_year_start_month
        )
    ]
    if temporal_visibility_fits(
        labeled,
        dates,
        encoding_time_unit,
        format_time_unit,
        measurer,
        font_size,
        band,
        edge_labels_flushed=edge_labels_flushed,
        fiscal_year_start_month=fiscal_year_start_month,
    ):
        return format_time_unit, True

    visibility = next_coarser_label_unit(format_time_unit) if allow_skip else None
    if visibility is None:
        return format_time_unit, False
    labeled = [
        i
        for i, d in enumerate(dates)
        if is_label_opener(d, encoding_time_unit, visibility, fiscal_year_start_month)
    ]
    return visibility, temporal_visibility_fits(
        labeled,
        dates,
        encoding_time_unit,
        format_time_unit,
        measurer,
        font_size,
        band,
        edge_labels_flushed=edge_labels_flushed,
        fiscal_year_start_month=fiscal_year_start_month,
    )


def _ordinal_axis_iso_value(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _ordinal_bucket_key(value: Any) -> str:
    """Date-only ISO string a row's x-value shares with its scaffold bucket.

    ``complete_ordinal_time_series`` enumerates buckets as date-only ISO
    strings (``bucket.isoformat()``) and looks up each row by this key, so a
    string value must collapse to the same date-only form as a `datetime`/
    `date` object — an ISO datetime string left as-is (``"2024-01-01T00:00:00"``)
    would never match its scaffold bucket (``"2024-01-01"``), and every row
    would synthesize as a missing (null) bucket.
    """
    parsed = _parse_date(value)
    if isinstance(parsed, dt.datetime):
        return parsed.date().isoformat()
    if isinstance(parsed, dt.date):
        return parsed.isoformat()
    return str(value)


def _parse_date(value: Any) -> dt.date | dt.datetime | None:
    """Parse value to date/datetime. Returns None if unparseable."""
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        if _ISO_DATETIME_RE.match(value):
            try:
                # Python <3.11: fromisoformat doesn't accept the trailing 'Z' UTC suffix.
                v = value[:-1] + "+00:00" if value.endswith("Z") else value
                return dt.datetime.fromisoformat(v)
            except ValueError:
                return None
        if _ISO_DATE_RE.match(value):
            try:
                return dt.date.fromisoformat(value)
            except ValueError:
                return None
        return _parse_bucket_string(value)
    return None


def detect_time_unit(values: list[Any]) -> str | None:
    """Detect VL timeUnit from distinct non-null x-field values.

    Returns one of: "year", "yearquarter", "yearmonth", "yearweek",
    "yearmonthdate", or None (sub-daily continuous or insufficient data).

    Raises ValueError when ≥10% of distinct values are unparseable strings.
    """
    distinct = list({v for v in values if v is not None})
    if len(distinct) < 2:
        return None

    parsed: list[dt.date | dt.datetime] = []
    bad: list[Any] = []
    for v in distinct:
        p = _parse_date(v)
        if p is None:
            bad.append(v)
        else:
            parsed.append(p)

    if bad and len(bad) / len(distinct) >= 0.1:
        examples = bad[:5]
        raise ValueError(
            f"Couldn't auto-detect timeUnit: ≥10% unparseable date values: {examples}. "
            "Set style.axis_x.time_unit explicitly or fix the query."
        )

    if not parsed or len(parsed) < 2:
        return None

    # Sub-daily fallthrough: any nonzero hms → continuous
    for p in parsed:
        if isinstance(p, dt.datetime) and (p.hour or p.minute or p.second):
            return None

    # Normalize to date for predicate checks
    dates = [p.date() if isinstance(p, dt.datetime) else p for p in parsed]

    # Predicate check: coarsest to finest
    if all(d.month == 1 and d.day == 1 for d in dates):
        return "year"
    if all(d.day == 1 and d.month in (1, 4, 7, 10) for d in dates):
        return "yearquarter"
    if all(d.day == 1 for d in dates):
        return "yearmonth"
    # Weekly cadence: every distinct value falls on the same weekday AND the
    # median consecutive gap is ≤ 14 days. The same-weekday check alone fires
    # on any 7-day-multiple spacing (28, 35, 42 … days); 28-day-spaced Sunday
    # data is not weekly data — it would enumerate ~78 weekly ordinal buckets
    # for 20 actual data points. The median gap gate rejects those cases and
    # returns None (continuous temporal) rather than falling through to
    # yearmonthdate, which would be worse (daily-bucket enumeration of the
    # same sparse span). Threshold ≤ 14 preserves the existing behaviour for
    # weekly series with occasional holiday skips (max gap 14 days, median 14).
    if len({d.weekday() for d in dates}) == 1:
        sorted_dates = sorted(dates)
        gaps = [
            (sorted_dates[i] - sorted_dates[i - 1]).days
            for i in range(1, len(sorted_dates))
        ]
        if statistics.median(gaps) <= 14:
            return "yearweek"
        # Same weekday but non-weekly spacing — no recognizable bucket grain.
        return None
    return "yearmonthdate"


_MIXED_LABEL_MSG = (
    "Couldn't auto-detect timeUnit: column contains mixed label and "
    "non-label values. "
    "Set style.axis_x.time_unit explicitly."
)


def _week_to_iso(v: str) -> str:
    year, week = int(v[:4]), int(v[6:])
    try:
        return dt.date.fromisocalendar(year, week, 1).isoformat()
    except ValueError as exc:
        raise ValueError(
            f"Couldn't auto-detect timeUnit: '{v}' is not a valid ISO week "
            f"(week {week} does not exist in year {year}). "
            "Set style.axis_x.time_unit explicitly or fix the query."
        ) from exc


def _quarter_to_iso(v: str) -> str:
    return dt.date(int(v[:4]), _QUARTER_FIRST_MONTH_LOOKUP[int(v[6])], 1).isoformat()


def _bucket_to_iso(v: str) -> str:
    """Convert any recognized bucket string to an ISO date string."""
    if _ISO_WEEK_RE.match(v):
        return _week_to_iso(v)
    if _ISO_QUARTER_RE.match(v):
        return _quarter_to_iso(v)
    anchor = _parse_bucket_string(v)
    if anchor is None:
        raise ValueError(
            f"Couldn't auto-detect timeUnit: unrecognized bucket format '{v}'. "
            "Set style.axis_x.time_unit explicitly or fix the query."
        )
    return anchor.isoformat()


def normalize_labeled_temporal(
    data: list[dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    """Convert labeled bucket strings in *field* to ISO dates.

    Supported formats: YYYY-Www, YYYY-Qn, Qn YYYY, YYYYQn, YYYY-MM,
    Mon YYYY, MM/YYYY, FYnnnn, MM/DD/YYYY, Mon DD YYYY, W[eek ]N YYYY.

    When all non-null values share the same format family, returns a copy
    with values replaced by the ISO date for the first instant of each
    bucket. Returns *data* unchanged when the field uses plain ISO dates
    or date/datetime objects (no labeling needed).

    Raises ValueError when:
    - labeled values are mixed with ISO date strings (or other non-labeled)
    - values span more than one format family (e.g. YYYY-Www with YYYY-Qn)
    - an ISO week label encodes an invalid week number
    """
    values = [row[field] for row in data if field in row and row[field] is not None]
    if not values:
        return data

    if is_year_shaped(values):
        return [
            (
                {**row, field: dt.date(int(row[field]), 1, 1).isoformat()}
                if field in row and row[field] is not None
                else row
            )
            for row in data
        ]

    def _is_iso(v: Any) -> bool:
        return isinstance(v, str) and bool(
            _ISO_DATE_RE.match(v) or _ISO_DATETIME_RE.match(v)
        )

    def _is_labeled(v: Any) -> bool:
        return isinstance(v, str) and not _is_iso(v) and _classify_bucket(v) is not None

    labeled = [v for v in values if _is_labeled(v)]
    if not labeled:
        return data

    # Any ISO dates mixed in → mixed label error
    if any(_is_iso(v) for v in values):
        raise ValueError(_MIXED_LABEL_MSG)

    # Any unrecognized strings mixed in → mixed label error
    if len(labeled) < len(values):
        raise ValueError(_MIXED_LABEL_MSG)

    # All are labeled — check they're all the same format family
    families = {_classify_bucket(v) for v in labeled}
    if len(families) > 1:
        raise ValueError(_MIXED_LABEL_MSG)

    return [
        (
            {**row, field: _bucket_to_iso(row[field])}
            if field in row and row[field] is not None
            else row
        )
        for row in data
    ]


def calendar_bucket_key(value: Any) -> dt.datetime | None:
    """Return the instant ``value`` denotes, or None if it denotes none.

    Identity for a band on a shared calendar x domain. Two spellings of one
    instant — a date-only ``2023-01-01`` and the ``2023-01-01T00:00:00+00:00``
    a timezone-aware datetime isoformats to — are the same band, and counting
    them twice measures a scale that isn't the one rendering.

    Deliberately the *instant*, not the calendar day: a sub-daily column
    (six-hourly readings, say) puts several genuinely distinct bands inside one
    day, and keying on the day would collapse eight rendered bands to two —
    mis-measuring the axis in exactly the direction this module exists to
    prevent. Everything is normalized to a naive UTC datetime so the two
    spellings above still compare equal.

    ``detect_time_unit`` and the label-cadence helpers all reach values through
    ``_parse_date``, so identity and membership are decided by that same
    parser rather than by a "looks like a date" pattern: the two genuinely
    disagree — the half-year forms (``2024-H1``, ``H1 2024``) are date-shaped
    but unparseable, and timezone-aware ISO strings are parseable but match no
    pattern.
    """
    parsed = _parse_date(value)
    if parsed is None:
        return None
    if not isinstance(parsed, dt.datetime):
        return dt.datetime.combine(parsed, dt.time.min)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)


def ordinal_axis_values(
    data: list[dict[str, Any]],
    field: str,
) -> list[Any] | None:
    """Return sorted distinct x-values for a bucketed-time ordinal axis.

    Returns the full encoding-grain domain. The x-encoding builder filters it
    to calendar openers when the resolved label-format time unit is coarser.
    Width-driven visibility thinning does not filter ticks.

    Returns None when the field has no non-null values.
    """
    values = sorted(
        {
            _ordinal_axis_iso_value(row[field])
            for row in data
            if field in row and row[field] is not None
        }
    )
    return values if values else None


def enumerated_axis_values(
    values: Iterable[Any],
    time_unit: str,
    fiscal_year_start_month: int,
) -> list[str | dt.date | dt.datetime]:
    """Return every calendar bucket from the min to max date, inclusive.

    Unlike ``ordinal_axis_values`` (which only returns buckets a value
    actually occupies), this enumerates the full span regardless of which
    buckets are represented — for a continuous temporal scale, label-cadence
    ticks (a coarser "opener" period, e.g. month labels over weekly data) must
    be derivable from every represented period, not just the ones a query
    happened to return a row for. ``complete_ordinal_time_series`` used to
    guarantee this implicitly by scaffolding a row per bucket; a bucketed
    grain that skips that scaffold (continuous temporal, no gap-fill) must
    still enumerate the same span here.

    Takes the domain's values rather than rows: the span is a property of the
    x domain, which on a layered chart is the union across every layer, not
    the base series' own rows (``overlay_x_domain_values``).

    Returns an empty list when no value is non-null and parseable.
    """
    parsed_dates = [_parse_date(v) for v in values if v is not None]
    dates = [d.date() if isinstance(d, dt.datetime) else d for d in parsed_dates if d]
    if not dates:
        return []
    buckets = _enumerate_buckets(
        min(dates), max(dates), time_unit, fiscal_year_start_month
    )
    return [b.isoformat() for b in buckets]


def _next_bucket(date: dt.date, time_unit: str) -> dt.date:
    """Return the first date of the next bucket at the given grain.

    A fiscal offset does not change this step: once a bucket start is
    correctly anchored (see ``_floor_to_bucket_start``), advancing by a fixed
    +1/+3/+12-month increment preserves the anchor's month-of-year alignment
    regardless of which month the fiscal year starts in.
    """
    if time_unit == "yearmonthdate":
        return date + dt.timedelta(days=1)
    if time_unit == "yearweek":
        return date + dt.timedelta(weeks=1)
    if time_unit == "yearmonth":
        # Advance to first of the next month
        if date.month == 12:
            return dt.date(date.year + 1, 1, 1)
        return dt.date(date.year, date.month + 1, 1)
    if time_unit == "yearquarter":
        # Advance by 3 months
        new_month = date.month + 3
        if new_month > 12:
            return dt.date(date.year + 1, new_month - 12, 1)
        return dt.date(date.year, new_month, 1)
    if time_unit == "year":
        return dt.date(date.year + 1, 1, 1)
    raise ValueError(f"Unsupported time_unit for bucket stepping: {time_unit!r}")


def _floor_to_period_start(
    date: dt.date, period_months: int, start_month: int
) -> dt.date:
    """Floor date to the most recent period boundary of length period_months.

    Boundaries are the months {start_month, start_month + period_months, ...}
    (mod 12). Works in a month-index space shifted so start_month becomes the
    period origin, floors to a period_months multiple, then shifts back.
    """
    offset = start_month - 1
    total_months = date.year * 12 + (date.month - 1)
    shifted = total_months - offset
    floored_shifted = shifted - (shifted % period_months)
    floored_total = floored_shifted + offset
    year, month0 = divmod(floored_total, 12)
    return dt.date(year, month0 + 1, 1)


def _floor_to_bucket_start(date: dt.date, time_unit: str, start_month: int) -> dt.date:
    """Floor date to the start of its enclosing bucket for time_unit.

    Only `year` and `yearquarter` grains have configurable anchoring — a
    fiscal offset shifts which month opens the year/quarter. `yearmonth`
    buckets always start on day 1 (detect_time_unit requires day == 1 for
    every value in the yearmonth predicate), so flooring to day 1 is a safe
    no-op for real data and a correct floor for synthetic/authored min dates.
    `yearmonthdate` (daily) has no coarser boundary to floor to. `yearweek`
    has NO universal "day 1" the way months do — detect_time_unit accepts any
    consistent weekday as a week anchor (Sunday-start data is common, not just
    ISO Monday-start), so flooring to the ISO Monday would shift a
    Sunday-anchored week's bucket dates by up to 6 days. yearweek's bucket
    start is whatever weekday the data already uses — trust min_date as-is.
    """
    if time_unit == "year":
        return _floor_to_period_start(date, 12, start_month)
    if time_unit == "yearquarter":
        return _floor_to_period_start(date, 3, start_month)
    if time_unit == "yearmonth":
        return date.replace(day=1)
    if time_unit in ("yearweek", "yearmonthdate"):
        return date
    raise ValueError(f"Unsupported time_unit for bucket flooring: {time_unit!r}")


def _enumerate_buckets(
    min_date: dt.date,
    max_date: dt.date,
    time_unit: str,
    fiscal_year_start_month: int,
) -> list[dt.date]:
    """Return every bucket date from min_date's enclosing bucket to max_date."""
    buckets: list[dt.date] = []
    current = _floor_to_bucket_start(min_date, time_unit, fiscal_year_start_month)
    while current <= max_date:
        buckets.append(current)
        current = _next_bucket(current, time_unit)
    return buckets


_GAP_FILL_HANDLINGS = frozenset(
    {
        "linear",
        "step-after",
        "step-before",
        "step-center",
        "curve",
    }
)


def _smoothstep(t: float) -> float:
    """Hermite ease: 0 at t=0, 1 at t=1, flat derivatives at endpoints."""
    return t * t * (3.0 - 2.0 * t)


def _apply_gap_fill_handling(
    rows: list[dict[str, Any]],
    x_field: str,
    dim_fields: list[str],
    dim_combos: list[tuple[Any, ...]],
    measure_cols: list[str],
    mode: str,
) -> None:
    """Fill null measures on synthetic buckets; mutates ``rows`` in place."""
    key_to_row: dict[tuple[Any, ...], dict[str, Any]] = {}
    bucket_order: dict[str, int] = {}
    for row in rows:
        bkt = row[x_field]
        if bkt not in bucket_order:
            bucket_order[bkt] = len(bucket_order)
        combo = tuple(row.get(d) for d in dim_fields)
        key_to_row[(bkt, *combo)] = row

    all_buckets_sorted = sorted(bucket_order, key=lambda b: bucket_order[b])

    for combo in dim_combos:
        group_rows: list[dict[str, Any]] = []
        for bkt in all_buckets_sorted:
            key = (bkt, *combo)
            if key in key_to_row:
                group_rows.append(key_to_row[key])

        for col in measure_cols:
            n = len(group_rows)
            # Only observed (query) rows are anchors — not values filled in this pass.
            # Any non-null value is a valid anchor; arithmetic below raises loudly if
            # the value is non-numeric (e.g. a string) rather than silently skipping it.
            anchors = [idx for idx in range(n) if group_rows[idx][col] is not None]
            for i, row in enumerate(group_rows):
                if row[col] is not None:
                    continue
                left_anchors = [a for a in anchors if a < i]
                right_anchors = [a for a in anchors if a > i]
                left_idx = left_anchors[-1] if left_anchors else -1
                right_idx = right_anchors[0] if right_anchors else -1

                if mode == "step-after":
                    if left_idx >= 0:
                        row[col] = group_rows[left_idx][col]
                    continue

                if mode == "step-before":
                    if right_idx >= 0:
                        row[col] = group_rows[right_idx][col]
                    continue

                if left_idx < 0 or right_idx < 0:
                    continue

                left_val = group_rows[left_idx][col]
                right_val = group_rows[right_idx][col]
                gap_width = right_idx - left_idx
                gap_pos = i - left_idx
                t = gap_pos / gap_width

                if mode == "linear":
                    row[col] = left_val + (right_val - left_val) * t
                elif mode == "step-center":
                    mid = left_idx + gap_width / 2
                    row[col] = left_val if i < mid else right_val
                elif mode == "curve":
                    row[col] = left_val + (right_val - left_val) * _smoothstep(t)


def canonicalize_and_sort_ordinal_x(
    data: ChartRenderData, x_field: str
) -> ChartRenderData:
    """Rewrite ``x_field`` to a date-only ISO string and sort chronologically.

    Used when a bucketed calendar grain resolves to a continuous temporal
    scale and no missing-bucket synthesis is needed, but the other two
    ``complete_ordinal_time_series`` side effects still must apply: a raw
    date/datetime object or a non-date-only date-like string (e.g. an ISO
    datetime with a "T"/space time component) otherwise reaches the emitted
    spec unstringified or with a stray time component, which Vega's JS
    ``Date`` parser can read as local time, shifting every point by the
    runtime's UTC offset.
    """
    canonicalized: ChartRenderData = []
    for row in data:
        if x_field not in row or row[x_field] is None:
            canonicalized.append(row)
            continue
        canonicalized.append({**row, x_field: _ordinal_bucket_key(row[x_field])})
    return sorted(canonicalized, key=lambda row: str(row.get(x_field)))


def complete_ordinal_time_series(
    data: list[dict[str, Any]],
    x_field: str,
    time_unit: str,
    dim_fields: list[str],
    fill: str,
    fiscal_year_start_month: int,
) -> list[dict[str, Any]]:
    """Synthesize missing time-bucket rows so every bucket in [min, max] is present.

    For ordinal bucketed-time charts the engine must supply every bucket
    between the dataset's min and max so the ordinal x-axis has a slot for
    each period. Without this, missing buckets simply disappear from the axis.

    Args:
        data: rows from the query (non-empty; caller must guard empty datasets).
        x_field: the x-encoding column name (must be ISO date strings or
            datetime.date objects after normalize_labeled_temporal runs).
        time_unit: one of BUCKETED_CALENDAR_UNITS (year, yearquarter, yearmonth,
            yearweek, yearmonthdate).
        dim_fields: categorical dimension columns to cross-join over (e.g. the
            color/series field). Engine only cross-joins over values actually
            present in the data window.
        fill: "null" fills missing measure columns with None;
            "zero" fills with 0; interpolate-* modes fill interior synthetic
            buckets (see ``_GAP_FILL_HANDLINGS``).
        fiscal_year_start_month: calendar month (1=Jan..12=Dec) that anchors
            year/yearquarter bucket boundaries; 1 (default) is the calendar
            convention. Floors the enclosing bucket of the dataset's min date
            to this anchor before enumerating forward, so mid-period data
            (e.g. starting in March) still yields a full Jan/Apr/Jul/Oct-
            anchored (or fiscally-shifted) bucket range.

    Returns:
        A new list of dicts, sorted (bucket asc, dim_1 asc, …), with the
        original rows merged in. When no buckets are missing, returns data
        sorted by the same key. If data is empty, returns data unchanged.
    """
    if not data:
        return data

    # Collect all x values; parse to date for comparison
    raw_x_values = [
        row[x_field] for row in data if x_field in row and row[x_field] is not None
    ]
    if not raw_x_values:
        return data

    x_iso = [_ordinal_bucket_key(v) for v in raw_x_values]

    # Parse to dates for arithmetic
    parsed_dates: list[dt.date] = []
    for iso in x_iso:
        d = _parse_date(iso)
        if d is not None:
            parsed_dates.append(d.date() if isinstance(d, dt.datetime) else d)

    if not parsed_dates:
        return data

    min_date = min(parsed_dates)
    max_date = max(parsed_dates)
    all_buckets = _enumerate_buckets(
        min_date, max_date, time_unit, fiscal_year_start_month
    )

    # Determine distinct dimension values from actual data
    dim_values: list[list[Any]] = []
    for dim in dim_fields:
        seen: list[Any] = []
        seen_set: set[Any] = set()
        for row in data:
            v = row.get(dim)
            if v not in seen_set:
                seen_set.add(v)
                seen.append(v)
        dim_values.append(sorted(seen, key=lambda x: (x is None, x)))

    # Identify measure columns: all non-x, non-dim columns
    sample_keys = list(data[0].keys())
    dim_set = set(dim_fields) | {x_field}
    measure_cols = [k for k in sample_keys if k not in dim_set]

    # For fill modes other than "zero", synthesized rows start as None; the
    # second pass (_apply_gap_fill_handling) overwrites them for interior gaps.
    fill_value = 0 if fill == "zero" else None

    # Build lookup from (bucket_str, *dim_vals) → row
    def _row_key(row: dict[str, Any]) -> tuple[Any, ...]:
        return (_ordinal_bucket_key(row.get(x_field)),) + tuple(
            row.get(d) for d in dim_fields
        )

    existing: dict[tuple[Any, ...], dict[str, Any]] = {
        _row_key(row): row for row in data
    }

    # Generate full scaffold via cross-product of buckets × dim combinations
    if dim_fields:
        dim_combos: list[tuple[Any, ...]] = list(itertools.product(*dim_values))
    else:
        dim_combos = [()]

    result: list[dict[str, Any]] = []
    for bucket in all_buckets:
        bucket_str = bucket.isoformat()
        for combo in dim_combos:
            key = (bucket_str,) + combo
            if key in existing:
                row = dict(existing[key])
                row[x_field] = bucket_str
                result.append(row)
            else:
                # Synthesize a row: bucket value + dim values + filled measures
                synth: dict[str, Any] = {x_field: bucket_str}
                for dim, val in zip(dim_fields, combo, strict=True):
                    synth[dim] = val
                for col in measure_cols:
                    synth[col] = fill_value
                result.append(synth)

    if fill in _GAP_FILL_HANDLINGS:
        _apply_gap_fill_handling(
            result, x_field, dim_fields, dim_combos, measure_cols, fill
        )

    return result


def _opens_fiscal_period(date: dt.date, period_length: int, start_month: int) -> bool:
    """True when date.month opens a fiscal period of period_length months.

    period_length=12 → year boundary; period_length=3 → quarter boundary.
    start_month=1 (default) reproduces the plain calendar check
    (month == 1, or month % 3 == 1 for quarters).
    """
    return (date.month - start_month) % period_length == 0


def is_label_opener(
    date: dt.date,
    encoding_unit: str,
    label_unit: str,
    fiscal_year_start_month: int = 1,
) -> bool:
    """Return True when *date* opens a new label period.

    Python-boolean mirror of ``opens_label_period``'s JS gate — used by the
    overlap resolver to decide which bucket indices carry a label.

    fiscal_year_start_month (1=Jan..12=Dec, default 1) shifts the year/quarter
    boundary check for the "year"/"yearquarter" label cadences; it is a no-op
    for "yearmonth"/"yearweek"/"yearmonthdate".
    """
    if label_unit == "year":
        is_year_open = _opens_fiscal_period(date, 12, fiscal_year_start_month)
        if encoding_unit in {"yearweek", "yearmonthdate"}:
            return is_year_open and date.day <= 7
        return is_year_open and date.day == 1
    if label_unit == "yearquarter":
        is_quarter_open = _opens_fiscal_period(date, 3, fiscal_year_start_month)
        if encoding_unit == "yearweek":
            return is_quarter_open and date.day <= 7
        if encoding_unit == "yearmonthdate":
            return is_quarter_open and date.day == 1
        return is_quarter_open and date.day == 1  # yearmonth
    if label_unit == "yearmonth":
        if encoding_unit == "yearweek":
            return date.day <= 7
        if encoding_unit == "yearmonthdate":
            return date.day == 1
    if label_unit == "yearweek" and encoding_unit == "yearmonthdate":
        return date.weekday() == 0
    return True  # same cadence or unknown — include all


def label_opener_values(
    values: list[str | dt.date | dt.datetime],
    encoding_unit: str,
    label_unit: str,
    fiscal_year_start_month: int,
) -> list[str | dt.date | dt.datetime]:
    """Return values whose dates open a label period."""
    openers: list[str | dt.date | dt.datetime] = []
    for value in values:
        parsed = _parse_date(value)
        if parsed is None:
            continue
        date = parsed.date() if isinstance(parsed, dt.datetime) else parsed
        if is_label_opener(date, encoding_unit, label_unit, fiscal_year_start_month):
            openers.append(value)
    return openers


def vl_time_unit(time_unit: str) -> str:
    """Return the Vega-Lite timeUnit for a Dataface time_unit value.

    Chronological grains return their UTC variant (utcyearmonth etc.) so VL
    bucketing stays UTC-aligned regardless of the renderer's TZ.  Time-part
    units (monthofyear, dayofweek, hourofday, …) are cyclic and have no utc*
    sibling — they pass through via _TIME_UNIT_TO_VL.
    """
    if time_unit in BUCKETED_CALENDAR_UNITS:
        return f"utc{time_unit}"
    return _TIME_UNIT_TO_VL.get(time_unit, time_unit)


def resolve_label_time_unit(
    encoding_time_unit: str | None, authored_label_time_unit: str | None
) -> str | None:
    """Return the authored label format or inherit the encoding grain.

    ``None``/``auto`` inherit the encoding vocabulary. Render-time layout may
    promote daily or weekly labels to months when the native labels do not fit
    and the domain crosses multiple months. ``none`` disables Dataface's smart
    label expression.
    """
    if authored_label_time_unit == "none":
        return None
    if authored_label_time_unit not in (None, "auto"):
        return authored_label_time_unit
    return encoding_time_unit


def _fiscal_month_expr(month_fn: str, v: str, fiscal_year_start_month: int) -> str:
    """Vega expression for the 0-indexed fiscal month (0 = fiscal year start).

    ``month_fn`` returns VL's 0-indexed calendar month (0=Jan..11=Dec); shift
    it so 0 lines up with ``fiscal_year_start_month`` instead of January. At
    the default offset (start month 1) this returns the bare calendar-month
    expression unchanged, so generated labelExpr strings are byte-identical
    to the pre-fiscal-offset output.
    """
    offset = fiscal_year_start_month - 1
    if offset == 0:
        return f"{month_fn}({v})"
    return f"(({month_fn}({v}) - {offset} + 12) % 12)"


def _year_context_row(main_label: str, year_context: str, inline: bool) -> str:
    """Combine a month/quarter label with its year context for one tick.

    Stacked (``[main, context]``) by default — Vega renders a two-element
    array as a two-row label. At a full-vertical tilt that stacking axis
    rotates onto the horizontal, so the context row spills into the
    neighboring tick; ``inline`` flows it onto one row instead, year first
    (``2024 Jan``, ``2024 Q1``).
    """
    if inline:
        return f"{year_context} + ' ' + {main_label}"
    return f"[{main_label}, {year_context}]"


def _year_label(
    v: str,
    fmt: str,
    _month: str,
    _date: str,
    _fiscal_year_start_month: int,
    _anchor: str,
    _inline: bool,
) -> str:
    return f"{fmt}({v}, '%Y')"


def _month_label(
    v: str,
    fmt: str,
    month: str,
    _date: str,
    fiscal_year_start_month: int,
    anchor: str,
    inline: bool,
) -> str:
    fiscal_month = _fiscal_month_expr(month, v, fiscal_year_start_month)
    month_label = f"{fmt}({v}, '%b')"
    with_year = _year_context_row(month_label, f"{fmt}({v}, '%Y')", inline)
    return f"({anchor} || {fiscal_month} === 0) ? ({with_year}) : {month_label}"


def _quarter_label(
    v: str,
    fmt: str,
    month: str,
    _date: str,
    fiscal_year_start_month: int,
    anchor: str,
    inline: bool,
) -> str:
    fiscal_month = _fiscal_month_expr(month, v, fiscal_year_start_month)
    quarter_label = f"'Q' + (floor({fiscal_month}/3) + 1)"
    with_year = _year_context_row(quarter_label, f"{fmt}({v}, '%Y')", inline)
    return f"({anchor} || {fiscal_month} === 0) ? ({with_year}) : {quarter_label}"


def _day_number_label(
    v: str,
    fmt: str,
    month: str,
    fiscal_year_start_month: int,
    anchor: str,
    opens_month: str,
    inline: bool,
) -> str:
    fiscal_month = _fiscal_month_expr(month, v, fiscal_year_start_month)
    day_label = f"{fmt}({v}, '%-d')"
    year_token = f"{fmt}({v}, '%b') + \"'\" + {fmt}({v}, '%y')"
    carries_year = f"({anchor} || ({opens_month} && {fiscal_month} === 0))"
    row_two = f"{carries_year} ? {year_token} : ({opens_month} ? {fmt}({v}, '%b') : '')"
    if inline:
        return f"{day_label} + (({row_two}) ? ' ' + ({row_two}) : '')"
    return f"[{day_label}, {row_two}]"


def _week_label(
    v: str,
    fmt: str,
    month: str,
    date: str,
    fiscal_year_start_month: int,
    anchor: str,
    inline: bool,
) -> str:
    return _day_number_label(
        v,
        fmt,
        month,
        fiscal_year_start_month,
        anchor,
        f"{date}({v}) <= 7",
        inline,
    )


def _day_label(
    v: str,
    fmt: str,
    month: str,
    date: str,
    fiscal_year_start_month: int,
    anchor: str,
    inline: bool,
) -> str:
    return _day_number_label(
        v,
        fmt,
        month,
        fiscal_year_start_month,
        anchor,
        f"{date}({v}) === 1",
        inline,
    )


def day_week_context(
    date: dt.date,
    format_time_unit: str,
    position: int,
    fiscal_year_start_month: int,
) -> str:
    """Python mirror of ``_day_number_label``'s row-two text (``_week_label``/
    ``_day_label`` above): ``%b'%y`` on the anchor or fiscal-year-opening
    tick, bare ``%b`` on a month opener, otherwise blank. Render-layer width
    measurement calls this so it measures what actually gets drawn."""
    opens_month = date.day <= 7 if format_time_unit == "yearweek" else date.day == 1
    carries_year = position == 0 or (
        opens_month and (date.month - fiscal_year_start_month) % 12 == 0
    )
    if carries_year:
        return date.strftime("%b'%y")
    return date.strftime("%b") if opens_month else ""


def opens_label_period(
    encoding_time_unit: str,
    label_time_unit: str,
    fiscal_year_start_month: int,
    v: str = "datum.value",
    month: str = "month",
    date: str = "date",
) -> str | None:
    if label_time_unit == "yearquarter" and encoding_time_unit in {
        "yearmonth",
        "yearweek",
        "yearmonthdate",
    }:
        fiscal_month = _fiscal_month_expr(month, v, fiscal_year_start_month)
        clauses = [f"{fiscal_month} % 3 === 0"]
        if encoding_time_unit == "yearweek":
            clauses.append(f"{date}({v}) <= 7")
        elif encoding_time_unit == "yearmonthdate":
            clauses.append(f"{date}({v}) === 1")
        return " && ".join(clauses)
    if label_time_unit == "yearmonth" and encoding_time_unit in {
        "yearweek",
        "yearmonthdate",
    }:
        return (
            f"{date}({v}) <= 7"
            if encoding_time_unit == "yearweek"
            else f"{date}({v}) === 1"
        )
    if label_time_unit == "yearweek" and encoding_time_unit == "yearmonthdate":
        return f"utcday({v}) === 1"
    if label_time_unit == "year" and encoding_time_unit not in {"year"}:
        fiscal_month = _fiscal_month_expr(month, v, fiscal_year_start_month)
        clauses = [f"{fiscal_month} === 0"]
        if encoding_time_unit in {"yearweek", "yearmonthdate"}:
            clauses.append(
                f"{date}({v}) <= 7"
                if encoding_time_unit == "yearweek"
                else f"{date}({v}) === 1"
            )
        return " && ".join(clauses)
    return None


def default_label_expr_for(
    encoding_time_unit: str | None,
    format_time_unit: str | None,
    visibility_time_unit: str | None = None,
    fiscal_year_start_month: int = 1,
    anchor_index: int = 0,
    anchor_value: str = "",
    *,
    ticks_are_buckets: bool = True,
    steep_tilt: bool = False,
) -> str | None:
    """Return a smart Vega labelExpr with independent format and visibility.

    The gate (``opens_label_period``) filters to label-period openers because
    VL's tick cadence is geometry-driven and may overshoot the label cadence —
    producing duplicate Q-labels when monthly ticks land inside a quarter.

    Always emits ``toDate(datum.value)`` + ``utcFormat`` / ``utcmonth`` /
    ``utcdate``. Ordinal axes are string-domain (need ``toDate`` to parse);
    temporal axes use ``scale.type: "utc"`` (so component extraction must
    also be UTC, otherwise local-TZ ``month()`` shifts January UTC into
    December local and the cadence gate stamps every tick blank). ``toDate``
    is a no-op on Date values, so a single shape covers both paths without
    local-TZ drift.

    fiscal_year_start_month (1=Jan..12=Dec, default 1) shifts the year/quarter
    boundary check and Q1..Q4 numbering for the "year"/"yearquarter" label
    cadences; it is a no-op for "yearmonth"/"yearweek"/"yearmonthdate".

    ``format_time_unit`` chooses the text vocabulary. ``visibility_time_unit``
    only gates which ticks receive that text. ``anchor_index`` or
    ``anchor_value`` identifies the first visible tick and always gives it year
    context. When ``ticks_are_buckets`` is ``True`` the comparison uses the
    visibility grain (so a native month tick still matches a weekly source
    opener after Vega-Lite normalizes both to different concrete dates); when
    ``False`` it uses the encoding grain (Vega generates ticks at that grain,
    and a coarser visibility comparison would match every tick in the period).
    Value anchoring is used whenever Vega-Lite's tick-array indices do not
    reliably match source-bucket indices.

    ``ticks_are_buckets`` is ``False`` for a genuinely continuous temporal axis.
    Day labels use the same two-row day-number vocabulary as week labels either
    way. Vega's continuous ``utcyearweek`` ticks are Sunday-anchored, so weekly
    labels shift the tick date to the represented Monday bucket before
    formatting it when ``ticks_are_buckets`` is ``False``.

    ``steep_tilt`` flows year/month context inline on one row instead of
    stacking it as a second row — at a full-vertical label angle, Vega's
    row-stacking axis rotates onto the horizontal and the context row spills
    into the neighboring tick.
    """
    if not encoding_time_unit or not format_time_unit:
        return None
    if format_time_unit in {"auto", "none"}:
        return None
    label_exprs = {
        "year": _year_label,
        "yearquarter": _quarter_label,
        "yearmonth": _month_label,
        "yearweek": _week_label,
        "yearmonthdate": _day_label,
    }
    if format_time_unit not in label_exprs:
        return None
    label_fn = label_exprs[format_time_unit]
    v = (
        "utcOffset('day', toDate(datum.value), 1)"
        if (
            encoding_time_unit == "yearweek"
            and format_time_unit == "yearweek"
            and not ticks_are_buckets
        )
        else "toDate(datum.value)"
    )
    fmt = "utcFormat"
    month = "utcmonth"
    date = "utcdate"
    visibility = visibility_time_unit or format_time_unit
    anchor_formats = {
        "year": "%Y",
        "yearquarter": "%Y-%m",
        "yearmonth": "%Y-%m",
        "yearweek": "%Y-%U",
        "yearmonthdate": "%Y-%m-%d",
    }
    if anchor_value:
        # On the continuous temporal path ticks are generated at the encoding
        # grain, so compare at that grain — a coarser visibility-grain
        # comparison is a period test that matches every tick in the period.
        # On the bucket path ticks are injected opener values (at visibility
        # grain), so the coarser comparison correctly handles the case where a
        # native-month tick is compared against a weekly source opener.
        anchor_format = anchor_formats[
            encoding_time_unit if not ticks_are_buckets else visibility
        ]
        anchor = (
            f"{fmt}({v}, '{anchor_format}') === "
            f"{fmt}(toDate({json.dumps(anchor_value)}), '{anchor_format}')"
        )
    else:
        anchor = f"datum.index === {anchor_index}"
    expr = label_fn(v, fmt, month, date, fiscal_year_start_month, anchor, steep_tilt)
    gate = opens_label_period(
        encoding_time_unit, visibility, fiscal_year_start_month, v, month, date
    )
    if not gate:
        return expr
    return f"({anchor} || {gate}) ? ({expr}) : ''"


def tooltip_header_date_expr(value_ref: str, time_unit: str) -> str:
    """Self-sufficient date expression for a structured-tooltip identity header.

    Unlike ``default_label_expr_for``'s tick labelExpr — which gates on tick
    position so an axis can drop a repeated year between adjacent labels — a
    tooltip header has no neighboring tick to borrow context from, so it
    always renders the full bucket (``Feb 2024``, never bare ``Feb``). Reuses
    the same ``utcFormat``/``utcmonth`` primitives and quarter arithmetic as
    the axis label vocabulary above, just without the opener gate.

    ``time_unit`` is one of ``BUCKETED_CALENDAR_UNITS`` (as returned by
    ``detect_time_unit``) or ``""`` for continuous/sub-daily temporal data,
    which falls back to a full calendar-date format shared with
    ``yearmonthdate`` (both want day-level precision).
    """
    v = f"toDate({value_ref})"
    if time_unit == "year":
        return f"utcFormat({v}, '%Y')"
    if time_unit == "yearquarter":
        return f"'Q' + (floor(utcmonth({v}) / 3) + 1) + ' ' + utcFormat({v}, '%Y')"
    if time_unit == "yearmonth":
        return f"utcFormat({v}, '%b %Y')"
    if time_unit == "yearweek":
        return f"'Week of ' + utcFormat({v}, '%b %-d, %Y')"
    return f"utcFormat({v}, '%b %-d, %Y')"


def _parse_label_value_date(value: Any) -> dt.date | dt.datetime:
    """Parse one authored ``label.values`` entry into a date/datetime.

    ``label.values`` is authored directly in YAML (not sourced from query
    data), so only ISO date/datetime strings and date/datetime objects are
    accepted — the ambiguous bucket-label formats ``_parse_bucket_string``
    tolerates for data columns (``Jan 2024``, ``Q1 2024``, ...) are out of
    scope for an explicit, unambiguous author-authored list. Raises a coded
    ``ChartDataError`` (ERR-LABEL-VALUES-INVALID-DATE) on anything else
    (validate-and-error-fast).
    """
    if isinstance(value, (dt.datetime, dt.date)):
        return value
    if isinstance(value, str):
        # Python <3.11: fromisoformat rejects the trailing 'Z' UTC suffix —
        # normalize it so the same board parses identically on 3.10 and 3.13
        # (mirrors _parse_date above).
        v = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return dt.datetime.fromisoformat(v)
        except ValueError:
            pass
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            pass
    from dbt_charts.core.diagnostics.chart_data import ChartDataError
    from dbt_charts.core.diagnostics.codes_render import (
        ERR_LABEL_VALUES_INVALID_DATE,
    )

    raise ChartDataError.from_code(ERR_LABEL_VALUES_INVALID_DATE, value=value)


def _label_value_to_utc_ms(value: dt.date | dt.datetime) -> float:
    """Convert a parsed label.values entry to UTC epoch-milliseconds.

    Matches how Vega's ``time(toDate(datum.value))`` resolves a tick — both
    ordinal (ISO date string) and temporal (Date/utc scale) domains parse
    bare date strings as UTC midnight, so comparing on UTC ms is exact
    regardless of which VL scale type the axis ultimately resolves to.
    """
    if isinstance(value, dt.datetime):
        d = value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)
        return d.timestamp() * 1000
    return (
        dt.datetime(
            value.year, value.month, value.day, tzinfo=dt.timezone.utc
        ).timestamp()
        * 1000
    )


def label_values_filter_expr(label_values: list[Any], inner_expr: str) -> str:
    """Build a labelExpr that blanks any tick not in the authored label_values.

    ``label_values`` are the authored dates (ISO strings or date/datetime
    objects); ``inner_expr`` is the label text to use for ticks that DO
    match (typically ``datum.label``, or whatever smart-cadence/format
    expression the axis already resolved to). This is how tick/grid density
    stays decoupled from label density: callers leave tick/grid
    values at their natural rhythm and use this to sparsify only the text.
    """
    ms_values = [
        _label_value_to_utc_ms(_parse_label_value_date(v)) for v in label_values
    ]
    membership = f"indexof({json.dumps(ms_values)}, time(toDate(datum.value)))"
    return f"{membership} === -1 ? '' : ({inner_expr})"
