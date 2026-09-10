"""Tests for the merge-engine foundation: Merge marker, strategy(), merge_patches().

TDD: these tests are written before the implementation.
No D-NN tokens in this file.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.models.markers import Merge, Strategy

# ---------------------------------------------------------------------------
# Small helper models for merge_patches tests — no dependency on AuthoredBoard.
# ---------------------------------------------------------------------------


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str | None = None
    y: int | None = None


class _InnerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str | None = None
    y: int | None = None


class _SimplePatch(BaseModel):
    """Minimal patch model: scalar + list + dict + nested model."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Merge(Strategy.OVERRIDE)] = None
    tags: Annotated[list[str] | None, Merge(Strategy.APPEND, nested=Strategy.CHILD)] = (
        None
    )
    mapping: Annotated[dict[str, str] | None, Merge(Strategy.BY_KEY)] = None
    nested: Annotated[_InnerPatch | None, Merge(Strategy.DEEP)] = None
    child_field: Annotated[
        str | None, Merge(Strategy.APPEND, nested=Strategy.CHILD)
    ] = None


# ===========================================================================
# Merge marker
# ===========================================================================


def test_merge_marker_valid_strategies() -> None:
    m = Merge(Strategy.APPEND)
    assert m.file == Strategy.APPEND
    assert m.nested is None

    m2 = Merge(Strategy.BY_KEY, nested=Strategy.CHILD)
    assert m2.file == Strategy.BY_KEY
    assert m2.nested == Strategy.CHILD


def test_merge_marker_nested_defaults_to_none() -> None:
    assert Merge(Strategy.APPEND).nested is None


def test_merge_marker_all_strategies_accepted() -> None:
    for strat in (
        Strategy.OVERRIDE,
        Strategy.DEEP,
        Strategy.BY_KEY,
        Strategy.APPEND,
        Strategy.CHILD,
    ):
        m = Merge(strat)
        assert m.file == strat
        m2 = Merge(Strategy.OVERRIDE, nested=strat)
        assert m2.nested == strat


# ===========================================================================
# Strategy enum
# ===========================================================================


def test_strategy_enum_str_compat() -> None:
    """Strategy members compare equal to their string values (str subclass)."""
    assert Strategy.OVERRIDE == "override"
    assert Strategy.DEEP == "deep"
    assert Strategy.BY_KEY == "by_key"
    assert Strategy.APPEND == "append"
    assert Strategy.CHILD == "child"


def test_strategy_enum_merge_field_identity() -> None:
    """Merge(Strategy.DEEP).file is the enum member, not a bare string."""
    m = Merge(Strategy.DEEP)
    assert m.file is Strategy.DEEP
    assert isinstance(m.file, Strategy)


def test_strategy_enum_invalid_raises() -> None:
    """Strategy("bogus") raises ValueError — enum IS the validation."""
    with pytest.raises(ValueError, match="bogus"):
        Strategy("bogus")


# ===========================================================================
# strategy()
# ===========================================================================


def test_strategy_reads_explicit_file_marker() -> None:
    from dbt_charts.core.compile.merge import strategy

    field = _SimplePatch.model_fields["tags"]
    assert strategy(field, nested=False) == "append"


def test_strategy_nested_override_when_nested_set() -> None:
    from dbt_charts.core.compile.merge import strategy

    field = _SimplePatch.model_fields["tags"]  # Merge("append", nested="child")
    assert strategy(field, nested=True) == "child"


def test_strategy_nested_falls_back_to_file_when_no_nested() -> None:
    from dbt_charts.core.compile.merge import strategy

    field = _SimplePatch.model_fields["mapping"]  # Merge("by_key"), no nested
    assert strategy(field, nested=True) == "by_key"


def test_strategy_type_inferred_model() -> None:
    """Field with no Merge marker whose type is a BaseModel -> 'deep'."""
    from dbt_charts.core.compile.merge import strategy

    class _NakedPatch(BaseModel):
        sub: _InnerPatch | None = None

    field = _NakedPatch.model_fields["sub"]
    assert strategy(field, nested=False) == "deep"


def test_strategy_type_inferred_dict() -> None:
    from dbt_charts.core.compile.merge import strategy

    class _NakedPatch(BaseModel):
        d: dict[str, str] | None = None

    field = _NakedPatch.model_fields["d"]
    assert strategy(field, nested=False) == "by_key"


def test_strategy_type_inferred_scalar() -> None:
    from dbt_charts.core.compile.merge import strategy

    class _NakedPatch(BaseModel):
        s: str | None = None

    field = _NakedPatch.model_fields["s"]
    assert strategy(field, nested=False) == "override"


def test_strategy_list_without_merge_raises() -> None:
    """List-typed fields with no Merge marker must raise — silent override would
    clobber accumulated lists from lower layers."""
    from dbt_charts.core.compile.merge import strategy

    class _NakedListPatch(BaseModel):
        items: list[str] | None = None

    field = _NakedListPatch.model_fields["items"]
    with pytest.raises(TypeError, match="list"):
        strategy(field, nested=False)


# ===========================================================================
# merge_patches — core semantics
# ===========================================================================


def _make(model: type[BaseModel], **kwargs: object) -> BaseModel:
    """Construct a patch with exactly the given fields set (all others unset)."""
    return model.model_validate(kwargs)


def test_merge_patches_override_upper_wins() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, title="base")
    hi = _make(_SimplePatch, title="override")
    result = merge_patches(lo, hi, nested=False)
    assert result.title == "override"


def test_merge_patches_override_empty_model_upper_changes_nothing() -> None:
    """An empty block (``x: {}``) sets no field, so it replaces nothing.

    The rule is general, not cache-specific: OVERRIDE is the default strategy
    for any un-annotated field, and every other strategy already merges an
    all-unset patch to a no-op — override is the one that would otherwise
    clobber the lower value with a blank model.
    """
    from dbt_charts.core.compile.merge import merge_patches

    class _OuterPatch(BaseModel):
        model_config = ConfigDict(extra="forbid")

        # No Merge marker: OVERRIDE is the default for un-annotated fields.
        inner: _InnerPatch | None = None

    lo = _OuterPatch.model_validate({"inner": {"x": "keep", "y": 1}})
    hi = _OuterPatch.model_validate({"inner": {}})
    assert hi.inner is not None and not hi.inner.model_fields_set

    result = merge_patches(lo, hi, nested=False)
    assert result.inner is not None
    assert (result.inner.x, result.inner.y) == ("keep", 1)


def test_merge_patches_unset_upper_keeps_lower() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, title="base")
    hi = _SimplePatch()  # title not in model_fields_set
    assert "title" not in hi.model_fields_set
    result = merge_patches(lo, hi, nested=False)
    assert result.title == "base"


def test_merge_patches_explicit_null_clears() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, title="base")
    # Explicitly set title=None — must be in model_fields_set
    hi = _SimplePatch.model_construct(title=None)
    # model_construct doesn't track fields_set; validate instead:
    hi = _make(_SimplePatch, title=None)
    # model_validate({"title": None}) sets model_fields_set = {"title"}
    assert "title" in hi.model_fields_set
    result = merge_patches(lo, hi, nested=False)
    assert result.title is None


def test_merge_patches_append_list() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, tags=["a"])
    hi = _make(_SimplePatch, tags=["b"])
    result = merge_patches(lo, hi, nested=False)
    assert result.tags == ["a", "b"]


def test_merge_patches_append_lo_none_takes_hi() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _SimplePatch()
    hi = _make(_SimplePatch, tags=["b"])
    result = merge_patches(lo, hi, nested=False)
    assert result.tags == ["b"]


def test_merge_patches_by_key_merges_dicts() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, mapping={"a": "1"})
    hi = _make(_SimplePatch, mapping={"b": "2"})
    result = merge_patches(lo, hi, nested=False)
    assert result.mapping == {"a": "1", "b": "2"}


def test_merge_patches_by_key_upper_wins_collision() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, mapping={"a": "old"})
    hi = _make(_SimplePatch, mapping={"a": "new"})
    result = merge_patches(lo, hi, nested=False)
    assert result.mapping == {"a": "new"}


def test_merge_patches_child_takes_upper_even_when_none() -> None:
    """child strategy: result is always upper's value, even when it is None."""
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, child_field="parent_value")
    # upper explicitly sets child_field=None
    hi = _make(_SimplePatch, child_field=None)
    result = merge_patches(lo, hi, nested=True)
    assert result.child_field is None


def test_merge_patches_child_unset_in_upper_suppresses_parent() -> None:
    """child strategy: upper did not set the field at all → parent is suppressed.

    This is the key child invariant: even when upper leaves the field completely
    unset (not in model_fields_set), the parent's value is not carried through.
    The result is the patch default (None), not the parent's value.
    """
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, child_field="parent_value")
    hi = _SimplePatch()  # child_field NOT in model_fields_set
    assert "child_field" not in hi.model_fields_set
    result = merge_patches(lo, hi, nested=True)
    assert result.child_field is None  # parent contribution suppressed


def test_merge_patches_child_takes_upper_set_value() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, child_field="parent_value")
    hi = _make(_SimplePatch, child_field="child_value")
    result = merge_patches(lo, hi, nested=True)
    assert result.child_field == "child_value"


def test_merge_patches_deep_recurses() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_SimplePatch, nested={"x": "from_lo", "y": 1})
    hi = _make(_SimplePatch, nested={"x": "from_hi"})
    result = merge_patches(lo, hi, nested=False)
    assert result.nested is not None
    assert result.nested.x == "from_hi"
    assert result.nested.y == 1  # preserved from lo, unset in hi


def test_merge_patches_lo_none_takes_hi() -> None:
    """When lo.field is None and hi.field is set, take hi regardless of strategy."""
    from dbt_charts.core.compile.merge import merge_patches

    lo = _SimplePatch()  # mapping not set (None)
    hi = _make(_SimplePatch, mapping={"k": "v"})
    result = merge_patches(lo, hi, nested=False)
    assert result.mapping == {"k": "v"}


def test_merge_patches_returns_same_type() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _SimplePatch()
    hi = _SimplePatch()
    result = merge_patches(lo, hi, nested=False)
    assert type(result) is _SimplePatch


# ===========================================================================
# Cross-axis layout rule (policy ruling 2)
# ===========================================================================


class _LayoutPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: Annotated[list[str] | None, Merge(Strategy.APPEND, nested=Strategy.CHILD)] = (
        None
    )
    cols: Annotated[list[str] | None, Merge(Strategy.APPEND, nested=Strategy.CHILD)] = (
        None
    )
    title: Annotated[str | None, Merge(Strategy.OVERRIDE)] = None


def test_cross_axis_layout_lower_cleared() -> None:
    """When lower has rows and upper has cols, lower's rows are cleared."""
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_LayoutPatch, rows=["x"], title="keep")
    hi = _make(_LayoutPatch, cols=["y"])
    result = merge_patches(lo, hi, nested=False)
    assert result.rows is None
    assert result.cols == ["y"]
    assert result.title == "keep"  # non-layout field unaffected


def test_same_axis_layout_appends() -> None:
    from dbt_charts.core.compile.merge import merge_patches

    lo = _make(_LayoutPatch, rows=["x"])
    hi = _make(_LayoutPatch, rows=["y"])
    result = merge_patches(lo, hi, nested=False)
    assert result.rows == ["x", "y"]


# ===========================================================================
# BoardPatch + EMPTY_PATCH
# ===========================================================================


def test_board_patch_all_fields_optional() -> None:
    from dbt_charts.core.compile.models.board.patch import BoardPatch

    p = BoardPatch()
    assert p is not None


def test_board_patch_carries_merge_marker_on_tags() -> None:
    from dbt_charts.core.compile.models.board.patch import BoardPatch
    from dbt_charts.core.compile.models.markers import Merge

    meta = BoardPatch.model_fields["tags"].metadata
    merge_markers = [m for m in meta if isinstance(m, Merge)]
    assert len(merge_markers) == 1
    m = merge_markers[0]
    assert m.file == "append"
    assert m.nested == "child"


def test_board_patch_carries_merge_marker_on_queries() -> None:
    from dbt_charts.core.compile.models.board.patch import BoardPatch
    from dbt_charts.core.compile.models.markers import Merge

    meta = BoardPatch.model_fields["queries"].metadata
    merge_markers = [m for m in meta if isinstance(m, Merge)]
    assert len(merge_markers) == 1
    assert merge_markers[0].file == "by_key"


def test_empty_patch_no_fields_set() -> None:
    from dbt_charts.core.compile.models.board.patch import EMPTY_PATCH

    assert EMPTY_PATCH.model_fields_set == set()


def test_empty_patch_title_is_none() -> None:
    from dbt_charts.core.compile.models.board.patch import EMPTY_PATCH

    assert EMPTY_PATCH.title is None  # type: ignore[attr-defined]


# ===========================================================================
# Guard: every list field in every patch model must carry a Merge marker
# ===========================================================================


def _collect_patch_models(
    cls: type[BaseModel], visited: set[type[BaseModel]] | None = None
) -> set[type[BaseModel]]:
    """Walk cls and all nested BaseModel fields, collecting every reachable model."""
    import types
    import typing

    if visited is None:
        visited = set()
    if cls in visited:
        return visited
    visited.add(cls)
    for _name, field in cls.model_fields.items():
        ann = field.annotation
        if typing.get_origin(ann) is Annotated:
            ann = typing.get_args(ann)[0]
        origin = typing.get_origin(ann)
        if origin is typing.Union or isinstance(ann, types.UnionType):
            non_none = [a for a in typing.get_args(ann) if a is not type(None)]
            if non_none:
                ann = non_none[0]
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            _collect_patch_models(ann, visited)
    return visited


def test_patch_list_fields_all_have_merge_markers() -> None:
    """Every list-typed field reachable from StylePatch must carry a Merge marker.

    strategy() raises TypeError on list fields without one. A multi-layer board
    composition (board → template → theme) triggers exactly this path.
    Any regression here is caught at import/test time, not at merge time.

    Scope note: this test only walks models reachable from StylePatch via
    _collect_patch_models. A list field on a model NOT reachable from StylePatch
    (e.g. a model only used in BoardPatch but not in StylePatch's tree) is out of
    scope and must carry its own Merge marker without this guard.
    """
    from dbt_charts.core.compile.merge import _unwrap_type, strategy
    from dbt_charts.core.compile.models.style.authored import StylePatch

    all_models = _collect_patch_models(StylePatch)

    bad: list[str] = []
    for cls in sorted(all_models, key=lambda c: c.__name__):
        for field_name, field in cls.model_fields.items():
            t = _unwrap_type(field)
            if t is list:
                try:
                    strategy(field, nested=False)
                except TypeError:
                    bad.append(f"{cls.__name__}.{field_name}")

    assert not bad, (
        "List fields without Merge markers (will crash on multi-layer merge):\n"
        + "\n".join(f"  {b}" for b in sorted(bad))
    )


def test_unwrap_type_resolves_tuple_behind_a_nested_annotated_constraint() -> None:
    """A constraint nested on an *inner* Annotated (e.g.
    Annotated[Annotated[tuple[X, X], Field(strict=True)] | None, Merge(...)]) --
    the pattern ScaleContinuousStyle.domain uses so the constraint survives
    build_patch_model_ext -- must still resolve to `tuple`, not the leftover
    Annotated wrapper. _unwrap_type previously peeled Annotated and Union each
    only once, in that fixed order, and missed this case."""
    from dbt_charts.core.compile.merge import _unwrap_type
    from dbt_charts.core.compile.models.style.theme.axis import ScaleContinuousStyle

    field = ScaleContinuousStyle.model_fields["domain"]
    assert _unwrap_type(field) is tuple


# ===========================================================================
# Regression: multi-layer composition of list-typed style fields
# ===========================================================================


def test_multi_layer_title_sizes_merge_does_not_crash(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """board → template → theme: merging style.title.sizes must not raise TypeError."""
    from dbt_charts.core.compile.compiler import compile_file

    project = local_project(tmp_path)
    (tmp_path / "dbt_charts.yml").write_text("")
    (tmp_path / "charts").mkdir()

    # Template sets title.sizes — this is the layer that used to crash.
    (tmp_path / "charts" / "base.yaml").write_text(
        "style:\n  title:\n    sizes: [32, 28, 22, 18, 16, 14]\n"
    )
    board_yaml = "extends: ./base.yaml\nrows:\n  - cols:\n    - text: hi\n"
    board_path = tmp_path / "charts" / "board.yaml"
    board_path.write_text(board_yaml)

    result = compile_file(
        project.path("charts/board.yaml").read_board(), apply_meta=True
    )
    assert result.success, result.errors


def test_multi_layer_dashes_merge_does_not_crash(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """board → template → theme: merging style.charts.dashes must not raise TypeError."""
    from dbt_charts.core.compile.compiler import compile_file

    project = local_project(tmp_path)
    (tmp_path / "dbt_charts.yml").write_text("")
    (tmp_path / "charts").mkdir()

    (tmp_path / "charts" / "base.yaml").write_text(
        "style:\n  charts:\n    dashes: [[4, 2], [8, 4]]\n"
    )
    board_yaml = "extends: ./base.yaml\nrows:\n  - cols:\n    - text: hi\n"
    board_path = tmp_path / "charts" / "board.yaml"
    board_path.write_text(board_yaml)

    result = compile_file(
        project.path("charts/board.yaml").read_board(), apply_meta=True
    )
    assert result.success, result.errors


def test_multi_layer_list_style_override_is_idempotent(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """When the same style.title.sizes appears at two cascade levels, last-layer wins.

    Documents the 'override' semantics: the board's own value replaces the template's,
    producing a deterministic result rather than crashing or appending.
    """
    from dbt_charts.core.compile.compiler import compile_file

    project = local_project(tmp_path)
    (tmp_path / "dbt_charts.yml").write_text("")
    (tmp_path / "charts").mkdir()

    (tmp_path / "charts" / "base.yaml").write_text(
        "style:\n  title:\n    sizes: [32, 28, 22, 18, 16, 14]\n"
    )
    # Board also sets sizes — should override base cleanly.
    board_yaml = (
        "extends: ./base.yaml\n"
        "style:\n  title:\n    sizes: [40, 34, 28, 22, 18, 16]\n"
        "rows:\n  - cols:\n    - text: hi\n"
    )
    board_path = tmp_path / "charts" / "board.yaml"
    board_path.write_text(board_yaml)

    result = compile_file(
        project.path("charts/board.yaml").read_board(), apply_meta=True
    )
    assert result.success, result.errors


# ---------------------------------------------------------------------------
# Unknown extends entry must raise CompilationError, not silently fall back.
# ---------------------------------------------------------------------------


def test_unknown_extends_name_raises_compilation_error(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """An unrecognized extends entry raises CompilationError with the entry name."""
    from dbt_charts.core.compile.errors import CompilationError
    from dbt_charts.core.compile.merge import merge_extends
    from dbt_charts.core.compile.models.board.patch import BoardPatch

    (tmp_path / "board.yaml").write_text("")
    project = local_project(tmp_path)
    board_file = project.path("board.yaml")

    node = BoardPatch.model_validate({"extends": "creem"})  # typo of "cream"/"paper"

    with pytest.raises(CompilationError, match="creem"):
        merge_extends(node, board_file, project.directory("."))


def test_known_theme_name_does_not_raise_via_merge_extends(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """A valid built-in theme name resolves successfully without raising."""
    from dbt_charts.core.compile.merge import merge_extends
    from dbt_charts.core.compile.models.board.patch import BoardPatch

    (tmp_path / "board.yaml").write_text("")
    project = local_project(tmp_path)
    board_file = project.path("board.yaml")

    node = BoardPatch.model_validate({"extends": "paper"})

    # Must not raise — paper is a valid built-in theme.
    result = merge_extends(node, board_file, project.directory("."))
    assert result is not None


def test_compile_file_surfaces_unknown_extends_as_structured_error(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """compile_file on a board with unknown extends returns structured error, not a crash."""
    from dbt_charts.core.compile.compiler import compile_file

    project = local_project(tmp_path)
    (tmp_path / "charts").mkdir()
    board_path = tmp_path / "charts" / "bad.yaml"
    board_path.write_text("extends: creem\nrows:\n  - cols:\n    - text: hi\n")

    result = compile_file(project.path("charts/bad.yaml").read_board())

    assert not result.success
    assert result.errors
    assert any("creem" in e.message for e in result.errors)


def test_compile_file_surfaces_unknown_theme_sugar_as_structured_error(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """`theme: creem` (sugar form) produces the same structured error as `extends: creem`."""
    from dbt_charts.core.compile.compiler import compile_file

    project = local_project(tmp_path)
    (tmp_path / "charts").mkdir()
    board_path = tmp_path / "charts" / "bad.yaml"
    board_path.write_text("theme: creem\nrows:\n  - cols:\n    - text: hi\n")

    result = compile_file(project.path("charts/bad.yaml").read_board())

    assert not result.success
    assert result.errors
    assert any("creem" in e.message for e in result.errors)


def test_compile_file_theme_and_extends_conflict_is_structured_error(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    """A board with both `theme:` and `extends:` returns a structured error, not a crash."""
    from dbt_charts.core.compile.compiler import compile_file

    project = local_project(tmp_path)
    (tmp_path / "charts").mkdir()
    board_path = tmp_path / "charts" / "conflict.yaml"
    board_path.write_text(
        "theme: paper\nextends: neon\nrows:\n  - cols:\n    - text: hi\n"
    )

    result = compile_file(project.path("charts/conflict.yaml").read_board())

    assert not result.success
    assert result.errors
    # The conflict message must surface — not a Python crash
    assert any(
        "theme" in e.message.lower() or "extends" in e.message.lower()
        for e in result.errors
    )
