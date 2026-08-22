"""Chart focus utilities.

This module provides the `focus_on_chart()` function for rendering a single
chart from a board. It transforms a compiled board to show only one chart
with its dependent variables.

There are two ways to focus on a chart:

1. **YAML field** (recommended for users):
   Add `chart_focus: chart_id` to your board YAML.
   The compiler will automatically apply the focus during normalization.

   ```yaml
   title: Sales Board
   chart_focus: revenue_chart  # Render only this chart
   charts:
     revenue_chart:
       query: sales
       type: bar
   rows:
     - revenue_chart
   ```

2. **Python API** (for programmatic use):
   ```python
   from dbt_charts.core.compile import compile, focus_on_chart

   result = compile(yaml_content)
   focused = focus_on_chart(result.board, "revenue_chart")
   render(focused, executor, format="svg")
   ```

Use cases:
- Chart editing (focus on one chart while editing)
- Export single chart (SVG/PNG/PDF)
- Embed a single chart in another page
"""

from dbt_charts.core.compile.models.board.authored import LayoutType
from dbt_charts.core.compile.models.board.normalized import (
    Board,
    Layout,
    LayoutItem,
)
from dbt_charts.core.compile.sizing import chart_slot_width


def focus_on_chart(board: Board, chart_id: str) -> Board:
    """Transform a compiled board to focus on a single chart.

    Creates a new board with:
    - Only the specified chart in the layout
    - Only the variables that chart depends on
    - The chart pinned at the slot width the dashboard layout assigned it,
      so the focused render is geometry-identical to the dashboard (WYSIWYG);
      a chart not placed in the layout keeps its preferred width
    - All sources and queries unchanged (they're lazy-loaded anyway)

    This is called automatically when `chart_focus` is set in the YAML.
    It can also be called directly for programmatic chart focusing.

    Args:
        board: The compiled board containing the chart
        chart_id: The ID of the chart to focus on

    Returns:
        A new Board with simplified layout and filtered variables

    Raises:
        ValueError: If the chart is not found

    Example:
        >>> result = compile(yaml_content)
        >>> focused = focus_on_chart(result.board, "revenue_chart")
        >>> render(focused, executor, format="svg")
    """
    # Find the chart - all charts (including inline) are now in board.charts
    chart = board.charts.get(chart_id)
    if chart is None:
        available_charts = (
            ", ".join(sorted(board.charts.keys())) if board.charts else "none"
        )
        raise ValueError(
            f"Chart '{chart_id}' not found in board. Available charts: {available_charts}"
        )

    # Filter variables to only those the chart needs.
    # variable_dependencies is declared on every Chart family.
    focused_variables = {
        name: var
        for name, var in board.variables.items()
        if name in chart.variable_dependencies
    }

    # Pin the dashboard slot width so the focused chart keeps the exact
    # geometry it had on the board (band widths, axis-label fit). The board
    # container hugs the pinned width the same way it hugs preferred widths.
    slot_width = chart_slot_width(board, chart_id)
    chart_item = LayoutItem(
        type="chart",
        chart=chart,
        user_width=None if slot_width is None else f"{slot_width}px",
    )
    simple_layout = Layout(type=LayoutType.ROWS, items=[chart_item])

    # Create new board with focused content
    # No title - this is a focused view, not a board
    focused_board = board.model_copy(
        update={
            "variables": focused_variables,
            "layout": simple_layout,
            "title": "",
        }
    )

    return focused_board
