"""Content-regression tests for the `intro` orientation skill.

`dct skills intro` is the first thing an agent that has never met dbt charts
reads, so the body has to carry the install line, disambiguate the product,
and route to every other CLI workflow skill by name. Deterministic: reads the
rendered body, no LLM.
"""

from __future__ import annotations

import pytest

from dbt_charts.agent_api.skills import SkillNotFound, get_skill, list_skills

SKILL = "intro"


@pytest.fixture(scope="module")
def body() -> str:
    return get_skill(SKILL, surface="cli").body


def test_skill_is_cli_only() -> None:
    assert SKILL in {s.name for s in list_skills(surface="cli").skills}
    with pytest.raises(SkillNotFound):
        get_skill(SKILL, surface="tool")


def test_description_triggers_on_the_marketing_sentence() -> None:
    description = get_skill(SKILL, surface="cli").description
    assert "make charts" in description.lower()
    assert "Do NOT use" in description


def test_names_the_install_line_and_the_version_check(body: str) -> None:
    assert "uv tool install dbt-charts" in body
    assert "dct --version" in body


def test_disambiguates_from_dbt_labs_cloud(body: str) -> None:
    assert "dbtcharts.com" in body
    assert "getdbt.com" in body


def test_routes_to_every_other_cli_workflow_skill(body: str) -> None:
    """On the `cli` surface, a sibling reference renders as the bare registry
    name: what `dct skills <name>` accepts, the same table this skill's own
    body points readers to."""
    workflows = {
        s.name
        for s in list_skills(surface="cli").skills
        if s.kind == "workflow" and s.name != SKILL
    }
    missing = sorted(name for name in workflows if f"`{name}`" not in body)
    assert missing == [], f"intro does not route to: {missing}"


def test_skill_install_is_optional_and_named(body: str) -> None:
    lowered = body.lower()
    assert "dct skills <name>" in body
    assert "dct init skills" in body
    assert "optional" in lowered


def test_covers_the_three_places_data_lives(body: str) -> None:
    assert "type: values" in body
    assert "type: csv" in body
    assert "dbt_charts.yml" in body
