"""Drift guard: every authored Pydantic enum is mentioned in DBT_CHARTS_SYNTAX.md.

The canonical YAML syntax reference lives in ``dbt_charts/DBT_CHARTS_SYNTAX.md``
and is currently hand-curated. Until codegen takes over (see the
build-the-dataface-core-spec-reference initiative), this test fires whenever a
``AUTHORED_CHART_TYPE_TAGS`` or ``VariableInputType`` value is added without a matching
mention in the doc.
"""

from __future__ import annotations

import importlib.resources
from typing import get_args

import pytest

from dbt_charts.core.compile.models.chart.authored import AUTHORED_CHART_TYPE_TAGS
from dbt_charts.core.compile.models.query.authored import RestMethod, TimeGrain
from dbt_charts.core.compile.models.variable.authored import VariableInputType

_SYNTAX_TEXT = (
    importlib.resources.files("dbt_charts") / "DBT_CHARTS_SYNTAX.md"
).read_text(encoding="utf-8")


@pytest.mark.parametrize("value", sorted(AUTHORED_CHART_TYPE_TAGS))
def test_chart_type_documented_in_syntax(value: str) -> None:
    """Every authorable chart type must appear verbatim in DBT_CHARTS_SYNTAX.md."""
    assert value in _SYNTAX_TEXT, (
        f"Authorable chart type {value!r} is not documented in dbt_charts/DBT_CHARTS_SYNTAX.md. "
        "Add a mention in the ## Charts section (or mark it internal explicitly)."
    )


@pytest.mark.parametrize("value", sorted(set(get_args(VariableInputType))))
def test_variable_input_type_documented_in_syntax(value: str) -> None:
    """Every VariableInputType literal must appear in DBT_CHARTS_SYNTAX.md."""
    assert value in _SYNTAX_TEXT, (
        f"VariableInputType {value!r} is not documented in dbt_charts/DBT_CHARTS_SYNTAX.md. "
        "Add it to the ## Variables section."
    )


@pytest.mark.parametrize("value", sorted(set(get_args(TimeGrain))))
def test_time_grain_documented_in_syntax(value: str) -> None:
    """Every TimeGrain literal must appear in DBT_CHARTS_SYNTAX.md."""
    assert value in _SYNTAX_TEXT, (
        f"TimeGrain {value!r} is not documented in dbt_charts/DBT_CHARTS_SYNTAX.md. "
        "Add it to the ## Queries section (MetricFlow)."
    )


@pytest.mark.parametrize("value", sorted(set(get_args(RestMethod))))
def test_rest_method_documented_in_syntax(value: str) -> None:
    """Every RestMethod literal must appear in DBT_CHARTS_SYNTAX.md."""
    assert value in _SYNTAX_TEXT, (
        f"RestMethod {value!r} is not documented in dbt_charts/DBT_CHARTS_SYNTAX.md. "
        "Add it to the ## Queries section (HTTP)."
    )
