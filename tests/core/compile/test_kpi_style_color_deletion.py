"""kpi.style.color is not a Deletion — the tail collides with the live
style.color on every other chart family, so it is removed fail-loud instead.

Same shape as the GridLayout.gap precedent
(``test_inert_grid_keys_deletion.py``): no Deletion is registered, an
authored board using the old key is not recognized as historical (its tail
still validates against a live sibling key on other families), and the
author sees a plain unknown-field error instead of a silent strip.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile import compile
from dbt_charts.core.compile.migrations.migrations import _board_migration_context
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.style.authored import KpiChartStylePatch


def test_no_deletion_registered_for_kpi_style_color() -> None:
    """The tail collides with the live style.color on other families."""
    _, registry = _board_migration_context()
    tails = {d.path for d in registry.deletions}
    assert ("color",) not in tails
    assert ("style", "color") not in tails


def test_kpi_chart_style_patch_rejects_color() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        KpiChartStylePatch.model_validate({"color": "#bf8700"})


def test_authoring_kpi_style_color_is_rejected_end_to_end() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        AuthoredBoard.model_validate(
            {
                "title": "Test",
                "queries": {"q1": {"sql": "SELECT 1 AS revenue", "source": "test"}},
                "charts": {
                    "revenue_kpi": {
                        "type": "kpi",
                        "query": "q1",
                        "value": "revenue",
                        "style": {"color": "#bf8700"},
                    }
                },
                "rows": ["revenue_kpi"],
            }
        )


def test_compile_rejects_kpi_style_color() -> None:
    """The other chart families' live style.color means this is not
    recognized as a historical document either — one plain unknown-field
    error, not a silent migration."""
    result = compile(
        """title: Test
queries:
  q1:
    sql: SELECT 1 AS revenue
    source: test
charts:
  revenue_kpi:
    type: kpi
    query: q1
    value: revenue
    style:
      color: '#bf8700'
rows:
- revenue_kpi
"""
    )

    assert not result.success
    unknown = {e.fields.get("unknown_field") for e in result.errors if e.fields}
    assert "color" in unknown
