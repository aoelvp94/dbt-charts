"""Overlay layer identity and the categorical sort guard.

Two rules govern ``render_cartesian_overlay`` / ``_reconcile_x_domain``
(``core/render/chart/emitters/_overlay.py``):

1. A layer's rows genuinely diverge from the base's only when its resolved
   query name differs from the base's own (``layer.query_name !=
   base_query_name``) — an unauthored layer's query always resolves to the
   base's own query name, so ``own_data is not None`` (or an identity check
   against the base's row list) cannot tell "reads its own rows" from
   "shares the base's".
2. A shared categorical x scale's domain is never pinned to raw row order
   when the base's x encoding carries an authored ``sort`` — an explicit
   ``scale.domain`` always wins over ``sort`` in Vega-Lite, so pinning one
   silently defeats the other. Mirrors the guard already in
   ``pin_categorical_domain_order`` (``emitters/_layers.py``).

Covers the two failing cases neither rule previously caught:
- an own-query or own-x overlay layer on a chart with an authored
  ``chart.sort`` (categorical x) — sort must survive, not get pinned away;
- an unauthored overlay layer on a date-bucketed / gap-filled base x — the
  overlay must share the base's own (already-normalized) rows, not a stale
  raw lookup mismatched against what the base actually renders.

No layer in this file authors ``labels:`` — the bug reproduces on plain
overlay layers, independent of the value-label/notation feature.
"""

from __future__ import annotations

import json

import vl_convert as vlc

from dbt_charts.core.compile.models.chart.authored import ChartSort
from dbt_charts.core.compile.models.chart.authored._layer import LineLayer
from dbt_charts.core.compile.models.chart.normalized import BarChart as NBarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.chart._chart_rows import regroup
from dbt_charts.core.font_measure import RESERVATION_GUARD
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters._overlay import _reconcile_x_domain
from dbt_charts.core.render.chart.emitters.bar import BarEmitter
from dbt_charts.core.render.chart.spec import RenderBox
from dbt_charts.core.render.chart.translate import translate_to_vl

_DEFAULT_BOX = RenderBox(width=600.0, height=300.0)


def _sql(sql: str = "SELECT 1"):
    return SqlQuery(sql=sql, source="t")


def _default_board_style():
    from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    return resolve_chart_style_context(get_theme_style(get_default_theme_name()))


def _bar_normalized(**kwargs):  # type: ignore[no-untyped-def]
    defaults = {
        "id": "bar1",
        "type": "bar",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
        "variable_dependencies": set(),
    }
    defaults.update(kwargs)
    return NBarChart(**defaults)


def _line_layer_wrapper(vl, y_field):  # type: ignore[no-untyped-def]
    """Return the overlay wrapper's own top-level dict for the given y field."""
    for layer in vl.get("layer", []):
        enc = layer.get("encoding", {})
        if enc.get("y", {}).get("field") == y_field:
            return layer
    raise AssertionError(f"no overlay layer with y field {y_field!r}")


def _rendered_x_axis_order(vl: VLDict) -> list[str]:
    """The chart's x-axis category labels, ordered by their RENDERED pixel
    position — read off Vega's compiled scenegraph, not the VL spec's
    ``sort`` key. An explicit ``scale.domain`` silently defeats an authored
    ``sort`` in Vega-Lite (the domain wins), so the emitted ``sort`` key can
    survive verbatim in the spec while being completely ignored at render
    time — asserting on it proves nothing. This walks the actual compiled
    Vega scenegraph's x-axis tick labels, left to right, which is what a
    viewer actually sees.
    """
    vega = vlc.vegalite_to_vega(json.dumps(vl))
    scenegraph = vlc.vega_to_scenegraph(vega)

    def walk(node):  # type: ignore[no-untyped-def]
        if isinstance(node, dict):
            if node.get("marktype") == "text" and node.get("role") == "axis-label":
                yield from ((item["x"], item["text"]) for item in node["items"])
            for child in node.get("items", []):
                yield from walk(child)
        elif isinstance(node, list):
            for child in node:
                yield from walk(child)

    positioned = sorted(walk(scenegraph["scenegraph"]), key=lambda pair: pair[0])
    # The y-axis's own numeric tick labels interleave in scenegraph order;
    # this chart's category labels are the only non-numeric axis-label text.
    # A leading RESERVATION_GUARD (if any survives) is stripped before the
    # digit check, or a padded numeric label reads as non-digit and leaks
    # into the category order this helper returns.
    _pad_chars = RESERVATION_GUARD
    return [
        text
        for _, text in positioned
        if not text.strip(_pad_chars)
        .replace(",", "")
        .replace(".", "")
        .lstrip("-")
        .isdigit()
    ]


_SORT_DATA: list[dict] = [
    {"month": "Jan", "revenue": 100.0},
    {"month": "Feb", "revenue": 200.0},
    {"month": "Mar", "revenue": 50.0},
]
_SORT_TARGETS: list[dict] = [
    {"month": "Jan", "target": 10.0},
    {"month": "Feb", "target": 90.0},
    {"month": "Mar", "target": 5.0},
]
_DESC_BY_REVENUE = ChartSort(by="revenue", order="desc")
# Row order is Jan/Feb/Mar; sorted descending by revenue it's Feb(200)/Jan(100)/Mar(50).
_EXPECTED_SORT_ORDER = ["Feb", "Jan", "Mar"]


def test_reconcile_x_domain_noop_when_x_encoding_carries_sort() -> None:
    """``_reconcile_x_domain`` must bail out whenever the shared x encoding
    carries a truthy ``sort`` — mirrors ``pin_categorical_domain_order``'s
    own guard (``emitters/_layers.py``) exactly. Regression for the false
    claim, previously in this function's own docstring, that an authored
    ``chart.sort`` was "reordered upstream of this function" — it is not;
    ``chart_sort_to_vl`` only builds a Vega-Lite ``sort:`` dict, the row
    order this function reads is never touched by it. Without this guard,
    pinning ``scale.domain`` here silently defeats that sort (Vega-Lite
    always prefers an explicit domain over ``sort``)."""
    x_enc: VLDict = {
        "field": "month",
        "type": "nominal",
        "sort": {"field": "revenue", "order": "descending"},
    }
    base_data: list[VLDict] = [
        {"month": "Jan"},
        {"month": "Feb"},
        {"month": "Mar"},
    ]
    layer_x_columns: list[tuple[str, list[VLDict]]] = [
        ("month", [{"month": "Jan"}, {"month": "Feb"}, {"month": "Apr"}])
    ]
    _reconcile_x_domain(x_enc, base_data, layer_x_columns)
    assert "scale" not in x_enc


def test_reconcile_x_domain_still_pins_domain_without_sort() -> None:
    """Negative control for the sort guard above: with NO authored sort,
    ``_reconcile_x_domain`` must still pin the union domain exactly as
    before — the new guard must not disable pinning generally, only when a
    sort is actually present."""
    x_enc: VLDict = {"field": "month", "type": "nominal"}
    base_data: list[VLDict] = [{"month": "Jan"}, {"month": "Feb"}]
    layer_x_columns: list[tuple[str, list[VLDict]]] = [
        ("month", [{"month": "Feb"}, {"month": "Mar"}])
    ]
    _reconcile_x_domain(x_enc, base_data, layer_x_columns)
    assert x_enc["scale"]["domain"] == ["Jan", "Feb", "Mar"]


def test_layered_bar_own_x_layer_with_authored_sort_renders_in_sort_order() -> None:
    """An overlay layer authoring its own ``x:`` field must not defeat an
    authored ``chart.sort`` on a categorical base x. Before the sort guard,
    the layer's authored ``x`` populated ``layer_x_columns``, and
    ``_reconcile_x_domain`` pinned an explicit ``scale.domain`` in raw
    base-query row order — silently overriding the sort. No labels are
    authored anywhere in this chart; the bug is unrelated to value labels.
    """
    layer = LineLayer(type="line", x="month", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], sort=_DESC_BY_REVENUE)
    resolved = resolve(chart, _SORT_DATA, _default_board_style())

    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), _SORT_DATA),
            datasets={"targets": _SORT_TARGETS},
        )
    )
    assert "scale" not in vl["encoding"]["x"] or "domain" not in vl["encoding"][
        "x"
    ].get("scale", {})
    assert _rendered_x_axis_order(vl) == _EXPECTED_SORT_ORDER


def test_layered_bar_own_query_layer_with_authored_sort_renders_in_sort_order() -> None:
    """An overlay layer authoring only its own ``query:`` (no ``x:``) must
    also not defeat an authored ``chart.sort``. This layer shares the base's
    x FIELD name but reads different (query-diverging) rows against it —
    those rows correctly feed the union-domain reconciliation (see
    ``test_unauthored_x_diverging_query_layer_contributes_to_union_domain``
    below), which makes the sort guard load-bearing here too, not just for
    an own-``x`` layer."""
    layer = LineLayer(type="line", y="target", query="targets")
    chart = _bar_normalized(layers=[layer], sort=_DESC_BY_REVENUE)
    resolved = resolve(chart, _SORT_DATA, _default_board_style())

    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), _SORT_DATA),
            datasets={"targets": _SORT_TARGETS},
        )
    )
    assert "scale" not in vl["encoding"]["x"] or "domain" not in vl["encoding"][
        "x"
    ].get("scale", {})
    assert _rendered_x_axis_order(vl) == _EXPECTED_SORT_ORDER


def test_unauthored_x_diverging_query_layer_contributes_to_union_domain() -> None:
    """An overlay layer authoring only its own ``query:`` (no ``x:``) must
    still contribute its own-query rows to the shared x-scale union domain —
    the ``or layer_diverges`` arm of the ``layer_x_columns`` gate in
    ``render_cartesian_overlay``. Before that arm existed, an x-unauthored
    diverging layer contributed NOTHING to ``layer_x_columns``, so a
    layer-only category (present in the layer's own rows on the shared x
    field, absent from the base's) was silently dropped whenever something
    upstream had already pinned the domain to base-only rows — e.g. a
    mixed-sign bar's positive/negative split
    (``pin_categorical_domain_order``, ``emitters/_layers.py``). This test
    pins the union directly: without the arm, ``layer_x_columns`` stays
    empty, ``_reconcile_x_domain`` returns at its first guard, and no
    ``scale.domain`` is set at all — the assertion below fails outright."""
    data = [
        {"month": "Jan", "revenue": 100.0},
        {"month": "Feb", "revenue": 200.0},
    ]
    layer = LineLayer(type="line", y="target", query="targets")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"month": "Jan", "target": 10.0},
        {"month": "Apr", "target": 40.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert domain == ["Jan", "Feb", "Apr"]


def test_unauthored_layer_shares_base_rows_on_year_shaped_x() -> None:
    """A layer authoring nothing at all (no ``query:``, no ``x:``) must
    share the base's OWN rows exactly — not a stale raw lookup from
    ``datasets`` (pre-normalization query rows). Before the fix,
    ``own_data is not None`` was true for this layer too (its resolved
    ``query_name`` defaults to the base's own), so it got an explicit,
    independently-computed ``.data`` block instead of correctly inheriting
    the base's already bucket-normalized rows."""
    data = [
        {"month": "2020", "revenue": 100.0, "target": 5.0},
        {"month": "2021", "revenue": 200.0, "target": 6.0},
        {"month": "2022", "revenue": 50.0, "target": 7.0},
    ]
    layer = LineLayer(type="line", y="target")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, data, _default_board_style())

    vl = translate_to_vl(
        BarEmitter().emit(
            resolved, _DEFAULT_BOX, regroup((), data), datasets={"q": data}
        )
    )
    wrapper = _line_layer_wrapper(vl, "target")
    assert wrapper.get("data") is None
    assert "domain" not in vl["encoding"]["x"].get("scale", {})
    outer_rows = vl["data"]["values"]
    base_rows = vl["layer"][0]["data"]["values"]
    assert len(outer_rows) == len(base_rows) == 3
    assert [row["month"] for row in outer_rows] == [row["month"] for row in base_rows]


def test_unauthored_layer_reconciles_against_gap_filled_base_x() -> None:
    """A layer authoring nothing must share the base's GAP-FILLED rows, not
    the raw pre-gap-fill rows from ``datasets``. The base's own bar mark
    gets a synthetic null row for the missing month (``gap_fill_ordinal_time``
    in ``emitters/bar.py``); before the fix, the overlay's stamped
    ``own_data`` came straight from ``datasets`` (3 rows, no gap), so it
    rendered against a DIFFERENT row set than the base — silently skipping
    the gap instead of showing it."""
    data = [
        {"month": "2024-01-01", "revenue": 100.0, "target": 5.0},
        {"month": "2024-02-01", "revenue": 200.0, "target": 6.0},
        {"month": "2024-04-01", "revenue": 50.0, "target": 7.0},  # March missing
    ]
    layer = LineLayer(type="line", y="target")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, data, _default_board_style())

    vl = translate_to_vl(
        BarEmitter().emit(
            resolved, _DEFAULT_BOX, regroup((), data), datasets={"q": data}
        )
    )
    wrapper = _line_layer_wrapper(vl, "target")
    assert wrapper.get("data") is None
    base_rows = vl["layer"][0]["data"]["values"]
    outer_rows = vl["data"]["values"]
    assert len(base_rows) == 4  # Jan, Feb, synthetic March, Apr
    assert outer_rows == base_rows


def test_layered_bar_plain_categorical_still_unions_without_sort() -> None:
    """Negative control: a genuinely diverging own-``x`` overlay layer with
    NO authored sort must keep pinning the union domain in base row order —
    unaffected by the sort guard added above."""
    data = [
        {"month": "Jan", "revenue": 100.0},
        {"month": "Feb", "revenue": 200.0},
    ]
    layer = LineLayer(type="line", x="quarter", y="target", query="targets")
    chart = _bar_normalized(layers=[layer])
    resolved = resolve(chart, data, _default_board_style())

    targets_rows = [
        {"quarter": "Q1", "target": 90.0},
        {"quarter": "Q2", "target": 95.0},
    ]
    vl = translate_to_vl(
        BarEmitter().emit(
            resolved,
            _DEFAULT_BOX,
            regroup((), data),
            datasets={"targets": targets_rows},
        )
    )
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert domain == ["Jan", "Feb", "Q1", "Q2"]


def test_layered_line_continuous_x_authored_scale_domain_survives() -> None:
    """An authored continuous-x ``scale.domain`` must survive on a chart
    with ``layers:`` — the union/reconcile machinery in this module is
    scoped to CATEGORICAL x scales only (``_CATEGORICAL_X_TYPES``) and must
    never touch a continuous (temporal/quantitative) authored domain, on any
    branch of the identity or sort-guard logic added here."""
    from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
    from dbt_charts.core.compile.models.chart.normalized.line import (
        LineChart as NLineChart,
    )
    from dbt_charts.core.compile.models.style.authored import (
        AxisXStylePatch,
        LineChartStylePatch,
        ScaleContinuousStylePatch,
        XScaleStylePatch,
    )
    from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
    from dbt_charts.core.render.chart.session import BoardRenderSession

    layer = LineLayer(type="line", y="target")
    data = [
        {"date": "2020-01-01", "revenue": 100.0, "target": 90.0},
        {"date": "2021-01-01", "revenue": 200.0, "target": 180.0},
    ]
    chart = NLineChart(
        id="line1",
        type="line",
        x="date",
        y="revenue",
        query=_sql(),
        query_name="q",
        variable_dependencies=set(),
        layers=[layer],
        style=LineChartStylePatch(
            axis_x=AxisXStylePatch(
                scale=XScaleStylePatch(
                    continuous=ScaleContinuousStylePatch(
                        domain=["2019-01-01", "2026-01-01"]
                    )
                )
            )
        ),
    )
    board_rs, board_ctx = resolve_style_and_context(
        get_theme_style(get_default_theme_name())
    )
    resolved = resolve(chart, data, board_ctx)
    session = BoardRenderSession.create(board_rs)
    vl = session.finalize_vl(
        session.emit_chart(resolved, _DEFAULT_BOX, {resolved.query_name: data})
    )
    assert vl["encoding"]["x"]["scale"]["domain"] == ["2019-01-01", "2026-01-01"]
