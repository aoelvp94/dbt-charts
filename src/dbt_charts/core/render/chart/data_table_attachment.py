"""Vega-Lite attachment for the chart.data_table primitive.

Post-pass on a chart-body Vega-Lite spec. Given a validated ChartDataTable
and the chart's x-encoding, emit:
- An optional strip-top divider rule (when divider.width > 0).
- One text layer per row — source rows use a format() calculate transform;
  aggregate rows add a Vega-Lite aggregate transform grouped by x.
- N-1 inter-row rule layers when row.rule.width > 0.
- One label text layer per row that carries label: — emitted at the
  y-axis tick label's x-anchor (right gutter for right-oriented axes,
  left gutter for left-oriented axes), derived from the resolved axis_y.orient.

No new primitives: every output layer is standard Vega-Lite (mark: text,
mark: rule).

Y-positioning is pixel-literal (`{"y": {"value": <px>}}`), computed from
the spec's explicit height plus per-row offsets. Vega-Lite treats
`{"y": {"expr": "..."}}` as a SCALED data value (not a pixel literal),
so the previous expr-based approach collapsed every row to one pixel
position via the parent's quantitative y-scale. Spec.height must be set
when data_table is non-None — auto-sized specs have no anchor.

The caller owns the space reservation for position:bottom via
``bump_padding_bottom``. For position:top the mechanism depends on whether
the chart has a title (not subtitle alone):
- Titled charts: ``title.offset = strip_h`` (the probe value) so the title's
  absolute position is invariant to the offset amount (verified: under
  autosize:pad the title stays fixed regardless of title.offset value).
  ``layout_sizing._correct_data_table_height`` calibrates the probe offset
  downward so the true gap between title baseline and strip top equals
  strip_h rather than strip_h + VL's natural baseline gap.
- Subtitle-only and titleless charts: ``bump_padding_top`` — VL does not emit
  a role-title-text element that _measure_vl_title_plot_gap can anchor on
  when there is no title, so the original padding mechanism is used instead.
The renderer's downstream finalize step respects the external padding kwarg
when supplied.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from d3_format import FormatSpec, parse as _d3_parse
from dbt_charts.core.compile.config import get_chart_rendering
from dbt_charts.core.compile.data_table import row_height
from dbt_charts.core.compile.format import resolve_format
from dbt_charts.core.compile.models.chart.authored import (
    ChartDataTable,
    ChartDataTableAggregate,
    ChartDataTableAggregateOp,
    ChartDataTablePerSeries,
    ChartDataTableSource,
)
from dbt_charts.core.compile.models.chart.resolved import (
    FormatState,
    effective_color_field,
)
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.primitives import FormatConfig
from dbt_charts.core.compile.models.style.resolved import (
    ResolvedAxisStyle,
    ResolvedChartDefaults,
)
from dbt_charts.core.compile.models.style.theme import DataTableStyle
from dbt_charts.core.diagnostics import ERR_INPUT_INVALID
from dbt_charts.core.font_measure import get_font_measurer
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.artifacts import ChartRenderData
from dbt_charts.core.render.chart.spec_builders import (
    bump_padding_bottom,
    bump_padding_top,
)
from dbt_charts.core.render.chart.time_unit_detect import (
    detect_time_unit,
    normalize_labeled_temporal,
    opens_label_period,
    resolve_label_time_unit,
    resolve_temporal_label_visibility,
)
from dbt_charts.core.render.chart.type_inference import (
    is_lex_sortable_date_like,
    temporal_edge_labels_flushed,
)
from dbt_charts.core.render.errors import RenderError
from dbt_charts.core.render.format_utils import format_value
from dbt_charts.core.text.case import inferred_display_name
from dbt_charts.core.text.numeral_scale import (
    SuffixMode,
    column_digit_format,
    shared_scale_for_column,
    suffix_at_register,
    tier_distance,
)
from dbt_charts.core.text.predefined_formats import PREDEFINED_NUMBER_NAMES

# Map authoring-surface aggregate names to Vega-Lite aggregate ops.
# Authoring names stay exact; the compiler is free to translate to VL ops.
# Keys are the ChartDataTableAggregateOp Literal values; the test guard
# test_agg_op_map_keys_are_all_authoring_surface_ops enforces coverage.
_AGG_OP_TO_VL: dict[ChartDataTableAggregateOp, str] = {
    "sum": "sum",
    "avg": "mean",
    "min": "min",
    "max": "max",
    "median": "median",
    "count": "count",
    "count_distinct": "distinct",
}

# Row labels share the y-axis tick column (~50–70 px for typical numeric
# formats). 80 px accommodates labels up to ~12 chars at 11 px Inter without
# the label reaching visibly into the legend zone or over-shrinking the plot.
_LABEL_STUB_LIMIT_PX = 80.0


def _strip_height(style: DataTableStyle, n_rows: int) -> float:
    """Total pixel height for the attached strip (position-agnostic)."""
    row_h = row_height(style)
    divider_gap = get_chart_rendering().data_table.divider_gap
    divider = (style.divider.width + divider_gap) if style.divider.width > 0 else 0.0
    inter_row = (
        style.row.rule.width * (n_rows - 1)
        if style.row.rule.width > 0 and n_rows > 1
        else 0.0
    )
    return (
        style.padding_top + divider + row_h * n_rows + inter_row + style.padding_bottom
    )


def data_table_strip_height(
    data_table: ChartDataTable | None,
    style: DataTableStyle,
    axis_offset_value: float | None,
    series_count: int = 0,
) -> float:
    """Pixel height to reserve on the appropriate padding side when attaching a strip.

    Data-aware: ``series_count`` is the size of the color domain the query
    produced, so this runs at render time alongside ``attach_data_table``.

    For ``position: bottom``: includes the axis-label gap between the plot bottom
    and the strip top; callers pass the result to ``padding.bottom``.

    For ``position: top``: no axis gap (x-axis is below the plot); callers pass
    the result to ``padding.top``.

    Returns 0 when no strip is attached.

    Args:
        data_table: The data_table block, or None for no strip.
        style: Resolved DataTableStyle (must carry ``position``).
        axis_offset_value: The resolved chart's own baked
            ``data_table_axis_offset`` (compile/resolve time — see
            ``compile.resolve._kwargs._data_table_geometry``). Required
            (non-None) when ``style.position == "bottom"``.
        series_count: How many series each ``per_series:`` entry expands to.
            All per_series entries on the same chart share one color domain,
            so one int suffices for the strip-height accounting. Required
            (>0) when any entry is ``ChartDataTablePerSeries`` — leaving it
            at 0 with a per_series entry present silently under-sizes the
            strip and the expanded rows render below the reserved padding.
            RenderError is raised in that case rather than guessing 1.
    """
    if data_table is None or not data_table.entries:
        return 0.0
    n_rows = 0
    for entry in data_table.entries:
        if isinstance(entry, ChartDataTablePerSeries):
            if entry.by_measure:
                n_rows += 1
            else:
                if series_count <= 0:
                    raise RenderError.from_code(
                        ERR_INPUT_INVALID,
                        message=(
                            "data_table_strip_height needs series_count > 0 when any "
                            "entry is `per_series:` — pass the number of color-domain "
                            "series the chart expands to. Defaulting to 1 silently "
                            "under-sizes the strip and the expanded rows render below "
                            "the reserved padding."
                        ),
                    )
                n_rows += series_count
        else:
            n_rows += 1
    strip_h = _strip_height(style, n_rows)
    if style.position == "bottom":
        assert axis_offset_value is not None, (
            "axis_offset_value is required when style.position == 'bottom' — "
            "the resolved chart's data_table_axis_offset must be baked (see "
            "compile.resolve._kwargs._data_table_geometry)"
        )
        return axis_offset_value + strip_h
    # top: x-axis is below the plot — no axis gap above the strip.
    return strip_h


def validate_data_table_against_data(
    data_table: ChartDataTable,
    x_field: str | None,
    data: list[dict[str, Any]],
    x_type: str | None = None,
) -> int:
    """Data-aware validation of a data_table block.

    Runs at render time where the actual query output is available.
    Complements the data-free checks in AuthoredChart.validate_data_table
    (duplicate entries, chart-type, multi-y).

    For temporal/quantitative x axes with more than
    ``chart_rendering.data_table.chart_data_table_max_x_ticks`` rows, sampling
    is applied instead of failing. Returns the sampling step (>= 1); step=1
    means no sampling is needed.

    For ordinal/nominal/unknown x_type exceeding the cap, raises RenderError
    (fail-closed: dropping categories silently would be wrong).

    Raises:
        RenderError (ERR-INPUT-INVALID) on violation. Messages are
        explicit — they name the offending field and point at the resolution
        (e.g., "Add 'aggregate: <op>'...").
    """
    # x-axis existence check.
    if not x_field:
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message=(
                "chart.data_table requires an x-encoding; the chart has no "
                "`x:` field. Add `x: <column>` or remove the data_table block."
            ),
        )

    # x-axis cardinality cap.
    x_values = {row.get(x_field) for row in data if x_field in row}
    n = len(x_values)
    sampling_step = 1
    max_x_ticks = get_chart_rendering().data_table.chart_data_table_max_x_ticks
    if n > max_x_ticks:
        if x_type in ("temporal", "quantitative"):
            # Temporal/quantitative: thin the strip labels via Vega-Lite
            # window+filter transforms. The chart data layers are unaffected.
            # Continue validating the checks below — an early return here
            # would silently skip the source-column-presence and
            # ambiguous-aggregation checks.
            sampling_step = math.ceil(n / max_x_ticks)
        else:
            raise RenderError.from_code(
                ERR_INPUT_INVALID,
                message=(
                    f"chart.data_table supports at most "
                    f"{max_x_ticks} x-axis ticks; got "
                    f"{n}. Aggregate or filter in the query before "
                    "rendering an attached table."
                ),
            )

    # Source column presence check: every referenced column must be present
    # in the query output. Use the first row as the schema sample (mirrors
    # how the rest of the render pipeline reads row shape).
    if data:
        available = set(data[0].keys())
        for entry in data_table.entries:
            if isinstance(entry, ChartDataTablePerSeries):
                source_col = entry.per_series
            else:
                source_col = entry.source
            if source_col not in available:
                cols = ", ".join(sorted(available))
                raise RenderError.from_code(
                    ERR_INPUT_INVALID,
                    message=(
                        f"chart.data_table entry references source column "
                        f"{source_col!r} which is not in the query output. "
                        f"Available columns: {cols}."
                    ),
                )

    # Ambiguous-aggregation guard: a bare `source:` entry is ambiguous if the
    # query returns multiple rows per x. Point the author at `aggregate:`.
    # Normal per_series entries (by_measure=False) are exempt — they aggregate
    # groupby [x, color] and expect multiple rows per x.
    # by_measure entries are NOT exempt — they read datum[field] directly with
    # no aggregation transform, so multiple rows per x produce a wrong result.
    if data and x_field:
        counts = Counter(row.get(x_field) for row in data)
        multi_row = any(c > 1 for c in counts.values())
        if multi_row:
            for entry in data_table.entries:
                is_aggregate = isinstance(entry, ChartDataTableAggregate)
                is_normal_per_series = (
                    isinstance(entry, ChartDataTablePerSeries) and not entry.by_measure
                )
                if not is_aggregate and not is_normal_per_series:
                    source_col = (
                        entry.per_series
                        if isinstance(entry, ChartDataTablePerSeries)
                        else entry.source
                    )
                    raise RenderError.from_code(
                        ERR_INPUT_INVALID,
                        message=(
                            f"chart.data_table entry references column {source_col!r} "
                            f"which is ambiguous on this chart — {x_field!r} "
                            "returns multiple rows per x. Add "
                            f"'aggregate: <op>' (e.g. 'aggregate: sum, "
                            f"source: {source_col}') to resolve."
                        ),
                    )

    return sampling_step


def _row_y_pixel(
    index: int,
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
) -> float:
    """Pixel y of the centroid of the ith row in the attached strip.

    For ``position: bottom``: y > spec_height (strip below the plot). Row 0 is
    closest to the plot (first below the divider); row index increases downward.

    For ``position: top``: y < 0 (strip above the plot, in padding.top zone).
    Row 0 is closest to the plot top (y nearest 0); row index increases upward
    (y becomes more negative). No axis-offset is needed since the x-axis is below.
    """
    divider_off = (
        style.divider.width + get_chart_rendering().data_table.divider_gap
        if style.divider.width > 0
        else 0.0
    )
    row_h = row_height(style)
    inter_row = (
        style.row.rule.width * index if style.row.rule.width > 0 and index > 0 else 0.0
    )
    if style.position == "bottom":
        assert axis_offset_value is not None, (
            "axis_offset_value is required when style.position == 'bottom'"
        )
        offset = (
            style.padding_top
            + axis_offset_value
            + divider_off
            + index * row_h
            + inter_row
            + row_h / 2.0
        )
        return spec_height + offset
    # top: measure from y=0 (plot top) going upward (negative y).
    # Row 0 is closest to the plot; row N is furthest above.
    # Layout (from y=0 upward): padding_bottom, then rows (0…N), then padding_top.
    # Divider sits just above y=0, between padding_bottom and rows.
    dist_from_plot_top = (
        style.padding_bottom + divider_off + index * row_h + inter_row + row_h / 2.0
    )
    return -dist_from_plot_top


def _divider_y_pixel(
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
) -> float:
    """Pixel y of the divider rule.

    For ``position: bottom``: divider sits between the axis and the strip rows
    (just below axis labels), at spec_height + padding_top + axis_offset.

    For ``position: top``: divider sits between the strip rows and the plot top
    (just above y=0), at -(padding_bottom).
    """
    if style.position == "bottom":
        assert axis_offset_value is not None, (
            "axis_offset_value is required when style.position == 'bottom'"
        )
        return spec_height + style.padding_top + axis_offset_value
    # top: divider is the boundary between strip and plot.
    return -style.padding_bottom


def _inter_row_rule_y_pixel(
    index: int,
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
) -> float:
    """Pixel y of the inter-row rule between row `index` and row `index + 1`.

    Centroid sits in the middle of the inter-row gap so the rule's stroke
    splits evenly between the two adjacent rows; without the half-stroke
    offset the rule biases visually toward the row above.

    For ``position: bottom``: row y values increase downward, so the rule
    between row 0 and row 1 is *below* row 0's centroid → add half-row +
    half-stroke.

    For ``position: top``: row y values are negative (above the plot) and
    become *more negative* as index increases. The rule between row 0 and
    row 1 must be *more negative* than row 0's centroid → subtract.
    """
    row_y = _row_y_pixel(index, style, axis_offset_value, spec_height)
    half_gap = row_height(style) / 2.0 + style.row.rule.width / 2.0
    if style.position == "bottom":
        return row_y + half_gap
    # top: "between rows" is more negative (further above plot)
    return row_y - half_gap


# Row number over the cells that survive every filter, so "the first drawn
# cell" is true by construction. Distinct from ``__data_table_row_index``,
# which _sampling_transforms numbers *before* its own filter and which would
# therefore anchor on a row that was thinned away.
DRAWN_INDEX_FIELD = "__data_table_drawn_index"
# 1 on every drawn cell that can carry the unit (valid, finite, non-zero), 0
# otherwise. A cumulative sum of this over the drawn cells makes the anchor the
# first cell that CAN carry the affix, not merely the first drawn -- a metric
# whose first period is 0 would otherwise anchor on "$0" and declare the
# magnitude nowhere.
CARRIES_FIELD = "__data_table_carries"


def _drawn_index_transform(
    x_field: str,
    value_field: str,
    suffix_is_magnitude: bool,
    sort_ascending: bool = True,
) -> list[VLDict]:
    """Rank drawn cells so the anchor lands on the first unit-carrying one.

    Flags each drawn cell as carrying then takes a running sum:
    the first carrying cell is the one where both the flag and the running
    total equal 1.

    For a magnitude suffix the zero check is part of "carrying": "0mn" is
    meaningless, so a zero cell cannot be the anchor. For percent and currency-
    prefix-only rows a zero cell carries its affix perfectly well ($0 and 0%
    are real readings), so the ``!== 0`` gate is omitted there.

    When sort_ascending is True (default, temporal path) the window sorts by
    x ascending to match VL's own paint order. When False (sort:null category
    path), the window uses the input row order, which for sort:null axes is
    the data-insertion order — the same order VL uses to assign bands.
    """
    nonzero = (
        f" && datum[{json.dumps(value_field)}] !== 0" if suffix_is_magnitude else ""
    )
    carries = (
        f"isValid(datum[{json.dumps(value_field)}]) "
        f"&& isFinite(datum[{json.dumps(value_field)}])"
        f"{nonzero} ? 1 : 0"
    )
    window: VLDict = {
        "window": [{"op": "sum", "field": CARRIES_FIELD, "as": DRAWN_INDEX_FIELD}],
        "frame": [None, 0],
    }
    if sort_ascending:
        window["sort"] = [{"field": x_field, "order": "ascending"}]
    return [{"calculate": carries, "as": CARRIES_FIELD}, window]


@dataclass(frozen=True)
class StripAnchor:
    """Which single cell declares the row's unit, and how the spec asks.

    Three mechanisms covering the three axis families.

    An **ordered** axis can be thinned (sampling, label-period openers), so the
    first cell painted is not the first row of data. A row number computed
    *after* every filter answers that: ``by_drawn_index`` sorts the window
    ascending (matching VL's own paint order) for true temporal axes.

    A **sort:null category** axis tells VL to paint the domain in data-insertion
    order; ``by_drawn_index_data_order`` uses an unsorted window so the index
    follows that same insertion order. This path is immune to period-filter
    (window runs after filter) and datetime normalization (no x-value comparison).

    ``nowhere`` covers everything that can't be anchored (authored sort, left-
    aligned strip, quantitative x): no window, no conditional expression, just
    affix-free per-cell formatting.
    """

    test: str
    needs_drawn_index: bool
    # True when the window must run in data-insertion order (sort:null category
    # path) rather than ascending-x order (temporal path).
    data_order: bool = False

    @staticmethod
    def by_drawn_index() -> StripAnchor:
        """Temporal path: window sorted ascending by x, matching VL's paint order."""
        return StripAnchor(
            f"datum.{CARRIES_FIELD} === 1 && datum.{DRAWN_INDEX_FIELD} === 1", True
        )

    @staticmethod
    def by_drawn_index_data_order() -> StripAnchor:
        """sort:null category path: unsorted window follows data-insertion order.

        Immune to query-order swaps, datetime normalization mismatches, and
        period-filter dropping the x-equality anchor cell — the window runs
        after every filter so the first surviving cell in data order gets index 1.
        """
        return StripAnchor(
            f"datum.{CARRIES_FIELD} === 1 && datum.{DRAWN_INDEX_FIELD} === 1",
            True,
            data_order=True,
        )

    @staticmethod
    def nowhere() -> StripAnchor:
        """No cell declares the unit — the row repeats it, as it always has.

        Used where the leftmost painted cell cannot be identified: an authored
        ``sort:``, a quantitative x, or a time-format spec. Carries no test
        expression because it pairs only with affix-free numerals, which emit
        no conditional at all — a test string here would be one the emitter can
        never reach.
        """
        return StripAnchor("", False)


@dataclass(frozen=True)
class StripNumerals:
    """How one strip row spells its numbers.

    Split from the entry's format once, by ``strip_numerals_for_values``,
    rather than re-parsed at emission — the same bake-once shape
    ``ResolvedRulerAxis`` uses, for the same reason: the text a cell paints and
    the width the band-centring dx is measured against must come from one
    computation, not two.

    Two spellings, because only one family needs the author's spec rewritten:

    ``$,.3s`` → ``$441mn  448  456``   COMPOSED: d3's ``s`` type re-picks a
        tier per value, which is the behavior this feature exists to
        override, so the row divides by one shared magnitude and formats the
        digits through a rebuilt fixed-point spec.
    ``,.1%``  → ``5.5%    5.9  6.2``   TRIMMED: nothing about the number
    ``$,.0f`` → ``$441    448  456``   changes, so every cell formats through
        the author's own spec untouched — sign, fill, width, zero pad and trim
        all survive — and the cells that don't declare the unit simply have
        the repeated affix removed from the formatted string.
    """

    # The d3 spec each cell formats through: the author's own on a trimmed
    # row, a rebuilt fixed-point spec on a composed one.
    digit_spec: str
    # Which single cell declares the unit. Carried here rather than threaded
    # beside this object: a row that declares nothing has no anchor to speak
    # of, so the two are never meaningfully independent.
    anchor: StripAnchor
    prefix: str = ""
    suffix: str = ""
    # Composed rows only. The shared tier every cell divides by, plus the two
    # rules a magnitude suffix follows that a unit suffix does not: it is
    # dropped on a zero cell ("0mn" is meaningless, and zero is zero at any
    # scale, unlike 0% which is a real reading), and it repeats once the row
    # outgrows the tier it names (numeral_scale's own rule).
    divisor: float = 1.0
    suffix_is_magnitude: bool = False
    repeat_suffix: bool = False
    # Which side the anchor's affix overhangs. "left" (default): affix leads
    # the digits, hanging into the y-axis gutter — current right-oriented axis
    # behavior. "right": affix trails the digits, hanging into the anchor cell's
    # own band — left-oriented axis behavior, which keeps digits left-aligned.
    hang: Literal["left", "right"] = "left"

    def bare_text(self, value: float) -> str:
        """The text a cell that does NOT declare the unit paints.

        The width pass measures this rather than the anchor's: the anchor
        carries affixes no sibling does, so sizing the lane to it would push
        every bare cell off the band it labels. A REPEAT row is the exception —
        there every non-zero cell paints the suffix, so it belongs in the width.
        """
        text = format_value(value / self.divisor, self.digit_spec, None)
        if self.suffix_is_magnitude:
            return text + self.suffix if self.repeat_suffix and value != 0 else text
        for affix in (self.prefix, self.suffix):
            if affix:
                text = text.replace(affix, "", 1)
        return text

    def anchor_text(self, value: float) -> str:
        """The text the anchor cell paints — all affixes included.

        Used only for width measurement so the band budget accounts for the
        widest *painted* cell, not just the bare one. Temporal anchors may
        land on band 2+ (when the first period is zero), so the band must be
        at least as wide as the anchor to prevent overlap with its neighbour.
        """
        if not (self.prefix or self.suffix):
            return self.bare_text(value)
        if self.suffix_is_magnitude:
            digits = format_value(abs(value) / self.divisor, self.digit_spec, None)
            sign = "−" if value < 0 else ""
            suffix = self.suffix if value != 0 else ""
            return sign + self.prefix + digits + suffix
        # Trimmed: the d3 format output already contains the affix.
        return format_value(value, self.digit_spec, None)

    @property
    def needs_drawn_index_window(self) -> bool:
        """Whether the emitted expression actually reads the drawn index.

        Only an affix gated on the anchor does. A REPEAT row's suffix rides
        every non-zero cell, so a REPEAT row with no prefix reads no index and
        must not carry the window -- a transform nothing references is exactly
        the surprise this render layer refuses to emit.
        """
        if not self.anchor.needs_drawn_index:
            return False
        anchored = bool(self.prefix) or (bool(self.suffix) and not self.repeat_suffix)
        return anchored


def _strip_numerals_text_expr(value_expr: str, numerals: StripNumerals) -> str:
    """Cell text for a row whose unit is declared once.

    A magnitude suffix speaks the narrative register (``441mn``), not
    ``SharedScale.register``'s mode-derived answer: a strip's cells are already
    separated by band space, so the analytic form's leading space would be a
    second separator competing with the first.

    The prefix anchors even when the suffix repeats — repeating a currency
    symbol on every cell disambiguates nothing (the convention
    ``plain_digit_format`` documents, shared with the axis).
    """
    anchor_test = numerals.anchor.test

    if not (numerals.prefix or numerals.suffix):
        # Nothing repeats, so nothing is declared: every cell paints the
        # author's own spec, byte for byte what this row emitted before.
        return f"format({value_expr}, '{numerals.digit_spec}')"

    if not numerals.suffix_is_magnitude:
        # Trimmed: format through the author's spec, then remove the affix it
        # repeats. Rebuilding the spec from parts is what silently dropped a
        # `+` sign or a zero pad; removing a known affix from the result
        # cannot, whatever else the spec asks for.
        full = f"format({value_expr}, '{numerals.digit_spec}')"
        bare = full
        for affix in (numerals.prefix, numerals.suffix):
            if affix:
                bare = f"replace({bare}, {json.dumps(affix)}, '')"
        if numerals.hang == "left":
            return f"({anchor_test} ? {full} : {bare})"
        # hang="right" (left-axis): prefix-carrying formats route to nowhere before
        # reaching here, so this path only ever carries a suffix (percent). The
        # early `if not (prefix or suffix)` return above already excludes the
        # empty case, so suffix is always truthy by the time control reaches here.
        # Anchor arm is bare + conditional suffix so digit left-edges align.
        anchor_expr = f"({bare} + ({anchor_test} ? {json.dumps(numerals.suffix)} : ''))"
        return f"({anchor_test} ? {anchor_expr} : {bare})"

    # The sign expression leads the composition: d3 renders a negative currency
    # as "-$448", so the sign must precede the anchored symbol. All reachable
    # predefined SI specs use the default "-" sign convention (negative \u2192
    # U+2212, positive \u2192 nothing).
    digits = (
        f"format(abs({value_expr}) / {numerals.divisor!r}, '{numerals.digit_spec}')"
    )
    nonzero = f"{value_expr} !== 0"
    present = nonzero if numerals.repeat_suffix else f"{nonzero} && {anchor_test}"
    suffix_part = f"({present} ? {json.dumps(numerals.suffix)} : '')"
    sign_part = f"({value_expr} < 0 ? '\u2212' : '')"
    parts = [sign_part, digits, suffix_part]
    if numerals.prefix:
        # Prefix leads digits, hanging into the y-axis gutter (right-axis only;
        # prefix-carrying formats on left-axis route to StripAnchor.nowhere()).
        parts.insert(1, f"({anchor_test} ? {json.dumps(numerals.prefix)} : '')")
    return " + ".join(parts)


def _magnitude_numerals(
    values: list[float],
    resolved: str,
    parsed: FormatSpec,
    anchor: StripAnchor,
    hang: Literal["left", "right"] = "left",
) -> StripNumerals:
    """Numerals for an SI row: one shared tier, and a derived decimal depth.

    Decimal depth is set by ``column_digit_format``, which pins precision to
    the finest (smallest non-zero) scaled value so that every cell in the row
    reaches its significant-figure count — the same formula the table's
    shared-scale column bake uses, ensuring strip and table never diverge.

    Zero and non-finite cells are excluded from that vote, the way
    ``shared_scale_for_column`` already excludes zeros from its tier vote: a
    zero scales to "0", one integer digit, and would otherwise buy the whole
    row a significant figure it never asked for.

    If the finest value is more than one SI tier below the shared majority
    (``tier_distance > 1``) the shared bake is refused: one outlier would
    inflate every other cell's precision far beyond the format's own
    significant-figure count. The row then keeps the author's spec, the
    same guard ``_table.py``'s shared-scale column bake applies.

    For a left-oriented axis (``hang="right"``), a currency prefix cannot anchor
    without leaving the unit absent from non-anchor cells. Such formats route to
    ``StripAnchor.nowhere()`` so every cell formats with its own spec unchanged.
    """
    if hang == "right" and parsed.symbol:
        return StripNumerals(digit_spec=resolved, anchor=StripAnchor.nowhere())
    # Filter before the scale call: shared_scale_for_column floors and counts
    # digits, which raises on NaN and overflows on inf.
    voters = [v for v in values if v != 0 and math.isfinite(v)]
    scale = shared_scale_for_column(voters) if voters else None
    if scale is None or not voters:
        # No shared magnitude to declare — the row keeps the author's spec.
        return StripNumerals(digit_spec=resolved, anchor=anchor, hang=hang)
    magnitude = 10.0**scale.exponent
    finest = min(voters, key=abs)
    distance = tier_distance(finest, scale.exponent)
    if distance is None or distance > 1:
        # Finest value is below all SI tiers, or more than one tier below the
        # majority — the shared bake would need so many decimals for that one
        # value that every sibling cell inherits unwarranted precision. Refuse.
        return StripNumerals(digit_spec=resolved, anchor=anchor, hang=hang)
    finest_scaled = abs(finest) / magnitude
    _, digit_spec = column_digit_format(resolved, finest_scaled)
    # column_digit_format calls _digit_spec(parsed, max(0, ...)), so precision is
    # always a non-negative int — None is structurally impossible here.
    parsed_digits = _d3_parse(digit_spec)
    decimals = parsed_digits.precision or 0  # type-state: silent_fallback — always set
    # Second guard from _table.py: even within tier_distance <= 1, a low
    # authored sig-fig count can leave a sub-tier value formatting as "0",
    # indistinguishable from a genuine zero row. Refuse when any non-zero voter
    # carries no nonzero digit in the shared digit_spec.
    if any(
        not any(
            c.isdigit() and c != "0"
            for c in format_value(v / magnitude, digit_spec, None)
        )
        for v in voters
    ):
        return StripNumerals(digit_spec=resolved, anchor=anchor, hang=hang)
    # shared_scale_for_column picks the mode from a *truncated* digit count,
    # which is right for a ruler writing values out in full. A strip rounds to
    # the derived precision first, so re-check against the number the cell
    # actually prints: 999,600 at `.3s` truncates to 3 digits but prints
    # "1,000", the four-digit case the mode rule exists to catch.
    printed_extreme = round(max(abs(v) for v in voters) / magnitude, decimals)
    # numeral_scale applies this same 4-digit rule to the truncated value; the
    # strip re-checks on the rounded value a cell actually prints, because a
    # value that truncates to 3 digits can round to 4 (e.g. 999,600 → "1,000").
    repeat = scale.mode is SuffixMode.REPEAT or len(str(int(printed_extreme))) >= 4
    return StripNumerals(
        digit_spec=digit_spec,
        anchor=anchor,
        prefix=parsed.symbol,
        suffix=suffix_at_register(scale.exponent, "narrative"),
        divisor=magnitude,
        suffix_is_magnitude=True,
        repeat_suffix=repeat,
        hang=hang,
    )


def strip_numerals_for_values(
    values: list[float],
    resolved: str,
    anchor: StripAnchor,
    hang: Literal["left", "right"] = "left",
) -> StripNumerals:
    """How a strip row spells its numbers.

    Every row gets an answer — a row with no unit to declare is spelled by the
    author's own spec with no affixes, which the emitter paints identically in
    every cell. That is the same output the row produced before this feature
    existed, so "declares nothing" is a kind of spelling rather than an absence.

    The author needs no new field to opt in: a format carrying a currency
    symbol, a percent sign, or an SI type has already said what the row's unit
    is. Reading it out of the spec they wrote is what keeps this off the
    authored surface entirely.

    Every non-SI type is spelled by the author's spec unchanged, whatever it is
    — ``p``, ``g``, a bare ``$,`` — because that path never rewrites the spec
    and so cannot misread one. Only ``s`` is rebuilt, and only there does the
    type need to be understood.

    For a left-oriented axis (``hang="right"``), a currency prefix cannot anchor
    without leaving the unit absent from non-anchor cells or using non-standard
    trailing-prefix typography. Such formats route to ``StripAnchor.nowhere()``
    so every cell formats with its own spec and the symbol always appears.

    Called only after the provenance gate in ``_entry_numerals`` confirms
    ``resolved`` is a predefined number name, so a time format or an unresolved
    alias never reaches here. Parse safety itself comes from
    ``compile/validate/formats.py``'s ``ERR_FORMAT_NATIVE_IN_VEGA_SLOT`` check,
    which rejects a ``PREDEFINED_NATIVE`` member (bypasses d3 entirely) on a
    Vega-painted slot like ``data_table`` at compile time -- not from the gate
    itself, which only narrows by name.
    """
    parsed = _d3_parse(resolved)
    if parsed.type == "s":
        return _magnitude_numerals(values, resolved, parsed, anchor, hang)
    if hang == "right" and parsed.symbol:
        # A prefix on a left-axis strip cannot anchor without losing the unit
        # on non-anchor cells. Every cell formats through its own spec instead.
        return StripNumerals(digit_spec=resolved, anchor=StripAnchor.nowhere())
    suffix = "%" if parsed.type == "%" else ""
    return StripNumerals(
        digit_spec=resolved,
        anchor=anchor,
        prefix=parsed.symbol,
        suffix=suffix,
        hang=hang,
    )


def _vl_format_calc(
    source: str,
    format_spec: FormatState,
    as_name: str,
    numerals: StripNumerals,
) -> dict[str, Any]:
    """Build a Vega-Lite calculate transform that formats or dashes invalid values."""
    value_expr = f"datum.{source}"
    valid_expr = (
        f"isValid({value_expr}) && (!isNumber({value_expr}) || isFinite({value_expr}))"
    )
    if format_spec is None:
        return {"calculate": f"{valid_expr} ? {value_expr} : '-'", "as": as_name}
    # The alias is already resolved: numerals.digit_spec is what
    # strip_numerals_for_values was handed, so nothing is re-resolved here.
    text_expr = _strip_numerals_text_expr(value_expr, numerals)
    return {
        "calculate": f"{valid_expr} ? {text_expr} : '-'",
        "as": as_name,
    }


def _default_data_table_label(
    entry: ChartDataTableSource | ChartDataTableAggregate,
) -> str:
    return entry.label or inferred_display_name(entry.source, case="title")


def _wrap_base_as_layer(spec: dict[str, Any]) -> dict[str, Any]:
    """Lift a single-mark spec into {layer: [base, ...]} form if needed."""
    if "layer" in spec:
        return dict(spec)
    base_layer: dict[str, Any] = {}
    for key in ("mark", "encoding", "transform"):
        if key in spec:
            base_layer[key] = spec[key]
    new_spec = {k: v for k, v in spec.items() if k not in ("mark", "encoding")}
    # `transform` stays on the base layer; the attached layers carry their own.
    if "transform" in new_spec:
        del new_spec["transform"]
    # Promote tooltip to spec-level so strip layers inherit it (PR #1877).
    # Strip text marks have only x + a calc text field; without an inherited
    # tooltip, hover shows the raw channel field (e.g. ``revenue: 100.5``)
    # instead of titled-and-formatted output.
    #
    # Two paths:
    # - If the base encoding carries an explicit tooltip array (legacy callers,
    #   unit tests that hand-feed one): promote it as-is.
    # - Otherwise: synthesize from the base's x/y channels — the bar layer's
    #   channels carry title + format after this PR, so the synthesized array
    #   is the same content the legacy tooltip array used to carry.
    #
    # Dict comprehension (not .pop) — base_layer["encoding"] is a shared
    # reference to spec["encoding"] and mutation would corrupt the input.
    base_encoding = base_layer.get("encoding")
    if isinstance(base_encoding, dict):
        existing_tooltip = base_encoding.get("tooltip")
        if existing_tooltip is not None:
            base_layer["encoding"] = {
                k: v for k, v in base_encoding.items() if k != "tooltip"
            }
            new_spec["encoding"] = {"tooltip": existing_tooltip}
        else:
            spec_tooltip = [
                {k: enc[k] for k in ("field", "type", "title", "format") if k in enc}
                for ch in ("x", "y")
                if (enc := base_encoding.get(ch, {})) and enc.get("field")
            ]
            if spec_tooltip:
                new_spec["encoding"] = {"tooltip": spec_tooltip}
    new_spec["layer"] = [base_layer]
    return new_spec


def _shared_x_encoding(
    parent_x_enc: dict[str, Any], mark_is_bar: bool
) -> dict[str, Any]:
    """Shared x-encoding for all attached layers.

    Copies field, type, and (when present) timeUnit from the parent chart's
    x-encoding so strip layers share the same scale type. Mismatched types
    (e.g. parent temporal vs strip ordinal) cause a vl-convert null-deref.

    bandPosition rules — the cell must ride the same x position as the base mark:
      - ordinal / nominal → 0.5 (band-centre anchor; marks render at the band
        centre either way — bars add dx to centre the number column, line/area
        lean toward the row label via align).
      - temporal + timeUnit → 0.5 only for a BAR: a bar spans the whole time
        band, so its number column centres on the band. A line/area point sits
        on its exact date (the grid tick), so its cell must ride that same
        per-point position — NO bandPosition. Anchoring a line/area cell to the
        band would both offset it half a band off the point AND pull the band's
        ``_end`` into the x-scale domain union, widening the axis past the data.
      - quantitative / plain temporal → omitted (continuous scale, no bands).

    No axis: null — setting axis to None crashes vl-convert with a TypeError
    in parseAxesAndHeaders. Omitting the axis key entirely is correct; Vega-Lite
    infers axis rendering from context and the text mark does not need axis ticks.
    """
    enc: dict[str, Any] = {"field": parent_x_enc["field"], "type": parent_x_enc["type"]}
    if "timeUnit" in parent_x_enc:
        enc["timeUnit"] = parent_x_enc["timeUnit"]
        if mark_is_bar:
            enc["bandPosition"] = 0.5
    elif parent_x_enc["type"] in ("ordinal", "nominal"):
        enc["bandPosition"] = 0.5
    return enc


def _text_mark_props(
    style: DataTableStyle,
    align: Literal["left", "right"],
    dx: float | None = None,
) -> dict[str, Any]:
    """Common mark properties for row-text layers.

    `align` mirrors the label side so values lean toward their row labels:
    axis_y orient left (labels on the left) → "left"; orient right → "right".

    `dx`, when set (bar charts only), centres the number column on the band
    midpoint.  Sign convention: align=right → +dx (right edge at band_centre +
    max_w/2); align=left → -dx (left edge at band_centre - max_w/2).

    For line/area charts dx is None: the aligned edge sits straight on the
    mark's x position (bandPosition pins the anchor to the band centre).
    """
    mark: dict[str, Any] = {
        "type": "text",
        "align": align,
        "baseline": "middle",
    }
    if dx is not None:
        mark["dx"] = -dx if align == "left" else dx
    font = style.font
    if font.family is not None:
        mark["font"] = font.family
    if font.size is not None:
        mark["fontSize"] = font.size
    if font.weight is not None:
        mark["fontWeight"] = font.weight
    if font.color is not None:
        mark["fill"] = font.color
    return mark


def _row_text_layer(
    index: int,
    entry: Any,
    parent_x_enc: dict[str, Any],
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
    numerals: StripNumerals,
    value_format: FormatState = None,
    sampling_step: int = 1,
    dx: float | None = None,
    value_align: Literal["left", "right"] = "right",
    label_period_filter_expr: str | None = None,
) -> dict[str, Any]:
    """Emit a text layer for one data_table row (source or aggregate).

    When sampling_step > 1, a Vega-Lite window+filter chain is inserted so
    only every Nth x position renders a cell. Transform ordering matters:
    - For aggregate entries: [aggregate, (period_filter), window, filter, format_calc]
      The aggregate collapses multi-row-per-x data first; period filter then thins
      to label-period openers; sampling then thins further if needed.
    - For source entries (1 row per x, enforced by the ambiguous-aggregation guard
      in validate_data_table_against_data): [(period_filter), window, filter, format_calc]

    When label_period_filter_expr is set, a filter transform is inserted to
    keep only x-values that open a new label period (e.g. quarterly openers on
    a monthly-band axis). This prevents the data_table strip from rendering one
    cell per band when the axis labels are at a coarser cadence.
    """
    is_agg = isinstance(entry, ChartDataTableAggregate)
    x_field = parent_x_enc["field"]
    # Internal field name for the formatted cell value.
    cell_name = f"__data_table_{index}"

    transforms: list[dict[str, Any]] = []
    if is_agg:
        vl_op = _AGG_OP_TO_VL[entry.aggregate]
        agg_name = f"{cell_name}_val"
        transforms.append(
            {
                "aggregate": [{"op": vl_op, "field": entry.source, "as": agg_name}],
                "groupby": [x_field],
            }
        )
        # Period filter after aggregate: one row per x, filter to label-period openers.
        if label_period_filter_expr is not None:
            transforms.append({"filter": label_period_filter_expr})
        # Sampling after period filter: thin further if still over the cap.
        if sampling_step > 1:
            transforms.extend(_sampling_transforms(x_field, sampling_step))
        if numerals.needs_drawn_index_window:
            transforms.extend(
                _drawn_index_transform(
                    x_field,
                    agg_name,
                    numerals.suffix_is_magnitude,
                    sort_ascending=not numerals.anchor.data_order,
                )
            )
        transforms.append(_vl_format_calc(agg_name, value_format, cell_name, numerals))
    else:
        # Source entry: the ambiguous-aggregation guard guarantees 1 row per x.
        # Period filter before sampling: thin to label-period openers first.
        if label_period_filter_expr is not None:
            transforms.append({"filter": label_period_filter_expr})
        if sampling_step > 1:
            transforms.extend(_sampling_transforms(x_field, sampling_step))
        if numerals.needs_drawn_index_window:
            transforms.extend(
                _drawn_index_transform(
                    x_field,
                    entry.source,
                    numerals.suffix_is_magnitude,
                    sort_ascending=not numerals.anchor.data_order,
                )
            )
        transforms.append(
            _vl_format_calc(entry.source, value_format, cell_name, numerals)
        )

    y_pixel = _row_y_pixel(index, style, axis_offset_value, spec_height)
    layer: dict[str, Any] = {
        "mark": _text_mark_props(style, value_align, dx=dx),
        "encoding": {
            "x": _shared_x_encoding(parent_x_enc, mark_is_bar=dx is not None),
            "y": {"value": y_pixel},
            "text": {"field": cell_name},
            # Opt out of inherited color encoding. Without this, VL sees own data
            # that lacks the series field, adds null to the categorical domain, and
            # null sorts first — consuming palette[0] and shifting every series mark
            # one slot up (the dark-companion off-by-one).
            "color": None,
        },
        "transform": transforms,
    }
    return layer


def _per_series_row_layers(
    row_start_index: int,
    entry: ChartDataTablePerSeries,
    parent_x_enc: dict[str, Any],
    color_field: str | None,
    series_order: list[str],
    dark_fills: list[str] | None,
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
    spec_width: float | None,
    axis_label_padding: float,
    numerals: StripNumerals,
    value_format: FormatState = None,
    sampling_step: int = 1,
    dx: float | None = None,
    label_period_filter_expr: str | None = None,
    axis_y_orient: Literal["left", "right"] = "left",
    label_limit: float | None = None,
    suppress_series_labels: bool = False,
) -> list[dict[str, Any]]:
    """Emit cell + label layers for one ``per_series:`` data_table entry.

    When ``entry.by_measure`` is True, a single row reads the named field
    directly (no per-series expansion). Otherwise, emits one cell + one
    label layer per series in series_order, used to resolve dark companion
    label ink.

    Args:
        row_start_index: pixel-row index of the first series row.
        entry: ChartDataTablePerSeries entry.
        parent_x_enc: parent chart's x-encoding dict.
        color_field: column name backing the color channel. Required for
            normal mode; may be None when ``entry.by_measure`` is True.
        series_order: Ordered series names.
        dark_fills: dark-companion label-ink colour for each series in
            series_order (already resolved by the caller). When None, label
            fill is omitted.
        style: Resolved DataTableStyle.
        axis_offset_value: the resolved chart's own baked data_table_axis_offset.
        spec_height: pixel height.
        spec_width: pixel width. Required (non-None) when
            ``axis_y_orient == "right"``; ignored for left-cap.
        axis_label_padding: resolved axis_y label padding, pixel offset for
            the label stub column — see ``_label_stub_left_layer``.
        sampling_step: thinning factor for dense x axes (>1 thins cells).
        axis_y_orient: Resolved y-axis orient — "right" or "left".
            Determines which label emitter fires and the mark's x-anchor
            and text-anchor.
        label_limit: mark.limit (pixels) applied to every label layer.
            When None, no limit is set. Pass _LABEL_STUB_LIMIT_PX to
            prevent labels from reaching into the legend zone.

    Returns:
        Flat list of Vega-Lite layer dicts (cell text + label text per series).

    Raises:
        RenderError (ERR-INPUT-INVALID) when ``axis_y_orient == "right"``
        but ``spec_width`` is None.
    """
    if axis_y_orient == "right" and spec_width is None:
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message=(
                "attach_data_table requires the spec to carry an explicit "
                "width when right-cap labels are present on per_series entries — "
                "pixel-literal label positioning has no anchor otherwise."
            ),
        )

    # by_measure mode: one row reading the named field directly.
    if entry.by_measure:
        row_idx = row_start_index
        bm_cell_name = f"__data_table_{row_idx}"
        bm_transforms: list[dict[str, Any]] = []
        if label_period_filter_expr is not None:
            bm_transforms.append({"filter": label_period_filter_expr})
        if sampling_step > 1:
            bm_transforms.extend(
                _sampling_transforms(parent_x_enc["field"], sampling_step)
            )
        if numerals.needs_drawn_index_window:
            bm_transforms.extend(
                _drawn_index_transform(
                    parent_x_enc["field"],
                    entry.per_series,
                    numerals.suffix_is_magnitude,
                    sort_ascending=not numerals.anchor.data_order,
                )
            )
        bm_transforms.append(
            _vl_format_calc(entry.per_series, value_format, bm_cell_name, numerals)
        )
        bm_y_pixel = _row_y_pixel(row_idx, style, axis_offset_value, spec_height)
        # bm_transforms always carries at least the format_calc appended above,
        # so it's never empty — set it unconditionally, matching _row_text_layer.
        bm_cell_layer: dict[str, Any] = {
            "mark": _text_mark_props(style, axis_y_orient, dx=dx),
            "encoding": {
                "x": _shared_x_encoding(parent_x_enc, mark_is_bar=dx is not None),
                "y": {"value": bm_y_pixel},
                "text": {"field": bm_cell_name},
            },
            "transform": bm_transforms,
        }
        if suppress_series_labels:
            return [bm_cell_layer]
        # Label stub: use entry.label when set, else fall back to the field name.
        bm_label_text = entry.label if entry.label is not None else entry.per_series
        if axis_y_orient == "right":
            assert spec_width is not None  # pre-check above guarantees this
            bm_label_layer = _label_stub_right_layer(
                row_idx,
                bm_label_text,
                style=style,
                axis_offset_value=axis_offset_value,
                spec_height=spec_height,
                spec_width=spec_width,
                axis_label_padding=axis_label_padding,
                limit=label_limit,
            )
        else:
            bm_label_layer = _label_stub_left_layer(
                row_idx,
                bm_label_text,
                style=style,
                axis_offset_value=axis_offset_value,
                spec_height=spec_height,
                axis_label_padding=axis_label_padding,
                limit=label_limit,
            )
        return [bm_cell_layer, bm_label_layer]

    # Normal mode: one cell + label per series in series_order.
    # color_field is guaranteed non-None here: attach_data_table raises RenderError
    # before calling this function for normal-mode entries when color_field is None.
    resolved_dark_fills: list[str | None] = (
        list(dark_fills) if dark_fills is not None else [None] * len(series_order)
    )

    x_field = parent_x_enc["field"]
    layers: list[dict[str, Any]] = []

    for series_idx, series_value in enumerate(series_order):
        row_idx = row_start_index + series_idx
        cell_name = f"__data_table_{row_idx}"
        agg_name = f"{cell_name}_val"

        transforms: list[dict[str, Any]] = [
            {
                "aggregate": [{"op": "sum", "field": entry.per_series, "as": agg_name}],
                "groupby": [x_field, color_field],
            },
        ]
        # Filter to this series first, THEN apply period filter, THEN sample.
        # Sampling after the aggregate but before the per-series filter would
        # window over the (x, series) cross-product, where ties on x_field have
        # unspecified row-number order — so series A might keep x1/x3/x5
        # while series B keeps x2/x4/x6, with cells at inconsistent
        # x positions across the strip's rows. Sampling AFTER the
        # per-series filter gives each series an independent 1-row-per-x
        # input that thins consistently. Period filter goes between the
        # per-series filter and sampling: it operates on per-series 1-row-per-x
        # data and further thins to label-period openers.
        safe_val = str(series_value).replace("\\", "\\\\").replace("'", "\\'")
        transforms.append({"filter": f"datum['{color_field}'] === '{safe_val}'"})
        if label_period_filter_expr is not None:
            transforms.append({"filter": label_period_filter_expr})
        if sampling_step > 1:
            transforms.extend(_sampling_transforms(x_field, sampling_step))
        # After the per-series filter, so each series numbers its own drawn
        # cells and anchors its own leftmost one -- not whichever row sorted
        # first across the (x, series) cross-product.
        if numerals.needs_drawn_index_window:
            transforms.extend(
                _drawn_index_transform(
                    x_field,
                    agg_name,
                    numerals.suffix_is_magnitude,
                    sort_ascending=not numerals.anchor.data_order,
                )
            )
        transforms.append(_vl_format_calc(agg_name, value_format, cell_name, numerals))

        y_pixel = _row_y_pixel(row_idx, style, axis_offset_value, spec_height)
        cell_layer: dict[str, Any] = {
            "mark": _text_mark_props(style, axis_y_orient, dx=dx),
            "encoding": {
                "x": _shared_x_encoding(parent_x_enc, mark_is_bar=dx is not None),
                "y": {"value": y_pixel},
                "text": {"field": cell_name},
            },
            "transform": transforms,
        }
        layers.append(cell_layer)

        if suppress_series_labels:
            continue

        # Label layer — series name with companion-resolved fill ink.
        # Delegates to _label_stub_right_layer / _label_stub_left_layer so
        # the orient-derived geometry (x, align, limit) lives in one place.
        dark_fill = (
            resolved_dark_fills[series_idx]
            if series_idx < len(resolved_dark_fills)
            else None
        )
        if axis_y_orient == "right":
            assert spec_width is not None  # pre-loop check guarantees this
            label_layer = _label_stub_right_layer(
                row_idx,
                str(series_value),
                style=style,
                axis_offset_value=axis_offset_value,
                spec_height=spec_height,
                spec_width=spec_width,
                axis_label_padding=axis_label_padding,
                limit=label_limit,
            )
        else:
            label_layer = _label_stub_left_layer(
                row_idx,
                str(series_value),
                style=style,
                axis_offset_value=axis_offset_value,
                spec_height=spec_height,
                axis_label_padding=axis_label_padding,
                limit=label_limit,
            )
        if dark_fill is not None:
            label_layer["mark"]["fill"] = dark_fill
        layers.append(label_layer)

    return layers


def _divider_rule_layer(
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
) -> dict[str, Any]:
    """Strip-top divider rule (ADR-006: rule-only, no header text)."""
    mark: dict[str, Any] = {
        "type": "rule",
        "strokeWidth": style.divider.width,
    }
    if style.divider.color is not None:
        mark["stroke"] = style.divider.color
    return {
        "data": {"values": [{}]},
        "mark": mark,
        "encoding": {
            "y": {"value": _divider_y_pixel(style, axis_offset_value, spec_height)}
        },
    }


def _row_rule_layer(
    index: int,
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
) -> dict[str, Any]:
    """Inter-row rule between row `index` and row `index + 1`."""
    mark: dict[str, Any] = {
        "type": "rule",
        "strokeWidth": style.row.rule.width,
    }
    if style.row.rule.color is not None:
        mark["stroke"] = style.row.rule.color
    return {
        "data": {"values": [{}]},
        "mark": mark,
        "encoding": {
            "y": {
                "value": _inter_row_rule_y_pixel(
                    index, style, axis_offset_value, spec_height
                )
            }
        },
    }


def _label_mark_props(style: DataTableStyle, align: str) -> dict[str, Any]:
    """Common mark properties shared by left-stub and right-cap label layers.

    `align` is derived from the chart's resolved axis_y.orient at the call site:
    right-oriented → "left" (text-anchor start); left-oriented → "right" (text-anchor end).
    """
    mark: dict[str, Any] = {
        "type": "text",
        "align": align,
        "baseline": "middle",
    }
    font = style.label.font
    if font.family is not None:
        mark["font"] = font.family
    if font.size is not None:
        mark["fontSize"] = font.size
    if font.weight is not None:
        mark["fontWeight"] = font.weight
    if font.color is not None:
        mark["fill"] = font.color
    return mark


def _label_stub_left_layer(
    index: int,
    label_text: str,
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
    axis_label_padding: float,
    limit: float | None = None,
) -> dict[str, Any]:
    """Left-gutter label layer anchored to the left y-axis tick column.

    x = -axis_y.labels.padding (same column as left-oriented y-axis tick labels,
    which extend leftward from x=0 with text-anchor end / align right).
    mark.limit caps the text width so VL's autosize does not shrink the plot.

    axis_label_padding is the caller's already-resolved ``resolved_chart.style.axis_y.labels.padding``
    (the fully chart-local-cascaded axis, not the board-level ``charts_style.axis_y``,
    which is authored-only/SkipInheritSlots and stays sparse until merged with axis).
    """
    x_pixel = -axis_label_padding
    mark = _label_mark_props(style, align="right")
    if limit is not None:
        mark["limit"] = limit
    return {
        "data": {"values": [{"__label": label_text}]},
        "mark": mark,
        "encoding": {
            "x": {"value": x_pixel},
            "y": {"value": _row_y_pixel(index, style, axis_offset_value, spec_height)},
            "text": {"field": "__label"},
            # Opt out of inherited color encoding. Without this, VL sees own data
            # that lacks the series field, adds null to the categorical domain, and
            # null sorts first — consuming palette[0] and shifting every series mark
            # one slot up (the dark-companion off-by-one).
            "color": None,
        },
    }


def _label_stub_right_layer(
    index: int,
    label_text: str,
    style: DataTableStyle,
    axis_offset_value: float | None,
    spec_height: float,
    spec_width: float,
    axis_label_padding: float,
    limit: float | None = None,
) -> dict[str, Any]:
    """Right-cap label layer anchored to the right y-axis tick column.

    x = spec_width + axis_y.labels.padding (same column as right-oriented y-axis
    tick labels, which extend rightward from that anchor with text-anchor start /
    align left). mark.limit caps the text width so VL's autosize does not shrink
    the plot.

    axis_label_padding is the caller's already-resolved ``resolved_chart.style.axis_y.labels.padding``
    — see ``_label_stub_left_layer`` for why this isn't recomputed from ``charts_style.axis_y``.
    """
    x_pixel = spec_width + axis_label_padding
    mark = _label_mark_props(style, align="left")
    if limit is not None:
        mark["limit"] = limit
    return {
        "data": {"values": [{"__label": label_text}]},
        "mark": mark,
        "encoding": {
            "x": {"value": x_pixel},
            "y": {"value": _row_y_pixel(index, style, axis_offset_value, spec_height)},
            "text": {"field": "__label"},
            # Opt out of inherited color encoding — same fix as _label_stub_left_layer.
            "color": None,
        },
    }


def _sampling_transforms(x_field: str, step: int) -> list[dict[str, Any]]:
    """Vega-Lite window + filter transforms for strip-cell sampling.

    Assigns a 1-indexed row_number sorted ascending by x_field, then filters
    to rows where (row_number - 1) % step == 0, keeping the first row and
    every step-th row after it.
    """
    return [
        {
            "window": [{"op": "row_number", "as": "__data_table_row_index"}],
            "sort": [{"field": x_field, "order": "ascending"}],
        },
        {"filter": f"(datum.__data_table_row_index - 1) % {step} === 0"},
    ]


def attach_data_table(
    spec: dict[str, Any],
    *,
    data_table: ChartDataTable | None,
    style: DataTableStyle,
    charts_style: ResolvedChartDefaults | None = None,
    axis_offset_value: float | None = None,
    axis_label_padding: float,
    sampling_step: int = 1,
    entry_dx: list[float] | None = None,
    entry_numerals: Sequence[StripNumerals],
    series_order: list[str] | None = None,
    dark_fills: list[str] | None = None,
    label_period_filter_expr: str | None = None,
    axis_y_orient: Literal["left", "right"],
    suppress_series_labels: bool = False,
) -> dict[str, Any]:
    """Append attached-data-table layers to a Vega-Lite chart spec.

    Y-positioning is pixel-literal (`{"y": {"value": <px>}}`), anchored to
    the spec's explicit height. Vega-Lite scales `{"y": {"expr": ...}}`
    through the parent's y-scale rather than treating it as a pixel
    literal, so the spec must carry an explicit height (Dataface's
    standard renderer always sets one).

    Args:
        spec: Base Vega-Lite chart spec (mark + encoding, or already a layer spec).
        data_table: Parsed ChartDataTable block, or None for no-op.
        style: Resolved DataTableStyle (already cascade-resolved).
        charts_style: ResolvedChartDefaults for x-axis label offset computation.
            Required when data_table is non-None.
        axis_label_padding: resolved_chart.style.axis_y.labels.padding — the
            chart-local-cascaded axis label padding used to anchor the label
            stub column. Callers read this off the resolved chart directly;
            it is not recomputed here.
        sampling_step: When > 1, prepend a Vega-Lite window+filter transform
            chain to each text-mark layer so only every Nth row renders a
            cell. The chart's bar/line/area base layer is not affected.
            Computed by validate_data_table_against_data for temporal/
            quantitative x axes that exceed ``chart_rendering.data_table.chart_data_table_max_x_ticks``.
        entry_dx: Per-entry dx half-widths (pixels) for band-centering on bar
            charts. When set, entry_dx[i] is applied as the VL mark ``dx``
            offset, centring the number column on the band midpoint. None (the
            default) means no dx — aligned edge sits straight on the mark.
        series_order: For per_series entries — ordered list of series names
            in the chart's stack/scale order. Required when any entry is a
            ChartDataTablePerSeries. Callers resolve this from the parent
            chart's color encoding domain.
        dark_fills: For per_series entries — the already-resolved dark
            companion label-ink colour for each series in series_order.
            When None, label fill is omitted.
        label_period_filter_expr: Vega filter expression that restricts strip
            cells to label-period openers. When set, each text-mark layer
            receives a ``{"filter": label_period_filter_expr}`` transform so
            only x-values that open a new label period (e.g. quarterly openers
            on a monthly-band axis) emit a cell. Computed by the render layer
            from the chart's encoding_time_unit / label_time_unit pair.
        axis_y_orient: Resolved y-axis orient — ``"right"`` or ``"left"``
            (line charts with right-edge endpoint labels). Determines which label
            emitter fires: right-oriented → label at ``spec_width +
            axis_y.labels.padding`` with ``align: left``; left-oriented → label at
            ``-axis_y.labels.padding`` with ``align: right``. Required — callers must
            resolve this from the chart's axis_y.orient before calling.

    Returns:
        New spec dict with attached layers appended and ``autosize`` set
        to ``pad`` so the outer SVG expands to include the strip rather
        than shrinking the plot. Padding is NOT touched — callers must
        reserve the strip's height themselves via
        ``data_table_strip_height``. Input spec not mutated.
    """
    if data_table is None or not data_table.entries:
        return spec

    if charts_style is None:
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message=(
                "attach_data_table requires charts_style when data_table is "
                "non-None — the height-synthesis fallback needs it."
            ),
        )
    if style.position == "bottom" and axis_offset_value is None:
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message=(
                "attach_data_table requires axis_offset_value when data_table "
                "is non-None and style.position is 'bottom' — pass the "
                "resolved chart's own data_table_axis_offset."
            ),
        )

    raw_width = spec.get("width")
    spec_width = (
        float(raw_width)
        if isinstance(raw_width, (int, float)) and raw_width > 0
        else None
    )

    spec_height = spec.get("height")
    if not isinstance(spec_height, (int, float)) or spec_height <= 0:
        # Optional callers (warnings detector, diagnostic scripts) reach
        # generate_vega_lite_spec without a board-level layout sizer, so the
        # spec arrives without an explicit height. Synthesize one from
        # charts_style.aspect_ratio clamped to [min_height, max_height] —
        # the same shape the layout sizer's static estimate uses. Width is
        # still required: it's the anchor we project the aspect ratio onto.
        if spec_width is None:
            raise RenderError.from_code(
                ERR_INPUT_INVALID,
                message=(
                    "attach_data_table requires the spec to carry an explicit "
                    "width when height is unset — no anchor exists to synthesize "
                    "a height default from."
                ),
            )
        synthesized_height = spec_width / charts_style.aspect_ratio
        synthesized_height = max(
            charts_style.min_height,
            min(charts_style.max_height, synthesized_height),
        )
        spec = {**spec, "height": synthesized_height}
        spec_height = synthesized_height

    # Compute the total number of visual rows.
    # by_measure entries each expand to 1 row; normal per_series entries expand
    # to N rows (one per series); source/aggregate entries are 1 row each.
    n_visual_rows = 0
    for entry in data_table.entries:
        if isinstance(entry, ChartDataTablePerSeries):
            if entry.by_measure:
                n_visual_rows += 1
            else:
                n_visual_rows += len(series_order) if series_order else 1
        else:
            n_visual_rows += 1

    # Extract parent x-encoding before wrapping (wrap moves encoding into the base layer).
    #
    # Three shapes are accepted:
    #
    # 1. Standard top-level encoding — `spec["encoding"]["x"]` is set. The bulk
    #    of charts arrive here.
    # 2. Layered VL spec with x per-layer only (no top-level encoding.x) — an
    #    overlay chart's top-level `spec["encoding"]` may be empty/absent while
    #    every `spec["layer"][i]["encoding"]` carries the same x.
    #    We anchor against `layer[0]`'s x.
    # 3. Any other shape — raise ChartDataError. The strip needs an unambiguous
    #    anchor; silently picking layer-0's x when other layers disagree (or when
    #    resolve.scale.x is independent) would misalign the strip against the
    #    other layers' x-buckets, which is the "wrong result that looks right"
    #    failure mode the repo non-negotiables forbid.
    _raw_top_encoding = spec.get("encoding")
    top_encoding: dict[str, Any] = (
        _raw_top_encoding if isinstance(_raw_top_encoding, dict) else {}
    )
    if "x" in top_encoding:
        parent_x_enc = top_encoding["x"]
    else:
        from dbt_charts.core.diagnostics.chart_data import ChartDataError

        layers_inline = spec.get("layer")
        if not isinstance(layers_inline, list) or not layers_inline:
            raise ChartDataError(
                "data_table attachment requires an x-encoding on the chart spec "
                "or its layers; none found."
            )
        if spec.get("resolve", {}).get("scale", {}).get("x") == "independent":
            raise ChartDataError(
                "data_table strip cannot anchor to a layer spec with "
                "resolve.scale.x == 'independent'; the layers have per-dataset "
                "x scales and the strip cannot anchor coherently."
            )
        layer_x_encs = [
            layer.get("encoding", {}).get("x")
            for layer in layers_inline
            if isinstance(layer, dict)
        ]
        non_null_x_encs = [enc for enc in layer_x_encs if isinstance(enc, dict)]
        if not non_null_x_encs:
            raise ChartDataError(
                "data_table attachment requires an x-encoding on the chart spec "
                "or its layers; none found."
            )
        first_x_field = non_null_x_encs[0].get("field")
        for enc in non_null_x_encs[1:]:
            if enc.get("field") != first_x_field:
                raise ChartDataError(
                    "data_table strip cannot anchor to a layer spec whose "
                    "per-layer x-encodings disagree on field; lift x to chart "
                    "level or remove data_table."
                )
        parent_x_enc = non_null_x_encs[0]
    # Resolve the color field from the parent spec's top-level encoding for
    # per_series entries. When top-level encoding has no color (color lives
    # per-layer), return None and let the per_series caller require an explicit
    # series_order/dark_fills.
    parent_color_enc = top_encoding.get("color")
    color_field: str | None = None
    if isinstance(parent_color_enc, dict):
        color_field = parent_color_enc.get("field")

    out = _wrap_base_as_layer(spec)
    layers: list[dict[str, Any]] = list(out["layer"])

    if style.divider.width > 0:
        layers.append(_divider_rule_layer(style, axis_offset_value, spec_height))

    _label_stub_limit: float = _LABEL_STUB_LIMIT_PX

    # Track the current visual row index as we iterate entries. Source and
    # aggregate entries each consume 1 row; per_series entries consume N rows.
    visual_row_idx = 0
    for entry_idx, entry in enumerate(data_table.entries):
        row_dx = entry_dx[entry_idx] if entry_dx is not None else None
        row_numerals = entry_numerals[entry_idx]
        row_format = entry.format
        if isinstance(entry, ChartDataTablePerSeries):
            if entry.by_measure:
                # by_measure: one row per entry, no series expansion needed.
                bm_layers = _per_series_row_layers(
                    visual_row_idx,
                    entry,
                    parent_x_enc=parent_x_enc,
                    color_field=None,
                    series_order=[],
                    dark_fills=None,
                    style=style,
                    axis_offset_value=axis_offset_value,
                    spec_height=spec_height,
                    spec_width=spec_width,
                    axis_label_padding=axis_label_padding,
                    value_format=row_format,
                    sampling_step=sampling_step,
                    dx=row_dx,
                    label_period_filter_expr=label_period_filter_expr,
                    axis_y_orient=axis_y_orient,
                    label_limit=_label_stub_limit,
                    suppress_series_labels=suppress_series_labels,
                    numerals=row_numerals,
                )
                layers.extend(bm_layers)
                if style.row.rule.width > 0 and visual_row_idx < n_visual_rows - 1:
                    layers.append(
                        _row_rule_layer(
                            visual_row_idx, style, axis_offset_value, spec_height
                        )
                    )
                visual_row_idx += 1
            else:
                if not series_order:
                    raise RenderError.from_code(
                        ERR_INPUT_INVALID,
                        message=(
                            "attach_data_table requires series_order when per_series "
                            "entries are present — callers must supply the ordered "
                            "series list resolved from the parent chart's color "
                            "encoding domain."
                        ),
                    )
                if color_field is None:
                    raise RenderError.from_code(
                        ERR_INPUT_INVALID,
                        message=(
                            "attach_data_table requires the spec to carry a color "
                            "encoding when per_series entries are present."
                        ),
                    )
                per_series_layers = _per_series_row_layers(
                    visual_row_idx,
                    entry,
                    parent_x_enc=parent_x_enc,
                    color_field=color_field,
                    series_order=series_order,
                    dark_fills=dark_fills,
                    style=style,
                    axis_offset_value=axis_offset_value,
                    spec_height=spec_height,
                    spec_width=spec_width,
                    axis_label_padding=axis_label_padding,
                    value_format=row_format,
                    sampling_step=sampling_step,
                    dx=row_dx,
                    label_period_filter_expr=label_period_filter_expr,
                    axis_y_orient=axis_y_orient,
                    label_limit=_label_stub_limit,
                    suppress_series_labels=suppress_series_labels,
                    numerals=row_numerals,
                )
                layers.extend(per_series_layers)
                n_series = len(series_order)
                # Inter-row rules: emit ONE per pair of adjacent visual rows
                # within the per_series block (n_series - 1 rules) plus one
                # trailing rule between this block and the next entry — same
                # cadence as source/aggregate rows, where every adjacent visual
                # pair gets a rule. Without the within-block rules, the strip
                # height accounting (which includes inter-row spacing for every
                # visual row) reserves gaps where no rules are drawn.
                if style.row.rule.width > 0:
                    last_in_block = visual_row_idx + n_series - 1
                    # Within-block rules: between each pair of adjacent series.
                    for inner_idx in range(visual_row_idx, last_in_block):
                        layers.append(
                            _row_rule_layer(
                                inner_idx, style, axis_offset_value, spec_height
                            )
                        )
                    # Trailing rule: between this block and the next entry.
                    if last_in_block < n_visual_rows - 1:
                        layers.append(
                            _row_rule_layer(
                                last_in_block, style, axis_offset_value, spec_height
                            )
                        )
                visual_row_idx += n_series
        else:
            row_layer = _row_text_layer(
                visual_row_idx,
                entry,
                parent_x_enc=parent_x_enc,
                style=style,
                axis_offset_value=axis_offset_value,
                spec_height=spec_height,
                value_format=row_format,
                sampling_step=sampling_step,
                dx=row_dx,
                value_align=axis_y_orient,
                label_period_filter_expr=label_period_filter_expr,
                numerals=row_numerals,
            )
            layers.append(row_layer)
            label = _default_data_table_label(entry)
            if label:
                if axis_y_orient == "right":
                    if spec_width is None:
                        raise RenderError.from_code(
                            ERR_INPUT_INVALID,
                            message=(
                                "attach_data_table requires the spec to carry an "
                                "explicit width when right-cap labels are present — "
                                "pixel-literal label positioning has no anchor "
                                "otherwise."
                            ),
                        )
                    layers.append(
                        _label_stub_right_layer(
                            visual_row_idx,
                            label,
                            style=style,
                            axis_offset_value=axis_offset_value,
                            spec_height=spec_height,
                            spec_width=spec_width,
                            axis_label_padding=axis_label_padding,
                            limit=_label_stub_limit,
                        )
                    )
                else:
                    layers.append(
                        _label_stub_left_layer(
                            visual_row_idx,
                            label,
                            style=style,
                            axis_offset_value=axis_offset_value,
                            spec_height=spec_height,
                            axis_label_padding=axis_label_padding,
                            limit=_label_stub_limit,
                        )
                    )
            if style.row.rule.width > 0 and visual_row_idx < n_visual_rows - 1:
                layers.append(
                    _row_rule_layer(
                        visual_row_idx, style, axis_offset_value, spec_height
                    )
                )
            visual_row_idx += 1

    out["layer"] = layers
    # Strip rows live outside the plot area (pixel y > spec.height for bottom;
    # pixel y < 0 for top). Override the chart-wide `autosize: fit` default with
    # `pad` so the outer SVG grows to include the strip rather than shrinking the plot. Trade-off: under
    # `pad`, spec.width refers to the inner plot, so the outer SVG is wider
    # than the requested width by axis-y label + padding overhead (constant
    # regardless of requested width — see
    # test_render_pipeline_svg_width_overhead_independent_of_requested_width).
    # layout_sizing.py compensates symmetrically on both axes. The initial
    # render-first sizing pass (_make_data_aware_height_provider) renders once
    # to measure the width overhead, then re-renders with spec.width pre-shrunk.
    # Cols alignment (_align_cols_heights) has a hard target_height, so after
    # its alignment re-render it measures any height overhead and re-renders
    # with spec.height pre-shrunk too. Both axes fit the slot.
    out["autosize"] = {"type": "pad", "contains": "padding"}
    return out


def _aggregate_by_x(
    data: list[dict[str, Any]],
    source: str,
    x_field: str,
    op: str,
) -> list[float]:
    """Group data by x_field, apply aggregate op, return resulting values.

    Mirrors the VL aggregate transform used in _row_text_layer so that width
    measurements reflect the actual rendered strings.  op must be one of:
    sum, avg, min, max, median, count, count_distinct.

    count/count_distinct do not coerce source values to float — they count
    rows / distinct raw values so non-numeric sources are first-class.
    For sum/avg/min/max/median, float() is intentionally not suppressed:
    a non-numeric source with a numeric aggregate is a query authoring error
    and should surface as ValueError, not silently produce wrong dx.

    Both ops share the _AGG_OP_TO_VL enum in data_table_attachment.py;
    update that mapping when adding a new op here.
    """
    # count/count_distinct: key on raw values directly (no float coercion)
    if op in ("count", "count_distinct"):
        raw_groups: dict[Any, list[Any]] = defaultdict(list)
        for row in data:
            x_val = row.get(x_field)
            raw = row.get(source)
            if x_val is None:
                continue
            raw_groups[x_val].append(raw)
        if op == "count":
            return [float(len(vals)) for vals in raw_groups.values() if vals]
        return [
            float(len({v for v in vals if v is not None}))
            for vals in raw_groups.values()
            if vals
        ]

    # numeric ops: float() is intentionally not suppressed — non-numeric source
    # values here mean a query authoring error, not an expected no-op.
    groups: dict[Any, list[float]] = defaultdict(list)
    for row in data:
        x_val = row.get(x_field)
        raw = row.get(source)
        if x_val is None or raw is None:
            continue
        groups[x_val].append(float(raw))

    results: list[float] = []
    for vals in groups.values():
        if not vals:
            continue
        if op == "sum":
            results.append(sum(vals))
        elif op == "avg":
            results.append(sum(vals) / len(vals))
        elif op == "min":
            results.append(min(vals))
        elif op == "max":
            results.append(max(vals))
        elif op == "median":
            results.append(statistics.median(vals))
        else:
            raise ValueError(f"unknown aggregate op {op!r}")
    return results


def _aggregate_by_x_and_color(
    data: list[dict[str, Any]],
    source: str,
    x_field: str,
    color_field: str,
) -> list[float]:
    """Sum ``source`` grouped by (x, color), mirroring the per_series VL transform.

    The per_series text layer in :mod:`data_table_attachment` emits a sum
    aggregate keyed on ``[x_field, color_field]`` and a per-series filter,
    so each rendered cell shows that one series' value at that x. This
    helper produces the matching width-measurement input — sum-per-(x,
    series) — so dx reflects the *actual* rendered cell widths rather
    than the across-series sum.
    """
    groups: dict[tuple[Any, Any], list[float]] = defaultdict(list)
    for row in data:
        x_val = row.get(x_field)
        c_val = row.get(color_field)
        raw = row.get(source)
        if x_val is None or c_val is None or raw is None:
            continue
        groups[(x_val, c_val)].append(float(raw))
    return [sum(vals) for vals in groups.values() if vals]


def _numeric_column(data: ChartRenderData, source: str) -> list[float]:
    """Coerce a column's non-null values to float, skipping non-numeric ones.

    Bare source columns can hold strings (Vega renders them as labels); those
    simply contribute no measurable numeric width.
    """
    values: list[float] = []
    for row in data:
        raw = row.get(source)
        if raw is None:
            continue
        with contextlib.suppress(ValueError, TypeError):
            values.append(float(raw))
    return values


def _entry_values(
    data_table: ChartDataTable,
    data: ChartRenderData,
    x_field: str | None,
    color_field: str | None,
) -> list[list[float]]:
    """The numeric values each entry's cells will render, one list per entry.

    The single place that answers "what does this row actually show" —
    per-series ``(x, color)`` aggregate, aggregate per x, or the raw source
    column. Cell widths, the shared magnitude, and the band-centring dx all
    read this one list, so a row cannot be measured against different numbers
    than it is scaled by.
    """
    per_entry: list[list[float]] = []
    for entry in data_table.entries:
        if isinstance(entry, ChartDataTablePerSeries):
            source = entry.per_series
            if x_field is not None and color_field is not None:
                values = _aggregate_by_x_and_color(data, source, x_field, color_field)
            else:
                values = _numeric_column(data, source)
        elif isinstance(entry, ChartDataTableAggregate) and x_field is not None:
            values = _aggregate_by_x(data, entry.source, x_field, entry.aggregate)
        else:
            values = _numeric_column(data, entry.source)
        per_entry.append(values)
    return per_entry


def plain_numerals(
    data_table: ChartDataTable, formats: dict[str, str] | None
) -> list[StripNumerals]:
    """Numerals that declare nothing: every cell paints the author's own spec.

    The shape a strip had before this feature existed, and the one it keeps
    wherever the leftmost painted cell cannot be identified.
    """
    return [
        StripNumerals(
            digit_spec=resolve_format(entry.format, formats),
            anchor=StripAnchor.nowhere(),
        )
        for entry in data_table.entries
    ]


def _entry_numerals(
    data_table: ChartDataTable,
    entry_values: list[list[float]],
    formats: dict[str, str] | None,
    anchor: StripAnchor,
    hang: Literal["left", "right"] = "left",
) -> list[StripNumerals]:
    """How each entry spells its numbers, one per entry.

    An entry with no ``format:`` at all still gets numerals: ``resolve_format``
    hands back the theme's own default spec, so the row is spelled by that and
    declares nothing — the same text it painted before.

    House rules (narrative register, declare-once) apply only to engine-predefined
    format names. A raw d3 literal or user alias opts out: the anchor is a house
    convention layered on top of the engine's own vocabulary, not something an
    author's own literal spec should be silently opted into.
    """
    result: list[StripNumerals] = []
    for entry, values in zip(data_table.entries, entry_values, strict=True):
        resolved = resolve_format(entry.format, formats)
        raw_format = (
            entry.format.spec
            if isinstance(entry.format, FormatConfig)
            else entry.format
        )
        if raw_format is None or raw_format not in PREDEFINED_NUMBER_NAMES:
            result.append(
                StripNumerals(digit_spec=resolved, anchor=StripAnchor.nowhere())
            )
            continue
        result.append(strip_numerals_for_values(values, resolved, anchor, hang))
    return result


def _entry_cell_widths(
    data_table: ChartDataTable,
    values_per_entry: Sequence[Sequence[float]],
    dt_style: DataTableStyle,
    entry_numerals: Sequence[StripNumerals],
) -> list[float]:
    """Max pixel width of each entry's rendered cells (one per entry).

    Single measurement path shared by the band-centring dx
    (``_compute_data_table_entry_dx``) and the width-aware thinning budget
    (``max(...)`` at the post-pass).

    Measures the **bare** cell when the row declares its unit once: the anchor
    carries affixes no other cell does, so sizing the lane to it would shift
    every non-anchor cell to accommodate one. Measuring bare keeps the cells'
    shared edges in one lane and lets the wider anchor overhang into the gutter
    (right-axis) or into its own band (left-axis).
    """
    font_size = dt_style.font.size
    if font_size is None:
        raise ValueError(
            "data_table.font.size must be set by the theme cascade; "
            "a missing value means the theme is misconfigured"
        )
    measurer = get_font_measurer(dt_style.font.family, numeric=True)
    widths: list[float] = []
    for index, entry in enumerate(data_table.entries):
        numerals = entry_numerals[index]
        max_w = 0.0
        for num in values_per_entry[index]:
            # An entry with no authored format paints the raw value, so measure
            # that -- its numerals exist but are never emitted (see
            # _vl_format_calc's own format_spec guard).
            formatted = str(num) if entry.format is None else numerals.bare_text(num)
            w = measurer.measure(formatted, font_size)
            if w > max_w:
                max_w = w
        widths.append(max_w)
    return widths


def _compute_data_table_entry_dx(
    data_table: ChartDataTable,
    dt_style: DataTableStyle,
    has_time_unit: bool,
    entry_numerals: Sequence[StripNumerals],
    values_per_entry: Sequence[Sequence[float]],
    x_type: str | None = None,
) -> list[float] | None:
    """Compute per-entry dx offsets for band-centred number lanes.

    Returns None when no offset is needed.  dx is only meaningful on band-scale
    axes (ordinal/nominal) where bandPosition:0.5 pins the text anchor to the
    band centre.  For continuous axes (temporal without timeUnit, quantitative)
    there are no bands — a non-zero dx would shift the text away from the data
    point rather than centering it.

    When dx is applicable, returns a list of floats, one per entry:
    dx = max_formatted_width / 2 so that right-aligned text's right edge sits
    at band_center + max_w/2, centering the column over the bar.

    For ChartDataTableAggregate entries, data is pre-aggregated per x_field
    before measuring widths so the dx reflects the actual rendered values
    (aggregates are typically wider than any individual raw row).

    Mirrors the centre-on-midpoint invariant of _compute_lane_positions
    (table.py): the number lane is centred; decimals still align within it.
    """
    # dx centres the number column on the band midpoint (paired with the strip's
    # bandPosition:0.5 anchor). Applies to banded scales only: ordinal/nominal,
    # or temporal bucketed by timeUnit. Continuous axes (temporal without
    # timeUnit, quantitative) have no bands — a non-zero dx would shift text off
    # the data point rather than centering it.
    if not (has_time_unit or x_type in ("ordinal", "nominal")):
        return None

    # dx = max_formatted_width / 2 so right-aligned text's right edge sits at
    # band_center + max_w/2, centring the column over the bar. Same measurement
    # the thinning budget uses (per-series (x,color) aggregate, aggregate per x,
    # or raw source).
    entry_dx = [
        w / 2.0
        for w in _entry_cell_widths(
            data_table, values_per_entry, dt_style, entry_numerals
        )
    ]
    return entry_dx if any(dx > 0 for dx in entry_dx) else None


# Below this per-band width the strip mirrors the axis's cadence thinning:
# sparse data (e.g. a handful of points) shows every cell, dense data thins to
# the label-period openers. Distinct from the cell-width `min_band_px` used by
# the width-based sampling path — this is a label-band density floor.
_LABEL_STRIP_MIN_BAND_PX: float = 45.0


def _label_period_filter_expr(
    spec: dict[str, Any],
    resolved_chart_style: ResolvedChartDefaults,
    data: list[dict[str, Any]],
    x_field: str,
    chart_type: str,
    chart_local_axis_x: ResolvedAxisStyle,
) -> str | None:
    """Return a Vega filter expression restricting data_table cells to label-period openers.

    Returns None when no filtering is needed: label cadence equals band cadence,
    no temporal axis, no coarser label cadence, or opens_label_period returns None
    for an unsupported encoding/label-cadence pair.

    Semantics for aggregate: entries — the filter shows the per-opener-band
    aggregate, not a re-aggregated sum across all bands in the period. This is
    correct for the primary case (one source row per band), and re-aggregating
    across bands would require a different VL groupby granularity that changes
    what the agg op operates on. The filter matches the opener list used by
    labelExpr so every visible axis label has exactly one data_table cell.

    Both the temporal path (timeUnit in spec x encoding) and the ordinal
    bucketed-time path build the same kind of filter: opens_label_period's
    UTC-month/date predicate on the raw x field. Ordinal axes carry no VL
    timeUnit marker, so that path uses the same visibility resolver as the
    overlap path. Axis values may use a coarser resolved label-format cadence;
    width-driven visibility thinning does not change them.
    """
    enc_x = spec.get("encoding", {}).get("x", {})
    x_type = enc_x.get("type")

    # Chart-type-specific axis_x patch (Layer 4, theme-level, sparse) —
    # used below by the ordinal path's own time_unit precedence, which needs
    # the raw patch rather than the fully-cascaded axis.
    ct_style = getattr(resolved_chart_style, chart_type, None)
    ct_axis_x = getattr(ct_style, "axis_x", None) if ct_style is not None else None

    # Temporal path: timeUnit present in spec x encoding.
    enc_time_unit = enc_x.get("timeUnit")
    if enc_time_unit:
        # vl_time_unit emits "utc<grain>" (e.g. "utcyearmonth") in the spec.
        # Strip that prefix so internal helpers that work with Dataface grain
        # names ("yearmonth", "yearweek", …) receive the right string.
        dft_time_unit = enc_time_unit.removeprefix("utc")
        # chart_local_axis_x is resolved_chart.style.axis_x — the fully
        # chart-local-cascaded axis (including the Layer 4 chart-type patch
        # and any chart-local override) already baked at resolve time.
        axis_st = chart_local_axis_x
        format_tu = resolve_label_time_unit(dft_time_unit, axis_st.labels.time_unit)
        if not format_tu:
            return None
        # Same density guard as the ordinal branch below: only thin via the
        # label-period-opener gate when bands are too dense to show every
        # data point without overlap (< ~45px/band). Sparser data (e.g. 5
        # weekly points) must show every cell. A continuous temporal x scale
        # has no per-bucket axis.values list to reuse, so recompute distinct
        # count straight from the data.
        x_distinct = {
            row.get(x_field)
            for row in data
            if x_field in row and row.get(x_field) is not None
        }
        spec_width = spec.get("width")
        if not isinstance(spec_width, (int, float)) or spec_width <= 0:
            return None
        if not x_distinct or spec_width / len(x_distinct) >= _LABEL_STRIP_MIN_BAND_PX:
            return None
        safe_field = x_field.replace("'", "\\'")
        font = axis_st.labels.font
        measurer = get_font_measurer(font.family)
        dates = sorted(datetime.date.fromisoformat(str(v)[:10]) for v in x_distinct)
        band = (spec_width * resolved_chart_style.label_usable_ratio) / len(dates)
        visibility_tu, _ = resolve_temporal_label_visibility(
            dates,
            dft_time_unit,
            format_tu,
            measurer,
            font.size,
            band,
            axis_st.fiscal_year_start_month,
            allow_skip=(
                axis_st.labels.overlap.skip
                if axis_st.labels.overlap is not None
                else False
            ),
            edge_labels_flushed=temporal_edge_labels_flushed("temporal", axis_st),
        )
        if visibility_tu == dft_time_unit:
            return None
        gate = opens_label_period(
            dft_time_unit,
            visibility_tu,
            v=f"toDate(datum['{safe_field}'])",
            month="utcmonth",
            date="utcdate",
            fiscal_year_start_month=axis_st.fiscal_year_start_month,
        )
        if gate is None:
            return None
        return gate

    # Ordinal bucketed-time path: no VL timeUnit marker exists (an ordinal
    # domain is plain strings), so resolve the encoding grain and visibility
    # independently — preferring an authored axis_x.time_unit/label.time_unit
    # (board-level ct_axis_x, else chart-local), falling back to detecting the
    # grain straight from the data when nothing is authored. This mirrors
    # resolve_axis_x_overlap's own precedence so both paths agree on the same
    # grain and land on the same shared render-time visibility decision.
    if x_type == "ordinal":
        authored_encoding_tu = ct_axis_x.time_unit if ct_axis_x is not None else None
        if authored_encoding_tu is None:
            authored_encoding_tu = chart_local_axis_x.time_unit
        raw_x_values = [
            row.get(x_field)
            for row in data
            if x_field in row and row.get(x_field) is not None
        ]
        ord_time_unit: str | None
        if authored_encoding_tu not in (None, "auto", "none"):
            ord_time_unit = authored_encoding_tu
        else:
            try:
                # Mirrors build_cartesian_x_encoding's own degrade-on-ValueError:
                # date-like-but-unparseable bucket strings (half-year, etc.) fall
                # back to no recognizable grain rather than raising here.
                ord_time_unit = detect_time_unit(raw_x_values)
            except ValueError:
                ord_time_unit = None
        if ord_time_unit is None:
            return None

        # raw_x_values (built above for detect_time_unit) is the same projection.
        ord_x_distinct = sorted(set(raw_x_values), key=str)
        spec_width = spec.get("width")
        if (
            not isinstance(spec_width, (int, float))
            or spec_width <= 0
            or not ord_x_distinct
        ):
            return None

        # chart_local_axis_x is resolved_chart.style.axis_x — the fully
        # chart-local-cascaded axis (font included; see the temporal branch
        # above) already baked at resolve time.
        axis_st = chart_local_axis_x
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        layout = resolve_axis_x_overlap(
            axis_st,
            x_field,
            data,
            resolved_chart_style.label_usable_ratio,
            bucket_aligned_temporal=True,
            edge_labels_flushed=False,
            chart_width=spec_width,
        )
        visibility_tu = layout.visibility_time_unit or layout.format_time_unit
        if visibility_tu == ord_time_unit:
            return None
        # Same density guard as the temporal path above: only filter the strip
        # when cells are too narrow to show every one without crowding — the
        # cadence walk already decided the LABEL cadence; this decides whether
        # the data_table should mirror that thinning.
        if spec_width / len(ord_x_distinct) >= _LABEL_STRIP_MIN_BAND_PX:
            return None
        safe_field = x_field.replace("'", "\\'")
        gate = opens_label_period(
            ord_time_unit,
            visibility_tu,
            axis_st.fiscal_year_start_month,
            v=f"toDate(datum['{safe_field}'])",
            month="utcmonth",
            date="utcdate",
        )
        if gate is None:
            return None
        return gate

    return None


def _series_order_strip(
    chart_type: str,
    resolved_chart: _CartesianResolvedChartFields,
    charts_style: ResolvedChartDefaults,
    data: list[dict[str, Any]],
    color_field: str,
    distinct: set[str],
) -> list[str]:
    """Return series names for the data table strip in row-index order.

    The default strip position is ``top`` (strip above the chart).  For
    ``position: top``, strip row 0 sits at the VISUAL BOTTOM of the strip
    (y ≈ 0, closest to the chart), so the strip reads top-to-bottom starting
    from the LAST row index.  To have the strip read top-to-bottom with the
    visual-top series first (matching how you read the chart top-to-bottom),
    series_order[0] must be the visual-BOTTOM series (largest sum / alpha-first /
    first-encounter for bars; lowest last-x y for lines) and series_order[N]
    must be the visual-TOP series.

    Bar (stacked, value order): series_order[0] = largest global sum (baseline).
    Bar (stacked, alphabetical): series_order[0] = alpha-FIRST (A, at baseline).
    Bar (stacked, data): series_order[0] = first-encountered (at baseline).
    Bar (non-stacked / grouped): alphabetical ascending.
    Line / non-stacked area: series_order[0] = lowest last-x y (bottom of chart).
    Stacked area: series_order[0] = alpha-FIRST (VL default puts A at baseline).
    """
    x_field = resolved_chart.x
    raw_y = resolved_chart.y
    y_field = raw_y if isinstance(raw_y, str) else None
    # .stack exists on ResolvedBarChart; None for other V2 types.
    stack = (
        resolved_chart.stack if isinstance(resolved_chart, ResolvedBarChart) else None
    )

    if chart_type == "bar":
        is_gb = stack == "none" and effective_color_field(resolved_chart) is not None
        is_stacked = stack != "none" and not is_gb
        if not is_stacked:
            return sorted(distinct)
        stack_order = charts_style.bar.stack_order
        if stack_order == "alphabetical":
            # alpha-LAST at top of stack → strip visual top → series_order[N]
            # series_order[0] = alpha-FIRST (at baseline)
            return sorted(distinct)
        if stack_order == "data":
            # last-encounter at top → strip visual top → series_order[N]
            # series_order[0] = first-encounter (at baseline)
            seen: list[str] = []
            seen_set: set[str] = set()
            for row in data:
                s = row.get(color_field)
                if s is not None:
                    key = str(s)
                    if key not in seen_set:
                        seen_set.add(key)
                        seen.append(key)
            return [s for s in seen if s in distinct]
        # Default: None / "value" — smallest sum at top of stack → series_order[N].
        # series_order[0] = largest sum (at baseline).
        global_sums: dict[str, float] = dict.fromkeys(distinct, 0.0)
        if y_field:
            for row in data:
                s = row.get(color_field)
                y = row.get(y_field)
                if s is None or y is None:
                    continue
                key = str(s)
                if key in global_sums:
                    with contextlib.suppress(ValueError, TypeError):
                        global_sums[key] += float(y)
        # Descending: largest (baseline) = series_order[0]; smallest (top) = series_order[N].
        # For position:top, visual reading order is reversed: row N is at strip top.
        return sorted(distinct, key=lambda s: (-global_sums[s], s))

    # Stacked area: alpha-LAST at top of VL stack → series_order[N]; alpha-FIRST = series_order[0].
    is_stacked_area = chart_type == "area" and stack != "none"
    if is_stacked_area:
        return sorted(distinct)

    # Line / non-stacked area: highest last-x y at chart top → series_order[N].
    # series_order[0] = lowest last-x y (bottom of chart).
    if not x_field or not y_field or not data:
        return sorted(distinct)

    last_x = None
    for row in data:
        v = row.get(x_field)
        if v is None:
            continue
        if last_x is None or v > last_x:
            last_x = v

    last_y: dict[str, float] = dict.fromkeys(distinct, 0.0)
    if last_x is not None:
        for row in data:
            if row.get(x_field) != last_x:
                continue
            s = row.get(color_field)
            y = row.get(y_field)
            if s is None or y is None:
                continue
            with contextlib.suppress(ValueError, TypeError):
                last_y[str(s)] = float(y)

    # Ascending: lowest y = series_order[0]; highest y (chart top) = series_order[N].
    return sorted(distinct, key=lambda s: (last_y[s], s))


def apply_chart_data_table_post_pass(
    spec: dict[str, Any],
    resolved_chart: _CartesianResolvedChartFields,
    charts_style: ResolvedChartDefaults,
    data: list[dict[str, Any]],
    padding: dict[str, Any] | None,
    chart_type: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Post-pass: attach the data_table strip when the chart authors one.

    Single source of truth for the validate → resolve-style → attach →
    reserve-padding sequence. Called from every render branch that needs
    to honor `chart.data_table`. Returns the (possibly mutated) spec plus the
    (possibly augmented) padding kwarg the caller forwards to _finalize.

    Padding-bump destination depends on whether the caller supplied an
    external padding kwarg (which _finalize overwrites wholesale) or
    None (which leaves spec.padding alone).
    """
    data_table = resolved_chart.data_table
    if data_table is None:
        return spec, padding
    if (
        isinstance(resolved_chart, ResolvedBarChart)
        and resolved_chart.orientation == "horizontal"
    ):
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message=(
                "chart.data_table is not supported on horizontal bar charts "
                f"(chart {resolved_chart.id!r}): horizontal bars swap the "
                "category axis onto y, and the strip's category-on-x layout "
                "has no defined position there. Use a vertical bar, or drop "
                "data_table until horizontal support is implemented."
            ),
        )
    # Normalize labeled temporal strings (e.g. "Jan 2024" → "2024-01-01") so
    # the validator sees lex-sortable ISO dates and the period-filter indexof
    # values match the ISO dates the V2 emitter produces in axis.values.
    # V1's render_standard_vega_spec does the same normalization before calling
    # validate_preaggregated_data; V2 emitters normalize internally but pass the
    # original data to this post-pass, so we mirror the normalization here.
    if resolved_chart.x:
        data = normalize_labeled_temporal(data, resolved_chart.x)
    # Extract the x encoding type from the already-built spec.
    _encoding = spec.get("encoding")
    _x_encoding = _encoding.get("x") if isinstance(_encoding, dict) else None
    x_encoding: VLDict = _x_encoding if isinstance(_x_encoding, dict) else {}
    x_type: str | None = x_encoding.get("type")
    # For the validator, chronologically-ordered axes behave like temporal — the
    # window sort produces chronological order — so sampling the strip is safe.
    # This covers (a) date/datetime objects (e.g. a bar's `::date` x column,
    # which the bar mark clamps to a categorical scale but is really temporal),
    # and (b) lex-sortable date-like strings (e.g. "2024-01"). Non-lex-sortable
    # string patterns ("Jan 2024", "01/2024") are normalized to ISO by
    # normalize_labeled_temporal above, so they also pass here.
    # IMPORTANT: this reclassification is only for the validator.  x_type (the
    # actual spec encoding type) is kept separate so centering still applies to
    # categorical date axes — they render with bandPosition:0.5, so they need
    # dx exactly like any other ordinal/nominal axis.
    validator_x_type = x_type
    if validator_x_type in ("ordinal", "nominal") and resolved_chart.x and data:
        # Require ALL non-null values to be chronologically ordered — one stray
        # non-date value mid-column keeps the axis categorical (fail-closed:
        # dropping real categories via sampling would be wrong).
        field = resolved_chart.x
        all_chronological = True
        for row in data:
            v = row.get(field)
            if v is None:
                continue
            if isinstance(v, datetime.date):  # date/datetime (datetime subclasses date)
                continue
            if isinstance(v, str) and is_lex_sortable_date_like(v):
                continue
            all_chronological = False
            break
        if all_chronological:
            validator_x_type = "temporal"
    dt_style = resolved_chart.effective_data_table_style
    assert dt_style is not None, (
        "resolved_chart.effective_data_table_style must be baked when "
        "data_table is not None — see compile.resolve._kwargs._data_table_geometry"
    )
    # color_field drives the series_order/palette resolution below.
    color_field = effective_color_field(resolved_chart)
    # How each row spells its numbers, resolved once from the values it will
    # render. Read three times below -- the width budget, the band-centring dx,
    # and the cells themselves -- so a row cannot be measured against different
    # numbers than it paints.
    # Declaring the unit once requires knowing which cell is painted leftmost.
    # An ordered axis can be thinned, so only a row number computed after every
    # filter answers that; a category axis is never thinned and carries
    # `sort: null`, so its leftmost cell is the first x in data order. An
    # authored `sort:` on a category axis defeats both, and there the strip
    # keeps today's per-cell formatting rather than stranding the unit mid-row.
    # axis_y.position is baked to "left"/"right" at resolve time; read from the
    # resolved chart style (not the board-level charts_style which is "auto").
    _ay_style = getattr(
        resolved_chart, "style", None
    )  # type-state: silent_fallback — a resolved cartesian chart may carry no style; pre-existing, relocated by this diff
    resolved_ay = getattr(
        _ay_style, "axis_y", None
    )  # type-state: silent_fallback — optional axis_y off that style; pre-existing, relocated by this diff
    assert resolved_ay is not None, (
        f"cartesian resolved chart must carry style.axis_y — got {resolved_chart!r}"
    )
    axis_label_padding = resolved_ay.labels.padding
    assert axis_label_padding is not None, "axis_y.labels.padding unset"
    position = resolved_ay.position
    resolved_orient: str = position if position is not None else "right"
    if resolved_orient not in ("left", "right"):
        raise ValueError(
            f"axis_y.position resolved to unexpected value {resolved_orient!r}; "
            "expected 'left' or 'right'"
        )
    # mypy can't narrow `resolved_orient` from the ValueError guard above,
    # so the cast is required for mypy even though pyright sees it as redundant.
    axis_y_orient = cast(Literal["left", "right"], resolved_orient)  # pyright: ignore[reportUnnecessaryCast]  # type-state: cast — mypy cannot narrow resolved_orient past the ValueError guard above; pyright sees it redundant; pre-existing, relocated by this diff
    # Which side the anchor's affix overhangs. Right-oriented y-axis: affix leads
    # digits, hanging into the gutter (left). Left-oriented y-axis: affix trails
    # digits, hanging into the anchor cell's own band (right), so every non-anchor
    # cell's left digit edge stays in one lane.
    hang: Literal["left", "right"] = "left" if axis_y_orient == "right" else "right"
    if (
        x_encoding.get("field")
        # Only `sort: null` (key present, value null) signals data order.
        # An absent sort key means VL picks alphabetical — not predictable from
        # data row order. Distinguish present-null from key-absent explicitly.
        and "sort" in x_encoding
        and x_encoding["sort"] is None
        and x_encoding.get("type") in ("nominal", "ordinal")
    ):
        # `sort: null` tells VL to paint the domain in data-insertion order.
        # An unsorted window follows the same order, so `by_drawn_index_data_order`
        # anchors the leftmost visible band regardless of query sort direction,
        # datetime normalization differences, or whether the period filter drops
        # the first emitter row.
        anchor = StripAnchor.by_drawn_index_data_order()
    elif x_encoding.get("type") in ("nominal", "ordinal") and "sort" in x_encoding:
        # Authored non-null sort: paint order is determined externally.
        # Fail-closed — no anchor.
        anchor = None
    elif validator_x_type == "temporal":
        # True temporal OR reclassified nominal/ordinal with no explicit sort:
        # VL sorts ascending by x, matching drawn_index's ascending window sort.
        anchor = StripAnchor.by_drawn_index()
    else:
        anchor = None
    entry_values = _entry_values(data_table, data, resolved_chart.x, color_field)
    entry_numerals = (
        _entry_numerals(data_table, entry_values, charts_style.formats, anchor, hang)
        if anchor is not None
        else plain_numerals(data_table, charts_style.formats)
    )
    # Per-band pixel budget: measured cell width + horizontal cell padding.
    # Drives width-aware thinning; replaces the former hardcoded per-band literal.
    max_cell_w = max(
        _entry_cell_widths(data_table, entry_values, dt_style, entry_numerals),
        default=0.0,
    )
    # Temporal (drawn-index) anchors may land on band 2+ when the first cell
    # is zero — the CARRIES running-sum skips it and anchors on the next
    # non-zero cell. That anchor paints more glyphs than the bare digit-only
    # cell the budget was measured from. If the anchor's affix width is not
    # folded in, it overhangs into an adjacent cell's glyphs.
    # entry_dx stays on the bare measurement (keeps shared edges aligned);
    # only min_band_px is expanded here.
    band_budget_w = max_cell_w
    # _entry_cell_widths raises ValueError on a None font size, so this is reachable
    # only when font.size is set.
    _font_size = dt_style.font.size
    if _font_size is None:
        raise ValueError(
            "dt_style.font.size must be set; _entry_cell_widths should have raised first"
        )
    _measurer = get_font_measurer(dt_style.font.family, numeric=True)
    for _num, _vals in zip(entry_numerals, entry_values, strict=True):
        if not _num.anchor.needs_drawn_index:
            continue
        # Measure the max-abs value (closest to the actual anchor cell width).
        max_abs_val = max((_v for _v in _vals), key=abs, default=None)
        if max_abs_val is not None:
            _aw = _measurer.measure(_num.anchor_text(max_abs_val), _font_size)
            if _aw > band_budget_w:
                band_budget_w = _aw
    min_band_px = band_budget_w + 2.0 * dt_style.row.padding.horizontal
    sampling_step = validate_data_table_against_data(
        data_table, resolved_chart.x, data, x_type=validator_x_type
    )
    # Width-based step for ordered axes: if the measured cell width exceeds the
    # per-band budget, compute how many columns fit and thin accordingly.
    # Only ordered axes (validator_x_type == "temporal") may be width-sampled;
    # non-chronological ordinal axes are never sampled (dropping unordered
    # categories is silent data loss — fail-closed).
    if validator_x_type == "temporal" and resolved_chart.x and data and min_band_px > 0:
        spec_w = spec.get("width")
        if isinstance(spec_w, (int, float)) and spec_w > 0:
            n_x = len(
                {
                    row.get(resolved_chart.x)
                    for row in data
                    if row.get(resolved_chart.x) is not None
                }
            )
            if n_x > 0:
                fit_cols = max(1, math.floor(spec_w / min_band_px))
                width_step = math.ceil(n_x / fit_cols)
                sampling_step = max(sampling_step, width_step)
    # When the overlap resolver allowed all labels (labelOverlap ≠ "parity"), the
    # axis does NOT drop any ticks, so the strip must show every cell too.  The
    # density gate in validate_data_table_against_data fires on row count alone;
    # override it to 1 when the emitted spec confirms all labels are visible.
    # Exception: temporal continuous x axes are gated out of this reset entirely
    # (regardless of labelOverlap) because VL places "nice" ticks rather than one
    # per data value. The strip still needs thinning via sampling_step — do not
    # reset it just because labelOverlap is not "parity".
    # Width-gate: do NOT reset when cells don't fit at the current density —
    # the spec axis may label OK (short ticks fit) while strip cells are too wide.
    if sampling_step > 1:
        enc = spec.get("encoding")
        x_enc = enc.get("x") if isinstance(enc, dict) else None
        x_axis = x_enc.get("axis") if isinstance(x_enc, dict) else None
        x_type = x_enc.get("type") if isinstance(x_enc, dict) else None
        # NOTE: We re-read the VL directive from the already-emitted spec rather
        # than threading the resolver's `label_overlap` directive here.  This is a
        # seam constraint — `attach_data_table` receives the finished spec, not the
        # resolver's return value.  The check assumes a flat `encoding.x.axis` shape;
        # faceted/multiples specs nest encoding differently and would bypass this path.
        if x_type != "temporal" and not (
            isinstance(x_axis, dict) and x_axis.get("labelOverlap") == "parity"
        ):
            # Only reset when cells actually fit; keep thinning when they overflow.
            spec_w = spec.get("width")
            n_x = (
                len(
                    {
                        row.get(resolved_chart.x)
                        for row in data
                        if resolved_chart.x and row.get(resolved_chart.x) is not None
                    }
                )
                if resolved_chart.x and data
                else 0
            )
            cells_fit = (
                isinstance(spec_w, (int, float))
                and spec_w > 0
                and n_x > 0
                and spec_w / n_x >= min_band_px
            )
            if cells_fit:
                sampling_step = 1
    # Resolve series_order and dark_fills for per_series entries.
    has_per_series = any(
        isinstance(e, ChartDataTablePerSeries) for e in data_table.entries
    )
    series_order: list[str] | None = None
    dark_fills: list[str] | None = None
    if has_per_series:
        # Resolve series order so the strip row adjacent to the plot matches
        # the chart's visual stack segment at that edge (adjacency invariant).
        # See _series_order_strip for full per-chart-type ordering rules.
        # Strip row 0 = visual bottom of strip (closest to chart); series_order[N]
        # = visual top of strip, matching the chart's own top-to-bottom reading.
        if color_field and data:
            distinct: set[str] = set()
            for row in data:
                s = row.get(color_field)
                if s is not None:
                    distinct.add(str(s))
            series_order = _series_order_strip(
                chart_type, resolved_chart, charts_style, data, color_field, distinct
            )
            dark_palette = list(charts_style.dark_companion_palette)
            # VL assigns palette[i] to the i-th series in alphabetical color
            # domain. Map each entry in series_order to its alphabetical
            # palette index (dark_companion_palette is positionally aligned
            # with palette) so non-alphabetical strip orders still render
            # with the same dark-companion ink the chart's own marks use.
            alpha_index = {s: i for i, s in enumerate(sorted(series_order))}
            dark_fills = [
                dark_palette[alpha_index[s] % len(dark_palette)] for s in series_order
            ]
    series_count = len(series_order) if series_order else 0
    chart_style = getattr(resolved_chart, "style", None)
    axis_x_style = chart_style.axis_x if chart_style is not None else None
    period_filter = None
    if resolved_chart.x:
        assert axis_x_style is not None, (
            f"cartesian resolved chart must carry style.axis_x — got {resolved_chart!r}"
        )
        period_filter = _label_period_filter_expr(
            spec,
            charts_style,
            data,
            resolved_chart.x,
            chart_type,
            chart_local_axis_x=axis_x_style,
        )
    # When a period_filter is active it already restricts strip cells to
    # label-period openers (e.g. one per month on a daily-data chart).
    # Applying sampling on top would further thin the strip — e.g. daily
    # data with 365 rows gives sampling_step=10, then the period filter
    # keeps 12 monthly openers, and sampling reduces that to ~2 cells.
    # The period filter is the correct thinning mechanism; suppress sampling.
    if period_filter is not None:
        sampling_step = 1
    # Per_series row labels repeat the series names; drop them when the chart
    # already shows those names via a legend or endpoint labels.
    # Resolved models carry .legend (shared base) with the per-chart resolved value.
    legend_visible = resolved_chart.legend.visible
    legend_shows_series = color_field is not None and legend_visible
    # When the table has per_series rows the strip labels serve as the series
    # legend.  Suppress the side legend to avoid redundant ink.  Endpoint labels
    # are orthogonal — both the label strip and the endpoint pane may be visible.
    suppress_legend = has_per_series and legend_shows_series
    # Bar charts: centre the value column on the band (dx = max formatted width / 2).
    # Line/area charts: anchor the aligned edge straight on the mark — no dx.
    has_time_unit = bool(spec.get("encoding", {}).get("x", {}).get("timeUnit"))
    entry_dx = (
        _compute_data_table_entry_dx(
            data_table,
            dt_style,
            has_time_unit,
            entry_numerals,
            entry_values,
            x_type=x_type,
        )
        if chart_type == "bar" and resolved_chart.x
        else None
    )
    spec = attach_data_table(
        spec,
        data_table=data_table,
        style=dt_style,
        charts_style=charts_style,
        axis_offset_value=resolved_chart.data_table_axis_offset,
        axis_label_padding=axis_label_padding,
        sampling_step=sampling_step,
        entry_dx=entry_dx,
        entry_numerals=entry_numerals,
        series_order=series_order,
        dark_fills=dark_fills,
        label_period_filter_expr=period_filter,
        axis_y_orient=axis_y_orient,
        suppress_series_labels=False,
    )
    if suppress_legend:
        # attach_data_table wraps the spec as a layered spec (via _wrap_base_as_layer),
        # moving encoding into spec["layer"][0] for single-mark (V1) specs.
        # V2 emitters place shared channel encodings at the spec top-level before
        # wrapping, so the color encoding may be at spec["encoding"]["color"] rather
        # than in layer[0].  Check both locations; the first data-bound color wins.
        layers = spec.get("layer")
        base_enc = (
            layers[0].get("encoding")
            if isinstance(layers, list) and layers and isinstance(layers[0], dict)
            else None
        )
        color_enc = base_enc.get("color") if isinstance(base_enc, dict) else None
        if not isinstance(color_enc, dict) or color_enc.get("field") is None:
            # Fall back to top-level encoding (V2 grouped/stacked bar path).
            top_enc = spec.get("encoding")
            color_enc = top_enc.get("color") if isinstance(top_enc, dict) else None
        if isinstance(color_enc, dict):
            color_enc["legend"] = None
    strip_h = data_table_strip_height(
        data_table,
        dt_style,
        resolved_chart.data_table_axis_offset,
        series_count=series_count,
    )
    if strip_h > 0:
        if dt_style.position == "top":
            # Only charts with a title use title.offset — VL anchors the title
            # group above the outer container, so title.offset shifts it without
            # displacing the plot. Subtitle-only charts (no title element) use
            # bump_padding_top: _measure_vl_title_plot_gap cannot anchor on
            # role-title-text when no title is present.
            has_title = bool(resolved_chart.title)
            if has_title:
                # Use title.offset to reserve strip space so the title's absolute
                # position is invariant to the offset amount (verified under
                # autosize:pad: title stays fixed at (x, title_y) regardless of
                # title.offset value). bump_padding_top shifts the title down with
                # everything else, causing cross-row title misalignment.
                title_block = spec.get("title")
                assert isinstance(title_block, dict), (
                    "spec['title'] must be a dict when resolved_chart has a title; "
                    "finalize_vl (assemble_final_vl) must run before this post-pass"
                )
                # Seed the offset from the theme so config.title.offset is not
                # silently discarded when a spec-level offset overrides it.
                # The theme value lives in charts_style.title.position.offset;
                # None means "let VL decide" — treat as 0 for the spec-level write.
                theme_title_offset = charts_style.title.position.offset
                existing_offset = (
                    theme_title_offset if theme_title_offset is not None else 0.0
                )
                spec["title"] = {**title_block, "offset": existing_offset + strip_h}
            elif padding is not None:
                padding = {
                    **padding,
                    "top": float(padding.get("top", 0)) + strip_h,
                }
            else:
                bump_padding_top(spec, strip_h)
        else:
            if padding is not None:
                padding = {
                    **padding,
                    "bottom": float(padding.get("bottom", 0)) + strip_h,
                }
            else:
                bump_padding_bottom(spec, strip_h)
    return spec, padding
