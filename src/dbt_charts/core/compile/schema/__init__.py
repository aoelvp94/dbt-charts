"""Schema documentation generation for AI integrations.

Delegates to the two-layer IR pipeline:
  introspect() → AuthorableSchema → render_prompt() → str
"""

from dbt_charts.core.compile.schema.facets import board_keys_with, keys_with
from dbt_charts.core.compile.schema.introspection import introspect
from dbt_charts.core.compile.schema.renderers.prompt import render_prompt


def get_schema_for_prompt() -> str:
    """Get complete schema documentation for AI prompts."""
    return render_prompt(introspect())


__all__ = ["board_keys_with", "get_schema_for_prompt", "keys_with"]
