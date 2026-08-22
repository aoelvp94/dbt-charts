"""Tests for data-aware pack scaffolding — TDD first.

Covers:
- ProposedDashboard.canonical_data_url is set when a single-table evidence target
  is present (source/schema/table all known)
- ProposedDashboard.canonical_data_url is None when evidence is empty
- ProposedDashboard.canonical_data_url is None when evidence spans multiple tables
  from different schemas (no single canonical target)
- plan_pack emits canonical_data_url on dashboards with single evidence targets
- plan_pack planned_actions includes data binding statements for dashboards with
  canonical URLs
- apply_proposal emits aliases: on generated board YAML when canonical_data_url set
- apply_proposal does NOT emit aliases: when canonical_data_url is None
- apply_proposal index.yml links to /data/... paths for dashboards with data URLs
- Round-trip: canonical_data_url survives dump_proposal → load_proposal
- Collision: two dashboards in same proposal cannot share the same canonical_data_url
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from dbt_charts.agent_api.pack import apply_proposal
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.pack.models import (
    PackProposal,
    ProposedDashboard,
    ProposedFolder,
    SchemaTarget,
)
from dbt_charts.core.pack.planner import SourceEntry, plan_pack
from dbt_charts.core.pack.proposal_store import dump_proposal, load_proposal
from dbt_charts.core.registered_views.data_urls import data_table_url
from dbt_charts.core.serve.alias_index import AliasIndex

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_target(source: str, schema: str, table: str) -> SchemaTarget:
    return SchemaTarget(data_source=source, schema_name=schema, table=table)


def _make_dashboard(
    name: str = "ticket-overview",
    entity: str = "ticket",
    evidence: list[SchemaTarget] | None = None,
) -> ProposedDashboard:
    return ProposedDashboard(
        name=name,
        title="Ticket Overview",
        purpose="Track ticket volume.",
        primary_entity=entity,
        evidence=evidence or [],
    )


# ---------------------------------------------------------------------------
# ProposedDashboard.canonical_data_url — model field
# ---------------------------------------------------------------------------


def test_dashboard_canonical_data_url_defaults_to_none() -> None:
    """canonical_data_url is None when not set (empty evidence case)."""
    dashboard = _make_dashboard(evidence=[])
    assert dashboard.canonical_data_url is None


def test_dashboard_canonical_data_url_round_trip(tmp_path: Path) -> None:
    """canonical_data_url survives dump_proposal → load_proposal unchanged."""
    # Build a proposal with a canonical URL (plan_pack assigns these automatically;
    # here we set it directly to keep the test self-contained).
    folders = [
        ProposedFolder(
            path="charts/zendesk",
            landing="index.yml",
            dashboards=[
                ProposedDashboard(
                    name="ticket-overview",
                    title="Ticket Overview",
                    purpose="Track tickets.",
                    primary_entity="ticket",
                    evidence=[_make_target("fivetran_zendesk", "zendesk", "tickets")],
                    canonical_data_url="/data/fivetran_zendesk/zendesk/tickets/",
                )
            ],
        )
    ]
    proposal_with_url = PackProposal(
        organization_mode="connector-first",
        detected_sources=["fivetran_zendesk"],
        folders=folders,
        partials=[],
        uncertainty_notes=[],
        planned_actions=[],
    )
    path = tmp_path / "proposal.yml"
    dump_proposal(proposal_with_url, path)
    reloaded = load_proposal(path)
    assert (
        reloaded.folders[0].dashboards[0].canonical_data_url
        == "/data/fivetran_zendesk/zendesk/tickets/"
    )


# ---------------------------------------------------------------------------
# plan_pack — data URL assignment
# ---------------------------------------------------------------------------


def test_plan_pack_sets_canonical_data_url_for_primary_table() -> None:
    """plan_pack assigns canonical_data_url to dashboards with primary entity tables."""
    proposal = plan_pack(
        sources={
            "fivetran_zendesk": SourceEntry(
                schema="zendesk",
                tables=["tickets", "users"],
                source_name="fivetran_zendesk",
            )
        }
    )
    all_dashboards = [d for f in proposal.folders for d in f.dashboards]
    ticket_dash = next(
        (d for d in all_dashboards if d.primary_entity == "ticket"), None
    )
    assert ticket_dash is not None, "Expected ticket dashboard"
    assert ticket_dash.canonical_data_url is not None, (
        "ticket dashboard must have canonical_data_url"
    )
    assert ticket_dash.canonical_data_url == "/data/fivetran_zendesk/zendesk/tickets/"


def test_plan_pack_canonical_url_format() -> None:
    """canonical_data_url follows /data/<source>/<schema>/<table>/ format."""
    proposal = plan_pack(
        sources={
            "mydb": SourceEntry(
                schema="analytics",
                tables=["orders"],
                source_name="mydb",
            )
        }
    )
    all_dashboards = [d for f in proposal.folders for d in f.dashboards]
    assert all_dashboards, "Expected at least one dashboard"
    for dash in all_dashboards:
        if dash.canonical_data_url is not None:
            assert dash.canonical_data_url.startswith("/data/"), (
                f"canonical_data_url must start with /data/: {dash.canonical_data_url}"
            )
            assert dash.canonical_data_url.endswith("/"), (
                f"canonical_data_url must end with /: {dash.canonical_data_url}"
            )
            parts = dash.canonical_data_url.strip("/").split("/")
            assert len(parts) == 4 and parts[0] == "data", (
                f"canonical_data_url must be /data/<source>/<schema>/<table>/: {dash.canonical_data_url}"
            )


def test_plan_pack_planned_actions_include_data_binding() -> None:
    """planned_actions includes data binding statements for dashboards with data URLs."""
    proposal = plan_pack(
        sources={
            "fivetran_zendesk": SourceEntry(
                schema="zendesk",
                tables=["tickets", "users"],
                source_name="fivetran_zendesk",
            )
        }
    )
    all_dashboards = [d for f in proposal.folders for d in f.dashboards]
    dashboards_with_url = [d for d in all_dashboards if d.canonical_data_url]
    assert dashboards_with_url, "Expected at least one dashboard with canonical URL"

    # Each dashboard with a canonical URL must have a corresponding planned action
    for dash in dashboards_with_url:
        url = dash.canonical_data_url
        assert url is not None
        binding_actions = [a for a in proposal.planned_actions if url in a]
        assert binding_actions, (
            f"No planned action for data binding {url!r}; "
            f"got actions: {proposal.planned_actions}"
        )


# ---------------------------------------------------------------------------
# apply_proposal — aliases emitted on generated boards
# ---------------------------------------------------------------------------


def test_apply_emits_aliases_on_board_with_canonical_url(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """apply_proposal emits aliases: on generated board YAML when canonical_data_url is set."""
    (tmp_path / "dbt_charts.yml").write_text("")
    # ticket-overview has a canonical URL; user-overview does not
    folders = [
        ProposedFolder(
            path="charts/zendesk",
            landing="index.yml",
            dashboards=[
                ProposedDashboard(
                    name="ticket-overview",
                    title="Ticket Overview",
                    purpose="Track tickets.",
                    primary_entity="ticket",
                    evidence=[_make_target("fivetran_zendesk", "zendesk", "tickets")],
                    canonical_data_url="/data/fivetran_zendesk/zendesk/tickets/",
                ),
                ProposedDashboard(
                    name="user-overview",
                    title="User Overview",
                    purpose="Track users.",
                    primary_entity="user",
                    evidence=[_make_target("fivetran_zendesk", "zendesk", "users")],
                    canonical_data_url=None,
                ),
            ],
        )
    ]
    proposal_with_urls = PackProposal(
        organization_mode="connector-first",
        detected_sources=["fivetran_zendesk"],
        folders=folders,
        partials=[],
        uncertainty_notes=[],
        planned_actions=[],
    )
    apply_proposal(proposal_with_urls, local_project(tmp_path))

    # ticket-overview.yml MUST have aliases
    ticket_path = tmp_path / "charts" / "zendesk" / "ticket-overview.yml"
    ticket_data = yaml.safe_load(ticket_path.read_text())
    assert "aliases" in ticket_data, (
        f"ticket-overview.yml must have aliases:, got keys: {list(ticket_data.keys())}"
    )
    assert "/data/fivetran_zendesk/zendesk/tickets/" in ticket_data["aliases"], (
        f"Expected data URL in aliases, got: {ticket_data['aliases']}"
    )

    # user-overview.yml must NOT have aliases (no canonical_data_url)
    user_path = tmp_path / "charts" / "zendesk" / "user-overview.yml"
    user_data = yaml.safe_load(user_path.read_text())
    assert "aliases" not in user_data, (
        f"user-overview.yml must not have aliases when no canonical URL, got: {user_data}"
    )


def test_emitted_alias_resolves_through_alias_index(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """A planner-emitted alias must resolve via the real AliasIndex when looked
    up through data_table_url — the parity that guards against the URL grammar
    drifting between the pack producer and the data-path consumer.
    """
    (tmp_path / "dbt_charts.yml").write_text("")
    proposal = PackProposal(
        organization_mode="connector-first",
        detected_sources=["fivetran_zendesk"],
        folders=[
            ProposedFolder(
                path="charts/zendesk",
                landing="index.yml",
                dashboards=[
                    ProposedDashboard(
                        name="ticket-overview",
                        title="Ticket Overview",
                        purpose="Track tickets.",
                        primary_entity="ticket",
                        evidence=[
                            _make_target("fivetran_zendesk", "zendesk", "tickets")
                        ],
                        canonical_data_url=data_table_url(
                            "fivetran_zendesk", "zendesk", "tickets"
                        ),
                    ),
                ],
            )
        ],
        partials=[],
        uncertainty_notes=[],
        planned_actions=[],
    )
    apply_proposal(proposal, local_project(tmp_path))

    index = AliasIndex.build(local_project(tmp_path))
    target = index.lookup(data_table_url("fivetran_zendesk", "zendesk", "tickets"))
    # Not None proves the emitted alias and the looked-up URL share one grammar;
    # the value is the served URL of the generated authored board.
    assert target == "/zendesk/ticket-overview/", target


def test_apply_with_plan_pack_output_has_aliases(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """When plan_pack produces canonical URLs, apply_proposal emits aliases on boards."""
    (tmp_path / "dbt_charts.yml").write_text("")
    proposal = plan_pack(
        sources={
            "fivetran_zendesk": SourceEntry(
                schema="zendesk",
                tables=["tickets"],
                source_name="fivetran_zendesk",
            )
        }
    )
    apply_proposal(proposal, local_project(tmp_path))

    # Find the ticket-overview board
    ticket_path = tmp_path / "charts" / "zendesk" / "ticket-overview.yml"
    assert ticket_path.exists(), f"Expected {ticket_path}"
    data = yaml.safe_load(ticket_path.read_text())
    assert "aliases" in data, (
        f"ticket-overview.yml from plan_pack must have aliases:, got: {list(data.keys())}"
    )
    assert any(
        "/data/fivetran_zendesk/zendesk/tickets/" in alias for alias in data["aliases"]
    ), f"Expected data URL in aliases, got: {data.get('aliases')}"


# ---------------------------------------------------------------------------
# apply_proposal — index.yml links to /data/... paths
# ---------------------------------------------------------------------------


def test_apply_index_links_to_data_urls(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """index.yml includes /data/... links for dashboards with canonical URLs."""
    (tmp_path / "dbt_charts.yml").write_text("")
    folders = [
        ProposedFolder(
            path="charts/zendesk",
            landing="index.yml",
            dashboards=[
                ProposedDashboard(
                    name="ticket-overview",
                    title="Ticket Overview",
                    purpose="Track tickets.",
                    primary_entity="ticket",
                    evidence=[_make_target("fivetran_zendesk", "zendesk", "tickets")],
                    canonical_data_url="/data/fivetran_zendesk/zendesk/tickets/",
                )
            ],
        )
    ]
    proposal = PackProposal(
        organization_mode="connector-first",
        detected_sources=["fivetran_zendesk"],
        folders=folders,
        partials=[],
        uncertainty_notes=[],
        planned_actions=[],
    )
    apply_proposal(proposal, local_project(tmp_path))

    index_path = tmp_path / "charts" / "zendesk" / "index.yml"
    content = index_path.read_text()
    assert "/data/fivetran_zendesk/zendesk/tickets/" in content, (
        f"index.yml must contain data URL, content: {content!r}"
    )


# ---------------------------------------------------------------------------
# apply_proposal — alias collision within a proposal is an error
# ---------------------------------------------------------------------------


def test_apply_raises_on_duplicate_canonical_data_url(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """Two dashboards in the same proposal claiming the same canonical URL raises."""
    (tmp_path / "dbt_charts.yml").write_text("")
    shared_url = "/data/fivetran_zendesk/zendesk/tickets/"
    folders = [
        ProposedFolder(
            path="charts/zendesk",
            landing="index.yml",
            dashboards=[
                ProposedDashboard(
                    name="ticket-overview",
                    title="Ticket Overview",
                    purpose="Track tickets.",
                    primary_entity="ticket",
                    evidence=[_make_target("fivetran_zendesk", "zendesk", "tickets")],
                    canonical_data_url=shared_url,
                ),
                ProposedDashboard(
                    name="ticket-detail",
                    title="Ticket Detail",
                    purpose="Detailed ticket view.",
                    primary_entity="ticket",
                    evidence=[_make_target("fivetran_zendesk", "zendesk", "tickets")],
                    canonical_data_url=shared_url,
                ),
            ],
        )
    ]
    proposal = PackProposal(
        organization_mode="connector-first",
        detected_sources=["fivetran_zendesk"],
        folders=folders,
        partials=[],
        uncertainty_notes=[],
        planned_actions=[],
    )
    with pytest.raises(ValueError, match="duplicate"):
        apply_proposal(proposal, local_project(tmp_path))
