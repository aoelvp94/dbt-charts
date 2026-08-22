"""Tests for ProjectSession.validate_query — relationship-calibrated SQL lint on ProjectSession.

These tests verify that:
1. ProjectSession.validate_query threads RelationshipContext into core, giving calibrated
   severity (e.g. "error" for high-fanout 1:N joins vs "warning" without context).
2. Graceful no-op when super-schema is not installed.
3. ProjectSession.refresh() invalidates the cached relationship context.
4. Both overload branches (default and return_suppressed=True) thread context.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from dbt_charts.agent_api.project_session import ProjectSession
from dbt_charts.agent_api.validate_query import (
    validate_query as stateless_validate_query,
)

# Skip all tests that exercise real super-schema I/O when the package is absent.
_SUPER_SCHEMA_AVAILABLE = (
    importlib.util.find_spec("dbt_charts_super_schema") is not None
)
pytestmark_super_schema = pytest.mark.skipif(
    not _SUPER_SCHEMA_AVAILABLE,
    reason="dbt_charts_super_schema not installed",
)

# SQL with a 1:N-risky join — aggregates from both tables → WARN-FANOUT-RISK candidate.
_JOIN_SQL = (
    "SELECT SUM(o.amount), SUM(li.qty) "
    "FROM orders o JOIN line_items li ON o.id = li.order_id "
    "GROUP BY o.id"
)


def _write_super_schema(project_dir: Path, fanout_factor: float = 20.0) -> None:
    """Write a fake super_schema.json with a 1:N orders→line_items hint.

    fanout_factor > HIGH_FANOUT_THRESHOLD (10.0) makes severity "error".
    """
    target = project_dir / "target"
    target.mkdir(exist_ok=True)
    data = {
        "version": 2,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "tables": {
            "orders": {
                "table_name": "orders",
                "relationships": [
                    {
                        "left_table": "orders",
                        "right_table": "line_items",
                        "confidence": 0.95,
                        "join_profile": {
                            "multiplicity": "one-to-many",
                            "fanout_factor": fanout_factor,
                        },
                    }
                ],
            },
            "line_items": {
                "table_name": "line_items",
                "relationships": [],
            },
        },
    }
    (target / "super_schema.json").write_text(json.dumps(data))


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Minimal project dir (no adapter needed — validate is stateless)."""
    (tmp_path / "dbt_charts.yml").write_text(
        "sources:\n  db:\n    type: duckdb\n    path: ':memory:'\n"
    )
    return tmp_path


@pytestmark_super_schema
def test_calibration_flows_through(project_dir: Path) -> None:
    """ProjectSession.validate_query returns calibrated 'error' for high-fanout 1:N join.

    The stateless agent_api.validate_query returns 'warning' for the same SQL
    because it has no relationship context.

    Also the regression pin for the cwd-coupling fix: no chdir happens, so the
    cache under project_dir is only found because load_relationship_context
    anchors to project.data_path(), not the process cwd. Before the fix the
    cwd-relative InspectionStorage() default missed it and severity stayed
    'warning'.
    """
    _write_super_schema(project_dir, fanout_factor=20.0)

    with ProjectSession.open(project_dir) as project_session:
        calibrated = project_session.validate_query(_JOIN_SQL)

    fanout_diags = [d for d in calibrated if d.code == "WARN-FANOUT-RISK"]
    assert fanout_diags, "expected at least one WARN-FANOUT-RISK diagnostic"
    assert fanout_diags[0].severity == "error", (
        f"expected calibrated 'error' severity, got {fanout_diags[0].severity!r}"
    )

    # Stateless verb has no relationship context → stays at 'warning'.
    uncalibrated = stateless_validate_query(_JOIN_SQL)
    fanout_uncal = [d for d in uncalibrated if d.code == "WARN-FANOUT-RISK"]
    assert fanout_uncal, "stateless validate_query should still detect WARN-FANOUT-RISK"
    assert fanout_uncal[0].severity == "warning"


def test_no_super_schema_returns_uncalibrated(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When super-schema is not available, validate_query returns uncalibrated severity."""
    monkeypatch.setattr(
        "dbt_charts.agent_api.project_session._SUPER_SCHEMA_AVAILABLE", False
    )
    with ProjectSession.open(project_dir) as project_session:
        diags = project_session.validate_query(_JOIN_SQL)

    fanout_diags = [d for d in diags if d.code == "WARN-FANOUT-RISK"]
    assert fanout_diags, "expected WARN-FANOUT-RISK even without context"
    assert fanout_diags[0].severity == "warning"


@pytestmark_super_schema
def test_refresh_invalidates_cache(project_dir: Path) -> None:
    """ProjectSession.refresh() forces _relationship_context to reload from disk."""
    # Write low fanout (below threshold) → 'warning'.
    _write_super_schema(project_dir, fanout_factor=2.0)
    with ProjectSession.open(project_dir) as project_session:
        diags_before = project_session.validate_query(_JOIN_SQL)
        fanout_before = [d for d in diags_before if d.code == "WARN-FANOUT-RISK"]
        assert fanout_before, "expected WARN-FANOUT-RISK diagnostic"
        sev_before = fanout_before[0].severity

        # Update the cache to high fanout → should become 'error' after refresh.
        _write_super_schema(project_dir, fanout_factor=20.0)

        # Without refresh, still sees old cached context.
        diags_stale = project_session.validate_query(_JOIN_SQL)
        fanout_stale = [d for d in diags_stale if d.code == "WARN-FANOUT-RISK"]
        assert fanout_stale[0].severity == sev_before, "expected stale cache hit"

        project_session.refresh()

        diags_after = project_session.validate_query(_JOIN_SQL)
        fanout_after = [d for d in diags_after if d.code == "WARN-FANOUT-RISK"]
        assert fanout_after, "expected WARN-FANOUT-RISK after refresh"
        assert fanout_after[0].severity == "error", (
            "expected 'error' after refresh loaded high-fanout hint"
        )


@pytestmark_super_schema
def test_return_suppressed_overload_threads_relationship_context(
    project_dir: Path,
) -> None:
    """return_suppressed=True branch also threads relationship_context.

    SQL has '-- dct:ignore WARN-FANOUT-RISK' so WARN-FANOUT-RISK is suppressed.
    The suppressed diagnostic should carry calibrated 'error' severity —
    proving that both overload branches forward the context.
    """
    _write_super_schema(project_dir, fanout_factor=20.0)

    sql_ignored = f"-- dct:ignore WARN-FANOUT-RISK\n{_JOIN_SQL}"
    with ProjectSession.open(project_dir) as project_session:
        active, suppressed = project_session.validate_query(
            sql_ignored, return_suppressed=True
        )

    suppressed_fanout = [d for d in suppressed if d.code == "WARN-FANOUT-RISK"]
    assert suppressed_fanout, "WARN-FANOUT-RISK should appear in suppressed list"
    assert suppressed_fanout[0].severity == "error", (
        "suppressed diagnostic should carry calibrated severity"
    )
    active_fanout = [d for d in active if d.code == "WARN-FANOUT-RISK"]
    assert not active_fanout, "WARN-FANOUT-RISK should not appear in active list"
