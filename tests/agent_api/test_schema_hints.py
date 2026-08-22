from dbt_charts.agent_api import SchemaHints
from dbt_charts.agent_api.schema_hints import schema_hints


def test_schema_hints_returns_typed_view_of_compile_constants() -> None:
    result = schema_hints()

    assert isinstance(result, SchemaHints)
    # chart_types reflects the authorable chart type tags
    assert "bar" in result.chart_types
    assert "line" in result.chart_types
    # Internal chart types (UI-hidden in _INTERNAL_CHART_TYPES) must not leak
    # into the public schema view consumed by LSP autocomplete.
    assert "auto" not in result.chart_types
    assert "donut" not in result.chart_types
    # input_types reflects VariableInputType
    assert "select" in result.input_types
    assert "slider" in result.input_types
    # theme_names reflects user_facing_theme_names()
    assert "stark" in result.theme_names
    # Private/diagnostic-only themes must not leak into the LSP-facing view.
    assert not any(t.startswith("_") for t in result.theme_names)
    assert not any(t.startswith("diagnostics-") for t in result.theme_names)
    # chart_type_display is a typed model with label + icon, matching the
    # shape of the canonical CHART_TYPE_DISPLAY dict in core.
    bar_display = result.chart_type_display["bar"]
    assert bar_display.label == "Bar"  # pin the live value
    assert bar_display.icon  # non-empty string
    # chart_types and chart_type_display cover exactly the same set of types
    # so consumers can index one by the other without missing entries.
    assert set(result.chart_types) == set(result.chart_type_display.keys())
    # Stateless: two calls return equal data
    assert schema_hints() == result
