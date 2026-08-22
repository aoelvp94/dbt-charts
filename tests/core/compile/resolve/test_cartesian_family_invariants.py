"""Family-invariant tests for the cartesian resolvers' shared policy.

Every cartesian family (bar, line, area, scatter, heatmap) hand-assembles its
own composition of the same shared helpers in
`compile/resolve/chart/_axes.py`, `_layers.py`, and `_domain.py`. A family
that skips a policy call renders wrong with no compile-time signal — nothing
polices that the composition is complete. This suite drives the real public
`resolve()` for every family and pins four invariants that must hold
identically across all of them, or be explicitly, reason-carrying skipped for
a family the invariant structurally does not apply to. A silently-missing
family is exactly the failure mode this file exists to catch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.chart.authored import (
    LayerAxisYStyle,
    LineLayer,
    MultiplesConfig,
)
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart,
    BarChart,
    Chart,
    HeatmapChart,
    LineChart,
    ScatterChart,
)
from dbt_charts.core.compile.models.chart.resolved import (
    ResolvedAreaChart,
    ResolvedBarChart,
    ResolvedChart,
    ResolvedLineChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import (
    AreaChartStylePatch,
    BarChartStylePatch,
    LineChartStylePatch,
    ScatterChartStylePatch,
)
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

_FAMILIES = ("bar", "line", "area", "scatter", "heatmap", "histogram")

# _resolve_histogram passes multiples=None, y=None to plan_cartesian by design
# (histogram bins x and counts rows -- there is no per-row y series) and never
# calls cartesian_series_naming(): no color-series legend, no multiples-facet
# top legend, no endpoint-label rail. Every invariant below is downstream of
# either that call or a per-family guard histogram never runs; each skip below
# names the specific reason, not this shared root cause alone.
_HISTOGRAM_NO_SERIES_LEGEND = (
    "histogram never calls cartesian_series_naming() (plan_cartesian is called "
    "with multiples=None, y=None by design) -- there is no series legend for "
    "this invariant to check."
)

_TINY_WIDTH = 200.0


@pytest.fixture(autouse=True)
def _reset() -> Any:
    reset_config()
    yield
    reset_config()


def _board() -> Any:
    return resolve_chart_style_context(get_theme_style())


def _sql() -> SqlQuery:
    return SqlQuery(sql="SELECT 1", source="t")


def _bar(**kwargs: Any) -> BarChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "bar",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
    }
    defaults.update(kwargs)
    return BarChart(**defaults)


def _line(**kwargs: Any) -> LineChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "line",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
    }
    defaults.update(kwargs)
    return LineChart(**defaults)


def _area(**kwargs: Any) -> AreaChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "area",
        "x": "month",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
    }
    defaults.update(kwargs)
    return AreaChart(**defaults)


def _scatter(**kwargs: Any) -> ScatterChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "scatter",
        "x": "month_index",
        "y": "revenue",
        "query": _sql(),
        "query_name": "q",
    }
    defaults.update(kwargs)
    return ScatterChart(**defaults)


def _heatmap(**kwargs: Any) -> HeatmapChart:
    defaults: dict[str, Any] = {
        "id": "c",
        "type": "heatmap",
        "x": "month",
        "y": "category",
        "query": _sql(),
        "query_name": "q",
    }
    defaults.update(kwargs)
    return HeatmapChart(**defaults)


_BUILDERS: dict[str, Callable[..., Chart]] = {
    "bar": _bar,
    "line": _line,
    "area": _area,
    "scatter": _scatter,
    "heatmap": _heatmap,
}

# Every non-heatmap family authors axis_y through its own StylePatch type;
# heatmap is never looked up here (invariants 2 and 3 skip it outright).
_STYLE_PATCHES: dict[str, Any] = {
    "bar": BarChartStylePatch,
    "line": LineChartStylePatch,
    "area": AreaChartStylePatch,
    "scatter": ScatterChartStylePatch,
}


def _family_params(exemptions: dict[str, str]) -> list[Any]:
    """Every family, with exempted ones wrapped as an explicit, reasoned skip."""
    return [
        pytest.param(family, marks=pytest.mark.skip(reason=exemptions[family]))
        if family in exemptions
        else family
        for family in _FAMILIES
    ]


# month/month_index: dimension, usable as either family's x. category: a second
# nominal field so heatmap's y differs from its x. series: the colour channel
# (bare field name -> mode="series", never a gradient). facet: the multiples
# partition, kept distinct from every other role so no family double-purposes
# a column between its own axes and the panel split.
_SERIES_DATA: list[dict[str, Any]] = [
    {
        "month": "Jan",
        "month_index": 1,
        "category": "Alpha",
        "series": "S1",
        "facet": "P1",
        "revenue": 10.0,
    },
    {
        "month": "Feb",
        "month_index": 2,
        "category": "Alpha",
        "series": "S1",
        "facet": "P1",
        "revenue": 20.0,
    },
    {
        "month": "Jan",
        "month_index": 1,
        "category": "Beta",
        "series": "S2",
        "facet": "P2",
        "revenue": 15.0,
    },
    {
        "month": "Feb",
        "month_index": 2,
        "category": "Beta",
        "series": "S2",
        "facet": "P2",
        "revenue": 25.0,
    },
]


class TestMultiplesWithColourSeriesGetsTopLegend:
    """Invariant 1: multiples + a colour series -> resolved legend is top and visible."""

    @pytest.mark.parametrize(
        "family", _family_params({"histogram": _HISTOGRAM_NO_SERIES_LEGEND})
    )
    def test_multiples_with_colour_series_gets_top_legend(self, family: str) -> None:
        # stack="zero" for bar: at the theme default stack="none",
        # unconditional_top_legend=True short-circuits the "row" branch in
        # _axes.py before _multiples_wants_top_legend is ever evaluated, so
        # the assertion would pass even with the multiples term deleted.
        # Stacked bar clears that short-circuit and actually exercises it.
        extra_kwargs: dict[str, Any] = {"stack": "zero"} if family == "bar" else {}
        chart = _BUILDERS[family](
            color="series",
            multiples=MultiplesConfig(rows="facet"),
            **extra_kwargs,
        )
        resolved = resolve(chart, _SERIES_DATA, _board())
        assert resolved.legend.position == "top", (
            f"{family}: faceted colour-series chart did not get a top legend "
            f"(position={resolved.legend.position!r})"
        )
        assert resolved.legend.visible is True, (
            f"{family}: faceted colour-series chart's top legend is not visible"
        )


_LAYER_DATA: list[dict[str, Any]] = [
    {"month": "Jan", "month_index": 1, "revenue": 100.0, "target": 4000.0},
    {"month": "Feb", "month_index": 2, "revenue": 200.0, "target": 5000.0},
    {"month": "Mar", "month_index": 3, "revenue": 150.0, "target": 4500.0},
]


class TestLayersWithAuthoredYDomainRaises:
    """Invariant 2: layers + an authored axis_y.scale.domain -> _check_layers_y_domain fires."""

    @pytest.mark.parametrize(
        "family",
        _family_params(
            {
                "heatmap": (
                    "HeatmapChart carries no `layers` field at all (both its axes "
                    "are nominal, no measure axis for an overlay to split) — there "
                    "is no dual-axis shape for _check_layers_y_domain to police."
                ),
                "histogram": (
                    "_resolve_histogram never resolves `normalized.layers` -- "
                    "layers is a family decision plan_cartesian's docstring "
                    "documents histogram opting out of (multiples=None, y=None) "
                    "-- no layer ever reaches _check_layers_y_domain to raise "
                    "against."
                ),
            }
        ),
    )
    def test_layers_with_authored_y_domain_and_split_axis_raises(
        self, family: str
    ) -> None:
        style_patch_cls = _STYLE_PATCHES[family]
        chart = _BUILDERS[family](
            layers=[
                LineLayer(
                    type="line", y="target", axis_y=LayerAxisYStyle(position="right")
                )
            ],
            style=style_patch_cls.model_validate(
                {"axis_y": {"scale": {"continuous": {"domain": [0, 300]}}}}
            ),
        )
        with pytest.raises(CompilationError) as exc_info:
            resolve(chart, _LAYER_DATA, _board())
        assert exc_info.value.code is not None
        assert exc_info.value.code.code == "ERR-LAYERS-AMBIGUOUS-Y-DOMAIN", (
            f"{family}: layered chart with a right-pinned overlay and an authored "
            f"axis_y.scale.domain did not raise ERR-LAYERS-AMBIGUOUS-Y-DOMAIN"
        )


_LOG_ZERO_DATA_NOMINAL_X: list[dict[str, Any]] = [
    {"month": "Jan", "revenue": 0.0},
    {"month": "Feb", "revenue": 200.0},
]
_LOG_ZERO_DATA_NUMERIC_X: list[dict[str, Any]] = [
    {"month_index": 1, "revenue": 0.0},
    {"month_index": 2, "revenue": 200.0},
]


class TestLogMeasureAxisWithNonPositiveDataRaises:
    """Invariant 3: a log measure axis with non-positive data -> ERR-LOG-SCALE-REQUIRES-POSITIVE-DATA."""

    @pytest.mark.parametrize(
        "family",
        _family_params(
            {
                "bar": (
                    "bar rejects axis_y.scale.type: log outright via "
                    "ERR_BAR_LOG_SCALE_NOT_SUPPORTED before the data is ever "
                    "inspected — a bar's length encodes magnitude from zero, "
                    "meaningless on a log scale."
                ),
                "heatmap": (
                    "heatmap bakes both axes as 'nominal' "
                    "(_resolve_heatmap -> _bake_cartesian_axes) — there is no "
                    "measure axis for a log scale to apply to."
                ),
                "histogram": (
                    "_resolve_histogram never calls "
                    "_reject_non_positive_log_scale_data. A histogram's y is a "
                    "bin count VL computes client-side, not an authored column "
                    "the resolver reads at compile time -- there is no y-column "
                    "extent for this guard to inspect."
                ),
            }
        ),
    )
    def test_log_measure_axis_with_non_positive_data_raises(self, family: str) -> None:
        style_patch_cls = _STYLE_PATCHES[family]
        data = (
            _LOG_ZERO_DATA_NUMERIC_X
            if family == "scatter"
            else _LOG_ZERO_DATA_NOMINAL_X
        )
        chart = _BUILDERS[family](
            style=style_patch_cls.model_validate(
                {"axis_y": {"scale": {"continuous": {"type": "log"}}}}
            ),
        )
        with pytest.raises(CompilationError) as exc_info:
            resolve(chart, data, _board())
        assert exc_info.value.code is not None
        assert exc_info.value.code.code == "ERR-LOG-SCALE-REQUIRES-POSITIVE-DATA", (
            f"{family}: log measure axis with a non-positive data value did not "
            f"raise ERR-LOG-SCALE-REQUIRES-POSITIVE-DATA"
        )


def _assert_compact_top_legend(resolved: ResolvedChart, family: str) -> None:
    assert resolved.legend.position == "top", (
        f"{family}: tiny-width colour-series chart did not fall back to a top "
        f"legend (position={resolved.legend.position!r})"
    )
    assert resolved.legend.columns != 0, (
        f"{family}: tiny-width top legend is not in compact-columns layout "
        f"(columns=0 means the uncompacted 'row' layout, not 'compact')"
    )
    # Only the three rail-bearing families discard the rail in favor of the
    # compact legend; scatter/heatmap have no endpoint_labels field to check —
    # "no rail" is their whole story, there is nothing to fall back from.
    if isinstance(resolved, ResolvedBarChart | ResolvedLineChart | ResolvedAreaChart):
        assert resolved.style.endpoint_labels.visible is False, (
            f"{family}: tiny-width colour-series chart kept the endpoint-label "
            f"rail instead of falling back to the compact top legend"
        )


class TestTinyWidthFallsBackToCompactTopLegend:
    """Invariant 4: tiny width -> series naming falls back to the compact top legend."""

    @pytest.mark.parametrize(
        "family", _family_params({"histogram": _HISTOGRAM_NO_SERIES_LEGEND})
    )
    def test_tiny_width_falls_back_to_compact_top_legend(self, family: str) -> None:
        chart = _BUILDERS[family](color="series")
        resolved = resolve(chart, _SERIES_DATA, _board(), width=_TINY_WIDTH)
        _assert_compact_top_legend(resolved, family)
