"""Version-migration module for the 0.3.1 -> 0.4.0 axis/scale model reshape.

Every rename is a pure tail substitution — same shared prefix, only the
trailing segment(s) change — so suffix_rename_moves derives every occurrence
a rename applies at. Leaf renames that land *inside* the "labels"/"scale"
containers run before the "labels"/"line" container renames themselves: a
leaf move creates its destination container on demand, and the later
container move must find that destination still empty (or absent) to avoid
a spurious MigrationConflictError against an unrelated field that also sets
the old container. See dbt-charts/AGENTS.md's "Two validation boundaries" —
these are structural moves; categorical_orient (deleted), the stable-axis
domain-strategy key (deleted), ticks.interval (reinterpreted vocabulary, not
renamed), and the band/point/quantize scale groups (deleted) are semantic
changes with no lossless move and are left to raise UnsupportedSchemaError for
manual migration.
"""

from __future__ import annotations

from dbt_charts.core.compile.migrations.migrations import (
    Move,
    YamlKeyPath,
    suffix_rename_moves,
)
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    YamlSchemaCatalog,
)

RENAMES: tuple[tuple[YamlKeyPath, YamlKeyPath], ...] = (
    (("labels", "format"), ("format",)),
    (("scale", "values"), ("values",)),
    (("scale", "continuous", "domain"), ("scale", "domain")),
    (("scale", "continuous", "zero"), ("scale", "zero")),
    (("scale", "continuous", "type"), ("scale", "type")),
    (("scale", "continuous", "log", "base"), ("scale", "base")),
    (("scale", "continuous", "pow", "exponent"), ("scale", "exponent")),
    (("scale", "continuous", "symlog", "constant"), ("scale", "constant")),
    (("scale", "padding"), ("scale", "band_padding_inner")),
    (("ticks", "length"), ("ticks", "size")),
    (("labels",), ("label",)),
    (("line",), ("domain",)),
)


def moves(
    source_schema: str, target_schema: str, *, catalog: YamlSchemaCatalog
) -> tuple[Move, ...]:
    """Return the Move objects for this version boundary."""
    from dbt_charts.core.compile.models.board.authored import AuthoredBoard

    return suffix_rename_moves(
        AuthoredBoard, source_schema, target_schema, RENAMES, catalog=catalog
    )
