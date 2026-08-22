"""TDD boundary tests: list-of-objects → name-keyed mapping rename for style.columns.

These tests verify:
- TableColumnConfig no longer has a ``column`` field (it was the list identity key)
- Channel grammar still uses ``column`` for data binding
- style.columns rejects the list-of-objects shape
- style.columns accepts the name-keyed mapping shape
"""

from __future__ import annotations

import pytest

# =============================================================================
# TableColumnConfig — column field removed
# =============================================================================


def test_table_column_config_rejects_column_key():
    """TableColumnConfig no longer carries a `column` binding field.

    The column name is now the dict key in style.columns, not a field
    inside the config object.
    """
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.chart.authored import (
        TableColumnConfig,
    )

    with pytest.raises(ValidationError):
        TableColumnConfig.model_validate({"column": "arr", "format": "$,.0f"})


def test_table_column_config_rejects_field_key():
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.chart.authored import (
        TableColumnConfig,
    )

    with pytest.raises(ValidationError):
        TableColumnConfig.model_validate({"field": "arr"})


# =============================================================================
# Channel grammar: parse_style_channel
# =============================================================================


def test_parse_style_channel_accepts_column_key():
    from dbt_charts.core.compile.resolve.chart.channel import parse_style_channel

    ch = parse_style_channel({"column": "arr"}, "color")
    assert ch.mode == "series"
    assert ch.data_field == "arr"


def test_parse_style_channel_rejects_field_key():
    from dbt_charts.core.compile.resolve.chart.channel import parse_style_channel

    with pytest.raises(ValueError, match="unknown keys"):
        parse_style_channel({"field": "arr"}, "color")


# =============================================================================
# ChartStylePatch.columns — rejects list, accepts name-keyed mapping
# =============================================================================


def test_chart_style_patch_rejects_list_shape_in_columns():
    """Any list passed to columns is rejected."""
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.style.authored import ChartStylePatch

    with pytest.raises(ValidationError, match=r"Input should be a valid dictionary"):
        ChartStylePatch.model_validate(
            {"table": {"columns": [{"field": "amount", "format": "$,.0f"}]}}
        )


def test_chart_style_patch_rejects_column_keyed_list_shape():
    """Even a list with the old `column:` key is rejected."""
    from pydantic import ValidationError

    from dbt_charts.core.compile.models.style.authored import ChartStylePatch

    with pytest.raises(ValidationError, match=r"Input should be a valid dictionary"):
        ChartStylePatch.model_validate(
            {"table": {"columns": [{"column": "amount", "format": "$,.0f"}]}}
        )


def test_chart_style_patch_accepts_name_keyed_mapping():
    """Dict keyed by column name is the accepted shape."""
    from dbt_charts.core.compile.models.chart.authored import TableColumnConfig
    from dbt_charts.core.compile.models.style.authored import ChartStylePatch

    patch = ChartStylePatch.model_validate(
        {"table": {"columns": {"amount": {"format": "$,.0f"}}}}
    )
    assert patch.table is not None
    col = patch.table.columns["amount"]
    assert isinstance(col, TableColumnConfig)
    assert col.format == "$,.0f"


def test_chart_style_patch_accepts_partial_columns():
    """Partial entries (no format, just empty dict) still pass."""
    from dbt_charts.core.compile.models.chart.authored import TableColumnConfig
    from dbt_charts.core.compile.models.style.authored import ChartStylePatch

    patch = ChartStylePatch.model_validate({"table": {"columns": {"amount": {}}}})
    assert patch.table is not None
    assert isinstance(patch.table.columns["amount"], TableColumnConfig)
