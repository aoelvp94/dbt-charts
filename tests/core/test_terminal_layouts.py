"""Tests for terminal layout stacking heuristics."""

from types import SimpleNamespace

from dbt_charts.core.render.terminal_layouts import (
    _cols_should_stack_vertically,
    _layout_item_is_table,
)


def _item(chart_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="chart",
        chart=SimpleNamespace(type=chart_type),
    )


def test_layout_item_is_table() -> None:
    assert _layout_item_is_table(_item("table")) is True
    assert _layout_item_is_table(_item("bar")) is False


def test_cols_stack_when_table_present() -> None:
    assert _cols_should_stack_vertically([_item("table"), _item("kpi")], 80) is True


def test_cols_stack_when_columns_too_narrow() -> None:
    assert _cols_should_stack_vertically([_item("kpi"), _item("kpi")], 40) is True


def test_cols_side_by_side_when_wide_enough_non_table() -> None:
    assert _cols_should_stack_vertically([_item("kpi"), _item("kpi")], 60) is False
