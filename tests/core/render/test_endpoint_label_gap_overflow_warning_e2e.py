"""End-to-end: an endpoint-label rail that cannot fit its intended gap into the
available plot height degrades to even distribution and fires an advisory
warning, instead of piling every label onto the domain edges.

Proves the full seam — compile -> render() -> RenderResult.warnings — not a
hand-built WarningContext, matching the pattern in
``test_table_overflow_warning_e2e.py``.
"""

from __future__ import annotations

import re
from unittest.mock import Mock

from dbt_charts.core.compile import compile
from dbt_charts.core.execute import Executor
from dbt_charts.core.render import render

_CODE = "WARN-ENDPOINT-LABEL-GAP-OVERFLOW"

# Eight series, endpoints packed into a 1.0-wide band — (n-1) * 18px cannot
# possibly fit into an 80px-tall card, forcing the overflow degradation.
_SERIES = [f"s{i}" for i in range(8)]


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i, s in enumerate(_SERIES):
        rows.append({"date": "2024-01-01", "value": 100.0, "series": s})
        rows.append({"date": "2024-02-01", "value": 100.0 + i * 0.1, "series": s})
    return rows


def _make_executor(face: object, query_registry: object, rows: list[dict[str, object]]):
    ok = Mock()
    ok.is_success = True
    ok.data = rows
    ok.column_descriptions = None
    ok.resolved_relations = None
    ok.truncated_reason = None
    mock_registry = Mock()
    mock_registry.execute.return_value = ok
    return Executor(face, adapter_registry=mock_registry, query_registry=query_registry)


_CRAMPED = """
title: Cramped rail
charts:
  trend:
    query: q
    type: line
    x: date
    y: value
    color: series
    style:
      endpoint_labels:
        visible: true
queries:
  q:
    sql: SELECT * FROM t
    source: test_source
rows:
  - height: 80
    cols:
      - trend
"""

_ROOMY = """
title: Roomy rail
charts:
  trend:
    query: q
    type: line
    x: date
    y: value
    color: series
    style:
      endpoint_labels:
        visible: true
queries:
  q:
    sql: SELECT * FROM t
    source: test_source
rows:
  - height: 600
    cols:
      - trend
"""


def test_cramped_rail_warns_and_distributes_evenly() -> None:
    result = compile(_CRAMPED)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _rows())

    render_result = render(result.board, executor, format="svg")

    codes = {w.code for w in render_result.warnings}
    assert _CODE in codes, (
        "eight series crammed into an 80px rail cannot fit (n-1)*18px of "
        "intended gap — the overflow warning must fire"
    )
    warning = next(w for w in render_result.warnings if w.code == _CODE)
    assert warning.chart == "trend"
    assert warning.fix

    assert render_result.output is not None
    match = re.search(
        r"concat_1_marks[^>]*>(.*?)</g></g>", render_result.output, re.DOTALL
    )
    assert match is not None
    ys = [
        float(y)
        for _, y in re.findall(
            r'transform="translate\(([\-0-9.]+),\s*([\-0-9.]+)\)"', match.group(1)
        )
    ]
    ys.sort()
    gaps = [b - a for a, b in zip(ys, ys[1:], strict=False)]
    # Even distribution: every successive gap is the same, within rounding —
    # the pre-fix pile-up produces wildly unequal (near-zero) gaps instead.
    assert max(gaps) - min(gaps) < 0.5, (
        f"overflowed rail must distribute labels evenly across the plot; "
        f"got gaps {gaps}"
    )


def test_roomy_rail_silent() -> None:
    result = compile(_ROOMY)
    assert result.success and result.board is not None, result.errors
    executor = _make_executor(result.board, result.query_registry, _rows())

    render_result = render(result.board, executor, format="svg")

    codes = {w.code for w in render_result.warnings}
    assert _CODE not in codes
