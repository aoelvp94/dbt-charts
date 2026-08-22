"""Unit tests for ``render/chart/table_support.py`` helpers."""

from __future__ import annotations

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.primitives import FontStyle
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.font_measure import get_font_measurer
from dbt_charts.core.render.chart.table_support import resolve_wrapped_headers


def test_resolve_wrapped_headers_cell_pad_none_falls_back_to_column_layout() -> None:
    """``resolve_wrapped_headers`` advertises ``cell_pad: int | None = None``; when
    None it must read the padding from ``table_config.column_layout.cell_padding``.

    Regression: the fallback used ``table_config.columns.cell_padding`` — but
    ``TableChartStyle.columns`` is a ``dict[str, TableColumnConfig] | None``, so that
    branch raised ``AttributeError`` whenever a caller passed ``cell_pad=None``. The
    fallback now reads ``column_layout`` (a ``TableColumnsStyle`` that has
    ``cell_padding``). Passing None must match passing that padding explicitly.
    """
    table_config = resolve_chart_style_context(get_theme_style("stark")).table
    header_font = FontStyle(family="Arial", size=12.0)
    measurer = get_font_measurer("Arial")
    columns = ["revenue"]
    col_widths = {"revenue": 80.0}

    common = {
        "header_overflow": "wrap",
        "header_height": 20.0,
        "header_font": header_font,
        "padding": 4,
        "table_config": table_config,
        "measurer": measurer,
    }

    # cell_pad=None must not raise and must fall back to column_layout.cell_padding.
    wrapped_none, _trunc_none, height_none = resolve_wrapped_headers(
        columns, {}, col_widths, cell_pad=None, **common
    )
    explicit_pad = int(table_config.column_layout.cell_padding)
    wrapped_explicit, _trunc_explicit, height_explicit = resolve_wrapped_headers(
        columns, {}, col_widths, cell_pad=explicit_pad, **common
    )

    assert wrapped_none == wrapped_explicit
    assert height_none == height_explicit
