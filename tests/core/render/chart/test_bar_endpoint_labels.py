"""TDD tests for the endpoint-labels primitive on the bar family.

Mirrors the line/area implementation: a multi-series column chart with
``style.bar.endpoint_labels.visible: true`` emits an ``hconcat`` with the
chart pane on the left and a series-label pane on the right. Anchor
computation is per-family:

- Stacked column (stack mode None / "zero"): segment midpoint of each
  series in the rightmost x column.
- 100% stacked (stack mode "normalize"): segment midpoint expressed on
  the 0..1 normalized scale.

Tests use synthetic data so the expected anchor y values are computable
by hand without pinning any theme literals.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())


@pytest.fixture
def seed_with_bar_endpoint_labels(model_copy_at):
    """Resolved style with bar.endpoint_labels override applied.

    Seeds from `stark` rather than the configured default so the legend tests
    in this file observe the cascade-default legend dict (the shipped editorial
    `default` theme sets legend.disable=true, which would mask the legend the
    no-wrap regression test is checking for).
    """
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.models.style.authored import EndpointLabelsConfig
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    def _build(enabled: bool, label_offset: float = 5.0):
        seed = model_copy_at(
            get_theme_style("stark"),
            "charts.bar.endpoint_labels",
            EndpointLabelsConfig(
                visible=enabled, label_offset=label_offset, height=20.0
            ),
        )
        return resolve_chart_style_context(seed)

    return _build


@pytest.fixture
def resolve_bar_chart(make_chart, seed_with_bar_endpoint_labels):
    """Resolved bar chart with endpoint_labels enabled and optional stack."""

    def _build(
        data: list[dict[str, Any]],
        enabled: bool,
        color: str | None = "series",
        stack: Any = "zero",
        author_asked: bool = False,
    ):
        kwargs: dict[str, Any] = {}
        if color is not None:
            kwargs["color"] = color
        if stack is not None:
            kwargs["stack"] = stack
        if author_asked:
            # The chart's own patch, not the board seed: only this outranks the
            # shape-based disqualifiers in _bar_endpoint_labels_for_stack.
            kwargs["style"] = {"endpoint_labels": {"visible": True}}
        chart = make_chart("bar", x="date", y="value", **kwargs)
        board_style = seed_with_bar_endpoint_labels(enabled)
        rc = resolve(chart, data, chart_style_context=board_style)
        return rc

    return _build


def _multi_series_stacked_data() -> list[dict[str, Any]]:
    """Two-series, two-x dataset where the trailing-x segment midpoints are
    obvious by hand.

    Trailing x = 2024-02-01:
      A = 40, B = 60 → total 100.
      _apply_stacked_bar_z_order default (value ordering): largest series at
      baseline. B (60) at bottom, A (40) on top:
        B at bottom: 0..60   → midpoint 30
        A on top:   60..100  → midpoint 80
      Normalize midpoints: B=0.30, A=0.80.
    """
    return [
        {"date": "2024-01-01", "value": 30, "series": "A"},
        {"date": "2024-01-01", "value": 50, "series": "B"},
        {"date": "2024-02-01", "value": 40, "series": "A"},
        {"date": "2024-02-01", "value": 60, "series": "B"},
    ]


def _single_series_data() -> list[dict[str, Any]]:
    return [
        {"date": "2024-01-01", "value": 30},
        {"date": "2024-02-01", "value": 50},
    ]


def _render(rc, data: list[dict[str, Any]]) -> dict[str, Any]:
    artifact = render_resolved_chart(rc, data, _BOARD_STYLE, width=400)
    assert artifact.kind == "vega_spec"
    return artifact.payload


# ---------------------------------------------------------------------------
# Schema cascade
# ---------------------------------------------------------------------------


def test_all_themes_compile_with_bar_endpoint_labels_field(compiled_themes):
    """Every production theme must compile and resolve with bar.endpoint_labels populated."""
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    for _, style in compiled_themes.items():
        ctx = resolve_chart_style_context(style)
        cfg = ctx.bar.endpoint_labels
        assert cfg is not None
        # Field is present and typed; we don't pin theme literal values.
        assert isinstance(cfg.visible, bool)
        assert isinstance(cfg.label_offset, float)


# ---------------------------------------------------------------------------
# Wrap gate
# ---------------------------------------------------------------------------


def test_bar_endpoint_labels_emits_hconcat_for_stacked(resolve_bar_chart):
    rc = resolve_bar_chart(data=_multi_series_stacked_data(), enabled=True)
    spec = _render(rc, _multi_series_stacked_data())
    assert "hconcat" in spec, f"Expected hconcat top-level key, got keys {list(spec)}"
    assert len(spec["hconcat"]) == 2, "Expected 2 panes: chart + label pane"
    assert spec.get("resolve", {}).get("scale", {}).get("color") == "independent"
    assert spec.get("resolve", {}).get("scale", {}).get("y") == "shared"


def test_bar_endpoint_labels_disabled_no_wrap(resolve_bar_chart):
    rc = resolve_bar_chart(data=_multi_series_stacked_data(), enabled=False)
    spec = _render(rc, _multi_series_stacked_data())
    assert "hconcat" not in spec


def test_bar_endpoint_labels_single_series_no_wrap(resolve_bar_chart):
    """Single-series bar (no color encoding) → no hconcat even if enabled.

    The wrap gate is multi-series only — the dark-companion palette pairing
    has no meaning when there is only one series colour.
    """
    rc = resolve_bar_chart(data=_single_series_data(), enabled=True, color=None)
    spec = _render(rc, _single_series_data())
    assert "hconcat" not in spec


# ---------------------------------------------------------------------------
# Anchor computation
# ---------------------------------------------------------------------------


def _label_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    pane = spec["hconcat"][1]
    return pane["data"]["values"]


def test_stacked_anchors_are_segment_midpoints(resolve_bar_chart):
    """Stacked column (stack='zero'): each label sits at its segment midpoint."""
    data = _multi_series_stacked_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Trailing x: A=40, B=60. Value ordering (B larger, at baseline):
    # B midpoint 30, A midpoint 80. Domain is wide ([0, 100]); cluster
    # spans the centre, so the cascade leaves anchors untouched
    # (gap 50 ≫ min_data_gap derived from font size).
    assert by_series == {"B": 30.0, "A": 80.0}


def test_normalize_anchors_on_unit_scale(resolve_bar_chart):
    """Stacked normalize ('normalize'): midpoints are shares of the column total."""
    data = _multi_series_stacked_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="normalize")
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Value ordering: B (60, larger) at baseline, A (40) on top.
    # Normalized midpoints: B=0.30, A=0.80.
    assert by_series["B"] == 0.30
    assert by_series["A"] == 0.80


def test_grouped_anchors_at_bar_tops(resolve_bar_chart):
    """Grouped/overlapping (stack: none): anchor = each series' value at last x.

    Grouped is not the default labelling shape — the author asked for it here.
    """
    data = _multi_series_stacked_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="none", author_asked=True)
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Last x: A=40, B=60 → labels sit at the bar tops.
    assert by_series == {"A": 40.0, "B": 60.0}


def _series_missing_from_final_column_data() -> list[dict[str, Any]]:
    """Three series where C has no row at the trailing x.

    Global sums: B=110, C=60, A=50 → value ordering stacks B, C, A from the
    baseline up, putting the absent series in the middle of the stack.

    Trailing x = 2024-02-01: B=60, A=40, C absent.
      B at baseline: 0..60   → midpoint 30
      C zero-height: 60..60  → seam at 60
      A on top:      60..100 → midpoint 80
    Column totals are 120 (Jan) and 100 (Feb), so the cascade domain is
    [0, 120] and the ≥20 anchor gaps clear the collision threshold untouched.
    """
    return [
        {"date": "2024-01-01", "value": 10, "series": "A"},
        {"date": "2024-01-01", "value": 50, "series": "B"},
        {"date": "2024-01-01", "value": 60, "series": "C"},
        {"date": "2024-02-01", "value": 40, "series": "A"},
        {"date": "2024-02-01", "value": 60, "series": "B"},
    ]


def test_stacked_labels_name_series_absent_from_final_column(resolve_bar_chart) -> None:
    """A series with no value in the trailing column still gets named.

    The rail replaces the color legend, so dropping the label would leave C
    painting segments in earlier columns under no name anywhere on the chart.
    """
    data = _series_missing_from_final_column_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)

    rows = _label_rows(spec)
    assert {r["series"] for r in rows} == {"A", "B", "C"}, (
        f"Rail must name every series in the chart exactly once, got "
        f"{[r['series'] for r in rows]!r}"
    )


def test_absent_series_anchors_at_its_zero_height_stack_seam(resolve_bar_chart) -> None:
    """The absent series anchors where its band would start, not at a neighbour.

    C is zero-height in the trailing column, so its seam is the boundary
    between B (below) and A (above) — 60 on a [0, 120] domain.
    """
    data = _series_missing_from_final_column_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    assert by_series == {"B": 30.0, "C": 60.0, "A": 80.0}


def test_grouped_by_default_anchors_at_bar_top(resolve_bar_chart):
    """stack=None + color (grouped-by-default): anchors at each bar's own value."""
    data = _multi_series_stacked_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack=None, author_asked=True)
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Grouped: each bar anchors at its own value (40 for A, 60 for B in the rightmost col)
    assert by_series == {"A": 40.0, "B": 60.0}


def test_negative_values_allowed_for_grouped(resolve_bar_chart):
    """For grouped bars (stack: none) negative values are fine: the bar
    dips below zero and the anchor sits at the bar's tip.

    Only the stacked cumulative midpoint breaks across zero, so the raise that
    disqualifies the stacked case has nothing to say here.
    """
    data = [
        {"date": "2024-01-01", "value": 10, "series": "A"},
        {"date": "2024-01-01", "value": -20, "series": "B"},
    ]
    rc = resolve_bar_chart(data=data, enabled=True, stack="none", author_asked=True)
    spec = _render(rc, data)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Anchors at the bar tops (values themselves), no exception raised.
    assert by_series == {"A": 10.0, "B": -20.0}


def test_explicit_stack_zero_anchors_at_segment_midpoints(resolve_bar_chart):
    """stack=zero: anchors at segment midpoints (stacked-bar layout)."""
    data = _multi_series_stacked_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Value ordering: B (60) at baseline, A (40) on top.
    assert by_series == {"B": 30.0, "A": 80.0}


# ---------------------------------------------------------------------------
# Label-pane structure (mirrors the line/area shape)
# ---------------------------------------------------------------------------


def test_label_pane_text_is_series_name(resolve_bar_chart):
    data = _multi_series_stacked_data()
    rc = resolve_bar_chart(data=data, enabled=True)
    spec = _render(rc, data)
    pane = spec["hconcat"][1]
    assert pane["mark"]["type"] == "text"
    assert pane["mark"]["align"] == "left"
    assert pane["encoding"]["text"]["field"] == "series"


def test_horizontal_bar_does_not_emit_hconcat_label_pane(
    make_chart, seed_with_bar_endpoint_labels
):
    """Horizontal bars never emit the right-side hconcat label pane.

    Stacked horizontal bars get the *top-row series rail* (vconcat) covered
    in test_horizontal_bar_endpoint_labels.py; this test pins the
    asymmetry — no horizontal variant gets the hconcat per-segment side
    labels that vertical stacks use.
    """
    from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

    data = [
        {"date": "2024-01-01", "value": 30, "series": "A"},
        {"date": "2024-01-01", "value": 50, "series": "B"},
    ]
    chart = make_chart(
        "bar",
        x="date",
        y="value",
        color="series",
        style=BarChartStylePatch.model_validate({"orientation": "horizontal"}),
    )
    board_style = seed_with_bar_endpoint_labels(enabled=True)
    rc = resolve(chart, data, chart_style_context=board_style)
    artifact = render_resolved_chart(rc, data, _BOARD_STYLE, width=400)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    assert "hconcat" not in spec, (
        "Horizontal bar must not emit hconcat (the right-side per-segment "
        "label pane is the vertical-stacked variant); horizontal variant "
        "uses vconcat with a top-row rail instead."
    )


def _center_stack_data() -> list[dict[str, Any]]:
    """Three x-points whose max column total (Feb, 100) is NOT the last x.

    Mirrors the streamgraph fixture so the center offset at the trailing x is
    genuinely non-zero: Mar totals 60, so every band floats up by
    ``(100 - 60) / 2 = 20``.
    """
    return [
        {"date": "2024-01-01", "value": 10, "series": "Alpha"},
        {"date": "2024-01-01", "value": 20, "series": "Zeta"},
        {"date": "2024-02-01", "value": 60, "series": "Alpha"},
        {"date": "2024-02-01", "value": 40, "series": "Zeta"},
        {"date": "2024-03-01", "value": 50, "series": "Alpha"},
        {"date": "2024-03-01", "value": 10, "series": "Zeta"},
    ]


def test_center_stack_anchors_at_center_offset_midpoints(resolve_bar_chart):
    """Center-stack vertical bar wraps in the same hconcat label pane every
    other stack mode uses, anchored at the offset segment midpoints.

    Trailing x (2024-03-01): Alpha=50, Zeta=10, total 60. Value ordering puts
    Alpha (larger) at the baseline. Vega-Lite floats the column up by
    ``(max_column_total - this_column_total) / 2 = (100 - 60) / 2 = 20``:
      Alpha: 0..50  -> midpoint 25, offset -> 45
      Zeta:  50..60 -> midpoint 55, offset -> 75
    """
    data = _center_stack_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="center")
    spec = _render(rc, data)
    assert "hconcat" in spec, (
        "Center-stack bar must wrap in an endpoint-label hconcat pane; "
        f"got top-level keys {list(spec)}"
    )
    by_series = {r["series"]: r["__y"] for r in _label_rows(spec)}
    assert by_series == {"Alpha": 45.0, "Zeta": 75.0}


def test_center_stack_renders_svg_naming_every_series(resolve_bar_chart):
    """The wrapped center-stack bar survives the real SVG path.

    Spec emission alone is not proof: the hconcat two-pass width correction
    runs only inside ``render_vega_spec``, and the bug this pins produced an
    empty-message ``AssertionError`` there while ``--format json`` (which
    never emits a chart spec) stayed green.
    """
    from dbt_charts.core.render.converters.chart import render_vega_spec

    data = _center_stack_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="center")
    artifact = render_resolved_chart(rc, data, _BOARD_STYLE, width=400)
    assert "hconcat" in artifact.payload
    svg = render_vega_spec(
        artifact.payload,
        "svg",
        _BOARD_STYLE,
        width=400.0,
        height=None,
        is_placeholder=False,
        chart_id="chart",
    )
    for series in ("Alpha", "Zeta"):
        assert series in svg, f"Series {series!r} missing from rendered SVG"


def test_negative_values_auto_disable_endpoint_labels(resolve_bar_chart):
    """Negative values in a stacked column would put VL's stacked domain
    across both signs and break the cumulative-midpoint computation — the
    render layer still raises if it ever sees this combination (defence in
    depth for a direct, non-default construction), but the resolve-time
    default now steers away from it first: same auto-disable treatment as
    stack: center above, and the chart still renders."""
    data = [
        {"date": "2024-01-01", "value": 10, "series": "A"},
        {"date": "2024-01-01", "value": -20, "series": "B"},
    ]
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    assert "hconcat" not in spec, (
        "Negative-value stacked bar must not wrap in an endpoint-label hconcat pane"
    )


def test_alphabetical_stack_order_independent_of_data_row_order(resolve_bar_chart):
    """Stacked-bar anchors must depend only on series → value mapping at
    the trailing x, not on the order rows arrive in. _apply_stacked_bar_z_order
    defaults to value ordering (largest series at baseline); the resolver must
    mirror that regardless of input shuffle."""
    forward = [
        {"date": "2024-01-01", "value": 30, "series": "A"},
        {"date": "2024-01-01", "value": 50, "series": "B"},
        {"date": "2024-02-01", "value": 40, "series": "A"},
        {"date": "2024-02-01", "value": 60, "series": "B"},
    ]
    reversed_rows = list(reversed(forward))

    rc_fwd = resolve_bar_chart(data=forward, enabled=True, stack="zero")
    rc_rev = resolve_bar_chart(data=reversed_rows, enabled=True, stack="zero")
    rows_fwd = _label_rows(_render(rc_fwd, forward))
    rows_rev = _label_rows(_render(rc_rev, reversed_rows))

    by_series_fwd = {r["series"]: r["__y"] for r in rows_fwd}
    by_series_rev = {r["series"]: r["__y"] for r in rows_rev}
    # Value ordering: B (60, larger) at baseline (mid 30), A (40) on top (mid 80).
    assert by_series_fwd == {"B": 30.0, "A": 80.0}
    assert by_series_fwd == by_series_rev


def test_cascade_nudges_clustered_anchors(resolve_bar_chart):
    """When two series' segment midpoints sit closer than ``min_data_gap``,
    the shared cascade pushes them apart — pins the bar resolver to the
    same collision-avoidance contract the line/area resolver upholds.

    The cascade now runs post-probe, against the real rendered plot geometry
    (``recascade_endpoint_labels``) rather than at spec-build time — this
    renders through the full pipeline (``render_vega_spec``), not just
    ``render_resolved_chart``, and reads the pane's own inline dataset after
    correction. Raw (pre-cascade) values still sit at the spec-build stage —
    see ``test_stacked_anchors_are_segment_midpoints`` for that contract.
    """
    from dbt_charts.core.render.converters.chart import render_vega_spec

    # Two tiny segments at the bottom of a much taller chart. Trailing-x
    # values A=2, B=4. Value ordering: B (larger) at baseline 0..4 → midpoint 2,
    # A on top 4..6 → midpoint 5. Raw separation = 3. The font-derived
    # min_data_gap on the chart's large effective y-domain (totals run up
    # to 1000) is much larger than the 3-unit raw gap, so the cascade must
    # push the labels further apart.
    data = [
        {"date": "2024-01-01", "value": 2, "series": "A"},
        {"date": "2024-01-01", "value": 4, "series": "B"},
        # A second x with a very tall total so the chart's effective y-domain
        # is large and the font-derived min_data_gap (in data units) clearly
        # exceeds the 3-unit raw separation between the trailing-x midpoints.
        {"date": "2023-12-01", "value": 500, "series": "A"},
        {"date": "2023-12-01", "value": 500, "series": "B"},
    ]
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    raw_rows = _label_rows(spec)
    raw_by_series = {r["series"]: r["__y"] for r in raw_rows}
    assert raw_by_series["A"] - raw_by_series["B"] == 3.0, (
        "Spec-build stage must still carry the raw, un-cascaded midpoints"
    )

    render_vega_spec(
        spec,
        "svg",
        _BOARD_STYLE,
        width=400,
        height=300,
        is_placeholder=False,
        chart_id="chart",
    )
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Value ordering: B at baseline, A on top. A_y > B_y.
    # Cascade pushed the labels apart by at least min_data_gap; the raw
    # midpoints (B=2, A=5) cannot both survive intact.
    assert (by_series["A"] - by_series["B"]) > 3.0, (
        "Expected the cascade to push the upper anchor (A, on top) further "
        f"from the lower (B, at baseline) than the raw 3-unit midpoint gap; "
        f"got {by_series!r}"
    )
    # And: still in descending-y order top-to-bottom.
    ys_in_pane_order = [r["__y"] for r in rows]
    assert ys_in_pane_order == sorted(ys_in_pane_order, reverse=True)


def test_label_pane_color_domain_alphabetical(resolve_bar_chart):
    """Label pane's color domain mirrors VL's default nominal sort so the
    dark-companion stops line up with the bar segments' colours."""
    data = [
        {"date": "2024-01-01", "value": 10, "series": "Zebra"},
        {"date": "2024-01-01", "value": 20, "series": "Apple"},
        {"date": "2024-02-01", "value": 30, "series": "Zebra"},
        {"date": "2024-02-01", "value": 40, "series": "Apple"},
    ]
    rc = resolve_bar_chart(data=data, enabled=True)
    spec = _render(rc, data)
    pane = spec["hconcat"][1]
    assert pane["encoding"]["color"]["scale"]["domain"] == ["Apple", "Zebra"]


# ---------------------------------------------------------------------------
# Wrap-time legend suppression and normalize y-domain pin
# ---------------------------------------------------------------------------


def test_wrap_disables_pane0_legend_when_endpoint_labels_enabled(resolve_bar_chart):
    """Auto-disable the categorical legend on pane[0] when wrapping.

    Direct labels and a side legend encode the same series→colour mapping;
    rendering both is double-encoding and the legend's overhang clips the
    label pane out of the canvas. Resolved in the endpoint-labels brief.
    """
    rc = resolve_bar_chart(data=_multi_series_stacked_data(), enabled=True)
    spec = _render(rc, _multi_series_stacked_data())
    pane0 = spec["hconcat"][0]
    assert pane0["encoding"]["color"]["legend"] is None, (
        "pane[0].encoding.color.legend must be None when endpoint labels wrap; "
        "the right-edge label pane already names every series."
    )


def test_no_wrap_leaves_legend_alone(resolve_bar_chart):
    """When endpoint_labels is disabled, the cascade-default legend survives.

    The auto-disable only fires inside the wrap helper. With endpoint_labels
    off, the cascade produces a legend dict (theme defaults: orient, label
    font, etc.) with ``disable`` unset or False — a regression that nulled
    the legend pre-wrap would be caught here.
    """
    rc = resolve_bar_chart(data=_multi_series_stacked_data(), enabled=False)
    spec = _render(rc, _multi_series_stacked_data())
    assert "hconcat" not in spec, (
        "Expected unwrapped chart when endpoint_labels disabled"
    )
    legend = spec.get("encoding", {}).get("color", {}).get("legend")
    assert isinstance(legend, dict), (
        f"Cascade should produce a legend dict when not wrapping, got {legend!r}"
    )
    assert legend.get("disable") in (
        None,
        False,
    ), (
        f"Cascade-default legend must not be disabled; got disable={legend.get('disable')!r}"
    )


def test_normalize_stack_pins_pane0_y_scale_domain_to_unit(resolve_bar_chart):
    """Stack normalize must pin pane[0].encoding.y.scale.domain = [0, 1].

    VL's auto-scale on the raw value field would yield [0, max(value)] and
    resolve.scale.y=shared then propagates that raw-domain scale to the
    label pane — squashing every label near zero on 100% stacks. The
    label-position resolver already works in [0, 1] for normalize, so
    pinning pane[0]'s scale to [0, 1] makes the shared scale agree with
    the label-pane domain.
    """
    rc = resolve_bar_chart(
        data=_multi_series_stacked_data(), enabled=True, stack="normalize"
    )
    spec = _render(rc, _multi_series_stacked_data())
    pane0 = spec["hconcat"][0]
    y_scale = pane0["encoding"]["y"].get("scale", {})
    assert y_scale.get("domain") == [0, 1], (
        f"Expected pane[0].encoding.y.scale.domain == [0, 1] for stack=normalize, "
        f"got {y_scale!r}"
    )


def test_zero_stack_does_not_pin_y_scale_domain(resolve_bar_chart):
    """Default (zero) stack must NOT inject a y-scale domain.

    For stack=zero the rendered y-domain is [0, max_total] and matches the
    auto-derived scale; pinning [0, 1] would shrink every bar to a fraction
    of the canvas. Only the normalize case needs the override.
    """
    rc = resolve_bar_chart(data=_multi_series_stacked_data(), enabled=True)
    spec = _render(rc, _multi_series_stacked_data())
    pane0 = spec["hconcat"][0]
    y_enc = pane0["encoding"]["y"]
    # Either no scale at all, or scale without an injected domain.
    domain = (
        y_enc.get("scale", {}).get("domain")
        if isinstance(y_enc.get("scale"), dict)
        else None
    )
    assert domain is None, (
        f"pane[0].encoding.y.scale.domain must NOT be pinned when stack != normalize; "
        f"got {domain!r}"
    )


def test_stack_order_matches_value_convention(resolve_bar_chart):
    """_apply_stacked_bar_z_order defaults to value ordering — largest aggregate
    sits at the baseline (bottom), smallest is at the top.

    Regression guard for the resolver's stack-order convention. This test pins
    which series actually sits at the top vs the bottom of the stack so a
    misaligned label-vs-segment pairing (the symptom: labels point at the wrong
    coloured segment) can't sneak past CI again.
    """
    # Three series with distinct values so segment positions are unambiguous.
    data = [
        {"date": "2024-01-01", "value": 10, "series": "Apple"},
        {"date": "2024-01-01", "value": 20, "series": "Banana"},
        {"date": "2024-01-01", "value": 30, "series": "Cherry"},
    ]
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # Value ordering (descending by aggregate): Cherry (30) at baseline, Banana
    # (20) in middle, Apple (10) on top.
    #   Cherry at bottom: 0..30   → midpoint 15
    #   Banana:           30..50  → midpoint 40
    #   Apple at top:     50..60  → midpoint 55
    assert by_series == {"Cherry": 15.0, "Banana": 40.0, "Apple": 55.0}, (
        f"Expected value-largest (Cherry) at BOTTOM and value-smallest (Apple) "
        f"at TOP per value-descending stack convention; "
        f"got {by_series!r}"
    )


def test_vertical_stacked_labels_follow_an_authored_sort(resolve_bar_chart):
    """The pane anchors on the last *rendered* column, not the lexicographic max.

    ``sort: {by: value, order: desc}`` puts the smallest-value column on the
    right, so that is the column whose segment midpoints the labels take.
    """
    from dbt_charts.core.compile.models.chart.authored import ChartSort

    data = _multi_series_stacked_data()
    rc = resolve_bar_chart(data=data, enabled=True, stack="zero", author_asked=True)
    rc = rc.model_copy(update={"sort": ChartSort(by="value", order="desc")})
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__y"] for r in rows}
    # min(value) per column: 2024-01 = 30, 2024-02 = 40. Descending puts
    # 2024-01 last, so its segments are the anchors: B=50 at the baseline
    # (0..50, mid 25) with A=30 on top (50..80, mid 65).
    assert by_series == {"A": 65.0, "B": 25.0}
