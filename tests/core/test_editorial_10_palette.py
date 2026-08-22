"""Regression tests for the editorial-10 categorical palette.

Editorial-10 is the default categorical palette for the editorial / cream
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
  3. Theme wiring — editorial + cream resolve to editorial-10;
     stark keeps vivid-10.

and, for each companion family (dark / light / ghost / ink): a locked stop
set, a stop-count match with the base for positional pairing, and a per-slot
pairing contract (each companion's lightness/hue relationship to its base
stop, with the charcoal slot 10 carve-out where dark and ink equal the base).
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

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
    "#3164a3",  # 1  denim
    "#779bc9",  # 2  sky
    "#ad9c7f",  # 3  sand
    "#7a8895",  # 4  gray
    "#8a576f",  # 5  plum
    "#5c7b5c",  # 6  green
    "#d49656",  # 7  gold
    "#ae6349",  # 8  rust
    "#609f9e",  # 9  teal
    "#232f3a",  # 10 charcoal
]


PRIMARY_CVD_MODES = ("deuteranopia", "protanopia", "tritanopia")
LEONARDO_THRESHOLD = 11.0


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


def test_editorial_themes_use_editorial_10():
    """Theme cascade: editorial + cream resolve to editorial-10."""
    editorial_cat = get_theme_style("editorial").charts.color.categorical
    editorial_cream_cat = get_theme_style("cream").charts.color.categorical
    assert editorial_cat is not None and editorial_cat.palette is not None
    assert editorial_cream_cat is not None and editorial_cream_cat.palette is not None
    editorial = editorial_cat.palette
    editorial_cream = editorial_cream_cat.palette
    assert editorial == EDITORIAL_10_STOPS, (
        f"editorial theme no longer resolves to editorial-10. Got: {editorial[:3]}..."
    )
    assert editorial_cream == EDITORIAL_10_STOPS, (
        f"cream theme no longer resolves to editorial-10. Got: {editorial_cream[:3]}..."
    )


def test_editorial_themes_rebind_category_roles():
    """Theme-relative role refs must follow the theme's palette family.

    `style.palettes` binds the category/category_dark/category_light/
    category_ghost roles that theme-portable refs like `category[2]` or
    `category_dark[2]` resolve through. The _base cascade root binds them
    to the vivid-10 family; editorial-voiced themes must rebind them to
    editorial-10, otherwise a board authored with role refs keeps stark's
    colors after a theme switch.
    """
    for theme in ("editorial", "cream"):
        bound = get_theme_style(theme).palettes
        assert bound["category"] == "editorial-10", (
            f"{theme} theme leaves the `category` role on "
            f"{bound['category']!r} — role refs won't follow the theme."
        )
        for role in ("category_dark", "category_light", "category_ghost"):
            expected = "editorial-10-" + role.removeprefix("category_")
            assert bound[role] == expected, (
                f"{theme} theme leaves the `{role}` role on {bound[role]!r}; "
                f"expected {expected!r}."
            )


def test_stark_keeps_category_role_family():
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
        "plain": gray_step,
        "editorial": gray_step,
        "cream": cream_step,
        "vivid": gray_step,
    }
    for theme, want in expected.items():
        fill = get_theme_style(theme).charts.marks.geoshape.fill
        assert fill == want, (
            f"{theme} basemap fill is {fill!r}; expected the scaffold step "
            f"{want!r}. Basemap chrome must not come from a categorical "
            f"data palette."
        )


def test_stark_theme_still_uses_vivid_10():
    """Regression guard: stark keeps vivid-10 unchanged.

    The structural-root theme (stark, opt-in for the stripped-back look)
    continues to use vivid-10. The shipped default theme uses editorial-10
    (covered by test_editorial_themes_use_editorial_10 above).
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
    "#0e4786",  # 1  denim
    "#557daf",  # 2  sky
    "#917d5a",  # 3  sand
    "#5b6b7a",  # 4  gray
    "#6f3854",  # 5  plum
    "#3a603b",  # 6  green
    "#b46e0f",  # 7  gold
    "#944123",  # 8  rust
    "#2a807f",  # 9  teal
    "#232f3a",  # 10 charcoal (consolidated onto base — see pairing test)
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


def _lab_lightness_and_hue(hex_str: str) -> tuple[float, float]:
    """Return (CIELAB L*, CIELAB hue angle in degrees) via the already-imported
    palette_deltae_checker helpers.

    Construction of editorial-10-dark happens in OKLCH (per the YAML comment),
    but the test contract here only needs (a) "is this stop darker?" and
    (b) "is this stop close in hue?" — both fall out of CIELAB without
    requiring a separate OKLCH conversion. Using the checker keeps this test
    free of test-side math re-implementation.
    """
    import math

    rgb = _checker.hex_to_rgb01(hex_str)
    lab = _checker.linear_rgb_to_lab(rgb)
    # linear_rgb_to_lab returns (L*, a*, b*) in CIELAB.
    L, a, b = lab
    hue = math.degrees(math.atan2(b, a)) % 360
    return L, hue


@pytest.mark.parametrize("slot", range(10))
def test_editorial_10_dark_pairing_per_slot(slot: int):
    """Each dark stop has lower L* and the same hue as its editorial-10 pair.

    The pairing contract: editorial-10-dark[N] inks labels for series
    rendered with editorial-10[N]. Same hue family, perceptibly darker.
    Hue drift up to 8° is acceptable (gamut clipping during OKLCH→sRGB
    can shift hue slightly at the chroma boundary; CIELAB and OKLCH hue
    angles also disagree mildly even for the same color).

    Exception — slot 10 (charcoal): the dark companion is intentionally equal
    to the base stop. Charcoal-base already sits at the ink-band floor
    (OKLCH L≈0.30), so there is no meaningful "darker twin" to ink a label
    with — the near-black base reads as authored ink on a light canvas on its
    own. Charcoal base / dark / ink are deliberately consolidated onto #232f3a.
    """
    if EDITORIAL_10_DARK_STOPS[slot] == EDITORIAL_10_STOPS[slot]:
        assert slot == 9, (
            f"Only charcoal (slot 10) may consolidate its dark companion onto "
            f"base; slot {slot + 1} unexpectedly equals its editorial-10 stop."
        )
        return

    main_L, main_H = _lab_lightness_and_hue(EDITORIAL_10_STOPS[slot])
    dark_L, dark_H = _lab_lightness_and_hue(EDITORIAL_10_DARK_STOPS[slot])

    # Lower L*: dark companion must be measurably darker. Threshold of 5
    # CIELAB units leaves comfortable margin against the smallest measured
    # gap in the locked stops while still admitting future taste-driven
    # tuning that stays inside the contract.
    assert dark_L < main_L - 5.0, (
        f"editorial-10-dark slot {slot + 1} is not measurably darker than "
        f"editorial-10 slot {slot + 1} "
        f"(main L*={main_L:.1f}, dark L*={dark_L:.1f}). "
        "Direct labels won't ink properly if the companion isn't darker."
    )

    # Same hue (within tolerance — handle 360° wrap for plum near H≈350°).
    hue_diff = abs(main_H - dark_H)
    hue_diff = min(hue_diff, 360 - hue_diff)
    assert hue_diff < 8, (
        f"editorial-10-dark slot {slot + 1} drifted in hue from its "
        f"editorial-10 pair (main H={main_H:.1f}°, dark H={dark_H:.1f}°, "
        f"Δ={hue_diff:.1f}°). The pairing contract says same hue."
    )


# ----------------------------------------------------------------------------
# editorial-10-light — moderate light companion
# ----------------------------------------------------------------------------

# Locked editorial-10-light stops. Edit in lock-step with editorial-10.yml.
EDITORIAL_10_LIGHT_STOPS = [
    "#6682a6",  # 1  denim
    "#a5b9d3",  # 2  sky
    "#c6bdac",  # 3  sand
    "#9ea6ad",  # 4  gray
    "#9b7d8a",  # 5  plum
    "#839583",  # 6  green
    "#dab696",  # 7  gold
    "#b88c7d",  # 8  rust
    "#9bbcbb",  # 9  teal
    "#3c4349",  # 10 charcoal
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
    assert hue_diff < 8, (
        f"editorial-10-light slot {slot + 1} drifted in hue from its "
        f"editorial-10 pair (main H={main_H:.1f}°, light H={light_H:.1f}°, "
        f"Δ={hue_diff:.1f}°). The pairing contract says same hue."
    )


# ----------------------------------------------------------------------------
# editorial-10-ghost — extreme de-emphasis companion
# ----------------------------------------------------------------------------

# Locked editorial-10-ghost stops. Edit in lock-step with editorial-10.yml.
EDITORIAL_10_GHOST_STOPS = [
    "#c1d3e9",  # 1  denim
    "#c6d2e2",  # 2  sky
    "#d6d0c7",  # 3  sand
    "#cdd2d6",  # 4  gray
    "#decbd3",  # 5  plum
    "#cad4c9",  # 6  green
    "#e2cdb9",  # 7  gold
    "#e6cac1",  # 8  rust
    "#c2d6d5",  # 9  teal
    "#babec3",  # 10 charcoal
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
    assert hue_diff < 8, (
        f"editorial-10-ghost slot {slot + 1} drifted in hue from its "
        f"editorial-10 pair (main H={main_H:.1f}°, ghost H={ghost_H:.1f}°, "
        f"Δ={hue_diff:.1f}°). The pairing contract says same hue."
    )


# ----------------------------------------------------------------------------
# editorial-10-ink — ink-grade single-series companion
# ----------------------------------------------------------------------------

# Locked editorial-10-ink stops. Edit in lock-step with editorial-10.yml.
EDITORIAL_10_INK_STOPS = [
    "#1b3659",  # 1  denim
    "#203c65",  # 2  sky
    "#443924",  # 3  sand
    "#2d383f",  # 4  gray
    "#4a2a3a",  # 5  plum
    "#263d2a",  # 6  green
    "#523500",  # 7  gold
    "#53291d",  # 8  rust
    "#143e3e",  # 9  teal
    "#232f3a",  # 10 charcoal (consolidated onto base — see pairing test)
]

# Documented ink band (see editorial-10-ink.yml): a tight OKLCH L 0.30–0.36
# with charcoal-ink anchoring the floor. The small tolerance below absorbs
# sRGB round-tripping at the band edges (charcoal lands at L≈0.299).
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

    Exception — slot 10 (charcoal): ink equals base #232f3a. Charcoal-base
    already sits at the ink-band floor (L≈0.30), so its ink companion is the
    base itself — the same consolidation the dark companion makes.
    """
    main_L, _, _ = _checker.hex_to_oklch(EDITORIAL_10_STOPS[slot])
    ink_L, _, _ = _checker.hex_to_oklch(EDITORIAL_10_INK_STOPS[slot])

    assert _INK_BAND_LO <= ink_L <= _INK_BAND_HI, (
        f"editorial-10-ink slot {slot + 1} L={ink_L:.3f} is outside the "
        f"documented ink band [{_INK_BAND_LO}, {_INK_BAND_HI}]."
    )

    if EDITORIAL_10_INK_STOPS[slot] == EDITORIAL_10_STOPS[slot]:
        assert slot == 9, (
            f"Only charcoal (slot 10) may consolidate its ink companion onto "
            f"base; slot {slot + 1} unexpectedly equals its editorial-10 stop."
        )
        return

    assert ink_L < main_L, (
        f"editorial-10-ink slot {slot + 1} is not darker than editorial-10 "
        f"slot {slot + 1} (main L={main_L:.3f}, ink L={ink_L:.3f})."
    )
