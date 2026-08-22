"""A board must declare something that renders.

`AuthoredBoard.validate_layout` rejects a board with no layout, no text, no title,
no description, and no charts. Styling alone does not qualify — a `style:` block
paints a box that has nothing in it, which is the empty-region failure the rule
exists to catch.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.authored import AuthoredBoard


class TestEmptyBoardRejected:
    def test_bare_board_raises(self):
        with pytest.raises(ValidationError, match="at least one layout type"):
            AuthoredBoard.model_validate({})

    def test_style_only_board_raises(self):
        """Styling is not content. A background paints an empty region."""
        with pytest.raises(ValidationError, match="at least one layout type"):
            AuthoredBoard.model_validate({"style": {"background": "vivid-10.1"}})

    def test_style_with_padding_only_raises(self):
        with pytest.raises(ValidationError, match="at least one layout type"):
            AuthoredBoard.model_validate({"style": {"padding": "8px"}})


class TestBoardWithContentAccepted:
    """Each content key on its own satisfies the rule."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"text": "hello"},
            {"title": "Section"},
            {"description": "why this board exists"},
            {"rows": ["some_chart"]},
        ],
        ids=["text", "title", "description", "rows"],
    )
    def test_content_key_is_enough(self, payload: dict[str, object]):
        AuthoredBoard.model_validate(payload)

    def test_styled_cell_with_text_is_the_swatch_shape(self):
        """The palette reference's swatch cells: a styled box carrying text."""
        AuthoredBoard.model_validate(
            {
                "text": " ",
                "width": "28px",
                "style": {"background": "vivid-10.1"},
            }
        )
