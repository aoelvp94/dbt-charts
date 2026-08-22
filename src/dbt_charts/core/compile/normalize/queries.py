"""Query normalization and external query resolution."""

from __future__ import annotations

import json
import logging
import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import sqlglot
from pydantic import ValidationError as PydanticValidationError
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect as SqlglotDialect
from sqlglot.errors import ParseError as SqlglotParseError

if TYPE_CHECKING:
    from dbt_charts.core.project import ProjectDirectory

from dbt_charts.cli.filesystem_project import (
    FilesystemProject,  # tach-ignore(core->cli: host-type guard; needs a non-cli signal on Project — deferred)
)
from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.cache import (
    INHERIT_CACHE,
    CachePatch,
    resolve_cache_policy,
    validate_cache_layer,
)
from dbt_charts.core.compile.models.query.authored import _BaseQueryFields
from dbt_charts.core.compile.models.query.normalized import (
    AnyQuery,
    HttpQuery,
    SchemaQuery,
    SqlParseError,
    SqlQuery,
    ValuesQuery,
    is_schema_query,
    is_sql_query,
)
from dbt_charts.core.compile.models.refs import infer_query_type_from_keys
from dbt_charts.core.compile.models.source import (
    CsvSourceConfig,
    DbtProfileSourceConfig,
    JsonSourceConfig,
    ParquetSourceConfig,
    SourceConfig,
    parse_source_config,
    source_cache_layer,
)
from dbt_charts.core.compile.normalize.sql_authoring_lint import (
    has_literal_escaped_newlines,
)
from dbt_charts.core.compile.sql_guard import (
    sqlglot_dialect,
    validate_select_only,
    validate_setup_sql,
)
from dbt_charts.core.compile.template.jinja import extract_variable_dependencies
from dbt_charts.core.diagnostics.ansi import strip_ansi
from dbt_charts.core.diagnostics.codes_compile import (
    ERR_SOURCE_INLINE_FORBIDDEN,
    ERR_SOURCE_NOT_FOUND,
    ERR_SOURCE_REQUIRED,
    ERR_SQL_LITERAL_NEWLINES,
)
from dbt_charts.core.diagnostics.execution import MutatingSqlError, UnparseableSqlError

logger = logging.getLogger(__name__)

# dbt adapter `type` -> MetricFlow (SqlEngine, sql_plan_renderer import path). Only the
# renderer class name is needed at import time (lazy, since metricflow is optional).
_METRICFLOW_DIALECTS: dict[str, tuple[str, str, str]] = {
    "duckdb": (
        "DUCKDB",
        "metricflow.sql.render.duckdb_renderer",
        "DuckDbSqlPlanRenderer",
    ),
    "postgres": (
        "POSTGRES",
        "metricflow.sql.render.postgres",
        "PostgresSQLSqlPlanRenderer",
    ),
    "snowflake": (
        "SNOWFLAKE",
        "metricflow.sql.render.snowflake",
        "SnowflakeSqlPlanRenderer",
    ),
    "bigquery": (
        "BIGQUERY",
        "metricflow.sql.render.big_query",
        "BigQuerySqlPlanRenderer",
    ),
    "redshift": (
        "REDSHIFT",
        "metricflow.sql.render.redshift",
        "RedshiftSqlPlanRenderer",
    ),
    "databricks": (
        "DATABRICKS",
        "metricflow.sql.render.databricks",
        "DatabricksSqlPlanRenderer",
    ),
    "trino": ("TRINO", "metricflow.sql.render.trino", "TrinoSqlPlanRenderer"),
}


# Jinja regions inside a metricflow where predicate ({{ ... }} / {% ... %}).
_JINJA_REGION_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)


def _predicate_columns(name: str, predicate: str) -> set[str]:
    """Columns a where predicate references, resolved statically.

    Two sources: first arguments of filter()/filter_date_range() calls inside
    Jinja regions (must be string literals — a variable column name cannot be
    classified at compile time), and plain column refs in the SQL once Jinja
    regions are masked out.
    """
    columns: set[str] = set()
    for region in _JINJA_REGION_RE.findall(predicate):
        for call in re.finditer(
            r"\b(filter|filter_date_range)\s*\(\s*([^,)]+)", region
        ):
            arg = call.group(2).strip()
            if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "'\"":
                columns.add(arg[1:-1])
            else:
                raise CompilationError(
                    f"metricflow query '{name}': cannot statically determine the "
                    f"column of {call.group(1)}() in where predicate {predicate!r}. "
                    "Pass the column as a string literal."
                )
    masked = _JINJA_REGION_RE.sub("NULL", predicate)
    try:
        tree = sqlglot.parse_one(f"SELECT 1 WHERE {masked}")
    except SqlglotParseError as e:
        raise CompilationError(
            f"metricflow query '{name}': unparseable where predicate {predicate!r}: {e}"
        ) from e
    columns |= {col.name for col in tree.find_all(exp.Column)}
    return columns


def _to_metricflow_constraint(name: str, predicate: str) -> str:
    """Rewrite a literal predicate's column refs into MetricFlow's where-filter
    templating ({{ Dimension('order_id__region') }}, {{ TimeDimension(...) }}).

    Only the column names are rewritten — operators and values pass through;
    MetricFlow validates the result against the semantic graph. A grain-less
    ``metric_time`` maps to ``Dimension('metric_time')`` (not TimeDimension);
    MetricFlow rejects that loudly, which is the intended behavior — a bare
    ``metric_time`` predicate is not a valid group-by-column filter here.
    """
    try:
        tree = sqlglot.parse_one(f"SELECT 1 WHERE {predicate}")
    except SqlglotParseError as e:
        raise CompilationError(
            f"metricflow query '{name}': unparseable where predicate {predicate!r}: {e}"
        ) from e

    def _template(node: exp.Expression) -> exp.Expression:
        # Rewrite only Column nodes — string literals and quoted identifiers
        # that happen to share a column's text are left untouched by construction.
        if not isinstance(node, exp.Column):
            return node
        grain = re.fullmatch(r"metric_time__(\w+)", node.name)
        target = (
            f"{{{{ TimeDimension('metric_time', '{grain.group(1)}') }}}}"
            if grain
            else f"{{{{ Dimension('{node.name}') }}}}"
        )
        return exp.Var(this=target)

    where = tree.transform(_template).find(exp.Where)
    if where is None:
        raise CompilationError(
            f"metricflow query '{name}': where predicate {predicate!r} has no condition"
        )
    return where.this.sql()


def _reject_non_commuting_metrics(
    name: str, metrics: list[str], manifest_json: str
) -> None:
    """where: is only exact when each group's value depends solely on that
    group's rows. Cumulative, conversion, and offset-window metrics read rows
    outside the group; a derived metric inherits that property transitively from
    any such input. Baking a predicate pre-aggregation and wrapping it
    post-aggregation would then give different results — refuse all of them. A
    metric whose type we can't prove commutes is refused too (validate-and-error
    §4: no silent best-effort).
    """
    entries = {m.get("name"): m for m in json.loads(manifest_json).get("metrics", [])}
    for metric_name in metrics:
        reason = _non_commuting_reason(metric_name, entries, set())
        if reason:
            raise CompilationError(
                f"metricflow query '{name}': metric '{metric_name}' is {reason}, "
                "so where: filters cannot be applied exactly. Use a sql: query."
            )


# MetricFlow metric types whose per-group value is a pure aggregation of that
# group's own rows — safe to post-filter on a selected group-by dimension.
_COMMUTING_METRIC_TYPES = frozenset({"simple", "ratio"})

# The two period-shift fields on a derived-metric input (dbt-semantic-interfaces
# MetricInput): a non-null value on either means the input reads rows from a
# different period, so the derived metric no longer commutes. Keyed off the
# *value* — a real dbt manifest always serializes both keys, as null when unset.
_DERIVED_INPUT_SHIFT_FIELDS = ("offset_window", "offset_to_grain")


def _non_commuting_reason(
    metric_name: str, entries: dict[str, Any], seen: set[str]
) -> str | None:
    """Why ``metric_name`` can't be exactly filtered, or None if it commutes.

    Recurses through derived-metric inputs; ``seen`` guards against reference
    cycles in a malformed manifest.
    """
    if metric_name in seen:
        return None
    seen.add(metric_name)
    entry = entries.get(metric_name)
    if entry is None:
        return None  # unknown metric — MetricFlow raises its own error downstream
    mtype = entry.get("type")
    if mtype in ("cumulative", "conversion"):
        return mtype
    if mtype == "derived":
        params = entry.get("type_params") or {}
        for input_metric in params.get("metrics") or []:
            if not isinstance(input_metric, dict):
                continue
            if any(input_metric.get(f) for f in _DERIVED_INPUT_SHIFT_FIELDS):
                return "derived with a period offset"
            inner = _non_commuting_reason(input_metric.get("name", ""), entries, seen)
            if inner:
                return f"derived from a {inner} metric"
        return None
    if mtype in _COMMUTING_METRIC_TYPES:
        return None
    return f"of an unsupported metric type ({mtype!r}) that cannot be proven to commute"


def _lower_metricflow_query(
    name: str,
    query_dict: dict[str, Any],
    sources: dict[str, Any],
    base_dir: ProjectDirectory | None = None,
) -> SqlQuery:
    """Lower a metricflow query dict to a SqlQuery at compile time (no MetricFlowAdapter).

    Reuses MetricFlow's own compiler (MetricFlowEngine.explain) against the dbt
    semantic manifest (target/semantic_manifest.json, from `dbt parse`) rather than
    reimplementing MetricFlow's SQL generation. The query's `source` must be a
    `dbt_profile` source (no separate `type: metricflow` source) — the dbt project
    is detected via `base_dir.project.exists("dbt_project.yml")` (the sibling-of-
    dbt_charts.yml convention DbtAdapter uses at execute time), a host-agnostic
    seam call rather than a raw filesystem walk. MetricFlow-over-dbt still needs a
    real filesystem path downstream (dbt adapter / profiles.yml resolution), so a
    non-filesystem host (e.g. Cloud's git-blob project) is refused with a clear
    CompilationError rather than silently reading the wrong directory. Raises
    CompilationError if `base_dir` is None.

    Dimension naming follows MetricFlow's own group-by naming scheme directly
    (e.g. `customer__region`, `metric_time`) — `dimensions:` is passed through
    verbatim; `time_grain:` appends `metric_time__<grain>` to the group-by list.
    MetricFlow bakes filter literals into SQL at compile time (no variable
    placeholder pass-through — compile-time lowering means recompile-per-change).
    """
    source_name = query_dict.get("source")
    if not isinstance(source_name, str):
        raise CompilationError(
            f"metricflow query '{name}': 'source' must be a string naming a dbt_profile source"
        )
    if source_name not in sources:
        raise CompilationError.from_code(
            ERR_SOURCE_NOT_FOUND,
            query_name=name,
            source=source_name,
            available=sorted(sources),
        )
    source_cfg = parse_source_config(sources[source_name])
    if not isinstance(source_cfg, DbtProfileSourceConfig):
        raise CompilationError(
            f"metricflow query '{name}': source '{source_name}' is not a dbt_profile source"
        )
    metrics = query_dict.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise CompilationError(
            f"metricflow query '{name}': metrics must be a non-empty list, "
            f"got {type(metrics).__name__}"
        )
    raw_dims = query_dict.get("dimensions")
    if raw_dims is not None and not isinstance(raw_dims, list):
        raise CompilationError(
            f"metricflow query '{name}': dimensions must be a list, "
            f"got {type(raw_dims).__name__}"
        )
    dimensions = list(raw_dims) if isinstance(raw_dims, list) else []
    time_grain = query_dict.get("time_grain")
    group_by_names = (
        [*dimensions, f"metric_time__{time_grain}"] if time_grain else dimensions
    )

    raw_where = query_dict.get("where")
    if raw_where is not None and (
        not isinstance(raw_where, list)
        or not all(isinstance(p, str) for p in raw_where)
    ):
        raise CompilationError(
            f"metricflow query '{name}': where must be a list of SQL predicate "
            f"strings, got {type(raw_where).__name__}"
        )
    where_predicates = list(raw_where) if raw_where else []
    literal_predicates = [p for p in where_predicates if "{{" not in p]
    variable_predicates = [p for p in where_predicates if "{{" in p]
    for predicate in variable_predicates:
        for column in _predicate_columns(name, predicate):
            if column not in group_by_names:
                raise CompilationError(
                    f"metricflow query '{name}': variable predicate on "
                    f"'{column}', which is not a selected dimension. Add "
                    f"'{column}' to dimensions: (the filter becomes exact), "
                    "or use a sql: query."
                )

    # Locate the dbt project via the compile-time base_dir (the board file's
    # project root), not CWD — this makes MetricFlow lowering host-agnostic
    # (Cloud, programmatic compile, and CLI all work the same).
    if base_dir is None:
        raise CompilationError(
            f"metricflow query '{name}': no project directory context. "
            "MetricFlow queries must be compiled with a base_dir (project root)."
        )
    # Sibling rule: dbt_project.yml is only valid when it sits next to
    # dbt_charts.yml, i.e. at the project root — same rule as
    # adapter_registry.build_adapter_registry. Detection goes through the
    # Project seam (host-agnostic), never a raw Path built off base_dir.
    if not base_dir.project.exists("dbt_project.yml"):
        raise CompilationError(
            f"metricflow query '{name}': no dbt project found. A metricflow query's "
            "dbt_profile source requires dbt_project.yml as a sibling of dbt_charts.yml."
        )
    # Anchored at the project root via base_dir.project (not base_dir itself —
    # base_dir may be a nested board directory, but target/ always sits at the
    # project root alongside dbt_project.yml).
    semantic_manifest_relpath = "target/semantic_manifest.json"
    semantic_manifest = base_dir.project.path(semantic_manifest_relpath)
    if not semantic_manifest.exists():
        raise CompilationError(
            f"metricflow query '{name}': no semantic manifest found at "
            f"{semantic_manifest_relpath}. Run `dbt parse` in the dbt project to "
            "generate it."
        )
    # A real dbt project was detected, but the dbt adapter and profiles.yml
    # resolution below still need a real filesystem directory — MetricFlow-
    # over-dbt is filesystem-only today. Refuse a non-filesystem host (e.g.
    # Cloud's git-blob-store project) rather than reading its base-class
    # `.root` (the worker CWD, not a real dbt project directory).
    if not isinstance(base_dir.project, FilesystemProject):
        raise CompilationError(
            f"metricflow query '{name}': dbt-project MetricFlow queries require a "
            f"local filesystem project; got {type(base_dir.project).__name__}."
        )
    dbt_project_path = base_dir.project.root

    # tach-ignore(pre-existing compile->execute coupling — accepted debt)
    from dbt_charts.core.execute.adapters.dbt_adapter import (
        _read_target_dict,
    )  # noqa: PLC0415

    profiles_dir = (
        (dbt_project_path / source_cfg.profiles_dir).resolve()
        if source_cfg.profiles_dir is not None
        else None
    )
    try:
        target_dict = _read_target_dict(
            dbt_project_path,
            source_cfg.profile,
            source_cfg.target,
            profiles_dir=profiles_dir,
        )
    except (FileNotFoundError, ValueError) as e:
        raise CompilationError(f"metricflow query '{name}': {e}") from e

    dialect = target_dict.get("type")
    if dialect not in _METRICFLOW_DIALECTS:
        raise CompilationError(
            f"metricflow query '{name}': unsupported dialect '{dialect}' for MetricFlow. "
            f"Supported: {sorted(_METRICFLOW_DIALECTS)}"
        )
    engine_name, renderer_module, renderer_class = _METRICFLOW_DIALECTS[dialect]

    try:
        # Lazy import: metricflow is optional (pip install dbt-charts[metricflow]).
        from metricflow.data_table.mf_table import MetricFlowDataTable  # noqa: PLC0415
        from metricflow.engine.metricflow_engine import (  # noqa: PLC0415
            MetricFlowEngine,
            MetricFlowQueryRequest,
        )
        from metricflow.protocols.sql_client import SqlEngine  # noqa: PLC0415
        from metricflow.sql.render.sql_plan_renderer import (  # noqa: PLC0415
            SqlPlanRenderer,
        )
        from metricflow_semantics.errors.error_classes import (  # noqa: PLC0415
            MetricFlowException,
        )
        from metricflow_semantics.model.dbt_manifest_parser import (  # noqa: PLC0415
            parse_manifest_from_dbt_generated_manifest,
        )
        from metricflow_semantics.model.semantic_manifest_lookup import (  # noqa: PLC0415
            SemanticManifestLookup,
        )
        from metricflow_semantics.sql.sql_bind_parameters import (  # noqa: PLC0415
            SqlBindParameterSet,
        )
    except ImportError as e:
        raise CompilationError(
            f"metricflow query '{name}': metricflow is not installed. "
            "Install with: pip install dbt-charts[metricflow]"
        ) from e

    # MetricFlow logs query-parsing/dataflow-planning steps at INFO, which floods
    # `dct compile`/`dct describe` output. Compile-time lowering never needs it.
    logging.getLogger("metricflow").setLevel(logging.WARNING)
    logging.getLogger("metricflow_semantics").setLevel(logging.WARNING)

    import importlib  # noqa: PLC0415

    renderer = getattr(importlib.import_module(renderer_module), renderer_class)()
    sql_engine = getattr(SqlEngine, engine_name)

    class _CompileTimeSqlClient:
        """Satisfies MetricFlow's SqlClient Protocol for compile-time-only use.

        MetricFlowEngine.explain() never issues a query — it only reads
        sql_engine_type (dialect) and sql_plan_renderer (pure Python) off the
        client to render SQL text. The query/execute/dry_run/close/
        render_bind_parameter_key methods below exist only to satisfy the
        Protocol's structural type; explain() never calls them, so each
        raises unconditionally.
        """

        @property
        def sql_engine_type(self) -> SqlEngine:
            return sql_engine

        @property
        def sql_plan_renderer(self) -> SqlPlanRenderer:
            return renderer

        def query(
            self,
            stmt: str,
            sql_bind_parameter_set: SqlBindParameterSet = SqlBindParameterSet(),
        ) -> MetricFlowDataTable:
            raise NotImplementedError(
                "compile-time-only SqlClient stub does not execute queries"
            )

        def execute(
            self,
            stmt: str,
            sql_bind_parameter_set: SqlBindParameterSet = SqlBindParameterSet(),
        ) -> None:
            raise NotImplementedError(
                "compile-time-only SqlClient stub does not execute queries"
            )

        def dry_run(
            self,
            stmt: str,
            sql_bind_parameter_set: SqlBindParameterSet = SqlBindParameterSet(),
        ) -> None:
            raise NotImplementedError(
                "compile-time-only SqlClient stub does not execute queries"
            )

        def close(self) -> None:
            raise NotImplementedError(
                "compile-time-only SqlClient stub has no connection to close"
            )

        def render_bind_parameter_key(self, bind_parameter_key: str) -> str:
            raise NotImplementedError(
                "compile-time-only SqlClient stub does not bind parameters"
            )

    try:
        manifest_json = semantic_manifest.read_text()
        lookup = SemanticManifestLookup(
            parse_manifest_from_dbt_generated_manifest(manifest_json)
        )
    except Exception as e:  # noqa: BLE001 — filesystem boundary; pydantic/JSON decode errors have no shared base
        raise CompilationError(
            f"metricflow query '{name}': invalid semantic manifest at "
            f"{semantic_manifest_relpath}: {e}"
        ) from e
    if where_predicates:
        _reject_non_commuting_metrics(name, metrics, manifest_json)

    try:
        engine = MetricFlowEngine(
            semantic_manifest_lookup=lookup, sql_client=_CompileTimeSqlClient()
        )
        result = engine.explain(
            MetricFlowQueryRequest.create(
                metric_names=metrics,
                group_by_names=group_by_names or None,
                where_constraints=[
                    _to_metricflow_constraint(name, p) for p in literal_predicates
                ]
                or None,
            )
        )
    except MetricFlowException as e:
        raise CompilationError(f"metricflow query '{name}': {e}") from e

    sql = result.sql_statement.sql
    if variable_predicates:
        # Compose around the baked SQL, never inside it. Filtering on a selected
        # group-by dimension commutes with aggregation, so the post-filter is
        # exact; the predicates' {{ }} resolve through render_parameterized at
        # execute (values bound as parameters, filter()/filter_date_range()
        # helpers available).
        conditions = " AND ".join(f"({p})" for p in variable_predicates)
        sql = f"SELECT * FROM (\n{sql}\n) mf_query WHERE {conditions}"
    return SqlQuery(
        sql=sql,
        source=source_name,
        limit=query_dict.get("limit"),
        description=query_dict.get("description"),
        ignore=query_dict.get("ignore"),
    )


_QUERY_TYPES_TAKING_CONNECTION_DEFAULT = frozenset({"sql", "metricflow"})

# A `source:` string containing '/' or ending in a data-file extension is
# an inline file reference, not a registry name. Type is inferred from the
# extension.
_FILE_SOURCE_EXTENSIONS: dict[str, str] = {
    ".csv": "csv",
    ".json": "json",
    ".parquet": "parquet",
}


def _is_file_source_ref(source: str) -> bool:
    """True if a `source:` string is an inline file path rather than a registry name.

    Extension matching is case-insensitive to stay consistent with
    ``_resolve_inline_file_source``, which lowercases the suffix — otherwise a
    bare ``SALES.CSV`` would misclassify as a registry name.
    """
    return "/" in source or source.lower().endswith(tuple(_FILE_SOURCE_EXTENSIONS))


def _build_file_source_config(
    file_type: str, stem: str, resolved_path: str
) -> CsvSourceConfig | JsonSourceConfig | ParquetSourceConfig:
    """Construct the typed single-file source config for *file_type*.

    A per-branch dispatch (rather than a class lookup table keyed by
    extension) so each constructor call keeps its own literal `type=` value —
    a lookup-table call site would need a type-ignore to paper over the union.
    """
    if file_type == "csv":
        return CsvSourceConfig(type="csv", files={stem: resolved_path})
    if file_type == "json":
        return JsonSourceConfig(type="json", files={stem: resolved_path})
    return ParquetSourceConfig(type="parquet", files={stem: resolved_path})


def _resolve_inline_file_source(
    name: str, ref: str, base_dir: ProjectDirectory | None
) -> dict[str, Any]:
    """Resolve an inline file-path `source:` ref to a source config dict.

    The table name is the file's stem (`sales.csv` -> table `sales`); an unknown
    extension or a stem that is not a valid SQL identifier is a compile error —
    no silent sanitization. The path is resolved via the board's ProjectDirectory
    (`base_dir`), which already rejects absolute/escaping paths.
    """
    suffix = PurePosixPath(ref).suffix.lower()
    file_type = _FILE_SOURCE_EXTENSIONS.get(suffix)
    if file_type is None:
        raise CompilationError(
            f"Query {name!r}: inline file source {ref!r} has an unrecognized "
            "extension. Supported: .csv, .json, .parquet."
        )
    if base_dir is None:
        raise CompilationError(
            f"Query {name!r}: cannot resolve inline file source {ref!r} — "
            "no base directory context (board was compiled without one)."
        )
    stem = PurePosixPath(ref).stem
    try:
        resolved = (base_dir / ref).relpath
    except ValueError as e:
        raise CompilationError(
            f"Query {name!r}: inline file source {ref!r} is invalid: {e}"
        ) from e
    try:
        config = _build_file_source_config(file_type, stem, resolved)
    except PydanticValidationError as e:
        raise CompilationError(
            f"Query {name!r}: inline file source {ref!r} is invalid: {e}"
        ) from e
    return config.model_dump()


def dialect_for_source(source: str | None, sources: dict[str, Any]) -> str | None:
    """The sqlglot dialect for a query's source, or None when unresolvable.

    A source's `type` is its dialect when the type names one ("duckdb",
    "bigquery", "sqlserver" via the alias table). Plenty don't: `csv` /
    `json` / `parquet` are file sources, and `dbt_profile`'s real dialect
    lives in the profile and isn't knowable until execute. sqlglot's own
    registry is the arbiter — asking it for an unknown name raises rather
    than degrading, and `dialects.get_dialect` can't stand in here because
    it silently answers postgres for anything it doesn't recognise.

    None means "could not establish one", and callers must treat it as "do
    not report parse findings" rather than falling back to the default
    dialect: parsing BigQuery SQL as generic SQL is how a parse warning ends
    up firing on ~40% of real boards.
    """
    if source is None:
        return None
    config = sources.get(source)
    # The registry holds either a raw dict or a validated config, depending on
    # how far normalization has gotten — `source_cache_layer` reads it the same
    # two ways. Handling only the dict would silently stop warning for the
    # other caller rather than fail.
    if isinstance(config, dict):
        source_type = config.get("type")
    elif isinstance(config, SourceConfig):
        source_type = config.type
    else:
        return None
    if not isinstance(source_type, str):
        return None
    if sqlglot_dialect(source_type) not in SqlglotDialect.classes:
        return None
    return source_type


def normalize_query(
    name: str,
    query_def: Any,
    default_source: str | None = None,
    *,
    sources: dict[str, Any],
    base_dir: ProjectDirectory | None = None,
    cache_root: CachePatch | None = None,
    board_cache: CachePatch = INHERIT_CACHE,
) -> AnyQuery:
    """Normalize a query definition to AnyQuery.

    Creates the appropriate query type (SqlQuery, HttpQuery, etc.) based on the
    query definition.

    Args:
        name: Query name
        query_def: AuthoredQuery definition (AuthoredQuery, dict, or bare SQL string shorthand)
        default_source: Default source to apply if query has no explicit source
        sources: Named source config dicts (project + board level), keyed by source
            name. Required, with no default: it carries the source-scope `cache:`
            layer, and the two cross-file import lanes each shipped without it
            once already — an optional registry that quietly resolves to `{}`
            turns "this caller has no source configs" and "this caller forgot to
            pass them" into the same, silent, day-old-data outcome. Also consulted
            by metricflow queries, which lower to SqlQuery at normalize
            time (no adapter; compile-time lowering).
        base_dir: ProjectDirectory anchor (board file's parent). Required for
            metricflow queries (locate dbt_project.yml without CWD).
        cache_root: The project's `cache:` block — the root of the cascade,
            threaded from the compile entry (`Project.cache`) rather than read
            off the process-global config: `load_config` runs only under `dct
            serve`, and installing a project's root globally would leak it
            between the orgs one Cloud worker compiles for. None means no
            project is attached (a board compiled from text), whose documented
            root is the shipped one.
        board_cache: The declaring dashboard's `cache:` layer, folded in between
            the source and the query itself. Empty (the default) authors
            nothing, so the query inherits the source/project layers unchanged.

    Returns:
        Query object (SqlQuery, HttpQuery, etc.)
    """
    # Non-SQL pre-built query types need no guard — return immediately.
    if isinstance(
        query_def,
        (
            HttpQuery,
            ValuesQuery,
            SchemaQuery,
        ),
    ):
        return query_def

    # Pre-built SqlQuery: skip reconstruction but still run guard + dep-extraction
    # below. It is already normalized, so it keeps the cache policy it carries.
    prebuilt = isinstance(query_def, SqlQuery)
    authored_cache: CachePatch | None = None
    if isinstance(query_def, SqlQuery):
        query: AnyQuery = query_def
    else:
        # Convert to dict
        query_dict: dict[
            str, Any
        ]  # WHY: prevents pyright narrowing to dict[str, str] in the bare-SQL {"sql": query_def} branch
        if isinstance(query_def, _BaseQueryFields):
            query_dict = query_def.model_dump(exclude_none=True)
            # The cascade layer is read off the instance and merged below, so
            # drop the dumped copy rather than carrying the same `cache:`
            # through the reconstruction on the other side.
            query_dict.pop("cache", None)
            authored_cache = query_def.cache
        elif isinstance(query_def, dict):
            query_dict = dict(query_def)
            authored_cache = validate_cache_layer(name, query_dict.pop("cache", None))
        elif isinstance(query_def, str):
            query_dict = {"sql": query_def}
        else:
            raise CompilationError(
                f"Query '{name}': Invalid query definition. Expected dict with 'sql' and 'source' fields for SQL queries."
            )

        # Ensure type field
        if "type" not in query_dict:
            query_dict["type"] = infer_query_type_from_keys(query_dict)

        query_type = query_dict.pop("type")

        # Apply default source if query doesn't have one. Only query types that
        # lower to a connection-backed SqlQuery take the inherited default:
        # ValuesQuery is inline data, SchemaQuery's source is a dbt source name
        # (not a connection reference), and HttpQuery uses url — none of those
        # have a connection slot for the default to fill.
        has_source = query_dict.get("source") is not None
        if (
            not has_source
            and default_source
            and query_type in _QUERY_TYPES_TAKING_CONNECTION_DEFAULT
        ):
            query_dict["source"] = default_source

        resolved_sources = sources

        # Reject inline dict sources before type dispatch.
        if isinstance(query_dict.get("source"), dict):
            raise CompilationError.from_code(
                ERR_SOURCE_INLINE_FORBIDDEN,
                query_name=name,
                offending_value=repr(query_dict["source"]),
            )

        # Create the appropriate query type
        if query_type == "sql":
            # Ensure sql is present
            if "sql" not in query_dict:
                raise CompilationError(
                    f"Query '{name}': SQL queries must have 'sql' field"
                )
            raw_source = query_dict.get("source")
            if isinstance(raw_source, str):
                if _is_file_source_ref(raw_source):
                    # Inline file-path source: register it into the sources
                    # registry under the literal authored ref so execute-time
                    # lookup (`board_sources.get(query.source)`) resolves it
                    # unchanged.
                    if raw_source not in resolved_sources:
                        resolved_sources[raw_source] = _resolve_inline_file_source(
                            name, raw_source, base_dir
                        )
                elif sources and raw_source not in sources:
                    # A registry name that isn't in the loaded project registry.
                    # Skipped when no registry was supplied at all (pure
                    # in-memory compile) — there the execute-time resolver
                    # remains the only backstop.
                    raise CompilationError.from_code(
                        ERR_SOURCE_NOT_FOUND,
                        query_name=name,
                        source=raw_source,
                        available=sorted(sources),
                    )
            # SqlQuery.source is required. This pre-check catches both the
            # missing-key case (source absent from query_dict) and the
            # explicit-null case (source=None from YAML null or a programmatic
            # caller), surfacing the friendly ERR-SOURCE-REQUIRED rather
            # than a raw ValidationError. With source guaranteed present and
            # non-null here, SqlQuery construction can no longer fail on a
            # missing source.
            if query_dict.get("source") is None:
                raise CompilationError.from_code(ERR_SOURCE_REQUIRED, query_name=name)
            query = SqlQuery(**query_dict)
        elif query_type == "metricflow":
            query = _lower_metricflow_query(
                name, query_dict, resolved_sources, base_dir
            )
        elif query_type == "http":
            if "url" not in query_dict:
                raise CompilationError(
                    f"Query '{name}': HTTP queries require a 'url' field"
                )
            try:
                query = HttpQuery(**query_dict)
            except PydanticValidationError as e:
                fields = ", ".join(
                    str(err["loc"][0]) for err in e.errors() if err["loc"]
                )
                raise CompilationError(
                    f"Query '{name}': invalid field(s) for HTTP query: {fields}"
                ) from e
        elif query_type == "values":
            query = ValuesQuery(**query_dict)
        elif query_type == "schema":
            query = SchemaQuery(**query_dict)
        else:
            raise CompilationError(
                f"Query '{name}': unknown type '{query_type}'. "
                "Valid types: http, metricflow, schema, sql, values."
            )

    # Validate setup_sql doesn't contain query references (non-nestable by design)
    if is_sql_query(query) and query.setup_sql and "{{ queries." in query.setup_sql:
        raise CompilationError(
            f"Query '{name}': setup_sql must not contain {{{{ queries.X }}}} references. "
            "setup_sql is for non-nestable setup statements (CREATE TEMP FUNCTION, etc.)."
        )

    # Compile-time SQL guard + variable-dep extraction for SQL queries.
    # UnparseableSqlError is silently deferred (compile lacks the dbt manifest for
    # {{ ref() }} resolution and must not reject boards with complex Jinja macros).
    # MutatingSqlError is fatal at compile time — wrap in CompilationError with query name.
    deps: set[str] = set()
    if is_sql_query(query):
        dialect: str | None = dialect_for_source(query.source, sources)

        # Authoring lint: detect literal \n (backslash + n) from single-quoted YAML.
        # Must run before validate_select_only because literal \n causes parse failure
        # that would otherwise be silently deferred as UnparseableSqlError.
        if has_literal_escaped_newlines(query.sql, dialect=dialect):
            raise CompilationError.from_code(
                ERR_SQL_LITERAL_NEWLINES, query_name=name, field_label="sql"
            )
        if query.setup_sql and has_literal_escaped_newlines(
            query.setup_sql, dialect=dialect
        ):
            raise CompilationError.from_code(
                ERR_SQL_LITERAL_NEWLINES,
                query_name=name,
                field_label="setup_sql",
            )

        try:
            validate_select_only(query.sql, dialect=dialect)
        except UnparseableSqlError as e:
            logger.debug("compile-time SQL validation deferred to runtime: %s", name)
            # Deferral stands either way — compile has no dbt manifest to
            # resolve {{ ref() }} against, so an unparseable body is "we
            # could not check this", not "this is definitely broken". But
            # when the dialect was resolvable AND sqlglot handed back a
            # concrete position, the failure is specific enough to show the
            # author. Anything vaguer stays silent rather than training
            # people to ignore the squiggle.
            if dialect is not None and e.sql_position is not None:
                query.parse_error = SqlParseError(
                    message=strip_ansi(str(e.cause)), position=e.sql_position
                )
        except MutatingSqlError as e:
            # Carry the cause's registered code: CompilationError.__init__
            # assigns the ERR_INTERNAL fallback, so this must follow it.
            error = CompilationError(f"Query '{name}': {e}")
            error.code = e.code
            raise error from e

        if query.setup_sql:
            try:
                validate_setup_sql(query.setup_sql, dialect=dialect)
            except UnparseableSqlError:
                logger.debug(
                    "compile-time setup_sql validation deferred to runtime: %s", name
                )
            except MutatingSqlError as e:
                error = CompilationError(f"Query '{name}' setup_sql: {e}")
                error.code = e.code
                raise error from e

        if query.sql:
            deps |= extract_variable_dependencies(query.sql)
        if query.setup_sql:
            deps |= extract_variable_dependencies(query.setup_sql)
    query.variable_dependencies = frozenset(deps)

    # Resolve the cache cascade (project root → source → board → query)
    # into one policy the executor consumes without cascade logic.
    # Pre-built normalized queries keep the policy they already carry.
    if not prebuilt:
        # Lazy import: compile.config sits above the model layer this module
        # otherwise stays within; imported at the single point of use.
        from dbt_charts.core.compile.config import shipped_cache_root

        # SchemaQuery carries a source and goes through the same executor cache
        # path as SqlQuery, so it takes the source scope too. HttpQuery and
        # ValuesQuery have no source to take one from.
        source_name = (
            query.source if is_sql_query(query) or is_schema_query(query) else None
        )
        query.cache = resolve_cache_policy(
            cache_root if cache_root is not None else shipped_cache_root(),
            source_cache_layer(sources, source_name, name),
            board_cache,
            authored_cache,
        )

    return query


def split_external_query_ref(query_ref: str) -> tuple[str, str]:
    """`path/to/file.yml#query_name` → `("path/to/file.yml", "query_name")`.

    The grammar only — which directory the file part is anchored at is the
    caller's business, and the two resolvers deliberately disagree about it
    (`resolve_external_query` below anchors at the compiling board's
    `base_dir`; the cross-board chart-import walk in `compiler.py` anchors at
    the *source* board's own directory). The parse itself must not diverge with
    them, or the same authored string resolves for a local chart and errors
    for an imported one.
    """
    file_part, _, query_name = query_ref.partition("#")
    if not file_part or not query_name:
        raise CompilationError(
            f"Invalid external query reference: '{query_ref}'. "
            "Expected format: 'path/to/file.yml#query_name'"
        )
    return file_part, query_name


def resolve_external_query(
    query_ref: str,
    query_registry: dict[str, AnyQuery],
    base_dir: ProjectDirectory | None = None,
    *,
    sources: dict[str, Any],
    cache_root: CachePatch | None = None,
    board_cache: CachePatch = INHERIT_CACHE,
) -> tuple[str, dict[str, AnyQuery]]:
    """Resolve an external query reference.

    Parses references like `path/to/file.yml#query_name` and loads
    queries from the external file, memoising via query_registry (compile-scoped).

    Args:
        query_ref: Query reference with file path (e.g., "_shared.yml#sales")
        query_registry: Current query registry to merge into
        base_dir: ProjectDirectory anchor for the board file (used to resolve paths).
        sources: Project source configs, for `normalize_query`'s source-scope
            cache layer.
        cache_root: The project's cascade root — same threading rule as
            `normalize_query`'s.
        board_cache: The importing board's cache layer — same rule as the dotted
            `other.queries.name` lane in `load_from_reference`: an imported
            query is a query of *this* dashboard, so the board's `cache:` has to
            reach it.

    Returns:
        Tuple of (resolved_query_name, updated_query_registry)

    Raises:
        CompilationError: If file not found or query not in file
    """
    file_part, query_name = split_external_query_ref(query_ref)

    if base_dir is None:
        raise CompilationError(
            f"Cannot resolve external query '{query_ref}': "
            "no base directory context (board was compiled without a base directory)"
        )

    registry_key = f"{file_part}#{query_name}"

    # Within-compile memo: this external ref was already resolved this compile.
    if registry_key in query_registry:
        return registry_key, query_registry

    try:
        ref_path = base_dir / file_part
    except ValueError as e:
        raise CompilationError(str(e)) from e

    if not ref_path.exists():
        raise CompilationError(
            f"External query file not found: '{file_part}' "
            f"(referenced as '{query_ref}')"
        )

    try:
        external_data = ref_path.read_yaml()
    except Exception as e:  # noqa: BLE001 — broad catch at IO boundary
        raise CompilationError(
            f"Failed to parse external query file '{file_part}': {e}"
        ) from e

    if not isinstance(external_data, dict):
        raise CompilationError(
            f"External query file '{file_part}' must be a YAML dictionary"
        )

    queries_section = external_data.get("queries", {})
    if query_name not in queries_section:
        available = ", ".join(queries_section.keys()) if queries_section else "none"
        raise CompilationError(
            f"Query '{query_name}' not found in '{file_part}'. "
            f"Available queries: {available}"
        )

    query_registry[registry_key] = normalize_query(
        query_name,
        queries_section[query_name],
        base_dir=base_dir,
        sources=sources,
        cache_root=cache_root,
        board_cache=board_cache,
    )
    return registry_key, query_registry
