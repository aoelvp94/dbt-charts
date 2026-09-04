"""Integration-test fixtures shared across test_examples.py and siblings."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from filelock import FileLock

from .._paths import DBT_CHARTS_DIR

_EXAMPLES_DIR = DBT_CHARTS_DIR / "examples"
_TUTORIAL_DBT_DIR = _EXAMPLES_DIR / "tutorial_dbt"


def _ensure_tutorial_manifest(project_dir: Path) -> None:
    """Generate ``target/manifest.json`` for tutorial_dbt via ``dbt parse``.

    ``target/`` is gitignored dbt build output — there is no committed-
    snapshot fallback (the manifest.snapshot.json convention was removed).
    This mirrors the tutorial's documented fresh-clone flow (README's
    ``dbt run`` / ``dbt parse`` step) instead of reading a committed manifest.

    FileLock prevents the TOCTOU race under xdist parallelism: without it,
    two workers can both pass ``not target.exists()`` before either finishes
    writing the ~490 KB manifest, and a worker that reads mid-write sees
    truncated JSON.
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
    left in place after the session (safe for repeated runs without re-seeding).
    """
    _ensure_tutorial_manifest(_TUTORIAL_DBT_DIR)
