"""Area charts always zero-anchor: the fill IS the magnitude encoding, so a
truncated area misstates the filled quantity exactly as a truncated bar
does. Pins the removal of "area" from
``enrich._OPTIONAL_ZERO_CHART_TYPES``, and the render-time baseline-rule
carve-outs that must survive it unchanged: streamgraph
(``stack: center``) draws no zero/top rule, and normalize-stack keeps its
top-rule-pair / unity-rule behavior.

Data ratio: min/max = 80/120 ~= 0.667 > 0.25 -- the smart-zero heuristic
that line/scatter still use would keep this data-fitted (``zero: False``);
area must anchor to zero regardless. Before this fix, area used the same
optional-zero heuristic and DID return ``zero: False`` for this data on
BOTH the unstacked and the stacked variant -- verified directly by running
the compiler with the fix reverted. Only a close-to-zero ratio (<= 0.25)
was already anchored pre-fix, via a now-deleted area-only special case.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

_BOARD_STYLE, _BOARD_CTX = resolve_style_and_context(get_theme_style())

# ratio = 80/120 ~= 0.667 > 0.25 -- far from zero, the discriminating case.
_FAR_RATIO_DATA = [
    {"date": "2024-01-01", "value": 100, "series": "Revenue"},
    {"date": "2024-02-01", "value": 120, "series": "Revenue"},
    {"date": "2024-01-01", "value": 80, "series": "Costs"},
    {"date": "2024-02-01", "value": 90, "series": "Costs"},
]


def _render(make_chart, stack, format=None):
    reset_config()
    kwargs: dict = {"color": "series"}
    if stack is not None:
        kwargs["stack"] = stack
    if format is not None:
        kwargs["format"] = format
    chart = make_chart("area", x="date", y="value", **kwargs)
    resolved = resolve(chart, _FAR_RATIO_DATA, chart_style_context=_BOARD_CTX)
    artifact = render_resolved_chart(resolved, _FAR_RATIO_DATA, _BOARD_STYLE, width=400)
    assert artifact.kind == "vega_spec"
    spec = artifact.payload
    return spec["hconcat"][0] if "hconcat" in spec else spec


def _rule_layers(spec: dict) -> list[dict]:
    return [
        layer
        for layer in spec.get("layer", [])
        if layer.get("mark", {}).get("type") == "rule"
    ]


def test_area_zero_anchors_when_unstacked_and_far_from_zero(make_chart) -> None:
    """Overlap/unstacked area (stack unset) zero-anchors on far-ratio data."""
    spec = _render(make_chart, stack=None)
    assert spec["encoding"]["y"]["scale"]["zero"] is True


def test_area_zero_anchors_when_stacked_and_far_from_zero(make_chart) -> None:
    """Stacked area (stack: zero) zero-anchors on far-ratio data."""
    spec = _render(make_chart, stack="zero")
    assert spec["encoding"]["y"]["scale"]["zero"] is True


def test_streamgraph_emits_no_zero_or_top_rule(make_chart) -> None:
    """Regression pin: stack: center (streamgraph) draws no baseline rule at
    all -- y=0 is the silhouette's visual centerline, not a baseline."""
    spec = _render(make_chart, stack="center")
    assert _rule_layers(spec) == []


def test_streamgraph_bakes_no_zero_anchor_onto_its_scale(make_chart) -> None:
    """A streamgraph's y=0 is the silhouette's centerline, so a zero anchor is
    not a weaker or stronger opinion there -- it is a meaningless one.

    Vega-Lite floats each center-stacked column up by
    ``(max_total - this_total) / 2``, so a ``domainMin: 0`` clips nothing
    today and the render is byte-identical with or without it. That is an
    accident of VL's offset never going negative, not a property this family
    guarantees -- which is why the anchor is skipped at the bake rather than
    left in as incidentally harmless. The emitted ``zero: False`` is the
    pre-existing streamgraph emission and is deliberately not asserted away
    here; only a positive zero anchor would be new.
    """
    scale = _render(make_chart, stack="center")["encoding"]["y"]["scale"]
    assert scale.get("zero") is not True
    assert "domainMin" not in scale


def test_normalize_stack_still_emits_top_rule_pair(make_chart) -> None:
    """Regression pin: stack: normalize still gets its 0% and 100% top rules."""
    spec = _render(make_chart, stack="normalize")
    rules = _rule_layers(spec)
    datums = sorted(layer["encoding"]["y"]["datum"] for layer in rules)
    assert datums == [0, 1]


def test_normalize_stack_with_percent_format_dedupes_unity_rule(
    make_chart,
) -> None:
    """Regression pin: percent-format normalize area keeps its 0% baseline
    and gets exactly ONE 100% unity rule at datum 1 -- never the old
    duplicate-unity ``[0, 1, 1]`` triple (two datum-1 rules, one from the
    top-rule pair and one from the unity gate)."""
    spec = _render(make_chart, stack="normalize", format=".0%")
    rules = _rule_layers(spec)
    datums = sorted(layer["encoding"]["y"]["datum"] for layer in rules)
    assert datums == [0, 1]
