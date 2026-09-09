"""Scaffold a GitHub Actions workflow that validates a project's boards in CI.

Tier 1 of the boards-CI story: structural, credential-free. `dct validate`
checks board YAML shape, enums, references and unknown keys without touching a
warehouse, so the emitted workflow runs anywhere with no secrets.

The dbt root is not always the repo root. GitHub reads workflows only from
`<repo root>/.github/workflows/`, and its `paths:` filters are always
repo-root-relative — so both the filter prefix and the job's working directory
are derived from the project's path relative to the repo root, never assumed
to be `.`. A nested project also gets its own workflow filename, so a monorepo
scaffolds one gate per project instead of the second overwriting the first.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from dbt_charts.core.project import (
    CHARTS_SUBDIR,
    PROJECT_CONFIG_NAME,
    posix_relpath,
)
from dbt_charts.core.project_roots import find_dct_root, find_repo_root

_HEADER = """\
# Validates dbt Charts boards on every PR that touches them.
# Structural only — checks board YAML shape, enums and references. It runs no
# queries and needs no warehouse credentials.
#
# To also validate dbt ref()/source() calls against your models, add a
# `dbt deps && dbt parse` step before the validate step: that writes
# target/manifest.json, which `dct validate` reads. Without it those refs are
# reported as an unvalidated warning rather than checked.
#
# The `paths:` filters mean the job does not start on a PR that touches no
# board files — if you make it a required status check, drop the filters so
# it runs (and passes quickly) on every PR instead of pinning the merge at
# "Expected — waiting for status". The push trigger assumes your default
# branch is `main`; adjust `branches:` if it is not.
name: {workflow_name}

on:
  pull_request:
    paths:
{paths}
  push:
    branches: [main]
    paths:
{paths}
  workflow_dispatch:

jobs:
  validate:
    name: Validate boards
    runs-on: ubuntu-latest
"""

_STEPS = """\
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v6
        with:
          python-version: '3.13'

      - name: Install dbt Charts
        run: pip install dbt-charts

      - name: Validate boards
        run: dct validate {charts_dir}
"""


class CiScaffoldResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_path: Path
    """Absolute path to the workflow, always under the repo root."""

    repo_root: Path
    project_dir: Path
    project_relpath: str
    """Project dir relative to the repo root, posix-style; ``.`` at the root."""

    skipped_existing: bool = False


def workflow_relpath(project_relpath: str = ".") -> str:
    """Repo-relative workflow path for a project — one file per project.

    The root project owns the plain name; a nested project's path is slugged
    into the filename so a monorepo's second `dct init ci` adds a gate instead
    of colliding with the first project's.
    """
    if project_relpath == ".":
        return ".github/workflows/dbt-charts.yml"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project_relpath).strip("-").lower()
    return f".github/workflows/dbt-charts-{slug}.yml"


def ci_workflow(*, project_relpath: str = ".") -> str:
    """Render the validation workflow for a project *project_relpath* below the repo root."""
    prefix = "" if project_relpath == "." else f"{project_relpath}/"
    paths = "\n".join(
        f"      - '{p}'"
        for p in (
            f"{prefix}{CHARTS_SUBDIR}/**",
            f"{prefix}{PROJECT_CONFIG_NAME}",
            workflow_relpath(project_relpath),
        )
    )
    workflow_name = (
        "dbt Charts" if project_relpath == "." else f"dbt Charts ({project_relpath})"
    )
    body = _HEADER.format(workflow_name=workflow_name, paths=paths)
    if project_relpath != ".":
        body += (
            f"    defaults:\n      run:\n        working-directory: {project_relpath}\n"
        )
    return body + _STEPS.format(charts_dir=CHARTS_SUBDIR)


def scaffold_ci(
    project_dir: Path | None = None,
    *,
    force: bool = False,
) -> CiScaffoldResult:
    """Write the boards-validation workflow to the repo root. Skips an existing file unless *force*.

    Raises ValueError when *project_dir* is not inside a dct/dbt project, or
    when the project has no git repository above it — GitHub only reads
    workflows committed at a repo root, so writing anywhere else scaffolds a
    gate that can never fire.
    """
    start = (project_dir or Path()).resolve()
    project = find_dct_root(start)
    if project is None:
        raise ValueError(
            f"{start} does not contain a dbt charts or dbt project (no "
            f"{PROJECT_CONFIG_NAME} or dbt_project.yml here or in any parent)."
        )
    repo_root = find_repo_root(project)
    if repo_root is None:
        raise ValueError(
            f"No git repository found above {project}. GitHub only runs "
            "workflows committed at the repo root — initialize the repo "
            "(git init) and re-run `dct init ci`."
        )

    relpath = posix_relpath(project, repo_root)
    workflow_path = repo_root / workflow_relpath(relpath)

    if workflow_path.exists() and not force:
        return CiScaffoldResult(
            workflow_path=workflow_path,
            repo_root=repo_root,
            project_dir=project,
            project_relpath=relpath,
            skipped_existing=True,
        )

    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(ci_workflow(project_relpath=relpath), encoding="utf-8")
    return CiScaffoldResult(
        workflow_path=workflow_path,
        repo_root=repo_root,
        project_dir=project,
        project_relpath=relpath,
    )
