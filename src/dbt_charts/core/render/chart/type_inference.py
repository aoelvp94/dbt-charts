"""Shared helpers for Vega-Lite type inference from query result data."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeAlias

from dbt_charts.core.compile.config import get_chart_rendering
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.artifacts import ChartRenderData
from dbt_charts.core.render.chart.vl_field_maps import emit_resolved_scale_vl
from dbt_charts.core.text.format_d3 import is_time_format

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.style.resolved import (
        ResolvedAxisStyle,
        ResolvedScaleStyle,
    )

# Date-only ISO forms (YYYY-MM, YYYY-MM-DD) — the only string shapes JS
# Date.parse treats as UTC midnight, making them safe domain values for the
# labels.values epoch-ms membership filter on ordinal axes. Datetime strings
# without an offset parse as LOCAL time in JS and are deliberately excluded.
_ISO_UTC_SAFE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$")

DetectedTimeUnit: TypeAlias = str | None


def _utc_time_label_expr(fmt: str) -> str:
    """Build a Vega ``labelExpr`` that formats a date-string axis tick under UTC.

    ``toDate(datum.value)`` parses ISO date strings (ordinal domain) or accepts
    Date instances unchanged; ``utcFormat`` emits the requested d3-time-format
    string in UTC so the spec renders identically under any runtime TZ.
    """
    fmt_escaped = fmt.replace("\\", "\\\\").replace("'", "\\'")
    return f"utcFormat(toDate(datum.value), '{fmt_escaped}')"


DATE_LIKE_PATTERNS = [
    r"^\d{4}-Q[1-4]$",
    r"^Q[1-4]\s*\d{4}$",
    r"^\d{4}Q[1-4]$",
    r"^\d{4}-\d{2}$",
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}$",
    r"^FY\d{4}$",
    r"^H[12]\s*\d{4}$",
    r"^\d{4}-H[12]$",
    r"^W(?:eek\s*)?\d{1,2}\s*\d{4}$",
    r"^\d{4}-W\d{2}$",  # ISO 8601 week: 2024-W01
    r"^\d{2}/\d{4}$",  # MM/YYYY: 01/2024
    r"^\d{2}/\d{2}/\d{4}$",  # MM/DD/YYYY: 01/15/2024
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}$",  # Mon DD, YYYY
    r"^\d{4}-\d{2}-\d{2}$",  # YYYY-MM-DD: 2024-01-15
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$",  # ISO 8601 naive timestamp, T or space separator: 2024-01-15T13:30:00 / 2024-01-15 13:30:00
]
DATE_LIKE_REGEXES = [
    re.compile(pattern, re.IGNORECASE) for pattern in DATE_LIKE_PATTERNS
]


def is_date_like_string(value: str) -> bool:
    """Return True when a string looks like an ordered date bucket."""
    return any(pattern.match(value) for pattern in DATE_LIKE_REGEXES)


# Year-leading patterns whose lexicographic ascending order equals chronological
# order. Safe to use as a window-sort field for x-cell sampling.
# Patterns NOT listed here (e.g. "Jan 2024", "01/2024", "Q1 2024") sort
# lex-incorrectly and must NOT trigger sampling — wrong cells would be selected.
# Every entry must also appear in DATE_LIKE_PATTERNS (the module-level assert
# below enforces this so the two lists cannot silently drift).
_LEX_SORTABLE_DATE_LIKE_PATTERNS = [
    r"^\d{4}-Q[1-4]$",  # 2024-Q1 lex == chron
    r"^\d{4}Q[1-4]$",  # 2024Q1 lex == chron
    r"^\d{4}-\d{2}$",  # 2024-01 lex == chron
    r"^FY\d{4}$",  # FY2024 lex == chron
    r"^\d{4}-H[12]$",  # 2024-H1 lex == chron
    r"^\d{4}-W\d{2}$",  # 2024-W01 lex == chron (ISO 8601 week)
    r"^\d{4}-\d{2}-\d{2}$",  # 2024-01-15 lex == chron
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$",  # naive ISO timestamp lex == chron (T or space, no tz suffix)
]
# Guard against drift: every lex-sortable pattern must be a subset of the
# full date-like list so a future edit to DATE_LIKE_PATTERNS can't leave
# is_lex_sortable_date_like silently matching patterns that were tightened.
# Use RuntimeError (not assert) so the guard survives python -O.
if not set(_LEX_SORTABLE_DATE_LIKE_PATTERNS) <= set(DATE_LIKE_PATTERNS):
    raise RuntimeError(
        "_LEX_SORTABLE_DATE_LIKE_PATTERNS contains patterns not in DATE_LIKE_PATTERNS; "
        "update or remove the stale entries"
    )
_LEX_SORTABLE_DATE_LIKE_REGEXES = [
    re.compile(p, re.IGNORECASE) for p in _LEX_SORTABLE_DATE_LIKE_PATTERNS
]

_TEMPORAL_TICK_INTERVAL: dict[str, tuple[str, int]] = {
    "year": ("year", 1),
    "yearquarter": ("month", 3),
    "yearmonth": ("month", 1),
    "yearweek": ("week", 1),
    "yearmonthdate": ("day", 1),
}

# Bar-family marks normally hide x ticks because every bucket is labeled. Once
# calendar labels become sparser than buckets, ticks restore the missing
# positional cue without changing which bucket positions the axis contains.
_LABEL_THINNING_TICK_MARK_TYPES = frozenset({"bar", "histogram"})


def is_lex_sortable_date_like(value: str) -> bool:
    """Return True when the string is a date-like bucket whose lex sort is chronological.

    Only year-leading ISO-prefix patterns qualify. Month-name, MM/YYYY, and
    quarter-first patterns sort incorrectly under string comparison and must
    not be used to drive the sampling window's ascending sort.
    """
    return any(p.match(value) for p in _LEX_SORTABLE_DATE_LIKE_REGEXES)


def resolve_authored_x_type(axis: ResolvedAxisStyle) -> str | None:
    """Authored ``axis_x.type``, with ``axis_x.scale.type: temporal`` as a
    second escape hatch for the same authored-temporal request — authors
    reach for ``scale.type``, not ``type``, since that's the field VL itself
    calls "scale type". The explicit ``axis.type`` wins when both are
    authored so there is one unambiguous override, not two competing ones.
    Only ``"temporal"`` participates; the quantitative Literal values
    (log/pow/sqrt/symlog) are meaningless on a dimension axis.
    """
    authored_type = axis.type
    if authored_type in (None, "auto") and axis.scale is not None:
        _ax_scale_type = (
            axis.scale.continuous.type if axis.scale.continuous is not None else None
        )
        if _ax_scale_type == "temporal":
            authored_type = "temporal"
    return authored_type


def resolve_cartesian_x_type(
    data: ChartRenderData,
    x_field: str,
    axis: ResolvedAxisStyle,
    mark_type: str,
    is_band_step: bool,
) -> tuple[str, str, DetectedTimeUnit]:
    """Return the emitted VL x type, data type, and calendar bucket grain."""
    from dbt_charts.core.render.chart.time_unit_detect import (
        BUCKETED_CALENDAR_UNITS,
        TIME_PART_UNITS,
        detect_time_unit,
    )

    x_type_from_data = infer_vega_type_from_data(data, x_field)
    authored_time_unit = axis.time_unit
    authored_type = resolve_authored_x_type(axis)

    if authored_time_unit is None and x_type_from_data == "temporal":
        time_unit = detect_time_unit(
            [row.get(x_field) for row in data if x_field in row]
        )
    elif authored_time_unit is None and x_type_from_data == "ordinal":
        try:
            time_unit = detect_time_unit(
                [row.get(x_field) for row in data if x_field in row]
            )
        except ValueError:
            time_unit = None
    else:
        time_unit = authored_time_unit

    if mark_type == "heatmap":
        # Grid dimension: always a nominal band scale — promoting it collapses
        # every rect cell to zero width (matches oracle _map_rect). time_unit
        # is still returned so build_cartesian_x_encoding gets the same
        # labelExpr/tick-thinning enrichment the ordinal branch gives bar.
        return "nominal", x_type_from_data, time_unit

    if (
        authored_type == "temporal"
        or authored_time_unit == "none"
        or (time_unit is not None and time_unit in TIME_PART_UNITS)
    ):
        vl_type = "temporal"
    elif authored_type == "ordinal":
        vl_type = "ordinal"
    elif time_unit and time_unit in BUCKETED_CALENDAR_UNITS:
        if is_band_step:
            vl_type = "ordinal"
        elif mark_type in ("line", "area", "scatter"):
            vl_type = "temporal"
        elif time_unit in {"yearweek", "yearmonthdate"}:
            vl_type = "ordinal"
        else:
            n_buckets = len({row.get(x_field) for row in data if x_field in row})
            max_ordinal = get_chart_rendering().type_inference.max_ordinal_buckets
            vl_type = "temporal" if n_buckets > max_ordinal else "ordinal"
    else:
        vl_type = x_type_from_data

    if (
        vl_type == "temporal"
        and time_unit in {"year", "yearquarter"}
        and axis.fiscal_year_start_month != 1
    ):
        vl_type = "ordinal"
    return vl_type, x_type_from_data, time_unit


def temporal_edge_labels_flushed(vl_type: str, axis: ResolvedAxisStyle) -> bool:
    """Whether Vega flushes this temporal axis's outer labels into the plot."""
    return vl_type == "temporal" and axis.labels.flush is not False


def apply_x_tick_cadence(
    axis_vl: VLDict | None,
    axis: ResolvedAxisStyle,
    x_field: str,
    vl_type: str,
    *,
    remedy: str | None = None,
) -> None:
    """Merge authored ``count``/``step`` onto an x-axis VL dict, in place.

    The one home for x-axis tick cadence, gate and merge together. Every
    cartesian x path calls this exactly once — through
    ``build_cartesian_x_encoding``, or directly where an emitter builds its
    own axis (scatter's quantitative fast path, histogram, the multi-measure
    heatmap, horizontal bar). A path that skips it turns an authored cadence
    back into a silent no-op, which is the defect this surface exists to
    remove.

    ``remedy`` overrides the "what to do instead" half of the error for a
    caller whose axis needs a better answer than the type alone can give.
    ``_emit_horizontal`` passes one: its ``axis_x`` is the CATEGORICAL axis
    (the measure is ``axis_y``), so "this domain is discrete" would leave an
    author who wrote ``axis_x`` meaning "the horizontal axis" no wiser — it
    names the orientation instead, exactly as it already does for
    ``labels.values``.

    The gate and the merge are one function on purpose. They were two, and the
    obligation to pair them correctly got half-done twice: once dropping the
    merge guard (a theme's tick density silently thinning an authored
    ``scale.values`` ladder), once dropping the call entirely.

    ``axis_vl`` is None on a path that draws no axis dict at all — the
    multi-measure heatmap's layered top-level x. Nothing can be merged there,
    but the band still renders category labels, so the gate must still fire.

    What merges, and what does not:

    - ``count`` is a target, not a ladder. VL honours it closely on a temporal
      scale and rounds to a nearby nice step on a quantitative one. A discrete
      scale has no tick-count concept, so it falls through unset — that has
      always been a silent no-op and stays one.
    - A bare ``step`` (no ``time_unit``) is the numeric interval lever, so off
      a quantitative scale it raises rather than no-ops: an explicit cadence is
      an explicit request. The remedy varies with what the author can actually
      do instead — on temporal, ``step`` needs a unit to name a calendar
      cadence; on a discrete domain nothing applies, and pointing at
      ``ticks.count`` there would just name a second inert field.
    - An existing ``values`` suppresses the whole merge (an enumerated ladder
      names every tick outright), and ``setdefault`` never overwrites a
      ``tickCount`` the caller already resolved. The gate fires either way: a
      misauthored cadence is an error whether or not anything would have read
      it.

    The temporal ``{interval, step}`` construction stays in
    ``build_cartesian_x_encoding``, which needs the resolved label grain. So
    does the ``ticks.time_unit`` gate, for a different reason: it is unchanged
    from before this surface existed, and the paths that skip
    ``build_cartesian_x_encoding`` have always silently ignored ``time_unit``.
    Moving it would newly break boards that render today.
    """
    ticks = axis.ticks
    out: dict[str, int] = {}

    if ticks.step is not None and ticks.time_unit is None:
        if vl_type != "quantitative":
            from dbt_charts.core.diagnostics.chart_data import ChartDataError
            from dbt_charts.core.diagnostics.codes_render import (
                ERR_TICKS_STEP_NOT_QUANTITATIVE,
            )

            raise ChartDataError.from_code(
                ERR_TICKS_STEP_NOT_QUANTITATIVE,
                field=x_field,
                vl_type=vl_type,
                remedy=remedy
                or (
                    "Author ticks.time_unit alongside step (e.g. time_unit: "
                    "year, step: 5) to name a calendar cadence."
                    if vl_type == "temporal"
                    else "This axis has a discrete domain, which has no "
                    "numeric tick interval — remove ticks.step."
                ),
            )
        out["tickMinStep"] = ticks.step

    if ticks.count is not None and vl_type in ("temporal", "quantitative"):
        out["tickCount"] = ticks.count

    if axis_vl is None or "values" in axis_vl:
        return
    for key, value in out.items():
        axis_vl.setdefault(key, value)


def build_cartesian_x_encoding(
    data: list[dict[str, Any]],
    x_field: str,
    axis: ResolvedAxisStyle | Any,
    ax_vl: dict[str, Any],
    mark_type: str,
    curve: str | None = None,
    format_time_unit: str = "",
    visibility_time_unit: str | None = None,
    label_anchor_index: int = 0,
    domain_values: list[Any] | None = None,
) -> tuple[str, dict[str, Any], DetectedTimeUnit]:
    """Return (vl_type, merged_ax_vl, detected_time_unit) for a cartesian x encoding.

    Composes the ``time_unit_detect`` helpers rather than reimplementing them.

    ax_vl is never mutated — a new dict is always returned.
    detected_time_unit is the resolved time_unit (authored or auto-detected),
    or None when no bucketing applies. Callers use it to decide timeUnit emission.

    mark_type distinguishes bar/column (ordinal bucketed bands, gated by
    ``chart_rendering.type_inference.max_ordinal_buckets``) from line/area/scatter
    (always continuous temporal for a BUCKETED_CALENDAR_UNITS grain — none of
    the three has a per-bucket gridline problem, and a scatter point needs its
    real continuous position, not a band-snapped one) when no authored type
    forces the decision either way. ``curve`` is the
    authored line/area curve style; a band-aware ``step`` curve requires a band
    (nominal/ordinal) x-scale (see ``step_band.py``) unconditionally, at any
    bucket count — it overrides both the line/area always-temporal rule and
    bar's density gate. ``step-before``/``step-after`` do not force a band
    scale — they render as literal VL step interpolation on the resolved axis.

    visibility_time_unit is the render-local label-thinning grain. It never
    changes the encoding, resolved label-format time unit, or tick cadence.
    A resolved label-format time unit coarser than the encoding grain does set
    the default ticks to the same calendar openers.
    label_anchor_index identifies the first visible ordinal label so it keeps
    year context after automatic thinning.

    domain_values is the x scale's full band domain when it is wider than
    ``data`` alone implies — a chart whose overlay layers extend past the base
    series (``overlay_x_domain_values``). Vega-Lite unions the sub-layer
    domains, so the tick values must be derived from that union and THEN
    thinned to the label cadence; deriving them from the base's rows leaves
    every extra band unlabelled. Unset means the base's rows are the domain.
    """
    from dbt_charts.core.render.chart.step_band import BAND_STEP_CURVE
    from dbt_charts.core.render.chart.time_unit_detect import (
        BUCKETED_CALENDAR_UNITS,
        default_label_expr_for,
        enumerated_axis_values,
        label_opener_values,
        ordinal_axis_values,
        resolve_label_time_unit,
    )

    vl_type, x_type_from_data, time_unit = resolve_cartesian_x_type(
        data, x_field, axis, mark_type, curve == BAND_STEP_CURVE
    )
    from dbt_charts.core.render.chart.vl_field_maps import _n

    label_values: list[Any] | None = _n(axis, "labels", "values")

    # label_tu is the resolved label cadence for a bucketed grain — computed once
    # so both the density gate below and the axis-values/labelExpr enrichment
    # further down agree on the same cadence.
    label_tu: str | None = None
    authored_label_tu: str | None = None
    if time_unit and time_unit in BUCKETED_CALENDAR_UNITS:
        authored_label_tu = getattr(getattr(axis, "labels", None), "time_unit", None)
        label_tu = (
            format_time_unit
            if format_time_unit
            else resolve_label_time_unit(time_unit, authored_label_tu)
        )

    fiscal_year_start_month = axis.fiscal_year_start_month
    all_axis_values = (
        (
            domain_values
            if domain_values is not None
            else ordinal_axis_values(data, x_field)
        )
        if time_unit in BUCKETED_CALENDAR_UNITS
        else None
    )
    # label_cadence_values feeds only the label-opener/anchor computation
    # below, never the ordinal ticks/values injection further down (which
    # must stay `all_axis_values` — real per-row buckets, one band each).
    # On the temporal path gap-fill may have skipped scaffolding a row for
    # every bucket (continuous scale needs no filler row), so an "opener"
    # bucket for a coarser label cadence (e.g. a month label over weekly
    # data) can be absent from `data` even though the domain spans it.
    # Enumerate the full calendar span instead so no represented period
    # silently loses its label tick.
    label_cadence_values = (
        enumerated_axis_values(all_axis_values, time_unit, fiscal_year_start_month)
        if vl_type == "temporal"
        and time_unit in BUCKETED_CALENDAR_UNITS
        and all_axis_values
        else all_axis_values
    )
    label_tick_cadence = (
        label_tu in BUCKETED_CALENDAR_UNITS
        and label_tu != time_unit
        and axis.ticks.count is None
        and axis.ticks.time_unit is None
        and "values" not in ax_vl
    )
    label_tick_values: list[Any] = []
    if (
        label_tick_cadence
        and label_tu is not None
        and time_unit is not None
        and label_cadence_values
    ):
        label_tick_values = (
            label_opener_values(
                label_cadence_values,
                time_unit,
                label_tu,
                fiscal_year_start_month,
            )
            or label_cadence_values[:1]
        )

    temporal_anchor_value = ""
    anchor_visibility: str | None = None
    if time_unit in BUCKETED_CALENDAR_UNITS and label_tu in BUCKETED_CALENDAR_UNITS:
        anchor_visibility = visibility_time_unit or label_tu
        anchor_values = label_tick_values or label_cadence_values
        if anchor_values:
            anchor_openers = label_opener_values(
                anchor_values,
                time_unit,
                anchor_visibility,
                fiscal_year_start_month,
            )
            temporal_anchor_value = str((anchor_openers or anchor_values[:1])[0])

    # labels.values needs the epoch-ms membership filter to match every
    # listed date exactly. On a continuous temporal scale datum.value is
    # already epoch ms — always exact. On any other emit path datum.value is
    # the raw domain value, which Vega parses with JS Date semantics: only
    # date-only ISO forms (YYYY-MM, YYYY-MM-DD) parse as UTC midnight.
    # Anything else — nominal/quantitative values, non-ISO bucket labels like
    # "Q1 2024", naive datetime strings like "2024-01-01T00:00:00" (LOCAL
    # time in JS) — would silently blank every label in non-UTC runtimes.
    # Validate against the same stringified form the ordinal enrichment emits
    # (date/datetime objects included) and raise loudly. No magic.
    if label_values is not None and vl_type != "temporal":
        from dbt_charts.core.render.chart.time_unit_detect import (
            _ordinal_axis_iso_value,
        )

        for row in data:
            if x_field not in row or row[x_field] is None:
                continue
            v = _ordinal_axis_iso_value(row[x_field])
            if not (isinstance(v, str) and _ISO_UTC_SAFE_RE.match(v)):
                from dbt_charts.core.diagnostics.chart_data import ChartDataError
                from dbt_charts.core.diagnostics.codes_render import (
                    ERR_LABEL_VALUES_NOT_TEMPORAL,
                )

                raise ChartDataError.from_code(
                    ERR_LABEL_VALUES_NOT_TEMPORAL,
                    field=x_field,
                    cause=f"it contains {row[x_field]!r}, which isn't a UTC-safe ISO date",
                    remedy=(
                        "Use date-only ISO dates (YYYY-MM-DD or YYYY-MM) or date "
                        "objects in the query, or remove labels.values."
                    ),
                )

    result = dict(ax_vl)
    label_angle = result.get("labelAngle")
    steep_tilt = isinstance(label_angle, (int, float)) and abs(label_angle) >= 90

    # Ordinal time-format routing: d3-time-format strings on non-temporal axes must
    # become utcFormat(toDate(datum.value), ...) labelExpr — raw `format` on an ordinal
    # axis is interpreted by d3-format (number format), not d3-time-format, so time
    # directives like %b or %Y silently produce garbage. Route early so subsequent
    # ordinal enrichment (smart labelExpr) respects an already-authored expr.
    if vl_type != "temporal":
        fmt = result.get("format")
        if isinstance(fmt, str) and is_time_format(fmt):
            if "labelExpr" not in result:
                result["labelExpr"] = _utc_time_label_expr(fmt)
            result.pop("format")

    # "nominal" only ever reaches here for heatmap's grid axis (the
    # mark_type == "heatmap" branch in resolve_cartesian_x_type) — it never
    # produces "nominal" for bar's own resolution.
    if (
        vl_type in ("ordinal", "nominal")
        and time_unit
        and time_unit in BUCKETED_CALENDAR_UNITS
    ):
        if "values" not in result:
            tick_values = label_tick_values if label_tick_cadence else all_axis_values
            if tick_values:
                result["values"] = tick_values

        visibility_thinned = (
            visibility_time_unit in BUCKETED_CALENDAR_UNITS
            and visibility_time_unit != label_tu
        )
        if mark_type in _LABEL_THINNING_TICK_MARK_TYPES and (
            label_tick_cadence or visibility_thinned
        ):
            result["ticks"] = True

        # Apply the smart cadence labelExpr whenever the grain was derived from
        # date-like data (temporal OR ordinal bucket strings like "2025-01").
        # Nominal data with a merely-authored time_unit ("Core"/"Growth") stays
        # unformatted. V1 normalized bucket strings to ISO dates first, so it
        # reached this via the temporal path; V2 reads the raw strings.
        if (
            x_type_from_data in ("temporal", "ordinal")
            and "format" not in result
            and "labelExpr" not in result
        ):
            smart_expr = default_label_expr_for(
                time_unit,
                label_tu,
                visibility_time_unit,
                fiscal_year_start_month,
                anchor_index=(
                    0 if label_tick_cadence or "values" in ax_vl else label_anchor_index
                ),
                anchor_value="" if "values" in ax_vl else temporal_anchor_value,
                ticks_are_buckets=True,
                steep_tilt=steep_tilt,
            )
            if smart_expr is not None:
                result["labelExpr"] = smart_expr

    elif vl_type == "temporal" and time_unit and time_unit in BUCKETED_CALENDAR_UNITS:
        if "values" not in result and label_tick_cadence and label_tick_values:
            # A coarser display grain uses source openers so short domains keep
            # every represented period (for example, a six-week Jan–Feb domain
            # gets both month ticks rather than only Vega's interior Feb tick).
            # Visibility thinning remains independent and never changes these.
            result["values"] = label_tick_values
        # Temporal escape-hatch with a bucketed time_unit: emit smart labelExpr so the
        # axis reads human-friendly cadence labels (e.g. "Jan 2024") instead of the
        # raw ISO tick values that Vega emits for utc temporal domains. An authored
        # format is a native d3-time-format on a temporal encoding — it wins outright,
        # same as the ordinal branch's "format" not in result guard.
        #
        if "labelExpr" not in result and "format" not in result:
            smart_expr_t = default_label_expr_for(
                time_unit,
                label_tu,
                visibility_time_unit,
                fiscal_year_start_month,
                anchor_index=0,
                anchor_value=(
                    ""
                    if "values" in ax_vl
                    # Use a calendar-semantic date anchor when the effective
                    # visibility grain differs from the encoding grain.
                    # When they match, datum.index === 0 is simpler and equally
                    # correct for the domain-start tick.
                    else (
                        temporal_anchor_value
                        if anchor_visibility and anchor_visibility != time_unit
                        else ""
                    )
                ),
                ticks_are_buckets=False,
                steep_tilt=steep_tilt,
            )
            if smart_expr_t is not None:
                result["labelExpr"] = smart_expr_t
    # Step-anchored cadence (axis.ticks.time_unit) requires a genuinely
    # continuous temporal x-axis — compile-time gates (_bake_cartesian_axes)
    # already reject it on axis_y, but whether THIS axis resolves to temporal
    # vs ordinal is a data-dependent decision only known here. Unlike count
    # (which silently no-ops on ordinal — see the density-gate test suite),
    # time_unit raises: the whole point of the surface is an explicit cadence,
    # so a silent no-op would hide a misconfiguration rather than surface it.
    # Deliberately NOT moved into apply_x_tick_cadence alongside the step gate:
    # this check is unchanged from before that helper existed, and the emitters
    # that bypass this function have always ignored time_unit. Widening its
    # reach here would newly reject boards that render on main today.
    if axis.ticks.time_unit is not None and vl_type != "temporal":
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.diagnostics.codes_render import (
            ERR_TICKS_INTERVAL_NOT_TEMPORAL,
        )

        raise ChartDataError.from_code(
            ERR_TICKS_INTERVAL_NOT_TEMPORAL, field=x_field, vl_type=vl_type
        )

    # Authored count/step, plus the bare-step gate — both need the resolved
    # vl_type, a data-dependent answer no compile-time check can reach.
    apply_x_tick_cadence(result, axis, x_field, vl_type)

    # The temporal-only half: ticks.time_unit becomes VL's own
    # axis.tickCount: {interval, step} (VL's wire format says "interval"
    # regardless of Dataface's field name), and absent any authored cadence
    # the resolved label grain supplies a default one. Both need the label
    # grain, which is why they stay here rather than in apply_x_tick_cadence.
    if vl_type == "temporal" and "tickCount" not in result and "values" not in result:
        _ticks_time_unit = axis.ticks.time_unit
        if _ticks_time_unit is not None:
            if _ticks_time_unit not in _TEMPORAL_TICK_INTERVAL:
                from dbt_charts.core.diagnostics.chart_data import ChartDataError

                raise ChartDataError(
                    f"ticks.time_unit: {_ticks_time_unit!r} has no step-anchored "
                    "cadence — only a calendar-bucketing grain "
                    f"({', '.join(_TEMPORAL_TICK_INTERVAL)}) names a VL tick "
                    "interval."
                )
            interval, _ = _TEMPORAL_TICK_INTERVAL[_ticks_time_unit]
            tick_count: dict[str, Any] = {"interval": interval}
            if axis.ticks.step is not None:
                tick_count["step"] = axis.ticks.step
            result["tickCount"] = tick_count
        else:
            tick_time_unit = label_tu if label_tu is not None else time_unit
            if tick_time_unit in _TEMPORAL_TICK_INTERVAL:
                interval, step = _TEMPORAL_TICK_INTERVAL[tick_time_unit]
                result["tickCount"] = {"interval": interval, "step": step}

    # Case injection runs last so it wraps any temporal smart-cadence labelExpr
    # that was set above (test: test_temporal_yearmonth_axis_upper_wraps_smart_cadence_expr).
    from dbt_charts.core.render.chart.vl_field_maps import (
        inject_axis_label_case,
        inject_axis_label_values_filter,
    )

    result = inject_axis_label_case(result, axis)
    # labels.values filter runs last of all — it wins over any smart-cadence
    # or case-transformed text already resolved above.
    result = inject_axis_label_values_filter(result, axis)
    return vl_type, result, time_unit


def y_zero_scale(
    axis: ResolvedAxisStyle | Any | None,
    tick_values: list[float] | None = None,
) -> dict[str, Any]:
    """Build a VL y-scale dict from the resolved y-axis style.

    Merges every scale field (``type``, ``base``, ``exponent``, etc.) via
    ``emit_resolved_scale_vl`` — one canonical emitter, so a measure-axis
    ``scale.type: log`` (previously honored only on scatter) reaches
    line/area/bar too. ``zero`` is excluded from that merge and computed
    separately:

    axis.scale.zero is True  → {"domainMin": tick_values[0] or 0.0, "zero": True}
    anything else            → {"zero": False}
    """
    scale = getattr(axis, "scale", None) if axis is not None else None

    out: dict[str, Any] = {}
    if scale is not None:
        out.update(emit_resolved_scale_vl(scale))
        out.pop("zero", None)  # zero is computed below, not passed through raw

    if is_zero_anchored(scale):
        domain_min = tick_values[0] if tick_values else 0.0
        out["domainMin"] = domain_min
        out["zero"] = True
    else:
        out["zero"] = False
    return out


def is_zero_anchored(scale: ResolvedScaleStyle | None) -> bool:
    """True when this measure scale anchors its domain at zero.

    The one spelling of that question: ``y_zero_scale`` branches on it to pin a
    ``domainMin``, and anything that needs to know where the axis actually
    starts reads the same answer rather than re-deriving it. Takes the scale
    rather than the axis so neither caller needs a duck-typed attribute read.
    """
    cont = scale.continuous if scale is not None else None
    return (cont.zero if cont is not None else None) is True


def is_vega_numeric_value(
    value: int | float | Decimal | bool | str | dt.date | dt.datetime,
) -> bool:
    """Whether ``value`` counts as numeric for Vega-Lite type inference.

    The single source of truth for "is this cell numeric" as far as deciding
    a color/measure encoding's VL type goes — ``infer_vega_type_from_data``
    below and ``_channels.py``'s ``_numeric_extent`` both call this so they
    cannot independently drift onto different numeric rules (that drift once
    caused a real bug: a numeric-*string* column got a numeric domain baked
    onto a scale VL was rendering nominal, since a looser string-coercing
    rule was used to compute the domain). Deliberately does NOT accept numeric
    strings — a `"77"` cell is nominal data VL cannot compare against a raw
    number, no matter how a downstream consumer feels about coercing it. Also
    deliberately does NOT exclude ``bool`` (unlike ``coerce_numeric_cell``,
    which does, for a different, render-formatting-cell contract): a boolean
    series field must reach the quantitative "no reorder" skip path (see
    test_shared_spatial_series_order), and ``bool`` is an ``int`` subclass, so
    counting it as numeric is the natural default of the isinstance check.
    Includes ``Decimal`` so warehouse NUMERIC/DECIMAL columns (BigQuery,
    DuckDB) are not misclassified nominal.
    """
    return isinstance(value, (int, float, Decimal))


def infer_vega_type_from_data(data: list[dict[str, Any]], field: str) -> str:
    """Infer the most appropriate Vega-Lite type for a field."""
    if not data or field not in data[0]:
        return "nominal"

    sample_values = [
        row.get(field) for row in data[: min(10, len(data))] if field in row
    ]
    if not sample_values:
        return "nominal"

    all_numeric = True
    all_temporal = True
    all_date_like = True

    for value in sample_values:
        if value is None:
            continue
        if not is_vega_numeric_value(value):
            all_numeric = False
        if isinstance(value, (dt.date, dt.datetime)):
            # date/datetime objects are always temporal; date_like too
            pass
        elif isinstance(value, str):
            # Require an actual date-like structure: YYYY-MM-DD, YYYY/MM/DD,
            # MM/DD/YYYY, or ISO timestamps. The old check (`count("-") >= 2`)
            # was too broad and misidentified strings like "claude-opus-4-7"
            # (3 hyphens, no digits in date positions) as temporal.
            is_standard_date = bool(
                re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}([T ][\d:.].*)?$", value)
                or re.match(r"^\d{2}/\d{2}/\d{4}$", value)
            )
            if not is_standard_date:
                all_temporal = False
            if not is_standard_date and not is_date_like_string(value):
                all_date_like = False
        else:
            all_temporal = False
            all_date_like = False

    if all_numeric:
        return "quantitative"
    if all_temporal:
        return "temporal"
    if all_date_like:
        return "ordinal"
    return "nominal"
