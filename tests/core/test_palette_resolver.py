"""Unit tests for the M2 palette resolver.

Covers: palette/color public API, shorthand parsing, diverging midpoint skip,
spine-direct resolution (no LUT), reverse, exception classes, and anti-pattern
handling.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dbt_charts.core.compile.resolve.style.palette import (
    CategoricalOverrequestError,
    SurfaceUnsupportedError,
    ToneAsPaletteError,
    UnknownColorError,
    UnknownPaletteError,
    _downsample,
    _parse_palette_reference,
    color,
    list_palettes,
    palette,
    palette_metadata,
    resolve_palette_alias,
    select_default_palette,
)

from .._paths import DBT_CHARTS_DIR

# Load palette_deltae_checker as a script (not a package).
# Same pattern as test_palette_cvd.py.
_SCRIPTS_DIR = DBT_CHARTS_DIR / "scripts"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_checker = _load_script("palette_deltae_checker")

# ============================================================================
# _parse_palette_reference
# ============================================================================


class TestParsePaletteReference:
    def test_plain_name(self):
        assert _parse_palette_reference("dbt-seq-blue") == ("dbt-seq-blue", None, False)

    def test_steps_shorthand(self):
        assert _parse_palette_reference("dbt-seq-blue:5") == ("dbt-seq-blue", 5, False)

    def test_reverse_shorthand(self):
        assert _parse_palette_reference("dbt-seq-blue_r") == (
            "dbt-seq-blue",
            None,
            True,
        )

    def test_steps_and_reverse(self):
        assert _parse_palette_reference("dbt-seq-blue:5_r") == ("dbt-seq-blue", 5, True)

    def test_hyphenated_name_unaffected(self):
        # The name itself contains hyphens — parser must not break them.
        assert _parse_palette_reference("dbt-div-blue-red") == (
            "dbt-div-blue-red",
            None,
            False,
        )

    def test_hyphenated_with_steps(self):
        assert _parse_palette_reference("dbt-div-blue-red:6") == (
            "dbt-div-blue-red",
            6,
            False,
        )

    def test_invalid_steps_raises(self):
        with pytest.raises(ValueError, match="steps"):
            _parse_palette_reference("dbt-seq-blue:notanumber")

    def test_zero_or_negative_steps_raises(self):
        with pytest.raises(ValueError, match="steps"):
            _parse_palette_reference("dbt-seq-blue:0")


# ============================================================================
# _downsample
# ============================================================================


class TestDownsample:
    def test_identity_when_n_equals_len(self):
        stops = [f"#{i:06x}" for i in range(11)]
        assert _downsample(stops, 11) == stops

    def test_endpoints_always_preserved(self):
        stops = [f"#{i:06x}" for i in range(120)]
        result = _downsample(stops, 5)
        assert result[0] == stops[0]
        assert result[-1] == stops[-1]
        assert len(result) == 5

    def test_diverging_even_n_skips_midpoint(self):
        # 11-stop palette with known midpoint at index 5.
        stops = [f"#{i:06x}" for i in range(11)]
        result = _downsample(stops, 4, skip_midpoint_on_even=True)
        assert len(result) == 4
        # With midpoint skip, the 11-stop spine's midpoint "#000005" must not appear.
        assert stops[5] not in result

    def test_diverging_odd_n_includes_midpoint(self):
        stops = [f"#{i:06x}" for i in range(11)]
        result = _downsample(stops, 5, skip_midpoint_on_even=True)
        assert len(result) == 5
        assert stops[5] in result  # odd N includes midpoint

    def test_identity_when_requesting_exact_count(self):
        """Requesting exactly the number of available stops returns the list unchanged."""
        stops = ["#aaa000", "#bbb000", "#ccc000"]
        result = _downsample(stops, 3)
        assert result == stops


# ============================================================================
# palette() — sequential + diverging
# ============================================================================


class TestPaletteSequential:
    def test_default_returns_11_stops(self):
        stops = palette("dbt-seq-blue")
        assert len(stops) == 11
        assert all(s.startswith("#") and len(s) == 7 for s in stops)

    def test_steps_5_returns_5(self):
        stops = palette("dbt-seq-blue", steps=5)
        assert len(stops) == 5

    def test_shorthand_colon_n(self):
        assert palette("dbt-seq-blue:5") == palette("dbt-seq-blue", steps=5)

    def test_reverse_kwarg(self):
        forward = palette("dbt-seq-blue")
        rev = palette("dbt-seq-blue", reverse=True)
        assert rev == list(reversed(forward))

    def test_reverse_shorthand(self):
        assert palette("dbt-seq-blue_r") == palette("dbt-seq-blue", reverse=True)

    def test_surface_table_returns_wcag_safe_stops(self):
        # surface="table" returns WCAG-safe stops via OKLCH interpolation.
        from dbt_charts.core.colors import wcag_contrast as _wcag_contrast
        from dbt_charts.core.compile.resolve.style.palette import palette

        result = palette("dbt-seq-blue", surface="table")
        assert isinstance(result, list)
        assert len(result) == 11
        for stop in result:
            assert _wcag_contrast("#222222", stop) >= 4.5


class TestPaletteDiverging:
    def test_default_returns_11_stops(self):
        assert len(palette("dbt-div-blue-red")) == 11

    def test_even_n_skips_midpoint(self):
        # Midpoint of dbt-div-blue-red spine is #e4e4e4.
        stops = palette("dbt-div-blue-red", steps=6)
        assert len(stops) == 6
        assert "#e4e4e4" not in [s.lower() for s in stops]

    def test_odd_n_includes_midpoint(self):
        stops = palette("dbt-div-blue-red", steps=5)
        assert len(stops) == 5

    def test_steps_2_does_not_divide_by_zero(self):
        """Regression: n=2 with midpoint-skip on an odd-length spine used to
        divide by zero (half=1, half-1 = 0). Should return the two extremes.
        """
        stops = palette("dbt-div-blue-red", steps=2)
        assert len(stops) == 2
        # Two stops: low extreme + high extreme, midpoint skipped.
        assert stops[0].lower() == "#002f55"
        assert stops[1].lower() == "#590b05"


# ============================================================================
# palette() — categorical + scaffold
# ============================================================================


class TestPaletteCategorical:
    def test_vivid_10_default_returns_all_10(self):
        stops = palette("vivid-10")
        assert len(stops) == 10

    def test_hero_6_default_returns_all_6(self):
        stops = palette("hero-6")
        assert len(stops) == 6

    def test_steps_less_than_len_slices(self):
        stops = palette("vivid-10", steps=3)
        assert len(stops) == 3
        # Categorical slice is deterministic first-N.
        assert stops == palette("vivid-10")[:3]

    def test_over_request_raises(self):
        with pytest.raises(CategoricalOverrequestError):
            palette("vivid-10", steps=15)

    def test_surface_on_categorical_raises(self):
        with pytest.raises(SurfaceUnsupportedError):
            palette("vivid-10", surface="table")

    def test_vivid_10_dark_pairs_positionally_with_vivid_10(self):
        # The dark companion exists specifically so direct labels can use
        # the dark twin of each bright slot. If someone retones one
        # palette without the other, slot N stops corresponding and the
        # pairing silently breaks. Length is the cheap structural guard.
        assert len(palette("vivid-10")) == len(palette("vivid-10-dark")) == 10


class TestVividTenDark:
    """Direct-label inking companion to vivid-10. Slot N is positionally
    paired with slot N in vivid-10, sitting measurably darker so endpoint
    and segment labels ink against light canvases."""

    LOCKED_STOPS = [
        "#005998",
        "#00a1c0",
        "#008055",
        "#a07400",
        "#b03e00",
        "#82568d",
        "#4a6c00",
        "#5f3a12",
        "#6c7685",
        "#404852",
    ]

    def test_stops_match_locked_set(self):
        assert palette("vivid-10-dark") == self.LOCKED_STOPS

    def test_resolves_through_categorical_pipeline(self):
        meta = palette_metadata("vivid-10-dark")
        assert meta["family"] == "categorical"


class TestVividTenLight:
    """Moderate light companion to vivid-10. Slot N is positionally paired
    with slot N in vivid-10 and vivid-10-dark, sitting lighter and
    more desaturated than the base, strictly under the ghost tier."""

    LOCKED_STOPS = [
        "#628eba",
        "#8cd2e7",
        "#8cccab",
        "#e0bf83",
        "#d0896f",
        "#b698be",
        "#9ab27e",
        "#917459",
        "#b3b8bf",
        "#686e78",
    ]

    def test_resolves_with_ten_hex_stops(self):
        stops = palette("vivid-10-light")
        assert len(stops) == 10
        for stop in stops:
            assert isinstance(stop, str)
            assert len(stop) == 7 and stop[0] == "#"
            int(stop[1:], 16)  # raises ValueError on non-hex

    def test_stops_match_locked_set(self):
        assert palette("vivid-10-light") == self.LOCKED_STOPS

    def test_positional_oklch_invariant_against_base_dark_and_ghost(self):
        # Structural guarantee, no hex pins. For every slot:
        #   1. dark.L < base.L - 0.05  (-dark is measurably darker: label ink)
        #   2. light.L > base.L + 0.04 AND light.L > dark.L
        #   3. light.L <= ghost.L - 0.03  (tier discipline: the moderate
        #      light band sits strictly under the extreme ghost band; the
        #      pre-retune palette had cyan/gold-light ABOVE their ghosts)
        #   4. companions are no more saturated than the base
        #   5. companions hold the base hue (slot identity is hue-carried)
        # The old light/dark mirror contract is gone — same reasoning as
        # editorial-10 (#4745): the mirror was a derivation convenience that
        # forced bright slots over the ghost tier.
        base = palette("vivid-10")
        dark = palette("vivid-10-dark")
        light = palette("vivid-10-light")
        ghost = palette("vivid-10-ghost")
        assert len(base) == len(dark) == len(light) == len(ghost) == 10

        for slot, (b, d, lt, gh) in enumerate(
            zip(base, dark, light, ghost, strict=True)
        ):
            b_l, b_c, b_h = _checker.hex_to_oklch(b)
            d_l, d_c, d_h = _checker.hex_to_oklch(d)
            lt_l, lt_c, lt_h = _checker.hex_to_oklch(lt)
            gh_l, gh_c, gh_h = _checker.hex_to_oklch(gh)

            assert d_l < b_l - 0.05, (
                f"slot {slot}: dark companion {d!r} OKLCH L={d_l:.3f} should sit "
                f"measurably under base {b!r} OKLCH L={b_l:.3f} — direct labels "
                "don't ink otherwise"
            )
            assert lt_l > b_l + 0.04, (
                f"slot {slot}: light companion {lt!r} OKLCH L={lt_l:.3f} should be "
                f"measurably lighter than base {b!r} OKLCH L={b_l:.3f}"
            )
            assert lt_l > d_l, (
                f"slot {slot}: light companion {lt!r} OKLCH L={lt_l:.3f} should be "
                f"greater than dark companion {d!r} OKLCH L={d_l:.3f}"
            )
            assert lt_l <= gh_l - 0.03, (
                f"slot {slot}: light companion {lt!r} OKLCH L={lt_l:.3f} crosses "
                f"the ghost tier ({gh!r} OKLCH L={gh_l:.3f}) — light must stay a "
                "distinct middle tier under ghost"
            )
            assert lt_c <= b_c + 0.005, (
                f"slot {slot}: light companion {lt!r} OKLCH C={lt_c:.3f} should "
                f"not exceed base {b!r} OKLCH C={b_c:.3f}"
            )
            assert d_c <= b_c + 0.02, (
                f"slot {slot}: dark companion {d!r} OKLCH C={d_c:.3f} may bump "
                f"chroma only slightly over base {b!r} OKLCH C={b_c:.3f}"
            )
            for variant, v_h in (("dark", d_h), ("light", lt_h), ("ghost", gh_h)):
                hue_diff = abs(b_h - v_h)
                hue_diff = min(hue_diff, 360 - hue_diff)
                assert hue_diff < 8, (
                    f"slot {slot}: {variant} companion drifted in hue from base "
                    f"{b!r} (base H={b_h:.1f}°, {variant} H={v_h:.1f}°, "
                    f"Δ={hue_diff:.1f}°) — pairing is hue-carried"
                )

    def test_resolves_through_categorical_pipeline(self):
        # Same loader path as vivid-10-dark; no special-case wiring.
        meta = palette_metadata("vivid-10-light")
        assert meta["family"] == "categorical"


class TestVividTenGhost:
    """Extreme de-emphasis companion to vivid-10.

    The pale band that ghosts non-focus series while preserving hue identity —
    a distinct tier above the moderate light companion.
    """

    LOCKED_STOPS = [
        "#b9d4f0",
        "#b2d9e5",
        "#b6dbc7",
        "#e2cfad",
        "#f2c6b6",
        "#dccae1",
        "#c8d7b8",
        "#dccec2",
        "#ced1d6",
        "#babec4",
    ]

    def test_stops_match_locked_set(self):
        assert palette("vivid-10-ghost") == self.LOCKED_STOPS

    def test_ghost_is_far_lighter_than_base(self):
        base = palette("vivid-10")
        ghost = palette("vivid-10-ghost")
        for slot, (b, gh) in enumerate(zip(base, ghost, strict=True)):
            b_l, b_c, _ = _checker.hex_to_oklch(b)
            gh_l, gh_c, _ = _checker.hex_to_oklch(gh)
            assert gh_l > b_l + 0.09, (
                f"slot {slot}: ghost companion {gh!r} OKLCH L={gh_l:.3f} should "
                f"sit far above base {b!r} OKLCH L={b_l:.3f}"
            )
            # The ghost tier is a band, not a per-slot lift: every slot sits
            # at L >= 0.79 so ghosted members read uniformly pale. Charcoal
            # sat at L 0.74 pre-retune — visibly heavier than its band-mates
            # (editorial-10-ghost fixed the same defect in #4745).
            assert gh_l >= 0.79, (
                f"slot {slot}: ghost companion {gh!r} OKLCH L={gh_l:.3f} sits "
                "below the ghost band (L >= 0.79)"
            )
            assert gh_c <= b_c + 0.005, (
                f"slot {slot}: ghost companion {gh!r} OKLCH C={gh_c:.3f} should "
                f"not exceed base {b!r} OKLCH C={b_c:.3f}"
            )

    def test_resolves_through_categorical_pipeline(self):
        meta = palette_metadata("vivid-10-ghost")
        assert meta["family"] == "categorical"


class TestVividTenInk:
    """Ink-grade companion to vivid-10 — the symmetric opposite of the ghost
    tier. Every slot drops into a tight dark band (OKLCH L 0.30-0.36); slot
    identity is carried by hue and chroma, not lightness. Consumed by the
    vivid-family themes via inlined `single_series_palette` hexes."""

    LOCKED_STOPS = [
        "#003761",
        "#004554",
        "#00442b",
        "#503900",
        "#621f00",
        "#4d1c5a",
        "#2a4000",
        "#54310b",
        "#2e3641",
        "#252e3d",
    ]

    # Documented ink band (see vivid-10-ink.yml): a tight OKLCH L 0.30-0.36
    # with charcoal-ink anchoring the floor. The small tolerance absorbs sRGB
    # round-tripping at the band edges.
    _BAND_LO = 0.295
    _BAND_HI = 0.365

    def test_stops_match_locked_set(self):
        assert palette("vivid-10-ink") == self.LOCKED_STOPS

    def test_length_matches_base(self):
        assert len(palette("vivid-10")) == len(palette("vivid-10-ink")) == 10

    def test_ink_sits_in_dark_band_and_darker_than_base(self):
        base = palette("vivid-10")
        ink = palette("vivid-10-ink")
        for slot, (b, ik) in enumerate(zip(base, ink, strict=True)):
            b_l, _, b_h = _checker.hex_to_oklch(b)
            ik_l, _, ik_h = _checker.hex_to_oklch(ik)
            assert self._BAND_LO <= ik_l <= self._BAND_HI, (
                f"slot {slot}: ink companion {ik!r} OKLCH L={ik_l:.3f} is "
                f"outside the ink band [{self._BAND_LO}, {self._BAND_HI}]"
            )
            assert ik_l < b_l, (
                f"slot {slot}: ink companion {ik!r} OKLCH L={ik_l:.3f} must sit "
                f"under base {b!r} OKLCH L={b_l:.3f}"
            )
            # Near-neutral slots (gray/charcoal) have unstable hue at low
            # chroma; the chromatic slots hold the base hue within tolerance.
            _, b_c, _ = _checker.hex_to_oklch(b)
            if b_c > 0.04:
                hue_diff = abs(b_h - ik_h)
                hue_diff = min(hue_diff, 360 - hue_diff)
                assert hue_diff < 8, (
                    f"slot {slot}: ink companion drifted in hue from base "
                    f"(base H={b_h:.1f}°, ink H={ik_h:.1f}°, Δ={hue_diff:.1f}°)"
                )

    def test_resolves_through_categorical_pipeline(self):
        meta = palette_metadata("vivid-10-ink")
        assert meta["family"] == "categorical"


class TestPaletteTonal:
    """Tonal monochromatic categorical palettes (M2)."""

    @pytest.mark.parametrize(
        ("name", "anchor"),
        [
            ("category-6-tonal-blue", "#0375c4"),
            ("category-6-tonal-green", "#00875a"),
            ("category-6-tonal-purple", "#9650a8"),
            ("category-6-tonal-orange", "#b74c1f"),
            ("category-6-tonal-brown", "#9a642b"),
        ],
    )
    def test_tonal_palette_ships_six_stops(self, name: str, anchor: str) -> None:
        stops = palette(name)
        assert len(stops) == 6
        assert stops[0].lower() == anchor.lower()

    def test_tonal_palette_strict_safe_core_passes_leonardo(self) -> None:
        """Slots 0-3 of every tonal palette must pairwise pass Leonardo ΔE ≥ 11
        across normal / deuteranopia / protanopia / tritanopia.

        Achromatopsia is intentionally excluded — it's stricter than the
        Leonardo standard four, and the contract advertised in the guide
        and YAML descriptions is Leonardo's four. (The shipped palettes
        do incidentally pass achromatopsia at the same gate, but pinning
        that here would make a hypothetical re-tune that fails *only*
        achromatopsia surprising to a future palette author who read the
        documented contract.)
        See docs/guides/palettes.md#tonal-monochrome-category-6-tonal-
        """
        leonardo_visions = ("normal", "deuteranopia", "protanopia", "tritanopia")
        for name in (
            "category-6-tonal-blue",
            "category-6-tonal-green",
            "category-6-tonal-purple",
            "category-6-tonal-orange",
            "category-6-tonal-brown",
        ):
            core = palette(name)[:4]
            for vision in leonardo_visions:
                matrix = _checker.VISION_MATRICES[vision]
                labs = []
                for hx in core:
                    rgb = _checker.hex_to_rgb01(hx.lower())
                    lin = (
                        _checker.srgb_to_linear(rgb[0]),
                        _checker.srgb_to_linear(rgb[1]),
                        _checker.srgb_to_linear(rgb[2]),
                    )
                    sim = _checker.apply_matrix(lin, matrix)
                    labs.append(_checker.xyz_to_lab(_checker.linear_rgb_to_xyz(sim)))
                pair_deltas = [
                    _checker.delta_e_ciede2000(labs[i], labs[j])
                    for i, j in itertools.combinations(range(4), 2)
                ]
                assert min(pair_deltas) >= 11.0, (
                    f"{name} core-4 fails Leonardo gate under {vision}: "
                    f"min ΔE = {min(pair_deltas):.2f}"
                )

    # test_studio_output_matches_shipped_yaml is intentionally not covered
    # here — it loads ai_notes/palette_studio/tonal_session.py, which is
    # outside dbt-charts/.

    @pytest.mark.parametrize(
        ("name", "anchor_hue", "wobble_tolerance"),
        [
            # All 6 stops within ±8° of anchor (the brief's "tonal" tolerance).
            ("category-6-tonal-blue", 248.8, 8.0),
            ("category-6-tonal-green", 161.3, 8.0),
            ("category-6-tonal-purple", 319.1, 8.0),
            ("category-6-tonal-orange", 41.0, 8.0),
            # Brown is documented as a special case: extended slots 4-5 wobble
            # +14° toward H≈78° to bridge into dbt-creams. So core slots are
            # within ±8°; extended slots can be up to 18° off the anchor.
            ("category-6-tonal-brown", 64.0, 18.0),
        ],
    )
    def test_tonal_palette_hue_stays_in_family(
        self, name: str, anchor_hue: float, wobble_tolerance: float
    ) -> None:
        """Defining property of a tonal palette: every stop shares the anchor
        hue within tolerance. Catches a re-tune that quietly broke single-hue
        identity (e.g. someone replacing a slot with a different hue family
        that still passes Leonardo).
        """
        for hx in palette(name):
            _, _, hue = _checker.hex_to_oklch(hx)
            # Circular distance, in case anchor is near the 0/360 boundary.
            delta = min(abs(hue - anchor_hue), 360 - abs(hue - anchor_hue))
            assert delta <= wobble_tolerance, (
                f"{name} stop {hx} at H={hue:.1f}° is "
                f"{delta:.1f}° from anchor {anchor_hue}° (tol {wobble_tolerance}°)"
            )


class TestPaletteScaffold:
    def test_dbt_grays_via_palette_raises(self):
        # Scaffolds are flat-mapping palettes; surface= must raise.
        with pytest.raises(SurfaceUnsupportedError):
            palette("dbt-grays", surface="table")

    def test_dbt_grays_via_color_slot(self):
        assert color("dbt-grays.ink").lower() == "#222222"
        assert color("dbt-creams.ink").lower() == "#2a2725"


# ============================================================================
# color() — semantic + scaffold tokens
# ============================================================================


class TestColor:
    def test_tone_slot(self):
        assert color("negative.solid").lower() == "#94001e"
        assert color("positive.solid").lower() == "#00884d"

    def test_unknown_role_raises(self):
        with pytest.raises(UnknownColorError):
            color("nonexistent.solid")

    def test_unknown_slot_raises(self):
        with pytest.raises(UnknownColorError):
            color("negative.nonexistent")

    def test_missing_dot_raises(self):
        with pytest.raises(UnknownColorError):
            color("negative")


# ============================================================================
# Exception classes
# ============================================================================


class TestExceptions:
    def test_unknown_palette_message_suggests_nearest(self):
        with pytest.raises(UnknownPaletteError) as excinfo:
            palette("dbt-seq-bule")  # typo
        assert "dbt-seq-blue" in str(excinfo.value)

    def test_tone_via_palette_raises(self):
        with pytest.raises(ToneAsPaletteError):
            palette("negative")


# ============================================================================
# Anti-patterns (§10)
# ============================================================================


class TestAntiPatterns:
    def test_jet_raises(self):
        with pytest.raises(UnknownPaletteError):
            palette("jet")

    def test_rainbow_raises(self):
        with pytest.raises(UnknownPaletteError):
            palette("rainbow")

    def test_hsv_raises(self):
        with pytest.raises(UnknownPaletteError):
            palette("hsv")

    def test_rdylgn_resolves_without_warning(self):
        """palette() resolves anti-pattern aliases silently — the
        WARN-PALETTE-UNSUPPORTED nudge is now a render-stage detector over the
        compiled board's requested_alias_palette, not an inline emit here."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            stops = palette("RdYlGn")
            assert len(stops) > 0
            assert not w, f"palette() must not warn directly; got {w}"

    def test_parula_resolves_without_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            stops = palette("parula")
            assert len(stops) > 0
            assert not w, f"palette() must not warn directly; got {w}"

    def test_hard_fail_error_message_points_at_palette_resolver(self):
        with pytest.raises(UnknownPaletteError) as excinfo:
            palette("jet")
        assert "docs/guides/palette-resolver.md#anti-patterns" in str(excinfo.value)


class TestResolvePaletteAlias:
    """resolve_palette_alias() is the single source of anti-pattern detection
    the CategoricalColorStyle model_validator uses to retain the requested
    name for the render-stage detector."""

    def test_warn_alias_name_reports_original_name(self):
        stops, requested = resolve_palette_alias("RdYlGn")
        assert len(stops) > 0
        assert requested == "RdYlGn"

    def test_warn_alias_shorthand_still_reports_base_name(self):
        stops, requested = resolve_palette_alias("RdYlGn:5")
        assert len(stops) == 5
        assert requested == "RdYlGn"

    def test_non_alias_name_reports_none(self):
        stops, requested = resolve_palette_alias("dbt-seq-blue")
        assert len(stops) > 0
        assert requested is None


# ============================================================================
# list_palettes / palette_metadata
# ============================================================================


class TestDiscovery:
    def test_list_all(self):
        names = list_palettes()
        assert "dbt-seq-blue" in names
        assert "vivid-10" in names
        assert "negative" in names
        assert "dbt-grays" in names

    def test_list_filtered_by_family(self):
        seq_names = list_palettes(family="sequential")
        assert "dbt-seq-blue" in seq_names
        assert "vivid-10" not in seq_names
        assert "negative" not in seq_names

    def test_list_tone_family(self):
        tone_names = list_palettes(family="tone")
        assert "negative" in tone_names
        assert "positive" in tone_names
        assert "warning" in tone_names
        assert "info" in tone_names
        assert len(tone_names) == 4

    def test_palette_metadata_basic(self):
        meta = palette_metadata("dbt-seq-blue")
        assert meta["name"] == "dbt-seq-blue"
        assert meta["family"] == "sequential"
        assert "description" in meta


# ============================================================================
# select_default_palette
# ============================================================================


class TestSelectDefault:
    def test_continuous_numeric(self):
        assert select_default_palette("continuous_numeric") == "dbt-seq-blue"

    def test_signed_numeric(self):
        assert select_default_palette("signed_numeric") == "dbt-div-blue-red"

    def test_discrete_enum(self):
        assert select_default_palette("discrete_enum") == "vivid-10"


# ============================================================================
# resolve_dark_companion_stops — direct-label inking
# ============================================================================


class TestResolveDarkCompanionStops:
    """The direct-label companion resolver is palette-agnostic: it auto-detects
    which registered categorical palette the emitted colors came from and
    looks up ``<bright>-dark``. Today's catalog has two such pairs registered:
    ``vivid-10`` ↔ ``vivid-10-dark`` (default theme) and
    ``editorial-10`` ↔ ``editorial-10-dark`` (editorial themes).
    """

    def test_editorial_10_stops_auto_resolve_to_editorial_10_dark(self):
        """The case that motivated this fix.

        Chart rendered under the editorial theme cycles ``editorial-10`` stops.
        Without auto-detection, the resolver would fall back to ``vivid-10``
        lookup (no match for editorial-10 hexes) and return the bright colors
        unchanged — labels would render at the same color as their marks.
        """
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        editorial_stops = palette("editorial-10", steps=5)
        result = resolve_dark_companion_stops(editorial_stops)
        expected = palette("editorial-10-dark", steps=5)
        assert result == expected

    def test_vivid_10_stops_resolve_to_vivid_10_dark(self):
        """Status-quo behavior preserved: vivid-10 marks still get
        vivid-10-dark companions when no palette name is passed."""
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        cat10_stops = palette("vivid-10", steps=5)
        result = resolve_dark_companion_stops(cat10_stops)
        expected = palette("vivid-10-dark", steps=5)
        assert result == expected

    def test_custom_hex_falls_through_to_bright(self):
        """When emitted colors don't match any registered palette (board
        author hand-pinned hex via ``style.range.category``), labels match
        the marks — same as today's behavior in that path."""
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        custom = ["#aabbcc", "#ddeeff", "#112233"]
        assert resolve_dark_companion_stops(custom) == custom

    def test_explicit_palette_name_disambiguates_auto_detect(self):
        """Callers that know the palette name can pass it to skip detection.

        Forward-compat affordance for the chart-series-label-color-binding
        follow-up task — once compiled-style carries the palette name, both
        call sites can plumb it through and bypass the auto-detect scan.
        """
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        editorial_stops = palette("editorial-10", steps=3)
        result = resolve_dark_companion_stops(
            editorial_stops, bright_palette_name="editorial-10"
        )
        expected = palette("editorial-10-dark", steps=3)
        assert result == expected

    def test_unknown_explicit_palette_name_falls_through_to_bright(self):
        """An explicit palette name that has no dark companion registered
        falls through to the bright colors rather than raising."""
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        editorial_stops = palette("editorial-10", steps=3)
        result = resolve_dark_companion_stops(
            editorial_stops, bright_palette_name="fake-palette"
        )
        assert result == editorial_stops

    def test_empty_input_returns_empty(self):
        """Defensive: zero-series chart shouldn't crash the resolver."""
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        assert resolve_dark_companion_stops([]) == []

    def test_off_by_one_emit_returns_wrong_slot_companions(self):
        """If a chart emits colors starting from a non-slot-0 stop (the
        ``palette[1:n+1]`` off-by-one currently affecting line/area charts;
        tracked in chart-series-label-color-binding), per-color lookup finds
        each color at its actual index in vivid-10 and returns the dark
        companion at that index.

        This means the resolver-side behavior is "dark companion at the wrong
        slot" — the caller passed wrong input. The chart-series-label-color-
        binding task fixes the upstream caller.
        """
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        # Cat-10 slots at indices 1-3 (skipping slot-0) — what line/area charts
        # emit today under the off-by-one bug.
        cat10 = palette("vivid-10")
        cat10_dark = palette("vivid-10-dark")
        skipped_emit = cat10[1:4]
        assert skipped_emit[0] != cat10[0]
        result = resolve_dark_companion_stops(skipped_emit)
        # Per-color: each is found at its actual index → returns dark at that index.
        assert result == [cat10_dark[1], cat10_dark[2], cat10_dark[3]]

    def test_author_picked_non_slot_0_editorial_10_slots_resolve_correctly(self):
        """Author picks editorial-10 indices 1 and 5. Under slot-0 equality
        the first color fails detection and both labels fall
        through to bright. Under per-color lookup each is found at its actual
        index and returns the correct dark companion.
        """
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        editorial = palette("editorial-10")
        author_picks = [editorial[1], editorial[5]]
        result = resolve_dark_companion_stops(author_picks)
        e10_dark = palette("editorial-10-dark")
        assert result == [e10_dark[1], e10_dark[5]]

    def test_mixed_palette_picks_resolve_each_to_own_dark(self):
        """One color from vivid-10 and one from editorial-10. Each resolves
        independently to its own palette's dark companion.
        """
        from dbt_charts.core.compile.resolve.style.palette import (
            resolve_dark_companion_stops,
        )

        cat10_slot3 = palette("vivid-10")[3]  # #e1a500
        e10_slot1 = palette("editorial-10")[1]
        result = resolve_dark_companion_stops([cat10_slot3, e10_slot1])
        assert result == [
            palette("vivid-10-dark")[3],
            palette("editorial-10-dark")[1],
        ]


def test_palette_index_and_spine_use_iterdir_and_read_text_not_glob_or_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_glob_traversable: Callable[[Path], Any],
) -> None:
    """Regression: building the palette index and loading a spine must use
    iterdir()/read_text(), never glob()/.open() — this test's double
    implements only the importlib.resources.Traversable protocol."""
    from dbt_charts.core.compile.resolve.style import palette as palette_mod

    cat_dir = tmp_path / "categorical"
    cat_dir.mkdir()
    (cat_dir / "zz-fake-b.yml").write_text("name: zz-fake-b\ncolors: ['#111111']\n")
    (cat_dir / "zz-fake-a.yml").write_text("name: zz-fake-a\ncolors: ['#222222']\n")

    monkeypatch.setattr(palette_mod, "_PALETTES_DIR", no_glob_traversable(tmp_path))
    monkeypatch.setattr(palette_mod, "_index", None)
    try:
        names = palette_mod.list_palettes(family="categorical")
        assert names == ["zz-fake-a", "zz-fake-b"]

        spine = palette_mod._load_spine("zz-fake-a")
        assert spine.colors == ["#222222"]
    finally:
        monkeypatch.setattr(palette_mod, "_index", None)
        palette_mod._spine_cache.pop("zz-fake-a", None)
        palette_mod._spine_cache.pop("zz-fake-b", None)
