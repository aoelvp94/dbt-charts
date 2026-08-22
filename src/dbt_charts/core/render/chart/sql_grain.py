"""SQL grain/lineage reasoning for auto-link: given a query's raw SQL, prove
whether its output is row-grain over a single base entity, and trace a base
column to its final output name.

This module owns the sqlglot AST reasoning; it has no dependency on links,
URLs, or the render context — that half lives in ``auto_link.py``, which
consumes ``resolve_cte_spine``, ``resolve_join_spine``, and
``build_col_output_alias_map`` as its grain/lineage layer.

Entry points:
  - ``resolve_cte_spine(tree)`` — resolve a single-CTE-wrap query to its base
    (schema, table), or ``_BAIL``. Pure AST walk, no adapter needed.
  - ``resolve_join_spine(tree, adapter_registry)`` — resolve a JOIN query to
    its spine (schema, table) via FK-edge proof, or ``_BAIL``.
  - ``build_col_output_alias_map(sql)`` — map base column names to their
    output names for the plain/single-CTE/JOIN shapes above, plus whether an
    unlisted column is still safe to assume identity for. See its docstring
    for the full contract: never assume an unlisted column shares its base
    name unless every relevant projection is a bare star.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlglot.expressions import Expression as _SqlglotExpression

    from dbt_charts.core.execute.adapters.adapter_registry import AdapterRegistry

# Sentinel used by private helpers to signal "bail — no location resolved".
# Callers check `if not result` to detect it.
_BAIL: tuple[()] = ()


def parse_sql(sql: str) -> _SqlglotExpression | None:
    """Strip Jinja tokens and parse ``sql`` into a sqlglot AST, or None on failure.

    Shared by every resolver in this module that needs to parse raw SQL.
    """
    import sqlglot
    import sqlglot.errors

    from dbt_charts.core.compile.sql_guard import as_expression

    stripped = re.sub(r"\{\{.*?\}\}", "1", sql, flags=re.DOTALL)
    stripped = re.sub(r"\{%.*?%\}", "", stripped, flags=re.DOTALL)
    try:
        parsed = sqlglot.parse_one(stripped)
    except sqlglot.errors.ParseError:
        return None
    return as_expression(parsed)


def resolve_cte_spine(tree: _SqlglotExpression) -> tuple[str, str] | tuple[()]:
    """Resolve a single-CTE row-grain query to its base (schema, table), or _BAIL.

    Succeeds only when:
    - Exactly one CTE is defined in the WITH clause, and the outer ``FROM``
      reads from *that CTE by name* — not some other table, and not a
      differently-named reference (a query whose outer SELECT ignores the
      CTE entirely must not resolve to the CTE's base table).
    - The CTE declares no explicit column-alias list (``WITH t(a, b) AS
      (...)``) — that syntax renames the body's projected columns
      *positionally*, which ``build_col_output_alias_map`` has no tracing
      for; without this bail it would derive output names straight from the
      body's own projection, silently wrong whenever the column list
      reorders or renames them (e.g. ``WITH t(ticket_number, id) AS (SELECT
      id, ticket_number FROM ...)`` swaps the two column names).
    - Nowhere in the whole query — outer or CTE body — is there a JOIN,
      GROUP BY, DISTINCT, aggregate function, or subquery. Any of those
      anywhere breaks the "one row in, one row out, over one base entity"
      guarantee, not just when they appear in the CTE body.
    - The CTE body reads from exactly one schema-qualified, non-catalog-
      qualified base table.

    Args:
        tree: Parsed sqlglot AST (a Select node with a With clause).

    Returns:
        ``(schema, table)`` on success, ``_BAIL`` on any violation.
    """
    from sqlglot import exp

    ctes = list(tree.find_all(exp.CTE))
    if len(ctes) != 1:
        return _BAIL
    cte = ctes[0]

    cte_alias_node = cte.args.get("alias")
    if isinstance(cte_alias_node, exp.TableAlias) and cte_alias_node.columns:
        return _BAIL

    # The outer SELECT must read from exactly this CTE (by its alias) — a
    # query whose FROM is some other table (or the CTE plus something else)
    # doesn't have "the CTE's base table" as its identity at all.
    from_clause = tree.args.get("from_")
    if not isinstance(from_clause, exp.From):
        return _BAIL
    from_table_expr = from_clause.this
    if not isinstance(from_table_expr, exp.Table):
        return _BAIL
    if from_table_expr.db or from_table_expr.catalog:
        return _BAIL  # a real schema-qualified table, not a CTE reference
    # Unquoted SQL identifiers are case-insensitive — `SELECT * FROM Resolved`
    # against `WITH resolved AS (...)` is the same reference, not a mismatch.
    if from_table_expr.name.casefold() != cte.alias.casefold():
        return _BAIL

    # Grain-breaking constructs anywhere in the query — outer or CTE body —
    # bail. `find_all` walks the whole tree (including the CTE body, a nested
    # Select), so these checks cover both without duplicating the outer/body
    # split. `tree.args.get("joins")` alone would miss joins nested inside the
    # CTE body's own Select node — use `find_all(exp.Join)` instead.
    if list(tree.find_all(exp.Join)):
        return _BAIL
    if list(tree.find_all(exp.Group)):
        return _BAIL
    if list(tree.find_all(exp.Distinct)):
        return _BAIL
    if list(tree.find_all(exp.AggFunc)):
        return _BAIL
    if list(tree.find_all(exp.Subquery)):
        return _BAIL

    cte_body = cte.this
    body_tables = list(cte_body.find_all(exp.Table))
    if len(body_tables) != 1:
        return _BAIL

    t = body_tables[0]
    if not t.name or not t.db or t.catalog:
        return _BAIL

    return t.db, t.name


def resolve_join_spine(
    tree: _SqlglotExpression,
    adapter_registry: AdapterRegistry,
) -> tuple[str, str] | tuple[()]:
    """Resolve a JOIN query to its spine (schema, table) via FK proof, or _BAIL.

    Succeeds only when the FROM clause is a single schema-qualified table
    (the spine), no CTE/GROUP BY/DISTINCT/aggregate function/scalar subquery
    appears anywhere in the query, and every JOIN's ``ON`` clause contains an
    equality conjunct matching a known FK edge (a `fetch_fk_edges` result —
    declared dbt ``relationships:`` or a super-schema recommended heuristic,
    confidence ≥ 0.80) from the spine table to the joined table, exactly on
    column names (``spine.from_column = joined.to_column``) — not merely a
    join against a table that happens to be *some* FK target of the spine.

    The FK edge proves referential existence (spine values exist in the
    target), not target uniqueness (no ``unique:`` signal is checked) — a
    fan-out here duplicates spine rows without changing which entity each
    duplicate drills to, so it's bounded, not a wrong-link risk.

    An ``OR`` anywhere in the ``ON`` clause, or a join with no ``ON`` clause
    at all, bails — those shapes can't be safely reduced to a provable
    equi-join on the declared FK columns.

    Args:
        tree: Parsed sqlglot AST (a Select node with joins).
        adapter_registry: Executor adapter registry for FK-edge lookup.

    Returns:
        ``(schema, table)`` for the spine, or ``_BAIL``.
    """
    from sqlglot import exp

    # A CTE anywhere means this isn't the plain-JOIN shape this resolver
    # handles — build_col_output_alias_map has no tracing for "CTE + JOIN"
    # (an untraced key would bail there anyway), so bail here too rather
    # than resolve a location no link could ever safely be keyed on.
    if list(tree.find_all(exp.CTE)):
        return _BAIL
    # Aggregation collapses grain even with FK-proven joins — checked over the
    # whole tree (not just the outer node's own args), mirroring the CTE path.
    if list(tree.find_all(exp.Group)):
        return _BAIL
    if list(tree.find_all(exp.Distinct)):
        return _BAIL
    if list(tree.find_all(exp.AggFunc)):
        return _BAIL
    if list(tree.find_all(exp.Subquery)):
        return _BAIL

    # sqlglot stores the FROM clause under "from_" (not "from") because
    # "from" is a Python keyword.
    from_clause = tree.args.get("from_")
    if not isinstance(from_clause, exp.From):
        return _BAIL

    from_table_expr = from_clause.this
    if not isinstance(from_table_expr, exp.Table):
        return _BAIL

    spine_table = from_table_expr.name
    spine_schema = from_table_expr.db
    if not spine_table or not spine_schema or from_table_expr.catalog:
        return _BAIL
    spine_alias = from_table_expr.alias_or_name

    joins = tree.args.get("joins")
    if not joins:
        return _BAIL

    from dbt_charts.core.execute.adapters.schema_adapter import (  # noqa: PLC0415
        fetch_fk_edges,
    )

    fk_edges = fetch_fk_edges(adapter_registry, spine_table)
    if not fk_edges:
        return _BAIL

    for join in joins:
        joined_expr = join.this
        if not isinstance(joined_expr, exp.Table):
            return _BAIL
        joined_table = joined_expr.name
        joined_alias = joined_expr.alias_or_name

        on_expr = join.args.get("on")
        if on_expr is None:
            return _BAIL
        conjuncts = _flatten_and_conjuncts(on_expr)
        if conjuncts is None:
            return _BAIL

        candidate_edges = [e for e in fk_edges if e["to_table"] == joined_table]
        if not any(
            _join_predicate_matches_edge(conjuncts, spine_alias, joined_alias, edge)
            for edge in candidate_edges
        ):
            return _BAIL

    return spine_schema, spine_table


def _flatten_and_conjuncts(
    node: _SqlglotExpression,
) -> list[_SqlglotExpression] | None:
    """Flatten an AND-chain into its leaf conjuncts, or None if an OR is present.

    A join ``ON`` clause with an ``OR`` anywhere can't be safely reduced to "this
    equi-join predicate always holds" — callers must bail rather than guess.
    ``None`` here means "this shape can't be reasoned about", distinct from
    the module's usual ``_BAIL`` sentinel (which means "no location resolved")
    — reusing ``_BAIL`` for two different meanings would conflate them.

    Unwraps a top-level ``exp.Paren`` first — ``ON (a = b)`` is a common
    formatting choice and shouldn't be treated any differently from
    ``ON a = b``.
    """
    from sqlglot import exp

    if isinstance(node, exp.Paren):
        return _flatten_and_conjuncts(node.this)
    if isinstance(node, exp.Or):
        return None
    if isinstance(node, exp.And):
        left = _flatten_and_conjuncts(node.this)
        right = _flatten_and_conjuncts(node.expression)
        if left is None or right is None:
            return None
        return left + right
    return [node]


def _join_predicate_matches_edge(
    conjuncts: list[_SqlglotExpression],
    spine_alias: str,
    joined_alias: str,
    edge: dict[str, str],
) -> bool:
    """True when some conjunct equates spine.from_column with joined.to_column.

    Column-qualifier comparison uses the table alias actually used in the SQL
    (``spine_alias``/``joined_alias``, from ``Table.alias_or_name``), matched
    against the declared FK edge's column names — not table names guessed from
    naming convention. Comparisons are case-insensitive (``.casefold()``) on
    both sides — unquoted SQL identifiers and manifest-declared column names
    from a different casing convention are still the same reference.
    """
    from sqlglot import exp

    for cond in conjuncts:
        if not isinstance(cond, exp.EQ):
            continue
        left, right = cond.this, cond.expression
        if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
            continue
        for x, y in ((left, right), (right, left)):
            if (
                x.table.casefold() == spine_alias.casefold()
                and x.name.casefold() == edge["from_column"].casefold()
                and y.table.casefold() == joined_alias.casefold()
                and y.name.casefold() == edge["to_column"].casefold()
            ):
                return True
    return False


def _is_star_projection(exprs: list[_SqlglotExpression]) -> bool:
    """True when a SELECT's top-level projection list is *only* a bare `*`
    or a single qualified `alias.*` — nothing else alongside it.

    Every current caller uses this in a single-table-in-scope context (a CTE
    body, a single-CTE's outer SELECT, or a plain query), where `alias.*` and
    a bare `*` denote the exact same column set — so a qualified star is
    just as safe to treat as full pass-through. (The one multi-table
    context, a JOIN's outer projection, already treats *any* star sighting
    here as "give up on identity" rather than "assume identity" — broadening
    this check doesn't change that, it just avoids `_project_col_map`
    recording a nonsense `{"*": "*"}` entry for `SELECT o.* FROM o JOIN c`.)

    Strict on the "nothing else alongside it" part: `SELECT *, ticket_number
    AS id FROM t` is not a pass-through — it has an explicit projection
    sitting alongside the star, and treating it as fully star-shaped would
    wrongly bless the un-listed base PK as identity-safe when a different
    column was aliased onto that same output name. A star-plus-extra
    projection falls through to `_project_col_map` instead, which excludes
    the bare `Star` entry and traces only the explicit aliases — correctly
    yielding no identity assumption for anything not explicitly proven.
    """
    from sqlglot import exp

    if len(exprs) != 1:
        return False
    e = exprs[0]
    return isinstance(e, exp.Star) or (
        isinstance(e, exp.Column) and isinstance(e.this, exp.Star)
    )


def _project_col_map(
    exprs: list[_SqlglotExpression], qualifier: str = ""
) -> dict[str, str]:
    """Build a ``source_col → output_col`` map from one SELECT's projections.

    Only ``col`` and ``col AS alias`` shapes are captured; anything else
    (expressions, function calls) is silently excluded — this function only
    ever needs to prove where a *bare column* ends up, never to resolve
    computed values.

    When ``qualifier`` is given (non-empty — a real table alias is never
    empty), only columns explicitly qualified by that table are included: a
    bare/unqualified column, or one qualified by a *different* table, proves
    nothing about whether ``qualifier``'s column of the same name is even
    present in the output, so it's excluded rather than guessed. This is the
    JOIN case, where more than one source table is in scope. Omitted
    (default), every bare column is captured regardless of qualifier — the
    single-CTE case, where exactly one source table is in scope so no
    qualifier filtering is needed.

    An output name claimed by more than one projection anywhere in ``exprs``
    (not just the qualifier-matched ones — a collision with an unrelated
    table's projection is just as real) is excluded from the map entirely:
    the executed query has exactly one column under that name, and nothing
    here can prove which projection's value actually survives into it
    (e.g. ``SELECT id, ticket_number AS id FROM t`` — tracing "id" to
    itself would be a guess, not a proof, once a second projection claims
    the same output name). Duplicate-output detection counts *every*
    aliased projection's output name — including expression-aliased ones
    like ``UPPER(subject) AS id`` — not just column-sourced ones, since an
    expression alias claims the output name just as validly as a bare
    column does (``SELECT id, UPPER(subject) AS id FROM t`` must exclude
    ``id`` too, even though only one of the two projections is traceable).
    The collision tally is case-insensitive (``.casefold()``) — most engines
    fold unquoted output column names to one canonical case, so ``SELECT id,
    ticket_number AS ID FROM t`` collides in the executed result exactly
    like a same-case duplicate would, even though the two output names are
    spelled differently in the SQL.
    """
    from collections import Counter

    from sqlglot import exp

    # First pass: every projection's output name counts toward collision
    # detection, whether or not it's a traceable bare-column source — an
    # expression-aliased duplicate is just as ambiguous as a column-aliased
    # one. Only column-sourced projections are collected as trace candidates.
    output_counts: Counter[str] = Counter()
    raw: list[tuple[str, str, bool]] = []
    for col_expr in exprs:
        if isinstance(col_expr, exp.Alias):
            output_counts[col_expr.alias.casefold()] += 1
            if isinstance(col_expr.this, exp.Column):
                col = col_expr.this
                raw.append(
                    (col.name, col_expr.alias, not qualifier or col.table == qualifier)
                )
        elif isinstance(col_expr, exp.Column):
            output_counts[col_expr.name.casefold()] += 1
            raw.append(
                (
                    col_expr.name,
                    col_expr.name,
                    not qualifier or col_expr.table == qualifier,
                )
            )

    col_map: dict[str, str] = {}
    for source, output, matches_qualifier in raw:
        if not matches_qualifier:
            continue
        if output_counts[output.casefold()] > 1:
            continue  # ambiguous — another projection claims the same output name
        col_map[source] = output
    return col_map


def _cte_col_output_alias_map(
    tree: _SqlglotExpression, cte: _SqlglotExpression
) -> tuple[dict[str, str], bool]:
    """``build_col_output_alias_map``'s logic for a single-CTE-wrap query.

    Only called after ``resolve_cte_spine`` has already resolved a location
    for this exact SQL, which requires zero ``exp.Subquery`` nodes anywhere
    in the tree — so ``cte.this`` is never itself wrapped in a ``Subquery``
    here (that only happens for a redundant double-paren CTE body, which
    ``resolve_cte_spine`` already bails on) — and no CTE column-alias list
    (``WITH t(a, b) AS (...)``), which ``resolve_cte_spine`` also bails on.
    The column-alias-list check is repeated here anyway (defense in depth):
    this function's whole contract is "never trace a renaming layer this
    module can't reason about," so it shouldn't rely solely on an upstream
    caller having already checked.
    """
    from sqlglot import exp

    cte_alias_node = cte.args.get("alias")
    if isinstance(cte_alias_node, exp.TableAlias) and cte_alias_node.columns:
        return {}, False

    cte_body = cte.this

    cte_is_star = _is_star_projection(cte_body.expressions)
    outer_is_star = _is_star_projection(tree.expressions)

    cte_map = {} if cte_is_star else _project_col_map(cte_body.expressions)
    outer_map = {} if outer_is_star else _project_col_map(tree.expressions)

    if cte_is_star and outer_is_star:
        return {}, True  # Full SELECT * → SELECT * pass-through — identity.

    # Compose: base → cte_output → outer_output.
    result: dict[str, str] = {}
    for base_col, cte_output in cte_map.items():
        if cte_output in outer_map:
            result[base_col] = outer_map[cte_output]
        elif outer_is_star:
            result[base_col] = cte_output
        # else: the outer SELECT is explicit and doesn't mention cte_output —
        # this base column is proven absent from the final output; omit it
        # rather than guessing it passes through.

    # The outer SELECT's own explicit projection — reachable only when the
    # CTE body was itself a full `SELECT *` (cte_is_star), because only then
    # does an outer_map key equal a *base table* column name. When the CTE
    # body has its own explicit projection, outer_map keys are the CTE's own
    # output names, not base columns — composing them here would mis-map a
    # base column that happens to share that name (e.g. CTE aliases id -> a,
    # and the base table separately has an unrelated column named a).
    #
    # Every entry here is proof the column is present in the output —
    # whether renamed (`outer_output != cte_col`) or passed through
    # unchanged (`outer_output == cte_col`); only recording renames would
    # prove nothing about `WITH c AS (SELECT * FROM t) SELECT id, subject
    # FROM c`'s `id`/`subject`, even though both provably appear in the
    # output under their own names.
    if cte_is_star:
        for cte_col, outer_output in outer_map.items():
            result[cte_col] = outer_output

    identity_safe_for_unlisted = cte_is_star and outer_is_star
    return result, identity_safe_for_unlisted


def _join_col_output_alias_map(tree: _SqlglotExpression) -> tuple[dict[str, str], bool]:
    """``build_col_output_alias_map``'s logic for an FK-proven JOIN query.

    Unlike the CTE case, a bare outer ``SELECT *`` across a join is never
    treated as safe identity: two joined tables can share a column name (both
    have ``id``), so which one survives in the output is statically
    ambiguous — not just untraced. Only columns explicitly qualified by the
    spine table's own alias are proof of anything; the caller never falls
    back to identity for a JOIN query.
    """
    from sqlglot import exp

    if _is_star_projection(tree.expressions):
        return {}, False

    from_clause = tree.args.get("from_")
    if not isinstance(from_clause, exp.From) or not isinstance(
        from_clause.this, exp.Table
    ):
        return {}, False
    spine_alias = from_clause.this.alias_or_name

    return _project_col_map(tree.expressions, qualifier=spine_alias), False


def build_col_output_alias_map(sql: str) -> tuple[dict[str, str], bool]:
    """Map base table column names to their output aliases.

    Handles the plain single-table shape, the single-CTE-wrap shape
    (``resolve_cte_spine``), and the FK-proven JOIN shape
    (``resolve_join_spine``) — every shape can trace its own SELECT list, so
    every shape is subject to the same rule below. Any other, unrecognized
    shape (multi-CTE, a CTE alongside a top-level JOIN, parse failure)
    returns ``({}, False)`` — untraced, never assume identity for a shape
    this function doesn't specifically understand.

    Returns ``(alias_map, identity_safe_for_unlisted)``:

    - ``alias_map`` maps ``base_column_name → output_column_name`` for every
      column *provably* present in the final output under a traced name.
    - ``identity_safe_for_unlisted`` is ``True`` only when the *entire*
      relevant projection is an unqualified ``SELECT *`` — for a plain query,
      its own SELECT list; for a single-CTE query, **both** the CTE body and
      the outer SELECT. Only then is every base column *provably* passed
      straight through, so a column absent from ``alias_map`` is still safe
      to assume identity for. When ``False``, a column absent from
      ``alias_map`` is **not** proven to appear in the output at all —
      callers must not fall back to the base name; the caller has proven
      nothing about that column and must drop it (no false drill), not guess.
      ``_is_star_projection`` is strict on purpose: a projection with a star
      *and* an explicit alias (``SELECT *, x AS id``) is not treated as
      identity-safe — the explicit alias could shadow the sought key.

    This distinction is load-bearing: a naive "missing key → assume identity"
    fallback silently resolves a sought PK to the wrong output column
    whenever a query's projection renames something *else* onto that name —
    e.g. ``WITH t AS (SELECT ticket_number AS id, subject FROM main.tickets)
    SELECT * FROM t`` never selects the base ``id`` at all, so a blind
    identity fallback for the sought PK ``id`` would silently resolve to the
    CTE's *unrelated* ``id`` output column (which actually holds
    ``ticket_number`` values) — a live drill to the wrong record. The
    identical failure mode exists for ``SELECT c.id, c.name, o.amount FROM
    orders o JOIN customers c ON o.cust_id = c.id`` — the spine is
    ``orders``, but the output's only ``id`` column is ``customers.id``.

    See ``test_sql_grain.py`` for the full worked-example matrix (plain,
    single-CTE, and JOIN shapes, star and explicit-projection variants).

    Args:
        sql: Raw SQL string (Jinja tokens are stripped before parsing).
    """
    from sqlglot import exp

    tree = parse_sql(sql)
    if tree is None:
        return {}, False

    ctes = list(tree.find_all(exp.CTE))
    has_joins = bool(list(tree.find_all(exp.Join)))

    if not ctes and not has_joins:
        # Plain single-table query — still has a renaming layer (its own
        # SELECT list), so trace it exactly like the CTE/JOIN cases rather
        # than blindly assuming identity for anything not a bare `SELECT *`.
        if _is_star_projection(tree.expressions):
            return {}, True
        return _project_col_map(tree.expressions), False
    if len(ctes) == 1 and not has_joins:
        return _cte_col_output_alias_map(tree, ctes[0])
    if has_joins and not ctes:
        return _join_col_output_alias_map(tree)
    # Any other shape (e.g. a CTE alongside a top-level JOIN, or multi-CTE) is
    # untraced — never assume identity for an unrecognized shape, even if
    # some other resolver happens to have proven a location for it.
    return {}, False
