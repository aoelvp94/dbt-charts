"""Recognize retained board schemas and apply declared structural migrations."""

from __future__ import annotations

import copy
import dataclasses
import importlib
import json
import re
import types
import warnings
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from functools import cache
from typing import TYPE_CHECKING, Annotated, TypeAlias, get_args, get_origin

from importlib_resources import files
from jsonschema import Draft7Validator
from pydantic import BaseModel, ValidationError

from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    JsonObject,
    JsonValue,
    YamlSchemaCatalog,
)

if TYPE_CHECKING:
    from dbt_charts.core.compile.authoring.yaml_patch import ScalarLeaf

YamlKeyPath: TypeAlias = tuple[str, ...]

# What a value map may map. Narrower than the setter's `ScalarLeaf`, which grew
# a `list[str]` arm for multi-value controls: a rename maps one spelling of a
# scalar to another, and `_mapped_value` refuses anything else at runtime.
MappedScalar: TypeAlias = str | int | float | bool

# Sentinel string returned by _recognize() and used as the loop-exit condition
# in migrate_mapping/migrate_yaml_text when the mapping already satisfies the
# live (unreleased) schema.  Also used as the target_schema on pending Deletion/
# Move entries loaded from versions/current.py.
_CURRENT = "current"


def _resolve_schema(catalog: YamlSchemaCatalog, schema: str) -> JsonObject:
    """Resolve a schema identifier to its JSON Schema, including ``_CURRENT``.

    ``catalog.current_schema`` is a fully computed live schema (generated the
    same way as any frozen snapshot), so this is a single place both the
    ``_CURRENT``-targeting boundary and every frozen boundary go through.
    """
    return catalog.current_schema if schema == _CURRENT else catalog.schema_for(schema)


class MigrationError(ValueError):
    """A raw YAML migration cannot be safely applied."""


class MigrationConflictError(MigrationError):
    """A move would overwrite an authored destination value."""


class UnsupportedSchemaError(MigrationError):
    """The mapping matches none of the retained grammars."""


class SchemaVersionTooOldError(MigrationError):
    """Transparent loading no longer supports the recognized schema."""


class SchemaMigrationWarning(UserWarning):
    """A board was migrated in memory and should be rewritten with ``dct migrate``."""


@dataclasses.dataclass(frozen=True)
class Move:
    """One resolved adjacent structural rename or move."""

    source_schema: str
    target_schema: str
    old_path: YamlKeyPath
    new_path: YamlKeyPath
    # When set, the source value is looked up here before assignment; raises
    # MigrationError for any value absent from the map (never passes unmapped
    # values through silently).  Use only for total, lossless value mappings.
    # Mapping isn't hashable -- excluded from __hash__, kept in __eq__.
    value_map: Mapping[MappedScalar, MappedScalar] | None = dataclasses.field(
        default=None, hash=False
    )


@dataclasses.dataclass(frozen=True)
class Deletion:
    """One resolved adjacent structural deletion — a path that existed in source but not target."""

    source_schema: str
    target_schema: str
    path: YamlKeyPath


@dataclasses.dataclass(frozen=True)
class ConditionalMove:
    """A relocation that fires only when its destination's parent mapping already exists.

    Restricted to charts whose ``type`` key equals ``chart_type``, so a
    same-named field on an unrelated chart family (e.g. callout's own
    ``style.tone``) is never touched.  ``old_tail``, ``new_tail``, and
    ``sibling_tail`` are relative to the chart mapping itself (not the full
    document root) so the rule applies uniformly regardless of nesting depth
    under rows/cols/grid/tabs.

    When the sibling at ``sibling_tail`` does not exist in the chart, the
    value at ``old_tail`` is dropped (not migrated) and a warning is emitted,
    naming the chart via the ``{chart}`` placeholder in ``drop_warning``.
    """

    source_schema: str
    target_schema: str
    chart_type: str
    old_tail: YamlKeyPath
    new_tail: YamlKeyPath
    sibling_tail: YamlKeyPath
    drop_warning: str  # may use ``{chart}`` placeholder


class MigrationRegistry:
    """Validated adjacent transitions assembled from tail-rename tables."""

    def __init__(
        self,
        moves: Iterable[Move],
        deletions: Iterable[Deletion] = (),
        conditional_moves: Iterable[ConditionalMove] = (),
        *,
        catalog: YamlSchemaCatalog,
    ) -> None:
        self.moves = tuple(moves)
        self.deletions = tuple(deletions)
        self.conditional_moves = tuple(conditional_moves)
        self._catalog = catalog
        self._moves_by_source: dict[str, tuple[Move, ...]] = {}
        for move in self.moves:
            moves_for_schema = self._moves_by_source.setdefault(move.source_schema, ())
            self._moves_by_source[move.source_schema] = (*moves_for_schema, move)
        self._deletions_by_source: dict[str, tuple[Deletion, ...]] = {}
        for deletion in self.deletions:
            dels_for_schema = self._deletions_by_source.setdefault(
                deletion.source_schema, ()
            )
            self._deletions_by_source[deletion.source_schema] = (
                *dels_for_schema,
                deletion,
            )
        self._cond_moves_by_source: dict[str, tuple[ConditionalMove, ...]] = {}
        for cond_move in self.conditional_moves:
            existing = self._cond_moves_by_source.setdefault(
                cond_move.source_schema, ()
            )
            self._cond_moves_by_source[cond_move.source_schema] = (
                *existing,
                cond_move,
            )
        self._validate()

    def transition_from(self, identifier: str) -> tuple[Move, ...]:
        if identifier not in self._moves_by_source:
            return ()
        return self._moves_by_source[identifier]

    def deletions_from(self, identifier: str) -> tuple[Deletion, ...]:
        if identifier not in self._deletions_by_source:
            return ()
        return self._deletions_by_source[identifier]

    def conditional_moves_from(self, identifier: str) -> tuple[ConditionalMove, ...]:
        if identifier not in self._cond_moves_by_source:
            return ()
        return self._cond_moves_by_source[identifier]

    def _validate(self) -> None:
        versions = self._catalog.versions
        positions = {version: index for index, version in enumerate(versions)}
        for move in self.moves:
            source_index = positions.get(move.source_schema)
            if source_index is None:
                raise MigrationError(
                    f"Move {_format_path(move.old_path)!r} → "
                    f"{_format_path(move.new_path)!r} references a schema "
                    "that is not retained"
                )
            if move.target_schema == _CURRENT:
                if move.source_schema != self._catalog.latest.version:
                    raise MigrationError(
                        f"Move {_format_path(move.old_path)!r} → "
                        f"{_format_path(move.new_path)!r} targeting 'current' "
                        "must source from the latest frozen schema"
                    )
            else:
                target_index = positions.get(move.target_schema)
                if target_index is None:
                    raise MigrationError(
                        f"Move {_format_path(move.old_path)!r} → "
                        f"{_format_path(move.new_path)!r} references a schema "
                        "that is not retained"
                    )
                if target_index != source_index - 1:
                    raise MigrationError(
                        f"Move {_format_path(move.old_path)!r} → "
                        f"{_format_path(move.new_path)!r} must target the "
                        "immediately succeeding schema"
                    )
            target_schema_obj = _resolve_schema(self._catalog, move.target_schema)
            if not _schema_path_exists(target_schema_obj, move.new_path):
                raise MigrationError(
                    f"Move destination path {_format_path(move.new_path)!r} is absent from "
                    f"{move.target_schema}"
                )
            if not _schema_path_exists(
                self._catalog.schema_for(move.source_schema), move.old_path
            ):
                raise MigrationError(
                    f"Move source path {_format_path(move.old_path)!r} is absent from "
                    f"{move.source_schema}"
                )
        for deletion in self.deletions:
            source_index = positions.get(deletion.source_schema)
            if source_index is None:
                raise MigrationError(
                    f"Deletion at {_format_path(deletion.path)!r} references a schema "
                    "that is not retained"
                )
            if deletion.target_schema == _CURRENT:
                if deletion.source_schema != self._catalog.latest.version:
                    raise MigrationError(
                        f"Deletion at {_format_path(deletion.path)!r} targeting 'current' "
                        "must source from the latest frozen schema"
                    )
            else:
                target_index = positions.get(deletion.target_schema)
                if target_index is None:
                    raise MigrationError(
                        f"Deletion at {_format_path(deletion.path)!r} references a schema "
                        "that is not retained"
                    )
                if target_index != source_index - 1:
                    raise MigrationError(
                        f"Deletion at {_format_path(deletion.path)!r} must target the "
                        "immediately succeeding schema"
                    )
            target_schema_obj = _resolve_schema(self._catalog, deletion.target_schema)
            if not _schema_has_tail(
                self._catalog.schema_for(deletion.source_schema), deletion.path
            ):
                raise MigrationError(
                    f"Deletion source path {_format_path(deletion.path)!r} is absent from "
                    f"{deletion.source_schema}"
                )
            if _schema_has_tail(target_schema_obj, deletion.path):
                raise MigrationError(
                    f"Deletion path {_format_path(deletion.path)!r} still exists in "
                    f"{deletion.target_schema!r}; the field was not removed in this "
                    "transition — use a Move if the field was renamed, or remove the "
                    "Deletion if the field is still valid"
                )
        for cond_move in self.conditional_moves:
            source_index = positions.get(cond_move.source_schema)
            if source_index is None:
                raise MigrationError(
                    f"ConditionalMove for chart_type={cond_move.chart_type!r} "
                    f"at {_format_path(cond_move.old_tail)!r} references a schema "
                    "that is not retained"
                )
            if cond_move.target_schema == _CURRENT:
                if cond_move.source_schema != self._catalog.latest.version:
                    raise MigrationError(
                        f"ConditionalMove at {_format_path(cond_move.old_tail)!r} "
                        "targeting 'current' must source from the latest frozen schema"
                    )
            else:
                target_index = positions.get(cond_move.target_schema)
                if target_index is None:
                    raise MigrationError(
                        f"ConditionalMove for chart_type={cond_move.chart_type!r} "
                        f"at {_format_path(cond_move.old_tail)!r} references a schema "
                        "that is not retained"
                    )
                if target_index != source_index - 1:
                    raise MigrationError(
                        f"ConditionalMove at {_format_path(cond_move.old_tail)!r} "
                        "must target the immediately succeeding schema"
                    )
            target_schema_obj = _resolve_schema(self._catalog, cond_move.target_schema)
            if not _schema_has_tail(
                self._catalog.schema_for(cond_move.source_schema), cond_move.old_tail
            ):
                raise MigrationError(
                    f"ConditionalMove source tail {_format_path(cond_move.old_tail)!r} "
                    f"is absent from {cond_move.source_schema}"
                )
            if not _schema_has_tail(target_schema_obj, cond_move.new_tail):
                raise MigrationError(
                    f"ConditionalMove destination tail {_format_path(cond_move.new_tail)!r} "
                    f"is absent from {cond_move.target_schema}"
                )


def suffix_rename_moves(
    root_model: type[BaseModel],
    source_schema: str,
    target_schema: str,
    renames: Iterable[tuple[YamlKeyPath, YamlKeyPath]],
    *,
    catalog: YamlSchemaCatalog,
    value_map: Mapping[MappedScalar, MappedScalar] | None = None,
) -> tuple[Move, ...]:
    """Resolve tail-only path renames to Move objects without constructing a registry.

    ``renames`` pairs a *new-path tail* with the corresponding *old-path tail*;
    this walks every occurrence of the new tail in the field tree and substitutes
    the old tail at that same position, keeping the shared prefix. Candidates
    that don't structurally exist in both frozen schemas are silently dropped —
    that keeps this safe to run over the whole field tree without hand-enumerating
    every real position.

    Walk the field tree once and reuse it for every rename tuple — re-walking per
    rename is O(renames * tree_size) and the per-variant axis/scale models made
    tree_size large enough for that to matter.

    ``value_map``, if given, is attached to every ``Move`` this call produces —
    it broadcasts across all of ``renames``, not per-tuple. A rename that needs
    its own value mapping belongs in a separate ``suffix_rename_moves`` call.
    """
    old_schema = catalog.schema_for(source_schema)
    new_schema = _resolve_schema(catalog, target_schema)
    paths = list(_walk_fields(root_model))
    seen: set[tuple[YamlKeyPath, YamlKeyPath]] = set()
    result: list[Move] = []
    for new_tail, old_tail in renames:
        width = len(new_tail)
        for path in paths:
            if len(path) < width or path[-width:] != new_tail:
                continue
            old_path = path[:-width] + old_tail
            key = (old_path, path)
            if key in seen:
                continue
            seen.add(key)
            if _schema_path_exists(old_schema, old_path) and _schema_path_exists(
                new_schema, path
            ):
                result.append(
                    Move(source_schema, target_schema, old_path, path, value_map)
                )
    return tuple(result)


def prepare_board_mapping(
    mapping: Mapping[str, JsonValue],
    *,
    model: type[BaseModel] | None = None,
    allow_expired: bool = False,
) -> JsonObject:
    """Recognize and migrate a raw board-shaped mapping before model validation.

    ``model`` is the currency check: does this mapping already validate
    against the current schema, so migration can be skipped? Defaults to
    ``AuthoredBoard`` for a real, standalone board. Callers handling a
    patch-shaped fragment (a theme YAML's ``style:``-only content, a
    meta.yaml override, an extends target) must pass ``BoardPatch`` —
    ``AuthoredBoard`` carries a "must have layout/chart/text/title/description"
    invariant that no patch can ever satisfy, which would make every current
    patch look like a migration candidate.
    """
    from dbt_charts.core.compile.models.board.authored import AuthoredBoard

    currency_model = model if model is not None else AuthoredBoard

    try:
        currency_model.model_validate(mapping)
    except ValidationError:
        if not _board_has_historical_schemas():
            return dict(mapping)
    else:
        return dict(mapping)

    catalog, registry = _board_migration_context()
    try:
        return migrate_mapping(
            mapping,
            catalog=catalog,
            registry=registry,
            allow_expired=allow_expired,
        )
    except UnsupportedSchemaError:
        # Current Pydantic models admit authoring shorthands that JSON Schema
        # cannot express. Let the parser validate those after recognition fails.
        return dict(mapping)


def migrate_board_yaml_text(yaml_text: str) -> str:
    """Rewrite one retained board grammar to the current grammar."""
    catalog, registry = _board_migration_context()
    return migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)


@cache
def _board_migration_context() -> tuple[YamlSchemaCatalog, MigrationRegistry]:
    """Load and validate the package's immutable migration metadata once.

    Walks catalog.entries newest-to-oldest, skipping the oldest (predecessor
    is None). For each remaining entry, imports the corresponding version module
    from ``migrations.versions``. A missing module means no structural migration
    was declared for that boundary — not an error. Each found module's
    ``moves()``, ``deletions()``, and/or ``conditional_moves()`` functions own
    the migration strategy; the collector stays agnostic to the mechanism.

    After the frozen-version walk, loads the optional pending module
    ``versions/current.py`` unconditionally. If present, its ``moves()``,
    ``deletions()``, and ``conditional_moves()`` functions declare the
    ``catalog.latest.version → _CURRENT`` boundary for any unreleased renames,
    key removals, or conditional relocations in flight. At release time the
    file is renamed to ``versions/v<new_version>.py`` with no content edit.

    ``catalog.current_schema`` is a fully computed live schema (see
    ``YamlSchemaCatalog``), generated the same way as any frozen snapshot —
    so a pending ``Move`` validates its destination path against it exactly
    as a pending ``Deletion`` validates the absence of its path against it,
    and a pending ``ConditionalMove`` validates both tails the same way.
    """
    from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
        load_yaml_schema_catalog,
    )

    catalog = load_yaml_schema_catalog()
    all_moves: list[Move] = []
    all_deletions: list[Deletion] = []
    all_conditional_moves: list[ConditionalMove] = []
    for entry in catalog.entries:
        if entry.predecessor is None:
            continue
        dotted = f"dbt_charts.core.compile.migrations.versions.v{entry.version.replace('.', '_')}"
        module = _load_migration_module(dotted)
        if module is None:
            continue
        if hasattr(module, "moves"):
            all_moves.extend(
                module.moves(entry.predecessor, entry.version, catalog=catalog)
            )
        if hasattr(module, "deletions"):
            all_deletions.extend(
                module.deletions(entry.predecessor, entry.version, catalog=catalog)
            )
        if hasattr(module, "conditional_moves"):
            all_conditional_moves.extend(
                module.conditional_moves(
                    entry.predecessor, entry.version, catalog=catalog
                )
            )
    pending = _load_migration_module(
        "dbt_charts.core.compile.migrations.versions.current"
    )
    if pending is not None:
        if hasattr(pending, "moves"):
            all_moves.extend(
                pending.moves(catalog.latest.version, _CURRENT, catalog=catalog)
            )
        if hasattr(pending, "deletions"):
            all_deletions.extend(
                pending.deletions(catalog.latest.version, _CURRENT, catalog=catalog)
            )
        if hasattr(pending, "conditional_moves"):
            all_conditional_moves.extend(
                pending.conditional_moves(
                    catalog.latest.version, _CURRENT, catalog=catalog
                )
            )
    return catalog, MigrationRegistry(
        all_moves, all_deletions, all_conditional_moves, catalog=catalog
    )


def _load_migration_module(dotted: str) -> types.ModuleType | None:
    """Import *dotted* migration module, returning None if absent."""
    try:
        module = importlib.import_module(dotted)
    except ModuleNotFoundError as exc:
        if exc.name != dotted:
            raise
        return None
    if (
        not hasattr(module, "moves")
        and not hasattr(module, "deletions")
        and not hasattr(module, "conditional_moves")
    ):
        raise MigrationError(
            f"{dotted} was found but does not define "
            "moves(source_schema, target_schema, *, catalog) -> tuple[Move, ...] "
            "or deletions(source_schema, target_schema, *, catalog) -> tuple[Deletion, ...] "
            "or conditional_moves(source_schema, target_schema, *, catalog) -> tuple[ConditionalMove, ...]"
        )
    return module


@cache
def _board_has_historical_schemas() -> bool:
    """Whether the packaged manifest retains a predecessor grammar."""
    manifest = json.loads(
        (files("dbt_charts") / "data" / "schemas" / "yaml" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    schemas = manifest.get("schemas") if isinstance(manifest, dict) else None
    if not isinstance(schemas, list):
        raise ValueError("Dataface YAML schema manifest has no schemas.")
    return len(schemas) > 1


def migrate_mapping(
    mapping: Mapping[str, JsonValue],
    *,
    catalog: YamlSchemaCatalog,
    registry: MigrationRegistry,
    allow_expired: bool = False,
    today: date = date.min,
) -> JsonObject:
    """Return a current-compatible copy of a recognized board mapping.

    The caller chooses ``allow_expired``: normal compilation is bounded by the
    support window, while the explicit migration command may rewrite any
    retained schema.
    """
    identifier = _recognize(mapping, catalog)
    if identifier == _CURRENT:
        return copy.deepcopy(dict(mapping))
    # The latest frozen schema is always transparently migratable — it is the
    # most recent released grammar, and the support window exists to discourage
    # accumulating decades of silent upgrades, not to penalise the newest format.
    if not allow_expired and identifier != catalog.latest.version:
        _enforce_support_window(identifier, catalog, today=today)

    result = copy.deepcopy(dict(mapping))
    while identifier != _CURRENT:
        moves = registry.transition_from(identifier)
        deletions = registry.deletions_from(identifier)
        cond_moves = registry.conditional_moves_from(identifier)
        if not moves and not deletions and not cond_moves:
            break
        for move in moves:
            _apply_move(result, move)
        for deletion in deletions:
            _delete_tail_recursive(result, deletion.path)
        for cond_move in cond_moves:
            drop_warnings = _apply_conditional_move(result, cond_move)
            for msg in drop_warnings:
                # Always emit drop warnings regardless of allow_expired: a dropped
                # value is data loss, not a routine "file needs rewriting" notice.
                # Authors running dct migrate especially need to see this.
                warnings.warn(msg, SchemaMigrationWarning, stacklevel=2)
        identifier = (moves or deletions or cond_moves)[0].target_schema

    # A transition's declared moves may not cover every field a source schema
    # allowed (a deleted field has no lossless Move). Recognizing an older
    # schema and exhausting its transition chain is not proof the result is
    # current-compatible; check explicitly rather than trust silently reaching
    # the current identifier.
    current_errors = _current_schema_rejections(result, catalog)
    if current_errors:
        raise _unsupported_schema_error(current_errors[0])

    if not allow_expired:
        warnings.warn(
            "Dataface migrated this YAML in memory; run `dct migrate` to update "
            "the file.",
            SchemaMigrationWarning,
            stacklevel=2,
        )
    return result


def migrate_yaml_text(
    yaml_text: str,
    *,
    catalog: YamlSchemaCatalog,
    registry: MigrationRegistry,
) -> str:
    """Rewrite declared moves while preserving unrelated YAML text.

    The general in-memory transformer supports any JSON-shaped value. The
    file writer is narrower, for two shapes only: it moves scalar
    block-mapping leaves, and it renames a key in place when the move is a
    pure rename (old and new path share the same parent -- only the final
    segment's spelling differs). A rename never relocates content, so it
    carries no restriction on the value's shape -- an entire nested block
    renames as cleanly as a scalar. Any other non-scalar move (a genuine
    relocation to a different parent) fails instead of reformatting a board
    through a YAML dump/load round trip.
    """
    from dbt_charts.core.compile.authoring.yaml_patch import (
        rename_key_at_path,
        set_board_values,
    )
    from dbt_charts.core.compile.parse.parser import load_yaml_mapping

    raw = load_yaml_mapping(yaml_text)
    identifier = _recognize(raw, catalog)
    if identifier == _CURRENT:
        return yaml_text

    updates: dict[str, ScalarLeaf] = {}
    removals: set[str] = set()
    staged = copy.deepcopy(raw)
    while identifier != _CURRENT:
        moves = registry.transition_from(identifier)
        deletions = registry.deletions_from(identifier)
        if not moves and not deletions:
            break
        for move in moves:
            for parent, key, bindings in list(_source_locations(staged, move.old_path)):
                if isinstance(parent, list):
                    raise MigrationError(
                        f"Cannot rewrite {_format_path(move.old_path)!r}: "
                        "list-item paths require "
                        "manual migration."
                    )
                assert isinstance(key, str)
                value = parent[key]
                source = _substitute_wildcards(move.old_path, bindings)
                destination = _substitute_wildcards(move.new_path, bindings)
                if value is None or not isinstance(value, (str, int, float, bool)):
                    if source[:-1] != destination[:-1]:
                        raise MigrationError(
                            f"Cannot rewrite {_format_path(move.old_path)!r}: "
                            "only scalar block-mapping moves or same-position "
                            "key renames are supported; migrate this field "
                            "manually."
                        )
                    # A rename never relocates content -- any value shape
                    # (including this nested mapping/list) is safe to
                    # rewrite in place; only the key token changes.
                    yaml_text = rename_key_at_path(
                        yaml_text, ".".join(source), destination[-1]
                    )
                else:
                    if move.value_map is not None:
                        value = _mapped_value(move.value_map, move.old_path, value)
                    updates[".".join(destination)] = value
                    removals.add(".".join(source))
            _apply_move(staged, move)
        for deletion in deletions:
            _delete_tail_recursive(staged, deletion.path)
            yaml_text = _delete_tail_in_yaml_text(yaml_text, deletion.path)
        identifier = (moves or deletions)[0].target_schema

    # See migrate_mapping's identical check: a transition's declared moves
    # may not cover every field the source schema allowed.
    current_errors = _current_schema_rejections(staged, catalog)
    if current_errors:
        raise _unsupported_schema_error(current_errors[0])

    final_text = set_board_values(
        yaml_text,
        {**updates, **dict.fromkeys(removals)},
    )
    # Verify the text-level rewrite produced the same result as the in-memory
    # migration. The text editor cannot handle flow-style mappings (the regex
    # only matches block-mapping key lines) or block-scalar content (which can
    # contain lines that look like YAML keys). Either case silently no-ops or
    # silently corrupts content without the equality check; equality against
    # staged catches both before returning a wrong result.
    reparsed = load_yaml_mapping(final_text)
    if dict(reparsed) != staged:
        raise MigrationError(
            "YAML text rewrite diverged from in-memory migration; "
            "the file may use YAML constructs the text editor cannot handle "
            "(flow-style mappings, block scalars, YAML anchors, quoted keys) "
            "— migrate this file manually."
        )
    return final_text


def _recognize(mapping: Mapping[str, JsonValue], catalog: YamlSchemaCatalog) -> str:
    """Return the schema identifier that best matches *mapping*.

    Returns ``_CURRENT`` when the mapping already satisfies the live (unreleased)
    schema.  Returns a frozen version string when the mapping satisfies that
    frozen release.  Raises ``UnsupportedSchemaError`` when no known schema fits.
    """
    current_errors = _current_schema_rejections(mapping, catalog)
    if not current_errors:
        return _CURRENT
    for identifier in catalog.versions:
        errors = list(
            Draft7Validator(catalog.schema_for(identifier)).iter_errors(mapping)
        )
        if not errors:
            return identifier
    raise _unsupported_schema_error(current_errors[0])


def _current_schema_rejections(
    mapping: Mapping[str, JsonValue], catalog: YamlSchemaCatalog
) -> tuple[str, ...]:
    return tuple(
        error.message
        for error in Draft7Validator(catalog.current_schema).iter_errors(mapping)
    )


def _unsupported_schema_error(current_error: str) -> UnsupportedSchemaError:
    return UnsupportedSchemaError(
        f"Unsupported YAML syntax; current schema rejected it: {current_error}"
    )


def _enforce_support_window(
    identifier: str, catalog: YamlSchemaCatalog, *, today: date
) -> None:
    current_date = date.today() if today == date.min else today
    cutoff = _subtract_months(current_date, 6)
    released_at = next(
        entry.released_at for entry in catalog.entries if entry.version == identifier
    )
    if released_at < cutoff:
        raise SchemaVersionTooOldError(
            f"Schema {identifier} is older than the transparent-migration cutoff "
            f"{cutoff.isoformat()}; run `dct migrate` to update the file."
        )


def _subtract_months(value: date, months: int) -> date:
    month = value.month - months
    year = value.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = (date(year, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(value.day, last_day))


def _apply_conditional_move(result: JsonObject, rule: ConditionalMove) -> list[str]:
    """Apply rule to result, returning a list of drop-warning messages.

    Recurses through the entire document so nested boards under rows/cols/grid
    are covered.  Warnings are collected (not emitted here) so the caller
    controls stacklevel.
    """
    drop_warnings: list[str] = []
    _apply_conditional_move_recursive(result, rule, drop_warnings, last_key="<root>")
    return drop_warnings


def _apply_conditional_move_recursive(
    node: JsonValue,
    rule: ConditionalMove,
    drop_warnings: list[str],
    last_key: str,
) -> None:
    """Walk node recursively; act on dicts whose ``type`` matches rule.chart_type."""
    if isinstance(node, dict):
        if node.get("type") == rule.chart_type:
            _try_conditional_move_at_chart(node, rule, drop_warnings, last_key)
        # Always recurse into children — handles nested boards and sibling charts.
        for key in list(node.keys()):
            _apply_conditional_move_recursive(node[key], rule, drop_warnings, key)
    elif isinstance(node, list):
        for item in node:
            _apply_conditional_move_recursive(item, rule, drop_warnings, last_key)


def _try_conditional_move_at_chart(
    chart: dict[str, JsonValue],
    rule: ConditionalMove,
    drop_warnings: list[str],
    chart_id: str,
) -> None:
    """Apply the conditional move to one chart dict in place."""
    # Navigate to old_tail to check existence and read value.
    old_parent: JsonValue = chart
    for part in rule.old_tail[:-1]:
        if not isinstance(old_parent, dict):
            return
        old_parent = old_parent.get(part)
        if old_parent is None:
            return
    if not isinstance(old_parent, dict):
        return
    old_key = rule.old_tail[-1]
    if old_key not in old_parent:
        return
    old_value = old_parent[old_key]

    # Check whether sibling mapping exists.
    sibling: JsonValue = chart
    for part in rule.sibling_tail:
        if not isinstance(sibling, dict):
            sibling = None
            break
        sibling = sibling.get(part)

    if isinstance(sibling, dict):
        # Check for conflict: is new_tail already set in the sibling?
        new_tail_in_sibling = rule.new_tail[len(rule.sibling_tail) :]
        conflict_node: JsonValue = sibling
        for part in new_tail_in_sibling[:-1]:
            if not isinstance(conflict_node, dict):
                break
            conflict_node = conflict_node.get(part)
        if (
            isinstance(conflict_node, dict)
            and new_tail_in_sibling
            and new_tail_in_sibling[-1] in conflict_node
        ):
            raise MigrationConflictError(
                f"Cannot conditionally move {_format_path(rule.old_tail)!r} to "
                f"{_format_path(rule.new_tail)!r} in chart {chart_id!r}: "
                "both fields exist. Choose one value and migrate manually."
            )
        # Pop old_tail (orphan-parent cleanup via _try_delete_tail).
        _try_delete_tail(chart, rule.old_tail)
        # Set value at new_tail (navigating from the sibling root).
        dest: dict[str, JsonValue] = sibling
        for part in new_tail_in_sibling[:-1]:
            child = dest.get(part)
            if not isinstance(child, dict):
                child = {}
                dest[part] = child
            dest = child
        dest[new_tail_in_sibling[-1]] = old_value
    else:
        # Drop the field — sibling doesn't exist so there's nowhere to land it.
        _try_delete_tail(chart, rule.old_tail)
        drop_warnings.append(rule.drop_warning.format(chart=chart_id))


def _delete_tail_recursive(node: JsonValue, tail: YamlKeyPath) -> None:
    """Delete tail at every position in node, recursing through dicts and lists.

    When deleting a tail causes a parent dict to become empty, that parent is
    also removed — the deletion propagates up through the document structure.
    """
    if isinstance(node, dict):
        _try_delete_tail(node, tail)
        for key in list(node.keys()):
            child = node[key]
            was_empty_before = isinstance(child, dict) and not child
            _delete_tail_recursive(child, tail)
            if isinstance(child, dict) and not child and not was_empty_before:
                del node[key]
    elif isinstance(node, list):
        for item in node:
            _delete_tail_recursive(item, tail)


def _try_delete_tail(node: dict[str, JsonValue], tail: YamlKeyPath) -> bool:
    """Delete tail from node if the key chain exists, following only dict children.

    Returns True if *node* itself became empty after the deletion so the caller
    can remove it from its own parent.
    """
    if len(tail) == 1:
        if tail[0] not in node:
            return False
        node.pop(tail[0])
        return len(node) == 0
    child = node.get(tail[0])
    if isinstance(child, dict):
        if _try_delete_tail(child, tail[1:]):
            del node[tail[0]]
            return len(node) == 0
    return False


def _apply_move(mapping: JsonObject, move: Move) -> None:
    for parent, key, bindings in list(_source_locations(mapping, move.old_path)):
        destination = _substitute_wildcards(move.new_path, bindings)
        _move_value(mapping, parent, key, destination, move)


def _source_locations(
    node: JsonValue, parts: YamlKeyPath, bindings: tuple[str, ...] = ()
) -> Iterable[tuple[JsonObject | list[JsonValue], str | int, tuple[str, ...]]]:
    if not parts:
        return
    part = parts[0]
    if len(parts) == 1:
        if part == "*" and isinstance(node, dict):
            for key in node:
                yield node, key, bindings + (str(key),)
        elif part == "*" and isinstance(node, list):
            for index in range(len(node)):
                yield node, index, bindings + (str(index),)
        elif isinstance(node, dict) and part in node:
            yield node, part, bindings
        return
    if part == "*" and isinstance(node, (dict, list)):
        for child_key, value in (
            list(node.items()) if isinstance(node, dict) else enumerate(node)
        ):
            yield from _source_locations(value, parts[1:], bindings + (str(child_key),))
    elif isinstance(node, dict) and part in node:
        yield from _source_locations(node[part], parts[1:], bindings)


def _substitute_wildcards(parts: YamlKeyPath, bindings: tuple[str, ...]) -> list[str]:
    iterator = iter(bindings)
    result: list[str] = []
    for part in parts:
        if part == "*":
            try:
                result.append(next(iterator))
            except StopIteration as exc:
                raise MigrationError(
                    "Destination path has more wildcards than source path"
                ) from exc
        else:
            result.append(part)
    if next(iterator, None) is not None:
        raise MigrationError("Source path has more wildcards than destination path")
    return result


def _move_value(
    mapping: JsonObject,
    source_parent: JsonObject | list[JsonValue],
    source_key: str | int,
    destination: list[str],
    move: Move,
) -> None:
    parent = mapping
    for part in destination[:-1]:
        value = parent.get(part)
        if value is None:
            value = {}
            parent[part] = value
        if not isinstance(value, dict):
            raise MigrationError(
                f"Cannot move {_format_path(move.old_path)!r} to "
                f"{_format_path(move.new_path)!r}: {part!r} "
                "must be a mapping. Migrate this field manually."
            )
        parent = value
    destination_key = destination[-1]
    if destination_key in parent:
        raise MigrationConflictError(
            f"Cannot move {_format_path(move.old_path)!r} to "
            f"{_format_path(move.new_path)!r}: both fields exist. "
            "Choose one value and migrate manually."
        )
    if isinstance(source_parent, dict):
        assert isinstance(source_key, str)
        popped_value = source_parent.pop(source_key)
    else:
        assert isinstance(source_key, int)
        popped_value = source_parent.pop(source_key)
    if move.value_map is not None:
        parent[destination_key] = _mapped_value(
            move.value_map, move.old_path, popped_value
        )
    else:
        parent[destination_key] = popped_value


def _mapped_value(
    value_map: Mapping[MappedScalar, MappedScalar],
    old_path: YamlKeyPath,
    value: JsonValue,
) -> MappedScalar:
    """Resolve value through a Move's value_map, rejecting anything it can't cover.

    A value_map is declared total over its field's real scalar domain (see
    Move.value_map), so a non-scalar or unmapped value here means the source
    schema admitted a shape the migration author didn't account for -- fail
    loud rather than guess.
    """
    if not isinstance(value, (str, int, float, bool)) or value not in value_map:
        raise MigrationError(
            f"Cannot migrate {_format_path(old_path)!r}: "
            f"value {value!r} has no entry in the value map. "
            "Migrate this field manually."
        )
    return value_map[value]


def _walk_fields(
    model: type[BaseModel],
    path: tuple[str, ...] = (),
    seen: frozenset[type[BaseModel]] = frozenset(),
) -> Iterable[tuple[str, ...]]:
    if model in seen:
        return
    for name, field in model.model_fields.items():
        field_path = path + (name,)
        yield field_path
        if field.annotation is not None:
            for nested, suffix in _nested_models(field.annotation):
                yield from _walk_fields(nested, field_path + suffix, seen | {model})


def _nested_models(
    annotation: type[BaseModel] | type | str,
) -> Iterable[tuple[type[BaseModel], tuple[str, ...]]]:
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation, ()
        return
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (dict, list):
        values = args[1:] if origin is dict else args
        for value in values:
            for nested, suffix in _nested_models(value):
                yield nested, ("*",) + suffix
        return
    for argument in args:
        yield from _nested_models(argument)


def _schema_path_exists(schema: JsonObject, path: YamlKeyPath) -> bool:
    nodes = [schema]
    for part in path:
        next_nodes: list[JsonObject] = []
        for node in nodes:
            for branch in _expand_anyof(schema, node):
                if part == "*":
                    child = branch.get("additionalProperties")
                    if child is None:
                        child = branch.get("items")
                else:
                    properties = branch.get("properties")
                    child = (
                        properties.get(part) if isinstance(properties, dict) else None
                    )
                if isinstance(child, dict):
                    next_nodes.append(child)
        nodes = next_nodes
        if not nodes:
            return False
    return True


def _expand_anyof(
    schema: JsonObject, node: JsonObject, seen: frozenset[str] = frozenset()
) -> list[JsonObject]:
    """Recursively flatten nested anyOf branches into leaf nodes.

    Follows ``$ref`` (including ``$ref: "#"``) and expands nested ``anyOf``
    unions so callers get a flat list of concrete schema branches.  The *seen*
    guard stops cycles caused by self-referential ``$ref: "#"`` appearing inside
    an ``anyOf`` union.
    """
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return []
        seen = seen | {ref}
    resolved = _resolve_ref(schema, node)
    branches = resolved.get("anyOf")
    if not isinstance(branches, list):
        return [resolved]
    result: list[JsonObject] = []
    for branch in branches:
        if isinstance(branch, dict):
            result.extend(_expand_anyof(schema, branch, seen))
    return result


def _resolve_ref(root: JsonObject, node: JsonObject) -> JsonObject:
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return node
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        return node
    target: JsonValue = root
    for part in ref[2:].split("/"):
        if not isinstance(target, dict):
            return node
        target = target[part]
    return target if isinstance(target, dict) else node


def _schema_has_tail(schema: JsonObject, tail: YamlKeyPath) -> bool:
    """True iff tail appears at any position in the JSON schema.

    Walks properties, anyOf, additionalProperties, and items, following $ref
    pointers. The seen-id guard stops cycles including ``$ref: "#"``
    self-references (the board schema's nested-board recursion), so every
    reachable schema node is visited exactly once.  ``schema`` is always the
    top-level root so $ref resolution stays correct when visiting child nodes.
    """
    seen: set[int] = set()

    def tail_exists_from(start: JsonObject) -> bool:
        """True iff tail is a property chain reachable from start."""
        nodes: list[JsonObject] = [start]
        for part in tail:
            next_nodes: list[JsonObject] = []
            for node in nodes:
                for branch in _expand_anyof(schema, node):
                    props = branch.get("properties")
                    child = props.get(part) if isinstance(props, dict) else None
                    if isinstance(child, dict):
                        next_nodes.append(child)
            nodes = next_nodes
            if not nodes:
                return False
        return True

    def walk(node: JsonObject) -> bool:
        resolved = _resolve_ref(schema, node)
        rid = id(resolved)
        if rid in seen:
            return False
        seen.add(rid)
        if tail_exists_from(resolved):
            return True
        branches = resolved.get("anyOf")
        if isinstance(branches, list):
            return any(isinstance(b, dict) and walk(b) for b in branches)
        props = resolved.get("properties")
        if isinstance(props, dict):
            for child in props.values():
                if isinstance(child, dict) and walk(child):
                    return True
        add_props = resolved.get("additionalProperties")
        if isinstance(add_props, dict) and walk(add_props):
            return True
        items_node = resolved.get("items")
        return isinstance(items_node, dict) and walk(items_node)

    return walk(schema)


# Regex for a YAML block-mapping key line: captures (indent, key, optional-inline-value).
_YAML_KEY_RE = re.compile(r"^( *)([A-Za-z0-9_.\-]+):(?:[ \t]+(\S.*?))?[ \t]*$")
# Matches blank lines and comment-only lines (both are transparent to parent-chain search).
_YAML_BLANK_OR_COMMENT_RE = re.compile(r"^\s*(#.*)?$")


def _delete_tail_in_yaml_text(yaml_text: str, tail: YamlKeyPath) -> str:
    """Remove every line whose key matches tail's leaf and whose ancestor chain matches.

    Scans every line for the leaf key and verifies the correct ancestor chain
    by walking backward over lines with strictly lower indentation. This removes
    *every* match at any depth; ``set_board_values`` edits one addressed path, so
    the two are not interchangeable even though both now reach into list items.

    When deleting a leaf leaves its parent block empty (the leaf was the only
    child), the orphaned parent key line is also removed — mirroring the
    in-memory cleanup in ``_delete_tail_recursive``.
    """
    leaf_key = tail[-1]
    parent_keys = tail[:-1]
    lines = yaml_text.split("\n")
    to_delete: set[int] = set()
    for i, line in enumerate(lines):
        m = _YAML_KEY_RE.match(line)
        if m is not None and m.group(2) == leaf_key:
            leaf_indent = len(m.group(1))
            if _yaml_parent_chain_matches(lines, i, leaf_indent, parent_keys):
                to_delete.add(i)
                # Delete the entire nested block below this key.  Find
                # block_end = the last non-blank line whose indentation is
                # strictly greater than leaf_indent; every line up to and
                # including that boundary (blank or not) belongs to this block.
                # For a scalar leaf block_end stays at i, so the range is empty
                # and the scalar-deletion behaviour is unchanged.
                block_end = i
                k = i + 1
                while k < len(lines):
                    child = lines[k]
                    if not _YAML_BLANK_OR_COMMENT_RE.match(child):
                        if len(child) - len(child.lstrip(" ")) <= leaf_indent:
                            break
                        block_end = k
                    k += 1
                for k in range(i + 1, block_end + 1):
                    to_delete.add(k)
    if parent_keys:
        _prune_childless_ancestors(lines, to_delete)
    return "\n".join(line for j, line in enumerate(lines) if j not in to_delete)


def _prune_childless_ancestors(lines: list[str], to_delete: set[int]) -> None:
    """Mark block-only ancestor keys for deletion when all their children are in to_delete.

    Only keys that are actual ancestors of already-deleted lines are candidates —
    never keys that are empty or comment-only for unrelated reasons.  The
    candidate scoping alone provides this guarantee: every candidate lies on the
    backward ancestor walk from a deleted line and therefore has at least one
    block child.

    Block-only means the key has no inline value *and* no inline trailing comment
    (``legend:`` or ``legend:  # appearance``); both forms have a null value with
    a multi-line block of children.

    Interior blank/comment lines inside a pruned block are also added to
    to_delete so they are not left orphaned at the wrong indentation.

    Iterates to a fixpoint: each pass may expose a grandparent once its child key
    is marked, propagating the cleanup upward through nested mappings.
    """
    changed = True
    while changed:
        changed = False
        candidates: set[int] = set()
        for deleted_idx in to_delete:
            m_del = _YAML_KEY_RE.match(lines[deleted_idx])
            if m_del is None:
                # Blank or comment line inside a pruned block — no ancestor walk needed.
                continue
            current_indent = len(m_del.group(1))
            for j in range(deleted_idx - 1, -1, -1):
                anc_line = lines[j]
                if _YAML_BLANK_OR_COMMENT_RE.match(anc_line):
                    continue
                anc_indent = len(anc_line) - len(anc_line.lstrip(" "))
                if anc_indent >= current_indent:
                    continue
                m_anc = _YAML_KEY_RE.match(anc_line)
                if m_anc is None:
                    current_indent = anc_indent
                    continue
                value = m_anc.group(3)
                if value is None or value.lstrip().startswith("#"):
                    candidates.add(j)
                current_indent = len(m_anc.group(1))
        for i in candidates:
            if i in to_delete:
                continue
            key_indent = len(lines[i]) - len(lines[i].lstrip(" "))
            j = i + 1
            has_live_child = False
            while j < len(lines):
                child_line = lines[j]
                if _YAML_BLANK_OR_COMMENT_RE.match(child_line):
                    j += 1
                    continue
                child_indent = len(child_line) - len(child_line.lstrip(" "))
                if child_indent <= key_indent:
                    break
                if j not in to_delete:
                    has_live_child = True
                    break
                j += 1
            if not has_live_child:
                # Find block_end — the last line at indent > key_indent — to
                # bound the cleanup to the block's actual extent.  Blank/comment
                # lines after that boundary belong to what follows the block.
                block_end = i
                k = i + 1
                while k < len(lines):
                    inner = lines[k]
                    if not _YAML_BLANK_OR_COMMENT_RE.match(inner):
                        if len(inner) - len(inner.lstrip(" ")) <= key_indent:
                            break
                        block_end = k
                    k += 1
                for k in range(i + 1, block_end + 1):
                    if _YAML_BLANK_OR_COMMENT_RE.match(lines[k]):
                        to_delete.add(k)
                to_delete.add(i)
                changed = True


def _yaml_parent_chain_matches(
    lines: list[str],
    leaf_idx: int,
    leaf_indent: int,
    parent_keys: tuple[str, ...],
) -> bool:
    """True iff the enclosing mapping ancestors match parent_keys (nearest first).

    Walks backward from leaf_idx looking for keys at strictly lower indentation.
    List item markers and other non-key lines (blank, comment) are transparent —
    they update the indentation tracking without requiring a key match.
    """
    if not parent_keys:
        return True
    remaining = list(reversed(parent_keys))  # nearest parent is first to check
    current_indent = leaf_indent
    for j in range(leaf_idx - 1, -1, -1):
        line = lines[j]
        if _YAML_BLANK_OR_COMMENT_RE.match(line):
            continue
        line_indent = len(line) - len(line.lstrip(" "))
        if line_indent >= current_indent:
            continue  # sibling or deeper, not an ancestor
        m = _YAML_KEY_RE.match(line)
        if m is None:
            # List item or other structural line — update indent without key check.
            current_indent = line_indent
            continue
        key = m.group(2)
        if key != remaining[0]:
            return False
        remaining.pop(0)
        current_indent = len(m.group(1))
        if not remaining:
            return True
    return False


def _format_path(path: YamlKeyPath) -> str:
    return ".".join(path)
