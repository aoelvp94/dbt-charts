"""SVG chart text selectability — cursor and ::selection CSS rules.

All chart text must show cursor:text so users know it is selectable. Interaction,
so it ships in the host stylesheet beside the runtime, never inside a board.
"""

from dbt_charts.core.render.controls import controls_stylesheet


def test_chart_text_cursor_is_text() -> None:
    styles = controls_stylesheet()
    assert ".dbt-chart text" in styles
    assert "cursor: text" in styles
    # pointer-events: auto overrides the inherited none from Vega's <g pointer-events="none">
    assert "pointer-events: auto" in styles


def test_chart_text_selection_highlight_present() -> None:
    styles = controls_stylesheet()
    assert ".dbt-chart text::selection" in styles
    assert "background:" in styles
