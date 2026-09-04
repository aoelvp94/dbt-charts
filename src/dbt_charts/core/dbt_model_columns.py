"""Catch a dbt column rename before `dbt run`, from the manifest's model SQL.

`--warehouse` validation reads the *warehouse*, so it is a lagging detector:
edit `models/orders.sql` to rename a column and every board referencing the
old name stays green until the model is rebuilt. This module derives each
model's output columns statically from the SQL recorded in
`target/manifest.json` (written by a bare `dbt parse` — no build, no
credentials) and checks board queries against that, so the rename fails
validation at edit time.

Both halves ride the same seam as the `dct impact` index
(:func:`~dbt_charts.core.column_refs.parse_sql_statements`): dbt-call
substitution with provenance, all-branches skeletonization, and honest
failure. Static inference is not total, and the contract mirrors
`warehouse_check`'s ``unchecked``: a model whose output columns cannot be
derived — a ``SELECT *``, a macro or templated suffix in projection position,
any projection without an authored name (an unaliased aggregate, cast,
subscript, or literal), jinja branches that disagree about the projection
list, a snapshot (dbt injects meta columns at build time), a seed (its
columns live in the CSV, not the manifest), SQL that does not parse — is
reported as *unresolved* via
``WARN-DBT-MODEL-COLUMNS-UNRESOLVED``, never silently skipped and never
guessed at. Errors are raised only against a model whose columns resolved
completely, and only for tables that reached the query through a ``ref()``
call — a bare table name that merely collides with a model's name is not
evidence the query reads that model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlglot.expressions as exp
from sqlglot.dialects.dialect import Dialect as SqlglotDialect

from dbt_charts.core.column_refs import (
    extract_base_column_refs,
    parse_sql_statements,
)
from dbt_charts.core.compile.models.query.normalized import is_sql_query
from dbt_charts.core.compile.sql_guard import (
    SKELETON_PLACEHOLDER_PREFIX,
    sqlglot_dialect,
)
from dbt_charts.core.dbt_manifest import LoadedManifest, load_manifest
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.diagnostics.codes_execute import (
    ERR_DBT_MODEL_COLUMN_MISSING,
    WARN_DBT_MODEL_COLUMNS_UNRESOLVED,
    WARN_DBT_QUERY_COLUMNS_INDETERMINATE,
)
from dbt_charts.core.diagnostics.diagnostic import Diagnostic
from dbt_charts.core.diagnostics.execution import ExecutionError
from dbt_charts.core.execute.dbt_jinja import has_dbt_jinja

if TYPE_CHECKING:
    from dbt_charts.core.compile.compiler import CompileResult
    from dbt_charts.core.project import Project

_PLACEHOLDER_PREFIX = SKELETON_PLACEHOLDER_PREFIX

# Leading jinja-only headers — `{{ config(materialized='table') }}`, jinja
# comments, `--` line comments — skeletonize to bare placeholder identifiers
# (or noise) ahead of the SELECT. They never contribute output columns, so
# they are stripped before the shared seam sees the SQL.
# One content atom of a `{{ }}` header: any non-brace, a lone brace (config
# args carry dict literals — meta={'owner': …}), or a one-level nested jinja
# call (post_hook="{{ grant_select(this) }}"). A `}}` never matches as content,
# so the outer match terminates at the header's own closing braces.
_HEADER_ATOM = r"[^{}]|\{(?!\{)|\}(?!\})"
_LEADING_JINJA_HEADER_RE = re.compile(
    r"^(?:\s+|--[^\n]*|\{#.*?#\}"
    rf"|\{{\{{(?:{_HEADER_ATOM}|\{{\{{(?:{_HEADER_ATOM})*\}}\}})*\}}\}})+",
    re.DOTALL,
)

# Per-process memo mirroring dbt_manifest's: derivation walks every node with
# a parse each, and every validated board would otherwise redo it.
_MEMO_MAXSIZE = 16
_memo: dict[tuple[str, str], dict[str, ModelColumns]] = {}


@dataclass(frozen=True)
class ModelColumns:
    """One model's statically derived output columns, or why there are none."""

    columns: frozenset[str] = frozenset()
    unresolved: str | None = None


def resolve_model_output_columns(loaded: LoadedManifest) -> dict[str, ModelColumns]:
    """Model name (lowercased) → output columns, derived from each node's SQL.

    Reads ``compiled_code`` when the manifest carries it and falls back to
    ``raw_code`` (all a bare ``dbt parse`` writes). Snapshots are always
    unresolved — dbt injects ``dbt_valid_from``-style meta columns at build
    time. Seeds are always unresolved — their columns live in the CSV, and a
    manifest ``columns`` entry holds only what someone *documented*, which a
    complete claim cannot be built on.
    """
    key = (loaded.relpath, loaded.version)
    cached = _memo.get(key)
    if cached is not None:
        return cached

    # adapter_type is written by the user's dbt project — unconstrained. An
    # unmapped name (vertica, glue) must degrade to the generic-parse path,
    # never reach sqlglot's dialect lookup, which raises a bare ValueError.
    adapter_type = loaded.raw.get(  # type-state: silent_fallback — absent adapter_type is a legal manifest state; a None dialect takes the shared seam's generic-parse path
        "metadata", {}
    ).get("adapter_type")
    dialect = sqlglot_dialect(adapter_type) if isinstance(adapter_type, str) else None
    if dialect not in SqlglotDialect.classes:
        dialect = None
    out: dict[str, ModelColumns] = {}
    for node in loaded.raw.get(
        "nodes", {}
    ).values():  # type-state: silent_fallback — raw-dict tolerance is dbt_manifest's documented contract; no nodes means nothing to derive
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed", "snapshot"):
            continue
        name = node.get("name")
        if not name:
            continue
        name_l = name.lower()
        if name_l in out:
            # A cross-package (or case-variant) name collision: either node's
            # columns would be a guess about which relation the ref meant.
            out[name_l] = ModelColumns(unresolved="two dbt nodes share this model name")
            continue
        if resource_type == "snapshot":
            out[name_l] = ModelColumns(
                unresolved="dbt injects snapshot meta columns at build time"
            )
            continue
        if resource_type == "seed":
            out[name_l] = ModelColumns(
                unresolved="seed columns come from its CSV, which the manifest "
                "does not carry"
            )
            continue
        sql = (
            node.get("compiled_code")
            or node.get("raw_code")
            or ""  # type-state: silent_fallback — bare `dbt parse` writes null compiled_code; an empty string resolves to the explicit no-SELECT unresolved state, not a pass
        )
        out[name_l] = _output_columns(sql, dialect=dialect)

    while len(_memo) >= _MEMO_MAXSIZE:
        _memo.pop(next(iter(_memo)))
    _memo[key] = out
    return out


def _output_columns(sql: str, dialect: str | None) -> ModelColumns:
    sql = _LEADING_JINJA_HEADER_RE.sub("", sql)
    parsed = parse_sql_statements(sql, dialect)
    if isinstance(parsed, str):
        return ModelColumns(unresolved=parsed)
    statements, _ = parsed

    projection_sets: list[frozenset[str]] = []
    for statement in statements:
        result = _statement_columns(statement)
        if isinstance(result, str):
            return ModelColumns(unresolved=result)
        projection_sets.append(result)

    distinct = set(projection_sets)
    if not distinct:
        return ModelColumns(unresolved="the model contains no SELECT statement")
    if len(distinct) > 1:
        # The all-branches skeleton splits a statement-level {% if %} into one
        # statement per arm; arms that disagree mean the projection list is
        # decided at render time.
        return ModelColumns(
            unresolved="jinja branches disagree about the model's projection list"
        )
    return ModelColumns(columns=distinct.pop())


def _statement_columns(statement: exp.Expression) -> frozenset[str] | str:
    """One statement's output column names, or why they cannot be known."""
    select = statement
    while isinstance(select, (exp.Union, exp.Intersect, exp.Except)):
        # Set operations take their column names from the first arm.
        select = select.this
    if isinstance(select, exp.Subquery):
        select = select.this
    if not isinstance(select, exp.Select):
        return "the model is not a plain SELECT statement"

    columns: set[str] = set()
    for projection in select.expressions:
        if isinstance(projection, exp.Star) or (
            isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
        ):
            return "a `*` projection hides the model's column list"
        # Only an authored name enters the claim: an alias, or a column
        # reference (optionally parenthesized). Everything else — count(*),
        # COLUMNS(), a subscript or JSON extract, a bare literal, an
        # unaliased cast (named after the inner column on Postgres, `f0_` on
        # BigQuery, the expression text on DuckDB/Snowflake) — has a name
        # only the engine decides; sqlglot's output_name/alias_or_name
        # render literal text for several of those, a fabricated name inside
        # a complete claim.
        if isinstance(projection, exp.Alias):
            name = projection.output_name
        else:
            node = projection
            while isinstance(node, exp.Paren):
                node = node.this
            if not isinstance(node, exp.Column) or isinstance(node.this, exp.Star):
                return "a projection carries no output name this static read can know"
            name = node.name
        if not name:
            return "a projection carries no output name this static read can know"
        if _PLACEHOLDER_PREFIX in name.lower():
            # A macro or templated fragment in projection position — the
            # engine decides an output name this static read cannot know.
            return (
                "a projection's output name is decided by a macro or "
                "templated expression"
            )
        columns.add(name.lower())
    if not columns:
        return "the model projects no columns"
    return frozenset(columns)


def check_model_columns(compile_result: CompileResult, project: Project) -> None:
    """Check board column references against statically derived model columns.

    Mutates ``compile_result.errors`` / ``.warnings``, like
    ``check_manifest_refs``. No-ops without a manifest — nothing to claim. A
    manifest that exists but cannot be read is a real fault at a real
    location and is reported here (``check_manifest_refs`` only loads the
    manifest when a query carries a ref()/source() call, so it cannot be
    relied on to have said it).

    Claims are scoped to ref() provenance: only a table that reached the
    query through ``{{ ref(...) }}`` is checked against the model registry —
    a bare name that happens to match a model may be a same-named relation on
    a different source entirely.
    """
    if compile_result.board is None:
        # A board that failed compile has no query registry to analyze; its
        # own compile errors are the report.
        return
    try:
        loaded = load_manifest(project)
    except ExecutionError as exc:
        diagnostic = exc.to_diagnostic()
        if all(e.code != diagnostic.code for e in compile_result.errors):
            compile_result.errors.append(diagnostic)
        return
    if loaded is None:
        return

    dbt_queries = {
        name
        for name, query in compile_result.query_registry.items()
        if is_sql_query(query)
        and (
            has_dbt_jinja(query.sql)
            or (query.setup_sql is not None and has_dbt_jinja(query.setup_sql))
        )
    }
    if not dbt_queries:
        # No query calls ref()/source() — nothing here makes a dbt claim.
        return

    column_refs = extract_base_column_refs(compile_result)
    # The per-node derivation walk is only owed when some determinate query
    # actually reached a table through ref().
    models = (
        resolve_model_output_columns(loaded)
        if any(refs.via_dbt for refs in column_refs.values())
        else {}
    )
    warned: set[tuple[str, str]] = set()

    for query_name, refs in column_refs.items():
        if refs.indeterminate is not None:
            if query_name in dbt_queries:
                # A dbt-backed query this check cannot vouch for — the gap
                # stays visible, never a silent green. Plain-SQL queries are
                # the SQL lint tiers' business.
                compile_result.warnings.append(
                    Diagnostic.from_code(
                        WARN_DBT_QUERY_COLUMNS_INDETERMINATE,
                        message=WARN_DBT_QUERY_COLUMNS_INDETERMINATE.message_template.format(
                            query_name=query_name, reason=refs.indeterminate
                        ),
                        fix=WARN_DBT_QUERY_COLUMNS_INDETERMINATE.fix_template,
                        query=query_name,
                    )
                )
            continue
        for table, column in sorted(refs.columns):
            table_l = table.lower()
            if table_l not in refs.via_dbt:
                continue
            model = models.get(table_l)
            if model is None:
                continue
            if model.unresolved is not None:
                if (query_name, table_l) not in warned:
                    warned.add((query_name, table_l))
                    compile_result.warnings.append(
                        Diagnostic.from_code(
                            WARN_DBT_MODEL_COLUMNS_UNRESOLVED,
                            message=WARN_DBT_MODEL_COLUMNS_UNRESOLVED.message_template.format(
                                query_name=query_name,
                                model=table,
                                reason=model.unresolved,
                            ),
                            fix=WARN_DBT_MODEL_COLUMNS_UNRESOLVED.fix_template,
                            query=query_name,
                        )
                    )
                continue
            if column.lower() not in model.columns:
                compile_result.errors.append(
                    DbtChartsError.from_code(
                        ERR_DBT_MODEL_COLUMN_MISSING,
                        query_name=query_name,
                        column_name=column,
                        model=table,
                        available=sorted(model.columns),
                    ).to_diagnostic()
                )
