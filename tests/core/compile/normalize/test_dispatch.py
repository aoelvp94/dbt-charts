"""Regression tests for normalizer.normalize_board and Board.set_theme.

board.level counts titled ancestors, not structural nesting depth.
Bare cols/rows wrappers with no title pass through transparently.
Author override: board.style.title.level = <int> locks the board's level.

Board.set_theme is the supported API for mutating board.theme after compile.
It re-cascades resolved_style for the board and every nested board, so render
can read resolved_style without re-checking. Direct ``board.theme = …``
writes leave resolved_style stale.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile import compile
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.normalize.dispatch import normalize_board
from dbt_charts.core.diagnostics.codes_compile import ERR_VALIDATION_FIELD

_NESTED_YAML = """\
title: Root
cols:
  - title: Left
    text: "left panel"
  - title: Right
    text: "right panel"
"""


def _compile_nested():
    result = compile(_NESTED_YAML)
    assert result.success, result.errors
    assert result.board is not None
    return result.board


class TestSemanticBoardLevel:
    """board.level = count of titled ancestors, not structural depth."""

    def test_titled_root_level_is_1(self):
        """Root board with a title is level=1."""
        board = normalize_board(
            AuthoredBoard.model_validate({"title": "Root", "text": "hello"})
        )
        assert board.level == 1

    def test_untitled_root_level_is_0(self):
        """Root board with no title is level=0 (no heading at this position)."""
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "rows": [{"title": "Section", "text": "hello"}],
                }
            )
        )
        assert board.level == 0

    def test_bare_wrapper_does_not_increment_level(self):
        """A bare cols wrapper (no title) must not bump level.

        dundersign-shape: titled root → bare cols → chart.
        chart.board_level must be 1, not 2.
        """
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Root",
                    "cols": [
                        {
                            # bare wrapper — no title
                            "rows": [{"title": "Section", "text": "hello"}],
                        }
                    ],
                }
            )
        )
        # Root is level=1 (has title)
        assert board.level == 1
        # Bare cols wrapper is level=1 (no title → doesn't bump)
        cols_item = board.layout.items[0]
        assert cols_item.board is not None
        bare_wrapper = cols_item.board
        assert bare_wrapper.level == 1
        # Section inside bare wrapper is level=2 (first titled descendant under root)
        section_item = bare_wrapper.layout.items[0]
        assert section_item.board is not None
        assert section_item.board.level == 2

    def test_dundersign_shape_wrapper_levels(self):
        """Titled root → bare cols wrapper → bare rows wrapper.

        This is the exact dundersign bug shape. Both bare wrappers must be
        level=1 (inheriting from the titled root) so that charts inside them
        receive board_level=1 and their titles render at sizes[1] (H2), not
        the previous wrong sizes[3] (H4).
        """
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Commercial finance",
                    "cols": [
                        {
                            # bare cols wrapper — no title
                            "rows": [
                                {
                                    # bare rows wrapper — no title
                                    "text": "placeholder content",
                                },
                            ],
                        }
                    ],
                }
            )
        )
        # Root has title → level=1
        assert board.level == 1

        # Walk down: board → cols_item.board → rows_item.board
        cols_item = board.layout.items[0]
        assert cols_item.board is not None, "expected board item for bare cols wrapper"
        bare_cols = cols_item.board
        assert bare_cols.level == 1, (
            f"bare cols wrapper should be level=1, got {bare_cols.level}"
        )

        rows_item = bare_cols.layout.items[0]
        assert rows_item.board is not None, "expected board item for bare rows wrapper"
        bare_rows = rows_item.board
        assert bare_rows.level == 1, (
            f"bare rows wrapper should be level=1, got {bare_rows.level}"
        )

    def test_untitled_root_first_titled_child_is_level_1(self):
        """Untitled root (level=0) → titled child is level=1."""
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "rows": [
                        {"title": "First Section", "text": "hello"},
                    ]
                }
            )
        )
        assert board.level == 0
        child = board.layout.items[0].board
        assert child is not None
        assert child.level == 1

    def test_titled_nested_under_titled_is_level_2(self):
        """Titled root → titled child is level=2 (two titled ancestors)."""
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Dashboard",
                    "rows": [
                        {"title": "Section A", "text": "hello"},
                    ],
                }
            )
        )
        assert board.level == 1
        child = board.layout.items[0].board
        assert child is not None
        assert child.level == 2

    def test_double_bare_wrapper_preserves_parent_level(self):
        """Two bare wrappers in a row: titled root → bare → bare → titled child.

        The titled child is at level=2 (only one titled ancestor: the root).
        """
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Root",
                    "cols": [
                        {
                            # first bare wrapper
                            "rows": [
                                {
                                    # second bare wrapper
                                    "cols": [
                                        {"title": "Deep Section", "text": "hello"},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )
        )
        # Walk the tree
        first_bare = board.layout.items[0].board
        assert first_bare is not None
        assert first_bare.level == 1  # no title, inherits root's level

        second_bare = first_bare.layout.items[0].board
        assert second_bare is not None
        assert second_bare.level == 1  # still no title

        deep_section = second_bare.layout.items[0].board
        assert deep_section is not None
        # Titled, and only one titled ancestor (root), so level=2
        assert deep_section.level == 2


class TestSemanticBoardLevelTabs:
    """Tab bodies inherit semantic level from their parent.

    Regression for the bug where content-only and empty tab branches in
    `_resolve_tab_items` constructed `Board(...)` directly without threading
    `parent_level`, so their level defaulted to 0 and titles rendered at H1.
    """

    def test_content_only_tabs_inherit_parent_level(self):
        """Titled root → titled tabs container → titled content-only tab.

        The titled tabs board is the parent of each tab body, and each tab title
        adds one more titled ancestor — so a content-only tab under a titled
        root is level=2 (root=1, tab=2).
        """
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Root",
                    "tabs": {
                        "items": [
                            {"title": "Tab A", "text": "alpha"},
                            {"title": "Tab B", "text": "beta"},
                        ],
                    },
                }
            )
        )
        assert board.level == 1
        tab_a = board.layout.items[0].board
        tab_b = board.layout.items[1].board
        assert tab_a is not None and tab_b is not None
        # Regression: previously these defaulted to level=0 and rendered at H1.
        assert tab_a.level == 2, (
            f"content-only tab A level should be 2, got {tab_a.level}"
        )
        assert tab_b.level == 2, (
            f"content-only tab B level should be 2, got {tab_b.level}"
        )

    def test_empty_tabs_inherit_parent_level(self):
        """Titled root → titled empty tab → level=2."""
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Root",
                    "tabs": {"items": [{"title": "Empty Tab"}]},
                }
            )
        )
        assert board.level == 1
        empty_tab = board.layout.items[0].board
        assert empty_tab is not None
        assert empty_tab.level == 2

    def test_deeply_nested_content_tabs(self):
        """Titled root → titled section → titled content-only tab → level=3.

        Exercises the case the reviewer flagged in the quick-guide demo: a
        layout board sitting between root and the tabs, so the tab body is
        three titled ancestors deep.
        """
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Dashboard",
                    "rows": [
                        {
                            "title": "Layout Types",
                            "tabs": {
                                "items": [
                                    {"title": "Tab A", "text": "alpha"},
                                ],
                            },
                        }
                    ],
                }
            )
        )
        assert board.level == 1
        section = board.layout.items[0].board
        assert section is not None
        assert section.level == 2
        tab_a = section.layout.items[0].board
        assert tab_a is not None
        assert tab_a.level == 3, f"deep tab A level should be 3, got {tab_a.level}"


class TestAuthorLevelOverride:
    """board.style.title.level: <int> overrides the semantic computation."""

    def test_author_override_wins_over_semantic(self):
        """style.title.level: 3 on a root board forces level=3."""
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Root",
                    "text": "hello",
                    "style": {"title": {"level": 3}},
                }
            )
        )
        # Semantic would give level=1, but override says 3
        assert board.level == 3

    def test_override_propagates_to_descendants(self):
        """When a board sets level=3, titled children compute level=4."""
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Root",
                    "style": {"title": {"level": 3}},
                    "rows": [
                        {"title": "Child Section", "text": "hello"},
                    ],
                }
            )
        )
        assert board.level == 3
        child = board.layout.items[0].board
        assert child is not None
        # Child has a title, parent_level=3, so child.level=4
        assert child.level == 4

    def test_override_with_bare_wrapper_child(self):
        """Override on titled root → bare child inherits the override level."""
        board = normalize_board(
            AuthoredBoard.model_validate(
                {
                    "title": "Root",
                    "style": {"title": {"level": 2}},
                    "cols": [
                        {
                            # bare wrapper, inherits parent_level=2
                            "text": "content",
                        }
                    ],
                }
            )
        )
        assert board.level == 2
        bare_child = board.layout.items[0].board
        assert bare_child is not None
        # Bare child (no title) inherits parent_level=2, no increment
        assert bare_child.level == 2

    def test_level_above_ramp_rejected(self):
        """style.title.level beyond the sizes ramp must raise at compile."""
        import pytest

        with pytest.raises(ValueError, match=r"exceeds the H-ramp"):
            normalize_board(
                AuthoredBoard.model_validate(
                    {
                        "title": "Root",
                        "text": "hi",
                        # default ramp has 6 entries (H1–H6); 7 is out of range
                        "style": {"title": {"level": 7}},
                    }
                )
            )


# ---------------------------------------------------------------------------
# Board.set_theme — atomic theme mutation + cascade
# ---------------------------------------------------------------------------


class TestBoardSetTheme:
    """Board.set_theme is the only supported way to change a board's theme.

    Direct ``board.theme = …`` writes are unsupported because the render layer
    trusts ``resolved_style`` to reflect ``theme`` without re-checking.
    """

    def test_set_theme_recomputes_resolved_style(self):
        """set_theme changes the resolved_style background when switching to a
        provably different theme (clarity vs neon have different backgrounds)."""
        board = _compile_nested()
        board.set_theme("clarity")
        clarity_bg = board.resolved_style.background

        board.set_theme("neon")

        assert board.resolved_style.background != clarity_bg

    def test_set_theme_on_root_propagates_to_nested_boards(self):
        """Root.set_theme must update every nested board's resolved_style.

        Nested boards' own ``board.theme`` values stay at the compile-time
        default; the cascade still has to re-run on them so semantic tokens
        (``muted``, ``accent``) flow from the new root cascade.
        """
        board = _compile_nested()
        nested_left = board.layout.items[0].board
        nested_right = board.layout.items[1].board
        assert nested_left is not None
        assert nested_right is not None

        original_left_style = nested_left.resolved_style
        original_right_style = nested_right.resolved_style

        board.set_theme("neon")

        assert nested_left.resolved_style is not original_left_style
        assert nested_right.resolved_style is not original_right_style

    def test_set_theme_on_nested_board_recomputes_subtree(self):
        """A nested board's set_theme re-cascades that subtree only.

        The nested board has its own authored_style block — the cascade output
        must reflect (new theme base × that authored_style).
        """
        result = compile(
            """\
title: Root
cols:
  - title: Left
    text: "left panel"
    style:
      background: "#eeeeee"
  - title: Right
    text: "right panel"
"""
        )
        assert result.success, result.errors
        board = result.board
        assert board is not None

        nested_board = board.layout.items[0].board
        assert nested_board is not None
        assert nested_board.authored_style is not None
        original_nested_style = nested_board.resolved_style

        nested_board.set_theme("neon")

        assert nested_board.resolved_style != original_nested_style

    def test_direct_theme_write_does_not_recompute(self):
        """Pins the regression contract that direct .theme writes are unsupported.

        Writing ``board.theme = X`` leaves ``resolved_style`` stale; the render
        layer treats this as a programmer error rather than a state to
        recover from. ``Board.set_theme`` is the supported API.
        """
        board = _compile_nested()
        original_style = board.resolved_style

        board.theme = "dark"

        assert board.resolved_style is original_style


class TestNormalizeChartWiring:
    """STEP 4 populates board.charts for all named charts.

    charts_v2 is computed from the same authored chart_def/query_registry as
    the flat Chart — a second, independent normalization, not derived from the
    flat model. See h1-wire-normalize-chart-v2-delete-flat-to-normalized.
    """

    _YAML = """\
title: Root
queries:
  q:
    sql: SELECT month, revenue FROM t
    source: test
charts:
  bar1:
    query: q
    type: bar
    x: month
    y: revenue
rows:
  - bar1
"""

    def test_charts_v2_populated_on_board(self):
        result = compile(self._YAML)
        assert result.success, result.errors
        board = result.board
        assert board is not None
        assert "bar1" in board.charts
        assert board.charts["bar1"].type == "bar"


class TestStyleFrameKey:
    """``style.board:`` was renamed to ``style.frame:`` (``BoardStyle`` -> ``FrameStyle``).

    Pre-launch, no compat alias: the old key must be rejected outright by
    ``extra="forbid"``, not silently accepted alongside the new one.
    """

    def test_style_frame_key_accepted(self):
        board = normalize_board(
            AuthoredBoard.model_validate(
                {"style": {"frame": {"width": 900}}, "text": "hello"}
            )
        )
        assert board.resolved_style.frame.width == 900.0

    def test_style_board_key_rejected(self):
        with pytest.raises(ValidationError):
            AuthoredBoard.model_validate(
                {"style": {"board": {"width": 900}}, "text": "hello"}
            )


class TestRootBoardWidth:
    """Root-level ``width:`` is sugar for ``style.frame.width`` — same effect.

    ``width:`` is normally read only when a board is nested (LayoutItem.user_width
    in normalize/layout.py); on the root board it must set the board's own width
    instead, since there is no parent layout to place it into.
    """

    def test_root_width_sets_board_width(self):
        board = normalize_board(
            AuthoredBoard.model_validate(
                {"width": 900, "text": "hello"},
            )
        )
        assert board.resolved_style.frame.width == 900.0

    def test_root_width_px_string_sets_board_width(self):
        board = normalize_board(
            AuthoredBoard.model_validate(
                {"width": "900px", "text": "hello"},
            )
        )
        assert board.resolved_style.frame.width == 900.0

    def test_root_width_percent_is_rejected(self):
        from dbt_charts.core.compile.errors import CompilationError

        with pytest.raises(CompilationError, match="width") as exc:
            normalize_board(
                AuthoredBoard.model_validate(
                    {"width": "50%", "text": "hello"},
                )
            )
        assert exc.value.code is ERR_VALIDATION_FIELD

    def test_root_width_unparseable_is_rejected(self):
        from dbt_charts.core.compile.errors import CompilationError

        with pytest.raises(CompilationError, match="not a valid dimension") as exc:
            normalize_board(
                AuthoredBoard.model_validate(
                    {"width": "wide", "text": "hello"},
                )
            )
        assert exc.value.code is ERR_VALIDATION_FIELD

    def test_root_width_zero_is_rejected(self):
        from dbt_charts.core.compile.errors import CompilationError

        with pytest.raises(CompilationError, match="positive") as exc:
            normalize_board(
                AuthoredBoard.model_validate(
                    {"width": 0, "text": "hello"},
                )
            )
        assert exc.value.code is ERR_VALIDATION_FIELD

    def test_root_width_conflicting_with_board_width_style_is_rejected(self):
        from dbt_charts.core.compile.errors import CompilationError

        with pytest.raises(CompilationError, match="Cannot specify both") as exc:
            normalize_board(
                AuthoredBoard.model_validate(
                    {
                        "width": 900,
                        "style": {"frame": {"width": 700}},
                        "text": "hello",
                    }
                )
            )
        assert exc.value.code is ERR_VALIDATION_FIELD
        assert "style.frame.width" in str(exc.value)

    def test_root_width_survives_set_theme(self):
        """width: sugar must survive set_theme like style.frame.width does."""
        board = normalize_board(
            AuthoredBoard.model_validate({"width": 900, "text": "hello"})
        )
        assert board.resolved_style.frame.width == 900.0
        board.set_theme("paper")
        assert board.resolved_style.frame.width == 900.0

    def test_nested_board_width_still_means_layout_width_not_board_width(self):
        """A nested board's width: is layout placement, untouched by this fix."""
        result = compile(
            "title: Root\n"
            "cols:\n"
            "  - title: Left\n"
            '    width: "30%"\n'
            "    text: left\n"
            "  - title: Right\n"
            "    text: right\n"
        )
        assert result.success, result.errors
        board = result.board
        assert board is not None
        left_item = board.layout.items[0]
        assert left_item.user_width == "30%"
        assert left_item.board is not None
        assert (
            left_item.board.resolved_style.frame.width
            == board.resolved_style.frame.width
        )
