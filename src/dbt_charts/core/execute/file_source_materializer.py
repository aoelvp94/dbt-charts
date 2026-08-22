"""FileSourceMaterializer — load file sources into any QueryResultCache backend.

Stage: EXECUTE
Purpose: Parse CSV/JSON/Parquet files (via PyArrow, no DuckDB filesystem access)
into rows, store in a QueryResultCache via put(), and register a SQL view per
table name so author SQL like ``SELECT * FROM sales`` works against the cache engine.

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

from dbt_charts.core.compile.config import get_execution_config
from dbt_charts.core.compile.models.source import (
    CsvSourceConfig,
    JsonSourceConfig,
    ParquetSourceConfig,
)
from dbt_charts.core.compile.template.parameterized import render_parameterized
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.diagnostics.codes_execute import (
    ERR_GLOB_EMPTY,
    ERR_GLOB_SCHEMA_MISMATCH,
    ERR_GLOB_TOO_MANY,
)
from dbt_charts.core.execute.cache_backend import FILE_SOURCE_VARS_HASH, CacheHit
from dbt_charts.core.execute.duckdb_cache import compute_source_hash
from dbt_charts.core.project import is_glob

if TYPE_CHECKING:
    from dbt_charts.core.execute.cache_backend import QueryResultCache
    from dbt_charts.core.project import Project

# JSON files carry runtime-dynamic column schemas; Any is the correct boundary type.
_JsonRow: TypeAlias = dict[str, Any]

logger = logging.getLogger(__name__)


def default_local_materializer_factory(
    project: Project,
) -> Callable[[], FileSourceMaterializer]:
    """A factory that lazily builds the local DuckDB-backed file materializer.

    Handed to ``Executor(file_materializer_factory=...)`` for local ``dct`` so the
    per-render materializer (and its in-memory DuckDB) is created only when a
    file-source query actually misses the result cache — a fully-cached dashboard
    never opens one. Cloud injects its own Postgres-backed materializer instead.
    """

    def _build() -> FileSourceMaterializer:
        from dbt_charts.core.execute.trivial_local_cache import TrivialDuckDBCache

        return FileSourceMaterializer(project, TrivialDuckDBCache())

    return _build


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
        project: The Dataface project (for resolving file paths and reading bytes).
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

    def materialize_and_run(
        self,
        source: CsvSourceConfig | JsonSourceConfig | ParquetSourceConfig,
        sql: str,
        variables: dict[str, Any],
        source_name: str,
    ) -> list[_JsonRow]:
        """Ensure all tables in *source* are in the cache, then execute *sql*.

        Glob patterns (``*`` / ``?``) in ``source.files`` values are expanded via
        ``project.files.glob()``.  Each glob must match at least one file and may
        not exceed ``execution.max_glob_file_count``.  All matched files are loaded
        and their rows concatenated into one table.

        Args:
            source: A CsvSourceConfig, JsonSourceConfig, or ParquetSourceConfig.
            sql: SQL template (may contain {{ variable }} Jinja expressions).
            variables: Variable values substituted into *sql* via render_parameterized.
            source_name: Authored source name (for error messages).

        Returns:
            Rows returned by *sql*.

        Raises:
            DbtChartsError: Empty glob match or fan-out cap exceeded.
            RuntimeError: If SQL execution fails (propagated from execute_file_source_sql,
                includes external-access violations in author SQL).
        """
        source_hash = compute_source_hash(source)
        cap = get_execution_config().max_glob_file_count

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

        # Render {{ variable }} templates to parameterized SQL before executing.
        # profile_type="duckdb" → $1/$2/… placeholders (DuckDB positional style).
        parameterized = render_parameterized(sql, variables, profile_type="duckdb")

        union_by_name = isinstance(source, JsonSourceConfig) and source.union_by_name

        with self._lock:
            for table_name, vkey, relpaths in table_specs:
                # Cache miss → read + parse + store. A hit never opens any file.
                if not isinstance(
                    self._cache.get(source_hash, vkey, FILE_SOURCE_VARS_HASH), CacheHit
                ):
                    rows: list[_JsonRow] = []
                    first_relpath = ""
                    first_keys: frozenset[str] = frozenset()
                    for relpath in relpaths:
                        file_rows = _parse(
                            source, self._project.read_bytes(relpath), relpath
                        )
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
                    if union_by_name and rows:
                        # Union of column names in first-seen insertion order so
                        # the created table's column order is deterministic across
                        # processes (a set would vary under hash randomisation).
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
                    self._cache.put(
                        source_hash,
                        vkey,
                        FILE_SOURCE_VARS_HASH,
                        rows,
                        board_slug="__file_source__",
                        query_name=table_name,
                    )

                # Register (or re-register) so SQL can reference the table name.
                # For DuckDB: creates/replaces a VIEW pointing at the _r_<hash> table.
                # For Postgres: records the mapping for execute_file_source_sql to load.
                self._cache.register_file_table(table_name, source_hash, vkey)

            return self._cache.execute_file_source_sql(
                parameterized.sql, parameterized.params
            )


# ── Module-level parse helpers (no DuckDB filesystem access) ─────────────────


def _parse(
    source: CsvSourceConfig | JsonSourceConfig | ParquetSourceConfig,
    file_bytes: bytes,
    relpath: str,
) -> list[_JsonRow]:
    """Dispatch to the correct parser for the given source type."""
    if isinstance(source, CsvSourceConfig):
        return _parse_csv(file_bytes, source.delimiter, source.encoding)
    if isinstance(source, JsonSourceConfig):
        return _parse_json(file_bytes, relpath)
    return _parse_parquet(file_bytes)


def _parse_csv(file_bytes: bytes, delimiter: str, encoding: str) -> list[_JsonRow]:
    """Parse CSV bytes to list[dict] using PyArrow's CSV reader.

    PyArrow infers column types (int, float, string, bool) — no-magic violation
    requires types be inferred from data, not returned as all-string.
    """
    import pyarrow.csv as pacsv

    parse_opts = pacsv.ParseOptions(delimiter=delimiter)
    read_opts = pacsv.ReadOptions(encoding=encoding)
    table = pacsv.read_csv(
        io.BytesIO(file_bytes), parse_options=parse_opts, read_options=read_opts
    )
    return table.to_pylist()


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


def _parse_parquet(file_bytes: bytes) -> list[_JsonRow]:
    """Parse Parquet bytes to list[dict] using PyArrow."""
    import pyarrow.parquet as pq

    table = pq.read_table(io.BytesIO(file_bytes))  # type: ignore[no-untyped-call]
    return table.to_pylist()
