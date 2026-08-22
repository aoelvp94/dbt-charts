"""V2 callout SVG golden tests.

Verifies render_callout_chart_svg produces valid, non-empty SVG output
for a range of callout configurations. The v1 oracle (render_callout_chart_svg)
has been deleted; these tests pin v2 output directly.

  v2: normalize_chart -> resolve() -> render_callout_chart_svg
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context


def _rs_and_ctx():
    return resolve_style_and_context(get_theme_style(get_default_theme_name()))


def _chart_def(
    message: str, title: str | None = None, style: dict[str, Any] | None = None
) -> dict[str, Any]:
    chart_def: dict[str, Any] = {"type": "callout", "message": message}
    if title is not None:
        chart_def["title"] = title
    if style is not None:
        chart_def["style"] = style
    return chart_def


def _v2_svg(
    message: str, title: str | None = None, style: dict[str, Any] | None = None
) -> str:
    """v2 path: authored dict -> normalize_chart -> resolve() -> render_callout_chart_svg."""
    from dbt_charts.core.compile.models.chart.resolved.callout import (
        ResolvedCalloutChart,
    )
    from dbt_charts.core.compile.normalize.charts import normalize_chart
    from dbt_charts.core.compile.resolve import resolve
    from dbt_charts.core.render.chart.callout import render_callout_chart_svg

    _, ctx = _rs_and_ctx()
    normalized = normalize_chart(
        "co", _chart_def(message, title, style), {}, sources={}
    )
    resolved = resolve(normalized, [], ctx)
    assert isinstance(resolved, ResolvedCalloutChart)
    return render_callout_chart_svg(resolved, [])


def test_v2_callout_message_only_produces_svg() -> None:
    message = "This dashboard is under construction."
    svg = _v2_svg(message)
    assert "<svg" in svg
    assert message in svg


def test_v2_callout_message_and_title_produces_svg() -> None:
    message = "This chart requires review."
    title = "Heads up"
    svg = _v2_svg(message, title)
    assert "<svg" in svg
    assert message in svg
    assert title in svg


def test_v2_callout_with_chart_local_style_override_produces_svg() -> None:
    message = "Some data may be incomplete."
    style = {
        "tone": "warning",
        "padding": {"left": 12, "right": 12, "top": 8, "bottom": 8},
        "border": {"width": 2, "color": "#ff0000", "radius": 4},
    }
    svg = _v2_svg(message, style=style)
    assert "<svg" in svg
    assert message in svg


def test_v2_callout_border_dash_array_emits_svg_dasharray() -> None:
    message = "Dashed callout border."
    style = {
        "border": {
            "width": 2,
            "color": "#ff0000",
            "radius": 4,
            "dash_array": [4, 4],
            "line_cap": "round",
        },
    }
    svg = _v2_svg(message, style=style)
    assert 'stroke-dasharray="4,4"' in svg
    assert 'stroke-linecap="round"' in svg


def test_v2_callout_bold_message_uses_theme_bold_weight() -> None:
    """A **bold** span inside a callout message renders at the theme's bold
    weight, not mdsvg's hardcoded default. render/chart/callout.py builds its
    own mdsvg.Style rather than going through compact_style_kwargs(), so this
    pins that bold_font_weight is actually threaded through, not left stale."""
    from dbt_charts.core.compile.models.style.theme import font_weight_as_css

    rs, _ = _rs_and_ctx()
    expected_weight = font_weight_as_css(rs.text.bold.weight)
    svg = _v2_svg("A **bold** word.")
    assert f"font-weight: {expected_weight}" in svg


def test_v2_callout_bold_title_matches_title_base_weight() -> None:
    """A **bold** span inside a callout title must not render lighter than
    the title's own (non-bold) text around it -- the two weights share one
    theme token, so a bold run and the surrounding title text always agree."""
    from dbt_charts.core.compile.models.style.theme import font_weight_as_css

    rs, ctx = _rs_and_ctx()
    expected_bold = font_weight_as_css(rs.text.bold.weight)
    expected_title = font_weight_as_css(ctx.callout.title.font.weight)
    assert expected_bold == expected_title, (
        "callout.title.font.weight must match text.bold.weight — otherwise "
        "a **bold** span inside a title renders at a different weight than "
        "the title's own base text, inverting emphasis on the same line."
    )
    svg = _v2_svg("Plain title with **bold** word", title="A **bold** title")
    assert f"font-weight: {expected_bold}" in svg
