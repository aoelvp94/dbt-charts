"""Axis style ticks/mirror invariants after per-variant split.

``ticks`` lives on ``BaseAxisStyle`` and is a fully-defaulted container
(all sub-fields None-defaulted) -- it must default via ``default_factory``,
not force theme YAML to write ``{}``.

``mirror`` lives on ``AxisYStyle`` (y-axis feature only).
``fill`` lives on ``AxisXStyle`` (x-axis feature only).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.style.theme.axis import (
    AxisMirrorStyle,
    AxisXStyle,
    AxisYStyle,
)


def test_axis_style_ticks_defaults_when_not_provided():
    axis = AxisXStyle(fill="null", fiscal_year_start_month=1)
    assert axis.ticks is not None


def test_axis_style_ticks_defaults_when_omitted():
    axis = AxisXStyle.model_validate({"fill": "null", "fiscal_year_start_month": 1})
    assert axis.ticks.visible is None


def test_axis_style_mirror_accepts_plain_bool():
    """The existing ``mirror: true`` shorthand keeps working unchanged."""
    axis = AxisYStyle.model_validate({"mirror": True})
    assert axis.mirror is True


def test_axis_style_mirror_accepts_format_override_object():
    """``mirror: {format: ...}`` relabels the mirrored edge without a second scale."""
    axis = AxisYStyle.model_validate({"mirror": {"format": ".0%"}})
    assert isinstance(axis.mirror, AxisMirrorStyle)
    assert axis.mirror.format == ".0%"
    assert axis.mirror.expr is None


def test_axis_style_mirror_object_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AxisYStyle.model_validate({"mirror": {"bogus": 1}})


def test_axis_style_mirror_object_rejects_empty_object():
    """`mirror: {}` is meaningless input -- an override object that overrides
    nothing. Error fast and point the author at ``mirror: true``."""
    with pytest.raises(ValidationError, match="mirror: true"):
        AxisYStyle.model_validate({"mirror": {}})


def test_axis_style_mirror_object_rejects_format_plus_expr():
    """format and expr are both label overrides for the same edge; VL ignores
    format whenever labelExpr is present, so both-set would make format dead
    config -- reject rather than silently prefer expr."""
    with pytest.raises(ValidationError, match="not both"):
        AxisYStyle.model_validate({"mirror": {"format": ".0%", "expr": "datum.value"}})
