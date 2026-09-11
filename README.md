# dbt charts

**Declarative, dbt-native boards in YAML**

[dbt charts](https://dbtcharts.com) (package `dbt-charts`, CLI `dct`) compiles YAML board definitions into
interactive boards, static HTML, and PDF reports. Queries run as plain SQL against
your warehouse — no dbt project required, though dbt models are queried the same way
(via `ref()`) when you have one.

Try it without installing anything at **[play.dbtcharts.com](https://play.dbtcharts.com)**.

> This repository is a read-only mirror of a private upstream. Issues are welcome;
> pull requests are not accepted. See
> [CONTRIBUTING.md](https://github.com/dbt-labs/dbt-charts/blob/main/CONTRIBUTING.md).

---

## Why

Boards are YAML files in Git, so they version, review, and deploy like the rest of your
project. No BI tool to learn, no app code to write, no hosted platform required. When
boards live inside a dbt project, they move through branches in lockstep with the models
they query: a column rename and the boards that read it ship in one PR.

YAML is also a format LLMs generate and edit reliably, which is why dbt charts ships an
MCP server and a set of board-authoring skills for agents.

---

## Getting started

Requires Python 3.10 to 3.13.

```bash
uv tool install dbt-charts   # or: pip install dbt-charts
dct --version
```

`dct` talks to your warehouse through dbt adapters. Inside an existing dbt project the
adapter is already installed; otherwise install the one you need as an extra:

```bash
uv tool install "dbt-charts[bigquery]"  # or: pip install "dbt-charts[bigquery]"
                                         # also: databricks, postgresql, redshift,
                                         # snowflake, spark, trino
```

Using a coding agent? Hand it one sentence. `dct skills intro` teaches it the tool
and which skill to read next:

```text
Make charts of this with dbt charts. Start with: uv tool install dbt-charts && dct skills intro
```

By hand:

```bash
dct init                        # bootstrap a project (creates charts/guide.yml)
dct validate charts/guide.yml   # check board YAML for errors, no warehouse needed
dct serve                       # live preview server
```

### Project layout

```
my-dbt-project/
├── dbt_project.yml
├── models/
├── charts/                  # boards live here
│   ├── sales_overview.yml
│   └── finance.yml
└── assets/                  # optional: images/, data/
```

A dbt project isn't required — `charts/` can stand alone and query your warehouse
directly. Nesting it under a dbt project is what unlocks branch-based deploys in lockstep
with your models.

### MCP and agent skills

```bash
uv tool install "dbt-charts[mcp]"   # or: pip install "dbt-charts[mcp]"
dct init mcp      # wire the MCP server into Cursor, VS Code, Claude Desktop, Codex, …
dct init skills   # install board-authoring skills for file-based agent discovery
```

---

## CLI

The CLI is `dct` (**d**bt **c**har**t**s), mirroring `dbt`.

```bash
dct validate [PATH]           # default: everything under charts/; --strict fails on warnings
dct serve [--port N] [--host H]
dct render BOARD... --format {html,pdf,png,svg,json}
dct query SOURCE 'SELECT …'   # run raw SQL, or a named board query
dct search <query>            # find boards by keyword
dct impact <column>           # which boards reference a column
dct docs [TOPIC]              # built-in YAML reference
dct examples [SLUG]           # bundled board specimens
```

`dct` reads `DCT_PROJECT_DIR` when `--project-dir` is not passed. The
[CLI reference](https://docs.dbtcharts.com/cli/#environment-variables) lists every
environment variable.

---

## Examples

A KPI row:

```yaml
title: "Executive KPIs"

queries:
  q_totals:
    source: warehouse
    sql: |
      SELECT SUM(revenue) AS total_revenue,
             COUNT(*) AS order_count
      FROM orders

charts:
  revenue:
    label: "Total Revenue"
    query: q_totals
    type: kpi
    value: total_revenue
  orders:
    label: "Total Orders"
    query: q_totals
    type: kpi
    value: order_count

rows:
  - title: "Key Metrics"
    cols: [revenue, orders]
```

Variables become filter UI, and macros expand them into safe SQL predicates:

```yaml
title: "Sales Dashboard"

variables:
  date_range:
    input: daterange
    default: ["2024-01-01", "2024-12-31"]
  region:
    input: multiselect
    options:
      static: ["North", "South", "East", "West"]
    default: ["North", "South"]

queries:
  q_sales:
    source: my_db
    sql: |
      SELECT month, region, SUM(revenue) AS revenue
      FROM sales
      WHERE {{ filter_date_range('order_date', date_range) }}
        AND {{ filter('region', region) }}
      GROUP BY month, region

charts:
  revenue_trend:
    title: "Revenue Over Time"
    query: q_sales
    type: line
    x: month
    y: revenue
    color: region

rows:
  - title: "Revenue Trends"
    cols: [revenue_trend]
```

---

## How it works

```
board YAML → compile (validate, resolve theme + layout)
           → execute (SQL against your warehouse via dbt adapters)
           → render  (Vega-Lite specs → live HTML, static HTML, PDF, PNG, SVG)
```

Built on Pydantic (schema validation), Jinja2 (templating, as in dbt), Vega-Lite via
`vl-convert` (charting), and FastAPI (the preview server).

---

## Documentation

- [Getting started](https://docs.dbtcharts.com/guides/getting-started/)
- [YAML style guide](https://docs.dbtcharts.com/guides/yaml-style-guide/)
- [CLI reference](https://docs.dbtcharts.com/cli/)
- [Chart types](https://docs.dbtcharts.com/charts/types/)
- [Variables and filters](https://docs.dbtcharts.com/variables/)

---

## Contributing

Development happens in a private upstream repository and is mirrored here read-only.
Pull requests opened against this repository are closed unmerged; bug reports and feature
requests are welcome via [GitHub Issues](https://github.com/dbt-labs/dbt-charts/issues).
See [CONTRIBUTING.md](https://github.com/dbt-labs/dbt-charts/blob/main/CONTRIBUTING.md)
and [SECURITY.md](https://github.com/dbt-labs/dbt-charts/blob/main/SECURITY.md).

## License

[Apache License 2.0](https://github.com/dbt-labs/dbt-charts/blob/main/LICENSE).
