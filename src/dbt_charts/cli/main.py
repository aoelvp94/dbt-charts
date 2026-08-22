"""Main CLI entry point."""

import importlib.util
import io
import logging
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from typer.core import TyperGroup

from dbt_charts.agent_api import RenderFormat, set_surface
from dbt_charts.cli._console import is_plain_output
from dbt_charts.cli._extras import require_extras
from dbt_charts.cli._parsing import parse_kv_pairs
from dbt_charts.cli._project import has_charts_marker
from dbt_charts.cli.commands import (
    board_artifact as board_artifact_cmd,
    describe as describe_cmd,
    docs as docs_cmd,
    extension as extension_cmd,
    init as init_cmd,
    inspect as inspect_cmd,
    mcp as mcp_cmd,
    migrate as migrate_cmd,
    query as query_cmd,
    render as render_cmd,
    search as search_cmd,
    serve as serve_cmd,
    skills as skills_cmd,
    validate as validate_cmd,
)
from dbt_charts.cli.commands.mcp_init import run_init as _mcp_run_init
from dbt_charts.cli.commands.skills_init import run_init_skills as _skills_run_init

# Evaluated once at process startup — mid-session env changes won't take effect.
_RICH_MARKUP_MODE: Literal["rich"] | None = None if is_plain_output() else "rich"
# Probe for private package once at startup; avoids repeated find_spec calls.
_SUPER_SCHEMA_AVAILABLE: bool = (
    importlib.util.find_spec("dbt_charts_super_schema") is not None
)

# MCP subcommand app
mcp_app = typer.Typer(
    name="mcp",
    help="MCP (Model Context Protocol) server commands for AI assistant integration.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode=_RICH_MARKUP_MODE,
)

# Init subcommand app — `dct init` (project scaffold), `dct init mcp [client]`
# (AI integration), `dct init code|cursor|vscode` (editor extension install).
init_app = typer.Typer(
    name="init",
    help="Bootstrap a Dataface project, plus its AI / editor integrations.",
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode=_RICH_MARKUP_MODE,
)

# Inspect subcommand app
inspect_app = typer.Typer(
    name="inspect",
    help="Inspect database tables and manage inspect templates.",
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode=_RICH_MARKUP_MODE,
)

# Artifact subcommand app — `dct artifact emit` / `dct artifact render`
artifact_app = typer.Typer(
    name="artifact",
    help="Emit a resolved-board artifact + recording, and render one back.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode=_RICH_MARKUP_MODE,
)

# Shared --project-dir option. Every user-visible command that accepts a
# project root uses this alias so help text, validation, and DCT_PROJECT_DIR
# env-var wiring stay in lock-step.
ProjectDirOption = Annotated[
    Path | None,
    typer.Option(
        "--project-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        envvar="DCT_PROJECT_DIR",
        help="Project root for resolving board paths and finding project config",
    ),
]


# Configure logging for CLI (only if no handlers configured yet)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s - %(levelname)s - %(message)s",
    )


def _render_init_banner() -> None:
    """Print a nudge to run ``dct init``.

    Only called from :class:`_RootHelpGroup.format_help` when cwd is
    not inside a scaffolded project. In plain mode (agent context or
    piped stdout) the banner renders as a single plain line so context
    captures do not pick up Panel chrome.
    """
    if is_plain_output():
        Console(force_terminal=False, no_color=True).print(
            "Welcome to Dataface — run `dct init` to start a new project."
        )
        return
    Console().print(
        Panel(
            "Run [bold cyan]dct init[/bold cyan] to start a new project!",
            title="Welcome to Dataface",
            title_align="left",
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


# Panel sections on `dct --help`, in the order they render. A panel absent
# from this tuple sorts last (alphabetically among its peers).
PANEL_ORDER: tuple[str, ...] = ("Dashboards", "Data & SQL", "AI", "Reference")


def _panel_rank(panel: str) -> int:
    return PANEL_ORDER.index(panel) if panel in PANEL_ORDER else len(PANEL_ORDER)


class _RootHelpGroup(TyperGroup):
    """Root-only group: alphabetize the Options panel + commands and gate the init banner.

    Click otherwise displays params in declaration order with the
    auto-added `--help` last; that puts `--version` ahead of `--help`
    on the root help. TyperGroup also overrides Click's sorted
    list_commands with registration order, which buckets sub-typer
    groups after leaf commands within the same rich_help_panel (e.g.
    `init` after docs/playground/skills under Reference). Sorting here
    interleaves them so each panel reads A-Z. Also prints the "run
    `dct init`" banner above the help body when cwd isn't a scaffolded
    Dataface project. Intentionally attached to the root Typer only —
    sub-typer and leaf-command orders are left as authored, and
    sub-typer help never shows the banner.
    """

    def get_params(self, ctx: Any) -> list[Any]:
        def key(p: Any) -> str:
            for opt in getattr(p, "opts", ()) or ():
                if opt.startswith("--"):
                    return opt.lstrip("-").lower()
            return (p.name or "").lower()

        return sorted(super().get_params(ctx), key=key)

    def list_commands(self, ctx: Any) -> list[str]:
        # typer.rich_utils.rich_format_help iterates this list once and buckets
        # by rich_help_panel; the per-panel order is the iteration order, and
        # the panel-section order is determined by which panel gets its first
        # command first. Sort by (panel-rank, name) so PANEL_ORDER survives
        # while sub-typer groups interleave alphabetically with leaf commands
        # inside each panel.
        #
        # Rank comes from PANEL_ORDER, not registration order: Typer lists all
        # leaf commands before sub-typer groups, so a panel whose only entry is
        # a group (AI, which holds just `mcp`) would otherwise sink below every
        # panel that has a leaf command.
        panel_by_name: dict[str, str] = {}
        for n in super().list_commands(ctx):
            cmd = self.get_command(ctx, n)
            panel_by_name[n] = getattr(cmd, "rich_help_panel", None) or ""
        return sorted(
            panel_by_name,
            key=lambda n: (_panel_rank(panel_by_name[n]), n),
        )

    def format_help(self, ctx: Any, formatter: Any) -> None:
        if not has_charts_marker(Path.cwd()):
            _render_init_banner()
        super().format_help(ctx, formatter)


# `help_option_names` on the root Click context inherits down to every
# sub-Typer's group context and every leaf command, so a single setting
# here gives `-h` to the whole CLI tree.
app = typer.Typer(
    name="dct",
    help="Declarative, dbt-native dashboards in YAML.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    cls=_RootHelpGroup,
    rich_markup_mode=_RICH_MARKUP_MODE,
)


# =============================================================================
# init_app — `dct init …` subcommands (registered as a sub-typer at the bottom)
# =============================================================================


@init_app.callback(invoke_without_command=True)
def init_default(
    ctx: typer.Context,
    project_dir: ProjectDirOption = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing scaffold files"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Accept all defaults without prompting"),
    ] = False,
    skills: Annotated[
        bool | None,
        typer.Option(
            "--skills/--no-skills",
            help="Install workflow skills to agent skill directories",
        ),
    ] = None,
    mcp: Annotated[
        bool | None,
        typer.Option("--mcp/--no-mcp", help="Set up MCP server for AI assistants"),
    ] = None,
    with_playground: Annotated[
        bool | None,
        typer.Option(
            "--with-playground/--no-with-playground",
            help="Install dbt-charts[playground] extra (enables dct playground)",
        ),
    ] = None,
    vscode: Annotated[
        bool | None,
        typer.Option(
            "--vscode/--no-vscode", help="Install Dataface extension into VS Code"
        ),
    ] = None,
    cursor: Annotated[
        bool | None,
        typer.Option(
            "--cursor/--no-cursor", help="Install Dataface extension into Cursor"
        ),
    ] = None,
) -> None:
    """Bootstrap a Dataface project in an existing repo.

    Detects dbt projects, creates charts/ and charts/partials/, ejects inspect
    templates, and writes starter dashboards. Optionally wires up MCP for AI
    assistants and installs IDE extensions.

    Safe to re-run — existing files are never overwritten unless --force is used.

    Subcommands:
      dct init skills [target]  # Install workflow skills for AI assistants
      dct init mcp [client]     # Wire up MCP server
      dct init code             # Install Dataface extension into VS Code
      dct init cursor           # …or Cursor

    \b
    Examples:
      dct init                        # Init with interactive wizard
      dct init --yes                  # Accept all defaults non-interactively
      dct init --project-dir ./myrepo # Init in a specific directory
      dct init --force                # Re-scaffold, overwriting files
      dct init --no-mcp --no-vscode   # Skip MCP and IDE extension
      dct init --with-playground      # Also install dbt-charts[playground]
    """
    if ctx.invoked_subcommand is not None:
        return
    init_cmd.run_wizard(
        project_dir=project_dir,
        force=force,
        yes=yes,
        skills=skills,
        mcp=mcp,
        with_playground=with_playground,
        vscode=vscode,
        cursor=cursor,
    )


@init_app.command("code")
def init_code() -> None:
    """Install the Dataface extension into VS Code.

    Installs the latest release of the Dataface extension into VS Code.
    Idempotent — re-runs upgrade to the newest version.
    """
    raise typer.Exit(extension_cmd.install_extension("code", emit=typer.echo))


@init_app.command("cursor")
def init_cursor() -> None:
    """Install the Dataface extension into Cursor.

    Installs the latest release of the Dataface extension into Cursor.
    Idempotent — re-runs upgrade to the newest version.
    """
    raise typer.Exit(extension_cmd.install_extension("cursor", emit=typer.echo))


@init_app.command("vscode")
def init_vscode() -> None:
    """Alias for `dct init code`."""
    raise typer.Exit(extension_cmd.install_extension("code", emit=typer.echo))


# `dct init skills [target]` — file-based workflow skill install.
@init_app.command("skills")
def init_skills(
    target: Annotated[
        str | None,
        typer.Argument(
            help="Install target: agents (Cursor/Codex/Copilot), codex, or claude"
        ),
    ] = None,
    all_targets: Annotated[
        bool,
        typer.Option("--all", help="Install to every detected skill directory"),
    ] = False,
    dir_override: Annotated[
        Path | None,
        typer.Option(
            "--dir",
            help="Explicit skills directory (e.g. .agents/skills)",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing skill files"),
    ] = False,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Dry run: show what would be installed without writing files",
        ),
    ] = False,
    project_dir: ProjectDirOption = None,
) -> None:
    """Install Dataface workflow skills for file-based agent auto-discovery.

    Writes CLI-rendered skill files to ``.agents/skills/`` (Cursor, Codex,
    Copilot) and/or ``.claude/skills/`` (Claude Code). Does not configure MCP
    or modify AGENTS.md / CLAUDE.md.

    \b
    Examples:
      dct init skills                 # Detect targets and install
      dct init skills agents          # .agents/skills/ only
      dct init skills claude          # .claude/skills/ only
      dct init skills --all           # Every detected target dir
      dct init skills --dir PATH      # Explicit destination
      dct init skills --check         # Dry run
      dct init skills -f              # Overwrite existing files
    """
    _skills_run_init(
        target=target,
        all_targets=all_targets,
        dir_override=dir_override,
        force=force,
        check=check,
        project_dir=project_dir,
    )


# `dct init mcp [client]` — MCP config only (skills: `dct init skills`).
@init_app.command("mcp")
def init_mcp(
    client: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Client to configure: cursor, vscode, claude, claude-code, "
                "codex, copilot, or print. Omit to auto-detect."
            )
        ),
    ] = None,
    all_clients: Annotated[
        bool,
        typer.Option("--all", help="Write MCP config files for every supported client"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing MCP client config"),
    ] = False,
    project_dir: ProjectDirOption = None,
) -> None:
    """Add Dataface to your AI client's MCP configuration.

    Writes MCP server entries only. Install workflow skills separately with
    ``dct init skills``.

    The project root is resolved by walking up from the current directory
    looking for dbt_charts.yml or dbt_project.yml. Pass
    --project-dir to override. When the project root differs from your AI
    client's workspace, the recorded server command points at the project
    so it starts in the right place.

    \b
    Examples:
      dct init mcp                          # Auto-detect clients + project
      dct init mcp cursor                   # Configure Cursor only
      dct init mcp claude-code              # Configure Claude Code
      dct init mcp --all                    # Write every supported config file
      dct init mcp --project-dir ./analytics  # Target a specific project dir
      dct init mcp print                    # Print config JSON (for manual setup)
    """
    _mcp_run_init(
        client=client,
        all_clients=all_clients,
        force=force,
        project_dir=project_dir,
    )


# =============================================================================
# inspect_app — `dct inspect …` subcommands (registered hidden at the bottom)
# =============================================================================


@inspect_app.callback(invoke_without_command=True)
def inspect_default(
    ctx: typer.Context,
    connection: Annotated[
        str,
        typer.Option(help="Database connection string", hidden=True),
    ] = ":memory:",
    dialect: Annotated[
        str,
        typer.Option(
            help="SQL dialect (duckdb, postgres, bigquery, etc.)", hidden=True
        ),
    ] = "duckdb",
    schema: Annotated[
        str | None,
        typer.Option(help="Schema filter", hidden=True),
    ] = None,
    output: Annotated[
        str,
        typer.Option(help="Path to save inspection JSON", hidden=True),
    ] = "target/super_schema.json",
    approximate: Annotated[
        str,
        typer.Option(help="Approximate profiling mode: auto, on, off", hidden=True),
    ] = "auto",
    include: Annotated[
        str | None,
        typer.Option(help="Glob pattern to include tables", hidden=True),
    ] = None,
    exclude: Annotated[
        str | None,
        typer.Option(help="Glob pattern to exclude tables", hidden=True),
    ] = None,
) -> None:
    """Manage inspect templates and profile database tables (with dbt-charts-super-schema).

    Without subcommand: profiles all tables (requires dbt-charts-super-schema).

    \b
    Examples:
      dct inspect eject model          # Copy template to charts/inspect/
      dct inspect templates            # List built-in templates
      dct inspect table orders         # Profile a table (needs private pkg)
    """
    if ctx.invoked_subcommand is not None:
        return
    if not _SUPER_SCHEMA_AVAILABLE:
        typer.echo(
            "Batch profiling requires the dbt-charts-super-schema package.\n"
            "Install it from the monorepo or your private registry.\n\n"
            "Run 'dct inspect --help' for available template-management commands.",
            err=True,
        )
        raise typer.Exit(1)
    from dbt_charts_super_schema.cli.commands.inspect import (  # noqa: PLC0415
        inspect_all_command,
    )

    inspect_all_command(
        connection=connection,
        dialect=dialect,
        schema=schema,
        output=output,
        approximate=approximate,
        include=include,
        exclude=exclude,
    )


@inspect_app.command("eject")
def inspect_eject(
    templates: Annotated[
        list[str] | None,
        typer.Argument(help="Template names to eject (e.g., model quality)"),
    ] = None,
    all_templates: Annotated[
        bool,
        typer.Option("--all", help="Eject all available templates"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing files"),
    ] = False,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Output directory (default: charts/inspect/)"
        ),
    ] = None,
) -> None:
    """Copy inspect templates to charts/inspect/ for customization.

    Ejected templates can be modified to customize the inspect dashboards.
    The server will use your customized version instead of the built-in template.

    \b
    Examples:
      dct inspect eject model            # Eject just the model template
      dct inspect eject model quality    # Eject specific templates
      dct inspect eject --all            # Eject all templates
      dct inspect eject model --force    # Overwrite existing
      dct inspect eject --all -o custom/ # Custom output directory
    """
    inspect_cmd.eject_command(
        templates=templates or [],
        all_templates=all_templates,
        force=force,
        output_dir=output_dir,
    )


@inspect_app.command("templates")
def inspect_templates() -> None:
    """List available inspect templates.

    Shows all built-in inspect templates that can be ejected and customized.

    \b
    Examples:
      dct inspect templates
    """
    inspect_cmd.templates_command()


@inspect_app.command("validate-templates")
def inspect_validate_templates(
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Inspect template directory (default: charts/inspect/)",
        ),
    ] = None,
) -> None:
    """Validate ejected inspect templates against current built-in template versions.

    Helps teams detect when upstream template changes require rebasing custom templates.
    """
    inspect_cmd.validate_ejected_templates_command(output_dir=output_dir)


# =============================================================================
# mcp_app — `dct mcp …` subcommands (registered as a sub-typer at the bottom)
# =============================================================================


@mcp_app.command("serve")
def mcp_serve(
    project_dir: ProjectDirOption = None,
) -> None:
    """Start the MCP server for AI assistant integration.

    This command starts an MCP (Model Context Protocol) server that enables
    AI assistants like Claude, Cursor, and ChatGPT to interact with Dataface
    dashboards.

    The server speaks the MCP protocol over standard input/output — the
    transport AI clients expect.

    Requires the ``mcp`` extra (run ``dct mcp serve`` with it missing and
    the printed install command is the canonical one for your environment).

    \b
    Examples:
      dct mcp serve
      dct mcp serve --project-dir ./my-project

    \b
    Configuration for Claude Desktop (~/.config/claude/config.json):
      {
        "mcpServers": {
          "dbt-charts": {
            "command": "dct",
            "args": ["mcp", "serve"]
          }
        }
      }
    """
    # Extras gate runs before project discovery: mcp serve cannot run at all
    # without its deps, so a missing-extra install hint must win over a
    # "no project found" error when both apply.
    require_extras("mcp")
    mcp_cmd.serve_command(project_dir=project_dir)


# =============================================================================
# Root commands — grouped by panel and kept alphabetical within each block for
# readability. Neither ordering is load-bearing: `_RootHelpGroup.list_commands`
# sorts by (PANEL_ORDER rank, name), so panel order comes from PANEL_ORDER above
# and within-panel order is sorted at render time. Sub-typer add_typer() calls
# are inlined at their alphabetical positions to match.
# =============================================================================


# --- Dashboards -------------------------------------------------------------


app.add_typer(artifact_app, name="artifact", rich_help_panel="Dashboards")


@app.command("describe", rich_help_panel="Dashboards")
def describe(
    paths: Annotated[
        list[Path],
        typer.Argument(
            metavar="[PATH]...",
            help="Path(s) to board YAML files or directories to describe.",
        ),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    project_dir: ProjectDirOption = None,
) -> None:
    """Describe a dashboard's queries, charts, variables, and layout.

    Compiles the board YAML and returns a structured summary without executing
    any queries. Use this for orientation when picking up an unfamiliar dashboard.
    Accepts multiple paths; each may be a file or a directory (walked recursively).

    \b
    Examples:
      dct describe charts/sales.yml
      dct describe charts/sales.yml --json
      dct describe charts/sales.yml --project-dir ./myrepo
      dct describe charts/
      dct describe charts/*.yml --json | jq '.[] | select(.charts | length > 5)'
    """
    describe_cmd.describe_command(
        paths,
        json_output=json_output,
        project_dir=project_dir,
    )


@app.command("render", rich_help_panel="Dashboards")
def render(
    boards: Annotated[
        list[Path],
        typer.Argument(
            # No exists=/file_okay=: "-" is a valid stdin sentinel and must not fail the check.
            help='Path(s) to board YAML file(s), or "-" to read YAML from stdin (single path only)',
        ),
    ],
    output: Annotated[
        str | None,
        typer.Option(
            help=(
                "Output file path. For multiple inputs, use {stem} or {dir} "
                "placeholders (e.g. renders/{stem}.svg). Default: renders/<board>.<ext>."
            )
        ),
    ] = None,
    format: Annotated[
        RenderFormat | None,
        typer.Option(
            help="Output format: svg, html, png, pdf, terminal, json, text, yaml, or data"
        ),
    ] = None,
    project_dir: ProjectDirOption = None,
    var: Annotated[
        list[str] | None,
        typer.Option(help="Variable value as key=value (repeatable)"),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache", help="Bypass all query caches and re-run from scratch"
        ),
    ] = False,
    cache: Annotated[
        Path | None,
        typer.Option(
            "--cache",
            envvar="DCT_CACHE_PATH",
            help=(
                "Persist the query cache to this DuckDB file (created if absent). "
                "Default: falls back to dbt_charts.yml's cache: block (in-memory "
                "unless a path is configured there). Mutually exclusive with --no-cache."
            ),
        ),
    ] = None,
    diagnostics_json: Annotated[
        bool,
        typer.Option(
            "--diagnostics-json",
            help=(
                "Emit all diagnostics (errors and warnings) as JSON Lines to stderr. "
                "Stdout stays the render payload on success; stderr carries "
                "one compact JSON object per diagnostic, line-delimited."
            ),
        ),
    ] = False,
    no_warnings: Annotated[
        bool,
        typer.Option(
            "--no-warnings",
            help=(
                "Suppress warning output to stderr. Warnings are still included "
                "in --format json output so agents and consumers always see them."
            ),
        ),
    ] = False,
    ignore_warning: Annotated[
        list[str] | None,
        typer.Option(
            "--ignore-warning",
            help=(
                "Suppress a specific warning code (repeatable). Suppressed warnings "
                "move to suppressed_warnings in --format json output. "
                "Unknown codes print a notice but do not exit non-zero."
            ),
        ),
    ] = None,
    allow_chart_errors: Annotated[
        bool,
        typer.Option(
            "--allow-chart-errors",
            help=(
                "Allow per-chart runtime errors without exiting non-zero. "
                "The default (fail on chart errors) is the CI-safe behaviour: "
                "exit 1 when any chart errors are present so regressions don't "
                "ship undetected. Use --allow-chart-errors for live previews and "
                "agent iteration where partial renders are acceptable."
            ),
        ),
    ] = False,
    max_workers: Annotated[
        int | None,
        typer.Option(
            "--max-workers",
            envvar="DCT_MAX_WORKERS",
            help=(
                "Maximum parallel query workers (default: 8, from config). "
                "Effective only for external warehouse executors — DuckDB "
                "serializes access internally regardless of this setting."
            ),
        ),
    ] = None,
    print0: Annotated[
        bool,
        typer.Option(
            "--print0",
            "-0",
            help=(
                "Delimit produced output paths with NUL (\\0) instead of newline. "
                "Enables safe piping to xargs -0 for paths containing spaces."
            ),
        ),
    ] = False,
    fail_fast: Annotated[
        bool,
        typer.Option(
            "--fail-fast",
            help=(
                "Stop immediately on the first render failure. "
                "Default: continue rendering remaining boards, exit 1 at end."
            ),
        ),
    ] = False,
    chart: Annotated[
        str | None,
        typer.Option(
            "--chart",
            help=(
                "Render only this chart (by chart id). "
                "Valid only with a single board argument or stdin."
            ),
        ),
    ] = None,
) -> None:
    """Render one or more dashboards to SVG, HTML, PNG, PDF, or terminal.

    Accepts multiple board paths; output paths are printed to stdout (one per
    line) so results can be piped to other tools. Use --print0 for NUL-delimited
    output safe with xargs -0.

    Use "-" as the sole board argument to read YAML from stdin.

    By default, per-chart runtime errors (missing columns, query failures)
    cause exit 1 so CI smoke tests detect broken charts. Pass
    --allow-chart-errors to suppress this and keep the partial render
    behaviour for live previews.

    \b
    Examples:
      dct render charts/sales.yml
      dct render charts/sales.yml --format html
      dct render charts/*.yml --output renders/{stem}.svg
      dct render charts/*.yml --output renders/{stem}.svg --print0 | xargs -0 ls -lh
      dct render charts/sales.yml --var region=West --var category=Electronics
      dct render charts/sales.yml --format terminal
      dct render charts/sales.yml --no-cache
      dct render charts/sales.yml --cache renders.duckdb
      dct render charts/sales.yml --diagnostics-json
      dct render charts/sales.yml --no-warnings
      dct render charts/sales.yml --ignore-warning WARN-REDUNDANT-ENCODING
      dct render charts/sales.yml --allow-chart-errors
      echo 'charts: {c: {query: {type: csv, file: data.csv}}}' | dct render - --format terminal
    """
    if cache is not None and no_cache:
        raise typer.BadParameter(
            "--cache (or its DCT_CACHE_PATH env backing) and --no-cache are "
            "mutually exclusive",
            param_hint="--cache",
        )
    variables = parse_kv_pairs(var or [], "--var")
    use_cache = not no_cache
    ignore_codes = set(ignore_warning) if ignore_warning else None
    fail_on_chart_errors = not allow_chart_errors

    # Reject stdin mixed with other paths
    has_stdin = any(str(f) == "-" for f in boards)
    if has_stdin and len(boards) > 1:
        raise typer.BadParameter(
            '"-" (stdin) can only be used as the sole board argument',
            param_hint="BOARDS",
        )

    # Infer format from output extension when not explicitly given
    effective_format: RenderFormat = (
        format or (output and render_cmd.infer_format_from_extension(output)) or "svg"
    )

    # Reject flat --output when rendering multiple boards (ambiguous destination)
    if len(boards) > 1 and output is not None:
        if "{stem}" not in output and "{dir}" not in output:
            raise typer.BadParameter(
                f'use a template like "{{stem}}.{effective_format}" for multiple inputs; '
                f'"{output}" is ambiguous with {len(boards)} board arguments',
                param_hint="--output",
            )

    # --chart is ambiguous with multiple boards: no mapping syntax, no silent fanout.
    if chart is not None and len(boards) > 1:
        raise typer.BadParameter(
            f"--chart is only valid with a single board argument; "
            f"got {len(boards)} board arguments",
            param_hint="--chart",
        )

    # Stdin path (single board "-")
    if has_stdin:
        yaml_content = sys.stdin.read()
        if not yaml_content.strip():
            print("Error: No YAML input received from stdin", file=sys.stderr)
            raise typer.Exit(1)
        render_cmd.render_command_from_yaml(
            yaml_content=yaml_content,
            output=output,
            format=effective_format,
            project_dir=project_dir,
            variables=variables or None,
            use_cache=use_cache,
            cache_path=cache,
            diagnostics_json=diagnostics_json,
            no_warnings=no_warnings,
            ignore_codes=ignore_codes,
            fail_on_chart_errors=fail_on_chart_errors,
            max_workers=max_workers,
            print0=print0,
            chart=chart,
        )
        return

    render_cmd.render_commands(
        board_paths=boards,
        output=output,
        format=effective_format,
        project_dir=project_dir,
        variables=variables or None,
        use_cache=use_cache,
        cache_path=cache,
        diagnostics_json=diagnostics_json,
        no_warnings=no_warnings,
        ignore_codes=ignore_codes,
        fail_on_chart_errors=fail_on_chart_errors,
        max_workers=max_workers,
        print0=print0,
        fail_fast=fail_fast,
        chart=chart,
    )


@artifact_app.command("emit")
def emit_board(
    board: Annotated[
        Path,
        typer.Argument(
            help="Path to the board YAML file to compile, resolve, and execute."
        ),
    ],
    project_dir: ProjectDirOption = None,
    artifact: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Where to write the board artifact (the resolved board's "
                "published, data-free contract). Default: "
                "boards/<board-stem>.board.json."
            )
        ),
    ] = None,
    recording: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Where to write the recording sidecar (the rows the board was "
                "resolved against, plus variable values and a recorded_at "
                "stamp). Default: boards/<board-stem>.recording.json."
            )
        ),
    ] = None,
    var: Annotated[
        list[str] | None,
        typer.Option(help="Variable value as key=value (repeatable)"),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache", help="Bypass all query caches and re-run from scratch"
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Compile, resolve, and execute a board; write its board artifact + recording.

    The artifact is the resolved board's published, data-free contract; the
    recording is a separate sidecar carrying the rows it was resolved
    against. Render the pair back with `dct artifact render` — no compile step,
    no warehouse connection.

    \b
    Examples:
      dct artifact emit charts/sales.yml
      dct artifact emit charts/sales.yml --artifact out/sales.board.json --recording out/sales.recording.json
      dct artifact emit charts/sales.yml --var region=West
    """
    board_artifact_cmd.emit_board_command(
        board,
        project_dir=project_dir,
        artifact=artifact,
        recording=recording,
        var=var,
        no_cache=no_cache,
        json_output=json_output,
    )


@artifact_app.command("render")
def render_board(
    artifact: Annotated[Path, typer.Argument(help="Path to a board artifact file.")],
    recording: Annotated[
        Path, typer.Argument(help="Path to the artifact's recording sidecar.")
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Write the rendered SVG here. Default: stdout."
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Render a board from its artifact + recording — no compile, no warehouse.

    Both files come from `dct artifact emit`. A recording missing a query, or
    captured under different variable values than the artifact expects,
    fails loudly rather than rendering an empty or wrong chart.

    \b
    Examples:
      dct artifact render out/sales.board.json out/sales.recording.json
      dct artifact render out/sales.board.json out/sales.recording.json --output sales.svg
    """
    board_artifact_cmd.render_board_command(
        artifact,
        recording,
        output=output,
        json_output=json_output,
    )


@app.command("search", rich_help_panel="Dashboards")
def search(
    query: Annotated[
        str,
        typer.Argument(help="Keywords to match against dashboard metadata"),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum results to return (default 10, max 50)"),
    ] = 10,
    project_dir: ProjectDirOption = None,
) -> None:
    """Search dashboards by keyword with ranked results.

    Returns dashboards ranked by relevance to the query. Each hit includes
    the title, summary, match score, source path, and matched query/chart names.

    \b
    Examples:
      dct search revenue
      dct search "monthly trends" --limit 5
      dct search orders --json
    """
    search_cmd.search_command(
        query=query,
        json_output=json_output,
        limit=limit,
        project_dir=project_dir,
    )


@app.command("serve", rich_help_panel="Dashboards")
def serve(
    port: Annotated[
        int | None,
        typer.Option(help="Port number (auto-resolved if not set)"),
    ] = None,
    host: Annotated[
        str,
        typer.Option(help="Host address"),
    ] = "localhost",
    project_dir: ProjectDirOption = None,
    dialect: Annotated[
        str | None,
        typer.Option(help="SQL dialect (auto-detected from dbt, or duckdb)"),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option(
            help="dbt target name (default: DBT_TARGET env, then profile default)"
        ),
    ] = None,
    max_workers: Annotated[
        int | None,
        typer.Option(
            "--max-workers",
            envvar="DCT_MAX_WORKERS",
            help=(
                "Maximum parallel query workers per render (default: 8, from config). "
                "Effective only for external warehouse executors — DuckDB "
                "serializes access internally regardless of this setting."
            ),
        ),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help="Skip the query-result cache entirely (every request re-runs queries).",
        ),
    ] = False,
    cache: Annotated[
        Path | None,
        typer.Option(
            "--cache",
            envvar="DCT_CACHE_PATH",
            help=(
                "Persist the query cache to this DuckDB file (created if absent). "
                "Default: falls back to dbt_charts.yml's cache: block (in-memory "
                "unless a path is configured there). A persistent cache file "
                "supports only one writer at a time — don't share it across "
                "concurrently running servers. Mutually exclusive with --no-cache."
            ),
        ),
    ] = None,
) -> None:
    """Start the dashboard server.

    Renders your dashboards in the browser. Board file paths map
    to URLs (charts/sales.yml → /sales/). Query params become variables.

    Auto-discovers the project root by walking UP from the current directory
    to find dbt_charts.yml or dbt_project.yml. Subdirectories are not searched.
    When a dbt project is found, the SQL dialect is inferred from the profile
    target.

    dbt profile location is resolved in this order:
      1. profiles_dir field in the dbt_profile source config (dbt_charts.yml)
      2. DBT_PROFILES_DIR environment variable
      3. Project root (next to dbt_charts.yml / dbt_project.yml)
      4. ~/.dbt/profiles.yml

    Port is auto-resolved: --port flag > DCT_PORT env var > dbt_charts.yml
    server.port > deterministic hash of project directory. If the chosen port
    is occupied, the next available port is used automatically.

    The query-result cache is in-memory by default — ephemeral, discarded when
    the server exits. Pass --cache <path> to persist it across restarts.

    \b
    Examples:
      dct serve
      dct serve --port 3000
      dct serve --dialect duckdb
      dct serve --target prod
      dct serve --max-workers 16
      dct serve --cache cache.duckdb
      dct serve --no-cache
    """
    if cache is not None and no_cache:
        raise typer.BadParameter(
            "--cache (or its DCT_CACHE_PATH env backing) and --no-cache are "
            "mutually exclusive",
            param_hint="--cache",
        )
    serve_cmd.serve_command(
        port=port,
        host=host,
        project_dir=project_dir,
        dialect=dialect,
        target=target,
        max_workers=max_workers,
        no_cache=no_cache,
        cache_path=cache,
    )


@app.command("validate", rich_help_panel="Dashboards")
def validate(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(
            metavar="[PATH]...",
            help="Board YAML files or directories (default: charts/)",
        ),
    ] = None,
    project_dir: ProjectDirOption = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(help="Errors always fail; with --strict, warnings also fail."),
    ] = False,
    warehouse: Annotated[
        bool,
        typer.Option(
            "--warehouse",
            help=(
                "Validate queries against the warehouse using the per-adapter mechanism. "
                "DuckDB: DESCRIBE — schema only, no billing. "
                "BigQuery: native dry-run — validity + schema, unbilled. "
                "All other adapters report 'unchecked' — queries are never run to "
                "check them."
            ),
        ),
    ] = False,
) -> None:
    """Fast YAML schema + cross-reference validation. No DB, no execute.

    By default, validation is stateless — no warehouse connection, no query
    execution. Add --warehouse to validate queries against your warehouse using
    the cheapest per-adapter mechanism (DuckDB: DESCRIBE; BigQuery: dry-run;
    'unchecked' everywhere else). No query is ever run at full cost to check it.

    \b
    Examples:
      dct validate                              # Validate all boards in charts/
      dct validate charts/                       # Validate all boards in a directory
      dct validate charts/sales.yml              # Validate one file
      dct validate charts/*.yml                  # Shell-expanded glob
      dct validate charts/*.yml --json | jq '.[] | select(.success == false)'
      dct validate charts/sales.yml charts/orders.yml --strict
      dct validate charts/sales.yml --warehouse  # Warehouse-level validation
    """
    validate_cmd.validate_command(
        paths=paths,
        project_dir=project_dir,
        json_output=json_output,
        strict=strict,
        warehouse=warehouse,
    )


@app.command("migrate", rich_help_panel="Dashboards")
def migrate(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(
            metavar="[PATH]...",
            help="Board YAML files or directories (default: project root).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report changes without writing files."),
    ] = False,
    project_dir: ProjectDirOption = None,
) -> None:
    """Rewrite supported older board YAML syntax for the current Dataface release.

    A board has no authored schema version. Dataface recognizes its newest
    compatible retained grammar, then applies only declared lossless moves.

    \b
    Examples:
      dct migrate --dry-run
      dct migrate
      dct migrate charts/revenue.yml
      dct migrate charts/
    """
    migrate_cmd.migrate_command(
        paths,
        project_dir=project_dir,
        dry_run=dry_run,
    )


# --- Data & SQL -------------------------------------------------------------


@app.command(
    "query",
    rich_help_panel="Data & SQL",
    help="""\b
SQL and named board queries — common forms:
  dct query SOURCE 'SQL'
  dct query BOARD.yaml REFERENCE
  dct query SOURCE 'SQL' --validate
  dct query BOARD.yaml REFERENCE --describe

The first operand is the query context: a data source name, or a .yaml board file.
--file reads SQL from a file for source contexts.""",
)
def query(
    context: Annotated[
        str | None,
        typer.Argument(
            metavar="CONTEXT",
            help="Data source name, or .yaml board path",
        ),
    ] = None,
    query_text: Annotated[
        str | None,
        typer.Argument(
            metavar="QUERY",
            help="SQL string for source contexts, or query reference for .yaml boards",
        ),
    ] = None,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Static SQL lint only (works for named queries and raw SQL)",
        ),
    ] = False,
    describe: Annotated[
        bool,
        typer.Option(
            "--describe",
            help="Return column names and types (runs --validate gate first)",
        ),
    ] = False,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", metavar="PATH", help="Read SQL from file"),
    ] = None,
    dialect: Annotated[
        str | None,
        typer.Option("--dialect", help="SQL dialect for lint (duckdb, bigquery, …)"),
    ] = None,
    var: Annotated[
        list[str] | None,
        typer.Option("--var", help="Variable override as key=value (repeatable)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Max rows, execute path (default 20, max 1000)"),
    ] = 20,
    show_suppressed: Annotated[
        bool,
        typer.Option("--show-suppressed", help="Include suppressed lint diagnostics"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="JSON output"),
    ] = False,
    project_dir: ProjectDirOption = None,
) -> None:
    variables = parse_kv_pairs(var or [], "--var")

    query_cmd.query_command(
        context=context,
        query_text=query_text,
        validate=validate,
        describe=describe,
        file=file,
        dialect=dialect,
        vars=variables or None,
        limit=limit,
        show_suppressed=show_suppressed,
        json_output=json_output,
        project_dir=project_dir,
    )


# --- AI ---------------------------------------------------------------------


app.add_typer(mcp_app, name="mcp", rich_help_panel="AI")


# --- Reference --------------------------------------------------------------


@app.command("docs", rich_help_panel="Reference")
def docs(
    topic: Annotated[
        str | None,
        typer.Argument(
            help="Topic name (run `dct docs` for the index). Use 'all' for the whole reference, 'reference' for the YAML field reference, or 'errors'/'warnings' to browse diagnostic codes."
        ),
    ] = None,
    code: Annotated[
        str | None,
        typer.Argument(
            help="Diagnostic code for detail view (only used when topic is 'errors' or 'warnings')."
        ),
    ] = None,
    search: Annotated[
        str | None,
        typer.Option("--search", "-s", help="Full-text query across all topics"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            max=50,
            help="Max search hits to return (default 5, max 50)",
        ),
    ] = 5,
) -> None:
    """Browse the Dataface YAML reference offline (topics, search).

    \b
    Modes:
      dct docs                    # Topic index (one row per H2 section)
      dct docs cheatsheet         # One-page essentials
      dct docs <topic>            # Full docs for one section
      dct docs all                # Whole reference, unsliced
      dct docs reference          # Generated YAML field reference
      dct docs errors             # List all error codes
      dct docs errors <CODE>      # Full doc for one error code
      dct docs warnings           # List all warning codes
      dct docs warnings <CODE>    # Full doc for one warning code
      dct docs --search "grid"    # Substring search across all topics

    Use --json for stable, machine-readable output.
    """
    docs_cmd.docs_command(
        topic=topic,
        code=code,
        search=search,
        json_output=json_output,
        limit=limit,
    )


app.add_typer(init_app, name="init", rich_help_panel="Reference")


# Split "extra not installed" (use stub) from "extra installed but broken"
# (let the ImportError propagate) — a blanket except would swallow real
# transitive-import failures into the install-hint stub.
if importlib.util.find_spec("dbt_charts_playground") is None:

    @app.command("playground", rich_help_panel="Reference")
    def playground_not_installed() -> None:
        """Start interactive playground with YAML editor and live preview.

        Requires the ``playground`` extra.
        """
        require_extras("playground")

else:
    from dbt_charts_playground.cli import main as _playground_main

    app.command("playground", rich_help_panel="Reference")(_playground_main)


@app.command("skills", rich_help_panel="Reference")
def skills(
    skill_name: Annotated[
        str | None,
        typer.Argument(help="Skill name to show (default: list all)"),
    ] = None,
    search: Annotated[
        str | None,
        typer.Option("--search", "-s", help="Search names, descriptions, and bodies"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=25, help="Max search hits (default 10)"),
    ] = 10,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """List packaged agent skills, search them, or show one by name.

    \b
    Modes:
      dct skills                  # List all skills (grouped: workflows + patterns)
      dct skills <name>           # Show the named skill body
      dct skills -s "<query>"     # Search names, descriptions, and bodies
      dct skills --json           # Stable JSON for any of the above

    Skills are agent workflows and layout patterns. For YAML field reference,
    use `dct docs` instead.
    """
    skills_cmd.skills_command(
        name=skill_name,
        search=search,
        limit=limit,
        as_json=as_json,
    )


# Hidden — not shown in root help
app.add_typer(inspect_app, name="inspect", hidden=True)

# Load CLI plugins registered via [project.entry-points."dbt_charts.cli_plugins"].
# Each plugin's ``register()`` callable mounts its subcommands onto Typer apps
# (e.g. ``inspect_app``) before the app executes. Runs at import time so that
# ``dct --help`` shows profiler commands when the private package is installed.
# importlib.metadata is stdlib since Python 3.8; dataface requires >=3.10, so
# the outer try is unnecessary. Plugin load errors surface to the user rather
# than being silently swallowed.
from importlib.metadata import entry_points as _entry_points

for _ep in _entry_points(group="dbt_charts.cli_plugins"):
    _plugin = _ep.load()
    _plugin()


def _reconfigure_console_encoding() -> None:
    """Force UTF-8 on stdout/stderr so non-ASCII diagnostics never crash.

    Windows consoles default to the legacy cp1252 codepage; printing
    non-ASCII text (e.g. an arrow in an error message) would otherwise raise
    UnicodeEncodeError while reporting the original error. No-op on
    Linux/macOS, where the streams are already UTF-8. Streams without
    reconfigure() — e.g. one swapped in under test capture — are left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from dbt_charts.cli._version_info import collect

        typer.echo(collect().render())
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            help="Print version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """dct - Declarative, dbt-native dashboards in YAML."""
    _reconfigure_console_encoding()
    # Runs before any subcommand, so every warehouse query this process sends is
    # attributed to the CLI. `dct serve` narrows it to "serve" in its own command.
    set_surface("cli")


if __name__ == "__main__":
    app()
