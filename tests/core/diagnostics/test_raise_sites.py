"""Regression tests for raise-site migrations in the render domain.

Each test triggers a specific migrated raise site and asserts `e.code is
ERR_*`. Without these, a future regression that drops `from_code` and
falls back to a string-message raise would still pass behavior tests but
silently stamp ERR-INTERNAL.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.compiler import compile
from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.chart.normalized import KpiChart
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.render.errors import (
    FormatError,
    RenderError,
)

_BOARD_STYLE = resolve_chart_style_context(get_theme_style())


class TestRenderNoLayoutCarriesCode:
    def test_render_no_layout_carries_code(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from dbt_charts.core.diagnostics.codes_render import ERR_NO_LAYOUT
        from dbt_charts.core.render.renderer import render

        board_yaml = """\
charts:
  rev:
    query:
      sql: "SELECT 1 AS n"
      source: test
    type: kpi
    value: n
rows: []
"""
        result = compile(board_yaml)
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )

        with pytest.raises(RenderError) as exc_info:
            render(result.board, executor)

        assert exc_info.value.code is ERR_NO_LAYOUT


class TestRenderFormatUnsupportedCarriesCode:
    def test_render_unknown_format_carries_code(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Boards with text-only layouts skip query execution, so we hit the
        format dispatch with a clean executor.
        """
        from dbt_charts.core.diagnostics.codes_render import ERR_FORMAT_UNSUPPORTED
        from dbt_charts.core.render.renderer import render

        board_yaml = """\
text: "static text only"
"""
        result = compile(board_yaml)
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )

        with pytest.raises(FormatError) as exc_info:
            render(result.board, executor, format="not-a-real-format")

        assert exc_info.value.code is ERR_FORMAT_UNSUPPORTED


class TestRenderKpiMultirowCarriesCode:
    def test_kpi_multirow_carries_code(self) -> None:
        from dbt_charts.core.compile.models.query.normalized import SqlQuery
        from dbt_charts.core.diagnostics.codes_render import ERR_KPI_MULTIROW
        from dbt_charts.core.render.chart.kpi import render_kpi_svg

        chart = KpiChart(
            id="rev",
            query=SqlQuery(sql="SELECT 1", source="test"),
            query_name="q",
            type="kpi",
            value="n",
        )
        data = [{"n": 1}, {"n": 2}]
        resolved = resolve(chart, data, chart_style_context=_BOARD_STYLE)

        with pytest.raises(ChartDataError) as exc_info:
            render_kpi_svg(
                resolved,
                data,
                width=200,
                height=140,
                board_style=resolve_style(get_theme_style()),
            )

        assert exc_info.value.code is ERR_KPI_MULTIROW


class TestRenderMapLookupKeyMismatchCarriesCode:
    def test_world_map_alpha_lookup_carries_code(self, make_chart) -> None:
        from dbt_charts.core.diagnostics.codes_render import (
            ERR_MAP_LOOKUP_KEY_MISMATCH,
        )
        from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

        chart = make_chart(
            "map",
            geo={"source": "world-countries"},
            lookup="code",
            value="launches",
        )
        data = [{"code": "USA", "launches": 100}]
        resolve(chart, data, chart_style_context=_BOARD_STYLE)

        with pytest.raises(ChartDataError) as exc_info:
            generate_vega_lite_spec(chart, data)

        assert exc_info.value.code is ERR_MAP_LOOKUP_KEY_MISMATCH


class TestRenderPublicEntryPointPreservesPerSiteCodes:
    """The broad except in renderer.render() must let DbtChartsError through
    unwrapped, so per-site ERR-* codes raised inside render_board_svg
    reach the caller — not re-stamped to ERR_INTERNAL.

    Chart-level ChartDataErrors (KPI multirow, column missing) get caught at
    the chart-rendering layer and rendered as inline error tiles, so they
    never bubble to render(). The contract still matters for any other
    DbtChartsError subclass that escapes the inline-tile handler — we simulate
    one with a mock to lock in the narrow-`except` invariant.
    """

    def test_dataface_error_via_public_render_preserves_code(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        from unittest.mock import patch

        from dbt_charts.core.diagnostics.chart_data import ChartDataError
        from dbt_charts.core.diagnostics.codes_render import ERR_KPI_MULTIROW
        from dbt_charts.core.diagnostics.codes_unknown import ERR_INTERNAL
        from dbt_charts.core.render.renderer import render

        board_yaml = """\
text: "static"
"""
        result = compile(board_yaml)
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )
        injected = ChartDataError.from_code(
            ERR_KPI_MULTIROW,
            chart_id="injected",
            row_count=5,
        )

        # patch.object on the imported module bypasses the
        # `dbt_charts.core.render` package-vs-function name collision in
        # core/__init__.py that breaks dotted-path patch().
        from dbt_charts.core.render import renderer as renderer_module

        with patch.object(renderer_module, "render_board_svg", side_effect=injected):
            render_result = render(result.board, executor, format="svg")

        # The DbtChartsError reaches the caller as board_error with its original code;
        # the broad-except wrapper must NOT re-stamp it to ERR_INTERNAL.
        assert render_result.board_error is not None
        assert render_result.board_error.code == ERR_KPI_MULTIROW.code
        assert render_result.board_error.code != ERR_INTERNAL.code


class TestRenderInternalCarriesCode:
    def test_render_internal_wraps_unexpected_exception(
        self, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """The catch-all in renderer.render() wraps any non-DbtChartsError
        raised during svg rendering as RenderError(ERR_INTERNAL).
        """
        from unittest.mock import patch

        from dbt_charts.core.diagnostics.codes_unknown import ERR_INTERNAL
        from dbt_charts.core.render.renderer import render

        board_yaml = """\
charts:
  rev:
    query:
      sql: "SELECT 1 AS n"
      source: test
    type: kpi
    value: n
rows:
  - rev
"""
        result = compile(board_yaml)
        executor = Executor(
            result.board,
            adapter_registry=build_adapter_registry(local_project(Path.cwd())),
            query_registry=result.query_registry,
        )

        from dbt_charts.core.render import renderer as renderer_module

        with patch.object(
            renderer_module,
            "render_board_svg",
            side_effect=RuntimeError("simulated bug"),
        ):
            render_result = render(result.board, executor, format="svg")

        assert render_result.board_error is not None
        assert render_result.board_error.code == ERR_INTERNAL.code


class TestRenderVegaLiteUnsupportedTypeCarriesCode:
    def test_svg_chart_type_carries_code(self, make_chart) -> None:
        from dbt_charts.core.diagnostics.codes_render import (
            ERR_VEGA_LITE_UNSUPPORTED_TYPE,
        )
        from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

        chart = make_chart("kpi", value="n")
        data = [{"n": 1}]
        resolve(chart, data, chart_style_context=_BOARD_STYLE)

        with pytest.raises(RenderError) as exc_info:
            generate_vega_lite_spec(chart, data)

        assert exc_info.value.code is ERR_VEGA_LITE_UNSUPPORTED_TYPE
