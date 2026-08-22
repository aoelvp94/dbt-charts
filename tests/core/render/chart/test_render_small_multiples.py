"""V2 render path: ``multiples:`` compiles to a Vega-Lite ``facet`` spec.

Small multiples partition a single cartesian grammar by a ``rows`` field
(vertical stack), a ``columns`` field (side by side), or both (grid). Panels
share one measure scale by default; the facet value reads as a header label
(left for rows, top for columns), not a per-panel title. The both-edge y-axis
(mirror) auto-enables when there is more than one column, by defaulting the ONE
shipped ``resolved_axis_y.mirror`` flag — no second mirror mechanism.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    Chart,
    LineChart,
)
from dbt_charts.core.compile.models.chart.resolved._partition import PartitionAxis
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.render.chart.spec import RenderBox

_DEFAULT_BOX = RenderBox(width=600.0, height=300.0)


@pytest.fixture(autouse=True)
def reset():
    reset_config()
    yield
    reset_config()


def _board() -> Any:
    return resolve_style_and_context(get_theme_style("editorial"))


def _v2_vl(norm: Chart, data: list[dict[str, Any]]) -> dict[str, Any]:
    from dbt_charts.core.compile.resolve import resolve
    from dbt_charts.core.render.chart.session import BoardRenderSession

    board_rs, board_ctx = _board()
    resolved = resolve(norm, data, chart_style_context=board_ctx)
    session = BoardRenderSession.create(board_rs)
    return session.finalize_vl(
        session.emit_chart(resolved, _DEFAULT_BOX, {resolved.query_name: data})
    )


def _grid_data() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region in ("West", "East", "North"):
        for product in ("Widgets", "Gadgets"):
            for month in range(6):
                rows.append(
                    {
                        "month": month,
                        "region": region,
                        "product": product,
                        "revenue": 100 + month * 5,
                        "cost": 40 + month * 2,
                    }
                )
    return rows


def _row_data() -> list[dict[str, Any]]:
    return [
        {"month": m, "region": r, "revenue": 100 + m * 5}
        for r in ("West", "East", "North")
        for m in range(6)
    ]


def _grouped_horizontal_bar_data() -> list[dict[str, Any]]:
    return [
        {"quarter": q, "region": region, "segment": segment, "revenue": 100 + i * 5}
        for i, (region, segment, q) in enumerate(
            (region, segment, q)
            for region in ("West", "East")
            for segment in ("A", "B")
            for q in ("Q1", "Q2")
        )
    ]


def _lopsided_row_data() -> list[dict[str, Any]]:
    """Two panels whose measure ranges barely overlap — under one shared scale
    the East panel's bars are a smear against West's 200."""
    return [
        {"product": product, "region": region, "revenue": revenue, "target": target}
        for region, values in (
            (
                "West",
                (("Widgets", 200, 180), ("Gadgets", 120, 140), ("Doodads", 10, 12)),
            ),
            ("East", (("Widgets", 8, 9), ("Gadgets", 6, 5), ("Doodads", 5, 7))),
        )
        for product, revenue, target in values
    ]


def _bar(
    multiples: dict[str, Any],
    orientation: Literal["vertical", "horizontal"],
    **extra: Any,
) -> BarChart:
    return BarChart.model_validate(
        {
            "id": "t",
            "type": "bar",
            "query_name": "q",
            "x": "product",
            "y": "revenue",
            "multiples": multiples,
            "style": {"orientation": orientation},
            **extra,
        }
    )


def _area(multiples: dict[str, Any], **extra: Any) -> AreaChart:
    return AreaChart.model_validate(
        {
            "id": "t",
            "type": "area",
            "query_name": "q",
            "x": "month",
            "y": "revenue",
            "multiples": multiples,
            **extra,
        }
    )


def _y_axis_orients(spec: dict[str, Any]) -> set[str]:
    """All y-axis orient values across the spec's layers + top level."""
    found: set[str] = set()

    def walk(s: dict[str, Any]) -> None:
        enc = s.get("encoding")
        if isinstance(enc, dict) and isinstance(enc.get("y"), dict):
            axis = enc["y"].get("axis")
            if isinstance(axis, dict) and axis.get("orient"):
                found.add(axis["orient"])
        for lyr in s.get("layer", []):
            if isinstance(lyr, dict):
                walk(lyr)

    walk(spec)
    return found


class TestFacetStructure:
    def test_rows_only_emits_facet_row(self):
        spec = _v2_vl(_area({"rows": "region"}), _row_data())
        facet = spec.get("facet")
        assert isinstance(facet, dict), f"expected top-level facet, got {spec.keys()}"
        assert facet.get("row", {}).get("field") == "region"
        assert "column" not in facet
        assert isinstance(spec.get("spec"), dict), "unit spec nested under 'spec'"

    def test_columns_only_emits_facet_column(self):
        """Columns-only: a horizontal strip of panels — facet.column, no row."""
        spec = _v2_vl(_area({"columns": "region"}), _row_data())
        facet = spec.get("facet", {})
        assert facet.get("column", {}).get("field") == "region"
        assert "row" not in facet

    def test_both_emit_facet_row_and_column(self):
        spec = _v2_vl(_area({"rows": "region", "columns": "product"}), _grid_data())
        facet = spec.get("facet", {})
        assert facet.get("row", {}).get("field") == "region"
        assert facet.get("column", {}).get("field") == "product"

    def test_row_header_label_is_left(self):
        """The row facet value reads as a left row-header, not a per-panel title."""
        spec = _v2_vl(_area({"rows": "region"}), _row_data())
        header = spec["facet"]["row"].get("header", {})
        assert header.get("orient") == "left"
        assert not spec.get("spec", {}).get("title")

    def test_chart_title_frames_whole_set(self):
        """A chart-level title belongs on the facet root, not the inner panel spec."""
        spec = _v2_vl(_area({"rows": "region"}, title="Revenue by region"), _row_data())
        assert "title" in spec, "chart title should sit on the facet root"
        assert not spec.get("spec", {}).get("title"), "not repeated on inner panels"


class TestFacetScale:
    def test_shared_scale_by_default(self):
        spec = _v2_vl(_area({"rows": "region"}), _row_data())
        assert spec.get("resolve", {}).get("scale", {}).get("y") != "independent"

    def test_independent_scale_emits_resolve(self):
        spec = _v2_vl(_area({"rows": "region", "scale": "independent"}), _row_data())
        assert spec.get("resolve", {}).get("scale", {}).get("y") == "independent"

    def test_horizontal_bar_independent_scale_frees_the_measure_channel(self):
        """`scale: independent` frees the MEASURE scale, and a horizontal bar
        renders its measure on VL x (the category lands on VL y). Resolving y
        instead leaves every panel sharing one measure domain — the exact thing
        the author asked to stop sharing — while freeing a category scale that
        was never the point."""
        spec = _v2_vl(
            _bar({"rows": "region", "scale": "independent"}, "horizontal"),
            _lopsided_row_data(),
        )
        scale_resolve = spec.get("resolve", {}).get("scale", {})
        assert scale_resolve.get("x") == "independent"
        assert scale_resolve.get("y") != "independent"

    def test_horizontal_bar_with_layers_still_frees_the_measure_channel(self):
        """An authored `layers:` overlay hands back a fresh ChartSpec, so a
        measure channel stamped by the emitter would be lost by the time the
        facet wrap reads it."""
        chart = _bar(
            {"rows": "region", "scale": "independent"},
            "horizontal",
            layers=[{"type": "line", "x": "revenue", "y": "target"}],
        )
        spec = _v2_vl(chart, _lopsided_row_data())
        scale_resolve = spec.get("resolve", {}).get("scale", {})
        assert scale_resolve.get("x") == "independent"
        assert scale_resolve.get("y") != "independent"

    def test_vertical_bar_independent_scale_frees_the_measure_channel(self):
        spec = _v2_vl(
            _bar({"rows": "region", "scale": "independent"}, "vertical"),
            _lopsided_row_data(),
        )
        scale_resolve = spec.get("resolve", {}).get("scale", {})
        assert scale_resolve.get("y") == "independent"
        assert scale_resolve.get("x") != "independent"


class TestFacetMirrorDefault:
    def test_rows_only_does_not_mirror(self):
        """One column (row stack) → no both-edge auto-default."""
        spec = _v2_vl(_area({"rows": "region"}), _row_data())
        assert len(_y_axis_orients(spec["spec"])) == 1

    def test_columns_auto_mirror_both_edges(self):
        """Columns present → the measure axis mirrors to the far edge (shared scale)."""
        spec = _v2_vl(_area({"columns": "region"}), _row_data())
        assert {"left", "right"} <= _y_axis_orients(spec["spec"])

    def test_grid_auto_mirrors_both_edges(self):
        spec = _v2_vl(_area({"rows": "region", "columns": "product"}), _grid_data())
        assert {"left", "right"} <= _y_axis_orients(spec["spec"])

    def test_mirror_does_not_proliferate_axes_under_facet(self):
        """Both-edge under facet must not redraw the shared measure axis on every
        layer (the overpainting bug). The shared-encoding y-axis is isolated onto
        one layer so exactly the two outer edges render, not one per layer/panel."""
        spec = _v2_vl(_area({"columns": "region"}), _row_data())
        unit = spec["spec"]
        # Shared encoding y-axis stripped → layers can't inherit-and-multiply it.
        shared_y = unit.get("encoding", {}).get("y") or {}
        assert shared_y.get("axis") is None, (
            "shared y-axis must be isolated off encoding"
        )
        # Exactly the two outer edges are declared, each by a single layer.
        edges = [
            lyr["encoding"]["y"]["axis"]["orient"]
            for lyr in unit.get("layer", [])
            if isinstance(
                ((lyr.get("encoding", {}) or {}).get("y", {}) or {}).get("axis"), dict
            )
            and lyr["encoding"]["y"]["axis"].get("orient") in ("left", "right")
        ]
        assert sorted(edges) == [
            "left",
            "right",
        ], f"expected 2 outer edges, got {edges}"

    def test_explicit_mirror_false_wins_with_columns(self):
        """Explicit author intent always wins: mirror:false stays off with columns."""
        spec = _v2_vl(
            _area(
                {"rows": "region", "columns": "product"},
                style={"axis_y": {"mirror": False}},
            ),
            _grid_data(),
        )
        assert len(_y_axis_orients(spec["spec"])) == 1

    def test_horizontal_grouped_bar_columns_keeps_mirrored_axis_despite_authored_endpoint_labels(
        self,
    ):
        """Regression: a horizontal, grouped (stack: none) bar's endpoint-label
        rail never renders regardless of `endpoint_labels.visible` — grouped bars
        are excluded by `EndpointLabelFeature.applies_to`'s own
        `chart.stack not in (None, "none")` check. Predicting "the rail will
        render" from the authored flag alone (without that orientation- and
        stack-dependent condition, which isn't resolved until after this bake)
        used to wrongly suppress the auto-mirror default here, silently dropping
        the chart's far-edge y-axis even though nothing ever collided with it.
        The auto-mirror default must not depend on that prediction at all."""
        chart = BarChart.model_validate(
            {
                "id": "t",
                "type": "bar",
                "query_name": "q",
                "x": "quarter",
                "y": "revenue",
                "color": "segment",
                "stack": "none",
                "multiples": {"columns": "region"},
                "style": {
                    "orientation": "horizontal",
                    "endpoint_labels": {"visible": True},
                },
            }
        )
        spec = _v2_vl(chart, _grouped_horizontal_bar_data())
        assert {"left", "right"} <= _y_axis_orients(spec["spec"])


class TestFacetValidation:
    def test_scale_independent_plus_mirror_raises(self):
        """Fires the typed ERR-MULTIPLES-INDEPENDENT-SCALE-MIRROR code, never
        the ERR-INTERNAL fallback."""
        from dbt_charts.core.diagnostics.codes_render import (
            ERR_MULTIPLES_INDEPENDENT_SCALE_MIRROR,
        )

        chart = _area(
            {"rows": "region", "columns": "product", "scale": "independent"},
            style={"axis_y": {"mirror": True}},
        )
        with pytest.raises(
            ChartDataError, match="each panel has its own scale"
        ) as exc_info:
            _v2_vl(chart, _grid_data())
        assert exc_info.value.code is ERR_MULTIPLES_INDEPENDENT_SCALE_MIRROR

    def test_scale_independent_plus_mirror_format_override_raises(self):
        """The scale-independent/mirror contradiction must also fire for the
        object form (mirror: {format: ...}) — an AxisMirrorStyle override still
        turns mirroring on, it just also relabels the mirrored edge."""
        chart = _area(
            {"rows": "region", "columns": "product", "scale": "independent"},
            style={"axis_y": {"mirror": {"format": ".0%"}}},
        )
        with pytest.raises(ChartDataError, match="each panel has its own scale"):
            _v2_vl(chart, _grid_data())


class TestAuthoredSurface:
    """The authored surface is object-only: rows and/or columns (at least one)."""

    def test_rows_only(self):
        from dbt_charts.core.compile.models.chart.authored import (
            AreaChart as AuthoredArea,
            MultiplesConfig,
        )

        chart = AuthoredArea.model_validate(
            {
                "id": "t",
                "type": "area",
                "x": "month",
                "y": "revenue",
                "multiples": {"rows": "region"},
            }
        )
        assert isinstance(chart.multiples, MultiplesConfig)
        assert chart.multiples.rows == "region"
        assert chart.multiples.columns is None
        assert chart.multiples.scale == "shared"

    def test_columns_only(self):
        from dbt_charts.core.compile.models.chart.authored import (
            AreaChart as AuthoredArea,
        )

        chart = AuthoredArea.model_validate(
            {
                "id": "t",
                "type": "area",
                "x": "month",
                "y": "revenue",
                "multiples": {"columns": "product"},
            }
        )
        assert chart.multiples is not None
        assert chart.multiples.rows is None
        assert chart.multiples.columns == "product"

    def test_both_with_independent_scale(self):
        from dbt_charts.core.compile.models.chart.authored import (
            AreaChart as AuthoredArea,
        )

        chart = AuthoredArea.model_validate(
            {
                "id": "t",
                "type": "area",
                "x": "month",
                "y": "revenue",
                "multiples": {
                    "rows": "region",
                    "columns": "product",
                    "scale": "independent",
                },
            }
        )
        assert chart.multiples is not None
        assert chart.multiples.rows == "region"
        assert chart.multiples.columns == "product"
        assert chart.multiples.scale == "independent"

    def test_empty_multiples_raises(self):
        """Neither rows nor columns → error (at least one required)."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.chart.authored import (
            AreaChart as AuthoredArea,
        )

        with pytest.raises(
            ValidationError, match="at least one of `rows` or `columns`"
        ):
            AuthoredArea.model_validate(
                {
                    "id": "t",
                    "type": "area",
                    "x": "month",
                    "y": "revenue",
                    "multiples": {"scale": "shared"},
                }
            )

    def test_pie_rejects_multiples(self):
        """multiples is cartesian-only — a non-cartesian family rejects it via
        extra='forbid' (small multiples has no meaning on an arc chart)."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.chart.authored import PieChart

        with pytest.raises(ValidationError):
            PieChart.model_validate(
                {
                    "id": "t",
                    "type": "pie",
                    "theta": "revenue",
                    "multiples": {"rows": "region"},
                }
            )


class TestFacetChartTypes:
    def test_line_faceted(self):
        chart = LineChart.model_validate(
            {
                "id": "t",
                "type": "line",
                "query_name": "q",
                "x": "month",
                "y": "revenue",
                "multiples": {"rows": "region"},
            }
        )
        spec = _v2_vl(chart, _row_data())
        assert spec.get("facet", {}).get("row", {}).get("field") == "region"

    def test_heatmap_grid_does_not_auto_mirror(self):
        """Heatmap y is categorical — a both-edge (mirror) axis is meaningless, so
        the auto-default must NOT fire even with columns."""
        from dbt_charts.core.compile.models.chart.normalized import HeatmapChart

        chart = HeatmapChart.model_validate(
            {
                "id": "t",
                "type": "heatmap",
                "query_name": "q",
                "x": "month",
                "y": "region",
                "color": "revenue",
                "multiples": {"rows": "region", "columns": "product"},
            }
        )
        spec = _v2_vl(chart, _grid_data())
        assert "right" not in _y_axis_orients(spec["spec"])


def _colour_series_chart(chart_type: str, multiples: dict[str, Any], **extra: Any):
    """A faceted cartesian chart whose colour channel is a second dimension —
    the shape that has series needing names once the panels are drawn."""
    cls = {"area": AreaChart, "bar": BarChart, "line": LineChart}[chart_type]
    return cls.model_validate(
        {
            "id": "t",
            "type": chart_type,
            "query_name": "q",
            "x": "month",
            "y": "revenue",
            "color": "product",
            "multiples": multiples,
            **extra,
        }
    )


def _colour_legend(spec: dict[str, Any]) -> dict[str, Any]:
    """The colour legend from a faceted spec's unit spec."""
    unit = spec["spec"]
    legend = unit["encoding"]["color"].get("legend")
    assert isinstance(legend, dict), f"no colour legend on the unit spec: {legend!r}"
    return legend


_MULTIPLES_AXES = [{"rows": "region"}, {"columns": "region"}]
_COLOUR_SERIES_FAMILIES = [
    ("area", {}),
    ("bar", {}),
    ("bar", {"style": {"stack": "zero"}}),
    ("line", {}),
]


class TestMultiplesColourSeriesTopLegend:
    """Faceting takes away the endpoint-label rail, so the legend has to name the
    series instead — and it goes above the panels, where one legend reads across
    the whole grid, rather than down a rail beside whichever panel it lands next
    to."""

    @pytest.mark.parametrize("multiples", _MULTIPLES_AXES, ids=lambda m: str(m))
    @pytest.mark.parametrize(
        ("chart_type", "extra"), _COLOUR_SERIES_FAMILIES, ids=lambda v: str(v)
    )
    def test_colour_series_gets_a_top_horizontal_legend(
        self, chart_type: str, extra: dict[str, Any], multiples: dict[str, Any]
    ) -> None:
        spec = _v2_vl(
            _colour_series_chart(chart_type, multiples, **extra), _grid_data()
        )
        legend = _colour_legend(spec)
        assert legend.get("orient") == "top"
        assert legend.get("direction") == "horizontal"

    @pytest.mark.parametrize("multiples", _MULTIPLES_AXES, ids=lambda m: str(m))
    @pytest.mark.parametrize(
        ("chart_type", "extra"), _COLOUR_SERIES_FAMILIES, ids=lambda v: str(v)
    )
    def test_colour_series_renders_instead_of_refusing(
        self, chart_type: str, extra: dict[str, Any], multiples: dict[str, Any]
    ) -> None:
        """line and area ship the rail on by default; the default steps aside for
        `multiples:` on every family rather than the composition being refused."""
        spec = _v2_vl(
            _colour_series_chart(chart_type, multiples, **extra), _grid_data()
        )
        assert isinstance(spec.get("facet"), dict)

    @pytest.mark.parametrize("chart_type", ["area", "bar", "line"])
    def test_authored_endpoint_labels_still_refuse(self, chart_type: str) -> None:
        """Steering a default is not overriding an author. Someone who wrote the
        rail on for a faceted chart still gets the diagnostic naming both fields,
        not a silently different chart."""
        chart = _colour_series_chart(
            chart_type, {"rows": "region"}, style={"endpoint_labels": {"visible": True}}
        )
        with pytest.raises(ChartDataError, match="endpoint labels"):
            _v2_vl(chart, _grid_data())

    def test_non_series_colour_keeps_the_legend_where_it_was(self) -> None:
        """The top legend replaces the endpoint-label rail, and the rail only
        ever names a *series* colour channel. A gradient colour (a continuous
        field bound with a scale) has nothing the rail could have named, so
        faceting it must not force a top-horizontal legend either — only
        ``color_ch.mode == "series"`` earns that treatment."""
        chart = _area(
            {"rows": "region"},
            color="revenue",
            style={"color": {"gradient": {"palette": ["#fff", "#000"]}}},
        )
        spec = _v2_vl(chart, _row_data())
        legend = spec["spec"]["encoding"]["color"].get("legend")
        top_forced = (
            isinstance(legend, dict)
            and legend.get("orient") == "top"
            and legend.get("direction") == "horizontal"
        )
        assert not top_forced

    def test_wide_measure_area_gets_a_top_legend(self) -> None:
        """A folded wide-form area (``y: [measure, measure]``, no ``color:``)
        has a series to name from the fold itself — the measure list *is*
        the series. Faceting one must force the same top-horizontal legend a
        colour series gets, or a wide area loses its only naming once
        panelled."""
        chart = _area({"rows": "region", "columns": "product"}, y=["revenue", "cost"])
        spec = _v2_vl(chart, _grid_data())
        assert isinstance(spec.get("facet"), dict)
        legend = _colour_legend(spec)
        assert legend.get("orient") == "top"
        assert legend.get("direction") == "horizontal"

    def test_wide_measure_stacked_bar_gets_a_top_legend(self) -> None:
        """A folded wide-form stacked bar (``y: [measure, measure]``,
        ``stack: zero``, no ``color:``) has a series to name from the fold
        itself, same as wide area — faceting one must force the same
        top-horizontal legend, not fall back to the stacked bar's default
        side rail."""
        chart = BarChart.model_validate(
            {
                "id": "t",
                "type": "bar",
                "query_name": "q",
                "x": "month",
                "y": ["revenue", "cost"],
                "stack": "zero",
                "multiples": {"rows": "region"},
            }
        )
        spec = _v2_vl(chart, _grid_data())
        assert isinstance(spec.get("facet"), dict)
        legend = _colour_legend(spec)
        assert legend.get("orient") == "top"
        assert legend.get("direction") == "horizontal"


# ---------------------------------------------------------------------------
# Facet panel sizing (pure bridge helpers) — the render bridge divides the slot
# into per-panel dimensions because vl-convert does not reflow facet panels.
# ---------------------------------------------------------------------------


def _facet_vl(*, row=None, column=None, both_edge=False):
    """Hand-built faceted VL dict for exercising the sizing helpers directly."""
    unit: dict[str, Any] = {
        "encoding": {"y": {"axis": {"orient": "left"}}},
        "layer": [],
    }
    if both_edge:
        unit["layer"] = [{"encoding": {"y": {"axis": {"orient": "right"}}}}]
    facet: dict[str, Any] = {}
    if row is not None:
        facet["row"] = {"field": row}
    if column is not None:
        facet["column"] = {"field": column}
    return {"facet": facet, "spec": unit}


def _facet_cfg():
    """Per-panel sizing constants from chart_rendering.facet (default_config.yml)."""
    from dbt_charts.core.compile.config import get_chart_rendering

    return get_chart_rendering().facet


def _axes(*fields_and_cards: tuple[str, int]) -> tuple[PartitionAxis, ...]:
    """Baked ``panel_axes`` fixture: (field, cardinality) pairs → PartitionAxis tuple.

    Only the cardinality (``len(values)``) matters to ``_apply_facet_layout`` —
    the values themselves are opaque canonical strings, so a placeholder
    sequence stands in for them here.
    """
    return tuple(
        PartitionAxis(field=field, values=tuple(f"v{i}" for i in range(card)))
        for field, card in fields_and_cards
    )


def _spec_has_both_edge_y(unit: dict[str, Any]) -> bool:
    """True when the unit spec draws a y-axis on both left and right edges.

    A test-local copy of the walk ``_apply_facet_layout`` used to do at render
    time via the now-deleted ``_facet_has_both_edge_y`` — kept here as the
    independent oracle this class pins against ``resolved.style.axis_y.mirror``
    (the baked verdict ``_apply_facet_layout`` reads instead, post-fix).
    """
    edges: set[str] = set()

    def walk(s: dict[str, Any]) -> None:
        enc = s.get("encoding")
        if isinstance(enc, dict) and isinstance(enc.get("y"), dict):
            axis = enc["y"].get("axis")
            if isinstance(axis, dict) and axis.get("orient") in ("left", "right"):
                edges.add(axis["orient"])
        for layer in s.get("layer", []):
            if isinstance(layer, dict):
                walk(layer)

    walk(unit)
    return {"left", "right"} <= edges


class TestMirrorGutterMatchesEmittedSpec:
    """The baked ``ay.mirror`` flag agrees with what the emitted spec actually
    draws, across every shape in this file's faceted corpus. Written to pin
    this equivalence BEFORE deleting the render-side ``_facet_has_both_edge_y``
    it used to re-derive from the spec (confirmed green against that function
    first) — ``_apply_facet_layout`` now reads ``resolved.style.axis_y.mirror``
    directly instead.
    """

    @pytest.mark.parametrize(
        ("multiples", "data"),
        [
            ({"rows": "region"}, _row_data()),
            ({"columns": "region"}, _row_data()),
            ({"rows": "region", "columns": "product"}, _grid_data()),
        ],
    )
    def test_mirror_flag_matches_spec(self, multiples, data) -> None:
        from dbt_charts.core.compile.resolve import resolve

        norm = _area(multiples)
        board_rs, board_ctx = _board()
        resolved = resolve(norm, data, chart_style_context=board_ctx)
        spec = _v2_vl(norm, data)
        assert _spec_has_both_edge_y(spec["spec"]) == bool(resolved.style.axis_y.mirror)


class TestFacetLayout:
    def test_row_stack_width_reserves_chrome(self):
        from dbt_charts.core.render.chart.vega_lite import _apply_facet_layout

        vl = _facet_vl(row="region")
        _apply_facet_layout(
            vl, _axes(("region", 3)), has_mirror=False, width=800, height=300
        )
        # One column: full slot minus the header/axis gutter.
        assert vl["spec"]["width"] == 800 - _facet_cfg().chrome_px
        # Three regions stacked → height split three ways.
        assert vl["spec"]["height"] == 300 / 3

    def test_columns_only_divides_by_columns(self):
        from dbt_charts.core.render.chart.vega_lite import _apply_facet_layout

        # Columns-only strip: one row, three columns, both-edge axis present.
        vl = _facet_vl(column="region", both_edge=True)
        _apply_facet_layout(
            vl, _axes(("region", 3)), has_mirror=True, width=900, height=200
        )
        chrome = _facet_cfg().chrome_px + _facet_cfg().mirror_axis_px
        assert vl["spec"]["width"] == (900 - chrome) / 3
        assert vl["spec"]["height"] == 200  # single row

    def test_grid_mirror_reserves_extra_gutter(self):
        from dbt_charts.core.render.chart.vega_lite import _apply_facet_layout

        vl = _facet_vl(row="region", column="product", both_edge=True)
        _apply_facet_layout(
            vl,
            _axes(("region", 3), ("product", 2)),
            has_mirror=True,
            width=800,
            height=300,
        )
        chrome = _facet_cfg().chrome_px + _facet_cfg().mirror_axis_px
        assert vl["spec"]["width"] == (800 - chrome) / 2

    def test_narrow_slot_shrinks_panel_width_below_floor(self):
        """The card boundary always wins: a slot too narrow to hold every panel
        at the legibility floor shrinks panels below it rather than pushing
        painted content past the card's edge (RJ's call, 2026-08-10 — see
        faceted-charts-overflow-their-box-and-collide-with-neighbours)."""
        from dbt_charts.core.render.chart.vega_lite import _apply_facet_layout

        vl = _facet_vl(row="region", column="product")
        _apply_facet_layout(
            vl,
            _axes(("region", 3), ("product", 2)),
            has_mirror=False,
            width=100,
            height=300,
        )
        # Two product columns, no mirror: (100 - chrome_px) floored at 0, / 2.
        assert vl["spec"]["width"] < _facet_cfg().min_panel_px
        assert vl["spec"]["width"] == pytest.approx(
            max(100 - _facet_cfg().chrome_px, 0.0) / 2
        )


# ---------------------------------------------------------------------------
# render_chart bridge — V1 refusal + V2 faceted integration
# ---------------------------------------------------------------------------

_BOARD_1D = (
    "queries:\n"
    "  data:\n"
    "    rows:\n"
    "      - {month: Jan, region: West, revenue: 10}\n"
    "      - {month: Feb, region: West, revenue: 20}\n"
    "      - {month: Jan, region: East, revenue: 5}\n"
    "      - {month: Feb, region: East, revenue: 8}\n"
    "charts:\n"
    "  panel:\n"
    "    type: area\n"
    "    query: data\n"
    "    x: month\n"
    "    y: revenue\n"
    "    multiples: {rows: region}\n"
    "rows: [panel]\n"
)


def _compile_panel(monkeypatch):
    """Compile _BOARD_1D and return its faceted panel chart."""
    from dbt_charts import compile

    reset_config()
    result = compile(_BOARD_1D)
    assert result.success, result.errors
    assert result.board is not None
    return result.board.charts["panel"]


_BOARD_1D_LONG_Y_3PANEL = (
    "queries:\n"
    "  data:\n"
    "    rows:\n"
    "      - {month: Jan, region: West, estimated_total_revenue_from_new_customers: 10}\n"
    "      - {month: Feb, region: West, estimated_total_revenue_from_new_customers: 20}\n"
    "      - {month: Jan, region: East, estimated_total_revenue_from_new_customers: 5}\n"
    "      - {month: Feb, region: East, estimated_total_revenue_from_new_customers: 8}\n"
    "      - {month: Jan, region: North, estimated_total_revenue_from_new_customers: 7}\n"
    "      - {month: Feb, region: North, estimated_total_revenue_from_new_customers: 9}\n"
    "charts:\n"
    "  panel:\n"
    "    type: area\n"
    "    query: data\n"
    "    x: month\n"
    "    y: estimated_total_revenue_from_new_customers\n"
    "    multiples: {rows: region}\n"
    "rows: [panel]\n"
)


def _compile_panel_long_y(monkeypatch):
    """Compile _BOARD_1D_LONG_Y_3PANEL and return its faceted panel chart."""
    from dbt_charts import compile

    reset_config()
    result = compile(_BOARD_1D_LONG_Y_3PANEL)
    assert result.success, result.errors
    assert result.board is not None
    return result.board.charts["panel"]


class TestRenderChartBridge:
    def test_v2_bridge_sizes_inner_panels(self, tmp_path, monkeypatch):
        """render_chart wraps in facet and sizes the inner unit spec."""
        import json

        from dbt_charts.core.render.chart.vega_lite import render_chart

        chart = _compile_panel(monkeypatch)
        data = [
            {"month": "Jan", "region": "West", "revenue": 10},
            {"month": "Feb", "region": "West", "revenue": 20},
            {"month": "Jan", "region": "East", "revenue": 5},
            {"month": "Feb", "region": "East", "revenue": 8},
        ]
        monkeypatch.setenv("DCT_TRACE_VL", str(tmp_path))
        board_rs, board_ctx = _board()
        render_chart(
            chart, board_rs, board_ctx, data, format="svg", width=800, height=240
        )
        traced = json.loads((tmp_path / "panel-v2.json").read_text())
        assert "facet" in traced, "bridge should emit a facet spec"
        assert traced["spec"]["width"] > 0, "inner panel width set by the bridge"
        assert traced["spec"]["height"] > 0, "inner panel height set by the bridge"

    def test_v2_bridge_height_none_measures_title_wrap_per_panel(
        self, tmp_path, monkeypatch
    ):
        """No explicit height: `_apply_facet_layout` stamps nothing on the unit
        spec, so VL falls back to `config.view.continuousHeight` *per panel*
        (a unit-view default, not a whole-slot one). `RenderBox.height` must
        equal that continuous height undivided, not divided by the row-axis
        cardinality — dividing it wraps the y-axis title against a fraction
        of the space each panel actually gets. Regression for the bug where
        `box_height_full` was divided on both the explicit-height and the
        `continuous_height`-fallback branch.
        """
        import json

        from dbt_charts.core.render.chart.vega_lite import render_chart

        chart = _compile_panel_long_y(monkeypatch)
        data = [
            {
                "month": "Jan",
                "region": "West",
                "estimated_total_revenue_from_new_customers": 10,
            },
            {
                "month": "Feb",
                "region": "West",
                "estimated_total_revenue_from_new_customers": 20,
            },
            {
                "month": "Jan",
                "region": "East",
                "estimated_total_revenue_from_new_customers": 5,
            },
            {
                "month": "Feb",
                "region": "East",
                "estimated_total_revenue_from_new_customers": 8,
            },
            {
                "month": "Jan",
                "region": "North",
                "estimated_total_revenue_from_new_customers": 7,
            },
            {
                "month": "Feb",
                "region": "North",
                "estimated_total_revenue_from_new_customers": 9,
            },
        ]
        monkeypatch.setenv("DCT_TRACE_VL", str(tmp_path))
        board_rs, board_ctx = _board()
        render_chart(
            chart, board_rs, board_ctx, data, format="svg", width=800, height=None
        )
        traced = json.loads((tmp_path / "panel-v2.json").read_text())
        assert "height" not in traced["spec"], (
            "no explicit height given: nothing should be stamped on the unit spec"
        )
        y_title = traced["spec"]["encoding"]["y"]["title"]
        assert y_title == ["Estimated Total Revenue from New", "Customers"], (
            f"y title wrapped against a divided height, got {y_title!r}"
        )

    def test_v2_bridge_explicit_height_measures_title_wrap_per_panel(
        self, tmp_path, monkeypatch
    ):
        """Explicit height: `RenderBox.height` must be the *panel* height
        (`effective_height / row_cardinality`), not the whole-slot height.

        `box.height`'s only faceted consumer is `_cartesian.py`'s
        `wrap_axis_title(y_text, box.height, ...)` — endpoint labels, the
        other reader, are refused outright by `FacetFeature`. So the y-title
        wrap is the observable, and reverting `box_height_full` to plain
        `effective_height` wraps a 3-panel chart's title against 3x the space
        each panel actually has.

        Asserted by varying the *panel count* at a fixed height, not by
        varying the height: two heights scale together whether or not the
        division happens, so that comparison cannot detect the regression
        (verified — it passes with the division reverted). Panel count is the
        discriminator. With the division, the same chart and height wrap
        differently at 3 panels (300/3 = 100px) than at 1 (300px). Without
        it, both measure 300 and wrap identically — which is the regression,
        and it holds under any font metrics.
        """
        import json

        from dbt_charts.core.render.chart.vega_lite import render_chart

        chart = _compile_panel_long_y(monkeypatch)
        data = [
            {
                "month": month,
                "region": region,
                "estimated_total_revenue_from_new_customers": value,
            }
            for month, region, value in (
                ("Jan", "West", 10),
                ("Feb", "West", 20),
                ("Jan", "East", 5),
                ("Feb", "East", 8),
                ("Jan", "North", 7),
                ("Feb", "North", 9),
            )
        ]
        board_rs, board_ctx = _board()

        def _y_title(label: str, rows: list[dict[str, object]]) -> list[str]:
            out = tmp_path / label
            out.mkdir()
            monkeypatch.setenv("DCT_TRACE_VL", str(out))
            render_chart(
                chart, board_rs, board_ctx, rows, format="svg", width=800, height=300
            )
            traced = json.loads((out / "panel-v2.json").read_text())
            title = traced["spec"]["encoding"]["y"]["title"]
            return title if isinstance(title, list) else [title]

        three = _y_title("three", data)
        one = _y_title("one", [r for r in data if r["region"] == "West"])
        assert len(three[0]) < len(one[0]), (
            "at the same 300px height, a 3-panel rows facet wrapped its y-axis "
            "title identically to a 1-panel one, so RenderBox.height is the "
            f"whole-slot height rather than the panel's: {three!r} vs {one!r}"
        )

    def test_v2_placeholder_renders_faceted(self, tmp_path, monkeypatch):
        """A faceted chart renders as a placeholder (no query data yet) without
        raising — placeholder data synthesizes the facet columns FacetFeature
        validates against, so the preview is a faceted skeleton, not an error card."""
        import json

        from dbt_charts.core.render.chart.vega_lite import render_chart

        chart = _compile_panel(monkeypatch)
        monkeypatch.setenv("DCT_TRACE_VL", str(tmp_path))
        board_rs, board_ctx = _board()
        out = render_chart(
            chart,
            board_rs,
            board_ctx,
            [],
            format="svg",
            width=600,
            height=200,
            is_placeholder=True,
        )
        assert out, "placeholder render produced no output"
        traced = json.loads((tmp_path / "panel-v2.json").read_text())
        assert "facet" in traced, "placeholder should still render as a facet"


# ---------------------------------------------------------------------------
# FacetFeature refusals — incompatible compositions error, not silently render
# ---------------------------------------------------------------------------


class TestFacetRefusals:
    def _resolved_area(
        self, multiples: dict[str, Any], extra: dict[str, Any] | None = None
    ):
        from dbt_charts.core.compile.resolve import resolve

        spec = {
            "id": "t",
            "type": "area",
            "x": "month",
            "y": "revenue",
            "multiples": multiples,
        }
        if extra:
            spec.update(extra)
        return resolve(
            AreaChart.model_validate(spec), _row_data(), chart_style_context=_board()[1]
        )

    def test_facet_plus_endpoint_labels_raises(self):
        """Fires the typed ERR-MULTIPLES-ENDPOINT-LABELS code, never the
        ERR-INTERNAL fallback."""
        from dbt_charts.core.diagnostics.codes_render import (
            ERR_MULTIPLES_ENDPOINT_LABELS,
        )
        from dbt_charts.core.render.chart.features.facet import FacetFeature
        from dbt_charts.core.render.chart.spec import ChartSpec

        resolved = self._resolved_area({"rows": "region"})
        composed = ChartSpec(mark="area", endpoint_label_layout="right_pane")
        with pytest.raises(ChartDataError, match="endpoint labels") as exc_info:
            FacetFeature().apply(
                composed, resolved, _DEFAULT_BOX, {resolved.query_name: _row_data()}
            )
        assert exc_info.value.code is ERR_MULTIPLES_ENDPOINT_LABELS

    def test_unknown_partition_field_raises(self):
        """A mistyped multiples field fails loud with the available columns, like x/y."""
        chart = _area({"rows": "regionn"})  # typo
        with pytest.raises(ChartDataError, match="not found in the query result"):
            _v2_vl(chart, _row_data())

    def test_facet_plus_data_table_raises(self):
        """Fires the typed ERR-MULTIPLES-DATA-TABLE code, never the
        ERR-INTERNAL fallback."""
        from dbt_charts.core.compile.models.chart.authored import ChartDataTable
        from dbt_charts.core.diagnostics.codes_render import ERR_MULTIPLES_DATA_TABLE
        from dbt_charts.core.render.chart.features.facet import FacetFeature
        from dbt_charts.core.render.chart.spec import ChartSpec

        resolved = self._resolved_area({"rows": "region"}).model_copy(
            update={
                "data_table": ChartDataTable.model_validate(
                    {"entries": [{"source": "revenue"}]}
                )
            }
        )
        with pytest.raises(ChartDataError, match="data_table") as exc_info:
            FacetFeature().apply(
                ChartSpec(mark="area"),
                resolved,
                _DEFAULT_BOX,
                {resolved.query_name: _row_data()},
            )
        assert exc_info.value.code is ERR_MULTIPLES_DATA_TABLE
