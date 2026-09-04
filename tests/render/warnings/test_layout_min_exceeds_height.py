"""Tests for the LAYOUT_MIN_EXCEEDS_HEIGHT render-warning detector.

Detection rule: fires on a horizontal bar chart when the category-count
readability floor (min_height_for_horizontal_bar_categories — the same
floor vega_lite.py's _render_vl_artifact applies at render time) exceeds
ctx.authored_chart_heights' entry for that chart.

These are unit tests for the comparison logic only, driven by a hand-set
authored_chart_heights value — they do NOT prove renderer.py actually
computes that value correctly for a real board (a hand-built WarningContext
can pass while the real pipeline stays silent). The end-to-end gate for
that is dbt-charts/tests/core/render/test_layout_min_exceeds_height_warning_e2e.py,
which goes through compile() -> render() and reads RenderResult.warnings.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.authored._base import MultiplesConfig
from dbt_charts.core.compile.models.chart.normalized import BarChart, LineChart
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.style.authored import BarChartStylePatch
from dbt_charts.core.diagnostics import WARN_LAYOUT_MIN_EXCEEDS_HEIGHT, Diagnostic
from dbt_charts.core.render.chart.emitters._cartesian import (
    min_height_for_horizontal_bar_categories,
)
from dbt_charts.core.render.chart.vl_field_maps import effective_bar_size
from dbt_charts.core.render.warnings import (
    WarningContext,
    layout_min_exceeds_height as detector,
)

from ...core._board_utils import make_test_resolved_board, make_test_resolved_chart


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"cat": f"c{i:02d}", "val": i} for i in range(n)]


def _horizontal_bar() -> BarChart:
    return BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="cat",
        y="val",
        # model_construct, not the normal constructor: BarChartStylePatch's
        # TYPE_CHECKING stub aliases the full (non-optional) BarChartStyle, so
        # pyright demands every theme field here in this strictly-swept dir.
        style=BarChartStylePatch.model_construct(orientation="horizontal"),
    )


def _ctx(
    chart: Any,
    rows: list[dict[str, Any]],
    authored_height: float | None,
) -> WarningContext:
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    authored_chart_heights = (
        {resolved.id: authored_height} if authored_height is not None else {}
    )
    return WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={},
        authored_chart_heights=authored_chart_heights,
    )


def test_fires_when_authored_height_below_category_floor() -> None:
    """17 categories exceed the theme's category-count floor; the row
    authored only 280px, well under it."""
    chart = _horizontal_bar()
    rows = _rows(17)
    ctx = _ctx(chart, rows, authored_height=280.0)
    resolved = ctx.board_spec.charts["c1"]
    assert isinstance(resolved, ResolvedBarChart)
    expected_min_h = min_height_for_horizontal_bar_categories(
        17, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    w = warnings[0]
    assert isinstance(w, Diagnostic)
    assert w.code == WARN_LAYOUT_MIN_EXCEEDS_HEIGHT.code
    assert w.chart == "c1"
    assert "17" in w.message
    assert f"{expected_min_h:.0f}" in w.message
    assert "280" in w.message
    assert w.fix is not None


def test_silent_when_authored_height_comfortably_above_floor() -> None:
    """3 categories need ~189px; the row authored 900px — nowhere near the floor."""
    chart = _horizontal_bar()
    rows = _rows(3)
    assert detector.detect(_ctx(chart, rows, authored_height=900.0)) == []


def test_silent_when_nothing_was_authored() -> None:
    """No entry in authored_chart_heights at all -> nothing was overridden."""
    chart = _horizontal_bar()
    rows = _rows(17)
    assert detector.detect(_ctx(chart, rows, authored_height=None)) == []


def test_silent_when_rows_facet_narrows_the_category_axis_to_one_per_panel() -> None:
    """A horizontal bar faceted rows-only on its own category field holds
    exactly one category per panel, by construction of the row split — the
    floor must be computed from that per-panel count, not the whole-dataset
    union, or this warning misinstructs the author to grow an already-
    sufficient height."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="cat",
        y="val",
        multiples=MultiplesConfig(rows="cat"),
        style=BarChartStylePatch.model_construct(orientation="horizontal"),
    )
    rows = _rows(6)
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    assert isinstance(resolved, ResolvedBarChart)
    per_panel_floor = min_height_for_horizontal_bar_categories(
        1, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    # Comfortably above the correct (narrowed) per-panel floor, but far
    # below what the whole-dataset-union floor (6 categories x 6 row
    # panels) would have demanded before this fix.
    authored_height = per_panel_floor * 6 * 1.5
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={},
        authored_chart_heights={resolved.id: authored_height},
    )
    assert detector.detect(ctx) == []


def test_grid_facet_falls_back_to_the_full_domain_when_narrowing_is_unaffordable() -> (
    None
):
    """A columns/grid facet's category narrowing is width-gated
    (`facet_bound_position_channels`'s affordability check) — this detector
    has no render-time card width, so it recovers the pre-narrowing
    baseline from the emitted spec itself (`unit["width"]` plus, only when
    the spec shows narrowing actually applied, the measured reservation
    added back). Here the spec shows narrowing did NOT apply (no
    `resolve.scale.y`, a tiny 50px panel width) — every panel's own `cat`
    subset (2-3 of 5) WOULD be a real domain-subset candidate, but the real
    renderer declined it as unaffordable. The floor must use the
    whole-domain count (5), not the narrower per-panel one (3) — passing
    `None` (the pre-fix behaviour) skips the affordability check entirely
    and would wrongly narrow anyway, under-computing the floor and
    under-warning the author."""
    # Explicit mirror: False — a columns/grid facet auto-defaults mirror on
    # for bar's quantitative measure axis, and the mirror guard in
    # `facet_bound_position_channels` would exclude "y" regardless of
    # affordability, masking the exact gap this test targets. model_validate
    # (not model_construct) so the nested axis_y patch actually validates.
    chart = BarChart.model_validate(
        {
            "id": "c1",
            "type": "bar",
            "query_name": "q",
            "x": "cat",
            "y": "val",
            "multiples": {"rows": "grp", "columns": "seg"},
            "style": {"orientation": "horizontal", "axis_y": {"mirror": False}},
        }
    )
    cells = {
        ("G1", "S1"): ("c0", "c1"),
        ("G1", "S2"): ("c0", "c1", "c2"),
        ("G2", "S1"): ("c2", "c3"),
        ("G2", "S2"): ("c3", "c4"),
    }
    rows = [
        {"cat": c, "grp": grp, "seg": seg, "val": 1}
        for (grp, seg), cats in cells.items()
        for c in cats
    ]
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    assert isinstance(resolved, ResolvedBarChart)
    full_domain_floor = min_height_for_horizontal_bar_categories(
        5, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    narrowed_floor = min_height_for_horizontal_bar_categories(
        3, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    row_cardinality = 2  # multiples.rows="grp" -> {G1, G2}
    # Below the correct (full-domain) floor, but above the wrongly-narrowed
    # one — isolates exactly the case a `None`-fallback bug would miss.
    authored_height = narrowed_floor * row_cardinality * 1.1
    assert authored_height < full_domain_floor * row_cardinality
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={
            resolved.id: {
                "facet": {"row": {"field": "grp"}, "column": {"field": "seg"}},
                "spec": {"width": 50.0},
            }
        },
        authored_chart_heights={resolved.id: authored_height},
    )
    warnings = detector.detect(ctx)
    assert len(warnings) == 1
    assert warnings[0].code == WARN_LAYOUT_MIN_EXCEEDS_HEIGHT.code
    assert "5" in warnings[0].message


def test_grid_facet_uses_the_narrowed_domain_when_the_spec_shows_narrowing_applied() -> (
    None
):
    """Mirror image of the unaffordable case above: here the emitted spec DOES
    show narrowing (`resolve.scale.y == "independent"`), so the floor must use
    the widest panel's own count, not the whole domain.

    The detector cannot read `render_width` as the baseline for its own
    affordability re-check, because by then the width has already had the
    reservation subtracted — re-checking against the post-narrowing width
    double-charges it, the check fails, and the floor inflates back to the
    full domain. The warning then fires on a board whose panels genuinely
    fit. That is the spurious-fire defect this file exists to prevent, and
    only a spec carrying `resolve` can reach the branch that avoids it.
    """
    chart = BarChart.model_validate(
        {
            "id": "c1",
            "type": "bar",
            "query_name": "q",
            "x": "cat",
            "y": "val",
            "multiples": {"rows": "grp", "columns": "seg"},
            "style": {"orientation": "horizontal", "axis_y": {"mirror": False}},
        }
    )
    cells = {
        ("G1", "S1"): ("c0", "c1"),
        ("G1", "S2"): ("c0", "c1", "c2"),
        ("G2", "S1"): ("c2", "c3"),
        ("G2", "S2"): ("c3", "c4"),
    }
    rows = [
        {"cat": c, "grp": grp, "seg": seg, "val": 1}
        for (grp, seg), cats in cells.items()
        for c in cats
    ]
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    assert isinstance(resolved, ResolvedBarChart)
    full_domain_floor = min_height_for_horizontal_bar_categories(
        5, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    narrowed_floor = min_height_for_horizontal_bar_categories(
        3, resolved.style.axis_x, effective_bar_size(resolved.style.mark)
    )
    row_cardinality = 2
    # Between the two floors again — but this time the narrowed one is the
    # correct answer, so the same height that must warn above must stay
    # silent here. The two tests differ only by the spec's `resolve` key.
    authored_height = narrowed_floor * row_cardinality * 1.1
    assert authored_height < full_domain_floor * row_cardinality
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={
            resolved.id: {
                "facet": {"row": {"field": "grp"}, "column": {"field": "seg"}},
                # `resolve` sits at the facet ROOT, beside `facet`/`spec` —
                # that is where `facet_channel_is_independent` reads it.
                "spec": {"width": 150.0},
                "resolve": {"scale": {"y": "independent"}},
            }
        },
        authored_chart_heights={resolved.id: authored_height},
    )
    assert detector.detect(ctx) == []


def test_silent_on_vertical_bar() -> None:
    """Vertical bars band along width, not height — this detector doesn't apply."""
    chart = BarChart(
        id="c1",
        type="bar",
        query_name="q",
        x="cat",
        y="val",
        style=BarChartStylePatch.model_construct(orientation="vertical"),
    )
    rows = _rows(17)
    assert detector.detect(_ctx(chart, rows, authored_height=280.0)) == []


def test_silent_on_non_bar_chart() -> None:
    chart = LineChart(id="c1", type="line", query_name="q", x="cat", y="val")
    rows = _rows(17)
    assert detector.detect(_ctx(chart, rows, authored_height=280.0)) == []


def test_silent_when_chart_has_no_authored_height_entry() -> None:
    """A chart absent from authored_chart_heights has no cap to violate."""
    chart = _horizontal_bar()
    rows = _rows(17)
    resolved = make_test_resolved_chart(chart, rows)
    board = make_test_resolved_board(charts={resolved.id: resolved})
    ctx = WarningContext(
        board_spec=board,
        chart_results={resolved.id: rows},
        vega_specs={},
        authored_chart_heights={},
    )
    assert detector.detect(ctx) == []


def test_silent_without_chart_results() -> None:
    """No executed rows means no category count to judge."""
    chart = _horizontal_bar()
    assert detector.detect(_ctx(chart, [], authored_height=280.0)) == []
