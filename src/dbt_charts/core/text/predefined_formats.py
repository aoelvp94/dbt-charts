"""Engine-owned predefined format vocabulary.

Every format the engine treats as a semantic name -- with house rules (notation
registers, round-aware trim, native formatters) -- lives here. Format values
from three sources:

| source          | behaviour                                                  |
|-----------------|-----------------------------------------------------------|
| enum member     | house rules: engine spec + notation register + trim       |
| style.formats   | native d3: literal spec, no post-processing               |
| inline d3 str   | native d3: literal spec, no post-processing               |

House glyphs (MINUS U+2212, NULL_DISPLAY em-dash) stay universal for ALL
format sources. They are chart typography, not format semantics -- a user alias
should not resurrect ASCII hyphen-minus in one cell of a table whose other
cells use the proper glyph.

A style.formats key equal to any ALL_PREDEFINED_NAMES member is a shadowing
violation -- the engine owns those names. Raise ERR-FORMAT-PREDEFINED-SHADOW at compile.

NULL_DISPLAY and MINUS are intentionally re-declared here rather than imported
from format_d3 to avoid a circular import (format_d3 imports PREDEFINED_NUMBER_NAMES
from this module).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any

# Same glyph constants as format_d3 -- declared here to break the circular
# import (format_d3 imports PREDEFINED_NUMBER_NAMES from this module).
_NULL_DISPLAY = "—"  # em-dash — the house null sentinel
_MINUS = "−"  # minus sign − replacing ASCII '-'


def _with_minus(s: str) -> str:
    return s.replace("-", _MINUS)


class PredefinedNumberFormat(str, Enum):
    """Engine-owned number format names.

    Each member triggers house rules (notation registers, round-aware trim,
    or a native formatter that bypasses d3 entirely). Authors write the member
    name in format: fields; the engine owns what it produces.

    Members percent_number / percent_number_delta / percentage_points_delta
    bypass d3 because the value IS the whole-number percent or point delta
    (d3's % type multiplies by 100, which is wrong for these).

    __str__ returns the string value (not "ClassName.member") so members pass
    cleanly through code paths that call str() on format specs. StrEnum does the
    same but only exists in Python 3.11+; this shim covers 3.10.
    """

    def __str__(self) -> str:
        return str.__str__(self)

    currency = "currency"
    currency_whole = "currency_whole"
    currency_compact = "currency_compact"
    percent = "percent"
    percent_whole = "percent_whole"
    percent_delta = "percent_delta"
    compact = "compact"
    integer = "integer"
    delta = "delta"
    number = "number"
    year = "year"
    number_default = "number_default"
    percent_number = "percent_number"
    percent_number_delta = "percent_number_delta"
    percentage_points_delta = "percentage_points_delta"


class PredefinedTimeFormat(str, Enum):
    """Engine-owned time format names.

    date_short is the theme-mandated default for temporal table cells. It is
    referenced by name from the theme's axis_quantitative.labels.format and
    read directly by table rendering. Absence raises at compile.
    """

    def __str__(self) -> str:
        return str.__str__(self)

    date_short = "date_short"


# Engine-owned d3 specs for each predefined number format member.
# Members with a PREDEFINED_NATIVE entry bypass this table entirely.
PREDEFINED_SPECS: dict[str, str] = {
    PredefinedNumberFormat.currency: "$,.2f",
    PredefinedNumberFormat.currency_whole: "$,.0f",
    PredefinedNumberFormat.currency_compact: "$~s",
    PredefinedNumberFormat.percent: ".1%",
    PredefinedNumberFormat.percent_whole: ".0%",
    PredefinedNumberFormat.percent_delta: "+.1%",
    PredefinedNumberFormat.compact: "~s",
    PredefinedNumberFormat.integer: ",.0f",
    PredefinedNumberFormat.delta: "+,d",
    PredefinedNumberFormat.number: ",.2f",
    PredefinedNumberFormat.year: "d",
    PredefinedNumberFormat.number_default: ".3~s",
}

# Engine-owned d3 time specs for each predefined time format member.
PREDEFINED_TIME_SPECS: dict[str, str] = {
    PredefinedTimeFormat.date_short: "%-d %b %Y",
}

# Native formatters: bypass d3 entirely. The value already IS in the caller's
# unit (whole-number percent, point delta). Each returns (number_str, unit_str)
# so callers that split prefix/number/suffix continue to work unchanged.
PREDEFINED_NATIVE: dict[str, Callable[[Any], tuple[str, str]]] = {
    PredefinedNumberFormat.percent_number: lambda v: (
        (_NULL_DISPLAY, "") if v is None else (_with_minus(f"{float(v):.1f}"), "%")
    ),
    PredefinedNumberFormat.percent_number_delta: lambda v: (
        (_NULL_DISPLAY, "") if v is None else (_with_minus(f"{float(v):+.1f}"), "%")
    ),
    PredefinedNumberFormat.percentage_points_delta: lambda v: (
        (_NULL_DISPLAY, "") if v is None else (_with_minus(f"{float(v):+.1f}"), " pts")
    ),
}

# Fast membership sets -- use these for string-key checks rather than
# constructing enum members (Pydantic does NOT coerce str to str-Enum when
# | str is present in the union, so runtime detection must use these sets).
PREDEFINED_NUMBER_NAMES: frozenset[str] = frozenset(
    m.value for m in PredefinedNumberFormat
)
PREDEFINED_TIME_NAMES: frozenset[str] = frozenset(m.value for m in PredefinedTimeFormat)
ALL_PREDEFINED_NAMES: frozenset[str] = PREDEFINED_NUMBER_NAMES | PREDEFINED_TIME_NAMES
# Native members bypass d3 entirely — valid only in Python-painted slots (KPI,
# table). Vega-painted slots (axis labels, mark labels, number_format, time_format,
# data_table) must reject these at compile; Vega has no equivalent renderer.
PREDEFINED_NATIVE_NAMES: frozenset[str] = frozenset(PREDEFINED_NATIVE)

# Every PredefinedNumberFormat member must resolve: either a d3 spec in
# PREDEFINED_SPECS or a native formatter in PREDEFINED_NATIVE. A member without
# an entry passes validate/formats.py (which whitelists ALL_PREDEFINED_NAMES)
# but causes _d3_format("<name>") to raise deep in render — exactly the silent
# failure validate-and-error-fast exists to prevent.
_unresolvable = PREDEFINED_NUMBER_NAMES - (
    frozenset(PREDEFINED_SPECS) | frozenset(PREDEFINED_NATIVE)
)
assert not _unresolvable, (
    f"PredefinedNumberFormat members with no resolver: {_unresolvable!r}. "
    f"Add to PREDEFINED_SPECS or PREDEFINED_NATIVE."
)
