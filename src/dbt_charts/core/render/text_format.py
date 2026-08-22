"""Text render output format for AI agents.

Templates the dict produced by board_to_dict into compact markdown text.
"""

from typing import Any

from dbt_charts.core.compile.models.board.normalized import (
    Board,
    VariableValues,
)
from dbt_charts.core.diagnostics import Diagnostic
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.render.board_to_dict import (
    NO_ROW_CAP,
    board_to_dict,
    kept_rows_phrase,
)


def render_board_text(
    board: Board,
    executor: Executor,
    variables: VariableValues,
    error_collector: list[Diagnostic] | None = None,
    max_rows_per_query: int = NO_ROW_CAP,
) -> str:
    """Render a compiled board to compact markdown text for AI agents."""
    d = board_to_dict(board, executor, variables, error_collector, max_rows_per_query)
    lines: list[str] = []
    _render_board(d, lines, depth=1)
    return "\n".join(lines)


def _render_board(board: dict[str, Any], lines: list[str], depth: int) -> None:
    """Render a board dict to markdown lines at the given heading depth."""
    title = board.get("title") or board.get("id", "Untitled")
    lines.append(f"{'#' * depth} {title}")
    for item in board.get("items", []):
        if item["type"] == "chart":
            _render_chart(item, lines, depth + 1)
        elif item["type"] == "board":
            lines.append("")
            _render_board(item["board"], lines, depth + 1)


def _render_chart(item: dict[str, Any], lines: list[str], depth: int) -> None:
    """Render a chart item to markdown lines."""
    # Chart error: emit a compact error line instead of data
    if "_error" in item:
        err = item["_error"]
        code = err.get("code", "")
        msg = err.get("message", "error")
        chart_id = err.get("fields", {}).get("chart_id", "unknown")
        lines.append(f"\n[chart error: {code} {msg} (chart: {chart_id})]")
        return

    chart = item["chart"]
    data = item.get("data", [])

    chart_type = chart.get("chart_type", "unknown")
    title = chart.get("title") or chart.get("id", "chart")
    lines.append("")
    lines.append(f"{'#' * depth} {title} ({chart_type})")

    # KPI: show value, optionally resolved against the bound row when the
    # authored value is a column reference.
    if chart_type == "kpi":
        raw = chart.get("value")
        cell = (
            data[0].get(raw)
            if isinstance(raw, str) and data and raw in data[0]
            else raw
        )
        if isinstance(cell, (int, float)):
            display = f"{cell:,}" if cell == int(cell) else f"{cell:,.2f}"
        elif cell is not None:
            display = str(cell)
        else:
            display = ""
        if display:
            lines.append(f"- value: {display}")
        return

    # Field mappings
    fields = _field_mappings(chart)
    if fields:
        lines.append(f"- {', '.join(fields)}")

    # Data summary
    if data:
        summary = _data_summary(chart, data, item.get("rows_truncated", {}))
        if summary:
            lines.append(f"- {summary}")


def _field_mappings(chart: dict[str, Any]) -> list[str]:
    """Extract field mapping strings like 'x: month, y: revenue'."""
    mappings = []
    for key in ("x", "y", "color", "size", "theta", "value"):
        val = chart.get(key)
        if val:
            mappings.append(f"{key}: {val}")
    return mappings


def _data_summary(
    chart: dict[str, Any],
    data: list[dict[str, Any]],
    rows_truncated: dict[str, int],
) -> str:
    """Build a compact data summary string."""
    if rows_truncated:
        parts = [f"showing {kept_rows_phrase(rows_truncated)}"]
    else:
        parts = [f"{len(data)} rows"]

    # Collect chart field names by role
    field_roles: dict[str, str] = {}
    for key in ("x", "y", "color", "size", "theta"):
        val = chart.get(key)
        if val:
            field_roles[val] = key

    for col, role in field_roles.items():
        values: list[Any] = [row[col] for row in data if row.get(col) is not None]
        if not values:
            continue
        if all(isinstance(v, (int, float)) for v in values) and role in (
            "y",
            "size",
            "theta",
        ):
            lo, hi = min(values), max(values)
            parts.append(f"{col}: {lo}–{hi}")
        elif all(isinstance(v, str) for v in values) and role in ("x", "color"):
            distinct = sorted(set(values))
            if len(distinct) <= 5:
                parts.append(f"{col}: {', '.join(distinct)}")
            else:
                parts.append(f"{col}: {len(distinct)} distinct")

    return " | ".join(parts)
