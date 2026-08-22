"""Tests for board-resolved.schema.json drift and shape.

TDD: written before
dbt-charts/src/dbt_charts/data/schemas/board-resolved/board-resolved.schema.json
existed. Run to watch them fail, then run `just gen-board-resolved-schema`
to make them pass.
"""

from __future__ import annotations

import json
from typing import Any

from ....._paths import DBT_CHARTS_PKG_DIR

SCHEMA_PATH = (
    DBT_CHARTS_PKG_DIR
    / "data"
    / "schemas"
    / "board-resolved"
    / "board-resolved.schema.json"
)

_CANONICAL_SCHEMA_LIST_KEYS = {
    "allOf",
    "anyOf",
    "enum",
    "fileMatch",
    "oneOf",
    "required",
}


def _canonicalize_schema(value: Any, parent_key: str | None = None) -> Any:
    """Normalize schema list ordering for stable comparison across Python versions."""
    if isinstance(value, dict):
        return {
            key: _canonicalize_schema(item, parent_key=key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        normalized = [
            _canonicalize_schema(item, parent_key=parent_key) for item in value
        ]
        if parent_key in _CANONICAL_SCHEMA_LIST_KEYS:
            return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
        return normalized
    return value


def _regenerate_canonical_schema() -> dict[str, Any]:
    from dbt_charts.core.compile.schema.renderers.board_resolved import (
        render_board_resolved_schema,
    )

    # The value is arbitrary: test_board_resolved_schema_matches_regeneration
    # drops "version" from both sides before comparing.
    return _canonicalize_schema(render_board_resolved_schema(version="0.0.0"))


def test_board_resolved_schema_matches_regeneration():
    """Committed board-resolved.schema.json must match regeneration.

    Fails when a ResolvedBoard (or any type it references) changes without
    re-running `just gen-board-resolved-schema`.

    ``version`` is excluded from the comparison: it is stamped from the
    working tree's live commit distance at generation time (see
    dbt-charts/scripts/gen_board_resolved_schema.py's ``_current_source_version``),
    so it legitimately drifts on every later commit with no shape change at all.
    Comparing the parsed dicts (rather than raw text) with that one key dropped
    still fails on any real shape edit, including a hand-edit of the committed file.
    """
    assert SCHEMA_PATH.exists(), (
        f"board-resolved.schema.json not found at {SCHEMA_PATH}. "
        "Run: just gen-board-resolved-schema"
    )

    committed = json.loads(SCHEMA_PATH.read_text())
    regenerated = _regenerate_canonical_schema()

    assert "version" in committed and "version" in regenerated
    del committed["version"]
    del regenerated["version"]

    assert committed == regenerated, (
        "board-resolved.schema.json is stale. Re-run: just gen-board-resolved-schema"
    )


def test_render_board_resolved_schema_stamps_caller_supplied_version():
    """version is stamped verbatim from the caller, never looked up from
    installed package metadata."""
    from dbt_charts.core.compile.schema.renderers.board_resolved import (
        render_board_resolved_schema,
    )

    schema = render_board_resolved_schema(version="0.0.0-caller-supplied-marker")
    assert schema["version"] == "0.0.0-caller-supplied-marker"


def test_board_resolved_schema_has_expected_metadata():
    committed = json.loads(SCHEMA_PATH.read_text())
    assert committed["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert (
        committed["$id"] == "https://dbtcharts.com/schemas/board-resolved.schema.json"
    )
    assert isinstance(committed["version"], str) and committed["version"]
    assert "$defs" in committed
    assert committed["required"] == ["$id", "board", "styles", "version"]
    assert committed["properties"]["board"] == {"$ref": "#/$defs/ResolvedBoard"}


def test_board_resolved_schema_hoists_style_into_a_ref():
    """ResolvedBoard.style is a $style_ref pointer, not an inline ResolvedStyle —
    dbt-charts/AGENTS.md's dedupe rationale: one style per artifact, not one per
    board. The $defs entry is recursive, so this single edit covers nested
    boards too, without walking the tree by hand."""
    committed = json.loads(SCHEMA_PATH.read_text())
    assert committed["$defs"]["ResolvedBoard"]["properties"]["style"] == {
        "$ref": "#/$defs/StyleRef"
    }
    assert "$style_ref" in committed["$defs"]["StyleRef"]["properties"]
    assert committed["properties"]["styles"]["additionalProperties"] == {
        "$ref": "#/$defs/ResolvedStyle"
    }


def test_board_resolved_schema_query_defs_are_discriminated():
    """AnyQuery's discriminator must survive into the published schema as a
    query_type-tagged shape, not a bare untagged oneOf/anyOf."""
    committed = json.loads(SCHEMA_PATH.read_text())
    defs = committed["$defs"]
    for name in ("SqlQuery", "HttpQuery", "ValuesQuery", "SchemaQuery"):
        assert name in defs, f"{name} missing from $defs"
        assert "query_type" in defs[name]["properties"]
