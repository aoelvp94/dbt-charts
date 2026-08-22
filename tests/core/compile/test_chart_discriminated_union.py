"""TDD smoke tests for per-family discriminated AuthoredChart union.

Phase 1 of the split-AuthoredChart task. These tests drive the implementation of:
- Per-family Patch classes (BarChart, KpiChart, PieChart, etc.)
- AuthoredChart as a Discriminator("type") union alias (not a BaseModel)
- Structural enforcement: extra fields rejected, required fields enforced
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from dbt_charts.core.compile.models.chart.authored import (
    AreaChart,
    AuthoredChart,
    BarChart,
    CalloutChart,
    GeoshapeChart,
    HeatmapChart,
    KpiChart,
    LineChart,
    PieChart,
    PointMapChart,
    ScatterChart,
)


def test_bar_patch_validates():
    p = BarChart(type="bar", x="month", y="revenue")
    assert p.type == "bar"
    assert p.x == "month"


def test_bar_patch_rejects_kpi_field():
    """KPI-only field value: is extra-forbidden on BarChart."""
    with pytest.raises(ValidationError):
        BarChart(type="bar", value="x")  # type: ignore[call-arg]


def test_bar_patch_rejects_theta():
    """Pie-only field theta: is extra-forbidden on BarChart."""
    with pytest.raises(ValidationError):
        BarChart(type="bar", theta="slice")  # type: ignore[call-arg]


def test_kpi_patch_requires_value():
    """KpiChart.value is required (structural, not a validator)."""
    with pytest.raises(ValidationError, match="value"):
        KpiChart(type="kpi")  # type: ignore[call-arg]


def test_kpi_patch_accepts_required_value():
    p = KpiChart(type="kpi", value="revenue")
    assert p.value == "revenue"


def test_pie_patch_requires_theta():
    """PieChart.theta is required (structural)."""
    with pytest.raises(ValidationError, match="theta"):
        PieChart(type="pie")  # type: ignore[call-arg]


def test_pie_patch_rejects_x():
    """x is not declared on PieChart — extra forbidden."""
    with pytest.raises(ValidationError):
        PieChart(type="pie", theta="amount", x="region")  # type: ignore[call-arg]


def test_callout_patch_requires_message():
    """CalloutChart.message is required (structural)."""
    with pytest.raises(ValidationError, match="message"):
        CalloutChart(type="callout")  # type: ignore[call-arg]


def test_chartpatch_union_dispatches_to_bar():
    adapter = TypeAdapter(AuthoredChart)
    result = adapter.validate_python({"type": "bar", "x": "month", "y": "revenue"})
    assert isinstance(result, BarChart)


def test_chartpatch_union_dispatches_to_kpi():
    adapter = TypeAdapter(AuthoredChart)
    result = adapter.validate_python({"type": "kpi", "value": "rev", "query": "q"})
    assert isinstance(result, KpiChart)


def test_chartpatch_union_dispatches_to_pie():
    adapter = TypeAdapter(AuthoredChart)
    result = adapter.validate_python({"type": "pie", "theta": "amount"})
    assert isinstance(result, PieChart)


# --- Regression tests for type: enforcement ---


def test_chartpatch_union_rejects_unknown_type():
    """Unknown type raises ValidationError — no fallback catch-all class exists."""
    adapter = TypeAdapter(AuthoredChart)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "fuzzbomp"})


def test_chartpatch_union_rejects_missing_type():
    """Missing type: raises ValidationError — type is mandatory."""
    adapter = TypeAdapter(AuthoredChart)
    with pytest.raises(ValidationError):
        adapter.validate_python({})


def test_line_patch_rejects_size():
    """size is structurally impossible on LineChart — extra_forbidden."""
    with pytest.raises(ValidationError):
        LineChart(type="line", x="m", y="v", size="col")  # type: ignore[call-arg]


def test_pie_patch_accepts_conditional_formatting():
    """pie has a CF lowering path — conditional_formatting must parse."""
    p = PieChart(
        type="pie",
        theta="revenue",
        conditional_formatting={
            "revenue": {"when": [{"gt": 100, "background": "#ff0000"}]}
        },
    )
    assert p.conditional_formatting is not None


def test_geoshape_patch_accepts_conditional_formatting():
    """geoshape has a CF lowering path — conditional_formatting must parse."""
    g = GeoshapeChart(
        type="geoshape",
        conditional_formatting={
            "sales": {"when": [{"gt": 1000, "background": "#ff0000"}]}
        },
    )
    assert g.conditional_formatting is not None


def test_point_map_patch_accepts_conditional_formatting():
    """point_map has a CF lowering path — conditional_formatting must parse."""
    p = PointMapChart(
        type="point_map",
        conditional_formatting={
            "value": {"when": [{"gt": 50, "background": "#00ff00"}]}
        },
    )
    assert p.conditional_formatting is not None


def test_bubble_map_patch_accepts_conditional_formatting():
    """bubble_map has a CF lowering path — conditional_formatting must parse."""
    p = PointMapChart(
        type="bubble_map",
        conditional_formatting={
            "value": {"when": [{"gt": 50, "background": "#0000ff"}]}
        },
    )
    assert p.conditional_formatting is not None


def test_callout_patch_rejects_conditional_formatting():
    with pytest.raises(ValidationError, match="conditional_formatting"):
        CalloutChart(type="callout", message="hi", conditional_formatting={})  # type: ignore[call-arg]


def test_heatmap_patch_rejects_conditional_formatting():
    with pytest.raises(ValidationError, match="conditional_formatting"):
        HeatmapChart(type="heatmap", x="m", y="v", conditional_formatting={})  # type: ignore[call-arg]


def test_bar_patch_accepts_conditional_formatting():
    """bar is in the honored set — conditional_formatting still parses."""
    p = BarChart(
        type="bar",
        x="month",
        y="revenue",
        conditional_formatting={
            "revenue": {"when": [{"gt": 100, "background": "#00ff00"}]}
        },
    )
    assert p.conditional_formatting is not None


def test_bar_patch_accepts_stack():
    """stack is valid on BarChart via style.bar.stack."""
    from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

    p = BarChart(type="bar", x="m", y="v", style=BarChartStylePatch(stack="zero"))
    assert p.style is not None
    assert p.style.stack == "zero"


@pytest.mark.parametrize("bad_value", [True, False])
def test_bar_patch_rejects_bool_stack(bad_value: bool) -> None:
    """stack: true/false must be rejected — only enum values are valid."""
    from dbt_charts.core.compile.models.style.authored import BarChartStylePatch

    with pytest.raises(ValidationError):
        BarChartStylePatch(stack=bad_value)


@pytest.mark.parametrize(
    ("chart_cls", "type_str"),
    [
        (BarChart, "bar"),
        (LineChart, "line"),
        (AreaChart, "area"),
    ],
)
def test_chart_families_reject_root_stack(chart_cls, type_str):
    """stack is a style-cascade field only; chart-root form is rejected on every family."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        chart_cls(type=type_str, x="m", y="v", stack="zero")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("chart_cls", "type_str"),
    [
        (BarChart, "bar"),
        (LineChart, "line"),
        (AreaChart, "area"),
        (ScatterChart, "scatter"),
        (HeatmapChart, "heatmap"),
    ],
)
def test_cartesian_families_reject_labels(chart_cls, type_str):
    """labels: has no render path on cartesian families — extra_forbidden, not a silent drop."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        chart_cls(  # type: ignore[call-arg]
            type=type_str, x="m", y="v", labels={"template": "{{ v }}"}
        )


def test_pie_rejects_chart_level_labels():
    """labels: is no longer accepted on pie/donut — template/where live under
    style.marks.slice.labels after being folded into SliceMarkStyle."""
    with pytest.raises(ValidationError):
        PieChart(type="pie", theta="amount", labels={"template": "{{ amount }}"})


def test_slice_labels_style_rejects_broken_template():
    """SliceLabelsStyle.template validator rejects malformed Jinja."""
    from dbt_charts.core.compile.models.style.theme import (
        LabelsDefaultTemplate,
        SliceLabelsStyle,
    )

    dt = LabelsDefaultTemplate(
        with_color="{{ color }}: {{ value }}", no_color="{{ value }}"
    )
    with pytest.raises(ValidationError):
        SliceLabelsStyle(
            offset=10.0, line_height=16.0, default_template=dt, template="{{ broken"
        )


def test_slice_labels_style_rejects_broken_where():
    """SliceLabelsStyle.where validator rejects malformed Jinja."""
    from dbt_charts.core.compile.models.style.theme import (
        LabelsDefaultTemplate,
        SliceLabelsStyle,
    )

    dt = LabelsDefaultTemplate(
        with_color="{{ color }}: {{ value }}", no_color="{{ value }}"
    )
    with pytest.raises(ValidationError):
        SliceLabelsStyle(
            offset=10.0, line_height=16.0, default_template=dt, where="value >>>> 2"
        )


# --- Regression tests for formerly dropped validations ---


def test_pie_style_inner_radius_rejected_on_bar():
    """BarChartStylePatch has no 'pie' field — extra_forbidden rejects it."""
    with pytest.raises(ValidationError, match="pie"):
        BarChart(type="bar", x="a", y="b", style={"pie": {"inner_radius": 0.5}})


def test_pie_style_inner_radius_accepted_on_pie():
    """style.inner_radius is valid directly on PieChartStylePatch (no nested 'pie' key)."""
    p = PieChart(type="pie", theta="amount", style={"inner_radius": 0.3})
    assert p.style is not None
    assert p.style.inner_radius == 0.3


def test_chartpatch_union_dispatches_already_instantiated_callout():
    """An already-instantiated CalloutChart (plain BaseModel, not _BaseChartFields)
    must still dispatch through the AuthoredChart discriminator."""
    adapter = TypeAdapter(AuthoredChart)
    callout = CalloutChart(type="callout", message="hi")
    result = adapter.validate_python(callout)
    assert isinstance(result, CalloutChart)
