"""LegendStyle.position and .direction accept only the values Vega-Lite's
legend orient/direction actually support -- not arbitrary strings.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.style.theme.legend import LegendStyle


def _legend(position: str = "right", direction: str = "vertical") -> LegendStyle:
    return LegendStyle.model_validate(
        {
            "position": position,
            "direction": direction,
            "columns": 0,
            "compact_columns": 2,
            "label": {"padding": 8.0},
            "title": {"padding": 0.0},
        }
    )


@pytest.mark.parametrize(
    "position",
    [
        "left",
        "right",
        "top",
        "bottom",
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
    ],
)
def test_legend_style_accepts_valid_positions(position: str) -> None:
    assert _legend(position=position).position == position


@pytest.mark.parametrize("position", ["center", "none"])
def test_legend_style_rejects_invalid_position(position: str) -> None:
    """``none`` is VL's "place me by hand", not "hide me" — that is `visible`."""
    with pytest.raises(ValidationError):
        _legend(position=position)


@pytest.mark.parametrize("direction", ["horizontal", "vertical"])
def test_legend_style_accepts_valid_directions(direction: str) -> None:
    assert _legend(direction=direction).direction == direction


def test_legend_style_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError):
        _legend(direction="diagonal")
