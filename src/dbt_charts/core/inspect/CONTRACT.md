# Profiler Response Contract

**Contract version**: `1.2` (see `PROFILER_CONTRACT_VERSION` in `inspector.py`)

This document defines the stable JSON shapes emitted by `TableInspection.to_dict()` (snake_case, file/CLI) and `TableInspection.to_json_dict()` (camelCase, JSON API / extension panels). Extensions MUST check `contract_version` / `contractVersion` and handle unknown versions gracefully.

## Table-level keys

### `to_dict()` (snake_case)

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `contract_version` | `str` | yes | Semver-style version of this contract |
| `table_name` | `str` | yes | Inspected table name |
| `schema_name` | `str \| null` | yes | Schema (may be null for DuckDB) |
| `database_name` | `str \| null` | yes | Database name |
| `profiled_at` | `str` (ISO 8601) | yes | UTC timestamp of profiling run |
| `inspector_version` | `str` | yes | Inspector code version |
| `row_count` | `int` | yes | Total row count |
| `column_count` | `int` | yes | Number of columns profiled |
| `primary_date_column` | `str \| null` | yes | Auto-detected primary date column |
| `empty_columns` | `list[str]` | yes | Columns with 100% nulls |
| `high_null_columns` | `list[str]` | yes | Columns with >50% nulls |
| `stats` | `object` | yes | Profiling run metadata (see below) |
| `stats_approximate` | `bool` | yes | True when stats came from TABLESAMPLE + APPROX_* functions |
| `sample_percent` | `int \| null` | yes | TABLESAMPLE percentage used; null for full-table scans |
| `columns` | `list[object]` | yes | Per-column profiles (see below) |
| `table_description` | `str` | no | Only present if enrichment provided it |
| `size_bytes` | `int` | no | Only present if enrichment provided it |
| `partition_info` | `object` | no | Only present for partitioned tables |
| `clustering_fields` | `list[str]` | no | Only present for clustered tables |
| `declared_foreign_keys` | `list[object]` | no | Declared FKs captured at profiling time, one entry per constraint (composite FKs stay grouped, not decomposed): `{columns: list[str], references_table, references_columns: list[str \| null]}`. Primary input to relationship detection. File-cache only — absent from `to_json_dict()`. |

### `to_json_dict()` (camelCase)

| Key | Type | Required |
|-----|------|----------|
| `contractVersion` | `str` | yes |
| `tableName` | `str` | yes |
| `rowCount` | `int` | yes |
| `profiledAt` | `str` | yes |
| `primaryDateColumn` | `str \| null` | yes |
| `stats` | `object` | yes |
| `statsApproximate` | `bool` | yes |
| `samplePercent` | `int \| null` | yes |
| `columns` | `list[object]` | yes |
| `tableDescription` | `str` | no |
| `sizeBytes` | `int` | no |
| `partitionInfo` | `object` | no |
| `clusteringFields` | `list[str]` | no |

## Stats object

| snake_case | camelCase | Type |
|------------|-----------|------|
| `query_count` | `queryCount` | `int` |

## Column-level keys (`to_dict()`)

| Key | Type | Description |
|-----|------|-------------|
| `order` | `int` | 1-indexed position |
| `name` | `str` | Column name |
| `database_type` | `str` | Raw database type (e.g., `VARCHAR`, `DECIMAL`) |
| `semantic_type` | `str \| null` | Detected semantic type (e.g., `email`, `currency_amount`, `category`) |
| `semantic_type_confidence` | `float` | 0.0 to 1.0 confidence score |
| `role` | `str` | One of: `measure`, `dimension`, `identifier`, `unknown` |
| `distribution` | `str` | One of: `continuous`, `categorical`, `boolean`, `constant`, `unique`, `sparse`, `empty` |
| `completeness` | `str` | One of: `complete`, `mostly_complete`, `sparse`, `empty` |
| `key_role` | `str` | One of: `primary_key`, `foreign_key`, `none` |
| `null_percentage` | `float` | 0.0 to 100.0 |
| `distinct_count` | `int` | Number of unique non-null values |
| `uniqueness_ratio` | `float` | 0.0 to 1.0 (empirical, profiled from a sample) |
| `declared_unique` | `bool` | True if a declared single-column `UNIQUE` constraint proves uniqueness (proof of intent, distinct from the profiled `uniqueness_ratio`) |
| `min_value` | `str \| null` | Stringified min (null if all-null) |
| `max_value` | `str \| null` | Stringified max |
| `mean_value` | `float \| null` | Numeric columns only |
| `median_value` | `float \| null` | Numeric columns only |
| `stddev_value` | `float \| null` | Numeric columns only |
| `min_length` | `int \| null` | String columns only |
| `max_length` | `int \| null` | String columns only |
| `avg_length` | `float \| null` | String columns only |
| `top_values` | `list[{value, frequency}]` | Up to 10 most frequent values |
| `enum_values` | `list[str] \| null` | Low-cardinality categorical values; `null` unless `deep_profile` or `collect_enum_values` is enabled |
| `histogram_bins` | `list[{bin_start, bin_end, count}]` | Numeric distribution bins; empty list unless `deep_profile` or `collect_histogram_bins` is enabled |
| `date_distribution` | `list[{bucket, count}]` | Temporal distribution buckets; empty list unless `deep_profile` or `collect_date_distribution` is enabled |
| `approximate` | `bool` | True when column stats were computed from a sample |

### Boolean flags (13 total)

All are `bool`. Present on every column in `to_dict()`:

| Field | Label | Description |
|-------|-------|-------------|
| `is_non_negative` | non-neg | All values >= 0 |
| `is_normalized` | normalized | Values in [0, 1] range |
| `is_zero_inflated` | zero-inflated | Disproportionate zero count |
| `has_outliers` | outliers | Statistical outliers detected |
| `is_skewed` | skew | Distribution is skewed |
| `is_incremental` | incremental | Values increase monotonically |
| `is_sequential` | sequential | Values form a gap-free sequence |
| `is_fixed_length` | fixed-len | All string values same length |
| `is_free_text` | free-text | Long-form text content |
| `is_ordinal` | ordinal | Values form an ordered set |
| `is_currency` | currency | Monetary values detected |
| `is_geo` | geo | Geographic data detected |
| `is_pii` | pii | Personally identifiable information |

## Column-level keys (`to_json_dict()`)

Subset of `to_dict()` in camelCase:

| Key | Type |
|-----|------|
| `order` | `int` |
| `name` | `str` |
| `type` | `str` (maps to `database_type`) |
| `role` | `str` |
| `distribution` | `str` |
| `semanticType` | `str \| null` |
| `nullPercentage` | `float` |
| `distinctCount` | `int` |
| `minValue` | `str \| null` |
| `maxValue` | `str \| null` |
| `topValues` | `list[{value, frequency}]` |
| `histogramBins` | `list[{bin_start, bin_end, count}]` |
| `dateDistribution` | `list[{bucket, count}]` |
| `approximate` | `bool` |

## Deep profile enrichment

`histogram_bins`, `date_distribution`, and `enum_values` are populated only when deep profile is enabled. With the default config (all off), these fields are empty lists or `null`. Extensions must treat empty lists as "data not collected" — not as "column has no distribution".

Enable enrichment via config:
```yaml
inspector:
  deep_profile: true            # all three collectors
  collect_histogram_bins: true  # numeric columns only
  collect_date_distribution: true  # temporal columns only
  collect_enum_values: true     # categorical columns only
```

## Chart hints for extensions

Extensions should use these rules when choosing visualization:

| Condition | Chart type |
|-----------|-----------|
| `histogram_bins` non-empty | Histogram bar chart |
| `date_distribution` non-empty | Time series line/bar chart |
| `distribution == "categorical"` and `top_values` non-empty | Horizontal bar chart |
| `distribution == "boolean"` | Pie chart |
| `role == "measure"` and numeric stats present | Summary card with sparkline |

## Renderer distribution files

The renderer writes sidecar JSON files for dashboard templates:

| File pattern | Shape | Used by |
|--------------|-------|---------|
| `.{model}_distributions.json` | `[{column, type, bin_start?, bin_end?, count, bucket?}]` | Histogram and date charts |
| `.{model}_pivoted.json` | `[{Stat, col1, col2, ...}]` | Stats table |
| `.{model}_completeness.json` | `[{Stat, col1, col2, ...}]` | Completeness bars |
| `.{model}_classification.json` | `[{Stat, col1, col2, ...}]` | Classification table |
| `.{model}_overview.json` | `[{column, type, role, semantic, null_pct, distinct_pct}]` | Overview table |

## Versioning policy

- Additive changes (new optional keys): no version bump needed.
- Removing or renaming required keys: bump `PROFILER_CONTRACT_VERSION` major.
- Changing value types of existing keys: bump `PROFILER_CONTRACT_VERSION` major.
- Adding new required keys: bump `PROFILER_CONTRACT_VERSION` minor.
