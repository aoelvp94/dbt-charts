"""Chart-level `model:` sugar — MetricFlow path.

`model: <source>.<semantic_model>` on a chart with no `query:` desugars into a
synthesized named metricflow query, and the chart's bare channel fields are
classified against the dbt `semantic_manifest.json`: a metric name stays a
metric, a categorical dimension is entity-qualified (`region` ->
`order_id__region`), and `metric_time__<grain>` becomes the `time_grain`. This
the qualifier is a semantic model, and the role split comes from the dbt
semantic manifest.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest
import yaml

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.project import ProjectDirectory

from ..._paths import DBT_CHARTS_DIR
from .conftest import compile_with_board_sources

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
        }
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

SOURCES = """
sources:
  analytics:
    type: dbt_profile
    profile: test_project
    target: dev
"""


@pytest.fixture
def base_dir(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> ProjectDirectory:
    """A dbt project dir with dbt_charts.yml, dbt_project.yml, profiles.yml, a
    seeded duckdb file, and a committed target/semantic_manifest.json."""
    (tmp_path / "dbt_charts.yml").write_text("name: test_project\n")
    (tmp_path / "dbt_project.yml").write_text(
        "name: test_project\nprofile: test_project\n"
    )
    db_path = tmp_path / "warehouse.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "CREATE TABLE orders "
        "(order_id INTEGER, order_date DATE, region VARCHAR, revenue DOUBLE)"
    )
    conn.close()
    (tmp_path / "profiles.yml").write_text(
        yaml.dump(
            {
                "test_project": {
                    "target": "dev",
                    "outputs": {"dev": {"type": "duckdb", "path": str(db_path)}},
                }
            }
        )
    )
    target = tmp_path / "target"
    target.mkdir()
    (target / "semantic_manifest.json").write_text(json.dumps(MANIFEST))
    return local_project(tmp_path).directory()


def test_model_sugar_lowers_to_same_sql_as_explicit_query(
    base_dir: ProjectDirectory,
) -> None:
    """A `model: source.semantic_model` chart with bare channel fields lowers to
    the same SqlQuery as the explicit `query: {metrics, dimensions, time_grain}`
    form, and the channels resolve to the same MetricFlow group-by names."""
    explicit_yaml = (
        SOURCES
        + """
queries:
  revenue:
    source: analytics
    metrics: [total_revenue]
    dimensions: [order_id__region]
    time_grain: month
charts:
  hero:
    type: bar
    query: revenue
    x: metric_time__month
    y: total_revenue
    color: order_id__region
rows:
  - hero
"""
    )
    model_yaml = (
        SOURCES
        + """
charts:
  hero:
    type: bar
    model: analytics.orders
    x: metric_time__month
    y: total_revenue
    color: region
rows:
  - hero
"""
    )
    explicit_result = compile_with_board_sources(explicit_yaml, base_dir=base_dir)
    model_result = compile_with_board_sources(model_yaml, base_dir=base_dir)

    assert explicit_result.success, [str(e) for e in explicit_result.errors]
    assert model_result.success, [str(e) for e in model_result.errors]

    explicit_board = explicit_result.board
    model_board = model_result.board
    assert explicit_board is not None
    assert model_board is not None

    (explicit_query,) = explicit_board.queries.values()
    (model_query,) = model_board.queries.values()
    assert isinstance(explicit_query, SqlQuery)
    assert isinstance(model_query, SqlQuery)
    assert explicit_query.sql == model_query.sql
    assert model_query.source == "analytics"

    # Manifest-driven role inference: bare `region` becomes the entity-qualified
    # `order_id__region`, matching the explicit form's dimension name.
    assert model_board.charts["hero"].x == explicit_board.charts["hero"].x
    assert model_board.charts["hero"].y == explicit_board.charts["hero"].y
    assert model_board.charts["hero"].color == explicit_board.charts["hero"].color
    assert model_board.charts["hero"].color == "order_id__region"


def test_model_entity_channel_is_grouped_bare(base_dir: ProjectDirectory) -> None:
    """A channel naming an entity (`order_id`) groups by the bare entity name —
    MetricFlow references entities un-qualified, unlike categorical dimensions."""
    model_yaml = (
        SOURCES
        + """
charts:
  hero:
    type: bar
    model: analytics.orders
    x: order_id
    y: total_revenue
rows:
  - hero
"""
    )
    result = compile_with_board_sources(model_yaml, base_dir=base_dir)
    assert result.success, [str(e) for e in result.errors]
    assert result.board is not None
    assert result.board.charts["hero"].x == "order_id"


def test_model_and_query_both_set_raises(base_dir: ProjectDirectory) -> None:
    model_yaml = (
        SOURCES
        + """
queries:
  revenue:
    source: analytics
    metrics: [total_revenue]
charts:
  hero:
    type: bar
    query: revenue
    model: analytics.orders
    y: total_revenue
rows:
  - hero
"""
    )
    result = compile_with_board_sources(model_yaml, base_dir=base_dir)
    assert not result.success
    assert any("model" in e.message and "query" in e.message for e in result.errors)


def test_model_unknown_semantic_model_raises(base_dir: ProjectDirectory) -> None:
    """`model: analytics.nope` names a real dbt_profile source but a semantic
    model absent from the manifest — must raise, not silently drop."""
    model_yaml = (
        SOURCES
        + """
charts:
  hero:
    type: bar
    model: analytics.nope
    y: total_revenue
rows:
  - hero
"""
    )
    result = compile_with_board_sources(model_yaml, base_dir=base_dir)
    assert not result.success
    assert any("nope" in e.message for e in result.errors)


def test_model_unknown_channel_field_raises(base_dir: ProjectDirectory) -> None:
    """A channel field that is neither a metric, a dimension, nor metric_time in
    the manifest must raise a clear error (validate-and-error, no silent drop)."""
    model_yaml = (
        SOURCES
        + """
charts:
  hero:
    type: bar
    model: analytics.orders
    x: metric_time__month
    y: total_revenue
    color: not_a_field
rows:
  - hero
"""
    )
    result = compile_with_board_sources(model_yaml, base_dir=base_dir)
    assert not result.success
    assert any("not_a_field" in e.message for e in result.errors)


def test_model_time_dimension_without_grain_raises(base_dir: ProjectDirectory) -> None:
    """A bare time reference needs an explicit grain; the manifest can't guess one."""
    model_yaml = (
        SOURCES
        + """
charts:
  hero:
    type: bar
    model: analytics.orders
    x: metric_time
    y: total_revenue
rows:
  - hero
"""
    )
    result = compile_with_board_sources(model_yaml, base_dir=base_dir)
    assert not result.success
    assert any("grain" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# Fusion-emitted semantic_manifest.json — real output, not the hand-built
# MANIFEST dict above.
#
# `dbt-charts/tests/fixtures/fusion_manifest/semantic_manifest.json` is
# `dbt-fusion 2.0.0-preview.193`'s real `target/semantic_manifest.json` for
# a project with NO semantic models declared at all (jaffle_shop_duckdb).
# It confirms `_read_semantic_manifest`/`_build_model_view` handle a present-
# but-empty Fusion semantic manifest without a magic fallback.
#
# Separately — and this is the load-bearing finding, not a code gap — Fusion
# 2.0.0-preview.193 does not emit `target/semantic_manifest.json` *at all*
# for a project that declares semantic models using today's standard
# dbt-Core `semantic_models:`/`metrics:` YAML (verified against the
# `jaffle-shop` project, which defines several): it logs `SemanticModelDeprecated
# (dbt1157)` ("defines semantic models and metrics using the legacy YAML")
# and skips semantic-manifest generation entirely, even once every other
# parse error in that project is fixed. `model:` chart sugar and `metricflow:`
# queries are consequently unusable against a Fusion-parsed manifest today for
# any project written in the current dbt-Core semantic-layer YAML — see the
# task worksheet's divergence table. Both code paths already fail loudly
# (`CompilationError`) when the file is absent, so no dataface fix applies;
# this is Fusion's current output, not a parsing bug.
# ---------------------------------------------------------------------------

_FUSION_EMPTY_SEMANTIC_MANIFEST = (
    DBT_CHARTS_DIR / "tests" / "fixtures" / "fusion_manifest" / "semantic_manifest.json"
).read_text()


@pytest.fixture
def fusion_base_dir(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> ProjectDirectory:
    """Same project shape as `base_dir`, but `target/semantic_manifest.json`
    is the real (empty) Fusion output instead of the hand-built MANIFEST."""
    (tmp_path / "dbt_charts.yml").write_text("name: test_project\n")
    target = tmp_path / "target"
    target.mkdir()
    (target / "semantic_manifest.json").write_text(_FUSION_EMPTY_SEMANTIC_MANIFEST)
    return local_project(tmp_path).directory()


def test_model_sugar_raises_against_real_fusion_manifest_without_semantic_models(
    fusion_base_dir: ProjectDirectory,
) -> None:
    """A Fusion manifest with no semantic models is honestly empty, not
    malformed — `model:` sugar must raise the same clear error as an
    unknown semantic model name, never resolve silently to nothing."""
    model_yaml = (
        SOURCES
        + """
charts:
  hero:
    type: bar
    model: analytics.orders
    y: total_revenue
rows:
  - hero
"""
    )
    result = compile_with_board_sources(model_yaml, base_dir=fusion_base_dir)
    assert not result.success
    assert any(
        "orders" in e.message and "target/semantic_manifest.json" in e.message
        for e in result.errors
    )
