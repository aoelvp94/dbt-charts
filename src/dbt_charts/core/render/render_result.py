"""RenderResult — the return type of render()."""

from pydantic import BaseModel

from dbt_charts.core.diagnostics import Diagnostic


class RenderResult(BaseModel):
    output: str | bytes | None = None
    chart_errors: list[Diagnostic] = []
    board_error: Diagnostic | None = None
    warnings: list[Diagnostic] = []
    suppressed_warnings: list[Diagnostic] = []
