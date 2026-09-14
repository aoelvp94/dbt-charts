"""Tests for the highlight manifest renderer and the committed board.json artifact.

Two assertions:
1. The manifest's enum sets match the live introspection output.
2. The committed board.json is in sync with generator output.

A committed tmLanguage.json copy is kept in sync by a guard test outside
dbt-charts/, not covered here.
"""

from __future__ import annotations

import json

from dbt_charts.core.compile.schema.introspection import introspect
from dbt_charts.core.compile.schema.renderers.highlight_manifest import (
    render_highlight_manifest,
)

from ....._paths import DBT_CHARTS_DIR, DBT_CHARTS_PKG_DIR

_MANIFEST_PATH = DBT_CHARTS_PKG_DIR / "data" / "highlighting" / "board.json"


class TestGenerateScriptPaths:
    def test_generate_script_writes_to_committed_manifest_path(self) -> None:
        """gen_highlight_artifacts.py's MANIFEST_PATH must point at the committed board.json."""
        import importlib.util

        script_path = DBT_CHARTS_DIR / "scripts" / "gen_highlight_artifacts.py"
        spec = importlib.util.spec_from_file_location(
            "gen_highlight_artifacts", script_path
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.MANIFEST_PATH == _MANIFEST_PATH


class TestHighlightManifestMatchesIntrospection:
    def test_chart_types_match_introspect(self) -> None:
        schema = introspect()
        manifest = render_highlight_manifest(schema)
        chart_model = schema.models["AuthoredChart"]
        # AuthoredChart is a discriminated union; type tags come from union.variants.
        assert chart_model.union is not None
        expected_tags = set(chart_model.union.variants.keys())
        assert set(manifest.enum_values_by_key["type"]) == expected_tags

    def test_input_types_match_introspect(self) -> None:
        schema = introspect()
        manifest = render_highlight_manifest(schema)
        var_model = schema.models["Variable"]
        input_field = next(f for f in var_model.fields if f.name == "input")
        assert input_field.enum_values is not None
        assert set(manifest.enum_values_by_key["input"]) == set(input_field.enum_values)

    def test_top_level_keys_match_authored_board(self) -> None:
        schema = introspect()
        manifest = render_highlight_manifest(schema)
        board_model = schema.models["AuthoredBoard"]
        board_keys = {f.name for f in board_model.fields}
        assert set(manifest.top_level_keys) == board_keys

    def test_sql_block_scalar_keys_non_empty(self) -> None:
        schema = introspect()
        manifest = render_highlight_manifest(schema)
        assert "sql" in manifest.sql_block_scalar_keys
        assert "query" in manifest.sql_block_scalar_keys

    def test_sql_block_scalar_parents_names_the_queries_shorthand(self) -> None:
        """Block scalars directly under top-level ``queries:`` are SQL by structure."""
        schema = introspect()
        manifest = render_highlight_manifest(schema)
        assert manifest.sql_block_scalar_parents == ["queries"]
        assert manifest.to_dict()["sql_block_scalar_parents"] == ["queries"]


class TestCommittedManifestInSync:
    def test_committed_highlight_manifest_in_sync(self) -> None:
        """Committed board.json must match render_highlight_manifest(introspect())."""
        schema = introspect()
        manifest = render_highlight_manifest(schema)
        committed = json.loads(_MANIFEST_PATH.read_text())
        generated = manifest.to_dict()
        assert committed == generated, (
            "dbt_charts/data/highlighting/board.json is out of sync. "
            "Run: just gen-highlight-artifacts"
        )
