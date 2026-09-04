"""Resolve-tier test: stacked_domain_max is the max PER-PANEL stacked total.

Uses reproduction A (rows-only, sparse tail) via the shared
..._small_multiples_repro_a fixture, also used by the emitted-spec tier in
test_small_multiples_data_grain.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style, reset_config
from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import resolve_style_and_context

from ...._small_multiples_repro_a import (
    repro_a_chart as _repro_a_chart,
    repro_a_rows as _repro_a_rows,
)


@pytest.fixture(autouse=True)
def reset():
    reset_config()
    yield
    reset_config()


def _board() -> Any:
    return resolve_style_and_context(get_theme_style("clarity"))


def test_stacked_domain_max_is_the_max_per_panel_total_not_cross_panel_sum():
    """The true per-panel max is 10 (two families x 5 each on one month).

    On main (pre-fix) this bakes 21.6 — the cross-panel sum inflated by
    headroom, from the reproduction A bug report.
    """
    _, ctx = _board()
    resolved = resolve(_repro_a_chart(), _repro_a_rows(), chart_style_context=ctx)
    assert resolved.stacked_domain_max is not None
    assert resolved.stacked_domain_max < 15.0, (
        f"expected a per-panel max around 10 (+ headroom), got "
        f"{resolved.stacked_domain_max}"
    )


def test_stacked_domain_max_when_x_is_also_the_multiples_field():
    """`x` and `multiples.rows` naming the same column: `partition()` strips
    that column from each panel's own rows, so a fold that groups by
    `x_field` inside a panel must restamp it first or every row's `x_field`
    reads as absent and the stacked total silently folds to None.

    One panel: 2 series summing to 20 (5 + 15). ``stacked_domain_max`` must
    reflect that total (with headroom), not bake ``None``.
    """
    _, ctx = _board()
    rows = [
        {"cat": "2020", "series": "A", "revenue": 5},
        {"cat": "2020", "series": "B", "revenue": 15},
        {"cat": "2021", "series": "A", "revenue": 3},
        {"cat": "2021", "series": "B", "revenue": 4},
    ]
    chart = BarChart.model_validate(
        {
            "id": "t",
            "type": "bar",
            "query_name": "q",
            "x": "cat",
            "y": "revenue",
            "color": "series",
            "multiples": {"rows": "cat"},
            "stack": "zero",
        }
    )
    resolved = resolve(chart, rows, chart_style_context=ctx)
    assert resolved.stacked_domain_max is not None
    assert resolved.stacked_domain_max >= 20.0
