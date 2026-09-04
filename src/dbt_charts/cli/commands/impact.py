"""impact command — thin wrapper over dbt_charts.agent_api.impact."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.markup import escape

from dbt_charts.agent_api import Project
from dbt_charts.cli._console import dct_console
from dbt_charts.cli._project import with_project

if TYPE_CHECKING:
    from dbt_charts.agent_api.impact import ColumnImpactResult

_console = dct_console()


@with_project
def impact_command(
    column: str,
    *,
    project: Project,
    table: str | None = None,
    json_output: bool = False,
) -> None:
    from dbt_charts.agent_api.impact import column_impact

    result = column_impact(project, column=column, table=table)
    _emit(result, json_output=json_output)


def _emit(result: ColumnImpactResult, *, json_output: bool) -> None:
    if json_output:
        typer.echo(result.model_dump_json(exclude_none=True, indent=2))
        return

    target = f"{result.table}.{result.column}" if result.table else result.column
    if result.boards_scanned == 0:
        # Zero boards scanned is not "no dependents" — say so instead of
        # printing an answer indistinguishable from a clean sweep.
        _console.print(
            f"No boards found under charts/ — nothing was checked for "
            f"[bold]{escape(target)}[/bold]."
        )
        return
    if result.hits:
        _console.print(f"Boards referencing [bold]{escape(target)}[/bold]:")
        for hit in result.hits:
            _console.print(
                f"  {escape(hit.board)}  query: {escape(hit.query)}  "
                f"({escape(hit.table)}.{escape(hit.column)})"
            )
    else:
        _console.print(
            f"No board queries reference [bold]{escape(target)}[/bold] "
            f"({result.boards_scanned} boards checked)."
        )

    if result.indeterminate:
        _console.print("")
        _console.print(
            "Could not be analyzed — verify these by hand before treating the "
            "list above as complete:"
        )
        for item in result.indeterminate:
            _console.print(
                f"  {escape(item.board)}  query: {escape(item.query)} — "
                f"{escape(item.reason)}"
            )
