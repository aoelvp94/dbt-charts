"""Regression tests: build_patch_model lives in compile.factories."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from dbt_charts.core.compile.models.factories import build_patch_model


class _SampleCompiled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    label: str


class _WithAny(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: Any


def test_build_patch_model_produces_all_optional_fields() -> None:
    PatchCls = build_patch_model(_SampleCompiled)
    patch = PatchCls()
    assert patch.value is None
    assert patch.label is None


def test_build_patch_model_accepts_partial_values() -> None:
    PatchCls = build_patch_model(_SampleCompiled)
    patch = PatchCls(value=1.0)
    assert patch.value == 1.0
    assert patch.label is None


def test_build_patch_model_rejects_extra_fields() -> None:
    PatchCls = build_patch_model(_SampleCompiled)
    with pytest.raises(ValidationError, match="bogus"):
        PatchCls(bogus=True)  # type: ignore[call-arg]


def test_build_patch_model_is_cached() -> None:
    cls1 = build_patch_model(_SampleCompiled)
    cls2 = build_patch_model(_SampleCompiled)
    assert cls1 is cls2


def test_build_patch_model_any_field_accepts_none() -> None:
    # Any | None ≡ Any — patch model must accept None for an Any-typed field.
    PatchCls = build_patch_model(_WithAny)
    patch = PatchCls(data=None)
    assert patch.data is None
    patch2 = PatchCls(data={"nested": 42})
    assert patch2.data == {"nested": 42}


def test_build_patch_model_optional_nested_basemodel_recurses() -> None:
    """Optional[BaseModel] fields must recurse to PatchVersion | None, not compiled | None.

    Regression: _make_patch_annotation early-returned Optional[T] as-is when
    T was a BaseModel, leaving the compiled type (with required fields) in the
    patch annotation instead of its all-Optional patch variant.
    """

    class _Inner(BaseModel):
        model_config = ConfigDict(extra="forbid")
        size: float

    class _Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        # Optional nested sub-model — the field that triggered the bug.
        inner: _Inner | None = None

    OuterPatch = build_patch_model(_Outer)
    # Must accept a partial dict for inner (missing required field 'size' is OK
    # in the patch version — it's all-Optional).
    patch = OuterPatch(inner={"size": 5.0})
    assert patch.inner is not None
    assert patch.inner.size == 5.0

    # Must also accept None (field itself optional).
    empty = OuterPatch()
    assert empty.inner is None

    # The annotation on the patch's `inner` field should be PatchVariant | None,
    # not the compiled _Inner type.  We verify this indirectly: the compiled
    # _Inner has a required `size` field, so if the patch stored compiled _Inner
    # in its annotation, `OuterPatch(inner={})` would raise ValidationError.
    # After the fix, the patch stores _InnerPatch (all-Optional), so {} is fine.
    partial_inner = OuterPatch(inner={})
    assert partial_inner.inner is not None
    assert partial_inner.inner.size is None


def test_axis_grid_style_patch_threshold_field_is_patch_variant() -> None:
    """BaseAxisGridStylePatch.threshold must be AxisGridThresholdStylePatch | None,
    not compiled | None.

    This is the real-world case from PR #2868 that triggered the regression:
    a nested compiled type in a field annotation produced a patch with the
    compiled type (required fields) instead of its patch variant. ``threshold``
    lives on the shared BaseAxisGridStyle, reachable from every axis slot.
    """
    from dbt_charts.core.compile.models.style.theme import (
        AxisGridThresholdStyle,
        BaseAxisGridStyle,
    )

    AxisGridStylePatch = build_patch_model(BaseAxisGridStyle)
    AxisGridThresholdStylePatch = build_patch_model(AxisGridThresholdStyle)

    # threshold field annotation should be AxisGridThresholdStylePatch | None,
    # not AxisGridThresholdStyle | None. We verify by accepting a partial
    # threshold dict with no fields (all-Optional patch).
    patch = AxisGridStylePatch(threshold={})
    assert patch.threshold is not None
    # Patch fields default to None.
    assert patch.threshold.color is None
    assert patch.threshold.width is None

    # With an actual value it should round-trip.
    patch2 = AxisGridStylePatch(threshold={"color": "#ff0000"})
    assert patch2.threshold is not None
    assert patch2.threshold.color == "#ff0000"

    # The threshold field's model must be the patch class, not the compiled class.
    assert type(patch.threshold) is AxisGridThresholdStylePatch
