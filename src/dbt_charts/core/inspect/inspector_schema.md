# Inspector Output Schema

The inspector profiles database tables and writes results to `target/super_schema.json`.
This document is the schema reference for that output. Internally, this artifact
is the shared Super Schema: inspect is one producer of it, not its only reason
to exist.

If you're an AI agent building charts, writing SQL, or picking visualizations,
this is what you need to know about each column.

## File Structure

```json
{
  "version": 2,
  "generated_at": "ISO 8601 timestamp",
  "tables": {
    "<schema.table_name>": { "...table object..." }
  }
}
```

- `version` — schema version. Version 2 uses axes + flags (described below).
- `tables` — keyed by `schema.table_name` (or just `table_name` if no schema).
  Multiple tables can be stored in one file; `save_inspection()` merges by key.

## Table Object

```json
{
  "table_name": "orders",
  "schema_name": "public",
  "database_name": null,
  "profiled_at": "2026-02-08T12:00:00+00:00",
  "inspector_version": "2.0.0",
  "row_count": 50000,
  "column_count": 12,
  "primary_date_column": "created_at",
  "empty_columns": ["deprecated_field"],
  "high_null_columns": ["middle_name"],
  "columns": [ "...column objects..." ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `table_name` | string | Table name without schema prefix |
| `schema_name` | string or null | Database schema (e.g. `public`) |
| `database_name` | string or null | Database name if applicable |
| `profiled_at` | string (ISO 8601) | When this profile was generated |
| `inspector_version` | string | Version of the inspector that produced this |
| `row_count` | integer | Total rows in table at profile time |
| `column_count` | integer | Total columns |
| `primary_date_column` | string or null | The main date/time column for this table, if one exists. This is the column to use as the default time axis and for incremental queries. Selected by: first `role=time` + `is_incremental=true` column, falling back to first `role=time` column, or null if no time columns exist. Look up this column in `columns` to check `is_incremental` and other flags. |
| `empty_columns` | list of strings | Column names that are ≥99.9% null |
| `high_null_columns` | list of strings | Column names that are 50–99.9% null |
| `columns` | list of column objects | One per column, ordered by `order` field |
| `grain` | object or absent | Grain candidate describing what entity each row represents. See "Grain Object" below. |
| `relationships` | list or absent | Cross-table relationship edges with multiplicity and fanout metadata. See "Relationship Object" below. |

### Grain Object (optional, additive in contract v1.1)

Present when the inspector can infer what entity each row represents.

```json
{
  "grain": {
    "columns": ["order_id"],
    "label": "one row per order_id",
    "confidence": 1.0,
    "source": "primary_key",
    "is_composite": false
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `columns` | list of strings | Column(s) that define the grain |
| `label` | string | Human-readable description (e.g. "one row per order_id") |
| `confidence` | float (0.0–1.0) | Detection confidence (1.0 = explicit PK, 0.7 = heuristic) |
| `source` | string | Detection method: `primary_key`, `composite_key`, or `uniqueness` |
| `is_composite` | boolean | Whether grain spans multiple columns |

### Relationship Object (optional, additive in contract v1.1)

Present when cross-table relationships are detected from naming conventions and profile data.
The base relationship fields (`left_table` through `warnings`) are emitted by `RelationshipEdge`.
The `join_profile` and `fanout_risk` sub-objects are added by profiling-time
relationship enrichment — they are not part of the core `RelationshipEdge` serialization.

```json
{
  "relationships": [
    {
      "left_table": "orders",
      "left_column": "customer_id",
      "right_table": "customers",
      "right_column": "id",
      "multiplicity": "many-to-one",
      "confidence": 0.9,
      "source": "naming+key_role",
      "is_recommended": true,
      "warnings": [],
      "join_profile": {
        "multiplicity": "many-to-one",
        "fanout_factor": 1.0,
        "left_coverage": 1.0,
        "right_coverage": 1.0
      },
      "fanout_risk": {
        "level": "none",
        "reason": "N:1 dimension lookup — safe",
        "recommendation": "No action needed"
      }
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `left_table` | string | FK (referencing) table name |
| `left_column` | string | FK column name |
| `right_table` | string | PK (referenced) table name |
| `right_column` | string | PK column name |
| `multiplicity` | string | `one-to-one`, `one-to-many`, `many-to-one`, or `many-to-many` |
| `confidence` | float (0.0–1.0) | Detection confidence |
| `source` | string | Evidence sources (e.g. `naming+key_role+value_range`) |
| `is_recommended` | boolean | Whether confidence >= 0.80 |
| `warnings` | list of strings | Any detection warnings |
| `join_profile.multiplicity` | string | Full 4-way multiplicity from both sides' uniqueness |
| `join_profile.fanout_factor` | float | Average row multiplication (1.0 = no fanout) |
| `join_profile.left_coverage` | float (0.0–1.0) | Fraction of left rows with non-null join key |
| `join_profile.right_coverage` | float (0.0–1.0) | Fraction of right rows with non-null join key |
| `fanout_risk.level` | string | `none`, `low`, `medium`, `high`, or `critical` |
| `fanout_risk.reason` | string | Human-readable risk explanation |
| `fanout_risk.recommendation` | string | Actionable fix suggestion |

**`primary_date_column` selection heuristic:**
1. Prefer `role=time` + `is_incremental=true` columns (e.g. `created_at`)
2. Among those, prefer names in priority order: `created_at`, `created`, `date`, `timestamp`, `event_date`, `event_time`
3. Fall back to first `role=time` column even if not incremental
4. `null` if no time columns found

## Column Object

Every column has three layers of information:

1. **Identity** — what the column is (name, database type, semantic type)
2. **Classification** — what the column means (4 axes + boolean flags)
3. **Statistics** — raw numbers from the profiling queries

### Full Example

```json
{
  "order": 3,
  "name": "revenue",
  "database_type": "DECIMAL",
  "semantic_type": "currency_amount",
  "semantic_type_confidence": 0.9,

  "role": "measure",
  "distribution": "continuous",
  "completeness": "dense",
  "key_role": "none",

  "is_non_negative": true,
  "is_normalized": false,
  "is_zero_inflated": false,
  "has_outliers": true,
  "is_skewed": true,
  "is_incremental": false,
  "is_sequential": false,
  "is_fixed_length": false,
  "is_free_text": false,
  "is_ordinal": false,
  "is_currency": true,
  "is_geo": false,
  "is_pii": false,

  "null_percentage": 2.1,
  "distinct_count": 48234,
  "uniqueness_ratio": 0.965,
  "min_value": "0.50",
  "max_value": "99999.99",
  "mean_value": 142.37,
  "median_value": 89.00,
  "stddev_value": 312.45,
  "min_length": null,
  "max_length": null,
  "avg_length": null,
  "top_values": [
    {"value": "99.99", "frequency": 312}
  ],
  "enum_values": null
}
```

---

## Identity Fields

| Field | Type | Description |
|-------|------|-------------|
| `order` | integer | 1-based column position (matches SQL ordinal_position) |
| `name` | string | Column name |
| `database_type` | string | Raw database type (e.g. `VARCHAR`, `INTEGER`, `DECIMAL(18,2)`) |
| `semantic_type` | string or null | Detected meaning beyond the database type. See "Semantic Types" below. |
| `semantic_type_confidence` | float (0.0–1.0) | How confident the detection is. ≥0.7 is the minimum threshold. |

### Semantic Types

A column gets at most one semantic type. Types are either **format types** (how the data
is encoded — affects rendering) or **role types** (what it represents — affects analysis).
When both apply, role wins.

#### All 27 Implemented Types

| Type | Category | Example Values | Detection |
|------|----------|---------------|-----------|
| `email` | contact | `user@example.com` | Regex + column name hints |
| `phone` | contact | `+1-555-123-4567` | Regex patterns (US, international) |
| `url` | format | `https://example.com/path` | URL regex |
| `uuid` | identifier | `550e8400-e29b-41d4-...` | UUID v4 regex |
| `iso_date` | temporal | `2026-01-15` | `YYYY-MM-DD` pattern |
| `iso_datetime` | temporal | `2026-01-15T10:30:00` | ISO 8601 datetime pattern |
| `unix_timestamp` | temporal | `1706345400` | Integer in epoch range + column name hints |
| `latitude` | geo | `37.7749` | Float in -90..90 + column name hints |
| `longitude` | geo | `-122.4194` | Float in -180..180 + column name hints |
| `currency_amount` | numeric | `142.37` | Numeric + column name hints (amount, price, cost, revenue) |
| `percentage` | numeric | `0.85` or `85.0` | Numeric in 0–1 or 0–100 + column name hints |
| `rating` | numeric | `4` | Integer 0–10 + column name hints (rating, score, stars) |
| `json` | format | `{"key": "value"}` | JSON/JSONB db type or parseable JSON strings |
| `html` | format | `<div>content</div>` | HTML tag patterns + column name hints |
| `markdown` | format | `## Header` | Markdown syntax patterns + column name hints |
| `hex_color` | format | `#FF5733` | Hex color regex + column name hints |
| `slug` | format | `my-blog-post` | Lowercase alphanumeric + hyphens |
| `boolean_int` | boolean | `0` or `1` | Integer with only values 0 and 1, ≤2 distinct |
| `yes_no` | boolean | `yes`, `no`, `true`, `false` | String matching yes/no variants |
| `country` | geo | `US`, `United States`, `GBR` | ISO 3166 codes + full names + column name hints |
| `region` | geo | `CA`, `California`, `Ontario` | US state codes/names + column name hints (state, province, region) |
| `city` | geo | `San Francisco` | Column name matches city + moderate cardinality |
| `postal_code` | geo | `94105`, `94105-1234` | 5 or 9 digit patterns + column name hints |
| `timezone` | geo | `America/New_York`, `UTC` | IANA timezone patterns + column name hints |
| `currency_code` | financial | `USD`, `EUR`, `GBP` | ISO 4217 currency codes + column name hints |
| `language` | format | `en`, `fr`, `es`, `en-US` | ISO 639 language codes + column name hints |
| `ip_address` | network | `192.168.1.1`, `::1` | IPv4/IPv6 regex + column name hints |

---

## Classification Axes

Each axis is **mutually exclusive** — every column gets exactly one value per axis.
These are the most important fields for deciding what to do with a column.

### `role` — What do you do with this column?

This is the primary classification. Use this to decide how a column participates
in a chart, query, or analysis.

| Value | What it means | Chart behavior |
|-------|--------------|----------------|
| `measure` | A number you aggregate (SUM, AVG, COUNT) | Y-axis, cell value, size encoding |
| `dimension` | A category you group by or filter on | X-axis labels, color, legend, filter |
| `time` | A date or timestamp | X-axis for time series, date range filters |
| `identifier` | A join key (ID, UUID, FK) — not for analysis | Skip in charts. Use for joins only. |
| `text` | Long-form content (descriptions, notes) | Show in detail views, not on charts |
| `unknown` | Couldn't classify | Needs manual inspection |

**Precedence:** identifier > time > text > measure > dimension > unknown.
A column named `created_at` with a TIMESTAMP type is `time`, not `dimension`,
even though it could technically be grouped by.

### `distribution` — What does the data look like?

Describes the shape of distinct values relative to row count.

| Value | What it means | Typical columns |
|-------|--------------|-----------------|
| `unique` | Nearly every value is distinct (>99% unique) | IDs, emails, UUIDs |
| `continuous` | Spread across a numeric range | Revenue, temperature, scores |
| `categorical` | Finite set of repeating values (<5% unique or ≤50 distinct) | Country, status, department |
| `boolean` | Exactly 2 distinct values | is_active, has_subscription |
| `constant` | Exactly 1 distinct value | Probably a deprecated or default column |
| `empty` | No data (0 distinct or >99.9% null) | Unused column |

`categorical` is ratio-based: a `country` column with 40 distinct values in a 100K-row
table is categorical because 40/100000 = 0.04% unique. This avoids brittle absolute
thresholds.

### `completeness` — How much data is present?

| Value | Null % range | What it means |
|-------|-------------|---------------|
| `complete` | 0% | No nulls at all |
| `dense` | 0–10% | Nearly complete |
| `partial` | 10–70% | Mixed |
| `sparse` | 70–99.9% | Mostly null |
| `empty` | ≥99.9% | Effectively all null |

### `key_role` — Is this a key column?

| Value | What it means |
|-------|--------------|
| `primary_key` | 100% unique and name matches `id` or `*_id` pattern |
| `foreign_key` | Name ends with `_id` but not fully unique — references another table |
| `none` | No detected key relationship |

---

## Boolean Flags

Every column has every flag. Always `true` or `false`, never missing.
For non-applicable types the value is `false` (e.g. `is_non_negative` is `false` on
a VARCHAR — not "null" or absent). This keeps the schema fixed for warehouse tables
and avoids three-valued logic.

Flags use `is_` prefix for column properties or `has_` prefix for data properties.

### Value Shape

| Flag | When true |
|------|-----------|
| `is_non_negative` | Numeric column where min >= 0. For "strictly positive" (no zeros, safe for log scale), check `min_value > 0` directly. |
| `is_normalized` | Numeric values fall in the 0–1 range |
| `is_zero_inflated` | 30–90% of values are zero |

### Distribution Shape

| Flag | When true |
|------|-----------|
| `has_outliers` | Statistical outliers detected (IQR or stddev heuristic) |
| `is_skewed` | Mean and median diverge significantly — asymmetric distribution |

### Temporal / Incremental

| Flag | When true |
|------|-----------|
| `is_incremental` | Values only increase over time. Never goes backward. This is the key signal for incremental charts (cumulative sums, waterfall) and incremental query strategies. Applies to timestamps (`created_at`), auto-increment IDs, running totals. |
| `is_sequential` | Integer values where each = previous + 1. Strictly sequential, no gaps. A subset of incremental. |

### Text

| Flag | When true |
|------|-----------|
| `is_fixed_length` | All string values have the same length (codes, hashes) |
| `is_free_text` | Average string length > 100 characters (descriptions, notes) |

### Semantic

| Flag | When true |
|------|-----------|
| `is_ordinal` | Values have a natural sort order (low/medium/high, S/M/L/XL) |
| `is_currency` | Semantic type is `currency_amount` — format with $ and commas |
| `is_geo` | Geographic data — map eligible (lat, lon, country_code, etc.) |
| `is_pii` | Personally identifiable information (email, phone, SSN) |

---

## Statistics Fields

Raw profiling numbers. These are always present but may be null when not
applicable (e.g. `mean_value` is null for string columns).

| Field | Type | Description |
|-------|------|-------------|
| `null_percentage` | float | Percentage of null values (0.0–100.0) |
| `distinct_count` | integer | Number of distinct non-null values |
| `uniqueness_ratio` | float | distinct_count / non_null_count (0.0–1.0) |
| `min_value` | string or null | Minimum value, serialized as string for JSON compatibility |
| `max_value` | string or null | Maximum value, serialized as string |
| `mean_value` | float or null | Arithmetic mean (numeric columns only) |
| `median_value` | float or null | Median (numeric columns, dialect-dependent) |
| `stddev_value` | float or null | Standard deviation (numeric columns, not SQLite) |
| `min_length` | integer or null | Shortest string length (string columns only) |
| `max_length` | integer or null | Longest string length (string columns only) |
| `avg_length` | float or null | Average string length (string columns only) |
| `top_values` | list of {value, frequency} | Up to 10 most common values. Only collected for eligible columns (low-cardinality string types). |
| `enum_values` | list of strings or null | All distinct values if the column is detected as categorical with ≤20 distinct values. Sorted alphabetically. Empty / null unless `deep_profile` or `collect_enum_values` is enabled. |

---

## Quick Reference: Reading a Column for Chart Decisions

```
role        → WHERE does this go?     measure=Y-axis, dimension=X-axis/color, time=X-axis
distribution → WHAT does it look like? categorical=bar, continuous=histogram, boolean=toggle
completeness → CAN I trust it?         sparse=warn user, empty=skip entirely
key_role    → IS this a join key?      primary_key/foreign_key=skip in charts

is_incremental → Safe for cumulative/waterfall charts?
is_currency    → Format as $?
is_geo         → Show on a map?
is_ordinal     → Sort axis by natural order instead of alphabetical?
is_pii         → Mask or warn before displaying?
```

### Common Column Patterns

| Column | role | distribution | Key flags | Meaning |
|--------|------|-------------|-----------|---------|
| `id` | identifier | unique | `key_role=primary_key` | Skip in charts, use for joins |
| `user_id` | identifier | categorical | `key_role=foreign_key` | Groupable FK — depends on context |
| `created_at` | time | unique | `is_incremental=true` | Time series X-axis, incremental-safe |
| `status` | dimension | categorical | — | Group by, color encode, filter |
| `country` | dimension | categorical | `is_geo=true` | Group by or show on map |
| `revenue` | measure | continuous | `is_currency=true`, `has_outliers=true` | SUM/AVG, format as $, watch outliers |
| `quantity` | measure | continuous | `is_non_negative=true` | SUM/AVG, always ≥ 0 |
| `is_active` | dimension | boolean | — | Filter toggle, binary split |
| `rating` | dimension | categorical | `is_ordinal=true` | Bar chart, sort 1→5 not alphabetically |
| `notes` | text | unique | `is_free_text=true` | Detail view only, not on charts |
| `email` | identifier | unique | `is_pii=true` | Don't display in dashboards |
| `price_tier` | dimension | categorical | `is_ordinal=true` | Low/Medium/High, sort naturally |
