"""`dct init ci` thin wrapper: parse args, call agent_api.init_ci, format output."""

from __future__ import annotations

from pathlib import Path

import typer

from dbt_charts.agent_api import init_ci


def run_init_ci(
    *,
    force: bool,
    project_dir: Path | None = None,
) -> None:
    """Shared implementation for ``dct init ci``."""
    try:
        result = init_ci.scaffold_ci(project_dir=project_dir, force=force)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None

    rel = result.workflow_path.relative_to(result.repo_root)

    if project_dir is not None and result.project_dir != project_dir.resolve():
        typer.echo(
            f"  project root resolved to {result.project_dir} "
            f"(walked up from {project_dir.resolve()})"
        )

    if result.skipped_existing:
        typer.echo(f"  skipped {rel} (already exists)")
        typer.echo("  Pass --force to overwrite it.")
        return

    typer.echo(f"  created {rel}")
    if result.project_relpath != ".":
        typer.echo(
            f"  project dir: {result.project_relpath}/ (relative to the repo root)"
        )
    typer.echo("")
    typer.echo(
        "  Commit it to gate PRs on `dct validate` — no warehouse credentials needed."
    )
