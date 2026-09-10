"""FileSourceMaterializer — load file sources into any QueryResultCache backend.

Stage: EXECUTE
Purpose: Parse CSV/JSON/Parquet files (via PyArrow, no DuckDB filesystem access)
into rows, store in a QueryResultCache via put(), and register a SQL view per
table name so author SQL like ``SELECT * FROM sales`` works against the cache engine.

CSV and Parquet also hand put() the ``pyarrow.Table`` they parsed, so the stored
table carries the file's own column types (a Parquet DECIMAL(18,2) stays a
DECIMAL(18,2)) instead of whatever the backend's row-dict storage encoding would
have made of them. JSON/NDJSON have no schema beyond ``json.loads``, so they stay
on the row-dict path.

Cache key per file table:
    source_hash    = compute_source_hash(source_config)
    query_hash     = Project.file_version(relpath), hashed to 16 hex — the single
                     file-identity token (a stat signature locally, a git blob OID
                     on Cloud), NOT a re-hash of the file's bytes. Computing it is
                     cheap, so a warm table skips the read entirely.
    variables_hash = FILE_SOURCE_VARS_HASH  (file sources have no variables)

For glob patterns (paths containing ``*`` or ``?``), the files: value is expanded
via ``project.files.glob()``. The combined version key encodes the full set of
matched relpaths and their individual version tokens, so the cache invalidates
when any matched file changes OR when files are added/removed from the glob set.

On a cache hit the table/view already exists and the file is never read; on a miss
we read + parse + put + register. When the cache is a DuckDB-backed cache,
disable_external_access() is called once at construction so author SQL cannot call
read_csv('http://...') or access local filesystem paths at query time.
"""

from __future__ import annotations

import hashlib
import io
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeAlias

from dbt_charts.core.compile.config import (
    get_execution_config,
    resolve_file_source_max_bytes,
    resolve_file_source_max_tables,
)
from dbt_charts.core.compile.models.source import (
    CsvSourceConfig,
    JsonSourceConfig,
    ParquetSourceConfig,
)
from dbt_charts.core.compile.template.parameterized import render_parameterized
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.diagnostics.codes_execute import (
    ERR_FILE_SOURCE_DECIMAL_TOO_WIDE,
    ERR_FILE_SOURCE_TOO_LARGE,
    ERR_FILE_SOURCE_TOO_MANY_TABLES,
    ERR_GLOB_EMPTY,
    ERR_GLOB_SCHEMA_MISMATCH,
    ERR_GLOB_TOO_MANY,
)
from dbt_charts.core.execute.adapters.base import QueryParams
from dbt_charts.core.execute.cache_backend import FILE_SOURCE_VARS_HASH, CacheHit
from dbt_charts.core.execute.duckdb_cache import compute_source_hash
from dbt_charts.core.project import is_glob

if TYPE_CHECKING:
    import pyarrow as pa

    from dbt_charts.core.execute.cache_backend import QueryResultCache
    from dbt_charts.core.project import Project

# JSON files carry runtime-dynamic column schemas; Any is the correct boundary type.
_JsonRow: TypeAlias = dict[str, Any]

# Decimal MB, matching how execution.file_source_max_bytes is documented
# ("5 GB" == 5_000_000_000) — a MiB divisor would render that default as a
# confusing "4768.4 MB".
_BYTES_PER_MB = 1_000_000

logger = logging.getLogger(__name__)


def default_local_materializer_factory(
    project: Project,
) -> Callable[[], FileSourceMaterializer]:
    """A factory that lazily builds the local DuckDB-backed file materializer.

    Handed to ``Executor(file_materializer_factory=...)`` and
    ``AdapterRegistry(file_materializer_factory=...)`` for local ``dct`` so the
    materializer (and its in-memory DuckDB) is created only when a file-source
    query actually misses the result cache — a fully-cached render, or a
    session that never touches a file source, never opens one. Cloud injects
    its own Postgres-backed materializer instead.
    """

    def _build() -> FileSourceMaterializer:
        from dbt_charts.core.execute.trivial_local_cache import TrivialDuckDBCache

        return FileSourceMaterializer(project, TrivialDuckDBCache())

    return _build


def resolve_local_file_materializer_factory(
    project: Project,
    file_materializer: FileSourceMaterializer | None,
) -> Callable[[], FileSourceMaterializer] | None:
    """The one place that resolves "local means the DuckDB-backed factory".

    Every local composition root (render, registered views, the ad-hoc
    ``AdapterRegistry`` a ``ProjectSession`` lazily builds) needs the same
    choice: an injected ``file_materializer`` (Cloud, or any other host) wins
    outright and needs no factory; its absence falls back to
    ``default_local_materializer_factory``. Routing every call site through
    this function is what keeps that fallback from being reinvented per site.
    """
    if file_materializer is not None:
        return None
    return default_local_materializer_factory(project)


def _version_key(token: str) -> str:
    """Hash a Project.file_version token to the 16-hex cache-key slot form.

    file_version tokens are host-specific (a ``mtime_ns:size`` stat signature
    locally, a git blob OID on Cloud); hashing them to a fixed 16-hex string
    yields an identifier-safe cache-key component regardless of the token shape.
    """
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _glob_vkey(sorted_pairs: list[tuple[str, str]]) -> str:
    """Composite version key for a glob table.

    Encodes both the set of matched relpaths and their per-file version tokens
    so the cache invalidates when any file changes content, is added, or is
    removed from the glob match set.  ``sorted_pairs`` must be pre-sorted by
    relpath (``project.files.glob`` yields sorted order).
    """
    combined = "\n".join(f"{relpath}:{vk}" for relpath, vk in sorted_pairs)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


class FileSourceMaterializer:
    """Materializes file-based sources into any QueryResultCache backend.

    Each table in the source's ``files`` mapping is loaded into the cache via
    ``cache.put()``. A SQL view/alias is then created under the table's authored
    name so author SQL can reference it by name directly.

    When the cache backend is DuckDB-based, ``disable_external_access()`` is
    called once at construction to prevent author SQL from reading the filesystem
    or network (``read_csv('http://...')``, etc.).

    Args:
        project: The dbt charts project (for resolving file paths and reading bytes).
        cache: Any QueryResultCache implementation to materialize into.
    """

    def __init__(self, project: Project, cache: QueryResultCache) -> None:
        self._project = project
        self._cache = cache
        # Serialize all cache access across threads. DuckDB in-memory connections
        # are not thread-safe; this lock covers the full materialize_and_run
        # critical section. For Postgres-backed caches, the lock still serializes
        # the put+register pair so register always sees the row it just wrote.
        self._lock = threading.Lock()
        # Disable external access once at construction. For DuckDB: prevents author
        # SQL from reaching the filesystem or network. For Postgres: no-op.
        self._cache.disable_external_access()

    def close(self) -> None:
        """Release the backing cache's held resources (e.g. a DuckDB handle)."""
        self._cache.close()

    def materialize_and_run(
        self,
        source: CsvSourceConfig | JsonSourceConfig | ParquetSourceConfig,
        sql: str,
        variables: dict[str, Any],
        source_name: str,
        params: QueryParams = None,
        strict: bool = True,
    ) -> list[_JsonRow]:
        """Ensure all tables in *source* are in the cache, then execute *sql*.

        Glob patterns (``*`` / ``?``) in ``source.files`` values are expanded via
        ``project.files.glob()``.  Each glob must match at least one file and may
        not exceed ``execution.max_glob_file_count``.  All matched files are loaded
        and their rows concatenated into one table.

        Two more guardrails bound a single relation's growth: ``source.files``
        may not declare more tables than ``execution.file_source_max_tables``
        (checked up front, before any file read), and each relation's
        uncompressed byte size — summed across its matched files, measured by
        ``_uncompressed_bytes`` — may not exceed
        ``execution.file_source_max_bytes`` (checked as each file is read,
        before it is parsed or written to the cache).

        Args:
            source: A CsvSourceConfig, JsonSourceConfig, or ParquetSourceConfig.
            sql: SQL template (may contain {{ variable }} Jinja expressions),
                or — when *params* is given — SQL already rendered to the
                "duckdb" placeholder style (``$1``, ``$2``, …) by an upstream
                composition step (``AdapterRegistry._compose_query_refs``),
                which also expands ``{{ queries.X }}`` refs this method's own
                rendering does not.
            variables: Variable values substituted into *sql* via
                render_parameterized. Ignored when *params* is given — *sql*
                is already rendered.
            source_name: Authored source name (for error messages).
            params: Pre-rendered positional parameter values, in the same
                "duckdb" placeholder style this method renders internally
                when omitted. Passed by ``AdapterRegistry`` once it has
                already composed the SQL; ``None`` (the render path's own
                caller) renders *sql* against *variables* here instead.
            strict: Passed to the internal ``render_parameterized`` call when
                *params* is None (a caller that already composed *sql* has
                already made this choice). Mirrors every other adapter's
                ``strict=not query.lenient_variables`` — an undefined
                ``{{ variable }}`` raises when True (default), renders as an
                empty string when False.

        Returns:
            Rows returned by *sql*.

        Raises:
            DbtChartsError: Empty glob match, glob fan-out cap exceeded,
                table-count cap exceeded, or materialized-byte cap exceeded.
            RuntimeError: If SQL execution fails (propagated from execute_file_source_sql,
                includes external-access violations in author SQL).
        """
        source_hash = compute_source_hash(source)
        cap = get_execution_config().max_glob_file_count
        byte_cap = resolve_file_source_max_bytes()

        table_cap = resolve_file_source_max_tables()
        if len(source.files) > table_cap:
            raise DbtChartsError.from_code(
                ERR_FILE_SOURCE_TOO_MANY_TABLES,
                source_name=source_name,
                count=len(source.files),
                cap=table_cap,
            )

        # Each entry: (table_name, vkey, sorted_relpaths).
        # For literal paths: one relpath, vkey from that file alone.
        # For globs: sorted relpaths from glob expansion, composite vkey.
        # Glob expansion and cap/empty checks happen here — before the lock,
        # before any file reads, so a bad glob fails fast.
        table_specs: list[tuple[str, str, list[str]]] = []
        for table_name, path_or_glob in source.files.items():
            if is_glob(path_or_glob):
                matched = sorted(
                    p.relpath for p in self._project.files.glob(path_or_glob)
                )
                if not matched:
                    raise DbtChartsError.from_code(
                        ERR_GLOB_EMPTY,
                        source_name=source_name,
                        table_name=table_name,
                        pattern=path_or_glob,
                    )
                if len(matched) > cap:
                    raise DbtChartsError.from_code(
                        ERR_GLOB_TOO_MANY,
                        source_name=source_name,
                        table_name=table_name,
                        pattern=path_or_glob,
                        count=len(matched),
                        cap=cap,
                    )
                pairs = [
                    (r, _version_key(self._project.file_version(r))) for r in matched
                ]
                vkey = _glob_vkey(pairs)
                table_specs.append((table_name, vkey, matched))
            else:
                vkey = _version_key(self._project.file_version(path_or_glob))
                table_specs.append((table_name, vkey, [path_or_glob]))

        if params is not None:
            # Already rendered by the caller (AdapterRegistry._compose_query_refs)
            # in this same "duckdb" placeholder style — {{ queries.X }} refs and
            # variables are both expanded, so there is nothing left to render here.
            resolved_sql, resolved_params = sql, params
        else:
            # Render {{ variable }} templates to parameterized SQL before
            # executing. profile_type="duckdb" → $1/$2/… placeholders (DuckDB
            # positional style).
            parameterized = render_parameterized(
                sql, variables, profile_type="duckdb", strict=strict
            )
            resolved_sql, resolved_params = parameterized.sql, parameterized.params

        union_by_name = isinstance(source, JsonSourceConfig) and source.union_by_name

        with self._lock:
            for table_name, vkey, relpaths in table_specs:
                # Cache miss → read + parse + store. A hit never opens any file.
                if not isinstance(
                    self._cache.get(source_hash, vkey, FILE_SOURCE_VARS_HASH), CacheHit
                ):
                    rows: list[_JsonRow] = []
                    arrow: pa.Table | None = None
                    # The file folded into `arrow` most recently — the neighbor
                    # a schema conflict is actually against, which for a long
                    # glob is more useful than always blaming the first shard.
                    previous_relpath = ""
                    first_relpath = ""
                    first_keys: frozenset[str] = frozenset()
                    materialized_bytes = 0
                    for relpath in relpaths:
                        file_bytes = self._project.read_bytes(relpath)
                        materialized_bytes += _uncompressed_bytes(source, file_bytes)
                        if materialized_bytes > byte_cap:
                            raise DbtChartsError.from_code(
                                ERR_FILE_SOURCE_TOO_LARGE,
                                source_name=source_name,
                                table_name=table_name,
                                relpath=relpath,
                                raw_mb=len(file_bytes) / _BYTES_PER_MB,
                                size_mb=materialized_bytes / _BYTES_PER_MB,
                                cap_mb=byte_cap / _BYTES_PER_MB,
                            )
                        file_rows, file_arrow = _parse(source, file_bytes, relpath)
                        if file_rows:
                            # Schema check uses only the first row's keys.  This catches
                            # header-level mismatches (the common authoring mistake) but
                            # will not detect a mid-file column shift in irregular formats.
                            file_keys = frozenset(file_rows[0])
                            if not first_relpath:
                                first_keys = file_keys
                                first_relpath = relpath
                            elif not union_by_name and file_keys != first_keys:
                                extra = sorted(file_keys - first_keys)
                                missing = sorted(first_keys - file_keys)
                                detail = (f"Extra: {extra}. " if extra else "") + (
                                    f"Missing: {missing}. " if missing else ""
                                )
                                raise DbtChartsError.from_code(
                                    ERR_GLOB_SCHEMA_MISMATCH,
                                    source_name=source_name,
                                    table_name=table_name,
                                    path=relpath,
                                    first_path=first_relpath,
                                    detail=detail,
                                )
                            rows.extend(file_rows)
                            if file_arrow is not None:
                                arrow = _merge_arrow(
                                    arrow,
                                    _normalize_arrow(
                                        file_arrow, source_name, table_name, relpath
                                    ),
                                    source_name,
                                    table_name,
                                    relpath,
                                    previous_relpath,
                                )
                                previous_relpath = relpath
                    if union_by_name and rows:
                        # Union of column names in first-seen insertion order so
                        # the created table's column order is deterministic across
                        # processes (a set would vary under hash randomization).
                        all_keys = dict.fromkeys(k for row in rows for k in row)
                        for row in rows:
                            for k in all_keys:
                                row.setdefault(k, None)
                    # Individual glob-matched files with zero rows are silently
                    # skipped (common for empty partitions); the error fires only
                    # when *all* matched files together contribute no rows.
                    if not rows:
                        raise ValueError(
                            f"File table {table_name!r}: parsed file(s) contain no rows. "
                            "Empty file sources are not supported — "
                            "provide a file with at least one data row."
                        )
                    if arrow is not None:
                        import pyarrow as pa

                        # A column still ``null`` after the merge had no values
                        # in any shard. DuckDB would make it INTEGER, breaking
                        # the text SQL an author wrote for it; VARCHAR is what
                        # the row-dict path always gave it.
                        arrow = _normalize_arrow(
                            arrow,
                            source_name,
                            table_name,
                            previous_relpath,
                            null_as=pa.string(),
                        )
                    self._cache.put(
                        source_hash,
                        vkey,
                        FILE_SOURCE_VARS_HASH,
                        rows,
                        board_slug="__file_source__",
                        query_name=table_name,
                        arrow=arrow,
                    )

                # Register (or re-register) so SQL can reference the table name.
                # For DuckDB: creates/replaces a VIEW pointing at the _r_<hash> table.
                # For Postgres: records the mapping for execute_file_source_sql to load.
                self._cache.register_file_table(table_name, source_hash, vkey)

            return self._cache.execute_file_source_sql(resolved_sql, resolved_params)


def _uncompressed_bytes(
    source: CsvSourceConfig | JsonSourceConfig | ParquetSourceConfig,
    file_bytes: bytes,
) -> int:
    """How much data this file actually carries, in bytes.

    For CSV and JSON that is the file itself. For Parquet it is the sum of
    the row groups' ``total_byte_size``, read from the footer — the file's own
    record of its uncompressed size, which is the same quantity ``len()``
    reports for the text formats. Measuring all three that way is what lets
    one cap mean one thing across formats, so the compact format is never
    the one a budget rejects.

    The footer parse is free relative to the check it feeds: the caller has
    already read the whole file (``Project`` exposes no range read), and this
    is what avoids paying ``pq.read_table`` on a relation that will not fit.
    """
    if not isinstance(source, ParquetSourceConfig):
        return len(file_bytes)
    import pyarrow.parquet as pq

    metadata = pq.ParquetFile(  # type: ignore[no-untyped-call]  # type-state: type_ignore — pyarrow's stubs are placeholders; upstream gap
        io.BytesIO(file_bytes)
    ).metadata
    return sum(
        metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups)
    )


# ── Module-level parse helpers (no DuckDB filesystem access) ─────────────────


def _engine_type(
    arrow_type: pa.DataType, null_as: pa.DataType | None = None
) -> pa.DataType:
    """The nearest type DuckDB's Arrow bridge accepts, recursing into children.

    ``float16`` and ``decimal256`` are the two Parquet can hand us that the
    bridge rejects outright, at the top level or nested inside a list, struct,
    or map. Widening a half float to ``float32`` is lossless; narrowing a
    ``decimal256`` to ``DECIMAL(38, s)`` is lossless for every value that fits,
    and the caller's ``safe`` cast raises rather than truncating for one that
    does not.
    """
    import pyarrow as pa

    # ``null`` (a column with no values at all) is left alone per shard so the
    # glob merge can promote it to a sibling's type; only the merged table
    # asks for it as text — see the ``null_as`` pass in materialize_and_run.
    if null_as is not None and pa.types.is_null(arrow_type):
        return null_as
    if pa.types.is_float16(arrow_type):
        return pa.float32()
    if pa.types.is_decimal256(arrow_type):
        return pa.decimal128(38, arrow_type.scale)
    if pa.types.is_list(arrow_type):
        return pa.list_(_engine_field(arrow_type.value_field, null_as))
    if pa.types.is_large_list(arrow_type):
        return pa.large_list(_engine_field(arrow_type.value_field, null_as))
    if pa.types.is_fixed_size_list(arrow_type):
        return pa.list_(
            _engine_field(arrow_type.value_field, null_as), arrow_type.list_size
        )
    if pa.types.is_struct(arrow_type):
        return pa.struct([_engine_field(child, null_as) for child in arrow_type])
    if pa.types.is_map(arrow_type):
        return pa.map_(
            _engine_type(arrow_type.key_type, null_as),
            _engine_type(arrow_type.item_type, null_as),
        )
    return arrow_type


def _engine_field(field: pa.Field, null_as: pa.DataType | None) -> pa.Field:
    return field.with_type(_engine_type(field.type, null_as))


def _normalize_arrow(
    table: pa.Table,
    source_name: str,
    table_name: str,
    relpath: str,
    *,
    null_as: pa.DataType | None = None,
) -> pa.Table:
    """Recast *table* into types the query engine can load, or raise.

    Every cast is ``safe``, so a value that will not fit the narrowed type
    raises here instead of arriving silently truncated in a chart.

    Positional throughout: Arrow permits duplicate column names, and looking a
    field up by name returns -1 when there are two, which would corrupt the
    table it is meant to be fixing.
    """
    import pyarrow as pa

    normalized = pa.schema(
        [_engine_field(field, null_as) for field in table.schema],
        metadata=table.schema.metadata,
    )
    if normalized.equals(table.schema):
        return table

    columns = []
    for index, field in enumerate(table.schema):
        column = table.column(index)
        target = normalized.field(index).type
        if target == field.type:
            columns.append(column)
            continue
        try:
            fitted = column.cast(target, safe=True)  # type-state: cast — raises
        except pa.ArrowInvalid as e:
            raise DbtChartsError.from_code(
                ERR_FILE_SOURCE_DECIMAL_TOO_WIDE,
                source_name=source_name,
                table_name=table_name,
                column=field.name,
                relpath=relpath,
                column_type=str(field.type),
            ) from e
        columns.append(fitted)
    return pa.Table.from_arrays(columns, schema=normalized)


def _merge_arrow(
    accumulated: pa.Table | None,
    table: pa.Table,
    source_name: str,
    table_name: str,
    relpath: str,
    previous_relpath: str,
) -> pa.Table:
    """Fold one more matched file into the glob's typed table.

    ``promote_options="default"`` unifies by column name and lets a shard whose
    column is empty (PyArrow types it ``null``) take a sibling's type — both are
    ordinary shard shapes that the row-dict path always accepted. It does not
    unify two *widths* of one kind (int32/int64, float/double, timestamp[ms]/
    [us], DECIMAL(18,2)/DECIMAL(38,2)) — two producers writing the same column,
    which the row-dict path also loaded losslessly — so ``_widen_to_match``
    casts those to the wider side first. It stops short of ``"permissive"``,
    which would widen an int64 column to double to swallow a genuine type
    conflict. Folding per file rather than concatenating at the end is what
    lets the error name the two files that disagree.
    """
    if accumulated is None:
        return table
    import pyarrow as pa

    try:
        accumulated, table = _widen_to_match(accumulated, table)
        return pa.concat_tables([accumulated, table], promote_options="default")
    except (pa.ArrowInvalid, pa.ArrowTypeError) as e:
        raise DbtChartsError.from_code(
            ERR_GLOB_SCHEMA_MISMATCH,
            source_name=source_name,
            table_name=table_name,
            path=relpath,
            first_path=previous_relpath,
            detail=f"{e}. ",
        ) from e


# Finer is wider — except nanoseconds, whose int64 range ends in 2262 and
# would put a 9999-12-31 sentinel out of bounds. DuckDB's TIMESTAMP is
# microseconds, so that is where a unit pair caps.
_TIME_UNIT_RANK = {"s": 0, "ms": 1, "us": 2, "ns": 2}
_TIME_UNIT_AT_RANK = {0: "s", 1: "ms", 2: "us"}


def _wider(a: pa.DataType, b: pa.DataType) -> pa.DataType | None:
    """The lossless common type of two widths of one kind, or None when the
    pair is a genuine conflict (int vs double, string vs numeric, nested)."""
    import pyarrow as pa

    if pa.types.is_integer(a) and pa.types.is_integer(b):
        if pa.types.is_signed_integer(a) != pa.types.is_signed_integer(b):
            return None
        return a if a.bit_width >= b.bit_width else b
    if pa.types.is_floating(a) and pa.types.is_floating(b):
        return a if a.bit_width >= b.bit_width else b
    if pa.types.is_timestamp(a) and pa.types.is_timestamp(b) and a.tz == b.tz:
        rank = max(_TIME_UNIT_RANK[a.unit], _TIME_UNIT_RANK[b.unit])
        return pa.timestamp(_TIME_UNIT_AT_RANK[rank], a.tz)
    if pa.types.is_decimal(a) and pa.types.is_decimal(b) and a.scale == b.scale:
        return a if a.precision >= b.precision else b
    return None


def _widen_to_match(
    accumulated: pa.Table, table: pa.Table
) -> tuple[pa.Table, pa.Table]:
    """Cast width-only differences on shared column names to the wider type.

    Integer, float and decimal-precision widening cannot lose a value. A
    timestamp pair caps at microseconds (see ``_TIME_UNIT_RANK``), so a
    nanosecond shard with sub-microsecond remainders is the one cast that can
    refuse — it raises inside ``_merge_arrow``'s guard and is stamped like any
    other shard mismatch. A duplicated column name (``get_field_index``
    answers -1) is left for ``concat_tables`` to judge.
    """
    for name in set(accumulated.schema.names) & set(table.schema.names):
        ia = accumulated.schema.get_field_index(name)
        ib = table.schema.get_field_index(name)
        if ia < 0 or ib < 0:
            continue
        ta, tb = accumulated.schema.field(ia).type, table.schema.field(ib).type
        if ta == tb:
            continue
        wide = _wider(ta, tb)
        if wide is None:
            continue
        if ta != wide:
            accumulated = accumulated.set_column(
                ia,
                accumulated.schema.field(ia).with_type(wide),
                accumulated.column(ia).cast(wide),  # type-state: cast — widening
            )
        if tb != wide:
            table = table.set_column(
                ib,
                table.schema.field(ib).with_type(wide),
                table.column(ib).cast(wide),  # type-state: cast — widening
            )
    return accumulated, table


def _parse(
    source: CsvSourceConfig | JsonSourceConfig | ParquetSourceConfig,
    file_bytes: bytes,
    relpath: str,
) -> tuple[list[_JsonRow], pa.Table | None]:
    """Dispatch to the correct parser, returning rows and the typed Arrow form.

    The Arrow table is None for JSON/NDJSON, whose values carry no schema beyond
    what ``json.loads`` produces; for CSV and Parquet it is the file's own typed
    representation, which ``materialize_and_run`` hands to ``cache.put`` so the
    SQL-visible table keeps those types.
    """
    if isinstance(source, CsvSourceConfig):
        table = _parse_csv(file_bytes, source.delimiter, source.encoding)
    elif isinstance(source, JsonSourceConfig):
        return _parse_json(file_bytes, relpath), None
    else:
        table = _parse_parquet(file_bytes)
    return table.to_pylist(), table


def _parse_csv(file_bytes: bytes, delimiter: str, encoding: str) -> pa.Table:
    """Parse CSV bytes with PyArrow's CSV reader.

    PyArrow infers column types (int, float, string, bool, date) — no-magic
    violation requires types be inferred from data, not returned as all-string.
    """
    import pyarrow.csv as pacsv

    parse_opts = pacsv.ParseOptions(delimiter=delimiter)
    read_opts = pacsv.ReadOptions(encoding=encoding)
    return pacsv.read_csv(
        io.BytesIO(file_bytes), parse_options=parse_opts, read_options=read_opts
    )


def _parse_json(
    file_bytes: bytes,
    relpath: str,
) -> list[_JsonRow]:
    """Parse JSON or NDJSON bytes to list[dict].

    The parser is chosen by extension: ``.jsonl`` → NDJSON, ``.json`` → standard
    JSON.  The extension is validated at compile time, so only these two values
    are possible at runtime.

    Raises ValueError when the file cannot be parsed in the selected format.
    """
    import json

    if relpath.lower().endswith(".jsonl"):
        return _parse_ndjson(file_bytes)

    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"JSON file is not valid UTF-8: {e}") from e

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON file is not valid JSON: {e}") from e

    if isinstance(parsed, dict):
        return [parsed]
    if not isinstance(parsed, list):
        raise ValueError(
            f"JSON file must contain a top-level object or array of objects, "
            f"got: {type(parsed).__name__!r}."
        )
    return parsed


def _parse_ndjson(file_bytes: bytes) -> list[_JsonRow]:
    """Parse newline-delimited JSON (NDJSON) bytes to list[dict].

    Each non-empty line must be a JSON object ``{...}``.

    Raises ValueError on any line that is not a valid JSON object.
    """
    import json

    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"NDJSON file is not valid UTF-8: {e}") from e

    rows: list[_JsonRow] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"NDJSON line {lineno} is not valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(
                f"NDJSON line {lineno} must be a JSON object, "
                f"got: {type(obj).__name__!r}."
            )
        rows.append(obj)
    return rows


def _parse_parquet(file_bytes: bytes) -> pa.Table:
    """Parse Parquet bytes with PyArrow."""
    import pyarrow.parquet as pq

    return pq.read_table(io.BytesIO(file_bytes))  # type: ignore[no-untyped-call]  # type-state: type_ignore — pyarrow's stubs are placeholders; upstream gap
