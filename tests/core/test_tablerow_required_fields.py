"""Behavior tests: TableRow* fields are required (no hardcoded defaults).

Verifies that bare construction raises ValidationError and that values propagate
from the theme pipeline through to the render layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import (
    get_theme_style,
    reset_config,
)
from dbt_charts.core.compile.models.primitives import RuleStyle
from dbt_charts.core.compile.models.style.theme import (
    TableRowRolesStyle,
    TableRowRoleStyle,
    TableRowStyle,
)


def test_compiled_rule_style_requires_width():
    with pytest.raises(ValidationError):
        RuleStyle(continuous=False)


def test_compiled_rule_style_requires_continuous():
    with pytest.raises(ValidationError):
        RuleStyle(width=0.0)


def test_compiled_table_row_role_style_requires_rule_width():
    with pytest.raises(ValidationError):
        TableRowRoleStyle()


def test_compiled_table_row_roles_style_requires_summary():
    with pytest.raises(ValidationError):
        TableRowRolesStyle(total=TableRowRoleStyle(rule_width=0.0))


def test_compiled_table_row_roles_style_requires_total():
    with pytest.raises(ValidationError):
        TableRowRolesStyle(summary=TableRowRoleStyle(rule_width=1.0))


def test_compiled_table_row_style_requires_height():
    with pytest.raises(ValidationError):
        TableRowStyle(
            rule=RuleStyle(width=0.0, continuous=False),
            roles=TableRowRolesStyle(
                summary=TableRowRoleStyle(rule_width=1.0),
                total=TableRowRoleStyle(rule_width=0.0),
            ),
        )


def test_theme_pipeline_populates_row_fields():
    """Theme pipeline produces populated TableRowStyle with required fields."""
    reset_config()  # guard against config-cache corruption from other tests
    row = get_theme_style().charts.table.row
    assert isinstance(row, TableRowStyle)
    assert isinstance(row.height, float)
    assert isinstance(row.rule, RuleStyle)
    assert isinstance(row.rule.width, float)
    assert isinstance(row.rule.continuous, bool)
    assert isinstance(row.roles, TableRowRolesStyle)
    assert isinstance(row.roles.summary.rule_width, float)
    assert isinstance(row.roles.total.rule_width, float)
