"""Resolve x-axis label visibility and angle at render time."""

from __future__ import annotations

import datetime
import math
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal, NamedTuple

from dbt_charts.core.compile.config import get_chart_rendering
from dbt_charts.core.compile.models.style.resolved import (
    ResolvedAxisElementStyle,
    ResolvedAxisLabelOverlapConfig,
    ResolvedAxisStyle,
)
from dbt_charts.core.font_measure import FontMeasurer, get_font_measurer
from dbt_charts.core.render.chart.time_unit_detect import (
    BUCKETED_CALENDAR_UNITS,
    TIME_PART_UNITS,
    day_week_context,
    detect_time_unit,
    is_label_opener,
    resolve_label_time_unit,
    resolve_temporal_label_visibility,
)
from dbt_charts.core.render.chart.type_inference import infer_vega_type_from_data
from dbt_charts.core.text.format_d3 import portable_strftime


class AxisLabelLayout(NamedTuple):
    """Render-local choices that never mutate the resolved axis style.

    ``collision_label_count`` is ``None`` whenever this module didn't measure
    a residual collision — either because the layout it picked (skip/tilt/
    coarsen) is known to fit, or because no measurement applies (overlap
    disabled, no x field/data, a quantitative axis). It is set to the size of
    the label set actually measured — after whatever skip-narrowing, temporal
    coarsen/anchor thinning, or parity halving that call site applied — only
    at the exact point a "no more strategies left" fallback still doesn't
    fit. Consumed by ``render/chart/axis_label_collision.py`` to record a
    warning fact — this module has no warning-domain knowledge of its own. A
    re-count over the raw input data, as opposed to the set actually
    measured, would misreport by whatever factor that site's narrowing
    applied.
    """

    label_overlap: Literal["allow", "parity"] | None
    angle: float | None
    visibility_time_unit: str | None
    anchor_index: int
    format_time_unit: str
    collision_label_count: int | None = None


AxisDatum = str | int | float | Decimal | datetime.date | datetime.datetime | None


def _generic_temporal_labels(
    values: list[str],
    encoding_time_unit: str,
    format_time_unit: str,
) -> list[str]:
    if not format_time_unit:
        return values
    parsed: list[datetime.datetime] = []
    for value in values:
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            parsed.append(datetime.datetime.fromisoformat(normalized))
        except ValueError:
            return (
                list(dict.fromkeys(values))
                if encoding_time_unit in TIME_PART_UNITS
                else values
            )

    formatters: dict[str, Callable[[datetime.datetime], str]] = {
        "year": lambda value: str(value.year),
        "yearquarter": lambda value: f"Q{(value.month - 1) // 3 + 1}",
        "yearmonth": lambda value: value.strftime("%b"),
        "yearweek": lambda value: portable_strftime(value, "W%V"),
        "yearmonthdate": lambda value: portable_strftime(value, "%-d %b"),
        "monthofyear": lambda value: value.strftime("%b"),
        "dayofweek": lambda value: value.strftime("%a"),
        "dayofmonth": lambda value: str(value.day),
        "dayofyear": lambda value: str(value.timetuple().tm_yday),
        "hourofday": lambda value: str(value.hour),
    }
    formatter = formatters.get(format_time_unit)
    labels = [formatter(value) for value in parsed] if formatter else values
    if encoding_time_unit in TIME_PART_UNITS:
        return list(dict.fromkeys(labels))
    return labels


def _generic_layout(
    axis: ResolvedAxisStyle,
    overlap: ResolvedAxisLabelOverlapConfig,
    widths: list[float],
    usable_width: float,
) -> AxisLabelLayout:
    if _fits_flat(widths, usable_width):
        return AxisLabelLayout("allow", 0.0, None, 0, "")

    directive: Literal["allow", "parity"] = "allow"
    considered_widths = widths
    if overlap.skip:
        directive = "parity"
        considered_widths = widths[::2]
        if _fits_flat(considered_widths, usable_width):
            return AxisLabelLayout(directive, 0.0, None, 0, "")
    if overlap.tilt:
        angle, fits = _pick_tilt_for_widths(
            axis.labels, considered_widths, usable_width
        )
        return AxisLabelLayout(
            directive,
            angle,
            None,
            0,
            "",
            collision_label_count=None if fits else len(considered_widths),
        )
    # Reached only when flat and (if attempted) skip both failed, and tilt
    # is disabled — no strategy left to try, and it does not fit.
    return AxisLabelLayout(
        directive,
        0.0,
        None,
        0,
        "",
        collision_label_count=len(considered_widths),
    )


def _max_pair(widths: list[float]) -> float:
    if len(widths) == 1:
        return widths[0]
    return max((widths[i] + widths[i + 1]) / 2 for i in range(len(widths) - 1))


def _fits_flat(widths: list[float], usable_width: float) -> bool:
    if not widths:
        return True
    band = usable_width / len(widths)
    return _max_pair(widths) <= band


def _submonth_candidate_indices(
    dates: list[datetime.date], encoding_time_unit: str, format_time_unit: str
) -> list[int]:
    if encoding_time_unit == "yearmonthdate" and format_time_unit == "yearweek":
        return [i for i, date in enumerate(dates) if date.weekday() == 0]
    return list(range(len(dates)))


def _submonth_candidate_fits(
    dates: list[datetime.date],
    encoding_time_unit: str,
    format_time_unit: str,
    fiscal_year_start_month: int,
    measurer: FontMeasurer,
    font_size: float,
    usable_width: float,
) -> bool:
    indices = _submonth_candidate_indices(dates, encoding_time_unit, format_time_unit)
    if not indices:
        return False
    band = usable_width / len(dates)
    axis_config = get_chart_rendering().axis
    gaps = (
        axis_config.label_gap_spaces_numeric * measurer.measure(" ", font_size),
        axis_config.label_gap_spaces * measurer.measure(" ", font_size),
    )
    rows: tuple[list[tuple[int, str]], list[tuple[int, str]]] = ([], [])
    for position, index in enumerate(indices):
        date = dates[index]
        context = day_week_context(
            date, format_time_unit, position, fiscal_year_start_month
        )
        rows[0].append((index, str(date.day)))
        if context:
            rows[1].append((index, context))
    for row, gap in zip(rows, gaps, strict=True):
        for (left_i, left), (right_i, right) in zip(row, row[1:], strict=False):
            widths = (
                measurer.measure(left, font_size) + gap,
                measurer.measure(right, font_size) + gap,
            )
            if sum(widths) / 2 > (right_i - left_i) * band:
                return False
    return True


def _pick_tilt_for_widths(
    label: ResolvedAxisElementStyle,
    widths: list[float],
    usable_width: float,
) -> tuple[float, bool]:
    """Shallowest ladder angle whose rotated footprint fits one band.

    Footprint is the rotated label's bounding-box width, ``w*cos(t) +
    line_height*sin(t)``, which does NOT decrease monotonically down the
    ladder. A rung is narrower than every shallower one only for labels wider
    than ``line_height * cot(t/2)`` — at the theme's 11px labels that is
    w > 19px for -60, > 27px for -45, > 41px for -30. Below those widths a mild
    tilt genuinely occupies more horizontal room than flat text ("Apr" rotated
    30 degrees is wider than "Apr" sitting flat), so a short temporal
    vocabulary steps straight from flat to vertical. That is the geometry, not
    a dead rung: a `2015`/`W07` axis at a 22-24px band does pick -60.

    Walking the ladder in order stays optimal even where the sequence widens.
    A rung is only reached once every shallower rung has failed, so a rung no
    narrower than the narrowest of those failures cannot fit either — skipping
    such rungs early would change no result, only the comparison count.
    """
    increments = label.tilt_increments
    if increments is None:
        raise ValueError("label.tilt_increments is not baked in theme")
    if not increments or not widths:
        return 0.0, True
    band = usable_width / len(widths)
    line_height = label.font.size
    max_width = max(widths)
    for angle in increments:
        radians = math.radians(abs(angle))
        footprint = max_width * math.cos(radians) + line_height * math.sin(radians)
        if footprint <= band:
            return float(angle), True
    return float(increments[-1]), False


def _temporal_layout(
    axis: ResolvedAxisStyle,
    overlap: ResolvedAxisLabelOverlapConfig,
    values: list[str],
    label_usable_ratio: float,
    chart_width: float,
    bucket_aligned_temporal: bool,
    edge_labels_flushed: bool,
) -> AxisLabelLayout:
    supported_time_units = BUCKETED_CALENDAR_UNITS | TIME_PART_UNITS
    encoding_time_unit = (
        axis.time_unit
        if axis.time_unit in supported_time_units
        else detect_time_unit(values)
    )
    if encoding_time_unit is None:
        # No custom thinning was computed for this cadence (e.g. a 28-day
        # gap detect_time_unit refuses to call "weekly"). axis_to_vl maps
        # "allow" to labelOverlap=False and None to omitted (VL's own
        # adaptive default) — so skip=False (never drop a label) must
        # resolve to "allow", everything else to None.
        return AxisLabelLayout(None if overlap.skip else "allow", 0.0, None, 0, "")

    font = axis.labels.font
    measurer = get_font_measurer(font.family)
    usable_width = chart_width * label_usable_ratio
    format_time_unit = resolve_label_time_unit(
        encoding_time_unit, axis.labels.time_unit
    )
    dates = [datetime.date.fromisoformat(value[:10]) for value in values]
    if (
        encoding_time_unit in {"yearweek", "yearmonthdate"}
        and axis.labels.time_unit in (None, "auto")
        and bucket_aligned_temporal
    ):
        candidates = (
            ("yearmonthdate", "yearweek")
            if encoding_time_unit == "yearmonthdate"
            else ("yearweek",)
        )
        for candidate in candidates:
            if _submonth_candidate_fits(
                dates,
                encoding_time_unit,
                candidate,
                axis.fiscal_year_start_month,
                measurer,
                font.size,
                usable_width,
            ):
                visibility = candidate if candidate != encoding_time_unit else None
                indices = _submonth_candidate_indices(
                    dates, encoding_time_unit, candidate
                )
                return AxisLabelLayout("allow", 0.0, visibility, indices[0], candidate)
        month_openers = [
            date
            for date in dates
            if is_label_opener(
                date,
                encoding_time_unit,
                "yearmonth",
                axis.fiscal_year_start_month,
            )
        ]
        if len(month_openers) >= 2:
            format_time_unit = "yearmonth"
        else:
            candidate = candidates[-1]
            indices = _submonth_candidate_indices(dates, encoding_time_unit, candidate)
            widths = [
                measurer.measure(str(dates[index].day), font.size) for index in indices
            ]
            angle, fits = (
                _pick_tilt_for_widths(axis.labels, widths, usable_width)
                if overlap.tilt
                else (0.0, _fits_flat(widths, usable_width))
            )
            return AxisLabelLayout(
                "allow",
                angle,
                candidate if candidate != encoding_time_unit else None,
                indices[0],
                candidate,
                collision_label_count=None if fits else len(widths),
            )
    elif encoding_time_unit in {
        "yearweek",
        "yearmonthdate",
    } and axis.labels.time_unit in (None, "auto"):
        gap = get_chart_rendering().axis.label_gap_spaces * measurer.measure(
            " ", font.size
        )
        if encoding_time_unit == "yearmonthdate":
            # _day_label renders two rows ("%-d" over a possibly-blank
            # month/year row); measure that shape directly rather than the
            # single-row _generic_temporal_labels vocabulary, which is wider
            # than what's drawn and would wrongly promote away from daily
            # labels that actually fit.
            native_widths = [
                max(
                    measurer.measure(str(date.day), font.size),
                    measurer.measure(
                        day_week_context(
                            date,
                            encoding_time_unit,
                            position,
                            axis.fiscal_year_start_month,
                        ),
                        font.size,
                    ),
                )
                + gap
                for position, date in enumerate(dates)
            ]
        else:
            native_labels = _generic_temporal_labels(
                values, encoding_time_unit, encoding_time_unit
            )
            native_widths = [
                measurer.measure(value, font.size) + gap for value in native_labels
            ]
        month_openers = [
            date
            for date in dates
            if is_label_opener(
                date,
                encoding_time_unit,
                "yearmonth",
                axis.fiscal_year_start_month,
            )
        ]
        native_fits = _fits_flat(native_widths, usable_width)
        if len(month_openers) < 2 or (
            encoding_time_unit == "yearmonthdate" and native_fits
        ):
            return _generic_layout(axis, overlap, native_widths, usable_width)._replace(
                format_time_unit=encoding_time_unit
            )
        format_time_unit = "yearmonth"

    if (
        encoding_time_unit not in BUCKETED_CALENDAR_UNITS
        or format_time_unit not in BUCKETED_CALENDAR_UNITS
    ):
        if format_time_unit is None:
            format_time_unit = (
                encoding_time_unit if encoding_time_unit in TIME_PART_UNITS else ""
            )
        labels = _generic_temporal_labels(
            values,
            encoding_time_unit,
            format_time_unit,
        )
        widths = [measurer.measure(value, font.size) for value in labels]
        gap = get_chart_rendering().axis.label_gap_spaces * measurer.measure(
            " ", font.size
        )
        return _generic_layout(
            axis, overlap, [width + gap for width in widths], usable_width
        )._replace(format_time_unit=format_time_unit)

    band = usable_width / len(dates)
    visibility, fits = resolve_temporal_label_visibility(
        dates,
        encoding_time_unit,
        format_time_unit,
        measurer,
        font.size,
        band,
        axis.fiscal_year_start_month,
        allow_skip=overlap.skip,
        edge_labels_flushed=edge_labels_flushed,
    )
    visible_indices = [
        i
        for i, date in enumerate(dates)
        if is_label_opener(
            date,
            encoding_time_unit,
            visibility,
            axis.fiscal_year_start_month,
        )
    ]
    anchor_index = visible_indices[0] if visible_indices else 0
    # At year cadence the label vocabulary promotes to the bare year (every
    # visible tick is a January, so "Jan" repeated at every tick carries no
    # information) — see resolve_temporal_label_visibility's docstring. Every
    # other rung keeps the caller's own vocabulary unchanged.
    promoted_format_time_unit = "year" if visibility == "year" else format_time_unit
    if fits:
        return AxisLabelLayout(
            "allow", 0.0, visibility, anchor_index, promoted_format_time_unit
        )

    visible_dates = [
        date
        for date in dates
        if is_label_opener(
            date,
            encoding_time_unit,
            visibility,
            axis.fiscal_year_start_month,
        )
    ]
    directive: Literal["allow", "parity"] = "allow"
    narrowed_further = False
    if overlap.skip and visibility == "year":
        directive = "parity"
        visible_dates = visible_dates[::2]
        narrowed_further = True
    if promoted_format_time_unit == "yearmonthdate":
        # _day_label renders two rows ("%-d" over a possibly-blank month/year
        # row) — measure that shape, not a single-row string nothing draws.
        widths = [
            max(
                measurer.measure(str(date.day), font.size),
                measurer.measure(
                    day_week_context(
                        date,
                        promoted_format_time_unit,
                        position,
                        axis.fiscal_year_start_month,
                    ),
                    font.size,
                ),
            )
            for position, date in enumerate(visible_dates)
        ]
    else:
        label_texts: dict[str, Callable[[datetime.date], str]] = {
            "year": lambda date: str(date.year),
            "yearquarter": lambda date: f"Q{(date.month - 1) // 3 + 1}",
            "yearmonth": lambda date: date.strftime("%b"),
            "yearweek": lambda date: portable_strftime(date, "W%V"),
        }
        widths = [
            measurer.measure(label_texts[promoted_format_time_unit](date), font.size)
            for date in visible_dates
        ]
    if overlap.tilt:
        angle, fits = _pick_tilt_for_widths(axis.labels, widths, usable_width)
        return AxisLabelLayout(
            directive,
            angle,
            visibility,
            anchor_index,
            promoted_format_time_unit,
            collision_label_count=None if fits else len(widths),
        )
    # No tilt to try. Absent further narrowing, `widths` is the exact set
    # `resolve_temporal_label_visibility` already judged not-fit via its
    # flush-edge-aware pairwise check above — re-deriving with `_fits_flat`'s
    # coarser uniform-band average could disagree and silently overwrite a
    # real collision. Only the year-cadence parity skip produces a set that
    # was never checked and needs a fresh verdict.
    fits = _fits_flat(widths, usable_width) if narrowed_further else False
    return AxisLabelLayout(
        directive,
        0.0,
        visibility,
        anchor_index,
        promoted_format_time_unit,
        collision_label_count=None if fits else len(widths),
    )


def resolve_axis_x_overlap(
    axis: ResolvedAxisStyle,
    x_field: str | None,
    data: list[dict[str, AxisDatum]],
    label_usable_ratio: float,
    *,
    is_horizontal_bar: bool = False,
    bucket_aligned_temporal: bool = True,
    edge_labels_flushed: bool,
    chart_width: float,
    domain_values: list[Any] | None = None,
) -> AxisLabelLayout:
    """Return render-local overlap, angle, and temporal visibility choices.

    ``domain_values`` is the x scale's full band domain when overlay layers
    extend it past the base series (``overlay_x_domain_values``). Crowding
    must be measured against the bands that actually render — measuring the
    base's own rows on a layered chart under-counts them and picks a flatter
    angle or finer cadence than the rendered axis has room for. Honoured on
    both the temporal and the ordinal/nominal branch: the tilt angle below is
    picked from the same ``widths``/``usable_width`` the flat-fit gate just
    measured, never re-derived from ``data`` alone.
    """
    overlap = axis.labels.overlap
    if overlap is None:
        return AxisLabelLayout(None, axis.labels.angle, None, 0, "")
    if axis.labels.angle is not None:
        return AxisLabelLayout("allow", axis.labels.angle, None, 0, "")
    if is_horizontal_bar:
        return AxisLabelLayout("allow", 0.0, None, 0, "")
    if not x_field or not data:
        return AxisLabelLayout("allow", 0.0, None, 0, "")

    raw_type = infer_vega_type_from_data(data, x_field)
    if raw_type == "quantitative":
        return AxisLabelLayout("allow", 0.0, None, 0, "")
    values = list(
        dict.fromkeys(
            str(v)
            for v in (
                domain_values
                if domain_values is not None
                else (
                    row[x_field]
                    for row in data
                    if x_field in row and row[x_field] is not None
                )
            )
        )
    )
    if not values:
        return AxisLabelLayout("allow", 0.0, None, 0, "")
    if raw_type == "temporal":
        return _temporal_layout(
            axis,
            overlap,
            sorted(values),
            label_usable_ratio,
            chart_width,
            bucket_aligned_temporal,
            edge_labels_flushed,
        )

    font = axis.labels.font
    measurer = get_font_measurer(font.family)
    widths = [measurer.measure(value, font.size) for value in values]
    gap = get_chart_rendering().axis.label_gap_spaces * measurer.measure(" ", font.size)
    widths = [width + gap for width in widths]
    usable_width = chart_width * label_usable_ratio
    flat_fits = _fits_flat(widths, usable_width)
    if overlap.tilt and not flat_fits:
        angle, fits = _pick_tilt_for_widths(axis.labels, widths, usable_width)
        return AxisLabelLayout(
            "allow",
            angle,
            None,
            0,
            "",
            collision_label_count=None if fits else len(widths),
        )
    return AxisLabelLayout(
        "allow",
        0.0,
        None,
        0,
        "",
        collision_label_count=None if flat_fits else len(widths),
    )
