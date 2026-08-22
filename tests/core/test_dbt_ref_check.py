"""Tests for core/dbt_ref_check.py — extract_ref_calls extraction primitive."""

from __future__ import annotations

from dataclasses import dataclass, field

from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.diagnostics.diagnostic import Diagnostic


@dataclass
class _FakeCompileResult:
    """Minimal stand-in for CompileResult — only the fields dbt_ref_check reads."""

    query_registry: dict[str, object] = field(default_factory=dict)
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)


_REF_SQL = "SELECT * FROM {{ ref('orders') }}"
_SOURCE_SQL = "SELECT * FROM {{ source('jaffle', 'customers') }}"
_PLAIN_SQL = "SELECT 1"
_BOTH_SQL = "SELECT * FROM {{ ref('orders') }} JOIN {{ source('jaffle', 'customers') }}"


def _sql_query(sql: str) -> SqlQuery:
    return SqlQuery(sql=sql)


def test_extract_finds_refs() -> None:
    from dbt_charts.core.dbt_ref_check import QueryRefCalls, extract_ref_calls

    result = _FakeCompileResult(query_registry={"my_query": _sql_query(_REF_SQL)})
    found = extract_ref_calls(result)  # type: ignore[arg-type]
    assert found == {"my_query": QueryRefCalls(refs=["orders"], sources=[])}


def test_extract_finds_sources() -> None:
    from dbt_charts.core.dbt_ref_check import QueryRefCalls, extract_ref_calls

    result = _FakeCompileResult(query_registry={"src_query": _sql_query(_SOURCE_SQL)})
    found = extract_ref_calls(result)  # type: ignore[arg-type]
    assert found == {
        "src_query": QueryRefCalls(refs=[], sources=[("jaffle", "customers")])
    }


def test_extract_skips_queries_with_no_dbt_calls() -> None:
    from dbt_charts.core.dbt_ref_check import extract_ref_calls

    result = _FakeCompileResult(query_registry={"plain": _sql_query(_PLAIN_SQL)})
    found = extract_ref_calls(result)  # type: ignore[arg-type]
    assert found == {}


def test_extract_mixed() -> None:
    """Only queries with dbt calls appear in the result."""
    from dbt_charts.core.dbt_ref_check import QueryRefCalls, extract_ref_calls

    result = _FakeCompileResult(
        query_registry={
            "with_ref": _sql_query(_REF_SQL),
            "plain": _sql_query(_PLAIN_SQL),
        }
    )
    found = extract_ref_calls(result)  # type: ignore[arg-type]
    assert set(found.keys()) == {"with_ref"}
    assert found["with_ref"] == QueryRefCalls(refs=["orders"], sources=[])
