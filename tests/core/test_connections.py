"""The public dbt_charts.core connection API: discovery helpers, probes,
bulk schema, and test_connection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dbt_charts.core.compile.models.source import (
    BigQuerySourceConfig,
    DuckDBSourceConfig,
)
from dbt_charts.core.connections import (
    build_bigquery_client,
    bulk_schema_for_config,
    dataset_location,
    list_datasets,
    probe_relation_readability,
)
from dbt_charts.core.inspect.relations import Relation


@dataclass
class _StubDataset:
    dataset_id: str
    location: str


class _StubClient:
    """Stands in for google.cloud.bigquery.Client."""

    def __init__(self, datasets: list[_StubDataset]) -> None:
        self._datasets = datasets
        self.got: list[str] = []

    def list_datasets(self) -> list[_StubDataset]:
        return self._datasets

    def get_dataset(self, dataset_id: str) -> _StubDataset:
        self.got.append(dataset_id)
        for ds in self._datasets:
            if ds.dataset_id == dataset_id:
                return ds
        raise KeyError(dataset_id)


def _bq_config(dataset: str = "") -> BigQuerySourceConfig:
    return BigQuerySourceConfig(
        type="bigquery",
        project="my-project",
        dataset=dataset,
        keyfile_json={"type": "service_account", "project_id": "my-project"},
    )


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch) -> _StubClient:
    client = _StubClient(
        [_StubDataset("analytics", "us-east4"), _StubDataset("raw", "EU")]
    )

    def _build(*_args: Any, **_kwargs: Any) -> _StubClient:
        return client

    monkeypatch.setattr("dbt_charts.core.connections.build_bigquery_client", _build)
    return client


def test_list_datasets_returns_names(stub_client: _StubClient) -> None:
    """Discovery works with no dataset set — that is the whole point of it."""
    assert list_datasets(_bq_config()) == ["analytics", "raw"]


def test_dataset_location_reads_the_chosen_dataset(stub_client: _StubClient) -> None:
    assert dataset_location(_bq_config("raw")) == "EU"
    # Exactly one lookup: resolving every listed dataset would be an N+1.
    assert stub_client.got == ["raw"]


def test_dataset_location_requires_a_dataset() -> None:
    """No dataset is a caller bug, not a None-returning soft path."""
    with pytest.raises(ValueError, match="dataset"):
        dataset_location(_bq_config())


def test_dataset_location_rejects_non_bigquery() -> None:
    """No other warehouse has a dataset location — asking for one is a caller bug."""
    cfg = DuckDBSourceConfig(type="duckdb", path=":memory:")
    with pytest.raises(ValueError, match="BigQuery"):
        dataset_location(cfg)


def test_list_datasets_rejects_non_bigquery() -> None:
    cfg = DuckDBSourceConfig(type="duckdb", path=":memory:")
    with pytest.raises(ValueError, match="BigQuery"):
        list_datasets(cfg)


def test_missing_bigquery_extra_names_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing optional dep must say how to fix it, not raise a bare ImportError."""

    def _no_module(_name: str) -> Any:
        raise ImportError("No module named 'google.cloud.bigquery'")

    monkeypatch.setattr("dbt_charts.core.connections.import_bigquery", _no_module)
    with pytest.raises(ImportError, match="bigquery"):
        list_datasets(_bq_config())


# ── build_bigquery_client: the one home for BigQuery client construction ─────


def test_missing_google_cloud_raises_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_import(name: str) -> Any:
        if name == "google.cloud.bigquery":
            raise ModuleNotFoundError(
                "No module named 'google.cloud'", name="google.cloud"
            )
        raise AssertionError(f"unexpected module import: {name}")

    monkeypatch.setattr("importlib.import_module", _fake_import)
    with pytest.raises(ImportError, match=r"dbt-charts\[bigquery\]"):
        build_bigquery_client("my-project")


def test_missing_google_oauth_raises_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_import(name: str) -> Any:
        if name == "google.cloud.bigquery":
            return SimpleNamespace(Client=lambda **_kwargs: object())
        if name == "google.oauth2.service_account":
            raise ModuleNotFoundError(
                "No module named 'google.oauth2'", name="google.oauth2"
            )
        raise AssertionError(f"unexpected module import: {name}")

    monkeypatch.setattr("importlib.import_module", _fake_import)
    with pytest.raises(ImportError, match=r"dbt-charts\[bigquery\]"):
        build_bigquery_client("my-project", {"type": "service_account"})


# ── probe_relation_readability: the D-03 per-relation LIMIT 0 probe ──────────


def _duckdb_with_table(tmp_path: Path, schema: str, table: str) -> DuckDBSourceConfig:
    import duckdb

    db_path = tmp_path / "probe.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute(f"CREATE SCHEMA {schema}")
    con.execute(f"CREATE TABLE {schema}.{table} (id INTEGER)")
    con.close()
    return DuckDBSourceConfig(type="duckdb", path=str(db_path))


def test_a_readable_relation_probes_successfully(tmp_path: Path) -> None:
    source_config = _duckdb_with_table(tmp_path, "analytics", "orders")
    success, message = probe_relation_readability(
        source_config, Relation(name="orders", schema="analytics")
    )
    assert success is True
    assert message == ""


def test_an_unreadable_relation_reports_the_failure(tmp_path: Path) -> None:
    source_config = _duckdb_with_table(tmp_path, "analytics", "orders")
    success, message = probe_relation_readability(
        source_config, Relation(name="missing_table", schema="analytics")
    )
    assert success is False
    assert message


def test_probe_never_raises_on_a_driver_error(tmp_path: Path) -> None:
    """The probe reports failure through the return value, like test_connection —
    never an unhandled exception, since a caller runs this per relation in a loop."""
    source_config = _duckdb_with_table(tmp_path, "analytics", "orders")
    success, _message = probe_relation_readability(
        source_config, Relation(name="nope", schema="does_not_exist")
    )
    assert success is False


# ── bulk_schema_for_config: the connection-scoped bulk-schema seam ───────────


def _duckdb_with_two_schemas(tmp_path: Path) -> DuckDBSourceConfig:
    import duckdb

    db_path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE SCHEMA sales")
        con.execute("CREATE SCHEMA marketing")
        con.execute("CREATE TABLE sales.orders (id INTEGER, amount DECIMAL(10,2))")
        con.execute("CREATE TABLE marketing.campaigns (id INTEGER, channel VARCHAR)")
    finally:
        con.close()
    return DuckDBSourceConfig(type="duckdb", path=str(db_path))


def test_bulk_schema_for_config_returns_the_schema_tree(tmp_path: Path) -> None:
    source_config = _duckdb_with_two_schemas(tmp_path)
    tree = bulk_schema_for_config(source_config)

    assert set(tree) >= {"sales", "marketing"}
    assert set(tree["sales"]) == {"orders"}
    assert list(tree["sales"]["orders"]) == ["id", "amount"]
    assert set(tree["marketing"]["campaigns"]) == {"id", "channel"}


def test_bulk_schema_for_config_propagates_not_implemented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dialect with no bulk-introspection form must not be swallowed into a
    RuntimeError — the caller needs to distinguish 'unsupported' from 'failed'."""
    source_config = _duckdb_with_two_schemas(tmp_path)

    class _NoBulkFormDialect:
        def bulk_schema_sql(self, scope: str = "") -> str:
            raise NotImplementedError("no bulk-introspection form")

    monkeypatch.setattr(
        "dbt_charts.core.dialects.get_dialect", lambda _type: _NoBulkFormDialect()
    )
    with pytest.raises(NotImplementedError):
        bulk_schema_for_config(source_config)


def test_bulk_schema_for_config_normalizes_driver_errors_to_runtime_error(
    tmp_path: Path,
) -> None:
    source_config = DuckDBSourceConfig(
        type="duckdb", path=str(tmp_path / "missing_dir" / "wh.duckdb")
    )
    # match pins the normalized wrapper: a bare RuntimeError would also accept
    # NotImplementedError (its subclass) — the very case the contract separates.
    with pytest.raises(RuntimeError, match="bulk_schema_for_config query failed"):
        bulk_schema_for_config(source_config)


def test_bulk_schema_for_config_scopes_bigquery_to_the_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scope must survive the SourceConfig→model_dump→bulk_schema_scope
    hop: if the dump ever stops carrying `location`, BigQuery's dialect raises
    NotImplementedError and every BigQuery connection profiles as an error."""
    from types import SimpleNamespace

    from dbt_charts.core.compile.models.source import BigQuerySourceConfig

    captured: dict[str, str] = {}

    class _CapturingAdapter:
        def connection_named(self, name: str):
            from contextlib import nullcontext

            return nullcontext()

        def execute(self, sql: str, **kwargs: object):
            captured["sql"] = sql
            table = SimpleNamespace(
                column_names=["table_schema", "table_name", "column_name", "data_type"],
                rows=[],
            )
            return None, table

    monkeypatch.setattr(
        "dbt_charts.core.execute.adapters.dbt_adapter_factory.build_adapter",
        lambda creds, **kwargs: _CapturingAdapter(),
    )
    tree = bulk_schema_for_config(
        BigQuerySourceConfig(type="bigquery", project="p", dataset="d", location="US")
    )
    assert tree == {}
    assert "`region-us`" in captured["sql"]


def test_bulk_schema_for_config_raises_on_max_rows_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same guard as bulk_schema: a truncated catalogue must raise loudly, and
    the fetch itself is bounded — never the whole warehouse into memory."""
    monkeypatch.setenv("DCT_MAX_ROWS_CEILING", "1")
    source_config = _duckdb_with_two_schemas(tmp_path)

    with pytest.raises(RuntimeError, match="truncated"):
        bulk_schema_for_config(source_config)


# --- test_connection: the cleanup crash must not replace the real cause ------
#
# dbt-bigquery's BigQueryConnectionManager.close is a bare
# `connection.handle.close()`. A credential that fails to parse leaves
# `handle` None, so the release the `connection_named` context manager runs on
# every exit raises AttributeError -- and that AttributeError is what a caller
# sees unless test_connection holds on to the open failure itself.

_PEM_FAILURE = (
    "Database Error\n  Unable to load PEM file. See "
    "https://cryptography.io/en/latest/faq/ for more details. "
    "InvalidData(InvalidPadding)"
)

# A private key that fails PEM parsing before any network call is attempted.
_UNPARSEABLE_KEYFILE_JSON = {
    "type": "service_account",
    "project_id": "my-project",
    "private_key_id": "abc123",
    "private_key": "-----BEGIN PRIVATE KEY-----\nNOTAREALKEY\n-----END PRIVATE KEY-----\n",
    "client_email": "svc@my-project.iam.gserviceaccount.com",
    "client_id": "1",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}


class _UnopenableConnection:
    """dbt's Connection after a failed open: no handle, and asking for one raises."""

    def __init__(self, open_error: Exception) -> None:
        self._open_error = open_error

    @property
    def handle(self) -> Any:
        raise self._open_error


class _CleanupCrashingAdapter:
    """dbt-bigquery's shape on a credential that will not parse."""

    def __init__(self, open_error: Exception) -> None:
        self._open_error = open_error
        self.connections = SimpleNamespace(
            get_thread_connection=lambda: _UnopenableConnection(open_error)
        )

    @contextmanager
    def connection_named(self, name: str) -> Iterator[None]:
        try:
            yield
        finally:
            # BigQueryConnectionManager.close, verbatim in effect.
            crash = AttributeError("'NoneType' object has no attribute 'close'")
            crash.__context__ = self._open_error
            raise crash

    def execute(self, sql: str, **kwargs: Any) -> None:
        raise self._open_error


def test_test_connection_reports_the_credential_error_not_the_cleanup_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    open_error = RuntimeError(_PEM_FAILURE)
    monkeypatch.setattr(
        "dbt_charts.core.execute.adapters.dbt_adapter_factory.build_adapter",
        lambda creds, **kwargs: _CleanupCrashingAdapter(open_error),
    )

    from dbt_charts.core.connections import test_connection

    ok, message = test_connection(_bq_config("analytics"))

    assert ok is False
    assert "'NoneType' object has no attribute 'close'" not in message
    assert "Unable to load PEM file" in message
    assert message.startswith("bigquery: Could not open the warehouse:")


def test_test_connection_names_an_unparseable_bigquery_key() -> None:
    """The whole path, against the real dbt-bigquery adapter.

    Offline: PEM parsing fails while the credential is being built, long before
    anything would reach Google.
    """
    from dbt_charts.core.connections import test_connection

    ok, message = test_connection(
        BigQuerySourceConfig(
            type="bigquery",
            project="my-project",
            dataset="analytics",
            keyfile_json=_UNPARSEABLE_KEYFILE_JSON,
        )
    )

    assert ok is False
    assert "'NoneType' object has no attribute 'close'" not in message
    assert "PEM" in message
    assert "Could not open the warehouse" in message
