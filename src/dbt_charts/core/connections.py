"""Public dbt_charts.core connection API.

Exports test_connection(source_config) → (bool, str), probe_relation_readability,
bulk_schema_for_config, plus the BigQuery discovery helpers hosts use to fill a
connection form: build_bigquery_client, list_datasets, dataset_location.

All DB connection machinery lives in execute/adapters/dbt_adapter_factory.py.
Cloud and other consumers call this, not dbt.adapters directly — Cloud in
particular must never import google.cloud itself.

Discovery deliberately bypasses build_adapter: dbt's Credentials base requires
`schema` (the BigQuery dataset) as a str, which is the very thing discovery is
looking for, so routing through an adapter would mean inventing a sentinel
dataset just to construct one. The BigQuery client needs no dataset at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.source import BigQuerySourceConfig, SourceConfig
    from dbt_charts.core.inspect.bulk_schema import SchemaTree
    from dbt_charts.core.inspect.relations import Relation


def import_bigquery(module_name: str) -> Any:
    """Import an optional google-cloud-bigquery module, naming the extra if absent.

    google-cloud-bigquery ships in the `bigquery` extra, not the runtime deps,
    so a plain ImportError here would read as a bug rather than a missing
    install.
    """
    import importlib

    try:
        return importlib.import_module(module_name)
    except ImportError as err:
        raise ImportError(
            f"{module_name} is required for BigQuery connections. "
            "Install the bigquery extra: pip install 'dbt-charts[bigquery]'"
        ) from err


def build_bigquery_client(
    project: str,
    keyfile_json: dict[str, Any] | None = None,
    keyfile: str | None = None,
) -> Any:
    """Construct a google.cloud.bigquery.Client.

    Takes the three credential inputs rather than a SourceConfig so callers
    holding a raw source-config dict (dbt-charts-super-schema) and callers
    holding a typed model share one implementation.

    Mirrors dbt-bigquery's credential resolution order:
      1. keyfile_json dict → service account credentials
      2. keyfile path     → service account credentials from file
      3. neither          → Application Default Credentials (ADC / metadata server)
    """
    bigquery = import_bigquery("google.cloud.bigquery")
    if keyfile_json is not None:
        service_account = import_bigquery("google.oauth2.service_account")
        creds = service_account.Credentials.from_service_account_info(keyfile_json)
    elif keyfile is not None:
        service_account = import_bigquery("google.oauth2.service_account")
        creds = service_account.Credentials.from_service_account_file(keyfile)
    else:
        creds = None  # ADC / metadata server
    return bigquery.Client(project=project, credentials=creds)


def _client_for(source_config: BigQuerySourceConfig) -> Any:
    return build_bigquery_client(
        source_config.project, source_config.keyfile_json, source_config.keyfile
    )


def list_datasets(source_config: SourceConfig) -> list[str]:
    """Dataset names reachable with these credentials.

    The source_config's own `dataset` is irrelevant here and may be empty —
    this is what the connection form calls before the user can know which
    datasets exist.
    """
    from dbt_charts.core.compile.models.source import BigQuerySourceConfig

    if not isinstance(source_config, BigQuerySourceConfig):
        raise ValueError(
            f"list_datasets is BigQuery-only, got {source_config.type!r}. "
            "Other warehouses list schemas through the dbt adapter."
        )
    client = _client_for(source_config)
    return [ds.dataset_id for ds in client.list_datasets()]


def dataset_location(source_config: SourceConfig) -> str:
    """Location of the dataset named in source_config.

    BigQuery-only, like list_datasets — no other warehouse has a dataset-level
    location, so a non-BigQuery config is a caller bug rather than a None.

    Resolved one dataset at a time on purpose: list_datasets() returns partial
    resources without a location, so filling it for every listed dataset would
    be an N+1 across potentially hundreds of them.
    """
    from dbt_charts.core.compile.models.source import BigQuerySourceConfig

    if not isinstance(source_config, BigQuerySourceConfig):
        raise ValueError(
            f"dataset_location is BigQuery-only, got {source_config.type!r}."
        )
    if not source_config.dataset:
        raise ValueError("dataset_location requires a dataset to look up.")
    location: str = (
        _client_for(source_config).get_dataset(source_config.dataset).location
    )
    return location


def test_connection(source_config: SourceConfig) -> tuple[bool, str]:
    """Verify that source_config can reach the database.

    Constructs a fresh adapter, opens the connection, pings with SELECT 1, and
    lets GC clean up when the local reference drops at function exit. The temp
    target dir is removed by the weakref.finalize registered in build_adapter.

    The connection is opened explicitly, before any SQL, for the same reason
    ``dct query`` does it (execute/adapters/dbt_adapter.py): a connect failure is
    not a warehouse rejection, and it gets the ERR-WAREHOUSE-CONNECTION sentence
    rather than a bare driver string. Holding that failure in ``open_error``
    rather than returning on the spot is what keeps it: ``connection_named``
    releases on *every* exit, and dbt-bigquery's release dereferences the handle
    a failed open left as None, so the AttributeError it raises would otherwise
    replace a verdict already reached — including the value of a plain ``return``
    from inside the block.

    Args:
        source_config: Typed SourceConfig instance (DuckDBSourceConfig,
            PostgresSourceConfig, etc.).

    Returns:
        (True, "Connection successful") on success.
        (False, "<error message>") on any failure — driver missing, bad creds,
        network unreachable, unsupported type, etc.
    """
    from dbt_charts.core.execute.adapters.base import connection_failure_message
    from dbt_charts.core.execute.adapters.dbt_adapter_factory import build_adapter

    creds = source_config.model_dump(
        by_alias=True, exclude_unset=True, exclude_none=True
    )
    open_error: Exception | None = None
    try:
        adapter = build_adapter(creds)
        with adapter.connection_named("test"):
            try:
                _ = adapter.connections.get_thread_connection().handle
            except Exception as e:  # noqa: BLE001 — any driver's connect failure
                open_error = e
            else:
                adapter.execute("SELECT 1", auto_begin=False, fetch=True)
    except Exception as e:  # noqa: BLE001 — driver-level errors become messages
        if open_error is None:
            return False, str(e) or type(e).__name__
    if open_error is not None:
        return False, connection_failure_message(source_config.type, open_error)
    return True, "Connection successful"


def bulk_schema_for_config(source_config: SourceConfig) -> SchemaTree:
    """Return source_config's whole schema tree from a single warehouse query.

    Connection-scoped sibling of ``bulk_schema`` — same SQL builder and
    row→tree parser, but keyed by a bare ``SourceConfig`` (via ``build_adapter``,
    the ``test_connection`` pattern) instead of an ``AdapterRegistry``. For
    hosts holding a connection's credentials with no project/registry, such
    as Cloud's per-connection schema profile.

    Fails only through the same narrow contract as ``bulk_schema``:

      * ``NotImplementedError`` — the dialect has no bulk-introspection form
        (e.g. BigQuery without a region qualifier).
      * ``RuntimeError`` — the query returned or raised an error (any driver
        exception is normalized into this), or the result was truncated by the
        ``execution.max_rows``/``DCT_MAX_ROWS_CEILING`` ceiling — a partial
        tree would silently under-count, so it raises instead.
    """
    # Function-local like every other dbt_charts import in this module: keeping
    # the module itself leaf-light is what lets `dbt_charts.cli.main` import
    # without eagerly loading core.compile (pinned by test_lazy_imports).
    from dbt_charts.core.dialects import get_dialect
    from dbt_charts.core.execute.adapters.base import (
        apply_row_limit_truncation,
        resolve_effective_row_limit,
    )
    from dbt_charts.core.execute.adapters.dbt_adapter_factory import build_adapter
    from dbt_charts.core.inspect.bulk_schema import (
        bulk_schema_scope,
        parse_bulk_schema_rows,
    )

    creds = source_config.model_dump(
        by_alias=True, exclude_unset=True, exclude_none=True
    )
    source_type = str(creds.get("type"))
    dialect = get_dialect(source_type)
    sql = dialect.bulk_schema_sql(bulk_schema_scope(source_type, creds))

    # Same execution.max_rows/DCT_MAX_ROWS_CEILING guard as the registry path:
    # bound the driver fetch where the cursor supports it, post-slice otherwise,
    # and raise rather than return a silently partial tree.
    row_limit = resolve_effective_row_limit(None)
    driver_limit = (
        row_limit.fetch_limit if dialect.cursor_supports_driver_limit else None
    )

    try:
        # No macro context: this runs plain metadata SQL on every connection
        # save in a long-lived worker, and register_macros' bootstrap closure
        # keeps the adapter (and its warehouse session) alive until a gen-GC
        # sweep.
        adapter = build_adapter(creds, register_macros=False)
        with adapter.connection_named("bulk_schema_for_config"):
            _response, table = adapter.execute(
                sql, auto_begin=False, fetch=True, limit=driver_limit
            )
        rows, truncated_reason = apply_row_limit_truncation(list(table.rows), row_limit)
        tree = parse_bulk_schema_rows(
            dict(zip(table.column_names, row, strict=True)) for row in rows
        )
    except (
        Exception  # noqa: BLE001 — normalize driver errors to RuntimeError
    ) as e:
        raise RuntimeError(f"bulk_schema_for_config query failed: {e}") from e
    if truncated_reason is not None:
        raise RuntimeError(
            f"bulk_schema_for_config query for {source_type!r} was truncated to "
            f"{row_limit.effective_limit} rows by {truncated_reason!r} — schema "
            "tree is incomplete. Raise execution.max_rows or "
            "DCT_MAX_ROWS_CEILING above the source's column count to fix this."
        )
    return tree


def probe_relation_readability(
    source_config: SourceConfig, relation: Relation
) -> tuple[bool, str]:
    """Verify *relation* is readable with *source_config*'s credential.

    ``SELECT * FROM <relation> LIMIT 0`` — a live probe. Portable across every
    supported dialect and truthful regardless of how the grant was applied (dbt,
    Terraform, or by hand), since it asks the warehouse directly rather than
    reading declared config. Zero rows are ever fetched or returned; only
    whether the statement itself was accepted.

    Args:
        source_config: The connection's own credential.
        relation: One relation from ``inspect.relations.relations_read_by`` —
            ``database``/``schema`` may be None when the query didn't qualify it.

    Returns:
        (True, "") when the relation is readable.
        (False, "<error message>") on any failure — missing grant, missing
        relation, unreachable warehouse. Never raises: a caller probes many
        relations in a loop and one failure must not abort the rest.
    """
    from dbt_charts.core.execute.adapters.dbt_adapter_factory import build_adapter

    creds = source_config.model_dump(
        by_alias=True, exclude_unset=True, exclude_none=True
    )
    try:
        adapter = build_adapter(creds)
        qualified = ".".join(
            adapter.quote(part)
            for part in (relation.database, relation.schema, relation.name)
            if part
        )
        with adapter.connection_named("probe_relation_readability"):
            adapter.execute(
                f"SELECT * FROM {qualified} LIMIT 0", auto_begin=False, fetch=True
            )
        return True, ""
    except (
        Exception  # noqa: BLE001
    ) as e:  # broad on purpose — surfaces driver-level errors as messages
        return False, str(e) or type(e).__name__
