"""Tests that key compiled and input models have Field(description=...) annotations.

Field descriptions enable:
- Better IDE autocomplete tooltips in JSON Schema
- AI understanding of field semantics
- Auto-generation of apps/docs/docs/reference/yaml-reference.md via `just gen-yaml-reference`

Design: denylist approach — assert all model fields have descriptions,
with explicit exemptions for fields intentionally left bare (e.g., private/internal
fields, fields inherited from abstract bases that can't be annotated here).

TDD: these tests were written before the descriptions were added and drove the
implementation. Any field added to these models without a description will now fail CI.
"""

from pydantic import BaseModel

from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.board.normalized import Board, Layout, LayoutItem
from dbt_charts.core.compile.models.chart.authored import (
    BarChart,
    KpiChart,
    PieChart,
)
from dbt_charts.core.compile.models.chart.normalized import (
    _BaseChartFields,
)
from dbt_charts.core.compile.models.primitives import FormatConfig
from dbt_charts.core.compile.models.query.normalized import (
    HttpQuery,
    Query,
    SqlQuery,
    ValuesQuery,
)
from dbt_charts.core.compile.models.variable.authored import Variable


def _fields_missing_description(
    model: type[BaseModel], exemptions: set[str] | None = None
) -> list[str]:
    """Return field names that lack a description, excluding exempted fields."""
    skip = exemptions or set()
    return [
        name
        for name, field_info in model.model_fields.items()
        if name not in skip and not field_info.description
    ]


class TestChartDescriptions:
    """Every field on _BaseChartFields must have a description.

    _BaseChartFields is the base for all normalized chart family models — it's the
    primary output of compilation and the surface AI assistants see when writing render code.
    """

    def test_all_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(_BaseChartFields)
        assert not missing, (
            f"_BaseChartFields fields missing description: {missing}\n"
            "Add Field(description='...') to each field in models/chart/normalized.py"
        )


class TestChartFieldsDescriptions:
    """Every field on per-family chart patch classes must have a description.

    Per-family patches define the authored vocabulary for each chart type.
    """

    def test_bar_patch_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(BarChart)
        assert not missing, (
            f"BarChart fields missing description: {missing}\n"
            "Add Field(description='...') to each field in chart/authored.py"
        )

    def test_kpi_patch_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(KpiChart)
        assert not missing, (
            f"KpiChart fields missing description: {missing}\n"
            "Add Field(description='...') to each field in chart/authored.py"
        )

    def test_pie_patch_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(PieChart)
        assert not missing, (
            f"PieChart fields missing description: {missing}\n"
            "Add Field(description='...') to each field in chart/authored.py"
        )


class TestBoardDescriptions:
    """Every field on Board must have a description."""

    def test_all_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(Board)
        assert not missing, (
            f"Board fields missing description: {missing}\n"
            "Add Field(description='...') to each field in models/board/normalized.py"
        )


class TestLayoutDescriptions:
    """Every field on Layout and LayoutItem must have a description."""

    def test_layout_all_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(Layout)
        assert not missing, f"Layout fields missing description: {missing}"

    def test_layout_item_all_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(LayoutItem)
        assert not missing, f"LayoutItem fields missing description: {missing}"


class TestQueryBaseDescriptions:
    """Every field on Query base class must have a description."""

    def test_all_fields_have_descriptions(self) -> None:
        # variable_dependencies uses default_factory=frozenset — described via Field
        missing = _fields_missing_description(Query)
        assert not missing, f"Query base fields missing description: {missing}"


class TestQueryTypeDescriptions:
    """Every field on each query type must have a description."""

    def test_sql_query_all_fields_have_descriptions(self) -> None:
        # Exclude base class fields (tested separately via TestQueryBaseDescriptions)
        base_fields = set(Query.model_fields)
        missing = _fields_missing_description(SqlQuery, exemptions=base_fields)
        assert not missing, f"SqlQuery fields missing description: {missing}"

    def test_http_query_all_fields_have_descriptions(self) -> None:
        base_fields = set(Query.model_fields)
        missing = _fields_missing_description(HttpQuery, exemptions=base_fields)
        assert not missing, f"HttpQuery fields missing description: {missing}"

    def test_values_query_all_fields_have_descriptions(self) -> None:
        base_fields = set(Query.model_fields)
        missing = _fields_missing_description(ValuesQuery, exemptions=base_fields)
        assert not missing, f"ValuesQuery fields missing description: {missing}"


class TestInputTypeDescriptions:
    """Key input model fields must have descriptions."""

    # input_auto_detected is an exclude=True internal tracking field
    _VARIABLE_EXEMPTIONS: set[str] = {"input_auto_detected"}

    def test_board_all_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(AuthoredBoard)
        assert not missing, f"AuthoredBoard fields missing description: {missing}"

    def test_variable_all_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(Variable, self._VARIABLE_EXEMPTIONS)
        assert not missing, f"Variable fields missing description: {missing}"

    def test_format_config_all_fields_have_descriptions(self) -> None:
        missing = _fields_missing_description(FormatConfig)
        assert not missing, f"FormatConfig fields missing description: {missing}"
