"""Heatmap has no quantitative axis to style -- axis_quantitative is gone.

Heatmap's axes are both nominal (its magnitude lives on the color channel),
so ``axis_quantitative`` never had anything to apply to. This is pinned two
ways: structurally (the field is absent from heatmap's authored patch, so
authoring it is a parse-time error -- covered by
``test_yaml_error_formatter.py`` and ``test_heatmap_axis_quantitative_
migration.py``) and behaviorally (heatmap still resolves end to end through
the shared ``plan_cartesian()`` prelude every cartesian family calls).

An earlier draft of this removal also covered ``axis_band`` on scatter --
that half was wrong and withdrawn (see initiative research.md, section F3): a
scatter with a nominal x is a dot plot, and it genuinely honors axis_band.
``test_scatter_nominal_x_still_honors_axis_band`` below guards against
silently reintroducing that withdrawn scope.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import (
    BarChart,
    HeatmapChart,
    ScatterChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import (
    AreaChartStylePatch,
    BarChartStylePatch,
    LineChartStylePatch,
    ScatterChartStylePatch,
)
from dbt_charts.core.compile.models.style.theme import HistogramChartStyle
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context


def _sql() -> SqlQuery:
    return SqlQuery(sql="SELECT 1", source="t")


def _board() -> Any:
    reset_config()
    return resolve_chart_style_context(get_theme_style())


class TestHeatmapHasNoQuantitativeAxisField:
    """Structural pin: axis_quantitative sits on a mixin heatmap doesn't inherit."""

    def test_every_other_cartesian_family_keeps_axis_quantitative(self) -> None:
        for patch_cls in (
            BarChartStylePatch,
            LineChartStylePatch,
            AreaChartStylePatch,
            ScatterChartStylePatch,
        ):
            assert "axis_quantitative" in patch_cls.model_fields, (
                f"{patch_cls.__name__} lost axis_quantitative -- the removal "
                "must be heatmap-only"
            )
        # Histogram reuses BarChart's authored patch (no HistogramChartStylePatch
        # exists), so its axis_quantitative is pinned on the theme-stage class
        # directly instead.
        assert "axis_quantitative" in HistogramChartStyle.model_fields


class TestHeatmapStillResolves:
    """heatmap must still call plan_cartesian() like every other family --
    the removal narrows what it can style, not whether it runs the shared
    prelude (see compile/resolve/chart/AGENTS.md's "never skip the call")."""

    def test_heatmap_resolves_without_error(self) -> None:
        chart = HeatmapChart(
            id="c",
            type="heatmap",
            x="month",
            y="category",
            query=_sql(),
            query_name="q",
        )
        data = [{"month": "Jan", "category": "Alpha", "value": 1.0}]
        resolved = resolve(chart, data, _board())
        assert resolved.chart_type == "heatmap"


class TestQuantitativeFamiliesStillHonorChartLocalAxisQuantitative:
    """The other half of the removal: the five families that DO have a
    quantitative axis must still read a chart-local ``axis_quantitative``.

    ``plan_cartesian``'s ``has_quantitative_axis`` gates that read. Only
    heatmap's ``False`` branch was pinned (it would ``AttributeError``
    without it); this pins the ``True`` branch the other five depend on, so
    flipping the flag -- or adding a sixth family whose call site omits it --
    fails here instead of silently dropping every chart-local override.
    Existing axis_quantitative coverage seeds the board-global tier, which
    this gate does not control.
    """

    def test_bar_applies_a_chart_local_axis_quantitative_patch(self) -> None:
        patch = BarChartStylePatch.model_validate(
            {"axis_quantitative": {"grid": {"visible": False}}}
        )
        chart = BarChart(
            id="c",
            type="bar",
            x="month",
            y="value",
            query=_sql(),
            query_name="q",
            style=patch,
        )
        data = [{"month": "Jan", "value": 1.0}, {"month": "Feb", "value": 2.0}]
        resolved = resolve(chart, data, _board())
        assert resolved.style.axis_y.grid.visible is False


class TestScatterNominalXStillHonorsAxisBand:
    """Regression guard for the withdrawn half of this removal's original
    scope: a scatter with a nominal x is a dot plot, and axis_band must
    still be both accepted and honored on it."""

    def test_nominal_x_scatter_applies_axis_band_patch(self) -> None:
        patch = ScatterChartStylePatch.model_validate(
            {"axis_band": {"grid": {"visible": False}}}
        )
        chart = ScatterChart(
            id="c",
            type="scatter",
            x="month",
            y="value",
            query=_sql(),
            query_name="q",
            style=patch,
        )
        data = [{"month": "Jan", "value": 1.0}, {"month": "Feb", "value": 2.0}]
        resolved = resolve(chart, data, _board())
        assert resolved.style.axis_x.grid.visible is False

    def test_quantitative_x_scatter_does_not_apply_the_band_patch(self) -> None:
        """Contrast case: the same axis_band patch is inert on a quantitative
        x -- proving the nominal-x case above is genuinely channel-type
        conditional, not just always-applied."""
        patch = ScatterChartStylePatch.model_validate(
            {"axis_band": {"grid": {"visible": False}}}
        )
        chart = ScatterChart(
            id="c",
            type="scatter",
            x="idx",
            y="value",
            query=_sql(),
            query_name="q",
            style=patch,
        )
        data = [{"idx": 1, "value": 1.0}, {"idx": 2, "value": 2.0}]
        resolved = resolve(chart, data, _board())
        assert resolved.style.axis_x.grid.visible is True
