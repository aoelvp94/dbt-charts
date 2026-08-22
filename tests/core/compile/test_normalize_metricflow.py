"""Seam tests for the metricflow query type: inference + normalize lowering to
SqlQuery via MetricFlow's own compiler, and the contract that no
MetricFlowAdapter is registered.

Covers the compile-time lowering seam.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest
import yaml

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.refs import infer_query_type_from_keys
from dbt_charts.core.compile.normalize.queries import normalize_query
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.project import Project

MANIFEST = {
    "semantic_models": [
        {
            "name": "orders",
            "node_relation": {
                "alias": "orders",
                "schema_name": "main",
                "relation_name": "main.orders",
            },
            "entities": [{"name": "order_id", "type": "primary", "expr": "order_id"}],
            "measures": [
                {
                    "name": "total_revenue",
                    "agg": "sum",
                    "expr": "revenue",
                    "agg_time_dimension": "order_date",
                }
            ],
            "dimensions": [
                {
                    "name": "order_date",
                    "type": "time",
                    "type_params": {"time_granularity": "day"},
                    "expr": "order_date",
                },
                {"name": "region", "type": "categorical", "expr": "region"},
            ],
        }
    ],
    "metrics": [
        {
            "name": "total_revenue",
            "type": "simple",
            "type_params": {"measure": {"name": "total_revenue"}},
        },
        {
            "name": "revenue_running_total",
            "type": "cumulative",
            "type_params": {"measure": {"name": "total_revenue"}},
        },
        {
            # Plain commuting derived metric — a ratio of two simple metrics.
            # dbt serializes the null offset fields explicitly (exclude_none is
            # off in its pydantic-v1 .json()), so they must NOT trip the guard.
            "name": "revenue_ratio",
            "type": "derived",
            "type_params": {
                "expr": "a / b",
                "metrics": [
                    {
                        "name": "total_revenue",
                        "alias": "a",
                        "filter": None,
                        "offset_window": None,
                        "offset_to_grain": None,
                    },
                    {
                        "name": "total_revenue",
                        "alias": "b",
                        "filter": None,
                        "offset_window": None,
                        "offset_to_grain": None,
                    },
                ],
            },
        },
        {
            # derived from a cumulative input (no offset of its own): still
            # non-commuting — the guard must catch this transitively.
            "name": "pct_of_running_total",
            "type": "derived",
            "type_params": {
                "expr": "total_revenue / revenue_running_total",
                "metrics": [
                    {
                        "name": "total_revenue",
                        "alias": None,
                        "filter": None,
                        "offset_window": None,
                        "offset_to_grain": None,
                    },
                    {
                        "name": "revenue_running_total",
                        "alias": None,
                        "filter": None,
                        "offset_window": None,
                        "offset_to_grain": None,
                    },
                ],
            },
        },
        {
            # derived with an offset_window on one input: month-over-month.
            "name": "revenue_mom",
            "type": "derived",
            "type_params": {
                "expr": "revenue / revenue_prev",
                "metrics": [
                    {
                        "name": "total_revenue",
                        "alias": "revenue",
                        "filter": None,
                        "offset_window": None,
                        "offset_to_grain": None,
                    },
                    {
                        "name": "total_revenue",
                        "alias": "revenue_prev",
                        "filter": None,
                        "offset_window": "1 month",
                        "offset_to_grain": None,
                    },
                ],
            },
        },
        {
            # derived with offset_to_grain (year-to-date) on a *simple* input:
            # the input still reads rows from a different period, so it does not
            # commute — the guard must catch the non-null shift value.
            "name": "ytd_revenue",
            "type": "derived",
            "type_params": {
                "expr": "revenue_ytd",
                "metrics": [
                    {
                        "name": "total_revenue",
                        "alias": "revenue_ytd",
                        "filter": None,
                        "offset_window": None,
                        "offset_to_grain": "year",
                    },
                ],
            },
        },
    ],
    "project_configuration": {
        "time_spine_table_configurations": [],
        "time_spines": [
            {
                "node_relation": {
                    "alias": "time_spine_day",
                    "schema_name": "main",
                    "relation_name": "main.time_spine_day",
                },
                "primary_column": {"name": "date_day", "time_granularity": "day"},
            }
        ],
    },
}


def _write_profiles_yml(project_dir: Path, db_path: Path) -> None:
    content = yaml.dump(
        {
            "test_project": {
                "target": "dev",
                "outputs": {"dev": {"type": "duckdb", "path": str(db_path)}},
            }
        }
    )
    (project_dir / "profiles.yml").write_text(content)


def _make_duckdb_file(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "CREATE TABLE orders (order_id INTEGER, order_date DATE, region VARCHAR, revenue DOUBLE)"
    )
    conn.execute(
        "INSERT INTO orders VALUES "
        "(1, '2024-01-05', 'east', 100.0), "
        "(2, '2024-01-20', 'west', 50.0), "
        "(3, '2024-02-10', 'east', 75.0)"
    )
    conn.close()


def _build_mf_project_dir(tmp_path: Path) -> Path:
    """Write dbt_charts.yml, dbt_project.yml, profiles.yml, and a seeded duckdb
    file for MetricFlow lowering. Does NOT write target/semantic_manifest.json
    — callers add that on disk (mf_project) or serve it via the project seam
    (mf_project_no_disk_manifest).
    """
    (tmp_path / "dbt_charts.yml").write_text(
        "name: test_project\n"
        "sources:\n"
        "  analytics:\n"
        "    type: dbt_profile\n"
        "    profile: test_project\n"
        "    target: dev\n"
    )
    (tmp_path / "dbt_project.yml").write_text(
        "name: test_project\nprofile: test_project\n"
    )
    db_path = tmp_path / "warehouse.duckdb"
    _make_duckdb_file(db_path)
    _write_profiles_yml(tmp_path, db_path)
    return tmp_path


@pytest.fixture
def mf_project(tmp_path: Path) -> Path:
    """A dbt project dir with profiles.yml, a seeded duckdb file, and a
    committed target/semantic_manifest.json.

    Returns the project root Path. Tests pass `local_project(mf_project).directory()`
    as `base_dir` to normalize_query — no chdir; the lowering resolves the dbt
    project via base_dir.project_root, not CWD.
    """
    _build_mf_project_dir(tmp_path)
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / "semantic_manifest.json").write_text(json.dumps(MANIFEST))
    return tmp_path


@pytest.fixture
def mf_project_no_disk_manifest(tmp_path: Path) -> Path:
    """Same as mf_project but omits target/semantic_manifest.json from disk.

    Proves MetricFlow lowering resolves the semantic manifest through the
    project seam ((base_dir / ...).exists()/.read_text()), not a raw
    dbt_project_path / Path built straight off the filesystem.
    """
    return _build_mf_project_dir(tmp_path)


def _sources() -> dict[str, dict[str, str]]:
    return {
        "analytics": {"type": "dbt_profile", "profile": "test_project", "target": "dev"}
    }


def test_infer_type_from_metrics_key() -> None:
    assert (
        infer_query_type_from_keys(
            {"metrics": ["total_revenue"], "source": "analytics"}
        )
        == "metricflow"
    )


def test_metricflow_query_lowers_to_sql_query_and_executes(
    mf_project: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    base_dir = local_project(mf_project).directory()
    query = normalize_query(
        "revenue",
        {
            "type": "metricflow",
            "metrics": ["total_revenue"],
            "time_grain": "month",
            "source": "analytics",
        },
        sources=_sources(),
        base_dir=base_dir,
    )
    assert isinstance(query, SqlQuery)
    assert query.source == "analytics"
    assert "total_revenue" in query.sql
    assert "metric_time__month" in query.sql

    registry = build_adapter_registry(local_project(mf_project), read_only=True)
    result = registry.execute(query)
    assert result.error is None, f"execute failed: {result.error}"
    totals = sorted(row["total_revenue"] for row in result.data)
    assert totals == [75.0, 150.0]


def test_metricflow_query_missing_metrics_raises(
    mf_project: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    base_dir = local_project(mf_project).directory()
    with pytest.raises(CompilationError, match="metrics"):
        normalize_query(
            "revenue",
            {"type": "metricflow", "source": "analytics"},
            sources=_sources(),
            base_dir=base_dir,
        )


def test_metricflow_query_scalar_metrics_raises(
    mf_project: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """metrics: 'revenue' (string, not list) must raise a clear CompilationError before
    reaching MetricFlow — not coerce or produce a confusing per-character error."""
    base_dir = local_project(mf_project).directory()
    with pytest.raises(CompilationError, match="metrics must be a non-empty list"):
        normalize_query(
            "revenue",
            {
                "type": "metricflow",
                "metrics": "total_revenue",
                "source": "analytics",
            },
            sources=_sources(),
            base_dir=base_dir,
        )


def test_metricflow_query_scalar_dimensions_raises(
    mf_project: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """dimensions: 'order_date' (string, not list) must raise CompilationError, not silently drop."""
    base_dir = local_project(mf_project).directory()
    with pytest.raises(CompilationError, match="dimensions must be a list"):
        normalize_query(
            "revenue",
            {
                "type": "metricflow",
                "metrics": ["total_revenue"],
                "dimensions": "order_date",
                "source": "analytics",
            },
            sources=_sources(),
            base_dir=base_dir,
        )


def test_metricflow_query_source_must_be_dbt_profile_type() -> None:
    sources = {"analytics": {"type": "duckdb", "path": ":memory:"}}
    with pytest.raises(CompilationError, match="not a dbt_profile source"):
        normalize_query(
            "revenue",
            {"type": "metricflow", "metrics": ["total_revenue"], "source": "analytics"},
            sources=sources,
        )


def test_metricflow_query_no_base_dir_raises() -> None:
    """No base_dir → clear CompilationError before any filesystem access."""
    with pytest.raises(CompilationError, match="no project directory context"):
        normalize_query(
            "revenue",
            {"type": "metricflow", "metrics": ["total_revenue"], "source": "analytics"},
            sources=_sources(),
            base_dir=None,
        )


def test_metricflow_query_no_dbt_project_raises(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """base_dir points to a project without dbt_project.yml -> clear CompilationError."""
    base_dir = local_project(tmp_path).directory()
    with pytest.raises(CompilationError, match="dbt project"):
        normalize_query(
            "revenue",
            {"type": "metricflow", "metrics": ["total_revenue"], "source": "analytics"},
            sources=_sources(),
            base_dir=base_dir,
        )


def test_metricflow_query_missing_manifest_raises(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """dbt project exists but `dbt parse` was never run -> clear CompilationError."""
    (tmp_path / "dbt_project.yml").write_text(
        "name: test_project\nprofile: test_project\n"
    )
    _write_profiles_yml(tmp_path, tmp_path / "warehouse.duckdb")
    base_dir = local_project(tmp_path).directory()
    with pytest.raises(CompilationError, match="dbt parse"):
        normalize_query(
            "revenue",
            {"type": "metricflow", "metrics": ["total_revenue"], "source": "analytics"},
            sources=_sources(),
            base_dir=base_dir,
        )


def test_metricflow_query_unknown_metric_raises_compilation_error(
    mf_project: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    base_dir = local_project(mf_project).directory()
    with pytest.raises(CompilationError, match="no_such_metric"):
        normalize_query(
            "revenue",
            {
                "type": "metricflow",
                "metrics": ["no_such_metric"],
                "source": "analytics",
            },
            sources=_sources(),
            base_dir=base_dir,
        )


def test_metricflow_query_filters_rejected_structurally() -> None:
    """filters: is not a metricflow field — Pydantic extra_forbidden at parse.

    The old normalize-time rejection is gone; the authored model itself has no
    filters field on any query family (a
    different, family-local field).
    """
    from pydantic import TypeAdapter, ValidationError

    from dbt_charts.core.compile.models.query.authored import AuthoredQuery

    with pytest.raises(ValidationError, match="filters"):
        TypeAdapter(AuthoredQuery).validate_python(
            {
                "type": "metricflow",
                "metrics": ["total_revenue"],
                "source": "analytics",
                "filters": {"region": "east"},
            }
        )


def test_metricflow_query_carries_limit_and_cache(
    mf_project: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """Authored limit/cache/description/ignore must survive lowering to SqlQuery."""
    base_dir = local_project(mf_project).directory()
    query = normalize_query(
        "revenue",
        {
            "type": "metricflow",
            "metrics": ["total_revenue"],
            "source": "analytics",
            "limit": 1,
            "description": "top line revenue",
            "cache": False,
        },
        sources=_sources(),
        base_dir=base_dir,
    )
    assert isinstance(query, SqlQuery)
    assert query.limit == 1
    assert query.description == "top line revenue"
    assert query.cache.enabled is False


def test_no_metricflow_adapter_registered(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    registry = build_adapter_registry(local_project(tmp_path), read_only=False)
    assert "metricflow" not in registry.supported_types


def test_metricflow_dbt_project_detected_via_project_seam_not_raw_path(
    tmp_path: Path,
    in_memory_project: Callable[[Path, dict[str, str]], Project],
) -> None:
    """dbt_project.yml detection must go through project.exists(), not a raw
    Path built off base_dir.project_root.

    tmp_path has no dbt_project.yml on disk — Project.root diverges from
    where the project's store actually reads. Only the InMemoryProject's
    in-memory dict has dbt_project.yml and the semantic manifest. The old
    raw-Path implementation (dbt_project_path_for(base_dir.project_root))
    walks Project.root on disk, finds nothing, and raises "no dbt project
    found" — wrong, since the store does have one. Detection must use
    base_dir.project.exists("dbt_project.yml") instead, so lowering proceeds
    past that check and fails later for the real reason (no local-filesystem
    edge to read the dbt profile from), not the divergent-root false negative.
    """
    project = in_memory_project(
        tmp_path,
        {
            "dbt_project.yml": "name: test_project\nprofile: test_project\n",
            "target/semantic_manifest.json": json.dumps(MANIFEST),
        },
    )
    base_dir = project.directory()

    with pytest.raises(CompilationError) as exc_info:
        normalize_query(
            "revenue",
            {
                "type": "metricflow",
                "metrics": ["total_revenue"],
                "source": "analytics",
            },
            sources=_sources(),
            base_dir=base_dir,
        )
    message = str(exc_info.value)
    assert "no dbt project found" not in message
    assert "filesystem" in message.lower()


class _ManifestOverrideProject(FilesystemProject):
    """FilesystemProject that also serves a few relpaths from an in-memory
    override instead of disk.

    Dbt-project detection now requires a real ``FilesystemProject`` edge (a
    non-filesystem host can't run MetricFlow-over-dbt at all), so the manifest
    seam test needs a double that still passes that isinstance check while
    proving target/semantic_manifest.json resolves via ``exists()``/
    ``read_text()``, not a raw disk path.
    """

    def __init__(self, root: Path, overrides: dict[str, str]) -> None:
        super().__init__(root)
        self._overrides = overrides

    def exists(self, relpath: str) -> bool:
        return relpath in self._overrides or super().exists(relpath)

    def read_text(self, relpath: str) -> str:
        if relpath in self._overrides:
            return self._overrides[relpath]
        return super().read_text(relpath)


def test_metricflow_manifest_reads_via_project_seam_not_raw_path(
    mf_project_no_disk_manifest: Path,
) -> None:
    """MetricFlow lowering must resolve target/semantic_manifest.json through
    (base_dir / ...).exists()/.read_text(), not dbt_project_path / Path.

    target/semantic_manifest.json is absent from disk (mf_project_no_disk_manifest);
    it's served only via the override. A raw-Path implementation finds
    nothing there and raises "no semantic manifest found".
    """
    project = _ManifestOverrideProject(
        mf_project_no_disk_manifest,
        {"target/semantic_manifest.json": json.dumps(MANIFEST)},
    )
    # base_dir anchored at the board's own directory (charts/), not project root —
    # target/ lives at the project root regardless of where the board sits, so
    # resolution must go through base_dir.project, not base_dir itself.
    base_dir = project.directory("charts")

    query = normalize_query(
        "revenue",
        {
            "type": "metricflow",
            "metrics": ["total_revenue"],
            "time_grain": "month",
            "source": "analytics",
        },
        sources=_sources(),
        base_dir=base_dir,
    )
    assert isinstance(query, SqlQuery)
    assert "total_revenue" in query.sql
    assert "metric_time__month" in query.sql


# ---------------------------------------------------------------------------
# where: predicates — bake literals, wrap variable predicates, error the rest
# ---------------------------------------------------------------------------


def _mf_query(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "metricflow",
        "metrics": ["total_revenue"],
        "dimensions": ["order_id__region"],
        "source": "analytics",
    }
    base.update(overrides)
    return base


class TestMetricflowWhere:
    def test_literal_where_bakes_and_filters(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A literal predicate bakes into the MetricFlow SQL and filters rows."""
        base_dir = local_project(mf_project).directory()
        query = normalize_query(
            "revenue",
            _mf_query(where=["order_id__region = 'east'"]),
            sources=_sources(),
            base_dir=base_dir,
        )
        assert isinstance(query, SqlQuery)
        assert "{{" not in query.sql
        registry = build_adapter_registry(local_project(mf_project), read_only=True)
        result = registry.execute(query)
        assert result.error is None, f"execute failed: {result.error}"
        assert [row["total_revenue"] for row in result.data] == [175.0]

    def test_literal_where_on_non_selected_dimension_bakes(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Literals work on dimensions NOT in the group-by — MetricFlow applies
        them pre-aggregation with semantic-graph awareness."""
        base_dir = local_project(mf_project).directory()
        query = normalize_query(
            "revenue",
            _mf_query(
                dimensions=[],
                time_grain="month",
                where=["order_id__region = 'east'"],
            ),
            sources=_sources(),
            base_dir=base_dir,
        )
        assert isinstance(query, SqlQuery)
        registry = build_adapter_registry(local_project(mf_project), read_only=True)
        result = registry.execute(query)
        assert result.error is None, f"execute failed: {result.error}"
        totals = sorted(row["total_revenue"] for row in result.data)
        assert totals == [75.0, 100.0]

    def test_variable_where_wraps_and_matches_baked_equivalent(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A {{ }} predicate on a selected dimension wraps the baked SQL; the
        result equals the literal-baked equivalent (the commutation pin)."""
        base_dir = local_project(mf_project).directory()
        wrapped = normalize_query(
            "revenue",
            _mf_query(where=["{{ filter('order_id__region', region_pick) }}"]),
            sources=_sources(),
            base_dir=base_dir,
        )
        assert isinstance(wrapped, SqlQuery)
        assert "{{ filter('order_id__region', region_pick) }}" in wrapped.sql
        assert "region_pick" in wrapped.variable_dependencies

        registry = build_adapter_registry(local_project(mf_project), read_only=True)
        wrapped_result = registry.execute(wrapped, variables={"region_pick": "east"})
        assert wrapped_result.error is None, f"execute failed: {wrapped_result.error}"

        baked = normalize_query(
            "revenue",
            _mf_query(where=["order_id__region = 'east'"]),
            sources=_sources(),
            base_dir=base_dir,
        )
        baked_result = registry.execute(baked)
        assert baked_result.error is None
        assert wrapped_result.data == baked_result.data

    def test_filter_helper_unset_variable_returns_all_rows(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """An unset picker via filter() means unfiltered (1=1), not an error."""
        base_dir = local_project(mf_project).directory()
        query = normalize_query(
            "revenue",
            _mf_query(where=["{{ filter('order_id__region', region_pick) }}"]),
            sources=_sources(),
            base_dir=base_dir,
        )
        assert isinstance(query, SqlQuery)
        assert "{{ filter(" in query.sql
        registry = build_adapter_registry(local_project(mf_project), read_only=True)
        result = registry.execute(query, variables={"region_pick": None})
        assert result.error is None, f"execute failed: {result.error}"
        totals = sorted(row["total_revenue"] for row in result.data)
        assert totals == [50.0, 175.0]

    def test_quote_bearing_value_binds_as_parameter(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A quote-bearing value must bind through parameters, not interpolation."""
        base_dir = local_project(mf_project).directory()
        query = normalize_query(
            "revenue",
            _mf_query(where=["{{ filter('order_id__region', region_pick) }}"]),
            sources=_sources(),
            base_dir=base_dir,
        )
        registry = build_adapter_registry(local_project(mf_project), read_only=True)
        result = registry.execute(query, variables={"region_pick": "ea'st"})
        assert result.error is None, f"execute failed: {result.error}"
        assert result.data == []

    def test_bare_variable_unset_errors_at_execute(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A bare {{ var }} predicate with the variable unset raises strictly —
        only filter() makes unset-means-unfiltered explicit."""
        base_dir = local_project(mf_project).directory()
        query = normalize_query(
            "revenue",
            _mf_query(where=["order_id__region = '{{ region_pick }}'"]),
            sources=_sources(),
            base_dir=base_dir,
        )
        from dbt_charts.core.compile.errors import JinjaError

        registry = build_adapter_registry(local_project(mf_project), read_only=True)
        with pytest.raises(JinjaError, match="region_pick"):
            registry.execute(query, variables={})

    def test_variable_where_on_non_selected_dimension_raises(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        base_dir = local_project(mf_project).directory()
        with pytest.raises(CompilationError, match="not a selected dimension"):
            normalize_query(
                "revenue",
                _mf_query(
                    dimensions=[],
                    time_grain="month",
                    where=["{{ filter('order_id__region', region_pick) }}"],
                ),
                sources=_sources(),
                base_dir=base_dir,
            )

    def test_variable_where_on_metric_raises(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        base_dir = local_project(mf_project).directory()
        with pytest.raises(CompilationError, match="not a selected dimension"):
            normalize_query(
                "revenue",
                _mf_query(where=["{{ filter('total_revenue', min_rev) }}"]),
                sources=_sources(),
                base_dir=base_dir,
            )

    def test_cumulative_metric_where_raises(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """Cumulative metrics don't commute — any where: is an error, baked or
        wrapped, because the two tiers would give different results."""
        base_dir = local_project(mf_project).directory()
        with pytest.raises(CompilationError, match="cumulative"):
            normalize_query(
                "revenue",
                _mf_query(
                    metrics=["revenue_running_total"],
                    where=["order_id__region = 'east'"],
                ),
                sources=_sources(),
                base_dir=base_dir,
            )

    def test_plain_derived_metric_where_allowed(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A derived metric that is a plain ratio of simple metrics commutes —
        the always-present null offset keys of a real manifest must NOT trip the
        guard. Regression pin for the value-vs-key-presence check."""
        base_dir = local_project(mf_project).directory()
        query = normalize_query(
            "revenue",
            _mf_query(
                metrics=["revenue_ratio"],
                where=["order_id__region = 'east'"],
            ),
            sources=_sources(),
            base_dir=base_dir,
        )
        assert isinstance(query, SqlQuery)

    def test_derived_of_cumulative_metric_where_raises(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A derived metric built on a cumulative input inherits non-commutation
        transitively (no offset of its own) — the guard must reject it too."""
        base_dir = local_project(mf_project).directory()
        with pytest.raises(CompilationError, match="derived from a cumulative"):
            normalize_query(
                "revenue",
                _mf_query(
                    metrics=["pct_of_running_total"],
                    where=["order_id__region = 'east'"],
                ),
                sources=_sources(),
                base_dir=base_dir,
            )

    def test_derived_offset_window_metric_where_raises(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A derived metric with an offset_window input (month-over-month) reads
        the prior period's rows — where: cannot be applied exactly."""
        base_dir = local_project(mf_project).directory()
        with pytest.raises(CompilationError, match="period offset"):
            normalize_query(
                "revenue",
                _mf_query(
                    metrics=["revenue_mom"],
                    where=["order_id__region = 'east'"],
                ),
                sources=_sources(),
                base_dir=base_dir,
            )

    def test_derived_offset_to_grain_metric_where_raises(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """A derived metric with an offset_to_grain input (year-to-date) shifts
        the period — the guard fails closed on the shift key, not just
        offset_window."""
        base_dir = local_project(mf_project).directory()
        with pytest.raises(CompilationError, match="period offset"):
            normalize_query(
                "revenue",
                _mf_query(
                    metrics=["ytd_revenue"],
                    where=["order_id__region = 'east'"],
                ),
                sources=_sources(),
                base_dir=base_dir,
            )

    def test_malformed_where_raises(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        base_dir = local_project(mf_project).directory()
        with pytest.raises(CompilationError, match="list of SQL predicate strings"):
            normalize_query(
                "revenue",
                _mf_query(where={"region": "east"}),
                sources=_sources(),
                base_dir=base_dir,
            )
        with pytest.raises(CompilationError, match="list of SQL predicate strings"):
            normalize_query(
                "revenue",
                _mf_query(where=[123]),
                sources=_sources(),
                base_dir=base_dir,
            )

    def test_where_carries_limit(
        self, mf_project: Path, local_project: Callable[..., FilesystemProject]
    ) -> None:
        """limit/cache/description survive lowering when a wrapper is added."""
        base_dir = local_project(mf_project).directory()
        query = normalize_query(
            "revenue",
            _mf_query(
                where=["{{ filter('order_id__region', region_pick) }}"],
                limit=1,
                cache=False,
                description="top-line revenue",
            ),
            sources=_sources(),
            base_dir=base_dir,
        )
        assert isinstance(query, SqlQuery)
        assert "{{ filter(" in query.sql
        assert query.limit == 1
        assert query.cache.enabled is False
        assert query.description == "top-line revenue"


def test_non_commuting_reason_rejects_unknown_metric_type() -> None:
    """A metric whose type we can't prove commutes is refused (fail-closed §4)."""
    from dbt_charts.core.compile.normalize.queries import _non_commuting_reason

    entries = {"weird": {"name": "weird", "type": "quantile_over_window"}}
    assert _non_commuting_reason("weird", entries, set()) is not None


def test_non_commuting_reason_allows_simple_and_ratio() -> None:
    """Simple and ratio metrics aggregate each group's own rows — they commute."""
    from dbt_charts.core.compile.normalize.queries import _non_commuting_reason

    entries = {
        "s": {"name": "s", "type": "simple"},
        "r": {"name": "r", "type": "ratio"},
    }
    assert _non_commuting_reason("s", entries, set()) is None
    assert _non_commuting_reason("r", entries, set()) is None


def test_non_commuting_reason_allows_derived_with_null_offset_keys() -> None:
    """Null offset keys (always serialized by dbt) must read as no shift."""
    from dbt_charts.core.compile.normalize.queries import _non_commuting_reason

    entries = {
        "s": {"name": "s", "type": "simple"},
        "d": {
            "name": "d",
            "type": "derived",
            "type_params": {
                "metrics": [
                    {"name": "s", "offset_window": None, "offset_to_grain": None}
                ]
            },
        },
    }
    assert _non_commuting_reason("d", entries, set()) is None


def test_non_commuting_reason_flags_offset_to_grain_value() -> None:
    """A non-null offset_to_grain value is a period shift → non-commuting."""
    from dbt_charts.core.compile.normalize.queries import _non_commuting_reason

    entries = {
        "s": {"name": "s", "type": "simple"},
        "d": {
            "name": "d",
            "type": "derived",
            "type_params": {
                "metrics": [
                    {"name": "s", "offset_window": None, "offset_to_grain": "year"}
                ]
            },
        },
    }
    assert _non_commuting_reason("d", entries, set()) == "derived with a period offset"
