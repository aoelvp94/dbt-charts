"""Tests for agent_api.validate_query — typed stateless SQL lint verb."""

from __future__ import annotations

from dbt_charts.agent_api import QueryDiagnostic
from dbt_charts.agent_api.validate_query import validate_query


def test_validate_query_returns_typed_diagnostics_and_honors_suppress() -> None:
    clean = validate_query("SELECT 1")
    assert clean == []

    # Comma-join over two tables → WARN-MISSING-JOIN-PREDICATE (error severity).
    bad_sql = "SELECT a.x, b.y FROM t1 a, t2 b"
    findings = validate_query(bad_sql)
    assert findings, "expected at least one diagnostic for an implicit cross join"
    assert all(isinstance(f, QueryDiagnostic) for f in findings)
    codes = {f.code for f in findings}
    assert "WARN-MISSING-JOIN-PREDICATE" in codes

    suppressed = validate_query(bad_sql, suppress={"WARN-MISSING-JOIN-PREDICATE"})
    assert "WARN-MISSING-JOIN-PREDICATE" not in {f.code for f in suppressed}
