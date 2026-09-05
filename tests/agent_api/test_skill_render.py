"""Tests for surface-aware macro expansion in skill bodies."""

from __future__ import annotations

import re
from importlib.resources import files

import pytest

from dbt_charts.agent_api.skill_render import (
    MissingSurfaceAlias,
    render_skill_body,
)


class TestSurfaceExpansion:
    def test_expands_s_macro_on_tool_surface(self) -> None:
        out = render_skill_body("Run {{ s_validate_board }} now.", surface="tool")
        assert out == "Run validate_board now."

    def test_expands_s_macro_on_cli(self) -> None:
        out = render_skill_body("Run {{ s_validate_board }} now.", surface="cli")
        assert out == "Run dct validate now."

    def test_expands_multi_line_block_macro_tool_surface(self) -> None:
        body = "Try this:\n{{ s_validate_example }}\nDone."
        out = render_skill_body(body, surface="tool")
        assert 'validate_board(path="' in out
        assert "dct validate" not in out

    def test_expands_multi_line_block_macro_cli(self) -> None:
        body = "Try this:\n{{ s_validate_example }}\nDone."
        out = render_skill_body(body, surface="cli")
        assert "dct validate charts/" in out
        assert "validate_board(" not in out


class TestSurfaceSelection:
    """Single {{ s_key }} picks the right side per surface."""

    @pytest.mark.parametrize(
        ("body", "surface", "expected"),
        [
            ("{{ s_validate_board }}", "tool", "validate_board"),
            ("{{ s_validate_board }}", "cli", "dct validate"),
            # Regression: s_query_board CLI side uses positional board context.
            ("{{ s_query_board }}", "cli", "dct query BOARD.yml QUERY"),
            ("{{ s_query_board }}", "tool", "query_board"),
        ],
    )
    def test_s_macro_picks_correct_side(
        self, body: str, surface: str, expected: str
    ) -> None:
        out = render_skill_body(body, surface=surface)  # type: ignore[arg-type]
        assert out == expected


class TestUnknownKey:
    @pytest.mark.parametrize("surface", ["tool", "cli"])
    def test_unknown_key_raises(self, surface: str) -> None:
        with pytest.raises(MissingSurfaceAlias, match="bogus_key_xyz"):
            render_skill_body("{{ s_bogus_key_xyz }}", surface=surface)  # type: ignore[arg-type]

    @pytest.mark.parametrize("surface", ["tool", "cli"])
    def test_old_dashboard_named_key_no_longer_resolves(self, surface: str) -> None:
        """Pre-rename key. No back-compat alias — must raise, not silently resolve."""
        with pytest.raises(MissingSurfaceAlias, match="validate_dashboard"):
            render_skill_body("{{ s_validate_dashboard }}", surface=surface)  # type: ignore[arg-type]


class TestToolAvailabilityGate:
    """{{#if_tool NAME}}...{{/if_tool}} blocks gate on available_tools."""

    def test_keeps_block_when_tool_available(self) -> None:
        body = "Before.\n{{#if_tool validate_board}}Call validate_board.{{/if_tool}}\nAfter."
        out = render_skill_body(
            body, surface="tool", available_tools={"validate_board"}
        )
        assert "Call validate_board." in out
        assert "{{#if_tool" not in out
        assert "{{/if_tool}}" not in out

    def test_drops_block_when_tool_unavailable(self) -> None:
        body = (
            "Before.\n{{#if_tool search_boards}}Call search_boards.{{/if_tool}}\nAfter."
        )
        out = render_skill_body(
            body, surface="tool", available_tools={"validate_board"}
        )
        assert "search_boards" not in out
        assert "Before." in out
        assert "After." in out

    def test_keeps_all_blocks_when_available_tools_is_none(self) -> None:
        """available_tools=None (the default) preserves CLI/MCP behavior — nothing gated."""
        body = "{{#if_tool search_boards}}Call search_boards.{{/if_tool}}"
        out = render_skill_body(body, surface="tool")
        assert "Call search_boards." in out


class TestPassthrough:
    def test_body_without_macros_passes_through(self) -> None:
        body = "Just a normal SKILL.md\nwith **markdown** and `code`."
        for surface in ("tool", "cli"):
            assert (
                render_skill_body(body, surface=surface)  # type: ignore[arg-type]
                == body
            )

    def test_plain_variable_no_s_prefix_passes_through(self) -> None:
        """{{ variable }} without s_ prefix is a board-YAML template token — must be untouched."""
        body = "SELECT * FROM {{ region }}"
        for surface in ("tool", "cli"):
            assert (
                render_skill_body(body, surface=surface)  # type: ignore[arg-type]
                == body
            )

    def test_board_yaml_variable_in_fenced_block_passes_through(self) -> None:
        """board-YAML {{ variable }} tokens inside fenced SQL blocks must not be consumed."""
        body = "```sql\nSELECT * FROM orders WHERE region = '{{ region }}'\n```"
        for surface in ("tool", "cli"):
            assert (
                render_skill_body(body, surface=surface)  # type: ignore[arg-type]
                == body
            )


# Old skill-ID prefixes the board rename retires in one cut. No aliases
# survive. Old wire tool-name coverage lives in test_skills.py's
# LEGACY_TOOL_NAMES (a plain substring guard — no quote-anchoring to slip
# past on a backticked reference).
_OLD_SKILL_ID_RE = re.compile(
    r"\bdashboard-(build|design|pack-scaffolding|replicate|review|structural-review|visual-review)\b"
)


class TestNoStaleDashboardVocabularyInSkills:
    """The board rename breaks skill rendering silently if split. Guard every SKILL.md."""

    def test_no_skill_references_old_dashboard_skill_ids(self) -> None:
        skills_root = files("dbt_charts.ai.skills")
        offenders: list[str] = []
        for entry in skills_root.iterdir():  # type: ignore[attr-defined]
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            text = skill_md.read_text(encoding="utf-8")
            if _OLD_SKILL_ID_RE.search(text):
                offenders.append(str(skill_md))
        assert offenders == []
