"""Integration-test fixtures shared across test_examples.py and siblings."""

from __future__ import annotations

import subprocess
from pathlib import Path

import duckdb
import pytest
from filelock import FileLock

from .._paths import DBT_CHARTS_DIR

_EXAMPLES_DIR = DBT_CHARTS_DIR / "examples"
_METRICFLOW_WAREHOUSE = _EXAMPLES_DIR / "metricflow" / "warehouse.duckdb"
_TUTORIAL_DBT_DIR = _EXAMPLES_DIR / "tutorial_dbt"


def _ensure_metricflow_warehouse(target: Path) -> bool:
    """Create the metricflow warehouse DuckDB if absent; return True if created.

    FileLock prevents the TOCTOU race under xdist parallelism: without it, two
    workers can both pass ``not target.exists()`` before either finishes writing.
    See apps/looker_migrate/tests/integration/conftest.py for the same pattern.
    """
    with FileLock(str(target.with_suffix(".lock"))):
        if not target.exists():
            conn = duckdb.connect(str(target))
            conn.execute(
                "CREATE TABLE orders "
                "(order_id INTEGER, order_date DATE, region VARCHAR, revenue DOUBLE)"
            )
            conn.execute(
                "INSERT INTO orders VALUES "
                "(1, DATE '2024-01-05', 'east', 100.0), "
                "(2, DATE '2024-01-20', 'west', 50.0), "
                "(3, DATE '2024-02-10', 'east', 75.0), "
                "(4, DATE '2024-02-15', 'west', 200.0), "
                "(5, DATE '2024-03-01', 'east', 80.0), "
                "(6, DATE '2024-03-20', 'west', 60.0)"
            )
            conn.close()
            return True
        return False


@pytest.fixture(scope="session", autouse=True)
def seed_metricflow_warehouse() -> None:
    """Seed examples/metricflow/warehouse.duckdb before the test session.

    warehouse.duckdb is intentionally NOT committed (it would exceed the 500 KB
    pre-commit limit). This fixture creates the minimal orders table the metricflow
    example and test_examples.py rely on. The file is gitignored and derived, so
    it is left in place after the session — safe for repeated runs without re-seeding.

    The file lives at a known absolute path rather than tmp_path because the dbt
    profile uses a relative ``path: warehouse.duckdb`` resolved against the dbt
    project dir (examples/metricflow/). Generating it in tmp_path would require
    rewriting the profile, diverging from the shipped example.

    FileLock inside _ensure_metricflow_warehouse prevents the TOCTOU race under
    xdist parallelism (mirrors the apps/looker_migrate conftest pattern).
    """
    _ensure_metricflow_warehouse(_METRICFLOW_WAREHOUSE)


def _ensure_tutorial_manifest(project_dir: Path) -> None:
    """Generate ``target/manifest.json`` for tutorial_dbt via ``dbt parse``.

    ``target/`` is gitignored dbt build output — there is no committed-
    snapshot fallback (the manifest.snapshot.json convention was removed).
    This mirrors the tutorial's documented fresh-clone flow (README's
    ``dbt run`` / ``dbt parse`` step) instead of reading a committed manifest.

    FileLock prevents the TOCTOU race under xdist parallelism: without it,
    two workers can both pass ``not target.exists()`` before either finishes
    writing the ~490 KB manifest, and a worker that reads mid-write sees
    truncated JSON (mirrors ``_ensure_metricflow_warehouse``).
    """
    target = project_dir / "target" / "manifest.json"
    # Lock file lives at the project root, not inside target/ — target/ may
    # not exist yet on a fresh clone, and FileLock does not create parent dirs.
    with FileLock(str(project_dir / ".manifest.lock")):
        if target.exists():
            return

        # Subprocess, not in-process dbtRunner: dbt's `flags.GLOBAL_FLAGS`
        # is process-global state that a project-scoped invoke would leave
        # pointed at this project dir for the rest of the test session.
        # --no-send-anonymous-usage-stats skips dbt's telemetry ping.
        result = subprocess.run(
            [
                "dbt",
                "parse",
                "--project-dir",
                str(project_dir),
                "--profiles-dir",
                str(project_dir),
                "--no-send-anonymous-usage-stats",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"dbt parse failed for tutorial_dbt:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="session", autouse=True)
def seed_tutorial_dbt_manifest() -> None:
    """Generate examples/tutorial_dbt/target/manifest.json before the test session.

    See ``_ensure_tutorial_manifest`` — the file is gitignored and derived,
    left in place after the session like the metricflow warehouse above.
    """
    _ensure_tutorial_manifest(_TUTORIAL_DBT_DIR)
