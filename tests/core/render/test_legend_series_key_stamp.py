"""Tests for ``_stamp_series_keys`` -- the SVG post-process pass that stamps
``data-dbt-series`` on legend labels so ``chart_interactivity.js``'s
``legendSeriesOrder()`` can join a mark to its legend entry on the raw
series value instead of Vega's rendered (possibly ellipsis-truncated)
legend text.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest
import vl_convert as vlc

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.models.style.authored import (
    BarChartStylePatch,
    LegendStylePatch,
)
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.emitters._tooltip import ROLE_ORDER, ROLE_SERIES
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec
from dbt_charts.core.render.converters.chart import _stamp_series_keys, render_vega_spec

_BOARD_RS, _BOARD_CTX = resolve_style_and_context(get_theme_style())

# Grouped (stack unset -> None) bar with a nominal color field: the LUT's
# fallback path -- no color-scale domain override, so no baked ROLE_ORDER
# rank (see features/structured_tooltip.py's _series_order_role).
_GROUPED_BAR_DATA = [
    {"month": "Jan", "revenue": 100.0, "kind": "Enterprise Self-Serve Renewals"},
    {"month": "Jan", "revenue": 80.0, "kind": "Enterprise Self-Serve Upgrades"},
    {"month": "Feb", "revenue": 150.0, "kind": "Enterprise Self-Serve Renewals"},
    {"month": "Feb", "revenue": 90.0, "kind": "Enterprise Self-Serve Upgrades"},
]

_LEGEND_LABEL_TEXT_RE = re.compile(
    r'<g class="[^"]*role-legend-label[^"]*"[^>]*>\s*<text[^>]*>([^<]*)</text>'
)
_LEGEND_LABEL_STAMP_RE = re.compile(
    r'<g class="[^"]*role-legend-label[^"]*"[^>]*data-dbt-series="([^"]*)"'
)


@pytest.fixture(autouse=True)
def reset():
    reset_config()
    yield
    reset_config()


def _grouped_bar_chart(max_width: float, data_field: str = "kind") -> BarChart:
    return BarChart(
        id="t",
        type="bar",
        x="month",
        y="revenue",
        color=data_field,
        style=BarChartStylePatch.model_validate(
            {
                "legend": LegendStylePatch.model_validate(
                    {"label": {"max_width": max_width}}
                )
            }
        ),
    )


def _render(chart: BarChart, data: list[dict]) -> str:
    spec = generate_vega_lite_spec(
        chart, data, board_style=_BOARD_RS, chart_style_context=_BOARD_CTX, width=400
    )
    return render_vega_spec(spec, "svg", _BOARD_RS, 400.0, None, False, chart_id="t")


def test_legend_labels_stamp_untruncated_series_value_even_when_rendered_text_is_ellipsized() -> (
    None
):
    # "Enterprise Self-Serve Renewals"/"...Upgrades" share a prefix well past
    # 90px, so a 90px labelLimit ellipsizes both to the identical rendered
    # text -- the exact collision the stamped attribute must resolve.
    svg = _render(_grouped_bar_chart(max_width=90), _GROUPED_BAR_DATA)
    assert ROLE_ORDER not in svg, "expected the fallback (no baked rank) path"

    legend_texts = _LEGEND_LABEL_TEXT_RE.findall(svg)
    assert all("…" in text for text in legend_texts)

    stamped_values = _LEGEND_LABEL_STAMP_RE.findall(svg)
    assert stamped_values == [
        "Enterprise Self-Serve Renewals",
        "Enterprise Self-Serve Upgrades",
    ]


def test_legend_label_stamp_is_trimmed() -> None:
    """A series value with trailing whitespace must stamp trimmed to match
    the mark side: chart_interactivity.js's parseAriaLabel trims each
    aria-label part from its outer edges, which reaches trailing whitespace
    on a mark's own series value but not leading whitespace (the ROLE_SERIES
    marker sits between the part's edge and any leading whitespace in the
    raw value, so trim() never gets past it) -- pre-existing JS-side
    asymmetry, unrelated to this stamp. This test only pins the trailing
    side, which is what the two sides actually agree on."""
    data = [
        {"month": "Jan", "revenue": 100.0, "kind": "  Padded  "},
        {"month": "Jan", "revenue": 80.0, "kind": "Other"},
    ]
    svg = _render(_grouped_bar_chart(max_width=1000), data)
    assert "Padded" in _LEGEND_LABEL_STAMP_RE.findall(svg)
    assert "  Padded  " not in _LEGEND_LABEL_STAMP_RE.findall(svg)


def test_series_value_containing_ampersand_stays_valid_xml() -> None:
    """A series value containing '&' must not produce malformed SVG --
    the raw scenegraph text is HTML-escaped before it's written into the
    ``data-dbt-series`` attribute."""
    data = [
        {"month": "Jan", "revenue": 100.0, "kind": "R&D"},
        {"month": "Jan", "revenue": 80.0, "kind": "Sales"},
    ]
    svg = _render(_grouped_bar_chart(max_width=1000), data)
    ET.fromstring(svg)  # raises ET.ParseError on malformed SVG
    assert "R&amp;D" in svg


@pytest.mark.parametrize(
    "series_value", ["Line1\nLine2", "Line1\rLine2", "A\tB"], ids=["lf", "cr", "tab"]
)
def test_legend_stamp_preserves_internal_control_whitespace_exactly(
    series_value: str,
) -> None:
    """A literal newline/CR/tab inside an XML attribute value gets space-
    normalized under strict XML attribute-value parsing; a numeric character
    reference does not. Vega's own aria-label already writes a mark's series
    value with a character reference for internal control whitespace, so the
    stamped attribute must decode to the identical string after real
    attribute parsing, not just after a raw string strip -- a value with
    only leading/trailing whitespace wouldn't exercise this at all, since
    that's removed before either side is ever escaped."""
    data = [
        {"month": "Jan", "revenue": 100.0, "kind": series_value},
        {"month": "Jan", "revenue": 80.0, "kind": "Other"},
    ]
    svg = _render(_grouped_bar_chart(max_width=1000), data)

    root = ET.fromstring(svg)  # applies real XML attribute-value normalization
    stamped_values = {
        el.get("data-dbt-series")
        for el in root.iter()
        if el.get("data-dbt-series") is not None
    }
    mark_series_values: set[str] = set()
    for el in root.iter():
        for part in (el.get("aria-label") or "").split(";"):
            trimmed = part.strip()
            if trimmed.startswith(ROLE_SERIES):
                mark_series_values.add(trimmed[1:])

    assert series_value in mark_series_values, mark_series_values
    assert series_value in stamped_values, stamped_values


def test_baked_role_order_family_gate_is_a_no_op() -> None:
    """A family with a baked ROLE_ORDER rank (a stacked bar) never reaches
    the legend fallback -- the gate must produce byte-identical SVG."""
    chart = BarChart(
        id="t", type="bar", x="month", y="revenue", color="kind", stack="zero"
    )
    spec = generate_vega_lite_spec(
        chart,
        _GROUPED_BAR_DATA,
        board_style=_BOARD_RS,
        chart_style_context=_BOARD_CTX,
        width=400,
    )
    svg = vlc.vegalite_to_svg(spec)
    assert ROLE_ORDER in svg, "expected this family to bake a display-order rank"
    assert _stamp_series_keys(svg, spec, vlc, "t") == svg


def test_no_series_encoding_gate_is_a_no_op() -> None:
    """A chart with no color/series channel at all carries no ROLE_SERIES
    entry -- the gate must produce byte-identical SVG."""
    chart = BarChart(id="t", type="bar", x="month", y="revenue")
    data = [{"month": "Jan", "revenue": 100.0}, {"month": "Feb", "revenue": 150.0}]
    spec = generate_vega_lite_spec(
        chart, data, board_style=_BOARD_RS, chart_style_context=_BOARD_CTX, width=400
    )
    svg = vlc.vegalite_to_svg(spec)
    assert ROLE_SERIES not in svg
    assert _stamp_series_keys(svg, spec, vlc, "t") == svg


def test_role_order_codepoint_inside_a_real_value_does_not_flip_the_gate() -> None:
    """ROLE_ORDER (U+200C ZERO WIDTH NON-JOINER) occurs natively in real
    text -- a series value merely containing that codepoint must not be
    mistaken for a baked rank and disable legend stamping."""
    data = [
        {"month": "Jan", "revenue": 100.0, "kind": "Bar‌Foo"},
        {"month": "Jan", "revenue": 80.0, "kind": "Other"},
    ]
    svg = _render(_grouped_bar_chart(max_width=1000), data)
    assert _LEGEND_LABEL_STAMP_RE.findall(svg), (
        "a stray ROLE_ORDER codepoint in authored data must not suppress stamping"
    )


def test_continuous_color_legend_is_not_stamped() -> None:
    """A numeric color field renders ONE legend-label scenegraph node whose
    ``items`` holds every tick label (a gradient tick strip), not one node
    per series -- there is no per-series text to extract there. Stamping
    must bail for the whole chart rather than mis-stamp a tick label (e.g.
    the first tick, "1") as if it were a series value."""
    data = [
        {"month": "Jan", "revenue": 100.0, "score": 1},
        {"month": "Jan", "revenue": 80.0, "score": 2},
        {"month": "Feb", "revenue": 150.0, "score": 3},
        {"month": "Feb", "revenue": 90.0, "score": 4},
    ]
    chart = _grouped_bar_chart(max_width=1000, data_field="score")
    spec = generate_vega_lite_spec(
        chart, data, board_style=_BOARD_RS, chart_style_context=_BOARD_CTX, width=400
    )
    svg = vlc.vegalite_to_svg(spec)
    assert ROLE_SERIES in svg, "expected a series row on this chart"
    assert "role-legend-label" in svg, "expected a legend to render"

    assert _stamp_series_keys(svg, spec, vlc, "t") == svg
    assert "data-dbt-series" not in svg
