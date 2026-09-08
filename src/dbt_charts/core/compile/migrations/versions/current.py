"""Version-migration module for the unreleased 0.6.0 -> current boundary.

Declares the pending structural changes since the 0.6.0 freeze. Authored as
``versions/current.py`` while unreleased (the ``catalog.latest.version ->
current`` boundary); renamed to ``versions/v<new_version>.py`` at release time
with no content edit, same convention as ``v0_5_0.py``/``v0_6_0.py``.

No structural changes are in flight yet.
"""

from __future__ import annotations

from dbt_charts.core.compile.migrations.migrations import Deletion, MappedScalar
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    YamlSchemaCatalog,
)

THEME_RENAMES: dict[MappedScalar, MappedScalar] = {}


def deletions(
    source_schema: str, target_schema: str, *, catalog: YamlSchemaCatalog
) -> tuple[Deletion, ...]:
    """Return Deletion objects for the 0.6.0 -> current boundary."""
    return ()
