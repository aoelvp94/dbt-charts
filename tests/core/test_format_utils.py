"""Tests for D3 formatting utilities.

Tests the dbt_charts.render.format_utils module for formatting values
using D3-style format specifications and theme-defined format aliases.
"""

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import get_theme_style, list_built_in_themes
from dbt_charts.core.compile.format import resolve_label_format
from dbt_charts.core.diagnostics.codes_render import ERR_PERCENT_RANGE
from dbt_charts.core.render.errors import RenderError
from dbt_charts.core.render.format_utils import (
    FormatConfig,
    format_d3,
    format_kpi_parts,
    format_value,
    get_format_prefix_suffix,
    resolve_format,
)

_ALIAS_FORMATS = {"compact": "~s", "currency": "$,.2f"}


class TestResolveLabelFormat:
    """resolve_label_format: alias-vs-literal is the only register signal.

    House (narrative) fires exactly when the raw string is a theme alias
    resolving to an SI spec — never based on who set it. A hand-typed literal
    SI spec is always a native opt-out, alias or not otherwise.
    """

    def test_alias_si_is_house(self):
        # "compact" is a predefined name, not a user alias — hits predefined
        # path regardless of the formats dict; the _ALIAS_FORMATS dict is
        # irrelevant here but kept for API-contract clarity.
        resolved, is_house = resolve_label_format("compact", _ALIAS_FORMATS)
        assert resolved == "~s"
        assert is_house is True

    def test_literal_si_is_not_house(self):
        # Inline d3 specs are native (three-way contract): no trim injection,
        # no house-notation register — .2s stays .2s.
        resolved, is_house = resolve_label_format(".2s", _ALIAS_FORMATS)
        assert resolved == ".2s"
        assert is_house is False

    def test_non_si_alias_is_not_house(self):
        resolved, is_house = resolve_label_format("currency", _ALIAS_FORMATS)
        assert resolved == "$,.2f"
        assert is_house is False

    def test_non_si_literal_is_not_house(self):
        resolved, is_house = resolve_label_format("$,.2f", _ALIAS_FORMATS)
        assert resolved == "$,.2f"
        assert is_house is False

    def test_none_is_not_house(self):
        resolved, is_house = resolve_label_format(None, _ALIAS_FORMATS)
        assert resolved is None
        assert is_house is False

    def test_unknown_key_not_in_formats_treated_as_literal(self):
        # A string that isn't a real alias and isn't valid d3 grammar either
        # is a compile-time authoring error elsewhere; resolve_label_format
        # itself just reports is_alias=False for it (not house).
        resolved, is_house = resolve_label_format("~s", None)
        assert resolved == "~s"
        assert is_house is False

    def test_various_alias_si_shapes(self):
        # User-alias keys that are not predefined names: native d3 path.
        # No trim injection, not house — the spec is returned verbatim.
        formats = {"a": "~s", "b": ".2~s", "c": ".3s", "d": "s"}
        expected_resolved = {"a": "~s", "b": ".2~s", "c": ".3s", "d": "s"}
        for key in formats:
            resolved, is_house = resolve_label_format(key, formats)
            assert resolved == expected_resolved[key], key
            assert is_house is False, key

    def test_format_config_object_uses_spec_for_alias_check(self):
        # "compact" is a predefined name; FormatConfig.spec is the lookup key.
        resolved, is_house = resolve_label_format(
            FormatConfig(spec="compact"), _ALIAS_FORMATS
        )
        assert resolved == "~s"
        assert is_house is True


class TestResolveFormatThemeLookup:
    """resolve_format resolves aliases from a caller-supplied formats dict."""

    def test_alias_in_formats_dict(self):
        assert resolve_format("currency", {"currency": "$,.2f"}) == "$,.2f"

    def test_custom_alias_in_formats_dict(self):
        assert resolve_format("revenue", {"revenue": "$~s"}) == "$~s"

    def test_raw_d3_spec_passthrough_when_not_in_formats(self):
        assert resolve_format("$,.0f", {"currency": "$,.2f"}) == "$,.0f"

    def test_no_formats_dict_predefined_resolves(self):
        # Predefined names resolve via the engine spec regardless of formats dict.
        assert resolve_format("currency", None) == "$,.2f"

    def test_predefined_resolves_without_formats_dict(self):
        # "compact" is a predefined member — trim already in spec, round_aware_spec is no-op.
        assert resolve_format("compact") == "~s"

    def test_null_format_input_returns_empty(self):
        assert resolve_format(None, {"currency": "$,.2f"}) == ""

    def test_null_format_input_no_formats_returns_empty(self):
        assert resolve_format(None) == ""

    def test_format_config_spec_resolved_via_formats(self):
        config = FormatConfig(spec="currency")
        assert resolve_format(config, {"currency": "$,.2f"}) == "$,.2f"

    def test_format_config_raw_d3_passthrough(self):
        config = FormatConfig(spec="$,.2f")
        assert resolve_format(config, {"currency": "$,.2f"}) == "$,.2f"

    def test_dict_format_spec_resolved_via_formats(self):
        assert resolve_format({"spec": "currency"}, {"currency": "$,.2f"}) == "$,.2f"

    def test_dict_format_raw_d3_passthrough(self):
        assert resolve_format({"spec": "$,.2f"}, {"currency": "$,.2f"}) == "$,.2f"

    def test_empty_spec_returns_empty(self):
        assert resolve_format(FormatConfig(spec=None), {"currency": "$,.2f"}) == ""
        assert resolve_format(FormatConfig(spec=""), {"currency": "$,.2f"}) == ""
        assert resolve_format({"spec": ""}, {"currency": "$,.2f"}) == ""

    def test_formats_dict_case_sensitive(self):
        # Lookup is case-sensitive — theme key "Currency" != "currency"
        assert resolve_format("Currency", {"currency": "$,.2f"}) == "Currency"

    def test_unknown_alias_passthrough(self):
        # Not in formats → passthrough (d3 may reject at render time)
        assert resolve_format("~s", {"currency": "$,.2f"}) == "~s"
        assert resolve_format("+$,.2f", {"currency": "$,.2f"}) == "+$,.2f"


class TestD3Passthrough:
    """D3 format strings pass through unchanged regardless of formats dict."""

    def test_d3_formats_passed_through_with_formats(self):
        # Inline d3 specs are native — no trim, no substitution.
        fmt = {"currency": "$,.2f"}
        assert resolve_format("$,.2f", fmt) == "$,.2f"
        assert resolve_format(".1%", fmt) == ".1%"
        assert resolve_format(",.2s", fmt) == ",.2s"
        assert resolve_format(".0f", fmt) == ".0f"

    def test_d3_formats_passed_through_without_formats(self):
        assert resolve_format("$,.2f") == "$,.2f"
        assert resolve_format(".1%") == ".1%"


class TestGetFormatPrefixSuffix:
    """Tests for prefix/suffix extraction."""

    def test_string_format_no_prefix_suffix(self):
        assert get_format_prefix_suffix("currency") == ("", "")
        assert get_format_prefix_suffix("$,.2f") == ("", "")

    def test_format_config_prefix_suffix(self):
        config = FormatConfig(spec=",.0f", prefix="$", suffix=" USD")
        assert get_format_prefix_suffix(config) == ("$", " USD")

    def test_dict_prefix_suffix(self):
        fmt = {"spec": ",.0f", "prefix": "€", "suffix": " EUR"}
        assert get_format_prefix_suffix(fmt) == ("€", " EUR")

    def test_none_values(self):
        assert get_format_prefix_suffix(None) == ("", "")
        config = FormatConfig(spec=",.0f")
        assert get_format_prefix_suffix(config) == ("", "")


class TestFormatD3:
    """Tests for D3-style value formatting — d3-correct output via libs/d3-format/."""

    def test_fixed_point_formatting(self):
        assert format_d3(1234.567, ",.2f") == "1,234.57"
        assert format_d3(1234.567, ".2f") == "1234.57"
        assert format_d3(1234.567, ",.0f") == "1,235"

    def test_currency_formatting(self):
        assert format_d3(1234.56, "$,.2f") == "$1,234.56"
        assert format_d3(1000, "$,.0f") == "$1,000"

    def test_percent_formatting(self):
        assert format_d3(0.123, ".1%") == "12.3%"
        assert format_d3(0.1234, ".2%") == "12.34%"
        assert format_d3(1, ".0%") == "100%"

    def test_si_prefix_formatting(self):
        # d3's .2s = 2 significant figures. format_d3 with notation=None
        # (the default) returns raw d3 output — no house notation substitution.
        # Notation substitution only fires when the caller passes notation= explicitly.
        assert format_d3(1500000, ",.2s") == "1.5M"
        assert format_d3(1500, ",.2s") == "1.5k"
        assert format_d3(1500000000, ",.2s") == "1.5G"
        assert format_d3(1500000000000, ",.2s") == "1.5T"

    def test_custom_prefix_suffix(self):
        assert format_d3(1234, ",.0f", prefix="$", suffix=" USD") == "$1,234 USD"
        assert format_d3(100, ",.0f", suffix=" users") == "100 users"

    def test_none_value(self):
        assert format_d3(None, ",.2f") == "—"
        assert format_d3(None, "$,.2f", prefix="$") == "$—"

    def test_empty_format(self):
        assert format_d3(1234, "") == "1234"
        assert format_d3(1234, "", prefix="$") == "$1234"

    def test_negative_values(self):
        # d3 uses U+2212 (−) and places sign before the currency symbol.
        assert format_d3(-1234.56, "$,.2f") == "−$1,234.56"
        assert format_d3(-0.15, ".1%") == "−15.0%"

    def test_negative_si_values(self):
        # d3 uses U+2212 minus sign. Raw d3 output with notation=None.
        assert format_d3(-1500000, ",.2s") == "−1.5M"


class TestFormatValue:
    """Tests for the main format_value entry point — accepts formats dict."""

    def test_alias_formatting_with_formats(self):
        formats = {"currency": "$,.2f", "percent": ".1%", "compact": ",.2s"}
        assert format_value(1234567.89, "currency", formats) == "$1,234,567.89"
        assert format_value(0.123, "percent", formats) == "12.3%"
        # .2s = 2 significant figures via d3_format lib
        assert format_value(1500000, "compact", formats) == "1.5 M"

    def test_d3_formatting_without_formats(self):
        assert format_value(1234.56, "$,.2f") == "$1,234.56"
        assert format_value(0.123, ".1%") == "12.3%"

    def test_format_config_object(self):
        config = FormatConfig(spec=",.0f", prefix="$", suffix=" USD")
        assert format_value(1234, config) == "$1,234 USD"

    def test_dict_format_config(self):
        # Dict format config with no notation key: native d3 (no substitution).
        config = {"spec": ",.2s", "suffix": " users"}
        assert format_value(1500000, config) == "1.5M users"

    def test_none_format(self):
        assert format_value(1234, None) == "1234"

    def test_none_value_with_prefix_suffix_config(self):
        # None falls through to format_d3 which returns f"{prefix}—{suffix}".
        assert (
            format_value(None, FormatConfig(spec=".2f", prefix="£", suffix=" GBP"))
            == "£— GBP"
        )


class TestNewAliases:
    """Verify predefined format names that were previously theme aliases.

    These are now engine-owned predefined formats. The formats dict is ignored
    for these names — they always resolve through the predefined-spec path.
    """

    def test_currency_whole_resolves(self):
        assert resolve_format("currency_whole") == "$,.0f"

    def test_currency_whole_formats_value(self):
        assert format_value(1234.56, "currency_whole") == "$1,235"

    def test_currency_compact_resolves(self):
        # Engine spec "$~s" — trim already set; round_aware_spec is a no-op.
        assert resolve_format("currency_compact") == "$~s"

    def test_currency_compact_formats_value(self):
        assert format_value(1_500_000, "currency_compact") == "$1.5 M"

    def test_percent_whole_resolves(self):
        assert resolve_format("percent_whole") == ".0%"

    def test_percent_whole_formats_value(self):
        assert format_value(0.154, "percent_whole") == "15%"

    def test_percent_delta_resolves(self):
        assert resolve_format("percent_delta") == "+.1%"

    def test_percent_delta_positive_value(self):
        assert format_value(0.054, "percent_delta") == "+5.4%"

    def test_percent_delta_negative_value(self):
        assert format_value(-0.054, "percent_delta") == "−5.4%"


class TestDeltaAlias:
    """`delta` predefined format — signed integer, for KPI support deltas.

    d3's `+` sign flag forces a leading sign on positive values; the minus
    sign on negatives is d3's normal behavior (U+2212, not ASCII hyphen).
    Now engine-owned (predefined), so no theme cascade needed.
    """

    def test_delta_resolves(self):
        # Engine-owned predefined: resolves regardless of formats dict.
        assert resolve_format("delta") == "+,d"

    def test_delta_positive_value(self):
        assert format_value(31, "delta") == "+31"

    def test_delta_negative_value(self):
        assert format_value(-31, "delta") == "−31"

    @pytest.mark.parametrize(
        "theme", [t for t in list_built_in_themes() if not t.startswith("_")]
    )
    def test_delta_predefined_every_theme_formats_is_none(self, theme: str):
        """delta is now a predefined engine format, not a theme alias.
        Themes no longer carry it in style.formats."""
        theme_formats = get_theme_style(theme).formats
        assert theme_formats is None or "delta" not in theme_formats


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_value_with_formats(self):
        formats = {"currency": "$,.2f", "percent": ".1%", "compact": ",.2s"}
        assert format_value(0, "currency", formats) == "$0.00"
        # .1% is not an SI spec, so round-awareness doesn't apply — 0 → "0.0%"
        assert format_value(0, "percent", formats) == "0.0%"
        # d3's .2s on 0, round-aware: no SI prefix and no false-precision zero.
        assert format_value(0, "compact", formats) == "0"

    def test_very_large_numbers(self):
        # d3's .2s = 2 significant figures: 999_999_999_999 → 1.0T not 1,000B.
        # User alias "big_si" (non-predefined) → native d3 path, no notation
        # substitution — raw d3 suffix "T" stays as-is (no space).
        assert format_value(999999999999, "big_si", {"big_si": ",.2s"}) == "1.0T"
        assert format_value(1234567890123, "big_si", {"big_si": ",.2s"}) == "1.2T"

    def test_float_precision(self):
        result = format_value(0.1 + 0.2, ".1f")
        assert result == "0.3"


class TestNotationFamilies:
    """Tests for analytic and narrative notation families."""

    # --- Analytic notation (default) ---

    def test_no_default_notation_gives_raw_d3(self):
        # format_d3 without notation= returns raw d3 output — no house
        # substitution. Analytic/narrative require explicit notation= by the
        # predefined-format caller; inline specs use native d3.
        assert format_d3(1_500, ",.2s") == "1.5k"
        assert format_d3(2_500_000, ",.2s") == "2.5M"
        assert format_d3(3_500_000_000, ",.2s") == "3.5G"
        assert format_d3(4_500_000_000_000, ",.2s") == "4.5T"

    def test_analytic_notation_explicit(self):
        assert format_d3(1_500, ",.2s", notation="analytic") == "1.5 K"
        assert format_d3(2_500_000, ",.2s", notation="analytic") == "2.5 M"

    # --- Narrative notation ---

    def test_narrative_notation_suffixes(self):
        assert format_d3(1_500, ",.2s", notation="narrative") == "1.5k"
        assert format_d3(2_500_000, ",.2s", notation="narrative") == "2.5mn"
        assert format_d3(3_500_000_000, ",.2s", notation="narrative") == "3.5bn"
        assert format_d3(4_500_000_000_000, ",.2s", notation="narrative") == "4.5trn"

    def test_narrative_notation_negative(self):
        # d3 uses U+2212 minus sign
        assert format_d3(-1_500_000, ",.2s", notation="narrative") == "−1.5mn"

    def test_narrative_notation_below_threshold(self):
        assert format_d3(500, ",.2s", notation="narrative") == "500"

    # --- FormatConfig threading ---

    def test_format_config_notation_field(self):
        config = FormatConfig(spec=",.2s", notation="narrative")
        assert config.notation == "narrative"

    def test_format_config_notation_default(self):
        config = FormatConfig(spec=",.2s")
        assert config.notation is None

    def test_format_value_with_narrative_config(self):
        config = FormatConfig(spec=",.2s", notation="narrative")
        assert format_value(2_500_000, config) == "2.5mn"

    def test_format_value_with_dict_notation(self):
        config = {"spec": ",.2s", "notation": "narrative"}
        assert format_value(2_500_000, config) == "2.5mn"

    def test_format_kpi_parts_with_narrative(self):
        config = FormatConfig(spec=",.2s", notation="narrative")
        assert format_kpi_parts(2_500_000, config) == ("", "2.5", "mn")

    def test_format_value_dict_no_notation_is_native(self):
        # Dict format without notation= takes the native-d3 path: no substitution.
        assert format_value(1_500_000, {"spec": ",.2s"}) == "1.5M"

    def test_unknown_notation_raises(self):
        with pytest.raises(ValueError, match="Unknown notation"):
            format_d3(1_500, ",.2s", notation="scientific")

    def test_notation_only_affects_si_format(self):
        config = FormatConfig(spec=",.2f", notation="narrative")
        assert format_value(1_500_000, config) == "1,500,000.00"


class TestPercentRangeGuard:
    """percent-family non-delta formats reject 0-100-shaped values instead of
    silently multiplying them by 100 (e.g. 18.2 -> "1820%").

    Threshold is 10.0 for `percent` / `percent_whole` (shares and rates where
    >10 is nearly always a SQL mistake). Delta specs (d3 `+` sign flag, e.g.
    `+.1%` = `percent_delta`) are unconditionally exempt — large deltas like
    +1200% growth (12.0) are legitimate data, not SQL mistakes.
    Callers short-circuit None before the guard.
    """

    _FORMATS = {"percent": ".1%", "percent_whole": ".0%", "percent_delta": "+.1%"}

    def test_percent_whole_rejects_0_100_shaped_value(self):
        with pytest.raises(RenderError) as exc_info:
            format_value(18.2, "percent_whole", self._FORMATS)
        assert exc_info.value.code is ERR_PERCENT_RANGE

    def test_percent_whole_ratio_value_unchanged(self):
        assert format_value(0.182, "percent_whole", self._FORMATS) == "18%"

    def test_boundary_9_9_is_a_legitimate_high_ratio(self):
        # 9.9 is below the 10.0 threshold — a genuine 990% ratio (e.g. 9x ROI),
        # not 0-100-shaped SQL data.
        assert format_value(9.9, "percent_whole", self._FORMATS) == "990%"

    def test_boundary_10_0_rejected(self):
        with pytest.raises(RenderError) as exc_info:
            format_value(10.0, "percent_whole", self._FORMATS)
        assert exc_info.value.code is ERR_PERCENT_RANGE

    def test_percent_delta_large_values_never_raise(self):
        # Delta specs (d3 + sign flag) are unconditionally exempt — no threshold.
        # +1200% growth (12.0) and -1820% (−18.2) are legitimate delta values.
        assert format_value(3.0, "percent_delta", self._FORMATS) == "+300.0%"
        assert format_value(12.0, "percent_delta", self._FORMATS) == "+1200.0%"
        assert format_value(-18.2, "percent_delta", self._FORMATS) == "−1820.0%"

    def test_negative_0_100_shaped_value_rejected(self):
        with pytest.raises(RenderError) as exc_info:
            format_value(-18.2, "percent_whole", self._FORMATS)
        assert exc_info.value.code is ERR_PERCENT_RANGE

    def test_percent_guarded_not_delta(self):
        with pytest.raises(RenderError):
            format_value(18.2, "percent", self._FORMATS)
        # percent_delta is exempt — same value renders without error
        assert format_value(18.2, "percent_delta", self._FORMATS) == "+1820.0%"

    def test_raw_d3_percent_spec_also_guarded(self):
        # Non-delta raw d3 "%" specs get the guard — failure mode identical.
        with pytest.raises(RenderError):
            format_value(18.2, ".0%")

    def test_raw_delta_d3_spec_not_guarded(self):
        # Raw d3 "+.0%" is a delta spec (d3 sign flag) — exempt from the guard.
        assert format_value(18.2, "+.0%") == "+1820%"

    def test_error_message_mentions_dividing_by_100(self):
        with pytest.raises(RenderError) as exc_info:
            format_value(18.2, "percent_whole", self._FORMATS)
        assert "100" in str(exc_info.value)

    def test_percent_number_native_formatter_not_guarded(self):
        # percent_number is a native formatter (the value already IS the
        # percent, e.g. 12.8 means 12.8%) — not part of the d3 "%"-type
        # percent family, so the range guard does not apply to it.
        assert format_value(18.2, "percent_number") == "18.2%"

    def test_format_kpi_parts_also_guarded(self):
        with pytest.raises(RenderError) as exc_info:
            format_kpi_parts(18.2, "percent_whole", self._FORMATS)
        assert exc_info.value.code is ERR_PERCENT_RANGE


class TestNotationRenameRegression:
    """Old `bi`/`editorial` names are gone; only `analytic`/`narrative` validate."""

    def test_analytic_validates(self):
        assert FormatConfig(notation="analytic").notation == "analytic"

    def test_narrative_validates(self):
        assert FormatConfig(notation="narrative").notation == "narrative"

    def test_old_bi_name_rejected(self):
        with pytest.raises(ValidationError):
            FormatConfig(notation="bi")

    def test_old_editorial_name_rejected(self):
        with pytest.raises(ValidationError):
            FormatConfig(notation="default")

    def test_format_d3_analytic_renders_analytic_register(self):
        assert format_d3(1_500, "$.2s", notation="analytic") == "$1.5 K"

    def test_format_d3_narrative_renders_narrative_register(self):
        assert format_d3(1_500_000_000, ".2s", notation="narrative") == "1.5bn"


class TestRoundAwareSignificantFigures:
    """Trim (``~``) on SI specs: baked once at resolve_format for predefined formats.

    format_d3 is a pure D3 formatter — it no longer injects ``~`` internally.
    Authors who want trailing-zero trimming on inline SI specs must write ``~``
    themselves (``".2~s"``), or use a predefined format whose resolve_format
    bakes the trim.

    format_kpi_parts uses _d3_format directly for its SI split path; trim only
    applies when the spec already carries ``~``.
    """

    def test_inline_si_without_tilde_keeps_trailing_zero(self):
        # No ~ in spec: format_d3 does not inject it — "$1.0M" (trailing zero).
        assert format_d3(1_000_000, "$,.2s") == "$1.0M"

    def test_non_clean_value_keeps_its_digits(self):
        assert format_d3(1_250_000, "$,.3s") == "$1.25M"

    def test_explicit_trim_flag_removes_trailing_zero(self):
        # Author-supplied ~: trim is applied by d3 itself.
        assert format_d3(1_000_000, "$,.2~s") == "$1M"

    def test_non_si_spec_is_unaffected(self):
        assert format_d3(1_000_000, ",.2f") == "1,000,000.00"

    def test_kpi_parts_inline_d3_no_trim_in_spec(self):
        # Inline "$,.2s" — no trim → "1.0M".
        assert format_kpi_parts(1_000_000, "$,.2s") == ("$", "1.0", "M")

    def test_kpi_parts_predefined_trim_baked(self):
        # "currency_compact" → resolve_format returns "$~s" (trim already set) → "1M".
        assert format_kpi_parts(1_000_000, "currency_compact") == ("$", "1", "M")

    def test_kpi_parts_real_digit_survives(self):
        assert format_kpi_parts(1_250_000, "$,.3s") == ("$", "1.25", "M")


class TestAboveTrillionsNarrativeFallback:
    """No accepted narrative form exists above trillions, so narrative
    borrows the analytic (spaced, capital-letter) suffix rather than emit
    d3's bare, unmapped SI letter — a shipped artifact must always speak a
    house register."""

    def test_peta_falls_back_to_analytic_form(self):
        assert format_d3(1e15, ",.2~s", notation="narrative") == "1 P"

    def test_fallback_is_never_the_bare_d3_letter(self):
        # d3's own raw SI output for 1e15 is "1P" -- the house register must
        # never let that reach a shipped artifact.
        assert format_d3(1e15, ",.2~s", notation="narrative") != "1P"

    def test_exa_zetta_yotta_all_fall_back(self):
        assert format_d3(1e18, ",.2~s", notation="narrative") == "1 E"
        assert format_d3(1e21, ",.2~s", notation="narrative") == "1 Z"
        assert format_d3(1e24, ",.2~s", notation="narrative") == "1 Y"

    def test_analytic_unaffected_by_the_fallback(self):
        assert format_d3(1e15, ",.2~s", notation="analytic") == "1 P"

    def test_kpi_parts_headline_fallback_has_no_leading_space(self):
        # format_kpi_parts splits the magnitude into its own lane; visual
        # spacing is geometry (kpi.py's dx="2"), not a string character, so
        # the lane-suffix stays bare like every other magnitude token.
        assert format_kpi_parts(1e15, {"spec": ",.2~s", "notation": "narrative"}) == (
            "",
            "1",
            "P",
        )


class TestNullZeroSharedContract:
    """Null and zero render from one shared constant, not per-surface literals."""

    def test_format_d3_null_uses_the_shared_constant(self):
        from dbt_charts.core.text.format_d3 import NULL_DISPLAY

        assert format_d3(None, ",.2f") == NULL_DISPLAY

    def test_format_kpi_parts_null_uses_the_shared_constant(self):
        from dbt_charts.core.text.format_d3 import NULL_DISPLAY

        assert format_kpi_parts(None, ",.2f") == ("", NULL_DISPLAY, "")

    def test_zero_is_a_real_value_not_the_null_display(self):
        assert format_d3(0, ",.0f") == "0"
        assert format_kpi_parts(0, ",.0f") == ("", "0", "")


class TestYearAlias:
    """A year is an identifier, not a quantity — no grouping, no SI scaling."""

    def test_year_resolves(self):
        assert resolve_format("year") == "d"

    def test_year_formats_a_value_with_no_thousands_separator(self):
        assert format_value(2025, "year") == "2025"

    @pytest.mark.parametrize(
        "theme", [t for t in list_built_in_themes() if not t.startswith("_")]
    )
    def test_year_alias_theme_formats_is_none_or_has_no_year_key(self, theme: str):
        """year is now a predefined engine format, not a theme alias.
        Themes no longer need to carry it in style.formats."""
        theme_formats = get_theme_style(theme).formats
        assert theme_formats is None or "year" not in theme_formats


class TestPercentagePointsDeltaToken:
    """The difference of two percentages is expressed in points, not the `%`
    that d3's `%` type would multiply by 100 (which is right for a ratio
    delta but wrong for a percentage-point delta)."""

    def test_positive_value(self):
        assert format_value(3.2, "percentage_points_delta") == "+3.2 pts"

    def test_negative_value(self):
        # PREDEFINED_NATIVE bypasses d3_format, so its own lambda is
        # responsible for the house minus glyph (U+2212), same as every
        # d3-formatted negative.
        assert format_value(-1.5, "percentage_points_delta") == "−1.5 pts"

    def test_null_value(self):
        from dbt_charts.core.text.format_d3 import NULL_DISPLAY

        assert format_value(None, "percentage_points_delta") == NULL_DISPLAY

    def test_kpi_parts_splits_unit_into_suffix_lane(self):
        """The ' pts' unit must land in the suffix lane, not ride inside the
        number lane — table symbol_mode: anchors anchors the suffix lane to
        the first row; a unit stuck in the number lane repeats on every row
        and the digits don't align down the column."""
        prefix, number, suffix = format_kpi_parts(-3.2, "percentage_points_delta")
        assert prefix == ""
        assert number == "−3.2"
        assert suffix == " pts"


class TestFormatKpiPartsNative:
    """format_kpi_parts(native=True) keeps raw d3 SI suffix chars instead of
    substituting them with the house analytic/narrative vocabulary."""

    def test_native_true_keeps_raw_d3_suffix(self):
        """native=True: 1_200_000 with ~s format → suffix "M" (raw d3), not "mn"."""
        prefix, num, suffix = format_kpi_parts(
            1_200_000,
            FormatConfig(spec="~s", notation="narrative"),
            formats={},
            native=True,
        )
        assert suffix == "M", f"expected raw d3 'M', got {suffix!r}"
        assert num == "1.2"
        assert prefix == ""

    def test_native_false_uses_narrative_notation(self):
        """native=False (default): FormatConfig with notation='narrative' → suffix 'mn'."""
        _, _, suffix = format_kpi_parts(
            1_200_000,
            FormatConfig(spec="~s", notation="narrative"),
            formats={},
            native=False,
        )
        assert suffix == "mn"

    def test_native_true_thousands(self):
        """native=True: 5_000 with ~s format → suffix "k" (raw d3 lowercase)."""
        _, num, suffix = format_kpi_parts(
            5_000,
            FormatConfig(spec="~s", notation="narrative"),
            formats={},
            native=True,
        )
        assert suffix == "k"
        assert num == "5"

    def test_native_true_billions_keeps_g_suffix(self):
        """native=True: 3.2e9 with ~s → suffix "G" (raw d3 giga, not house "B").

        MAGNITUDE_SUFFIXES must include raw d3 keys (k/M/G/T/…) in addition to
        house notation values (K/M/B/T/…). Without "G", table symbol_mode:anchors
        strips the suffix from non-first rows, making 3.2B render as "3.2".
        """
        _, num, suffix = format_kpi_parts(
            3_200_000_000,
            "~s",
            formats={},
            native=True,
        )
        from dbt_charts.core.render.format_utils import MAGNITUDE_SUFFIXES

        assert suffix == "G", f"expected raw d3 'G', got {suffix!r}"
        assert "G" in MAGNITUDE_SUFFIXES, "MAGNITUDE_SUFFIXES must include raw d3 'G'"


class TestJinjaFormatFilter:
    """The {{ value | format(...) }} Jinja filter uses format_d3 with no trim injection.

    Before this branch, format_d3 silently injected the round-aware '~' trim flag
    and defaulted notation to 'analytic'. Now the filter is native d3 only: the
    spec passes through unchanged and no notation is applied. Authors who want trim
    or notation use a predefined name on the chart-level format: field, not the
    Jinja filter.
    """

    def _render(self, template: str, value: float) -> str:
        from dbt_charts.core.compile.template.labels_env import label_jinja_env

        env = label_jinja_env()
        return env.from_string(template).render(value=value)

    def test_si_spec_no_trim_injected(self) -> None:
        """Inline SI spec keeps trailing zeros — no '~' trim is baked in."""
        result = self._render("{{ value | format('.3s') }}", 1_000_000.0)
        assert result == "1.00M", f"expected '1.00M', got {result!r}"

    def test_si_spec_with_explicit_trim_trims(self) -> None:
        """Author-supplied '~' in the spec is honoured as native d3."""
        result = self._render("{{ value | format('.3~s') }}", 1_000_000.0)
        assert result == "1M", f"expected '1M', got {result!r}"

    def test_no_analytic_notation_applied(self) -> None:
        """No house notation — '1.5G' not rewritten to '1.5 B'."""
        result = self._render("{{ value | format('.2s') }}", 1_500_000_000.0)
        assert result == "1.5G", f"expected raw d3 '1.5G', got {result!r}"
