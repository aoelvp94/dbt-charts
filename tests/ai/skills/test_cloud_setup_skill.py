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


def test_recommends_registry_sources_first(body: str) -> None:
    """The pre-flight bullet recommends the `sources:` registry before the
    inline one-off path and no longer warns that Cloud can't resolve
    registry file sources."""
    where_data_lives = body.index("Where the data lives")
    step1 = body.index("## Step 1")
    section_lower = body[where_data_lives:step1].lower()
    assert "sources:" in section_lower
    assert section_lower.index("sources:") < section_lower.index("source: ")
    assert "one-off" in section_lower
    assert "does not resolve registry file sources" not in body.lower()


def test_render_gated_on_mapped_sources(body: str) -> None:
    """A board whose every query failed still completes a render, so `ready`
    from `dct cloud boards` is not evidence of data — the skill must say so."""
    assert "`ready`" in body
    render_at = body.index("## Step 7")
    assert "unmapped" in body[render_at:].lower()


def test_github_only(body: str) -> None:
    """Cloud connects GitHub repositories only; the skill must not promise any
    other git host, and must keep the public-URL path to GitHub URLs."""
    lowered = body.lower()
    assert "any repo cloud can clone" not in lowered
    assert "any git host" not in lowered
    assert "other git hosts" in lowered, "must say other hosts are unsupported"
    assert "https://github.com/" in body


def test_connect_runs_right_after_login(body: str) -> None:
    """The GitHub App install is the only other browser hop, so it follows login
    in the same sitting and waits in the background while boards get authored."""
    connect_at = body.index("Connect the project")
    assert body.index("## Step 1") < connect_at < body.index("Boards, if none exist")
    connect_section = body[connect_at : body.index("Boards, if none exist")]
    assert "/tmp/dct-connect.log" in connect_section
    assert "Picked" in connect_section, "must wait on the CLI's own pick line"


def test_serves_locally_and_keeps_going(body: str) -> None:
    """The user should see boards in a local `dct serve` before Cloud renders
    them; the agent opens the URL and continues, it does not stop for approval."""
    serve_at = body.index("dct serve", body.index("## Step 1"))
    assert serve_at < body.index("## When you're done")
    lowered = body.lower()
    assert "keep going" in lowered
    assert "local url" in lowered


def test_file_source_projects_skip_the_warehouse_step(body: str) -> None:
    """A csv/json/parquet project needs no connection at all; the skill must say
    so at the top of the warehouse step, so `connections: 0` doesn't read as an
    unfinished setup."""
    step5 = body.index("## Step 5")
    head = body[step5 : body.index("## Step 6")].lower()
    assert "skip this whole step" in head
    assert "file source" in head
    assert "connections: 0" in head


def test_says_how_to_ship_a_change_after_setup(body: str) -> None:
    """Day two is 'I edited a board, get it live'. A push republishes on its
    own, on a latency that depends on how the repo is connected, and `ready` is
    not evidence the live render is yours."""
    step8 = body.index("## Step 8")
    section = body[step8 : body.index("## The loop that actually drives this")]
    lowered = section.lower()
    assert "republishes on its own" in lowered
    assert "github app" in lowered
    assert "hourly" in lowered
    assert "dct cloud project sync" in section
    assert "no timestamp" in lowered


def test_day_two_is_reachable_from_the_status_loop(body: str) -> None:
    """The loop section tells the agent to drive from `dct cloud status` until
    it reports nothing left, and `status` never names "tell the user how to ship
    a change" — so Step 8 is skippable unless the sign-off says otherwise."""
    section = body[body.index("## When you're done") :].lower()
    assert "step 8" in section
    assert "will never prompt you to" in section


def test_uses_bare_dct(body: str) -> None:
    assert "dct cloud login" in body
    assert "uv run dct" not in body, "shipped skill uses bare `dct`"


def test_mapping_rerenders_and_force_is_the_manual_lever(body: str) -> None:
    """The first render fires on sync, before any source is mapped. The skill
    must say that mapping re-renders on its own, and name ``--force`` for the
    case where nothing else moves a dead board."""
    map_at = body.index("## Step 6")
    render_at = body.index("## Step 7")
    assert "re-render" in body[map_at:render_at].lower()
    assert "dct cloud render --force" in body[render_at:]


def test_verifies_each_board_with_its_own_token(body: str) -> None:
    """The agent fetches the board it published rather than handing an
    unchecked URL to the user: the login token reads board pages, so
    "I could not see it myself" is no longer a valid handoff."""
    done_at = body.index("## When you're done")
    section = body[done_at:]
    assert "Authorization: Bearer" in section
    assert "dct cloud boards --json" in section
    lowered = section.lower()
    assert "unverified" in lowered, "a refused fetch is not a broken board"
    assert "never echo" in lowered, "must warn against printing the credential"
