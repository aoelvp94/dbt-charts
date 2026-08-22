"""Public chart rendering entrypoints."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path  # noqa: TID251 — DCT_TRACE_VL debug spec dump
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.chart.normalized import Chart
    from dbt_charts.core.compile.models.chart.resolved._partition import PartitionAxis
    from dbt_charts.core.compile.models.style.context import ChartStyleContext
    from dbt_charts.core.compile.models.style.resolved import (
        ResolvedChartDefaults,
        ResolvedStyle,
    )

_log = logging.getLogger(__name__)


def _trace_vl_spec(chart_id: str, renderer: str, spec: dict[str, Any]) -> None:
    """Write *spec* to DCT_TRACE_VL/<chart_id>-<renderer>.json when the env var is set.

    Set DCT_TRACE_VL to any directory path to enable.  The directory is created
    on first use.  renderer is "v1" or "v2".
    """
    trace_dir = os.getenv("DCT_TRACE_VL")  # noqa: TID251 — DCT_TRACE_VL debug knob
    if not trace_dir:
        return
    # Map the chart id to a safe basename so a id containing path separators or
    # ".." can't write outside the trace directory.
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", chart_id).strip(".") or "chart"
    out = Path(trace_dir) / f"{safe_id}-{renderer}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, default=str), encoding="utf-8")
    _log.debug("VL spec trace → %s", out)


from dbt_charts.core.compile.models.chart.resolved import ResolvedChart
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
    _SharedResolvedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.chart.resolved.pie import ResolvedPieChart
from dbt_charts.core.compile.resolve.chart.adaptive_stroke import (
    facet_panel_width,
    panel_axis_cardinality,
)
from dbt_charts.core.diagnostics import (
    ERR_RESOLVED_PIE_WIDTH_MISMATCH,
    ERR_VEGA_LITE_UNSUPPORTED_TYPE,
)
from dbt_charts.core.render.chart.artifacts import ChartRenderData, RenderArtifact
from dbt_charts.core.render.chart.data_table_attachment import (
    apply_chart_data_table_post_pass,
)
from dbt_charts.core.render.chart.emitters._cartesian import (
    count_horizontal_bar_categories,
    min_height_for_horizontal_bar_categories,
)
from dbt_charts.core.render.chart.serialization import build_dataface_json
from dbt_charts.core.render.chart.spec import RenderBox
from dbt_charts.core.render.chart.title_overflow import apply_title_overflow_to_spec
from dbt_charts.core.render.converters.chart import render_chart_artifact
from dbt_charts.core.render.errors import RenderError


def _render_vl_artifact(
    resolved: ResolvedChart,
    render_data: ChartRenderData,
    resolved_style: ResolvedStyle,
    *,
    width: float,
    height: float | None,
    is_placeholder: bool,
    datasets: dict[str | None, ChartRenderData] | None,
    padding: dict[str, int | float] | None,
) -> RenderArtifact:
    """VL emit path without the arc attached-table dispatch.

    Called by render_resolved_chart (after the dispatch check) and by
    _render_arc_attached_table (to render the donut without recursing into
    the dispatch again).

    ``width`` is always concrete here — every caller resolves a caller-omitted
    width to a real number (authored width, or the theme default) before
    reaching this function, so there is exactly one place per entry point
    where "no width given" becomes a number, not one per chart family.
    ``height`` stays ``None``-able: that's a real, meaningful signal ("let
    Vega auto-size vertically") with no equivalent fallback to resolve to.
    """
    from dbt_charts.core.render.chart.session import BoardRenderSession

    session = BoardRenderSession.create(resolved_style)
    svg = session.render_svg_family(
        resolved,
        render_data,
        width=width,
        height=height,
        is_placeholder=is_placeholder,
    )
    if svg is not None:
        return RenderArtifact(kind="svg", payload=svg)
    # render_svg_family only returns None for the VL families, all of which
    # are _SharedResolvedChartFields subclasses (KPI/callout/table/spark_bar
    # return svg above) — title_style is guaranteed present below.
    assert isinstance(resolved, _SharedResolvedChartFields)

    # Small multiples: every geometry decision an emitter makes (label
    # thinning, bar-band width, axis-title wrap...) must measure against the
    # panel it will actually paint into, not the whole card. Only a cartesian
    # chart with `multiples` authored can facet; every other resolved chart is the
    # N=1 case (row/col cardinality 1, no mirror gutter, box width == card
    # width) with no branch needed below. Gated on `multiples`, not on
    # `panel_axes` being non-empty: a chart resolved without data still
    # authors `multiples` and still renders a (degenerate, one empty-panel)
    # facet, so it still reserves facet chrome — `panel_axis_cardinality`
    # below floors an empty axes tuple to 1 on its own.
    is_faceted = (
        isinstance(resolved, _CartesianResolvedChartFields)
        and resolved.multiples is not None
    )
    row_cardinality = 1
    col_cardinality = 1
    has_mirror = False
    if is_faceted:
        assert isinstance(resolved, _CartesianResolvedChartFields)
        assert resolved.multiples is not None  # panel_axes is non-empty only then
        row_cardinality = panel_axis_cardinality(
            resolved.panel_axes, resolved.multiples.rows
        )
        col_cardinality = panel_axis_cardinality(
            resolved.panel_axes, resolved.multiples.columns
        )
        has_mirror = bool(resolved.style.axis_y.mirror)

    effective_height = height
    if (
        isinstance(resolved, ResolvedBarChart)
        and resolved.orientation == "horizontal"
        and render_data
        and height is not None
        and height > 0
    ):
        n = count_horizontal_bar_categories(resolved.x, render_data)
        min_h = min_height_for_horizontal_bar_categories(
            n, resolved.style.axis_x, resolved.style.mark.size
        )
        if min_h > 0:
            # Multiply the whole-set floor by the row count BEFORE dividing
            # by it below — otherwise every panel gets min_h / row_cardinality
            # and lands under its own floor (a height-axis instance of the
            # same card-width-not-panel-width bug this task exists to fix).
            # The facet operator resolves the category ordinal scale as
            # shared, so every panel paints the union of every panel's
            # categories regardless of which rows landed in it — the
            # whole-set count is what each panel actually needs room for.
            effective_height = max(height, min_h * row_cardinality)

    # effective_height stays None-able for the *spec* below — that's a real
    # signal ("let Vega auto-size vertically"). RenderBox is a different
    # question: emitters need the extent the chart will actually occupy.
    # When a height *is* given, `_apply_facet_layout` stamps it on the unit
    # spec's `height`, so VL divides it across the row axis and each panel
    # gets `effective_height / row_cardinality` — divide here to match. When
    # no height is given, nothing is stamped: VL falls back to
    # `config.view.continuousHeight`, which applies per *unit* view, i.e.
    # already per-panel — dividing it again here would measure chrome
    # against a fraction of what each panel actually paints. Width has no
    # such branch: `facet_panel_width` always divides, because the card
    # width is always a real number by this point (never None-able).
    box_height_full = (
        effective_height / row_cardinality
        if effective_height is not None
        else resolved_style.chart_defaults.view.continuous_height
    )
    box = RenderBox(
        width=(
            facet_panel_width(width, col_cardinality, has_mirror)
            if is_faceted
            else width
        ),
        height=box_height_full,
    )
    # emit_chart resolves the chart's own rows from `datasets` by query_name —
    # the caller's `datasets` (layer overrides only, for older callers) may not
    # carry the base entry, so it's added here if missing. `render_data` is
    # this function's own (data, datasets) contract, unrelated to emit_chart's
    # collapsed single-datasets one; kept as-is (used above for the arc/bar
    # dispatch checks and the data_table strip after this call).
    full_datasets: dict[str | None, ChartRenderData] = (
        dict(datasets) if datasets else {}
    )
    if resolved.query_name not in full_datasets:
        full_datasets[resolved.query_name] = render_data
    chart_spec = session.emit_chart(
        resolved,
        box,
        full_datasets,
    )
    vl = session.finalize_vl(chart_spec)
    if "facet" in vl:
        # Small multiples: per-panel width/height go on the inner unit spec, while
        # padding and title frame the whole set at the facet root. Facet is mutually
        # exclusive with hconcat/data_table (FacetFeature refuses those combos).
        if padding is not None:
            vl["padding"] = padding
        assert isinstance(
            resolved, _CartesianResolvedChartFields
        )  # is_faceted implies this
        _apply_facet_layout(
            vl, resolved.panel_axes, has_mirror, width, effective_height
        )
        apply_title_overflow_to_spec(vl, resolved.title_style, chart_id=resolved.id)
        _trace_vl_spec(resolved.id, "v2", vl)
        return RenderArtifact(kind="vega_spec", payload=vl)
    if "hconcat" in vl:
        size_target = vl["hconcat"][0]
        if "title" in vl:
            size_target["title"] = vl.pop("title")
        # hconcat's title wrap is deferred to render_vega_spec (see the
        # comment below) — stamp the chart's own title_style so the deferred
        # wrap reads the same chart-local source as the non-hconcat path
        # above, instead of re-deriving it from the board-level style bag.
        # A plain dict, not the live TitleStyle object: this sentinel can
        # leak into a raw spec dict handed directly to vl-convert (e.g.
        # generate_vega_lite_spec()'s return value, or a RenderArtifact
        # payload used outside render_chart_artifact) — an unrecognized
        # dict-valued key is harmless there, but a Pydantic object is not
        # JSON-serializable.
        vl["$df_title_style"] = resolved.title_style.model_dump()
        # right_pane endpoint labels only (top_rail/vconcat is out of scope —
        # it separates labels along x, not y, and is unaffected by this
        # defect). Carries what render_vega_spec's post-probe re-cascade
        # needs: the intended pixel gap and the raw data-value clamp bounds.
        # A plain dict for the same JSON-safety reason as $df_title_style above.
        if (
            chart_spec.endpoint_label_layout == "right_pane"
            and chart_spec.endpoint_label_data is not None
        ):
            eld = chart_spec.endpoint_label_data
            vl["$df_endpoint_label_cascade"] = {
                # The true endpoint values. The pane's own rows may have been
                # spread apart to make the scale measurable (translate.py's
                # _spread_for_measurement), so they are not a source of truth.
                "anchors": list(eld.positions),
                "gap_px": eld.label_gap_px,
                "y_domain_min": eld.y_domain_min,
                "y_domain_max": eld.y_domain_max,
                "series_field": eld.series_field,
                "value_alias": eld.value_alias,
            }
    else:
        size_target = vl
    if padding is not None:
        # Padding is root-only in Vega-Lite: on a concat it is dropped from a
        # child pane and Vega falls back to its own default, which put a
        # multi-series chart's ink 11px higher in its cell than its
        # single-series neighbour's. Width and height stay on `size_target` —
        # those genuinely are per-pane.
        vl["padding"] = padding
    if width > 0:
        size_target["width"] = width
        if "hconcat" in vl:
            vl["$df_target_width"] = width
        elif "vconcat" in vl:
            # VL ignores top-level width on vconcat (unlike single views / hconcat).
            # Propagate to each child pane explicitly so the overshoot corrector has a
            # concrete width to shrink — mirrors V1's _wrap_horizontal_top_row_rail which
            # always pinned both panes to chart_pane_width before setting $df_target_width.
            for pane in vl["vconcat"]:
                pane.setdefault("width", width)
            vl["$df_target_width"] = width
    if effective_height is not None and effective_height > 0:
        size_target["height"] = effective_height
        if "hconcat" in vl:
            vl["$df_target_height"] = effective_height
            if len(vl["hconcat"]) > 1:
                vl["hconcat"][1]["height"] = effective_height
        elif "vconcat" in vl:
            # VL ignores top-level height on vconcat, same as width above.
            # _wrap_vconcat_label_rail is the only producer of this shape and
            # always sets both the rail pane's height and the root spacing, so
            # read them rather than hardcoding: the chart pane (index 1) gets
            # whatever the authored height leaves once the rail and the gap
            # below it are paid for, so the panes together fill the slot.
            rail_height = vl["vconcat"][0]["height"]
            spacing = vl["spacing"]
            vl["vconcat"][1]["height"] = max(
                effective_height - rail_height - spacing, 1.0
            )
            vl["$df_target_height"] = effective_height
    if "hconcat" not in vl:
        # hconcat's title wrap is deferred to render_vega_spec: vl-convert
        # ignores autosize:fit on concat children, so pane[0].width here is
        # still the full column width — wrapping against it now overstates
        # the room the title actually has. render_vega_spec wraps it after
        # _correct_concat_overshoot shrinks pane[0] to its real width.
        apply_title_overflow_to_spec(
            size_target, resolved.title_style, chart_id=resolved.id
        )
    _trace_vl_spec(resolved.id, "v2", vl)
    return RenderArtifact(kind="vega_spec", payload=vl)


def _apply_facet_layout(
    vl: dict[str, Any],
    axes: tuple[PartitionAxis, ...],
    has_mirror: bool,
    width: float,
    height: float | None,
) -> None:
    """Size small-multiples panels on the inner unit spec of a facet ``vl``.

    vl-convert does not reflow facet panels under ``autosize:fit``, so the slot
    dimensions (whole-set size) are divided into per-panel width/height here. The
    row/column counts are read off the baked ``panel_axes`` (matched to
    ``vl["facet"]``'s own field names, never re-derived from render data — this
    is the same source ``density_adaptive_stroke`` and the ``RenderBox``
    construction above key off, so all three can never drift); a chrome gutter
    is reserved for the row-header label and, when the measure axis is
    mirrored to the far edge (``has_mirror``, resolve's baked
    ``resolved.style.axis_y.mirror`` verdict), the opposite-edge axis. Mutates
    ``vl["spec"]`` in place.
    """
    # _wrap_facet builds the inner spec and at least one of facet.row/column, so
    # index directly — a missing key is a builder bug, not a runtime input to
    # tolerate. Either facet dimension may be absent (rows-only / columns-only).
    facet = vl["facet"]
    unit = vl["spec"]
    row_field = facet["row"]["field"] if "row" in facet else None
    col_field = facet["column"]["field"] if "column" in facet else None
    panel_rows = panel_axis_cardinality(axes, row_field)
    panel_cols = panel_axis_cardinality(axes, col_field)
    if width > 0:
        unit["width"] = facet_panel_width(width, panel_cols, has_mirror)
    if height is not None and height > 0:
        unit["height"] = height / panel_rows


def _render_arc_attached_table(
    chart: ResolvedPieChart,
    data: list[dict[str, Any]],
    resolved_style: ResolvedStyle,
    *,
    padding: dict[str, int | float] | None,
) -> RenderArtifact:
    """Render and compose the finalized pie and companion table children."""
    from dbt_charts.core.render.chart.arc_attached_table import (
        compose_attached_table_svg,
    )
    from dbt_charts.core.render.chart.emitters.pie import prepare_pie_render_rows
    from dbt_charts.core.render.chart.table import render_table_svg
    from dbt_charts.core.render.svg_utils import extract_svg_dimensions

    assert chart.attached_table is not None
    assert chart.attached_table_placement != "none"
    assert chart.attached_heading_font is not None
    donut_artifact = _render_vl_artifact(
        chart,
        data,
        resolved_style,
        width=chart.wheel_width,
        height=None,
        is_placeholder=False,
        datasets=None,
        padding=padding,
    )
    donut_svg = render_chart_artifact(
        donut_artifact,
        "svg",
        resolved_style,
        width=chart.wheel_width,
        height=None,
        chart_id=chart.id,
    )
    donut_dims = extract_svg_dimensions(donut_svg)
    table_svg = render_table_svg(
        chart.attached_table,
        prepare_pie_render_rows(chart, data)[1],
        width=chart.attached_table_width,
        board_style=resolved_style,
    )
    table_dims = extract_svg_dimensions(table_svg)
    composed, _w, _h = compose_attached_table_svg(
        donut_svg=donut_svg,
        table_svg=table_svg,
        donut_width=donut_dims.width,
        donut_height=donut_dims.height,
        table_width=table_dims.width,
        table_height=table_dims.height,
        card_width=chart.resolution_width,
        placement=chart.attached_table_placement,
        heading=chart.attached_heading,
        heading_font_family=chart.attached_heading_font.family,
        heading_font_size=chart.attached_heading_font.size,
        heading_font_weight=str(chart.attached_heading_font.weight),
        heading_color=chart.attached_heading_font.color,
        gap=chart.attached_table_gap,
        heading_gap=chart.hybrid_heading_gap,
    )
    return RenderArtifact(kind="svg", payload=composed)


def render_resolved_chart(
    resolved: ResolvedChart,
    render_data: ChartRenderData,
    resolved_style: ResolvedStyle,
    *,
    width: float | None = None,
    height: float | None = None,
    is_placeholder: bool = False,
    datasets: dict[str | None, ChartRenderData] | None = None,
    padding: dict[str, int | float] | None = None,
) -> RenderArtifact:
    """Render an already-resolved chart to a RenderArtifact.

    Takes a data-resolved ResolvedChart (no re-resolve).  Two callers:
    (a) render_chart() — resolves and delegates here;
    (b) render_chart_item() — passes the tree's data-resolved chart straight in.

    Wave 1's render_svg_family dispatch + VL emit_chart→finalize_vl→
    hconcat/padding/title-overflow post-processing live here.

    Resolved pies carry the width used to finalize their data-aware layout;
    omission reuses it and a conflicting explicit width is rejected. Other
    families retain the theme-family fallback for callers without a slot.
    """
    if isinstance(resolved, ResolvedPieChart):
        if width is not None and width != resolved.resolution_width:
            raise RenderError.from_code(
                ERR_RESOLVED_PIE_WIDTH_MISMATCH,
                chart_id=resolved.id,
                resolved_width=resolved.resolution_width,
                render_width=width,
            )
        resolved_width = resolved.resolution_width
        if resolved.attached_table is not None:
            return _render_arc_attached_table(
                resolved,
                render_data,
                resolved_style,
                padding=padding,
            )
    else:
        from dbt_charts.core.compile.resolve import default_chart_width

        resolved_width = (
            width
            if width is not None
            else default_chart_width(resolved.chart_type, resolved_style.chart_defaults)
        )

    artifact = _render_vl_artifact(
        resolved,
        render_data,
        resolved_style,
        width=resolved_width,
        height=height,
        is_placeholder=is_placeholder,
        datasets=datasets,
        padding=padding,
    )
    if artifact.kind == "vega_spec" and isinstance(artifact.payload, dict):
        vl = _apply_data_table_strip(
            artifact.payload, resolved, resolved_style.chart_defaults, render_data
        )
        if vl is not None:
            artifact = RenderArtifact(kind="vega_spec", payload=vl)
            _trace_vl_spec(resolved.id, "v2", vl)
    return artifact


def _apply_data_table_strip(
    vl: dict[str, Any],
    resolved: ResolvedChart,
    charts_style: ResolvedChartDefaults,
    render_data: ChartRenderData,
) -> dict[str, Any] | None:
    """Attach the chart.data_table strip to a cartesian VL spec.

    Single call site for the validate → resolve-style → attach →
    reserve-padding sequence every VL-spec caller (board render,
    render_chart, generate_vega_lite_spec) must apply when the resolved
    chart carries a data_table. Returns None (no-op) for chart families the
    primitive doesn't support (pie/kpi/table/...) or charts without one.
    """
    if (
        not isinstance(resolved, _CartesianResolvedChartFields)
        or resolved.data_table is None
    ):
        return None
    size_target = vl["hconcat"][0] if "hconcat" in vl else vl
    if "padding" not in size_target:
        size_target["padding"] = {"left": 0, "right": 0, "top": 0, "bottom": 0}
    size_target, _ = apply_chart_data_table_post_pass(
        size_target,
        resolved,
        charts_style,
        render_data,
        None,
        resolved.chart_type,
    )
    if "hconcat" in vl:
        vl["hconcat"][0] = size_target
        # The strip's layers are pixel literals anchored to spec.height, and its
        # out-of-plot marks extend the scenegraph past that height (autosize:pad
        # on the concat child keeps them rather than shrinking the plot).
        # $df_target_height would have _correct_concat_overshoot shrink the pane
        # to absorb that excess, sliding the plot bottom out from under the
        # strip. Height fits the slot via a pre-shrunk re-render instead
        # (layout_sizing._correct_data_table_height), which re-bakes the literals.
        #
        # Width keeps its sentinel, and NOT because the pre-shrink covers it: for
        # a concat spec the converter has already equalized outer width against
        # render_inner_width, so layout_sizing's `if overhead > 0` width
        # pre-shrink never fires. The post-hoc pane shrink is the only width
        # fitter these specs get — dropping it would leave the overflow.
        vl.pop("$df_target_height", None)
        return vl
    return size_target


def generate_vega_lite_spec(
    chart: Chart,
    data: ChartRenderData,
    *,
    width: float | None = None,
    height: float | None = None,
    board_style: ResolvedStyle | None = None,
    chart_style_context: ChartStyleContext | None = None,
) -> dict[str, Any]:
    """Generate a Vega-Lite spec for charts that render as Vega-Lite.

    SVG-family charts (kpi, table, spark_bar, callout) have no Vega-Lite
    spec; callers that ask for one get ERR_VEGA_LITE_UNSUPPORTED_TYPE.

    This is a standalone chart-resolution entry point (no production caller
    threads it through the normal board-render pipeline — used by warning
    detectors, diagnostics, and tests): it runs ``resolve()`` itself, so it
    needs the board's ``ChartStyleContext`` alongside ``board_style``, not
    just the final ``ResolvedStyle``. ``board_style``/``chart_style_context``
    must be supplied together or not at all — both default to the bare
    theme's cascade when omitted.
    """
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve import preferred_chart_width, resolve
    from dbt_charts.core.compile.resolve.style.board import (
        resolve_chart_style_context,
        resolve_style,
    )

    if (board_style is None) != (chart_style_context is None):
        raise ValueError(
            "generate_vega_lite_spec requires board_style and chart_style_context "
            "together — pass both or neither."
        )
    style = board_style if board_style is not None else resolve_style(get_theme_style())
    context = (
        chart_style_context
        if chart_style_context is not None
        else resolve_chart_style_context(get_theme_style())
    )
    # resolve() dispatches on chart.type first and raises for unsupported/synthetic
    # types (arc, boxplot, errorbar) before any width math runs. preferred_chart_width
    # indexes _FAMILY_SLOT by chart.type and KeyErrors on those same types, so it must
    # only run after resolve() has confirmed the type is a real, authorable family.
    resolved = resolve(chart, data, chart_style_context=context, width=width)
    resolved_width = (
        resolved.resolution_width
        if isinstance(resolved, ResolvedPieChart)
        else width
        if width is not None
        else preferred_chart_width(chart, context)
    )
    # The resolved chart already carries its final chart-local presentation
    # values (background, title_style) baked in at resolve() — no second
    # style decision here. style is the unchanged board-level style.
    artifact = _render_vl_artifact(
        resolved,
        data,
        style,
        width=resolved_width,
        height=height,
        is_placeholder=False,
        datasets=None,
        padding=None,
    )
    if artifact.kind == "svg":
        raise RenderError.from_code(
            ERR_VEGA_LITE_UNSUPPORTED_TYPE, chart_type=chart.type
        )
    assert isinstance(artifact.payload, dict)
    vl = _apply_data_table_strip(artifact.payload, resolved, style.chart_defaults, data)
    result = vl if vl is not None else artifact.payload
    # $df_title_style is an internal hand-off to render_vega_spec's deferred
    # hconcat title wrap (converters/chart.py) — this entry point returns the
    # spec directly without going through that conversion, and the sentinel
    # holds a non-JSON-serializable TitleStyle object, so it must not leak
    # into the public return value.
    result.pop("$df_title_style", None)
    return result


def render_chart(
    chart: Chart,
    resolved_style: ResolvedStyle,
    chart_style_context: ChartStyleContext,
    data: list[dict[str, Any]],
    format: str = "json",
    width: float | None = None,
    height: float | None = None,
    is_placeholder: bool = False,
    datasets: dict[str | None, list[dict[str, Any]]] | None = None,
    padding: dict[str, Any] | None = None,
) -> str:
    """Render a chart to JSON, SVG, PNG, or PDF."""
    if format == "json":
        artifact: RenderArtifact = RenderArtifact(
            kind="json",
            payload=build_dataface_json(chart, data, width=width, height=height),
        )
        return render_chart_artifact(
            artifact,
            format,
            resolved_style,
            width=width,
            height=height,
            is_placeholder=is_placeholder,
            chart_id=chart.id,
        )

    render_data: ChartRenderData = data
    if is_placeholder and not data:
        from dbt_charts.core.render.placeholder import generate_placeholder_data

        render_data = generate_placeholder_data(chart.type, chart)

    from dbt_charts.core.compile.resolve import preferred_chart_width, resolve

    # This is the entry point's one width resolution: an omitted width falls
    # back to the chart's authored width. Every downstream call (resolve,
    # render_resolved_chart, render_chart_artifact) gets the concrete result.
    resolved_width = (
        width
        if width is not None
        else preferred_chart_width(chart, chart_style_context)
    )
    resolved = resolve(
        chart,
        render_data,
        chart_style_context=chart_style_context,
        width=resolved_width,
        datasets=(
            ...
            if datasets is None
            else {name: rows for name, rows in datasets.items() if name is not None}
        ),
    )
    artifact = render_resolved_chart(
        resolved,
        render_data,
        resolved_style,
        width=resolved_width,
        height=height,
        is_placeholder=is_placeholder,
        datasets=datasets or None,
        padding=padding,
    )
    # Data_table strip (when the resolved chart has one) is applied inside
    # render_resolved_chart — the single call site every VL-spec caller
    # (board render, this function, generate_vega_lite_spec) shares.
    return render_chart_artifact(
        artifact,
        format,
        resolved_style,
        width=resolved_width,
        height=height,
        chart_id=resolved.id,
        is_placeholder=is_placeholder,
    )
