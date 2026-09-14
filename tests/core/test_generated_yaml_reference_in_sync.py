"""Drift guard: the wheel's yaml-reference copy must match get_schema_for_prompt().

Two copies must stay in sync:
  - agent_api/docs/yaml-reference.md inside the package — wheel / pip install (no frontmatter)
  - apps/docs/docs/reference/yaml-reference.md — MkDocs site (has frontmatter); kept in
    sync by a guard test outside dbt-charts/, not covered here.

Fails when Pydantic models change without re-running `just gen-yaml-reference`.
"""

import os
import subprocess
import sys

from .._paths import DBT_CHARTS_DIR, DBT_CHARTS_PKG_DIR

# Reach the wheel copy through DBT_CHARTS_PKG_DIR so installed wheels work too.
# agent_api subpackage → docs → yaml-reference.md
_WHEEL_REFERENCE_PATH = DBT_CHARTS_PKG_DIR / "agent_api" / "docs" / "yaml-reference.md"


def _generated_reference_content() -> str:
    """Render the reference in a fresh interpreter to avoid test-order contamination."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from dbt_charts.core.compile.schema import get_schema_for_prompt; "
                "print(get_schema_for_prompt(), end='')"
            ),
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
        cwd=DBT_CHARTS_DIR,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return result.stdout + "\n"


def test_committed_yaml_reference_matches_generator() -> None:
    """The committed wheel yaml-reference.md must match get_schema_for_prompt().

    When this fails, run `just gen-yaml-reference` and commit the results.
    """
    content = _generated_reference_content()

    committed_wheel = _WHEEL_REFERENCE_PATH.read_text(encoding="utf-8")
    assert committed_wheel == content, (
        "agent_api/docs/yaml-reference.md is out of sync with Pydantic models. "
        "Run `just gen-yaml-reference` and commit the updated file."
    )
