"""TDD tests for y-axis position: auto resolution.

After this feature:
- BaseAxisStyle.position accepts Literal["left","right","top","bottom","auto"]
- "auto" → "right" when endpoint labels are not enabled (default)
- "auto" → "left" when line endpoint labels are on the right edge
- Explicit "left"/"right" always pass through unchanged
- Invalid values raise ValidationError at compile time
"""

from __future__ import annotations

from pydantic import TypeAdapter

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import Chart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_RESOLVED_STYLE, _BOARD_STYLE = resolve_style_and_context(get_theme_style())

_DATA = [{"month": "Jan", "rev": 100}, {"month": "Feb", "rev": 200}]


def _spec(chart_type: str = "bar", style=None) -> dict:
    reset_config()
    chart = TypeAdapter(Chart).validate_python(
        {
            "id": "t",
            "type": chart_type,
            "x": "month",
            "y": "rev",
            "query": SqlQuery(sql="SELECT 1", source="src"),
            "query_name": "q",
            "style": style,
        }
    )
    return generate_vega_lite_spec(
        chart,
        _DATA,
        board_style=_RESOLVED_STYLE,
        chart_style_context=_BOARD_STYLE,
        width=400,
    )


def test_auto_resolves_right_without_endpoint_labels():
    """position: auto → 'right' for bar charts (endpoint labels disabled by default)."""
    from dbt_charts.core.compile.models.style.authored import (
        BarChartStylePatch,
    )

    spec = _spec(
        chart_type="bar",
        style=BarChartStylePatch(orientation="vertical"),
    )
    y_axis = spec.get("encoding", {}).get("y", {}).get("axis", {})
    assert y_axis.get("orient") == "right", (
        f"Expected right, got {y_axis.get('orient')}"
    )


# Positive cases (position flips to "left" when the endpoint-label pane
# actually fires, i.e., multi-series + non-horizontal-bar) and negative
# cases (single-series → no flip; horizontal bar → no flip) are covered
# by `test_endpoint_label_pane_predicate.py`. The orient resolver
# delegates the firing condition to
# `EndpointLabelFeature.applies_to()` in `features/endpoint_labels.py`.


def test_auto_resolves_right_for_bar_no_endpoint_labels():
    """position: auto → 'right' for bar (no endpoint_labels field); getattr returns None."""
    from dbt_charts.core.compile.models.style.authored import (
        BarChartStylePatch,
    )

    spec = _spec(
        chart_type="bar",
        style=BarChartStylePatch(orientation="vertical"),
    )
    y_axis = spec.get("encoding", {}).get("y", {}).get("axis", {})
    assert y_axis.get("orient") == "right", (
        f"Expected right for bar (no endpoint_labels), got {y_axis.get('orient')}"
    )


def test_explicit_left_bypasses_auto():
    """position: left in a chart-local patch always produces 'left', regardless of endpoint labels."""
    from dbt_charts.core.compile.models.style.authored import (
        AxisYStylePatch,
        BarChartStylePatch,
    )

    patch = BarChartStylePatch(axis_y=AxisYStylePatch(position="left"))
    spec = _spec(chart_type="bar", style=patch)
    y_axis = spec.get("encoding", {}).get("y", {}).get("axis", {})
    assert y_axis.get("orient") == "left"


def test_explicit_right_bypasses_auto():
    """position: right in a chart-local patch always produces 'right'."""
    from dbt_charts.core.compile.models.style.authored import (
        AxisYStylePatch,
        BarChartStylePatch,
    )

    patch = BarChartStylePatch(
        orientation="vertical", axis_y=AxisYStylePatch(position="right")
    )
    spec = _spec(chart_type="bar", style=patch)
    y_axis = spec.get("encoding", {}).get("y", {}).get("axis", {})
    assert y_axis.get("orient") == "right"


def test_invalid_orientation_raises_validation_error():
    """position: 'diagonal' raises ValidationError at compile time."""
    import pytest
    from pydantic import ValidationError

    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.models.style.theme import AxisYStyle

    base = get_theme_style().charts.axis_y
    data = base.model_dump()
    data["position"] = "diagonal"
    with pytest.raises(ValidationError, match="diagonal"):
        AxisYStyle.model_validate(data)


def test_editorial_theme_preserves_auto_orientation_sentinel():
    """editorial (and descendants like cream) must keep axis_y.position
    as the 'auto' sentinel so the endpoint-labels collision flip fires.

    Hardcoding 'right' in a theme short-circuits ``_resolve_position_auto`` and
    causes the y-axis to collide with the right-edge endpoint label pane on
    multi-series line/area charts.
    """
    from dbt_charts.core.compile.config import get_theme_style

    for theme_name in ("editorial", "cream"):
        compiled = get_theme_style(theme_name)
        assert compiled.charts.axis_y.position == "auto", (
            f"{theme_name} theme overrides axis_y.position to "
            f"{compiled.charts.axis_y.position!r}; this short-circuits the "
            f"endpoint-labels auto-flip helper. Use 'auto' instead."
        )
