"""Drive the strip renderer the way a board render does.

Production resolves variables once and hands the result to the strip; a test
that wants SVG for a bare ``Variable`` has to do the same resolution step, so
none smuggles in an unresolved control the renderer would never see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dbt_charts.core.render.variables_resolve import resolve_controls
from dbt_charts.core.render.variables_strip import (
    StripAlign,
    render_variables_strip_svg,
)

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.style.resolved import ResolvedStyle
    from dbt_charts.core.compile.models.variable.authored import Variable
    from dbt_charts.core.execute.chart_data_provider import ChartDataProvider


def render_strip_for(
    variable_defs: dict[str, Variable],
    current_values: dict[str, Any],
    width: float,
    executor: ChartDataProvider | None,
    resolved_style: ResolvedStyle,
    align: StripAlign = "start",
    *,
    variables_path: str,
) -> tuple[str, float]:
    """The SVG strip for these variable definitions, plus its band height.

    `variables_path` has no default for the reason the renderer's own signature
    gives: defaulting it stamps an authored handle on the case that must not
    carry one, and a test that forgot to think about it would still pass.
    """
    return render_variables_strip_svg(
        resolve_controls(
            variable_defs, current_values, executor, resolved_style.variables
        ),
        width,
        resolved_style,
        align,
        variables_path=variables_path,
    )
