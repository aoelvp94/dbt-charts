"""TDD regression tests: endpoint-label gap resolves against the real plot height.

The bug: ``_cascade_gap`` converted an intended pixel gap into a data-unit gap
using two assumptions about the plot rectangle (``box.height`` and the raw data
domain) that the renderer never actually uses — the real plot height is
shorter (chrome eats into it) and Vega-Lite's rendered y-domain is wider
(``nice``/headroom expansion). Both errors compound, delivering ~71-81% of the
intended pixel gap, height-dependently.

These tests render through the REAL pipeline (``vega_lite.render_resolved_chart``
-> ``converters.chart.render_vega_spec``) and parse label baselines out of the
label pane's ``<text transform="translate(x,y)">`` marks in the rendered SVG —
a unit test of ``_cascade_gap``'s return value cannot see this defect, because
the formula is self-consistent with itself; the gap only goes wrong once it is
converted back to pixels against the geometry Vega-Lite actually resolved.
"""

from __future__ import annotations

import re

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.features.endpoint_labels import (
    RecascadeResult,
    _apply_label_cascade,
    _distribute_evenly,
    recascade_endpoint_labels,
)
from dbt_charts.core.render.chart.translate import _spread_for_measurement
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart
from dbt_charts.core.render.converters.chart import render_vega_spec

_BOARD_STYLE = resolve_style(get_theme_style())
_BOARD_CONTEXT = resolve_chart_style_context(get_theme_style())

# Matches a label-pane text mark: <text ... transform="translate(x,y)" ...>NAME</text>
_LABEL_TEXT_RE = re.compile(
    r'<text[^>]*transform="translate\(([\-0-9.]+),\s*([\-0-9.]+)\)"[^>]*>([^<]*)</text>'
)


def _label_pane_positions(svg: str) -> list[tuple[str, float]]:
    """Parse (series_name, pixel_y) pairs from the label pane's rendered text marks."""
    match = re.search(r"concat_1_marks[^>]*>(.*?)</g></g>", svg, re.DOTALL)
    assert match is not None, "expected a concat_1 (label pane) marks group in the SVG"
    block = match.group(1)
    return [(text, float(y)) for _, y, text in _LABEL_TEXT_RE.findall(block)]


def _clustered_series_data() -> list[dict[str, object]]:
    """5-series line data whose endpoints cluster near the domain's top edge.

    Mirrors the task brief's measured board: a 5-series rail with descenders
    (``google_ads``, ``postgres``, ``bigquery``) crowded together, raw domain
    100-212 like the brief's own reproduction. Clustered endpoints force the
    greedy cascade to do real work, unlike evenly-pre-spaced synthetic data.
    """
    series = ["google_ads", "postgres", "bigquery", "salesforce", "stripe"]
    jan = [100, 105, 110, 115, 120]
    feb = [150, 155, 160, 165, 170]
    mar = [190, 196, 202, 208, 212]
    data: list[dict[str, object]] = []
    for i, s in enumerate(series):
        data.append({"date": "2024-01-01", "value": jan[i], "series": s})
        data.append({"date": "2024-02-01", "value": feb[i], "series": s})
        data.append({"date": "2024-03-01", "value": mar[i], "series": s})
    return data


def _render_svg(resolved, data, board_style, *, width: float, height: float) -> str:
    artifact = render_resolved_chart(
        resolved, data, board_style, width=width, height=height
    )
    assert artifact.kind == "vega_spec"
    return render_vega_spec(
        artifact.payload,
        "svg",
        board_style,
        width=width,
        height=height,
        is_placeholder=False,
        chart_id="test",
    )


class TestDeliveredSpacingAtTwoHeights:
    """Step 1: delivered pixel gap must meet the intended target, at two heights."""

    def _intended_gap_px(self, resolved) -> float:
        """The target the engine resolved — never a test-side copy of the formula.

        Recomputing `max(font_size * mult, min_px)` here would make these tests
        track any change to that formula instead of pinning it.
        """
        return resolved.style.series_label.gap_px

    def test_smallest_gap_meets_target_at_284(self, make_chart):
        chart = make_chart("line", x="date", y="value", color="series")
        data = _clustered_series_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CONTEXT)

        svg = _render_svg(resolved, data, _BOARD_STYLE, width=564.0, height=284.0)
        positions = sorted(y for _, y in _label_pane_positions(svg))
        gaps = [b - a for a, b in zip(positions, positions[1:], strict=False)]

        intended = self._intended_gap_px(resolved)
        assert min(gaps) >= intended - 0.5, (
            f"smallest delivered gap {min(gaps):.2f}px must meet the intended "
            f"target {intended:.2f}px at height=284 (got ratio "
            f"{min(gaps) / intended:.3f})"
        )

    def test_smallest_gap_meets_target_at_500(self, make_chart):
        chart = make_chart("line", x="date", y="value", color="series")
        data = _clustered_series_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CONTEXT)

        svg = _render_svg(resolved, data, _BOARD_STYLE, width=564.0, height=500.0)
        positions = sorted(y for _, y in _label_pane_positions(svg))
        gaps = [b - a for a, b in zip(positions, positions[1:], strict=False)]

        intended = self._intended_gap_px(resolved)
        assert min(gaps) >= intended - 0.5, (
            f"smallest delivered gap {min(gaps):.2f}px must meet the intended "
            f"target {intended:.2f}px at height=500 (got ratio "
            f"{min(gaps) / intended:.3f})"
        )

    def test_two_heights_agree_within_tolerance(self, make_chart):
        """Height-independence is the property being fixed — not just a bigger number."""
        chart = make_chart("line", x="date", y="value", color="series")
        data = _clustered_series_data()
        resolved = resolve(chart, data, chart_style_context=_BOARD_CONTEXT)

        svg_284 = _render_svg(resolved, data, _BOARD_STYLE, width=564.0, height=284.0)
        svg_500 = _render_svg(resolved, data, _BOARD_STYLE, width=564.0, height=500.0)
        gaps_284 = sorted(y for _, y in _label_pane_positions(svg_284))
        gaps_500 = sorted(y for _, y in _label_pane_positions(svg_500))
        min_gap_284 = min(b - a for a, b in zip(gaps_284, gaps_284[1:], strict=False))
        min_gap_500 = min(b - a for a, b in zip(gaps_500, gaps_500[1:], strict=False))

        intended = self._intended_gap_px(resolved)
        ratio_284 = min_gap_284 / intended
        ratio_500 = min_gap_500 / intended
        assert abs(ratio_284 - ratio_500) < 0.05, (
            f"delivered/intended ratio must agree across heights: "
            f"{ratio_284:.3f} at h=284 vs {ratio_500:.3f} at h=500"
        )


class TestCompactTierSpacing:
    """Step 2: compact-type charts must deliver ~1.3x font size, not ~1.64x.

    Regression guard: the gap floor used to be a single 18px regardless of
    font tier, so compact (11px) type asked for max(11*1.3, 18) = 18px — 1.64x
    the glyph size, nearly full-size spacing around a shrunk label. The
    compact floor (14px) lets the multiplier govern instead, matching the
    full-size ratio.
    """

    def test_compact_gap_matches_full_size_ratio(self, make_chart):
        chart = make_chart("line", x="date", y="value", color="series")
        data = _clustered_series_data()
        # width=400 sits in the "narrow" width tier (352.5-540.5px): compact
        # enough for _resolved_series_label to bake the compact font + gap
        # floor, but not so tiny that cartesian_series_naming folds the rail
        # into a top legend instead (that fold triggers only below 352.5px).
        resolved = resolve(chart, data, chart_style_context=_BOARD_CONTEXT, width=400.0)
        assert (
            resolved.style.series_label.font_size
            == _BOARD_CONTEXT.series_label.font.compact_size
        )
        assert resolved.style.endpoint_labels.visible

        svg = _render_svg(resolved, data, _BOARD_STYLE, width=400.0, height=284.0)
        positions = sorted(y for _, y in _label_pane_positions(svg))
        gaps = [b - a for a, b in zip(positions, positions[1:], strict=False)]

        compact_font_size = resolved.style.series_label.font_size
        expected = resolved.style.series_label.gap_px

        assert min(gaps) >= expected - 0.5, (
            f"compact delivered gap {min(gaps):.2f}px must meet {expected:.2f}px "
            f"(font_size * line_height_multiplier)"
        )
        assert min(gaps) / compact_font_size < 1.5, (
            f"compact delivered gap is {min(gaps) / compact_font_size:.2f}x font "
            f"size; expected ~1.3x. The spacing must tier with the type — a "
            f"full-size gap on compact type was the pre-fix ~1.64x."
        )


class TestNonCircularityInvariant:
    """Acceptance: cascade output must never exceed [y_domain_min, y_domain_max].

    The two panes share one y-scale. If a re-cascaded label position could sit
    outside the raw data domain, it would widen the shared scale, which would
    change the very slope the re-cascade measured itself against — circular.
    ``_apply_label_cascade``'s clamp is what keeps this from happening; pin it
    here so a future change that lets a label escape the clamp is caught.
    """

    def test_recascade_clamps_into_raw_domain(self):
        # Sized so the greedy cascade runs rather than the overflow branch:
        # slope -10 px/unit -> data_gap 1.8, and (n-1)*1.8 = 7.2 < span 10.
        # Without this the case duplicates the overflow test below and leaves
        # _apply_label_cascade's clamp unpinned at this layer.
        anchors = {"a": 59.0, "b": 58.5, "c": 58.0, "d": 57.5, "e": 57.0}
        result = recascade_endpoint_labels(
            anchors=anchors,
            pixel_gap=18.0,
            y_domain_min=50.0,
            y_domain_max=60.0,
            label_mark_leaves=[
                {"text": name, "y": 1000.0 - value * 10.0}
                for name, value in anchors.items()
            ],
            height_correction_ratio=1.0,
            emitted=anchors,
        )
        assert isinstance(result, RecascadeResult)
        assert result.outcome == "fit", "must exercise the greedy cascade, not overflow"
        for _, y in result.positions:
            assert 50.0 <= y <= 60.0, (
                f"cascade output {y} escaped [50.0, 60.0] — this would widen "
                "the shared y-scale and invalidate the measured slope"
            )

    def test_recascade_clamps_into_raw_domain_on_overflow(self):
        """Even the overflow (evenly-distributed) degradation must stay clamped."""
        anchors = {str(i): 100.0 + i * 0.1 for i in range(8)}
        result = recascade_endpoint_labels(
            anchors=anchors,
            pixel_gap=18.0,
            y_domain_min=100.0,
            y_domain_max=100.7,
            label_mark_leaves=[
                {"text": name, "y": 500.0 - value * 10}
                for name, value in anchors.items()
            ],
            height_correction_ratio=1.0,
            emitted=anchors,
        )
        assert result.outcome == "gap_did_not_fit"
        for _, y in result.positions:
            assert 100.0 <= y <= 100.7

    def test_tied_labels_distribute_evenly_and_report(self):
        """A pane with no measurable slope at all spreads out and says so.

        Ordinary ties no longer reach here: `translate._spread_for_measurement`
        separates them in the probe so the scale stays measurable and the
        normal cascade clusters them near their shared endpoint. This covers
        what is left — a collapsed domain (`scale.domain: [5, 5]`), where
        spreading has nowhere to go. Raising blanked the chart; returning the
        ties silently reported nothing.
        """
        anchors = {"a": 42.0, "b": 42.0, "c": 42.0}
        result = recascade_endpoint_labels(
            anchors=anchors,
            pixel_gap=18.0,
            y_domain_min=0.0,
            y_domain_max=100.0,
            label_mark_leaves=[{"text": name, "y": 250.0} for name in anchors],
            height_correction_ratio=1.0,
            emitted=anchors,
        )
        assert result.outcome == "no_slope", "cause must be recorded, not silent"
        assert result.positions == [("c", 100.0), ("b", 50.0), ("a", 0.0)], (
            "even distribution must keep the rail's series order: anchors arrive "
            "baseline-first, so the first-inserted series belongs at the bottom"
        )

    def test_zero_pixel_spread_does_not_crash(self):
        """Distinct data values collapsed onto one pixel must not divide by zero.

        Reachable from `style.axis_y.scale.domain: [5, 5]`, which compiles
        cleanly. slope would be 0.0 and `pixel_gap / abs(slope)` raised
        ZeroDivisionError, escaping as ERR-INTERNAL — a blank chart from valid
        authored YAML.
        """
        anchors = {"a": 10.0, "b": 20.0}
        result = recascade_endpoint_labels(
            anchors=anchors,
            pixel_gap=18.0,
            y_domain_min=0.0,
            y_domain_max=100.0,
            label_mark_leaves=[{"text": n, "y": 100.0} for n in anchors],
            height_correction_ratio=1.0,
            emitted=anchors,
        )
        assert result.outcome == "no_slope"
        assert sorted(y for _, y in result.positions) == [0.0, 100.0]

    def test_unmatched_marks_distribute_evenly(self):
        """Fewer than two matched marks is also 'no slope', not a failure."""
        anchors = {"a": 10.0, "b": 20.0}
        result = recascade_endpoint_labels(
            anchors=anchors,
            pixel_gap=18.0,
            y_domain_min=0.0,
            y_domain_max=100.0,
            label_mark_leaves=[{"text": "a", "y": 250.0}],
            height_correction_ratio=1.0,
            emitted=anchors,
        )
        assert result.outcome == "no_slope"
        assert sorted(y for _, y in result.positions) == [0.0, 100.0]

    def test_tie_ordering_matches_the_greedy_cascade(self):
        """The two placement paths must agree on series order, or the rail lies.

        Regression: `_distribute_evenly` sorted descending and mapped the
        first-inserted series to the top. Python's sort is stable, so a tie
        group kept insertion order — baseline-first on the stacked path — and
        came out vertically inverted against its own stack. The rail replaces
        the color legend, so its order IS the reader's series order.

        Asserting on `sorted(y for _, y in ...)` cannot catch this: both
        orderings produce the same set of y values. The label->position mapping
        is the thing under test.
        """
        anchors = {f"s{i}": 0.0 for i in range(5)}
        distributed = _distribute_evenly(anchors, 0.0, 500.0, "no_slope")
        cascaded = _apply_label_cascade(
            anchors, min_data_gap=20.0, y_domain_min=0.0, y_domain_max=500.0
        )
        assert [name for name, _ in distributed.positions] == [
            name for name, _ in cascaded
        ], "even distribution and the greedy cascade disagree on series order"
        assert distributed.positions[-1][0] == "s0", (
            "baseline series belongs at the bottom"
        )

    def test_tied_anchors_cluster_near_their_shared_endpoint(self):
        """Tied labels use the ordinary cascade, not a bespoke spread.

        A crowded rail is a crowded rail — ties are just its extreme case, and
        `_apply_label_cascade` already nudges crowded labels apart around the
        value they name. Spreading them across the whole domain instead put
        each label most of a plot-height from the endpoint it labels.

        The probe pane is spread (`translate._spread_for_measurement`) purely so
        the scale stays measurable; placement still comes from the true anchors.
        """
        anchors = dict.fromkeys(("alpha", "beta", "gamma", "delta", "eps"), 42.0)
        spread = _spread_for_measurement(list(anchors.items()), 0.0, 100.0)
        result = recascade_endpoint_labels(
            anchors=anchors,
            pixel_gap=18.0,
            y_domain_min=0.0,
            y_domain_max=100.0,
            label_mark_leaves=[{"text": n, "y": 300.0 - v * 2.0} for n, v in spread],
            height_correction_ratio=1.0,
            emitted=dict(spread),
        )
        assert result.outcome == "fit", "ties must reach the ordinary cascade"
        values = [y for _, y in result.positions]
        gaps = [a - b for a, b in zip(values, values[1:], strict=False)]
        assert all(abs(g * 2.0 - 18.0) < 0.01 for g in gaps), (
            "adjacent labels must sit exactly the intended 18px apart"
        )
        assert max(values) - min(values) < 50.0, (
            "the cluster must stay near its shared endpoint, not span the domain"
        )
