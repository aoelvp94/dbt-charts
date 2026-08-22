"""Tests for the series-label primitive (`style.charts.series_label`).

The primitive resolves D-053, D-049, D-044: a shared typography surface for any
text mark that names a data series — endpoint labels, direct stack labels,
slice callouts. Placement is family-specific; typography is shared.

See `design/chart-briefs/series-labels.md`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

# ---------------------------------------------------------------------------
# Theme cascade populates the primitive
# ---------------------------------------------------------------------------


def test_default_theme_populates_series_label_font_size():
    """Default theme provides an explicit series_label.font.size — does not
    rely on falling through to ``charts.label.font.size``."""
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    compiled = get_theme_style()
    resolved = resolve_chart_style_context(compiled)
    size = resolved.series_label.font.size
    assert size is not None, (
        "series_label.font.size is None after cascade — theme must populate "
        "the primitive's typography defaults"
    )


def test_series_label_size_is_decoupled_from_label_size():
    """series_label and label have independent ``font.size`` values.

    Uses a sentinel override on marks.text.font.size so the inequality is
    structurally guaranteed regardless of theme defaults.
    """

    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    compiled = get_theme_style()
    resolved = resolve_chart_style_context(compiled)
    series_size = resolved.series_label.font.size

    # Override marks.text.font.size to a sentinel that differs from series_label.font.size.
    # resolved is a dataclass; marks/text/font are Pydantic models.
    sentinel_text_size = (series_size or 11.0) + 50.0
    text_font = resolved.marks.text.font.model_copy(update={"size": sentinel_text_size})
    marks_text = resolved.marks.text.model_copy(update={"font": text_font})
    marks = resolved.marks.model_copy(update={"text": marks_text})
    resolved_with_sentinel = dataclasses.replace(resolved, marks=marks)

    assert resolved_with_sentinel.series_label.font.size != sentinel_text_size, (
        f"series_label.font.size ({resolved_with_sentinel.series_label.font.size}) "
        f"must not track marks.text.font.size ({sentinel_text_size}) — "
        f"primitive must decouple from the text-mark default"
    )


def test_endpoint_labels_height_propagates_through_cascade(model_copy_at):
    """Distinctive-value-plus-propagation for the endpoint-label pane height:
    overriding ``charts.line.endpoint_labels.height`` in the theme cascade
    must reach the merged ``LineChartStyle.endpoint_labels`` that
    ``build_chart_style_context`` returns — the same cascade path ``label_offset``
    already uses.
    """
    from dbt_charts.core.compile.models.chart.normalized import LineChart
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
    from dbt_charts.core.compile.resolve.style.chart_context import (
        build_chart_style_context,
    )

    seed = model_copy_at(get_theme_style(), "charts.line.endpoint_labels.height", 37.0)
    board = resolve_chart_style_context(seed)
    chart = LineChart(id="c", type="line", style=None)
    result = build_chart_style_context(board, chart)
    assert result.line.endpoint_labels.height == 37.0, (
        f"line.endpoint_labels.height is {result.line.endpoint_labels.height}, "
        "expected 37.0 — theme override did not reach EndpointLabelsConfig"
    )


def test_series_label_font_family_inherits_from_charts_font():
    """When theme leaves ``series_label.font.family`` unset, the cascade fills
    it from ``charts.font.family`` so series labels match the body sans."""
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    compiled = get_theme_style()
    resolved = resolve_chart_style_context(compiled)
    assert resolved.series_label.font.family is not None, (
        "series_label.font.family is None after resolve_chart_style_context — "
        "inherit graph must fill it from charts.font (same pattern as charts.label.font)"
    )


# ---------------------------------------------------------------------------
# Renderer reads from the primitive, not from charts.label
# ---------------------------------------------------------------------------


def _multi_series_data():
    return [
        {"date": "2024-01-01", "value": 100, "series": "Core"},
        {"date": "2024-02-01", "value": 120, "series": "Core"},
        {"date": "2024-03-01", "value": 140, "series": "Core"},
        {"date": "2024-01-01", "value": 200, "series": "Growth"},
        {"date": "2024-02-01", "value": 220, "series": "Growth"},
        {"date": "2024-03-01", "value": 180, "series": "Growth"},
    ]


@pytest.fixture
def render_endpoint_label_pane(make_chart, model_copy_at):
    """Render a multi-series line with endpoint labels enabled and the given
    ``series_label.font.*`` overrides applied to the cascade. Return the
    full hconcat spec so callers can inspect both panes.
    """
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.models.style.authored import EndpointLabelsConfig
    from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context

    def _build(**series_label_overrides) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        chart = make_chart("line", x="date", y="value", color="series")

        seed = model_copy_at(
            get_theme_style(),
            "charts.line.endpoint_labels",
            EndpointLabelsConfig(visible=True, label_offset=5.0, height=20.0),
        )
        for key, value in series_label_overrides.items():
            seed = model_copy_at(seed, f"charts.series_label.font.{key}", value)

        board, board_context = resolve_style_and_context(seed)
        return generate_vega_lite_spec(
            chart,
            _multi_series_data(),
            board_style=board,
            chart_style_context=board_context,
        )

    return _build


def test_endpoint_label_pane_uses_series_label_font_size(
    make_chart, render_endpoint_label_pane
):
    """Distinctive-value-plus-propagation: when a chart sets
    ``series_label.font.size`` to a unique value, the rendered endpoint-label
    text mark carries that value through to its ``fontSize``.

    Today's bug this resolves: endpoint labels read ``label.font.size``
    (the generic text-mark default, 11). After this primitive lands they
    read ``series_label.font.size``.
    """
    distinctive = 23.0
    spec = render_endpoint_label_pane(size=distinctive)
    assert "hconcat" in spec, (
        "endpoint_labels.visible=true should produce an hconcat — got: "
        f"{list(spec.keys())}"
    )
    rendered_size = spec["hconcat"][1]["mark"]["fontSize"]
    assert rendered_size == distinctive, (
        f"endpoint label fontSize is {rendered_size}, expected {distinctive} "
        f"(propagated from series_label.font.size). Renderer is still reading "
        f"from label.font.size or another stale source."
    )


def test_endpoint_label_pane_uses_series_label_font_weight(
    make_chart, render_endpoint_label_pane
):
    """Distinctive-value-plus-propagation for ``series_label.font.weight``.

    Closes the test gap noted in code review: ``fontWeight`` on the endpoint
    label mark must propagate from ``series_label.font.weight``, not from the
    generic ``charts.label.font.weight`` (the now-decoupled text-mark default).
    """
    distinctive = "700"
    spec = render_endpoint_label_pane(weight=distinctive)
    assert "hconcat" in spec
    rendered_weight = spec["hconcat"][1]["mark"]["fontWeight"]
    assert rendered_weight == distinctive, (
        f"endpoint label fontWeight is {rendered_weight}, expected "
        f"{distinctive} (propagated from series_label.font.weight)"
    )


def test_overriding_label_font_size_does_not_affect_endpoint_labels(
    make_chart, model_copy_at
):
    """Inverse propagation check: after the primitive lands, bumping
    ``charts.label.font.size`` must NOT bleed into endpoint labels.

    Confirms the decoupling works in both directions — generic text-mark
    typography and series-label typography evolve independently.
    """
    from dbt_charts.core.compile.models.style.authored import EndpointLabelsConfig
    from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context

    chart = make_chart("line", x="date", y="value", color="series")
    base = get_theme_style()
    series_size = base.charts.series_label.font.size
    seed = model_copy_at(
        model_copy_at(
            base,
            "charts.line.endpoint_labels",
            EndpointLabelsConfig(visible=True, label_offset=5.0, height=20.0),
        ),
        "charts.marks.text.font.size",
        99.0,
    )

    board, board_context = resolve_style_and_context(seed)
    spec = generate_vega_lite_spec(
        chart,
        _multi_series_data(),
        board_style=board,
        chart_style_context=board_context,
    )
    assert "hconcat" in spec
    rendered_size = spec["hconcat"][1]["mark"]["fontSize"]
    assert rendered_size == series_size, (
        f"endpoint label fontSize is {rendered_size}, expected {series_size} "
        f"(from series_label). Bumping charts.label.font.size leaked into "
        f"endpoint labels — decoupling failed."
    )
