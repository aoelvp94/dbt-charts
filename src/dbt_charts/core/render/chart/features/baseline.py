"""Baseline rule features: zero, top (normalize), unity (ratio-percent).

Rule layers are modelled as real ``ChartSpec(mark="rule", ...)`` overlays — not
sentinel strings.  The translator handles ``"rule"`` as a normal VL mark and folds
it into a ``layer[]`` spec alongside the main encoding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from dbt_charts.core.compile.models.chart.resolved import FormatState, ResolvedChart
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved.area import ResolvedAreaChart
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.chart.resolved.line import ResolvedLineChart
from dbt_charts.core.compile.models.chart.resolved.scatter import ResolvedScatterChart
from dbt_charts.core.compile.models.primitives import FormatConfig
from dbt_charts.core.compile.resolve.chart._chart_rows import ChartRows
from dbt_charts.core.render.chart.emitters._cartesian import (
    authored_measure_domain,
    build_zero_rule_if_applicable,
    effective_measure_domain,
    full_rule_at,
    multiples_scale_independent,
    non_bar_zero_rule_should_fire,
)
from dbt_charts.core.render.chart.feature import chart_rows
from dbt_charts.core.render.chart.spec import ChartSpec, RenderBox
from dbt_charts.core.render.layout_sizing import rows_for_query
from dbt_charts.core.utils import numeric_column_values


def _insert_rule(
    spec: ChartSpec,
    rule: ChartSpec,
    chart: ResolvedChart,
) -> None:
    """Insert ``rule`` into ``spec.layers`` at the V1-matching z-position.

    - bar/other: append last — rule renders above all fills.
    - line: prepend first — rule renders below strokes.
    - area: insert after the last ``area`` sub-layer — above fills, below fg stroke.

    A chart with ``chart.layers`` (an authored overlay — bar/line/area/scatter
    on top of the base) is a DIFFERENT shape: ``render_cartesian_overlay``
    wraps the base's own composite sub-layers into ONE outer entry, so
    ``spec.layers`` here is ``[base_composite, overlay1, overlay2, ...]`` —
    not the flat per-mark sub-layer list the per-chart-type branches below
    assume. Scanning that outer list for a top-level ``area`` mark never
    matches (it's nested one level down inside ``base_composite``), so the
    rule must simply append last: on top of the base AND every overlay
    layer, matching the "readability reference line" contract regardless of
    chart type. The area-specific under-the-fg-stroke placement only applies
    to a bare area's own internal composition, with no overlay on top of it.
    """
    if (
        isinstance(chart, (ResolvedBarChart, ResolvedLineChart, ResolvedAreaChart))
        and chart.layers
    ):
        spec.layers.append(rule)
        return
    if isinstance(chart, ResolvedLineChart):
        spec.layers.insert(0, rule)
    elif isinstance(chart, ResolvedAreaChart):
        last_area_idx = -1
        for i, layer in enumerate(spec.layers):
            if layer.mark == "area":
                last_area_idx = i
        if last_area_idx >= 0:
            spec.layers.insert(last_area_idx + 1, rule)
        elif len(spec.layers) >= 2:
            # No area layers found (unusual): insert before the last layer (hover).
            spec.layers.insert(len(spec.layers) - 1, rule)
        else:
            spec.layers.append(rule)
    else:
        # bar / layered / other: append last.
        spec.layers.append(rule)


def _is_percent_format(fmt: FormatState) -> bool:
    """True when a format string or FormatConfig spec contains a ``%`` token."""
    if isinstance(fmt, str):
        return "%" in fmt
    if isinstance(fmt, FormatConfig) and fmt.spec is not None:
        return "%" in fmt.spec
    return False


def _measure_field(
    chart: ResolvedBarChart
    | ResolvedLineChart
    | ResolvedAreaChart
    | ResolvedScatterChart,
    spec: ChartSpec,
    axis: str,
) -> str | Literal[False]:
    if isinstance(chart.y, str):
        return chart.y
    encoding = spec.encoding.get(axis)
    if isinstance(encoding, dict) and isinstance(encoding.get("field"), str):
        return encoding["field"]
    return False


def _zero_in_shared_domain(
    chart: ResolvedBarChart
    | ResolvedLineChart
    | ResolvedAreaChart
    | ResolvedScatterChart,
    measure_field: str,
    datasets: dict[str | None, ChartRows],
) -> bool:
    """Whether 0 lies inside the y domain every mark on this scale shares.

    Mirrors ``_shared_y_values``, the resolve-time function that actually
    decides the domain: the union of the base measure (or every wide
    measure) and every layer not pinned to an independent right axis.
    ``apply()`` has already bailed out for an independent dual axis, so
    every layer reaching here shares the base's scale.

    The union is the question, not "does any one series straddle 0". Two
    series that each stay on one side of zero still bracket it once they
    share a scale — an all-negative base under an all-positive overlay
    renders a domain spanning 0, and the rule belongs on it.
    """
    base_rows = chart_rows(chart, datasets).all_rows()
    # Wide charts carry the authored measures in wide_measures; query rows
    # have the real columns, not the synthetic WIDE_VALUE_FIELD. Scatter has
    # no fold/multi-measure render path, so it never has wide measures.
    fields = (
        chart.wide_measures
        if isinstance(chart, (ResolvedLineChart, ResolvedAreaChart))
        and chart.wide_measures
        else (measure_field,)
    )
    values = [v for field in fields for v in numeric_column_values(base_rows, field)]
    for layer in chart.layers:
        if layer.type == "bar":
            # VL bars always extend to/from 0 regardless of their own data
            # range — 0 is unconditionally in the shared domain once any bar
            # layer exists.
            return True
        if layer.y is None:
            continue
        values.extend(
            numeric_column_values(
                rows_for_query(layer.query_name, datasets, base_rows), layer.y
            )
        )
    if not values:
        return False
    return min(values) <= 0.0 <= max(values)


def _y_carries_the_measure(chart: ResolvedChart) -> bool:
    """Whether the y channel holds the measure a ``datum`` rule references.

    Line and area always put the measure on y. Scatter has no orientation
    field — x and y are both free-form data columns — so the dot-plot recipe
    rotates a scatter by moving the value onto x and the category onto y. A
    ``datum: 0`` or ``datum: 1`` rule has no position on a categorical axis,
    so it must not fire there.

    Read off the RESOLVED chart, never ``spec.encoding``: a scatter with
    authored ``layers`` has its encoding hoisted into the sub-layers by
    ``render_cartesian_overlay``, leaving ``x`` alone on the outer spec — a
    spec-side read answers False there and silently drops the rule from
    exactly the charts that layer a target line onto a scatter.
    ``ResolvedAxisStyle.is_quantitative`` is baked once at resolve time from
    the same channel classification that already decides the axis type, so
    this reads a fact fixed before the spec exists rather than
    reverse-engineering it from how the emitter composed the layers.
    """
    if not isinstance(chart, ResolvedScatterChart):
        return True
    return chart.style.axis_y.is_quantitative


def _domain_reaches(
    chart: ResolvedLineChart | ResolvedAreaChart | ResolvedScatterChart,
    data: list[dict[str, Any]],
    field: str,
    value: float,
) -> bool:
    """True when ``value`` lies within the bounds the measure axis pins.

    Reads ``effective_measure_domain`` — authored domain, else the
    headroom-expanded ``domain_min`` / ``domain_max``, else a zero-anchored
    axis's floor, else the data extent. See that function for why it reads only
    values the emitter really pins and never predicts Vega-Lite's own ``nice``.

    Reading the raw data range alone made the gate disagree with the render in
    two ways, each leaving a percent chart with a 100% tick painted and no rule
    on it: headroom pulling the domain across ``value`` with no data point
    there, and a zero-anchored axis starting at 0. Both are fixed.

    Deliberately conservative where nothing is pinned: an axis whose tick
    ladder rounds out past ``value`` still reports False, because a rung is a
    tick position and not a domain edge. Reading it once made this gate
    non-monotonic in headroom and let a rule paint outside the domain it then
    stretched to fit itself.

    Not a promise that True means painted, or that False means absent. Under
    ``multiples: {scale: independent}`` resolve bakes neither ladder nor
    bounds, so this reads the whole-dataset extent while each panel auto-fits
    its own narrower domain — a pre-existing disagreement this gate inherits.
    """
    values = numeric_column_values(data, field)
    bounds = effective_measure_domain(
        chart.style.axis_y,
        (min(values), max(values)) if values else None,
    )
    if bounds is None:
        return False
    lo, hi = bounds
    return lo <= value <= hi


@dataclass
class BaselineFeature:
    """Zero, top (normalize-stack), and unity (percent-format) baseline rules.

    Bar: zero rule always fires.
    Line / area / scatter: zero rule fires when data straddles 0 (or
    scale.zero isn't explicitly False).
    Normalize-stacked bar/area: top rules fire at datum 0 and 1 instead of a
    zero rule — except normalize-stacked, percent-format area, which gets
    only the single unity rule at datum 1 (no duplicate y=1 reference line).
    Line / area / scatter with percent format: unity rule fires at datum 1,
    independent of the zero/top rule above.
    """

    def applies_to(self, chart: ResolvedChart) -> bool:
        return isinstance(
            chart,
            (
                ResolvedBarChart,
                ResolvedLineChart,
                ResolvedAreaChart,
                ResolvedScatterChart,
            ),
        )

    def apply(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        box: RenderBox,
        datasets: dict[str | None, list[dict[str, Any]]],
    ) -> ChartSpec:
        # Independent dual-axis: a `datum: 0` rule added here would get its own
        # degenerate y scale (VL can't bind it to the base measure scale under
        # independent resolve). `render_cartesian_overlay` (emitters/_overlay.py)
        # owns zero-rule insertion for this case instead, nesting each rule
        # inside the specific layer entry that owns the scale it binds to;
        # skip here so this feature never also adds one.
        resolve_scale = spec.resolve.get("scale")
        if resolve_scale is not None and resolve_scale.get("y") == "independent":
            return spec
        # Independent small-multiples scale: FacetFeature (which records
        # `spec.facet_scale`, later realized as the facet-root `resolve.scale`
        # in translate.py) runs after this feature, so `spec.resolve` never
        # carries it here — check the chart's own `multiples.scale` instead.
        # The rule/unity decision below is made once from the pooled union of
        # every panel's rows; under independent scale each panel gets its own
        # y-domain, so a single chart-wide verdict can be wrong for any one
        # panel — skip it, same as the dual-axis case above.
        if isinstance(
            chart, _CartesianResolvedChartFields
        ) and multiples_scale_independent(chart):
            return spec
        self._apply_zero_or_top(spec, chart, datasets)
        self._apply_unity(spec, chart, chart_rows(chart, datasets).all_rows())
        return spec

    def _apply_zero_or_top(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        datasets: dict[str | None, list[dict[str, Any]]],
    ) -> None:
        if isinstance(chart, ResolvedAreaChart) and chart.stack == "center":
            # Streamgraph: y=0 is the visual centerline of the silhouette, not
            # a meaningful baseline — an explicit rule reads as chart noise.
            return
        if (
            isinstance(chart, (ResolvedBarChart, ResolvedAreaChart))
            and chart.stack == "normalize"
        ):
            if isinstance(chart, ResolvedAreaChart) and _is_percent_format(
                chart.format
            ):
                return  # unity rule (below) is the sole y=1 reference
            self._insert_top_rules(spec, chart)
            return
        if not chart_rows(chart, datasets).all_rows():
            return
        self._insert_zero_rule(spec, chart, datasets)

    def _insert_zero_rule(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        datasets: dict[str | None, list[dict[str, Any]]],
    ) -> None:
        assert isinstance(
            chart,
            (
                ResolvedBarChart,
                ResolvedLineChart,
                ResolvedAreaChart,
                ResolvedScatterChart,
            ),
        )
        authored = authored_measure_domain(chart.style.axis_y)

        # Determine whether the rule should fire. The log-scale, authored-domain,
        # and grid.visible guards live once in build_zero_rule_if_applicable below
        # — this branch only decides the family-specific straddle/always-fire
        # verdict feeding its `should_fire`.
        if isinstance(chart, ResolvedBarChart):
            should_fire = True
        else:
            # Line / area / scatter: mirror V1 _domain_includes_zero. The
            # rule's datum:0 pulls 0 into the unified domain, so it fires
            # whenever the measure axis isn't explicitly scale.zero=False.
            # Only an explicit scale.zero=False requires a straddle check.
            non_bar_measure_field = _measure_field(chart, spec, "y")
            if non_bar_measure_field is False:
                return
            if not _y_carries_the_measure(chart):
                return
            scale = chart.style.axis_y.scale
            _bsl_cont3 = scale.continuous if scale is not None else None
            zero_setting = _bsl_cont3.zero if _bsl_cont3 is not None else None
            should_fire = non_bar_zero_rule_should_fire(
                isinstance(chart, ResolvedScatterChart),
                zero_setting,
                zero_anchored=chart.style.axis_y.zero_anchored,
                authored_domain=authored,
                zero_in_domain=lambda: _zero_in_shared_domain(
                    chart, non_bar_measure_field, datasets
                ),
            )

        # Determine measure_field for synthetic data row.
        rule_axis = (
            "x"
            if isinstance(chart, ResolvedBarChart) and chart.orientation == "horizontal"
            else "y"
        )
        measure_field = _measure_field(chart, spec, rule_axis)

        if measure_field is False:
            return
        # Read zero style from the chart's own baked axis cascade (style.axis_y),
        # not board-level style — a chart-local axis patch has to win.
        zero_style = chart.style.axis_y.grid.zero
        assert zero_style is not None, (
            "zero grid style must be resolved before emitting the baseline rule"
        )
        axis_y_scale = chart.style.axis_y.scale
        continuous = axis_y_scale.continuous if axis_y_scale is not None else None
        rule = build_zero_rule_if_applicable(
            measure_field,
            rule_axis,
            log_scale=continuous is not None and continuous.type == "log",
            authored_domain=authored,
            grid_visible=chart.style.axis_y.grid.visible,
            zero_color=zero_style.color,
            zero_width=zero_style.width,
            should_fire=should_fire,
        )
        if rule is None:
            return
        _insert_rule(spec, rule, chart)

    def _insert_top_rules(self, spec: ChartSpec, chart: ResolvedChart) -> None:
        # Normalize stacks get BOTH the 0% baseline and 100% top reference lines,
        # fully styled (colour/width from the baked zero grid style) and drawn on
        # top of the bars — matches V1's two datum rules.
        assert isinstance(chart, (ResolvedBarChart, ResolvedAreaChart))
        # Same log-domain incompatibility as _insert_zero_rule's datum:0 guard.
        axis_y_scale = chart.style.axis_y.scale
        _top_cont = axis_y_scale.continuous if axis_y_scale is not None else None
        if _top_cont is not None and _top_cont.type == "log":
            return
        rule_axis = (
            "x"
            if isinstance(chart, ResolvedBarChart) and chart.orientation == "horizontal"
            else "y"
        )
        measure_field = _measure_field(chart, spec, rule_axis)
        if measure_field is False:
            return
        zero_style = chart.style.axis_y.grid.zero
        assert zero_style is not None, (
            "zero grid style must be resolved before emitting top rules"
        )
        # Horizontal bars put the measure on x, so the 0%/100% datum rules anchor
        # on x — not the categorical y axis (mirrors the zero rule).
        for datum in (0, 1):
            _insert_rule(
                spec,
                full_rule_at(
                    datum,
                    axis=rule_axis,
                    measure_field=measure_field,
                    color=zero_style.color,
                    width=zero_style.width,
                ),
                chart,
            )

    def _apply_unity(
        self,
        spec: ChartSpec,
        chart: ResolvedChart,
        data: list[dict[str, Any]],
    ) -> None:
        if not isinstance(
            chart, (ResolvedLineChart, ResolvedAreaChart, ResolvedScatterChart)
        ):
            return
        # axis_y.labels.format is the D3 spec resolved from the board+theme cascade.
        # Check it first — it converts dbt charts aliases ("percent_whole") to
        # their literal D3 form (".0%"), which always contains "%".
        ax_fmt = chart.style.axis_y.labels.format
        if not ((ax_fmt and "%" in ax_fmt) or _is_percent_format(chart.format)):
            return
        # grid.visible=False suppresses the unity rule (mirrors zero-rule gate).
        if not chart.style.axis_y.grid.visible:
            return
        measure_field = _measure_field(chart, spec, "y")
        if measure_field is False:
            return
        if not _y_carries_the_measure(chart):
            return
        # A normalize-stacked area reroutes its definitional 1.0 ceiling through
        # this rule (see _apply_zero_or_top); its unity rule always fires. Every
        # other percent chart fires only when the rendered domain reaches 1.0 —
        # see _domain_reaches.
        is_normalize_area = (
            isinstance(chart, ResolvedAreaChart) and chart.stack == "normalize"
        )
        if not is_normalize_area and not _domain_reaches(
            chart, data, measure_field, 1.0
        ):
            return
        zero_style = chart.style.axis_y.grid.zero
        assert zero_style is not None, (
            "zero grid style must be resolved before emitting unity rule"
        )
        _insert_rule(
            spec,
            full_rule_at(
                1,
                axis="y",
                measure_field=measure_field,
                color=zero_style.color,
                width=zero_style.width,
            ),
            chart,
        )
