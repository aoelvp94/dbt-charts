"""Root-level style.color is not a Deletion — same shape as the
kpi.style.color precedent (``test_kpi_style_color_deletion.py``, which pins
the registry has no Deletion for either tail): both the bare ``("color",)``
and anchored ``("style", "color")`` tails collide with a live sibling color
field elsewhere in the schema, so it is removed fail-loud instead — a plain
unknown-field error, not a silent strip. This file pins the fail-loud side:
authoring root ``style.color`` is rejected at the ``StylePatch``,
``AuthoredBoard``, and ``compile()`` layers alike.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile import compile
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.style.authored import StylePatch


def test_style_patch_rejects_color() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        StylePatch.model_validate({"color": "#bf8700"})


def test_authoring_root_style_color_is_rejected_end_to_end() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        AuthoredBoard.model_validate(
            {
                "title": "Test",
                "queries": {"q1": {"sql": "SELECT 1 AS revenue", "source": "test"}},
                "style": {"color": "#bf8700"},
                "charts": {
                    "revenue_kpi": {
                        "type": "kpi",
                        "query": "q1",
                        "value": "revenue",
                    }
                },
                "rows": ["revenue_kpi"],
            }
        )


def test_compile_rejects_root_style_color() -> None:
    """The live chart-family style.color means this is not recognized as a
    historical document either — one plain unknown-field error, not a
    silent migration."""
    result = compile(
        """title: Test
queries:
  q1:
    sql: SELECT 1 AS revenue
    source: test
style:
  color: '#bf8700'
charts:
  revenue_kpi:
    type: kpi
    query: q1
    value: revenue
rows:
- revenue_kpi
"""
    )

    assert not result.success
    unknown = {e.fields.get("unknown_field") for e in result.errors if e.fields}
    assert "color" in unknown
