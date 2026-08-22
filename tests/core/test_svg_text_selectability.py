"""SVG chart text selectability — cursor and ::selection CSS rules.

All chart text must show cursor:text so users know it is selectable.
"""

from dbt_charts.core.render.svg_utils import generate_svg_styles


def test_chart_text_cursor_is_text() -> None:
    styles = generate_svg_styles(emoji_mode="disabled", font_face_css="")
    assert ".dbt-chart text" in styles
    assert "cursor: text" in styles
    # pointer-events: auto overrides the inherited none from Vega's <g pointer-events="none">
    assert "pointer-events: auto" in styles


def test_chart_text_selection_highlight_present() -> None:
    styles = generate_svg_styles(emoji_mode="disabled", font_face_css="")
    assert ".dbt-chart text::selection" in styles
    assert "background:" in styles
