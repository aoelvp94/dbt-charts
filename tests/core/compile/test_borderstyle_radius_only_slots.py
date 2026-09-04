"""BorderStyle slots that only apply radius: InputStyle.border,
SparkColumnsStyle.border, SparkBarCellStyle.border, SparkBarChartStyle.border.

These four slots typed the full ``BorderStyle`` (width/color/radius plus
optional dash fields) but every render path reads only ``radius`` — the other
fields were schema-valid and silently ignored. Narrowed to a radius-only
``CornerStyle`` so the schema stops promising styling it doesn't deliver.

Uses ``AuthoredBoard.model_validate`` directly (not ``compile()``) so these
pin current-schema rejection without the migration engine's auto-strip
rescuing an old-shaped document — that behavior is covered separately in
``test_borderstyle_radius_only_migration.py``.

TDD tests — written BEFORE the narrowing. All should fail initially.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.authored import AuthoredBoard

# Each slot's dotted path under `style:`.
SLOT_PATHS: dict[str, list[str]] = {
    "variables.input.border": ["variables", "input", "border"],
    "charts.table.spark.columns.border": [
        "charts",
        "table",
        "spark",
        "columns",
        "border",
    ],
    "charts.table.spark.bar.border": ["charts", "table", "spark", "bar", "border"],
    "charts.spark_bar.border": ["charts", "spark_bar", "border"],
}


def _board(slot: str, border: dict[str, Any]) -> dict[str, Any]:
    style: dict[str, Any] = {}
    node = style
    for part in SLOT_PATHS[slot][:-1]:
        node = node.setdefault(part, {})
    node[SLOT_PATHS[slot][-1]] = border
    return {
        "charts": {
            "c1": {"type": "bar", "query": "q1", "x": "x", "y": "x"},
        },
        "queries": {"q1": {"sql": "SELECT 1 AS x", "source": "test"}},
        "style": style,
    }


@pytest.mark.parametrize("slot", list(SLOT_PATHS))
@pytest.mark.parametrize(
    "border",
    [
        {"width": 2.0, "radius": 4.0},
        {"color": "red", "radius": 4.0},
        {"dash_array": [4, 4], "radius": 4.0},
    ],
    ids=["width", "color", "dash_array"],
)
def test_inert_border_field_rejected_on_radius_only_slot(
    slot: str, border: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        AuthoredBoard.model_validate(_board(slot, border))


@pytest.mark.parametrize("slot", list(SLOT_PATHS))
def test_radius_still_accepted_on_radius_only_slot(slot: str) -> None:
    AuthoredBoard.model_validate(_board(slot, {"radius": 6.0}))
