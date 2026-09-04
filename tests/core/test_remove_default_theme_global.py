"""Regression tests: global-mutable default-theme pattern is gone.

Failing before the fix:
- set_default_theme_name no longer exported from config
- get_default_theme_name() reads DCT_DEFAULT_THEME env var directly
- dbt_charts.yml: theme: raises a ValidationError (no longer stripped)
- apply_default_theme no longer exists in bootstrap
"""

import pytest


def test_set_default_theme_name_not_exported() -> None:
    """set_default_theme_name must not exist — the global mutable is deleted."""
    from dbt_charts.core.compile import config

    assert not hasattr(config, "set_default_theme_name")


def test_get_default_theme_name_reads_dct_default_theme_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_default_theme_name() reads DCT_DEFAULT_THEME from env at call time."""
    monkeypatch.setenv("DCT_DEFAULT_THEME", "neon")
    from dbt_charts.core.compile.config import get_default_theme_name

    assert get_default_theme_name() == "neon"


def test_get_default_theme_name_returns_constant_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_default_theme_name() falls back to the shipped constant when env unset."""
    monkeypatch.delenv("DCT_DEFAULT_THEME", raising=False)
    from dbt_charts.core.compile.config import (
        SHIPPED_DEFAULT_THEME_NAME,
        get_default_theme_name,
    )

    assert get_default_theme_name() == SHIPPED_DEFAULT_THEME_NAME


def test_dbt_charts_yml_theme_key_raises_validation_error(
    tmp_path, local_project
) -> None:  # type: ignore[no-untyped-def]
    """dbt_charts.yml: theme: is no longer accepted — raises pydantic ValidationError."""
    from pydantic import ValidationError

    from dbt_charts.core.compile.config import load_config, reset_config

    (tmp_path / "dbt_charts.yml").write_text("theme: stark\n")
    reset_config()
    try:
        with pytest.raises(ValidationError):
            load_config(local_project(tmp_path))
    finally:
        reset_config()


def test_apply_default_theme_not_in_bootstrap() -> None:
    """apply_default_theme no longer exists — bootstrap module is deleted."""
    with pytest.raises(ImportError):
        from dbt_charts.core.serve import bootstrap  # noqa: F401
