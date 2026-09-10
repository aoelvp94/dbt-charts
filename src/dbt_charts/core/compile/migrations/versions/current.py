"""Version-migration module for the unreleased 0.6.0 -> current boundary.

Declares the pending structural changes since the 0.6.0 freeze. Authored as
``versions/current.py`` while unreleased (the ``catalog.latest.version ->
current`` boundary); renamed to ``versions/v<new_version>.py`` at release time
with no content edit, same convention as ``v0_5_0.py``/``v0_6_0.py``.

THIS FILE IS SCHEMA CHANGES ONLY. Do not add an entry here for anything that
is not a key rename, a key removal, or an authored value's meaning changing
in place (the unmigratable-redefinition case, which still owes the author a
signal per ``migrations/AGENTS.md``). A renderer-default tweak, a bug fix, a
performance change, a visual behavior change, an internal refactor -- none of
these are grammar changes, and none of them get a bullet here, no matter how
significant. If you cannot point to the ``Move``, ``Deletion``, in-place
redefinition, or a documented removed-fail-loud (no migration exists;
`MigrationRegistry` rejects any tail collision, and the bullet exists to say
so) backing your bullet, it does not belong in this file. Put it in the task
or the PR description instead. See ``migrations/AGENTS.md``'s "If you catch
yourself thinking..." table.

Changes in this release:

- Two dead root-level ``style:`` fields removed:

  - ``style.page`` (``PageStyle`` had exactly one field, ``background``).
    Deletion tail is ``("style", "page")``, not ``("page", "background")``:
    the old grammar allowed a bare ``page: {}``/``page: null`` with no
    required fields, so a tail scoped to ``background`` alone would leave
    those two shapes unrecognized. Anchored at ``style`` rather than a bare
    ``("page",)`` — same reasoning as ``v0_5_0.py``'s ``("style",
    "tooltip")`` precedent: the in-memory schema walk only ever matches this
    tail under ``style``, but a bare tail is also live on ``dct migrate``'s
    text path, which has no schema awareness and would strike a ``page:``
    key at any depth (e.g. inside a query's own free-form row data). The
    anchored form strips all three authored shapes
    (``style.page.background: ...``, ``style.page: {}``,
    ``style.page: null``) and is auto-stripped by ``dct migrate``.
  - ``style.color`` (a per-board text-color override) was fully inert — it
    never rendered — so a ``Move`` to its natural hand-edit target,
    ``style.font.color``, would be unsafe rather than lossless: ``font.color``
    *is* live, so redirecting an inert value onto it would change every
    affected board's render instead of preserving it. Same ``kpi.style.color``
    situation as the KPI text-styling reconciliation on the 0.5.0 -> 0.6.0
    boundary: ``color`` is one of the most common leaf names in the schema
    (every chart family's chart-local ``style.color``, plus
    ``kpi.style.color``), so neither the bare tail ``("color",)`` nor the
    anchored ``("style", "color")`` is Deletion-eligible — both still match a
    live sibling field elsewhere. Removed fail-loud instead: an authored
    root ``style.color`` now raises ``extra_forbidden`` naming the field,
    same outcome as authoring it never having existed.

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


- ``axis*.grid.zero`` renamed to ``axis*.grid.threshold``. The block styles the
  heavy rule drawn where a quantitative axis crosses a meaningful threshold, and
  it always styled more than zero — the unity rule at 1.0 on a ratio axis read
  the same block — so the old spelling named only one of the thresholds it
  governed. It also gains a ``visible`` flag, the targeted off switch: before it,
  the only way to silence the rule was ``grid.visible: false``, which took every
  gridline on the axis with it.

  Declared via ``suffix_rename_moves`` in ``THRESHOLD_RENAMES`` below, anchored
  two segments deep (``grid`` + ``threshold``) rather than on a bare
  ``threshold`` tail. The anchor is hygiene rather than necessity —
  ``suffix_rename_moves`` matches on the NEW tail, so a bare ``("threshold",)``
  could not have collided with the unrelated ``scale.continuous.zero`` boolean
  either — but the qualified form says at the declaration which ``zero`` moved.

  Same self-nesting caveat as every other position-scoped rename in this file:
  ``_relative_field_paths``' ``seen`` guard makes a self-nested ``AuthoredBoard``
  opaque, so a sub-board reached by recursion is not walked and its own
  ``grid.zero`` is not rewritten.
"""

from __future__ import annotations

from dbt_charts.core.compile.migrations.migrations import (
    Deletion,
    MappedScalar,
    Move,
    YamlKeyPath,
    suffix_rename_moves,
)
from dbt_charts.core.compile.schema.renderers.yaml_schema_catalog import (
    YamlSchemaCatalog,
)

THEME_RENAMES: dict[MappedScalar, MappedScalar] = {}

# style.page (PageStyle had exactly one field, `background`) — anchored tail,
# not the bare `page` key (see the module docstring for why).
DELETED_TAILS: tuple[YamlKeyPath, ...] = (("style", "page"),)


def _deletion_reason(tail: YamlKeyPath) -> str | None:
    """Reason text for ``DELETED_TAILS`` entries that benefit from one.

    ``("style", "page")`` is not an inert key: ``page.background`` drove real
    render behavior (the standalone-HTML export's outer ``<body>``) before
    this boundary, so an author on a board that explicitly diverged its
    ``page.background`` from its own ``background`` benefits from knowing
    the strip is not a no-op.
    """
    if tail == ("style", "page"):
        return (
            "The page canvas this board explicitly requested is gone; the "
            "standalone-HTML export, dct serve, and Cloud's HTML download "
            "now use this board's own style.background instead, which is "
            "what page.background already equaled on every shipped theme, "
            "a no-op unless this board's page.background diverged from "
            "its own background."
        )
    return None


# grid's threshold sub-block, renamed from its old "zero" spelling (see the
# module docstring for why the tail is qualified by "grid").
THRESHOLD_RENAMES: tuple[tuple[YamlKeyPath, YamlKeyPath], ...] = (
    (("grid", "threshold"), ("grid", "zero")),
)


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
    style_tail_deletions = tuple(
        Deletion(
            source_schema,
            target_schema,
            tail,
            reason=_deletion_reason(tail),
        )
        for tail in DELETED_TAILS
    )
    conditional_formatting_deletions = tuple(
        Deletion(
            source_schema,
            target_schema,
            ("conditional_formatting",),
            reason=_conditional_formatting_deletion_reason(chart_type),
            chart_type=chart_type,
        )
        for chart_type in CONDITIONAL_FORMATTING_RETIRED_CHART_TYPES
    )
    return style_tail_deletions + conditional_formatting_deletions


def moves(
    source_schema: str, target_schema: str, *, catalog: YamlSchemaCatalog
) -> tuple[Move, ...]:
    """Return Move objects for the 0.6.0 -> current boundary."""
    from dbt_charts.core.compile.models.board.authored import AuthoredBoard

    return suffix_rename_moves(
        AuthoredBoard,
        source_schema,
        target_schema,
        THRESHOLD_RENAMES,
        catalog=catalog,
    )
