"""Tests for the max_result_bytes ceiling resolver: config value clamped to
an optional DCT_MAX_RESULT_BYTES_CEILING deployment ceiling.

Precedence mirrors resolve_html_policy_ceiling: a ceiling env var can only
lower the effective value, never raise it above the project config value.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import (
    get_execution_config,
    reset_config,
    resolve_max_result_bytes,
    resolve_max_result_bytes_ceiling,
)


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    yield
    reset_config()


class TestResolveMaxResultBytesCeiling:
    def test_no_env_var_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DCT_MAX_RESULT_BYTES_CEILING", raising=False)
        assert resolve_max_result_bytes_ceiling() is None

    def test_env_var_returns_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_MAX_RESULT_BYTES_CEILING", "1024")
        assert resolve_max_result_bytes_ceiling() == 1024

    def test_negative_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_MAX_RESULT_BYTES_CEILING", "-1")
        with pytest.raises(ValueError, match="DCT_MAX_RESULT_BYTES_CEILING"):
            resolve_max_result_bytes_ceiling()

    def test_zero_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_MAX_RESULT_BYTES_CEILING", "0")
        with pytest.raises(ValueError, match="DCT_MAX_RESULT_BYTES_CEILING"):
            resolve_max_result_bytes_ceiling()

    def test_non_integer_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DCT_MAX_RESULT_BYTES_CEILING", "not-a-number")
        with pytest.raises(ValueError, match="DCT_MAX_RESULT_BYTES_CEILING"):
            resolve_max_result_bytes_ceiling()


class TestResolveMaxResultBytes:
    def test_no_ceiling_returns_config_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DCT_MAX_RESULT_BYTES_CEILING", raising=False)
        assert resolve_max_result_bytes() == get_execution_config().max_result_bytes

    def test_ceiling_below_config_clamps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config_value = get_execution_config().max_result_bytes
        tighter = config_value - 1
        monkeypatch.setenv("DCT_MAX_RESULT_BYTES_CEILING", str(tighter))
        assert resolve_max_result_bytes() == tighter

    def test_ceiling_above_config_does_not_raise_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_value = get_execution_config().max_result_bytes
        looser = config_value + 1000
        monkeypatch.setenv("DCT_MAX_RESULT_BYTES_CEILING", str(looser))
        assert resolve_max_result_bytes() == config_value
