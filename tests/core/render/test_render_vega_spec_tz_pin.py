"""Regression: a composition root that calls ``pin_vl_convert_tz_utc()`` before
rendering gets a byte-identical render regardless of the host machine's
timezone -- the actual contract ``dbt_charts._render_tz`` exists to provide.

``vl_convert.get_local_tz()`` has no setter and no per-call override -- ``TZ``
is read once and cached for the process lifetime (see
``test_tz_independence.py``'s module docstring). ``render_vega_spec()`` itself
does not pin anything -- ``core`` may not touch ``os.environ`` (see
``core/ruff.toml``'s ``TID251`` banned-api) -- so the pin lives outside core,
in ``dbt_charts._render_tz``, and a composition root (the ``dct`` CLI,
``tests/conftest.py``) calls it once at its own startup, before the first
render. This test simulates that: pin, then render, in a fresh subprocess per
zone, and assert the two zones agree.

Subprocess isolation is load-bearing for the same reason as
``test_tz_independence.py``: running both zones in one interpreter would
reuse the first observation's cache and mask the property under test.

Coverage note: this is the only regression test for the pin. The pin now
runs exactly once, at composition-root startup (the ``dct`` CLI's
``cli/main.py``, or this test suite's own session fixture), before *any*
vl-convert call -- not per call site -- so ``to_png()`` and ``to_pdf()`` are
covered by the same single pin, not by calling it themselves. They aren't
separately regression-tested here: both operate on already-rendered SVG text
(no Vega-Lite time functions run at that stage), and ``vl_convert.svg_to_png``
does not itself warm the TZ cache on the pinned vl-convert version, so a
subprocess test built the same way as this one would pass whether or not the
pin ran -- it would not be a regression test. Don't add one that can't fail.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from dbt_charts.core.compile.config import get_theme_style
from dbt_charts.core.compile.models.chart.normalized import LineChart
from dbt_charts.core.compile.models.style.authored import (
    AxisXStylePatch,
    LineChartStylePatch,
)
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.vega_lite import generate_vega_lite_spec

from .test_tz_independence import _svg_texts

_LABEL_EXPR = "timeFormat(datum.value, '%b %Y')"

_DATA = [
    {"date": "2024-04-15T00:00:00", "value": 10},
    {"date": "2024-05-15T00:00:00", "value": 20},
    {"date": "2024-06-15T00:00:00", "value": 30},
]


def _build_spec() -> dict[str, Any]:
    """Authored ``timeFormat()`` labelExpr on a bucketed axis -- the known
    local-time-leaking shape measured during the M5 wave (Apr/May/Jun under
    UTC vs Mar/Apr/May under America/Los_Angeles for this exact data)."""
    chart = LineChart(
        id="tz_pin_render_vega_spec",
        type="line",
        x="date",
        y="value",
        style=LineChartStylePatch.model_validate(
            {
                "axis_x": AxisXStylePatch.model_validate(
                    {
                        "type": "temporal",
                        "time_unit": "yearmonth",
                        "labels": {"expr": _LABEL_EXPR},
                    }
                )
            }
        ),
    )
    board_rs = resolve_style(get_theme_style())
    board_ctx = resolve_chart_style_context(get_theme_style())
    return generate_vega_lite_spec(
        chart, _DATA, board_style=board_rs, chart_style_context=board_ctx
    )


def _render_pinned_in_subprocess(spec: dict[str, Any], tz: str) -> str:
    """Pin then render ``spec`` in a fresh interpreter with ``TZ`` set --
    simulating what a composition root (the ``dct`` CLI, ``tests/conftest.py``)
    does: call ``pin_vl_convert_tz_utc()`` once, before the first render."""
    script = textwrap.dedent(
        """
        import json, sys
        try:
            import vl_convert  # noqa: F401 -- import-guard, mirrors production
        except ImportError:
            sys.exit(99)
        from dbt_charts._render_tz import pin_vl_convert_tz_utc
        from dbt_charts.core.compile.config import get_theme_style
        from dbt_charts.core.compile.resolve.style.board import resolve_style
        from dbt_charts.core.render.converters.chart import render_vega_spec

        pin_vl_convert_tz_utc()

        spec = json.loads(sys.stdin.read())
        resolved_style = resolve_style(get_theme_style())
        svg = render_vega_spec(
            spec, "svg", resolved_style, None, None, False, "tz_pin_render_vega_spec"
        )
        sys.stdout.write(svg)
        """
    )
    env = {k: v for k, v in os.environ.items() if k != "TZ"}
    env["TZ"] = tz
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(spec),
        capture_output=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    if result.returncode == 99:
        pytest.skip("vl_convert not installed in test interpreter")
    assert result.returncode == 0, (
        f"subprocess render failed under TZ={tz}: stderr={result.stderr!r}"
    )
    return result.stdout


def test_pinned_render_is_tz_independent() -> None:
    """A composition root that pins before rendering gets identical axis-tick
    text under ``TZ=UTC`` and ``TZ=America/Los_Angeles`` -- the golden gate's
    actual contract, not a hand-built spec routed straight to vl-convert."""
    spec = _build_spec()
    texts_utc = _svg_texts(_render_pinned_in_subprocess(spec, tz="UTC"))
    texts_pdt = _svg_texts(_render_pinned_in_subprocess(spec, tz="America/Los_Angeles"))
    assert texts_utc == texts_pdt, (
        f"pinned render differs between TZ=UTC and TZ=America/Los_Angeles: "
        f"UTC={texts_utc!r} vs PDT={texts_pdt!r}. A golden approved on one "
        f"machine would not match one regenerated on the other."
    )


def test_spec_still_carries_the_raw_authored_expr() -> None:
    """Canary, mirroring ``test_tz_independence.py``'s
    ``test_property_test_covers_both_emit_shapes``: this module's whole
    premise is that the *pin*, not the emitted spec, is what makes the render
    TZ-independent -- ``generate_vega_lite_spec`` never rewrites an authored
    ``labels.expr`` (see ``render/chart/AGENTS.md``'s no-magic policy). If a
    future change started rewriting ``timeFormat()`` to ``utcFormat()`` at
    emit time, ``test_pinned_render_is_tz_independent`` above would keep
    passing but for an entirely different reason -- the spec would already be
    TZ-safe on its own, and the pin would no longer be exercised by this file
    at all. Catch that here.
    """
    spec = _build_spec()
    axis = spec["encoding"]["x"]["axis"]
    assert axis["labelExpr"] == _LABEL_EXPR, axis
    assert "utcFormat" not in axis["labelExpr"], axis
