"""Tests for core/dbt_model_columns.py — static model output columns from the manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile import compile as compile_board
from dbt_charts.core.compile.config import ProjectSourcesConfig
from dbt_charts.core.dbt_manifest import LoadedManifest, load_manifest
from dbt_charts.core.dbt_model_columns import (
    check_model_columns,
    resolve_model_output_columns,
)


def _project_with_manifest(tmp_path: Path, nodes: dict) -> FilesystemProject:
    (tmp_path / "dbt_charts.yml").write_text("name: p\n")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text(
        json.dumps({"metadata": {"adapter_type": "postgres"}, "nodes": nodes})
    )
    return FilesystemProject(tmp_path)


def _model(name: str, sql: str, resource_type: str = "model") -> dict:
    return {
        "resource_type": resource_type,
        "name": name,
        "schema": "main",
        "raw_code": sql,
    }


def _compile(sql: str):
    result = compile_board(
        yaml.dump(
            {
                "source": "s",
                "queries": {"q": sql},
                "charts": {"c": {"query": "q", "type": "table"}},
                "rows": ["c"],
            }
        )
    )
    assert result.board is not None, result.errors
    return result


class TestResolveModelOutputColumns:
    def test_explicit_projections_resolve(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.orders": _model(
                    "orders", "SELECT id AS user_id, amount FROM raw"
                )
            },
        )
        loaded = load_manifest(project)
        assert loaded is not None
        resolved = resolve_model_output_columns(loaded)
        assert resolved["orders"].columns == {"user_id", "amount"}
        assert resolved["orders"].unresolved is None

    def test_jinja_in_the_model_body_still_resolves_projections(self, tmp_path):
        sql = "SELECT customer_id FROM {{ ref('stg_orders') }} WHERE d > '{{ var(\"day\") }}'"
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"customer_id"}

    def test_select_star_is_unresolved_never_guessed(self, tmp_path):
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", "SELECT * FROM raw")}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None

    def test_macro_in_projection_position_is_unresolved(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.orders": _model(
                    "orders", "SELECT {{ dbt_utils.star(ref('x')) }} FROM raw"
                )
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None

    def test_seeds_are_always_unresolved_even_when_partially_documented(self, tmp_path):
        """Manifest seed `columns` hold only what someone documented, not the
        CSV header — a complete claim built on it hard-fails boards reading
        the undocumented columns."""
        node = _model("customers", "", resource_type="seed")
        node["columns"] = {"code": {}, "name": {}}
        project = _project_with_manifest(tmp_path, {"seed.p.customers": node})
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["customers"].unresolved is not None

    def test_config_header_does_not_defeat_resolution(self, tmp_path):
        """`{{ config(materialized='table') }}` heads most real models; its
        skeleton placeholder must not turn every one of them unresolved."""
        sql = "{{ config(materialized='table') }}\nSELECT product_id, amount FROM raw"
        project = _project_with_manifest(
            tmp_path, {"model.p.sales": _model("sales", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["sales"].columns == {"product_id", "amount"}
        assert resolved["sales"].unresolved is None

    def test_disagreeing_jinja_branches_are_unresolved(self, tmp_path):
        sql = (
            "{% if var('x') %} SELECT order_id, customer_id FROM raw "
            "{% else %} SELECT order_id, customer_hash FROM raw {% endif %}"
        )
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None
        assert "branches" in resolved["orders"].unresolved

    def test_agreeing_jinja_branches_resolve(self, tmp_path):
        sql = (
            "{% if var('x') %} SELECT order_id FROM raw_a "
            "{% else %} SELECT order_id FROM raw_b {% endif %}"
        )
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"order_id"}

    def test_templated_projection_suffix_is_unresolved(self, tmp_path):
        sql = "SELECT id, amount_{{ var('currency') }} FROM raw"
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None

    def test_snapshots_are_unresolved_because_dbt_injects_meta_columns(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {
                "snapshot.p.s1": _model(
                    "s1", "SELECT id FROM raw", resource_type="snapshot"
                )
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["s1"].unresolved is not None


class TestCheckModelColumns:
    def test_column_renamed_in_the_model_but_not_yet_built_fails(self, tmp_path):
        """THE drift case: the model file now says user_id, the warehouse still
        has customer_id, and a board referencing customer_id must fail at
        validate time — today this passes green until `dbt run`."""
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.orders": _model(
                    "orders", "SELECT id AS user_id, amount FROM raw"
                )
            },
        )
        result = _compile("SELECT customer_id FROM {{ ref('orders') }}")
        check_model_columns(result, project)
        codes = [e.code for e in result.errors]
        assert "ERR-DBT-MODEL-COLUMN-MISSING" in codes
        msg = next(e for e in result.errors if e.code == "ERR-DBT-MODEL-COLUMN-MISSING")
        assert "customer_id" in msg.message
        assert "orders" in msg.message
        assert "user_id" in (msg.hint or "")

    def test_matching_column_passes_clean(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {"model.p.orders": _model("orders", "SELECT customer_id, amount FROM raw")},
        )
        result = _compile("SELECT customer_id FROM {{ ref('orders') }}")
        check_model_columns(result, project)
        assert result.errors == []
        assert result.warnings == []

    def test_case_differences_are_not_drift(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {"model.p.orders": _model("orders", "SELECT CUSTOMER_ID FROM raw")},
        )
        result = _compile("SELECT customer_id FROM {{ ref('orders') }}")
        check_model_columns(result, project)
        assert result.errors == []

    def test_unresolved_model_warns_never_errors_or_passes_silently(self, tmp_path):
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", "SELECT * FROM raw")}
        )
        result = _compile("SELECT customer_id FROM {{ ref('orders') }}")
        check_model_columns(result, project)
        assert result.errors == []
        assert [w.code for w in result.warnings] == [
            "WARN-DBT-MODEL-COLUMNS-UNRESOLVED"
        ]

    def test_bare_name_collision_with_a_model_makes_no_claim(self, tmp_path):
        """A literal `FROM orders` may be a same-named relation on a different
        source; only ref() provenance is evidence the query reads the model."""
        project = _project_with_manifest(
            tmp_path,
            {"model.p.orders": _model("orders", "SELECT id AS user_id FROM raw")},
        )
        result = _compile("SELECT customer_id FROM orders")
        check_model_columns(result, project)
        assert result.errors == []
        assert result.warnings == []

    def test_corrupt_manifest_is_reported_not_swallowed(self, tmp_path):
        """check_manifest_refs only loads the manifest when a query carries a
        ref() call — a bare-table board with a corrupt manifest would
        otherwise validate clean."""
        (tmp_path / "dbt_charts.yml").write_text("name: p\n")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "manifest.json").write_text("{not json")
        project = FilesystemProject(tmp_path)
        result = _compile("SELECT customer_id FROM {{ ref('orders') }}")
        check_model_columns(result, project)
        assert [e.code for e in result.errors] == ["ERR-DBT-MANIFEST-UNREADABLE"]

    def test_snowflake_casing_does_not_dodge_the_model_lookup(self, tmp_path):
        """Snowflake's qualify uppercases table identifiers; the model lookup
        must still find the lowercase manifest node."""
        nodes = {"model.p.orders": _model("orders", "SELECT id AS user_id FROM raw")}
        (tmp_path / "dbt_charts.yml").write_text("name: p\n")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "manifest.json").write_text(
            json.dumps({"metadata": {"adapter_type": "snowflake"}, "nodes": nodes})
        )
        project = FilesystemProject(tmp_path)
        result = compile_board(
            yaml.dump(
                {
                    "source": "s",
                    "queries": {"q": "SELECT customer_id FROM {{ ref('orders') }}"},
                    "charts": {"c": {"query": "q", "type": "table"}},
                    "rows": ["c"],
                }
            ),
            project_sources=ProjectSourcesConfig(
                sources={
                    "s": {
                        "type": "snowflake",
                        "account": "a",
                        "user": "u",
                        "password": "p",
                        "database": "d",
                    }
                }
            ),
        )
        assert result.board is not None, result.errors
        check_model_columns(result, project)
        assert "ERR-DBT-MODEL-COLUMN-MISSING" in [e.code for e in result.errors]

    def test_a_table_that_is_not_a_dbt_model_makes_no_claim(self, tmp_path):
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", "SELECT a FROM raw")}
        )
        result = _compile("SELECT anything FROM warehouse_native_view")
        check_model_columns(result, project)
        assert result.errors == []
        assert result.warnings == []

    def test_a_board_that_failed_compile_is_a_no_op(self, tmp_path):
        """A failed compile has no query registry; its compile errors are the
        report — this check must not raise past them."""
        project = _project_with_manifest(
            tmp_path,
            {"model.p.orders": _model("orders", "SELECT id FROM raw")},
        )
        result = compile_board("title: X\nrows:\n  - nope\n")
        assert result.board is None
        before = list(result.errors)
        check_model_columns(result, project)
        assert result.errors == before

    def test_no_manifest_is_a_no_op(self, tmp_path):
        (tmp_path / "dbt_charts.yml").write_text("name: p\n")
        project = FilesystemProject(tmp_path)
        result = _compile("SELECT customer_id FROM orders")
        check_model_columns(result, project)
        assert result.errors == []
        assert result.warnings == []


class TestMemoAndManifestIdentity:
    def test_memo_hits_on_relpath_and_version_not_object_identity(self, tmp_path):
        """Two loads of the same manifest version must share one derivation;
        an id()-keyed memo misses (and can collide after GC reuses the id)."""
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", "SELECT id FROM raw")}
        )
        raw = json.loads((tmp_path / "target" / "manifest.json").read_text())
        a = LoadedManifest(
            raw=raw,
            relpath="target/manifest.json",
            version=project.file_version("target/manifest.json"),
        )
        b = LoadedManifest(
            raw=json.loads(json.dumps(raw)),
            relpath="target/manifest.json",
            version=a.version,
        )
        assert resolve_model_output_columns(a) is resolve_model_output_columns(b)

    def test_a_new_manifest_version_is_rederived(self, tmp_path):
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", "SELECT id FROM raw")}
        )
        assert resolve_model_output_columns(load_manifest(project))[
            "orders"
        ].columns == {"id"}
        manifest_path = tmp_path / "target" / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "metadata": {"adapter_type": "postgres"},
                    "nodes": {
                        "model.p.orders": _model("orders", "SELECT id2 FROM raw")
                    },
                }
            )
        )
        assert resolve_model_output_columns(load_manifest(project))[
            "orders"
        ].columns == {"id2"}


class TestDuplicateModelNames:
    def test_two_nodes_sharing_a_lowercased_name_are_unresolved(self, tmp_path):
        """Cross-package name collisions must not silently last-win — either
        node's columns would be a guess about which relation the ref meant."""
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.orders": _model("orders", "SELECT id FROM raw"),
                "model.other.Orders": _model("Orders", "SELECT amount FROM raw2"),
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None
        assert "share" in resolved["orders"].unresolved


class TestJinjaHeaderStripping:
    def test_config_header_with_nested_jinja_is_stripped(self, tmp_path):
        sql = (
            '{{ config(materialized="table", post_hook="{{ grant_select(this) }}") }}\n'
            "SELECT id, amount FROM raw"
        )
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"id", "amount"}

    def test_leading_jinja_comment_and_sql_comment_are_stripped(self, tmp_path):
        sql = (
            "{# owner: data-eng #}\n"
            "-- staging model\n"
            "{{ config(materialized='view') }}\n"
            "SELECT id FROM raw"
        )
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"id"}


def test_missing_column_error_suggests_the_close_name(tmp_path):
    project = _project_with_manifest(
        tmp_path,
        {"model.p.orders": _model("orders", "SELECT id, amount_usd FROM raw")},
    )
    result = _compile("SELECT amount FROM {{ ref('orders') }}")
    check_model_columns(result, project)
    (error,) = result.errors
    assert error.hint is not None
    assert "amount_usd" in error.hint


class TestCompiledCodePreference:
    def test_compiled_code_is_preferred_over_raw_code(self, tmp_path):
        """A compiled manifest carries jinja-rendered SQL — a model unresolved
        under raw_code must resolve from compiled_code."""
        node = _model("orders", "SELECT {{ dbt_utils.star(ref('x')) }} FROM raw")
        node["compiled_code"] = "SELECT id, amount FROM analytics.raw"
        project = _project_with_manifest(tmp_path, {"model.p.orders": node})
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"id", "amount"}
        assert resolved["orders"].unresolved is None


class TestRealWorldHeaders:
    def test_config_header_with_dict_literal_is_stripped(self, tmp_path):
        """meta={...} / grants={...} put lone braces inside the call — the
        header strip must cross them."""
        sql = (
            "{{ config(materialized='table', meta={'owner': 'data-eng'}) }}\n"
            "SELECT id, amount FROM raw"
        )
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"id", "amount"}
        assert resolved["orders"].unresolved is None

    def test_leading_set_statement_is_stripped(self, tmp_path):
        sql = "{% set label = 'net' %}\nSELECT id FROM raw"
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"id"}
        assert resolved["orders"].unresolved is None


class TestUnionModels:
    def test_union_takes_columns_from_the_first_arm(self, tmp_path):
        sql = "SELECT id, amount FROM a UNION ALL SELECT id, amount FROM b"
        project = _project_with_manifest(
            tmp_path, {"model.p.orders": _model("orders", sql)}
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"id", "amount"}


def test_setup_sql_ref_provenance_is_checked(tmp_path):
    """A ref() reached only through setup_sql still carries provenance — a
    column drift behind a temp view must not be silently unchecked."""
    project = _project_with_manifest(
        tmp_path,
        {"model.p.orders": _model("orders", "SELECT id FROM raw")},
    )
    result = compile_board(
        yaml.dump(
            {
                "source": "s",
                "queries": {
                    "q": {
                        "setup_sql": (
                            "CREATE TEMP VIEW v AS "
                            "SELECT wrong_col FROM {{ ref('orders') }}"
                        ),
                        "sql": "SELECT wrong_col FROM v",
                    }
                },
                "charts": {"c": {"query": "q", "type": "table"}},
                "rows": ["c"],
            }
        )
    )
    assert result.board is not None, result.errors
    check_model_columns(result, project)
    codes = [e.code for e in result.errors]
    assert "ERR-DBT-MODEL-COLUMN-MISSING" in codes


def test_unresolved_warning_names_every_affected_query(tmp_path):
    """Two queries reading the same unresolved model each get their warning —
    the dedupe must not under-report the blast radius."""
    project = _project_with_manifest(
        tmp_path,
        {"model.p.orders": _model("orders", "SELECT * FROM raw")},
    )
    result = compile_board(
        yaml.dump(
            {
                "source": "s",
                "queries": {
                    "a": "SELECT x FROM {{ ref('orders') }}",
                    "b": "SELECT y FROM {{ ref('orders') }}",
                },
                "charts": {
                    "c1": {"query": "a", "type": "table"},
                    "c2": {"query": "b", "type": "table"},
                },
                "rows": ["c1", "c2"],
            }
        )
    )
    assert result.board is not None, result.errors
    check_model_columns(result, project)
    warnings = [
        w for w in result.warnings if w.code == "WARN-DBT-MODEL-COLUMNS-UNRESOLVED"
    ]
    named = {w.message.split("'")[1] for w in warnings}
    assert named == {"a", "b"}


def test_missing_column_error_carries_the_query_name(tmp_path):
    """The execute domain's field spelling is query_name — the diagnostic's
    query attribution must not be silently null."""
    project = _project_with_manifest(
        tmp_path,
        {"model.p.orders": _model("orders", "SELECT id FROM raw")},
    )
    result = _compile("SELECT missing FROM {{ ref('orders') }}")
    check_model_columns(result, project)
    (error,) = result.errors
    assert error.query == "q"


def test_corrupt_manifest_is_reported_even_without_dbt_refs(tmp_path):
    """Deliberate widening: a half-written manifest is a real fault at a real
    location, reported even when no query carries a ref()."""
    (tmp_path / "dbt_charts.yml").write_text("name: p\n")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text("{not json")
    project = FilesystemProject(tmp_path)
    result = _compile("SELECT a FROM plain_table")
    check_model_columns(result, project)
    codes = [e.code for e in result.errors]
    assert "ERR-DBT-MANIFEST-UNREADABLE" in codes


def test_unreadable_manifest_error_is_not_duplicated(tmp_path):
    (tmp_path / "dbt_charts.yml").write_text("name: p\n")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text("{not json")
    project = FilesystemProject(tmp_path)
    result = _compile("SELECT a FROM plain_table")
    check_model_columns(result, project)
    check_model_columns(result, project)
    codes = [e.code for e in result.errors]
    assert codes.count("ERR-DBT-MANIFEST-UNREADABLE") == 1


class TestIndeterminateQueries:
    def test_an_indeterminate_dbt_query_warns_never_passes_silently(self, tmp_path):
        """SELECT * FROM {{ ref(...) }} cannot be checked — the honesty
        contract demands a warning naming the query and the reason, not a
        silent green."""
        project = _project_with_manifest(
            tmp_path,
            {"model.p.orders": _model("orders", "SELECT id FROM raw")},
        )
        result = _compile("SELECT * FROM {{ ref('orders') }}")
        check_model_columns(result, project)
        assert result.errors == []
        (warning,) = [
            w
            for w in result.warnings
            if w.code == "WARN-DBT-QUERY-COLUMNS-INDETERMINATE"
        ]
        assert warning.query == "q"
        assert "*" in warning.message

    def test_a_plain_sql_query_without_dbt_calls_is_out_of_charter(self, tmp_path):
        """A SELECT * against a raw relation makes no dbt claim — the SQL lint
        tiers own it, not the model-column check."""
        project = _project_with_manifest(
            tmp_path,
            {"model.p.orders": _model("orders", "SELECT id FROM raw")},
        )
        result = _compile("SELECT * FROM warehouse_native_view")
        check_model_columns(result, project)
        assert result.errors == []
        assert result.warnings == []


def test_warnings_carry_structured_query_attribution(tmp_path):
    project = _project_with_manifest(
        tmp_path,
        {"model.p.orders": _model("orders", "SELECT * FROM raw")},
    )
    result = _compile("SELECT x FROM {{ ref('orders') }}")
    check_model_columns(result, project)
    (warning,) = [
        w for w in result.warnings if w.code == "WARN-DBT-MODEL-COLUMNS-UNRESOLVED"
    ]
    assert warning.query == "q"


class TestForeignAdapterTypes:
    @pytest.mark.parametrize("adapter_type", ["sqlserver", "vertica"])
    def test_foreign_adapter_types_never_crash_the_derivation(
        self, tmp_path, adapter_type
    ):
        """adapter_type is written by the user's dbt project. `sqlserver` pins
        the alias map (→ tsql); `vertica` has neither a sqlglot module nor an
        alias entry and pins the fail-closed guard to the generic-parse path —
        without it, sqlglot's dialect lookup raises an uncaught ValueError."""
        (tmp_path / "dbt_charts.yml").write_text("name: p\n")
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "manifest.json").write_text(
            json.dumps(
                {
                    "metadata": {"adapter_type": adapter_type},
                    "nodes": {
                        "model.p.orders": _model("orders", "SELECT id, amount FROM raw")
                    },
                }
            )
        )
        project = FilesystemProject(tmp_path)
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"id", "amount"}


class TestProjectionShapesBelowTheTopLevel:
    def test_unaliased_count_star_is_unresolved_never_a_fabricated_column(
        self, tmp_path
    ):
        """count(*) has no authored output name — alias_or_name renders it as
        the literal '*', which must not enter a complete claim."""
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.orders": _model(
                    "orders", "SELECT customer_id, count(*) FROM raw GROUP BY 1"
                )
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None

    def test_columns_function_projection_is_unresolved(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.wide": _model(
                    "wide",
                    "SELECT columns('^amount_') FROM raw",
                )
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["wide"].unresolved is not None


class TestProjectionNameProvenance:
    def test_unaliased_subscript_projection_is_unresolved(self, tmp_path):
        """payload['event_type'] has no authored output name — sqlglot's
        output_name renders the subscript literal, a name no engine emits."""
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.events": _model(
                    "events", "SELECT user_id, payload['event_type'] FROM raw"
                )
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["events"].unresolved is not None

    def test_unaliased_json_extract_projection_is_unresolved(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {"model.p.events": _model("events", "SELECT j -> 'id' FROM raw")},
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["events"].unresolved is not None

    def test_unaliased_literal_projection_is_unresolved(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {"model.p.orders": _model("orders", "SELECT 'US', id FROM raw")},
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None

    def test_unaliased_cast_is_unresolved_because_its_name_is_dialect_lore(
        self, tmp_path
    ):
        """Postgres names CAST(amount AS INT) after the inner column; BigQuery
        says f0_, DuckDB the expression text — a guess, not an authored name."""
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.orders": _model(
                    "orders", "SELECT id, CAST(amount AS INT) FROM raw"
                )
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].unresolved is not None

    def test_aliased_and_parenthesized_projections_resolve(self, tmp_path):
        project = _project_with_manifest(
            tmp_path,
            {
                "model.p.orders": _model(
                    "orders", "SELECT 'US' AS country, (amount) FROM raw"
                )
            },
        )
        resolved = resolve_model_output_columns(load_manifest(project))
        assert resolved["orders"].columns == {"country", "amount"}
        assert resolved["orders"].unresolved is None
