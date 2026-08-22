"""Regression: streamgraph (area, stack: center) places labels at final-x
band midpoints instead of skipping the endpoint-label pane.

Endpoint-label anchor computation for stacked charts uses the cumulative
(0..sum) domain; stack: center is diverging, so a prior fix made the feature
skip center-stack area entirely rather than mislabel it — the only way to
render a streamgraph WITH direct labels was to fall back to a legend. This
extends the stack-aware anchor math with Vega-Lite's own center-offset
formula: each column is shifted by ``(max_column_total - this_column_total)
/ 2`` (NOT a per-column ``-total/2`` silhouette, which is the wrong formula
and was caught by cross-checking against Vega's own compiled scenegraph
output via vl-convert) — so the rendered domain is ``[0, max_column_total]``,
the same as a plain zero-stack, not symmetric around zero.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.style.authored import EndpointLabelsConfig
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

# Three x-points so the max-column-total (Feb) is NOT the last x (Mar) —
# this makes the center-offset genuinely non-zero and distinguishes the
# correct (max_total - total_last)/2 formula from the wrong -total_last/2
# one (which happened to coincide with a 2-point fixture where the last x
# was also the max column). Series magnitude also flips between x points
# (Zeta > Alpha in Jan/Feb, Alpha > Zeta in Mar) so a naive "biggest series
# at bottom" heuristic would put a different series at the baseline than
# Vega-Lite's own NATIVE_STACK_ORDER (descending string sort) does.
_WIGGLY_DATA = [
    {"date": "2024-01-01", "value": 10, "series": "Alpha"},
    {"date": "2024-01-01", "value": 20, "series": "Zeta"},
    {"date": "2024-02-01", "value": 60, "series": "Alpha"},
    {"date": "2024-02-01", "value": 40, "series": "Zeta"},
    {"date": "2024-03-01", "value": 50, "series": "Alpha"},
    {"date": "2024-03-01", "value": 10, "series": "Zeta"},
]


def _resolved_streamgraph(make_chart, model_copy_at):
    chart = make_chart("area", x="date", y="value", color="series", stack="center")
    seed = model_copy_at(
        get_theme_style(),
        "charts.area.endpoint_labels",
        EndpointLabelsConfig(visible=True, label_offset=6.0, height=20.0),
    )
    rs, ctx = resolve_style_and_context(seed)
    return resolve(chart, _WIGGLY_DATA, chart_style_context=ctx), rs


def test_streamgraph_renders_without_raising(make_chart, model_copy_at):
    """Center-stack area with endpoint_labels.visible=True must not raise."""
    resolved, board_style = _resolved_streamgraph(make_chart, model_copy_at)
    artifact = render_resolved_chart(resolved, _WIGGLY_DATA, board_style, width=400)
    assert artifact.kind == "vega_spec"


def test_streamgraph_emits_endpoint_label_pane(make_chart, model_copy_at):
    """Center-stack area now wraps in the same hconcat endpoint-label pane
    every other stack mode uses — no more silent skip."""
    resolved, board_style = _resolved_streamgraph(make_chart, model_copy_at)
    artifact = render_resolved_chart(resolved, _WIGGLY_DATA, board_style, width=400)
    spec = artifact.payload
    assert "hconcat" in spec, (
        "Center-stack area must wrap in an endpoint-label hconcat pane; "
        f"got top-level keys {list(spec.keys())}"
    )


def test_streamgraph_labels_anchor_at_center_offset_midpoints_in_native_stack_order(
    make_chart, model_copy_at
):
    """Labels land at the final-x band midpoints, offset by Vega-Lite's own
    center-offset formula ``(max_column_total - this_column_total) / 2``,
    with series in NATIVE_STACK_ORDER (descending string sort) — not by
    data-encounter order or by magnitude.

    Final x (2024-03-01): Alpha=50, Zeta=10, total=60. Max column total
    across all x is 100 (2024-02-01), so offset = (100-60)/2 = 20. Native
    order puts Zeta (alphabetically last) at the baseline despite being the
    SMALLER value at this x — pinning that the anchor tracks stack order,
    not size.
      Zeta:  0..10  -> midpoint 5,  offset: 5 + 20 = 25
      Alpha: 10..60 -> midpoint 35, offset: 35 + 20 = 55

    Independently verified against Vega-Lite's own compiled scenegraph
    output (vl-convert) for this exact fixture — the band midpoints it
    actually renders land at pixel-identical positions to these labels.
    """
    resolved, board_style = _resolved_streamgraph(make_chart, model_copy_at)
    artifact = render_resolved_chart(resolved, _WIGGLY_DATA, board_style, width=400)
    spec = artifact.payload
    label_pane = spec["hconcat"][1]
    rows = label_pane["data"]["values"]
    by_series = {row["series"]: row["__y"] for row in rows}
    assert by_series == {"Zeta": 25.0, "Alpha": 55.0}


def test_streamgraph_pins_pane0_y_domain_to_stacked_extent(make_chart, model_copy_at):
    """Pane[0]'s y-scale domain is pinned to [0, max_column_total] — the
    same domain a plain zero-stack renders on, NOT a domain symmetric
    around zero. Vega-Lite's center-offset floats each column up toward
    that shared ceiling rather than self-centering each column
    independently. Max column total across all x is 100 (2024-02-01).
    """
    resolved, board_style = _resolved_streamgraph(make_chart, model_copy_at)
    artifact = render_resolved_chart(resolved, _WIGGLY_DATA, board_style, width=400)
    spec = artifact.payload
    pane0 = spec["hconcat"][0]
    y_scale = pane0["encoding"]["y"].get("scale", {})
    assert y_scale.get("domain") == [0.0, 100.0]


def test_zero_stack_endpoint_labels_still_wrap(make_chart, model_copy_at):
    """Sanity check: stack='zero' endpoint-label behavior is unchanged by the fix."""
    chart = make_chart("area", x="date", y="value", color="series", stack="zero")
    seed = model_copy_at(
        get_theme_style(),
        "charts.area.endpoint_labels",
        EndpointLabelsConfig(visible=True, label_offset=6.0, height=20.0),
    )
    rs, ctx = resolve_style_and_context(seed)
    resolved = resolve(chart, _WIGGLY_DATA, chart_style_context=ctx)
    artifact = render_resolved_chart(resolved, _WIGGLY_DATA, rs, width=400)
    spec = artifact.payload
    assert "hconcat" in spec
