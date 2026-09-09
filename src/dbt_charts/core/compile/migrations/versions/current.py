"""Version-migration module for the unreleased 0.6.0 -> current boundary.

Declares the pending structural changes since the 0.6.0 freeze. Authored as
``versions/current.py`` while unreleased (the ``catalog.latest.version ->
current`` boundary); renamed to ``versions/v<new_version>.py`` at release time
with no content edit, same convention as ``v0_5_0.py``/``v0_6_0.py``.

Changes in this release:

- ``conditional_formatting:`` retired from 11 ``type:`` literals: ``bar``,
  ``histogram``, ``line``, ``area``, ``scatter``, ``pie``, ``donut``, ``map``,
  ``geoshape``, ``point_map``, ``bubble_map``, kept unchanged on ``table``
  and ``kpi``, the only two families whose render path meaningfully honors
  every (table) or some (kpi) of the field's rule outputs; the other seven
  only ever lowered ``rule.background`` onto the mark fill, with `font`,
  `glyph`, `glyph_color`, and `tone` silently discarded. Declared
  as 11 ``Deletion`` entries below (``CONDITIONAL_FORMATTING_RETIRED_CHART_TYPES``),
  one per removed ``type:`` literal, each scoped via ``Deletion.chart_type``
  so the shared path ``("conditional_formatting",)`` retires only on its own
  family and a board mixing a retired family with ``table``/``kpi`` in one
  file migrates correctly on both the in-memory and ``dct migrate`` text
  paths. See ``Deletion.chart_type``'s own docstring in ``migrations.py``
  for why a bare per-path deletion cannot express this.

"""

from __future__ import annotations

from dbt_charts.core.compile.migrations.migrations import Deletion, MappedScalar
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    YamlSchemaCatalog,
)

THEME_RENAMES: dict[MappedScalar, MappedScalar] = {}


# conditional_formatting retired from these 11 `type:` literals -- kept on
# table/kpi. One entry per authored `type:` literal, not per Python model
# class (BarChart backs both "bar" and "histogram"; PieChart backs "pie" and
# "donut"; GeoshapeChart backs "geoshape" and "map"; PointMapChart backs
# "point_map" and "bubble_map") -- Deletion.chart_type gates on the
# document's own `type:` value, not on which class would parse it.
CONDITIONAL_FORMATTING_RETIRED_CHART_TYPES: tuple[str, ...] = (
    "bar",
    "histogram",
    "line",
    "area",
    "scatter",
    "pie",
    "donut",
    "map",
    "geoshape",
    "point_map",
    "bubble_map",
)


def _conditional_formatting_deletion_reason(chart_type: str) -> str:
    return (
        f"{chart_type} charts no longer support rule-driven styling "
        "(conditional_formatting). Use table or kpi for conditional formatting."
    )


def deletions(
    source_schema: str, target_schema: str, *, catalog: YamlSchemaCatalog
) -> tuple[Deletion, ...]:
    """Return Deletion objects for the 0.6.0 -> current boundary."""
    return tuple(
        Deletion(
            source_schema,
            target_schema,
            ("conditional_formatting",),
            reason=_conditional_formatting_deletion_reason(chart_type),
            chart_type=chart_type,
        )
        for chart_type in CONDITIONAL_FORMATTING_RETIRED_CHART_TYPES
    )
