"""ERR-* and WARN-* codes for the render domain.

Error codes: KPI multirow, bar duplicate rows, map key mismatch, format
unsupported, no layout, input invalid, Vega-Lite unsupported type, histogram
non-numeric, histogram pre-aggregated, label/ticks validation, percent range,
emitter not found, labels field not found, scale domain, concat overshoot,
chart painted no marks, pie null theta, pie negative theta, multiples +
endpoint labels, mirror + endpoint labels, multiples + data_table,
multiples independent-scale + mirror.

Warning codes: every render-time detector code, declared here (not in the
detector modules, which sit above this leaf) so the registry is complete on
import of core.diagnostics. Detectors import their constants back from this
package.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics.registry import REGISTRY, ErrorCode, WarningCode

ERR_KPI_MULTIROW = REGISTRY.register(
    ErrorCode(
        code="ERR-KPI-MULTIROW",
        domain="render",
        title="KPI query returned more than one row",
        message_template=(
            "KPI chart {chart_id!r} expects exactly 1 row, got {row_count}. "
            "Use a query that returns a single row (e.g. SELECT SUM(...) or LIMIT 1)."
        ),
        doc=(
            "Fired when a KPI chart's query returns more than one row. KPI charts "
            "display exactly one value; use a query that returns a single row "
            "(e.g. SELECT SUM(...) or LIMIT 1)."
        ),
        docs_topic="charts",
    )
)

ERR_BAR_DUPLICATE_ROWS = REGISTRY.register(
    ErrorCode(
        code="ERR-BAR-DUPLICATE-ROWS",
        domain="render",
        title="Bar chart data has duplicate rows that require aggregation",
        message_template=(
            "{chart_type} chart {chart_id!r} requires pre-aggregated data "
            "with at most one row per plotted key ({field_list}). "
            "Found duplicate rows for {duplicate_preview}. "
            "Aggregate in the query before rendering."
        ),
        doc=(
            "Fired when a bar, horizontal-bar, or grouped-bar chart receives data "
            "with more than one row per plotted key. These chart types require "
            "pre-aggregated data; aggregate in the query before rendering."
        ),
        docs_topic="charts",
    )
)

ERR_COLOR_NULL_SERIES = REGISTRY.register(
    ErrorCode(
        code="ERR-COLOR-NULL-SERIES",
        domain="render",
        title="Color column contains NULL values",
        message_template=(
            "{chart_type} chart {chart_id!r} has {null_rows} row(s) with a NULL "
            "value in its color column {color_field!r}. A NULL category cannot "
            "be painted or named in the legend, but its rows still occupy "
            "stack space — the chart would read as bars floating off the "
            "baseline. Give every row a category in the query "
            "(e.g. COALESCE({color_field}, 'Unknown'))."
        ),
        doc=(
            "Fired when the column bound to a chart's `color` channel contains "
            "NULL values. The renderer cannot assign a NULL a palette slot or a "
            "legend entry, so the series would consume stack space while being "
            "invisible and unattributable. Fix the grain in the query — the most "
            "common cause is a `CASE` with no `ELSE`, or an `ELSE` that passes "
            "the raw column through unchanged."
        ),
        summary="Fired when a chart's color column contains NULL values.",
        docs_topic="charts",
    )
)

ERR_PIE_NULL_THETA = REGISTRY.register(
    ErrorCode(
        code="ERR-PIE-NULL-THETA",
        domain="render",
        title="Pie chart theta column contains NULL values",
        message_template=(
            "Pie chart {chart_id!r} has {null_rows} row(s) with a NULL value "
            "in its theta column {theta_field!r}. A pie slice can't represent "
            "a missing value. Filter the null rows or give them a real number "
            "in the query (e.g. COALESCE({theta_field}, 0))."
        ),
        doc=(
            "Fired when the column bound to a pie or donut chart's `theta` "
            "channel contains NULL values. A pie slice's angle comes directly "
            "from theta, so a NULL cannot be drawn or labeled — fix the grain "
            "in the query instead of letting the renderer guess a value."
        ),
        summary="Fired when a pie chart's theta column contains NULL values.",
        docs_topic="charts",
    )
)

ERR_PIE_NEGATIVE_THETA = REGISTRY.register(
    ErrorCode(
        code="ERR-PIE-NEGATIVE-THETA",
        domain="render",
        title="Pie chart theta column contains a negative value",
        message_template=(
            "Pie chart {chart_id!r} has {negative_rows} row(s) with a "
            "negative value in its theta column {theta_field!r}. A pie slice "
            "can't represent a negative share of the whole. Filter or "
            "transform the value in the query."
        ),
        doc=(
            "Fired when the column bound to a pie or donut chart's `theta` "
            "channel contains a negative value. A pie's slices are angles "
            "summing to a full circle; a negative theta has no geometric "
            "meaning, so it must be filtered or transformed in the query."
        ),
        summary=("Fired when a pie chart's theta column contains a negative value."),
        docs_topic="charts",
    )
)

ERR_MAP_LOOKUP_KEY_MISMATCH = REGISTRY.register(
    ErrorCode(
        code="ERR-MAP-LOOKUP-KEY-MISMATCH",
        domain="render",
        title="Map chart cannot join on mismatched key format",
        message_template=(
            "Map chart {chart_id!r} cannot join lookup field {lookup_field!r} "
            "to geo source {geo_source!r} on key {geo_key!r}: the geo source "
            "expects {expected_format} keys like {expected_samples}, but the "
            "query returned values like {query_samples}."
        ),
        doc=(
            "Fired when a map chart's lookup field values do not match the format "
            "expected by the geo source. Check that the lookup field uses the same "
            "key format (e.g. FIPS codes, ISO country codes) as the geo source."
        ),
        docs_topic="charts",
    )
)

ERR_FORMAT_UNSUPPORTED = REGISTRY.register(
    ErrorCode(
        code="ERR-FORMAT-UNSUPPORTED",
        domain="render",
        title="Unknown render format",
        message_template="Unknown format: {format!r}",
        doc=(
            "Fired when a render verb is called with an output format that is not "
            "supported. Check the supported formats in the CLI reference."
        ),
        docs_topic="errors",
    )
)

ERR_RESOLVED_PIE_WIDTH_MISMATCH = REGISTRY.register(
    ErrorCode(
        code="ERR-RESOLVED-PIE-WIDTH-MISMATCH",
        domain="render",
        title="Resolved pie width does not match its render slot",
        message_template=(
            "Resolved pie {chart_id!r} was finalized at width {resolved_width}, "
            "not {render_width}. Resolve the chart again for the target slot."
        ),
        doc=(
            "Fired when a resolved pie is rendered at a different width from the "
            "one used to finalize its label and attached-table layout. Resolve the "
            "chart again with the actual target width before rendering."
        ),
        docs_topic="charts",
    )
)

ERR_RESOLVED_PIE_DATA_MISMATCH = REGISTRY.register(
    ErrorCode(
        code="ERR-RESOLVED-PIE-DATA-MISMATCH",
        domain="render",
        title="Resolved pie rows do not match its recording",
        message_template=(
            "Resolved pie {chart_id!r} was finalized from different query rows. "
            "Resolve the chart and record its data in the same emission."
        ),
        doc=(
            "Fired when replay data differs from the rows used to finalize pie "
            "label and attached-table policy. Resolved board artifacts and recordings "
            "must come from the same emission."
        ),
        docs_topic="charts",
    )
)

ERR_DUPLICATE_CHART_ID = REGISTRY.register(
    ErrorCode(
        code="ERR-DUPLICATE-CHART-ID",
        domain="render",
        title="Two charts share an id across nested boards",
        message_template=(
            "Two charts share the id {chart_id!r} across nested boards, which the "
            "flat {format!r} format cannot represent without dropping one. "
            "Rename one of them, or use --format json, which keeps the layout "
            "nesting."
        ),
        doc=(
            "Chart ids are unique within a board but not across a board tree: two "
            "imported partials, including the same partial imported twice, can "
            "declare the same id. The flat output formats key charts by id, so a "
            "collision would silently drop every chart but the last. Rename the "
            "colliding chart, or render with a format that preserves the layout."
        ),
        docs_topic="errors",
    )
)

ERR_NO_LAYOUT = REGISTRY.register(
    ErrorCode(
        code="ERR-NO-LAYOUT",
        domain="render",
        title="Board defines charts but has no layout",
        message_template=(
            "Board defines charts ({charts}) but no layout — would render with no visible "
            "charts. Add a `rows:`/`cols:`/`grid:`/`tabs:` block that references them."
        ),
        doc=(
            "Fired when a board defines charts but no layout block "
            "(rows/cols/grid/tabs). Without a layout, the board would render with "
            "no visible charts. Add a layout block that references the charts."
        ),
        docs_topic="layout",
    )
)

ERR_INPUT_INVALID = REGISTRY.register(
    ErrorCode(
        code="ERR-INPUT-INVALID",
        domain="render",
        title="Invalid render input",
        message_template="{message}",
        doc=(
            "Fired when the render layer receives input data that fails a "
            "structural check. The message carries the specific validation error."
        ),
        docs_topic="charts",
    )
)

ERR_VEGA_LITE_UNSUPPORTED_TYPE = REGISTRY.register(
    ErrorCode(
        code="ERR-VEGA-LITE-UNSUPPORTED-TYPE",
        domain="render",
        title="Chart type does not render to a Vega-Lite spec",
        message_template=(
            "Chart type {chart_type!r} does not render to a Vega-Lite spec."
        ),
        doc=(
            "Fired when a chart type is asked to render a Vega-Lite spec but does "
            "not support that output format. Use a Vega-Lite-compatible chart type "
            "or choose a different output format."
        ),
        docs_topic="charts",
    )
)

# WHY: Histogram requires a numeric x field for binning. A missing or non-numeric
# x field would silently pass bin:True to VL on a nominal column (garbage output)
# or crash vl_convert on a null field.
ERR_HISTOGRAM_NON_NUMERIC = REGISTRY.register(
    ErrorCode(
        code="ERR-HISTOGRAM-NON-NUMERIC",
        domain="render",
        title="Histogram x field is not numeric",
        message_template=(
            "Histogram chart {chart_id!r} requires a numeric x field for binning, "
            "but {field!r} is {vl_type!r}. Use a quantitative (numeric) column as x."
        ),
        doc=(
            "Fired when a histogram chart's x field is not numeric (quantitative). "
            "Histograms bin values into ranges, which requires a numeric column. "
            "Use a quantitative column as x."
        ),
        docs_topic="charts",
    )
)

# WHY: see validate_raw_rows_for_histogram's docstring (render/chart/validation.py)
# for the full reasoning behind the two-condition check this code reports.
ERR_HISTOGRAM_PREAGGREGATED = REGISTRY.register(
    ErrorCode(
        code="ERR-HISTOGRAM-PREAGGREGATED",
        domain="render",
        title="Histogram data looks pre-aggregated, not raw rows",
        message_template=(
            "Histogram chart {chart_id!r} received data where {field!r} forms "
            "a gapless run of whole numbers alongside unused numeric column(s) "
            "{count_fields} — this looks like pre-aggregated data (one row "
            "per bucket, e.g. `GROUP BY {field}`), not the raw, ungrouped "
            "rows a histogram bins itself. Vega-Lite would bin and count "
            "these already-counted rows again, silently discarding whatever "
            "real measure they carry. Use `type: bar` with `x: {field}` and "
            "one of {count_fields} as `y` to chart pre-aggregated data instead."
        ),
        doc=(
            "Fired when a histogram chart receives data where its x field forms "
            "a gapless run of whole numbers alongside an unused numeric column "
            "— the shape of already-aggregated, one-row-per-bucket data. "
            "Histograms rely on Vega-Lite's own binning + counting over raw, "
            "ungrouped rows; pre-aggregated data silently produces a wrong, "
            "miscounted histogram instead of erroring. Aggregate in the query "
            "and use `type: bar` instead."
        ),
        docs_topic="charts",
    )
)

ERR_LABEL_VALUES_NOT_TEMPORAL = REGISTRY.register(
    ErrorCode(
        code="ERR-LABEL-VALUES-NOT-TEMPORAL",
        domain="render",
        title="labels.values requires a temporal x-axis",
        # {cause}/{remedy} are supplied per raise site rather than hardcoded,
        # because two unrelated conditions share this code: the x-axis values
        # aren't valid ISO dates (a data problem — fixable by using ISO dates),
        # and a horizontal bar's categorical axis never honors labels.values at
        # all regardless of date format (an orientation problem — no date fix
        # applies). A single fixed message asserting "your dates aren't ISO"
        # would be false on the second path.
        message_template="style.axis_x.labels.values isn't usable on {field!r}: {cause}. {remedy}",
        doc=(
            "Fired when `style.axis_x.labels.values` is set on an x-axis that can't "
            "honor it — either the x-axis values aren't valid ISO dates or datetime "
            "objects, or the chart's horizontal-bar categorical axis never applies "
            "label filtering regardless of date format."
        ),
        summary="Fired when `labels.values` is set on an axis that can't honor it.",
        docs_topic="charts",
    )
)

ERR_TICKS_STEP_NOT_QUANTITATIVE = REGISTRY.register(
    ErrorCode(
        code="ERR-TICKS-STEP-NOT-QUANTITATIVE",
        domain="render",
        title="a bare ticks.step requires a quantitative x-axis",
        message_template=(
            "style.axis_x.ticks.step without ticks.time_unit is a numeric tick "
            "interval, but {field!r} resolved to a {vl_type!r} scale. {remedy}"
        ),
        doc=(
            "Fired when `style.axis_x.ticks.step` is set without "
            "`ticks.time_unit` on an x-axis that does not resolve to a "
            "quantitative scale. A bare `step` is the numeric cadence lever "
            "(it emits Vega-Lite's `tickMinStep`) and only a quantitative "
            "scale has a numeric tick interval. On a temporal axis, author "
            "`ticks.time_unit` alongside `step` to name a calendar cadence. "
            "On a discrete axis (ordinal or nominal) there is no tick "
            "interval to set — remove `ticks.step`. A horizontal bar is the "
            "case worth calling out: its `axis_x` is the categorical axis and "
            "its measure is `axis_y`, so `orientation: vertical` is usually "
            "what the author wanted."
        ),
        summary="Fired when a bare `ticks.step` is set on a non-quantitative x-axis.",
        docs_topic="charts",
    )
)

ERR_TICKS_INTERVAL_NOT_TEMPORAL = REGISTRY.register(
    ErrorCode(
        code="ERR-TICKS-INTERVAL-NOT-TEMPORAL",
        domain="render",
        title="ticks.time_unit requires a continuous temporal x-axis",
        message_template=(
            "style.axis_x.ticks.time_unit requires a continuous temporal "
            "x-axis, but {field!r} resolved to a {vl_type!r} scale. Force a "
            "continuous scale with axis_x.type: temporal (or "
            "axis_x.time_unit: none), or remove ticks.time_unit."
        ),
        doc=(
            "Fired when `style.axis_x.ticks.time_unit` is set but the x-axis "
            "does not resolve to a continuous temporal scale. Force a continuous "
            "scale with `axis_x.type: temporal` (or `axis_x.time_unit: none`), "
            "or remove `ticks.time_unit`."
        ),
        summary="Fired when `ticks.time_unit` is set but the x-axis doesn't resolve to a continuous temporal scale.",
        docs_topic="charts",
    )
)

ERR_LABEL_VALUES_INVALID_DATE = REGISTRY.register(
    ErrorCode(
        code="ERR-LABEL-VALUES-INVALID-DATE",
        domain="render",
        title="labels.values entry is not a valid ISO date",
        message_template=(
            "style.axis_x.labels.values entries must be ISO date or datetime "
            "strings (e.g. '2024-01-01') or date/datetime objects; got {value!r}."
        ),
        doc=(
            "Fired when an entry in `style.axis_x.labels.values` cannot be parsed "
            "as an ISO date or datetime. Use ISO date strings (e.g. '2024-01-01') "
            "or date/datetime objects."
        ),
        summary="Fired when an axis label value can't be parsed as an ISO date or datetime.",
        docs_topic="charts",
    )
)

ERR_PERCENT_RANGE = REGISTRY.register(
    ErrorCode(
        code="ERR-PERCENT-RANGE",
        domain="render",
        title="Percent format received a 0-100-shaped value instead of a ratio",
        message_template=(
            "Value {value!r} passed to percent format {format_spec!r} looks "
            "0-100-shaped, but percent formats expect a 0-1 ratio (0.182, not "
            "18.2). To fix: divide by 100 in SQL so the value is a ratio, or "
            "switch to the `percent_number`/`percent_number_delta` formats if "
            "the value is already in the 0-100 scale (e.g. 18.2 means 18.2%)."
        ),
        doc=(
            "Fired when a percent format receives a value that looks like it is "
            "already in the 0-100 scale rather than the 0-1 ratio scale that "
            "percent formats expect. Divide by 100 in SQL so the value is a ratio, "
            "or switch to a `percent_number` format."
        ),
        docs_topic="charts",
    )
)

ERR_NUMERAL_EXPR_EMPTY_SPEC = REGISTRY.register(
    ErrorCode(
        code="ERR-NUMERAL-EXPR-EMPTY-SPEC",
        domain="render",
        title="Empty format spec cannot build a numeral Vega expression",
        message_template=(
            "numeral_vega_expr() requires a non-empty format_spec. format_d3 "
            "treats an empty spec as a distinct 'no d3 formatting' path (the "
            "bare Python value) that a Vega expression cannot reproduce "
            "byte-for-byte."
        ),
        doc=(
            "Fired when numeral_vega_expr() is called with an empty format_spec. "
            "format_d3 short-circuits an empty spec to the bare Python value, "
            "bypassing d3 entirely — a Vega expression cannot reproduce that "
            "byte-for-byte (Python and JS do not stringify numbers identically), "
            "so building the expression is rejected rather than silently "
            "diverging. This indicates an engine bug: callers should always "
            "resolve a concrete d3 spec before reaching this emitter."
        ),
        docs_topic="errors",
    )
)

ERR_EMITTER_NOT_FOUND = REGISTRY.register(
    ErrorCode(
        code="ERR-EMITTER-NOT-FOUND",
        domain="render",
        title="No emitter registered for the resolved chart type",
        message_template=(
            "No emitter registered for resolved chart type {resolved_type!r}. "
            "This indicates an engine bug — the normalizer should have rejected "
            "this chart before it reached render."
        ),
        doc=(
            "Fired when the render engine cannot find an emitter for the resolved "
            "chart type. This indicates an engine bug; the normalizer should have "
            "rejected this chart before it reached render."
        ),
        docs_topic="errors",
    )
)

ERR_STACKED_MIDDLE_ALIGNED_LABELS = REGISTRY.register(
    ErrorCode(
        code="ERR-STACKED-MIDDLE-ALIGNED-LABELS",
        domain="render",
        title="labels.position: middle_aligned is not meaningful on a stacked bar",
        message_template=(
            "labels.position 'middle_aligned' aligns every bar's label to one "
            "shared height, which has no meaning for the segments of a stacked "
            "bar. Use 'middle' to center each label in its own segment, or "
            "'top'/'bottom' to pin it to a segment edge."
        ),
        doc=(
            "Fired when `labels.position: middle_aligned` is set on a stacked "
            "bar. `middle_aligned` places every label at a single common height "
            "(the mean bar height, halved) so a row of labels reads as one line "
            "— a whole-bar idea with no per-segment reading. Stacked segments "
            "each need their own center: use `middle`."
        ),
        summary=(
            "Fired when `labels.position: middle_aligned` is set on a stacked bar."
        ),
        docs_topic="charts",
    )
)

ERR_LABELS_FIELD_NOT_FOUND = REGISTRY.register(
    ErrorCode(
        code="ERR-LABELS-FIELD-NOT-FOUND",
        domain="render",
        title="labels.field names a column not in the query result",
        message_template=(
            "labels.field {field!r} names a column not present in the data. "
            "Available columns: {available}."
        ),
        doc=(
            "Fired when `labels.field` names a column that is not present in "
            "the query result. Check the column name against the actual columns "
            "returned by the query."
        ),
        summary="Fired when `labels.field` names a column that isn't present in the query result.",
        docs_topic="charts",
    )
)

# WHY: an authored 2-element scale.domain only makes sense against a continuous
# (temporal/quantitative) x scale. On an ordinal/nominal (band) x scale
# Vega-Lite reads a 2-element domain as exactly two category values,
# collapsing every mark onto the first one.
ERR_SCALE_DOMAIN_REQUIRES_CONTINUOUS_X = REGISTRY.register(
    ErrorCode(
        code="ERR-SCALE-DOMAIN-REQUIRES-CONTINUOUS-X",
        domain="render",
        title="axis_x.scale.domain requires a continuous x-axis scale",
        message_template=(
            "Chart {chart_id!r}: axis_x.scale.domain is set, but the x-axis "
            "resolved to a {vl_type!r} (categorical) scale, not a continuous "
            "one. An explicit [low, high] domain only extends a continuous "
            "scale — on a categorical scale Vega-Lite reads it as exactly two "
            "category values, collapsing every mark onto the first one. If "
            "the x field is a date, add `axis_x.scale.type: temporal` to "
            "force a continuous temporal scale."
        ),
        doc=(
            "Fired when `axis_x.scale.domain` is set but the x-axis resolves to "
            "a categorical (ordinal/nominal) scale rather than a continuous one. "
            "An explicit [low, high] domain only extends a continuous scale; on a "
            "categorical scale Vega-Lite reads it as exactly two category values. "
            "Add `axis_x.scale.type: temporal` to force a continuous temporal scale "
            "if needed."
        ),
        summary="Fired when an explicit x-axis domain is set but the x-axis resolves to a categorical scale.",
        docs_topic="charts",
    )
)

ERR_CONCAT_OVERSHOOT_NONPOSITIVE = REGISTRY.register(
    ErrorCode(
        code="ERR-CONCAT-OVERSHOOT-NONPOSITIVE",
        domain="render",
        title="Overshoot correction produced a non-positive pane width",
        message_template=(
            "Overshoot correction produced a non-positive pane width "
            "({new_w:.1f}px): pane width {orig_w:.1f}px minus overshoot "
            "{overshoot:.1f}px. The chart content (title, subtitle, axis labels, "
            "series labels, or legend) is wider than the available canvas "
            "({target_width:.1f}px)."
        ),
        doc=(
            "Fired when the overshoot correction algorithm for a concatenated "
            "layout produces a non-positive pane width. The chart content (title, "
            "subtitle, axis labels, series labels, or legend) is wider than the "
            "available canvas. Series labels come from the column bound to "
            "`color:`, and are the usual cause when that column holds long text."
        ),
        docs_topic="charts",
    )
)

ERR_BOARD_ARTIFACT_INVALID = REGISTRY.register(
    ErrorCode(
        code="ERR-BOARD-ARTIFACT-INVALID",
        domain="render",
        title="Resolved-board artifact does not match the expected schema",
        message_template=(
            "Board artifact is invalid: {detail}. It may have been produced by "
            "an incompatible dct version, hand-edited, or truncated. Re-emit it "
            "with `dct artifact emit`."
        ),
        doc=(
            "Fired when a resolved-board artifact fails to validate against "
            "`ResolvedBoard` while loading it for replay. The artifact is the "
            "published, versioned contract a resolved board serializes to — this "
            "means the file is not a valid instance of that contract."
        ),
        docs_topic="errors",
    )
)

ERR_BOARD_RECORDING_INVALID = REGISTRY.register(
    ErrorCode(
        code="ERR-BOARD-RECORDING-INVALID",
        domain="render",
        title="Board recording sidecar does not match the expected schema",
        message_template=(
            "Board recording is invalid: {detail}. It may have been produced by "
            "an incompatible dct version, hand-edited, or truncated. Re-emit it "
            "with `dct artifact emit`."
        ),
        doc=(
            "Fired when a board recording sidecar fails to validate against "
            "`BoardRecording` while loading it for replay."
        ),
        docs_topic="errors",
    )
)

ERR_BOARD_RECORDING_MISMATCH = REGISTRY.register(
    ErrorCode(
        code="ERR-BOARD-RECORDING-MISMATCH",
        domain="render",
        title="Board recording does not match the artifact it was replayed against",
        message_template=(
            "Board recording does not match this artifact: {detail} The artifact "
            "and its recording must come from the same `dct artifact emit` run."
        ),
        doc=(
            "Fired when replaying a resolved-board artifact against a recording "
            "that either lacks rows for one of the artifact's queries, or "
            "recorded them under different variable values. Both mean the "
            "artifact and recording came from different emits (or a truncated "
            "one) — replaying anyway would render an empty or wrong chart that "
            "looks like real data."
        ),
        docs_topic="errors",
    )
)

ERR_CHART_PAINTED_NO_MARKS = REGISTRY.register(
    ErrorCode(
        code="ERR-CHART-PAINTED-NO-MARKS",
        domain="render",
        title="Chart received rows but painted no marks",
        message_template=(
            "Chart {chart_id!r} received {row_count} row(s) but every mark it drew "
            "has zero width or height — check whether the x/y fields and scale "
            "types match the data's actual shape."
        ),
        doc=(
            "Fired when a plotting-family chart's query returns at least one row "
            "but the rendered SVG contains no mark with visible extent — every "
            "bar, line, area, point, wedge, or shape it drew is degenerate. "
            "`WARN-QUERY-RETURNED-ZERO-ROWS` covers the honest empty case (no "
            "rows); this covers the dishonest one — rows arrived, the renderer "
            "just didn't paint anything visible with them."
        ),
        docs_topic="charts",
    )
)

ERR_MULTIPLES_ENDPOINT_LABELS = REGISTRY.register(
    ErrorCode(
        code="ERR-MULTIPLES-ENDPOINT-LABELS",
        domain="render",
        title="multiples cannot be combined with endpoint labels",
        message_template=(
            "Chart {chart_id!r}: multiples cannot be combined with endpoint "
            "labels — the endpoint-label rail names series for a single "
            "panel, and a faceted chart has no single panel for it to sit "
            "beside. Set style.endpoint_labels.visible: false on this chart "
            "to keep the small multiples, or remove multiples to keep the "
            "labels."
        ),
        doc=(
            "Fired when a chart authors `multiples:` while its endpoint-label "
            "rail is explicitly switched on. The rail names series for one "
            "panel; a faceted chart has no single panel for it to sit beside. "
            "The shipped default switches the rail off wherever `multiples:` "
            "is set — a legend above the panels names the series instead — so "
            "this fires only where the rail was asked for by name. Turn off "
            "`style.endpoint_labels.visible` to keep the small multiples, or "
            "remove `multiples:` to keep the labels."
        ),
        docs_topic="charts",
    )
)

ERR_MIRROR_ENDPOINT_LABELS = REGISTRY.register(
    ErrorCode(
        code="ERR-MIRROR-ENDPOINT-LABELS",
        domain="render",
        title="axis_y.mirror cannot be combined with endpoint labels",
        message_template=(
            "Chart {chart_id!r}: axis_y.mirror is not supported together "
            "with endpoint labels — the endpoint-label rail occupies the "
            "opposite edge. Use one or the other on this chart."
        ),
        doc=(
            "Fired when a chart authors (or its theme sets) "
            "`style.axis_y.mirror` while its endpoint-label rail is also "
            "visible. Both want the opposite edge from the chart's primary "
            "y-axis — the mirrored scale and the label rail can't share it. "
            "Distinct from ERR-MULTIPLES-ENDPOINT-LABELS: this code fires "
            "when the chart has no `multiples:` at all, so `axis_y.mirror` "
            "is the field actually responsible for the collision; a "
            "`multiples:` grid's collision (even one that also happens to "
            "auto-derive a both-edge axis internally) is reported as "
            "ERR-MULTIPLES-ENDPOINT-LABELS instead, since `multiples:` is "
            "the field the author wrote."
        ),
        summary=(
            "Fired when a chart authors (or its theme sets) "
            "`style.axis_y.mirror` while its endpoint-label rail is also "
            "visible."
        ),
        docs_topic="charts",
    )
)

ERR_MIRROR_MULTI_SERIES = REGISTRY.register(
    ErrorCode(
        code="ERR-MIRROR-MULTI-SERIES",
        domain="render",
        title="axis_y.mirror requires a single y field",
        message_template=(
            "Chart {chart_id!r}: axis_y.mirror is not supported on multi-series "
            "charts (y = {y}) — a mirrored axis restates one shared y-scale, "
            "and folded measures have no single scale to restate. Collapse "
            "`y:` to one field, or drop `style.axis_y.mirror`."
        ),
        doc=(
            "Fired when a chart carries a list-valued `y:` while "
            "`style.axis_y.mirror` is on. Mirror draws the same y-scale on both "
            "edges of a wide chart, which only means something when there is "
            "exactly one measure scale to draw. Reported at render rather than "
            "by `dct validate` because mirror is cascade-resolved: a theme "
            "layer can turn it on for a chart that never authored it, so the "
            "combination is not visible on the authored chart alone."
        ),
        summary=(
            "Fired when a chart with a list-valued `y:` also has "
            "`style.axis_y.mirror` on, from either the chart or its theme."
        ),
        docs_topic="charts",
    )
)

ERR_MULTIPLES_DATA_TABLE = REGISTRY.register(
    ErrorCode(
        code="ERR-MULTIPLES-DATA-TABLE",
        domain="render",
        title="multiples cannot be combined with a chart data_table",
        message_template=(
            "Chart {chart_id!r}: multiples is not supported together with a "
            "chart data_table — the attached table has no meaning per panel. "
            "Use one or the other on this chart."
        ),
        doc=(
            "Fired when a chart authors both `multiples:` and a "
            "`data_table:`. The attached table is a single per-chart "
            "element; once the chart is faceted into a small-multiples grid "
            "it has no per-panel meaning. Remove one or the other."
        ),
        docs_topic="charts",
    )
)

ERR_MULTIPLES_LAYER_PARTITION = REGISTRY.register(
    ErrorCode(
        code="ERR-MULTIPLES-LAYER-PARTITION",
        domain="render",
        title="multiples cannot be combined with an own-query layer that returns the partition field",
        message_template=(
            "Chart {chart_id!r}: multiples cannot be combined with an "
            "own-query overlay layer whose query returns the partition "
            "field(s) {fields} — Vega-Lite cannot split one inline layer "
            "dataset per panel. Remove the partition column(s) from the "
            "layer's query to repeat the layer in every panel, or drop "
            "multiples."
        ),
        doc=(
            "Fired when a chart authors both `multiples:` and a `layers:` "
            "entry with its own `query:` whose result includes the "
            "partition column(s). Vega-Lite's facet operator only "
            "partitions the root dataset, never a layer's own inline "
            "dataset, so per-panel layer data cannot be represented. A "
            "layer whose query does not return the partition column is "
            "unaffected — it repeats identically in every panel, which is "
            "correct for a global reference line."
        ),
        docs_topic="charts",
    )
)

ERR_MULTIPLES_ROW_OUTSIDE_PANEL_AXES = REGISTRY.register(
    ErrorCode(
        code="ERR-MULTIPLES-ROW-OUTSIDE-PANEL-AXES",
        domain="render",
        title="row's multiples value is not among the resolved panel_axes",
        message_template=(
            "Row's {field!r} value {value!r} is not among the resolved "
            "panel_axes values {allowed} for this chart's multiples "
            "partition."
        ),
        doc=(
            "Fired when a chart is rendered against rows whose partition "
            "column carries a value `resolve()` never saw — the row-truncated "
            "render path can only ever hold a subset of the axis values "
            "baked at resolve, never one the axes lack, so this firing means "
            "the chart is being rendered against data resolve never saw. "
            "Re-resolve the chart against its actual data before rendering."
        ),
        summary="Fired when a rendered row's multiples value is absent from the resolve-time panel_axes.",
        docs_topic="charts",
    )
)

ERR_MULTIPLES_ROW_MISSING_PARTITION_FIELD = REGISTRY.register(
    ErrorCode(
        code="ERR-MULTIPLES-ROW-MISSING-PARTITION-FIELD",
        domain="render",
        title="row is missing a multiples partition field entirely",
        message_template=(
            "Row is missing the multiples partition field {field!r} "
            "entirely (it carries: {available}) — every row must carry "
            "every partition field, even one whose value is null."
        ),
        doc=(
            "Fired when a chart is rendered against a row that does not "
            "carry a partition column at all, as distinct from carrying it "
            "with a null value (a legitimate panel `resolve()` may have "
            "baked). A ragged row silently defaulting the missing field to "
            "`None` could misroute into that legitimate null panel by "
            "accident, so this is checked and raised separately."
        ),
        summary="Fired when a rendered row is missing a multiples partition column entirely, not merely null.",
        docs_topic="charts",
    )
)

ERR_MULTIPLES_RESOLVED_WITHOUT_DATA = REGISTRY.register(
    ErrorCode(
        code="ERR-MULTIPLES-RESOLVED-WITHOUT-DATA",
        domain="render",
        title="a faceted chart resolved without data is being rendered with real rows",
        message_template=(
            "Chart {chart_id!r}: multiples is set but this chart was "
            "resolved against no data (panel_axes is empty) and is now "
            "being rendered against real rows. Re-resolve the chart "
            "against its actual data before rendering."
        ),
        doc=(
            "Fired when a chart authors `multiples:`, was resolved with an "
            "empty query result (baking `panel_axes == ()`, the same N=1 "
            "state a non-faceted chart gets), and is then rendered against "
            "non-empty rows. Silently falling through would render the "
            "chart unfaceted instead of raising on data resolve never saw. "
            "Re-resolve the chart against its actual data before rendering."
        ),
        summary="Fired when a chart resolved without data (empty panel_axes) is rendered against real rows.",
        docs_topic="charts",
    )
)

ERR_MULTIPLES_INDEPENDENT_SCALE_MIRROR = REGISTRY.register(
    ErrorCode(
        code="ERR-MULTIPLES-INDEPENDENT-SCALE-MIRROR",
        domain="render",
        title="multiples with scale: independent cannot use a both-edge mirror axis",
        message_template=(
            "Chart {chart_id!r}: multiples with scale: independent cannot "
            "use a both-edge (mirror) y-axis — mirroring a shared scale to "
            "both edges is meaningless when each panel has its own scale. "
            "Use scale: shared, or set style.axis_y.mirror: false."
        ),
        doc=(
            "Fired when a chart authors `multiples: {scale: independent}` "
            "together with `style.axis_y.mirror` (bool true or an "
            "AxisMirrorStyle format/expr override). Mirroring reflects one "
            "shared scale to both edges — meaningless once every panel has "
            "its own independent scale. Use `scale: shared`, or turn mirror "
            "off."
        ),
        summary=(
            "Fired when a chart authors `multiples: {scale: independent}` "
            "together with a both-edge mirrored y-axis."
        ),
        docs_topic="charts",
    )
)


# ──────────────────────────────── Warning codes ───────────────────────────────
# Every render-time warning code is declared here in the leaf; detectors
# import their constants back rather than declaring codes in-module.

WARN_BAR_BAND_WIDTH_TOO_NARROW = REGISTRY.register(
    WarningCode(
        code="WARN-BAR-BAND-WIDTH-TOO-NARROW",
        domain="render",
        title="Bar chart bands are too narrow to read",
        message_template=(
            "Chart {chart_id!r} has {distinct} bands x {series} series across "
            "{render_width:.0f}px (~{bar_width:.2f}px per bar); "
            "below {min_band_width:.0f}px the fill disappears under "
            "the bar's own stroke."
        ),
        fix_template=(
            "Widen the chart, reduce the number of categories, "
            "or (for time series) roll up to a coarser grain "
            "(e.g. day -> week or month)."
        ),
        doc=(
            "Fires when a (vertical) bar chart packs so many bands into its plot "
            "width that each band's fill drops below a readability floor — the fill "
            "disappears and the bar's own border stroke merges neighbours into a "
            '"ghost band" smear. Classic trigger: daily-granularity data (hundreds '
            "of distinct days) rendered as bars at a normal chart width."
        ),
        docs_topic="charts",
    )
)

WARN_FACET_PANEL_WIDTH_BELOW_MINIMUM = REGISTRY.register(
    WarningCode(
        code="WARN-FACET-PANEL-WIDTH-BELOW-MINIMUM",
        domain="render",
        title="Small-multiples panel width shrank below the legibility floor",
        message_template=(
            "Chart {chart_id!r} facets into {panel_cols} column panel(s) at "
            "{panel_width:.0f}px each — below the {min_panel_px:.0f}px floor "
            "small multiples need to stay legible."
        ),
        fix_template=(
            "Widen the chart, reduce the column-facet's cardinality, or move "
            "part of the split from `multiples.columns` to `multiples.rows` "
            "(rows stack vertically instead of dividing the card's width)."
        ),
        doc=(
            "Fires when a small-multiples chart's column-facet cardinality "
            "leaves each panel narrower than the configured legibility floor. "
            "The floor is `chart_rendering.facet.min_panel_px`. The card's "
            "declared width is never negotiable — panels shrink below the "
            "floor rather than push painted content past the card's edge — "
            "so this is the author's only signal that the panel count has "
            "outgrown the card."
        ),
        docs_topic="charts",
    )
)

WARN_ENDPOINT_LABEL_GAP_OVERFLOW = REGISTRY.register(
    WarningCode(
        code="WARN-ENDPOINT-LABEL-GAP-OVERFLOW",
        domain="render",
        title="Endpoint-label rail is too cramped for its intended spacing",
        message_template=(
            "Chart {chart_id!r} packs {series_count} endpoint labels needing "
            "{gap_px:.0f}px apart into a plot shorter than that — labels are "
            "distributed evenly across the plot instead of at their intended "
            "spacing."
        ),
        fix_template=(
            "Give the chart more height, reduce the number of series, or "
            "switch to a color legend instead of an endpoint-label rail."
        ),
        summary=(
            "Fired when an endpoint-label rail cannot fit its intended label "
            "spacing in the plot's height."
        ),
        doc=(
            "Fires when an endpoint-label rail's intended gap — "
            "`font_size * chart_rendering.endpoint_labels.line_height_multiplier` "
            "— cannot fit between the "
            "rail's series count and the plot's actual height. This is "
            "advisory, not a floor: the rail still renders, with labels "
            "distributed evenly across the available plot rather than piled "
            "onto the domain edges."
        ),
        docs_topic="charts",
    )
)

WARN_ENDPOINT_LABEL_RAIL_TIED = REGISTRY.register(
    WarningCode(
        code="WARN-ENDPOINT-LABEL-RAIL-TIED",
        domain="render",
        title="Endpoint-label rail has no spread to place labels along",
        message_template=(
            "Chart {chart_id!r}: all {series_count} series end on the same "
            "value, so the rail has no vertical spread to space labels by — "
            "they are distributed evenly across the plot instead of stacking "
            "on one point."
        ),
        fix_template=(
            "This is a property of the data, not the layout — more height will "
            "not change it. Check whether the trailing rows are null or zero "
            "for every series; if that is expected, a color legend names the "
            "series without implying distinct endpoints."
        ),
        summary=(
            "Fired when every series in an endpoint-label rail ends on the "
            "same value, leaving no spread to place labels along."
        ),
        doc=(
            "Fires when an endpoint-label rail's labels cannot be spaced "
            "because no pixels-per-data-unit could be measured from them: "
            "every series ends on the same value (a trailing all-null or "
            "all-zero column is the usual cause), or the y scale collapsed "
            "them onto a single pixel. Distinct from "
            "`WARN-ENDPOINT-LABEL-GAP-OVERFLOW`, which is a height problem — "
            "this one is a data property and adding height cannot clear it. "
            "Advisory, not a floor: the rail still renders."
        ),
        docs_topic="charts",
    )
)

WARN_LAYERED_CHART_SHARED_Y_AXIS_SCALE_MISMATCH = REGISTRY.register(
    WarningCode(
        code="WARN-LAYERED-CHART-SHARED-Y-AXIS-SCALE-MISMATCH",
        domain="render",
        title="Layered chart y series have a large scale mismatch",
        message_template=(
            "Chart {chart_id!r}: y columns {col_a!r} and {col_b!r} share a y-axis "
            "but their value ranges differ by {ratio:.0f}× — the smaller series "
            "will be visually crushed to a flat line."
        ),
        fix_template=(
            "Split into two y-axes by adding `axis_y:` on one of the layers, "
            "or normalize the series to a common scale in the query."
        ),
        doc=(
            "Fires on a layered chart where the base chart's own y series and/or "
            "its layers share the y-axis but their value ranges differ by ≥100× — "
            "the smaller series is visually crushed to a flat line. Classic example: "
            "revenue (millions) overlaid with conversion rate ([0, 1])."
        ),
        docs_topic="charts",
    )
)

WARN_LAYOUT_MIN_EXCEEDS_HEIGHT = REGISTRY.register(
    WarningCode(
        code="WARN-LAYOUT-MIN-EXCEEDS-HEIGHT",
        domain="render",
        title="Chart's category count needs more height than its row allows",
        message_template=(
            "Chart {chart_id!r} has {n_categories} category bands, which need "
            "at least {min_height:.0f}px to stay readable, but its row/tile "
            "height caps it at {authored_height:.0f}px. The chart rendered at "
            "{min_height:.0f}px anyway — the row's authored height was not honored, "
            "and any sibling charts sharing the row grew to match."
        ),
        fix_template=(
            "Raise the row's height to fit the category count, or reduce the "
            "categories (filter, paginate, or roll up to a coarser grain) so "
            "the readable minimum fits inside the authored height."
        ),
        doc=(
            "Fires when a horizontal bar chart's category count forces a "
            "minimum height — one readable band per category — that exceeds "
            "the row/tile height its author assigned. The engine expands the "
            "chart to the computed minimum regardless (squashing labels past "
            "legibility to honor an impossible authored height would be worse), "
            "so the row's authored height silently loses; any sibling chart in "
            "the same row inherits the expansion. This warns so the author "
            "learns why the row grew, instead of measuring it by hand."
        ),
        docs_topic="charts",
    )
)

WARN_LOCAL_TIME_LABEL_EXPR_ON_BUCKETED_AXIS = REGISTRY.register(
    WarningCode(
        code="WARN-LOCAL-TIME-LABEL-EXPR-ON-BUCKETED-AXIS",
        domain="render",
        title="Authored axis label expression uses local time on a bucketed axis",
        message_template=(
            "Chart {chart_id!r}: axis_x.labels.expr calls {accessor}(), which "
            "reads datum.value in the render host's local time zone. The "
            "{time_unit!r} bucketing produces UTC-midnight tick values, so this "
            "can render a tick one bucket early depending on where the chart "
            "renders (e.g. Apr 2024 reads as Mar 2024 under a negative UTC "
            "offset)."
        ),
        fix_template=(
            "Replace local-time accessors with their utc-prefixed equivalents "
            "(utcFormat()/utcyear()/utcmonth()/...) — e.g. "
            "utcFormat(toDate(datum.value), '%b %Y') — so the label renders "
            "identically regardless of the render host's time zone."
        ),
        doc=(
            "Fires on bar (vertical + horizontal, single-metric + multi-metric), "
            "line, and area charts when axis_x.labels.expr contains a local-time "
            "accessor (timeFormat(), year(), month(), date(), quarter(), ...) while "
            "the chart's x-axis buckets to a UTC-midnight calendar grain "
            "(yearmonth, yearquarter, year, ...) — whether authored via "
            "axis_x.time_unit or auto-detected from the query data. Vega-Lite's "
            "bucketed timeUnit transform produces UTC-midnight Date values, but "
            "local-time accessors — unlike their utc-prefixed equivalents — "
            "format them in the render host's local time zone, so a tick can read "
            "as the previous bucket depending on where the chart renders. Heatmap "
            "and scatter are not yet covered. dbt charts never rewrites an authored "
            "label expression, so this only warns; switch to utcFormat() or "
            "utcmonth()/utcyear()/... to fix the render."
        ),
        summary=(
            "Fired on bar/line/area charts when an authored axis label expression "
            "calls a local-time accessor (timeFormat(), year(), month(), ...) on a "
            "bucketed temporal axis, which renders under the render host's local "
            "time zone instead of UTC."
        ),
        docs_topic="charts",
    )
)

WARN_LIKELY_CURRENCY_OR_PERCENT_MISSING_FORMATTER = REGISTRY.register(
    WarningCode(
        code="WARN-LIKELY-CURRENCY-OR-PERCENT-MISSING-FORMATTER",
        domain="render",
        title="Y-axis field looks like money or a percentage but uses a generic format",
        message_template=(
            "Chart {chart_id!r}: field {field!r} looks like {kind} "
            "but the y-axis format is {format!r}."
        ),
        fix_template=(
            "Set `style.axis_y.labels.format` to a currency format (e.g. `$,.2f`) "
            "or a percent format (e.g. `.1%`) to match the field's meaning."
        ),
        doc=(
            "Fires when a chart's y-encoding field name looks like money or a "
            "percentage but the chart's baked y-axis format is unfit to render "
            "that kind. Detection is name-based: fields ending in _usd, _revenue, "
            "_amount, _pct, _rate, etc. trigger when the resolved y-axis format "
            "does not carry `$` or `%`."
        ),
        docs_topic="charts",
    )
)

WARN_PIE_DOMINANT_SEGMENT = REGISTRY.register(
    WarningCode(
        code="WARN-PIE-DOMINANT-SEGMENT",
        domain="render",
        title="Pie chart is dominated by a single segment",
        message_template=(
            "Pie chart {chart_id!r}: {dominant_field!r} holds "
            "{dominant_share:.0%} of the total — the chart conveys a single value."
        ),
        fix_template=(
            "Use a KPI chart for the dominant share and a bar or table for the "
            "breakdown, rather than a pie dominated by one slice."
        ),
        doc=(
            "Fires on pie/donut charts where one slice is so large that the chart "
            "conveys a single value — the other slices are visually negligible. "
            "A near-single-value pie should be a KPI (the dominant share) plus a "
            "breakdown elsewhere."
        ),
        docs_topic="charts",
    )
)

WARN_PIE_TOO_MANY_SEGMENTS = REGISTRY.register(
    WarningCode(
        code="WARN-PIE-TOO-MANY-SEGMENTS",
        domain="render",
        title="Pie has too many slices to read",
        message_template=(
            "Pie chart {chart_id!r} has {segment_count} segments; "
            "angles are hard to compare past {max_segments} slices."
        ),
        fix_template=(
            "Use a bar chart sorted by value, or group small segments into 'Other'."
        ),
        doc=(
            "Fires on pie/donut charts whose query returns more segments than a "
            "reader can compare by angle. Humans judge angle poorly past a handful "
            "of slices; a pie with many segments is unreadable and should be a "
            "sorted bar chart."
        ),
        docs_topic="charts",
    )
)

WARN_POINT_MAP_NEGATIVE_SIZE_VALUES = REGISTRY.register(
    WarningCode(
        code="WARN-POINT-MAP-NEGATIVE-SIZE-VALUES",
        domain="render",
        title="Point map size measure has negative values",
        message_template=(
            "Point map {chart_id!r}: {dropped_count} of {total_count} points "
            "have a negative {size_field!r} value and were not drawn — mark "
            "area cannot be negative."
        ),
        fix_template=(
            "Size by a magnitude instead of a signed value (e.g. "
            "`size: abs({size_field})` in the query) and encode direction "
            "with a diverging `color:` instead."
        ),
        doc=(
            "Fires when a bubble_map's `size:` measure contains negative "
            "values. Mark area cannot be negative, so rows with a negative "
            "size value are dropped before Vega-Lite sees them rather than "
            "drawn at the smallest visible size — a negative value clamped "
            'to the scale\'s zero floor would read as "nearly zero", '
            "misrepresenting a large-magnitude negative measurement. Size "
            "by a magnitude (e.g. `abs(...)` in the query) and encode "
            "direction with a diverging `color:` instead. A zero-valued row "
            "is legitimate data with a legitimate area of nothing and is "
            "never dropped or counted here."
        ),
        summary=(
            "Fires when a point_map's `size:` measure contains negative "
            "values; those rows are dropped rather than drawn misleadingly small."
        ),
        docs_topic="charts",
    )
)

WARN_POINT_MAP_OUT_OF_PROJECTION = REGISTRY.register(
    WarningCode(
        code="WARN-POINT-MAP-OUT-OF-PROJECTION",
        domain="render",
        title="Point map has data outside the projection boundary",
        message_template=(
            "Point map {chart_id!r}: {dropped_count} of {total_count} points "
            "are outside the {projection!r} projection boundary and were dropped."
        ),
        fix_template=(
            "Filter the data to the projection's region, or switch to a "
            "projection that covers the full data extent."
        ),
        doc=(
            "Fires when a point_map chart uses a bounded projection (e.g. "
            "albersUsa) and some data points fall outside its mapped region. "
            "The emitter drops those rows from spec.data before Vega-Lite sees "
            "them; this warning reports how many points were dropped and why."
        ),
        summary=(
            "Fires when a point_map chart uses a bounded projection and some "
            "data points fall outside its mapped region."
        ),
        docs_topic="charts",
    )
)

WARN_QUERY_RETURNED_ZERO_ROWS = REGISTRY.register(
    WarningCode(
        code="WARN-QUERY-RETURNED-ZERO-ROWS",
        domain="render",
        title="Chart query returned zero rows",
        message_template="Chart {chart_id!r}: query returned zero rows.",
        fix_template=(
            "Check the WHERE clause or date filter — it may be excluding all data "
            "for the current filter values."
        ),
        doc=(
            "Fires on any chart whose query returned zero rows. An empty chart "
            "renders as a blank panel with axes — no signal to the viewer that "
            "the query returned nothing. Most common cause: a WHERE clause or "
            "date filter that excludes all data."
        ),
        docs_topic="charts",
    )
)

WARN_QUERY_RESULT_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-QUERY-RESULT-TRUNCATED",
        domain="render",
        title="Chart query result truncated",
        message_template=(
            "{subject}: query result exceeded the {reason} limit; "
            "truncated to {kept_row_count} rows."
        ),
        fix_template=(
            "Add a LIMIT to the query, narrow its filters, or raise "
            "execution.max_rows/max_result_bytes in dbt_charts.yml if the full "
            "result is genuinely needed."
        ),
        doc=(
            "Fires when a query's result exceeded the execution.max_rows or "
            "max_result_bytes safety ceiling and was truncated before it ever "
            "reached the result cache. The chart still renders with the "
            "truncated data — this is a safety net against an unbounded query "
            "exhausting memory or bloating the cache, not a hard error."
        ),
        summary=(
            "Fired when a query result exceeded the max_rows/max_result_bytes "
            "safety ceiling and was truncated."
        ),
        docs_topic="charts",
    )
)

WARN_REDUNDANT_ENCODING = REGISTRY.register(
    WarningCode(
        code="WARN-REDUNDANT-ENCODING",
        domain="render",
        redundant=True,
        title="Same column bound to two visual channels",
        message_template=(
            "Chart {chart_id!r}: field {field!r} is bound to channels "
            "{channels} — binding the same field twice adds no information."
        ),
        fix_template=(
            "Remove one of the channel bindings, or use different fields for "
            "each channel to encode distinct dimensions."
        ),
        doc=(
            "Fires when one query column is bound to two or more visual channels "
            "of the same chart (e.g. `y` and `color` both set to the same field). "
            "Binding the same field twice adds no information — the second channel "
            "is redundant. The bar `x==color` case is excluded: it renders "
            "full-width category-colored bars, which is a useful pattern."
        ),
        summary=(
            "Fires when one query column is bound to two or more visual "
            "channels of the same chart."
        ),
        docs_topic="charts",
    )
)

WARN_STATIC_PAGINATION_CAPPED = REGISTRY.register(
    WarningCode(
        code="WARN-STATIC-PAGINATION-CAPPED",
        domain="render",
        title="Static export stopped short of every table page",
        message_template=(
            "Table {chart_id!r}: static export pre-rendered {rendered_pages} "
            "of {total_pages} pages — rows past page {rendered_pages} are not "
            "in this file."
        ),
        fix_template=(
            "Reduce the row count, raise style.pagination.page_rows so fewer "
            "pages are needed, or view the table on an interactive host (dct "
            "serve, Cloud) instead of a static export."
        ),
        doc=(
            "Fires when a static export (dct render --format html/svg) has a "
            "table with more pages than the renderer will pre-draw. A static "
            "export ships no JS runtime that can ask a server for another "
            "page, so every page's rows are pre-rendered into the artifact "
            "as toggle groups; left uncapped, that makes file size scale with "
            "total row count instead of page size. Past the cap, the "
            "renderer stops pre-rendering — the artifact shows only the "
            "first N pages, and states so in the exported file itself."
        ),
        docs_topic="charts",
    )
)

WARN_TABLE_COLUMNS_OVERFLOW = REGISTRY.register(
    WarningCode(
        code="WARN-TABLE-COLUMNS-OVERFLOW",
        domain="render",
        title="Table is wider than its dashboard slot",
        message_template=(
            "Table {chart_id!r} overflows its slot: "
            "needed {needed_width:.0f}px but only {available_width:.0f}px available."
        ),
        fix_template=(
            "Widen the table's dashboard slot, reduce the number of columns, "
            "or add explicit column widths to control how the table distributes "
            "its available space."
        ),
        doc=(
            "Fires when a table needs more width than the slot it was given. A "
            "table sizes each column to its minimum readable width; when those "
            "widths sum past the available width, the renderer widens the whole "
            "table past its slot — so in a dashboard it spills over its neighbour "
            "or is clipped, printing columns on top of each other."
        ),
        docs_topic="charts",
    )
)

WARN_TEMPORAL_SINGLE_POINT = REGISTRY.register(
    WarningCode(
        code="WARN-TEMPORAL-SINGLE-POINT",
        domain="render",
        title="Temporal line or area chart has only one data point",
        message_template=(
            "Chart {chart_id!r} ({chart_type}): temporal x-axis has exactly "
            "one data point — a one-point line/area conveys no trend."
        ),
        fix_template=(
            "Widen the date filter to include more time periods, "
            "or switch to a KPI or stat tile if a single-point value is intentional."
        ),
        doc=(
            "Fires on line and area charts where the x-axis is temporal and the "
            "query result has exactly one row. A one-point line is rendered as a "
            "single dot; a one-point area is a vertical line. Both render but "
            "convey nothing about a trend — this almost always means the date "
            "filter is too narrow."
        ),
        docs_topic="charts",
    )
)

WARN_TOO_MANY_COLOR_CATEGORIES = REGISTRY.register(
    WarningCode(
        code="WARN-TOO-MANY-COLOR-CATEGORIES",
        domain="render",
        title="Color encoding has more categories than the palette can distinguish",
        message_template=(
            "Chart {chart_id!r}: color field {field!r} has {count} distinct "
            "values — the palette only has {max_categories} distinct colors "
            "before recycling."
        ),
        fix_template=(
            "Reduce the number of color categories by grouping small values into "
            "'Other', or filter the data to the most significant categories."
        ),
        doc=(
            "Fires when a categorical color encoding has more distinct values than "
            "the palette can distinguish — colors recycle and the legend becomes "
            "unreadable. Gated on the Vega-Lite color encoding type so a continuous "
            "(quantitative) color gradient never trips it."
        ),
        docs_topic="charts",
    )
)

WARN_PALETTE_UNSUPPORTED = REGISTRY.register(
    WarningCode(
        code="WARN-PALETTE-UNSUPPORTED",
        domain="render",
        title="Palette name is a known anti-pattern",
        message_template=(
            "Chart {chart_id!r}: palette {requested!r} is a known anti-pattern; "
            "resolved to {resolved} instead."
        ),
        fix_template=(
            "Author a supported palette name — see the anti-patterns table in "
            "docs/guides/palette-resolver.md#anti-patterns."
        ),
        doc=(
            "Fires when a chart authors a palette name on the known anti-pattern "
            "list (e.g. 'RdYlGn', 'parula') — these are CVD-hostile or superseded "
            "by a DFT-native palette. palette() resolves the substitute silently "
            "at compile time; this detector is the only place the nudge surfaces."
        ),
        summary=(
            "Fires when a chart authors a palette name on the known anti-pattern "
            "list — these are CVD-hostile or superseded by a DFT-native palette."
        ),
        docs_topic="charts",
    )
)

WARN_TOO_MANY_X_CATEGORIES = REGISTRY.register(
    WarningCode(
        code="WARN-TOO-MANY-X-CATEGORIES",
        domain="render",
        title="Categorical x-axis has too many distinct values to read",
        message_template=(
            "Chart {chart_id!r}: x field {field!r} has {count} distinct "
            "values — labels collide and marks are too thin to read "
            "(limit: {max_categories})."
        ),
        fix_template=(
            "Filter to the top N categories by value, roll up to a coarser "
            "grouping, or switch to a scrollable table for wide categorical data."
        ),
        doc=(
            "Fires when a categorical (nominal/ordinal) x-axis has more distinct "
            "values than fit legibly — labels collide and the marks are too thin "
            "to read. For a bar chart, also fires on a temporal x-axis: bars still "
            "draw one band per distinct x value even where the density gate has "
            "moved bucketed temporal data off the ordinal scale. Never fires on a "
            "quantitative axis, or on a temporal axis for line/area/scatter charts, "
            "where a dense axis is a continuous draw, not a crowded band."
        ),
        docs_topic="charts",
    )
)

WARN_VALUE_LABELS_CROWD_WIDTH = REGISTRY.register(
    WarningCode(
        code="WARN-VALUE-LABELS-CROWD-WIDTH",
        domain="render",
        title="Value labels are wider than their per-mark slot",
        message_template=(
            "Chart {chart_id!r}: widest value label is {label_width:.0f}px "
            "but each mark only has {slot_width:.0f}px — labels will overflow "
            "and collide with neighbours."
        ),
        fix_template=(
            "Shorten the number format (e.g. use SI suffix `.2~s` instead of "
            "full precision), reduce the number of labeled marks, or widen the chart."
        ),
        doc=(
            "Fires when a chart's value labels are wider than the horizontal room "
            "each one gets. Value labels are drawn at the mark, fixed size, with "
            "no adaptive avoidance, so they are the label kind that genuinely "
            "overflows. The check uses the panel's real rendered width and font "
            "metrics — it fires exactly when the widest label is wider than its slot."
        ),
        docs_topic="charts",
    )
)

WARN_AXIS_TITLE_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-AXIS-TITLE-TRUNCATED",
        domain="render",
        title="Axis title was too long and was truncated with an ellipsis",
        message_template=(
            "Chart {chart_id!r}: {authored_field!r} was truncated — "
            "the authored text {authored_text!r} did not fit within two "
            "lines at the available extent."
        ),
        fix_template="Shorten the axis title, or widen the chart so the title has more room.",
        doc=(
            "Fires when an axis title is pre-wrapped to at most two lines "
            "(to prevent Vega-Lite's autosize from collapsing the plot) and "
            "the authored text is still too long — the last line is cut with "
            "a Unicode ellipsis (…) and the remainder of the title is lost. "
            "The title text in the message is the full authored text before "
            "truncation, so you can see exactly what was cut."
        ),
        docs_topic="charts",
    )
)

WARN_SERIES_LABEL_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-SERIES-LABEL-TRUNCATED",
        domain="render",
        title="Series label was too long for the endpoint-label rail and was truncated",
        message_template=(
            "Chart {chart_id!r}: {count} series {labels_noun} from {authored_field!r} "
            "{were} truncated in the endpoint-label rail, which is capped at a "
            "fraction of the chart's width: {labels}."
        ),
        fix_template=(
            "Shorten the {authored_field} values, widen the chart, or set "
            "style.endpoint_labels.visible: false to keep the series names in "
            "the legend."
        ),
        doc=(
            "Fires when a chart's series labels are drawn in the right-hand "
            "endpoint-label rail and do not fit. The rail may claim only a "
            "fraction of the chart's width, so longer names are cut with an "
            "ellipsis (…). The labels are the values of the column bound to "
            "`color:`, or — for a wide-form area authored `y: [a, b, …]` — the "
            "measure names themselves; the warning names whichever key you "
            "wrote. The label text in the message is the full value before "
            "truncation, so you can see exactly what was cut. Only the drawn "
            "label is shortened: the underlying values, the color scale, and "
            "tooltips still carry the full text."
        ),
        docs_topic="charts",
    )
)

WARN_CHART_TITLE_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-CHART-TITLE-TRUNCATED",
        domain="render",
        title="Chart title or subtitle was truncated with an ellipsis",
        message_template=(
            "Chart {chart_id!r}: {authored_field!r} was truncated — "
            "the authored text {authored_text!r} did not fit within the "
            "available width."
        ),
        fix_template="Shorten the title or subtitle, or widen the chart.",
        doc=(
            "Fires when a chart title or subtitle is wrapped and the last "
            "line is cut with a Unicode ellipsis (…) because the authored "
            "text exceeds the available width. The message shows the full "
            "authored text before truncation."
        ),
        docs_topic="charts",
    )
)

WARN_KPI_LABEL_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-KPI-LABEL-TRUNCATED",
        domain="render",
        title="KPI card label was truncated",
        message_template=(
            "Chart {chart_id!r}: KPI label was truncated — "
            "the authored text {authored_text!r} did not fit within the "
            "card at the available width."
        ),
        fix_template=(
            "Shorten the KPI label, widen the card, or use a smaller font size."
        ),
        doc=(
            "Fires when the KPI card label text is clipped or wrapped with "
            "an ellipsis because it exceeds the card width. The message shows "
            "the full authored label before truncation."
        ),
        docs_topic="charts",
    )
)

WARN_TABLE_TEXT_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-TABLE-TEXT-TRUNCATED",
        domain="render",
        title="Table column header or cell text was truncated",
        message_template=(
            "Chart {chart_id!r}: column {authored_field!r} has truncated text — "
            "{truncation_count} value(s) were cut with an ellipsis."
        ),
        fix_template=(
            "Widen the column, shorten the values, or increase the chart width."
        ),
        doc=(
            "Fires when a table column header or one or more cell values are "
            "clipped with an ellipsis because they exceed the column width. "
            "One warning fires per column that has any truncation."
        ),
        docs_topic="charts",
    )
)

WARN_CALLOUT_TEXT_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-CALLOUT-TEXT-TRUNCATED",
        domain="render",
        title="Callout text was truncated",
        message_template=(
            "Chart {chart_id!r}: callout {authored_field!r} was truncated — "
            "the authored text {authored_text!r} exceeded the maximum lines."
        ),
        fix_template=("Shorten the callout text, or increase the chart height/width."),
        doc=(
            "Fires when a callout chart's title, message, or hint text is "
            "wrapped and the last line is cut with a Unicode ellipsis because "
            "the text exceeds the maximum line count."
        ),
        docs_topic="charts",
    )
)

WARN_SPARK_LABEL_TRUNCATED = REGISTRY.register(
    WarningCode(
        code="WARN-SPARK-LABEL-TRUNCATED",
        domain="render",
        title="Spark-bar row label was truncated",
        message_template=(
            "Chart {chart_id!r}: {truncation_count} spark-bar label(s) were "
            "truncated — the label column is too narrow to show the full text."
        ),
        fix_template=(
            "Widen the chart or increase the label column width in the chart style."
        ),
        doc=(
            "Fires when one or more spark-bar row labels are truncated because "
            "the label column is too narrow to fit the full text. One warning "
            "fires per chart with any truncated labels."
        ),
        docs_topic="charts",
    )
)

WARN_Y_ENCODING_MOSTLY_NULL = REGISTRY.register(
    WarningCode(
        code="WARN-Y-ENCODING-MOSTLY-NULL",
        domain="render",
        title="Y-encoding field is mostly NULL in the query result",
        message_template=(
            "Chart {chart_id!r}: y field {field!r} is {null_pct:.0%} NULL "
            "across {row_count} rows."
        ),
        fix_template=(
            "Check for a broken join or a nullable source column. "
            "A COALESCE or WHERE clause may be needed to filter the empty rows."
        ),
        doc=(
            "Fires on any chart where the y-encoding field is more than 50% NULL "
            "in the query result rows. Mostly-empty visual marks with no explanation "
            "usually indicate a broken join or a nullable source column. "
            "NULL-only differs from NULL+zero: zero is a valid measurement."
        ),
        docs_topic="charts",
    )
)
