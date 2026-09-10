"""Tests for schema_names.py drift and name-list exclusions.

TDD: written before the fix existed. The drift test regenerates the module
in memory and compares it to the committed source.
"""

from __future__ import annotations

import importlib.util
import typing

from ...._paths import DBT_CHARTS_DIR, DBT_CHARTS_PKG_DIR

_SCRIPT_PATH = DBT_CHARTS_DIR / "scripts" / "generate_schema_names.py"
_MODULE_PATH = DBT_CHARTS_PKG_DIR / "core" / "compile" / "models" / "schema_names.py"


def test_schema_names_matches_generator_output(tmp_path, monkeypatch):
    """Committed schema_names.py must match fresh regeneration."""
    committed = _MODULE_PATH.read_text(encoding="utf-8")

    fake_out = tmp_path / "schema_names.py"
    spec = importlib.util.spec_from_file_location("generate_schema_names", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_OUT", fake_out)
    mod.main()

    assert fake_out.read_text(encoding="utf-8") == committed, (
        "schema_names.py is stale. Re-run: just generate-schema-names"
    )


def test_generate_script_writes_to_committed_module_path():
    spec = importlib.util.spec_from_file_location("generate_schema_names", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._OUT == _MODULE_PATH


def test_theme_name_excludes_private_and_diagnostics():
    from dbt_charts.core.compile.models.schema_names import ThemeName

    names = typing.get_args(ThemeName)
    assert not any(n.startswith("_") for n in names)
    assert not any(n.startswith("diagnostics-") for n in names)
    assert "clarity" in names


def test_palette_name_excludes_hard_fail_and_warn_alias_names():
    from dbt_charts.core.compile.models.schema_names import PaletteName
    from dbt_charts.core.compile.resolve.style.palette import (
        _HARD_FAIL_NAMES,
        _WARN_ALIASES,
    )

    names = set(typing.get_args(PaletteName))
    assert not (names & _HARD_FAIL_NAMES)
    assert not (names & set(_WARN_ALIASES))


def test_stops_palette_name_holds_only_names_that_resolve_to_stops():
    """`palette()` raises `ToneAsPaletteError` on every tone name, so a
    `palette:` field naming one parses and dies at resolve with
    ERR-PALETTE-UNKNOWN. Offering them was a completion whose every use breaks
    the board — and the design panel turns a completion into a control.

    `PaletteName` keeps the whole index: `style.palettes` binds roles to color
    sources, and `_base.yaml` binds `info: info`.
    """
    from dbt_charts.core.compile.models.schema_names import (
        PaletteName,
        StopsPaletteName,
    )
    from dbt_charts.core.compile.resolve.style.palette import list_palettes, palette

    tones = set(list_palettes("tone"))
    names = set(typing.get_args(StopsPaletteName))
    assert not (names & tones)
    assert set(typing.get_args(PaletteName)) - names == tones
    for name in names:
        palette(name)


def test_scale_palette_name_excludes_hard_fail_and_warn_alias_names():
    """VEGA_SCHEME_NAMES contains "rainbow", which is also a _HARD_FAIL_NAMES
    anti-pattern — the union must not resurrect it into ScalePaletteName."""
    from dbt_charts.core.compile.models.schema_names import ScalePaletteName
    from dbt_charts.core.compile.resolve.style.palette import (
        _HARD_FAIL_NAMES,
        _WARN_ALIASES,
    )

    names = set(typing.get_args(ScalePaletteName))
    assert not (names & _HARD_FAIL_NAMES), (
        f"hard-fail anti-pattern name(s) leaked into ScalePaletteName: {names & _HARD_FAIL_NAMES}"
    )
    assert not (names & set(_WARN_ALIASES))


def test_scale_palette_name_is_union_of_palettes_and_vega_schemes_minus_excluded():
    from dbt_charts.core.compile.models.primitives import VEGA_SCHEME_NAMES
    from dbt_charts.core.compile.models.schema_names import (
        ScalePaletteName,
        StopsPaletteName,
    )
    from dbt_charts.core.compile.resolve.style.palette import (
        _HARD_FAIL_NAMES,
        _WARN_ALIASES,
    )

    names = set(typing.get_args(ScalePaletteName))
    excluded = _HARD_FAIL_NAMES | set(_WARN_ALIASES)
    expected = (set(typing.get_args(StopsPaletteName)) | VEGA_SCHEME_NAMES) - excluded
    assert names == expected
