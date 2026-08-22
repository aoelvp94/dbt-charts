"""board.py must thread _relationship_context() into validate_compiled_queries.

Tests here exercise the board.py wiring seam — the guarantee that deleting
relationship_context= from validate_compiled_queries calls in board.py makes
the suite fail. The SQL uses a single-table SUM (no multi_table_agg structural
signal) so WARN-FANOUT-RISK only fires via the relationship-triggered path when
relationship_context is non-None.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.board import render_dashboard
from dbt_charts.core.execute.adapters import AdapterRegistry
from dbt_charts.core.inspect.query_validator import (
    RelationshipContext,
    RelationshipHint,
)
from dbt_charts.core.project import InMemoryBoard
from dbt_charts.core.render.render_result import RenderResult

# Single-table SUM in a JOIN — no multi_table_agg structural signal.
# WARN-FANOUT-RISK only fires if relationship_context is passed to
# validate_compiled_queries.
_BOARD_YAML = """\
queries:
  revenue:
    sql: >-
      SELECT SUM(o.amount) AS total
      FROM orders o JOIN items i ON o.id = i.order_id
      GROUP BY o.id
    source: analytics
charts:
  revenue_trend:
    query: revenue
    type: bar
    x: o.id
    y: total
rows:
  - revenue_trend
"""

_NM_CTX = RelationshipContext(
    hints=(
        RelationshipHint(
            left_table="orders",
            right_table="items",
            multiplicity="many-to-many",
            fanout_factor=5.0,
            confidence=0.9,
        ),
    )
)


class TestBoardRelationshipWiring:
    """board.py full-render path threads _relationship_context() to the linter."""

    def test_full_render_threads_relationship_context_to_lint(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Full-render arm wires _relationship_context() into structural lint.

        Patches board._relationship_context to return an N:M RelationshipContext
        and asserts error-severity WARN-FANOUT-RISK appears — only possible when
        the context reaches validate_compiled_queries. Deleting
        relationship_context=_relationship_context(project) from board.py makes
        this test fail.
        """
        project = local_project(tmp_path)
        mock_registry = MagicMock(spec=AdapterRegistry)
        render_result = RenderResult(
            output='{"id": "test", "title": "Revenue Board", "items": []}'
        )

        with (
            patch("dbt_charts.core.board._relationship_context", return_value=_NM_CTX),
            patch("dbt_charts.core.board.render", return_value=render_result),
            patch("dbt_charts.core.board.Executor"),
        ):
            result = render_dashboard(
                board=InMemoryBoard(_BOARD_YAML, path=project.path("charts/test.yaml")),
                adapter_registry=mock_registry,
                format="json",
                project=project,
                result_cache=None,
            )

        fanout_errors = [
            w
            for w in result.warnings
            if w.code == "WARN-FANOUT-RISK" and w.fields.get("severity") == "error"
        ]
        assert len(fanout_errors) >= 1, (
            "board.py must pass relationship_context to validate_compiled_queries; "
            "N:M hint must produce error-severity WARN-FANOUT-RISK; "
            f"got: {[(w.code, w.fields.get('severity')) for w in result.warnings]}"
        )
