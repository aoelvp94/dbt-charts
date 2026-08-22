---
name: board-structural-review
kind: workflow
description: >
  Review a Dataface board's YAML structure and content choices without rendering.
  Reads the board file, runs schema validation, then evaluates the YAML against
  a design checklist (chart-data shape match, layout intent, variable wiring,
  descriptive naming, anti-patterns). Use when asked to 'review this
  dashboard', 'check this board', 'is this YAML well-shaped', 'find problems in
  this dashboard', or after editing a board before delivery. Cheap — no
  rendering, no PNG, no LLM judge in the loop. Do NOT use for visual problems
  that need to be seen (use board-visual-review). Do NOT use as a YAML
  linter substitute — schema validation already covers that.
metadata:
  author: fivetran
---

# Dashboard Structural Review

Read the board's YAML, run `{{ s_validate_board }}`,
then evaluate the design choices encoded in the YAML against a checklist.
Produces a markdown findings list with severity tags. No rendering required —
this is the cheap pass.

## When to use

- Post-build sanity check before delivering a new board
- Post-edit verification after adding charts, queries, or variables
- Pre-PR review of a board change
- First pass inside the `board-review` orchestrator

## When NOT to use

- Schema validation alone — `{{ s_validate_board }}`
  is the right tool, this skill calls it
- Visual problems ("the legend is overlapping the title") — use
  `board-visual-review`
- Comparing two versions of a board — use `looker-compare-diff` pattern instead

## Protocol

1. **Validate.** Run `{{ s_validate_board }}`
   on the board path:

   {{ s_validate_example }}

   If validation reports errors, surface them and stop — there's nothing to
   review until the schema is valid.

2. **Read the board YAML** with the agent's file-reading tool.

3. **Evaluate against the checklist below.** For each finding, emit a row with
   severity, the YAML path or chart name, and a concrete fix.

## Checklist

### Layout intent

- [ ] Top of the board is a summary (KPI row, hero metric) — not a detail table
- [ ] Reading order (top-down, left-to-right) tells a story: headline → trend →
      breakdowns → detail
- [ ] Related charts are grouped (same `cols:` row or adjacent rows)
- [ ] No more than 8 visualizations on one board — unless the user asked for
      more or the board replicates a larger source (board-replicate)

### Chart-data shape match

- [ ] `type: kpi` queries return **exactly 1 row** (aggregate, not raw)
- [ ] `type: pie` queries are pre-aggregated and have **2–3 segments** (use
      `bar` for 4+)
- [ ] `type: line` / `area` use a temporal x-axis
- [ ] `type: bar` has a categorical x-axis (not a continuous date)
- [ ] `type: table` columns make sense as a list — no 1-row tables, no
      single-column tables that should be KPIs
- [ ] No single-bar bar charts (one bar = use a KPI)

### Variables and parameterization

- [ ] Filters declared in `variables:` are referenced by at least one query
- [ ] Queries don't hardcode values that should be variables (date ranges,
      categorical filters)
- [ ] Variable defaults are sensible (last 30 days, most common segment)
- [ ] Executive / always-on dashboards have **no** filter variables

### Descriptive metadata

- [ ] Every query has a `description:` (what it returns and why)
- [ ] Every chart has a `description:` (what question it answers)
- [ ] Every variable has a `description:` (how it should be used)
- [ ] Chart names communicate intent (`revenue_trend`, not `chart_1`)
- [ ] Titles state what the chart answers (`"Revenue by Region, Last 30 Days"`,
      not `"Sales"`)

### Anti-patterns

- [ ] No `kpi` displaying a string column (KPIs are numeric)
- [ ] No chart that exists without a clear question it answers
- [ ] No duplicated queries (same SQL repeated under different names)
- [ ] No raw / unaggregated data feeding a chart that requires pre-aggregation

### Formatting

- [ ] No raw D3 format strings — use named presets (`currency_compact`, not `"$,.2s"`)
- [ ] Cartesian charts use `style.number_format` (or `style.axis_y.format`) — **not** chart-root `format:`
- [ ] KPI values use `style.value.format` — **not** chart-root `format:`
- [ ] Table columns use `style.columns.<col>.format` (dict keyed by column name)
- [ ] Currency/percent columns have an explicit preset when render warnings flag missing formatters
- [ ] Integer columns where exact counts matter use `integer` preset (not SI compact)

**Preset reference**

| Preset | D3 equivalent | Example |
|--------|--------------|---------|
| `integer` | `",.0f"` | `1,234` |
| `number` | `",.2f"` | `1,234.56` |
| `currency` | `"$,.2f"` | `$1,234.56` |
| `currency_whole` | `"$,.0f"` | `$1,234` |
| `currency_compact` | `"$,.2s"` | `$1.2M` |
| `percent` | `".1%"` | `2.3%` |
| `percent_whole` | `".0%"` | `2%` |
| `percent_delta` | `"+.1%"` | `+2.3%` |
| `compact` | `",.2s"` | `1.2M` |
| `date_short` | `"%-d %b %Y"` | `26 May 2026` |

**Render-time format hints** (from `render_board` warnings — not compile-time auto-formatting)

When no explicit format is set, render may warn that a column looks like currency or percent. Fix by adding the preset in the correct slot (`style.number_format`, `style.value.format`, or `style.columns.<col>.format`) — not chart-root `format:`.

- Column name matches `*_pct`, `*_rate`, `*_ratio`, `*_share`, `*_proportion` → likely wants `percent`
- Column name matches `*revenue*`, `*amount*`, `*cost*`, `*price*`, `*spend*`, `*profit*`, `*fee*` → likely wants `currency_whole`
- Columns named `arr`, `mrr`, `acv`, etc. do **not** auto-trigger currency hints — set `currency*` explicitly

## Output format

A markdown bulleted list, severity-tagged. Group by severity, most severe first:

```markdown
**Findings**

- `blocker` `charts.revenue_kpi`: query returns 12 rows but `type: kpi` requires
  exactly 1. Aggregate with `SUM()` or take the latest row only.
- `warning` `charts.region_pie`: 7 segments in a pie chart — humans compare
  angles poorly past 3. Switch to `type: bar` ordered by value.
- `warning` `queries.orders`: no `description:` field. Add one sentence stating
  what the query returns.
- `nit` `charts.chart_1`: generic name. Rename to indicate intent
  (e.g. `daily_active_users`).
```

If there are no findings: emit exactly `**No findings.**` so the orchestrator
can short-circuit.

## Severity rubric

| Tag | Meaning | Examples |
|---|---|---|
| `blocker` | The board will render wrong, error, or mislead | KPI on multi-row query; bar chart on raw rows when GROUP BY is expected |
| `warning` | The board renders but violates a clear design principle | Pie with >3 segments; missing descriptions; generic titles |
| `nit` | Stylistic — author can take or leave | Suboptimal chart name; consistent-but-verbose pattern |

## Common mistakes

| Mistake | Fix |
|---|---|
| Returning "looks fine" without validating first | Always run `{{ s_validate_board }}` — if it fails, there's nothing to review |
| Padding findings with `nit`-level noise | Cap at 5 findings total; promote the most severe |
| Emitting findings without a concrete fix | Every finding needs an actionable suggestion |
| Inventing rules not in the checklist | Stay anchored to the checklist; if you discover a real gap, file a follow-up to extend the skill |

## Rationalizations to resist

| Excuse | Reality |
|---|---|
| "The user knows what they're doing" | Reviewing is the job. Apply the checklist. |
| "I'll just suggest the fix without the severity tag" | Severity is how the orchestrator ranks and the user prioritizes. Always tag. |
| "If I can't find anything, I'll find something" | If the board passes the checklist, say so. Padding erodes the skill's signal. |
