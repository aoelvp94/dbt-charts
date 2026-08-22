"""Regression tests for dbt Sans Tabular as a variable font.

Guards the three invariants after the rebuild:
1. The font exposes a wght axis (100–900, default 400) with a STAT table.
2. The tnum bake propagated glyf outlines, gvar deltas, and hmtx metrics from
   the tabular alternates to the base digit glyphs at every weight.
3. All digits share a common advance width at each instantiated weight
   (i.e., the font is truly tabular across the full axis).
"""

import pytest
from fontTools.ttLib import TTFont  # pyright: ignore[reportMissingTypeStubs]
from fontTools.varLib.instancer import (  # pyright: ignore[reportMissingTypeStubs]
    instantiateVariableFont,
)

from dbt_charts.core.fonts import DBT_SANS_TABULAR_FONT_FAMILY, get_face

FONT_PATH = get_face(DBT_SANS_TABULAR_FONT_FAMILY).measure_path

DIGITS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
)

# zero.tf and one.tf are simple glyphs with distinct outlines: glyf+gvar were copied.
# four.tf and seven.tf are composites of four/seven respectively: only hmtx+HVAR copied.
SIMPLE_TNUM = {"zero": "zero.tf", "one": "one.tf"}
COMPOSITE_TNUM = {"four": "four.tf", "seven": "seven.tf"}


@pytest.fixture(scope="module")
def font() -> TTFont:
    return TTFont(FONT_PATH)


class TestVariableWeightAxis:
    """Font must expose a wght axis 100–900 with STAT support."""

    def test_fvar_present(self, font: TTFont) -> None:
        assert "fvar" in font

    def test_wght_axis_tag(self, font: TTFont) -> None:
        axes = font["fvar"].axes
        assert axes[0].axisTag == "wght"

    def test_wght_axis_range(self, font: TTFont) -> None:
        ax = font["fvar"].axes[0]
        assert ax.minValue == 100
        assert ax.maxValue == 900

    def test_wght_axis_default(self, font: TTFont) -> None:
        ax = font["fvar"].axes[0]
        assert ax.defaultValue == 400

    def test_stat_present(self, font: TTFont) -> None:
        assert "STAT" in font

    def test_stat_declares_wght_axis(self, font: TTFont) -> None:
        record = font["STAT"].table.DesignAxisRecord
        assert record is not None
        tags = [a.AxisTag for a in record.Axis]
        assert "wght" in tags


class TestTnumBakeAtAllWeights:
    """After bake, base digit glyphs must match the tabular alternate at every level."""

    def test_glyf_bytes_match_for_simple_tnum(self, font: TTFont) -> None:
        # Simple tnum variants have distinct outlines that were copied to the base.
        glyf = font["glyf"]
        for src, tgt in SIMPLE_TNUM.items():
            src_bytes = glyf[src].compile(glyf)
            tgt_bytes = glyf[tgt].compile(glyf)
            assert src_bytes == tgt_bytes, f"glyf mismatch: {src} vs {tgt}"

    def test_gvar_deltas_match_for_simple_tnum(self, font: TTFont) -> None:
        # Simple tnum gvar deltas were also copied — verify byte-level identity.
        axis_tags = [a.axisTag for a in font["fvar"].axes]
        gvar_variations = font["gvar"].variations
        for src, tgt in SIMPLE_TNUM.items():
            src_vars = gvar_variations.get(src, [])
            tgt_vars = gvar_variations.get(tgt, [])
            assert len(src_vars) == len(tgt_vars), (
                f"gvar length mismatch: {src}({len(src_vars)}) vs {tgt}({len(tgt_vars)})"
            )
            for tv_a, tv_b in zip(src_vars, tgt_vars, strict=True):
                assert tv_a.compile(axis_tags) == tv_b.compile(axis_tags), (
                    f"gvar delta mismatch: {src} vs {tgt}"
                )

    def test_hmtx_metrics_match(self, font: TTFont) -> None:
        # Both simple and composite tnum pairs must share the same advance width at default.
        metrics = font["hmtx"].metrics
        for src, tgt in {**SIMPLE_TNUM, **COMPOSITE_TNUM}.items():
            assert metrics[src] == metrics[tgt], (
                f"hmtx mismatch: {src}{metrics[src]} vs {tgt}{metrics[tgt]}"
            )


class TestTabularWidthAcrossWeights:
    """All digits must share the same advance width at each instantiated weight."""

    @pytest.mark.parametrize(
        "wght", [100, 400, 900]
    )  # axis endpoints + default; interior weights duplicate the interpolation
    def test_digits_are_tabular_at_weight(self, font: TTFont, wght: int) -> None:
        inst = instantiateVariableFont(font, {"wght": wght}, inplace=False)
        widths = {inst["hmtx"].metrics[d][0] for d in DIGITS}
        assert len(widths) == 1, f"non-tabular at wght={wght}: {widths}"
