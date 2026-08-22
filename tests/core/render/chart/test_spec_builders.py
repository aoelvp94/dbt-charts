"""Tests for spec-building helpers (dbt_charts.core.render.chart.spec_builders)."""

from __future__ import annotations

from dbt_charts.core.render.chart.spec_builders import bump_padding_bottom


def test_bump_padding_bottom_adds_to_existing_dict():
    spec = {"padding": {"top": 5, "right": 5, "bottom": 10, "left": 5}}
    bump_padding_bottom(spec, 30)
    assert spec["padding"] == {"top": 5, "right": 5, "bottom": 40, "left": 5}
