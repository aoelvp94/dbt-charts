"""The magnitude gate must agree with the emitter's own encoding choice.

``_flag_quantitative_color`` (compile-time) exists so hover-emphasis's
palette gate can know, before any row is rendered, whether a bare
``color: <field>`` will end up as Vega-Lite's continuous gradient
encoding -- the exact question ``channel_to_encoding``
(``render/chart/emitters/_channels.py``) answers at emit time via
``infer_vega_type_from_data``. Before the shared predicate, the two asked
different questions (a >80%-numeric threshold over up to 20 non-null
samples, accepting numeric strings and excluding bool, vs. an
all-or-nothing check over the first 10 rows, rejecting numeric strings and
counting bool as numeric) and could disagree in both directions -- see the
regression this pins.
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.models.chart.normalized import BarChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.resolve.chart._channels import _channels_for
from dbt_charts.core.render.chart.type_inference import infer_vega_type_from_data


def _sql() -> SqlQuery:
    return SqlQuery(sql="SELECT 1", source="src")


def _bar_with_color() -> BarChart:
    return BarChart(
        id="b", type="bar", x="cat", y="val", color="c", query=_sql(), query_name="q"
    )


def _rows(color_values: list[Any]) -> list[dict[str, Any]]:
    return [{"cat": f"c{i}", "val": i, "c": v} for i, v in enumerate(color_values)]


_CASES: dict[str, tuple[list[Any], bool]] = {
    "all numeric": (list(range(15)), True),
    # First 10 rows are all numeric (Vega-Lite's own sample window); rows
    # past it turn non-numeric. The bug this pins: the old compile-side
    # threshold pooled up to 20 non-null samples and required >80% numeric,
    # so this case fell under the threshold and went unflagged while the
    # emitter -- which only ever looks at the first 10 -- rendered a
    # gradient legend anyway.
    "numeric then n/a past row 10": (
        list(range(10)) + ["n/a"] * 5,
        True,
    ),
    # A wholly-null color column. infer_vega_type_from_data's own
    # `all_numeric` starts True and every value is skipped by the `is None`
    # continue, so it never flips to False -- Vega-Lite renders the
    # quantitative gradient scale even with nothing to plot. The gate must
    # flag this too, not treat "no samples" as "not numeric."
    "all null": ([None] * 10, True),
    "mixed strings": (["red", "green", "blue"] * 4, False),
    # Numeric-looking strings are still Python `str` -- Vega-Lite's own
    # type inference (`is_vega_numeric_value`) never coerces them, unlike
    # the old compile-side `classify_column_type`, which did.
    "numeric strings": ([str(i) for i in range(10)], False),
    # `bool` is an `int` subclass -- Vega-Lite's numeric check counts it as
    # numeric, unlike the old compile-side classifier, which excluded it.
    "booleans": ([i % 2 == 0 for i in range(10)], True),
}


@pytest.mark.parametrize(("name", "case"), _CASES.items())
def test_gate_flag_matches_emitters_quantitative_choice(
    name: str, case: tuple[list[Any], bool]
) -> None:
    color_values, expected = case
    data = _rows(color_values)

    channels = _channels_for(_bar_with_color(), data)
    gate_flagged = channels["color"].quantitative_data

    emitter_is_quantitative = infer_vega_type_from_data(data, "c") == "quantitative"

    assert gate_flagged is expected, name
    assert emitter_is_quantitative is expected, name
    assert gate_flagged is emitter_is_quantitative, name
