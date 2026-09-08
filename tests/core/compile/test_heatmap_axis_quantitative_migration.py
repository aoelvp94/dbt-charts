"""Migration coverage for the heatmap ``axis_quantitative`` removal.

Heatmap's axes are both nominal — it has no quantitative axis for
``axis_quantitative`` to style. The board-level slot
(``style.charts.heatmap.axis_quantitative``) was accepted by the 0.5.0
grammar and is auto-stripped by ``dct migrate``. The chart-local position
(``charts.<id>.style.axis_quantitative``) cannot ship a Deletion — its only
available tail is still live on the other five cartesian families — so it
fails loud instead (covered by ``test_yaml_error_formatter.py``).
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from dbt_charts.core.compile.migrations import (
    SchemaMigrationWarning,
    migrate_mapping,
)
from dbt_charts.core.compile.migrations.migrations import (
    _board_migration_context,
    _schema_has_tail,
)
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    YamlSchemaCatalog,
    load_yaml_schema_catalog,
)

OTHER_CARTESIAN_FAMILIES = ("bar", "line", "area", "scatter", "histogram")


@pytest.fixture
def catalog() -> YamlSchemaCatalog:
    return load_yaml_schema_catalog()


def _migrate(raw: dict[str, Any], catalog: YamlSchemaCatalog) -> dict[str, Any]:
    _, registry = _board_migration_context()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SchemaMigrationWarning)
        return migrate_mapping(raw, catalog=catalog, registry=registry)


def _board(style: dict[str, Any]) -> dict[str, Any]:
    return {
        "charts": {
            "grid": {
                "type": "heatmap",
                "query": "counts",
                "x": "month",
                "y": "category",
            }
        },
        "style": style,
        "rows": ["grid"],
    }


def test_registry_declares_the_theme_level_deletion() -> None:
    """The removal was declared at the 0.5.0 -> 0.6.0 boundary, now frozen --
    not at ``catalog.latest.version``, which is 0.6.0 itself post-freeze."""
    _, registry = _board_migration_context()
    deletions = registry.deletions_from("0.5.0")

    declared = {d.path for d in deletions}
    assert ("charts", "heatmap", "axis_quantitative") in declared


def test_tail_was_in_the_released_grammar_and_is_gone_from_the_live_one(
    catalog: YamlSchemaCatalog,
) -> None:
    """Both halves of what makes a Deletion legal, asserted directly.

    Source-present is what makes the key worth migrating; target-absent is
    what stops the tail stripping a slot that still works. Source is pinned
    to 0.5.0, the grammar the tail actually shipped in -- not
    ``catalog.latest.version``, which is 0.6.0 post-freeze and never had it.
    """
    tail = ("charts", "heatmap", "axis_quantitative")
    assert _schema_has_tail(catalog.schema_for("0.5.0"), tail)
    assert not _schema_has_tail(catalog.current_schema, tail)


def test_board_level_axis_quantitative_key_stripped(catalog: YamlSchemaCatalog) -> None:
    raw = _board(
        {
            "charts": {
                "heatmap": {
                    "axis_quantitative": {"scale": {"continuous": {"zero": False}}},
                    "cell_padding": 4,
                }
            }
        }
    )

    migrated = _migrate(raw, catalog)

    assert "axis_quantitative" not in migrated["style"]["charts"]["heatmap"]
    # The sibling key on the same slot survives -- the tail strips one field,
    # not the whole family block.
    assert migrated["style"]["charts"]["heatmap"]["cell_padding"] == 4
    AuthoredBoard.model_validate(migrated)


@pytest.mark.parametrize("family", OTHER_CARTESIAN_FAMILIES)
def test_live_sibling_family_axis_quantitative_survives_migration(
    family: str, catalog: YamlSchemaCatalog
) -> None:
    """The heatmap-anchored tail must not strip a live sibling family's slot.

    A bare ("axis_quantitative",) tail would have matched every one of these;
    the ``charts``/``heatmap`` anchor is what prevents that.
    """
    raw = _board(
        {"charts": {family: {"axis_quantitative": {"scale": {"round": True}}}}}
    )

    migrated = _migrate(raw, catalog)

    assert migrated["style"]["charts"][family]["axis_quantitative"] == {
        "scale": {"round": True}
    }
    AuthoredBoard.model_validate(migrated)


def test_chart_local_position_is_not_migrated_and_fails_loud() -> None:
    """The chart-local half ships no Deletion, by necessity -- assert the
    tail the mechanism would need is still live, so the registry would reject
    it. The author-facing error for this position is covered by
    test_yaml_error_formatter.py.
    """
    catalog = load_yaml_schema_catalog()
    assert _schema_has_tail(catalog.current_schema, ("style", "axis_quantitative"))
