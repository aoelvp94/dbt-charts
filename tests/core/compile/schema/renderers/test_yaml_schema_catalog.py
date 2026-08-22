"""Dataface YAML schemas are strict, frozen package contracts."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.schema.introspection import introspect
from dbt_charts.core.compile.schema.renderers.json_schema import (
    render_yaml_schema,
)
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    load_yaml_schema_catalog,
    load_yaml_schema_catalog_from,
)
from dbt_charts.schema_release import freeze_yaml_schema, verify_released_yaml_schema


def test_yaml_schema_closes_authored_objects() -> None:
    schema = render_yaml_schema(introspect())

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["BarChart"]["additionalProperties"] is False
    assert any(
        branch.get("additionalProperties")
        for branch in schema["properties"]["charts"]["anyOf"]
    )


def test_yaml_schema_matches_the_authored_board_boundary() -> None:
    schema = render_yaml_schema(introspect())
    valid = {
        "charts": {
            "revenue": {
                "type": "bar",
                "x": "month",
                "y": "revenue",
                "query": {"sql": "select month, revenue from revenue"},
            }
        }
    }

    jsonschema.Draft7Validator(schema).validate(valid)
    AuthoredBoard.model_validate(valid)

    invalid = {**valid, "not_a_dataface_key": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(schema).validate(invalid)
    with pytest.raises(ValidationError):
        AuthoredBoard.model_validate(invalid)


def test_yaml_schema_accepts_layout_name_shorthand() -> None:
    board = {
        "charts": {
            "revenue": {
                "type": "bar",
                "x": "month",
                "y": "revenue",
                "query": {"sql": "select month, revenue from revenue"},
            }
        },
        "rows": ["revenue"],
    }

    AuthoredBoard.model_validate(board)
    jsonschema.Draft7Validator(render_yaml_schema(introspect())).validate(board)


def test_packaged_catalog_loads_newest_schema_first() -> None:
    catalog = load_yaml_schema_catalog()

    assert catalog.entries
    assert catalog.entries[0].version == catalog.latest.version
    assert catalog.schema_for(catalog.latest.version)["additionalProperties"] is False


def test_catalog_rejects_a_modified_frozen_snapshot(tmp_path: Path) -> None:
    schema_path = tmp_path / "0.3.0.json"
    schema_path.write_text('{"type": "object"}\n', encoding="utf-8")
    manifest = {
        "schemas": [
            {
                "version": "0.3.0",
                "released_at": "2026-07-30",
                "file": "0.3.0.json",
                "sha256": "not-the-schema-hash",
                "predecessor": None,
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        load_yaml_schema_catalog_from(tmp_path)


def test_freeze_only_appends_when_the_candidate_changes(tmp_path: Path) -> None:
    version = "0.3.0"
    candidate = {"type": "object", "additionalProperties": False}

    first = freeze_yaml_schema(
        tmp_path,
        version=version,
        released_at=date(2026, 7, 30),
        candidate=candidate,
    )
    assert first.version == version
    assert first.released_at == date(2026, 7, 30)
    assert first.filename == "0.3.0.json"
    before = (tmp_path / first.filename).read_bytes()
    assert (
        freeze_yaml_schema(
            tmp_path,
            version=version,
            released_at=date(2026, 7, 30),
            candidate=candidate,
        )
        == first
    )
    assert (tmp_path / first.filename).read_bytes() == before

    second = freeze_yaml_schema(
        tmp_path,
        version="0.4.0",
        released_at=date(2026, 8, 1),
        candidate={"type": "object", "additionalProperties": False, "title": "Board"},
    )
    assert second.version == "0.4.0"

    catalog = load_yaml_schema_catalog_from(tmp_path)
    assert [item.version for item in catalog.entries] == ["0.4.0", "0.3.0"]


def test_release_verification_requires_a_current_yaml_schema(tmp_path: Path) -> None:
    candidate = {"type": "object", "additionalProperties": False}
    freeze_yaml_schema(
        tmp_path,
        version="0.3.0",
        released_at=date(2026, 7, 30),
        candidate=candidate,
    )

    verify_released_yaml_schema(tmp_path, version="0.3.0", candidate=candidate)

    with pytest.raises(ValueError, match="unfrozen YAML grammar"):
        verify_released_yaml_schema(
            tmp_path,
            version="0.4.0",
            candidate={
                "type": "object",
                "additionalProperties": False,
                "title": "Board",
            },
        )
