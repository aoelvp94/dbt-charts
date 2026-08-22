"""Guard against scattered literal ``dbt-charts/<subdir>/`` path strings.

External callers must reach package-source assets through
:data:`dbt-charts.tests._paths.DBT_CHARTS_PKG_DIR` (tests, scripts) or a public
``dbt_charts.core.<asset>`` accessor (production code). Re-introducing a literal
``"dbt_charts/core/..."`` string outside the package source tree silently re-
couples the caller to the on-disk layout and breaks any future structural
move (rename, src-layout migration, sub-package split).

Scope: ``dbt-charts/tests/`` only — the same guard over ``apps/``,
``scripts/``, and the top-level ``tests/`` tree is intentionally not
covered here, since those roots are outside dbt-charts/. The
``libs/tasks/pr/`` PR diff classifier (and its tests) is legitimately
layout-coupled — it pattern-matches GitHub-style diff paths — and is
intentionally out of scope everywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .._paths import DBT_CHARTS_DIR

_FORBIDDEN = (
    "dbt_charts/core/",
    "dbt_charts/cli/",
    "dbt_charts/ai/",
    "dbt_charts/integrations/",
    "dbt_charts/agent_api/",
)

_SCAN_ROOTS = (DBT_CHARTS_DIR / "tests",)

# Files whose literal paths are correct by contract — wheel-content assertions
# (the wheel's internal package layout, not the source layout) and this guard
# test itself, which names the forbidden substrings.
_ALLOWLIST = frozenset(
    {
        DBT_CHARTS_DIR / "tests" / "_paths.py",
        DBT_CHARTS_DIR
        / "tests"
        / "core"
        / "test_no_literal_dbt_charts_subdir_paths.py",
        DBT_CHARTS_DIR / "tests" / "core" / "test_packaging_mdsvg.py",
        DBT_CHARTS_DIR / "tests" / "core" / "test_wheel_asset_inventory.py",
        DBT_CHARTS_DIR / "tests" / "integration" / "test_oss_install_smoke.py",
    }
)


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        files.extend(p for p in root.rglob("*.py") if p.resolve() not in _ALLOWLIST)
    return sorted(files)


@pytest.mark.parametrize(
    "path", _iter_python_files(), ids=lambda p: str(p.relative_to(DBT_CHARTS_DIR))
)
def test_no_literal_dbt_charts_subdir_path(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    offenders = [needle for needle in _FORBIDDEN if needle in text]
    if offenders:
        raise AssertionError(
            f"{path.relative_to(DBT_CHARTS_DIR)} contains literal package-source "
            f"path strings: {offenders}. Reach assets through "
            "DBT_CHARTS_PKG_DIR (tests/scripts) or a dbt_charts.core.<asset> "
            "accessor (production)."
        )
