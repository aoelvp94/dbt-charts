"""The MetricFlow authoring surface is gone, and legacy boards fail loudly.

Pre-launch removal (no compat shim): `type: metricflow`, chart-level `model:`,
and `Variable.model`/`Variable.dimension`/`Variable.measure` are not
accepted-and-ignored — each names the offending key in the error an author
sees. Mirrors `test_lookml_surface_removed.py` (deleted alongside the LookML
pull-out, but the pattern is the precedent this file follows): assert on the
key name, not the exception class, since the failure path differs (explicit
`type: metricflow` fails union discrimination; `model:`/`dimension:`/
`measure:` fail extra_forbidden).
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from dbt_charts.core.compile.models.chart.authored import BarChart
from dbt_charts.core.compile.models.query.authored import AuthoredQuery
from dbt_charts.core.compile.models.refs import normalize_query_value
from dbt_charts.core.compile.models.variable.authored import Variable

_ADAPTER: TypeAdapter[object] = TypeAdapter(AuthoredQuery)


def _validate(query_dict: dict[str, object]) -> object:
    return _ADAPTER.validate_python(normalize_query_value(query_dict))


def test_explicit_metricflow_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="metricflow"):
        _validate({"type": "metricflow", "metrics": ["revenue"]})


def test_bare_metrics_key_no_longer_infers_metricflow() -> None:
    """`metrics:`/`dimensions:` without an explicit `type:` used to infer
    `type: metricflow`; with the union member gone, it falls through to `sql`
    and trips extra_forbidden on `metrics` — still rejected, different reason."""
    with pytest.raises(ValidationError, match="metrics"):
        _validate({"metrics": ["revenue"]})


def test_chart_model_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="model"):
        BarChart(type="bar", x="month", y="revenue", model="analytics.orders")  # type: ignore[call-arg]


def test_variable_model_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="model"):
        Variable(model="orders")  # type: ignore[call-arg]


def test_variable_dimension_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="dimension"):
        Variable(dimension="region")  # type: ignore[call-arg]


def test_variable_measure_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="measure"):
        Variable(measure="total_revenue")  # type: ignore[call-arg]
