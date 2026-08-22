"""Tests for d3-format spec grammar parser.

TDD: these tests are written BEFORE the implementation.
"""

import itertools
import json
import pathlib

import pytest

from d3_format import D3FormatError
from d3_format.spec import FormatSpec, parse

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "d3_reference.json").read_text()
)
ALL_SPECS = list(dict.fromkeys(item["spec"] for item in FIXTURE))


class TestParseRoundtrip:
    """Every spec in the fixture must parse without error."""

    @pytest.mark.parametrize("spec", ALL_SPECS)
    def test_parses_without_error(self, spec: str) -> None:
        result = parse(spec)
        assert isinstance(result, FormatSpec)

    def test_empty_spec(self) -> None:
        spec = parse("")
        assert spec.type == ""
        assert spec.fill == " "
        assert spec.align == ">"
        assert spec.sign == "-"
        assert spec.symbol == ""
        assert not spec.zero
        assert spec.width is None
        assert not spec.comma
        assert spec.precision is None
        assert not spec.trim

    def test_simple_f(self) -> None:
        spec = parse(".2f")
        assert spec.type == "f"
        assert spec.precision == 2
        assert not spec.comma

    def test_comma_f(self) -> None:
        spec = parse(",.2f")
        assert spec.type == "f"
        assert spec.precision == 2
        assert spec.comma

    def test_currency_comma_f(self) -> None:
        spec = parse("$,.2f")
        assert spec.symbol == "$"
        assert spec.comma
        assert spec.precision == 2
        assert spec.type == "f"

    def test_zero_pad(self) -> None:
        spec = parse("06.2f")
        assert spec.zero
        assert spec.width == 6
        assert spec.type == "f"
        assert spec.precision == 2

    def test_fill_align(self) -> None:
        spec = parse("0>10.2f")
        assert spec.fill == "0"
        assert spec.align == ">"
        assert spec.width == 10

    def test_sign_plus(self) -> None:
        spec = parse("+,.2f")
        assert spec.sign == "+"

    def test_sign_space(self) -> None:
        spec = parse(" ,.2f")
        assert spec.sign == " "

    def test_sign_parens(self) -> None:
        spec = parse("(,.2f")
        assert spec.sign == "("

    def test_trim(self) -> None:
        spec = parse(".1~%")
        assert spec.trim
        assert spec.type == "%"
        assert spec.precision == 1

    def test_si_type(self) -> None:
        spec = parse(",.2s")
        assert spec.type == "s"
        assert spec.comma
        assert spec.precision == 2

    def test_tilde_s(self) -> None:
        spec = parse("~s")
        assert spec.trim
        assert spec.type == "s"

    def test_d_type(self) -> None:
        spec = parse("d")
        assert spec.type == "d"

    def test_n_type(self) -> None:
        spec = parse("n")
        assert spec.type == "n"

    def test_e_type(self) -> None:
        spec = parse(".2e")
        assert spec.type == "e"
        assert spec.precision == 2

    def test_g_type(self) -> None:
        spec = parse(".2g")
        assert spec.type == "g"
        assert spec.precision == 2

    def test_r_type(self) -> None:
        spec = parse(".2r")
        assert spec.type == "r"
        assert spec.precision == 2

    def test_percent_type(self) -> None:
        spec = parse(".1%")
        assert spec.type == "%"
        assert spec.precision == 1


class TestParseErrors:
    """Parser must raise D3FormatError for text outside d3's grammar."""

    def test_trailing_garbage(self) -> None:
        with pytest.raises(D3FormatError):
            parse(".2fXXX")

    def test_multi_letter_type_raises(self) -> None:
        with pytest.raises(D3FormatError):
            parse("percent")

    def test_underscore_raises(self) -> None:
        """The typo that motivated compile-time validation of format slots."""
        with pytest.raises(D3FormatError):
            parse("percent_1")

    def test_two_symbols_raise(self) -> None:
        """d3's grammar admits one of '$' or '#', never both."""
        with pytest.raises(D3FormatError):
            parse("$#x")

    def test_non_ascii_letter_raises(self) -> None:
        """d3's type group is ASCII; a Unicode letter is not a valid type."""
        with pytest.raises(D3FormatError):
            parse(".2é")

    def test_non_ascii_digit_raises(self) -> None:
        """d3's width/precision groups are ASCII `\\d`, not any Unicode digit."""
        with pytest.raises(D3FormatError):
            parse("١٠.2f")
        with pytest.raises(D3FormatError):
            parse(".٢f")

    def test_error_has_spec_attribute(self) -> None:
        with pytest.raises(D3FormatError) as exc_info:
            parse(".2fXXX")
        assert exc_info.value.spec == ".2fXXX"

    def test_error_has_position_attribute(self) -> None:
        with pytest.raises(D3FormatError) as exc_info:
            parse(".2fXXX")
        assert isinstance(exc_info.value.position, int)

    def test_error_has_reason_attribute(self) -> None:
        with pytest.raises(D3FormatError) as exc_info:
            parse(".2fXXX")
        assert isinstance(exc_info.value.reason, str)
        assert exc_info.value.reason

    def test_dot_without_digits_raises(self) -> None:
        with pytest.raises(D3FormatError):
            parse(".f")

    def test_error_message_contains_spec(self) -> None:
        with pytest.raises(D3FormatError) as exc_info:
            parse(".2fXXX")
        assert ".2fXXX" in str(exc_info.value)

    def test_error_is_value_error(self) -> None:
        """D3FormatError inherits from ValueError."""
        with pytest.raises(ValueError, match="d3-format parse error"):
            parse(".2fXXX")


class TestFullD3Grammar:
    """Everything d3's grammar admits parses here, with no narrower subset."""

    @pytest.mark.parametrize("type_char", list("efgrs%dnpboxXc"))
    def test_every_d3_type_parses(self, type_char: str) -> None:
        assert parse(type_char).type == type_char

    @pytest.mark.parametrize("spec", ["#b", "#o", "#x", "#X", "#.2f"])
    def test_alternate_form_symbol_parses(self, spec: str) -> None:
        assert parse(spec).symbol == "#"

    def test_parens_with_zero_pad_parses(self) -> None:
        """d3 accepts the combination and brackets the zero-padded digits."""
        spec = parse("(010.2f")
        assert spec.sign == "("
        assert spec.zero is True

    def test_zero_fill_with_equals_align_implies_zero_pad(self) -> None:
        """d3 collapses a '0' fill under '=' align into the zero-pad state."""
        assert parse("0=10.2f").zero is True
        assert parse("0>10.2f").zero is False

    def test_unknown_letter_parses_as_written(self) -> None:
        """parse() reports the spec as authored; the '.12~g' aliasing is format's."""
        assert parse(".1q").type == "q"
        assert parse("Z").type == "Z"


class TestFormatSpecStr:
    """str(FormatSpec) serializes back to a d3-format spec string."""

    @pytest.mark.parametrize(
        "spec_str",
        [
            " =$8,.0s",
            " =$8,.0s",
            ",.2f",
            "$,.0f",
            "0>10.2f",
            ".3~s",
            "+.2%",
        ],
    )
    def test_authored_specs_round_trip_exactly(self, spec_str: str) -> None:
        """str(parse(s)) == s for specs authors actually write."""
        assert str(parse(spec_str)) == spec_str

    def test_default_spec_serializes_empty(self) -> None:
        assert str(FormatSpec()) == ""

    def test_omits_default_valued_tokens(self) -> None:
        """A bare parse(',.2f') does not serialize to a fully-expanded spec."""
        assert str(parse(",.2f")) == ",.2f"


class TestZeroCollapseSerialization:
    """The zero flag must not be emitted alongside a redundant '0=' fill+align."""

    def test_zero_flag_and_explicit_zero_fill_serialize_identically(self) -> None:
        flag_only = parse("05d")
        explicit_fill_align = parse("0=05d")
        assert flag_only == explicit_fill_align
        assert str(flag_only) == "05d"
        assert str(explicit_fill_align) == "05d"

    def test_zero_serialization_has_no_redundant_prefix(self) -> None:
        assert "0=" not in str(parse("05d"))

    def test_mutated_fill_under_zero_raises_instead_of_dropping_silently(self) -> None:
        """str() must not silently discard a caller's fill mutation.

        A zero-padded spec's fill/align are fixed at '0'/'=' by parse()'s
        collapse; a caller-set fill the grammar cannot express alongside the
        zero flag must raise, not disappear.
        """
        spec = parse("05d")
        spec.fill = " "
        with pytest.raises(ValueError, match="zero"):
            str(spec)

    def test_clearing_zero_before_mutating_fill_works(self) -> None:
        """The supported pattern: clear zero, then set an explicit fill/align."""
        spec = parse("05d")
        spec.zero = False
        spec.fill = " "
        assert str(spec) == " =5d"
        assert parse(str(spec)) == spec


class TestFillAlignSymbolHazard:
    """The prior-art note's claimed '$=' corruption hazard, verified rather than assumed.

    The note worried that a spec beginning ``$=`` reads ``$`` as fill, not as
    the currency symbol, and that unparse would therefore need to force an
    explicit fill whenever ``align == "="`` and a symbol is set. Since
    serialization follows grammar order (fill+align, then sign, then symbol),
    a symbol is never emitted immediately before an align character, so the
    ambiguous shape the note describes is never produced. The matrix below
    covers every fill/align/symbol combination and is the actual evidence.
    """

    FILLS = (" ", "0", "$", "#", "=", " ", "*")
    ALIGNS = ("<", ">", "^", "=")
    SYMBOLS = ("", "$", "#")

    @pytest.mark.parametrize("symbol", SYMBOLS)
    @pytest.mark.parametrize("align", ALIGNS)
    @pytest.mark.parametrize("fill", FILLS)
    def test_fill_align_symbol_matrix_round_trips(
        self, fill: str, align: str, symbol: str
    ) -> None:
        built = f"{fill}{align}{symbol}8,.0s"
        spec = parse(built)
        assert parse(str(spec)) == spec

    def test_dollar_align_and_dollar_fill_do_not_collide(self) -> None:
        """'=$...' (align + symbol) and '$=...' (fill + align) are distinct specs."""
        symbol_spec = parse("=$8,.0s")
        fill_spec = parse("$=8,.0s")
        assert symbol_spec != fill_spec
        assert symbol_spec.symbol == "$"
        assert fill_spec.fill == "$"
        assert fill_spec.symbol == ""
        assert parse(str(symbol_spec)) == symbol_spec
        assert parse(str(fill_spec)) == fill_spec


class TestFormatSpecStrProperty:
    """Broad property: parse(str(spec)) == spec, generated across every field."""

    def test_round_trip_matrix(self) -> None:
        fill_aligns = ["", ">", "0>", "$="]
        signs = ["", "-", "+", " ", "("]
        symbols = ["", "$", "#"]
        zero_flags = ["", "0"]
        commas = ["", ","]
        precisions = ["", ".2"]
        trims = ["", "~"]
        types = [*list("efgrs%dnpboxXc"), ""]

        combos = itertools.product(
            fill_aligns, signs, symbols, zero_flags, commas, precisions, trims, types
        )
        for fill_align, sign, symbol, zero, comma, precision, trim, type_ in combos:
            built = f"{fill_align}{sign}{symbol}{zero}8{comma}{precision}{trim}{type_}"
            spec = parse(built)
            assert parse(str(spec)) == spec, f"round trip failed for {built!r}"

    def test_width_variants_round_trip(self) -> None:
        widths = ["", "0", "3", "12"]
        fill_aligns = ["", "0>", "$="]
        for fill_align, width in itertools.product(fill_aligns, widths):
            built = f"{fill_align}{width}.2f"
            spec = parse(built)
            assert parse(str(spec)) == spec, f"round trip failed for {built!r}"
