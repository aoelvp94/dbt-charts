from __future__ import annotations

import warnings
from copy import deepcopy
from datetime import date
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError

from dbt_charts.core.compile.errors import ParseError
from dbt_charts.core.compile.migrations import (
    ConditionalMove,
    Deletion,
    MigrationConflictError,
    MigrationError,
    MigrationRegistry,
    Move,
    SchemaMigrationWarning,
    SchemaVersionTooOldError,
    UnsupportedSchemaError,
    migrate_mapping,
    migrate_yaml_text,
    prepare_board_mapping,
)
from dbt_charts.core.compile.migrations.migrations import _CURRENT
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    JsonObject,
    YamlSchemaCatalog,
    YamlSchemaEntry,
)

V1 = "0.1.0"
V2 = "0.2.0"
V3 = "0.3.0"


def _catalog(schemas: dict[str, JsonObject]) -> YamlSchemaCatalog:
    versions = tuple(reversed(schemas))
    entries = tuple(
        YamlSchemaEntry(
            version=version,
            released_at=date(2026, len(versions) + 4 - index, 1),
            filename=f"{version}.json",
            sha256="test",
            predecessor=None,
        )
        for index, version in enumerate(versions)
    )
    # In synthetic catalogs the "current" live schema equals the newest frozen
    # schema — the distinction only matters in the real catalog when a PR has
    # changed the Pydantic models but hasn't been released yet.
    current_schema = schemas[versions[0]]
    return YamlSchemaCatalog(entries, schemas, current_schema)


def _schema(*keys: str) -> JsonObject:
    return cast(
        JsonObject,
        {
            "type": "object",
            "properties": {key: {"type": "string"} for key in keys},
            "additionalProperties": False,
        },
    )


def _chart_schema(type_required: bool) -> JsonObject:
    chart_schema: JsonObject = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "type": {"type": "string"},
        },
        "additionalProperties": False,
    }
    if type_required:
        chart_schema["required"] = ["type"]
    return {
        "type": "object",
        "properties": {
            "charts": {
                "type": "object",
                "additionalProperties": chart_schema,
            }
        },
        "additionalProperties": False,
    }


def _required_chart_type_context() -> tuple[YamlSchemaCatalog, MigrationRegistry]:
    catalog = _catalog({V1: _chart_schema(False), V2: _chart_schema(True)})
    return catalog, MigrationRegistry([], catalog=catalog)


def test_migrates_a_retired_key_before_current_validation() -> None:
    catalog = _catalog({V1: _schema("old"), V2: _schema("new")})
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("new",))], catalog=catalog)

    result = migrate_mapping({"old": "value"}, catalog=catalog, registry=registry)

    assert result == {"new": "value"}


def test_current_mapping_is_not_rewritten() -> None:
    catalog = _catalog({V1: _schema("old"), V2: _schema("new")})
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("new",))], catalog=catalog)
    raw = {"new": "value"}

    result = migrate_mapping(raw, catalog=catalog, registry=registry)

    assert result == raw
    assert result is not raw


def test_uses_the_newest_matching_schema() -> None:
    catalog = _catalog({V1: _schema("old"), V2: _schema("old", "new")})
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("new",))], catalog=catalog)

    result = migrate_mapping({"old": "value"}, catalog=catalog, registry=registry)

    assert result == {"old": "value"}


def test_applies_adjacent_moves_in_order() -> None:
    catalog = _catalog({V1: _schema("old"), V2: _schema("middle"), V3: _schema("new")})
    registry = MigrationRegistry(
        [
            Move(V1, V2, ("old",), ("middle",)),
            Move(V2, V3, ("middle",), ("new",)),
        ],
        catalog=catalog,
    )

    result = migrate_mapping({"old": "value"}, catalog=catalog, registry=registry)

    assert result == {"new": "value"}


def test_declared_move_can_reach_current_schema_without_another_move() -> None:
    catalog = _catalog(
        {
            V1: _schema("old"),
            V2: _schema("middle"),
            V3: _schema("middle", "optional"),
        }
    )
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("middle",))], catalog=catalog)

    result = migrate_mapping({"old": "value"}, catalog=catalog, registry=registry)

    assert result == {"middle": "value"}


def test_conflicting_destination_does_not_mutate_input() -> None:
    catalog = _catalog({V1: _schema("old", "new"), V2: _schema("new")})
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("new",))], catalog=catalog)
    raw = {"old": "old value", "new": "new value"}
    original = deepcopy(raw)

    with pytest.raises(MigrationConflictError, match="old.*new"):
        migrate_mapping(raw, catalog=catalog, registry=registry)

    assert raw == original


def test_rejects_unknown_grammar_with_current_diagnostic() -> None:
    catalog = _catalog({V1: _schema("old"), V2: _schema("new")})
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("new",))], catalog=catalog)

    with pytest.raises(UnsupportedSchemaError, match="unexpected"):
        migrate_mapping({"unexpected": "value"}, catalog=catalog, registry=registry)


def test_non_structural_current_rejection_uses_current_diagnostic() -> None:
    catalog, registry = _required_chart_type_context()

    with pytest.raises(UnsupportedSchemaError, match="'type' is a required property"):
        migrate_mapping(
            {"charts": {"revenue": {"query": "revenue"}}},
            catalog=catalog,
            registry=registry,
        )


def test_explicit_non_structural_migration_uses_current_diagnostic() -> None:
    catalog, registry = _required_chart_type_context()

    with pytest.raises(UnsupportedSchemaError, match="'type' is a required property"):
        migrate_yaml_text(
            "charts:\n  revenue:\n    query: revenue\n",
            catalog=catalog,
            registry=registry,
        )


def test_rewrites_a_scalar_move_without_reformatting_comments() -> None:
    catalog = _catalog({V1: _schema("old"), V2: _schema("new")})
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("new",))], catalog=catalog)

    result = migrate_yaml_text(
        "# preserve me\nold: value\n# preserve me too\n",
        catalog=catalog,
        registry=registry,
    )

    assert 'new: "value"' in result
    assert "old:" not in result
    assert "# preserve me\n" in result
    assert "# preserve me too\n" in result


def _object_schema_pair(*, old_key: str, new_key: str) -> dict[str, JsonObject]:
    return {
        V1: cast(
            JsonObject,
            {
                "type": "object",
                "properties": {old_key: {"type": "object"}},
                "additionalProperties": False,
            },
        ),
        V2: cast(
            JsonObject,
            {
                "type": "object",
                "properties": {new_key: {"type": "object"}},
                "additionalProperties": False,
            },
        ),
    }


def test_renames_a_block_valued_key_in_place_without_reformatting() -> None:
    """A pure rename (old/new path share the same parent) never relocates
    content, so it's not restricted to scalars: the nested mapping under
    `old:` moves to `new:` untouched, and unrelated comments survive."""
    catalog = _catalog(_object_schema_pair(old_key="old", new_key="new"))
    registry = MigrationRegistry([Move(V1, V2, ("old",), ("new",))], catalog=catalog)

    result = migrate_yaml_text(
        "# preserve me\nold:\n  nested: value\n# preserve me too\n",
        catalog=catalog,
        registry=registry,
    )

    assert result == "# preserve me\nnew:\n  nested: value\n# preserve me too\n"


def test_rejects_non_scalar_relocation_to_a_different_parent() -> None:
    """A move to a genuinely different parent (not a same-position rename)
    still can't relocate a nested block without a redump, so it still fails
    loudly instead of guessing."""
    catalog = _catalog(
        {
            V1: cast(
                JsonObject,
                {
                    "type": "object",
                    "properties": {"old": {"type": "object"}},
                    "additionalProperties": False,
                },
            ),
            V2: cast(
                JsonObject,
                {
                    "type": "object",
                    "properties": {
                        "wrapper": {
                            "type": "object",
                            "properties": {"new": {"type": "object"}},
                            "additionalProperties": False,
                        }
                    },
                    "additionalProperties": False,
                },
            ),
        }
    )
    registry = MigrationRegistry(
        [Move(V1, V2, ("old",), ("wrapper", "new"))], catalog=catalog
    )

    with pytest.raises(MigrationError, match="only scalar"):
        migrate_yaml_text("old:\n  nested: value\n", catalog=catalog, registry=registry)


def test_current_recognition_schema_accepts_layout_name_shorthand() -> None:
    raw = {"rows": ["revenue_trend"]}

    assert prepare_board_mapping(cast(JsonObject, raw)) == raw


def test_current_pydantic_shorthand_is_not_rejected_by_schema_recognition() -> None:
    raw = {"theme": "cream"}

    assert prepare_board_mapping(raw) == raw


def test_prepare_mapping_defers_non_structural_rejection_to_pydantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dbt_charts.core.compile.migrations import migrations as _migrations_impl
    from dbt_charts.core.compile.models.board.authored import AuthoredBoard

    catalog, registry = _required_chart_type_context()
    raw: JsonObject = {"charts": {"revenue": {"query": "revenue"}}}
    # Patch the submodule where prepare_board_mapping lives and calls these names —
    # patching the re-exporting __init__ does not affect the internal call site.
    monkeypatch.setattr(_migrations_impl, "_board_has_historical_schemas", lambda: True)
    monkeypatch.setattr(
        _migrations_impl, "_board_migration_context", lambda: (catalog, registry)
    )

    prepared = prepare_board_mapping(raw)

    assert prepared == raw
    with pytest.raises(ValidationError, match="type"):
        AuthoredBoard.model_validate(prepared)


def test_catalog_version_without_module_is_skipped() -> None:
    """A catalog entry with no matching v*.py file contributes no moves and raises no error."""
    from dbt_charts.core.compile.migrations.migrations import (
        _board_migration_context,
        _load_migration_module,
    )
    from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
        load_yaml_schema_catalog,
    )

    catalog = load_yaml_schema_catalog()
    # Find a real catalog entry with no version module, rather than pinning one by
    # version number — that pin breaks every time the retained catalog changes.
    moduleless = next(
        e
        for e in catalog.entries
        if e.predecessor is not None
        and _load_migration_module(
            f"dbt_charts.core.compile.migrations.versions.v{e.version.replace('.', '_')}"
        )
        is None
    )

    _, registry = _board_migration_context()

    assert registry.transition_from(moduleless.predecessor) == ()


def test_version_module_without_moves_or_deletions_raises_migration_error() -> None:
    """A found version module that lacks both moves() and deletions() raises MigrationError."""
    import sys
    import types

    from dbt_charts.core.compile.migrations.migrations import (
        MigrationError,
        _load_migration_module,
    )

    dotted = "dbt_charts.core.compile.migrations.versions.v9_9_9"
    fake = types.ModuleType(dotted)
    # intentionally no 'moves' or 'deletions' attribute

    sys.modules[dotted] = fake
    try:
        with pytest.raises(MigrationError, match="does not define"):
            _load_migration_module(dotted)
    finally:
        del sys.modules[dotted]


def test_prepare_mapping_current_schema_patch_takes_fast_path_under_boardpatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A current-schema, patch-shaped fragment (no charts/layout/title — the
    shape of every theme YAML and meta.yaml) must not be treated as a
    migration candidate just because it fails the AuthoredBoard
    "must have layout/chart/etc" invariant. Passing model=BoardPatch checks
    currency against a model that admits partial content."""
    from dbt_charts.core.compile.migrations import migrations as _migrations_impl
    from dbt_charts.core.compile.models.board.patch import BoardPatch

    raw: JsonObject = {"style": {"charts": {"axis_x": {"labels": {"format": "auto"}}}}}

    def _boom() -> tuple[YamlSchemaCatalog, MigrationRegistry]:
        raise AssertionError(
            "prepare_board_mapping must not build the migration registry for a "
            "current-schema patch"
        )

    monkeypatch.setattr(_migrations_impl, "_board_migration_context", _boom)

    prepared = prepare_board_mapping(raw, model=BoardPatch)

    assert prepared == raw


def test_prepare_mapping_old_schema_patch_still_migrates_under_boardpatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old-schema patch fragment (pre-rename field name) must still reach
    real migration when checked with model=BoardPatch — the fast path must
    not swallow genuine migration needs for patch-shaped content."""
    from dbt_charts.core.compile.migrations import migrations as _migrations_impl
    from dbt_charts.core.compile.migrations.migrations import suffix_rename_moves
    from dbt_charts.core.compile.models.board.patch import BoardPatch

    old_schema = _schema_with_axis_field("label")
    new_schema = _schema_with_axis_field("labels")
    catalog = _catalog({V1: old_schema, V2: new_schema})
    registry = MigrationRegistry(
        suffix_rename_moves(
            _AxisHolderPatch,
            V1,
            V2,
            ((("labels",), ("label",)),),
            catalog=catalog,
        ),
        catalog=catalog,
    )
    monkeypatch.setattr(_migrations_impl, "_board_has_historical_schemas", lambda: True)
    monkeypatch.setattr(
        _migrations_impl, "_board_migration_context", lambda: (catalog, registry)
    )

    raw: JsonObject = {"axis_x": {"label": "auto"}}
    prepared = prepare_board_mapping(raw, model=BoardPatch)

    assert prepared == {"axis_x": {"labels": "auto"}}


def _schema_with_axis_field(field_name: str) -> JsonObject:
    return cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "axis_x": {
                    "type": "object",
                    "properties": {field_name: {"type": "string"}},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        },
    )


class _AxisFieldHolder(BaseModel):
    labels: str | None = None


class _AxisHolderPatch(BaseModel):
    axis_x: _AxisFieldHolder | None = None


# ---------------------------------------------------------------------------
# Deletion primitive
# ---------------------------------------------------------------------------


def _deletion_catalog() -> YamlSchemaCatalog:
    """V1 has key 'dead'; V2 does not."""
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"dead": {"type": "string"}, "live": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"live": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    return _catalog({V1: old, V2: new})


def test_deletion_strips_key_from_mapping() -> None:
    catalog = _deletion_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("dead",))],
        catalog=catalog,
    )

    result = migrate_mapping(
        {"dead": "gone", "live": "keep"}, catalog=catalog, registry=registry
    )

    assert result == {"live": "keep"}


def test_deletion_absent_key_is_noop() -> None:
    catalog = _deletion_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("dead",))],
        catalog=catalog,
    )

    result = migrate_mapping({"live": "keep"}, catalog=catalog, registry=registry)

    assert result == {"live": "keep"}


def test_deletion_strips_key_from_yaml_text() -> None:
    catalog = _deletion_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("dead",))],
        catalog=catalog,
    )

    result = migrate_yaml_text(
        "# comment\ndead: gone\nlive: keep\n",
        catalog=catalog,
        registry=registry,
    )

    assert "dead:" not in result
    assert "live:" in result
    assert "# comment\n" in result


def test_deletion_current_schema_document_untouched() -> None:
    catalog = _deletion_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("dead",))],
        catalog=catalog,
    )
    raw = {"live": "keep"}

    result = migrate_mapping(raw, catalog=catalog, registry=registry)

    assert result == raw
    assert result is not raw


def test_deletion_validates_source_path_must_exist() -> None:
    catalog = _deletion_catalog()

    with pytest.raises(MigrationError, match="absent from"):
        MigrationRegistry(
            [],
            [Deletion(V1, V2, ("nonexistent",))],
            catalog=catalog,
        )


def test_deletion_validates_adjacent_schema() -> None:
    catalog = _catalog({V1: _schema("a"), V2: _schema("a"), V3: _schema("a")})

    with pytest.raises(MigrationError, match="immediately succeeding"):
        MigrationRegistry(
            [],
            [Deletion(V1, V3, ("a",))],
            catalog=catalog,
        )


def test_deletions_from_returns_empty_for_unknown_schema() -> None:
    catalog = _deletion_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("dead",))],
        catalog=catalog,
    )

    assert registry.deletions_from("9.9.9") == ()


def _legend_catalog() -> YamlSchemaCatalog:
    """V1 has legend.dead + legend.live; V2 has only legend.live."""
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "legend": {
                    "type": "object",
                    "properties": {
                        "dead": {"type": "boolean"},
                        "live": {"type": "string"},
                    },
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "legend": {
                    "type": "object",
                    "properties": {"live": {"type": "string"}},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        },
    )
    return _catalog({V1: old, V2: new})


def _current_boundary_catalog() -> YamlSchemaCatalog:
    """V2 is latest with 'dead'+'live'; current_schema has only 'live'.

    Simulates an unreleased deletion — the latest frozen schema still has the
    field, but the live Pydantic model has removed it.
    """
    latest_schema: JsonObject = _schema("dead", "live")
    current_schema: JsonObject = _schema("live")
    entries = (
        YamlSchemaEntry(
            version=V2,
            released_at=date(2026, 6, 1),
            filename=f"{V2}.json",
            sha256="test2",
            predecessor=V1,
        ),
        YamlSchemaEntry(
            version=V1,
            released_at=date(2026, 5, 1),
            filename=f"{V1}.json",
            sha256="test1",
            predecessor=None,
        ),
    )
    return YamlSchemaCatalog(
        entries, {V1: _schema("ancient"), V2: latest_schema}, current_schema
    )


def test_deletion_target_path_must_be_absent_from_target_schema() -> None:
    """A tail still present in the target schema must not be declared as a Deletion."""
    catalog = _legend_catalog()

    # "live" exists in both V1 and V2 — declaring a deletion is wrong
    with pytest.raises(MigrationError, match="still exists in"):
        MigrationRegistry(
            [],
            [Deletion(V1, V2, ("legend", "live"))],
            catalog=catalog,
        )


def test_deletion_current_target_path_must_be_absent_from_current_schema() -> None:
    """A tail still present in the current (live) schema must not be deleted to _CURRENT."""
    catalog = _current_boundary_catalog()

    # "live" still exists in the current schema — declaring a deletion is wrong
    with pytest.raises(MigrationError, match="still exists in"):
        MigrationRegistry(
            [],
            [Deletion(V2, _CURRENT, ("live",))],
            catalog=catalog,
        )


def test_deletion_valid_current_target_accepts_absent_tail() -> None:
    """Deletion to _CURRENT is accepted when the tail is absent from current_schema."""
    catalog = _current_boundary_catalog()

    # "dead" is in V2 (source) but not in current_schema — valid deletion
    registry = MigrationRegistry(
        [],
        [Deletion(V2, _CURRENT, ("dead",))],
        catalog=catalog,
    )
    assert registry.deletions_from(V2)


def test_deletion_current_source_must_be_latest_schema() -> None:
    """Deletion targeting _CURRENT must source from the latest frozen schema, not an older one."""
    catalog = _current_boundary_catalog()

    with pytest.raises(MigrationError, match="latest frozen schema"):
        MigrationRegistry(
            [],
            [Deletion(V1, _CURRENT, ("ancient",))],
            catalog=catalog,
        )


def test_deletion_unretained_source_raises() -> None:
    """Deletion referencing a schema version not in the catalog raises."""
    catalog = _deletion_catalog()

    with pytest.raises(MigrationError, match="not retained"):
        MigrationRegistry(
            [],
            [Deletion("9.9.9", V2, ("dead",))],
            catalog=catalog,
        )


def test_support_window_exemption_latest_schema_is_always_migratable() -> None:
    """The latest released schema is exempt from the six-month support window.

    Older schemas age out, but the newest release is always transparently
    migratable regardless of how old it is.
    """
    catalog = _deletion_catalog()
    # V1 is the older schema (not latest); V2 is latest.
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("dead",))],
        catalog=catalog,
    )

    # today = far future (well past 6 months from release dates)
    far_future = date(2099, 1, 1)

    # V1 is the older schema and should be subject to the support window
    with pytest.raises(SchemaVersionTooOldError):
        migrate_mapping(
            {"dead": "gone", "live": "keep"},
            catalog=catalog,
            registry=registry,
            today=far_future,
        )

    # V2 is the latest frozen schema — always exempt regardless of date
    pending_catalog = _current_boundary_catalog()
    pending_registry = MigrationRegistry(
        [],
        [Deletion(V2, _CURRENT, ("dead",))],
        catalog=pending_catalog,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SchemaMigrationWarning)
        result = migrate_mapping(
            {"dead": "present", "live": "keep"},
            catalog=pending_catalog,
            registry=pending_registry,
            today=far_future,
        )
    assert result == {"live": "keep"}


def test_deletion_strips_nested_list_item_from_yaml_text() -> None:
    """Deletion in a list-nested mapping (rows/cols) works in the YAML text writer.

    Pre-enumeration computed numeric path segments that set_board_values cannot
    address; tail-matching walks the document instead.
    """
    legend_schema_v1: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "dead": {"type": "string"},
                "live": {"type": "string"},
            },
            "additionalProperties": False,
        },
    )
    legend_schema_v2: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"live": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    row_item_v1: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "style": {
                    "type": "object",
                    "properties": {"legend": legend_schema_v1},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        },
    )
    row_item_v2: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "style": {
                    "type": "object",
                    "properties": {"legend": legend_schema_v2},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        },
    )
    old_schema: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"rows": {"type": "array", "items": row_item_v1}},
            "additionalProperties": False,
        },
    )
    new_schema: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"rows": {"type": "array", "items": row_item_v2}},
            "additionalProperties": False,
        },
    )
    catalog = _catalog({V1: old_schema, V2: new_schema})
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )

    yaml_text = (
        "rows:\n  - style:\n      legend:\n        dead: gone\n        live: keep\n"
    )

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "dead:" not in result
    assert "live: keep" in result
    assert "rows:" in result


def test_deletion_raises_on_flow_style_yaml() -> None:
    """Deletion in a flow-style mapping raises MigrationError instead of silently no-oping.

    A line like ``legend: {dead: true, live: keep}`` is legal YAML but the text
    editor's line-regex only matches block-mapping key lines, so it cannot remove
    ``dead`` without reformatting the whole mapping.  Without an equality check
    the file comes back byte-identical while the in-memory result has ``dead``
    gone — the user is told to run ``dft migrate`` on a file that already reports
    as current.  The equality check catches this before returning a wrong result.
    """
    catalog = _legend_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )

    yaml_text = "legend: {dead: true, live: keep}\n"

    with pytest.raises(MigrationError, match="flow-style"):
        migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)


def test_deletion_raises_on_block_scalar_containing_key() -> None:
    """Deletion raises MigrationError instead of silently corrupting block-scalar content.

    A ``text: |`` block scalar whose content contains a line like ``dead: true``
    looks identical to a real YAML key to the line-regex scanner.  Without an
    equality check the line is deleted from inside the prose and the file is
    returned silently corrupted.  The equality check against the in-memory result
    catches the mismatch before returning.
    """
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "dead": {"type": "boolean"},
                "text": {"type": "string"},
                "live": {"type": "string"},
            },
            "additionalProperties": False,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "live": {"type": "string"},
            },
            "additionalProperties": False,
        },
    )
    catalog = _catalog({V1: old, V2: new})
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("dead",))],
        catalog=catalog,
    )

    yaml_text = "dead: true\ntext: |\n    dead: true\n    Prose after.\nlive: keep\n"

    with pytest.raises(MigrationError, match="block scalar"):
        migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)


def test_version_module_with_only_deletions_is_accepted() -> None:
    """A version module with deletions() but no moves() is valid."""
    import sys
    import types

    from dbt_charts.core.compile.migrations.migrations import _load_migration_module

    dotted = "dbt_charts.core.compile.migrations.versions.v9_9_9"
    fake = types.ModuleType(dotted)
    fake.deletions = lambda *a, **kw: ()  # type: ignore[attr-defined]

    sys.modules[dotted] = fake
    try:
        module = _load_migration_module(dotted)
        assert module is fake
    finally:
        del sys.modules[dotted]


def _orphan_parent_catalog() -> YamlSchemaCatalog:
    """V1 has legend.dead + live; V2 has only live (no legend key at all)."""
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "legend": {
                    "type": "object",
                    "properties": {"dead": {"type": "boolean"}},
                    "additionalProperties": False,
                },
                "live": {"type": "string"},
            },
            "additionalProperties": False,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"live": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    return _catalog({V1: old, V2: new})


def test_deletion_cleans_up_orphaned_parent_in_mapping() -> None:
    """Deleting the sole child of a parent dict also removes the empty parent."""
    catalog = _orphan_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )

    result = migrate_mapping(
        {"legend": {"dead": True}, "live": "keep"},
        catalog=catalog,
        registry=registry,
    )

    assert "legend" not in result
    assert result == {"live": "keep"}


def test_deletion_cleans_up_orphaned_parent_in_yaml_text() -> None:
    """Deleting the sole child of a parent mapping also removes the orphaned parent line."""
    catalog = _orphan_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )

    yaml_text = "legend:\n  dead: true\nlive: keep\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "legend" not in result
    assert "live: keep" in result


def _sibling_parent_catalog() -> YamlSchemaCatalog:
    """V1 has legend.{dead,live} + other.dead; V2 has legend.{live} + other.dead."""
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "legend": {
                    "type": "object",
                    "properties": {
                        "dead": {"type": "boolean"},
                        "live": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "other": {
                    "type": "object",
                    "properties": {"dead": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "legend": {
                    "type": "object",
                    "properties": {"live": {"type": "string"}},
                    "additionalProperties": False,
                },
                "other": {
                    "type": "object",
                    "properties": {"dead": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    )
    return _catalog({V1: old, V2: new})


def test_deletion_does_not_affect_sibling_parent_in_mapping() -> None:
    """A tail key under a different parent must not be deleted.

    The guard in _try_delete_tail checks the parent key before descending.
    Regressing it to an unconditional delete would remove ``other.dead``
    when the declared deletion only targets ``legend.dead``.
    """
    catalog = _sibling_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )

    result = migrate_mapping(
        {"legend": {"dead": True, "live": "keep"}, "other": {"dead": "preserved"}},
        catalog=catalog,
        registry=registry,
    )

    assert result["other"] == {"dead": "preserved"}


def test_deletion_does_not_affect_sibling_parent_in_yaml_text() -> None:
    """A tail key under a different parent must not be deleted from YAML text.

    The parent-chain guard in _yaml_parent_chain_matches verifies that the
    enclosing block is ``legend``, not ``other``.  Regressing it to an
    unconditional delete would strip the ``dead`` line from the ``other`` block.
    """
    catalog = _sibling_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )

    yaml_text = "legend:\n  dead: true\n  live: keep\nother:\n  dead: preserved\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "other:\n  dead: preserved" in result
    assert "legend:\n  dead" not in result


def _open_legend_catalog() -> YamlSchemaCatalog:
    """V1 has legend.{dead,live} + open additional properties; V2 has legend.{live}."""
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "legend": {
                    "type": "object",
                    "properties": {
                        "dead": {"type": "boolean"},
                        "live": {"type": "string"},
                    },
                    "additionalProperties": False,
                }
            },
            "additionalProperties": True,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "legend": {
                    "type": "object",
                    "properties": {"live": {"type": "string"}},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": True,
        },
    )
    return _catalog({V1: old, V2: new})


def test_deletion_does_not_remove_null_valued_key_in_yaml_text() -> None:
    """A null-valued block key unrelated to the deletion must not be pruned.

    _prune_childless_ancestors is scoped to ancestors of deleted lines; a key
    that is not on the ancestor walk is never a candidate, regardless of how
    many children it has.
    """
    catalog = _open_legend_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    # description: has a null value — no children, unrelated to the deletion
    yaml_text = "description:\nlegend:\n  dead: true\n  live: keep\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "description:" in result
    assert "dead:" not in result


def test_deletion_does_not_remove_comment_only_block_in_yaml_text() -> None:
    """A key whose only block content is comments must not be pruned.

    The key is not on the ancestor walk of any deleted line, so it is never a
    candidate — candidate scoping, not child counting, provides this guarantee.
    """
    catalog = _open_legend_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "notes:\n  # todo\nlegend:\n  dead: true\n  live: keep\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "notes:" in result
    assert "dead:" not in result


def test_deletion_prunes_parent_with_inline_comment_in_yaml_text() -> None:
    """A parent key with a trailing inline comment is treated as block-only.

    ``legend:  # appearance`` has a null value (the comment is not the value).
    When the deletion empties the block, the parent key line — comment and
    all — must be pruned, not left behind as a dangling null entry that
    diverges from the in-memory result.
    """
    catalog = _open_legend_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    # legend has a trailing comment; dead is its only child → parent must be pruned.
    # keep: provides a surviving root key so the final document is non-empty.
    yaml_text = "keep: survivor\nlegend:  # appearance\n  dead: true\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "keep: survivor" in result
    assert "legend:" not in result
    assert "dead:" not in result


def test_deletion_prunes_style_parent_with_inline_comment_in_yaml_text() -> None:
    """Comment-bearing intermediate keys are pruned when their only child goes.

    Verifies the fixpoint propagation: style: # comment → legend: # comment →
    dead: true.  Both are treated as block-only; both are pruned.
    """
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "style": {
                    "type": "object",
                    "properties": {
                        "legend": {
                            "type": "object",
                            "properties": {"dead": {"type": "boolean"}},
                            "additionalProperties": False,
                        }
                    },
                    "additionalProperties": False,
                }
            },
            "additionalProperties": True,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "style": {
                    "type": "object",
                    "properties": {
                        "legend": {
                            "type": "object",
                            "additionalProperties": False,
                        }
                    },
                    "additionalProperties": False,
                }
            },
            "additionalProperties": True,
        },
    )
    catalog = _catalog({V1: old, V2: new})
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("style", "legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "keep: survivor\nstyle:  # style\n  legend:  # legend\n    dead: true\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "keep: survivor" in result
    assert "style:" not in result
    assert "legend:" not in result
    assert "dead:" not in result


def test_deletion_does_not_remove_column_zero_sequence_key_in_yaml_text() -> None:
    """A key followed by a column-0 sequence item must not be pruned.

    ``rows:\\n- item`` is PyYAML's default emit for list-valued keys.  The
    sequence item has the same indentation as ``rows:``, so it fails the
    child_indent > key_indent check — the key has no counted children and
    must not be deleted.
    """
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "rows": {"type": "array", "items": {"type": "string"}},
                "legend": {
                    "type": "object",
                    "properties": {
                        "dead": {"type": "boolean"},
                        "live": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "rows": {"type": "array", "items": {"type": "string"}},
                "legend": {
                    "type": "object",
                    "properties": {"live": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    )
    catalog = _catalog({V1: old, V2: new})
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "rows:\n- a\nlegend:\n  dead: true\n  live: keep\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "rows:\n- a\n" in result
    assert "dead:" not in result


def test_deletion_does_not_remove_preexisting_empty_dict_in_mapping() -> None:
    """A pre-existing empty mapping (authored style: {}) must not be silently deleted.

    _delete_tail_recursive only removes a child dict when this deletion caused
    it to become empty.  An empty dict that existed before the migration ran
    must be passed through unchanged.
    """
    old: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "charts": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "style": {
                                "type": "object",
                                "properties": {
                                    "legend": {
                                        "type": "object",
                                        "properties": {
                                            "dead": {"type": "boolean"},
                                        },
                                        "additionalProperties": False,
                                    },
                                },
                                "additionalProperties": True,
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    )
    new: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "charts": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "style": {
                                "type": "object",
                                "properties": {
                                    "legend": {
                                        "type": "object",
                                        "additionalProperties": False,
                                    },
                                },
                                "additionalProperties": False,
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    )
    catalog = _catalog({V1: old, V2: new})
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    # chart a has the deletion target; chart b has a pre-existing empty style;
    # chart c has an empty legend inside style.  The migration must strip
    # legend.dead from a but leave both b's style: {} and c's style: {legend: {}}
    # intact — _try_delete_tail must return False when the key is absent, not True.
    mapping = {
        "charts": {
            "a": {"type": "bar", "style": {"legend": {"dead": True}}},
            "b": {"type": "bar", "style": {}},
            "c": {"type": "bar", "style": {"legend": {}}},
        }
    }

    result = migrate_mapping(mapping, catalog=catalog, registry=registry)

    assert result["charts"]["b"]["style"] == {}
    assert result["charts"]["c"]["style"] == {"legend": {}}


def test_deletion_emptying_board_raises_parse_error_in_yaml_text_migration() -> None:
    """Deleting every key raises ParseError — migrate_paths catches it as MigrateError.

    When the only content is the deleted key, the pruner empties the file and
    load_yaml_mapping raises ParseError on the null document.  migrate_yaml_text
    lets it propagate; migrate_paths widens its handler to record a MigrateError
    instead of crashing the run.
    """
    catalog = _orphan_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "legend:\n  dead: true\n"

    with pytest.raises(ParseError, match="Empty YAML document"):
        migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)


def test_deletion_emptying_board_with_comment_raises_parse_error() -> None:
    """Interior comment plus deleted key also raises ParseError.

    After the MEDIUM fix prunes interior comments alongside the block, the
    resulting document is empty rather than comment-only; ParseError is still
    raised and migrate_paths still records it as MigrateError.
    """
    catalog = _orphan_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "legend:\n  # why we set this\n  dead: true\n"

    with pytest.raises(ParseError, match="Empty YAML document"):
        migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)


def test_deletion_does_not_orphan_interior_comment_in_yaml_text() -> None:
    """Comments inside a pruned block must be deleted along with the block.

    Without the fix, the pruner marks the parent key for deletion but skips
    comment lines during the child scan, leaving them at the wrong indentation.
    """
    catalog = _open_legend_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "legend:\n  # why\n  dead: true\ntitle: T\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "legend" not in result
    assert "# why" not in result
    assert "title: T" in result


def test_pruned_block_does_not_delete_trailing_column_zero_comment() -> None:
    """A column-0 comment after a pruned block must survive.

    _prune_childless_ancestors consumed every blank/comment line after the
    block because the cleanup loop had no bound on the block's extent.  A
    column-0 banner comment that follows the pruned block must be preserved.
    """
    catalog = _orphan_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "legend:\n  dead: true\n\n# banner\nlive: keep\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "legend" not in result
    assert "# banner" in result
    assert "live: keep" in result


def test_pruned_block_does_not_delete_sibling_leading_comment() -> None:
    """A comment immediately after a pruned block belongs to the next key.

    When a sibling key's leading comment sits directly after the pruned
    block, the pruner must not consume it.
    """
    catalog = _orphan_parent_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V1, V2, ("legend", "dead"))],
        catalog=catalog,
    )
    yaml_text = "legend:\n  dead: true\n# describes live\nlive: keep\n"

    result = migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)

    assert "legend" not in result
    assert "# describes live" in result
    assert "live: keep" in result


def test_pending_moves_are_loaded_and_applied() -> None:
    """A pending module's (current.py) moves() land in the registry, not just avoid raising.

    catalog.current_schema is a fully computed live schema, generated the same
    way as any frozen snapshot -- Deletion already validates its own _CURRENT
    carve-out against it. Move gets the same treatment. This deliberately does
    not borrow whatever rename versions/current.py happens to declare right
    now (that content gets frozen away at every release, which would break
    this test on a schedule) -- it uses two real, structural top-level
    AuthoredBoard fields (title/id) that are certain to keep existing, so the
    returned Move is genuinely validated against the real packaged catalog,
    not just accepted because it's empty.
    """
    import sys
    import types

    from dbt_charts.core.compile.migrations.migrations import _board_migration_context

    pending_dotted = "dbt_charts.core.compile.migrations.versions.current"
    fake_pending = types.ModuleType(pending_dotted)
    fake_pending.moves = lambda source, target, *, catalog: (  # type: ignore[attr-defined]
        Move(source, target, ("title",), ("id",)),
    )

    original = sys.modules.get(pending_dotted)
    sys.modules[pending_dotted] = fake_pending
    _board_migration_context.cache_clear()
    try:
        catalog, registry = _board_migration_context()
        moves = registry.transition_from(catalog.latest.version)
        assert any(
            move.old_path == ("title",) and move.new_path == ("id",) for move in moves
        )
    finally:
        if original is not None:
            sys.modules[pending_dotted] = original
        else:
            sys.modules.pop(pending_dotted, None)
        _board_migration_context.cache_clear()


def _current_boundary_move_catalog() -> YamlSchemaCatalog:
    """V2 is latest with 'old'; current_schema has 'new' (unreleased rename)."""
    latest_schema: JsonObject = _schema("old")
    current_schema: JsonObject = _schema("new")
    entries = (
        YamlSchemaEntry(
            version=V2,
            released_at=date(2026, 6, 1),
            filename=f"{V2}.json",
            sha256="test2",
            predecessor=V1,
        ),
        YamlSchemaEntry(
            version=V1,
            released_at=date(2026, 5, 1),
            filename=f"{V1}.json",
            sha256="test1",
            predecessor=None,
        ),
    )
    return YamlSchemaCatalog(
        entries, {V1: _schema("ancient"), V2: latest_schema}, current_schema
    )


def test_move_current_target_accepts_present_new_path() -> None:
    """A Move to _CURRENT validates when the new path exists in current_schema."""
    catalog = _current_boundary_move_catalog()

    registry = MigrationRegistry(
        [Move(V2, _CURRENT, ("old",), ("new",))],
        catalog=catalog,
    )

    assert registry.transition_from(V2)


def test_move_current_target_path_must_be_present_in_current_schema() -> None:
    """A Move's new path missing from current_schema must not be declared."""
    catalog = _current_boundary_move_catalog()

    with pytest.raises(MigrationError, match="absent from"):
        MigrationRegistry(
            [Move(V2, _CURRENT, ("old",), ("missing",))],
            catalog=catalog,
        )


def test_move_current_source_must_be_latest_schema() -> None:
    """A Move targeting _CURRENT must source from the latest frozen schema."""
    catalog = _current_boundary_move_catalog()

    with pytest.raises(MigrationError, match="latest frozen schema"):
        MigrationRegistry(
            [Move(V1, _CURRENT, ("ancient",), ("new",))],
            catalog=catalog,
        )


def test_migrates_old_shape_document_via_pending_move() -> None:
    """An old-shape document reaches the current shape through a pending Move."""
    catalog = _current_boundary_move_catalog()
    registry = MigrationRegistry(
        [Move(V2, _CURRENT, ("old",), ("new",))],
        catalog=catalog,
    )

    result = migrate_mapping({"old": "value"}, catalog=catalog, registry=registry)

    assert result == {"new": "value"}


# ---------------------------------------------------------------------------
# ConditionalMove primitive
# ---------------------------------------------------------------------------


def _conditional_move_catalog() -> YamlSchemaCatalog:
    """V1 has charts.*.style.tone + charts.*.support.label;
    V2 has charts.*.support.{label,tone} but NO style.tone.

    Both schemas use additionalProperties: false on the chart so that
    documents with style.tone are recognised as V1 (not V2/current),
    triggering the ConditionalMove.
    """
    chart_v1: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "style": {
                    "type": "object",
                    "properties": {"tone": {"type": "string"}},
                    "additionalProperties": False,
                },
                "support": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    )
    chart_v2: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "support": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "tone": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    )
    v1: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "charts": {"type": "object", "additionalProperties": chart_v1}
            },
            "additionalProperties": True,
        },
    )
    v2: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "charts": {"type": "object", "additionalProperties": chart_v2}
            },
            "additionalProperties": True,
        },
    )
    return _catalog({V1: v1, V2: v2})


def _cond_move(catalog: YamlSchemaCatalog) -> ConditionalMove:
    return ConditionalMove(
        source_schema=V1,
        target_schema=V2,
        chart_type="kpi",
        old_tail=("style", "tone"),
        new_tail=("support", "tone"),
        sibling_tail=("support",),
        drop_warning="Dropped tone from chart {chart}",
    )


def test_conditional_move_validates_and_accepts_correctly() -> None:
    catalog = _conditional_move_catalog()
    registry = MigrationRegistry([], [], [_cond_move(catalog)], catalog=catalog)
    assert registry.conditional_moves_from(V1)


def test_conditional_move_moves_tone_into_existing_support() -> None:
    catalog = _conditional_move_catalog()
    registry = MigrationRegistry([], [], [_cond_move(catalog)], catalog=catalog)
    raw = {
        "charts": {
            "k1": {
                "type": "kpi",
                "style": {"tone": "positive"},
                "support": {"label": "x"},
            }
        }
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SchemaMigrationWarning)
        result = migrate_mapping(raw, catalog=catalog, registry=registry)

    chart = result["charts"]["k1"]
    assert chart["support"]["tone"] == "positive"
    assert chart["support"]["label"] == "x"
    # style.tone was the only style key → style is cleaned up
    assert "style" not in chart


def test_conditional_move_drops_and_warns_when_sibling_absent() -> None:
    catalog = _conditional_move_catalog()
    registry = MigrationRegistry([], [], [_cond_move(catalog)], catalog=catalog)
    raw = {"charts": {"k1": {"type": "kpi", "style": {"tone": "positive"}}}}

    with pytest.warns(SchemaMigrationWarning, match="k1"):
        result = migrate_mapping(raw, catalog=catalog, registry=registry)

    chart = result["charts"]["k1"]
    assert "tone" not in str(chart)
    assert "style" not in chart


def test_conditional_move_conflict_raises_when_destination_already_set() -> None:
    """Conflict: both style.tone (old) and support.tone (new) present → error.

    Tests _apply_conditional_move directly — schema recognition is not the
    behaviour being exercised, only the conflict detection.
    """
    from copy import deepcopy

    from dbt_charts.core.compile.migrations.migrations import _apply_conditional_move

    catalog = _conditional_move_catalog()
    rule = _cond_move(catalog)
    document = {
        "charts": {
            "k1": {
                "type": "kpi",
                "style": {"tone": "positive"},
                "support": {"label": "x", "tone": "negative"},
            }
        }
    }
    result = deepcopy(document)

    with pytest.raises(MigrationConflictError, match="k1"):
        _apply_conditional_move(result, rule)


def test_conditional_move_skips_non_matching_chart_type() -> None:
    """A callout chart with the same style.tone path must not be touched.

    Tests _apply_conditional_move directly — the synthetic V2 schema
    purposely excludes ``style`` to force V1 recognition for KPI documents,
    but the callout test doesn't need schema round-trip.  The important
    invariant is that _apply_conditional_move_recursive only acts on
    dicts whose ``type`` equals the rule's chart_type.
    """
    from copy import deepcopy

    from dbt_charts.core.compile.migrations.migrations import _apply_conditional_move

    catalog = _conditional_move_catalog()
    rule = _cond_move(catalog)
    document = {"charts": {"c1": {"type": "callout", "style": {"tone": "warning"}}}}
    result = deepcopy(document)

    drop_warnings = _apply_conditional_move(result, rule)

    # callout's style.tone must survive untouched, no warnings emitted
    assert result["charts"]["c1"]["style"]["tone"] == "warning"
    assert not drop_warnings


def test_conditional_move_absent_source_key_is_noop() -> None:
    catalog = _conditional_move_catalog()
    registry = MigrationRegistry([], [], [_cond_move(catalog)], catalog=catalog)
    raw = {"charts": {"k1": {"type": "kpi", "support": {"label": "x"}}}}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SchemaMigrationWarning)
        result = migrate_mapping(raw, catalog=catalog, registry=registry)

    assert result == {"charts": {"k1": {"type": "kpi", "support": {"label": "x"}}}}


def test_conditional_move_validates_wrong_adjacency_raises() -> None:
    """A ConditionalMove must target the immediately succeeding schema."""
    catalog = _catalog({V1: _schema("a"), V2: _schema("a"), V3: _schema("a")})

    with pytest.raises(MigrationError, match="immediately succeeding"):
        MigrationRegistry(
            [],
            [],
            [
                ConditionalMove(
                    source_schema=V1,
                    target_schema=V3,
                    chart_type="kpi",
                    old_tail=("a",),
                    new_tail=("a",),
                    sibling_tail=("a",),
                    drop_warning="dropped {chart}",
                )
            ],
            catalog=catalog,
        )


def test_conditional_move_current_target_source_must_be_latest() -> None:
    """ConditionalMove targeting _CURRENT must source from the latest frozen schema."""
    catalog = _current_boundary_catalog()

    with pytest.raises(MigrationError, match="latest frozen schema"):
        MigrationRegistry(
            [],
            [],
            [
                ConditionalMove(
                    source_schema=V1,
                    target_schema=_CURRENT,
                    chart_type="kpi",
                    old_tail=("ancient",),
                    new_tail=("live",),
                    sibling_tail=("live",),
                    drop_warning="dropped {chart}",
                )
            ],
            catalog=catalog,
        )


def test_conditional_move_validates_source_tail_must_exist() -> None:
    catalog = _conditional_move_catalog()

    with pytest.raises(MigrationError, match="absent from"):
        MigrationRegistry(
            [],
            [],
            [
                ConditionalMove(
                    source_schema=V1,
                    target_schema=V2,
                    chart_type="kpi",
                    old_tail=("nonexistent", "tone"),
                    new_tail=("support", "tone"),
                    sibling_tail=("support",),
                    drop_warning="dropped {chart}",
                )
            ],
            catalog=catalog,
        )


def test_conditional_move_validates_destination_tail_must_exist() -> None:
    catalog = _conditional_move_catalog()

    with pytest.raises(MigrationError, match="absent from"):
        MigrationRegistry(
            [],
            [],
            [
                ConditionalMove(
                    source_schema=V1,
                    target_schema=V2,
                    chart_type="kpi",
                    old_tail=("style", "tone"),
                    new_tail=("nonexistent", "tone"),
                    sibling_tail=("support",),
                    drop_warning="dropped {chart}",
                )
            ],
            catalog=catalog,
        )


def test_conditional_move_nested_board_dict_recurse() -> None:
    """ConditionalMove reaches chart dicts nested under rows/cols dicts.

    Tests _apply_conditional_move directly: the synthetic catalog has
    additionalProperties:true at document root (rows/cols are unconstrained),
    so a rows-only document matches both schemas → schema recognition
    returns _CURRENT → no migration loop.  Testing _apply_conditional_move
    directly isolates the recursive walk behaviour without the schema gate.
    """
    from copy import deepcopy

    from dbt_charts.core.compile.migrations.migrations import _apply_conditional_move

    catalog = _conditional_move_catalog()
    rule = _cond_move(catalog)
    document = {
        "rows": [
            {
                "cols": [
                    {
                        "charts": {
                            "nested_kpi": {
                                "type": "kpi",
                                "style": {"tone": "positive"},
                                "support": {"label": "x"},
                            }
                        }
                    }
                ]
            }
        ]
    }
    result = deepcopy(document)

    drop_warnings = _apply_conditional_move(result, rule)

    chart = result["rows"][0]["cols"][0]["charts"]["nested_kpi"]
    assert chart["support"]["tone"] == "positive"
    assert "style" not in chart
    assert not drop_warnings


def test_conditional_moves_from_returns_empty_for_unknown_schema() -> None:
    catalog = _conditional_move_catalog()
    registry = MigrationRegistry([], [], [_cond_move(catalog)], catalog=catalog)
    assert registry.conditional_moves_from("9.9.9") == ()


def test_version_module_with_only_conditional_moves_is_accepted() -> None:
    """A version module with only conditional_moves() but no moves/deletions is valid."""
    import sys
    import types

    from dbt_charts.core.compile.migrations.migrations import _load_migration_module

    dotted = "dbt_charts.core.compile.migrations.versions.v9_9_9"
    fake = types.ModuleType(dotted)
    fake.conditional_moves = lambda *a, **kw: ()  # type: ignore[attr-defined]

    sys.modules[dotted] = fake
    try:
        module = _load_migration_module(dotted)
        assert module is fake
    finally:
        del sys.modules[dotted]


# ---------------------------------------------------------------------------
# Pending deletions regression: marks.square / marks.tick / marks.trail
# ---------------------------------------------------------------------------


def _marks_boundary_catalog() -> YamlSchemaCatalog:
    """V2 is latest with marks.square/tick/trail; current_schema has only marks.rule.

    Mirrors the actual pending deletion: GlobalMarksStyle removed the three dead
    mark slots, so a board that authored marks.tick (etc.) must be migrated.
    """
    marks_with_dead: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "square": {"type": "object", "additionalProperties": True},
                "tick": {"type": "object", "additionalProperties": True},
                "trail": {"type": "object", "additionalProperties": True},
                "rule": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": False,
        },
    )
    marks_without_dead: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"rule": {"type": "object", "additionalProperties": True}},
            "additionalProperties": False,
        },
    )
    latest_schema: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"marks": marks_with_dead},
            "additionalProperties": True,
        },
    )
    current_schema: JsonObject = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"marks": marks_without_dead},
            "additionalProperties": True,
        },
    )
    entries = (
        YamlSchemaEntry(
            version=V2,
            released_at=date(2026, 6, 1),
            filename=f"{V2}.json",
            sha256="test2",
            predecessor=V1,
        ),
        YamlSchemaEntry(
            version=V1,
            released_at=date(2026, 5, 1),
            filename=f"{V1}.json",
            sha256="test1",
            predecessor=None,
        ),
    )
    return YamlSchemaCatalog(
        entries, {V1: _schema("ancient"), V2: latest_schema}, current_schema
    )


def test_marks_dead_slots_pending_deletions_strip_their_keys() -> None:
    """marks.square/tick/trail in DELETED_TAILS strip those keys during migration.

    Regression guard: removing any of the three entries from DELETED_TAILS causes
    this test to fail — either the assertion or the migrate_mapping check.
    """
    from dbt_charts.core.compile.migrations.versions.v0_5_0 import DELETED_TAILS

    marks_deletions = {t for t in DELETED_TAILS if t[0] == "marks"}
    assert marks_deletions == {
        ("marks", "square"),
        ("marks", "tick"),
        ("marks", "trail"),
    }

    catalog = _marks_boundary_catalog()
    registry = MigrationRegistry(
        [],
        [Deletion(V2, _CURRENT, tail) for tail in sorted(marks_deletions)],
        catalog=catalog,
    )

    result = migrate_mapping(
        {
            "marks": {
                "tick": {"stroke": {}},
                "square": {"opacity": 0.5},
                "trail": {},
                "rule": {"stroke": {}},
            }
        },
        catalog=catalog,
        registry=registry,
    )

    assert result == {"marks": {"rule": {"stroke": {}}}}
