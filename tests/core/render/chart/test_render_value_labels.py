from __future__ import annotations

from dbt_charts.core.render.chart.spec import RenderBox

_DEFAULT_BOX = RenderBox(width=600.0, height=300.0)
from dbt_charts.core.compile.models.chart.normalized import Chart

"""TDD tests: v2 value-label parity with the v1 oracle.

These tests assert that the v2 render path (emit → features → translate_to_vl)
produces a VL text layer that is byte-identical to the v1 oracle path when
style.marks.<mark>.labels.visible is True.

Families covered: bar (vertical + horizontal), line, scatter, layered.
"""

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context

from ...conftest import chart_pane

SAMPLE_DATA = [{"month": "Jan", "revenue": 100}, {"month": "Feb", "revenue": 200}]
SCATTER_DATA = [{"cost": 100, "revenue": 200}, {"cost": 150, "revenue": 350}]

_DUMMY_QUERY = SqlQuery(sql="SELECT 1", source="test")
_V2_QUERY_REGISTRY: dict[str, Any] = {"q": _DUMMY_QUERY}


def _v2_chart_def(
    chart_type: str, x: str = "x_field", y: str = "y_field", **kwargs: Any
) -> dict[str, Any]:
    """Authored-dict twin of the make_chart fixture, for the normalize_chart path."""
    chart_def: dict[str, Any] = {"type": chart_type, "query": "q"}
    if chart_type in ("arc", "pie"):
        chart_def.update(theta=y, color=x)
    else:
        chart_def.update(x=x, y=y)
    chart_def.update(kwargs)
    return chart_def


@pytest.fixture(autouse=True)
def reset():
    reset_config()
    yield
    reset_config()


def _board_with_bar_labels_visible(visible: bool = True):
    compiled = get_theme_style("clarity")
    new_labels = compiled.charts.marks.bar.labels.model_copy(
        update={"visible": visible}
    )
    new_bar = compiled.charts.marks.bar.model_copy(update={"labels": new_labels})
    new_marks = compiled.charts.marks.model_copy(update={"bar": new_bar})
    charts = compiled.charts.model_copy(update={"marks": new_marks})
    return resolve_style_and_context(compiled.model_copy(update={"charts": charts}))


def _board_with_line_labels_visible(visible: bool = True):
    compiled = get_theme_style("clarity")
    new_labels = compiled.charts.marks.line.labels.model_copy(
        update={"visible": visible}
    )
    new_line = compiled.charts.marks.line.model_copy(update={"labels": new_labels})
    new_marks = compiled.charts.marks.model_copy(update={"line": new_line})
    charts = compiled.charts.model_copy(update={"marks": new_marks})
    return resolve_style_and_context(compiled.model_copy(update={"charts": charts}))


def _board_with_point_labels_visible(visible: bool = True):
    compiled = get_theme_style("clarity")
    new_labels = compiled.charts.marks.point.labels.model_copy(
        update={"visible": visible}
    )
    new_point = compiled.charts.marks.point.model_copy(update={"labels": new_labels})
    new_marks = compiled.charts.marks.model_copy(update={"point": new_point})
    charts = compiled.charts.model_copy(update={"marks": new_marks})
    return resolve_style_and_context(compiled.model_copy(update={"charts": charts}))


def _oracle_vl(
    chart: Chart, data: list[dict[str, Any]], board_style: Any
) -> dict[str, Any]:
    from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

    board_rs, board_ctx = board_style
    return generate_vega_lite_spec(
        chart, data, board_style=board_rs, chart_style_context=board_ctx
    )


def _v2_vl(
    chart_def: dict[str, Any], data: list[dict[str, Any]], board_style: Any
) -> dict[str, Any]:
    from dbt_charts.core.compile.normalize.charts import normalize_chart
    from dbt_charts.core.render.chart.session import BoardRenderSession

    board_rs, board_ctx = board_style
    compiled = normalize_chart("v2chart", chart_def, _V2_QUERY_REGISTRY, sources={})
    resolved = resolve(compiled, data, chart_style_context=board_ctx)
    session = BoardRenderSession.create(board_rs)
    spec = session.emit_chart(resolved, _DEFAULT_BOX, {resolved.query_name: data})
    return session.finalize_vl(spec)


def _has_text_layer(spec: dict[str, Any]) -> bool:
    for lyr in spec.get("layer", []):
        m = lyr.get("mark", {})
        if isinstance(m, dict) and m.get("type") == "text":
            return True
        if isinstance(m, str) and m == "text":
            return True
    return False


def _get_text_layers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    pane = chart_pane(spec)
    return [
        lyr
        for lyr in pane.get("layer", [])
        if isinstance(lyr.get("mark"), dict) and lyr["mark"].get("type") == "text"
    ]


# ---------------------------------------------------------------------------
# Presence/absence gate
# ---------------------------------------------------------------------------


class TestValueLabelPresence:
    """v2 must emit text layer iff labels.visible=True."""

    def test_bar_labels_visible_true_emits_text_layer(self, make_chart):
        board = _board_with_bar_labels_visible(True)
        chart_def = _v2_chart_def("bar", x="month", y="revenue")
        v2 = _v2_vl(chart_def, SAMPLE_DATA, board)
        assert _has_text_layer(v2), (
            f"v2 bar must emit text layer; layers={v2.get('layer')}"
        )

    def test_bar_labels_visible_false_no_text_layer(self, make_chart):
        board = _board_with_bar_labels_visible(False)
        chart_def = _v2_chart_def("bar", x="month", y="revenue")
        v2 = _v2_vl(chart_def, SAMPLE_DATA, board)
        assert not _has_text_layer(v2), (
            "v2 bar must not emit text layer when visible=False"
        )

    def test_line_labels_visible_true_emits_text_layer(self, make_chart):
        board = _board_with_line_labels_visible(True)
        chart_def = _v2_chart_def("line", x="month", y="revenue")
        v2 = _v2_vl(chart_def, SAMPLE_DATA, board)
        assert _has_text_layer(v2), (
            f"v2 line must emit text layer; layers={v2.get('layer')}"
        )

    def test_line_labels_visible_false_no_text_layer(self, make_chart):
        board = _board_with_line_labels_visible(False)
        chart_def = _v2_chart_def("line", x="month", y="revenue")
        v2 = _v2_vl(chart_def, SAMPLE_DATA, board)
        assert not _has_text_layer(v2), (
            "v2 line must not emit text layer when visible=False"
        )

    def test_scatter_labels_visible_true_emits_text_layer(self, make_chart):
        board = _board_with_point_labels_visible(True)
        chart_def = _v2_chart_def("scatter", x="cost", y="revenue")
        v2 = _v2_vl(chart_def, SCATTER_DATA, board)
        assert _has_text_layer(v2), (
            f"v2 scatter must emit text layer; layers={v2.get('layer')}"
        )

    def test_scatter_labels_visible_false_no_text_layer(self, make_chart):
        board = _board_with_point_labels_visible(False)
        chart_def = _v2_chart_def("scatter", x="cost", y="revenue")
        v2 = _v2_vl(chart_def, SCATTER_DATA, board)
        assert not _has_text_layer(v2), (
            "v2 scatter must not emit text layer when visible=False"
        )


# ---------------------------------------------------------------------------
# Parity gate — v2 text-layer must match v1 oracle exactly
# ---------------------------------------------------------------------------


class TestValueLabelParity:
    """v2 text layers must be byte-identical to v1 oracle text layers."""

    def _oracle_text_layers(self, chart, data, board):
        spec = _oracle_vl(chart, data, board)
        return _get_text_layers(spec)

    def _v2_text_layers(self, chart_def, data, board):
        spec = _v2_vl(chart_def, data, board)
        return _get_text_layers(spec)

    def test_bar_horizontal_above_parity(self, make_chart):
        """Horizontal bar (default), position=above → parity."""
        compiled = get_theme_style("clarity")
        new_labels = compiled.charts.marks.bar.labels.model_copy(
            update={"visible": True, "position": "above"}
        )
        new_bar = compiled.charts.marks.bar.model_copy(update={"labels": new_labels})
        new_marks = compiled.charts.marks.model_copy(update={"bar": new_bar})
        charts = compiled.charts.model_copy(update={"marks": new_marks})
        board = resolve_style_and_context(
            compiled.model_copy(update={"charts": charts})
        )
        chart = make_chart("bar", x="month", y="revenue")
        chart_def = _v2_chart_def("bar", x="month", y="revenue")

        oracle_layers = self._oracle_text_layers(chart, SAMPLE_DATA, board)
        v2_layers = self._v2_text_layers(chart_def, SAMPLE_DATA, board)

        assert oracle_layers, "oracle must emit text layer"
        assert v2_layers == oracle_layers, (
            f"v2 text layers must match oracle\nORACLE={oracle_layers}\nV2={v2_layers}"
        )

    def test_bar_vertical_above_parity(self, make_chart):
        """Vertical bar, position=above → parity."""
        compiled = get_theme_style("clarity")
        new_labels = compiled.charts.marks.bar.labels.model_copy(
            update={"visible": True, "position": "above"}
        )
        new_bar = compiled.charts.marks.bar.model_copy(update={"labels": new_labels})
        new_marks = compiled.charts.marks.model_copy(update={"bar": new_bar})
        charts = compiled.charts.model_copy(update={"marks": new_marks})
        board = resolve_style_and_context(
            compiled.model_copy(update={"charts": charts})
        )
        chart = make_chart(
            "bar", x="month", y="revenue", style={"orientation": "vertical"}
        )
        chart_def = _v2_chart_def(
            "bar", x="month", y="revenue", style={"orientation": "vertical"}
        )

        oracle_layers = self._oracle_text_layers(chart, SAMPLE_DATA, board)
        v2_layers = self._v2_text_layers(chart_def, SAMPLE_DATA, board)

        assert oracle_layers, "oracle must emit text layer"
        assert v2_layers == oracle_layers, (
            f"v2 text layers must match oracle\nORACLE={oracle_layers}\nV2={v2_layers}"
        )

    def test_bar_stacked_label_pins_constant_color_parity(self, make_chart):
        """Stacked bar labels: v2 matches the oracle AND pins a constant color.

        Regression — without an explicit ``color: {value: ...}`` the text layer
        inherits the outer nominal color encoding and paints each label in its
        own segment's fill (invisible). Both renderers must pin the constant.
        """
        stacked_data = [
            {"month": "Jan", "channel": "Web", "revenue": 100},
            {"month": "Jan", "channel": "Mobile", "revenue": 60},
            {"month": "Feb", "channel": "Web", "revenue": 120},
            {"month": "Feb", "channel": "Mobile", "revenue": 80},
        ]
        board = _board_with_bar_labels_visible(True)
        chart = make_chart(
            "bar",
            x="month",
            y="revenue",
            color="channel",
            stack="zero",
            style={"bar": {"orientation": "vertical"}},
        )
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            color="channel",
            style={"orientation": "vertical", "stack": "zero"},
        )
        oracle_layers = self._oracle_text_layers(chart, stacked_data, board)
        v2_layers = self._v2_text_layers(chart_def, stacked_data, board)

        assert oracle_layers, "oracle must emit a stacked text layer"
        assert v2_layers == oracle_layers, (
            f"v2 stacked text layers must match oracle\nORACLE={oracle_layers}\nV2={v2_layers}"
        )
        color_enc = v2_layers[0].get("encoding", {}).get("color")
        assert isinstance(color_enc, dict) and "value" in color_enc, (
            "stacked label must pin a constant color, not inherit the series "
            f"field: {color_enc!r}"
        )
        assert "field" not in color_enc, (
            f"stacked label color must be a constant, not a field: {color_enc!r}"
        )

    @pytest.mark.parametrize("position", ["middle", "bottom", "middle_aligned"])
    def test_horizontal_bar_label_position_preserves_sort(self, make_chart, position):
        """V2 hoists label-positioning transforms to the outer spec so y.sort survives.

        A sub-layer transform makes vl-convert drop the outer y.sort (bars render
        alphabetically). V2 moves the __-prefixed transform to the top-level spec:
        the text sub-layer carries NO transform, the outer spec does, and the
        categorical sort is preserved. This intentionally diverges from V1, which
        still emits the transform on the sub-layer (same latent bug).
        """
        compiled = get_theme_style("clarity")
        new_labels = compiled.charts.marks.bar.labels.model_copy(
            update={"visible": True, "position": position}
        )
        new_bar = compiled.charts.marks.bar.model_copy(update={"labels": new_labels})
        new_marks = compiled.charts.marks.model_copy(update={"bar": new_bar})
        charts = compiled.charts.model_copy(update={"marks": new_marks})
        board = resolve_style_and_context(
            compiled.model_copy(update={"charts": charts})
        )
        chart_def = _v2_chart_def("bar", x="month", y="revenue")

        spec = _v2_vl(chart_def, SAMPLE_DATA, board)
        text_layers = _get_text_layers(spec)
        assert text_layers, "v2 must emit a text layer"
        # No transform on the text sub-layer (that is what broke the sort).
        for lyr in text_layers:
            assert "transform" not in lyr, (
                f"text sub-layer must carry no transform: {lyr}"
            )
        # The positioning transform moved to the outer spec.
        assert spec.get("transform"), "outer spec must carry the hoisted transform"
        # The categorical y sort is still present and survives vl-convert.
        y_enc = spec.get("encoding", {}).get("y", {})
        assert y_enc.get("sort"), f"y.sort must be preserved, got {y_enc!r}"

    def test_scatter_top_parity(self, make_chart):
        """Scatter, position=top → parity."""
        compiled = get_theme_style("clarity")
        new_labels = compiled.charts.marks.point.labels.model_copy(
            update={"visible": True, "position": "top"}
        )
        new_point = compiled.charts.marks.point.model_copy(
            update={"labels": new_labels}
        )
        new_marks = compiled.charts.marks.model_copy(update={"point": new_point})
        charts = compiled.charts.model_copy(update={"marks": new_marks})
        board = resolve_style_and_context(
            compiled.model_copy(update={"charts": charts})
        )
        chart = make_chart("scatter", x="cost", y="revenue")
        chart_def = _v2_chart_def("scatter", x="cost", y="revenue")

        oracle_layers = self._oracle_text_layers(chart, SCATTER_DATA, board)
        v2_layers = self._v2_text_layers(chart_def, SCATTER_DATA, board)

        assert oracle_layers, "oracle must emit text layer"
        assert v2_layers == oracle_layers, (
            f"v2 text layers must match oracle\nORACLE={oracle_layers}\nV2={v2_layers}"
        )

    def test_line_top_parity(self, make_chart):
        """Line, position=top → parity (text layers in layered spec)."""
        compiled = get_theme_style("clarity")
        new_labels = compiled.charts.marks.line.labels.model_copy(
            update={"visible": True, "position": "top"}
        )
        new_line_mark = compiled.charts.marks.line.model_copy(
            update={"labels": new_labels}
        )
        new_marks = compiled.charts.marks.model_copy(update={"line": new_line_mark})
        charts = compiled.charts.model_copy(update={"marks": new_marks})
        board = resolve_style_and_context(
            compiled.model_copy(update={"charts": charts})
        )
        chart = make_chart("line", x="month", y="revenue")
        chart_def = _v2_chart_def("line", x="month", y="revenue")

        oracle_layers = self._oracle_text_layers(chart, SAMPLE_DATA, board)
        v2_layers = self._v2_text_layers(chart_def, SAMPLE_DATA, board)

        assert oracle_layers, "oracle must emit text layer"
        assert v2_layers == oracle_layers, (
            f"v2 text layers must match oracle\nORACLE={oracle_layers}\nV2={v2_layers}"
        )


# ---------------------------------------------------------------------------
# Overlay layers — each typed layer gets its OWN value-label text layer when
# its OWN mark style enables labels.visible, using its OWN data (query_name).
# ---------------------------------------------------------------------------

DATA_WITH_TARGET = [
    {"month": "Jan", "revenue": 100, "target": 90},
    {"month": "Feb", "revenue": 200, "target": 180},
]


def _plain_board():
    """Board with all mark labels off (default theme state)."""
    return resolve_style_and_context(get_theme_style("clarity"))


def _v2_vl_multi(
    chart_def: dict[str, Any],
    base_data: list[dict[str, Any]],
    extra_datasets: dict[str, list[dict[str, Any]]],
    board_style: Any,
) -> dict[str, Any]:
    """Like ``_v2_vl`` but supports layers reading from their OWN named query."""
    from dbt_charts.core.compile.normalize.charts import normalize_chart
    from dbt_charts.core.render.chart.session import BoardRenderSession

    registry: dict[str, Any] = dict(_V2_QUERY_REGISTRY)
    for name in extra_datasets:
        registry.setdefault(name, _DUMMY_QUERY)
    board_rs, board_ctx = board_style
    compiled = normalize_chart("v2chart", chart_def, registry, sources={})
    resolved = resolve(compiled, base_data, chart_style_context=board_ctx)
    session = BoardRenderSession.create(board_rs)
    datasets = {resolved.query_name: base_data, **extra_datasets}
    spec = session.emit_chart(resolved, _DEFAULT_BOX, datasets)
    return session.finalize_vl(spec)


class TestOverlayLayerValueLabels:
    """Each overlay layer's own labels.visible fires its own text layer."""

    def test_only_line_layer_labels_visible_emits_only_for_layer(self, make_chart):
        """Base bar labels off; only the line layer's own style enables labels.

        Only the line layer's data points get a text layer — the base gets
        none. The layer has no own label format, so label_is_house=False and
        the text encoding references the raw "target" field directly (no
        calculate transform, no house register).
        """
        board = _plain_board()
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            layers=[
                {
                    "type": "line",
                    "y": "target",
                    "style": {"marks": {"line": {"labels": {"visible": True}}}},
                }
            ],
        )
        vl = _v2_vl(chart_def, DATA_WITH_TARGET, board)
        text_layers = _get_text_layers(vl)
        assert len(text_layers) == 1, f"expected exactly one text layer: {vl['layer']}"
        assert text_layers[0]["encoding"]["text"]["field"] == "target"

    def test_layer_label_uses_own_query_dataset_not_base(self, make_chart):
        """A layer with its own `query:` must label from THAT dataset — a
        per-layer-query chart must not leak the base chart's rows onto the
        layer's own value-label layer.

        The layer has no own label format, so label_is_house=False and the
        text encoding references the raw "target" field. The dataset check
        (not the field name) is what this test pins."""
        board = _plain_board()
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            layers=[
                {
                    "type": "line",
                    "y": "target",
                    "query": "layer_q",
                    "style": {"marks": {"line": {"labels": {"visible": True}}}},
                }
            ],
        )
        layer_rows = [{"month": "Jan", "target": 999}]
        vl = _v2_vl_multi(chart_def, SAMPLE_DATA, {"layer_q": layer_rows}, board)
        text_layers = _get_text_layers(vl)
        assert len(text_layers) == 1
        label = text_layers[0]
        assert label["encoding"]["text"]["field"] == "target"
        assert label.get("data", {}).get("values") == layer_rows, (
            f"label must read the layer's own dataset, got {label.get('data')}"
        )

    def test_base_labels_with_unlabeled_layer_present_still_apply(self, make_chart):
        """Base chart labels visible, overlay layer present but NOT labeled.

        Regression guard: an overlay layer must not suppress the base chart's
        own value labels. The base chart's label format resolves to the
        theme's SI default, so it takes the narrative house register — a
        computed field, not 'revenue' directly (unlike an overlay layer's own
        labels, which never inherit the base axis's format fallback and stay
        unset here — see compile/resolve/_layers.py)."""
        board = _board_with_bar_labels_visible(True)
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            layers=[{"type": "line", "y": "target"}],
        )
        vl = _v2_vl(chart_def, DATA_WITH_TARGET, board)
        text_layers = _get_text_layers(vl)
        assert len(text_layers) == 1, f"expected exactly one text layer: {vl['layer']}"
        assert text_layers[0]["encoding"]["text"]["field"] == "__value_label_text"

    def test_base_and_layer_labels_both_visible_both_render(self, make_chart):
        """Both base and an overlay layer enable labels — both get their own
        correct, non-conflicting text layers.

        The base chart's label format resolves to the theme's SI default
        (narrative house register -> __value_label_text). The overlay layer
        has no own label format, so label_is_house=False and its text
        encoding references the raw "target" field directly (no calculate
        transform). The two sublayers are non-conflicting because each
        carries its own local y.field (revenue vs target)."""
        board = _board_with_bar_labels_visible(True)
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            layers=[
                {
                    "type": "line",
                    "y": "target",
                    "style": {"marks": {"line": {"labels": {"visible": True}}}},
                }
            ],
        )
        vl = _v2_vl(chart_def, DATA_WITH_TARGET, board)
        text_layers = _get_text_layers(vl)
        assert len(text_layers) == 2, f"expected both labels: {text_layers}"
        text_fields = {t["encoding"]["text"]["field"] for t in text_layers}
        assert "__value_label_text" in text_fields, (
            f"base chart label must use narrative register: {text_layers}"
        )
        assert "target" in text_fields, (
            f"overlay layer label must reference raw field (no format): {text_layers}"
        )
        y_fields = sorted(t["encoding"]["y"]["field"] for t in text_layers)
        assert y_fields == ["revenue", "target"], (
            f"expected one sublayer per measure: {text_layers}"
        )


# ---------------------------------------------------------------------------
# Stacked bar + layers: value-label stack ordering
# ---------------------------------------------------------------------------

_STACKED_LAYER_DATA = [
    {"month": "Jan", "channel": "Web", "revenue": 90},
    {"month": "Jan", "channel": "Mobile", "revenue": 10},
    # Feb inverts the series order — labels mis-pair without shared ordering.
    {"month": "Feb", "channel": "Web", "revenue": 20},
    {"month": "Feb", "channel": "Mobile", "revenue": 80},
]
# Date-format x values trigger gap-fill, which stamps .data on the bar spec before
# render_cartesian_overlay runs. The fix clears that .data so the bar sublayer
# inherits the outer transforms (including __df_series_order).
_STACKED_LAYER_DATE_DATA = [
    {"month": "2024-01-01", "channel": "Web", "revenue": 90},
    {"month": "2024-01-01", "channel": "Mobile", "revenue": 10},
    {"month": "2024-02-01", "channel": "Web", "revenue": 20},
    {"month": "2024-02-01", "channel": "Mobile", "revenue": 80},
]
_DF_SERIES_ORDER_KEY = "__df_series_order"


class TestStackedBarLayersValueLabelPairing:
    """Stacked bar value labels must pair with the correct segment when ``layers:`` is present.

    Without the fix the outer spec carries only ``x`` — the bar sublayer holds
    ``order`` locally and the text-label sublayer computes its own independent
    stack, mispairing labels.  After the fix ``order`` and its calculate transform
    are elevated to the outer spec so bar and label sublayers inherit one shared
    stack ordering.  Overlay line/area layers explicitly opt out (``order: null``)
    so they do not inherit the stacked-bar ordering which would reorder line paths.
    """

    def _stacked_bar_with_layer_vl(self) -> dict[str, Any]:
        board = _board_with_bar_labels_visible(True)
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            color="channel",
            style={"stack": "zero"},
            layers=[{"type": "line", "y": "revenue"}],
        )
        return _v2_vl(chart_def, _STACKED_LAYER_DATA, board)

    def test_order_encoding_elevated_to_outer_spec(self):
        """order encoding must be at the outer pane level so all sublayers share it."""
        vl = self._stacked_bar_with_layer_vl()
        pane = chart_pane(vl)
        outer_enc = pane.get("encoding", {})
        assert "order" in outer_enc, (
            "order encoding must be elevated to the outer spec for shared stacking; "
            f"outer encoding keys: {list(outer_enc)}"
        )

    def test_series_order_transform_elevated_to_outer_spec(self):
        """__df_series_order calculate transform must be at the outer pane level."""
        vl = self._stacked_bar_with_layer_vl()
        pane = chart_pane(vl)
        order_ts = [
            t for t in pane.get("transform", []) if t.get("as") == _DF_SERIES_ORDER_KEY
        ]
        assert order_ts, (
            "__df_series_order transform must be at the outer spec level; "
            f"outer transforms: {pane.get('transform', [])}"
        )

    def test_overlay_layer_opts_out_of_order(self):
        """Overlay line/area wrappers must explicitly null out the inherited order.

        Pinning CRITICAL: on a line, 'order' controls point-connection order, not
        z-order — inheriting __df_series_order would connect segments in wrong order.
        The outer spec carries order; overlays override it with null.
        """
        vl = self._stacked_bar_with_layer_vl()
        pane = chart_pane(vl)
        # Overlay wrappers are the nested layered specs — sublayers that have
        # their own "layer" key (not a bare mark type).
        overlay_wrappers = [lyr for lyr in pane.get("layer", []) if "layer" in lyr]
        assert overlay_wrappers, "expected at least one overlay wrapper layer"
        for wrapper in overlay_wrappers:
            enc = wrapper.get("encoding", {})
            assert "order" in enc and enc["order"] is None, (
                "overlay wrapper must have order:null to opt out of the outer "
                f"stacked-bar ordering; got encoding: {enc}"
            )

    def test_bar_sublayer_has_no_own_data_when_gap_fill_fires(self):
        """Bar sublayer must not carry its own data even when gap-fill stamps it.

        Pinning CRITICAL: bar.py stamps spec.data before calling render_cartesian_overlay
        when gap_fill fires (date-shaped x). render_cartesian_overlay must clear it so
        the bar sublayer inherits the outer transforms (including __df_series_order).
        A sublayer with its own .data does not receive the parent's transform cascade.
        """
        board = _board_with_bar_labels_visible(True)
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            color="channel",
            style={"stack": "zero"},
            layers=[{"type": "line", "y": "revenue"}],
        )
        vl = _v2_vl(chart_def, _STACKED_LAYER_DATE_DATA, board)
        pane = chart_pane(vl)
        layers = pane.get("layer", [])
        assert layers, "expected sublayers in outer pane"
        bar_sublayer = layers[0]
        assert "data" not in bar_sublayer, (
            "bar sublayer must not own its data (so it inherits the outer "
            "__df_series_order transform); if data is present the transform is "
            "inaccessible and the bar stacks independently of the text label"
        )

    def test_mixed_sign_stacked_bar_with_layers_hoists_order_and_transform(self):
        """Mixed-sign data triggers _layers.py's sign-split (base ChartSpec mark='layered').

        In that path the order calculate lives inside each sign sub-layer, not on the
        outer spec's transforms list. render_cartesian_overlay must hoist both the
        order encoding AND its calculate transform from the sub-layers to the outer spec.
        Assert both are present so a future edit cannot silently break the sign-split path.
        """
        board = _board_with_bar_labels_visible(True)
        chart_def = _v2_chart_def(
            "bar",
            x="month",
            y="revenue",
            color="channel",
            style={"stack": "zero"},
            layers=[{"type": "line", "y": "revenue"}],
        )
        mixed_sign = [
            {"month": "Jan", "channel": "Web", "revenue": 90},
            {"month": "Jan", "channel": "Mobile", "revenue": -10},
            {"month": "Feb", "channel": "Web", "revenue": 20},
            {"month": "Feb", "channel": "Mobile", "revenue": -80},
        ]
        vl = _v2_vl(chart_def, mixed_sign, board)
        pane = chart_pane(vl)
        assert "order" in pane.get("encoding", {}), (
            "order encoding must be hoisted to the outer spec on the sign-split path; "
            f"outer encoding keys: {list(pane.get('encoding', {}))}"
        )
        order_ts = [
            t for t in pane.get("transform", []) if t.get("as") == _DF_SERIES_ORDER_KEY
        ]
        assert order_ts, (
            "__df_series_order calculate transform must be hoisted from sign-split "
            "sub-layers to the outer spec; without it the order field is undefined "
            f"outer transforms: {pane.get('transform', [])}"
        )

    def test_feb_value_labels_land_in_correct_segment(self):
        """Each value label must sit inside the correct stacked segment in the SVG.

        The discriminating case is Feb (Web=20 baseline, Mobile=80 on top):
        - Web has the higher total (110 vs 90) so it is the baseline/bottom series.
        - After the fix, label '20' sits in the lower Web segment (higher SVG y)
          and label '80' sits in the upper Mobile segment (lower SVG y).
        - Before the fix the text sublayer stacks independently and the ordering
          inverts: '80' lands at the bottom, '20' at the top.

        Fails before the fix (y('20') < y('80')) and passes after.
        """
        import json
        import re
        import xml.etree.ElementTree as ET

        vl_convert = pytest.importorskip("vl_convert")

        vl = self._stacked_bar_with_layer_vl()
        svg = ET.fromstring(vl_convert.vegalite_to_svg(json.dumps(vl)))
        ns = "http://www.w3.org/2000/svg"

        def _translate_y(transform: str) -> float:
            m = re.match(r"translate\([^,]+,([^)]+)\)", transform)
            assert m, f"unexpected transform format: {transform!r}"
            return float(m.group(1))

        all_labels: list[str] = []
        label_ys: dict[str, float] = {}
        for g in svg.iter(f"{{{ns}}}g"):
            if "mark-text" in g.get("class", "") and "role-mark" in g.get("class", ""):
                for text in g.iter(f"{{{ns}}}text"):
                    content = (text.text or "").strip()
                    if content:
                        all_labels.append(content)
                    if content in ("20", "80"):
                        label_ys[content] = _translate_y(text.get("transform", ""))

        # 4 segments (2 months × 2 series) → 4 labels drawn.
        assert len(all_labels) == 4, (
            f"Expected 4 value labels (2 months × 2 series), got {len(all_labels)}: {all_labels}"
        )
        assert "20" in label_ys and "80" in label_ys, (
            f"Could not find both Feb labels in SVG: found {list(label_ys)}"
        )
        # Web=20 is the baseline (bottom) series → higher SVG y (lower on screen).
        # Mobile=80 is the top series → lower SVG y (higher on screen).
        assert label_ys["20"] > label_ys["80"], (
            "Label '20' (Web, baseline) must sit below label '80' (Mobile, top) — "
            "higher SVG y means lower on screen. Before the fix the text sublayer "
            "stacks independently and the two labels swap segments. "
            f"Got y('20')={label_ys['20']:.1f}, y('80')={label_ys['80']:.1f}"
        )

    def test_value_label_sublayer_inherits_outer_order(self):
        """Value-label text sublayer must inherit the outer spec's order encoding.

        Before the fix the outer spec had no order (only the bar sublayer had it),
        so the text sublayer stacked independently and mismatched segments. After the
        fix the outer spec carries order and the text sublayer — having no own order
        override — inherits it, giving the same stack as the bar.

        This test fails before the fix (outer has no order → assertion 1 fails) and
        passes after (outer has order AND text sublayer does not override it).
        """
        vl = self._stacked_bar_with_layer_vl()
        pane = chart_pane(vl)

        outer_enc = pane.get("encoding", {})
        assert "order" in outer_enc, (
            "outer spec must carry order encoding so the text label sublayer can "
            "inherit it; without outer order the text layer stacks independently "
            f"and mismatches segments. Outer encoding keys: {list(outer_enc)}"
        )

        text_sublayers = [
            lyr
            for lyr in pane.get("layer", [])
            if (isinstance(lyr.get("mark"), dict) and lyr["mark"].get("type") == "text")
            or lyr.get("mark") == "text"
        ]
        assert text_sublayers, (
            "expected at least one text-mark sublayer for value labels"
        )
        for lyr in text_sublayers:
            enc = lyr.get("encoding", {})
            assert "order" not in enc, (
                "text/label sublayer must not have its own order encoding — "
                "it must inherit the outer spec's order for correct label-to-segment "
                f"pairing; got sublayer encoding keys: {list(enc)}"
            )
