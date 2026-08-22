# dbt charts

**Declarative, dbt-native boards in YAML**

dbt charts (installed as `dbt-charts`, CLI `dct`) is a Python-based board framework that
compiles YAML board definitions into interactive visualizations. Queries run as plain
SQL against your warehouse by default — no dbt project required — with an optional,
deeper integration into dbt's Semantic Layer (MetricFlow) when you have metrics and
dimensions already defined there.

---

## Why dbt charts?

### The Problem

If you're a data analyst, you've probably experienced this:
- You have data in a warehouse (with or without dbt models on top of it)
- You want to build dashboards to share insights with your team
- But building dashboards requires learning complex BI tools, writing app code, or
  paying for a hosted platform

### The Solution

dbt charts lets you:
- **Write boards in YAML** — simple, human-readable format
- **Query with plain SQL** — or reference existing dbt Semantic Layer metrics, if you
  have them
- **Create interactive visualizations** — filters, drill-downs, and click actions
- **Share and collaborate** — boards are version-controlled YAML files
- **Stay in sync with dbt** — when you do use dbt, boards and models deploy together
  through Git branches, eliminating broken dashboards after data migrations

### How It Works

1. **You write a YAML file** describing what data to show and how to visualize it
2. **dbt charts compiles it** into an interactive board
3. **The board queries your warehouse** — plain SQL by default, or your dbt Semantic
   Layer (MetricFlow) if you reference metrics/dimensions instead
4. **Users interact** with filters, click charts, and explore the data

---

## Getting Started

### Prerequisites

- **Python 3.10-3.13**
- **dbt** project (optional but highly recommended)

### Install

```bash
uv tool install dbt-charts   # or: pip install "dbt-charts"
```

Verify:

```bash
dct --version
```

### Without dbt (optional)

If you don't already have a dbt project, install dbt charts with the warehouse adapter you need:

```bash
pip install "dbt-charts[bigquery]"
pip install "dbt-charts[databricks]"
pip install "dbt-charts[postgresql]"
pip install "dbt-charts[redshift]"
pip install "dbt-charts[snowflake]"
pip install "dbt-charts[spark]"
```

### MCP (optional)

dbt charts ships an MCP server for use with any compatible AI agent:

```bash
pip install "dbt-charts[mcp]"
dct init mcp
```

### Quick Start

```bash
# Bootstrap a new project
dct init

# Validate a board for errors
dct validate charts/guide.yaml

# Start a live preview server
dct serve
```

### Environment variables

`dct` reads `DCT_PROJECT_DIR` when no `--project-dir` is passed — handy in CI or when working in multiple project trees from one shell. The flag wins if both are set. See the [CLI environment variables reference](https://docs.dataface.com/cli/#environment-variables) for the full list (themes, ports, dbt overrides, etc.).

### Place boards in your dbt project (optional)

```
my-dbt-project/
├── dbt_project.yml
├── models/
├── charts/                  # Your boards here
│   ├── sales_overview.yml
│   ├── marketing.yml
│   └── finance.yml
└── assets/                  # Assets directory (optional)
    ├── images/             # Logos, icons, images
    └── data/               # CSV files and other data
```

A dbt project isn't required — `charts/` can live on its own, querying your warehouse
directly with plain SQL. Nesting it under a dbt project is what unlocks Semantic Layer
queries and Git-branch deploys in lockstep with your models.

---

## Key Features

### dbt-Native
- Queries run as plain SQL against your warehouse by default
- Optionally query dbt's Semantic Layer (MetricFlow) directly — no need to redefine metrics
- Reads your `profiles.yml` automatically
- Works with all dbt adapters (Snowflake, BigQuery, Postgres, etc.)
- Boards sync with dbt models through Git branches — no broken dashboards after data migrations

### Declarative YAML
- Human-readable, version-control friendly
- No code required
- AI-friendly format (perfect for LLMs to generate)

### Interactive Visualizations
- Variables/filters that update in real-time
- Click interactions (drill-down, set variables, filter)
- Built on Vega-Lite (declarative charting)

### Multiple Output Modes
- **Live mode:** Interactive web dashboard (FastAPI server)
- **Static mode:** Shareable HTML snapshot (data baked in)
- **PDF mode:** Printable/shareable PDF reports

### AI-First
- YAML is perfect for AI generation
- MCP server for any compatible AI agent (Cursor, VS Code, Claude Desktop, Codex)
- AI can create, modify, and iterate on dashboards

---

## Interactive Playground

Try dbt charts online without installing anything:

**[play.dataface.com](https://play.dataface.com)**

A split-pane YAML editor with live preview. No dbt project needed (uses sample data).

---

## CLI Commands

The CLI is called `dct`, intentionally mirroring `dbt` (Data Build Tool). Just as dbt transforms your data, dct transforms your boards.

### Validate

Validate boards for errors:

```bash
dct validate [PATH]

# Examples:
dct validate                        # Validate all in charts/
dct validate charts/                # Validate all in a directory
dct validate charts/guide.yaml       # Validate one file
dct validate --strict               # Fail on warnings
```

### Serve

Start interactive preview server:

```bash
dct serve [OPTIONS]

# Examples:
dct serve
dct serve --port 3000
dct serve --host 0.0.0.0  # bind on the LAN, not just localhost
```

### Render

Render one or more boards to a self-contained file:

```bash
dct render BOARDS... [OPTIONS]

# Examples:
dct render charts/guide.yaml --format html
dct render charts/guide.yaml --format pdf
dct render charts/guide.yaml --format png --output guide.png
dct render charts/guide.yaml --format json   # resolved layout + executed data
```

---

## Example Dashboards

### Simple KPI Dashboard

```yaml
title: "Executive KPIs"

queries:
  q_totals:
    metrics: [total_revenue, order_count, customer_count]

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
  customers:
    label: "Total Customers"
    query: q_totals
    type: kpi
    value: customer_count

rows:
  - title: "Key Metrics"
    cols:
      - revenue
      - orders
      - customers
```

### Interactive Dashboard with Filters

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
    cols:
      - revenue_trend
```

---

## Architecture

dbt charts is built on:

- **Python 3.10+** - Core language
- **Pydantic** - Schema validation and data models
- **Jinja2** - Template engine (same as dbt!)
- **Vega-Lite** - Declarative charting via `vl-convert`
- **FastAPI** - Web server for live mode
- **dbt adapters** - Direct database access

### How It Works

```
YAML Board → Python Compiler → Vega-Lite Specs → Renderer
                  ↓
              (Validation)
                  ↓
    Warehouse (SQL or dbt MetricFlow) → Query Data → Charts
                  ↓
           Live HTML or Static PDF
```

---

## Comparison to Other Tools

| Feature | dbt charts | Lightdash | Looker | Superset |
|---------|----------|-----------|--------|----------|
| **Format** | YAML | UI + YAML | LookML | UI |
| **dbt Integration** | SQL, or native (MetricFlow) | dbt metrics | Separate | Limited |
| **Installation** | `pip install dbt-charts` | Self-host + PostgreSQL | Enterprise license | Self-host + database |
| **Version Control** | Native (Git) | Export/Import | Native (Git) | Limited |
| **AI-Friendly** | YAML | UI-first | LookML | No |
| **Static Export** | PDF, HTML | No | Enterprise only | No |

---

## Documentation

- [Getting Started Guide](https://docs.dataface.com/guides/getting-started/) — Step-by-step onboarding
- [YAML Style Guide](https://docs.dataface.com/guides/yaml-style-guide/) — Board YAML conventions
- [CLI Reference](https://docs.dataface.com/cli/) — All `dct` commands
- [Chart Types](https://docs.dataface.com/charts/types/) — Available chart types and configuration
- [Variables & Filters](https://docs.dataface.com/variables/) — Interactive variables and UI elements

---

## Contributing

This project is developed in a private upstream repository and mirrored here read-only
— pull requests against this repository are not accepted and will be closed (see
[CONTRIBUTING.md](https://github.com/dbt-labs/dbt-charts/blob/main/CONTRIBUTING.md)). Bug reports and feature requests are welcome via
[GitHub Issues](https://github.com/dbt-labs/dbt-charts/issues).
