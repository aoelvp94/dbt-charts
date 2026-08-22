"""Pydantic models for render-time warnings.

Diagnostic (the wire shape for a single warning) lives in
``dbt_charts.core.diagnostics.diagnostic`` — below render — so compile-time
authoring warnings can construct it without depending on render.

WarningContext carries everything detectors need:
  - board_spec: the compiled Board (typed — detectors use attribute access).
  - chart_results: chart id → list of row dicts (query output).
  - vega_specs: chart id → Vega-Lite spec dict.
  - table_overflows: chart id → the table's slot overflow captured at render.
  - authored_chart_heights: chart id → the nearest ancestor's literal
    authored layout height, in px.
  - text_truncations: chart id → list of TextTruncation records captured
    by renderers when any user-visible text is clipped or cut with an
    ellipsis. Sparse — only charts with truncated text appear.
  - chart_truncations: chart id → TruncationInfo record for a query result
    truncated by execution.max_rows/max_result_bytes. Sparse — only charts
    whose query was actually truncated this render appear.

vega_specs is SPARSE: KPI, text, and markdown charts do not compile to
Vega-Lite, so their ids are OMITTED from this dict (not present as None).
Detectors that key into vega_specs must guard with:
    if chart_id not in ctx.vega_specs:
        continue

table_overflows is likewise SPARSE: only tables that overflowed their slot
appear, and only on SVG-family renders (non-SVG formats never rasterize a
table, so it is empty for them).

static_pagination_caps is likewise SPARSE: only tables whose static export
hit the pre-rendered-page cap appear, and only on SVG-family renders (a
static export is the only surface that pre-renders pages at all — non-SVG
formats and interactive hosts never populate it).

authored_chart_heights is likewise SPARSE: a chart with no authored height
anywhere in its ancestor chain is OMITTED, not present as 0 or None. The
value is a snapshot of the chart's real, assigned px slot height, taken by
build_resolved_board (via layout_sizing._snapshot_authored_slot_heights)
immediately after the sizing pass assigns it but before cols-alignment can
re-expand it — for a `cols:`-wrapped chart, that alignment step re-expands
the resolved height to the chart's natural/unconstrained size afterward to
keep siblings visually aligned, discarding the authored cap. Because the
value is read off the sizing pass's own output (not re-derived), it already
reflects a `rows:` wrapper splitting its height across children and a
percentage-authored height resolved against real available space.

text_truncations is SPARSE: only charts where any user-visible text was cut
with an ellipsis (or silently clipped) appear. The warning pass re-renders
all charts (including non-VL families) with the sink open, so table, KPI,
callout, and spark_bar truncations are captured alongside VL axis titles.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from dbt_charts.core.compile.models.board.resolved import ResolvedBoard
from dbt_charts.core.execute.executor import TruncationInfo
from dbt_charts.core.render.chart.endpoint_label_overflow import (
    EndpointLabelGapOverflow,
)
from dbt_charts.core.render.chart.series_label_truncation import SeriesLabelTruncation
from dbt_charts.core.render.chart.table_overflow import TableOverflow
from dbt_charts.core.render.chart.table_static_pagination import StaticPaginationCap
from dbt_charts.core.render.chart.text_truncation import TextTruncation


class WarningContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_spec: ResolvedBoard
    # chart id → list of row dicts from the executed query
    chart_results: dict[str, list[dict[str, Any]]]
    # chart id → Vega-Lite spec dict (sparse — non-vega charts are omitted)
    vega_specs: dict[str, dict[str, Any]]
    # chart id → the table's slot overflow at render time (tables only; sparse —
    # captured from the real SVG render, so empty for non-SVG formats).
    table_overflows: dict[str, TableOverflow] = {}
    # chart id → the table's static-export page cap at render time (tables
    # only; sparse — only a static export that hit the cap populates this).
    static_pagination_caps: dict[str, StaticPaginationCap] = {}
    # chart id → the endpoint-label rail's gap overflow at render time
    # (right_pane layout only; sparse — captured from the real SVG render's
    # probe, so only charts whose intended gap didn't fit appear).
    endpoint_label_gap_overflows: dict[str, EndpointLabelGapOverflow] = {}
    # chart id → nearest ancestor's literal authored layout height, in px
    # (sparse — see module docstring for why this isn't derived from
    # board_spec.layout's resolved .height).
    authored_chart_heights: dict[str, float] = {}
    # chart id → the series labels the endpoint-label rail cap cut, captured at
    # the single measure site (render/chart/features/endpoint_labels.py). Sparse —
    # only charts whose rail was actually degraded appear.
    series_label_truncations: dict[str, list[SeriesLabelTruncation]] = {}
    # chart id → list of text truncations captured at render time across all
    # surfaces (axis titles included). Sparse — only charts with truncated
    # text appear.
    text_truncations: dict[str, list[TextTruncation]] = {}
    # chart id → the query-result truncation record (execution.max_rows /
    # max_result_bytes) for that chart's query, from Executor.truncations().
    # Sparse — only charts whose query was actually truncated appear.
    chart_truncations: dict[str, TruncationInfo] = {}
    # query name → truncation record for queries that were truncated but whose
    # query_name does not map to any chart (e.g. upstream queries demand-executed
    # by a cache-ref composition — only the composed query is charted, not its
    # upstreams). Sparse — only present when such orphan truncations exist.
    unattributed_truncations: dict[str, TruncationInfo] = {}


def encoding_channel_type(vega_spec: dict[str, object], channel: str) -> str:
    """Vega-Lite encoding ``type`` for a channel ("x", "color", …).

    Returns "" when the spec declares no such channel or no type — Vega specs
    are generated and these keys are not guaranteed present; absence means "no
    categorical encoding here", which detectors treat as "do not fire".
    """
    encoding = vega_spec.get("encoding")
    if not isinstance(encoding, dict):
        return ""
    channel_def = encoding.get(channel)
    if not isinstance(channel_def, dict):
        return ""
    channel_type = channel_def.get("type")
    return channel_type if isinstance(channel_type, str) else ""
