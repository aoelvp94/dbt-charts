"""Deterministic dashboard-pack proposal planner.

The planner is a pure function: it reads schema metadata (source → schema + tables)
and emits a :class:`PackProposal`. No LLM calls, no database queries, no
file writes inside this module. The caller (``agent_api/pack.py``) handles
resolver wiring and artifact persistence.

Organization-mode heuristic
---------------------------
- **connector-first**: a single dominant data source. One folder per source,
  named after the connector slug (e.g. ``charts/zendesk/``). The folder receives
  one dashboard per primary entity table.
- **domain-first**: multiple sources that each contribute to the same user
  workflow. Folder is named after the shared business domain inferred from
  the source names (e.g. ``charts/support/`` when both Zendesk and Salesforce
  are present). Dashboards in this folder draw evidence from all sources.
- **hybrid**: explicit override only. The auto-heuristic never emits hybrid —
  it picks connector-first (single source) or domain-first (multi-source).

Why not LLM for v1?
-------------------
Table names and source names are already highly semantic. A ticket table in a
Zendesk source is unambiguously about tickets. The deterministic approach is
testable, reproducible, and fast. An LLM ranking pass can annotate or re-rank
the deterministic skeleton in a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dbt_charts.core.pack.models import (
    PackProposal,
    ProposedDashboard,
    ProposedFolder,
    SchemaTarget,
)
from dbt_charts.core.project import CHARTS_SUBDIR
from dbt_charts.core.registered_views.data_urls import data_table_url


@dataclass(frozen=True)
class SourceEntry:
    """Schema metadata for one data source.

    Attributes:
        schema: The real schema name as reported by the resolver
            (e.g. ``"zendesk_data"`` — not a slug guess).
        tables: Table names within that schema.
        source_name: The configured source identifier from ``dbt_charts.yml``
            (e.g. ``"db"``, ``"fivetran_zendesk"``). Used as
            ``SchemaTarget.data_source`` in evidence so targets stay
            resolvable even when a single source expands into multiple
            per-schema entries. Required — callers must always pass the
            configured source name explicitly; no fallback to schema.
    """

    schema: str
    tables: list[str]
    source_name: str

    def __post_init__(self) -> None:
        if not self.schema:
            raise ValueError("SourceEntry.schema must not be empty")
        if not self.tables:
            raise ValueError("SourceEntry.tables must not be empty")
        if not self.source_name:
            raise ValueError("SourceEntry.source_name must not be empty")


# ---------------------------------------------------------------------------
# Domain inference — maps connector name fragments to a shared business domain.
# When ALL sources in a multi-source project share a domain, domain-first wins.
# Add new entries as new connectors are onboarded.
# ---------------------------------------------------------------------------

_CONNECTOR_DOMAINS: dict[str, str] = {
    "zendesk": "support",
    "salesforce": "support",
    "hubspot": "marketing",
    "marketo": "marketing",
    "stripe": "revenue",
    "quickbooks": "revenue",
    "shopify": "ecommerce",
    "woocommerce": "ecommerce",
    "jira": "engineering",
    "github": "engineering",
}

# Tables that represent the primary entity of a connector — the central "fact"
# around which dashboards are built. Matched by exact name (lower-case).
# Unlisted tables are treated as supporting entities grouped under the primary.
_PRIMARY_ENTITY_TABLES: frozenset[str] = frozenset(
    {
        # Support
        "tickets",
        "ticket",
        "cases",
        "case",
        # CRM
        "opportunity",
        "opportunities",
        "deal",
        "deals",
        "lead",
        "leads",
        "account",
        "accounts",
        "contact",
        "contacts",
        # Marketing
        "campaign",
        "campaigns",
        "email",
        "emails",
        # Cross-domain
        "user",
        "users",
        # Revenue
        "invoice",
        "invoices",
        "order",
        "orders",
        "subscription",
        "subscriptions",
        "charge",
        "charges",
        # Engineering
        "issue",
        "issues",
        "pull_request",
        "pull_requests",
        "commit",
        "commits",
    }
)


def _connector_slug(source_name: str) -> str:
    """Extract the connector short name from a source identifier.

    Used only for folder path naming (``charts/<slug>/``), not for schema evidence.
    The real schema name comes from the resolver via ``SourceEntry.schema``.

    Examples:
        "fivetran_zendesk" → "zendesk"
        "zendesk"          → "zendesk"
        "my_salesforce"    → "salesforce"
        "product_db"       → "product-db"
    """
    lower = source_name.lower()
    for known in _CONNECTOR_DOMAINS:
        if known in lower:
            return known
    return lower.replace("_", "-")


def _infer_domain(sources: dict[str, SourceEntry]) -> str | None:
    """Return the shared business domain if all sources agree, else None."""
    domains = {_CONNECTOR_DOMAINS.get(_connector_slug(s)) for s in sources}
    domains.discard(None)
    if len(domains) == 1:
        return next(iter(domains))  # set[str | None] with None discarded → str
    return None


def _pick_mode(
    sources: dict[str, SourceEntry], mode: str | None
) -> Literal["connector-first", "domain-first", "hybrid"]:
    """Choose organization_mode from explicit override or heuristic.

    Single dominant source → connector-first.
    Multiple sources that share a domain concept → domain-first.
    Otherwise → connector-first (safest fallback — concrete and unambiguous).
    """
    if mode is not None:
        if mode == "connector-first":
            return "connector-first"
        if mode == "domain-first":
            return "domain-first"
        if mode == "hybrid":
            return "hybrid"
        raise ValueError(
            f"Unknown organization_mode {mode!r}; "
            "expected 'connector-first', 'domain-first', or 'hybrid'."
        )
    if len(sources) == 1:
        return "connector-first"
    if _infer_domain(sources) is not None:
        return "domain-first"
    return "connector-first"


def _primary_entities(tables: list[str]) -> list[str]:
    """Return table names that represent primary entities, preserving order."""
    return [t for t in tables if t.lower() in _PRIMARY_ENTITY_TABLES]


def _entity_slug(table: str) -> str:
    """Normalize a table name to a dashboard entity label (singular, lowercase).

    Only called with members of ``_PRIMARY_ENTITY_TABLES``, so the naive
    de-pluralization (drop trailing 's') is safe for that curated set.
    """
    lower = table.lower()
    # De-pluralize only when the table ends with a single 's'.
    # Using [:-1] rather than rstrip('s') so "ss"-ending words are safe.
    if lower.endswith("s") and not lower.endswith("ss"):
        lower = lower[:-1]
    if lower in ("opportunitie",):
        return "opportunity"
    return lower


def _build_dashboard(
    *,
    entity_table: str,
    source_name: str,
    real_schema: str,
    supporting_tables: list[str],
) -> ProposedDashboard:
    """Build one ProposedDashboard for a primary entity.

    ``real_schema`` is the schema name as reported by the resolver, not a
    slug guess, so evidence targets can be matched against live metadata.
    The dashboard's canonical entity URL is set from the primary table's
    source/schema/table triple so the generated board can claim that URL
    via its ``aliases:`` field.
    """
    entity = _entity_slug(entity_table)
    primary_target = SchemaTarget(
        data_source=source_name,
        schema=real_schema,
        table=entity_table,
    )
    evidence: list[SchemaTarget] = [primary_target]
    # Attach up to two supporting tables as additional evidence
    for tbl in supporting_tables[:2]:
        evidence.append(
            SchemaTarget(
                data_source=source_name,
                schema=real_schema,
                table=tbl,
            )
        )
    return ProposedDashboard(
        name=f"{entity}-overview",
        title=f"{entity.replace('-', ' ').title()} Overview",
        purpose=f"Track {entity} volume, trends, and key metrics.",
        primary_entity=entity,
        evidence=evidence,
        canonical_data_url=data_table_url(source_name, real_schema, entity_table),
    )


def _connector_first_folders(sources: dict[str, SourceEntry]) -> list[ProposedFolder]:
    """Build one folder per source using the real schema from the resolver.

    The dict key drives the folder slug (e.g. ``"zendesk"`` → ``charts/zendesk/``).
    Evidence targets use ``entry.source_name`` — the configured source identifier —
    so the grounding is resolvable even when the dict key is a schema name.
    """
    folders: list[ProposedFolder] = []
    for slug_key in sorted(sources):
        entry = sources[slug_key]
        slug = _connector_slug(slug_key)

        primary = _primary_entities(entry.tables)
        supporting = [t for t in entry.tables if t not in set(primary)]

        if not primary:
            # No known entity tables — propose one generic dashboard grounded
            # in the first real table that came back from the schema resolver.
            first_table = entry.tables[0]
            dashboards = [
                ProposedDashboard(
                    name="overview",
                    title="Overview",
                    purpose=f"Overview of the {slug} data source.",
                    primary_entity=slug,
                    evidence=[
                        SchemaTarget(
                            data_source=entry.source_name,
                            schema=entry.schema,
                            table=first_table,
                        )
                    ],
                    canonical_data_url=data_table_url(
                        entry.source_name, entry.schema, first_table
                    ),
                )
            ]
        else:
            dashboards = [
                _build_dashboard(
                    entity_table=pt,
                    source_name=entry.source_name,
                    real_schema=entry.schema,
                    supporting_tables=supporting,
                )
                for pt in primary
            ]

        folders.append(
            ProposedFolder(
                path=f"{CHARTS_SUBDIR}/{slug}",
                landing="index.yml",
                dashboards=dashboards,
            )
        )
    return folders


def _domain_first_folders(sources: dict[str, SourceEntry]) -> list[ProposedFolder]:
    """Build one folder per shared domain, combining evidence from all sources.

    Evidence targets use ``entry.source_name`` — the configured source identifier —
    so grounding is resolvable even when a single physical source expanded into
    multiple per-schema dict entries.
    """
    domain = _infer_domain(sources) or "combined"

    seen_entities: set[str] = set()
    dashboards: list[ProposedDashboard] = []

    for slug_key in sorted(sources):
        entry = sources[slug_key]
        primary = _primary_entities(entry.tables)
        supporting = [t for t in entry.tables if t not in set(primary)]

        for pt in primary:
            entity = _entity_slug(pt)
            if entity in seen_entities:
                continue
            seen_entities.add(entity)
            dashboards.append(
                _build_dashboard(
                    entity_table=pt,
                    source_name=entry.source_name,
                    real_schema=entry.schema,
                    supporting_tables=supporting,
                )
            )

    # If no known entities across all sources, add a generic overview using the
    # first real table from the first source.
    if not dashboards:
        first_key = sorted(sources)[0]
        first_entry = sources[first_key]
        first_table = first_entry.tables[0]
        dashboards.append(
            ProposedDashboard(
                name="overview",
                title="Overview",
                purpose=f"Overview of {domain}.",
                primary_entity=domain,
                evidence=[
                    SchemaTarget(
                        data_source=first_entry.source_name,
                        schema=first_entry.schema,
                        table=first_table,
                    )
                ],
                canonical_data_url=data_table_url(
                    first_entry.source_name, first_entry.schema, first_table
                ),
            )
        )

    # Add cross-source evidence so domain-first dashboards reflect all sources.
    dashboards_with_full_evidence = _enrich_with_cross_source_evidence(
        dashboards, sources
    )

    return [
        ProposedFolder(
            path=f"{CHARTS_SUBDIR}/{domain}",
            landing="index.yml",
            dashboards=dashboards_with_full_evidence,
        )
    ]


def _enrich_with_cross_source_evidence(
    dashboards: list[ProposedDashboard],
    sources: dict[str, SourceEntry],
) -> list[ProposedDashboard]:
    """Attach one SchemaTarget from each additional source to every dashboard.

    Uses ``entry.source_name`` (the configured source identifier) for
    ``data_source`` so evidence targets remain resolvable when one physical
    source expanded into multiple per-schema dict entries.
    """
    enriched: list[ProposedDashboard] = []
    for dash in dashboards:
        existing_sources = {t.data_source for t in dash.evidence}
        extra_evidence: list[SchemaTarget] = list(dash.evidence)
        for slug_key in sorted(sources):
            entry = sources[slug_key]
            if entry.source_name in existing_sources:
                continue
            existing_sources.add(entry.source_name)
            extra_evidence.append(
                SchemaTarget(
                    data_source=entry.source_name,
                    schema=entry.schema,
                    table=entry.tables[0],
                )
            )
        enriched.append(
            ProposedDashboard(
                name=dash.name,
                title=dash.title,
                purpose=dash.purpose,
                primary_entity=dash.primary_entity,
                evidence=extra_evidence,
                canonical_data_url=dash.canonical_data_url,
            )
        )
    return enriched


def plan_pack(
    *,
    sources: dict[str, SourceEntry | None],
    mode: str | None = None,
) -> PackProposal:
    """Emit a deterministic PackProposal from schema metadata.

    Args:
        sources: Mapping of source/connector name → :class:`SourceEntry` (real
            schema name + table names as reported by the resolver), or ``None``
            when the source was unreachable. ``None`` entries are excluded from
            folder generation and surfaced as ``uncertainty_notes``.
        mode: Organization mode override (``"connector-first"``,
            ``"domain-first"``, or ``"hybrid"``). When ``None``, the planner
            uses its heuristic (single source → connector-first; multiple
            sources sharing a domain → domain-first).

    Returns:
        A fully-validated :class:`~dbt_charts.core.pack.models.PackProposal`.

    Raises:
        ValueError: When *sources* is empty, or when every source is ``None``
            (all unreachable) — never silently return an empty proposal.
    """
    if not sources:
        raise ValueError(
            "plan_pack requires at least one source; no sources were provided"
        )

    # Partition into reachable (have a SourceEntry) and unreachable (None).
    # Unreachable sources are surfaced as uncertainty notes, not silently dropped.
    unreachable = [s for s, entry in sources.items() if entry is None]
    reachable: dict[str, SourceEntry] = {
        s: entry for s, entry in sources.items() if entry is not None
    }

    if not reachable:
        raise ValueError(
            "plan_pack found no tables in any configured source; "
            "run 'dct inspect' to verify the sources are reachable"
        )

    organization_mode = _pick_mode(reachable, mode)

    if organization_mode == "connector-first":
        folders = _connector_first_folders(reachable)
    else:
        # domain-first and hybrid both use domain-first folder logic in v1.
        # hybrid is an explicit override — wire it the same as domain-first
        # until a dedicated hybrid strategy is implemented.
        folders = _domain_first_folders(reachable)

    detected_sources = sorted(sources.keys())

    planned_actions: list[str] = []
    for folder in folders:
        planned_actions.append(f"Create {folder.path}/")
        planned_actions.append(f"Write {folder.path}/{folder.landing}")
        for dash in folder.dashboards:
            planned_actions.append(f"Write {folder.path}/{dash.name}.yml")
            if dash.canonical_data_url:
                planned_actions.append(
                    f"Bind {folder.path}/{dash.name}.yml → "
                    f"{dash.canonical_data_url} (aliases: entry on board)"
                )

    uncertainty_notes: list[str] = [
        "Verify that proposed entity tables match your primary KPIs.",
        "Review folder structure before running the apply step.",
    ]
    for s in unreachable:
        uncertainty_notes.append(
            f"Source '{s}' returned no tables — schema coverage may be incomplete."
        )

    return PackProposal(
        organization_mode=organization_mode,
        detected_sources=detected_sources,
        folders=folders,
        partials=["_date_filter.yml"],
        uncertainty_notes=uncertainty_notes,
        planned_actions=planned_actions,
    )
