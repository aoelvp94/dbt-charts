"""dbt_charts renderer module.

Stage: RENDER
Purpose: Render compiled boards to various output formats.

Entry Points:
    - render(board, executor, format, variables, **options) -> str | bytes
    - render_chart(chart, data, **options) -> str

This is the main rendering orchestration module. It:
1. Takes a Board from compile stage
2. Delegates SVG rendering to boards.py
3. Delegates format conversion to converters/
4. Produces output in requested format

Dependencies:
    - dbt_charts.compile (for Board, Chart)
    - dbt_charts.execute (for Executor)
    - .boards (for SVG rendering)
    - .charts (for chart rendering)
    - .converters (for format conversion)
"""

import contextlib
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.chart.resolved import ResolvedChart
    from dbt_charts.core.compile.models.style.resolved import ResolvedStyle

from dbt_charts.core.compile.config import (
    get_rendering_config,
    resolve_max_workers,
)
from dbt_charts.core.compile.models.board.normalized import (
    Board,
    VariableValues,
)
from dbt_charts.core.compile.models.board.resolved import (
    ResolvedBoard,
    ResolvedLayout,
)
from dbt_charts.core.compile.models.chart.normalized import NON_ASPECT_RATIO_TYPES
from dbt_charts.core.compile.template.variables import (
    normalize_multiselect_values,
    parse_variable_json_strings,
    variable_value_is_absent,
)
from dbt_charts.core.diagnostics import Diagnostic
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.diagnostics.suppression import partition as _partition_warnings
from dbt_charts.core.execute.collect import (
    collect_all_query_names,
    collect_layout_chart_query_names,
)
from dbt_charts.core.execute.executor import Executor
from dbt_charts.core.execute.parallel import execute_queries_parallel
from dbt_charts.core.render.board_to_dict import NO_ROW_CAP
from dbt_charts.core.render.boards import render_board_svg
from dbt_charts.core.render.chart.endpoint_label_overflow import (
    EndpointLabelGapOverflow,
    collect_endpoint_label_gap_overflows,
)
from dbt_charts.core.render.chart.series_label_truncation import (
    collect_series_label_truncations,
)
from dbt_charts.core.render.chart.table import strip_pagination_chrome
from dbt_charts.core.render.chart.table_overflow import (
    TableOverflow,
    collect_table_overflows,
)
from dbt_charts.core.render.chart.table_static_pagination import (
    StaticPaginationCap,
    collect_static_pagination_caps,
)
from dbt_charts.core.render.chart.text_truncation import (
    TextTruncation,
    collect_text_truncations,
)
from dbt_charts.core.render.controls import interactive_controls
from dbt_charts.core.render.converters import to_html, to_pdf, to_png
from dbt_charts.core.render.errors import (
    FormatError,
    MissingRequiredVariablesError,
    MissingVariable,
    RenderError,
)
from dbt_charts.core.render.font_selection import collect_painted_italic_families
from dbt_charts.core.render.layout_sizing import RenderCache
from dbt_charts.core.render.render_result import RenderResult
from dbt_charts.core.render.sizing import resolve_active_tab_index
from dbt_charts.core.render.warnings import (
    WarningContext,
    registry as _warnings_registry,
    run_all,
)

# Formats that produce SVG output (require vl-convert chart rendering).
_SVG_FORMATS = frozenset({"svg", "html", "png", "pdf"})

# Formats that walk the layout tree for data instead of rasterizing an SVG.
_DATA_FORMATS = frozenset({"json", "text", "yaml", "data"})


class DataFormatRenderer(Protocol):
    """Signature every data-bearing format renderer shares.

    Narrower than the implementations, deliberately: this dispatch always
    supplies a collector and a cap, so neither is optional here.
    """

    def __call__(
        self,
        board: Board,
        executor: Executor,
        variables: VariableValues,
        error_collector: list[Diagnostic],
        max_rows_per_query: int,
    ) -> str: ...


def _data_format_renderer(format: str) -> DataFormatRenderer:
    """Resolve a data-bearing format to its renderer.

    Imported here rather than at module scope so the serializer modules stay
    off the import path of an SVG-only render.
    """
    from dbt_charts.core.render.data_format import render_board_data
    from dbt_charts.core.render.json_format import render_board_json
    from dbt_charts.core.render.text_format import render_board_text
    from dbt_charts.core.render.yaml_format import render_board_yaml

    return {
        "json": render_board_json,
        "text": render_board_text,
        "yaml": render_board_yaml,
        "data": render_board_data,
    }[format]


def _collect_active_layout_charts(
    board: ResolvedBoard, variables: VariableValues
) -> dict[str, tuple["ResolvedChart", float]]:
    """Map chart_id -> (the chart instance, its real laid-out width) for the
    active-tab subtree.

    Reads each ``ResolvedLayoutItem`` directly rather than looking a chart id
    up in ``board.charts`` — the catalog holds one entry per id, but a shared
    chart id can carry several distinct ``ResolvedChart`` instances in the
    layout tree, each resolved at its own item's width
    (``_resolve_layout_item`` keys its variant cache by
    ``(chart_id, width, style)``). Reading the item directly makes
    ``resolution_width == width`` hold by construction for whatever is
    returned here — there is no catalog entry that can belong to a
    different placement than the one being judged.

    A tabs layout descends into only the active tab's item — like
    ``active_layout_items`` — instead of every tab. Zero-width items (an
    inactive tab or a collapsed ``details:`` chart, never laid out) are
    excluded outright; a chart placed twice at different real widths within
    the active subtree keeps its narrowest placement — that is where
    crowding shows.
    """
    charts: dict[str, tuple[ResolvedChart, float]] = {}

    def _walk(layout: ResolvedLayout) -> None:
        items = layout.items
        if layout.type == "tabs" and items:
            active = resolve_active_tab_index(
                len(items),
                layout.tab_variable,
                list(layout.tab_slugs),
                layout.default_tab,
                variables,
            )
            items = (items[active],)
        for item in items:
            if item.chart is not None and item.width:
                existing = charts.get(item.chart.id)
                if existing is None or item.width < existing[1]:
                    charts[item.chart.id] = (item.chart, item.width)
            if item.board is not None:
                _walk(item.board.layout)

    _walk(board.layout)
    return charts


def _collect_render_warnings(
    board: ResolvedBoard,
    authored_chart_heights: dict[str, float],
    executor: Executor,
    variables: VariableValues,
    table_overflows: dict[str, TableOverflow],
    text_truncations: dict[str, list[TextTruncation]],
    static_pagination_caps: dict[str, StaticPaginationCap],
    endpoint_label_gap_overflows: dict[str, EndpointLabelGapOverflow],
) -> list[Diagnostic]:
    """Build WarningContext from cached query results and run all detectors.

    Called after queries have already executed (results are in the executor
    cache). Only charts reachable from the layout tree are included — orphan
    charts (present in board.charts but absent from the layout) were never
    pre-executed and are intentionally excluded so this function never
    triggers a fresh adapter call.

    This is warning diagnostics only, not the board render path — but a
    *geometry* detector must judge a chart against the width it actually
    renders at, so each chart's real layout width (from the already-computed
    ``board.layout`` tree) is passed through rather than falling back to the
    unrelated theme-family default; a *data* detector runs off the query
    result alone and does not care whether the chart has a width at all. See
    ``render/warnings/registry.py``'s module docstring for the split.

    ``authored_chart_heights`` is the snapshot ``build_resolved_board`` took of
    each chart's real assigned slot height, for charts under an authored
    ancestor, captured before cols-alignment could overwrite it — see
    ``layout_sizing._snapshot_authored_slot_heights``.
    """
    # Fast path: skip all spec/query work when no detectors are registered.
    # Avoids double-building vega specs on every SVG render for zero benefit.
    if not _warnings_registry.DETECTORS:
        return []

    # Restrict to charts the layout actually renders — same set that
    # execute_queries_parallel pre-executed.
    # Orphan charts (in board.charts but absent from the layout) were never
    # pre-cached; including them would trigger a fresh adapter call.
    pre_executed_query_names = collect_layout_chart_query_names(board)

    # A tabs layout's inactive-tab charts are data-resolved (ResolvedBoard.charts
    # must agree with what record_board records) but never laid out — the
    # render-first vl-convert measurement the active tab gets is exactly the
    # cost this skips, so these items (and a collapsed `details:` chart, sized
    # the same unmeasured way) keep width=height=0.0.
    #
    # That absence of a real width only invalidates GEOMETRY detectors —
    # truncation, category counts, band width, panel width — which judge
    # something that was never painted at any width. It says nothing about
    # DATA detectors (WARN-QUERY-RETURNED-ZERO-ROWS, formatter/currency
    # nudges, pie share/segment checks, …): the query still executed and
    # a genuine defect in its result is real regardless of whether the chart
    # is on-screen right now. See registry.py's module docstring for the
    # detector-kind split this gate exists to preserve.
    active_charts = _collect_active_layout_charts(board, variables)

    chart_results: dict[str, list[dict[str, Any]]] = {}
    for chart_id, chart in board.charts.items():
        if chart.query_name not in pre_executed_query_names:
            continue
        # Unconditional on width: chart_results feeds data detectors, which
        # must run whether or not this chart is currently on-screen.
        # Omit failed charts so detectors can distinguish failure from genuine
        # zero rows: absent from chart_results = failed execute.
        with contextlib.suppress(Exception):  # noqa: BLE001 — query failure already recorded elsewhere
            if chart.query_name:
                # Re-use cached execute_query result; no re-execution.
                chart_results[chart_id] = executor.execute_query(
                    chart.query_name, variables
                )

    # chart id → truncation record, for every chart whose query was cut by
    # execution.max_rows/max_result_bytes this render.
    query_truncations = executor.truncations()
    chart_query_names = {
        chart.query_name for chart in board.charts.values() if chart.query_name
    }
    chart_truncations = {
        chart_id: query_truncations[chart.query_name]
        for chart_id, chart in board.charts.items()
        if chart.query_name in query_truncations
    }
    # Truncations for queries not owned by any chart (e.g. upstream queries
    # demand-executed by cache-ref composition — only the composed query is
    # charted, not its upstreams). Surfaced as board-level warnings so the
    # author knows the data they see may be incomplete even though no chart
    # id maps to the affected query.
    unattributed_truncations = {
        name: info
        for name, info in query_truncations.items()
        if name not in chart_query_names
    }

    from dbt_charts.core.render.chart.vega_lite import render_resolved_chart

    vega_specs: dict[str, dict[str, Any]] = {}
    # Open a fresh sink so VL chart spec-generation here (for the detection
    # pass) captures axis_title / chart_title truncations. This is distinct
    # from the sizing-pass sink (``text_truncations`` param) — both are needed:
    # sizing-pass covers the SVG render path (specs cached, not regenerated),
    # and this detection-pass sink covers the json/data render path (sizing
    # pass skips VL rendering). The two are merged below.
    with (
        collect_series_label_truncations() as series_label_truncations,
        collect_text_truncations() as _detection_truncations,
    ):
        for chart_id, (chart, layout_width) in active_charts.items():
            if chart.query_name not in pre_executed_query_names:
                continue
            # Non-VL families (kpi, table, spark_bar, callout) never produce a
            # vega_spec artifact — skip them to avoid an extra render pass.
            if chart.chart_type in NON_ASPECT_RATIO_TYPES:
                continue
            data = chart_results.get(chart_id, [])
            # Spec generation failure must not block the render — omit from vega_specs.
            with contextlib.suppress(Exception):  # noqa: BLE001 — spec failure must not block render
                artifact = render_resolved_chart(
                    chart,
                    data,
                    board.style,
                    width=layout_width,
                )
                if artifact.kind == "vega_spec" and isinstance(artifact.payload, dict):
                    vega_specs[chart_id] = artifact.payload

    # Merge sizing-pass truncations with detection-pass truncations per
    # (surface, authored_field), detection winning on a collision — the two
    # passes can render the same chart at slightly different widths, so a
    # whole-list overwrite could drop a record the other pass didn't produce.
    merged_truncations = dict(text_truncations)
    for chart_id, records in _detection_truncations.items():
        existing = {
            (r.surface, r.authored_field): r
            for r in merged_truncations.setdefault(chart_id, [])
        }
        for r in records:
            existing[(r.surface, r.authored_field)] = r
        merged_truncations[chart_id] = list(existing.values())

    ctx = WarningContext(
        board_spec=board,
        chart_results=chart_results,
        vega_specs=vega_specs,
        table_overflows=table_overflows,
        static_pagination_caps=static_pagination_caps,
        authored_chart_heights=authored_chart_heights,
        series_label_truncations=series_label_truncations,
        text_truncations=merged_truncations,
        endpoint_label_gap_overflows=endpoint_label_gap_overflows,
        chart_truncations=chart_truncations,
        unattributed_truncations=unattributed_truncations,
    )
    return run_all(ctx)


def render(
    board: Board,
    executor: Executor,
    format: str = "svg",
    variables: VariableValues | None = None,
    ignore_codes: set[str] | None = None,
    builtin_variables: VariableValues | None = None,
    max_workers: int | None = None,
    warnings_ignore: frozenset[str] = frozenset(),
    max_rows_per_query: int = NO_ROW_CAP,
    **options: Any,
) -> RenderResult:
    """Render a compiled board.

    Stage: RENDER (Main Entry Point)

    This is the main rendering function. It walks the layout structure,
    renders each chart (triggering lazy query execution), and produces
    output in the requested format.

    Args:
        board: Compiled board to render
        executor: Executor for query execution
        format: Output format (svg, html, png, pdf, terminal, json, text, yaml)
        variables: Variable values for queries
        ignore_codes: Caller-supplied set of warning codes to suppress (CLI seam).
        builtin_variables: Pre-computed built-in variables (e.g. dir-navigation
            context from ``lazy_dir_context``) injected UNDER user variables so
            user-declared variables take precedence.  Computed by callers that
            have a real board file location (render_dashboard); omit for in-memory
            boards or inspect renders.
        warnings_ignore: Project-level warning codes to suppress. Callers resolve
            these before calling render() — typically via ``ProjectSession.warnings_ignore``
            or get_project_warnings_ignore(). Defaults to frozenset() (no suppression).
        max_rows_per_query: Cap on rows embedded per chart in the data-bearing
            formats (json/text/yaml); each truncation is declared in the output
            (``rows_truncated`` record / comment header). Defaults to
            ``NO_ROW_CAP`` (embed all rows). Other formats ignore it.
        **options: Format-specific options
            - background: Background color
            - scale: Scale factor (for png)
            - grid: Show grid overlay (for debugging)
            - controls: Host can re-run queries, so ship the control runtime
            - standalone: Output will be opened with no host, so carry the font
              bytes inline instead of naming /static/fonts/ (html and svg only)

    Returns:
        RenderResult with:
            - output: rendered content (str or bytes)
            - chart_errors: per-chart runtime failures (board still rendered)
            - board_error: post-validation fatal (None when render succeeded)
            - warnings: active (non-suppressed) warnings
            - suppressed_warnings: warnings dropped by any ignore layer

    Raises:
        RenderError: If a board-level invariant is violated before rendering starts
        FormatError: If format is unknown
    """
    # Compile warns on orphans; render hard-fails the empty-layout-with-charts
    # case so the dashboard never silently renders with nothing visible.
    if board.charts and not board.layout.items:
        from dbt_charts.core.diagnostics import ERR_NO_LAYOUT

        chart_list = ", ".join(sorted(board.charts.keys()))
        raise RenderError.from_code(ERR_NO_LAYOUT, charts=chart_list)

    # Trust the normalizer - use pre-computed variable_defaults
    variable_registry = board.variable_registry or {}

    # Merge variables: start with None for all vars, then defaults, then user values
    all_variables: dict[str, Any] = dict.fromkeys(variable_registry)
    all_variables.update(board.variable_defaults)  # Pre-computed by normalizer
    # Parse JSON strings in variables (from URL parameters) and merge
    parsed_variables = parse_variable_json_strings(variables or {})
    merged_variables = {**all_variables, **parsed_variables}

    # Inject caller-supplied built-in variables (e.g. dir-navigation context
    # computed by render_dashboard).  Builtins sit UNDER user-declared
    # variables so merged_variables can shadow any name.
    if builtin_variables is not None:
        merged_variables = {**builtin_variables, **merged_variables}

    # A multiselect is a list on every path. The seed above is `None` for any
    # variable without a default, and markdown/title Jinja reads this dict
    # directly — so without this, `{{ v | join(', ') }}` on an unset multiselect
    # raises and the whole board renders as an error. Queries get the same
    # narrowing from coerce_variable_values; this is the render half.
    merged_variables = normalize_multiselect_values(merged_variables, variable_registry)

    # Board-level precondition: required variables must have a value before any query runs.
    if variable_registry:
        missing = [
            MissingVariable(
                key=key,
                label=var.label,
                description=var.description,
                input_type=var.input,
            )
            for key, var in variable_registry.items()
            if var.required is True
            and variable_value_is_absent(merged_variables.get(key))
        ]
        if missing:
            raise MissingRequiredVariablesError(missing)

    # Resolve max_workers: explicit param → DCT_MAX_WORKERS env var → config default.
    resolved_max_workers = resolve_max_workers(max_workers)

    # Pre-render query execution — authoritative, not a fallback.
    # Queries run BEFORE calculate_data_aware_layout so the sizing pass can
    # use cached results (render-first sizing reads query data from the executor
    # cache without re-executing).
    # Cache-hit pre-pass: queries already in cache are resolved synchronously
    # so they never occupy a worker thread or wait behind slow warehouse misses.
    # Only misses go to the ThreadPoolExecutor.
    # Errors are stored on the executor (executor._query_errors) so that
    # execute_chart() during the render walk raises the stored error
    # instead of re-executing.  The render walk never retries a failed query.
    query_names = collect_all_query_names(board)

    # Partition: resolve hits synchronously, submit only misses to pool.
    # The probe runs twice for a hit (once here, once inside execute_query) but the
    # probe cost — dict lookup + optional duckdb sub-ms read — is negligible vs
    # the worker-slot wait it avoids on a saturated pool with slow warehouse queries.
    cache_miss_names: set[str] = set()
    for name in query_names:
        if executor.is_cached(name, merged_variables):
            executor.execute_query(name, merged_variables)
        else:
            cache_miss_names.add(name)

    execute_queries_parallel(
        executor, cache_miss_names, merged_variables, resolved_max_workers
    )

    # board.resolved_style is trusted here. Compile populated it; if a caller
    # mutated board.theme they must have gone through Board.set_theme(), which
    # re-cascades synchronously. Direct writes to board.theme are not supported.

    # Set auto-link context BEFORE calculate_data_aware_layout because the
    # render-first sizing pass resolves charts (layout_sizing._require_resolved),
    # which needs the context active to synthesize links.  The sizing-pass SVG
    # is cached and reused in the main render pass, so the context must be set here.
    from dbt_charts.core.render.board_links import (
        set_link_context as _set_link_context,  # noqa: PLC0415
    )
    from dbt_charts.core.render.chart.auto_link import (  # noqa: PLC0415
        set_auto_link_context as _set_auto_link_context,
        set_filter_variables_context as _set_filter_variables_context,
    )

    _link_context = options.get("link_context")
    _set_link_context(_link_context)
    _set_auto_link_context(board.auto_link)
    _filter_var_names = (
        frozenset(variable_registry) if variable_registry else frozenset()
    )
    _set_filter_variables_context(_filter_var_names)

    # Per-chart error collector: single append site in render_chart_item.
    # All formats share this collector so callers get chart_errors regardless of format.
    error_collector: list[Diagnostic] = []
    authored_chart_heights: dict[str, float] = {}
    _sizing_truncations: dict[str, list[TextTruncation]] = {}

    def _reset_contexts() -> None:
        _set_link_context(None)
        _set_auto_link_context(False)
        _set_filter_variables_context(frozenset())

    # Narrow first try: only build_resolved_board(). Failures here mean no render
    # work has started, so there is nothing to detect warnings against — return
    # empty lists directly rather than routing through _finalize_warnings.
    # A chart's own resolve failure no longer reaches this except at all: the
    # sizing pass records it per-chart and the tile renders as an error. Only a
    # sizing-pass failure that is not chart-scoped would land here.
    # Calculate layout with data awareness — table heights use actual row counts,
    # and Vega-Lite charts are rendered to get true heights (render-first sizing).
    # Render-first sizing is skipped for non-SVG formats (yaml/json/text) since
    # those formats don't render charts and don't benefit from actual heights.
    # Single-resolution pass: each chart is resolved once and the sizing pass
    # reuses that resolution rather than resolving a second time.
    from dbt_charts.core.render.board_resolve import build_resolved_board

    render_cache: RenderCache
    # Open the sizing-pass sink before build_resolved_board so that VL chart
    # title truncations (apply_title_overflow_to_spec) and callout overflow
    # (height cap) detected during render-first sizing are captured. Callout
    # is cached after the sizing pass; KPI/table/spark_bar re-render in the
    # main pass and are caught by the inner sink below.
    with collect_text_truncations() as _sizing_truncations:
        try:
            resolved_board, render_cache = build_resolved_board(
                board,
                executor,
                merged_variables,
                render_first=format in _SVG_FORMATS,
                authored_slot_heights=authored_chart_heights,
            )
        except DbtChartsError as e:
            _reset_contexts()
            return RenderResult(
                output=None,
                chart_errors=error_collector,
                board_error=e.to_diagnostic(),
                warnings=[],
                suppressed_warnings=[],
            )
        except Exception as e:  # noqa: BLE001
            from dbt_charts.core.diagnostics import ERR_INTERNAL

            _reset_contexts()
            wrapped = RenderError.from_code(ERR_INTERNAL, message=str(e))
            return RenderResult(
                output=None,
                chart_errors=error_collector,
                board_error=wrapped.to_diagnostic(),
                warnings=[],
                suppressed_warnings=[],
            )

    # resolved_board is now a plain ResolvedBoard for the rest of this function.

    # Run warning detectors now that queries are cached, partitioning into
    # active vs suppressed via the union of three ignore layers. TABLE_COLUMNS_OVERFLOW
    # reads real render-time overflow, which only exists once the SVG is rendered —
    # so finalize is a closure recomputed with the populated capture on the SVG path,
    # and with an empty capture for formats that never rasterize a table.
    _per_chart_codes: dict[str, set[str]] = {
        chart_id: set(chart.warnings_ignore)
        for chart_id, chart in board.charts.items()
        if chart.warnings_ignore
    }

    def _finalize_warnings(
        table_overflows: dict[str, TableOverflow],
        text_truncations: dict[str, list[TextTruncation]],
        static_pagination_caps: dict[str, StaticPaginationCap],
        endpoint_label_gap_overflows: dict[str, EndpointLabelGapOverflow],
    ) -> tuple[list[Diagnostic], list[Diagnostic]]:
        all_warnings = _collect_render_warnings(
            resolved_board,
            authored_chart_heights,
            executor,
            merged_variables,
            table_overflows,
            text_truncations,
            static_pagination_caps,
            endpoint_label_gap_overflows,
        )
        return _partition_warnings(
            all_warnings,
            cli_codes=ignore_codes or set(),
            project_codes=set(warnings_ignore),
            per_chart_codes=_per_chart_codes,
        )

    # Warnings are finalized once per path: json/text/yaml (below) and error
    # paths use an empty capture since they never rasterize a table; the SVG
    # render finalizes afterward with the real overflow capture. No path runs the
    # detectors — or rebuilds vega specs — more than once.

    # Resolve SVG canvas background: API override wins, otherwise use the
    # cascaded board background (theme default or authored override, already merged).
    override = options.get("background")
    if override is not None:
        background = None if override == "transparent" else override
    else:
        resolved_bg = resolved_board.style.background
        background = None if resolved_bg == "transparent" else resolved_bg

    # Second try: data-format branch and SVG render. resolved_board is guaranteed
    # bound here, so _finalize_warnings can run on error paths too.
    try:
        # Data-bearing formats: skip SVG rendering entirely — walk layout tree directly.
        if format in _DATA_FORMATS:
            output = _data_format_renderer(format)(
                board,
                executor,
                merged_variables,
                error_collector=error_collector,
                max_rows_per_query=max_rows_per_query,
            )
            _active, _suppressed = _finalize_warnings({}, {}, {}, {})
            return RenderResult(
                output=output,
                chart_errors=error_collector,
                warnings=_active,
                suppressed_warnings=_suppressed,
            )

        # Render the canonical SVG once; output formats only wrap or convert it.
        # The capture sinks record each table's real post-cascade column overflow,
        # all text truncations, the static-export page cap, and any endpoint-label
        # rail that couldn't fit its intended gap, so warnings can be finalized
        # against what actually rendered.
        _table_overflows: dict[str, TableOverflow] = {}
        _text_truncations: dict[str, list[TextTruncation]] = {}
        _static_pagination_caps: dict[str, StaticPaginationCap] = {}
        _endpoint_label_gap_overflows: dict[str, EndpointLabelGapOverflow] = {}
        grid_enabled = options.get("grid", False)
        margins_enabled = options.get("margins", False)
        # Interactivity is opt-in and only meaningful on a host that can re-run
        # the queries behind a control (`dct serve`, Cloud, Playground). The
        # controls are drawn either way — that is what keeps an export and a
        # live board the same picture — so what this switches on is the payload
        # a runtime needs and an artifact cannot use.
        # An artifact nobody serves has to carry its own fonts: `/static/fonts/…`
        # is root-relative and resolves only while a server is running, so a file
        # on disk, in a mailbox or in a bucket paints in fallback type at wrap
        # points measured for a font it isn't using. `standalone` is the caller
        # saying the output will be opened without a host — `dct render` writing
        # files sets it; a live host does not. `svg` is included because it is what
        # `dct render` writes by default, and a `.svg` opened from disk needs its
        # fonts exactly as much as an HTML page does. The visual goldens render
        # through `format="svg"` too but never set the flag, so they stay on URLs
        # and the golden tree carries no payloads.
        #
        # png/pdf are excluded whatever the flag says: they go through resvg, which
        # binds fonts from the registered font directory and never reads @font-face,
        # so base64 in the SVG it rasterizes would be bytes nothing reads.
        embed_fonts = format in ("html", "svg") and bool(options.get("standalone"))
        with (
            collect_table_overflows() as _table_overflows,
            collect_text_truncations() as _text_truncations,
            collect_static_pagination_caps() as _static_pagination_caps,
            collect_endpoint_label_gap_overflows() as _endpoint_label_gap_overflows,
            collect_painted_italic_families(),
            interactive_controls(options.get("controls", False)),
        ):
            svg_content = render_board_svg(
                resolved_board,
                executor,
                merged_variables,
                background,
                grid_enabled,
                render_cache=render_cache,
                margins=margins_enabled,
                error_collector=error_collector,
                embed_fonts=embed_fonts,
            )
    except DbtChartsError as e:
        # Board-level fatal: a render-domain code escaped chart isolation
        # (e.g. ERR_NO_LAYOUT, MissingRequiredVariablesError). Surface as
        # board_error so callers see the structured code unwrapped.
        _reset_contexts()
        # Render failed before a table could rasterize: finalize with an empty
        # capture so detector warnings still surface alongside the board error.
        _active, _suppressed = _finalize_warnings({}, {}, {}, {})
        return RenderResult(
            output=None,
            chart_errors=error_collector,
            board_error=e.to_diagnostic(),
            warnings=_active,
            suppressed_warnings=_suppressed,
        )
    except Exception as e:  # noqa: BLE001
        from dbt_charts.core.diagnostics import ERR_INTERNAL

        _reset_contexts()
        wrapped = RenderError.from_code(ERR_INTERNAL, message=str(e))
        _active, _suppressed = _finalize_warnings({}, {}, {}, {})
        return RenderResult(
            output=None,
            chart_errors=error_collector,
            board_error=wrapped.to_diagnostic(),
            warnings=_active,
            suppressed_warnings=_suppressed,
        )
    finally:
        _reset_contexts()

    # The SVG render is done — finalize warnings against the real table overflow,
    # text truncations, and static-pagination cap captured across both passes.
    # The render pass (_text_truncations) wins per chart-id when both passes
    # record the same chart (e.g. spark_bar). All SVG-family outputs below derive
    # from this same svg_content, so they share this capture.
    render_warnings, suppressed_warnings = _finalize_warnings(
        _table_overflows,
        {**_sizing_truncations, **_text_truncations},
        _static_pagination_caps,
        _endpoint_label_gap_overflows,
    )

    # Convert to requested format
    if format == "svg":
        return RenderResult(
            output=svg_content,
            chart_errors=error_collector,
            warnings=render_warnings,
            suppressed_warnings=suppressed_warnings,
        )

    elif format == "html":
        # Exclude keys that are already positional args to to_html — specifically
        # 'background', which callers pass as an SVG canvas override but is not
        # a to_html option (the HTML page background comes from resolved_style).
        html_options = {k: v for k, v in options.items() if k != "background"}
        html_output = to_html(
            svg_content,
            **html_options,
        )
        return RenderResult(
            output=html_output,
            chart_errors=error_collector,
            warnings=render_warnings,
            suppressed_warnings=suppressed_warnings,
        )

    elif format == "png":
        png_scale = options.get("scale")
        if png_scale is None:
            png_scale = get_rendering_config().png.scale
        return RenderResult(
            output=to_png(strip_pagination_chrome(svg_content), png_scale),
            chart_errors=error_collector,
            warnings=render_warnings,
            suppressed_warnings=suppressed_warnings,
        )

    elif format == "pdf":
        return RenderResult(
            output=to_pdf(strip_pagination_chrome(svg_content)),
            chart_errors=error_collector,
            warnings=render_warnings,
            suppressed_warnings=suppressed_warnings,
        )

    elif format == "terminal":
        return RenderResult(
            output=_to_terminal(
                board, executor, merged_variables, resolved_board.style, **options
            ),
            chart_errors=error_collector,
            warnings=render_warnings,
            suppressed_warnings=suppressed_warnings,
        )

    else:
        from dbt_charts.core.diagnostics import ERR_FORMAT_UNSUPPORTED

        raise FormatError.from_code(ERR_FORMAT_UNSUPPORTED, format=format)


def _to_terminal(
    board: Board,
    executor: Executor,
    variables: VariableValues,
    resolved_style: "ResolvedStyle",
    **options: Any,
) -> str:
    """Render board to terminal output.

    Args:
        board: Board to render
        executor: Executor for query execution
        variables: Variable values for queries
        resolved_style: Board-scoped resolved style (from resolved_board.style).
        **options: Terminal-specific options
            - width: Terminal width in characters
            - height: Terminal height in characters
            - colors: Whether to use ANSI colors (default: True)

    Returns:
        Terminal-formatted string
    """
    from dbt_charts.core.render.terminal import render_board_terminal

    return render_board_terminal(
        board,
        executor,
        variables=variables,
        width=options.get("width"),
        height=options.get("height"),
        colors=options.get("colors", True),
        resolved_style=resolved_style,
        **{k: v for k, v in options.items() if k not in ("width", "height", "colors")},
    )


__all__ = [
    "render",
]
