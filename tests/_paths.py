from pathlib import Path

import dbt_charts

_pkg_file = dbt_charts.__file__
assert _pkg_file is not None

DBT_CHARTS_PKG_DIR = Path(_pkg_file).resolve().parent


def _find_dbt_charts_dir(start: Path) -> Path:
    """Walk up from the installed dbt_charts package to find the dbt-charts/ package root.

    Marker: a directory containing both ``pyproject.toml`` and ``src/dbt_charts/``.
    No hardcoded hop count — resilient to layout changes that shift how deeply
    the package is nested relative to its containing repository root.
    """
    candidate = start
    while not (
        (candidate / "pyproject.toml").exists()
        and (candidate / "src" / "dbt_charts").is_dir()
    ):
        if candidate.parent == candidate:
            raise RuntimeError(
                f"Could not locate dbt-charts package root above {start} "
                "(expected a directory with both pyproject.toml and src/dbt_charts)"
            )
        candidate = candidate.parent
    return candidate


# dbt-charts/ package root (contains pyproject.toml and src/dbt_charts/).
# INV1: nothing under dbt-charts/tests/ reads a path outside DBT_CHARTS_DIR
# (tests/visual/ is the sole named carve-out — see its own discovery.py).
# There is therefore nothing legitimate above this directory for a test to
# reach, so no PROJECT_ROOT is exposed here.
DBT_CHARTS_DIR = _find_dbt_charts_dir(DBT_CHARTS_PKG_DIR)
