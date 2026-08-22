"""Comprehensive fanout detection test suite.

Proves that the query validator detects fanout risk across:
- Aggregation functions: SUM, AVG, MIN, MAX, COUNT, COUNT(DISTINCT),
  STDDEV, VARIANCE, ARRAY_AGG, GROUP_CONCAT
- Join types: INNER, LEFT, RIGHT, FULL OUTER, self-join, 3-table chain,
  4-table star schema
- SQL patterns: CTEs, HAVING, CASE/COALESCE inside aggregates, aliased
  expressions
- Safe queries: pre-aggregated subqueries, EXISTS, scalar subqueries,
  window-only, DISTINCT without aggregation
- Dialect variations: BigQuery, Snowflake, DuckDB
- Error message clarity: tables named, risk explained, fix recommended
"""

from __future__ import annotations

import pytest

from dbt_charts.core.inspect.query_validator import (
    QueryDiagnostic,
    validate_query,
)


def _has_fanout(diags: list[QueryDiagnostic]) -> bool:
    return any(d.code == "WARN-FANOUT-RISK" for d in diags)


def _fanout_diags(diags: list[QueryDiagnostic]) -> list[QueryDiagnostic]:
    return [d for d in diags if d.code == "WARN-FANOUT-RISK"]


# ---------------------------------------------------------------------------
# A. Aggregation function coverage — each should trigger with a 1:N join
# ---------------------------------------------------------------------------


class TestAggregationFunctions:
    """Every common aggregate function should trigger fanout detection
    when applied to columns from multiple joined tables."""

    @pytest.mark.parametrize(
        "agg_expr",
        [
            "AVG(o.amount), AVG(li.quantity)",
            "MIN(o.amount), MIN(li.quantity)",
            "MAX(o.amount), MAX(li.quantity)",
            "COUNT(o.id), COUNT(li.id)",
            "STDDEV(o.amount), STDDEV(li.quantity)",
            "VARIANCE(o.amount), VARIANCE(li.quantity)",
            "ARRAY_AGG(o.amount), ARRAY_AGG(li.quantity)",
            "GROUP_CONCAT(o.status), GROUP_CONCAT(li.name)",
        ],
        ids=[
            "avg",
            "min",
            "max",
            "count_col",
            "stddev",
            "variance",
            "array_agg",
            "group_concat",
        ],
    )
    def test_basic_agg_multi_table(self, agg_expr: str) -> None:
        sql = f"""
            SELECT {agg_expr}
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        assert _has_fanout(validate_query(sql))

    def test_count_distinct_multi_table(self) -> None:
        """COUNT(DISTINCT col) from one table + another agg from another table."""
        sql = """
            SELECT COUNT(DISTINCT o.id), SUM(li.quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.customer_id
        """
        assert _has_fanout(validate_query(sql))

    @pytest.mark.parametrize(
        "agg_expr",
        [
            "SUM(o.amount) + SUM(li.quantity)",
            "SUM(o.amount) - AVG(li.quantity)",
            "SUM(o.amount) * COUNT(li.id)",
        ],
        ids=["sum_plus_sum", "sum_minus_avg", "sum_times_count"],
    )
    def test_arithmetic_on_multi_table_aggs(self, agg_expr: str) -> None:
        """Aggregates from different tables combined with arithmetic."""
        sql = f"""
            SELECT {agg_expr}
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        assert _has_fanout(validate_query(sql))

    def test_mixed_agg_functions_same_query(self) -> None:
        """Multiple different agg functions across tables in one SELECT."""
        sql = """
            SELECT
                SUM(o.amount),
                AVG(li.price),
                MAX(o.created_at),
                MIN(li.quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.customer_id
        """
        assert _has_fanout(validate_query(sql))


# ---------------------------------------------------------------------------
# B. Join type coverage
# ---------------------------------------------------------------------------


class TestJoinTypes:
    """Fanout should be detected regardless of which JOIN keyword is used."""

    @pytest.mark.parametrize(
        "join_kw",
        [
            "JOIN",
            "INNER JOIN",
            "LEFT JOIN",
            "LEFT OUTER JOIN",
            "RIGHT JOIN",
            "RIGHT OUTER JOIN",
            "FULL JOIN",
            "FULL OUTER JOIN",
        ],
        ids=[
            "join",
            "inner",
            "left",
            "left_outer",
            "right",
            "right_outer",
            "full",
            "full_outer",
        ],
    )
    def test_join_keyword_variants(self, join_kw: str) -> None:
        sql = f"""
            SELECT SUM(o.amount), SUM(li.quantity)
            FROM orders o
            {join_kw} line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        assert _has_fanout(validate_query(sql))

    def test_self_join(self) -> None:
        """Self-join with aggregation from both aliases."""
        sql = """
            SELECT SUM(e1.salary), SUM(e2.salary)
            FROM employees e1
            JOIN employees e2 ON e1.manager_id = e2.id
            GROUP BY e1.department_id
        """
        assert _has_fanout(validate_query(sql))

    def test_three_table_chain(self) -> None:
        """Three-table join chain with aggregates spanning tables."""
        sql = """
            SELECT SUM(o.amount), SUM(li.quantity), COUNT(p.id)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            JOIN products p ON li.product_id = p.id
            GROUP BY o.customer_id
        """
        assert _has_fanout(validate_query(sql))

    def test_four_table_star_join(self) -> None:
        """Star schema join — fact table joined to multiple dimensions."""
        sql = """
            SELECT SUM(f.revenue), COUNT(c.id), MAX(p.name)
            FROM fact_sales f
            JOIN dim_customer c ON f.customer_id = c.id
            JOIN dim_product p ON f.product_id = p.id
            JOIN dim_date d ON f.date_id = d.id
            GROUP BY d.year
        """
        assert _has_fanout(validate_query(sql))


# ---------------------------------------------------------------------------
# C. SQL pattern coverage
# ---------------------------------------------------------------------------


class TestSQLPatterns:
    """Fanout detection across diverse SQL constructs."""

    def test_cte_with_fanout_in_outer_query(self) -> None:
        """CTE materialized, then joined in outer query with multi-table agg."""
        sql = """
            WITH order_totals AS (
                SELECT id, customer_id, amount FROM orders
            )
            SELECT SUM(ot.amount), SUM(li.quantity)
            FROM order_totals ot
            JOIN line_items li ON ot.id = li.order_id
            GROUP BY ot.customer_id
        """
        assert _has_fanout(validate_query(sql))

    def test_cte_joined_to_cte(self) -> None:
        """Two CTEs joined in the outer query with multi-table agg."""
        sql = """
            WITH cte_a AS (SELECT id, val FROM table_a),
                 cte_b AS (SELECT id, val FROM table_b)
            SELECT SUM(a.val), SUM(b.val)
            FROM cte_a a
            JOIN cte_b b ON a.id = b.id
            GROUP BY a.id
        """
        assert _has_fanout(validate_query(sql))

    def test_having_with_multi_table_agg(self) -> None:
        """HAVING with aggregate referencing joined table column."""
        sql = """
            SELECT o.id, SUM(o.amount)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
            HAVING SUM(li.quantity) > 10
        """
        assert _has_fanout(validate_query(sql))

    def test_aliased_aggregate_expression(self) -> None:
        """Aggregate with alias should still be detected."""
        sql = """
            SELECT SUM(o.amount) AS total_amount, SUM(li.quantity) AS total_qty
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        assert _has_fanout(validate_query(sql))

    def test_case_inside_aggregate(self) -> None:
        """CASE expression inside aggregate referencing multiple tables."""
        sql = """
            SELECT
                SUM(CASE WHEN o.status = 'complete' THEN o.amount ELSE 0 END),
                SUM(li.quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.customer_id
        """
        assert _has_fanout(validate_query(sql))

    def test_coalesce_inside_aggregate(self) -> None:
        """COALESCE inside aggregate referencing multiple tables."""
        sql = """
            SELECT SUM(COALESCE(o.amount, 0)), SUM(li.quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        assert _has_fanout(validate_query(sql))


# ---------------------------------------------------------------------------
# D. Safe queries — false-positive avoidance
# ---------------------------------------------------------------------------


class TestSafeQueriesComprehensive:
    """Queries that should NOT trigger WARN-FANOUT-RISK."""

    def test_pre_aggregated_subquery(self) -> None:
        """Pre-aggregated subquery joined to dimension — the recommended fix pattern."""
        sql = """
            SELECT
                order_totals.total,
                item_counts.cnt
            FROM (
                SELECT customer_id, SUM(amount) AS total
                FROM orders
                GROUP BY customer_id
            ) order_totals
            JOIN (
                SELECT order_id, COUNT(*) AS cnt
                FROM line_items
                GROUP BY order_id
            ) item_counts ON order_totals.customer_id = item_counts.order_id
        """
        assert not _has_fanout(validate_query(sql))

    def test_exists_subquery(self) -> None:
        """EXISTS subquery — not a join, no fanout."""
        sql = """
            SELECT customer_id, SUM(amount)
            FROM orders o
            WHERE EXISTS (
                SELECT 1 FROM customers c WHERE c.id = o.customer_id
            )
            GROUP BY customer_id
        """
        assert not _has_fanout(validate_query(sql))

    def test_scalar_subquery_in_select(self) -> None:
        """Scalar subquery in SELECT — not a join, no fanout."""
        sql = """
            SELECT
                customer_id,
                SUM(amount),
                (SELECT name FROM customers c WHERE c.id = o.customer_id) AS customer_name
            FROM orders o
            GROUP BY customer_id
        """
        assert not _has_fanout(validate_query(sql))

    def test_window_function_only_no_group_by(self) -> None:
        """Window function without GROUP BY — no aggregation fanout."""
        sql = """
            SELECT
                o.id,
                SUM(o.amount) OVER (PARTITION BY o.customer_id) AS running_total
            FROM orders o
            JOIN customers c ON o.customer_id = c.id
        """
        assert not _has_fanout(validate_query(sql))

    def test_distinct_without_aggregation(self) -> None:
        """DISTINCT without aggregation — no fanout."""
        sql = """
            SELECT DISTINCT o.customer_id, c.name
            FROM orders o
            JOIN customers c ON o.customer_id = c.id
        """
        assert not _has_fanout(validate_query(sql))


# ---------------------------------------------------------------------------
# E. Error message clarity
# ---------------------------------------------------------------------------


class TestErrorMessageClarity:
    """Validate that fanout diagnostics are clear, specific, and actionable."""

    def _get_fanout(self, sql: str) -> QueryDiagnostic:
        diags = _fanout_diags(validate_query(sql))
        assert len(diags) >= 1, f"Expected WARN-FANOUT-RISK diagnostic for: {sql}"
        return diags[0]

    def test_message_describes_the_problem(self) -> None:
        """The message should explain WHAT the risk is."""
        d = self._get_fanout(
            """
            SELECT SUM(o.amount), SUM(li.quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        )
        msg = d.message.lower()
        assert "aggregat" in msg or "inflate" in msg or "fanout" in msg

    def test_detail_names_tables(self) -> None:
        """The detail should name which tables are involved."""
        d = self._get_fanout(
            """
            SELECT SUM(o.amount), SUM(li.quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        )
        assert d.detail is not None
        detail = d.detail.lower()
        assert "orders" in detail or "line_items" in detail

    def test_detail_for_count_star_mentions_multiplication(self) -> None:
        """COUNT(*) diagnostic should explain row multiplication."""
        d = self._get_fanout(
            """
            SELECT o.customer_id, COUNT(*)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.customer_id
        """
        )
        assert d.detail is not None
        detail = d.detail.lower()
        assert "count(*)" in detail or "count" in detail
        assert "inflat" in detail or "multipl" in detail

    def test_detail_for_unqualified_mentions_ambiguity(self) -> None:
        """Unqualified column diagnostic should mention ambiguity."""
        d = self._get_fanout(
            """
            SELECT SUM(amount), SUM(quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        )
        assert d.detail is not None
        assert "unqualified" in d.detail.lower() or "ambiguous" in d.detail.lower()

    def test_self_join_detail_names_table_and_aliases(self) -> None:
        """Self-join detail should mention the table name and both aliases."""
        d = self._get_fanout(
            """
            SELECT SUM(e1.salary), SUM(e2.salary)
            FROM employees e1
            JOIN employees e2 ON e1.manager_id = e2.id
            GROUP BY e1.department_id
        """
        )
        assert d.detail is not None
        detail = d.detail.lower()
        assert "employees" in detail
        assert "e1" in detail
        assert "e2" in detail


# ---------------------------------------------------------------------------
# F. Dialect coverage
# ---------------------------------------------------------------------------


class TestDialectCoverage:
    """Fanout detection should work across SQL dialects."""

    def test_bigquery_backtick_tables(self) -> None:
        sql = """
            SELECT SUM(o.amount), SUM(li.quantity)
            FROM `project.dataset.orders` o
            JOIN `project.dataset.line_items` li ON o.id = li.order_id
            GROUP BY o.id
        """
        assert _has_fanout(validate_query(sql, dialect="bigquery"))

    def test_snowflake_double_quoted(self) -> None:
        sql = """
            SELECT SUM(o."AMOUNT"), SUM(li."QUANTITY")
            FROM "ORDERS" o
            JOIN "LINE_ITEMS" li ON o."ID" = li."ORDER_ID"
            GROUP BY o."ID"
        """
        assert _has_fanout(validate_query(sql, dialect="snowflake"))

    def test_duckdb_dialect(self) -> None:
        sql = """
            SELECT SUM(o.amount), SUM(li.quantity)
            FROM orders o
            JOIN line_items li ON o.id = li.order_id
            GROUP BY o.id
        """
        assert _has_fanout(validate_query(sql, dialect="duckdb"))
