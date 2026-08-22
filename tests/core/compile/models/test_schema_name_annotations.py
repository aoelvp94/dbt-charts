"""TDD tests: baking ThemeName/PaletteName/ScalePaletteName into model fields
must not narrow what already validates. `extends`, `ScaleTargetConfig.palette`,
and `CategoricalColorStyle.palette`/`.single_series_palette` keep an open
`str`/`list` arm because real authored forms (name:N_r shorthand, board
paths, list-of-names extends) aren't literal members of the enum.
`Style.palettes` does not: its values are looked up as an exact key with no
shorthand parsing, so a bare `PaletteName` is the only legal value.
"""

from __future__ import annotations

import pydantic
import pytest

from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.primitives import (
    CategoricalColorStyle,
    ScaleTargetConfig,
)
from dbt_charts.core.compile.models.style.theme.style import Style


class TestExtendsOpenForms:
    def test_built_in_theme_name_still_validates(self) -> None:
        board = AuthoredBoard(extends="editorial", rows=[])
        assert board.extends == "editorial"

    def test_relative_path_still_validates(self) -> None:
        board = AuthoredBoard(extends="./_template.yaml", rows=[])
        assert board.extends == "./_template.yaml"

    def test_board_name_not_a_known_theme_still_validates(self) -> None:
        board = AuthoredBoard(extends="my-custom-board", rows=[])
        assert board.extends == "my-custom-board"

    def test_list_form_mixing_theme_and_path_still_validates(self) -> None:
        board = AuthoredBoard(extends=["stark", "./_report-base.yml"], rows=[])
        assert board.extends == ["stark", "./_report-base.yml"]

    def test_theme_sugar_still_desugars_to_extends(self) -> None:
        board = AuthoredBoard.model_validate({"theme": "editorial", "rows": []})
        assert board.extends == "editorial"


class TestScaleTargetConfigPaletteOpenForms:
    def test_named_dataface_palette_still_validates(self) -> None:
        config = ScaleTargetConfig(palette="dbt-seq-blue")
        assert config.palette == "dbt-seq-blue"

    def test_shorthand_steps_and_reverse_still_validates(self) -> None:
        config = ScaleTargetConfig(palette="dbt-seq-blue:5_r")
        assert config.palette == "dbt-seq-blue:5_r"

    def test_vega_scheme_name_still_validates(self) -> None:
        config = ScaleTargetConfig(palette="viridis")
        assert config.palette == "viridis"

    def test_inline_stop_list_still_validates(self) -> None:
        config = ScaleTargetConfig(palette=["#fff", "#000"])
        assert config.palette == ["#fff", "#000"]


class TestCategoricalColorStylePaletteOpenForms:
    def test_named_palette_expands_to_stops(self) -> None:
        style = CategoricalColorStyle(palette="category-6-tonal-blue")
        assert style.palette and all(c.startswith("#") for c in style.palette)

    def test_inline_stop_list_still_validates(self) -> None:
        style = CategoricalColorStyle(palette=["#fff", "#000"])
        assert style.palette == ["#fff", "#000"]


class TestStylePalettesDictValueIsClosed:
    """Style has many other required fields; validate the palettes field's
    real annotation in isolation via TypeAdapter rather than constructing a
    full Style (or bypassing validation with model_construct).

    Unlike ScaleTargetConfig.palette/CategoricalColorStyle.palette, values
    here are looked up as an exact key against the shipped palette index
    (palette.py's color_from_theme) — the name:N_r shorthand parser never
    runs on them, so there is no open form to keep legal. A bare PaletteName
    is the only valid value (review round 3, 2026-08-14).
    """

    def _adapter(self):
        from pydantic import TypeAdapter

        return TypeAdapter(Style.model_fields["palettes"].annotation)

    def test_named_palette_value_still_validates(self) -> None:
        result = self._adapter().validate_python({"category": "dbt-seq-blue"})
        assert result == {"category": "dbt-seq-blue"}

    def test_unknown_string_value_is_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            self._adapter().validate_python({"chrome": "not-a-real-palette-name"})

    def test_shorthand_suffix_is_rejected(self) -> None:
        # The name:N_r shorthand is real syntax on ScaleTargetConfig.palette/
        # CategoricalColorStyle.palette, but color_from_theme's role/alias
        # lookup never parses it — it isn't a legal Style.palettes value.
        with pytest.raises(pydantic.ValidationError):
            self._adapter().validate_python({"category": "dbt-seq-blue:5_r"})

    def test_every_built_in_theme_palettes_block_validates(self) -> None:
        from dbt_charts.core.compile.config import get_theme_style, list_built_in_themes

        adapter = self._adapter()
        for name in list_built_in_themes():
            if name == "_base":
                continue  # completeness floor, not independently loadable
            style = get_theme_style(name)
            adapter.validate_python(style.palettes)
