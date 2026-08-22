"""Regression: BoardPatch must accept the same authored query shorthand AuthoredBoard does.

BoardPatch is the all-optional overlay of AuthoredBoard. Bare-string query shorthand
(``queries: {q: "SELECT ..."}``) is authored input the normalizer rewrites to
``{type: sql, sql: ...}``. That rewrite is a shared ``mode="before"`` model validator,
so meta files and extends fragments — which are validated as ``BoardPatch`` by the merge
engine — must accept it too.

Before the shared-mixin fix, ``build_patch_model_ext`` carried over ``_desugar_theme``
(it lived on the ``_BoardDesugarMixin`` base) but dropped ``_normalize_queries`` (defined
directly on ``AuthoredBoard``). So ``BoardPatch`` read the bare string as a query
*reference* and raised "Invalid query reference 'SELECT ...'", which in turn forced the
compiler to hand-roll a dict-level meta/board merge instead of using ``merge_patches``.
"""

from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.compile.models.board.patch import BoardPatch


def test_boardpatch_accepts_bare_string_query_shorthand() -> None:
    # Must not raise — bare-string query shorthand is valid authored input.
    patch = BoardPatch.model_validate({"queries": {"sales": "SELECT 1 AS x"}})
    assert patch.queries is not None
    assert patch.queries["sales"] is not None


def test_boardpatch_query_shorthand_matches_authoredboard() -> None:
    """The patch model and its parent normalize identical shorthand identically."""
    raw = {"title": "T", "queries": {"sales": "SELECT 1 AS x"}}
    fp = BoardPatch.model_validate(raw)
    af = AuthoredBoard.model_validate(raw)
    assert type(fp.queries["sales"]) is type(af.queries["sales"])
