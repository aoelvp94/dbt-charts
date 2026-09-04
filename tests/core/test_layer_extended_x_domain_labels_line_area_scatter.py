"""Line/area/scatter x-axis tick values must cover the full union domain.

Same defect as ``test_layer_extended_x_domain_labels.py`` fixed on bar
(``overlay_x_domain_values``, ``_overlay.py``), reaching the three cartesian
families that route x through the shared ``resolve_cartesian_x`` seam
(``emitters/_cartesian.py``) instead of building it inline the way bar does.
An overlay layer with more x buckets than the base series (a forward goal
ramp against actuals) widens the shared band/temporal scale; the axis tick
values must be derived from that union, on both the authored-ordinal and the
default-temporal path.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
from dbt_charts.core.compile.models.chart.authored._layer import LineLayer
from dbt_charts.core.compile.models.chart.normalized import (
    AreaChart as NAreaChart,
    LineChart as NLineChart,
    ScatterChart as NScatterChart,
)
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.chart._chart_rows import regroup
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.emitters.area import AreaEmitter
from dbt_charts.core.render.chart.emitters.line import LineEmitter
from dbt_charts.core.render.chart.emitters.scatter import ScatterEmitter
from dbt_charts.core.render.chart.spec import RenderBox
from dbt_charts.core.render.chart.translate import translate_to_vl

_EMITTERS = {
    "line": (NLineChart, LineEmitter),
    "area": (NAreaChart, AreaEmitter),
    "scatter": (NScatterChart, ScatterEmitter),
}

_BASE_MONTHS = [f"{y}-{m:02d}-01" for y in (2023, 2024) for m in range(1, 13)]
_GOAL_MONTHS = [
    f"{y}-{m:02d}-01" for y in (2023, 2024, 2025, 2026) for m in range(1, 13)
]


def _default_board_style() -> Any:
    return resolve_chart_style_context(get_theme_style(get_default_theme_name()))


def _emit(
    family: str,
    *,
    ordinal: bool,
    width: float = 600.0,
    base: list[dict] | None = None,
    goal: list[dict] | None = None,
    label_time_unit: str | None = "year",
) -> VLDict:
    """Emit a month base series with a longer goal-line overlay for ``family``.

    ``ordinal`` selects the authored-ordinal x-type path (``axis_x.type:
    ordinal``) vs. the default continuous-temporal path Vega-Lite resolves on
    its own for a bucketed monthly grain. ``label_time_unit`` authors a
    coarser label cadence (year openers); ``None`` leaves every bucket at
    its own encoding grain, for crowding tests that need every month to
    compete for space.
    """
    chart_cls, emitter_cls = _EMITTERS[family]
    base = base if base is not None else _BASE_MONTHS
    goal = goal if goal is not None else _GOAL_MONTHS
    base_rows = [{"month": m, "revenue": 100.0 + i} for i, m in enumerate(base)]
    goal_rows = [{"month": m, "goal": 150.0 + i} for i, m in enumerate(goal)]
    axis_x: dict[str, Any] = (
        {"labels": {"time_unit": label_time_unit}} if label_time_unit else {}
    )
    if ordinal:
        axis_x["type"] = "ordinal"
    chart = chart_cls(
        id="c1",
        type=family,
        x="month",
        y="revenue",
        query=SqlQuery(sql="SELECT 1", source="t"),
        query_name="q",
        variable_dependencies=set(),
        layers=[LineLayer(type="line", y="goal", query="goals")],
        style={"axis_x": axis_x},
    )
    resolved = resolve(chart, base_rows, _default_board_style())
    return translate_to_vl(
        emitter_cls().emit(
            resolved,
            RenderBox(width=width, height=300.0),
            regroup((), base_rows),
            datasets={"goals": goal_rows},
        )
    )


def _axis_values_at_every_injection_site(vl: VLDict) -> list[list]:
    """Every ``axis.values`` list the spec carries on an x encoding."""
    found: list[list] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            x_enc = node.get("encoding", {}).get("x")
            if isinstance(x_enc, dict):
                values = x_enc.get("axis", {}).get("values")
                if values is not None:
                    found.append(values)
            for child in node.get("layer", []):
                walk(child)

    walk(vl)
    return found


class TestAxisValuesCoverFullUnionDomain:
    """The base carries 24 months, the goal layer 48. Cadence is year, so
    the union must thin to 4 January openers (2023-2026), not 2."""

    def test_line_authored_ordinal(self) -> None:
        vl = _emit("line", ordinal=True)
        injections = _axis_values_at_every_injection_site(vl)
        assert injections, "expected axis.values on the shared x encoding"
        for values in injections:
            assert values == [
                "2023-01-01",
                "2024-01-01",
                "2025-01-01",
                "2026-01-01",
            ], values

    def test_line_default_temporal(self) -> None:
        vl = _emit("line", ordinal=False)
        assert vl["encoding"]["x"]["type"] == "temporal"
        injections = _axis_values_at_every_injection_site(vl)
        assert injections, "expected axis.values on the shared x encoding"
        for values in injections:
            assert values == [
                "2023-01-01",
                "2024-01-01",
                "2025-01-01",
                "2026-01-01",
            ], values

    def test_area_authored_ordinal(self) -> None:
        vl = _emit("area", ordinal=True)
        injections = _axis_values_at_every_injection_site(vl)
        assert injections, "expected axis.values on the shared x encoding"
        for values in injections:
            assert values == [
                "2023-01-01",
                "2024-01-01",
                "2025-01-01",
                "2026-01-01",
            ], values

    def test_area_default_temporal(self) -> None:
        vl = _emit("area", ordinal=False)
        assert vl["encoding"]["x"]["type"] == "temporal"
        injections = _axis_values_at_every_injection_site(vl)
        assert injections, "expected axis.values on the shared x encoding"
        for values in injections:
            assert values == [
                "2023-01-01",
                "2024-01-01",
                "2025-01-01",
                "2026-01-01",
            ], values

    def test_scatter_authored_ordinal(self) -> None:
        vl = _emit("scatter", ordinal=True)
        injections = _axis_values_at_every_injection_site(vl)
        assert injections, "expected axis.values on the shared x encoding"
        for values in injections:
            assert values == [
                "2023-01-01",
                "2024-01-01",
                "2025-01-01",
                "2026-01-01",
            ], values

    def test_scatter_default_temporal(self) -> None:
        vl = _emit("scatter", ordinal=False)
        assert vl["encoding"]["x"]["type"] == "temporal"
        injections = _axis_values_at_every_injection_site(vl)
        assert injections, "expected axis.values on the shared x encoding"
        for values in injections:
            assert values == [
                "2023-01-01",
                "2024-01-01",
                "2025-01-01",
                "2026-01-01",
            ], values


def test_authored_ordinal_domain_and_axis_values_agree_on_length() -> None:
    """The exact contradiction the task brief measured: a 2-entry
    ``axis.values`` beside a 48-entry ``scale.domain`` on the same encoding."""
    vl = _emit("line", ordinal=True)
    domain = vl["encoding"]["x"]["scale"]["domain"]
    assert len(domain) == len(_GOAL_MONTHS)
    assert len(vl["encoding"]["x"]["axis"]["values"]) == 4


def test_label_crowding_is_measured_against_the_rendered_band_count() -> None:
    """The domain feeds ``resolve_axis_x_overlap`` too, not just tick values.

    3 base months under a 40-month goal layer at 300px: measuring the base's
    own 3 labels says they fit flat; measuring the 40 that render says they
    do not. Mirrors the bar regression
    (``test_layer_extended_x_domain_labels.py``) — every other assertion in
    this module passes with the overlap half stripped, so without this one
    that half of the fix is unpinned for line/area/scatter.

    400 months, not 40: the cadence ladder now loops to ``year`` and takes it
    whenever it fits flat. At 300px a 40-month layer reaches year cadence at
    four labels 72px apart, which fits — so the axis renders FLAT and the tilt
    signal this test relies on disappears, even though the crowding really was
    measured against all 40 bands. 400 months (33 years) keeps even the year
    rung too dense to fit, so a tilt still means "measured against the rendered
    bands" and a flat axis still means "measured against the base's 3". Mirrors
    the same widening already applied to the ordinal sibling in
    ``test_layer_extended_x_domain_labels.py``.
    """
    base = [f"2024-{m:02d}-01" for m in range(1, 4)]
    goal_months, year, month = [], 2024, 1
    for _ in range(400):
        goal_months.append(f"{year}-{month:02d}-01")
        month += 1
        if month == 13:
            month, year = 1, year + 1

    for family in ("line", "area", "scatter"):
        vl = _emit(
            family,
            ordinal=False,
            width=300.0,
            base=base,
            goal=goal_months,
            label_time_unit=None,
        )
        chart_cls, _ = _EMITTERS[family]
        resolved_style = resolve(
            chart_cls(
                id="c1",
                type=family,
                x="month",
                y="revenue",
                query=SqlQuery(sql="SELECT 1", source="t"),
                query_name="q",
                variable_dependencies=set(),
            ),
            [{"month": m, "revenue": 1.0} for m in base],
            _default_board_style(),
        ).style
        steepest = resolved_style.axis_x.labels.tilt_increments[-1]
        assert vl["encoding"]["x"]["axis"]["labelAngle"] == steepest, family
