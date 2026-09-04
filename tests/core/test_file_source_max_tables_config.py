"""Tests for the file_source_max_tables ceiling resolver: config value
clamped to an optional DCT_FILE_SOURCE_MAX_TABLES_CEILING deployment ceiling.

Precedence mirrors resolve_max_result_bytes: a ceiling env var can only
lower the effective value, never raise it above the project config value.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import (
    get_execution_config,
    reset_config,
    resolve_file_source_max_tables,
    resolve_file_source_max_tables_ceiling,
)


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    yield
    reset_config()


class TestResolveFileSourceMaxTablesCeiling:
    def test_no_env_var_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", raising=False)
        assert resolve_file_source_max_tables_ceiling() is None

    def test_env_var_returns_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", "10")
        assert resolve_file_source_max_tables_ceiling() == 10

    def test_negative_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", "-1")
        with pytest.raises(ValueError, match="DCT_FILE_SOURCE_MAX_TABLES_CEILING"):
            resolve_file_source_max_tables_ceiling()

    def test_zero_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", "0")
        with pytest.raises(ValueError, match="DCT_FILE_SOURCE_MAX_TABLES_CEILING"):
            resolve_file_source_max_tables_ceiling()

    def test_non_integer_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", "not-a-number")
        with pytest.raises(ValueError, match="DCT_FILE_SOURCE_MAX_TABLES_CEILING"):
            resolve_file_source_max_tables_ceiling()


class TestResolveFileSourceMaxTables:
    def test_no_ceiling_returns_config_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", raising=False)
        assert (
            resolve_file_source_max_tables()
            == get_execution_config().file_source_max_tables
        )

    def test_ceiling_below_config_clamps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config_value = get_execution_config().file_source_max_tables
        tighter = config_value - 1
        monkeypatch.setenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", str(tighter))
        assert resolve_file_source_max_tables() == tighter

    def test_ceiling_above_config_does_not_raise_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_value = get_execution_config().file_source_max_tables
        looser = config_value + 1000
        monkeypatch.setenv("DCT_FILE_SOURCE_MAX_TABLES_CEILING", str(looser))
        assert resolve_file_source_max_tables() == config_value
