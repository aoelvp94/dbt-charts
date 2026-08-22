"""Regression fixture for the `charts/meta.yaml` cascade on a real on-disk
project.

`meta-cascade` is a minimal project whose `overview` board owns no `queries:`
of its own — its only chart references `shared_kpi`, a query defined solely in
`charts/meta.yaml`. This proves the fixture is valid and that `compile_file`'s
`apply_meta` cascade resolves it locally. Cloud's stored-board render path does
not run this cascade yet (see
`apps/cloud/tests/integration/test_meta_cascade.py`, the xfail premise test
for task apply-boards-meta-yaml-cascade-for-github-backed-projects) — this
fixture is shared by both tests.
"""

from __future__ import annotations

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile import compile_file

from ..._paths import DBT_CHARTS_DIR

FIXTURE_DIR = DBT_CHARTS_DIR / "tests" / "fixtures" / "meta-cascade"


def test_meta_cascade_applies_shared_query() -> None:
    project = FilesystemProject(FIXTURE_DIR)
    result = compile_file(
        project.path("charts/overview.yml").read_board(), apply_meta=True
    )

    assert result.success
    assert "shared_kpi" in result.query_registry
