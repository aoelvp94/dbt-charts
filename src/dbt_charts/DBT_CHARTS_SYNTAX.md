# Dataface YAML Syntax

Authoring reference for Dataface board YAML. Every option in this file is enforced by the compiler (`extra="forbid"` is set on every model — unknown keys are schema errors).

Browse with `dct docs` (run with no args for the topic catalog, `dct docs <topic>` for one section, `dct docs all` for the whole file).

## Getting Started

Dataface workflow — from a dbt project to a running dashboard.

### Step 1 — Validate your YAML

```bash
dct validate charts/my_dashboard.yml
```

`dct validate` performs YAML schema + cross-reference validation. It checks that every field, chart reference, query name, and variable is correctly structured. **No database connection is required.**

To verify that your database connection works, run a simple query:

```bash
dct query 'SELECT 1' --source <your_source>
```

A successful result means your data source is reachable.

### Step 2 — Browse your schema

Explore available tables and columns with metadata SQL before writing queries:

```bash
dct query mydb "SELECT table_schema, table_name FROM INFORMATION_SCHEMA.TABLES"
dct query mydb "SELECT column_name, data_type FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name = 'orders'"
```

(DuckDB also supports `DESCRIBE orders`; SQLite uses `sqlite_master` and
`PRAGMA table_info(orders)`.)

Never invent column names — always verify them against the schema first.

### Step 3 — Build one chart

Write the minimal YAML needed for a single chart:

```yaml
source: mydb

queries:
  revenue: SELECT month, SUM(amount) AS total FROM orders GROUP BY 1 ORDER BY 1

charts:
  revenue_trend:
    query: revenue
    type: line
    x: month
    y: total

rows:
  - revenue_trend
```

Then validate and render:

```bash
dct validate charts/my_dashboard.yml
dct render charts/my_dashboard.yml
```

Add each additional chart after the previous one validates and renders cleanly.

### Step 4 — Serve locally

```bash
dct serve
```

Opens a live-preview server. Edit the YAML and reload the browser to see changes.

**See also:** `dct docs cheatsheet` (minimal examples), `dct docs queries`, `dct docs charts`, `dct docs variables`.

## Cheatsheet

One screen of essentials. Each topic below has a dedicated H2 (`dct docs board`, `dct docs queries`, …) for full coverage.

### Minimal board

```yaml
source: my_profile

queries:
  revenue: SELECT month, SUM(amount) AS total FROM orders GROUP BY 1 ORDER BY 1

charts:
  revenue_trend:
    query: revenue
    type: line
    x: month
    y: total

rows:
  - revenue_trend
```

### Top-level board fields

- `title`, `description`, `tags`
- `source` / `sources` — default and named data connections
- `variables` — interactive filter controls
- `queries` — named SQL / CSV / HTTP / dbt / inline queries
- `charts` — named chart definitions
- Exactly one of `rows`, `cols`, `grid`, `tabs` (or `text:` for a text-only board)
- `theme`, `style`, `id`, `width`, `height` — presentation

### Queries (named, parameterized, inline)

```yaml
variables:
  region:
    input: select
    options:
      static: [US, EU, APAC]

queries:
  # Bare-string form — SQL inherits the board-level source
  revenue: SELECT month, SUM(amount) AS total FROM orders GROUP BY 1 ORDER BY 1

  # Long form with options
  filtered:
    sql: "SELECT * FROM orders WHERE region = '{{ region }}'"
    source: warehouse

  # Inline data (no DB needed)
  targets:
    columns: [region, target]
    values:
      - [US, 100]
      - [EU, 80]
```

### Variables

```yaml
variables:
  region:
    input: select                  # See `dct docs variables` for all 14 input types
    options: { static: [US, EU, APAC] }
    default: US
```

Reference variables inside queries with bare `{{ region }}` — no `variables.` prefix.

### Charts

```yaml
charts:
  revenue_trend:
    query: revenue                 # Named query reference
    type: line                     # See `dct docs charts` for all 16 authorable chart types
    x: month
    y: total
    color: segment

  quick_chart:
    query: "SELECT month, revenue FROM orders"   # Bare SQL shorthand (no named query needed)
    type: bar
    x: month
    y: revenue
```

### Layout

Pick exactly one of:

- `rows: [chart_a, chart_b]` — vertical stack
- `cols: [chart_a, chart_b]` — horizontal arrangement
- `grid: { columns: 24, items: [...] }` — CSS-grid placement
- `tabs: { items: [{title: ..., rows: [...]}] }` — tabbed navigation

**See also:** `dct docs board` (full top-level reference),
`dct docs queries`, `dct docs charts`, `dct docs variables`, `dct docs layout`,
`dct docs errors` (common error codes), `dct docs all` (whole reference).

## Board

The top-level YAML mapping is a board. Exactly one layout key (`rows`, `cols`, `grid`, `tabs`) must be present unless `text:` is set.

```yaml-schema
title: "Sales Overview"
description: "Monthly KPIs and trend"
tags: [sales, weekly]

source: my_profile             # Default source (a name from dbt_charts.yml's sources: registry)

variables:                     # Optional — interactive controls
queries:                       # Named queries
charts:                        # Named charts
rows: [ ... ]                  # Or cols:, grid:, tabs: (pick one)

theme: neon                    # Vega-Lite theme; inherited by nested boards

# Nesting / layout primitives (mostly for nested boards inside rows/cols)
id: my_board                    # Auto-generated from filename if omitted
style: { padding: 16, background: dbt-grays.canvas }
width: 400                     # Pixels or "50%" when nested
height: 300

card_gap: false                # When true, adds gap between cards
chart_focus: revenue_trend     # Render only one chart with its dependent variables

details: "Click to expand"     # Collapsible section
expanded_title: "Hide details"
expanded: false
```

Top-level fields (22 total):

| Field | Type | Notes |
|-------|------|-------|
| `title` | string | Display title |
| `description` | string | Description text |
| `tags` | list[string] | Tags for categorization/search |
| `text` | string | Markdown body for text-only boards |
| `source` | string | Default source name for every query below (from `dbt_charts.yml`'s `sources:` registry), or an inline file path for a single colocated CSV/JSON/Parquet file. Inheritable via the `meta.yaml` cascade. |
| `variables` | object | See [Variables](#variables) |
| `queries` | object | See [Queries](#queries) |
| `charts` | object | See [Charts](#charts) |
| `rows` | list | Vertical layout — chart names or inline blocks |
| `cols` | list | Horizontal layout — chart names or inline blocks |
| `grid` | object | CSS-grid layout (see [Layout](#layout)) |
| `tabs` | object | Tabbed layout (see [Layout](#layout)) |
| `card_gap` | bool | Add visible gap between cards (default `false`) |
| `chart_focus` | string | Render only this chart (with its variables) |
| `details` | string | Collapsible-section summary text |
| `expanded_title` | string | Header text when expanded |
| `expanded` | bool | Default expanded state |
| `id` | string | Explicit board ID (auto-generated from filename) |
| `style` | object | Board-style block (see [Board style](#board-style)) |
| `width` | string \| int | Width when nested (`"50%"` or pixels) |
| `height` | string \| int | Height when nested |
| `theme` | string | Vega-Lite theme name (e.g. `editorial`, `stark`, `neon`) — inherited by nested boards |

`board:` as a top-level key is rejected. Put board properties (title, rows, queries, …) directly at the YAML root.

### Aliases

`aliases:` is a list of absolute URL paths that 302-redirect to this board's canonical file-path URL.  Each entry must start with `/`; trailing slashes are normalized automatically.

```yaml
aliases:
  - /old-reports/
  - /legacy/sales/
```

Rules:
- Every alias must be absolute (leading `/`) — a relative entry fails validation on that board.
- An alias must not collide with a real board file path — `dct serve` raises an error at startup if it does.
- Each alias must be unique across the project — two boards claiming the same alias is a startup error under `dct serve`. A host with no startup step resolves a duplicate to the first board by slug instead of reporting it.
- Aliasing a generated system route (data or inspector view) is allowed: the redirect takes precedence, letting you override what that URL serves.

#### Parameterized aliases (capture a path segment into a variable)

An alias may contain `<name>` capture segments.  A request matching the pattern
302-redirects to the board's canonical URL with each captured segment appended as a
query param of the same name — which the board then reads as its variable.  This
gives a single detail board a clean per-entity URL:

```yaml
# charts/milestone.yml  (canonical URL: /milestone)
aliases:
  - /milestones/<name>
variables:
  name: { input: select, options: { query: milestone_options, column: slug } }
```

Now `/milestones/m3-public-launch` redirects to `/milestone/?name=m3-public-launch`,
and `milestone.yml` renders with `name` bound to `m3-public-launch`.

- Capture names use the same grammar as built-in routes: `<name>` matches exactly
  one non-empty path segment (no `/`).  Use a capture name that matches the
  variable you want it to fill.
- A real board file always wins over a pattern alias, so `/milestones/` (the list
  board) and `/milestones/<name>` (the detail redirect) coexist without conflict.
- Plain aliases (no `<...>`) redirect as before; only aliases with a capture are
  treated as patterns.

There are two ways to override a data/inspector route for a given path:
- **Board file at that path** — create `charts/data/warehouse/schema/table.yml` and the server renders it directly (no redirect).
- **`aliases:` entry** — any board can declare `/data/…/` as an alias; the server issues a 302 to the declaring board's canonical URL.

Both approaches work.  A board file wins without a redirect round-trip; an alias lets a board live anywhere and still capture a system-view URL.

### Board style

`style:` on a board, nested board, or layout section accepts a fixed set of keys — not arbitrary CSS:

```yaml
style:
  padding: "16px"
  margin: "0 0 12px 0"
  background: dbt-grays.canvas
  color: dbt-grays.ink
  gap: 12
  border:
    width: 1
    color: dbt-grays.border
    radius: 8
  text:
    align: left
    column:
      max_number: 2
      gap: 24
      rule:
        width: 1
        color: dbt-grays.separator
```

CSS-only keys like `border-radius`, `border-left`, `margin-top` are not board-style fields and are rejected.

#### Title heading levels

`style.title.level` controls the H-level (H1–H6) used for board and chart titles.

```yaml
# Default — compute from count of titled ancestors (the recommended default).
# A titled root board is H1, a titled child section is H2, and so on.
# Bare layout wrappers (no title) do not advance the counter.
style:
  title:
    level: auto

# Lock level to a specific heading — useful for embedded dashboards where
# H1/H2 are reserved by the outer page.
style:
  title:
    level: 3   # this board and all descendants start from H3
```

When set to an integer, it cascades to descendants: titled children render at
`level + 1`, bare wrappers inherit the locked level unchanged.

**See also:** `dct docs queries` (data layer), `dct docs charts` (display layer),
`dct docs layout` (composition), `dct docs cheatsheet` (one-page essentials).

## Queries

Queries are the data layer. Charts reference queries by name; queries never embed display logic.

```yaml
source: my_profile             # Optional: default source for every query below

variables:
  region:
    input: select
    options:
      static: [US, EU, APAC]

queries:
  # SQL — the default. `type: sql` is implicit when `sql:` is present.
  revenue: SELECT month, SUM(amount) AS total FROM orders GROUP BY 1 ORDER BY 1

  # SQL with metadata
  filtered:
    description: Monthly revenue filtered by region
    sql: SELECT * FROM orders WHERE {{ filter('region', region) }}
    source: warehouse           # Override board-level source
    setup_sql: CREATE TEMP FUNCTION norm(x FLOAT64) AS (x / 100.0);

  # CSV / JSON / Parquet file — declare a file source, then query it with SQL
  # (sources.local_files must define files: { targets: data/targets.csv })
  targets:
    type: sql
    sql: SELECT region, target FROM targets
    source: local_files

  # HTTP / REST API — self-contained; no source: field (nothing to look up by name)
  customers:
    type: http
    url: https://api.example.com/customers
    method: GET                  # GET | POST | PUT | DELETE | PATCH
    headers: { Authorization: "Bearer {{ api_token }}" }  # api_token: a board variable
    params: { status: active }
    body: { ... }
    json_path: $.data

  # Inline file source — a single colocated CSV/JSON/Parquet, no registry entry
  targets_inline:
    type: sql
    sql: SELECT region, target FROM targets
    source: ./data/targets.csv   # path (contains "/" or a data extension) = inline file; table name = stem

  # MetricFlow / dbt Semantic Layer
  revenue_by_region:
    type: metricflow             # Optional — also implied by `metrics:` presence
    metrics: [revenue]
    dimensions: [region]
    time_grain: month            # day | week | month | quarter | year

  # Inline values (no database)
  sample:
    type: values                 # Optional — implied by `rows:`, `columns:`, or `values:`
    columns: [name, score]
    values:
      - [Alice, 92.4]
      - [Bob, 87.1]
```

Query types (`type:` literals): `sql`, `http`, `metricflow`, `values`. `schema_resolver` is internal-only and not part of the authored surface.

Common fields (all query types):

| Field | Description |
|-------|-------------|
| `description` | Metadata sentence for AI search and tooltips |
| `source` | Source name (from `dbt_charts.yml`'s `sources:` registry), or an inline file path (`./data/x.csv`) for a single colocated CSV/JSON/Parquet. An inline connection dict (`{type: postgres, ...}`) is rejected — reference a named source instead. Not accepted on `http` queries. |
| `target` | dbt target name (defaults to `dev`) |
| `filters` | Post-execution result filters |
| `limit` | Maximum rows returned |
| `pivot` | Table-rendering cross-tab hint: `{column, value}` |
| `ignore` | Diagnostic codes to suppress (e.g. `["WARN-FANOUT-RISK"]`) |

SQL fields: `sql`, `setup_sql`.
MetricFlow fields: `metrics`, `dimensions`, `time_grain`.
HTTP fields: `url`, `method`, `headers`, `params`, `body`, `json_path`.
dbt-model fields: `model`, `columns`.
Inline-values fields: `columns`, `values` (or `rows` for record-shape).

Connection source types (named in the project root `dbt_charts.yml`'s `sources:`
registry — never inline in a board): `postgres`, `snowflake`, `bigquery`,
`redshift`, `mysql`, `duckdb`, `sqlite`, `csv`, `json`, `parquet`, `http`, `dbt_profile`.
CSV/JSON/Parquet may instead be referenced inline as a `source:` file path
without a registry entry — see the example above.

### Jinja variable injection

Queries are Jinja-rendered before execution. Reference variables as bare names — `{{ region }}` — not with a `variables.` namespace prefix.

```yaml
variables:
  region: { input: select, options: { static: [US, EU, APAC] } }
  period: { input: daterange }

queries:
  sales:
    sql: |
      SELECT month, revenue
      FROM orders
      WHERE {{ filter('region', region) }}
        AND {{ filter_date_range('month', period) }}
```

For multiline SQL, always use block scalar (`sql: |`). Never use `"SELECT\n…"` or `'SELECT\n…'` — escaped newlines make diffs unreadable and confuse agents learning from examples. Single-line SQL in double quotes is fine: `sql: "SELECT 1 AS n"`.

`filter()` and `filter_date_range()` are helper macros that emit safe SQL predicates for select/multiselect and daterange variables respectively.

**Common multiselect mistake** — `tojson` produces double-quoted strings; most SQL dialects (including DuckDB) treat `"trial"` as a *column reference*, not a string literal. The query silently returns an empty result and `dct render` exits 0.

```sql
-- WRONG: produces WHERE plan IN ("trial", "pro") — treated as column refs, not strings
WHERE plan IN ({{ plans | map('tojson') | join(', ') }})
```

Use the `filter()` macro instead — it emits correctly quoted predicates:

```sql
-- CORRECT
WHERE {{ filter('plan', plans) }}
```

The `filter()` macro handles `select` (single value → `=`) and `multiselect` (list → `IN (...)`) automatically and quotes all string literals correctly.

Select and multiselect controls render only the options the board author provides. Dataface does not add an "All" option; author a real sentinel option and matching SQL/Jinja explicitly if a dashboard needs one.

### Inline query in a chart

A chart can carry its own one-off query instead of referencing a named one. Three equivalent forms:

```yaml
charts:
  rev_chart:
    # Shorthand — bare SQL string (simplest form)
    query: "SELECT month, revenue FROM orders"
    type: bar
    x: month
    y: revenue

  rev_chart2:
    # Explicit inline dict
    query:
      sql: "SELECT month, revenue FROM orders"
    type: bar
    x: month
    y: revenue
```

The bare-string shorthand works whenever the value contains a SQL keyword (`SELECT`, `WITH`, `INSERT`, etc.) and is not already a named query. Use `query: {sql: ...}` when you need additional query options (`source:`, `description:`, etc.).

Inline queries are not reusable. Prefer named queries when more than one chart consumes the data.

**See also:** `dct docs variables` (use `{{ var }}` in SQL),
`dct docs charts` (charts reference queries by name),
`dct docs errors` (query-execution error codes).

## Charts

Each chart binds a query to a chart type and an encoding. Unknown chart fields are rejected.

```yaml
charts:
  revenue_trend:
    query: revenue            # Name of a query (or inline query def)
    type: line                # See chart types below
    title: "Revenue"
    subtitle: "Last 30 days"
    description: "AI/tooltip metadata about what this chart answers."

    # Data mapping (the channels)
    x: month                  # column name
    y: total                  # column name OR [col, col, ...] for multi-series
    color: segment            # a bare column name; nothing else is accepted here
                              # literal color -> style.color.static; scale -> style.color.gradient

    # Sizing — height lives at chart root; aspect_ratio is a style field
    height: 400               # exact px; bypasses aspect_ratio and min/max clamps
    # height/aspect_ratio are ignored on kpi, table, callout, spark_bar

    # Style + behavior
    sort: { by: total, order: desc }
    x_label: "Month"
    y_label: "Revenue (USD)"
    link: "/orders?month={{ month }}"      # Click-through URL template (drill-down)

    style:                    # Chart-local style patch (typed; not raw CSS) — paint only
      aspect_ratio: 2.0       # shape without a fixed size; height = width / aspect_ratio
      number_format: ",.0f"   # D3 format string or named alias for axis/tooltip format
      # bar/area families also accept style.orientation and style.stack
```

### Chart types (16 authorable)

Set `type:` to one of:

**Basic** (one mark per chart) -- `bar`, `line`, `area`, `scatter`, `pie`, `donut`, `kpi`, `table`.

**Statistical** -- `histogram`, `heatmap`.

**Geographic** -- `geoshape`, `map`, `point_map`, `bubble_map`.

**Overlays** -- `bar`, `line`, `area`, and `scatter` accept a `layers:` field for mixed-mark or dual-axis charts (see [Combo charts](#combo-charts-barlinearea-with-layers) and [Composition](#composition)).

**Sparklines** -- `spark_bar` (compact horizontal bars used in profiler cards).

**Auxiliary** -- `callout` (message card with a `style.tone:` field; `message:` required).

Note: `donut` is an internal alias for `pie` -- `donut` is accepted but normalizes to `pie` internally. `auto` is an internal sentinel (not authored). `boxplot`, `errorbar`, and `errorband` are Vega-Lite mark types that are not in the authorable surface.

Type aliases: `scatter` uses a circle mark, `heatmap` uses rect, `pie`/`donut` use arc, `histogram` uses bar with binning, `map` maps to geoshape.

### Shared chart fields

All chart types accept the channels and style fields below — but each type rejects fields that don't belong to it (e.g. `theta` on a bar chart, `x` on a pie chart).

| Field | Type | Description |
|-------|------|-------------|
| `x` | string | X-axis field |
| `y` | string \| list[string] | Y-axis field(s) — list for multi-series |
| `color` | string \| object | Field name, `{value}`, `{field, scale}`, or `{field, when}` |
| `size` | string | Field for size encoding |
| `shape` | string | Field for shape encoding |
| `opacity` | string \| object | Field name or `{field, scale}` |
| `stroke` | object | `{color, width}` — each accepts field/scale/when |
| `theta` | string | Angular field (pie/donut/arc) |
| `style.inner_radius` | float 0–1 | Donut hole ratio (hole/outer disk; pie/donut only); `type: donut` sets it to `0.6` automatically |
| `total` | object | `{label, format}` — center total for donut |
| `style.marks.slice.labels` | object | `{template, where}` — per-row Jinja annotations near slice callouts |
| `x_label` | string | X-axis title override |
| `y_label` | string | Y-axis title override |
| `message` | string | Static text for `type: callout` |
| `geo` | string \| object | GeoJSON field or inline spec (geoshape) |
| `geo_source` | string | Named geographic data source |
| `lookup` | string | Field that joins to the geographic source key |
| `value` | string | KPI: column reference (string column name); map: data field for fill color |
| `projection` | string \| object | Projection name (e.g. `mercator`, `albersUsa`) or VL projection config |
| `latitude` | string | Latitude field (point/bubble map) |
| `longitude` | string | Longitude field (point/bubble map) |
| `background` | string \| object | Background channel — color, `{value}`, `{field, scale/when}`, or map layer |
| `sort` | object | `{by, order}` — categorical sort. Horizontal bar charts default to value-descending order when omitted. |
| `link` | string | Click-through URL template for drill-down links |
| `layers` | list | Overlay layers on cartesian charts (`bar`/`line`/`area`/`scatter`) — see [Combo charts](#combo-charts-barlinearea-with-layers) |
| `conditional_formatting` | object | Discrete style rules by column (see [Conditional formatting](#conditional-formatting)) |
| `data_table` | list | Attached mini-table beneath bar/line/area charts (including those with `layers:`) — see [Composition](#composition) |
| `height` | int \| float | Exact pixel height. Wins over `aspect_ratio` and theme defaults. Bypasses `min_height`/`max_height`. Not valid on `kpi`, `table`, `callout`, `spark_bar`. |
| `aspect_ratio` | float | Chart shape: `height = width / aspect_ratio`. Theme default is `1.5`. Not valid on `kpi`, `table`, `callout`, `spark_bar`. |
| `min_height` | float | Height floor for this chart only; overrides `style.charts.min_height`. Ignored when `height` is set. |
| `max_height` | float | Height ceiling for this chart only; overrides `style.charts.max_height`. Ignored when `height` is set. |

`height` and `aspect_ratio` live at **chart root** — they are rejected under `style:`. `style:` is paint only (colors, fonts, marks).

KPI-only fields: `value`, `label`, `support`. KPI uses `label:` for the header text — `title:` is rejected on KPI charts. Chart-root `format:` / `formatter:` is rejected on all chart types. Use the family slot instead:

| Family | Format slot |
|--------|-------------|
| `line`, `bar`, `area`, `scatter`, `heatmap` | `style.number_format` or `style.axis_y.format` |
| `kpi` value | `style.value.format` |
| `kpi` support | `support.format` |
| `table` column | `style.columns.<col>.format` |

`glyph` and `tone` at chart root are also rejected on KPI — use `style.glyph.character` for the glyph. `tone` has no style-level home: it lives only on `support.tone`, since the support row is the block it paints (the headline value stays neutral). Override the value/glyph color directly with `style.color` — it paints both the headline value and its glyph.

Top-level chart fields shared by all types: `id`, `query`, `type`, `title`, `subtitle`, `description`, `height`, `aspect_ratio`, `style`, `link`, `conditional_formatting`.

### Chart-type cheatsheet

Each block below shows the minimum-viable shape for one chart type. They are stacked for compactness; in a board, each chart sits under its own key in `charts:`.

```yaml-schema
# bar — categorical x, numeric y
type: bar
x: category
y: value
color: group           # Optional second dimension; grouped side by side by default
style:
  orientation: vertical  # vertical = column chart; horizontal = horizontal bar chart.
                          # Auto-resolves from x's column type when omitted: categorical x → horizontal.
  stack: zero            # see the stack table under "area" — bar takes the same values

# line — temporal/ordered x, numeric y
type: line
x: date
y: revenue
color: segment         # Optional: one line per segment

# area — same encoding as line; filled below
type: area
x: date
y: value
color: segment         # Required for stacking — stack modes split by this field
style:
  # stack names the shape you get. All four values work on bar and area alike:
  stack: zero          # stacked
  # stack: none        # overlapping — bar groups side by side, area overlays.
                        # The default when color: is set.
  # stack: normalize   # 100% stacked — every column fills the full height
  # stack: center      # streamgraph — stacked around a centered baseline

# scatter — x and y numeric
type: scatter
x: spend
y: revenue
color: region
size: volume           # Optional bubble size

# pie / donut — pre-aggregated; one row per segment
type: pie
theta: revenue
color: segment
style:
  inner_radius: 0.6    # 0 = solid pie; >0 = donut (type: donut sets 0.6 by default)
  marks:
    slice:
      labels:
        template: "{{ segment }}\n{{ revenue | format(',.0f') }}"
total:
  label: Total
  format: integer

# kpi — requires exactly 1 row; value: is a column reference
type: kpi
value: total_revenue    # column name (always a column reference)
label: "Total Revenue"  # NOT `title:` — `title:` is rejected on KPI
style:
  value:
    format: ",.0f"       # number format; `format:`/`formatter:` at chart root is rejected on KPI
  glyph:
    character: "▲"       # glyph character; moved from chart root (ADR-001)
# To override glyph or value color: style.color (paints both)
# The headline value has no tone field — it stays neutral by design (NYT/FT
# convention). Tone lives on the block it paints: the support row.
support:                # Optional support line (same shape: value/label/format/glyph/tone)
  value: prev_revenue
  label: "vs last month"
  format: percent_delta
  glyph: "▲"
  tone: positive         # positive | negative | warning — colors this row only

# table — renders all query columns unless `style.columns` selects a subset
type: table
style:
  columns:
    - column: order_id
    - column: amount
      label: Amount
      format: currency_whole
      align: right                       # left | center | right
      header_overflow: wrap-two          # clip | truncate | wrap-two (default) | wrap
      header_link: "/columns/amount"
      link: "/orders?id={{ order_id }}"
      background: dbt-grays.canvas
      font: { color: dbt-grays.ink, weight: "600" }
      scale:
        background:
          palette: dbt-seq-blue                # palette name, or an explicit stop list
          domain: data                   # currently only "data"
          min: 0
          max: 1000000
          null_color: dbt-grays.surface-subtle
          hinge: auto                    # number | "auto"
          arm_mode: asymmetric           # asymmetric | symmetric
      spark:
        type: line                       # line | area | bar | bar-normalize | columns
        color: category[1]
        height: 24
        last_visible: true
      width: 120                         # int (px) or string
      glyph: "!"
      glyph_color: warning.solid

# heatmap — pre-aggregated; one row per (x, y) cell
type: heatmap
x: day_of_week
y: hour
color: event_count

# histogram — pre-bin in SQL OR use Vega-Lite binning behavior
type: histogram
x: amount

# geoshape — choropleth via GeoJSON
type: geoshape
geo_source: us-states
lookup: state
value: revenue

# map — generic choropleth (alias for geoshape with named source)
# world-countries/world-50m join on numeric TopoJSON ids such as 840, not ISO alpha codes.
type: map
geo_source: us-states
lookup: state
value: revenue

# point_map / bubble_map — lat/lng points (optional size for bubble)
type: point_map
latitude: lat
longitude: lng

type: bubble_map
latitude: lat
longitude: lng
size: events
color: severity

# spark_bar — compact horizontal bars (used inline in profiler cards)
type: spark_bar
x: rank
y: count

# Pure marks (advanced use — not accepted as base chart types):
# circle, square, tick, rule, trail, rect, arc, image

# callout — message card with a style.tone: field (info | negative | warning | positive)
type: callout
message: "Query is disabled in this environment."
style:
  tone: warning  # optional; defaults to info

```

### Combo charts (bar/line/area with layers)

```yaml
type: bar
x: month
y: actual
layers:
  - type: line                      # bar | line | area | scatter
    y: target
    label: Target
    axis_y:
      position: right              # left | right
      title: "Target"
```

The base chart (`type: bar`, `type: line`, or `type: area`) sets the primary mark, `x`, `y`, and `query`. Additional marks go in `layers:`. Each layer accepts: `type`, `y`, `label`, `color` (data channel, bare field name), `query` (overrides the base chart query for this layer), `x` (layer x-values extend the base x-scale), `axis_y`, and `style` (marks-only patch). Vega-Lite `encoding:` is not allowed inside a layer — use the typed channels.

### Conditional formatting

Discrete, rule-driven style overrides applied per column. Each entry under `conditional_formatting:` is keyed by column name and contains a `when:` list of rules.

```yaml
charts:
  accounts_table:
    type: table
    query: accounts
    conditional_formatting:
      status:
        when:
          - in: [blocked, escalated]      # predicate (exactly one per rule)
            background: negative.bg        # style output (at least one required)
            font:
              color: negative.text
              weight: "600"
          - is_null: true
            glyph: "!"
            glyph_color: warning.solid
          - default: true                  # must be LAST in the list when present
            font: { color: dbt-grays.ink }
```

Predicates (exactly one per rule): `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `between` (`[low, high]`), `in` (non-empty list), `is_null` (bool), `default` (`true` only — terminal fallback).

Style outputs (at least one per rule): `background`, `font` (color/weight/style/decoration), `glyph` (with optional `glyph_color`).

If `default: true` is set, it must be the last rule in the `when` list. Earlier rules win in order.

### Composition

Dataface composes charts in three ways:

1. **`layers:` on a base chart** — multiple marks share one x-axis and frame. The base chart (`type: bar`, `type: line`, `type: area`, or `type: scatter`) owns the x-axis, frame, title, legend container, and `sort`. Each layer defaults to the base `query:` but may declare its own `query:` — layer x-values extend the base x-scale rather than clip it. See [Combo charts](#combo-charts-barlinearea-with-layers) above.

2. **`data_table:` attached to a chart** — a mini cross-tab strip rendered below the chart, columns aligned to the chart's x-axis ticks. Supported on `bar`, `line`, and `area` charts (including those with `layers:`).

   ```yaml
   charts:
     revenue_trend:
       type: line
       query: monthly
       x: month
       y: revenue
       data_table:
         - source: revenue          # Read raw per-x value
           label: "Revenue"
           format: integer
         - aggregate: sum            # Per-x aggregate
           source: orders
           format: integer
           label: "Orders"
         - aggregate: avg
           source: order_value
         - per_series: revenue       # One row per color: series (requires `color:` on the chart)
   ```

   Each entry is one of three shapes (discriminated by which key is present):
   - `source:` — read the raw per-x value (no aggregation).
   - `aggregate:` + `source:` — apply an aggregate per x-group (`sum`, `avg`, `min`, `max`, `median`, `count`, `count_distinct` — exact names only, no aliases).
   - `per_series:` — expand into one row per `color:` series (requires the chart to have a `color:` channel).

   Optional per-entry fields: `format` (D3 format string), `label` (left-stub row label; not allowed on `per_series:`).

   Constraint: data_table requires a single chart-level `x:`. Layered charts with per-layer `x:` differing from the chart-level x are rejected.

3. **Layout composition** — the `rows`, `cols`, `grid`, `tabs` structure in [Layout](#layout). Layout composes charts into a board; chart-level composition belongs to `layers:` (overlays) and `data_table:`.

Non-goals (not part of the authored chart surface): Vega-Lite `encoding`, `mark`, `spec`, `config`, `transform`, `params`, `resolve`, `hconcat`, `vconcat`, `concat`, `repeat`. These keys are rejected at compile time. Use the typed channels (`x`, `y`, `color`, …) and `style:` instead; use the layout primitives for visual composition.

**See also:** `dct docs queries` (charts reference queries by name),
`dct docs variables` (use `{{ var }}` in chart queries),
`dct docs layout` (compose charts on the page),
`dct docs cheatsheet` (one-page essentials).

## Color

Colors are palette tokens, not hex — the theme resolves a token, so a board restyles itself on a theme switch.

| Want | Write |
|---|---|
| A series slot | `category[1]`, `category_dark[2]`, `category_light[3]`, `category_ghost[1]` |
| Good / bad / attention | `positive.solid`, `negative.solid`, `warning.solid`, `info.solid` — also `.bg`, `.subtle`, `.border`, `.text` |
| Chrome — text, grid, borders | `dbt-grays.ink`, `dbt-grays.muted`, `dbt-grays.border`, `dbt-grays.separator`, `dbt-grays.canvas` |
| A ramp for a continuous scale | `dbt-seq-blue`, `dbt-div-blue-red`; `:N` stops and `_r` reversed — `dbt-seq-blue:5_r` |
| A pin that must survive a theme switch | `vivid-10.1`, `dbt-seq-blue.3` |

Indices are 1-based, and two scopes take less than the table above implies:
`palette:` wants a palette name or a list of stops, never a single scalar hex;
and `conditional_formatting` takes the dotted tokens (`negative.bg`) but not the
bracket ones (`category[1]`). Author hex in those. Everywhere else a hex literal
is accepted too — the right choice only for a brand color that must not move.

```yaml
style:
  color:
    static: category[2]       # a literal color lives here, not at chart root
```

## Variables

Variables are the interactive filter layer. Each variable has an `input:` widget type and optional defaults / options.

```yaml
variables:
  region:
    input: select
    label: "Region"
    description: "Restrict every query to one region."
    options:
      static: [US, EU, APAC]
    default: US
```

Input types (14 total):

| Input | Widget |
|-------|--------|
| `auto` | Auto-detect from `options` shape (the default) |
| `select` | Single-value dropdown |
| `multiselect` | Multi-value dropdown |
| `input` | Plain text input (alias for `text` in some surfaces) |
| `text` | Free-text input |
| `textarea` | Multi-line text input |
| `number` | Numeric input |
| `slider` | Single-handle numeric slider |
| `range` | Two-handle numeric slider (returns `[low, high]`) |
| `date` | Single date picker (also `datepicker`) |
| `datepicker` | Single date picker |
| `daterange` | Date range picker (returns `[start, end]`) |
| `checkbox` | Boolean toggle |
| `radio` | Radio group |

Common variable fields:

| Field | Type | Description |
|-------|------|-------------|
| `input` | enum | One of the input types above |
| `label` | string | UI label |
| `description` | string | Helper text below the input |
| `default` | any | Default value when no URL param is set |
| `placeholder` | string | Placeholder text |
| `required` | bool | Block rendering until a value exists |
| `allow_null` | bool | `null` is a valid selection |
| `visible` | bool | Hidden when `false`; still settable via URL param |
| `disabled` | bool \| string \| `{query, column}` | Static, Jinja expr, or query-backed disable |
| `data_type` | string | Upstream type hint (informational; preserved through migrations) |

Slider / range fields: `min`, `max`, `step`.

Filter-generation field: `operator` — SQL operator used when generating predicates (e.g. `=`, `IN`, `LIKE`).

Options sources (for `select`, `multiselect`, `radio`):

```yaml
variables:
  product:
    input: select
    options:
      static: [All, Electronics, Clothing]    # Hardcoded list
      # OR
      query: products_list                     # Query whose first column is the option list
      column: product_name                     # Optional: which column in that query
      label_column: product_label              # Optional: separate label column

  region:
    input: select
    column: orders.region                      # Auto-populate from a database column
```

Top-level option-source binding (alternative to `options:`): `column`, `query`, `dimension` (MetricFlow), `measure` (MetricFlow), `model` (dbt).

Top-level `column` is `table.column`, and the table may be schema-qualified when it is not in the connection's default schema — `column: gis.fact_sales.property_type`. `filter()` accepts the same qualified form.

Enabled/disabled forms (`enabled: false` means the control is inactive):

```yaml
variables:
  # Static bool — enabled: false disables the control
  closed: { input: checkbox, enabled: false }

  # Jinja expression against current variable values
  q4_only: { input: select, options: { static: [Q4] }, enabled: "{{ year >= 2024 }}" }

  # Query-backed (must return exactly 1 row with the named boolean column)
  territory:
    input: select
    options: { query: territory_options }
    enabled:
      query: control_state
      column: territory_enabled
```

**Multiselect SQL antipattern** — the first instinct for filtering a multiselect variable in SQL is `IN ({{ plans | map('tojson') | join(', ') }})`. This is wrong: `tojson` produces double-quoted strings (`"trial"`), which most SQL dialects (including DuckDB) treat as *column references*, not string literals. The query silently returns an empty result and `dct render` exits 0.

Use `{{ filter('plan', plans) }}` instead — it emits a correctly quoted `IN (...)` predicate for multiselect and a simple `=` predicate for single-select:

```sql
-- WRONG: silent empty result
WHERE plan IN ({{ plans | map('tojson') | join(', ') }})

-- CORRECT
WHERE {{ filter('plan', plans) }}
```

**Numeric arithmetic antipattern** — `{{ n | int }}` and `{{ n | float }}` raise an error on parameterized variables. Jinja's `| int` filter calls `int(value)` internally; on a parameterized variable this would silently return 0, so Dataface rejects it instead. Write SQL arithmetic directly on the variable:

```sql
-- WRONG: raises ERR-JINJA-ERROR at render time
INTERVAL -({{ months | int - 1 }}) MONTH

-- CORRECT: {{ months }} emits the bound parameter; the database handles arithmetic
INTERVAL -({{ months }} - 1) MONTH
```

`{{ n }}` emits a bound parameter (`$1`, `%s`, `?` depending on dialect), whether or not the query composes another with `{{ queries.X }}` — a reference expands as text and the variables around it are bound in the single render that follows. `{{ n | int }}` and `{{ n | float }}` raise either way, so adding or removing a `{{ queries.X }}` reference cannot change the value a variable produces. Arithmetic, casting, and type coercion belong in the SQL expression around the variable, not in a Jinja filter.

Common mistakes (the validator rejects these — listed here so authors don't hit them):

- `options.values: [...]` → use `options.static: [...]`.
- `default:` nested inside `options:` → put `default:` at the variable level.
- `options: [a, b]` (bare list) → use `options.static: [a, b]`.
- Using a `variables.` namespace prefix inside Jinja → drop it and reference the bare variable name (e.g. `{{ region }}`).

**See also:** `dct docs queries` (variables are injected into SQL),
`dct docs board` (`variables:` is a top-level board field),
`dct docs cheatsheet` (minimal variable example).

## Layout

Choose exactly one of `rows`, `cols`, `grid`, `tabs` at the board top level (or use `text:` for a text-only board). Layouts nest freely. The block below shows all four side by side; in a real board you pick one.

```yaml-schema
# rows — vertical stack
rows:
  - cols: [kpi_1, kpi_2, kpi_3]         # Equal-width row of charts
  - cols: [big_chart, 2]                # big_chart takes 2 fractional columns
  - text: |                              # Markdown block as a row
      ## Trends
      Revenue has been increasing since Q2.
  - revenue_trend                        # Bare chart name = one chart per row
  - cols: [breakdown_a, breakdown_b]
  - detail_table

# cols — horizontal arrangement at the top level
cols:
  - rows: [kpi_revenue, kpi_users]
  - rows: [trend_chart]

# grid — CSS-grid placement with explicit positioning
grid:
  columns: 24
  default_width: 8
  default_height: 1
  row_height: "120px"
  gap: md                                # sm | md | lg | xl
  items:
    - item: kpi_revenue
      col: 0
      row: 0
      width: 8                            # alias for col_span
      height: 1                           # alias for row_span
    - item: trend_chart
      col: 0
      row: 1
      width: 24

# tabs — tabbed navigation
tabs:
  id: view                                # URL param + variable name (auto if omitted)
  position: top                           # top | left
  default: overview
  items:
    - title: Overview
      icon: 📊
      description: "KPIs and trend"
      rows: [kpi_revenue, trend_chart]
    - title: Details
      rows: [detail_table]
    - title: Notes
      text: |
        Operational notes go here.
      style: { padding: 16 }
```

### Section-level fields (per `rows` / `cols` entry)

```yaml
rows:
  - title: "Revenue overview"      # Section heading
    description: "AI/tooltip context for the section."
    text: "Monthly trend data."    # Markdown narrative above charts
    details:                       # Collapsible
      summary: "Click to expand"
      expanded_title: "Hide"
      expanded: false
    cols: [rev_chart, units_chart]  # Use one of: cols, rows, grid, or tabs
```

### Layout visibility (`visible`)

Layout items and chart references support a `visible` field that omits the item
from the rendered output when its condition is falsy.

Accepted forms:

| Form | Example | Behaviour |
|------|---------|-----------|
| Omitted | — | Always shown (default) |
| Static bool | `visible: false` | Always hidden / always shown |
| Variable name | `visible: show_panel` | Hidden when the variable is falsy; raises if the variable is absent (use `variables.show_panel.default` to ensure it is always defined) |
| Jinja expression | `visible: "a and b"` | Evaluated as a boolean Jinja expression; no `{{ }}` required |
| Query probe | `visible: {query: flags, column: show_warm}` | Executes the named query; must return **exactly 1 row** with a boolean-coercible value |

`visible` applies to:
- Bare chart name items (`- chart_name`)
- Inline chart items (`- query: ... type: ...`)
- Nested board items (`rows:`, `cols:`, `text:`, etc.)

> **Layout reflow:** In `rows:` layouts, hidden items collapse and the next item
> moves up. In `cols:`, `grid:`, and `tabs:` layouts, the slot keeps its
> pre-computed position — hiding leaves a blank gap. Use `rows:` when you need
> items to reflow around hidden entries.

> **Distinction from `variables.visible`:** `variables.<name>.visible: false` hides the
> *input control* in the variable bar only — the variable is still active and URL-settable.
> Layout-item `visible` controls whether the item renders in the board at all.

```yaml
variables:
  show_details:
    input: checkbox
    default: false

rows:
  - summary_kpis

  - visible: show_details
    rows:
      - region_map
      - region_table
```

### Inline charts inside layout

A layout entry can carry a full chart definition instead of a chart name:

```yaml
queries:
  revenue: SELECT month, total FROM rev_daily

rows:
  - revenue_line:
      query: revenue
      type: line
      x: month
      y: total
```

The key under `rows:` becomes the chart's ID.

### Nested boards

A layout entry can be a fully nested board (its own rows/cols/charts and optional `id`, `style`, `width`, `height`, `theme`):

```yaml
rows:
  - id: side_panel
    width: "30%"
    style: { padding: 12 }
    rows:
      - kpi_1
      - kpi_2
```

**See also:** `dct docs charts` (chart references inside layouts),
`dct docs board` (`rows`/`cols`/`grid`/`tabs` are top-level board fields),
`dct docs cheatsheet` (minimal layout examples).

## Errors

Dataface errors carry a machine-readable code in the form `ERR-<SLUG>`. The error message includes the code and a pointer to docs; a separate `domain` field on the error records where it originated (the code string itself has no domain segment).

```
DbtChartsError [ERR-KPI-MULTIROW]: KPI chart 'revenue' returned 12 rows but `value` is a column reference.
  Add LIMIT 1 or aggregate down to one row.
```

Active domains (see `dbt_charts/core/diagnostics/codes_*.py` for the authoritative registry):

| Domain | Meaning |
|--------|---------|
| `compile` | Compile-time errors (missing fields, unknown references, malformed YAML) |
| `render` | Chart rendering errors (wrong row counts, unknown chart types, format issues) |
| `execute` | Query execution errors (missing sources, inline-source policy, source typing) |
| `serve` | Server startup errors (invalid theme, launch failures) |
| `unknown` | Fallback codes for legacy string-message errors not yet migrated |

The registry is being filled out incrementally — some compile-time and variable-resolution errors still raise as plain `DbtChartsError` without a structured code.

Run `dct docs errors` to list every registered code with a one-line summary, straight from `dbt_charts.core.diagnostics.REGISTRY`. Run `dct docs error-reference` for the full reference — message template and docs pointer included. (`dct docs warnings` / `dct docs warning-reference` are the equivalents for `WARN-*` codes.) Run `dct validate <board>` to validate a board and see structured error details.

**See also:** `dct docs queries`, `dct docs charts`, `dct docs variables` (where most errors originate),
`dct docs all` (whole reference for context).
