"""TDD tests for scope_patch — the nested-scope patch accumulator.

Shared by the compile cascade (dispatch.compile_board_resolved_style) and the
design-verb read-only walk (agent_api.design._scope_style_patch): both derive
a scope's in-force patch from its parent's the same way, via this one helper.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dbt_charts.core.compile.merge import scope_patch


class _Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    data: dict[str, str] | None = None


def test_own_none_returns_inherited_unchanged() -> None:
    inherited = _Patch(label="parent")
    assert scope_patch(inherited, None) is inherited


def test_inherited_none_returns_own_unchanged() -> None:
    own = _Patch(label="child")
    assert scope_patch(None, own) is own


def test_both_none_returns_none() -> None:
    assert scope_patch(None, None) is None


def test_both_set_merges_nested_true() -> None:
    inherited = _Patch(label="parent", data={"a": "1"})
    own = _Patch(data={"b": "2"})

    merged = scope_patch(inherited, own)

    assert merged is not None
    # `label` unset on `own` falls through to `inherited` — the nested=True
    # relation, matching the real cascade's own-scope-over-parent order.
    assert merged.label == "parent"
    assert merged.data == {"a": "1", "b": "2"}
