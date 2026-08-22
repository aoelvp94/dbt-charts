"""dbt adapter integration for SQL query execution.

Stage: EXECUTE (inside RENDER stage)
Purpose: Execute SQL queries via dbt's adapter system.

This adapter leverages dbt's adapter API to execute SQL queries,
supporting dbt-specific features like ref() and source() resolution.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TID251 — reads dbt profiles.yml/dbt_project.yml
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.source import ResolvedSourceConfig
    from dbt_charts.core.project import Project

from dbt_charts.core.compile.models.board.normalized import VariableValues
from dbt_charts.core.compile.models.query.normalized import (
    AnyQuery,
    is_sql_query,
)
from dbt_charts.core.compile.sql_guard import validate_select_only
from dbt_charts.core.compile.template.jinja import resolve_jinja_template
from dbt_charts.core.compile.template.parameterized import render_parameterized
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.diagnostics.codes_execute import ERR_SOURCE_INVALID_TYPE
from dbt_charts.core.dialects import DIALECTS, get_dialect, list_dialects
from dbt_charts.core.execute.adapters.base import (
    BaseAdapter,
    QueryParams,
    QueryResult,
    apply_row_limit_truncation,
    classify_warehouse_error,
    handle_adapter_error,
    resolve_effective_row_limit,
)
from dbt_charts.core.execute.adapters.dbt_utils import DbtRefResolver
from dbt_charts.core.execute.dbt_jinja import has_dbt_jinja
from dbt_charts.core.execute.sql_literals import (
    INLINE_PLACEHOLDERS,
    inline_params_for_dialect,
)


def _read_profiles_yml(
    dbt_project_path: Path, profiles_dir: Path | None = None
) -> dict[str, Any]:
    """Read and return profiles.yml using the canonical resolution order.

    Resolution order: profiles_dir → DBT_PROFILES_DIR → project-local → ~/.dbt.
    Raises FileNotFoundError if none exists.

    Args:
        dbt_project_path: The dbt project root (where dbt_project.yml lives).
        profiles_dir: Explicit absolute path to the directory containing profiles.yml,
            already resolved. None means use the standard resolution order.
    """
    from dbt_charts.core.project_roots import resolve_profiles_path

    candidate = resolve_profiles_path(dbt_project_path, profiles_dir=profiles_dir)
    with candidate.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"profiles.yml at {candidate} did not parse to a mapping. "
            f"Got: {type(data).__name__}"
        )
    return data


# dbt spelling → the spelling Dataface's own code reads the field under. Deliberately
# tiny: these are the fields *Dataface* consumes, not a mirror of dbt's schema. Adding
# an entry here means some Dataface reader hardcodes a key name — check that first.
_DBT_KEYS_DATAFACE_READS: dict[str, dict[str, str]] = {
    # sql_adapter builds BigQuery's default_dataset from project/dataset;
    # database/schema are dbt's canonical names for the same two fields.
    "bigquery": {"database": "project", "schema": "dataset"},
    # normalize_duckdb_config reads duckdb_config; dbt-duckdb spells it config_options.
    "duckdb": {"config_options": "duckdb_config"},
}


def _read_target_dict(
    dbt_project_path: Path,
    profile_name: str,
    target_name: str | None,
    profiles_dir: Path | None = None,
) -> dict[str, Any]:
    """Return the connection fields for the given profile+target from profiles.yml.

    profiles.yml belongs to dbt, so the installed dbt adapter's credentials class
    validates the target — Dataface declares no schema of its own over a file it
    does not own, which is what rejected valid dbt config (`threads`, canonical
    BigQuery `database`/`schema`). Following dbt's own sequence: drop the
    profile-level `threads` (dbt keeps it beside the credentials, not in them),
    resolve the plugin from `type`, translate dbt's field aliases, then validate.
    Every connection field dbt accepts passes through untouched — dropping one
    would connect with different semantics than dbt, which is worse than erroring.

    dbt-adapters only: dbt.config / dbt.flags are off limits; dbt-core is used
    only for manifest loading (WritableManifest) and test execution.

    Relative `path:` entries (DuckDB) are resolved against `dbt_project_path`
    so the adapter opens the file dbt would have opened, regardless of CWD.

    Args:
        dbt_project_path: The dbt project root; used as the anchor for relative
            DuckDB path: entries and as the fallback location for profiles.yml.
        profile_name: The dbt profile name.
        target_name: The dbt target name. None means use the profile's declared
            default target (profile["target"]), falling back to "dev" if absent.
        profiles_dir: Explicit absolute path to the profiles.yml directory when the
            file does not live at dbt_project_path. None = standard resolution order.
    """
    profiles = _read_profiles_yml(dbt_project_path, profiles_dir=profiles_dir)
    profile = profiles.get(profile_name)
    if profile is None:
        available = [k for k in profiles if k != "config"]
        raise ValueError(
            f"Profile '{profile_name}' not found in profiles.yml "
            f"(checked {dbt_project_path}). "
            f"Available profiles: {available}"
        )
    resolved_target = target_name or profile.get("target", "dev")
    outputs = profile.get("outputs", {})
    target = outputs.get(resolved_target)
    if target is None:
        raise ValueError(
            f"Target '{resolved_target}' not found in profile '{profile_name}'. "
            f"Available targets: {list(outputs.keys())}"
        )

    from dbt.adapters.factory import load_plugin
    from dbt_common.exceptions import DbtRuntimeError
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

    from dbt_charts.core.compile.sources.dbt_jinja import render_dbt_jinja_in_dict

    target = dict(target)
    if "type" not in target:
        raise ValueError(
            f"Profile '{profile_name}' target '{resolved_target}' has no 'type' field. "
            f"Name the warehouse dbt connects with, e.g. `type: postgres`. "
            f"Found: {sorted(target)}"
        )
    typename = str(target["type"])
    connection = {k: v for k, v in target.items() if k not in {"threads", "type"}}

    # Everything dbt can reject about a target arrives as ValueError, which is what
    # all three callers guard on: an unknown adapter type, a duplicated alias
    # (project *and* database), or a schema violation.
    #
    # Validation needs dbt's canonical spelling AND its rendered values — dbt renders
    # Jinja first, so validating the raw YAML would reject an env_var() in any field
    # dbt types as non-string (port, threads, …). Both transforms apply to a throwaway
    # copy: the returned target keeps the author's spelling for the readers below, and
    # its Jinja is left raw. On the resolver path that dict becomes a
    # DbtTargetSourceConfig, whose inherited validator renders it exactly once —
    # rendering here as well would evaluate that pass's own output as a template. The
    # two direct callers (DbtAdapter._get_adapter, metricflow lowering) never render,
    # same as before this change.
    try:
        credentials_cls = load_plugin(typename)
        credentials_cls.validate(
            credentials_cls.translate_aliases(
                render_dbt_jinja_in_dict(dict(connection))
            )
        )
    except JsonSchemaValidationError as exc:
        raise ValueError(
            f"Profile '{profile_name}' target '{resolved_target}' is not a valid "
            f"{typename} connection for the installed dbt-{typename} adapter: "
            f"{exc.message}"
        ) from exc
    except DbtRuntimeError as exc:
        raise ValueError(
            f"Profile '{profile_name}' target '{resolved_target}': {exc}"
        ) from exc

    # dbt accepts several spellings per field; a few of them are read downstream by
    # *Dataface* under its own name (the BigQuery default_dataset build in
    # sql_adapter, normalize_duckdb_config), so those are renamed here or the
    # setting is silently lost. Only fields Dataface itself consumes — everything
    # else stays exactly as authored, for dbt's own credentials class to interpret.
    for dbt_name, dbt_charts_name in _DBT_KEYS_DATAFACE_READS.get(typename, {}).items():
        if dbt_name in connection and dbt_charts_name not in connection:
            connection[dbt_charts_name] = connection.pop(dbt_name)

    target = connection
    target["type"] = typename

    raw_path = target.get("path")
    if isinstance(raw_path, str) and raw_path and raw_path != ":memory:":
        path_obj = Path(raw_path)
        if not path_obj.is_absolute():
            target["path"] = str((dbt_project_path / path_obj).resolve())
    return target


class DbtAdapter(BaseAdapter):
    """Adapter for executing SQL queries via dbt's adapter system.

    Supported query types: sql

    Leverages dbt's adapter API to execute SQL queries with support for
    dbt-specific features like ref(), source(), etc.

    This adapter requires dbt-adapters and a warehouse-specific dbt package
    (e.g. dbt-duckdb, dbt-postgres) — not dbt-core. A valid dbt project
    with profiles.yml configuration is also required.

    Example:
        >>> from dbt_charts.cli.filesystem_project import FilesystemProject
        >>> project_path = Path("./my_dbt_project")
        >>> adapter = DbtAdapter(
        ...     project=FilesystemProject(project_path),
        ...     dbt_project_path=project_path,
        ...     target_name="dev",
        ... )
        >>> query = SqlQuery(sql="SELECT * FROM {{ ref('customers') }}", source="my_dbt_source")
        >>> result = adapter.execute(query)
    """

    def __init__(
        self,
        *,
        project: Project,
        dbt_project_path: Path,
        target_name: str,
        profile_name: str | None = None,
    ):
        """Initialize dbt adapter.

        Args:
            project: The Dataface project (manifest reads route through this,
                not dbt_project_path — see DbtRefResolver).
            dbt_project_path: Path to dbt project. Still used for profiles.yml
                / dbt_project.yml resolution, which stays a raw filesystem
                read (out of the Project seam) since dbt's own config
                resolution order is disk-anchored.
            target_name: dbt target name
            profile_name: dbt profile name (default: from dbt_project.yml)
        """
        self.project = project
        self.dbt_project_path = Path(dbt_project_path).resolve()
        self.profile_name = profile_name
        self.target_name = target_name
        self._adapter: Any = None
        # _dialect is populated by _get_dbt_adapter(), which always runs before
        # any validate_select_only() or filter-binding call site and stores this
        # field before the adapter another thread short-circuits on.
        self._dialect: str = ""
        self._dbt_refs = DbtRefResolver(project)

    @property
    def supported_types(self) -> set[str]:
        """Return supported query types."""
        return {"sql"}

    def _can_execute(
        self, query: AnyQuery, source_config: ResolvedSourceConfig | None
    ) -> bool:
        """Claim source-less SQL that uses dbt jinja ({{ ref() }}).

        A dbt-jinja query whose source resolves to no connection config defers to
        the dbt project's manifest/profiles.yml. A named `type: dbt_profile`
        source expands to its concrete warehouse type in the resolver before
        routing, so it lands on the type-owning adapter instead (see
        test_dbt_profile_routing.py).
        """
        return (
            is_sql_query(query) and source_config is None and has_dbt_jinja(query.sql)
        )

    def _execute(
        self,
        query: AnyQuery,
        variables: VariableValues | None = None,
        params: QueryParams = None,
        source_config: ResolvedSourceConfig | None = None,
    ) -> QueryResult:
        """Execute a SQL query via dbt adapter.

        Args:
            query: AnyQuery object (SqlQuery expected)
            variables: Variable values for Jinja resolution
            params: Accepted for interface compatibility; not used by dbt adapter.

        Returns:
            QueryResult with data or error
        """
        if not is_sql_query(query):
            return QueryResult(
                data=[],
                error=f"Expected SQL query, got {query.query_type}",
            )

        try:
            adapter = (
                self._adapter if self._adapter is not None else self._get_dbt_adapter()
            )
        except Exception as e:  # noqa: BLE001 — setup, not a warehouse rejection
            return handle_adapter_error("dbt adapter setup", e)

        try:
            resolved_sql = self._resolve_dbt_sql(
                query.sql, variables, strict=not query.lenient_variables
            )
        except Exception as e:  # noqa: BLE001 — names the actual failure, not setup
            return handle_adapter_error("query template rendering", e)

        try:
            validate_select_only(resolved_sql, dialect=self._dialect)
        except Exception as e:  # noqa: BLE001 — guard rejection, not a warehouse rejection
            return handle_adapter_error("dbt adapter setup", e)

        # Bounds the driver's own fetch (execute(..., limit=...) ->
        # cursor.fetchmany()) — resolved_sql is sent to the warehouse
        # unmodified, so every statement shape behaves exactly as it would
        # without this ceiling.
        row_fetch_limit = resolve_effective_row_limit(query.limit)
        # Some dbt-adapters cursors (dbt-spark's Hive/ODBC wrappers) implement
        # fetchall but not fetchmany — passing limit= there raises AttributeError
        # inside get_result_from_cursor. Omit it for those dialects and fall back
        # to the post-fetch slice below.
        driver_limit = (
            row_fetch_limit.fetch_limit
            if get_dialect(self._dialect).cursor_supports_driver_limit
            else None
        )

        try:
            # auto_begin=False, like dbt's own select path: a SELECT needs no
            # transaction, and one opened here is only ended by the release on
            # context exit. Nothing to end is stronger than something to clean up.
            with adapter.connection_named("dbt_charts_query"):
                _, table = adapter.execute(
                    resolved_sql,
                    auto_begin=False,
                    fetch=True,
                    limit=driver_limit,
                )
        except Exception as e:  # noqa: BLE001
            return classify_warehouse_error("dbt SQL execution", e, self._dialect)

        # Result materialization is client-side (no further warehouse round
        # trip) — left unguarded so a defect here surfaces as a crash, not a
        # mislabeled "warehouse rejected the query".
        columns = list(table.column_names)
        rows = list(table.rows)
        rows, truncated_reason = apply_row_limit_truncation(rows, row_fetch_limit)
        data = [dict(zip(columns, row, strict=False)) for row in rows]
        return QueryResult(
            data=data, columns=columns, truncated_reason=truncated_reason
        )

    def _get_dbt_adapter(self) -> Any:
        """Get dbt adapter instance (lazy-loaded).

        Delegates adapter construction to build_adapter() in the factory —
        single point of truth for source_config → dbt adapter.
        """
        if self._adapter is not None:
            return self._adapter

        if not self.profile_name:
            project_config_path = self.dbt_project_path / "dbt_project.yml"
            if project_config_path.exists():
                with project_config_path.open(encoding="utf-8") as f:
                    project_dict = yaml.safe_load(f)
                profile_from_project = project_dict.get("profile")
                if not profile_from_project:
                    raise ValueError(
                        f"dbt_project.yml at {project_config_path} has no 'profile:' key"
                    )
                self.profile_name = profile_from_project
            else:
                raise FileNotFoundError(
                    f"No dbt_project.yml found at {project_config_path} and no "
                    f"profile_name was provided to DbtAdapter"
                )

        target_dict = _read_target_dict(
            self.dbt_project_path, self.profile_name, self.target_name
        )
        from dbt_charts.core.execute.adapters.dbt_adapter_factory import build_adapter

        # Dialect first, adapter second, and not the other way round: workers run
        # this concurrently against one DbtAdapter and _execute short-circuits on
        # `self._adapter is not None`, so storing the adapter first opens a window
        # where another thread reads the empty dialect. `_read_target_dict` has
        # already raised if 'type' is missing, so reading it here is safe.
        # read_only=True: DbtAdapter is SELECT-only (validate_select_only gates
        # every execute), so the read-only DuckDB path is safe and lets us
        # coexist with other read-only connections on the same file.
        self._dialect = target_dict["type"]
        self._adapter = build_adapter(target_dict, read_only=True)
        return self._adapter

    def _resolve_dbt_sql(
        self,
        sql: str,
        variables: dict[str, Any] | None = None,
        *,
        strict: bool = True,
    ) -> str:
        """Resolve dbt refs, then render variables and filters to literal SQL.

        Variables resolve exactly as they always have on this path. Only the
        filter helpers change: `resolve_jinja_template` masks them so they never
        reach the raising interpolation stubs, and binds each one — from its own
        author-written text — while unmasking.

        One render, deliberately. A second pass over this method's output would
        be re-rendering substituted variable values, and values come from URL
        query parameters: they are data, never template source.

        Binding only the helpers is also what keeps a variable written *inside*
        a literal (`'%{{ q }}%'`, `'{{ year }}-01-01'`) rendering as before; a
        bound value arrives already quoted and cannot be spliced into the middle
        of somebody else's string.

        Args:
            sql: Query SQL, possibly containing dbt jinja and variable Jinja.
            variables: Variable values available to the template.
            strict: False lets undefined variables render empty, for queries
                that declare lenient_variables.
        """
        resolved, _ = self._dbt_refs.resolve(sql)
        return resolve_jinja_template(
            resolved,
            variables,
            strict=strict,
            bind_filters=lambda call: self._bind_filter_call(call, variables, strict),
        )

    def _bind_filter_call(
        self, call: str, variables: dict[str, Any] | None, strict: bool
    ) -> str:
        """Bind one `{{ filter(...) }}` span to a predicate with literal values.

        `call` is the span exactly as authored, so rendering it is rendering
        author-written template text — the values it references are supplied as
        parameters and flattened to escaped literals, never rendered.

        INLINE_PLACEHOLDERS rather than the warehouse's parameter syntax. A span
        holds no author-written literal, so the warehouse's own syntax would in
        fact round-trip today; this keeps the two halves agreeing on a style
        that cannot collide with anything, independent of what the span
        eventually contains. Escaping is a separate question from placeholder
        shape, and follows the engine that will parse the literal — the target
        this adapter connected to, never the internal placeholder style.

        Raises:
            DbtChartsError: The dbt target's warehouse type has no dialect here,
                so its literal grammar is unknown. `get_dialect` would answer
                postgres, which leaves backslashes alone — the wrong answer for
                a value on any engine that escapes them, and wrong in the
                direction that puts part of a value in code position.
        """
        warehouse = DIALECTS.get(self._dialect.lower())
        if warehouse is None:
            raise DbtChartsError.from_code(
                ERR_SOURCE_INVALID_TYPE,
                offending_value=self._dialect,
                available=list_dialects(),
            )
        parameterized = render_parameterized(
            call, variables=variables, dialect=INLINE_PLACEHOLDERS, strict=strict
        )
        return inline_params_for_dialect(
            parameterized.sql,
            parameterized.params,
            INLINE_PLACEHOLDERS,
            escaping=warehouse,
        )
