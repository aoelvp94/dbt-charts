"""Tests for temporal value formatting in table cells.

Covers the render-time contract for Python date/datetime objects and ISO
timestamp strings arriving from DuckDB fetchall() — values that previously
fell through to str(value) and produced machine-readable output instead of
human-readable dates.

Timezone policy (documented here per acceptance criteria):
  - Python datetime.date and naive datetime.datetime: treated as calendar-local
    (no TZ conversion). The date component is taken as-is.
  - ISO strings "YYYY-MM-DD" and "YYYY-MM-DDTHH:MM:SS": parsed in UTC
    so the display is identical under any runtime TZ.
  - timezone-aware datetime objects: the date component is extracted after
    UTC conversion to match ISO string behavior.
"""

import datetime

import pytest

from dbt_charts.core.render.chart.table_support import (
    format_table_cell_value,
    is_temporal_value,
)
from dbt_charts.core.utils import is_date_like

# The default format that must be present in stark.yaml as date_short.
_DATE_SHORT_FORMAT = "%-d %b %Y"


class TestIsTemporalValue:
    """Unit tests for the is_temporal_value() predicate."""

    def test_date_object(self) -> None:
        assert is_temporal_value(datetime.date(2024, 1, 15)) is True

    def test_datetime_object(self) -> None:
        assert is_temporal_value(datetime.datetime(2024, 1, 15, 13, 30, 0)) is True

    def test_datetime_aware_object(self) -> None:
        aware = datetime.datetime(2024, 1, 15, 13, 30, 0, tzinfo=datetime.timezone.utc)
        assert is_temporal_value(aware) is True

    def test_iso_date_string(self) -> None:
        assert is_temporal_value("2024-01-15") is True

    def test_iso_timestamp_string(self) -> None:
        assert is_temporal_value("2024-01-15T13:30:00") is True

    def test_iso_timestamp_with_microseconds(self) -> None:
        assert is_temporal_value("2024-01-15T13:30:00.123456") is True

    def test_integer_is_not_temporal(self) -> None:
        assert is_temporal_value(42) is False

    def test_float_is_not_temporal(self) -> None:
        assert is_temporal_value(3.14) is False

    def test_none_is_not_temporal(self) -> None:
        assert is_temporal_value(None) is False

    def test_plain_string_is_not_temporal(self) -> None:
        assert is_temporal_value("hello") is False

    def test_bool_is_not_temporal(self) -> None:
        assert is_temporal_value(True) is False

    def test_year_string_not_temporal(self) -> None:
        # "2024" as a bare year is not an ISO temporal value —
        # it's numeric (matched by the numeric cell path).
        assert is_temporal_value("2024") is False


class TestFormatTableCellValueTemporal:
    """format_table_cell_value applies date_short when no column format is set."""

    def test_date_object_default_format(self) -> None:
        # date(2024, 1, 15) → "15 Jan 2024" (%-d %b %Y)
        result = format_table_cell_value(
            datetime.date(2024, 1, 15), None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "15 Jan 2024"

    def test_datetime_object_default_format(self) -> None:
        # datetime without custom spec → date component only ("date_short")
        result = format_table_cell_value(
            datetime.datetime(2024, 1, 15, 13, 30, 0),
            None,
            {"date_short": _DATE_SHORT_FORMAT},
        )
        assert result == "15 Jan 2024"

    def test_iso_date_string_default_format(self) -> None:
        result = format_table_cell_value(
            "2024-01-15", None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "15 Jan 2024"

    def test_iso_timestamp_string_default_format(self) -> None:
        result = format_table_cell_value(
            "2024-01-15T13:30:00", None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "15 Jan 2024"

    def test_iso_timestamp_microseconds(self) -> None:
        result = format_table_cell_value(
            "2024-01-15T13:30:00.123456",
            None,
            {"date_short": _DATE_SHORT_FORMAT},
        )
        assert result == "15 Jan 2024"

    def test_explicit_d3_time_format(self) -> None:
        # Author sets format: "%b %d, %Y" in style.columns
        result = format_table_cell_value(
            datetime.date(2024, 1, 15),
            "%b %d, %Y",
            {"date_short": _DATE_SHORT_FORMAT},
        )
        assert result == "Jan 15, 2024"

    def test_explicit_format_on_iso_string(self) -> None:
        result = format_table_cell_value(
            "2024-01-15",
            "%Y-%m-%d",
            {"date_short": _DATE_SHORT_FORMAT},
        )
        assert result == "2024-01-15"

    def test_invalid_temporal_format_spec_raises(self) -> None:
        # %Q is not a valid strftime directive — must raise, not silently pass through.
        with pytest.raises(ValueError, match="%Q"):
            format_table_cell_value(
                datetime.date(2024, 1, 15),
                "%Q",
                {"date_short": _DATE_SHORT_FORMAT},
            )

    def test_non_temporal_value_unchanged_str(self) -> None:
        # Regular string passes through unchanged
        result = format_table_cell_value(
            "hello", None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "hello"

    def test_numeric_value_not_treated_as_temporal(self) -> None:
        # Integer: not temporal — formats via the theme's number spec
        # (SI here), not the date path.
        result = format_table_cell_value(
            1234, None, {"date_short": _DATE_SHORT_FORMAT, "number": ".3~s"}
        )
        assert result == "1.23 K"

    def test_single_digit_day_no_leading_zero(self) -> None:
        # %-d suppresses leading zero: "5 Jan 2024" not "05 Jan 2024"
        result = format_table_cell_value(
            datetime.date(2024, 1, 5), None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "5 Jan 2024"

    def test_timezone_aware_datetime(self) -> None:
        # Aware datetime that crosses UTC day boundary: PST 23:00 Jan 15 = UTC Jan 16.
        # This exercises the astimezone(UTC).date() path — UTC midnight can't catch it.
        pst = datetime.timezone(datetime.timedelta(hours=-8))
        aware = datetime.datetime(2024, 1, 15, 23, 0, 0, tzinfo=pst)
        result = format_table_cell_value(
            aware, None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "16 Jan 2024"

    def test_timezone_aware_iso_string_crosses_day_boundary(self) -> None:
        # ISO string with TZ offset: 23:00 PST on Jan 15 = 07:00 UTC on Jan 16.
        # Must render as "16 Jan 2024", not "15 Jan 2024" (which the old truncating
        # parser produced by dropping the -08:00 suffix).
        result = format_table_cell_value(
            "2024-01-15T23:00:00-08:00",
            None,
            {"date_short": _DATE_SHORT_FORMAT},
        )
        assert result == "16 Jan 2024"

    def test_timezone_aware_iso_string_z_suffix(self) -> None:
        # ISO string with Z suffix must be treated as UTC.
        result = format_table_cell_value(
            "2024-01-15T13:00:00Z",
            None,
            {"date_short": _DATE_SHORT_FORMAT},
        )
        assert result == "15 Jan 2024"

    def test_non_temporal_format_on_temporal_column_raises(self) -> None:
        # A d3/numeric format spec applied to a date must raise — not silently
        # fall back to str(value). "validate and error fast" non-negotiable.
        with pytest.raises(ValueError, match="non-temporal"):
            format_table_cell_value(
                datetime.date(2024, 1, 15),
                "compact",
                {"date_short": _DATE_SHORT_FORMAT},
            )

    def test_date_short_works_without_formats_dict(self) -> None:
        # "date_short" is predefined — no formats dict needed.
        # Whether formats={} or formats=None, the predefined spec is used.
        result_empty = format_table_cell_value(datetime.date(2024, 1, 15), None, {})
        result_none = format_table_cell_value(datetime.date(2024, 1, 15), None, None)
        assert result_empty == "15 Jan 2024"
        assert result_none == "15 Jan 2024"

    def test_postgres_space_separated_timestamp_detected(self) -> None:
        # DuckDB sometimes returns "YYYY-MM-DD HH:MM:SS" (space separator, no T)
        # when the result is fetched as a string. is_temporal_value must detect it.
        assert is_temporal_value("2024-01-15 13:30:00") is True

    def test_postgres_space_timestamp_formats_correctly(self) -> None:
        result = format_table_cell_value(
            "2024-01-15 13:30:00", None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "15 Jan 2024"

    def test_invalid_date_string_rejected(self) -> None:
        # "2024-13-99" matches the ISO regex shape but is not a real date.
        # is_temporal_value must reject it after post-regex validation.
        assert is_temporal_value("2024-13-99") is False

    def test_invalid_date_not_formatted(self) -> None:
        # An invalid date string should fall through to str() not raise.
        result = format_table_cell_value(
            "2024-13-99", None, {"date_short": _DATE_SHORT_FORMAT}
        )
        assert result == "2024-13-99"


class TestIsDateLikeWithTemporalObjects:
    """is_date_like must accept Python date/datetime so layout decisions are correct."""

    def test_date_object_is_date_like(self) -> None:
        # After this PR, DuckDB returns datetime.date objects directly.
        # is_date_like must return True so right-align and no-wrap apply.
        assert is_date_like(datetime.date(2024, 1, 15)) is True

    def test_datetime_object_is_date_like(self) -> None:
        assert is_date_like(datetime.datetime(2024, 1, 15, 13, 30, 0)) is True

    def test_integer_not_date_like(self) -> None:
        assert is_date_like(42) is False

    def test_string_date_still_works(self) -> None:
        assert is_date_like("15 Jan 2024") is True

    def test_parity_with_inspect_strftime_output(self) -> None:
        """Regression: render output matches the old inspect strftime literal."""
        d = datetime.date(2024, 5, 19)
        result = format_table_cell_value(d, None, {"date_short": _DATE_SHORT_FORMAT})
        assert result == "19 May 2024"


class TestFormatTableCellValueStringWithFormatConfig:
    """CSV adapters deliver every value as a string; a format_config on the column
    must still produce formatted output (e.g. currency) rather than the raw string."""

    def test_string_numeric_with_currency_format(self) -> None:
        """String '1234.5' + currency format_config → formatted currency string."""
        result = format_table_cell_value("1234.5", "$,.2f")
        assert result == "$1,234.50"

    def test_string_integer_with_comma_format(self) -> None:
        """String '42000' + comma format_config → '42,000'."""
        result = format_table_cell_value("42000", ",")
        assert result == "42,000"

    def test_non_numeric_string_with_format_config_falls_through(self) -> None:
        """Non-numeric string 'N/A' with format_config → raw string (no crash)."""
        result = format_table_cell_value("N/A", "$,.2f")
        assert result == "N/A"
