"""Content-regression tests for the cloud-setup onboarding skill.

Deterministic — reads the rendered SKILL.md body and asserts the guidance that
stops the four onboarding failures seen in the wild. No LLM is invoked; this is
the same pattern as `test_review_skills.py`.

The skill is CLI-only (`surfaces: [cli]`), so every read passes `surface="cli"`.
"""

from __future__ import annotations

import pytest

from dbt_charts.agent_api.skills import get_skill, list_skills

SKILL = "cloud-setup"


@pytest.fixture(scope="module")
def body() -> str:
    return get_skill(SKILL, surface="cli").body


def test_skill_is_discoverable() -> None:
    names = {s.name for s in list_skills(surface="cli").skills}
    assert SKILL in names, f"Registry missing {SKILL}; got {sorted(names)}"


def test_description_has_negative_boundary() -> None:
    assert "Do NOT use" in get_skill(SKILL, surface="cli").description


def test_disambiguates_from_dbt_labs_cloud(body: str) -> None:
    assert "dbtcharts.com" in body
    assert "getdbt.com" in body
    lowered = body.lower()
    assert "dbt labs" in lowered, "must name dbt Labs' dbt Cloud as the wrong product"


def test_forbids_account_creation_refusal(body: str) -> None:
    lowered = body.lower()
    assert "never refuse" in lowered
    assert "not a blocker" in lowered
    assert "sign up" in lowered or "sign-up" in lowered


def test_checks_github_auth_up_front(body: str) -> None:
    assert "gh auth status" in body
    before_you_start = body.index("Before you start")
    step_connect = body.index("Connect the project")
    assert before_you_start < body.index("gh auth status") < step_connect, (
        "GitHub auth check must sit in 'Before you start', not only at connect time"
    )


def test_owns_repo_folder_decision(body: str) -> None:
    lowered = body.lower()
    assert "dbt_charts.yml" in body
    assert "new repo" in lowered
    assert "git repo" in lowered


def test_step3_gates_on_authored_boards(body: str) -> None:
    """Step 3 must key the board-build handoff off user-authored boards, not the
    mere presence of `charts/` — else the `dct init` starter board gets connected
    and rendered as the user's own."""
    lowered = body.lower()
    assert "starter board" in lowered
    assert "authored" in lowered


def test_no_destructive_verb(body: str) -> None:
    """The skill must never name a Cloud delete verb (the 'delete the temp
    credential file' housekeeping instruction is fine — that's a local file)."""
    for verb in ("org delete", "project delete", "connection delete", "cloud delete"):
        assert verb not in body.lower(), (
            f"cloud-setup must not invoke `dct cloud {verb}`"
        )


def test_login_waits_for_approval_itself(body: str) -> None:
    """The agent must surface the URL at once and then block on the CLI's own
    `Logged in` line — not background the login and wait to be told."""
    assert "Logged in" in body
    assert "until grep" in body
    lowered = body.lower()
    assert "which account" in lowered, "must say whose browser account approves"


def test_warns_about_local_only_sources_before_boards(body: str) -> None:
    """A DuckDB/SQLite project learns Cloud can't connect to it before any board
    is authored in that dialect — in the pre-flight, not at connection time."""
    lowered = body.lower()
    duckdb_at = lowered.index("duckdb")
    assert body.index("Before you start") < duckdb_at < body.index("## Step 1")
    assert "parquet" in lowered
    assert "bigquery, postgresql, redshift, snowflake" in lowered


def test_render_gated_on_mapped_sources(body: str) -> None:
    """A board whose every query failed still completes a render, so `ready`
    from `dct cloud boards` is not evidence of data — the skill must say so."""
    assert "`ready`" in body
    render_at = body.index("Step 7")
    assert "unmapped" in body[render_at:].lower()


def test_uses_bare_dct(body: str) -> None:
    assert "dct cloud login" in body
    assert "uv run dct" not in body, "shipped skill uses bare `dct`"
