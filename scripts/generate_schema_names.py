#!/usr/bin/env python3
"""Generate schema_names.py — closed name lists baked in as Literal aliases.

Themes, palettes and format aliases are closed sets fixed at build time (read
from YAML packaged inside dbt_charts), but nothing about them reaches the
authored schema. This script snapshots them into a committed Python module so the
JSON Schema generator can introspect a real Literal type instead of a
hand-written enum list.

Re-run after adding/removing a theme or palette YAML file, or an entry in
PREDEFINED_SPECS (predefined_formats.py):

    just generate-schema-names

The drift test (test_schema_names.py::test_schema_names_matches_generator_output)
fails when the committed module diverges from a fresh regeneration.
"""

from __future__ import annotations

import sys
from pathlib import Path

# parents[1] is the dataface package root in both monorepo (dataface/scripts/)
# and standalone export (scripts/ after Copybara core.move("dataface", "")).
_DBT_CHARTS_DIR = Path(__file__).resolve().parents[1]
_SRC = _DBT_CHARTS_DIR / "src"
_OUT = _SRC / "dbt_charts" / "core" / "compile" / "models" / "schema_names.py"

sys.path.insert(0, str(_SRC))


def _literal_block(var_name: str, values: list[str]) -> str:
    items = ",\n".join(f'    "{v}"' for v in values)
    return f"{var_name} = Literal[\n{items},\n]\n"


def main() -> None:
    from dbt_charts.core.compile.config import list_built_in_themes
    from dbt_charts.core.compile.models.primitives import VEGA_SCHEME_NAMES
    from dbt_charts.core.compile.resolve.style.palette import (
        _HARD_FAIL_NAMES,
        _WARN_ALIASES,
        list_palettes,
    )
    from dbt_charts.core.text.predefined_formats import (
        PREDEFINED_SPECS,
        PREDEFINED_TIME_SPECS,
    )

    theme_names = sorted(
        name
        for name in list_built_in_themes()
        if not name.startswith("_") and not name.startswith("diagnostics-")
    )
    # Engine-owned: predefined number + time format names offered as completions.
    # Native formatters (Python-only, Vega-invalid) live in PREDEFINED_NATIVE and
    # are intentionally absent from PREDEFINED_SPECS and PREDEFINED_TIME_SPECS, so
    # the union excludes them without an explicit subtraction.
    format_aliases = sorted(set(PREDEFINED_SPECS) | set(PREDEFINED_TIME_SPECS))
    palette_names = sorted(list_palettes())
    # VEGA_SCHEME_NAMES includes "rainbow", which is also a _HARD_FAIL_NAMES
    # anti-pattern (perceptually non-uniform) — offering it in scale-palette
    # completion would promote the exact name the project hard-fails on.
    excluded_scheme_names = _HARD_FAIL_NAMES | set(_WARN_ALIASES)
    scale_palette_names = sorted(
        {*palette_names, *VEGA_SCHEME_NAMES} - excluded_scheme_names
    )

    content = (
        '"""Generated. Do not edit by hand — run `just generate-schema-names`.\n\n'
        "Source: list_built_in_themes() (compile/config.py), PREDEFINED_SPECS\n"
        "(text/predefined_formats.py), list_palettes() (compile/resolve/style/palette.py),\n"
        "VEGA_SCHEME_NAMES (compile/models/primitives.py).\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "from typing import Literal\n\n"
        "# Built-in theme stems offered as `theme:`/`extends:` value completions.\n"
        "# Excludes the private `_base` completeness floor and diagnostic-only themes.\n"
        f"{_literal_block('ThemeName', theme_names)}\n"
        "# Named dbt charts palettes (sequential, diverging, categorical, scaffold, tone).\n"
        "# Excludes hard-fail anti-pattern names and warn-alias migration names — neither\n"
        "# is a real palette YAML entry, so list_palettes() already omits them.\n"
        f"{_literal_block('PaletteName', palette_names)}\n"
        "# PaletteName union Vega/Vega-Lite scheme names — the only closed set\n"
        "# ScaleTargetConfig.palette accepts (it also forwards Vega scheme names\n"
        "# straight through to VL's scale.scheme). Hard-fail and warn-alias scheme\n"
        "# names (e.g. 'rainbow') are excluded — see _HARD_FAIL_NAMES/_WARN_ALIASES.\n"
        f"{_literal_block('ScalePaletteName', scale_palette_names)}\n"
        "# Engine-predefined format names (PredefinedNumberFormat + PredefinedTimeFormat).\n"
        "# A predefined name resolves to a d3 spec or native formatter at render time;\n"
        "# a raw d3 spec or user style.formats alias is equally legal, so every field\n"
        "# carrying this reads `FormatAlias | str` — the Literal names the shortcuts,\n"
        "# it does not close the set.\n"
        f"{_literal_block('FormatAlias', format_aliases)}"
    )
    _OUT.write_text(content, encoding="utf-8")
    try:
        out_display = _OUT.relative_to(_DBT_CHARTS_DIR)
    except ValueError:
        out_display = _OUT
    print(
        f"Wrote {len(theme_names)} themes, {len(palette_names)} palettes, "
        f"{len(scale_palette_names)} scale palettes, {len(format_aliases)} format "
        f"aliases → {out_display}"
    )


if __name__ == "__main__":
    main()
