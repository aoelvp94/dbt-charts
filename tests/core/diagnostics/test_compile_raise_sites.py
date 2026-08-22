"""Regression tests for compile-domain raise-site migrations.

Each test triggers a specific migrated raise site and asserts the error
carries a typed compile- or render-domain code rather than the
ERR-INTERNAL fallback.

Five sites covered:
1. validate/dispatch.py: chart references unknown query → ERR-UNKNOWN-QUERY
2. parser.py: Pydantic extra_forbidden field → ERR-EXTRA-FIELD
3. validation.py: bar chart with duplicate x-axis rows → ERR-BAR-DUPLICATE-ROWS
4. normalize/queries.py: SQL query missing source → ERR-SOURCE-REQUIRED
5. normalize/queries.py: inline dict on query source → ERR-SOURCE-INLINE-FORBIDDEN
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject

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


class TestUnknownQueryCarriesCode:
    """chart refs unknown query → ValidationError with ERR-UNKNOWN-QUERY."""

    def test_unknown_query_ref_carries_typed_code(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_MISSING_QUERY_YAML)

        assert not result.success
        assert len(result.errors) >= 1
        err = result.errors[0]
        # CompileResult.errors is now list[Diagnostic]; err.code is a str
        assert err.code == "ERR-UNKNOWN-QUERY", (
            f"Expected ERR-UNKNOWN-QUERY but got {err.code!r}"
        )


class TestExtraFieldCarriesCode:
    """Pydantic extra_forbidden field in style.charts → ParseError with ERR-EXTRA-FIELD."""

    def test_extra_field_carries_typed_code(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_EXTRA_FIELD_YAML)

        assert not result.success
        assert len(result.errors) >= 1
        err = result.errors[0]
        # CompileResult.errors is now list[Diagnostic]; err.code is a str
        assert err.code == "ERR-EXTRA-FIELD", (
            f"Expected ERR-EXTRA-FIELD but got {err.code!r}"
        )


class TestBarDuplicateRowsCarriesCode:
    """Bar chart with duplicate x-axis rows → ChartDataError with ERR-BAR-DUPLICATE-ROWS."""

    def test_bar_duplicate_rows_carries_typed_code(self) -> None:
        from dbt_charts.core.compile.config import get_theme_style
        from dbt_charts.core.compile.models.chart.normalized import BarChart
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.compile.resolve import resolve
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.diagnostics.codes_render import ERR_BAR_DUPLICATE_ROWS
        from dbt_charts.core.render.chart.validation import validate_preaggregated_data

        data = [
            {"product": "Widget A", "revenue": 100},
            {"product": "Widget A", "revenue": 200},
        ]
        chart_normalized = BarChart(
            id="rev",
            type="bar",
            x="product",
            y="revenue",
            query=SqlQuery(sql="SELECT 1", source="t"),
            query_name="q",
        )
        _bs = resolve_chart_style_context(get_theme_style())
        resolved = resolve(chart_normalized, data[:1], chart_style_context=_bs)

        with pytest.raises(ChartDataError) as exc_info:
            validate_preaggregated_data(resolved, data)

        assert exc_info.value.code is ERR_BAR_DUPLICATE_ROWS, (
            f"Expected ERR-BAR-DUPLICATE-ROWS but got {exc_info.value.code!r}"
        )

    @pytest.mark.parametrize("color", [None, "sale_source"])
    def test_bar_duplicate_rows_temporal_x_carries_typed_code(
        self, color: str | None
    ) -> None:
        """Bar chart with a temporal x-axis and a duplicate plot key raises
        ERR-BAR-DUPLICATE-ROWS instead of silently dropping a row.

        x is a real datetime column (e.g. date_trunc(...)), not a nominal/
        ordinal string — infer_vega_type_from_data classifies it "temporal",
        and _plot_key_fields's bar branch gates on that the same as nominal/
        ordinal. Parametrized over color=None (bare duplicate x) and
        color="sale_source" (the reported shape: two rows share
        (month, sale_source) but differ on an unencoded dimension like
        property_type).
        """
        import datetime as dt

        from dbt_charts.core.compile.config import get_theme_style
        from dbt_charts.core.compile.models.chart.normalized import BarChart
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.compile.resolve import resolve
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.diagnostics.codes_render import ERR_BAR_DUPLICATE_ROWS
        from dbt_charts.core.render.chart.validation import validate_preaggregated_data

        if color is None:
            data = [
                {"month": dt.datetime(2026, 7, 1), "revenue": 100},
                {"month": dt.datetime(2026, 7, 1), "revenue": 200},
            ]
        else:
            data = [
                {
                    "month": dt.datetime(2026, 7, 1),
                    "sale_source": "Both Sources",
                    "revenue": 12,
                },
                {
                    "month": dt.datetime(2026, 7, 1),
                    "sale_source": "Both Sources",
                    "revenue": 2,
                },
            ]
        chart_normalized = BarChart(
            id="rev",
            type="bar",
            x="month",
            y="revenue",
            color=color,
            query=SqlQuery(sql="SELECT 1", source="t"),
            query_name="q",
        )
        _bs = resolve_chart_style_context(get_theme_style())
        resolved = resolve(chart_normalized, data[:1], chart_style_context=_bs)

        with pytest.raises(ChartDataError) as exc_info:
            validate_preaggregated_data(resolved, data)

        assert exc_info.value.code is ERR_BAR_DUPLICATE_ROWS, (
            f"Expected ERR-BAR-DUPLICATE-ROWS but got {exc_info.value.code!r}"
        )

    def test_bar_non_duplicate_temporal_x_does_not_raise(self) -> None:
        """One row per (month, color) on a temporal x must not false-positive."""
        import datetime as dt

        from dbt_charts.core.compile.config import get_theme_style
        from dbt_charts.core.compile.models.chart.normalized import BarChart
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.compile.resolve import resolve
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )
        from dbt_charts.core.render.chart.validation import validate_preaggregated_data

        data = [
            {
                "month": dt.datetime(2026, 6, 1),
                "sale_source": "Both Sources",
                "revenue": 12,
            },
            {
                "month": dt.datetime(2026, 7, 1),
                "sale_source": "Both Sources",
                "revenue": 2,
            },
        ]
        chart_normalized = BarChart(
            id="rev",
            type="bar",
            x="month",
            y="revenue",
            color="sale_source",
            query=SqlQuery(sql="SELECT 1", source="t"),
            query_name="q",
        )
        _bs = resolve_chart_style_context(get_theme_style())
        resolved = resolve(chart_normalized, data[:1], chart_style_context=_bs)

        validate_preaggregated_data(resolved, data)


_SQL_NO_SOURCE_YAML = textwrap.dedent(
    """\
    title: "No Source Query"
    queries:
      daily:
        type: sql
        sql: "SELECT 1 AS n"
    charts:
      daily_chart:
        type: bar
        query: daily
        x: n
        y: n
    rows:
      - daily_chart
    """
)


class TestMissingSourceCarriesCode:
    """SQL query without source → CompilationError with ERR-SOURCE-REQUIRED."""

    def test_missing_source_carries_typed_code(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_SQL_NO_SOURCE_YAML)

        assert not result.success
        assert len(result.errors) >= 1
        err = result.errors[0]
        assert err.code == "ERR-SOURCE-REQUIRED", (
            f"Expected ERR-SOURCE-REQUIRED but got {err.code!r}"
        )

    def test_missing_source_message_mentions_source_field(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_SQL_NO_SOURCE_YAML)

        assert not result.success
        err = result.errors[0]
        assert "source:" in err.message, (
            f"Expected message to mention 'source:' but got: {err.message!r}"
        )


_INLINE_SOURCE_DICT_YAML = textwrap.dedent(
    """\
    queries:
      q:
        sql: SELECT 1
        source:
          type: duckdb
          path: ":memory:"
    charts:
      c:
        query: q
        type: kpi
        value: col
    rows:
      - c
    """
)


class TestInlineSourceForbiddenCarriesCode:
    """SQL query with inline dict source → CompilationError with ERR-SOURCE-INLINE-FORBIDDEN."""

    def test_inline_source_dict_on_query_raises_forbidden_code(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_INLINE_SOURCE_DICT_YAML)

        assert result.errors
        err = result.errors[0]
        assert err.code == "ERR-SOURCE-INLINE-FORBIDDEN", (
            f"Expected ERR-SOURCE-INLINE-FORBIDDEN but got {err.code!r}"
        )


class TestAgentApiValidateCarriesDomainCode:
    """agent_api.validate() on missing-query board returns domain-specific code."""

    def test_validate_missing_query_carries_domain_code(
        self, tmp_path: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.agent_api.validate import validate
        from dbt_charts.core.diagnostics.registry import REGISTRY

        board_file = tmp_path / "test.yml"
        board_file.write_text(_MISSING_QUERY_YAML)

        result = validate(board_file, project=local_project(tmp_path))

        assert result.success is False
        assert len(result.errors) >= 1
        err = result.errors[0]
        assert err.code != "ERR-INTERNAL", f"Expected domain code, got {err.code!r}"
        # The domain segment is dropped from the code string; resolve the
        # domain from the registry instead of a code-string prefix.
        domain = REGISTRY.get(err.code).domain
        assert domain == "compile", (
            f"Expected domain='compile', got {domain!r} (code={err.code!r})"
        )


_MISSING_QUERY_REF_YAML = textwrap.dedent(
    """\
    title: "Missing Query Reference"
    charts:
      sales_chart:
        type: bar
        query: shared.queries.missing_sales
        x: date
        y: revenue
    rows:
      - sales_chart
    """
)

_LAYER_MISSING_QUERY_YAML = textwrap.dedent(
    """\
    title: "Missing Layer Query Reference"
    queries:
      q:
        sql: "SELECT 1 AS date, 2 AS revenue"
        source: test
    charts:
      main:
        type: bar
        query: q
        x: date
        y: revenue
        layers:
          - type: line
            query: missing_layer_query
            y: target
    rows:
      - main
    """
)


class TestReferenceErrorCarriesLine:
    """ReferenceError.to_diagnostic() carries resolved lines for chart query refs."""

    def test_missing_query_ref_resolves_line(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        # SourceRange requires a file, so pass one through — without it the
        # resolved line has nowhere to attach (see compile()'s `file` arg doc).
        result = compile(_MISSING_QUERY_REF_YAML, file="charts/x.yml")

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE"
        assert err.range is not None
        assert err.range.start_line == 5, (
            f"Expected line 5, got {err.range.start_line!r}"
        )
        assert err.path == "charts.sales_chart.query"

    def test_missing_layer_query_ref_resolves_to_chart_level_line(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_LAYER_MISSING_QUERY_YAML, file="charts/x.yml")

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE"
        assert err.range is not None
        assert err.path == "charts.main.layers"

    def test_nested_board_chart_query_ref_has_no_line(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        yaml_content = textwrap.dedent(
            """\
            title: "Parent"
            rows:
              - title: "FirstNested"
                charts:
                  first_chart:
                    type: bar
                    query: q1
                    x: date
                    y: revenue
                queries:
                  q1:
                    sql: "SELECT 1 AS date, 2 AS revenue"
                    source: test
                rows:
                  - first_chart
              - title: "SecondNested"
                charts:
                  second_chart:
                    type: bar
                    query: shared.queries.missing
                    x: date
                    y: revenue
                rows:
                  - second_chart
            """
        )

        result = compile(yaml_content)

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE"
        assert err.range is None
        assert err.path is None

    def test_missing_layout_item_ref_in_a_nested_board_resolves_its_path(
        self,
    ) -> None:
        """A nested board's bad reference resolves to its own authored path.

        `range` stays None here only because this compile passes no `file=`:
        with no file identity there is no source map to resolve against.
        """
        from dbt_charts.core.compile.compiler import compile

        yaml_content = textwrap.dedent(
            """\
            title: "Parent"
            rows:
              - title: "Nested"
                charts:
                  existing:
                    type: kpi
                    query: q
                    value: v
                queries:
                  q:
                    sql: "SELECT 1 AS v"
                    source: test
                rows:
                  - existing
                  - nonexistent
            """
        )

        result = compile(yaml_content)

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNRESOLVED-REFERENCE"
        assert err.path == "rows.0.rows.1"
        assert err.range is None


_BARE_NAME_MISSING_QUERY_YAML = textwrap.dedent(
    """\
    title: "Bare Name Missing Query"
    charts:
      sales_chart:
        type: bar
        query: revenue_typo
        x: date
        y: revenue
    rows:
      - sales_chart
    """
)


class TestUnknownQueryValidationErrorCarriesLine:
    """Bare-name unknown query validation errors resolve to the query field."""

    def test_bare_name_unknown_query_resolves_line(self) -> None:
        from dbt_charts.core.compile.compiler import compile

        result = compile(_BARE_NAME_MISSING_QUERY_YAML, file="charts/x.yml")

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNKNOWN-QUERY"
        assert err.range is not None
        assert err.range.start_line == 5, (
            f"Expected line 5, got {err.range.start_line!r}"
        )
        assert err.path == "charts.sales_chart.query"

    def test_inline_layout_chart_unknown_query_resolves_to_its_query_field(
        self,
    ) -> None:
        """An inline layout chart's bad `query:` resolves to the same precision
        as the named-chart site above (`charts.<id>.query`), and for the same
        reason: the offending value is the `query:` scalar, not the whole item.

        `rows.0.query` is not a fabricated position: it is a real key in the
        source map, resolving to the line the bad reference is authored on.
        """
        from dbt_charts.core.compile.compiler import compile

        yaml_content = textwrap.dedent(
            """\
            title: "Inline Layout Chart"
            rows:
              - type: bar
                query: revenue_typo
                x: date
                y: revenue
            """
        )

        result = compile(yaml_content, file="charts/x.yml")

        assert not result.success
        err = result.errors[0]
        assert err.code == "ERR-UNKNOWN-QUERY"
        assert err.path == "rows.0.query"
        assert err.range is not None
        assert err.range.start_line == 4

    def test_unknown_query_carries_no_range_without_a_file(self) -> None:
        """No file identity means no source map, so nothing resolves — the
        honest outcome, not a line-1 fallback."""
        from dbt_charts.core.compile.compiler import compile

        yaml_content = textwrap.dedent(
            """\
            title: "Inline Layout Chart"
            rows:
              - type: bar
                query: revenue_typo
                x: date
                y: revenue
            """
        )

        result = compile(yaml_content)

        assert not result.success
        assert result.errors[0].range is None
