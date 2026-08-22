"""Pack proposal Pydantic models.

These models define the contract for the transient proposal artifact
written under ``target/dbt_charts/proposals/`` and consumed by the
scaffold apply step. They are not part of the board-compile pipeline.

Schema evidence reuses the ``data_source / schema / table / column``
tuple shape established in ``dbt_charts.core.inspect`` so the planner
and any future retrieval can match without an LLM.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SchemaTarget(BaseModel):
    """A precise pointer into a connector's schema hierarchy.

    Reuses the ``data_source.schema.table[.column]`` identity tuple
    from ``dbt_charts.core.inspect`` so targets can be matched against
    live schema metadata without an LLM.

    Attributes:
        data_source: The Fivetran connector / data-source identifier
            (e.g. ``"fivetran_zendesk"``).
        schema_name: Schema name within the data source (e.g. ``"zendesk"``).
            YAML field is ``schema:``; Python attribute is ``schema_name`` to
            avoid shadowing ``BaseModel.schema`` (a Pydantic v2 legacy
            classmethod). See the same pattern on the ``SchemaQuery``
            model in ``dbt_charts.core.compile.models.query.normalized``.
        table: Table name within the schema (e.g. ``"tickets"``).
        column: Column name, or ``None`` when the evidence applies to the
            whole table.
    """

    # populate_by_name=True: YAML authors write `schema:` which maps to the
    # `schema_name` Python attribute via alias. Without populate_by_name,
    # model_validate({...}) would only accept the alias form.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data_source: str = Field(..., description="Connector / data-source identifier.")
    schema_name: str = Field(
        ...,
        alias="schema",
        description="Schema name within the data source.",
    )
    table: str = Field(..., description="Table name within the schema.")
    column: str | None = Field(
        default=None,
        description="Column name, or None when evidence applies to the whole table.",
    )


class ProposedDashboard(BaseModel):
    """One proposed dashboard within a pack folder.

    Attributes:
        name: File-system-safe slug used as the YAML filename stem
            (e.g. ``"ticket-overview"``).
        title: Human-readable title for the dashboard.
        purpose: One sentence describing what this dashboard answers.
        primary_entity: The central domain entity (e.g. ``"ticket"``,
            ``"opportunity"``).
        evidence: Schema targets that ground the dashboard in specific
            tables/columns the planner identified.
        canonical_data_url: The canonical data URL this board should
            claim via ``aliases:``, e.g.
            ``"/data/fivetran_zendesk/zendesk/tickets/"``. Set by the
            planner from the dashboard's primary entity table (including the
            generic-overview fallbacks). ``None`` when no primary table is known.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description="File-system-safe slug used as the YAML filename stem.",
    )
    title: str = Field(..., description="Human-readable dashboard title.")
    purpose: str = Field(
        ...,
        description="One sentence describing what this dashboard answers.",
    )
    primary_entity: str = Field(
        ...,
        description="Central domain entity (e.g. 'ticket', 'opportunity').",
    )
    evidence: list[SchemaTarget] = Field(
        ...,
        description="Schema targets grounding the dashboard in specific tables/columns.",
    )
    canonical_data_url: str | None = Field(
        default=None,
        description=(
            "Canonical data URL for this dashboard's aliases: entry, e.g. "
            "'/data/fivetran_zendesk/zendesk/tickets/'. Set by the planner "
            "from the dashboard's primary entity table. None when no primary "
            "table is known."
        ),
    )


class ProposedFolder(BaseModel):
    """One proposed subdirectory under ``charts/``.

    Attributes:
        path: Proposed path relative to the project root
            (e.g. ``"charts/support"``).
        landing: Filename for the folder's index dashboard
            (always ``"index.yml"``).
        dashboards: Proposed dashboards inside this folder.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        description="Proposed path relative to the project root (e.g. 'charts/support').",
    )
    landing: str = Field(
        ...,
        description="Filename for the folder landing dashboard (always 'index.yml').",
    )
    dashboards: list[ProposedDashboard] = Field(
        ...,
        description="Proposed dashboards inside this folder.",
    )


class PackProposal(BaseModel):
    """Top-level pack proposal artifact.

    Written by the planner to ``target/dbt_charts/proposals/<name>.yml``
    and consumed by the apply step. Proposals are never committed — only
    the resulting ``charts/`` YAML is source of truth.

    Attributes:
        organization_mode: How the planner grouped dashboards into folders.
            ``connector-first`` groups by data source, ``domain-first``
            groups by business domain, ``hybrid`` mixes both strategies.
        detected_sources: List of connector / data-source identifiers the
            planner found in the project.
        folders: Proposed folder tree under ``charts/``.
        partials: Shared partial YAML files the scaffold should create under
            ``charts/partials/``.
        uncertainty_notes: Human-readable notes about decisions the planner
            could not resolve — surfaced for the user to answer.
        planned_actions: Human-readable list of file-system actions the apply
            step would take when the proposal is accepted.
    """

    model_config = ConfigDict(extra="forbid")

    organization_mode: Literal["connector-first", "domain-first", "hybrid"] = Field(
        ...,
        description=(
            "How dashboards are grouped: 'connector-first' by data source, "
            "'domain-first' by business domain, or 'hybrid' for a mix."
        ),
    )
    detected_sources: list[str] = Field(
        ...,
        description="Connector / data-source identifiers found in the project.",
    )
    folders: list[ProposedFolder] = Field(
        ...,
        description="Proposed folder tree under charts/.",
    )
    partials: list[str] = Field(
        ...,
        description="Shared partial YAML filenames to create under charts/partials/.",
    )
    uncertainty_notes: list[str] = Field(
        ...,
        description="Unresolved questions surfaced for the user to answer.",
    )
    planned_actions: list[str] = Field(
        ...,
        description="File-system actions the apply step would take on acceptance.",
    )
