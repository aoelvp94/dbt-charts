"""Migration coverage for the 0.4.0 -> 0.5.0 allow_html: bool -> html_policy:
str cut (dbt_charts.core.compile.migrations.versions.v0_5_0), the lossless
value-mapped rename that accompanies the html-policy type change.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from dbt_charts.core.compile.migrations import (
    MigrationError,
    SchemaMigrationWarning,
    migrate_mapping,
    migrate_yaml_text,
)
from dbt_charts.core.compile.migrations.migrations import (
    _CURRENT,
    Move,
    _apply_move,
    _board_migration_context,
)
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.parse.parser import load_yaml_mapping
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    JsonObject,
    YamlSchemaCatalog,
    load_yaml_schema_catalog,
)


@pytest.fixture
def catalog() -> YamlSchemaCatalog:
    return load_yaml_schema_catalog()


def _migrate(raw: JsonObject, catalog: YamlSchemaCatalog) -> JsonObject:
    _, registry = _board_migration_context()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SchemaMigrationWarning)
        return migrate_mapping(raw, catalog=catalog, registry=registry)


def _minimal_board(extra: dict[str, Any]) -> dict[str, Any]:
    """Return a minimal schema-shaped board dict with extra top-level keys."""
    return {
        "title": "Revenue",
        "rows": ["revenue"],
        "charts": {
            "revenue": {
                "type": "bar",
                "query": "revenue",
                "x": "month",
                "y": "amount",
            }
        },
        **extra,
    }


def test_registry_covers_the_0_4_0_transition(
    catalog: YamlSchemaCatalog,
) -> None:
    _, registry = _board_migration_context()

    moves = registry.transition_from("0.4.0")

    assert moves
    assert any(
        move.old_path == ("allow_html",)
        and move.new_path == ("html_policy",)
        and move.target_schema == "0.5.0"
        for move in moves
    )


def test_allow_html_true_migrates_to_trusted_raw_in_memory(
    catalog: YamlSchemaCatalog,
) -> None:
    raw = _minimal_board({"allow_html": True})

    migrated = _migrate(raw, catalog)

    assert migrated["html_policy"] == "trusted-raw"
    assert "allow_html" not in migrated
    AuthoredBoard.model_validate(migrated)


def test_allow_html_false_migrates_to_none_in_memory(
    catalog: YamlSchemaCatalog,
) -> None:
    raw = _minimal_board({"allow_html": False})

    migrated = _migrate(raw, catalog)

    assert migrated["html_policy"] == "none"
    assert "allow_html" not in migrated
    AuthoredBoard.model_validate(migrated)


@pytest.mark.parametrize(
    ("allow_html_literal", "expected_html_policy"),
    [("true", "trusted-raw"), ("false", "none")],
)
def test_allow_html_yaml_text_round_trip_preserves_comments(
    catalog: YamlSchemaCatalog, allow_html_literal: str, expected_html_policy: str
) -> None:
    """The file-preserving writer used by `dct migrate` rewrites allow_html:
    to html_policy: <mapped value>, leaving surrounding comments in the file
    intact (a scalar Move deletes the old key and inserts the new one as a
    top-level key -- the comment's line survives, but is not necessarily
    still adjacent to the moved value)."""
    _, registry = _board_migration_context()
    yaml_text = (
        "title: Revenue\n"
        "# this comment must survive\n"
        f"allow_html: {allow_html_literal}\n"
        "rows: [revenue]\n"
        "charts:\n"
        "  revenue:\n"
        "    type: bar\n"
        "    query: revenue\n"
        "    x: month\n"
        "    y: amount\n"
    )

    migrated = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "# this comment must survive" in migrated
    assert "allow_html" not in migrated
    doc = load_yaml_mapping(migrated)
    assert doc["html_policy"] == expected_html_policy
    AuthoredBoard.model_validate(doc)


def test_allow_html_rejected_on_a_current_board() -> None:
    """Un-migrated allow_html on a current-schema board raises ValidationError via
    extra='forbid' -- no alias, per the no-back-compat rule."""
    from pydantic import ValidationError

    raw: dict[str, Any] = {
        "title": "Revenue",
        "allow_html": True,
        "rows": ["revenue"],
    }

    with pytest.raises(ValidationError, match="allow_html"):
        AuthoredBoard.model_validate(raw)


def test_unmapped_value_raises_migration_error() -> None:
    """_apply_move raises MigrationError immediately when a Move's value_map
    doesn't cover the popped value -- never passes an unmapped value through.

    allow_html is strictly `type: boolean` in the frozen schemas, so no
    non-bool value can reach this Move via the real registry (schema
    recognition rejects it first) -- this exercises _apply_move directly to
    cover the value_map safety net itself, independent of any one field's
    schema.
    """
    move = Move(
        source_schema=_CURRENT,
        target_schema=_CURRENT,
        old_path=("allow_html",),
        new_path=("html_policy",),
        value_map={True: "trusted-raw", False: "none"},
    )
    mapping: dict[str, Any] = {"allow_html": "maybe"}

    with pytest.raises(MigrationError, match="allow_html"):
        _apply_move(mapping, move)


def test_apply_move_rejects_non_scalar_source() -> None:
    """_apply_move raises the same MigrationError for a non-scalar source
    value as for an unmapped one -- a value_map is declared total over a
    scalar domain, so anything else is a migration author's error to fix,
    not a value to guess through."""
    move = Move(
        source_schema=_CURRENT,
        target_schema=_CURRENT,
        old_path=("allow_html",),
        new_path=("html_policy",),
        value_map={True: "trusted-raw", False: "none"},
    )
    mapping: dict[str, Any] = {"allow_html": ["not", "scalar"]}

    with pytest.raises(MigrationError, match="allow_html"):
        _apply_move(mapping, move)
