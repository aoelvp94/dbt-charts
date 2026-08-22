"""``inject_axis_numeral_expr`` — the ruler's labelExpr producer.

Reads ``axis.ruler`` (baked at resolve, see
``dbt-charts/tests/core/compile/test_axis_ruler_resolve.py``) alone -- the
single "does this axis ship the ruler composition" decision, already folded
with the SI-format check, the authored-``label.expr`` opt-out, and the
column-forming override (a horizontal ruler's ``ruler.mode``/``reserve`` are
already the *effective*, folded values by the time they reach here; this
module never re-derives orientation) -- and produces the label text from
``datum.value``. It is the innermost layer, wrapped by
``inject_axis_label_case`` / ``inject_axis_label_values_filter`` exactly as
they already wrap the temporal smart-cadence producer. See "ruler" in
``ai_notes/jul26-02-numeral-system-design.md``.

The end-to-end tests render through real ``vl_convert`` rather than
asserting on the expression string alone: a labelExpr that reads right in
Python can still render wrong (or lose its reservation, or its composed
padding characters) once Vega actually evaluates it. See
``TestReservationSurvivesVlConvert`` -- a bare trailing U+2007 run is
stripped from the rendered ``<text>`` content by ``vl_convert``
(``ai_notes/jul26-02-phase-1-plan.md`` has the full investigation) -- and
``TestNegativeLadderAnchor`` -- the anchor is the tick that is the extreme
by absolute value, baked as a POSITION (``ruler.anchor_at_start``) rather
than the tick's raw value, because Vega may drop a baked ``tick_values``
entry it never draws; ``datum.index`` stays correct when it does.
"""

from __future__ import annotations

import html
import json
import re

import vl_convert as vlc

from dbt_charts.core.compile.models.style.resolved import (
    ResolvedRulerAxis,
    ResolvedTickLabel,
)
from dbt_charts.core.font_measure import (
    RESERVATION_GUARD,
    compose_suffix_reservation,
)
from dbt_charts.core.fonts import DBT_SANS_TABULAR_FONT_FAMILY
from dbt_charts.core.render.chart.vl_field_maps import inject_axis_numeral_expr
from dbt_charts.core.text.numeral_scale import (
    SuffixMode,
    ruler_digit_format,
    suffix_at_register,
)

_TEXT_RE = re.compile(r"<text[^>]*>(.*?)</text>", re.S)


def _ruler(
    exponent: int,
    mode: SuffixMode,
    anchor_at_start: bool = False,
    format_spec: str = ".3~s",
    reserve: bool = True,
) -> ResolvedRulerAxis:
    """Build a baked ``ResolvedRulerAxis`` the way ``build_resolved_axis``
    would -- ``prefix``/``digit_spec`` split once from a format spec via the
    same ``ruler_digit_format`` helper, and ``reservation`` composed via the
    same ``compose_suffix_reservation`` helper, rather than re-deriving any
    of it ad hoc per test. ``anchor_at_start`` defaults to False (the common
    case: the magnitude-extreme is the LAST tick of an ascending,
    non-negative ladder) -- tests for an all-negative ladder pass True
    explicitly.
    """
    prefix, digit_spec = ruler_digit_format(format_spec)
    register = "analytic" if mode is SuffixMode.ANCHOR else "narrative"
    suffix_text = suffix_at_register(exponent, register)
    reservation = (
        compose_suffix_reservation(suffix_text, DBT_SANS_TABULAR_FONT_FAMILY)
        if reserve
        else ""
    )
    return ResolvedRulerAxis(
        exponent=exponent,
        mode=mode,
        reserve=reserve,
        prefix=prefix,
        digit_spec=digit_spec,
        anchor_at_start=anchor_at_start,
        reservation=reservation,
    )


def _render_axis_labels(
    values: list[float], domain: tuple[float, float], label_expr: str
) -> list[str]:
    """Render a real y-axis with explicit tick values through vl_convert.

    Returns the rendered tick labels in domain order (filtered to the
    numeric ticks — the encoding also emits "x"/"y" axis-title text nodes,
    which never contain a digit).
    """
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": [{"x": "a", "y": domain[0]}, {"x": "b", "y": domain[1]}]},
        "mark": "point",
        "encoding": {
            "x": {"field": "x", "type": "nominal"},
            "y": {
                "field": "y",
                "type": "quantitative",
                "scale": {"domain": list(domain)},
                "axis": {"values": values, "labelExpr": label_expr},
            },
        },
    }
    svg = vlc.vegalite_to_svg(spec)
    texts = [html.unescape(t) for t in _TEXT_RE.findall(svg)]
    numeric = [t for t in texts if any(ch.isdigit() for ch in t)]
    assert len(numeric) == len(values), (
        f"expected {len(values)} tick labels, found {numeric!r} in {texts!r}"
    )
    return numeric


class TestCompositionGating:
    def test_no_ruler_is_noop(self) -> None:
        assert inject_axis_numeral_expr({}, None) == {}

    def test_authored_label_expr_is_the_full_opt_out(self) -> None:
        """Belt-and-braces: resolve never bakes ``ruler`` when
        ``label.expr`` is authored (see
        ``test_axis_ruler_resolve.py::test_authored_label_expr_never_bakes_ruler``),
        but this module still no-ops if ``labelExpr`` is already set on the
        VL dict for any reason -- it never overwrites one.
        """
        ruler = _ruler(3, SuffixMode.ANCHOR)
        ax_vl = {"labelExpr": "datum.label"}
        assert inject_axis_numeral_expr(ax_vl, ruler) == ax_vl


class TestExpressionShape:
    def test_anchor_mode_gates_the_suffix_on_the_last_tick_by_default(self) -> None:
        """``anchor_at_start=False`` (the common, non-negative-ladder case)
        gates on the LAST rendered tick, ``datum.index === 1``.
        """
        ruler = _ruler(3, SuffixMode.ANCHOR, anchor_at_start=False)
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        assert "datum.index === 1" in expr
        assert "datum.value !== 0" in expr

    def test_anchor_at_start_gates_the_suffix_on_the_first_tick(self) -> None:
        """An all-negative ladder's magnitude-extreme is the FIRST tick --
        see ``TestNegativeLadderAnchor`` for the real-render regression.
        """
        ruler = _ruler(3, SuffixMode.ANCHOR, anchor_at_start=True)
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        assert "datum.index === 0" in expr

    def test_repeat_mode_with_no_prefix_never_gates_on_the_anchor(self) -> None:
        """No currency symbol in the format and REPEAT mode's suffix gate is
        bare non-zero -- nothing in the expression references the anchor
        index at all in this combination.
        """
        ruler = _ruler(3, SuffixMode.REPEAT)
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        assert "datum.index" not in expr
        assert "datum.value !== 0" in expr

    def test_currency_prefix_anchors_on_index_in_both_modes(self) -> None:
        for mode in (SuffixMode.ANCHOR, SuffixMode.REPEAT):
            ruler = _ruler(3, mode, format_spec="$.3~s")
            expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
            assert "datum.index === 1" in expr
            # The symbol is embedded inside the anchor's format() spec (so d3-format
            # places it correctly relative to the sign) -- not as a bare "$" literal.
            assert re.search(r'format\([^,]+,"[^"]*\$[^"]*"\)', expr) is not None, expr

    def test_digit_format_call_strips_the_currency_symbol(self) -> None:
        """The anchor tick's format spec carries the currency symbol (so d3-format
        places it correctly relative to the sign); the non-anchor spec does not.
        Both must be present -- the ruler path emits a ternary of two format calls.
        """
        ruler = _ruler(3, SuffixMode.ANCHOR, format_spec="$.3~s")
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        calls = re.findall(r'format\([^,]+,"([^"]+)"\)', expr)
        assert len(calls) == 2, (
            f"expected two format calls (anchor + non-anchor), got {calls!r}"
        )
        # Anchor call has the symbol so d3 orders sign-before-symbol correctly.
        assert "$" in calls[0], f"anchor spec should contain '$': {calls[0]!r}"
        # Non-anchor call has no symbol -- it never shows one.
        assert "$" not in calls[1], (
            f"non-anchor spec must not contain '$': {calls[1]!r}"
        )

    def test_reserve_false_never_pads(self) -> None:
        """A non-column-forming (horizontal) axis is baked with
        ``reserve=False`` at resolve — this module reads that field alone
        and never re-derives orientation; folding the ladder's own mode
        into REPEAT for a horizontal ruler is entirely resolve's job (see
        ``test_axis_ruler_resolve.py::test_non_column_forming_axis_bakes_repeat_mode_regardless_of_ladder``).
        """
        ruler = _ruler(3, SuffixMode.REPEAT, reserve=False)
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        assert '"k"' in expr
        assert '" K"' not in expr
        assert RESERVATION_GUARD not in expr
        assert "''" in expr

    def test_vertical_reservation_carries_the_zero_width_guard(self) -> None:
        ruler = _ruler(3, SuffixMode.ANCHOR)
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        # json.dumps escapes non-ASCII to \uXXXX (valid JS string syntax) --
        # check for the escape sequence the emitted expression actually
        # contains, not the raw character.
        assert f"\\u{ord(RESERVATION_GUARD):04x}" in expr


class TestRealVegaRendering:
    """The worked examples from the numeral design doc's "ruler" section,
    rendered through real Vega (vl_convert), not hand-asserted strings.
    """

    def test_anchor_mode_450k_ladder(self) -> None:
        ruler = _ruler(3, SuffixMode.ANCHOR, format_spec="$.3~s")
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        ticks = [0.0, 100_000.0, 200_000.0, 300_000.0, 400_000.0, 500_000.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)

        pad = ruler.reservation
        assert labels == [
            "0" + pad,
            "100" + pad,
            "200" + pad,
            "300" + pad,
            "400" + pad,
            "$500 K",
        ]

    def test_repeat_mode_900k_ladder(self) -> None:
        ruler = _ruler(3, SuffixMode.REPEAT, format_spec="$.3~s")
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        ticks = [0.0, 200_000.0, 400_000.0, 600_000.0, 800_000.0, 1_000_000.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)

        pad = ruler.reservation
        assert labels == [
            "0" + pad,
            "200k",
            "400k",
            "600k",
            "800k",
            "$1,000k",
        ]

    def test_horizontal_ruler_is_always_repeat_mode_narrative_with_no_reservation(
        self,
    ) -> None:
        """A horizontal ruler is baked (at resolve) always narrative and
        always repeat, with ``reserve=False`` — never the anchor-plus-
        narrative combination the design contract rejects (a suffix stated
        once must be spaced/capital; unspaced/lowercase pairs only with a
        suffix on every member). Fed here as the already-folded, effective
        values this module trusts without re-deriving orientation.
        """
        ruler = _ruler(
            3,
            SuffixMode.REPEAT,
            format_spec="$.3~s",
            reserve=False,
        )
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        ticks = [0.0, 100_000.0, 200_000.0, 300_000.0, 400_000.0, 500_000.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)
        assert labels == [
            "0",
            "100k",
            "200k",
            "300k",
            "400k",
            "$500k",
        ]


class TestComposedReservationSurvivesVlConvert:
    """The composed padding is not a whole run of one character — it can be
    a mix of two or three different Unicode space codepoints. Confirm the
    exact composed characters (not just "some padding") survive vl_convert's
    SVG serialization, which is known to trim some whitespace at the edges
    of a string (see ``TestReservationSurvivesVlConvert`` below).
    """

    def test_composed_characters_appear_verbatim_in_the_rendered_labels(self) -> None:
        ruler = _ruler(3, SuffixMode.ANCHOR, format_spec="$.3~s")
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        ticks = [0.0, 100_000.0, 200_000.0, 300_000.0, 400_000.0, 500_000.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)

        assert len(ruler.reservation) > 1, (
            "expected a multi-character composition for ' K' (~1.45 "
            f"digit-widths), got {ruler.reservation!r}"
        )
        for label in labels[:-1]:
            assert label.endswith(ruler.reservation), (
                f"composed padding {ruler.reservation!r} missing or altered in {label!r}"
            )


class TestNegativeLadderAnchor:
    """Regression: an all-negative, zero-topped ladder must still declare
    its magnitude. The anchor is the tick that is the extreme by absolute
    value, which is the FIRST tick on an all-negative ladder like this one
    (``shared_scale_for_ladder`` picks the exponent/mode from
    ``max(abs(t) for t in ticks)``) -- not the *last-drawn* tick (0, which a
    zero-anchored measure axis bakes routinely over all-negative data, and
    which never carries a suffix).

    The anchor is baked as a POSITION (``ruler.anchor_at_start``), not the
    tick's raw value, because Vega may drop a baked ``tick_values`` entry it
    never actually draws (routine, and independent of sign -- see
    ``charts/bar-charts_7``'s real golden, which has no negative data at
    all). ``datum.index`` stays correct regardless of how many ticks Vega
    drops; a value comparison against a dropped entry would never match any
    rendered tick.
    """

    def test_all_negative_zero_topped_ladder_declares_the_magnitude_once(self) -> None:
        ruler = _ruler(3, SuffixMode.ANCHOR, anchor_at_start=True)
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        ticks = [-600_000.0, -400_000.0, -200_000.0, 0.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)

        pad = ruler.reservation
        # d3 emits U+2212 MINUS SIGN, not ASCII hyphen, for a negative value.
        assert labels == [
            "\u2212600 K",
            "\u2212400" + pad,
            "\u2212200" + pad,
            "0" + pad,
        ]


class TestReservationSurvivesVlConvert:
    """The regression pin: a reservation with nothing after it must still be
    present in what vl_convert actually renders. Corrected 2026-08-05 — a
    bare trailing U+2007 run is silently stripped from the rendered <text>
    content by vl_convert (the same production path
    ``render_chart_artifact`` uses), exactly like the already-known leading
    case; only appending a U+200B guard keeps the run interior to the
    string and preserves it. This is the test that keeps that regression
    from coming back, independent of the emitter's own string-shape tests
    above (which would pass even if vl_convert dropped every character).
    """

    def test_non_anchor_tick_keeps_its_reservation_through_vl_convert(self) -> None:
        ruler = _ruler(3, SuffixMode.ANCHOR)
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        ticks = [0.0, 100_000.0, 200_000.0, 300_000.0, 400_000.0, 500_000.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)

        non_anchor = labels[:-1]
        assert non_anchor, "expected at least one non-anchor tick"
        for label in non_anchor:
            assert label.endswith(ruler.reservation), (
                f"reservation missing or stripped from {label!r}"
            )

    def test_without_the_guard_the_reservation_is_silently_dropped(self) -> None:
        """Documents the failure this guard fixes: the same padding, with
        no guard appended, renders with nothing after "400" at all.
        """
        pad = "  "
        expr = (
            "format(datum.value,',d') + "
            "(datum.value !== 500000 ? " + repr(pad) + " : ' K')"
        )
        ticks = [0.0, 100_000.0, 200_000.0, 300_000.0, 400_000.0, 500_000.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)
        assert labels[:-1] == ["0", "100,000", "200,000", "300,000", "400,000"], (
            "expected the unguarded padding to be stripped — if this now "
            "fails, vl_convert's whitespace-trimming behavior changed and "
            "the guard workaround may no longer be needed"
        )


class TestNonCompactingEndAnchoredPrefix:
    """Non-compacting axis that is end-anchored (text-anchor=end): prefix appears
    on the anchor tick only, no padding characters needed.
    """

    def test_end_anchored_prefix_emits_anchor_only_ternary_no_pad(self) -> None:
        """A ``tick_label.prefix`` (currency symbol) must emit a ternary of two
        format calls -- anchor carries the symbol inside its spec (for d3's
        sign-before-symbol ordering), non-anchor does not. No pad() call or
        RESERVATION_GUARD -- none needed for text-anchor=end axes.
        """
        prefix = "$"
        expr = inject_axis_numeral_expr(
            {},
            None,
            tick_label=ResolvedTickLabel(
                format=",.0f", prefix=prefix, anchor_at_start=False
            ),
        )["labelExpr"]

        # Anchor-only conditional -- datum.index gates which format call runs.
        assert "datum.index === 1" in expr
        # The symbol is embedded in the anchor format spec (not a bare literal).
        assert re.search(r'format\([^,]+,"[^"]*\$[^"]*"\)', expr) is not None, expr
        # No padding device -- end-anchored alignment is inherent.
        assert "pad(" not in expr
        assert json.dumps(RESERVATION_GUARD) not in expr

    def test_end_anchored_prefix_anchor_at_start_uses_index_zero(self) -> None:
        """anchor_at_start=True: magnitude-extreme is the FIRST tick, so
        datum.index === 0 carries the prefix.
        """
        prefix = "$"
        expr = inject_axis_numeral_expr(
            {},
            None,
            tick_label=ResolvedTickLabel(
                format=",.0f", prefix=prefix, anchor_at_start=True
            ),
        )["labelExpr"]

        assert "datum.index === 0" in expr


class TestNegativeAnchorCurrencySign:
    """Regression: a currency anchor tick with a negative value must render
    sign-before-symbol ("-$500") not symbol-before-sign ("$-500").

    The bug was manual prefix concatenation: ``"$" + format(v, ",.0f")`` placed
    the literal ``$`` before d3's own minus sign for negative values. The fix
    passes the symbol into the d3 spec so d3-format's own sign-ordering applies.
    Both the ruler (compacting) and tick_label (non-compacting) paths are covered.
    """

    def test_ruler_negative_anchor_renders_sign_before_symbol(self) -> None:
        """Compacting ruler path: negative anchor tick must be '-$500 K', not '$-500 K'."""
        ruler = _ruler(3, SuffixMode.ANCHOR, anchor_at_start=True, format_spec="$.3~s")
        expr = inject_axis_numeral_expr({}, ruler)["labelExpr"]
        ticks = [-500_000.0, -300_000.0, -100_000.0, 0.0]
        labels = _render_axis_labels(ticks, (ticks[0], ticks[-1]), expr)
        # d3 emits U+2212 MINUS SIGN, not ASCII hyphen.
        assert labels[0] == "−$500 K", f"expected sign before symbol, got {labels[0]!r}"

    def test_tick_label_negative_anchor_renders_sign_before_symbol(self) -> None:
        """Non-compacting tick_label path: negative anchor must be '-$500', not '$-500'."""
        expr = inject_axis_numeral_expr(
            {},
            None,
            tick_label=ResolvedTickLabel(
                format=",.0f", prefix="$", anchor_at_start=True
            ),
        )["labelExpr"]
        labels = _render_axis_labels([-500.0, 0.0], (-500.0, 0.0), expr)
        # d3 emits U+2212 MINUS SIGN, not ASCII hyphen.
        assert labels[0] == "−$500", f"expected sign before symbol, got {labels[0]!r}"
