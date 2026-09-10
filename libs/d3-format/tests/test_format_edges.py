"""Edge case tests for d3_format formatter.

TDD: these tests are written BEFORE the implementation.
"""

import math
from decimal import Decimal

import pytest

from d3_format import D3FormatError, format as d3_format


class TestNumericTypes:
    """Formatter must accept int, float, and Decimal."""

    def test_int_input(self) -> None:
        assert d3_format(",.0f")(1000) == "1,000"

    def test_float_input(self) -> None:
        assert d3_format(",.2f")(1234.56) == "1,234.56"

    def test_decimal_input(self) -> None:
        result = d3_format(",.2f")(Decimal("1234.56"))
        assert result == "1,234.56"


class TestSpecialValues:
    """NaN and Infinity handling must match d3.js exactly."""

    def test_nan_returns_nan_string(self) -> None:
        result = d3_format(",.2f")(math.nan)
        assert result == "NaN"

    def test_pos_infinity(self) -> None:
        result = d3_format(",.2f")(math.inf)
        assert result == "Infinity"

    def test_neg_infinity(self) -> None:
        result = d3_format(",.2f")(-math.inf)
        # d3 uses U+2212 minus sign
        assert result == "−Infinity"

    def test_nan_with_dollar(self) -> None:
        # d3 keeps prefix for NaN
        result = d3_format("$,.2f")(math.nan)
        assert result == "$NaN"

    def test_inf_with_dollar(self) -> None:
        result = d3_format("$,.2f")(math.inf)
        assert result == "$Infinity"

    def test_neg_inf_with_dollar(self) -> None:
        result = d3_format("$,.2f")(-math.inf)
        assert result == "−$Infinity"

    def test_nan_with_percent(self) -> None:
        result = d3_format(".1%")(math.nan)
        assert result == "NaN%"

    def test_negative_zero(self) -> None:
        # -0.0 is formatted as 0
        result = d3_format(",.2f")(float("-0"))
        assert result == "0.00"


class TestExtremeValues:
    """Very large and very small values."""

    def test_very_large(self) -> None:
        # Should not crash
        result = d3_format(".2e")(1e100)
        assert "e+" in result

    def test_very_small(self) -> None:
        result = d3_format(".2e")(1e-100)
        assert "e-" in result or "e−" in result


class TestConvenienceCallStyle:
    """format() supports both curried and direct calling conventions."""

    def test_curried_call(self) -> None:
        formatter = d3_format(",.2f")
        assert formatter(1234.56) == "1,234.56"

    def test_direct_call(self) -> None:
        assert d3_format(",.2f", 1234.56) == "1,234.56"

    def test_curried_reuse(self) -> None:
        fmt = d3_format(",.0f")
        assert fmt(1000) == "1,000"
        assert fmt(2000) == "2,000"


class TestInvalidSpecRaises:
    """A spec outside d3's grammar must raise D3FormatError, not degrade.

    Every type letter d3 defines is formattable here (the parity fixture covers
    their output), so what is left to reject is text the grammar itself refuses
    -- which is what makes an authoring typo like `percent_1` catchable.
    """

    @pytest.mark.parametrize(
        "spec",
        [
            "percent_1",  # underscore is not in the grammar
            "percent",  # multi-letter type
            ".2fXXX",  # trailing garbage after the type
            ".f",  # precision dot with no digits
            "$#x",  # two symbols; d3 admits one
            "%%",  # not a type letter
        ],
    )
    def test_invalid_spec_raises(self, spec: str) -> None:
        with pytest.raises(D3FormatError):
            d3_format(spec)

    def test_unknown_type_letter_falls_back(self) -> None:
        """d3 aliases an unrecognized letter to '.12~g' rather than raising."""
        assert d3_format("q")(1234.5678) == d3_format("")(1234.5678)
        assert d3_format(".1q")(1234.5678) == "1e+3"


class TestZeroCommaGrouping:
    """Zero-pad + comma must group the leading zeros (d3 parity)."""

    def test_zero_comma_groups_leading_zeros(self) -> None:
        # d3: format("015,.0f")(1234567) → "000,001,234,567"
        assert d3_format("015,.0f")(1234567) == "000,001,234,567"

    def test_zero_comma_no_padding_needed(self) -> None:
        # Body already fills width — no extra zeros, normal grouping.
        assert d3_format("09,.0f")(1234567) == "1,234,567"

    def test_zero_comma_overflow(self) -> None:
        # Grouped body exceeds width — no truncation, return as-is.
        assert d3_format("06,.0f")(1234567) == "1,234,567"
