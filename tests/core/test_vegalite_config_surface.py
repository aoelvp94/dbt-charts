"""Tests for the hand-owned VegaLiteConfig surface contract.

The VegaLiteConfig model must explicitly cover every Vega-Lite config field
that Dataface ships through its built-in themes. style_to_vega_lite()
validates its output against VegaLiteConfig, so a missing field on a shipped
theme will surface here as a validation error.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.config import (
    get_theme_style,
    reset_config,
)
from dbt_charts.core.compile.models.vega_lite.config import VegaLiteConfig
from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context
from dbt_charts.core.compile.vega_lite.mapping import style_to_vega_lite


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def test_vegalite_config_model_validates_compiled_theme():
    """A compiled unified theme should produce a valid VegaLiteConfig via style_to_vega_lite."""
    compiled = get_theme_style()
    config = style_to_vega_lite(resolve_chart_style_context(compiled))
    # axis/legend moved to encoding level; check view (stays at config)
    assert config.view is not None


def test_vegalite_config_rejects_extra_fields():
    """VegaLiteConfig should NOT silently accept unknown fields.

    VegaLiteConfig is a closed contract. Unknown fields must be explicitly added.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VegaLiteConfig.model_validate({"inventedField": True})


def test_title_position_block_emits_anchor():
    """title.position.anchor round-trips through style_to_vega_lite."""
    compiled = get_theme_style("stark")
    # access via position block — confirms structure is nested
    assert compiled.title.position.anchor is not None
    vl_cfg = style_to_vega_lite(resolve_chart_style_context(compiled))
    assert vl_cfg.title is not None
    assert vl_cfg.title.anchor is not None


def test_title_position_block_diagnostic_override():
    """Diagnostic themes that set offset under position.* must propagate."""
    compiled = get_theme_style("diagnostics-title-offset-extreme")
    assert compiled.title.position.offset is not None
    vl_cfg = style_to_vega_lite(resolve_chart_style_context(compiled))
    assert vl_cfg.title is not None
    assert vl_cfg.title.offset is not None


def test_vegalite_config_scale_field_rejected():
    """scale: is not part of VegaLiteConfig — ScaleConfig was deleted.

    style_to_vega_lite() never emits config.scale; encoding-level scale
    overrides go through encoding.{x,y}.scale via BaseScaleStyle instead.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="scale"):
        VegaLiteConfig.model_validate({"scale": {"bandPaddingInner": 0.5}})


@pytest.mark.parametrize(
    "key", ["axis", "axisX", "axisY", "axisBand", "axisQuantitative"]
)
def test_vegalite_config_axis_keys_rejected(key: str) -> None:
    """axis* keys are not part of VegaLiteConfig — axis style is emitted at encoding level.

    style_to_vega_lite() never writes config.axis*; axis_to_vl in
    vl_field_maps.py applies axis style at encoding.x.axis / encoding.y.axis. All 5
    config-level axis variants (axis, axisX, axisY, axisBand, axisQuantitative)
    have been deleted from VegaLiteConfig. This also covers the historical
    formatType rejection — the entire axis key is gone, not just that sub-field.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=key):
        VegaLiteConfig.model_validate({key: {"domain": True}})


def test_vegalite_config_legend_key_rejected() -> None:
    """legend key is not part of VegaLiteConfig — legend style is emitted at encoding level.

    style_to_vega_lite() never writes config.legend; apply_color_legend in
    emitters/_channels.py applies legend style at encoding.color.legend /
    encoding.size.legend.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="legend"):
        VegaLiteConfig.model_validate({"legend": {"orient": "right"}})


@pytest.mark.parametrize(
    "key", ["bar", "line", "area", "arc", "point", "geoshape", "image"]
)
def test_vegalite_config_chart_mark_keys_rejected(key: str) -> None:
    """Per-chart mark keys not in VegaLiteConfig — emitted at spec.mark level.

    style_to_vega_lite() never writes config.{bar,line,area,arc,point};
    mark properties go via spec.mark, built per-family in the emitters.
    config.geoshape and config.image have no Dataface style equivalent.
    Generic marks (circle/square/tick/rule/trail/rect/path/shape/symbol/text)
    ARE populated and remain in VegaLiteConfig.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=key):
        VegaLiteConfig.model_validate({key: {"fill": "#ff0000"}})
