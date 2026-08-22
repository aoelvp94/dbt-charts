"""Pins the mdsvg packaging contract: vendored, not declared as a runtime dep.

The wheel-content anchor pins (mdsvg/__init__.py, font files) live in
test_wheel_asset_inventory.py — this test owns only what that one cannot:

- `mdsvg/renderer.py` is a deeper-than-anchor pin, proving the vendored
  package's submodules ship, not just the package marker.
- `Requires-Dist: markdown-svg` is absent from METADATA (mdsvg is vendored,
  not declared as a runtime dep on PyPI).
- `Requires-Dist: fonttools` is present (vendored mdsvg imports fonttools,
  so dataface's own METADATA must declare it).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

# Share the `built_dbt_charts_wheel` build with the other wheel-consuming files.
pytestmark = pytest.mark.xdist_group("dbt_charts_wheel")


@pytest.mark.timeout(120)
def test_wheel_vendors_mdsvg_and_declares_its_runtime_dependencies(
    built_dbt_charts_wheel: Path,
    dbt_charts_wheel_entries: set[str],
) -> None:
    with zipfile.ZipFile(built_dbt_charts_wheel) as wheel:
        metadata_name = next(
            name
            for name in dbt_charts_wheel_entries
            if name.endswith(".dist-info/METADATA")
        )
        metadata = wheel.read(metadata_name).decode("utf-8")

    assert "mdsvg/renderer.py" in dbt_charts_wheel_entries
    assert "Requires-Dist: markdown-svg" not in metadata
    assert "Requires-Dist: fonttools" in metadata
