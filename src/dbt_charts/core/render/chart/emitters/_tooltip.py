"""Chart-axes LUT + structured tooltip builder for render-v2.

The chart-axes LUT maps each in-scope chart family to its tooltip ROLES —
identity (header), dependent (value), and whether a colour dimension can be
promoted to a series row — never a VL screen axis. Orientation is resolved
downstream by each family's own emitter (see bar.py's vertical/horizontal
split); this table only ever reads authored semantic channels (``chart.x``/
``chart.y``/``color``), which stay independent/dependent regardless of
orientation.

``build_structured_tooltip_expr`` is the single function that turns those
roles into a per-datum expression string wired to VL's native ``description``
channel — not an appended ``encoding.tooltip`` array. ``description`` is the
only mechanism that gives exact, order-controlled aria-label content with no
risk of Vega-Lite's tooltip-merge duplicating a field already carried by its
own titled channel (the historical #2308 dedup bug guarded by
``test_tooltip_dedup.py``): an explicit ``tooltip`` array only ever *adds* to
channel-derived content, it never replaces it, so any field left off the
array (or covered by an already-titled channel) can still resurface — which
is exactly how #2308 happened. ``description`` fully replaces the mark's
aria-label instead of merging with it.

``translate.py::_apply_structured_tooltip`` wires the expression as a
``{"value": {"expr": ...}}`` def, deliberately NOT a ``{"field": ...}``
reference bound through a ``calculate`` transform — a field-bound description
is a genuine encoded channel, and Vega-Lite folds every encoded nominal
channel into the automatic ``impute`` transform's ``groupby`` for line/area
marks. Since the header always embeds the datum's own x/time value, every row
gets a distinct description, exploding that groupby to one group per row and
fragmenting the stacked area/line path with phantom imputed points. See
``_apply_structured_tooltip``'s docstring for the full mechanism.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from dbt_charts.core.render.chart.artifacts import ChartRenderData
from dbt_charts.core.render.chart.time_unit_detect import (
    detect_time_unit,
    tooltip_header_date_expr,
)
from dbt_charts.core.render.chart.type_inference import infer_vega_type_from_data

# Zero-width Unicode "format" characters (general category Cf — the same
# family as U+200B ZERO WIDTH SPACE) mark each tooltip entry's role so
# chart_interactivity.js can render the header/rows/footer hierarchy (bold
# header, swatched series, label:value dependent rows, emphasized footer
# total) from one flat aria-label string. Unlike C0 control characters these
# are valid XML/SVG attribute content, and browsers/screen readers neither
# render nor vocalize them — the accessible name still reads as clean prose,
# just without a redundant field-name prefix on the header/series rows.
# chart_interactivity.js mirrors these exact codepoints; keep the two in sync.
ROLE_HEADER = "⁡"  # FUNCTION APPLICATION
ROLE_HEADER_SWATCHED = "⁤"  # INVISIBLE PLUS -- header IS the colour dim (pie)
ROLE_SERIES = "⁢"  # INVISIBLE TIMES
ROLE_TOTAL = "⁣"  # INVISIBLE SEPARATOR
# A precomputed display-order rank for this mark's series -- the SAME order
# that already drives the color scale's reordered domain (and, via
# apply_legend_entry_order, legend.values). chart_interactivity.js prefers
# this over reading the rendered legend's DOM order, which is unavailable
# whenever no legend renders (e.g. a line using endpoint labels instead of a
# legend, the common default) -- see features/structured_tooltip.py.
ROLE_ORDER = "‌"  # ZERO WIDTH NON-JOINER
# Emphasis modifier, orthogonal to the role markers above: a value/total row
# prefixed with this renders its value at the low-contrast label colour rather
# than the loud value colour. Used where a percent is the row's lead and the
# raw number is only its companion context -- on a pie/donut the share % leads,
# so the raw slice count and the grand total are context. Composes with a role
# marker (a muted total is MUTED + ROLE_TOTAL). chart_interactivity.js mirrors it.
MUTED = "⁠"  # WORD JOINER


@dataclass(frozen=True)
class TooltipField:
    """One value contributing to a structured tooltip row.

    ``kind`` selects how the datum value renders: ``quantitative`` applies
    ``format``; ``temporal`` applies a UTC date format; ``nominal`` (default)
    passes the raw datum value through.
    """

    field: str
    title: str
    kind: Literal["nominal", "quantitative", "temporal"] = "nominal"
    format: str = ""
    # Bucketed calendar grain (see time_unit_detect.BUCKETED_CALENDAR_UNITS),
    # or "" for continuous/sub-daily temporal data (same empty-string-means-
    # unset convention as `format` above). Only meaningful when
    # kind == "temporal" — selects the header's date-format vocabulary.
    time_unit: str = ""
    # When True this row's VALUE renders at the low-contrast label colour, not
    # the loud value colour — a companion/context number beside a percent lead
    # (see MUTED). Structural, set by the role builder; never authored.
    muted: bool = False
    # When True, ``field`` IS the row's literal display string, not a datum
    # column name -- baked as a JSON string literal instead of a `datum[...]`
    # lookup. A combo overlay layer's own identity ("Target") is a Python-side
    # label cascade result, not a query column, so it has no field to read.
    literal: bool = False


@dataclass(frozen=True)
class ChartAxesRoles:
    """Tooltip role support for one chart family — data roles, not VL screen axes."""

    supports_series: bool
    # The header IS the colour-bound dimension (pie's category), so its row
    # carries a swatch the same way a series row would. False for every
    # cartesian family, whose header (x) is never colour-bound.
    header_is_swatched: bool = False


# Chart families with structured-tooltip support. An unlisted chart_type
# KeyErrors in build_structured_tooltip_expr — fail fast rather than guess a
# role shape. "scatter" and "scatter_colored" are two role shapes for the
# SAME authored chart_type ("scatter") — the LUT key a caller passes depends
# on whether a colour channel is bound (see features/structured_tooltip.py's
# _scatter_roles), not on any new authored discriminator.
CHART_AXES_LUT: dict[str, ChartAxesRoles] = {
    "line": ChartAxesRoles(supports_series=True),
    "area": ChartAxesRoles(supports_series=True),
    "bar": ChartAxesRoles(supports_series=True),
    "pie": ChartAxesRoles(supports_series=False, header_is_swatched=True),
    "heatmap": ChartAxesRoles(supports_series=False),
    "scatter": ChartAxesRoles(supports_series=False),
    "scatter_colored": ChartAxesRoles(supports_series=False, header_is_swatched=True),
}


def field_cardinality(field: str, data: ChartRenderData) -> int:
    """Count of distinct non-null values of ``field`` across ``data``."""
    return len({row[field] for row in data if row.get(field) is not None})


def header_tooltip_field(field: str, title: str, data: ChartRenderData) -> TooltipField:
    """One identity field for ``field`` -- temporal (with detected grain) when
    the data is date-like, nominal otherwise.

    Shared by cartesian headers (``features/structured_tooltip.py``), heatmap's
    compound [x, y] header, and a combo overlay layer's own header row
    (``emitters/_overlay.py``) — the overlay's header must resolve to the
    EXACT SAME formatted string as the base's for the same x, since
    ``chart_interactivity.js``'s x-unified grouping matches marks by header
    STRING equality, not by field identity.

    Mirrors ``build_cartesian_x_encoding``'s own detection (type_inference.py):
    a bucketed calendar string ("2024-01") infers as "ordinal", not "temporal",
    so the axis-format machinery re-detects the grain from the data rather
    than trusting the coarse VL type alone. Ordinal date-like data that
    detect_time_unit can't parse (half-year buckets, etc.) degrades to a
    plain nominal header, same as the axis itself.
    """
    field_type = infer_vega_type_from_data(data, field)
    time_unit = ""
    if field_type in ("temporal", "ordinal"):
        try:
            detected = detect_time_unit([row.get(field) for row in data])
            time_unit = detected if detected is not None else ""
        except ValueError:
            time_unit = ""
    if field_type == "temporal" or time_unit != "":
        return TooltipField(field, title, kind="temporal", time_unit=time_unit)
    return TooltipField(field, title, kind="nominal")


def series_row_promoted(field: str, data: ChartRenderData) -> bool:
    """A series row earns its place only when it actually distinguishes rows.

    Matches the LUT's promotion rule: colour-channel cardinality > 1. A bound
    field whose data happens to carry a single distinct value would be a
    redundant row (every mark shares the same series) — omit it instead of
    padding the tooltip with a constant. Caller guards a non-empty ``field``
    before calling (``ResolvedStyleChannel.data_field`` is a plain ``str``,
    empty when unbound).
    """
    return field_cardinality(field, data) > 1


def _value_expr(tf: TooltipField) -> str:
    if tf.literal:
        return json.dumps(tf.field)
    ref = f"datum[{json.dumps(tf.field)}]"
    if tf.kind == "quantitative":
        return f"format({ref}, {json.dumps(tf.format)})"
    if tf.kind == "temporal":
        return tooltip_header_date_expr(ref, tf.time_unit)
    return ref


def _row_expr(tf: TooltipField, marker: str = "") -> str:
    """Label + value row, e.g. ``"Revenue: " + format(...)``.

    ``marker`` optionally role-tags the row (the total footer) without
    disturbing its label:value shape; a muted field prepends ``MUTED`` ahead
    of that marker so the value renders at the low-contrast label colour.
    """
    prefix = (MUTED if tf.muted else "") + marker
    return f"{json.dumps(prefix + tf.title + ': ')} + ({_value_expr(tf)})"


def _bare_row_expr(tf: TooltipField, marker: str) -> str:
    """Role-tagged value with no field label — the header/series rows."""
    return f"{json.dumps(marker)} + ({_value_expr(tf)})"


def build_structured_tooltip_expr(
    chart_type: str,
    header: tuple[TooltipField, ...],
    series: tuple[TooltipField, ...],
    values: list[TooltipField],
    total: tuple[TooltipField, ...] = (),
    order: tuple[TooltipField, ...] = (),
) -> str:
    """Build the per-datum expression string for one mark's structured tooltip.

    ``header``/``series``/``total``/``order`` are 0-or-1-element tuples
    (absent vs. present), not ``TooltipField | None`` — cardinality expresses
    optionality here so assembly is a plain splat, no None-checks. Order is
    fixed — header (identity), series row, order rank, dependent values,
    footer total — the header/rows/footer model's single-mark projection
    (``rows`` length 1; x-unified multi-row expansion is a later slice).

    Every entry is role-tagged (``ROLE_HEADER``/``ROLE_SERIES``/``ROLE_TOTAL``/
    ``ROLE_ORDER``) so ``chart_interactivity.js`` can style header/series/
    dependent/footer rows differently — and sort x-unified rows by rank —
    from one flat aria-label string. See the module docstring. ``order``'s
    entry is invisible: it carries no display row, purely a sort signal.
    """
    roles = CHART_AXES_LUT[chart_type]
    # Internal-caller invariants, not user-facing data errors: every caller in
    # features/structured_tooltip.py only ever passes a series/total/order
    # entry for a family the LUT marks as series-capable, and always supplies
    # at least one field. A violation is a bug in this module's own caller,
    # not authored input.
    assert not series or roles.supports_series, (
        f"chart family {chart_type!r} has no series role"
    )
    assert not order or roles.supports_series, (
        f"chart family {chart_type!r} has no series role"
    )
    header_marker = ROLE_HEADER_SWATCHED if roles.header_is_swatched else ROLE_HEADER
    parts = [_bare_row_expr(tf, header_marker) for tf in header]
    parts += [_bare_row_expr(tf, ROLE_SERIES) for tf in series]
    parts += [_bare_row_expr(tf, ROLE_ORDER) for tf in order]
    parts += [_row_expr(tf) for tf in values]
    parts += [_row_expr(tf, ROLE_TOTAL) for tf in total]
    assert parts, "build_structured_tooltip_expr: at least one field required"
    return " + '; ' + ".join(parts)


__all__ = [
    "CHART_AXES_LUT",
    "MUTED",
    "ROLE_HEADER",
    "ROLE_HEADER_SWATCHED",
    "ROLE_ORDER",
    "ROLE_SERIES",
    "ROLE_TOTAL",
    "ChartAxesRoles",
    "TooltipField",
    "build_structured_tooltip_expr",
    "field_cardinality",
    "header_tooltip_field",
    "series_row_promoted",
]
