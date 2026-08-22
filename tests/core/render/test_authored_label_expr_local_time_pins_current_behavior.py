"""Pin: an authored ``axis_x.labels.expr`` calling ``timeFormat()`` on a
bucketed axis remains TZ-dependent by design.

This is the flip side of ``test_local_time_label_expr_on_bucketed_axis_warning_e2e.py``
and the ``WARN-LOCAL-TIME-LABEL-EXPR-ON-BUCKETED-AXIS`` detector: Dataface
chose to warn, not to rewrite the author's raw Vega expression (see
`render/chart/AGENTS.md`'s "no magic" / no chart-layer data transformation
policy -- rewriting arbitrary authored code is exactly the kind of hidden
mutation that policy forbids). So the render itself is NOT
fixed by this change; the warning is the whole remedy. This test proves that
directly, subprocess-isolated like ``test_tz_independence.py`` (vl_convert
caches the observed local TZ for the process lifetime).

It also pins a finding from investigating the bug: Vega-Lite's bucketed
``timeUnit`` transform anchors each tick at the *start* of its bucket (UTC
midnight of day 1), so a **negative** UTC offset (America/Los_Angeles) rolls
the local read back across midnight into the previous bucket, but a
**positive** offset (Asia/Tokyo) only moves later within the same UTC day and
never crosses back over a start-of-bucket boundary. The two zones are not
symmetric for this data shape -- Tokyo renders identically to UTC here.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import LineChart
from dbt_charts.core.compile.models.style.authored import (
    AxisXStylePatch,
    LineChartStylePatch,
)
from dbt_charts.core.compile.resolve.style import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

from .test_tz_independence import _render_in_subprocess, _svg_texts

_BOARD_RS = resolve_style(get_theme_style())
_BOARD_CTX = resolve_chart_style_context(get_theme_style())

_DATA = [
    {"date": "2024-04-15T00:00:00", "value": 10},
    {"date": "2024-05-15T00:00:00", "value": 20},
    {"date": "2024-06-15T00:00:00", "value": 30},
]


def _build_spec(time_unit: str, fmt: str) -> dict[str, Any]:
    chart = LineChart(
        id="authored_local_time",
        type="line",
        x="date",
        y="value",
        style=LineChartStylePatch.model_validate(
            {
                "axis_x": AxisXStylePatch.model_validate(
                    {
                        "type": "temporal",
                        "time_unit": time_unit,
                        "labels": {"expr": f"timeFormat(datum.value, '{fmt}')"},
                    }
                )
            }
        ),
    )
    return generate_vega_lite_spec(
        chart, _DATA, board_style=_BOARD_RS, chart_style_context=_BOARD_CTX
    )


def test_negative_offset_still_diverges_from_utc() -> None:
    """America/Los_Angeles (UTC-8) rolls the tick back across midnight into
    the previous bucket -- the reported bug, still present by design."""
    # Only the three date-axis ticks are the property under test; the trailing
    # y-axis value labels ("10"/"20"/"30") are theme-tunable presentation
    # (number formatting, zero-width-space insertion, etc.) that dbt-charts/AGENTS.md
    # says not to pin -- asserting the full tuple makes an unrelated theme
    # change fail this test with a message accusing it of rewriting the
    # authored expression.
    spec = _build_spec("yearmonth", "%b %Y")
    texts_utc = _svg_texts(_render_in_subprocess(spec, tz="UTC"))[:3]
    texts_pdt = _svg_texts(_render_in_subprocess(spec, tz="America/Los_Angeles"))[:3]
    assert texts_utc == ("Apr 2024", "May 2024", "Jun 2024"), texts_utc
    assert texts_pdt == ("Mar 2024", "Apr 2024", "May 2024"), (
        f"expected the authored timeFormat() escape hatch to remain "
        f"TZ-dependent under a negative offset (each month tick reading one "
        f"bucket early) -- got {texts_pdt!r}; if this now matches "
        f"{texts_utc!r}, something started rewriting the authored expression"
    )


def test_negative_offset_diverges_on_yearquarter_too() -> None:
    """A second grain -- quarter-boundary arithmetic differs from month."""
    # Only the single date-axis tick is the property under test; see the
    # comment in test_negative_offset_still_diverges_from_utc for why the
    # trailing value labels aren't pinned here.
    spec = _build_spec("yearquarter", "%b %d %Y")
    texts_utc = _svg_texts(_render_in_subprocess(spec, tz="UTC"))[:1]
    texts_pdt = _svg_texts(_render_in_subprocess(spec, tz="America/Los_Angeles"))[:1]
    assert texts_utc == ("Apr 01 2024",), texts_utc
    assert texts_pdt == ("Mar 31 2024",), (
        f"expected the yearquarter tick to roll back across the quarter "
        f"boundary under a negative offset -- got {texts_pdt!r} vs "
        f"UTC {texts_utc!r}"
    )
