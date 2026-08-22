"""Integration tests for manifest-backed ref/source validation via validate_content."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from dbt_charts.cli.filesystem_project import FilesystemProject

_MANIFEST_CONTENT = json.dumps(
    {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"
        },
        "nodes": {
            "model.analytics.fct_orders": {
                "resource_type": "model",
                "name": "fct_orders",
                "schema": "analytics",
                "relation_name": "analytics.fct_orders",
            }
        },
        "sources": {
            "source.analytics.raw.customers": {
                "source_name": "raw",
                "name": "customers",
                "schema": "raw",
                "relation_name": "raw.customers",
            }
        },
    }
)

_BOARD_WITH_VALID_REF = """
queries:
  orders:
    sql: "SELECT * FROM {{ ref('fct_orders') }}"
    source: dbt_duckdb
rows: []
"""

_BOARD_WITH_UNKNOWN_REF = """
queries:
  orders:
    sql: "SELECT * FROM {{ ref('typo_model') }}"
    source: dbt_duckdb
rows: []
"""

_BOARD_WITH_UNKNOWN_SOURCE = """
queries:
  orders:
    sql: "SELECT * FROM {{ source('raw', 'nonexistent') }}"
    source: dbt_duckdb
rows: []
"""

_BOARD_NO_REFS = """
queries:
  plain:
    sql: SELECT 1
    source: analytics
rows: []
"""


def _project_with_manifest(tmp_path: Path) -> FilesystemProject:
    (tmp_path / "charts").mkdir()
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text(_MANIFEST_CONTENT)
    return FilesystemProject(tmp_path)


def _project_without_manifest(tmp_path: Path) -> FilesystemProject:
    (tmp_path / "charts").mkdir()
    return FilesystemProject(tmp_path)


def test_valid_ref_passes(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate_content

    project = _project_with_manifest(tmp_path)
    result = validate_content(_BOARD_WITH_VALID_REF, project=project)
    manifest_errors = [e for e in result.errors if "ERR-DBT-REF" in e.code]
    manifest_warns = [
        w for w in result.warnings if w.code == "WARN-DBT-MANIFEST-MISSING"
    ]
    assert manifest_errors == []
    assert manifest_warns == []


def test_unknown_ref_produces_error(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate_content

    project = _project_with_manifest(tmp_path)
    result = validate_content(_BOARD_WITH_UNKNOWN_REF, project=project)
    error_codes = [e.code for e in result.errors]
    assert "ERR-DBT-REF-UNKNOWN-NODE" in error_codes


def test_unknown_source_produces_error(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate_content

    project = _project_with_manifest(tmp_path)
    result = validate_content(_BOARD_WITH_UNKNOWN_SOURCE, project=project)
    error_codes = [e.code for e in result.errors]
    assert "ERR-DBT-SOURCE-UNKNOWN-TABLE" in error_codes


def test_missing_manifest_warns_once(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate_content

    project = _project_without_manifest(tmp_path)
    result = validate_content(_BOARD_WITH_VALID_REF, project=project)
    manifest_warns = [
        w for w in result.warnings if w.code == "WARN-DBT-MANIFEST-MISSING"
    ]
    assert len(manifest_warns) == 1
    assert "looked for" in manifest_warns[0].message


def test_no_refs_no_manifest_no_warning(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate_content

    project = _project_without_manifest(tmp_path)
    result = validate_content(_BOARD_NO_REFS, project=project)
    manifest_warns = [
        w for w in result.warnings if w.code == "WARN-DBT-MANIFEST-MISSING"
    ]
    assert manifest_warns == []


def test_loader_not_called_when_no_refs(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate_content

    project = _project_without_manifest(tmp_path)
    with patch("dbt_charts.core.dbt_ref_check.load_manifest") as mock_load:
        validate_content(_BOARD_NO_REFS, project=project)
    mock_load.assert_not_called()


def test_file_based_validate_unknown_ref(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate

    (tmp_path / "charts").mkdir()
    board = tmp_path / "charts" / "board.yml"
    board.write_text(_BOARD_WITH_UNKNOWN_REF)
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text(_MANIFEST_CONTENT)
    project = FilesystemProject(tmp_path)

    result = validate(board, project=project)

    assert not result.success
    assert any(e.code == "ERR-DBT-REF-UNKNOWN-NODE" for e in result.errors)


def test_corrupt_manifest_surfaces_as_diagnostic(tmp_path: Path) -> None:
    from dbt_charts.agent_api.validate import validate_content

    (tmp_path / "charts").mkdir()
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text("{bad json")
    project = FilesystemProject(tmp_path)

    result = validate_content(_BOARD_WITH_VALID_REF, project=project)

    # Must not raise — error must be in result.errors as a diagnostic
    assert any("ERR-DBT-MANIFEST-INCOMPATIBLE" in e.code for e in result.errors)
