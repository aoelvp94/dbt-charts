"""TDD tests for the endpoint-labels primitive on horizontal stacked bars.

Vertical stacked bars get per-segment side labels (right-edge hconcat pane).
Horizontal stacked bars get a single label *rail* above the top categorical
row: one label per series, anchored to the segment x-midpoint within the
top row, with a vertical-dodge resolver to negotiate collisions when
adjacent labels would overlap.

Layout shape: ``vconcat`` of [labels-pane, chart-pane] with ``resolve.scale.x
= shared``. The labels pane carries one row per series; ``__x`` is
the chart-x at which the label centers, ``__dodge_row`` (0..MAX_DODGE)
lifts colliding labels above the base row.

Tests use synthetic data so the expected midpoints are computable by
hand without pinning theme literals.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE = resolve_style(get_theme_style())
_BOARD_CTX = resolve_chart_style_context(get_theme_style())

# Max __dodge_row tier for colliding rail labels (see module docstring).
_HORIZONTAL_LABEL_RAIL_MAX_DODGE = 3


@pytest.fixture
def seed_with_bar_endpoint_labels(model_copy_at):
    """Resolved style with bar.endpoint_labels override applied (seeded from stark)."""
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
def resolve_horizontal_bar_chart(make_chart, seed_with_bar_endpoint_labels):
    """Resolved horizontal bar chart with endpoint_labels enabled and optional stack."""
    from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

    def _build(
        data: list[dict[str, Any]],
        enabled: bool,
        color: str | None = "series",
        stack: Any = None,
        author_asked: bool = False,
    ):
        kwargs: dict[str, Any] = {}
        if color is not None:
            kwargs["color"] = color
        if stack is not None:
            kwargs["stack"] = stack
        style: dict[str, Any] = {"orientation": "horizontal"}
        if author_asked:
            # The default steers a ragged anchor row back to a legend (the rail
            # has no collision resolver); only the chart's own patch outranks it.
            style["endpoint_labels"] = {"visible": True}
        chart = make_chart(
            "bar",
            x="row",
            y="value",
            style=BarChartStylePatch.model_validate(style),
            **kwargs,
        )
        board_style = seed_with_bar_endpoint_labels(enabled)
        rc = resolve(chart, data, chart_style_context=board_style)
        return rc

    return _build


def _two_series_two_row_data() -> list[dict[str, Any]]:
    """Two categorical rows × two series. Top-row segments yield obvious midpoints.

    Alphabetical-first row = "alpha" → top of the chart. In the top row:
        A = 40, B = 60.
    Value ordering (_apply_stacked_bar_z_order default: largest at baseline):
        B at left  0..60   → midpoint 30
        A on right 60..100 → midpoint 80
    Normalize: B mid = 0.30, A mid = 0.80.
    """
    return [
        {"row": "alpha", "value": 40, "series": "A"},
        {"row": "alpha", "value": 60, "series": "B"},
        {"row": "beta", "value": 10, "series": "A"},
        {"row": "beta", "value": 90, "series": "B"},
    ]


def _render(rc, data: list[dict[str, Any]], width: float = 400.0) -> dict[str, Any]:
    artifact = render_resolved_chart(rc, data, _BOARD_STYLE, width=width)
    assert artifact.kind == "vega_spec"
    return artifact.payload


# ---------------------------------------------------------------------------
# Wrap gate
# ---------------------------------------------------------------------------


def test_horizontal_stacked_emits_vconcat(resolve_horizontal_bar_chart):
    """Stacked horizontal + endpoint_labels.visible → vconcat with labels on top."""
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    assert "vconcat" in spec, f"Expected vconcat top-level key, got keys {list(spec)}"
    assert len(spec["vconcat"]) == 2, (
        "Expected 2 panes: labels pane (top) + chart pane (bottom)"
    )
    assert spec.get("resolve", {}).get("scale", {}).get("x") == "shared"
    assert spec.get("resolve", {}).get("scale", {}).get("color") == "independent"


def test_horizontal_stacked_disabled_no_wrap(resolve_horizontal_bar_chart):
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=False, stack="zero")
    spec = _render(rc, data)
    assert "vconcat" not in spec
    assert "hconcat" not in spec


def test_horizontal_stacked_explicit_zero_fires(resolve_horizontal_bar_chart):
    """Explicit stack=zero on a multi-series horizontal bar → rail fires."""
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    assert "vconcat" in spec


def test_horizontal_grouped_by_default_does_not_fire(resolve_horizontal_bar_chart):
    """stack=None + color (grouped-by-default) → no rail (bars don't stack)."""
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack=None)
    spec = _render(rc, data)
    assert "vconcat" not in spec
    assert "hconcat" not in spec


def test_horizontal_grouped_does_not_fire(resolve_horizontal_bar_chart):
    """Grouped horizontal (stack: none) does not fire — the rail is for stacks only.

    The whole point of the top-row series rail is to direct-label color segments
    *within a single row*. Grouped bars share the row instead of stacking inside
    it; the right-side measure tip is a different placement primitive.
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="none")
    spec = _render(rc, data)
    assert "vconcat" not in spec
    assert "hconcat" not in spec


def test_horizontal_single_series_does_not_fire(resolve_horizontal_bar_chart):
    """Single-series horizontal bar (no color encoding) → no wrap.

    Same multi-series gate as the vertical variant: the rail names color
    segments, and a single-series chart has no segments to name.
    """
    data = [
        {"row": "alpha", "value": 40},
        {"row": "beta", "value": 10},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, color=None, stack="zero")
    spec = _render(rc, data)
    assert "vconcat" not in spec
    assert "hconcat" not in spec


# ---------------------------------------------------------------------------
# Anchor: top-row only, segment midpoints
# ---------------------------------------------------------------------------


def _label_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    pane = spec["vconcat"][0]
    return pane["data"]["values"]


def test_label_rail_emits_one_entry_per_series(resolve_horizontal_bar_chart):
    """One label per color value — not per (row, color) data point.

    Pins the top-row-only contract: the rail names every series exactly once,
    not once per categorical row.
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    rows = _label_rows(spec)
    series_in_rail = {r["series"] for r in rows}
    assert series_in_rail == {"A", "B"}
    assert len(rows) == 2


def test_label_rail_anchors_at_top_row_segment_midpoints(resolve_horizontal_bar_chart):
    """``__x`` for each series = cumulative segment midpoint within TOP ROW only.

    Top row is the alphabetical-first y-domain value ("alpha"). In that row
    A=40, B=60; value ordering puts B (larger) at baseline 0..60 → mid 30,
    A on top 60..100 → mid 80. Bottom row ("beta") values must NOT influence
    the rail.
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__x"] for r in rows}
    assert by_series == {"B": 30.0, "A": 80.0}, (
        f"Expected top-row midpoints B=30, A=80 (value ordering puts B at baseline), "
        f"got {by_series!r}. If a different row's data leaked in, the top-row filter "
        f"is broken."
    )


def _series_missing_from_top_row_data() -> list[dict[str, Any]]:
    """Three series where C has no segment in the top row ("alpha").

    Global sums: B=150, C=60, A=50 → value ordering stacks B, C, A from the
    baseline out, putting the absent series mid-stack.

    Top row: B=60 → 0..60 midpoint 30; C zero-width → seam at 60;
    A=40 → 60..100 midpoint 80.
    """
    return [
        {"row": "alpha", "value": 40, "series": "A"},
        {"row": "alpha", "value": 60, "series": "B"},
        {"row": "beta", "value": 10, "series": "A"},
        {"row": "beta", "value": 90, "series": "B"},
        {"row": "beta", "value": 60, "series": "C"},
    ]


def test_rail_names_series_absent_from_top_row(resolve_horizontal_bar_chart) -> None:
    """Under an explicit opt-in, a series absent from the top row still gets an entry.

    The seam math is the same as the vertical path's and stays correct; it is
    only the *default* that steers away, because this rail cannot yet dodge
    colliding labels. An author who asks for it must not lose a name.
    """
    data = _series_missing_from_top_row_data()
    rc = resolve_horizontal_bar_chart(
        data=data, enabled=True, stack="zero", author_asked=True
    )
    spec = _render(rc, data)
    rows = _label_rows(spec)
    assert {r["series"] for r in rows} == {"A", "B", "C"}, (
        f"Rail must name every series in the chart exactly once, got "
        f"{[r['series'] for r in rows]!r}"
    )


def test_absent_series_anchors_at_its_zero_width_stack_seam(
    resolve_horizontal_bar_chart,
) -> None:
    """The absent series anchors where its segment would start, not at a neighbour."""
    data = _series_missing_from_top_row_data()
    rc = resolve_horizontal_bar_chart(
        data=data, enabled=True, stack="zero", author_asked=True
    )
    spec = _render(rc, data)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__x"] for r in rows}
    assert by_series == {"B": 30.0, "C": 60.0, "A": 80.0}


def test_normalize_anchors_on_unit_scale(resolve_horizontal_bar_chart):
    """Stack normalize: midpoints are shares of the top row's total.

    A=40, B=60 in top row; value ordering: B (larger) at 0..0.60 → mid 0.30,
    A at 0.60..1.00 → mid 0.80.
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="normalize")
    spec = _render(rc, data)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__x"] for r in rows}
    assert by_series == {"B": 0.30, "A": 0.80}


def test_label_rail_color_domain_is_alphabetical(resolve_horizontal_bar_chart):
    """Pin the color encoding so dark-companion stops match the rendered segments."""
    data = [
        {"row": "alpha", "value": 30, "series": "Zebra"},
        {"row": "alpha", "value": 50, "series": "Apple"},
        {"row": "beta", "value": 10, "series": "Zebra"},
        {"row": "beta", "value": 20, "series": "Apple"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    pane = spec["vconcat"][0]
    assert pane["encoding"]["color"]["scale"]["domain"] == ["Apple", "Zebra"]


def test_label_rail_color_range_is_dark_companions(resolve_horizontal_bar_chart):
    """Pin the color *range* on the rail to the vivid-10-dark stops.

    The whole point of the ``_dark_companion_stops`` helper is that each
    label inks a notch darker than its segment for legibility — without
    this assertion a future refactor could silently swap the dark range
    for the bright one and the chart would still render, just with low-
    contrast labels.
    """
    from dbt_charts.core.compile.resolve.style.palette import palette as resolve_palette

    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    pane = spec["vconcat"][0]
    rail_range = pane["encoding"]["color"]["scale"]["range"]
    # Two distinct series → first two slots of the dark companion palette
    # (default cascade keeps the chart on vivid-10).
    assert rail_range == resolve_palette("vivid-10-dark")[: len(rail_range)]


def test_wrap_reduces_chart_pane_height_to_absorb_rail(resolve_horizontal_bar_chart):
    """The vconcat wrap helper must subtract the rail pane's footprint from the
    chart pane's height so the outer SVG fits the configured cell height.

    Mirrors the hconcat width-reduction strategy. Without this the rail
    would push the chart pane down and overflow the cell height.
    """

    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    artifact = render_resolved_chart(rc, data, _BOARD_STYLE, width=400, height=200)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    chart_pane = spec["vconcat"][1]
    rail_pane = spec["vconcat"][0]
    rail_height = float(rail_pane.get("height", 0) or 0)
    spacing = float(spec.get("spacing", 0) or 0)
    chart_height = float(chart_pane.get("height", 0) or 0)
    # Chart pane height was reduced to absorb the rail, so the total
    # stack (rail + spacing + chart) ≤ the configured 200px cell.
    assert chart_height + rail_height + spacing <= 200.0 + 0.5, (
        f"vconcat wrap should keep total height ≤ configured cell; got "
        f"chart={chart_height}, rail={rail_height}, spacing={spacing} "
        f"(total={chart_height + rail_height + spacing})"
    )


# ---------------------------------------------------------------------------
# Vertical dodge — leftmost stays at base, right-hand neighbor lifts
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="V2 gap: __dodge_row collision resolver not yet implemented in horizontal bar rail emitter"
)
def test_no_collision_all_labels_at_base_row(resolve_horizontal_bar_chart):
    """When top-row segments are wide and labels fit side-by-side, nothing dodges.

    Value ordering: B at midpoint 30, A at midpoint 80 on a 400-px chart with
    a [0, 100] x-domain → midpoints land ~120px and ~320px apart. Even with
    generous padding, two short labels ("A", "B") fit comfortably side-by-side
    with no collision; both stay at base (dodge_row=0).
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data, width=400.0)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__dodge_row"] for r in rows}
    assert by_series == {"A": 0, "B": 0}, (
        f"Expected both labels at base (dodge_row=0) when segments are wide, "
        f"got {by_series!r}"
    )


@pytest.mark.skip(
    reason="V2 gap: __dodge_row collision resolver not yet implemented in horizontal bar rail emitter"
)
def test_collision_right_hand_neighbor_dodges_up(resolve_horizontal_bar_chart):
    """When two adjacent labels overlap, the *right-hand* one lifts; left stays at 0.

    Two labels with long names ("LongLeftLabelName" and "LongRightLabelName")
    in a narrow chart force the bboxes to overlap — the resolver must lift the
    right-hand label and keep the left one at the base row.
    """
    data = [
        {"row": "alpha", "value": 6, "series": "LongLeftLabelName"},
        {"row": "alpha", "value": 14, "series": "LongRightLabelName"},
        {"row": "beta", "value": 1, "series": "LongLeftLabelName"},
        {"row": "beta", "value": 1, "series": "LongRightLabelName"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data, width=200.0)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__dodge_row"] for r in rows}
    # Value ordering: LongRightLabelName (14, larger) at left x=0..14 → mid 7;
    # LongLeftLabelName (6, smaller) on right x=14..20 → mid 17. Walking
    # left-to-right: LongRight at 7 lands first (dodge=0), LongLeft at 17
    # collides → dodge=1.
    assert by_series["LongRightLabelName"] == 0, (
        f"Leftmost label (LongRightLabelName at x=7) must stay at base; "
        f"got {by_series!r}"
    )
    assert by_series["LongLeftLabelName"] >= 1, (
        f"Right-hand label (LongLeftLabelName at x=17) must lift on collision; "
        f"got {by_series!r}"
    )


@pytest.mark.skip(
    reason="V2 gap: __dodge_row collision resolver not yet implemented in horizontal bar rail emitter"
)
def test_dodge_caps_and_accepts_overlap_deterministically(resolve_horizontal_bar_chart):
    """With many narrow segments, dodge caps at MAX_DODGE_ROWS — never raises.

    Five very wide labels in a tight chart force every right-hand label to
    collide with the left ones. The resolver must cap at the documented
    maximum and accept overlap deterministically (no exception).
    """
    data = []
    series_names = [f"VeryLongSeriesName_{c}" for c in "ABCDE"]
    for i, s in enumerate(series_names, start=1):
        data.append({"row": "alpha", "value": float(i), "series": s})
        data.append({"row": "beta", "value": 1.0, "series": s})
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    # Should not raise — we just want determinism.
    spec = _render(rc, data, width=200.0)
    rows = _label_rows(spec)
    dodge_rows = [r["__dodge_row"] for r in rows]
    # All dodge rows are in the documented range [0, MAX_DODGE].

    assert all(0 <= d <= _HORIZONTAL_LABEL_RAIL_MAX_DODGE for d in dodge_rows), (
        f"Dodge rows {dodge_rows!r} fell outside [0, {_HORIZONTAL_LABEL_RAIL_MAX_DODGE}]"
    )


@pytest.mark.skip(
    reason="V2 gap: __dodge_row collision resolver not yet implemented in horizontal bar rail emitter"
)
def test_leftmost_label_always_at_base_row(resolve_horizontal_bar_chart):
    """Across any input that triggers dodge, the leftmost label sits at row 0.

    Pins the resolver's determinism contract from the task spec.
    """
    data = []
    series_names = [f"WideLabel_{c}" for c in "ABCDE"]
    for i, s in enumerate(series_names, start=1):
        data.append({"row": "alpha", "value": float(i), "series": s})
        data.append({"row": "beta", "value": 1.0, "series": s})
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data, width=200.0)
    rows = _label_rows(spec)
    leftmost = min(rows, key=lambda r: r["__x"])
    assert leftmost["__dodge_row"] == 0, (
        f"Leftmost label {leftmost!r} must sit at base row; got dodge_row="
        f"{leftmost['__dodge_row']!r}. Resolver determinism contract violated."
    )


# ---------------------------------------------------------------------------
# Wrap-time legend suppression and normalize x-domain pin
# ---------------------------------------------------------------------------


def test_wrap_disables_pane1_legend(resolve_horizontal_bar_chart):
    """Auto-disable the categorical legend on the chart pane when wrapping.

    Mirrors the vertical/hconcat behavior: direct labels and a side legend
    encode the same series→colour mapping, and the rail is the direct label
    here, so the legend is suppressed.
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    chart_pane = spec["vconcat"][1]
    assert chart_pane["encoding"]["color"]["legend"] is None


def test_normalize_pins_chart_pane_x_scale_to_unit(resolve_horizontal_bar_chart):
    """``stack: normalize`` must pin the chart pane's x-scale to [0, 1].

    Without this pin VL's auto-scale on the raw value field would yield
    ``[0, max(value)]`` and ``resolve.scale.x = shared`` would propagate
    that raw-domain scale to the labels pane — so the labels (which work
    on a [0, 1] domain after normalize) would stack near zero.
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="normalize")
    spec = _render(rc, data)
    chart_pane = spec["vconcat"][1]
    x_scale = chart_pane["encoding"]["x"].get("scale", {})
    assert x_scale.get("domain") == [0, 1], (
        f"Expected chart-pane x-scale domain [0, 1] for stack=normalize, "
        f"got {x_scale!r}"
    )


def test_zero_stack_does_not_pin_x_scale_domain(resolve_horizontal_bar_chart):
    """Default (zero) stack must NOT inject an x-scale domain on the chart pane."""
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    chart_pane = spec["vconcat"][1]
    x_enc = chart_pane["encoding"]["x"]
    domain = (
        x_enc.get("scale", {}).get("domain")
        if isinstance(x_enc.get("scale"), dict)
        else None
    )
    assert domain is None, (
        f"chart-pane x-scale domain must NOT be pinned for stack=zero; got {domain!r}"
    )


# ---------------------------------------------------------------------------
# Label-pane structure
# ---------------------------------------------------------------------------


def test_label_pane_text_mark_is_centered(resolve_horizontal_bar_chart):
    """Each label centers horizontally on its segment midpoint."""
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    pane = spec["vconcat"][0]
    assert pane["mark"]["type"] == "text"
    # Horizontal centering on the segment midpoint is the whole point of
    # the rail; baseline puts the label above its anchor (closer to the
    # chart frame top, away from the bar).
    assert pane["mark"]["align"] == "center"
    assert pane["encoding"]["text"]["field"] == "series"


def test_center_stack_never_reaches_the_rail_s_refusal(resolve_horizontal_bar_chart):
    """The rail cannot anchor a centre stack, so resolve keeps charts away from it.

    The render-layer raise is still the contract for a ``ResolvedChart`` built
    directly with the combination; it is simply unreachable through resolve now
    that the labelling default disqualifies it.
    """
    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="center")

    assert rc.style.endpoint_labels.visible is False
    assert "vconcat" not in _render(rc, data)


def test_center_stack_still_raises_when_the_author_opts_in(
    resolve_horizontal_bar_chart,
):
    """The refusal above is the other half of that contract.

    Resolve steers the default away from a centre stack, but an explicit
    ``endpoint_labels.visible: true`` reaches render — and must meet the named
    conflict rather than a rail anchored on an axis the chart does not have.
    """
    import pytest

    from dbt_charts.core.diagnostics.chart_data import ChartDataError

    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    rc = rc.model_copy(update={"stack": "center"})
    with pytest.raises(ChartDataError, match="center"):
        _render(rc, data)


def test_negative_values_auto_disable_endpoint_labels_horizontal(
    resolve_horizontal_bar_chart,
):
    """Negative values in the top row break the cumulative-midpoint computation.

    The render layer still raises if it ever sees this combination (defence
    in depth for a direct, non-default construction), but the resolve-time
    default now steers away from it first — same auto-disable treatment as
    stack: center above, and the chart still renders."""
    data = [
        {"row": "alpha", "value": 10, "series": "A"},
        {"row": "alpha", "value": -20, "series": "B"},
        {"row": "beta", "value": 5, "series": "A"},
        {"row": "beta", "value": 5, "series": "B"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    assert "vconcat" not in spec, (
        "Negative-value stacked horizontal bar must not emit the top-row "
        "endpoint-label rail"
    )


def test_negative_values_still_raise_when_the_author_opts_in(
    resolve_horizontal_bar_chart,
):
    """The other half of the auto-disable contract above: an explicit opt-in
    reaches render and meets the refusal by name.
    """
    from dbt_charts.core.diagnostics.chart_data import ChartDataError

    data = [
        {"row": "alpha", "value": 10, "series": "A"},
        {"row": "alpha", "value": -20, "series": "B"},
        {"row": "beta", "value": 5, "series": "A"},
        {"row": "beta", "value": 5, "series": "B"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    rc = rc.model_copy(
        update={
            "style": rc.style.model_copy(
                update={
                    "endpoint_labels": rc.style.endpoint_labels.model_copy(
                        update={"visible": True}
                    )
                }
            )
        }
    )
    with pytest.raises(ChartDataError, match="negative"):
        _render(rc, data)


def test_alphabetical_top_row_independent_of_data_order(resolve_horizontal_bar_chart):
    """Anchors must depend on series→value mapping at the alphabetical-first row,
    not on input row order."""
    forward = _two_series_two_row_data()
    reversed_rows = list(reversed(forward))

    rc_fwd = resolve_horizontal_bar_chart(data=forward, enabled=True, stack="zero")
    rc_rev = resolve_horizontal_bar_chart(
        data=reversed_rows, enabled=True, stack="zero"
    )
    rows_fwd = _label_rows(_render(rc_fwd, forward))
    rows_rev = _label_rows(_render(rc_rev, reversed_rows))
    by_fwd = {r["series"]: r["__x"] for r in rows_fwd}
    by_rev = {r["series"]: r["__x"] for r in rows_rev}
    # Value ordering: B (60) at baseline → mid 30, A (40) on top → mid 80.
    assert by_fwd == by_rev == {"B": 30.0, "A": 80.0}


# ---------------------------------------------------------------------------
# axis_y orient: horizontal endpoint labels do NOT flip axis_y
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Regression: color→segment mapping was inverted (follow-up to #2390)
# ---------------------------------------------------------------------------


def test_ascending_stack_order_new_solved_midpoints(resolve_horizontal_bar_chart):
    """Regression: label x-midpoints must match the actual rendered stack order.

    _apply_stacked_bar_z_order defaults to value ordering (largest series at
    baseline). The label rail must anchor in the same order.

    Row "a_top" is alphabetically first (the top bar). With new=18, solved=12:
    value ordering puts new (larger) at 0..18 → mid 9;
    solved at 18..30 → mid 24.
    """
    data = [
        {"row": "a_top", "value": 18, "series": "new"},
        {"row": "a_top", "value": 12, "series": "solved"},
        {"row": "b_bottom", "value": 5, "series": "new"},
        {"row": "b_bottom", "value": 8, "series": "solved"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__x"] for r in rows}
    assert by_series == {"new": 9.0, "solved": 24.0}, (
        f"Expected new=9 (mid of 0..18, largest at baseline) and solved=24 "
        f"(mid of 18..30); got {by_series!r}. Color→segment mapping is inverted."
    )


def test_ascending_stack_order_three_series(resolve_horizontal_bar_chart):
    """Three-series case: all midpoints derive from value-descending stacking.

    Series apple=10, banana=20, cherry=30. Value ordering (largest at baseline):
    cherry at 0..30 → mid 15;
    banana at 30..50 → mid 40;
    apple at 50..60 → mid 55.
    """
    data = [
        {"row": "r1", "value": 10, "series": "apple"},
        {"row": "r1", "value": 20, "series": "banana"},
        {"row": "r1", "value": 30, "series": "cherry"},
        {"row": "r2", "value": 1, "series": "apple"},
        {"row": "r2", "value": 1, "series": "banana"},
        {"row": "r2", "value": 1, "series": "cherry"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    spec = _render(rc, data)
    rows = _label_rows(spec)
    by_series = {r["series"]: r["__x"] for r in rows}
    assert by_series == {"cherry": 15.0, "banana": 40.0, "apple": 55.0}, (
        f"Expected cherry=15 (baseline, largest), banana=40, apple=55 (top, smallest) "
        f"with value-descending stack order; got {by_series!r}."
    )


def test_horizontal_stacked_does_not_flip_axis_y_orient(make_chart):
    """The labels pane sits ABOVE the chart, not to its right — axis orient
    resolution must not flip ``axis_y`` to ``"left"`` for horizontal endpoint
    labels (no right-edge collision risk).
    """
    from dbt_charts.core.compile.config import reset_config
    from dbt_charts.core.compile.models.chart.normalized import BarChart
    from dbt_charts.core.compile.models.query.normalized import SqlQuery
    from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
    from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

    reset_config()
    patch = BarChartStylePatch.model_validate(
        {"endpoint_labels": {"visible": True}, "orientation": "horizontal"}
    )
    chart = BarChart(
        id="t",
        type="bar",
        x="row",
        y="value",
        color="series",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
        style=patch,
    )
    data = _two_series_two_row_data()
    _rc = resolve(chart, data, chart_style_context=_BOARD_CTX)
    spec = generate_vega_lite_spec(chart, data, width=400)
    # Horizontal stacked endpoint labels emit vconcat (rail above chart);
    # the chart pane is hconcat[1] in the vertical case but vconcat[1] here.
    chart_pane = spec["vconcat"][1] if "vconcat" in spec else spec
    # Post-swap: original axis_y carries the *measure* axis and lands as
    # encoding.x. orient resolution should not silently flip the measure
    # axis to "left" for a horizontal rail-wrapped chart.
    x_orient = chart_pane.get("encoding", {}).get("x", {}).get("axis", {}).get("orient")
    assert x_orient != "left", (
        f"Horizontal rail-wrapped bar should not move the measure axis to "
        f"'left' (no right-edge label pane to collide with); got {x_orient!r}"
    )


def test_rail_follows_vl_stacked_sum_not_per_row_min(resolve_horizontal_bar_chart):
    """Vega-Lite's sort op defaults to `sum` on a stacked plot, not `min`.

    Data chosen so the two disagree: alpha's min (1) beats beta's (30), but
    beta's total (70) beats alpha's (101) ascending. Mirroring `min` would
    anchor the rail on alpha while VL renders beta on top, putting a label
    past the end of the bar it names.
    """
    from dbt_charts.core.compile.models.chart.authored import ChartSort

    data = [
        {"row": "alpha", "value": 1, "series": "A"},
        {"row": "alpha", "value": 100, "series": "B"},
        {"row": "beta", "value": 30, "series": "A"},
        {"row": "beta", "value": 40, "series": "B"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    rc = rc.model_copy(update={"sort": ChartSort(by="value", order="asc")})
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__x"] for r in rows}
    # beta sorts first by total (70 < 101), so its segments are the anchors:
    # B=40 at the baseline (0..40, mid 20), A=30 on top (40..70, mid 55).
    assert by_series == {"A": 55.0, "B": 20.0}


def test_rail_sorts_decimal_measures_like_vega_lite_does(resolve_horizontal_bar_chart):
    """A SQL ``SUM`` over a numeric column arrives as ``Decimal``.

    Vega-Lite sees floats (the rows are normalized before they reach
    ``data.values``), so a domain order that only counts int/float would fall
    back to alphabetical and anchor the rail on a different row than the one
    rendered on top.
    """
    from decimal import Decimal

    from dbt_charts.core.compile.models.chart.authored import ChartSort

    data = [
        {"row": "alpha", "value": Decimal("1"), "series": "A"},
        {"row": "alpha", "value": Decimal("100"), "series": "B"},
        {"row": "beta", "value": Decimal("30"), "series": "A"},
        {"row": "beta", "value": Decimal("40"), "series": "B"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    rc = rc.model_copy(update={"sort": ChartSort(by="value", order="asc")})
    spec = _render(rc, data)

    rows = _label_rows(spec)
    by_series = {r["series"]: r["__x"] for r in rows}
    # Same totals as the float case: beta (70) sorts ahead of alpha (101), so
    # beta's segments anchor the rail — B=40 (0..40, mid 20), A=30 (40..70, mid 55).
    assert by_series == {"A": 55.0, "B": 20.0}


def test_non_numeric_sort_raises_when_the_author_opts_in(resolve_horizontal_bar_chart):
    """Resolve steers the default away from a sort column with no numbers.

    An explicit opt-in reaches render, where the rail cannot reproduce Vega-
    Lite's string-concatenation order — so it says so rather than anchoring on
    a row Vega-Lite does not draw on top.
    """
    from dbt_charts.core.compile.models.chart.authored import ChartSort
    from dbt_charts.core.diagnostics.chart_data import ChartDataError

    data = _two_series_two_row_data()
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")
    rc = rc.model_copy(update={"sort": ChartSort(by="row", order="desc")})
    with pytest.raises(ChartDataError, match="no numeric values"):
        _render(rc, data)


def test_top_rail_does_not_warn_about_labels_it_never_truncates(
    resolve_horizontal_bar_chart,
):
    """The vconcat rail ignores the pane-width cap, so nothing is cut — no warning.

    Regression: the cap was measured before the layout branch, so a horizontal
    stacked bar with long series names reported labels as truncated while
    _wrap_vconcat_label_rail drew them in full.
    """
    from dbt_charts.core.render.chart.series_label_truncation import (
        collect_series_label_truncations,
    )

    long_a = "Enterprise Cloud Data Integration Platform — North America West"
    data = [
        {"row": "alpha", "value": 40, "series": long_a},
        {"row": "alpha", "value": 60, "series": long_a + " East"},
    ]
    rc = resolve_horizontal_bar_chart(data=data, enabled=True, stack="zero")

    with collect_series_label_truncations() as truncations:
        spec = _render(rc, data)

    assert "vconcat" in spec, "fixture must exercise the top_rail layout"
    # The rail mark carries no limit, so Vega draws the full name — warning here
    # would send the author chasing a truncation that never happened.
    assert "limit" not in spec["vconcat"][0]["mark"]
    assert truncations == {}
