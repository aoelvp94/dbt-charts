"""The hover-emphasis switch reaches the runtime, and its strength stays engine-side.

Two surfaces, two owners, and the split is the point: a theme decides whether
hover emphasis happens at all, while how far a demoted mark recedes is ours to
tune. A regression that quietly moved the strength into the theme cascade would
still render correctly, so it is pinned here rather than left to review.
"""

from __future__ import annotations

import re

import pytest

from dbt_charts.core.compile.config import (
    get_chart_rendering,
    get_theme_style,
    reset_config,
)
from dbt_charts.core.compile.models.style.theme.charts import HoverEmphasisStyle
from dbt_charts.core.compile.resolve.style.board import resolve_style
from dbt_charts.core.render.chart_interactivity import (
    _build_hover_emphasis_dict,
    generate_chart_interactivity_source,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_config()


def test_theme_provides_the_switch_board_wide() -> None:
    """Every theme answers the question; the answer itself is the theme's business."""
    resolved = resolve_style(get_theme_style("stark"))
    assert isinstance(resolved.chart_defaults.hover_emphasis.visible, bool)


def test_strength_is_engine_config_not_a_theme_value() -> None:
    """The theme owns the switch and the drop-line paint; the strength stays ours to tune.

    ``model_fields`` is the whole contract: a ``dimmed_opacity`` added to the
    theme model lands there, and the engine value would quietly stop being the
    one that decides.
    """
    assert set(HoverEmphasisStyle.model_fields) == {
        "visible",
        "drop_line_color",
        "drop_line_width",
    }
    # Bounds, not type: an opacity outside (0, 1) is the failure that matters,
    # and the type is already declared.
    assert 0 < get_chart_rendering().hover_emphasis.dimmed_opacity < 1


def test_runtime_dict_carries_the_switch_and_the_strength() -> None:
    resolved = resolve_style(get_theme_style("stark"))
    blob = _build_hover_emphasis_dict(resolved)

    assert blob == {
        "visible": resolved.chart_defaults.hover_emphasis.visible,
        "opacity": get_chart_rendering().hover_emphasis.dimmed_opacity,
        "dropLineColor": resolved.chart_defaults.hover_emphasis.drop_line_color,
        "dropLineWidth": resolved.chart_defaults.hover_emphasis.drop_line_width,
    }


@pytest.mark.parametrize("theme", ["clarity", "paper", "stark", "vivid", "neon"])
def test_runtime_dict_carries_each_themes_own_drop_line_color_and_width(
    theme: str,
) -> None:
    """Each theme's own resolved drop-line paint reaches the runtime dict.

    Structural, not value-pinned (dbt-charts/AGENTS.md: don't pin theme
    literals) -- this guards the plumbing, not the designer's color/width
    picks. It compares the builder's output against the same ``resolved``
    object the builder was given, so it does not by itself prove the
    argument is what gets read rather than some other fixed source --
    ``test_an_authored_drop_line_override_reaches_the_rendered_runtime``
    below is the one that proves that, with a value no theme owns.
    """
    resolved = resolve_style(get_theme_style(theme))
    blob = _build_hover_emphasis_dict(resolved)

    assert (
        blob["dropLineColor"] == resolved.chart_defaults.hover_emphasis.drop_line_color
    )
    assert (
        blob["dropLineWidth"] == resolved.chart_defaults.hover_emphasis.drop_line_width
    )


def test_an_authored_switch_reaches_the_rendered_runtime() -> None:
    """Turning it off in a board has to arrive in the script the board ships.

    Asserted on the rendered SVG rather than on the resolver, because every
    stage between the two is a place the value could be stranded, and none of
    them would look wrong: nothing in the rendered SVG depends on the switch,
    so a board whose switch never arrived renders identically to one whose
    switch did.
    """
    from ._svg_render import render_board_to_svg

    on = render_board_to_svg(_BOARD)
    off = render_board_to_svg(_BOARD + _SWITCH_OFF)

    assert '"visible": true' in on
    assert '"visible": false' in off


_DROP_LINE_OVERRIDE = """
style:
  charts:
    hover_emphasis:
      drop_line_color: "#4b0082"
      drop_line_width: 12.75
"""


def test_an_authored_drop_line_override_reaches_the_rendered_runtime() -> None:
    """A board-level drop-line override reaches the runtime dict verbatim.

    The sentinel color/width below are values no built-in theme owns, so a
    match proves ``_build_hover_emphasis_dict`` read the ``resolved_style``
    it was actually given rather than some other fixed source -- which the
    theme-parametrized tests above cannot rule out, since they compare the
    builder's output to the same object they handed it.
    """
    from ._svg_render import render_board_to_svg

    svg = render_board_to_svg(_BOARD + _DROP_LINE_OVERRIDE)

    assert '"dropLineColor": "#4b0082"' in svg
    assert '"dropLineWidth": 12.75' in svg


def test_source_substitutes_the_hover_emphasis_placeholder() -> None:
    source = generate_chart_interactivity_source(
        resolve_style(get_theme_style("stark"))
    )

    assert "__DCT_HOVER_EMPHASIS__" not in source
    assert "const DCT_HOVER_EMPHASIS =" in source


_BOARD = """
title: T
queries:
  q:
    type: values
    rows:
      - {cat: A, val: 10}
      - {cat: B, val: 4}
charts:
  c:
    query: q
    type: bar
    x: cat
    y: val
rows:
  - c
"""
_SWITCH_OFF = "style:\n  charts:\n    hover_emphasis:\n      visible: false\n"


def _chart_markup(yaml: str) -> str:
    """Rendered SVG, normalized for everything that is not the board's own geometry.

    Three things legitimately differ between two renders and none of them is
    what this comparison is about: the injected runtime (carrying the switch is
    its whole job), ``data-rendered-at`` (a wall clock), and Vega's clipPath ids
    (a process-global counter, so the second render in a process is offset from
    the first). The ids are renumbered in order of appearance rather than erased,
    so a genuine change in which clip a node references still fails this.
    """
    from ._svg_render import render_board_to_svg

    svg = re.sub(r"<script.*?</script>", "", render_board_to_svg(yaml), flags=re.S)
    svg = re.sub(r'data-rendered-at="[^"]*"', "", svg)
    seen: dict[str, str] = {}
    return re.sub(
        r"clip\d+", lambda m: seen.setdefault(m.group(0), f"clip{len(seen)}"), svg
    )


def test_the_switch_changes_no_rendered_markup() -> None:
    """Turning hover emphasis off must not re-render the board differently.

    Hover emphasis lives entirely in the runtime; render emits nothing for it.
    If this fails, someone has made static SVG depend on an interaction setting
    static SVG cannot express, and the same board now renders two different
    files.
    """
    assert _chart_markup(_BOARD) == _chart_markup(_BOARD + _SWITCH_OFF)
