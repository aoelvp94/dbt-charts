"""Tests for theme: → extends: parse-time alias (Lane C, Phase 3).

`theme: X` is authoring sugar for `extends: X`. A before-validator in
AuthoredBoard rewrites the key at parse time so the resolution engine sees
only `extends:`.

Built-in theme YAMLs are Board fragments — they carry `extends:` and `style:`
and can be loaded as BoardPatch instances for use with merge_patches.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.models.board.authored import AuthoredBoard


class TestThemeAliasDesugars:
    """theme: X desugars to extends: X at parse time."""

    def test_theme_becomes_extends(self) -> None:
        board = AuthoredBoard.model_validate(
            {"title": "test", "rows": [], "theme": "dark"}
        )
        assert board.extends == "dark"

    def test_theme_none_is_ignored(self) -> None:
        board = AuthoredBoard.model_validate(
            {"title": "test", "rows": [], "theme": None}
        )
        assert board.extends is None

    def test_extends_still_works_without_theme(self) -> None:
        board = AuthoredBoard.model_validate(
            {"title": "test", "rows": [], "extends": "cream"}
        )
        assert board.extends == "cream"

    def test_theme_and_extends_conflict_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AuthoredBoard.model_validate(
                {"title": "test", "rows": [], "theme": "neon", "extends": "stark"}
            )


class TestBuiltInThemesAsBoardFragments:
    """Built-in theme YAMLs can be loaded as BoardPatch (Board fragments)."""

    def test_theme_yaml_loads_as_board_patch(self) -> None:
        """A built-in theme YAML parses as a BoardPatch without errors."""
        import yaml

        import dbt_charts
        from dbt_charts.core.compile.models.board.patch import BoardPatch

        pkg_dir = __import__("pathlib").Path(dbt_charts.__file__).resolve().parent
        themes_dir = pkg_dir / "core" / "defaults" / "themes"
        neon_path = themes_dir / "neon.yaml"
        assert neon_path.exists()

        raw = yaml.safe_load(neon_path.read_text(encoding="utf-8"))
        patch = BoardPatch.model_validate(raw)
        # neon extends stark
        assert patch.extends == "stark"

    def test_all_built_in_themes_parse_as_board_patch(self) -> None:
        """Every built-in theme YAML validates as a BoardPatch."""
        import yaml

        import dbt_charts
        from dbt_charts.core.compile.models.board.patch import BoardPatch

        pkg_dir = __import__("pathlib").Path(dbt_charts.__file__).resolve().parent
        themes_dir = pkg_dir / "core" / "defaults" / "themes"
        theme_files = list(themes_dir.glob("*.yaml"))
        assert theme_files, "No theme YAMLs found"

        for path in theme_files:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            # Must not raise
            BoardPatch.model_validate(raw)
