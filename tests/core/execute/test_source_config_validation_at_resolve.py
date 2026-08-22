"""D1 tests: malformed source configs raise typed ERR-SOURCE-* codes at resolve time.

These tests verify that source-config validation fires at the resolver boundary
(before any DB driver loads), not inside the adapter.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import ProjectSourcesConfig
from dbt_charts.core.diagnostics.codes_execute import (
    ERR_SOURCE_INVALID_TYPE,
    ERR_SOURCE_MISSING_TYPE,
)


def _project_sources(**sources: dict) -> ProjectSourcesConfig:
    ps = ProjectSourcesConfig()
    ps.sources = dict(sources)
    return ps


@pytest.fixture
def resolver():
    from dbt_charts.core.execute.source_resolver import DefaultSourceResolver

    return DefaultSourceResolver()


class TestSourceConfigValidationAtResolve:
    """D1: type-validation errors surface as ERR-SOURCE-* at resolve time."""

    def test_missing_type_raises_at_resolve(self, resolver):
        """Inline dict without 'type' raises ERR-SOURCE-MISSING-TYPE."""
        from dbt_charts.core.diagnostics.base import DbtChartsError

        with pytest.raises(DbtChartsError) as exc_info:
            resolver.resolve(
                authored={"path": ":memory:"},
                board_sources={},
                project_sources=_project_sources(),
                dbt_context=None,
            )
        assert exc_info.value.code == ERR_SOURCE_MISSING_TYPE

    def test_unknown_type_raises_at_resolve(self, resolver):
        """Inline dict with unrecognized 'type' raises ERR-SOURCE-INVALID-TYPE."""
        from dbt_charts.core.diagnostics.base import DbtChartsError

        with pytest.raises(DbtChartsError) as exc_info:
            resolver.resolve(
                authored={"type": "oracledb", "host": "db.example.com"},
                board_sources={},
                project_sources=_project_sources(),
                dbt_context=None,
            )
        assert exc_info.value.code == ERR_SOURCE_INVALID_TYPE

    def test_missing_type_in_board_source_raises_at_resolve(self, resolver):
        """Named board source without 'type' raises ERR-SOURCE-MISSING-TYPE."""
        from dbt_charts.core.diagnostics.base import DbtChartsError

        board_sources = {"bad_db": {"path": ":memory:"}}
        with pytest.raises(DbtChartsError) as exc_info:
            resolver.resolve(
                authored="bad_db",
                board_sources=board_sources,
                project_sources=_project_sources(),
                dbt_context=None,
            )
        assert exc_info.value.code == ERR_SOURCE_MISSING_TYPE

    def test_missing_type_in_project_source_raises_at_resolve(self, resolver):
        """Named project source without 'type' raises ERR-SOURCE-MISSING-TYPE."""
        from dbt_charts.core.diagnostics.base import DbtChartsError

        project_sources = _project_sources(bad_db={"path": ":memory:"})
        with pytest.raises(DbtChartsError) as exc_info:
            resolver.resolve(
                authored="bad_db",
                board_sources={},
                project_sources=project_sources,
                dbt_context=None,
            )
        assert exc_info.value.code == ERR_SOURCE_MISSING_TYPE

    def test_fr008_authored_none_no_default_returns_none(self, resolver):
        """FR-008: authored=None without project default returns None."""
        result = resolver.resolve(
            authored=None,
            board_sources={},
            project_sources=_project_sources(),
            dbt_context=None,
        )
        assert result is None
