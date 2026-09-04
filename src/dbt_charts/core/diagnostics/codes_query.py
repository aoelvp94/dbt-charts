"""WARN-* warning codes for the query (SQL-lint) domain.

These four codes are emitted by core/inspect/query_validator.py and reach
render output via core/diagnostics/from_query_diagnostic.py adapter.
They are declared here (not in the detector modules) so the registry is
complete on import of core.diagnostics, without importing back out to
core/inspect/.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics.registry import REGISTRY, WarningCode

WARN_FANOUT_RISK = REGISTRY.register(
    WarningCode(
        code="WARN-FANOUT-RISK",
        domain="query",
        title="Join may multiply rows beyond chart aggregation",
        message_template=("Query {query_name!r}: {message}"),
        fix_template=(
            "Add a GROUP BY or aggregation in the query to collapse the "
            "duplicate rows before they reach the chart."
        ),
        doc=(
            "Fires when query validation detects a join that may multiply rows "
            "beyond what the chart's aggregation can recover. When a cached "
            "relationship context (super-schema profiles) is available, severity "
            "is calibrated against known multiplicities. Emitted by "
            "`validate_compiled_queries` for every named query."
        ),
        docs_topic="queries",
    )
)

WARN_MISSING_JOIN_PREDICATE = REGISTRY.register(
    WarningCode(
        code="WARN-MISSING-JOIN-PREDICATE",
        domain="query",
        title="Join is missing a predicate and may produce a cross join",
        message_template=("Query {query_name!r}: {message}"),
        fix_template=("Add an ON clause to the join to specify how the tables relate."),
        doc=(
            "Fires when query validation detects an implicit cross join or an "
            "explicit CROSS JOIN without a predicate. These almost always indicate "
            "a missing ON clause and produce wildly fanned-out result sets. "
            "Emitted by `validate_compiled_queries` via the query validator."
        ),
        docs_topic="queries",
    )
)

WARN_PARSE_ERROR = REGISTRY.register(
    WarningCode(
        code="WARN-PARSE-ERROR",
        domain="query",
        title="SQL query could not be parsed for semantic validation",
        message_template=("Query {query_name!r}: {message}"),
        fix_template=(
            "Check the SQL syntax. The query may still execute, but "
            "semantic validation (fanout detection, reaggregation) cannot run "
            "on unparseable SQL."
        ),
        doc=(
            "Fires when a SQL query cannot be parsed as a structured AST. The "
            "query may still execute against the warehouse; this warning "
            "surfaces that semantic validation (fanout, reaggregation) cannot "
            "run on unparseable SQL. Emitted by `compile()` for authored "
            "queries whose dialect resolves and whose failure carries a "
            "specific position."
        ),
        docs_topic="queries",
    )
)

WARN_REAGGREGATION = REGISTRY.register(
    WarningCode(
        code="WARN-REAGGREGATION",
        domain="query",
        title="Aggregation applied on top of an already-aggregated input",
        message_template=("Query {query_name!r}: {message}"),
        fix_template=(
            "Refactor the query to aggregate only once at the correct level, "
            "or verify the double-aggregation is intentional."
        ),
        doc=(
            "Fires when query validation detects aggregation applied on top of an "
            "already-aggregated input (e.g. SUM(SUM(...)) patterns or aggregation "
            "over a query result that itself aggregates). The result is usually not "
            "what the author intended. Emitted by `validate_compiled_queries` via "
            "the query validator.\n\n"
            "Looker's symmetric aggregate is exempt. Migrated Looker queries read a "
            "measure across a fan-out join by packing it with a hash of the dedup "
            "key, `SUM(DISTINCT ...)`-ing so duplicate keys collapse, then "
            "subtracting a second `SUM(DISTINCT hash-only)`: an identity over a "
            "per-key value, not a second aggregation. Both halves of that "
            "subtraction must be present for the exemption to apply, so a plain "
            "`SUM(DISTINCT already_summed_column)` still warns."
        ),
        summary=(
            "Fires when query validation detects aggregation applied on top "
            "of an already-aggregated input."
        ),
        docs_topic="queries",
    )
)
