"""Integration tests for the 0.4.0 -> 0.5.0 KPI style.tone → support.tone ConditionalMove.

``style.tone`` was retired from KPI charts as part of the 0.5.0 release. The
frozen module ``versions/v0_5_0.py`` registers a ConditionalMove so that
authored boards from before the retirement migrate automatically when the
``support:`` block already exists; if it doesn't, ``style.tone`` is dropped and
a warning names the chart.

These tests use the real catalog and migration registry -- no synthetic data.

Callout regression: callout charts also have ``style.tone`` (a different, unrelated
field).  The ConditionalMove is scoped to ``chart_type="kpi"`` so callout boards
are never touched.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from dbt_charts.core.compile.migrations import (
    MigrationConflictError,
    SchemaMigrationWarning,
    UnsupportedSchemaError,
    migrate_mapping,
    migrate_yaml_text,
)
from dbt_charts.core.compile.migrations.migrations import (
    _board_migration_context,
)
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    YamlSchemaCatalog,
    load_yaml_schema_catalog,
)


@pytest.fixture
def catalog() -> YamlSchemaCatalog:
    return load_yaml_schema_catalog()


def _migrate(raw: dict[str, Any], catalog: YamlSchemaCatalog) -> dict[str, Any]:
    _, registry = _board_migration_context()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SchemaMigrationWarning)
        return migrate_mapping(raw, catalog=catalog, registry=registry)


def test_kpi_style_tone_migrates_into_existing_support(
    catalog: YamlSchemaCatalog,
) -> None:
    """style.tone on a KPI with an existing support: block moves to support.tone.

    The style key is cleaned up (emptied parent removed); the support block
    gains tone; the document validates against AuthoredBoard.
    """
    raw: dict[str, Any] = {
        "charts": {
            "revenue_kpi": {
                "type": "kpi",
                "query": "q1",
                "value": "revenue",
                "style": {"tone": "positive"},
                "support": {"label": "vs last year"},
            }
        },
        "rows": ["revenue_kpi"],
    }

    migrated = _migrate(raw, catalog)

    chart = migrated["charts"]["revenue_kpi"]
    assert chart["support"]["tone"] == "positive"
    assert chart["support"]["label"] == "vs last year"
    # style.tone was the sole style key → orphan cleanup removes style
    assert "style" not in chart
    AuthoredBoard.model_validate(migrated)


def test_kpi_style_tone_migrates_into_existing_support_with_other_style_keys(
    catalog: YamlSchemaCatalog,
) -> None:
    """style.tone is extracted while sibling style keys are preserved."""
    raw: dict[str, Any] = {
        "charts": {
            "revenue_kpi": {
                "type": "kpi",
                "query": "q1",
                "value": "revenue",
                "style": {"tone": "negative", "glyph": {"character": "▼"}},
                "support": {"label": "vs last year"},
            }
        },
        "rows": ["revenue_kpi"],
    }

    migrated = _migrate(raw, catalog)

    chart = migrated["charts"]["revenue_kpi"]
    assert chart["support"]["tone"] == "negative"
    # Other style key survives
    assert chart["style"]["glyph"]["character"] == "▼"
    assert "tone" not in chart["style"]
    AuthoredBoard.model_validate(migrated)


def test_kpi_style_tone_dropped_when_no_support_block(
    catalog: YamlSchemaCatalog,
) -> None:
    """style.tone is dropped (not migrated) when no support: block exists.

    A SchemaMigrationWarning naming the chart must be raised so the author
    can manually add a support: block and re-set the tone there.
    """
    _, registry = _board_migration_context()
    raw: dict[str, Any] = {
        "charts": {
            "revenue_kpi": {
                "type": "kpi",
                "query": "q1",
                "value": "revenue",
                "style": {"tone": "positive"},
            }
        },
        "rows": ["revenue_kpi"],
    }

    with pytest.warns(SchemaMigrationWarning, match="revenue_kpi"):
        migrated = migrate_mapping(raw, catalog=catalog, registry=registry)

    chart = migrated["charts"]["revenue_kpi"]
    assert "tone" not in str(chart)
    assert "style" not in chart
    AuthoredBoard.model_validate(migrated)


def test_callout_style_tone_is_untouched(catalog: YamlSchemaCatalog) -> None:
    """callout.style.tone survives when a KPI with style.tone triggers the migration.

    This is the critical regression: a naive path-only move would strip
    style.tone from every chart (including callout) and hand callout a
    support: block that CalloutChart rejects.  The chart_type="kpi"
    discriminant prevents this — only KPI charts are touched.

    The board contains both a KPI (style.tone → triggers 0.5.0 recognition)
    and a callout (style.tone → must survive unchanged).
    """
    raw: dict[str, Any] = {
        "charts": {
            "revenue_kpi": {
                "type": "kpi",
                "query": "q1",
                "value": "revenue",
                "style": {"tone": "positive"},
                "support": {"label": "vs last year"},
            },
            "alert": {
                "type": "callout",
                "message": "Data may be delayed.",
                "style": {"tone": "warning"},
            },
        },
        "rows": ["revenue_kpi", "alert"],
    }

    migrated = _migrate(raw, catalog)

    # KPI migrated normally
    assert migrated["charts"]["revenue_kpi"]["support"]["tone"] == "positive"
    assert "style" not in migrated["charts"]["revenue_kpi"]
    # Callout tone completely untouched
    assert migrated["charts"]["alert"]["style"]["tone"] == "warning"
    AuthoredBoard.model_validate(migrated)


def test_kpi_conflict_when_support_tone_already_set(
    catalog: YamlSchemaCatalog,
) -> None:
    """style.tone and support.tone both present raises MigrationConflictError.

    Mirrors test_conflicting_destination_does_not_mutate_input: the input
    must not be mutated when the conflict is detected.
    """
    import copy

    _, registry = _board_migration_context()
    raw: dict[str, Any] = {
        "charts": {
            "k1": {
                "type": "kpi",
                "query": "q1",
                "value": "revenue",
                "style": {"tone": "positive"},
                "support": {"label": "vs last year", "tone": "negative"},
            }
        },
        "rows": ["k1"],
    }
    original = copy.deepcopy(raw)

    with pytest.raises(MigrationConflictError):
        migrate_mapping(raw, catalog=catalog, registry=registry)

    # Input must not be mutated when conflict is raised
    assert raw == original


def test_nested_board_kpi_style_tone_migrates(catalog: YamlSchemaCatalog) -> None:
    """KPI chart nested inside rows→cols→charts is reached by the recursive walk.

    Mirrors test_nested_board_interactive_legend_stripped: the dominant authoring
    shape must be covered without an anchored-path implementation.
    """
    raw: dict[str, Any] = {
        "title": "t",
        "rows": [
            {
                "cols": [
                    {
                        "charts": {
                            "kpi_nested": {
                                "type": "kpi",
                                "query": "q",
                                "value": "revenue",
                                "style": {"tone": "positive"},
                                "support": {"label": "prior period"},
                            }
                        }
                    }
                ]
            }
        ],
    }

    migrated = _migrate(raw, catalog)

    chart: Any = migrated["rows"][0]["cols"][0]["charts"]["kpi_nested"]
    assert chart["support"]["tone"] == "positive"
    assert "style" not in chart


def test_board_without_style_tone_is_unchanged(catalog: YamlSchemaCatalog) -> None:
    """A KPI board without style.tone passes through untouched."""
    raw: dict[str, Any] = {
        "charts": {
            "k1": {
                "type": "kpi",
                "query": "q1",
                "value": "revenue",
                "support": {"label": "vs last year", "tone": "positive"},
            }
        },
        "rows": ["k1"],
    }

    migrated = _migrate(raw, catalog)

    assert migrated == raw
    AuthoredBoard.model_validate(migrated)


def test_registry_covers_the_0_4_0_conditional_moves(
    catalog: YamlSchemaCatalog,
) -> None:
    """The ConditionalMove is registered at the 0.4.0 -> 0.5.0 boundary."""
    _, registry = _board_migration_context()
    cond_moves = registry.conditional_moves_from("0.4.0")

    assert cond_moves
    assert all(cm.target_schema == "0.5.0" for cm in cond_moves)
    # The registered move targets KPI charts specifically
    kpi_moves = [cm for cm in cond_moves if cm.chart_type == "kpi"]
    assert kpi_moves


def test_migrate_yaml_text_raises_for_kpi_with_style_tone(
    catalog: YamlSchemaCatalog,
) -> None:
    """migrate_yaml_text does not implement ConditionalMove, so a KPI board
    with style.tone raises UnsupportedSchemaError rather than silently
    leaving the field or corrupting the output.
    """
    _, registry = _board_migration_context()
    yaml_text = (
        "charts:\n"
        "  k1:\n"
        "    type: kpi\n"
        "    query: q1\n"
        "    value: revenue\n"
        "    style:\n"
        "      tone: positive\n"
        "rows: [k1]\n"
    )

    with pytest.raises(UnsupportedSchemaError):
        migrate_yaml_text(yaml_text, catalog=catalog, registry=registry)
