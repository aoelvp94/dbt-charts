"""Test that dark themes apply correct table colors via resolved_style.

The base theme (config.style) provides light defaults. When a board specifies
theme=neon, resolved_style should reflect the dark theme's table colors.
"""

import pytest

from dbt_charts.core.compile import compile
from dbt_charts.core.compile.config import reset_config


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def test_dark_theme_board_resolved_style_has_dark_table_colors():
    """A board with theme=neon should have dark table colors in resolved_style."""
    yaml_content = """\
theme: neon
style:
  background: "#161616"
rows:
  - text: hello
"""
    dark_yaml = """\
rows:
  - text: hello
"""
    dark_result = compile(yaml_content)
    light_result = compile(dark_yaml)
    assert dark_result.board is not None
    assert light_result.board is not None

    dark_table = dark_result.board.chart_style_context.table
    light_table = light_result.board.chart_style_context.table

    # Dark theme header background must differ from the light theme header background
    assert dark_table.header.background != light_table.header.background, (
        f"Dark and light themes must have different header.background; "
        f"dark={dark_table.header.background!r}, light={light_table.header.background!r}"
    )
    # Dark theme row stripe must be set
    assert dark_table.row.stripe is not None, "Dark theme should set row.stripe"


def test_light_theme_board_resolved_style_has_light_table_colors():
    """Default (light) theme should have light table colors."""
    yaml_content = """\
rows:
  - text: hello
"""
    result = compile(yaml_content)
    assert result.board is not None

    table = result.board.chart_style_context.table

    # Universal default is "header rule only" — no header background fill.
    # See tests/core/test_default_table_scaffold.py for the full rationale.
    assert table.header.background is None
