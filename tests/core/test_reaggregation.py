"""Tests for propagation-backed re-aggregation detection.

Covers: detecting aggregate-over-aggregate patterns through subqueries,
CTEs, and nested scopes where outer queries re-aggregate already-aggregated
columns.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dbt_charts.cli.main import app
from dbt_charts.core.inspect.query_validator import (
    QueryDiagnostic,
    validate_query,
)


def _has_reaggregation(diags: list[QueryDiagnostic]) -> bool:
    return any(d.code == "WARN-REAGGREGATION" for d in diags)


runner = CliRunner()


# ---------------------------------------------------------------------------
# Re-aggregation through subqueries
# ---------------------------------------------------------------------------


class TestSubqueryReaggregation:
    """Detect aggregation applied to columns that are already aggregate-derived
    in a subquery."""

    def test_sum_of_derived_sum(self) -> None:
        """SUM(total) where total = SUM(amount) in subquery."""
        sql = """
            SELECT region, SUM(total) AS grand_total
            FROM (
                SELECT region, SUM(amount) AS total
                FROM orders
                GROUP BY region
            ) sub
            GROUP BY region
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" in codes

    def test_avg_of_derived_avg(self) -> None:
        """AVG(avg_score) where avg_score = AVG(score) in subquery."""
        sql = """
            SELECT AVG(avg_score)
            FROM (
                SELECT department, AVG(score) AS avg_score
                FROM reviews
                GROUP BY department
            ) sub
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" in codes

    def test_count_of_derived_count(self) -> None:
        """SUM(cnt) where cnt = COUNT(*) in subquery."""
        sql = """
            SELECT SUM(cnt) AS total_count
            FROM (
                SELECT customer_id, COUNT(*) AS cnt
                FROM orders
                GROUP BY customer_id
            ) sub
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" in codes

    def test_avg_of_derived_sum(self) -> None:
        """AVG(total) where total = SUM(amount) — mixing aggregate types."""
        sql = """
            SELECT AVG(total)
            FROM (
                SELECT store_id, SUM(amount) AS total
                FROM sales
                GROUP BY store_id
            ) sub
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" in codes

    def test_severity_is_warning(self) -> None:
        sql = """
            SELECT SUM(total)
            FROM (
                SELECT SUM(amount) AS total
                FROM orders
                GROUP BY region
            ) sub
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) >= 1
        assert reagg[0].severity == "warning"

    def test_recommendation_present(self) -> None:
        sql = """
            SELECT SUM(total)
            FROM (
                SELECT SUM(amount) AS total FROM orders GROUP BY region
            ) sub
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) >= 1
        assert reagg[0].recommendation is not None


# ---------------------------------------------------------------------------
# CTE re-aggregation
# ---------------------------------------------------------------------------


class TestCTEReaggregation:
    """Detect re-aggregation through Common Table Expressions."""

    def test_sum_of_cte_aggregate(self) -> None:
        sql = """
            WITH totals AS (
                SELECT region, SUM(amount) AS total
                FROM orders
                GROUP BY region
            )
            SELECT SUM(total) FROM totals
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" in codes

    def test_avg_of_cte_count(self) -> None:
        sql = """
            WITH counts AS (
                SELECT department, COUNT(*) AS cnt
                FROM employees
                GROUP BY department
            )
            SELECT AVG(cnt) FROM counts
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" in codes


# ---------------------------------------------------------------------------
# Safe patterns — no false positives
# ---------------------------------------------------------------------------


class TestSafeAggregationPatterns:
    """Queries that should NOT trigger re-aggregation diagnostics."""

    def test_aggregate_over_raw_column(self) -> None:
        """SUM on a raw (non-aggregated) column from subquery is fine."""
        sql = """
            SELECT SUM(amount)
            FROM (
                SELECT id, amount FROM orders WHERE status = 'active'
            ) sub
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" not in codes

    def test_group_by_key_not_flagged(self) -> None:
        """Re-using a GROUP BY key in outer aggregate is fine."""
        sql = """
            SELECT COUNT(region)
            FROM (
                SELECT region, SUM(amount) AS total
                FROM orders
                GROUP BY region
            ) sub
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) == 0

    def test_simple_cte_no_aggregation(self) -> None:
        """CTE without aggregation — outer aggregate is fine."""
        sql = """
            WITH filtered AS (
                SELECT id, amount FROM orders WHERE amount > 100
            )
            SELECT SUM(amount) FROM filtered
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" not in codes

    def test_single_table_no_subquery(self) -> None:
        """Plain aggregation — no subquery, no re-aggregation possible."""
        sql = "SELECT SUM(amount) FROM orders GROUP BY region"
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" not in codes

    def test_non_aggregate_alias_reused(self) -> None:
        """Column aliased in subquery but not aggregate-derived."""
        sql = """
            SELECT MAX(val)
            FROM (
                SELECT amount * 2 AS val FROM orders
            ) sub
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" not in codes

    def test_window_function_not_flagged(self) -> None:
        """Window function output is per-row, not a collapsed aggregate.
        Aggregating a windowed column is valid."""
        sql = """
            SELECT SUM(row_total)
            FROM (
                SELECT SUM(amount) OVER (PARTITION BY region) AS row_total
                FROM orders
            ) sub
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" not in codes

    def test_unqualified_column_ambiguous_sources(self) -> None:
        """Unqualified column present in both aggregate and non-aggregate
        sources should NOT be flagged — ambiguous ownership."""
        sql = """
            WITH a AS (SELECT region, SUM(amount) AS total FROM orders GROUP BY region),
                 b AS (SELECT region, amount AS total FROM refunds)
            SELECT SUM(total) FROM a JOIN b ON a.region = b.region
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) == 0


class TestAliasReuseAcrossScopes:
    """Reusing a column name across independent CTEs must not cause a false
    re-aggregation finding purely because the names collide (FR-79).

    ``_inherit_aggregate_lineage`` propagates aggregate-derived status through
    a pass-through CTE's unqualified columns. When that CTE joins two other
    known sources, an unqualified column must only inherit aggregate status
    from a source that actually defines it — matching by name against *any*
    joined source (regardless of whether that source is the real origin) is
    exactly the trap: a join used only for filtering can carry an unrelated
    column that happens to share a name.
    """

    def test_unrelated_join_partner_does_not_leak_aggregate_status(self) -> None:
        """`net_usd` is genuinely aggregate-derived in `ltv` and genuinely a
        raw column in `iap`. `per_player` selects the `iap` value (unqualified)
        while joining `ltv` only to filter by player — it must not inherit
        `ltv`'s aggregate-ness just because the names collide. The outer
        query's own aggregate (SUM) is real, but it aggregates the `iap`
        value, not a pre-aggregated one."""
        sql = """
            WITH
              ltv AS (
                SELECT player_id, SUM(revenue) AS net_usd
                FROM transactions
                GROUP BY player_id
              ),
              iap AS (
                SELECT player_id, amount AS net_usd
                FROM iap_purchases
              ),
              per_player AS (
                SELECT iap.player_id, net_usd
                FROM iap
                JOIN ltv ON ltv.player_id = iap.player_id
              )
            SELECT COUNT(*) AS iap_payers, SUM(net_usd) AS total_iap
            FROM per_player
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert reagg == [], f"expected no reaggregation finding, got: {reagg}"

    def test_join_partners_agreeing_on_aggregate_status_still_flagged(self) -> None:
        """When the unqualified column IS aggregate-derived in every joined
        source that defines it, re-aggregation is real and must still fire —
        the fix must not blanket-silence unqualified passthrough columns."""
        sql = """
            WITH
              a AS (SELECT k, SUM(x) AS total FROM t1 GROUP BY k),
              b AS (SELECT k, SUM(y) AS total FROM t2 GROUP BY k),
              combined AS (
                SELECT a.k, total
                FROM a JOIN b ON a.k = b.k
              )
            SELECT SUM(total) FROM combined
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) == 1


class TestAggregateSourceReachedViaCteInternalJoin:
    """The FR-79 scope guard must exclude a join only when it belongs to a
    *different* scope than the select under analysis — never the select's
    own JOIN clauses, even when that select is itself a CTE body.

    ``_direct_join_sources`` runs both on the outer query (where a CTE's
    internal join must be excluded) and, via lineage propagation, on each
    CTE body itself (where that CTE's own joins must be *included*). A
    whole-ancestor-chain check can't tell these apart — a join inside a CTE
    body has that CTE as an ancestor either way. Only a scope-relative check
    (is this join directly in the select being analyzed?) gets both right.
    """

    def test_aggregate_joined_into_dimension_cte_then_reaggregated(self) -> None:
        """`agg_cte` is aggregate; `dim_cte` reaches it via its own internal
        JOIN (not its FROM) and passes `total_amount` through unqualified
        via alias. The outer query's AVG re-aggregates it — must fire."""
        sql = """
            WITH
              agg_cte AS (
                SELECT customer_id, SUM(amount) AS total_amount
                FROM orders
                GROUP BY customer_id
              ),
              dim_cte AS (
                SELECT c.customer_id, c.region, a.total_amount
                FROM customers c
                JOIN agg_cte a ON a.customer_id = c.customer_id
              )
            SELECT region, AVG(total_amount) AS avg_total
            FROM dim_cte
            GROUP BY region
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) == 1, f"expected reaggregation finding, got: {diags}"

    def test_aggregate_source_first_in_from_dimension_joined_in(self) -> None:
        """Same shape with join direction flipped — the aggregate source is
        in `dim_cte`'s FROM and the dimension table is the JOIN partner.
        Re-aggregation must still fire regardless of which side is which."""
        sql = """
            WITH
              agg_cte AS (
                SELECT customer_id, SUM(amount) AS total_amount
                FROM orders
                GROUP BY customer_id
              ),
              dim_cte AS (
                SELECT a.customer_id, c.region, a.total_amount
                FROM agg_cte a
                JOIN customers c ON a.customer_id = c.customer_id
              )
            SELECT region, AVG(total_amount) AS avg_total
            FROM dim_cte
            GROUP BY region
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) == 1, f"expected reaggregation finding, got: {diags}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestReaggregationEdgeCases:
    """Nested scopes, aliases, and mixed patterns."""

    def test_deeply_nested_reaggregation(self) -> None:
        """Two levels of nesting — inner aggregate re-aggregated at outer."""
        sql = """
            SELECT SUM(mid_total)
            FROM (
                SELECT SUM(total) AS mid_total
                FROM (
                    SELECT region, SUM(amount) AS total
                    FROM orders
                    GROUP BY region
                ) inner_q
            ) outer_q
        """
        diags = validate_query(sql)
        codes = [d.code for d in diags]
        assert "WARN-REAGGREGATION" in codes

    def test_mixed_safe_and_unsafe(self) -> None:
        """One aggregate on raw column, one on derived aggregate."""
        sql = """
            SELECT SUM(total), MAX(region)
            FROM (
                SELECT region, SUM(amount) AS total
                FROM orders
                GROUP BY region
            ) sub
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        # Should flag SUM(total) but not MAX(region)
        assert len(reagg) == 1
        assert "total" in reagg[0].message.lower()

    def test_same_column_name_different_sources_both_flagged(self) -> None:
        """Same column name from two sources — both should be flagged."""
        sql = """
            SELECT SUM(a.total), SUM(b.total)
            FROM (SELECT SUM(x) AS total FROM t1 GROUP BY k) a
            JOIN (SELECT SUM(y) AS total FROM t2 GROUP BY k) b ON a.k = b.k
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) == 2

    def test_having_reaggregation(self) -> None:
        """Re-aggregation in HAVING clause should also be detected."""
        sql = """
            SELECT region
            FROM (
                SELECT region, SUM(amount) AS total
                FROM orders
                GROUP BY region
            ) sub
            GROUP BY region
            HAVING SUM(total) > 100
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) >= 1

    def test_detail_mentions_column(self) -> None:
        """Diagnostic detail should mention the offending column."""
        sql = """
            SELECT SUM(total)
            FROM (
                SELECT SUM(amount) AS total FROM orders GROUP BY region
            ) sub
        """
        diags = validate_query(sql)
        reagg = [d for d in diags if d.code == "WARN-REAGGREGATION"]
        assert len(reagg) >= 1
        assert "total" in (reagg[0].detail or "").lower()

    def test_window_function_in_cte_not_flagged_as_aggregate(self) -> None:
        """Window output is per-row. Covers the CTE branch of scope collection;
        `TestSafeAggregationPatterns` covers the inline-subquery branch."""
        sql = """
            WITH ranked AS (
                SELECT id, amount,
                       ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at) AS rn
                FROM orders
            )
            SELECT SUM(amount) FROM ranked WHERE rn = 1
        """
        diags = validate_query(sql)
        assert not _has_reaggregation(diags)

    def test_chained_cte_reaggregation(self) -> None:
        """Aggregate lineage survives a CTE selecting from an earlier CTE."""
        sql = """
            WITH base AS (
                SELECT region, SUM(amount) AS total FROM orders GROUP BY region
            ),
            passthrough AS (
                SELECT region, total FROM base
            )
            SELECT SUM(total) FROM passthrough
        """
        diags = validate_query(sql)
        assert _has_reaggregation(diags)

    def test_inline_subquery_passthrough_from_cte(self) -> None:
        """Lineage is inherited through an inline subquery over a CTE."""
        sql = """
            WITH base AS (
                SELECT region, SUM(amount) AS total FROM orders GROUP BY region
            )
            SELECT SUM(total) FROM (SELECT region, total FROM base) sub
        """
        diags = validate_query(sql)
        assert _has_reaggregation(diags)


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestReaggregationCLI:
    """Re-aggregation diagnostics appear through the CLI."""

    def test_cli_shows_reaggregation_warning(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text("# project marker\n")
        sql = (
            "SELECT SUM(total) FROM "
            "(SELECT SUM(amount) AS total FROM orders GROUP BY region) sub"
        )
        result = runner.invoke(
            app, ["query", "db", sql, "--validate", "--project-dir", str(tmp_path)]
        )
        assert result.exit_code == 0  # warnings don't cause exit 1
        assert "WARN-REAGGREGATION" in result.output

    def test_cli_json_includes_reaggregation(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text("# project marker\n")
        sql = (
            "SELECT SUM(total) FROM "
            "(SELECT SUM(amount) AS total FROM orders GROUP BY region) sub"
        )
        result = runner.invoke(
            app,
            [
                "query",
                "db",
                sql,
                "--validate",
                "--json",
                "--project-dir",
                str(tmp_path),
            ],
        )
        parsed = json.loads(result.output)
        assert any(d["code"] == "WARN-REAGGREGATION" for d in parsed)


# ===========================================================================
# Looker symmetric-aggregate carve-out
# ===========================================================================

# Looker's fan-out-safe measure: pack the measure with a hash of the dedup key,
# SUM(DISTINCT ...) to collapse duplicate keys, then subtract a second
# SUM(DISTINCT hash-only) to remove the packed hash mass. The subtraction is what
# makes it the identity `sum of M over distinct K` rather than a second summation.
# Reduced from the real emission in the Fivetran `revenue_change` TV board; the
# sibling emitter is libs/looker/likeml/src/likeml/symmetric.py.
_OFFSET = (
    "(CAST(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(CAST(g.goal_name AS STRING))), 1, 15))"
    " AS INT64) AS NUMERIC) * 4294967296 + CAST(CAST(CONCAT('0x',"
    " SUBSTR(TO_HEX(MD5(CAST(g.goal_name AS STRING))), 16, 8)) AS INT64) AS NUMERIC))"
    " * 0.000000001"
)

_GOALS_CTE = """
    WITH goals AS (
        SELECT date, goal_name, SUM(goal) AS goal
        FROM raw_goals
        GROUP BY 1, 2
    )
"""


def _symmetric_query(measure: str = "g.goal") -> str:
    """A symmetric aggregate over the pre-aggregated `goals` CTE."""
    return f"""{_GOALS_CTE}
        SELECT
            r.month,
            ROUND(COALESCE(CAST((
                SUM(DISTINCT (CAST(ROUND(COALESCE({measure}, 0) * (1/1000*1.0), 9)
                    AS NUMERIC) + {_OFFSET}))
                - SUM(DISTINCT ({_OFFSET}))
            ) / (1/1000*1.0) AS NUMERIC), 0), 6) AS goal_amount
        FROM revenue r
        LEFT JOIN goals g ON r.month = g.date
        GROUP BY 1
    """


class TestLookerSymmetricAggregate:
    """Looker's symmetric aggregate reads a per-key value across a fan-out join.

    It is an algebraic identity, not a second aggregation, so it must not trip
    WARN-REAGGREGATION — but the exemption is keyed to that exact shape, not to
    SUM(DISTINCT ...) in general.
    """

    def test_symmetric_aggregate_over_aggregated_cte_not_flagged(self) -> None:
        diags = validate_query(_symmetric_query(), dialect="bigquery")
        assert not _has_reaggregation(diags)

    def test_plain_sum_of_pre_summed_column_still_flagged(self) -> None:
        """The bug the check exists for — same CTE, no symmetric aggregate."""
        sql = f"""{_GOALS_CTE}
            SELECT r.month, SUM(g.goal) AS goal_amount
            FROM revenue r
            LEFT JOIN goals g ON r.month = g.date
            GROUP BY 1
        """
        diags = validate_query(sql, dialect="bigquery")
        assert _has_reaggregation(diags)

    def test_sum_distinct_without_hash_still_flagged(self) -> None:
        """DISTINCT alone does not make re-aggregation safe."""
        sql = f"""{_GOALS_CTE}
            SELECT r.month, SUM(DISTINCT g.goal) AS goal_amount
            FROM revenue r
            LEFT JOIN goals g ON r.month = g.date
            GROUP BY 1
        """
        diags = validate_query(sql, dialect="bigquery")
        assert _has_reaggregation(diags)

    def test_hashed_sum_distinct_without_paired_half_still_flagged(self) -> None:
        """A measure half with no subtracted hash-only half is not an identity —
        it is a meaningless number, and worth warning about."""
        sql = f"""{_GOALS_CTE}
            SELECT
                r.month,
                SUM(DISTINCT (CAST(ROUND(COALESCE(g.goal, 0) * (1/1000*1.0), 9)
                    AS NUMERIC) + {_OFFSET})) AS goal_amount
            FROM revenue r
            LEFT JOIN goals g ON r.month = g.date
            GROUP BY 1
        """
        diags = validate_query(sql, dialect="bigquery")
        assert _has_reaggregation(diags)

    def test_farm_fingerprint_variant_not_flagged(self) -> None:
        """Non-BigQuery-MD5 Looker dialects hash with FARM_FINGERPRINT."""
        offset = "CAST(FARM_FINGERPRINT(CAST(g.goal_name AS STRING)) AS NUMERIC) * 1e18"
        sql = f"""{_GOALS_CTE}
            SELECT
                r.month,
                (SUM(DISTINCT (CAST(g.goal AS NUMERIC) + {offset}))
                 - SUM(DISTINCT ({offset}))) AS goal_amount
            FROM revenue r
            LEFT JOIN goals g ON r.month = g.date
            GROUP BY 1
        """
        diags = validate_query(sql, dialect="bigquery")
        assert not _has_reaggregation(diags)

    def test_sibling_operand_must_itself_be_the_hash_half(self) -> None:
        """The pairing requires the other operand to BE a hash-only half.

        Searching its subtree instead would let any hashed `SUM(DISTINCT ...)`
        buried anywhere inside the sibling satisfy the pairing, carrying a real
        re-aggregation along with it.
        """
        sql = f"""{_GOALS_CTE}
            SELECT
                r.month,
                (SUM(DISTINCT (CAST(ROUND(COALESCE(g.goal, 0), 9) AS NUMERIC)
                    + {_OFFSET}))
                 - (SUM(DISTINCT ({_OFFSET})) + SUM(r.amount))) AS goal_amount
            FROM revenue r
            LEFT JOIN goals g ON r.month = g.date
            GROUP BY 1
        """
        diags = validate_query(sql, dialect="bigquery")
        assert _has_reaggregation(diags)
