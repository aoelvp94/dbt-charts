"""Content-regression test for the board-build skill's label/title guidance.

The engine infers a label from the object key for **variables** only
(`inferred_display_name` in `core/text/case.py`, wired through
`render/variables_resolve.py`) -- it never infers a chart's own `label`
(KPI) or `title` (every other chart type) from its object key. An earlier
revision of this skill told agents to "omit `label`, `title`" on the belief
both were inferred like the variable fields, which shipped boards with bare,
uncaptioned KPI tiles. Deterministic, no LLM -- same pattern as
`test_cloud_setup_skill.py` / `test_review_skills.py`.
"""

from __future__ import annotations

import pytest

from dbt_charts.agent_api.skills import get_skill

SKILL = "board-build"


@pytest.fixture(scope="module")
def body() -> str:
    return get_skill(SKILL).body


def test_does_not_claim_chart_label_or_title_are_inferred(body: str) -> None:
    """Only variable `label` is inferred from the object key -- chart `label`/`title` never are."""
    assert "labels and titles are inferred from object keys" not in body.lower()
    assert "omit `label`, `title`" not in body


def test_tells_agents_to_set_kpi_label_and_chart_title(body: str) -> None:
    assert "label:" in body.lower() or "set `label`" in body.lower()
    assert "kpi" in body.lower()
