"""CLI command for `dct docs`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import typer
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table

from dbt_charts._docs_site import docs_site_url
from dbt_charts.cli._console import dct_console, is_plain_output
from dbt_charts.cli._json_output import print_json_result

if TYPE_CHECKING:
    from dbt_charts.agent_api.docs import TopicEntry

console = dct_console()

# The two user-facing CLI verbs over the one diagnostic registry.
_DIAGNOSTIC_TOPICS: dict[str, Literal["error", "warning"]] = {
    "errors": "error",
    "warnings": "warning",
}


def docs_diagnostics_list(
    level: Literal["error", "warning"], json_output: bool
) -> None:
    """Print all registered codes at `level` with one-line descriptions, sorted."""
    from dbt_charts.agent_api.diagnostics import list_diagnostic_codes

    result = list_diagnostic_codes(level=level)

    if json_output:
        print_json_result(result)
        return

    if not result.codes:
        typer.echo(f"No {level} codes registered.")
        return

    width = max(len(e.code) for e in result.codes)
    if not is_plain_output():
        table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        table.add_column("Code", style="bold", no_wrap=True, width=width)
        table.add_column("Description", overflow="fold")
        for entry in result.codes:
            table.add_row(entry.code, entry.summary)
        console.print(table)
    else:
        for entry in result.codes:
            typer.echo(f"  {entry.code.ljust(width)}  {entry.summary}")

    typer.echo("")
    typer.echo(f"Run `dct docs {level}s <CODE>` for the full documentation.")


def docs_diagnostic_detail(
    code: str, level: Literal["error", "warning"], json_output: bool
) -> None:
    """Print the doc for a single diagnostic code. Exit 1 only if unregistered.

    A code registered under the other level still resolves — never "unknown
    code" for a code we ship — with a note pointing at the verb that matches
    its actual level.
    """
    from dbt_charts.agent_api.diagnostics import get_diagnostic_code

    result = get_diagnostic_code(code)

    if json_output:
        print_json_result(result)
        if not result.success:
            raise typer.Exit(1)
        return

    if not result.success:
        assert result.errors, "success=False guarantees errors is populated"
        typer.echo(result.errors[0], err=True)
        raise typer.Exit(1)

    assert result.detail is not None  # guaranteed by success=True
    if result.detail.level != level:
        typer.echo(
            f"Note: {result.detail.code} is a registered {result.detail.level} "
            f"code, not {level}. Try `dct docs {result.detail.level}s "
            f"{result.detail.code}`.\n",
            err=True,
        )
    _emit_markdown(result.detail.doc)


def docs_command(
    topic: str | None,
    code: str | None,
    search: str | None,
    json_output: bool,
    limit: int,
) -> None:
    if code is not None and topic not in _DIAGNOSTIC_TOPICS:
        raise typer.BadParameter(
            f"A second positional argument is only valid when topic is "
            f"'errors' or 'warnings'. Got topic={topic!r} and code={code!r}. "
            f"Did you mean: dct docs warnings {code!r} or dct docs errors {code!r}?"
        )

    if topic in _DIAGNOSTIC_TOPICS:
        level = _DIAGNOSTIC_TOPICS[topic]
        if search is not None:
            raise typer.BadParameter(
                f"{topic} does not support --search. "
                f"Run `dct docs {topic}` to list all codes, "
                f"or `dct docs {topic} <CODE>` for one code."
            )
        if code is not None:
            docs_diagnostic_detail(code, level, json_output)
        else:
            docs_diagnostics_list(level, json_output)
        return

    from dbt_charts.agent_api.docs import docs as _docs

    result = _docs(topic=topic, search=search, limit=limit)

    if json_output:
        print_json_result(result)
        if not result.success:
            raise typer.Exit(1)
        return

    if not result.success:
        for err in result.errors:
            typer.echo(err, err=True)
        for hint in result.hints:
            typer.echo(hint, err=True)
        raise typer.Exit(1)

    if result.mode == "index":
        _emit_topic_index(result.topics)
        return

    if result.mode == "search":
        if not result.search:
            typer.echo("No results found.")
            return
        for hit in result.search:
            typer.echo(f"[{hit.topic}]")
            _emit_markdown(hit.content + "\n")
            typer.echo("")
        typer.echo("Run `dct docs <topic>` to read a hit's whole topic.")
        return

    if result.topic is not None:
        _emit_markdown(result.topic.content)


def _emit_topic_index(topics: list[TopicEntry]) -> None:
    if not topics:
        typer.echo("No topics found.")
        return

    web_docs = f"{docs_site_url()}/cli/docs/"
    if not is_plain_output():
        _emit_topic_index_rich(topics, web_docs)
    else:
        _emit_topic_index_plain(topics, web_docs)


def _emit_topic_index_rich(topics: list[TopicEntry], web_docs: str) -> None:
    typer.echo(
        "dbt charts (`dct`) is a dbt-native dashboard layer. You author dashboards as "
        'YAML "boards" — queries, charts, variables, and layout — and `dct` compiles '
        "and renders them."
    )
    typer.echo("")
    typer.echo(
        "These docs are the offline YAML language reference bundled with `dct`. "
        "Every field here is enforced by the compiler — unknown keys are errors."
    )
    typer.echo("")
    console.print(f"Web docs: [link={web_docs}]{web_docs}[/link]")
    console.print("[dim]Override base URL with DCT_DOCS_URL[/dim]")
    console.print("")
    console.print("[bold]Topics[/bold]")
    console.print(Padding(_topic_table(topics), (0, 0, 0, 2)))
    console.print("")
    typer.echo("Next steps")
    typer.echo("  dct docs <topic>       Read one section with full formatting")
    typer.echo("  dct docs cheatsheet    One-screen essentials")
    typer.echo("  dct docs all           Full reference, unsliced")
    typer.echo('  dct docs -s "<query>"  Search across topics')
    typer.echo("  dct docs errors        List all error codes")
    typer.echo("  dct docs warnings      List all warning codes")
    typer.echo("  dct skills             Agent workflows and layout patterns")


def _emit_topic_index_plain(topics: list[TopicEntry], web_docs: str) -> None:
    typer.echo(
        "dbt charts (`dct`) is a dbt-native dashboard layer. You author dashboards as "
        'YAML "boards" — queries, charts, variables, and layout — and `dct` compiles '
        "and renders them.\n"
    )
    typer.echo(
        "These docs are the offline YAML language reference bundled with `dct`. "
        "Every field here is enforced by the compiler — unknown keys are errors.\n"
    )
    typer.echo(f"Web docs: {web_docs}")
    typer.echo("Override base URL with DCT_DOCS_URL\n")
    typer.echo("Topics")
    width = max(len(entry.id) for entry in topics)
    for entry in topics:
        suffix = f"  {entry.description}" if entry.description else ""
        typer.echo(f"  {entry.id.ljust(width)}{suffix}")
    typer.echo("")
    typer.echo("Next steps")
    typer.echo("  dct docs <topic>       Read one section")
    typer.echo("  dct docs cheatsheet    One-screen essentials")
    typer.echo("  dct docs all           Full reference, unsliced")
    typer.echo('  dct docs -s "<query>"  Search across topics')
    typer.echo("  dct docs errors        List all error codes")
    typer.echo("  dct docs warnings      List all warning codes")
    typer.echo("  dct skills             Agent workflows and layout patterns")


def _topic_table(topics: list[TopicEntry]) -> Table:
    name_width = max(len(entry.id) for entry in topics)
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("Topic", style="bold", no_wrap=True, width=name_width)
    table.add_column("Description", overflow="fold")
    for entry in topics:
        table.add_row(entry.id, entry.description)
    return table


def _emit_markdown(content: str) -> None:
    if not is_plain_output():
        console.print(Markdown(content))
    else:
        typer.echo(content, nl=False)
