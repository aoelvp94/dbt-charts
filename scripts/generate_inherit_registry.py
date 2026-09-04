#!/usr/bin/env python3
"""Generate inherit_registry.yaml from InheritGraph markers on the Style model.

Re-run after adding or removing Inherit / InheritSlot annotations on theme.py:

    just generate-inherit-registry

The drift test (test_inherit_registry.py::test_inherit_registry_matches_graph)
fails when the committed file diverges from a fresh regeneration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# In the monorepo this script lives at dbt-charts/scripts/; in the standalone
# export it lands at scripts/ (Copybara core.move("dbt-charts", "")). Either way
# parents[1] is the dbt-charts package root / standalone repo root — where src/ lives.
_DBT_CHARTS_DIR = Path(__file__).resolve().parents[1]
_SRC = _DBT_CHARTS_DIR / "src"
_OUT = (
    _SRC
    / "dbt_charts"
    / "core"
    / "compile"
    / "resolve"
    / "style"
    / "inherit_registry.yaml"
)

sys.path.insert(0, str(_SRC))


def main() -> None:
    from dbt_charts.core.compile.models.style.theme import Style
    from dbt_charts.core.compile.resolve.style.inherit_graph import (
        build_slot_graph,
        flatten_inherit_chains,
    )

    chains = flatten_inherit_chains(build_slot_graph(Style))
    # Sort for stable output; convert tuples to lists for YAML serialization.
    data = {k: list(v) for k, v in sorted(chains.items())}
    with _OUT.open("w") as fh:
        yaml.dump(data, fh, default_flow_style=False, sort_keys=True)
    print(f"Wrote {len(data)} entries → {_OUT.relative_to(_DBT_CHARTS_DIR)}")


if __name__ == "__main__":
    main()
