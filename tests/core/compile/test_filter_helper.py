"""Tests for the filter() Jinja macro helper — the parameterized path
(the make_filter_helper closure in parameterized.py, over a collector emitter).

The legacy unparameterized _filter_helper from jinja.py raises CompilationError
on any call — it uses string interpolation and is no longer supported.
"""

import pytest

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.template.jinja import (
    _filter_date_range_helper,
    _filter_helper,
)
from dbt_charts.core.compile.template.parameterized import (
    _NullValue,
    _ParameterCollector,
    make_filter_helper,
)
from dbt_charts.core.dialects.postgres import PostgresDialect

# ---------------------------------------------------------------------------
# Helpers for the parameterized path
# ---------------------------------------------------------------------------


def _collector() -> _ParameterCollector:
    return _ParameterCollector(variables={}, dialect=PostgresDialect())


def _make_helper(collector: _ParameterCollector | None = None):
    if collector is None:
        collector = _collector()
    return make_filter_helper(collector.add_param)


# ===========================================================================
# _filter_helper (jinja.py) — legacy path now raises
# ===========================================================================


class TestFilterHelperJinja:
    def test_raises_compilation_error(self):
        """The legacy string-interpolation filter() helper must raise on any call."""
        with pytest.raises(CompilationError, match="filter.*no longer supported"):
            _filter_helper("col", "value")

    def test_date_range_raises_compilation_error(self):
        """The legacy string-interpolation filter_date_range() must raise on any call."""
        with pytest.raises(
            CompilationError, match="filter_date_range.*no longer supported"
        ):
            _filter_date_range_helper("col", ["2025-01-01", "2025-03-31"])


# ===========================================================================
# parameterized filter helper (parameterized.py)
# ===========================================================================


class TestFilterHelperParameterized:
    # --- Backwards-compat ---

    def test_none_gives_allow_by_default(self):
        fn = _make_helper()
        assert fn("col", None) == "1=1"

    def test_empty_string_gives_allow_by_default(self):
        fn = _make_helper()
        assert fn("col", "") == "1=1"

    def test_empty_list_gives_allow_by_default(self):
        fn = _make_helper()
        assert fn("col", []) == "1=1"

    def test_null_value_sentinel_gives_allow_by_default(self):
        fn = _make_helper()
        assert fn("col", _NullValue()) == "1=1"

    def test_string_value_returns_predicate(self):
        fn = _make_helper()
        result = fn("col", "x")
        assert result == "col = $1"

    def test_falsy_integer_zero_passes_through(self):
        fn = _make_helper()
        result = fn("col", 0)
        assert result == "col = $1"

    # --- none='deny' new behaviour ---

    def test_none_with_deny_gives_deny(self):
        fn = _make_helper()
        assert fn("col", None, none="deny") == "1=0"

    def test_empty_string_with_deny_gives_deny(self):
        fn = _make_helper()
        assert fn("col", "", none="deny") == "1=0"

    def test_empty_list_with_deny_gives_deny(self):
        fn = _make_helper()
        assert fn("col", [], none="deny") == "1=0"

    def test_null_value_sentinel_with_deny_gives_deny(self):
        fn = _make_helper()
        assert fn("col", _NullValue(), none="deny") == "1=0"

    def test_string_value_with_deny_returns_predicate(self):
        fn = _make_helper()
        result = fn("col", "x", none="deny")
        assert result == "col = $1"

    def test_falsy_integer_zero_with_deny_passes_through(self):
        fn = _make_helper()
        result = fn("col", 0, none="deny")
        assert result == "col = $1"

    def test_explicit_allow_same_as_default(self):
        fn = _make_helper()
        assert fn("col", None, none="allow") == "1=1"

    # --- Operator + deny combo ---

    def test_operator_and_deny_on_null_sentinel_gives_deny(self):
        fn = _make_helper()
        assert fn("col", _NullValue(), "!=", none="deny") == "1=0"

    def test_operator_and_deny_on_value_returns_predicate(self):
        fn = _make_helper()
        result = fn("col", "x", "!=", none="deny")
        assert result == "col != $1"

    # --- Kwarg validation ---

    def test_bogus_none_kwarg_raises_value_error(self):
        fn = _make_helper()
        with pytest.raises(ValueError, match="none"):
            fn("col", None, none="bogus")

    # --- _validate_operator non-string regression ---

    def test_list_operator_raises_value_error_not_attribute_error(self):
        """A non-string operator must raise ValueError naming the allowlist, not AttributeError."""
        fn = _make_helper()
        with pytest.raises(ValueError, match="operator"):
            fn("col", "value", ["="])

    def test_int_operator_raises_value_error_not_attribute_error(self):
        """An integer operator must raise ValueError naming the allowlist, not AttributeError."""
        fn = _make_helper()
        with pytest.raises(ValueError, match="operator"):
            fn("col", "value", 1)
