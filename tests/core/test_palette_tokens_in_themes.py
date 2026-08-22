"""Tokens-in-themes: dotted palette tokens resolve everywhere a hex is allowed.

Themes name color *concepts* (e.g. ``dbt-grays.grid-emphasis``, ``negative.solid``)
rather than hard-coding hex literals. Tokens are resolved twice:
- when ``get_theme_style()`` builds and caches a built-in theme, so every
  Style reader sees concrete hex.
- again at the end of ``resolve_style()``, so board-level patches that
  introduce tokens are also resolved.

Also covers the ``charts.palette`` shorthand: a bare palette name string is
expanded to the categorical stops list at validation time.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import BaseModel

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.schema_names import ThemeName
from dbt_charts.core.compile.models.style.authored import StylePatch
from dbt_charts.core.compile.models.style.theme import ChartsStyle
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.compile.resolve.style.palette import (
    UnknownColorError,
    _wcag_contrast,
    color as resolve_palette_color,
    palette as resolve_palette,
)
from dbt_charts.core.compile.resolve.style.tokens import _THEME_SELF_TOKENS

# Slot count of the shipped categorical families (vivid-10 / editorial-10 and
# their companions). Every role token below is 1-indexed over this range.
_CATEGORICAL_SLOTS = 10

# =============================================================================
# Generalized token resolution through resolve_style
# =============================================================================


class TestScaffoldTokensThroughResolve:
    def test_bar_border_color_token_resolves_to_hex(self):
        patch = StylePatch.model_validate(
            {
                "charts": {
                    "marks": {"bar": {"border": {"color": "dbt-grays.grid-emphasis"}}}
                }
            }
        )
        ctx = resolve_chart_style_context(get_theme_style(), patch)
        assert ctx.marks.bar.border.color == resolve_palette_color(
            "dbt-grays.grid-emphasis"
        )

    def test_view_stroke_token_resolves_to_hex(self):
        patch = StylePatch.model_validate(
            {"charts": {"view": {"stroke": "dbt-creams.grid-emphasis"}}}
        )
        ctx = resolve_chart_style_context(get_theme_style(), patch)
        assert ctx.view.stroke == resolve_palette_color("dbt-creams.grid-emphasis")

    def test_page_background_token_resolves_to_hex(self):
        patch = StylePatch.model_validate({"page": {"background": "dbt-grays.canvas"}})
        resolved = resolve_style(get_theme_style(), patch)
        assert resolved.page.background == resolve_palette_color("dbt-grays.canvas")


class TestCategoryRoleBracketTokens:
    """Bracket role tokens (`category[2]`, 1-indexed) on board style leaves.

    These are the theme-portable way to address a categorical slot: the
    token resolves through the active theme's `style.palettes` role
    bindings, so a board restyles itself on a theme switch. Absolute pins
    (`vivid-10.1`, 1-indexed) intentionally do not.
    """

    # One representative bracket token per categorical role per shipped
    # theme, pinned to the slot of the family that theme's roles must bind.
    # A theme edit that drops or misroutes a rebinding (e.g. cream losing
    # editorial's `palettes:` block via an extends change) fails here
    # rather than silently repainting boards authored with role tokens.
    @pytest.mark.parametrize(
        ("theme", "family"),
        [
            ("stark", "vivid-10"),
            ("editorial", "editorial-10"),
            ("cream", "editorial-10"),
        ],
    )
    @pytest.mark.parametrize(
        ("role", "suffix"),
        [
            ("category", ""),
            ("category_dark", "-dark"),
            ("category_light", "-light"),
            ("category_ghost", "-ghost"),
            ("category_ink", "-ink"),
        ],
    )
    def test_every_categorical_role_follows_its_theme(
        self, theme: str, family: str, role: str, suffix: str
    ):
        patch = StylePatch.model_validate(
            {"charts": {"marks": {"bar": {"border": {"color": f"{role}[2]"}}}}}
        )
        ctx = resolve_chart_style_context(get_theme_style(theme), patch)
        assert ctx.marks.bar.border.color == resolve_palette(family + suffix)[1], (
            f"{role}[2] on the {theme} theme must resolve to "
            f"{family + suffix} slot 2 (1-indexed)"
        )

    @pytest.mark.parametrize("theme", get_args(ThemeName))
    def test_light_and_dark_roles_name_a_contrast_direction(self, theme: str):
        """``category_light`` never sits further from the canvas than
        ``category``; ``category_dark`` never sits nearer — on every theme.

        The role names describe where the companion sits relative to the
        canvas, not which pigment it is: on a dark canvas the two invert (neon
        binds ``category_dark`` to the *light* twin so marks read bright on
        black, and ``category_light`` to the dark twin). A board authoring
        ``category_light[N]`` for a deliberately recessive mark must stay
        recessive after a theme switch, which is exactly what this pins.

        Non-strict on purpose. Some slots have no darker (or lighter) twin to
        move to and the companion legitimately equals ``category`` there —
        ``editorial-10-dark`` documents its slot 10 as exactly that case. A
        strict ``>`` would red on unchanged palettes for a maintainer who
        widened the slot range, which is the obvious next edit to this test.
        Direction is the invariant; distance is palette design.
        """
        canvas = resolve_style(get_theme_style(theme)).page.background

        def stops(role: str) -> list[str]:
            colors: list[str] = []
            for slot in range(1, _CATEGORICAL_SLOTS + 1):
                patch = StylePatch.model_validate(
                    {
                        "charts": {
                            "marks": {"bar": {"border": {"color": f"{role}[{slot}]"}}}
                        }
                    }
                )
                ctx = resolve_chart_style_context(get_theme_style(theme), patch)
                colors.append(ctx.marks.bar.border.color)
            return colors

        base, darker, lighter = (
            stops("category"),
            stops("category_dark"),
            stops("category_light"),
        )

        # The bug this encodes: neon rebound only `category_dark`, leaving
        # `category_light` inheriting that same palette from `_base`, so the
        # pair collapsed and the recessive role gained contrast. Two roles
        # resolving identically at every slot means one of them is unbound.
        assert darker != lighter, (
            f"category_dark and category_light resolve to the same palette on "
            f"the {theme} theme — the pair is collapsed, so one role is doing "
            "nothing. Bind both, in opposite directions."
        )

        moved_darker = moved_lighter = False
        for slot, (b, d, light) in enumerate(
            zip(base, darker, lighter, strict=True), start=1
        ):
            base_c = _wcag_contrast(b, canvas)
            assert _wcag_contrast(d, canvas) >= base_c, (
                f"category_dark[{slot}] sits nearer the {theme} canvas than "
                "category — it is the higher-contrast companion"
            )
            assert _wcag_contrast(light, canvas) <= base_c, (
                f"category_light[{slot}] sits further from the {theme} canvas "
                "than category — it is the lower-contrast companion"
            )
            moved_darker = moved_darker or _wcag_contrast(d, canvas) > base_c
            moved_lighter = moved_lighter or _wcag_contrast(light, canvas) < base_c

        # The non-strict comparisons above are satisfied by a companion that
        # never moves at all, and `darker != lighter` is satisfied by one that
        # moves at a single slot. Require each direction to be real somewhere,
        # so a role bound to a palette that does nothing cannot green this.
        assert moved_darker, (
            f"category_dark never sits further from the {theme} canvas than "
            "category at any slot — the role is bound but inert"
        )
        assert moved_lighter, (
            f"category_light never sits nearer the {theme} canvas than "
            "category at any slot — the role is bound but inert"
        )

    def test_unknown_role_bracket_token_raises(self):
        patch = StylePatch.model_validate(
            {"charts": {"marks": {"bar": {"border": {"color": "categry[2]"}}}}}
        )
        with pytest.raises(UnknownColorError):
            resolve_chart_style_context(get_theme_style("stark"), patch)

    def test_table_row_stripe_color_token_resolves_to_hex(self):
        patch = StylePatch.model_validate(
            {
                "charts": {
                    "table": {"row": {"stripe": {"color": "dbt-grays.surface-subtle"}}}
                }
            }
        )
        ctx = resolve_chart_style_context(get_theme_style(), patch)
        assert ctx.table.row.stripe is not None
        assert ctx.table.row.stripe.color == resolve_palette_color(
            "dbt-grays.surface-subtle"
        )

    def test_literal_hex_passes_through_unchanged(self):
        patch = StylePatch.model_validate(
            {"charts": {"marks": {"bar": {"border": {"color": "#abcdef"}}}}}
        )
        ctx = resolve_chart_style_context(get_theme_style(), patch)
        assert ctx.marks.bar.border.color == "#abcdef"

    def test_tone_token_in_border_color_resolves_to_hex(self):
        patch = StylePatch.model_validate(
            {"border": {"color": "negative.border", "width": 1.0, "radius": 0.0}}
        )
        resolved = resolve_style(get_theme_style(), patch)
        assert resolved.border.color == resolve_palette_color("negative.border")

    def test_unknown_token_raises(self):
        patch = StylePatch.model_validate(
            {
                "charts": {
                    "marks": {"bar": {"border": {"color": "dbt-grays.does-not-exist"}}}
                }
            }
        )
        with pytest.raises(UnknownColorError):
            resolve_chart_style_context(get_theme_style(), patch)


# =============================================================================
# charts.palette accepts a palette name string
# =============================================================================


class TestPaletteByName:
    def _charts_dict(self) -> dict:
        # A complete ChartsStyle dict is too long to hand-write; round-trip
        # through the built-in theme to get every required field populated.
        return get_theme_style().charts.model_dump()

    def test_string_palette_name_expands_to_stops(self):
        base = self._charts_dict()
        base["color"] = {
            **base.get("color", {}),
            "categorical": {"palette": "vivid-10"},
        }
        charts = ChartsStyle.model_validate(base)
        assert charts.color.categorical is not None
        assert charts.color.categorical.palette == resolve_palette("vivid-10")

    def test_explicit_list_palette_passes_through(self):
        explicit = ["#111111", "#222222", "#333333"]
        base = self._charts_dict()
        base["color"] = {**base.get("color", {}), "categorical": {"palette": explicit}}
        charts = ChartsStyle.model_validate(base)
        assert charts.color.categorical is not None
        assert charts.color.categorical.palette == explicit

    def test_unknown_palette_name_raises_once_the_theme_is_loaded(self):
        """An unresolvable name fails at the theme cascade, not at model validation.

        A palette field may name a theme *role* (`category`), and a role cannot
        be told apart from a typo until the theme's `palettes:` map is final —
        which is after every `extends:` fragment has merged. So the check moved
        to `expand_palette_refs`, the first point where it can be made.
        """
        from dbt_charts.core.compile.resolve.style.tokens import expand_palette_refs

        base = self._charts_dict()
        base["color"] = {
            **base.get("color", {}),
            "categorical": {"palette": "no-such-palette"},
        }
        charts = ChartsStyle.model_validate(base)
        with pytest.raises(Exception, match="no-such-palette"):
            expand_palette_refs(charts, {"category": "vivid-10"})


# =============================================================================
# Integrated: built-in themes resolve to hex (no dotted token residue)
# =============================================================================


class TestBuiltInThemesResolveCleanly:
    @pytest.mark.parametrize("theme_name", ["stark", "neon", "cream"])
    def test_theme_resolves_with_no_dotted_token_residue(self, theme_name: str):
        base = get_theme_style(theme_name)
        ctx = resolve_chart_style_context(base)
        # Palette is always materialized as a list of hex stops (no unresolved tokens).
        assert isinstance(ctx.palette, list)
        assert len(ctx.palette) > 0
        for stop in ctx.palette:
            assert stop.startswith("#"), f"unresolved stop in {theme_name}: {stop!r}"


# =============================================================================
# Theme-self tokens (``theme.background``) — canvas-coupled fields
# =============================================================================


class TestThemeBackgroundSelfToken:
    """``arc.stroke: theme.background`` in stark propagates the
    theme's own ``style.background`` into ``charts.arc.stroke`` at compile
    time. Every theme — regardless of canvas color — gets a knockout-stroke
    separator that matches its own canvas, with no per-theme override.

    The substituted value can be either a palette token or a literal hex;
    ``_resolve_self_tokens`` runs before ``_resolve_color_tokens`` so
    palette-token backgrounds (e.g. ``dbt-creams.canvas``) are still
    resolved to concrete hex on the way out.
    """

    @pytest.mark.parametrize(
        "theme_name",
        ["stark", "cream", "neon"],
    )
    def test_arc_stroke_tracks_theme_background(self, theme_name: str):
        compiled = get_theme_style(theme_name)
        assert compiled.charts.marks.slice.stroke is not None
        assert compiled.charts.marks.slice.stroke.color == compiled.background, (
            f"charts.marks.slice.stroke.color did not track style.background on {theme_name}: "
            f"charts.marks.slice.stroke.color={compiled.charts.marks.slice.stroke.color!r}, "
            f"background={compiled.background!r}"
        )

    def test_self_token_string_does_not_survive_to_compiled(self):
        """``theme.background`` is a compile-time-only sentinel. It must
        never appear as a literal string in a Style field — if it
        did, downstream consumers (VL emit, etc.) would render the literal
        token text and fail."""
        for theme_name in ("stark", "cream", "neon"):
            compiled = get_theme_style(theme_name)
            assert compiled.charts.marks.slice.stroke is not None
            assert compiled.charts.marks.slice.stroke.color != "theme.background"

    @pytest.mark.parametrize(
        "theme_name",
        [
            "stark",
            "editorial",
            "cream",
            "plain",
            "vivid",
            "neon",
        ],
    )
    def test_no_self_token_residue_anywhere_in_compiled_tree(self, theme_name: str):
        """Walk every string field in every theme's compiled tree and assert
        no ``_THEME_SELF_TOKENS`` value survives. Catches the case where a
        future field is migrated to ``theme.background`` but only one of the
        two resolver call sites (theme-load, resolve_style) handled it, or
        where a new ``_THEME_SELF_TOKENS`` member is added without a
        matching ``_self_token_replacement`` branch.
        """
        compiled = get_theme_style(theme_name)
        residue: list[str] = []

        def walk(node: object, path: str) -> None:
            if isinstance(node, BaseModel):
                for name, value in node:
                    walk(value, f"{path}.{name}" if path else name)
            elif isinstance(node, str):
                if node in _THEME_SELF_TOKENS:
                    residue.append(f"{path}={node!r}")
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    walk(item, f"{path}[{i}]")
            elif isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{path}[{k!r}]")

        walk(compiled, "")
        assert not residue, f"unresolved theme-self tokens in {theme_name}: {residue}"

    def test_unknown_self_token_raises_loudly(self):
        """If ``_THEME_SELF_TOKENS`` ever grows a member without a matching
        ``_self_token_replacement`` branch, the next compile must raise
        loudly — not silently leak the literal sentinel into output."""
        from dbt_charts.core.compile.resolve.style.tokens import _self_token_replacement

        compiled = get_theme_style()
        with pytest.raises(ValueError, match="Unknown theme-self token"):
            _self_token_replacement("theme.no-such-thing", compiled)


# =============================================================================
# Neon chrome is scaffold-sourced (dbt-grays.void), not inline hex
# =============================================================================


def _rec709_luma(hex_str: str) -> float:
    """Relative luma of a #RRGGBB string — enough to order two grays."""
    r = int(hex_str[1:3], 16)
    g = int(hex_str[3:5], 16)
    b = int(hex_str[5:7], 16)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class TestNeonChromeFromScaffold:
    """Neon's dark canvas is the ``void`` scaffold step, not a hardcoded hex.

    ``void`` is the darkest ``dbt-grays`` step (one past ``ink``), added so the
    near-black neutral canvas has a real palette home. These are *binding*
    assertions (canvas tracks the scaffold slot), not brittle hex pins — retuning
    ``void``'s value moves both sides together.
    """

    def test_void_is_darkest_gray_step(self):
        assert _rec709_luma(resolve_palette_color("dbt-grays.void")) < _rec709_luma(
            resolve_palette_color("dbt-grays.ink")
        )

    def test_neon_canvas_tracks_void(self):
        compiled = get_theme_style("neon")
        void_hex = resolve_palette_color("dbt-grays.void")
        assert compiled.background == void_hex
        assert compiled.page.background == void_hex

    def test_neon_panel_tier_tracks_ink(self):
        compiled = get_theme_style("neon")
        assert compiled.charts.table.header.background == resolve_palette_color(
            "dbt-grays.ink"
        )


# =============================================================================
# Chrome accents track a named scaffold/cream token, not a bare literal
# =============================================================================


class TestChromeAccentTokens:
    def test_stark_accent_tracks_dbt_grays_accent(self) -> None:
        assert get_theme_style("stark").accent == resolve_palette_color(
            "dbt-grays.accent"
        )

    @pytest.mark.parametrize("theme_name", ["editorial", "plain"])
    def test_editorial_and_plain_accent_track_dbt_creams_accent(
        self, theme_name: str
    ) -> None:
        assert get_theme_style(theme_name).accent == resolve_palette_color(
            "dbt-creams.accent"
        )

    def test_editorial_input_border_tracks_dbt_grays_separator(self) -> None:
        compiled = get_theme_style("editorial")
        assert compiled.variables.input.border is not None
        assert compiled.variables.input.border.color == resolve_palette_color(
            "dbt-grays.separator"
        )


class TestVividFourTierAnchorsTrackScaffold:
    def test_accent_tracks_heading(self) -> None:
        assert get_theme_style("vivid").accent == resolve_palette_color(
            "dbt-grays.heading"
        )

    def test_muted_tracks_muted_step(self) -> None:
        assert get_theme_style("vivid").muted == resolve_palette_color(
            "dbt-grays.muted"
        )

    def test_border_tracks_grid_emphasis(self) -> None:
        compiled = get_theme_style("vivid")
        assert compiled.border.color == resolve_palette_color("dbt-grays.grid-emphasis")

    def test_axis_quantitative_zero_tracks_ink(self) -> None:
        compiled = get_theme_style("vivid")
        assert compiled.charts.axis_y.grid.zero is not None
        assert compiled.charts.axis_y.grid.zero.color == resolve_palette_color(
            "dbt-grays.ink"
        )


class TestSingleSeriesPaletteTracksCategoricalSlot:
    @pytest.mark.parametrize(
        ("theme_name", "family"),
        [
            ("plain", "editorial-10"),
            ("vivid", "vivid-10"),
            ("neon", "vivid-10"),
        ],
    )
    def test_single_series_palette_first_stop_tracks_family_slot_one(
        self, theme_name: str, family: str
    ) -> None:
        compiled = get_theme_style(theme_name)
        single_series = compiled.charts.color.categorical.single_series_palette
        assert single_series == [resolve_palette(family)[0]]
