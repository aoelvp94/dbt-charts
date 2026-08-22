"""Public dft-core connection API.

Exports test_connection(source_config) → (bool, str) plus the BigQuery
discovery helpers hosts use to fill a connection form: build_bigquery_client,
list_datasets, dataset_location.

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

    Constructs a fresh adapter, pings with SELECT 1, and lets GC clean up
    when the local reference drops at function exit. The temp target dir is
    removed by the weakref.finalize registered in build_adapter.

    Args:
        source_config: Typed SourceConfig instance (DuckDBSourceConfig,
            PostgresSourceConfig, etc.).

    Returns:
        (True, "Connection successful") on success.
        (False, "<error message>") on any failure — driver missing, bad creds,
        network unreachable, unsupported type, etc.
    """
    from dbt_charts.core.execute.adapters.dbt_adapter_factory import build_adapter

    creds = source_config.model_dump(
        by_alias=True, exclude_unset=True, exclude_none=True
    )
    try:
        adapter = build_adapter(creds)
        with adapter.connection_named("test"):
            adapter.execute("SELECT 1", auto_begin=False, fetch=True)
        return True, "Connection successful"
    except (
        Exception  # noqa: BLE001
    ) as e:  # broad on purpose — surfaces driver-level errors as messages
        return False, str(e) or type(e).__name__
