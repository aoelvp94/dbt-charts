"""Tests for inherit_registry.yaml drift and SchemaField inherit metadata.

TDD: these tests were written before the implementation existed.
Run them to watch them fail, then implement to make them pass.
"""

from __future__ import annotations

import importlib.util
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict

from dbt_charts.core.compile.models.markers import Inherit, InheritSlot
from dbt_charts.core.compile.schema.introspection import (
    SchemaField,
    _build_schema_field,
)

from ..._paths import DBT_CHARTS_DIR, DBT_CHARTS_PKG_DIR

_REGISTRY_PATH = (
    DBT_CHARTS_PKG_DIR
    / "core"
    / "compile"
    / "resolve"
    / "style"
    / "inherit_registry.yaml"
)


# ── Drift test ────────────────────────────────────────────────────────────────


def test_inherit_registry_matches_graph():
    """Committed inherit_registry.yaml must match slot-level regeneration from build_slot_graph.

    Fails when markers are added/removed from the Style model without re-running
    `just generate-inherit-registry`.
    """
    from dbt_charts.core.compile.models.style.theme import Style
    from dbt_charts.core.compile.resolve.style.inherit_graph import (
        build_slot_graph,
        flatten_inherit_chains,
    )

    assert _REGISTRY_PATH.exists(), (
        f"inherit_registry.yaml not found at {_REGISTRY_PATH}. "
        "Run: just generate-inherit-registry"
    )

    committed = yaml.safe_load(_REGISTRY_PATH.read_text()) or {}
    live_chains = flatten_inherit_chains(build_slot_graph(Style))

    # Normalize: committed stores lists, live stores tuples.
    committed_normalized = {k: tuple(v) for k, v in committed.items()}

    assert committed_normalized == live_chains, (
        "inherit_registry.yaml is stale. Re-run: just generate-inherit-registry"
    )


def test_generate_script_writes_to_committed_registry_path():
    """generate_inherit_registry.py's output path must match the committed registry."""
    spec = importlib.util.spec_from_file_location(
        "generate_inherit_registry",
        DBT_CHARTS_DIR / "scripts" / "generate_inherit_registry.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._OUT == _REGISTRY_PATH


def test_registry_uses_slot_level_keys():
    """inherit_registry.yaml must use slot-container paths, not per-leaf paths."""
    committed = yaml.safe_load(_REGISTRY_PATH.read_text()) or {}

    assert "Style.charts.font" in committed, (
        "registry should have slot-level 'Style.charts.font' key"
    )
    assert "Style.charts.font.color" not in committed, (
        "registry must not have leaf-level 'Style.charts.font.color' key"
    )


# ── SchemaField inherit metadata ──────────────────────────────────────────────


def test_schema_field_has_inherit_from_attribute():

    import dataclasses

    names = {f.name for f in dataclasses.fields(SchemaField)}
    assert "inherit_from" in names, "SchemaField is missing inherit_from field"
    assert "inherit_slot" in names, "SchemaField is missing inherit_slot field"


def test_build_schema_field_reads_inherit_marker():
    """_build_schema_field populates inherit_from from an Inherit marker."""

    class _Inner(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        color: str

    class _Root(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        inner: _Inner
        color: Annotated[str, Inherit(from_path="inner.color")]

    fi = _Root.model_fields["color"]
    sf = _build_schema_field("color", fi, fi.annotation)

    assert sf.inherit_from == ("inner.color",)
    assert sf.inherit_slot is None


def test_build_schema_field_reads_inherit_slot_marker():
    """_build_schema_field populates inherit_slot from an InheritSlot marker."""

    class _AxisFixture(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        visible: bool

    class _ChartsFixture(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        axis: _AxisFixture
        axis_x: Annotated[_AxisFixture, InheritSlot(from_path="charts.axis")]

    fi = _ChartsFixture.model_fields["axis_x"]
    sf = _build_schema_field("axis_x", fi, fi.annotation)

    assert sf.inherit_slot == "charts.axis"
    assert sf.inherit_from == ()


def test_build_schema_field_no_markers_leaves_inherit_empty():
    """Fields without Inherit/InheritSlot markers have empty/None inherit fields."""

    class _Plain(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        name: str

    fi = _Plain.model_fields["name"]
    sf = _build_schema_field("name", fi, fi.annotation)

    assert sf.inherit_from == ()
    assert sf.inherit_slot is None


# ── Style model collection in introspection IR ────────────────────────────────


def test_compiled_style_models_in_ir():
    """Compiled style models from theme.py must appear in the introspection IR."""
    from dbt_charts.core.compile.schema.introspection import introspect

    ir = introspect()
    # Style is the root compiled model — it must be present.
    assert "Style" in ir.models, (
        "Style not found in IR — _is_authored_model should accept style.theme models"
    )


def test_style_chart_style_in_ir():
    """ChartsStyle (a nested compiled style model) must appear in the IR."""
    from dbt_charts.core.compile.schema.introspection import introspect

    ir = introspect()
    assert "ChartsStyle" in ir.models
