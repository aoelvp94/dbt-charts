"""Parity tests: v2 VL ``config`` must equal old-path ``config`` output.

TDD gate for the presentation-config port. Once green, the T7 parity
suite can extend the same fixture to cover all families.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.render.chart.spec import RenderBox

_DEFAULT_BOX = RenderBox(width=600.0, height=300.0)

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
from dbt_charts.core.compile.models.chart.normalized import BarChart, LineChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
    resolve_style_and_context,
)
from dbt_charts.core.render.chart.session import BoardRenderSession
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

_BOARD_RS, _BOARD_CTX = resolve_style_and_context(get_theme_style())

# Required base fields (no defaults on non-None resolved model fields).
_B: dict[str, Any] = {
    "variable_dependencies": frozenset(),
    "palette": (),
    "resolved_channels": {},
}
_C: dict[str, Any] = dict(_B)

_DATA = [{"month": "Jan", "revenue": 100}, {"month": "Feb", "revenue": 200}]


def _board_rs():
    return resolve_style(get_theme_style(get_default_theme_name()))


def _board_ctx():
    return resolve_chart_style_context(get_theme_style(get_default_theme_name()))


# ── old-path helpers ─────────────────────────────────────────────────────────


def _old_bar_spec() -> dict[str, Any]:
    chart = BarChart(
        id="bar1",
        type="bar",
        x="month",
        y="revenue",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
    )
    return generate_vega_lite_spec(
        chart, _DATA, board_style=_BOARD_RS, chart_style_context=_BOARD_CTX
    )


def _old_line_spec() -> dict[str, Any]:
    chart = LineChart(
        id="line1",
        type="line",
        x="month",
        y="revenue",
        query=SqlQuery(sql="SELECT 1", source="src"),
        query_name="q",
    )
    return generate_vega_lite_spec(
        chart, _DATA, board_style=_BOARD_RS, chart_style_context=_BOARD_CTX
    )


# ── v2-path helpers ──────────────────────────────────────────────────────────


def _v2_bar_spec() -> dict[str, Any]:
    from dbt_charts.core.compile.models.chart.normalized import BarChart
    from dbt_charts.core.compile.resolve import resolve

    session = BoardRenderSession.create(_board_rs())
    chart = resolve(
        BarChart(id="bar1", type="bar", x="month", y="revenue"), _DATA, _board_ctx()
    )
    return session.finalize_vl(
        session.emit_chart(chart, _DEFAULT_BOX, {chart.query_name: _DATA})
    )


def _v2_line_spec() -> dict[str, Any]:
    from dbt_charts.core.compile.models.chart.normalized import LineChart
    from dbt_charts.core.compile.resolve import resolve

    session = BoardRenderSession.create(_board_rs())
    chart = resolve(
        LineChart(id="line1", type="line", x="month", y="revenue"),
        _DATA,
        _board_ctx(),
    )
    return session.finalize_vl(
        session.emit_chart(chart, _DEFAULT_BOX, {chart.query_name: _DATA})
    )


# ── parity assertions ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("old_fn", "v2_fn", "family"),
    [
        (_old_bar_spec, _v2_bar_spec, "bar"),
        (_old_line_spec, _v2_line_spec, "line"),
    ],
)
def test_v2_config_matches_old_path(old_fn, v2_fn, family):
    """v2 VL ``config`` must be byte-identical to old-path output."""
    old = old_fn()
    v2 = v2_fn()
    assert "config" in old, f"{family}: old path produced no config"
    assert "config" in v2, f"{family}: v2 produced no config"
    assert v2["config"] == old["config"], (
        f"{family}: v2 config diverges from old path.\n"
        f"Old keys: {sorted(old['config'])}\n"
        f"V2  keys: {sorted(v2['config'])}"
    )


def test_v2_background_matches_old_path_bar():
    """v2 background key must equal old-path value for bar (non-geo) chart."""
    old = _old_bar_spec()
    v2 = _v2_bar_spec()
    assert v2.get("background") == old.get("background"), (
        f"background mismatch: v2={v2.get('background')!r} old={old.get('background')!r}"
    )
