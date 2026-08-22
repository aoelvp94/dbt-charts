"""Tests for the shared-scale resolver: does a set of numbers compact, and at
what magnitude.

Ladders come from ``nice_tick_values(lo, hi, 6)``, the ``editorial`` tick cap,
so cases build ticks the way the engine does rather than hand-listing them.
See ``ai_notes/jul26-02-numeral-system-design.md`` ("ruler" under Form policy
per destination, "When to compact") and
``ai_notes/jul26-02-phase-1-plan.md`` for the design this pins.
"""

from __future__ import annotations

from dbt_charts.core.numeric import nice_tick_values
from dbt_charts.core.text.numeral_scale import (
    SharedScale,
    SuffixMode,
    _integer_digit_count,
    _precision_for_step,
    plain_digit_format,
    shared_scale_for_column,
    shared_scale_for_ladder,
    suffix_at_register,
)


def _ladder(lo: float, hi: float) -> list[float]:
    return nice_tick_values(lo, hi, 6)


def test_short_ladder_does_not_compact():
    """0-80: step 20 carries no SI tier at all, so there is nothing to compact."""
    assert shared_scale_for_ladder(_ladder(0, 80)) is None


def test_small_thousands_ladder_does_not_compact():
    """0-4,500 rounds to ticks up to 5,000 — 4 written-out digits, under the
    6-digit threshold. This is the pairing case: identical shape to 0-4.5bn
    (same tick count, same anchor, same bare digits), and only the absolute
    magnitude tells them apart — see "The ruler compaction threshold" in the
    design doc.
    """
    ticks = _ladder(0, 4_500)
    assert ticks == [0.0, 1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
    assert shared_scale_for_ladder(ticks) is None


def test_billions_ladder_compacts_anchor():
    """0-4.5bn: identical rendered shape to 0-4,500 above, but 5,000,000,000
    reaches 10 written-out digits, so this one compacts. The whole reason the
    threshold is magnitude-based rather than shape-based.
    """
    ticks = _ladder(0, 4.5e9)
    assert ticks == [0.0, 1e9, 2e9, 3e9, 4e9, 5e9]
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 9
    assert scale.mode is SuffixMode.ANCHOR


def test_450k_ladder_compacts_anchor_thousands():
    """0-450k: extreme tick 500,000 stays inside the thousands tier (3
    integer digits at scale), so the suffix anchors on the top tick only.
    """
    ticks = _ladder(0, 450_000)
    assert ticks == [0.0, 100_000.0, 200_000.0, 300_000.0, 400_000.0, 500_000.0]
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 3
    assert scale.mode is SuffixMode.ANCHOR


def test_900k_ladder_compacts_repeat():
    """0-900k: the data never leaves thousands, but the ladder overshoots to
    1,000,000 — 4 integer digits at the thousands scale — so the suffix
    repeats on every tick instead of anchoring once.
    """
    ticks = _ladder(0, 900_000)
    assert ticks == [0.0, 200_000.0, 400_000.0, 600_000.0, 800_000.0, 1_000_000.0]
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 3
    assert scale.mode is SuffixMode.REPEAT


def test_200trn_ladder_compacts_anchor():
    """0-200trn: extreme tick scaled to trillions is 200 — 3 integer digits —
    so this anchors, same as the billions case above.
    """
    ticks = _ladder(0, 200e12)
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 12
    assert scale.mode is SuffixMode.ANCHOR


def test_half_billion_step_resolves_to_millions_not_billions():
    """0-2.5bn: step 5e8 is half a billion, but a whole multiple (500) of a
    million. A fractional-ratio exception used to bump this to billions
    (one significant figure: 2.5 / 2 / 1.5 / 1 / 0.5 / 0 B); that exception
    was reverted (it fired on any tier, breaking a 500,000-step ladder the
    same way) -- whole-multiple-only means this now lands one tier down, in
    REPEAT mode: 2,500 / 2,000 / 1,500 / 1,000 / 500 / 0 M.
    """
    ticks = _ladder(0, 2.5e9)
    assert ticks == [0.0, 5e8, 1e9, 1.5e9, 2e9, 2.5e9]
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 6
    assert scale.mode is SuffixMode.REPEAT


def test_half_billion_step_ladder_1_5bn_resolves_to_millions():
    ticks = _ladder(0, 1.5e9)
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 6
    assert scale.mode is SuffixMode.REPEAT


def test_half_trillion_step_ladder_1_5trn_resolves_to_billions():
    ticks = _ladder(0, 1.5e12)
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 9
    assert scale.mode is SuffixMode.REPEAT


def test_one_fifth_step_is_not_permitted_as_a_tier_divisor():
    """0-900k's step (2e5) is 0.2 of a million as well as 200x a thousand.
    Only a whole-multiple ratio is permitted, so this must still resolve to
    thousands — the regression test_900k_ladder_compacts_repeat above pins
    the resulting mode; this test pins the ratio boundary directly.
    """
    ticks = _ladder(0, 900_000)
    step = ticks[1] - ticks[0]
    assert step / 1e6 == 0.2
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.exponent == 3


def test_hundred_thousands_ladder_compacts_anchor():
    """100,000-105,000: step 1,000 divides the thousands tier evenly and the
    extreme value reaches exactly 6 written-out digits — the threshold's own
    boundary case.
    """
    ticks = _ladder(100_000, 105_000)
    scale = shared_scale_for_ladder(ticks)
    assert scale is not None
    assert scale.mode is SuffixMode.ANCHOR


def test_off_tier_step_never_compacts():
    """999,800-1,000,200 at step 100: 100 is a tenth of the thousands tier,
    not a whole multiple or a half, so no SI tier divides it and no
    magnitude can be chosen at all. Caught by the tier-divisibility gate, not
    the digit-count threshold — the extreme value (1,000,200, 7 digits)
    would otherwise clear it.
    """
    ticks = _ladder(999_800, 1_000_200)
    assert ticks[1] - ticks[0] == 100
    assert shared_scale_for_ladder(ticks) is None


def test_integer_digit_count_truncates_a_fractional_value():
    """99,999.6 has 5 written integer digits, not 6. Both the compaction
    gate and the mode trigger key off this count, so rounding a fractional
    extreme up would cross either threshold one tick early.
    """
    assert _integer_digit_count(99_999.6) == 5


def test_half_of_lowest_tier_step_does_not_compact():
    """A step of 500 is half of the thousands tier -- the lowest tier there
    is, so there's no tier further down for a whole-multiple match to fall
    through to. The fractional-ratio exception used to compact this anyway
    (999k / 999.5k / 1,000k / …); reverted, so this no longer compacts at
    all and prints its exact digits instead.
    """
    ticks = _ladder(999_000, 1_001_000)
    assert ticks == [999_000.0, 999_500.0, 1_000_000.0, 1_000_500.0, 1_001_000.0]
    assert shared_scale_for_ladder(ticks) is None
    assert shared_scale_for_ladder([998_500.0, 999_000.0, 999_500.0]) is None


def test_zero_carries_no_suffix_in_repeat_mode():
    scale = SharedScale(exponent=3, mode=SuffixMode.REPEAT)
    assert scale.suffix(0, is_anchor=False) == ""
    assert scale.suffix(0, is_anchor=True) == ""


def test_zero_carries_no_suffix_in_anchor_mode():
    scale = SharedScale(exponent=6, mode=SuffixMode.ANCHOR)
    assert scale.suffix(0, is_anchor=True) == ""


def test_anchor_mode_suffix_only_on_the_anchor_member():
    scale = SharedScale(exponent=3, mode=SuffixMode.ANCHOR)
    assert scale.suffix(500_000, is_anchor=True) == " K"
    assert scale.suffix(400_000, is_anchor=False) == ""


def test_repeat_mode_suffix_on_every_nonzero_member():
    scale = SharedScale(exponent=3, mode=SuffixMode.REPEAT)
    assert scale.suffix(1_000_000, is_anchor=True) == "k"
    assert scale.suffix(800_000, is_anchor=False) == "k"


def test_register_is_derived_from_mode():
    assert SharedScale(exponent=3, mode=SuffixMode.ANCHOR).register == "analytic"
    assert SharedScale(exponent=3, mode=SuffixMode.REPEAT).register == "narrative"


def test_mixed_tier_column_takes_the_majority_tier():
    """Two members in millions, one in thousands: millions wins the vote, and
    the ruler's mode-trigger rule applies at that chosen magnitude — not a
    majority vote over ticks, which is reserved for the ladder path.
    """
    values = [1_200_000, 1_300_000, 900_000]
    scale = shared_scale_for_column(values)
    assert scale is not None
    assert scale.exponent == 6
    assert scale.mode is SuffixMode.ANCHOR


def test_column_majority_of_small_values_vetoes_a_large_outlier():
    """A single value in millions must not impose a millions magnitude on a
    column that is mostly sub-thousand — the vote counts every value,
    including those below the smallest SI tier, not just the tiered ones.
    """
    assert shared_scale_for_column([1_000_000, 500, 600]) is None


def test_column_tie_between_no_tier_and_a_tier_does_not_compact():
    """An even split between a tiered value and a sub-thousand one has no
    clear shared magnitude, so both values write out in full rather than
    scaling 500 as a fraction of a millions header the vote didn't clearly
    choose.
    """
    assert shared_scale_for_column([1_000_000, 500]) is None


def test_column_tie_break_prefers_the_higher_tier_and_is_order_independent():
    values = [1_000_000, 2_000_000, 1_000_000_000, 2_000_000_000]
    scale = shared_scale_for_column(values)
    assert scale is not None
    assert scale.exponent == 9
    assert scale.mode is SuffixMode.ANCHOR
    assert shared_scale_for_column(list(reversed(values))) == scale


def test_short_column_does_not_compact():
    """1,504 / 2,300 / 900: the extreme value is 4 written-out digits, under
    the 6-digit threshold, so the column stays in plain digits rather than
    becoming 1.5 / 2.3 / 0.9 under a header magnitude.
    """
    assert shared_scale_for_column([1_504, 2_300, 900]) is None


def test_column_takes_one_scale_even_when_a_minority_member_renders_small():
    """A ledger fixes one scale per column and lets significant figures vary
    — the mirror of the worked example where 47,300 renders as 0.05 under a
    USD-millions header. A minority member (900) rendering as a small
    fraction of the majority's magnitude is that regime working as designed,
    not a bug the resolver should compensate for; how many decimals a small
    member shows is the ledger consumer's fixed-decimal policy, out of scope
    here.
    """
    scale = shared_scale_for_column([1_200_000, 1_300_000, 900])
    assert scale is not None
    assert scale.exponent == 6
    assert scale.mode is SuffixMode.ANCHOR


def test_suffix_at_register_reads_the_named_table_regardless_of_mode():
    """A horizontal ruler forces narrative even when its ladder's own mode
    would select analytic (register normally follows mode) — the ruler
    consumer needs the narrative suffix for an exponent without first
    building a REPEAT-mode SharedScale just to reach it.
    """
    assert suffix_at_register(3, "analytic") == " K"
    assert suffix_at_register(3, "narrative") == "k"
    assert suffix_at_register(9, "analytic") == " B"
    assert suffix_at_register(9, "narrative") == "bn"


def test_suffix_string_delegates_to_suffix_at_register():
    anchor = SharedScale(exponent=6, mode=SuffixMode.ANCHOR)
    repeat = SharedScale(exponent=6, mode=SuffixMode.REPEAT)
    assert anchor.suffix_string == suffix_at_register(6, "analytic")
    assert repeat.suffix_string == suffix_at_register(6, "narrative")


def test_precision_for_step_integer_step_is_zero():
    assert _precision_for_step(500) == 0
    assert _precision_for_step(20_000) == 0


def test_precision_for_step_half_step_is_one():
    assert _precision_for_step(0.5) == 1
    assert _precision_for_step(1.5) == 1


def test_plain_digit_format_writes_out_full_digits():
    assert plain_digit_format(".3~s", 20_000) == ("", ",.0~f", 0)


def test_plain_digit_format_splits_the_currency_symbol_as_prefix():
    # The currency symbol is split out just like ruler_digit_format, as the
    # bare symbol -- the caller (_cascade.py's _prefix_with_guaranteed_gap)
    # appends a trailing FIGURE SPACE (U+2007) for a deterministic gap, since
    # this module (core.text) cannot depend on core.font_measure where that
    # constant lives.
    prefix, digit_spec, precision = plain_digit_format("$~s", 20_000)
    assert prefix == "$"
    assert digit_spec == ",.0~f"
    assert precision == 0


def test_plain_digit_format_keeps_a_half_step_decimal():
    assert plain_digit_format(".3~s", 0.5) == ("", ",.1~f", 1)


def test_plain_digit_format_no_symbol_empty_prefix():
    prefix, digit_spec, precision = plain_digit_format(",.0f", 2_000)
    assert prefix == ""
    # trim=True appends "~" to the type indicator.
    assert digit_spec == ",.0~f"
    assert precision == 0
