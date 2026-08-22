"""Tests for accent/muted board-to-board cascade on Style/ResolvedStyle.

ADR-003/ADR-009: accent and muted are semantic color tokens defined on Style.
They live at root level (1d), cascade to sub-fields within a board (_apply_token_cascade),
and cascade from parent board to child board via compile_board_resolved_style() (1c).

background is a box property and does NOT cascade.
"""

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.style.authored import StylePatch
from dbt_charts.core.compile.models.style.resolved import ResolvedStyle
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)

# ---------------------------------------------------------------------------
# Style — field presence and defaults
# ---------------------------------------------------------------------------


def test_compiled_style_accepts_muted():
    s = get_theme_style().model_copy(update={"muted": "#888888"})
    assert s.muted == "#888888"


def test_compiled_style_accepts_accent():
    s = get_theme_style().model_copy(update={"accent": "#ff0000"})
    assert s.accent == "#ff0000"


# ---------------------------------------------------------------------------
# resolve_style — passthrough into ResolvedStyle
# ---------------------------------------------------------------------------


def test_resolve_style_muted_passthrough():
    resolved = resolve_style(get_theme_style().model_copy(update={"muted": "#888888"}))
    assert resolved.muted == "#888888"


def test_resolve_style_accent_passthrough():
    resolved = resolve_style(get_theme_style().model_copy(update={"accent": "#3b82f6"}))
    assert resolved.accent == "#3b82f6"


def test_resolve_style_muted_via_patch():
    patch = StylePatch.model_validate({"muted": "#aabbcc"})
    resolved = resolve_style(get_theme_style(), patch)
    assert resolved.muted == "#aabbcc"


def test_resolve_style_accent_via_patch():
    patch = StylePatch.model_validate({"accent": "#ff0000"})
    resolved = resolve_style(get_theme_style(), patch)
    assert resolved.accent == "#ff0000"


def test_resolve_style_returns_resolved_style_type_with_tokens():
    resolved = resolve_style(
        get_theme_style().model_copy(update={"muted": "#888888", "accent": "#3b82f6"})
    )
    assert isinstance(resolved, ResolvedStyle)
    assert resolved.muted == "#888888"
    assert resolved.accent == "#3b82f6"


# ---------------------------------------------------------------------------
# Compile cascade — token values reach spark sub-fields via _apply_token_cascade
# NOTE: these verify the resolved compile output, NOT SVG renderer output.
# The renderer reads bar.background via resolved_style.spark_bar.bar.background.
# ---------------------------------------------------------------------------


def test_muted_does_not_cascade_to_spark_bar_track():
    """muted is the secondary-text token; the track fill stays theme-pinned."""
    base = get_theme_style()
    patched = base.model_copy(update={"muted": "#ff00ff"})
    resolved = resolve_style(patched)
    assert resolved.muted == "#ff00ff"
    ctx = resolve_chart_style_context(patched)
    assert ctx.spark_bar.bar.background == base.charts.spark_bar.bar.background


def test_single_series_palette_cascades_to_resolved_spark_bar_color():
    """style.charts.single_series_palette[0] reaches resolved spark_bar.bar.color.

    Spark bars (table inline-bars, spark_bar charts) are single-series
    surfaces and pull from single_series_palette — not from the theme's
    UI-affordance accent.
    """
    base = get_theme_style()
    _cat = base.charts.color.categorical
    assert _cat is not None
    updated_cat = _cat.model_copy(update={"single_series_palette": ["#abcdef"]})
    updated_color = base.charts.color.model_copy(update={"categorical": updated_cat})
    updated_charts = base.charts.model_copy(update={"color": updated_color})
    seed = base.model_copy(update={"charts": updated_charts})
    ctx = resolve_chart_style_context(seed)
    assert ctx.spark_bar.bar.color == "#abcdef"


# ---------------------------------------------------------------------------
# AuthoredBoard-to-board cascade via compile_board_resolved_style (1c contribution)
# ---------------------------------------------------------------------------


def _compile_and_get_child_resolved(
    parent_style: dict, child_style: dict | None = None
):
    """Compile a parent->child board tree and return the child's resolved_style."""
    from dbt_charts.core.compile.models.board.authored import AuthoredBoard
    from dbt_charts.core.compile.normalize.dispatch import normalize_board

    child: dict = {"title": "child"}
    if child_style is not None:
        child["style"] = child_style

    board = AuthoredBoard.model_validate(
        {"title": "parent", "style": parent_style, "rows": [child]}
    )
    compiled = normalize_board(board)
    child_board = compiled.layout.items[0].board
    assert child_board is not None
    return child_board.resolved_style


def test_muted_cascades_to_child_resolved_style():
    child_rs = _compile_and_get_child_resolved(parent_style={"muted": "#aabbcc"})
    assert child_rs.muted == "#aabbcc"


def test_accent_cascades_to_child_resolved_style():
    child_rs = _compile_and_get_child_resolved(parent_style={"accent": "#3b82f6"})
    assert child_rs.accent == "#3b82f6"


def test_child_muted_overrides_parent():
    child_rs = _compile_and_get_child_resolved(
        parent_style={"muted": "#aabbcc"},
        child_style={"muted": "#cccccc"},
    )
    assert child_rs.muted == "#cccccc"


def test_child_accent_overrides_parent():
    child_rs = _compile_and_get_child_resolved(
        parent_style={"accent": "#3b82f6"},
        child_style={"accent": "#ff0000"},
    )
    assert child_rs.accent == "#ff0000"


def test_muted_cascades_through_two_levels():
    """grandparent muted propagates all the way to grandchild."""
    from dbt_charts.core.compile.models.board.authored import AuthoredBoard
    from dbt_charts.core.compile.normalize.dispatch import normalize_board

    grandparent = AuthoredBoard.model_validate(
        {
            "title": "grandparent",
            "style": {"muted": "#aabbcc"},
            "rows": [{"title": "child", "rows": [{"title": "grandchild"}]}],
        }
    )
    compiled = normalize_board(grandparent)
    child_board = compiled.layout.items[0].board
    assert child_board is not None
    grandchild_board = child_board.layout.items[0].board
    assert grandchild_board is not None
    assert grandchild_board.resolved_style.muted == "#aabbcc"
