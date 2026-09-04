"""Synthetic schema catalogs shared by the migration tests.

Release dates are anchored to *today* rather than written as literals. A test
that is not about the transparent-migration support window must never start
failing because the calendar moved past a hardcoded date — that failure lands
on an unrelated green diff and names a support window the test has nothing to
do with. Tests that *are* about the window pass an explicit ``today=``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import cast

from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    JsonObject,
    YamlSchemaCatalog,
    YamlSchemaEntry,
)


def released(index: int) -> date:
    """Release date of the *index*-th newest grammar, 0 being the latest.

    Anchored rather than literal for the reason in the module docstring. Use it
    for any hand-built ``YamlSchemaEntry`` too, not just the ones
    ``synthetic_catalog`` makes.

    30-day steps against a six-month cutoff give about six in-window slots —
    index 6 clears by days, index 7 does not. Deliberately allowed past that:
    an index chosen to sit *outside* the window is how the expired-grammar case
    is built. A catalog that wants eight in-window versions needs tighter
    spacing, not a bigger index.
    """
    return date.today() - timedelta(days=30 * index)


def flat_schema(*keys: str) -> JsonObject:
    """A flat grammar accepting exactly *keys*, each a string."""
    return cast(
        JsonObject,
        {
            "type": "object",
            "properties": {key: {"type": "string"} for key in keys},
            "additionalProperties": False,
        },
    )


def synthetic_catalog(
    schemas: dict[str, JsonObject], current: JsonObject | None = None
) -> YamlSchemaCatalog:
    """Build a catalog from *schemas* given oldest-first.

    ``current`` is the live schema. It defaults to the newest frozen one, which
    is what a real catalog looks like between releases; pass it to model the
    state this module exists to test — unreleased model changes in flight, so
    the live grammar knows keys no frozen grammar has seen.
    """
    versions = tuple(reversed(schemas))
    entries = tuple(
        YamlSchemaEntry(
            version=version,
            released_at=released(index),
            filename=f"{version}.json",
            sha256="test",
            predecessor=None,
        )
        for index, version in enumerate(versions)
    )
    return YamlSchemaCatalog(
        entries, schemas, schemas[versions[0]] if current is None else current
    )
