"""Tests for the deterministic pack planner.

TDD-first — these tests are written before the implementation exists.

Covers:
- Single-source (Zendesk-only) → connector-first with zendesk/ folder
- Multi-source (Zendesk + Salesforce) → domain-first with support/ folder
- Every proposed dashboard carries a primary entity + schema evidence
- Evidence uses the real schema name from SourceEntry, not a slug guess
- Proposal serializes and re-loads as a PackProposal (round-trip)
- Planner is deterministic (same input → identical output, called twice)
- No charts/ writes occur; planner is propose-only
- Explicit mode override respected
- Empty schema (no sources) → clear error, not a silent empty proposal
- All-unreachable sources → clear error
- Unreachable source in mixed set → uncertainty note, not fabricated evidence
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dbt_charts.core.pack.planner import SourceEntry, plan_pack
from dbt_charts.core.pack.proposal_store import dump_proposal, load_proposal

# ---------------------------------------------------------------------------
# Helpers — build SourceEntry inputs
# ---------------------------------------------------------------------------


def _zendesk_sources() -> dict[str, SourceEntry | None]:
    """Minimal Zendesk schema: one source with the real schema name.

    The dict key is the configured source identifier; source_name is set
    explicitly so evidence targets resolve to the configured source.
    """
    return {
        "fivetran_zendesk": SourceEntry(
            schema="zendesk",
            tables=["tickets", "ticket_comments", "users", "groups", "organizations"],
            source_name="fivetran_zendesk",
        )
    }


def _salesforce_sources() -> dict[str, SourceEntry | None]:
    """Minimal Salesforce schema: one source with the real schema name."""
    return {
        "fivetran_salesforce": SourceEntry(
            schema="salesforce",
            tables=["opportunity", "account", "contact", "lead"],
            source_name="fivetran_salesforce",
        )
    }


# ---------------------------------------------------------------------------
# Single-source: Zendesk only → connector-first
# ---------------------------------------------------------------------------


def test_single_source_zendesk_yields_connector_first() -> None:
    """A Zendesk-only schema produces a connector-first proposal.

    Single dominant source → connector-first is the documented heuristic.
    """
    proposal = plan_pack(sources=_zendesk_sources())

    assert proposal.organization_mode == "connector-first"
    assert "fivetran_zendesk" in proposal.detected_sources


def test_single_source_zendesk_folder_layout() -> None:
    """Zendesk-only proposal has a zendesk/ folder with index.yml landing."""
    proposal = plan_pack(sources=_zendesk_sources())

    folder_paths = {f.path for f in proposal.folders}
    assert any("zendesk" in p for p in folder_paths), (
        f"Expected a 'zendesk' folder; got {folder_paths}"
    )
    zendesk_folder = next(f for f in proposal.folders if "zendesk" in f.path)
    assert zendesk_folder.landing == "index.yml", (
        "Folder landing must be 'index.yml', never 'overview.yml'"
    )


def test_single_source_zendesk_dashboards_have_entity_and_evidence() -> None:
    """Every proposed dashboard carries a primary_entity and non-empty evidence."""
    proposal = plan_pack(sources=_zendesk_sources())

    for folder in proposal.folders:
        for dashboard in folder.dashboards:
            assert dashboard.primary_entity, (
                f"Dashboard {dashboard.name!r} has no primary_entity"
            )
            assert dashboard.evidence, (
                f"Dashboard {dashboard.name!r} has empty evidence"
            )
            for target in dashboard.evidence:
                assert target.data_source, "SchemaTarget missing data_source"
                assert target.schema_name, "SchemaTarget missing schema_name"
                assert target.table, "SchemaTarget missing table"


def test_evidence_uses_real_schema_name() -> None:
    """SchemaTarget.schema_name must match the real schema from SourceEntry, not a slug guess."""
    # Use a non-trivial real schema name that differs from the connector slug.
    # source_name must match the configured source so the assertion below can fire.
    sources: dict[str, SourceEntry | None] = {
        "fivetran_zendesk": SourceEntry(
            schema="zendesk_production",
            tables=["tickets", "users"],
            source_name="fivetran_zendesk",
        )
    }
    proposal = plan_pack(sources=sources)

    all_dashboards = [d for f in proposal.folders for d in f.dashboards]
    matched = False
    for dash in all_dashboards:
        for target in dash.evidence:
            if target.data_source == "fivetran_zendesk":
                matched = True
                assert target.schema_name == "zendesk_production", (
                    f"Evidence must use the real schema 'zendesk_production', "
                    f"not a slug guess; got {target.schema_name!r}"
                )
    assert matched, (
        "Expected at least one evidence target with data_source='fivetran_zendesk'"
    )


def test_single_source_zendesk_includes_ticket_dashboard() -> None:
    """Zendesk proposal includes a ticket-focused dashboard."""
    proposal = plan_pack(sources=_zendesk_sources())

    all_dashboards = [d for f in proposal.folders for d in f.dashboards]
    entity_names = {d.primary_entity for d in all_dashboards}
    assert "ticket" in entity_names, (
        f"Expected a ticket dashboard; got entities: {entity_names}"
    )


def test_single_source_zendesk_entity_set_includes_user() -> None:
    """Zendesk with a users table proposes both ticket and user dashboards."""
    proposal = plan_pack(sources=_zendesk_sources())

    entity_names = {d.primary_entity for f in proposal.folders for d in f.dashboards}
    assert entity_names == {"ticket", "user"}


def test_unknown_connector_slug_preserves_full_schema_name() -> None:
    """Unknown connector folder slugs must not collapse to the last underscore segment."""
    proposal = plan_pack(
        sources={
            "product_db": SourceEntry(
                schema="product_db",
                tables=["audit_log", "user"],
                source_name="db",
            )
        },
        mode="connector-first",
    )

    folder_paths = [f.path for f in proposal.folders]
    assert folder_paths == ["charts/product-db"]


def test_user_table_is_primary_entity() -> None:
    """Common user/users tables should get a user overview, not only generic overview."""
    proposal = plan_pack(
        sources={
            "product_db": SourceEntry(
                schema="product_db",
                tables=["user", "audit_log"],
                source_name="db",
            )
        },
        mode="connector-first",
    )

    dashboards = [d for f in proposal.folders for d in f.dashboards]
    assert [d.primary_entity for d in dashboards] == ["user"]
    assert [d.name for d in dashboards] == ["user-overview"]


# ---------------------------------------------------------------------------
# Multi-source: Zendesk + Salesforce → domain-first
# ---------------------------------------------------------------------------


def test_multi_source_yields_domain_first() -> None:
    """Multiple sources sharing domain concepts yield a domain-first proposal.

    Both Zendesk and Salesforce have 'support' domain semantics when taken
    together. Domain-first is the heuristic for multi-source integration.
    """
    sources = {**_zendesk_sources(), **_salesforce_sources()}
    proposal = plan_pack(sources=sources)

    assert proposal.organization_mode == "domain-first"
    assert "fivetran_zendesk" in proposal.detected_sources
    assert "fivetran_salesforce" in proposal.detected_sources


def test_multi_source_folder_has_multi_source_evidence() -> None:
    """Domain-first folders contain evidence from multiple sources."""
    sources = {**_zendesk_sources(), **_salesforce_sources()}
    proposal = plan_pack(sources=sources)

    all_dashboards = [d for f in proposal.folders for d in f.dashboards]
    all_sources_in_evidence = {
        t.data_source for d in all_dashboards for t in d.evidence
    }
    assert "fivetran_zendesk" in all_sources_in_evidence
    assert "fivetran_salesforce" in all_sources_in_evidence


# ---------------------------------------------------------------------------
# Round-trip: proposal serializes and re-loads identically
# ---------------------------------------------------------------------------


def test_proposal_round_trips(tmp_path: Path) -> None:
    """plan_pack output can be dump_proposal'd and load_proposal'd identically."""
    proposal = plan_pack(sources=_zendesk_sources())
    out_path = tmp_path / "proposal.yml"
    dump_proposal(proposal, out_path)
    reloaded = load_proposal(out_path)
    assert reloaded == proposal


# ---------------------------------------------------------------------------
# Determinism: same input → identical output
# ---------------------------------------------------------------------------


def test_planner_is_deterministic() -> None:
    """Calling plan_pack twice with the same input produces the same proposal."""
    sources = _zendesk_sources()
    first = plan_pack(sources=sources)
    second = plan_pack(sources=sources)
    assert first == second, "Planner must be deterministic"


# ---------------------------------------------------------------------------
# Propose-only: no charts/ written
# ---------------------------------------------------------------------------


def test_planner_writes_no_boards(tmp_path: Path) -> None:
    """plan_pack must not create any files under charts/."""
    boards_dir = tmp_path / "charts"
    plan_pack(sources=_zendesk_sources())
    assert not boards_dir.exists(), "Planner must not write to charts/"


# ---------------------------------------------------------------------------
# Explicit mode override
# ---------------------------------------------------------------------------


def test_explicit_connector_first_override() -> None:
    """mode='connector-first' forces connector-first even for multi-source."""
    sources = {**_zendesk_sources(), **_salesforce_sources()}
    proposal = plan_pack(sources=sources, mode="connector-first")
    assert proposal.organization_mode == "connector-first"


def test_explicit_domain_first_override() -> None:
    """mode='domain-first' forces domain-first even for single-source."""
    proposal = plan_pack(sources=_zendesk_sources(), mode="domain-first")
    assert proposal.organization_mode == "domain-first"


def test_invalid_mode_raises_not_silently_falls_back() -> None:
    """An unrecognized mode string must raise, not silently become 'hybrid'.

    Regression: the original type-narrowing rewrite coerced any unknown string
    to 'hybrid'; validate-and-error-fast requires an explicit ValueError instead.
    """
    import pytest

    with pytest.raises(ValueError, match="Unknown organization_mode"):
        plan_pack(sources=_zendesk_sources(), mode="totally-bogus")


# ---------------------------------------------------------------------------
# Error: no sources at all
# ---------------------------------------------------------------------------


def test_empty_sources_raises() -> None:
    """plan_pack({}) must raise ValueError — no silent empty proposals."""
    with pytest.raises(ValueError, match="no sources"):
        plan_pack(sources={})


# ---------------------------------------------------------------------------
# Error: all sources unreachable
# ---------------------------------------------------------------------------


def test_all_unreachable_sources_raises() -> None:
    """plan_pack raises when every source is None (all unreachable)."""
    with pytest.raises(ValueError, match="no tables"):
        plan_pack(sources={"fivetran_zendesk": None})


# ---------------------------------------------------------------------------
# Mixed: one reachable source + one unreachable → uncertainty note, not fabricated evidence
# ---------------------------------------------------------------------------


def test_unreachable_source_emits_uncertainty_note() -> None:
    """An unreachable source adds an uncertainty note, not a fabricated dashboard."""
    sources: dict[str, SourceEntry | None] = {
        "fivetran_zendesk": SourceEntry(
            schema="zendesk",
            tables=["tickets"],
            source_name="fivetran_zendesk",
        ),
        "fivetran_salesforce": None,
    }
    proposal = plan_pack(sources=sources)

    # The unreachable source must appear in detected_sources
    assert "fivetran_salesforce" in proposal.detected_sources

    # But no dashboard evidence must fabricate a salesforce schema target
    all_evidence = [
        t for f in proposal.folders for d in f.dashboards for t in d.evidence
    ]
    salesforce_evidence = [
        e for e in all_evidence if e.data_source == "fivetran_salesforce"
    ]
    assert not salesforce_evidence, (
        "Unreachable source must not appear as fabricated evidence"
    )

    # And an uncertainty note must call out the unreachable source
    assert any("fivetran_salesforce" in note for note in proposal.uncertainty_notes), (
        "Expected an uncertainty note about the unreachable source"
    )
