"""Databricks dialect implementation.

Databricks uses:
- :param1, :param2 for named parameter placeholders
"""

from dbt_charts.core.dialects.base import SQLDialect


class DatabricksDialect(SQLDialect):
    """Databricks dialect with :paramN parameter style.

    Databricks (Spark SQL) uses named parameters with : prefix.

    max_query_duration_seconds is not enforced for Databricks — SET STATEMENT_TIMEOUT
    requires DBSQL warehouses 14.1+ and would fail on interactive clusters; pending a
    verified mechanism across all Databricks compute types.

    Example:
        >>> dialect = DatabricksDialect()
        >>> dialect.param(1)
        ':param1'
    """

    name = "databricks"
    # Spark SQL string literals: use \ to escape special characters (' or \).
    # https://spark.apache.org/docs/latest/sql-ref-literals.html
    escapes_backslashes = True
    uses_named_params = True

    def param(self, index: int) -> str:
        """Generate Databricks parameter placeholder.

        Databricks uses :paramN named style.

        Args:
            index: 1-based parameter index

        Returns:
            Parameter placeholder in :paramN format
        """
        return f":param{index}"


class SparkDialect(DatabricksDialect):
    """Spark dialect — same SQL grammar as Databricks, but the PySpark cursors
    (PyhiveConnectionWrapper, PyodbcConnectionWrapper, SparkConnectionWrapper)
    implement fetchall but not fetchmany.  cursor_supports_driver_limit = False
    causes the adapters to fall back to fetchall + post-fetch slice instead of
    using the limit= kwarg.
    """

    name = "spark"
    cursor_supports_driver_limit = False
