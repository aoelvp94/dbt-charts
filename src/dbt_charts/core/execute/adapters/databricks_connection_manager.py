"""Per-connection credential isolation for dbt-databricks.

dbt-databricks' DatabricksConnectionManager.open() writes the credential manager to a
class-level variable (cls.credentials_manager) and then reads it back to build
connection arguments — no lock between the write and the read.  In a multi-tenant
process two concurrent opens race: thread B's write clobbers the class var before
thread A reads it, so tenant A's SQL session opens authenticated as tenant B.

This module provides DbtChartsDatabricksConnectionManager, a subclass that overrides
open() to authenticate into a call-local variable and pass that local to
prepare_connection_arguments rather than writing to cls.credentials_manager,
eliminating the race.

Because open() never sets cls.credentials_manager, the inherited _query_dbr_version()
stays safe for SQL warehouses (it returns before reading the class var) and raises
loudly for clusters (class var is None) rather than crossing credentials — Dataface
Databricks connections are SQL warehouses.

Drift guard
-----------
If the upstream open() body changes in a dbt-databricks version bump, _VENDORED_OPEN_HASH
will no longer match and _assert_vendored_methods_unchanged() raises at import time, so CI
catches the desync before a silent credential mismatch at runtime.

To update after a version bump: first read the new upstream open() and confirm it
still writes the authenticated manager only to a call-local (never to
cls.credentials_manager) — matching the hash on bytes alone would silently re-arm
the cross-tenant race. Then re-run the hash computation and update the constant:

  uv run python -c "
  import inspect, hashlib
  from dbt.adapters.databricks.connections import DatabricksConnectionManager as C
  print(hashlib.sha256(inspect.getsource(C.open).encode()).hexdigest())
  "
"""

import inspect
from typing import cast

from databricks.sql.exc import Error
from dbt.adapters.contracts.connection import Connection, ConnectionState
from dbt.adapters.databricks.connections import (
    DatabricksConnectionManager,
    DatabricksDBTConnection,
    QueryConfigUtils,
    SqlUtils,
)
from dbt.adapters.databricks.credentials import (
    DatabricksCredentials,
)
from dbt.adapters.databricks.events.connection_events import (  # pyright: ignore[reportMissingTypeStubs]
    ConnectionCreateError,
)
from dbt.adapters.databricks.handle import DatabricksHandle
from dbt.adapters.databricks.logging import logger
from dbt.adapters.databricks.utils import is_cluster_http_path
from dbt_common.exceptions import DbtDatabaseError

# SHA-256 of inspect.getsource(DatabricksConnectionManager.open) for dbt-databricks 1.12.0.
# Update this constant whenever the package version changes and re-verify the override.
_VENDORED_OPEN_HASH = "256b105e3e59ad75b494d4687a770603677a9dce71663535a90aeece425f941c"


def _assert_vendored_methods_unchanged() -> None:
    """Raise if the vendored open() body has drifted.

    Called at module import time so CI fails fast on a dbt-databricks version bump
    that changes the patched method before a silent credential mismatch at runtime.
    """
    import hashlib

    src = inspect.getsource(DatabricksConnectionManager.open)
    actual = hashlib.sha256(src.encode()).hexdigest()
    if actual != _VENDORED_OPEN_HASH:
        raise RuntimeError(
            f"dbt-databricks vendored method DatabricksConnectionManager.open "
            f"has changed (expected hash {_VENDORED_OPEN_HASH}, got {actual}). "
            f"Update DbtChartsDatabricksConnectionManager.open to match the new "
            f"upstream body and update _VENDORED_OPEN_HASH."
        )


_assert_vendored_methods_unchanged()


class DbtChartsDatabricksConnectionManager(DatabricksConnectionManager):
    """DatabricksConnectionManager with per-connection credential isolation.

    Overrides open() so the credential manager is local to each call rather than
    shared via cls.credentials_manager, so concurrent opens from different tenants
    cannot cross credentials.
    """

    @classmethod
    def open(cls, connection: Connection) -> Connection:
        databricks_connection = cast(DatabricksDBTConnection, connection)

        if connection.state == ConnectionState.OPEN:
            return connection

        creds = cast(DatabricksCredentials, connection.credentials)
        timeout = creds.connect_timeout

        # Authenticate into a local variable instead of cls.credentials_manager so
        # concurrent opens in other threads cannot see this credential manager.
        creds_manager = creds.authenticate()

        # `_query_header_context` is a declared field on DatabricksDBTConnection
        # (`Any = None`), so it is always present — no getattr default needed.
        query_header_context = databricks_connection._query_header_context
        merged_query_tags: dict[str, str] = {}
        if query_header_context:
            merged_query_tags = QueryConfigUtils.get_merged_query_tags(
                query_header_context, creds
            )

        conn_args = SqlUtils.prepare_connection_arguments(
            creds, creds_manager, databricks_connection.http_path, merged_query_tags
        )

        def connect() -> DatabricksHandle:
            try:
                conn = DatabricksHandle.from_connection_args(
                    conn_args,
                    is_cluster_http_path(
                        databricks_connection.http_path, creds.cluster_id
                    ),
                )
                if conn:
                    databricks_connection.session_id = conn.session_id
                    cls._cache_dbr_capabilities(creds, databricks_connection.http_path)
                    databricks_connection.capabilities = (
                        cls._get_capabilities_for_http_path(
                            databricks_connection.http_path
                        )
                    )
                    return conn
                else:
                    raise DbtDatabaseError("Failed to create connection")
            except Error as exc:
                logger.error(ConnectionCreateError(exc))
                raise

        def exponential_backoff(attempt: int) -> int:
            return attempt * attempt

        retryable_exceptions: list[type[Exception]] = []
        if creds.retry_all:
            retryable_exceptions = [Error]

        return cls.retry_connection(
            connection,
            connect=connect,
            logger=logger,
            retryable_exceptions=retryable_exceptions,
            retry_limit=creds.connect_retries,
            retry_timeout=(timeout if timeout is not None else exponential_backoff),
        )
