"""Query command implementation — named board queries and raw SQL dispatch."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import typer
from pydantic import TypeAdapter
from rich.markup import escape
from rich.table import Table

if TYPE_CHECKING:
    from rich.console import Console

    from dbt_charts.agent_api.describe_query import DescribeQueryResult
    from dbt_charts.agent_api.query import (
        BoardQueryLookupResult,
        ExecuteQueryResult,
        QueryBoardResult,
    )
    from dbt_charts.agent_api.validate_query import QueryDiagnostic

from dbt_charts.agent_api import Project
from dbt_charts.cli._console import dct_console
from dbt_charts.cli._json_output import print_json_result
from dbt_charts.cli._project import with_project

console = dct_console()
err_console = dct_console(stderr=True)

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_SEVERITY_ICON = {"error": "❌", "warning": "⚠️ ", "info": "ℹ️ "}

_diagnostic_adapter: TypeAdapter[QueryDiagnostic] | None = None


def _diagnostic_wire_dict(d: QueryDiagnostic) -> dict[str, Any]:
    """Serialize a QueryDiagnostic the way ExecuteQueryResult/DescribeQueryResult
    do via model_dump_json(exclude_none=True), so `--validate --json` matches
    `--describe --json` / execute_query's wire shape key-for-key instead of the
    null-filled shape `QueryDiagnostic.to_dict()` used to produce.

    Builds the adapter lazily: `dbt_charts.core.inspect.query_validator`
    (QueryDiagnostic's module) imports `core.compile.sql_guard`, and
    `dbt_charts.cli.main` must not eagerly load `dbt_charts.core.compile`
    (test_lazy_imports.py).
    """
    global _diagnostic_adapter
    if _diagnostic_adapter is None:
        from dbt_charts.agent_api.validate_query import QueryDiagnostic as _QD

        _diagnostic_adapter = TypeAdapter(_QD)
    return _diagnostic_adapter.dump_python(d, mode="json", exclude_none=True)


def _rows_table(columns: list[str], data: list[dict[str, Any]]) -> Table:
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2, 0, 0))
    for col in columns:
        t.add_column(escape(col))
    for row in data:
        t.add_row(*(escape(str(row.get(col, ""))) for col in columns))
    return t


def _print_rows(
    columns: list[str], data: list[dict[str, Any]], row_count: int, truncated: bool
) -> None:
    if columns:
        console.print(_rows_table(columns, data))
    err_console.print(f"\n{row_count} rows{' (truncated)' if truncated else ''}")


def _print_diagnostic(d: QueryDiagnostic, target: Console = err_console) -> None:
    icon = _SEVERITY_ICON.get(d.severity, "⚠️ ")
    target.print(f"{icon} [{d.code}] {d.message}", markup=False)
    if d.detail:
        target.print(f"   {d.detail}", markup=False)
    if d.recommendation:
        target.print(f"   → {d.recommendation}", markup=False)
    if d.confidence is not None:
        target.print(f"   confidence: {d.confidence:.0%}")
    for ev in d.evidence:
        target.print(f"   evidence: {ev}", markup=False)


def _print_query_board_rich(result: QueryBoardResult) -> None:
    if not result.success:
        for err in result.errors:
            err_console.print(f"[red]Error:[/red] {escape(err)}")
        if result.available_queries:
            matches = difflib.get_close_matches(
                result.name, result.available_queries, n=3
            )
            if matches:
                err_console.print(f"Did you mean: {escape(', '.join(matches))}?")
            elif _looks_like_sql(result.name):
                err_console.print(
                    "Did you mean to use a source name instead of a .yaml board path?"
                )
            err_console.print(
                f"Available queries: {escape(', '.join(result.available_queries))}"
            )
        raise typer.Exit(1)
    _print_rows(result.columns, result.data, result.row_count, result.truncated)


def _print_execute_query_rich(result: ExecuteQueryResult) -> None:
    if not result.success:
        for err in result.errors:
            err_console.print(f"[red]Error:[/red] {escape(err)}")
        raise typer.Exit(1)
    _print_rows(result.columns, result.data, result.row_count, result.truncated)


def _print_validate_result(
    active: list[QueryDiagnostic],
    suppressed: list[QueryDiagnostic] | None = None,
    json_output: bool = False,
) -> None:
    """Print validate result and exit 1 on errors."""
    has_errors = any(d.severity == "error" for d in active)
    if json_output:
        active_dicts = [_diagnostic_wire_dict(d) for d in active]
        payload: Any = (
            {
                "diagnostics": active_dicts,
                "suppressed": [_diagnostic_wire_dict(d) for d in suppressed or []],
            }
            if suppressed is not None
            else active_dicts
        )
        typer.echo(json.dumps(payload, indent=2))
    elif not active and not suppressed:
        console.print("No issues found.")
    else:
        for d in active:
            _print_diagnostic(d, target=console)
        if suppressed:
            console.print(f"\nSuppressed ({len(suppressed)}):")
            for d in suppressed:
                console.print(f"  ~ [{d.code}] {d.message}", markup=False)

    if has_errors:
        raise typer.Exit(1)


def _print_describe_result(
    result: DescribeQueryResult, json_output: bool = False
) -> None:
    """Print describe result and exit 1 on failure."""
    if json_output:
        print_json_result(result)
        if not result.success:
            raise typer.Exit(1)
        return

    if not result.success:
        err_console.print(f"[red]Error:[/red] {escape(result.error or '')}")
        for d in result.diagnostics:
            _print_diagnostic(d)
        raise typer.Exit(1)

    if result.columns:
        t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2, 0, 0))
        t.add_column("name")
        t.add_column("type")
        for col in result.columns:
            t.add_row(escape(col.name), escape(col.type))
        console.print(t)

    for d in result.diagnostics:
        _print_diagnostic(d)


# ---------------------------------------------------------------------------
# SQL-source resolution helpers
# ---------------------------------------------------------------------------


def _is_board_context(context: str) -> bool:
    """Return True when the first operand selects board-query mode."""
    return Path(context).suffix == ".yaml"


def _resolve_query_input(
    context: str | None,
    query_text: str | None,
    file: Path | None,
) -> tuple[str, bool, str | None, Path | None, str | None]:
    """Resolve the input operands into dispatch mode.

    Returns (sql_text, mode_is_named, query_name, board_path, source_name).
    Raises typer.Exit(1) on any resolution error.
    """
    if context is None:
        typer.echo("Error: provide a source or .yaml board path.", err=True)
        raise typer.Exit(1)

    if _is_board_context(context):
        if file is not None:
            typer.echo(
                "Error: use a board query reference or --file, not both.", err=True
            )
            raise typer.Exit(1)
        if not query_text:
            typer.echo(
                "Error: provide a query reference for the board"
                " (e.g. dct query charts/sales.yaml revenue).",
                err=True,
            )
            raise typer.Exit(1)
        return "", True, query_text, Path(context), None

    if file and query_text:
        typer.echo("Error: provide SQL text or --file, not both.", err=True)
        raise typer.Exit(1)

    if file is not None:
        if not file.exists():
            typer.echo(f"Error: file not found: {file}", err=True)
            raise typer.Exit(1)
        return file.read_text(encoding="utf-8"), False, None, None, context

    if not query_text:
        typer.echo(
            "Error: provide SQL or --file for source context"
            " (e.g. dct query warehouse 'SELECT 1').",
            err=True,
        )
        raise typer.Exit(1)

    return query_text, False, None, None, context


_SQL_SHAPE_CHARS = frozenset(" \t\n()")


def _looks_like_sql(name: str) -> bool:
    """Return True if name resembles a SQL expression rather than a query identifier."""
    upper = name.upper()
    return (
        upper.startswith("SELECT")
        or upper.startswith("WITH")
        or any(c in name for c in _SQL_SHAPE_CHARS)
    )


def _handle_lookup_failure(lr: BoardQueryLookupResult, query_name: str) -> NoReturn:
    """Emit errors from a failed BoardQueryLookupResult and raise typer.Exit(1)."""
    for err in lr.errors:
        typer.echo(f"Error: {err}", err=True)
    if lr.available_queries:
        matches = difflib.get_close_matches(query_name, lr.available_queries, n=3)
        if matches:
            typer.echo("Did you mean: " + ", ".join(matches) + "?", err=True)
        elif _looks_like_sql(query_name):
            typer.echo(
                "Did you mean to use a source name instead of a .yaml board path?",
                err=True,
            )
        typer.echo("Available queries: " + ", ".join(lr.available_queries), err=True)
    raise typer.Exit(1)


def _resolve_source(source_context: str | None, board_source: str | None) -> str:
    """Resolve the effective source, raising if neither is available."""
    resolved = source_context or board_source
    if resolved is None:
        typer.echo(
            "Error: query describe requires a source. "
            "Set source on the board query or use `dct query SOURCE SQL --describe`.",
            err=True,
        )
        raise typer.Exit(1)
    return resolved


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@with_project
def query_command(
    context: str | None,
    query_text: str | None = None,
    validate: bool = False,
    describe: bool = False,
    file: Path | None = None,
    dialect: str | None = None,
    vars: dict[str, Any] | None = None,
    limit: int = 20,
    show_suppressed: bool = False,
    json_output: bool = False,
    *,
    project: Project,
) -> None:
    """Run a named board query, raw SQL, or static SQL lint/describe — selected from the input args."""
    from dbt_charts.agent_api import ProjectSession

    # --- 1. Resolve input shape ---
    sql_text, mode_is_named, query_name, board, source = _resolve_query_input(
        context, query_text, file
    )

    # --- 2. Apply mode flags ---
    # All branches open a ProjectSession so relationship context is available for
    # validate paths (raw-SQL validate-only was previously a stateless short-
    # circuit; it now routes through project_session.validate_query for calibrated severity).
    with ProjectSession.from_project(project) as project_session:
        if not validate and not describe:
            # Execute path — keep the named-query branch as a direct query_board call so
            # that file-not-found and compile errors are returned as structured JSON
            # (QueryBoardResult.success=False) rather than plain stderr messages.
            if mode_is_named:
                assert query_name is not None
                assert board is not None
                board_result = project_session.query_board(
                    name=query_name,
                    path=board,
                    vars=vars,
                    limit=limit,
                )
                if json_output:
                    print_json_result(board_result)
                    if not board_result.success:
                        raise SystemExit(1)
                else:
                    _print_query_board_rich(board_result)
            else:
                assert source is not None
                exec_result = project_session.execute_query(
                    sql_text,
                    variables=vars,
                    source=source,
                    limit=limit,
                )
                if json_output:
                    print_json_result(exec_result)
                    if not exec_result.success:
                        raise SystemExit(1)
                else:
                    _print_execute_query_rich(exec_result)
            return

        # raw-SQL validate-only — no named-query lookup needed.
        if validate and not describe and not mode_is_named:
            if show_suppressed:
                active, suppressed = project_session.validate_query(
                    sql_text, dialect=dialect, return_suppressed=True
                )
            else:
                active = project_session.validate_query(sql_text, dialect=dialect)
                suppressed = None
            _print_validate_result(active, suppressed, json_output=json_output)
            return

        # For validate/describe modes on named queries, extract SQL from the compiled board.
        # describe_query needs the adapter registry; validate_query is stateless.
        board_source: str | None = None
        if mode_is_named:
            assert query_name is not None
            assert board is not None
            lr = project_session.lookup_board_query_sql(query_name, board, vars=vars)
            if not lr.success:
                _handle_lookup_failure(lr, query_name)
            sql_text = lr.sql
            board_source = lr.source

        if validate and describe:
            # Run validate first; skip describe on error-severity diagnostics.
            if show_suppressed:
                active, suppressed = project_session.validate_query(
                    sql_text, dialect=dialect, return_suppressed=True
                )
            else:
                active = project_session.validate_query(sql_text, dialect=dialect)
                suppressed = None
            has_errors = any(d.severity == "error" for d in active)
            # Build the validate payload the same way on both error and success paths.
            active_dicts = [_diagnostic_wire_dict(d) for d in active]
            validate_payload: Any = (
                {
                    "diagnostics": active_dicts,
                    "suppressed": [_diagnostic_wire_dict(d) for d in suppressed or []],
                }
                if suppressed is not None
                else active_dicts
            )
            if has_errors:
                if json_output:
                    typer.echo(json.dumps({"validate": validate_payload}, indent=2))
                else:
                    _print_validate_result(active, suppressed)
                raise typer.Exit(1)

            resolved_source = _resolve_source(source, board_source)
            dr = project_session.describe_query(
                sql_text, source=resolved_source, dialect=dialect
            )

            if json_output:
                typer.echo(
                    json.dumps(
                        {
                            "validate": validate_payload,
                            "describe": dr.model_dump(mode="json", exclude_none=True),
                        },
                        indent=2,
                    )
                )
                if not dr.success:
                    raise typer.Exit(1)
            else:
                _print_validate_result(active, suppressed)
                _print_describe_result(dr)

        elif validate:
            # Named-query validate (mode_is_named=True).
            if show_suppressed:
                active, suppressed = project_session.validate_query(
                    sql_text, dialect=dialect, return_suppressed=True
                )
            else:
                active = project_session.validate_query(sql_text, dialect=dialect)
                suppressed = None
            _print_validate_result(active, suppressed, json_output=json_output)

        else:  # describe only
            resolved_source = _resolve_source(source, board_source)
            dr = project_session.describe_query(
                sql_text, source=resolved_source, dialect=dialect
            )
            _print_describe_result(dr, json_output=json_output)
