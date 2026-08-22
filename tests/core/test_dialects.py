"""Unit tests for SQL dialect abstraction layer.

Tests cover:
- Base SQLDialect class behavior
- Each dialect implementation (PostgreSQL, DuckDB, MySQL, etc.)
- Dialect registry and get_dialect() function
- Parameter generation, temp tables, and filter macros
"""

import pytest

from dbt_charts.core.dialects import (
    DIALECTS,
    AthenaDialect,
    BigQueryDialect,
    DatabricksDialect,
    DuckDBDialect,
    MySQLDialect,
    PostgresDialect,
    RedshiftDialect,
    SnowflakeDialect,
    SparkDialect,
    SQLDialect,
    SQLiteDialect,
    SQLServerDialect,
    get_dialect,
    list_dialects,
)


class TestSQLDialectBase:
    """Tests for the base SQLDialect abstract class."""

    def test_cannot_instantiate_base_class(self) -> None:
        """Base SQLDialect cannot be instantiated directly."""
        with pytest.raises(TypeError):
            SQLDialect()  # type: ignore

    def test_base_class_has_required_abstract_method(self) -> None:
        """Base class requires param() to be implemented."""

        class IncompleteDialect(SQLDialect):
            name = "incomplete"

        with pytest.raises(TypeError):
            IncompleteDialect()  # type: ignore


class TestPostgresDialect:
    """Tests for PostgreSQL dialect."""

    @pytest.fixture
    def dialect(self) -> PostgresDialect:
        return PostgresDialect()

    def test_name(self, dialect: PostgresDialect) -> None:
        """PostgreSQL dialect has correct name."""
        assert dialect.name == "postgres"

    def test_param_single(self, dialect: PostgresDialect) -> None:
        """Single parameter uses $N format."""
        assert dialect.param(1) == "$1"
        assert dialect.param(2) == "$2"
        assert dialect.param(10) == "$10"

    def test_params_list(self, dialect: PostgresDialect) -> None:
        """Multiple parameters generated correctly."""
        assert dialect.params(3) == ["$1", "$2", "$3"]
        assert dialect.params(1) == ["$1"]
        assert dialect.params(0) == []

    def test_statement_timeout_sql(self, dialect: PostgresDialect) -> None:
        """Postgres emits a server-side SET statement_timeout."""
        assert dialect.statement_timeout_sql(30) == "SET statement_timeout = '30s'"


class TestDuckDBDialect:
    """Tests for DuckDB dialect."""

    @pytest.fixture
    def dialect(self) -> DuckDBDialect:
        return DuckDBDialect()

    def test_name(self, dialect: DuckDBDialect) -> None:
        """DuckDB dialect has correct name."""
        assert dialect.name == "duckdb"

    def test_param(self, dialect: DuckDBDialect) -> None:
        """DuckDB uses $N parameters like PostgreSQL."""
        assert dialect.param(1) == "$1"
        assert dialect.param(2) == "$2"

    def test_statement_timeout_sql_is_noop(self, dialect: DuckDBDialect) -> None:
        """DuckDB has no server to enforce a statement timeout against."""
        assert dialect.statement_timeout_sql(30) is None


class TestSQLiteDialectTimeout:
    """SQLite's statement_timeout_sql no-op (mirrors DuckDB — no server)."""

    def test_statement_timeout_sql_is_noop(self) -> None:
        assert SQLiteDialect().statement_timeout_sql(30) is None


class TestMySQLDialect:
    """Tests for MySQL dialect."""

    @pytest.fixture
    def dialect(self) -> MySQLDialect:
        return MySQLDialect()

    def test_name(self, dialect: MySQLDialect) -> None:
        """MySQL dialect has correct name."""
        assert dialect.name == "mysql"

    def test_param_is_placeholder(self, dialect: MySQLDialect) -> None:
        """MySQL uses %s for all parameters (index ignored)."""
        assert dialect.param(1) == "%s"
        assert dialect.param(2) == "%s"
        assert dialect.param(100) == "%s"


class TestSnowflakeDialect:
    """Tests for Snowflake dialect."""

    @pytest.fixture
    def dialect(self) -> SnowflakeDialect:
        return SnowflakeDialect()

    def test_name(self, dialect: SnowflakeDialect) -> None:
        """Snowflake dialect has correct name."""
        assert dialect.name == "snowflake"

    def test_param(self, dialect: SnowflakeDialect) -> None:
        """Snowflake uses ? for parameters."""
        assert dialect.param(1) == "?"
        assert dialect.param(2) == "?"

    def test_statement_timeout_sql(self, dialect: SnowflakeDialect) -> None:
        """Snowflake emits ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS."""
        assert (
            dialect.statement_timeout_sql(45)
            == "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 45"
        )


class TestBigQueryDialect:
    """Tests for BigQuery dialect."""

    @pytest.fixture
    def dialect(self) -> BigQueryDialect:
        return BigQueryDialect()

    def test_name(self, dialect: BigQueryDialect) -> None:
        """BigQuery dialect has correct name."""
        assert dialect.name == "bigquery"

    def test_param(self, dialect: BigQueryDialect) -> None:
        """BigQuery uses @paramN format."""
        assert dialect.param(1) == "@param1"
        assert dialect.param(2) == "@param2"

    def test_statement_timeout_sql_is_noop(self, dialect: BigQueryDialect) -> None:
        """BigQuery's timeout is a job-level setting, not SQL — see sql_adapter.py."""
        assert dialect.statement_timeout_sql(60) is None


class TestRedshiftDialect:
    """Tests for Redshift dialect."""

    @pytest.fixture
    def dialect(self) -> RedshiftDialect:
        return RedshiftDialect()

    def test_name(self, dialect: RedshiftDialect) -> None:
        """Redshift dialect has correct name."""
        assert dialect.name == "redshift"

    def test_param_like_postgres(self, dialect: RedshiftDialect) -> None:
        """Redshift uses PostgreSQL-style $N parameters."""
        assert dialect.param(1) == "$1"
        assert dialect.param(2) == "$2"

    def test_statement_timeout_sql_inherited_from_postgres(
        self, dialect: RedshiftDialect
    ) -> None:
        """Redshift inherits Postgres's SET statement_timeout."""
        assert dialect.statement_timeout_sql(30) == "SET statement_timeout = '30s'"


class TestSQLServerDialect:
    """Tests for SQL Server dialect."""

    @pytest.fixture
    def dialect(self) -> SQLServerDialect:
        return SQLServerDialect()

    def test_name(self, dialect: SQLServerDialect) -> None:
        """SQL Server dialect has correct name."""
        assert dialect.name == "sqlserver"

    def test_param(self, dialect: SQLServerDialect) -> None:
        """SQL Server uses @pN format."""
        assert dialect.param(1) == "@p1"
        assert dialect.param(2) == "@p2"


class TestDatabricksDialect:
    """Tests for Databricks dialect."""

    @pytest.fixture
    def dialect(self) -> DatabricksDialect:
        return DatabricksDialect()

    def test_name(self, dialect: DatabricksDialect) -> None:
        """Databricks dialect has correct name."""
        assert dialect.name == "databricks"

    def test_param(self, dialect: DatabricksDialect) -> None:
        """Databricks uses :paramN format."""
        assert dialect.param(1) == ":param1"
        assert dialect.param(2) == ":param2"

    def test_statement_timeout_sql_is_noop(self, dialect: DatabricksDialect) -> None:
        """Databricks has no verified session-level timeout SQL across all compute types."""
        assert dialect.statement_timeout_sql(90) is None


class TestAthenaDialect:
    """Tests for Athena dialect."""

    @pytest.fixture
    def dialect(self) -> AthenaDialect:
        return AthenaDialect()

    def test_name(self, dialect: AthenaDialect) -> None:
        """Athena dialect has correct name."""
        assert dialect.name == "athena"

    def test_param(self, dialect: AthenaDialect) -> None:
        """Athena uses ? for parameters."""
        assert dialect.param(1) == "?"
        assert dialect.param(2) == "?"


class TestDialectRegistry:
    """Tests for the dialect registry and get_dialect() function."""

    def test_get_postgres_dialect(self) -> None:
        """Get PostgreSQL dialect."""
        dialect = get_dialect("postgres")
        assert isinstance(dialect, PostgresDialect)
        assert dialect.name == "postgres"

    def test_get_postgresql_alias(self) -> None:
        """postgresql is an alias for postgres."""
        dialect = get_dialect("postgresql")
        assert isinstance(dialect, PostgresDialect)

    def test_get_duckdb_dialect(self) -> None:
        """Get DuckDB dialect."""
        dialect = get_dialect("duckdb")
        assert isinstance(dialect, DuckDBDialect)

    def test_get_mysql_dialect(self) -> None:
        """Get MySQL dialect."""
        dialect = get_dialect("mysql")
        assert isinstance(dialect, MySQLDialect)

    def test_get_mariadb_alias(self) -> None:
        """mariadb is an alias for mysql."""
        dialect = get_dialect("mariadb")
        assert isinstance(dialect, MySQLDialect)

    def test_get_snowflake_dialect(self) -> None:
        """Get Snowflake dialect."""
        dialect = get_dialect("snowflake")
        assert isinstance(dialect, SnowflakeDialect)

    def test_get_bigquery_dialect(self) -> None:
        """Get BigQuery dialect."""
        dialect = get_dialect("bigquery")
        assert isinstance(dialect, BigQueryDialect)

    def test_get_redshift_dialect(self) -> None:
        """Get Redshift dialect."""
        dialect = get_dialect("redshift")
        assert isinstance(dialect, RedshiftDialect)

    def test_get_sqlserver_dialect(self) -> None:
        """Get SQL Server dialect."""
        dialect = get_dialect("sqlserver")
        assert isinstance(dialect, SQLServerDialect)

    def test_get_mssql_alias(self) -> None:
        """mssql is an alias for sqlserver."""
        dialect = get_dialect("mssql")
        assert isinstance(dialect, SQLServerDialect)

    def test_get_databricks_dialect(self) -> None:
        """Get Databricks dialect."""
        dialect = get_dialect("databricks")
        assert isinstance(dialect, DatabricksDialect)

    def test_get_spark_alias(self) -> None:
        """spark shares Databricks' SQL grammar (SparkDialect subclasses
        DatabricksDialect) but is its own dialect, not a shared instance —
        dbt-spark's cursor lacks fetchmany, unlike dbt-databricks'."""
        dialect = get_dialect("spark")
        assert isinstance(dialect, SparkDialect)
        assert isinstance(dialect, DatabricksDialect)
        assert dialect is not get_dialect("databricks")

    def test_databricks_and_spark_differ_on_driver_limit_support(self) -> None:
        """The one behavioral difference this split exists for: dbt-databricks'
        cursor implements fetchmany, dbt-spark's (Hive/ODBC wrappers) does not."""
        assert get_dialect("databricks").cursor_supports_driver_limit is True
        assert get_dialect("spark").cursor_supports_driver_limit is False

    def test_get_athena_dialect(self) -> None:
        """Get Athena dialect."""
        dialect = get_dialect("athena")
        assert isinstance(dialect, AthenaDialect)

    def test_get_presto_alias(self) -> None:
        """presto is an alias for athena."""
        dialect = get_dialect("presto")
        assert isinstance(dialect, AthenaDialect)

    def test_get_trino_alias(self) -> None:
        """trino is an alias for athena."""
        dialect = get_dialect("trino")
        assert isinstance(dialect, AthenaDialect)

    def test_unknown_dialect_returns_postgres(self) -> None:
        """Unknown dialect type falls back to PostgreSQL."""
        dialect = get_dialect("unknown_db")
        assert isinstance(dialect, PostgresDialect)

    def test_case_insensitive(self) -> None:
        """Dialect lookup is case-insensitive."""
        dialect = get_dialect("POSTGRES")
        assert isinstance(dialect, PostgresDialect)

        dialect = get_dialect("MySQL")
        assert isinstance(dialect, MySQLDialect)

    def test_singleton_instances(self) -> None:
        """Same dialect instance is returned for repeated calls."""
        dialect1 = get_dialect("postgres")
        dialect2 = get_dialect("postgres")
        assert dialect1 is dialect2

        dialect3 = get_dialect("postgresql")
        assert dialect1 is dialect3

    def test_dialects_dict_contains_all(self) -> None:
        """DIALECTS dict contains all expected entries."""
        expected_keys = [
            "postgres",
            "postgresql",
            "duckdb",
            "mysql",
            "mariadb",
            "snowflake",
            "bigquery",
            "redshift",
            "sqlserver",
            "mssql",
            "databricks",
            "spark",
            "athena",
            "presto",
            "trino",
        ]
        for key in expected_keys:
            assert key in DIALECTS, f"Missing dialect: {key}"

    def test_list_dialects(self) -> None:
        """list_dialects() returns all supported profile types."""
        dialects = list_dialects()
        assert "postgres" in dialects
        assert "mysql" in dialects
        assert "duckdb" in dialects
        assert len(dialects) >= 15  # At least all the expected keys


class TestDialectEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_param_index_zero(self) -> None:
        """Param index 0 (unusual but valid)."""
        dialect = PostgresDialect()
        assert dialect.param(0) == "$0"

    def test_param_large_index(self) -> None:
        """Large param index."""
        dialect = PostgresDialect()
        assert dialect.param(999) == "$999"

    def test_params_generates_correct_count(self) -> None:
        """params() generates exactly the requested count."""
        dialect = BigQueryDialect()
        params = dialect.params(5)
        assert len(params) == 5
        assert params == ["@param1", "@param2", "@param3", "@param4", "@param5"]
