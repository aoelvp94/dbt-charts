"""Typed dashboard verbs for the Dataface agent API.

All public functions have concrete typed arguments and typed Pydantic return
values. No bare dict[str, Any] in any return position. Tool/CLI callers use
.model_dump() at the wire boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from dbt_charts.agent_api._paths import resolve_board_or_error
from dbt_charts.agent_api.query import (
    VariableBinding,
    variables_to_dict as _vars_to_dict,
)
from dbt_charts.core.board import BoardRenderResult as BoardRenderResult
from dbt_charts.core.compile import Board, compile_file
from dbt_charts.core.diagnostics import Diagnostic
from dbt_charts.core.project import (
    CHARTS_SUBDIR,
    Project,
    ProjectDirectory,
    ProjectPath,
)

# Top-level keys whose presence classifies a YAML mapping as a dashboard.
DASHBOARD_KEYS = frozenset({"queries", "charts", "rows", "cols", "grid", "tabs"})

# ---------------------------------------------------------------------------
# Return-type models
# ---------------------------------------------------------------------------


class BoardSummary(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True, populate_by_name=True, frozen=True
    )

    file: ProjectPath = Field(serialization_alias="path")
    title: str
    description: str = ""
    queries: list[str] = []
    charts: list[str] = []
    variables: list[str] = []

    @field_serializer("file")
    def _serialize_file(self, pf: ProjectPath) -> str:
        return pf.relpath


class SkippedFile(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True, populate_by_name=True, frozen=True
    )

    file: ProjectPath = Field(serialization_alias="path")
    reason: str

    @field_serializer("file")
    def _serialize_file(self, pf: ProjectPath) -> str:
        return pf.relpath


class ListBoardsResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    success: bool
    errors: list[Diagnostic] = []
    boards: list[BoardSummary] = []
    count: int = 0
    directory: ProjectDirectory
    skipped_files: list[SkippedFile] = []

    @field_serializer("directory")
    def _serialize_directory(self, d: ProjectDirectory) -> str:
        return d.relpath


class CompiledBoard(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    board: Board | None = None
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    raw_yaml: str | None = None


class RenderBoardArgs(BaseModel):
    """Validate, compile, and render a Dataface dashboard, returning resolved chart semantics + executed data for reasoning. Use this to verify YAML is valid, inspect query results, and iterate on a dashboard. When 'path' is provided, the response also includes a localhost URL the user can open in a browser to view the live dashboard (from the embedded HTTP server used by agent sessions). Pass `as_link=true` with a path to skip execution and return only the preview URL."""

    path: Path | None = Field(
        None,
        description=(
            "Path to dashboard YAML file (use this OR yaml_content). "
            "Board-relative (no charts/ prefix needed, e.g. 'looker/x.yaml') or "
            "root-relative (e.g. 'charts/looker/x.yaml') both resolve. If the "
            "path came from search_boards, use the hit's board_path."
        ),
    )
    yaml_content: str | None = Field(
        None, description="YAML content to render directly (use this OR path)"
    )
    chart: str | None = Field(
        None,
        description=(
            "Render only this chart (by chart id) from the dashboard, with its "
            "dependent variables. Use to show one existing chart that answers "
            "a question instead of re-deriving its query — the rendered chart "
            "keeps the dashboard's canonical definition. Unknown ids fail with "
            "the list of available chart ids."
        ),
    )
    variables: list[VariableBinding] | None = Field(
        None,
        description=(
            "Variable values to apply to the dashboard, as an array of {name, value} pairs. "
            'Example: [{"name": "region", "value": "US"}, {"name": "year", "value": 2024}]'
        ),
    )
    format: Literal["json", "text", "yaml", "svg", "terminal", "data"] | None = Field(
        None,
        description=(
            "Output format. 'json' (default) returns the full resolved chart "
            "semantics and executed data as structured JSON, nested by "
            "layout. 'data' returns a flatter, narrower view: 'queries' "
            "keyed by query name (sql, plus one copy of the rows) and "
            "'charts' keyed by slug carrying title/description/type and "
            "encoding, each referencing its query by name. It drops the "
            "layout nesting, repeats no rows across charts that share a "
            "query, and reports the variable values the rows were produced "
            "with — but emits only the authored chart fields, not every "
            "resolved one, so prefer 'json' when you need the full chart. "
            "'text' "
            "returns a compact markdown summary of charts and data "
            "(most token-efficient). 'yaml' returns resolved Dataface "
            "YAML with inline data — valid input for re-compilation, "
            "ideal for round-trip editing. 'svg' returns the rendered "
            "dashboard as inline SVG (under result['data']) for hosts "
            "that embed the rendered output directly. 'terminal' returns "
            "the charts as ANSI text (under result['data']) for display "
            "in a terminal."
        ),
    )
    as_link: bool = Field(
        False,
        description=(
            "When true and 'path' is provided, skip query execution and return only "
            "the preview URL. Use this to surface an existing dashboard in the browser "
            "without paying the render cost — replaces the old view_dashboard tool."
        ),
    )

    @model_validator(mode="after")
    def _no_duplicate_variable_names(self) -> Self:
        if self.variables is not None:
            _vars_to_dict(self.variables)
        return self


# ---------------------------------------------------------------------------
# Public verbs
# ---------------------------------------------------------------------------


def list_boards(
    project: Project,
    *,
    under: str = CHARTS_SUBDIR,
    recursive: bool = True,
) -> ListBoardsResult:
    """List all available dashboards in a project."""
    dashboards: list[BoardSummary] = []
    skipped: list[SkippedFile] = []

    for pf in project.iter_boards(under=under, recursive=recursive):
        if not pf.is_yaml:
            continue
        try:
            content = yaml.safe_load(pf.read_text())
            if not isinstance(content, dict):
                skipped.append(SkippedFile(file=pf, reason="Not a YAML mapping"))
                continue
            if not any(key in content for key in DASHBOARD_KEYS):
                continue
            stem = pf.stem
            dashboards.append(
                BoardSummary(
                    file=pf,
                    title=content.get("title", stem),
                    description=content.get("description", ""),
                    queries=list(content.get("queries", {}).keys()),
                    charts=list(content.get("charts", {}).keys()),
                    variables=list(content.get("variables", {}).keys()),
                )
            )
        except yaml.YAMLError as e:
            skipped.append(SkippedFile(file=pf, reason=f"YAML parse error: {e}"))
        except OSError as e:
            skipped.append(SkippedFile(file=pf, reason=f"Read error: {e}"))

    return ListBoardsResult(
        success=True,
        boards=dashboards,
        count=len(dashboards),
        directory=project.directory(under),
        skipped_files=skipped,
    )


def get_board(
    path: Path,
    *,
    project: Project,
    include_raw: bool = False,
) -> CompiledBoard:
    """Get the compiled structure of a dashboard."""
    # One boards-first resolve/exists/is-file seam, shared with the render path.
    board = resolve_board_or_error(path, project)
    if isinstance(board, Diagnostic):
        return CompiledBoard(success=False, errors=[board])
    result = compile_file(board)

    return CompiledBoard(
        success=result.success,
        board=result.board if result.success else None,
        errors=list(result.errors),
        warnings=result.warnings,
        raw_yaml=board.content if include_raw else None,
    )
