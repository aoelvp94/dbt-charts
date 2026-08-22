"""SQL Server dialect implementation.

SQL Server uses:
- @p1, @p2, ... for parameter placeholders
"""

from dbt_charts.core.dialects.base import SQLDialect


class SQLServerDialect(SQLDialect):
    """SQL Server dialect with @pN parameter style.

    SQL Server uses named parameters with @ prefix.

    Example:
        >>> dialect = SQLServerDialect()
        >>> dialect.param(1)
        '@p1'
    """

    name = "sqlserver"
    # T-SQL character constants have one escape: an embedded quote is written as
    # two single quotation marks. Backslash carries no meaning.
    # https://learn.microsoft.com/en-us/sql/t-sql/data-types/constants-transact-sql
    escapes_backslashes = False
    uses_named_params = True

    def param(self, index: int) -> str:
        """Generate SQL Server parameter placeholder.

        SQL Server uses @pN named style.

        Args:
            index: 1-based parameter index

        Returns:
            Parameter placeholder in @pN format
        """
        return f"@p{index}"
