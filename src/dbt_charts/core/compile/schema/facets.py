"""Key sets derived from the facets declared on authored fields.

Five hand-written key lists across core and Cloud answered questions
``AuthoredBoard`` already knew — which top-level keys make a file a board,
which fields hold prose, URLs, markdown. Nothing in the type system connected
them to the model, so they drifted. These two functions are that connection:
the facts come from the schema, the mechanisms reading them stay their own.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache

from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.markers import Facet
from dbt_charts.core.compile.schema.introspection import introspect


@cache
def keys_with(facet: type[Facet]) -> frozenset[str]:
    """Field names carrying *facet* anywhere in the authored schema.

    Names, not paths: the consumers walk raw YAML of unknown depth and match
    keys by name, so ``text`` on a tab is the same fact as ``text`` on a board.
    """
    return _declared(
        facet,
        (
            field.name
            for model in introspect().models.values()
            for field in model.fields
            if any(isinstance(declared, facet) for declared in field.facets)
        ),
    )


@cache
def board_keys_with(facet: type[Facet]) -> frozenset[str]:
    """``AuthoredBoard``'s own top-level field names carrying *facet*.

    These callers classify a board's top-level mapping, where a name that only
    exists deeper in the graph (a chart's ``title``) would misfire.
    """
    return _declared(
        facet,
        (
            name
            for name, info in AuthoredBoard.model_fields.items()
            if any(isinstance(declared, facet) for declared in info.metadata)
        ),
    )


def _declared(facet: type[Facet], names: Iterable[str]) -> frozenset[str]:
    """Reject a facet no field declares — an empty set disables the gate reading it."""
    keys = frozenset(names)
    if not keys:
        raise ValueError(
            f"{facet.__name__} is declared on no field: a gate reading it would "
            "classify everything the same way."
        )
    return keys
