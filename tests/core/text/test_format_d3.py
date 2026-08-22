"""portable_strftime: GNU/BSD no-pad modifiers (%-d) computed in Python.

Regression coverage for Windows compile/render failures: the host CRT's
strftime doesn't implement the `-`/`_`/`0` padding modifiers d3-time-format
specs use (e.g. ``%-d %b %Y``), raising ``ValueError: Invalid format string``.

On glibc/macOS, the host strftime already implements `%-d` natively, so
asserting only the final rendered string doesn't prove the Python-side
substitution ran at all — it would pass identically with the fix reverted.
These tests instead pin the intermediate substituted format string (so no
`%[-_0]` directive survives to reach the host libc) and, for the end-to-end
path, run against a `date` subclass that raises exactly like Windows' CRT
does on any such directive.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from dbt_charts.core.text.format_d3 import _apply_padding_modifiers, portable_strftime


class _WindowsLikeDate(date):
    """Stand-in for Windows' CRT: raises on any unresolved %-/%_/%0 directive,
    and on `%C %e %G %j %k %l %u %V %W` even bare (no modifier) — Windows'
    CRT has never implemented these glibc/BSD extensions, with or without a
    padding modifier.

    Simulates the actual platform failure so the suite proves the fix
    regardless of what OS runs the tests.
    """

    def strftime(self, fmt: str) -> str:
        stripped = fmt.replace("%%", "")
        if re.search(r"%[-_0][A-Za-z]", stripped) or re.search(
            r"%[CeGjkluVW]", stripped
        ):
            raise ValueError("Invalid format string")
        return super().strftime(fmt)


def test_no_modifier_matches_plain_strftime() -> None:
    d = date(2024, 1, 3)
    assert portable_strftime(d, "%b %Y") == d.strftime("%b %Y")


def test_dash_modifier_strips_leading_zero() -> None:
    assert portable_strftime(date(2024, 1, 3), "%-d %b %Y") == "3 Jan 2024"
    assert portable_strftime(date(2024, 1, 13), "%-d %b %Y") == "13 Jan 2024"


def test_dash_modifier_on_zero_value_yields_zero_not_empty() -> None:
    d = datetime(2024, 1, 1, 0, 0)
    assert portable_strftime(d, "%-H:%-M") == "0:0"


def test_dash_modifier_on_space_padded_directive_matches_raw_strftime() -> None:
    """%e/%k/%l are space- not zero-padded by default; -/0 must still work."""
    d = datetime(2024, 1, 3, 9, 5)
    for directive in ("e", "k", "l"):
        assert (
            portable_strftime(d, f"%-{directive}")
            == d.strftime(f"%{directive}").strip()
        )


def test_zero_modifier_forces_zero_padding_on_space_padded_directive() -> None:
    d = datetime(2024, 1, 3, 9, 5)
    assert portable_strftime(d, "%0e") == "03"


def test_underscore_modifier_on_space_padded_directive_is_unchanged() -> None:
    """%e is already space-padded, so %_e must match the raw platform output."""
    d = datetime(2024, 1, 3, 9, 5)
    assert portable_strftime(d, "%_e") == d.strftime("%e")


def test_dash_modifier_mixed_with_plain_directives() -> None:
    d = datetime(2024, 1, 3, 9, 30)
    result = portable_strftime(d, "%H:%M on %-d %b %Y")
    assert result == "09:30 on 3 Jan 2024"


def test_underscore_modifier_space_pads() -> None:
    assert portable_strftime(date(2024, 1, 3), "%_d %b") == " 3 Jan"
    assert portable_strftime(date(2024, 1, 13), "%_d %b") == "13 Jan"


def test_literal_percent_escape_unaffected() -> None:
    d = date(2024, 1, 3)
    assert portable_strftime(d, "100%% on %-d %b") == "100% on 3 Jan"


def test_modifiers_are_resolved_before_strftime_sees_them() -> None:
    """Pins the substitution itself, not just its rendering on this host's libc."""
    out = _apply_padding_modifiers(date(2024, 1, 3), "%-d %b %Y")
    assert out == "3 %b %Y"
    assert not re.search(r"%[-_0]", out)


def test_escaped_percent_immediately_before_modifier_char_is_not_misread() -> None:
    """%%-d is a literal-percent escape followed by plain "-d" text, not %-d."""
    d = date(2024, 1, 3)
    assert portable_strftime(d, "%%-d") == "%-d"
    assert portable_strftime(d, "100%%-d %b") == "100%-d Jan"


def test_portable_strftime_survives_a_windows_like_strftime() -> None:
    """End-to-end: fails without the fix on any OS, not just Windows."""
    d = _WindowsLikeDate(2024, 1, 3)
    assert portable_strftime(d, "%-d %b %Y") == "3 Jan 2024"


def test_bare_iso_week_survives_windows_like_strftime() -> None:
    """%V used unmodified — the week-grain label-width path's "W%V" — must
    not reach the host libc at all, since Windows' CRT rejects it bare too.
    """
    d = _WindowsLikeDate(2024, 1, 3)
    assert portable_strftime(d, "W%V") == "W01"


def test_bare_crt_unsupported_directives_are_computed_in_python() -> None:
    d = _WindowsLikeDate(2024, 1, 3)
    assert portable_strftime(d, "%C") == "20"
    assert portable_strftime(d, "%e") == " 3"
    assert portable_strftime(d, "%G") == "2024"
    assert portable_strftime(d, "%j") == "003"
    assert portable_strftime(d, "%k") == " 0"  # date has no hour: defaults to 0
    assert portable_strftime(d, "%l") == "12"  # hour 0 in 12h clock is "12"
    assert portable_strftime(d, "%u") == "3"  # Wednesday, ISO weekday 1-7
    assert portable_strftime(d, "%V") == "01"
    assert portable_strftime(d, "%W") == "01"


def test_bare_crt_unsupported_directives_match_host_strftime() -> None:
    """Pins the computed values byte-identical to a real (non-Windows) libc.

    Uses a plain datetime, not `_WindowsLikeDate`, so the right-hand side can
    call raw `strftime` for comparison.
    """
    d = datetime(2024, 1, 3, 13, 5)
    for letter in "CeGjkluVW":
        assert portable_strftime(d, f"%{letter}") == d.strftime(f"%{letter}")


def test_iso_year_and_week_diverge_from_calendar_year_at_boundary() -> None:
    """2027-01-01 is a Friday whose ISO week belongs to 2026, week 53."""
    d = _WindowsLikeDate(2027, 1, 1)
    assert portable_strftime(d, "%G") == "2026"
    assert portable_strftime(d, "%V") == "53"
    assert d.year == 2027  # the calendar year, distinct from %G


def test_week_monday_first_has_a_real_week_zero() -> None:
    """%W (Monday-first) differs from %V (ISO) around the year boundary."""
    assert portable_strftime(_WindowsLikeDate(2023, 1, 1), "%W") == "00"  # Sun
    assert portable_strftime(_WindowsLikeDate(2023, 1, 2), "%W") == "01"  # Mon
    assert portable_strftime(_WindowsLikeDate(2023, 1, 9), "%W") == "02"  # Mon


def test_dash_modifier_on_computed_directive_strips_padding() -> None:
    """A padding modifier on one of the nine still resolves via the computed
    value rather than a host probe.
    """
    d = _WindowsLikeDate(2024, 1, 3)  # day-of-year "003"
    assert portable_strftime(d, "%-j") == "3"


@pytest.mark.windows
class TestBareCrtDirectivesAgainstRealDate:
    """The assertions above, against a plain ``date`` instead of the fake CRT.

    If one of the nine directives ever reached the host libc unresolved, the
    real Windows CRT raises ``ValueError`` while glibc silently supports it —
    so only this class can fail, and only on Windows.
    """

    def test_bare_crt_unsupported_directives_are_computed_in_python(self) -> None:
        d = date(2024, 1, 3)
        assert portable_strftime(d, "%C") == "20"
        assert portable_strftime(d, "%e") == " 3"
        assert portable_strftime(d, "%G") == "2024"
        assert portable_strftime(d, "%j") == "003"
        assert portable_strftime(d, "%k") == " 0"  # date has no hour: defaults to 0
        assert portable_strftime(d, "%l") == "12"  # hour 0 in 12h clock is "12"
        assert portable_strftime(d, "%u") == "3"  # Wednesday, ISO weekday 1-7
        assert portable_strftime(d, "%V") == "01"
        assert portable_strftime(d, "%W") == "01"

    def test_iso_year_and_week_diverge_from_calendar_year_at_boundary(self) -> None:
        """2027-01-01 is a Friday whose ISO week belongs to 2026, week 53."""
        d = date(2027, 1, 1)
        assert portable_strftime(d, "%G") == "2026"
        assert portable_strftime(d, "%V") == "53"

    def test_week_monday_first_has_a_real_week_zero(self) -> None:
        """%W (Monday-first) differs from %V (ISO) around the year boundary."""
        assert portable_strftime(date(2023, 1, 1), "%W") == "00"  # Sun
        assert portable_strftime(date(2023, 1, 2), "%W") == "01"  # Mon
        assert portable_strftime(date(2023, 1, 9), "%W") == "02"  # Mon


def test_modifier_on_composite_directive_passes_through_unchanged() -> None:
    """-/_/0 are only defined for single-field numeric directives.

    %T/%X/%D/%x/%r are composite (multiple padded sub-fields) and %Z is text
    — stripping zeros/whitespace from their combined output would mangle it
    (e.g. "00:00:00" -> ":00:00" for a naive %-T). These must reach strftime
    with the modifier still attached and render exactly as the raw platform
    strftime already does, unmodified by this substitution.
    """
    d = datetime(2024, 1, 3, 0, 0, 0)
    for fmt in ("%-T", "%_T", "%-X", "%-x", "%-D", "%-Z"):
        assert portable_strftime(d, fmt) == d.strftime(fmt)


def test_is_d3_si_spec_totality_over_compile_accepted_formats():
    """is_d3_si_spec answers, never raises, for every compile-accepted format.

    The `format:` surface accepts predefined names, style.formats alias names,
    strftime directives and literal d3 specs. build_resolved_axis runs this
    predicate once, up front, on whichever of those an axis authored -- a raise
    there would crash a valid board. The two compile-accepted inputs that are
    not d3 number grammar and would make `_d3_parse` raise are an unresolved
    alias name and a predefined *date* name; both must answer False.
    """
    from dbt_charts.core.text.format_d3 import is_d3_si_spec

    assert is_d3_si_spec("$,.3~s") is True  # a real SI d3 spec
    assert is_d3_si_spec("$,.2f") is False  # d3, but not SI-shaped
    assert is_d3_si_spec("date_short") is False  # predefined date name
    assert is_d3_si_spec("my_revenue_alias") is False  # unresolved alias name
    assert is_d3_si_spec("%b %Y") is False  # strftime directive
