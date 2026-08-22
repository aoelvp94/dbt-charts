"""Tests for the max_rows ceiling resolver: config value clamped to an
optional DCT_MAX_ROWS_CEILING deployment ceiling.

Precedence mirrors resolve_html_policy_ceiling: a ceiling env var can only
lower the effective value, never raise it above the project config value.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import (
    get_execution_config,
    reset_config,
    resolve_max_rows,
    resolve_max_rows_ceiling,
)


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    yield
    reset_config()


class TestResolveMaxRowsCeiling:
    def test_no_env_var_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DCT_MAX_ROWS_CEILING", raising=False)
        assert resolve_max_rows_ceiling() is None

    def test_env_var_returns_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_MAX_ROWS_CEILING", "500")
        assert resolve_max_rows_ceiling() == 500

    def test_negative_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A silent min(config, -1) == -1 pushes LIMIT 0 and slices rows[:-1] —
        # every chart on the board renders empty with no clear error.
        monkeypatch.setenv("DCT_MAX_ROWS_CEILING", "-1")
        with pytest.raises(ValueError, match="DCT_MAX_ROWS_CEILING"):
            resolve_max_rows_ceiling()

    def test_zero_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_MAX_ROWS_CEILING", "0")
        with pytest.raises(ValueError, match="DCT_MAX_ROWS_CEILING"):
            resolve_max_rows_ceiling()

    def test_non_integer_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_MAX_ROWS_CEILING", "not-a-number")
        with pytest.raises(ValueError, match="DCT_MAX_ROWS_CEILING"):
            resolve_max_rows_ceiling()


class TestResolveMaxRows:
    def test_no_ceiling_returns_config_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DCT_MAX_ROWS_CEILING", raising=False)
        assert resolve_max_rows() == get_execution_config().max_rows

    def test_ceiling_below_config_clamps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config_value = get_execution_config().max_rows
        tighter = config_value - 1
        monkeypatch.setenv("DCT_MAX_ROWS_CEILING", str(tighter))
        assert resolve_max_rows() == tighter

    def test_ceiling_above_config_does_not_raise_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_value = get_execution_config().max_rows
        looser = config_value + 1000
        monkeypatch.setenv("DCT_MAX_ROWS_CEILING", str(looser))
        assert resolve_max_rows() == config_value
