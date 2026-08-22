"""Boolean conditions authored in YAML — ``enabled``, ``visible``.

Stage: RENDER
Purpose: Turn a bool, a Jinja expression, or a single-row query probe into the
yes/no a renderer needs.

Three surfaces share this: a variable's ``enabled``, a layout item's
``visible``, and the terminal renderer's copy of the same question. They differ
only in what a missing condition means, which is why ``if_none`` is a parameter
rather than a default baked in here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dbt_charts.core.compile.template.jinja import resolve_jinja_template

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.variable.authored import SingleRowBoolProbe
    from dbt_charts.core.execute.chart_data_provider import ChartDataProvider


def coerce_bool(value: Any) -> bool:
    """Coerce value to bool; raise ValueError for unrecognized inputs."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in ("true", "1", "yes"):
            return True
        if lower in ("false", "0", "no"):
            return False
    raise ValueError(f"Cannot coerce {value!r} to bool; expected true/false/1/0/yes/no")


def eval_bool_condition(
    expr: bool | str | SingleRowBoolProbe | None,
    if_none: bool,
    current_values: dict[str, Any],
    executor: ChartDataProvider | None,
    context: str,
) -> bool:
    """Evaluate a bool/str/probe condition and return the result.

    Shared core for Variable.enabled and LayoutItem.visible; callers pass
    ``if_none`` to control the meaning of a missing (None) value.

    - None: return ``if_none`` (enabled → True, visible → True).
    - bool: return as-is.
    - str: auto-wrap in ``{{ }}`` if needed, evaluate as Jinja, coerce to bool.
    - SingleRowBoolProbe: execute the named query; expect exactly 1 row; coerce
      the named column to bool.

    Args:
        expr: The condition value (from YAML or a compiled model field).
        if_none: Value to return when expr is None.
        current_values: Current variable values for Jinja resolution.
        executor: Required when expr is a SingleRowBoolProbe.
        context: Human-readable label for error messages (e.g. "Variable 'region' disabled").

    Raises:
        ValueError: Wrong row count, missing column, non-bool-coercible value, or
            no executor for a query-backed condition.
    """
    if expr is None:
        return if_none
    if isinstance(expr, bool):
        return expr
    if isinstance(expr, str):
        # Auto-wrap bare variable names / Jinja expressions (no {{ }} required).
        jinja_expr = expr if "{{" in expr else f"{{{{ {expr} }}}}"
        rendered = resolve_jinja_template(jinja_expr, variables=current_values)
        return coerce_bool(rendered)
    if executor is None:
        raise ValueError(
            f"{context} query '{expr.query}' requires an executor but none was provided"
        )
    rows = executor.execute_query(expr.query, current_values)
    if not rows:
        raise ValueError(
            f"{context} query '{expr.query}' returned no rows; expected exactly 1"
        )
    if len(rows) > 1:
        raise ValueError(
            f"{context} query '{expr.query}' returned {len(rows)} rows; expected exactly 1"
        )
    row = rows[0]
    if expr.column not in row:
        raise ValueError(
            f"{context} query '{expr.query}' has no column '{expr.column}'; "
            f"available: {list(row.keys())}"
        )
    return coerce_bool(row[expr.column])


def evaluate_visible(
    expr: bool | str | SingleRowBoolProbe | None,
    current_values: dict[str, Any],
    executor: ChartDataProvider | None,
    context: str = "layout item",
) -> bool:
    """Return True when the layout item should be rendered.

    Args:
        expr: The visible value from the layout item.
        current_values: Current variable values for Jinja resolution.
        executor: Required when expr is a SingleRowBoolProbe.
        context: Human-readable label for error messages (e.g. "layout item 'kpi_a'").
    """
    return eval_bool_condition(
        expr,
        True,
        current_values,
        executor,
        f"{context} visible",
    )
