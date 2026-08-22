"""The LookML authoring surface is gone, and legacy boards fail loudly.

Pre-launch removal (no compat shim): `type: lookml`, `explore:`, `merge:`,
`lookml_path:`, and `models:` are not accepted-and-ignored — each names the
offending key in the error an author sees. The exception *class* differs by
path and is deliberately not pinned: source keys fail at Config load, an
inferred `explore:` falls through to `sql` and trips `extra="forbid"`, and an
explicit `type: lookml` fails union discrimination. Asserting one class across
three paths would invite a wrapper that normalizes them.

`union_tag_not_found` is also only today's message for the explicit-type case:
once `catalog.versions[0]` is frozen past 0.3.1, `prepare_board_mapping` matches
the board against the older grammar and raises `UnsupportedSchemaError` instead.
Both are correct, so these tests assert on the key name, not the class.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from dbt_charts.core.compile.models.query.authored import AuthoredQuery
from dbt_charts.core.compile.models.refs import normalize_query_value
from dbt_charts.core.compile.models.source import DuckDBSourceConfig

_ADAPTER: TypeAdapter[object] = TypeAdapter(AuthoredQuery)


def _validate(query_dict: dict[str, object]) -> object:
    return _ADAPTER.validate_python(normalize_query_value(query_dict))


def test_explore_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="explore"):
        _validate({"explore": "documents", "fields": ["documents.count"]})


def test_merge_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="merge"):
        _validate({"merge": [{"query": "a", "columns": ["x"]}]})


def test_explicit_lookml_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="lookml"):
        _validate({"type": "lookml", "explore": "documents"})


@pytest.mark.parametrize("field", ["lookml_path", "models"])
def test_source_lookml_fields_are_rejected(field: str) -> None:
    """Source keys fail at config load, where project sources are validated.

    Both values are *valid* under the old schema, so these are red before the
    removal and green after — not passing on an unrelated error.
    """
    value: object = (
        "lkml" if field == "lookml_path" else {"signing": {"explores": ["documents"]}}
    )
    with pytest.raises(ValidationError, match=field):
        DuckDBSourceConfig(type="duckdb", path="w.duckdb", **{field: value})
