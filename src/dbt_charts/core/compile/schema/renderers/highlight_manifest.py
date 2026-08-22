"""Highlight manifest renderer — derives syntax-highlighting metadata from the schema IR.

Produces a ``HighlightManifest`` from an ``AuthorableSchema`` (via ``introspect()``).
The manifest is the single source of truth for:

- Top-level board YAML keys (used in tmLanguage and Pygments lexer)
- Per-key enum value sets (chart types for ``type:``, input types for ``input:``)
- SQL block scalar keys (keys whose block-scalar bodies contain SQL)

Entry point: ``render_highlight_manifest(schema: AuthorableSchema) -> HighlightManifest``
"""

from __future__ import annotations

import dataclasses

from dbt_charts.core.compile.schema.introspection import AuthorableSchema

# Keys whose block-scalar bodies are SQL.  Stable: sql and query are the only
# authored SQL surfaces; adding one here also requires updating the Pygments lexer
# logic and regenerating the tmLanguage grammar via ``just gen-highlight-artifacts``.
_SQL_BLOCK_SCALAR_KEYS: list[str] = ["query", "sql"]


@dataclasses.dataclass(frozen=True)
class HighlightManifest:
    """Syntax-highlighting metadata derived from the schema IR.

    Args:
        top_level_keys: Sorted field names of AuthoredBoard (the top-level YAML keys).
        enum_values_by_key: Maps property key name to sorted list of enum values.
            Covers ``type`` (chart types) and ``input`` (variable input types).
        sql_block_scalar_keys: Sorted list of YAML keys whose block scalar bodies
            contain SQL (e.g. ``sql``, ``query``).
    """

    top_level_keys: list[str]
    enum_values_by_key: dict[str, list[str]]
    sql_block_scalar_keys: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "top_level_keys": self.top_level_keys,
            "enum_values_by_key": self.enum_values_by_key,
            "sql_block_scalar_keys": self.sql_block_scalar_keys,
        }


def render_highlight_manifest(schema: AuthorableSchema) -> HighlightManifest:
    """Build a HighlightManifest from an AuthorableSchema.

    Args:
        schema: Schema IR from ``introspect()``.

    Returns:
        Highlight manifest with top-level keys, enum value sets, and SQL block keys.
    """
    board_model = schema.models["AuthoredBoard"]
    top_level_keys = sorted(f.name for f in board_model.fields)

    enum_values_by_key: dict[str, list[str]] = {}

    chart_model = schema.models.get("AuthoredChart")
    if chart_model:
        if chart_model.union is not None:
            enum_values_by_key["type"] = sorted(chart_model.union.variants.keys())
        else:
            type_field = next((f for f in chart_model.fields if f.name == "type"), None)
            if type_field and type_field.enum_values:
                enum_values_by_key["type"] = sorted(
                    v for v in type_field.enum_values if isinstance(v, str)
                )

    var_model = schema.models.get("Variable")
    if var_model:
        input_field = next((f for f in var_model.fields if f.name == "input"), None)
        if input_field and input_field.enum_values:
            enum_values_by_key["input"] = sorted(
                v for v in input_field.enum_values if isinstance(v, str)
            )

    return HighlightManifest(
        top_level_keys=top_level_keys,
        enum_values_by_key=enum_values_by_key,
        sql_block_scalar_keys=sorted(_SQL_BLOCK_SCALAR_KEYS),
    )
