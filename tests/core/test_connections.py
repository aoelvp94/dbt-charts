"""BigQuery discovery helpers on the public dft-core connection API."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from dbt_charts.core.compile.models.source import (
    BigQuerySourceConfig,
    DuckDBSourceConfig,
)
from dbt_charts.core.connections import (
    build_bigquery_client,
    dataset_location,
    list_datasets,
)


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
