"""Tests for the defaults/ directory layout.

Built-in config assets must live under the package ``core/defaults/`` tree —
not under ``compile/``. This test file verifies the directory structure and
that ``config.py`` resolves paths from the new location.
"""

from __future__ import annotations

from dbt_charts.core.compile.config import (
    _default_config_path,
    _defaults_dir,
)

from .._paths import DBT_CHARTS_PKG_DIR

_CORE_DIR = DBT_CHARTS_PKG_DIR / "core"


def test_defaults_dir_exists():
    """The dedicated defaults/ directory must exist under core/."""
    assert _defaults_dir.exists(), f"Missing: {_defaults_dir}"
    assert _defaults_dir.is_dir()


def test_defaults_dir_is_under_core_not_compile():
    """defaults/ must be a sibling of compile/, not inside it."""
    assert _defaults_dir.parent.name == "core"
    assert "compile" not in _defaults_dir.relative_to(_CORE_DIR).parts


def test_default_config_lives_in_defaults():
    """default_config.yml must be inside defaults/."""
    assert _default_config_path.parent == _defaults_dir
    assert _default_config_path.exists()


def test_unified_themes_dir_lives_in_defaults():
    """themes/ (unified) must be inside defaults/."""
    from dbt_charts.core.compile.config import _built_in_unified_theme_dir

    assert _built_in_unified_theme_dir.parent == _defaults_dir
    assert _built_in_unified_theme_dir.exists()
    assert any(_built_in_unified_theme_dir.glob("*.yaml"))
