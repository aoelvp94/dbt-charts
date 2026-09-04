"""Contract tests for `iter_mark_units` — the VL composition walker in base.py.

These build specs by hand on purpose: this is a unit test of a pure function
over Vega-Lite's composition semantics, not a test of what our emitters happen
to produce today. The detector tests that DO need real specs use `_emitted_ctx`.

The inheritance rules differ per container and both directions can be wrong:
inheriting where VL does not invents channels on a view that never declared
them; not inheriting where VL does hides real ones.
"""

from __future__ import annotations

from dbt_charts.core.render.warnings.base import iter_mark_units, unit_mark_type


def _leaf(mark: str, **channels: object) -> dict[str, object]:
    return {"mark": {"type": mark}, "encoding": dict(channels)}


def test_layer_children_inherit_the_parent_encoding() -> None:
    """VL resolves a layered view's channels against the shared top-level
    encoding — which is exactly where the bar emitter hoists `x`."""
    spec = {
        "encoding": {"x": {"type": "quantitative"}},
        "layer": [_leaf("bar", xOffset={"field": "s"})],
    }
    units = list(iter_mark_units(spec))
    assert len(units) == 1
    _, encoding = units[0]
    assert encoding["x"] == {"type": "quantitative"}, "layer child lost the hoisted x"
    assert "xOffset" in encoding


def test_layer_child_overrides_an_inherited_channel() -> None:
    spec = {
        "encoding": {"x": {"type": "nominal"}},
        "layer": [_leaf("bar", x={"type": "quantitative"})],
    }
    _, encoding = next(iter(iter_mark_units(spec)))
    assert encoding["x"] == {"type": "quantitative"}


def test_concat_children_do_not_inherit_the_parent_encoding() -> None:
    """A concat child is an independent view. Our own wrappers never hoist an
    `encoding` onto a concat root, so this rule is unobservable through the
    emitters today — it is pinned here so the walker cannot start inventing
    channels if one ever does.
    """
    for container in ("hconcat", "vconcat", "concat"):
        spec = {
            "encoding": {"x": {"type": "quantitative"}},
            container: [_leaf("bar", xOffset={"field": "s"})],
        }
        units = list(iter_mark_units(spec))
        assert len(units) == 1, f"{container}: expected one leaf"
        _, encoding = units[0]
        assert "x" not in encoding, (
            f"{container} child inherited `x` from the root — a concat child is "
            "an independent view and must not"
        )


def test_facet_panel_does_not_inherit_and_is_descended() -> None:
    """VL's facet operator form has no top-level `encoding` of its own."""
    spec = {
        "encoding": {"x": {"type": "quantitative"}},
        "facet": {"column": {"field": "g"}},
        "spec": _leaf("bar", xOffset={"field": "s"}),
    }
    units = list(iter_mark_units(spec))
    assert len(units) == 1
    unit, encoding = units[0]
    assert unit_mark_type(unit) == "bar"
    assert "x" not in encoding


def test_nested_containers_are_all_descended() -> None:
    """The real endpoint-label shape: concat wrapping a layered chart."""
    spec = {
        "hconcat": [
            {
                "encoding": {"x": {"type": "quantitative"}},
                "layer": [_leaf("bar", xOffset={"field": "s"}), _leaf("rule")],
            },
            _leaf("text"),
        ]
    }
    units = list(iter_mark_units(spec))
    assert [unit_mark_type(u) for u, _ in units] == ["bar", "rule", "text"]
    bar_encoding = units[0][1]
    assert bar_encoding["x"] == {"type": "quantitative"}, (
        "bar lost the x hoisted onto its own layer parent"
    )


def test_repeat_is_not_descended() -> None:
    """No emitter produces `repeat`, and its inner spec addresses columns via
    templating rather than real field names — so it yields its own root, which
    carries no mark and every caller ignores."""
    spec = {"repeat": {"column": ["a", "b"]}, "spec": _leaf("bar")}
    units = list(iter_mark_units(spec))
    assert [unit_mark_type(u) for u, _ in units] == [""]


def test_a_plain_unit_spec_yields_itself() -> None:
    spec = _leaf("bar", x={"type": "quantitative"})
    units = list(iter_mark_units(spec))
    assert len(units) == 1
    assert unit_mark_type(units[0][0]) == "bar"
    assert units[0][1]["x"] == {"type": "quantitative"}
