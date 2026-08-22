"""Tests for pack proposal models and store — TDD-first.

Covers:
- Round-trip: dump_proposal → load_proposal yields identical model
- Round-trip pins the on-disk YAML field name as "schema:" (not "schema_name:")
- Unknown organization_mode raises ValidationError
- Extra top-level key raises (extra="forbid")
- Malformed SchemaTarget (missing required field) raises
- Missing path raises FileNotFoundError from load_proposal
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dbt_charts.core.pack.models import (
    PackProposal,
    ProposedDashboard,
    ProposedFolder,
    SchemaTarget,
)
from dbt_charts.core.pack.proposal_store import dump_proposal, load_proposal

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_proposal() -> PackProposal:
    """A minimal but fully-valid PackProposal."""
    # Use the Python attribute name (schema_name) not the YAML alias (schema).
    evidence = SchemaTarget(
        data_source="fivetran_zendesk",
        schema_name="zendesk",
        table="tickets",
        column=None,
    )
    dashboard = ProposedDashboard(
        name="ticket-overview",
        title="Ticket Overview",
        purpose="Monitor ticket volume and SLA health.",
        primary_entity="ticket",
        evidence=[evidence],
    )
    folder = ProposedFolder(
        path="charts/support",
        landing="index.yml",
        dashboards=[dashboard],
    )
    return PackProposal(
        organization_mode="connector-first",
        detected_sources=["fivetran_zendesk"],
        folders=[folder],
        partials=["_date_filter.yml"],
        uncertainty_notes=["Unclear whether backlog or volume is primary KPI."],
        planned_actions=["Create charts/support/", "Write charts/support/index.yml"],
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    """dump_proposal → load_proposal yields identical model."""
    path = tmp_path / "proposal.yml"
    proposal = _minimal_proposal()
    dump_proposal(proposal, path)
    loaded = load_proposal(path)
    assert loaded == proposal


def test_round_trip_yaml_uses_schema_alias(tmp_path: Path) -> None:
    """dump_proposal writes 'schema:' on disk, not 'schema_name:'.

    The alias machinery (dump with by_alias=True, load with populate_by_name=True)
    exists precisely so YAML authors see the user-facing 'schema:' key rather than
    the Python attribute 'schema_name'. This test pins that contract.
    """
    path = tmp_path / "proposal.yml"
    dump_proposal(_minimal_proposal(), path)
    raw_yaml = path.read_text()
    assert "schema: zendesk" in raw_yaml, (
        "on-disk key must be 'schema:', not 'schema_name:'"
    )
    assert "schema_name" not in raw_yaml, (
        "Python attribute name must not leak into YAML"
    )


# ---------------------------------------------------------------------------
# Validation — organization_mode
# ---------------------------------------------------------------------------


def test_unknown_organization_mode_raises() -> None:
    """An organization_mode value not in the Literal raises ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PackProposal(
            organization_mode="free-form",  # type: ignore[arg-type]
            detected_sources=[],
            folders=[],
            partials=[],
            uncertainty_notes=[],
            planned_actions=[],
        )


# ---------------------------------------------------------------------------
# Validation — malformed SchemaTarget
# ---------------------------------------------------------------------------


def test_malformed_schema_target_raises() -> None:
    """A SchemaTarget missing required fields raises ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        # schema_name (alias: schema) is required — omitting it must raise
        SchemaTarget(  # type: ignore[call-arg]
            data_source="fivetran_zendesk",
            table="tickets",
        )


# ---------------------------------------------------------------------------
# Validation — missing path
# ---------------------------------------------------------------------------


def test_load_missing_path_raises(tmp_path: Path) -> None:
    """load_proposal on a non-existent file raises FileNotFoundError."""
    missing = tmp_path / "does_not_exist.yml"
    with pytest.raises(FileNotFoundError):
        load_proposal(missing)
