"""Regression tests for the editorial-10 categorical palette.

Editorial-10 is the default categorical palette for the clarity and paper
themes. stark keeps vivid-10. The palette ships under the
core defaults catalog (resolved via `dbt_charts.core.compile.resolve.style.palette.palette`)
and the studio rationale lives in
`ai_notes/palette_studio/session7_editorial_categorical/BRIEF.md`.

Regression contracts pinned here, for the base palette:

  1. Stop identity — the 10 hex stops never drift silently. Editing the YAML
     forces an update here, which catches palette-content changes during review.
  2. N=5 Leonardo — the first five stops (the most-common cardinality for
     editorial charts) must remain pairwise-discriminable at ΔE ≥ 11 across
     the three primary CVD modes (deut / prot / trit).
  3. Theme wiring — clarity + paper resolve to editorial-10;
     stark keeps vivid-10.

and, for each companion family (dark / light / ghost / ink): a locked stop
set, a stop-count match with the base for positional pairing, and a per-slot
pairing contract (each companion's lightness/hue relationship to its base
stop). Every slot has five distinct, strictly ordered lightness tiers.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from dbt_charts.core.colors import wcag_contrast as _wcag_contrast
from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.resolve.style.palette import palette

from .._paths import DBT_CHARTS_DIR as _DBT_CHARTS_DIR

# Load palette_deltae_checker as a module (it's a script, not a package).
_checker_path = _DBT_CHARTS_DIR / "scripts" / "palette_deltae_checker.py"
_spec = importlib.util.spec_from_file_location("palette_deltae_checker", _checker_path)
assert _spec is not None and _spec.loader is not None
_checker = importlib.util.module_from_spec(_spec)
sys.modules["palette_deltae_checker"] = _checker
_spec.loader.exec_module(_checker)


# Locked editorial-10 stops. If you change the palette YAML, update this list
# (and the BRIEF and the docs guide).
EDITORIAL_10_STOPS = [
    "#40639c",  # 1  blue
    "#779bc9",  # 2  sky
    "#608470",  # 3  green
    "#775770",  # 4  purple
    "#d49656",  # 5  gold
    "#ae6349",  # 6  rust
    "#a0b6b7",  # 7  teal
    "#ad9c7f",  # 8  brown
    "#7a8895",  # 9  gray
    "#5c6668",  # 10 graphite
]


PRIMARY_CVD_MODES = ("deuteranopia", "protanopia", "tritanopia")
LEONARDO_THRESHOLD = 11.0
VISION_WEIGHTS = {
    "normal": 1.0,
    "deuteranopia": 1.0,
    "protanopia": 1.0,
    "tritanopia": 0.15,
    "achromatopsia": 0.05,
}
EDITORIAL_10_PREFIX_CURVE = [
    100.0,
    99.479167,
    99.218750,
    99.375000,
    97.083333,
    97.767857,
    97.042411,
    97.352431,
    96.354167,
]


def _delta_e_under_cvd(hex_a: str, hex_b: str, mode: str) -> float:
    rgb_a = _checker.hex_to_rgb01(hex_a)
    rgb_b = _checker.hex_to_rgb01(hex_b)
    sim_a = _checker.simulate_vision(rgb_a, mode)
    sim_b = _checker.simulate_vision(rgb_b, mode)
    return _checker.delta_e_ciede2000(
        _checker.linear_rgb_to_lab(sim_a),
        _checker.linear_rgb_to_lab(sim_b),
    )


def test_editorial_10_stops_match_locked_set():
    """Stop identity regression. Drift fails loudly."""
    stops = palette("editorial-10", steps=10)
    assert stops == EDITORIAL_10_STOPS, (
        "editorial-10 palette has drifted from the locked set. If this is "
        "intentional, update EDITORIAL_10_STOPS in this test AND "
        "ai_notes/palette_studio/session7_editorial_categorical/BRIEF.md AND "
        "docs/guides/palettes.md#editorial-10-default-for-editorial-themes to match."
    )


@pytest.mark.parametrize("vision", PRIMARY_CVD_MODES)
def test_n5_prefix_passes_leonardo_under_cvd(vision: str):
    """The first 5 stops are pairwise-discriminable under each primary CVD mode.

    1-5 series is the cardinality range where editorial-10's cycling
    posture matters most. Below ΔE >= 11 (Leonardo) we lose CVD discrimination
    on at least one pair, which would break the editorial-restraint contract.
    """
    stops = EDITORIAL_10_STOPS[:5]
    failing_pairs = []
    for i in range(len(stops)):
        for j in range(i + 1, len(stops)):
            de = _delta_e_under_cvd(stops[i], stops[j], vision)
            if de < LEONARDO_THRESHOLD:
                failing_pairs.append((stops[i], stops[j], round(de, 2)))
    assert not failing_pairs, (
        f"editorial-10 N=5 prefix fails Leonardo under {vision}: "
        f"{failing_pairs}. Lower-N is the cardinality editorial boards "
        "actually hit; a regression here is a ship-blocker."
    )


def test_editorial_10_weighted_prefix_curve_matches_locked_values() -> None:
    actual: list[float] = []
    for prefix_size in range(2, 11):
        passing_weight = 0.0
        for first in range(prefix_size):
            for second in range(first + 1, prefix_size):
                for vision, weight in VISION_WEIGHTS.items():
                    if (
                        _delta_e_under_cvd(
                            EDITORIAL_10_STOPS[first],
                            EDITORIAL_10_STOPS[second],
                            vision,
                        )
                        >= LEONARDO_THRESHOLD
                    ):
                        passing_weight += weight
        denominator = 3.2 * (prefix_size * (prefix_size - 1) / 2)
        actual.append(round(100 * passing_weight / denominator, 6))

    assert actual == EDITORIAL_10_PREFIX_CURVE


def test_clarity_themes_use_editorial_10():
    """Theme cascade: clarity + paper resolve to editorial-10."""
    clarity_cat = get_theme_style("clarity").charts.color.categorical
    paper_cat = get_theme_style("paper").charts.color.categorical
    assert clarity_cat is not None and clarity_cat.palette is not None
    assert paper_cat is not None and paper_cat.palette is not None
    clarity = clarity_cat.palette
    paper = paper_cat.palette
    assert clarity == EDITORIAL_10_STOPS, (
        f"clarity theme no longer resolves to editorial-10. Got: {clarity[:3]}..."
    )
    assert paper == EDITORIAL_10_STOPS, (
        f"paper theme no longer resolves to editorial-10. Got: {paper[:3]}..."
    )


def test_clarity_themes_rebind_category_roles():
    """Theme-relative role refs must follow the theme's palette family.

    `style.palettes` binds the category/category_dark/category_light/
    category_ghost roles that theme-portable refs like `category[2]` or
    `category_dark[2]` resolve through. The _base cascade root binds them
    to the vivid-10 family; editorial-voiced themes must rebind them to
    editorial-10, otherwise a board authored with role refs keeps stark's
    colors after a theme switch.
    """
    for theme in ("clarity", "paper"):
        bound = get_theme_style(theme).palettes
        assert bound["category"] == "editorial-10", (
            f"{theme} theme leaves the `category` role on "
            f"{bound['category']!r} — role refs won't follow the theme."
        )
        for role in (
            "category_dark",
            "category_light",
            "category_ghost",
            "category_ink",
        ):
            expected = "editorial-10-" + role.removeprefix("category_")
            assert bound[role] == expected, (
                f"{theme} theme leaves the `{role}` role on {bound[role]!r}; "
                f"expected {expected!r}."
            )


def test_structural_root_keeps_category_role_family():
    """stark (and the cascade root) stay on the vivid-10 family."""
    bound = get_theme_style("stark").palettes
    assert bound["category"] == "vivid-10"
    assert bound["category_dark"] == "vivid-10-dark"
    assert bound["category_light"] == "vivid-10-light"
    assert bound["category_ghost"] == "vivid-10-ghost"


def test_geoshape_basemap_fill_comes_from_the_scaffold_not_a_data_palette():
    """Basemap terrain is chrome, so it comes from the scaffold ladder.

    A categorical swatch is chosen to hold its own against other series;
    a basemap has the opposite job — it must recede behind the marks drawn
    on it. Four light themes previously sourced this from a categorical
    palette, and the darkest of them rendered a mid-tone mark effectively
    invisible against the terrain.

    Each theme takes its terrain from the scaffold matching its canvas.
    Cream sits a step lighter than the gray themes on purpose: the warm
    ladder is tinted at every step, so the value that reads as neutral
    ground on a gray canvas reads as a tan continent on cream.
    """
    gray_step = palette("dbt-grays", steps=12)[4]
    cream_step = palette("dbt-creams", steps=12)[2]
    expected = {
        "stark": gray_step,
        "clarity": gray_step,
        "paper": cream_step,
        "vivid": gray_step,
    }
    for theme, want in expected.items():
        fill = get_theme_style(theme).charts.marks.geoshape.fill
        assert fill == want, (
            f"{theme} basemap fill is {fill!r}; expected the scaffold step "
            f"{want!r}. Basemap chrome must not come from a categorical "
            f"data palette."
        )


def test_structural_root_theme_still_uses_vivid_10():
    """Regression guard: stark keeps vivid-10 unchanged.

    The structural-root theme (stark, opt-in for the stripped-back look)
    continues to use vivid-10. The shipped default theme uses editorial-10
    (covered by test_clarity_themes_use_editorial_10 above).
    """
    stark_cat = get_theme_style("stark").charts.color.categorical
    assert stark_cat is not None and stark_cat.palette is not None
    # stark must differ from editorial-10 slot 1 (distinct palette identity).
    assert stark_cat.palette[0] != EDITORIAL_10_STOPS[0], (
        "stark theme palette slot 1 matches editorial-10 slot 1 — "
        "stark must keep vivid-10, not editorial-10."
    )


# ----------------------------------------------------------------------------
# editorial-10-dark — direct-label inking companion
# ----------------------------------------------------------------------------

# Locked editorial-10-dark stops. Edit in lock-step with editorial-10.yml.
EDITORIAL_10_DARK_STOPS = [
    "#23467f",  # 1  blue
    "#476b98",  # 2  sky
    "#3d614e",  # 3  green
    "#5b3b55",  # 4  purple
    "#955902",  # 5  gold
    "#8a3f24",  # 6  rust
    "#586e6f",  # 7  teal
    "#77664a",  # 8  brown
    "#54626f",  # 9  gray
    "#424c4e",  # 10 graphite
]


def test_editorial_10_dark_stops_match_locked_set():
    """Stop identity regression for the dark companion."""
    stops = palette("editorial-10-dark", steps=10)
    assert stops == EDITORIAL_10_DARK_STOPS, (
        "editorial-10-dark palette has drifted from the locked set. If "
        "intentional, update EDITORIAL_10_DARK_STOPS in this test AND the "
        "Companion palette subsection at "
        "docs/guides/palettes.md#companion-palette-editorial-10-dark."
    )


def test_editorial_10_dark_length_matches_main():
    """Positional pairing requires identical stop counts."""
    main = palette("editorial-10", steps=10)
    dark = palette("editorial-10-dark", steps=10)
    assert len(main) == len(dark), (
        "editorial-10-dark must have the same number of stops as editorial-10 "
        f"for positional pairing (main={len(main)}, dark={len(dark)})."
    )


@pytest.mark.parametrize("slot", range(10))
def test_editorial_10_dark_pairing_per_slot(slot: int):
    """Each dark stop has lower L* and the same hue as its editorial-10 pair.

    The pairing contract: editorial-10-dark[N] inks labels for series
    rendered with editorial-10[N]. Same hue family, perceptibly darker.
    Hue drift up to 8° is acceptable (gamut clipping during OKLCH→sRGB
    can shift hue slightly at the chroma boundary; CIELAB and OKLCH hue
    angles also disagree mildly even for the same color).

    The refreshed graphite slot has a distinct dark stop; there are no
    equality exceptions in the family.
    """
    main_L, _, main_H = _checker.hex_to_oklch(EDITORIAL_10_STOPS[slot])
    dark_L, _, dark_H = _checker.hex_to_oklch(EDITORIAL_10_DARK_STOPS[slot])

    # Lower L*: dark companion must be measurably darker. Threshold of 5
    # OKLCH units leaves comfortable margin against the smallest measured
    # gap in the locked stops while still admitting future taste-driven
    # tuning that stays inside the contract.
    assert dark_L < main_L - 0.05, (
        f"editorial-10-dark slot {slot + 1} is not measurably darker than "
        f"editorial-10 slot {slot + 1} "
        f"(main L={main_L:.3f}, dark L={dark_L:.3f}). "
        "Direct labels won't ink properly if the companion isn't darker."
    )

    # Same hue within tolerance, with circular distance across 0°/360°.
    hue_diff = abs(main_H - dark_H)
    hue_diff = min(hue_diff, 360 - hue_diff)
    assert hue_diff < 10, (
        f"editorial-10-dark slot {slot + 1} drifted in hue from its "
        f"editorial-10 pair (main H={main_H:.1f}°, dark H={dark_H:.1f}°, "
        f"Δ={hue_diff:.1f}°). The pairing contract says same hue."
    )


# ----------------------------------------------------------------------------
# editorial-10-light — moderate light companion
# ----------------------------------------------------------------------------

# Locked editorial-10-light stops. Edit in lock-step with editorial-10.yml.
EDITORIAL_10_LIGHT_STOPS = [
    "#7990b6",  # 1  blue
    "#a3bad7",  # 2  sky
    "#8ea598",  # 3  green
    "#9a8595",  # 4  purple
    "#e0b993",  # 5  gold
    "#c29180",  # 6  rust
    "#bdcacb",  # 7  teal
    "#c7bcaa",  # 8  brown
    "#a0a9b1",  # 9  gray
    "#8a9092",  # 10 graphite
]


def test_editorial_10_light_stops_match_locked_set():
    """Stop identity regression for the light companion."""
    stops = palette("editorial-10-light", steps=10)
    assert stops == EDITORIAL_10_LIGHT_STOPS, (
        "editorial-10-light palette has drifted from the locked set. If "
        "intentional, update EDITORIAL_10_LIGHT_STOPS in this test AND the "
        "Companion palette subsection at "
        "docs/guides/palettes.md#companion-palette-editorial-10-light."
    )


def test_editorial_10_light_length_matches_main_and_dark():
    """Positional pairing requires identical stop counts across the trio."""
    main = palette("editorial-10", steps=10)
    dark = palette("editorial-10-dark", steps=10)
    light = palette("editorial-10-light", steps=10)
    assert len(main) == len(dark) == len(light) == 10, (
        "editorial-10, editorial-10-dark, and editorial-10-light must have "
        "matching stop counts for positional pairing "
        f"(main={len(main)}, dark={len(dark)}, light={len(light)})."
    )


@pytest.mark.parametrize("slot", range(10))
def test_editorial_10_light_pairing_per_slot(slot: int):
    """Each light stop is lighter than base (and than dark), no more chromatic,
    same hue.

    The light companion is no longer required to mirror the dark companion's
    exact OKLCH L gap. That mirror was a derivation convenience, not a
    user-visible property, and it forced gold-light onto a lightness outlier
    (gold's large dark drop demanded an equally large light lift). The contract
    is now directional only: lighter than base, lighter than dark, no louder,
    same hue.
    """
    main_L, main_C, main_H = _checker.hex_to_oklch(EDITORIAL_10_STOPS[slot])
    dark_L, _, _ = _checker.hex_to_oklch(EDITORIAL_10_DARK_STOPS[slot])
    light_L, light_C, light_H = _checker.hex_to_oklch(EDITORIAL_10_LIGHT_STOPS[slot])

    assert light_L > main_L, (
        f"editorial-10-light slot {slot + 1} is not lighter than "
        f"editorial-10 slot {slot + 1} "
        f"(main L={main_L:.3f}, light L={light_L:.3f})."
    )
    assert light_L > dark_L, (
        f"editorial-10-light slot {slot + 1} is not lighter than "
        f"editorial-10-dark slot {slot + 1} "
        f"(dark L={dark_L:.3f}, light L={light_L:.3f})."
    )
    assert light_C <= main_C + 0.005, (
        f"editorial-10-light slot {slot + 1} is more chromatic than its "
        f"editorial-10 pair (main C={main_C:.3f}, light C={light_C:.3f})."
    )

    hue_diff = abs(main_H - light_H)
    hue_diff = min(hue_diff, 360 - hue_diff)
    assert hue_diff < 10, (
        f"editorial-10-light slot {slot + 1} drifted in hue from its "
        f"editorial-10 pair (main H={main_H:.1f}°, light H={light_H:.1f}°, "
        f"Δ={hue_diff:.1f}°). The pairing contract says same hue."
    )


# ----------------------------------------------------------------------------
# editorial-10-ghost — extreme de-emphasis companion
# ----------------------------------------------------------------------------

# Locked editorial-10-ghost stops. Edit in lock-step with editorial-10.yml.
EDITORIAL_10_GHOST_STOPS = [
    "#c5d2e7",  # 1  blue
    "#cdd9e8",  # 2  sky
    "#c5d1ca",  # 3  green
    "#d6cad2",  # 4  purple
    "#e8d3c0",  # 5  gold
    "#e2c7be",  # 6  rust
    "#d8e0e0",  # 7  teal
    "#dcd7cd",  # 8  brown
    "#caced3",  # 9  gray
    "#c8cbcc",  # 10 graphite
]


def test_editorial_10_ghost_stops_match_locked_set():
    """Stop identity regression for the ghost companion."""
    stops = palette("editorial-10-ghost", steps=10)
    assert stops == EDITORIAL_10_GHOST_STOPS, (
        "editorial-10-ghost palette has drifted from the locked set. If "
        "intentional, update EDITORIAL_10_GHOST_STOPS in this test AND the "
        "Companion palette subsection at "
        "docs/guides/palettes.md#companion-palette-editorial-10-ghost."
    )


def test_editorial_10_ghost_length_matches_trio():
    """Positional pairing requires identical stop counts across the variants."""
    main = palette("editorial-10", steps=10)
    dark = palette("editorial-10-dark", steps=10)
    light = palette("editorial-10-light", steps=10)
    ghost = palette("editorial-10-ghost", steps=10)
    assert len(main) == len(dark) == len(light) == len(ghost) == 10, (
        "editorial-10 variants must have matching stop counts for positional "
        f"pairing (main={len(main)}, dark={len(dark)}, light={len(light)}, "
        f"ghost={len(ghost)})."
    )


@pytest.mark.parametrize("slot", range(10))
def test_editorial_10_ghost_pairing_per_slot(slot: int):
    """Each ghost stop is much lighter and no more chromatic than its base pair."""
    main_L, main_C, main_H = _checker.hex_to_oklch(EDITORIAL_10_STOPS[slot])
    ghost_L, ghost_C, ghost_H = _checker.hex_to_oklch(EDITORIAL_10_GHOST_STOPS[slot])

    assert ghost_L > main_L + 0.10, (
        f"editorial-10-ghost slot {slot + 1} is not far lighter than "
        f"editorial-10 slot {slot + 1} "
        f"(main L={main_L:.3f}, ghost L={ghost_L:.3f})."
    )
    assert ghost_C <= main_C + 0.005, (
        f"editorial-10-ghost slot {slot + 1} is more chromatic than its "
        f"editorial-10 pair (main C={main_C:.3f}, ghost C={ghost_C:.3f})."
    )

    hue_diff = abs(main_H - ghost_H)
    hue_diff = min(hue_diff, 360 - hue_diff)
    assert hue_diff < 10, (
        f"editorial-10-ghost slot {slot + 1} drifted in hue from its "
        f"editorial-10 pair (main H={main_H:.1f}°, ghost H={ghost_H:.1f}°, "
        f"Δ={hue_diff:.1f}°). The pairing contract says same hue."
    )


# ----------------------------------------------------------------------------
# editorial-10-ink — ink-grade single-series companion
# ----------------------------------------------------------------------------

# Locked editorial-10-ink stops. Edit in lock-step with editorial-10.yml.
EDITORIAL_10_INK_STOPS = [
    "#0f2c5a",  # 1  blue
    "#1c395c",  # 2  sky
    "#1f3d2d",  # 3  green
    "#3d2438",  # 4  purple
    "#563000",  # 5  gold
    "#591d05",  # 6  rust
    "#2b3c3c",  # 7  teal
    "#43361f",  # 8  brown
    "#29343e",  # 9  gray
    "#252d2f",  # 10 graphite
]

# Contract band for the locked ink family: compact OKLCH L 0.29–0.37.
_INK_BAND_LO, _INK_BAND_HI = 0.29, 0.37


def test_editorial_10_ink_stops_match_locked_set():
    """Stop identity regression for the ink companion."""
    stops = palette("editorial-10-ink", steps=10)
    assert stops == EDITORIAL_10_INK_STOPS, (
        "editorial-10-ink palette has drifted from the locked set. If "
        "intentional, update EDITORIAL_10_INK_STOPS in this test AND the "
        "Companion palette subsection at "
        "docs/guides/palettes.md#companion-palette-editorial-10-ink."
    )


def test_editorial_10_ink_length_matches_main():
    """Positional pairing requires identical stop counts."""
    main = palette("editorial-10", steps=10)
    ink = palette("editorial-10-ink", steps=10)
    assert len(main) == len(ink) == 10, (
        "editorial-10-ink must have the same number of stops as editorial-10 "
        f"for positional pairing (main={len(main)}, ink={len(ink)})."
    )


@pytest.mark.parametrize("slot", range(10))
def test_editorial_10_ink_pairing_per_slot(slot: int):
    """Each ink stop sits in the tight dark band and is darker than its base.

    Hue is intentionally not asserted here: unlike the lighter companions,
    the deep low-L ink stops clip enough in sRGB that a couple (near-neutral
    gray, very-dark gold) drift past the 8° the others hold. Slot identity for
    ink is carried by the locked set above, not a hue-pairing contract.

    The refreshed graphite slot has a distinct ink stop; there are no
    equality exceptions in the family.
    """
    main_L, _, _ = _checker.hex_to_oklch(EDITORIAL_10_STOPS[slot])
    ink_L, _, _ = _checker.hex_to_oklch(EDITORIAL_10_INK_STOPS[slot])

    assert _INK_BAND_LO <= ink_L <= _INK_BAND_HI, (
        f"editorial-10-ink slot {slot + 1} L={ink_L:.3f} is outside the "
        f"documented ink band [{_INK_BAND_LO}, {_INK_BAND_HI}]."
    )

    assert ink_L < main_L, (
        f"editorial-10-ink slot {slot + 1} is not darker than editorial-10 "
        f"slot {slot + 1} (main L={main_L:.3f}, ink L={ink_L:.3f})."
    )


@pytest.mark.parametrize("slot", range(10))
def test_editorial_10_family_has_strict_lightness_order(slot: int) -> None:
    tiers = (
        EDITORIAL_10_GHOST_STOPS[slot],
        EDITORIAL_10_LIGHT_STOPS[slot],
        EDITORIAL_10_STOPS[slot],
        EDITORIAL_10_DARK_STOPS[slot],
        EDITORIAL_10_INK_STOPS[slot],
    )
    lightness = [_checker.hex_to_oklch(color)[0] for color in tiers]
    assert all(
        upper > lower for upper, lower in zip(lightness, lightness[1:], strict=False)
    ), f"slot {slot + 1} family paths cross: {lightness}"


@pytest.mark.parametrize("canvas", ["#ffffff", "#fafafa", "#faf7f0"])
@pytest.mark.parametrize("slot", range(10))
def test_editorial_10_dark_clears_small_text_contrast(slot: int, canvas: str) -> None:
    assert _wcag_contrast(EDITORIAL_10_DARK_STOPS[slot], canvas) >= 4.5
