"""Regression tests for error display cleanup.

Pins the new contract after the legacy formatter paths are removed:
1. Extra-forbidden pydantic errors populate range/path on Diagnostic rather
   than baking them into the message string.
2. CLI display shows relative path when file is under cwd.
3. No emoji or legacy prefix in error messages.
"""

from __future__ import annotations

import textwrap
from pathlib import Path, PureWindowsPath

import pytest

_MISSING_QUERY_YAML = textwrap.dedent(
    """\
    title: "Missing Query Reference"
    charts:
      sales_chart:
        type: bar
        query: missing_sales
        x: date
        y: revenue
    rows:
      - sales_chart
    """
)

# bogus_field sits at the indent that causes line lookup to resolve to the
# "style → charts → bogus_field" path.  The exact line is asserted below.
_EXTRA_FIELD_YAML = textwrap.dedent(
    """\
    title: "Extra Field Test"
    queries:
      sales:
        sql: "SELECT 1 AS date, 2 AS revenue"
        source: test
    charts:
      sales_chart:
        type: bar
        query: sales
        x: date
        y: revenue
    style:
      charts:
        bogus_field: red
    rows:
      - sales_chart
    """
)


class TestExtraForbiddenPopulatesDiagnosticFields:
    """extra_forbidden validation errors must populate range/path instead of baking them into message."""

    def test_line_populated_not_in_message(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_EXTRA_FIELD_YAML, file="charts/x.yml")

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-EXTRA-FIELD"
        # range must be populated with a positive line, not None
        assert err.range is not None, "range should be populated on Diagnostic"
        assert err.range.start_line > 0

    def test_field_path_populated_not_in_message(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_EXTRA_FIELD_YAML)

        assert not result.success
        err = result.errors[0]
        assert err.path is not None, "path should be populated"
        assert "bogus_field" in err.path

    def test_message_has_no_legacy_prefix(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_EXTRA_FIELD_YAML)

        assert not result.success
        err = result.errors[0]
        # Message must NOT contain the legacy "Error at line N:" or
        # "YAML parse error:" prefix — those are renderer concerns.
        assert not err.message.startswith("Error at line"), (
            f"message starts with legacy prefix: {err.message[:60]!r}"
        )
        assert not err.message.startswith("YAML parse error:"), (
            f"message starts with legacy prefix: {err.message[:60]!r}"
        )
        assert not err.message.startswith("Validation error:"), (
            f"message starts with legacy prefix: {err.message[:60]!r}"
        )

    def test_no_emoji_in_hint(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_EXTRA_FIELD_YAML)

        assert not result.success
        err = result.errors[0]
        if err.hint is not None:
            assert "💡" not in err.hint, f"hint contains emoji: {err.hint!r}"


_INVALID_INPUT_TYPE_YAML = textwrap.dedent(
    """\
    title: "Invalid Input Type"
    queries:
      q:
        sql: "SELECT 1 AS x"
        source: test
    variables:
      region:
        input: typo_select
        label: "Region"
    charts:
      c:
        type: kpi
        query: q
        value: x
    rows:
      - c
    """
)


class TestVariableInputTypeHint:
    """format_validation_errors_structured restores did-you-mean hint for invalid input types."""

    def test_invalid_variable_input_type_has_hint(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_INVALID_INPUT_TYPE_YAML)

        assert not result.success
        err = next(
            (e for e in result.errors if "input" in (e.path or "")),
            None,
        )
        assert err is not None, "Expected an error about the 'input' field"
        assert err.hint is not None, (
            f"Expected a hint but got None; message={err.message!r}"
        )
        # The hint should reference valid input types
        assert "select" in err.hint, f"Hint missing 'select'; got: {err.hint!r}"

    def test_invalid_variable_input_type_hint_suggests_closest(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_INVALID_INPUT_TYPE_YAML)

        assert not result.success
        err = next(
            (e for e in result.errors if "input" in (e.path or "")),
            None,
        )
        assert err is not None
        assert err.hint is not None
        # "typo_select" is close to "select" — did-you-mean should fire
        assert "Did you mean" in err.hint, f"Expected did-you-mean; got: {err.hint!r}"


class TestQueryErrorNoWrapAndStringifyPrefix:
    """QueryError must not prepend "Query execution failed:" — that wrap-and-
    stringify prefix duplicates the "(query: name)" suffix already carried by
    ExecutionError, and forced a matching regex-strip in the VS Code preview
    panel. The message is the raw text, unwrapped."""

    def test_message_has_no_prefix(self) -> None:
        from dbt_charts.core.diagnostics.execution import QueryError

        err = QueryError("boom", "q1")

        assert str(err) == "boom (query: q1)", f"Got: {str(err)!r}"
        assert "Query execution failed" not in str(err)

    def test_init_has_no_prefix_message_param(self) -> None:
        import inspect

        from dbt_charts.core.diagnostics.execution import QueryError

        assert "prefix_message" not in inspect.signature(QueryError.__init__).parameters


class TestUnparseableSqlErrorUsesRegisteredTemplate:
    """UnparseableSqlError's message must be the registered ERR-UNPARSEABLE-SQL
    template, not a hand-rolled string that drifts from the generated docs."""

    def test_message_matches_registered_template(self) -> None:
        from dbt_charts.core.diagnostics.codes_execute import ERR_UNPARSEABLE_SQL
        from dbt_charts.core.diagnostics.execution import UnparseableSqlError

        err = UnparseableSqlError("boom")

        assert err.message == ERR_UNPARSEABLE_SQL.message_template.format(cause="boom")
        assert "could not be validated statically" not in err.message


class TestCliRelativePath:
    """CLI panel shows relative path when file is under cwd."""

    def test_display_path_relative_to_cwd(self, tmp_path: Path) -> None:
        from dbt_charts.cli._error_format import _display_path

        abs_file = str(tmp_path / "charts" / "missing-query.yml")
        result = _display_path(abs_file, None, cwd=tmp_path)

        assert result == "charts/missing-query.yml", f"Got: {result!r}"
        assert str(tmp_path) not in result, f"Absolute path leaked: {result!r}"

    def test_display_path_with_line(self, tmp_path: Path) -> None:
        from dbt_charts.cli._error_format import _display_path

        abs_file = str(tmp_path / "charts" / "bad.yml")
        result = _display_path(abs_file, 14, cwd=tmp_path)

        assert result == "charts/bad.yml:14", f"Got: {result!r}"

    def test_display_path_outside_cwd_stays_absolute(self, tmp_path: Path) -> None:
        from dbt_charts.cli._error_format import _display_path

        # file is under tmp_path/a; cwd is tmp_path/b — disjoint siblings
        abs_file = str(tmp_path / "a" / "bad.yml")
        unrelated_cwd = tmp_path / "b"
        result = _display_path(abs_file, None, cwd=unrelated_cwd)
        assert result == abs_file, f"Expected absolute path, got: {result!r}"

    def test_display_path_stays_posix_on_windows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Host-independent regression: _display_path must call
        posix_relpath, not str(p.relative_to(base)) — the latter emits
        OS-native separators (WindowsPath.__str__ rejoins with backslash),
        rendering CLI error/warning locations as `boards\\bad.yml:14` on
        Windows. Monkeypatch the `Path` name bound in cli/_error_format.py
        to PureWindowsPath — the real, unpatched host it runs on doesn't
        matter — so the bug reproduces on any host, including POSIX CI,
        without needing a real Windows machine.
        """
        import dbt_charts.cli._error_format as error_format

        monkeypatch.setattr(error_format, "Path", PureWindowsPath)

        result = error_format._display_path(
            r"C:\proj\boards\bad.yml", 14, cwd=PureWindowsPath(r"C:\proj")
        )

        assert result == "boards/bad.yml:14", f"Got: {result!r}"
