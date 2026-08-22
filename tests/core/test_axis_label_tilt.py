"""Tests for the tilt-picker and theme tilt_increments defaults.

Covers:
  - AxisLabelStyle.tilt_increments — list[float] | None, min_length=1
  - _pick_tilt(label, x_field, data, chart_width, label_usable_ratio) — fit-based picker
  - Theme default tilt_increments under axis_x.labels
"""

from __future__ import annotations

from typing import Any

import pytest

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style
from dbt_charts.core.compile.resolve.style.axis_cascade import resolved_axis_style
from dbt_charts.core.render.chart.emitters._label_overlap import (
    _pick_tilt as _pick_tilt_v2,
)


def _pick_tilt_angle(
    x_field: str,
    data: list[dict[str, Any]],
    charts: Any,
    chart_width: float,
    label_usable_ratio: float = 1.0,
) -> tuple[float, bool]:
    """Thin adapter: run the tilt picker against the fully-merged axis_x.labels.

    charts.axis_x is authored-only (SkipInheritSlots) — resolved_axis_style()
    merges it onto charts.axis to get the complete, theme-cascaded axis state.
    """
    axis_x = resolved_axis_style(
        charts, "axis_x", "ordinal", chart_type="", label_authored=False
    )
    return _pick_tilt_v2(
        axis_x.labels,
        x_field,
        data,
        chart_width,
        label_usable_ratio,
    )


@pytest.fixture(autouse=True)
def _reset():
    from dbt_charts.core.compile.config import reset_config

    reset_config()
    yield
    reset_config()


# =============================================================================
# Schema: tilt_increments field
# =============================================================================


class TestTiltIncrementsField:
    def test_accepts_list_of_floats(self):
        from dbt_charts.core.compile.models.style.theme import DimensionLabelStyle

        e = DimensionLabelStyle(tilt_increments=[0, -30, -45, -60, -90])
        assert e.tilt_increments == [0.0, -30.0, -45.0, -60.0, -90.0]

    def test_accepts_single_element_list(self):
        from dbt_charts.core.compile.models.style.theme import DimensionLabelStyle

        e = DimensionLabelStyle(tilt_increments=[-45])
        assert e.tilt_increments == [-45.0]

    def test_rejects_empty_list(self):
        """Empty list would IndexError in picker fall-through. min_length=1 prevents."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.style.theme import DimensionLabelStyle

        with pytest.raises(ValidationError):
            DimensionLabelStyle(tilt_increments=[])

    def test_rejects_non_numeric(self):
        """Non-coercible entries fail. (Pydantic coerces numeric strings → floats
        consistent with other axis float fields like padding.)"""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.style.theme import DimensionLabelStyle

        with pytest.raises(ValidationError):
            DimensionLabelStyle(tilt_increments=[{"angle": -30}])


# =============================================================================
# Theme default: tilt_increments lives under axis_x.labels
# =============================================================================


class TestThemeTiltIncrementsDefault:
    def test_default_theme_axis_x_tilt_increments(self):
        from dbt_charts.core.compile.config import (
            get_theme_style,
        )

        style = get_theme_style()
        increments = style.charts.axis_x.labels.tilt_increments
        # The descending ladder: starts at 0 (flat), includes only negative angles.
        assert increments is not None
        assert len(increments) > 0
        assert 0 in increments
        assert all(v <= 0 for v in increments), "all angles must be flat or negative"
        # List must be in descending order (0 first, most negative last)
        assert increments == sorted(increments, reverse=True)

    def test_axis_y_has_no_tilt_increments(self):
        """Y-axis label is AxisLabelStyle — tilt_increments is structurally absent."""
        from dbt_charts.core.compile.models.style.theme import AxisLabelStyle

        assert "tilt_increments" not in AxisLabelStyle.model_fields


# =============================================================================
# Picker: _pick_tilt_angle(x_field, data, resolved_style, chart_width)
# =============================================================================


def _resolved_charts():
    """Resolved default ChartStyleContext; the cascade fills axis_x.labels.tilt_increments."""
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    return resolve_chart_style_context(get_theme_style())


class TestPickTiltAngle:
    def test_short_labels_fit_at_zero(self):
        """Tiny labels at wide chart should fit at angle=0."""

        charts = _resolved_charts()
        data = [{"x": v} for v in ["A", "B", "C", "D"]]
        angle, fits = _pick_tilt_angle("x", data, charts, chart_width=1200)
        assert fits is True
        assert angle == 0

    def test_long_labels_force_steeper_angle(self):
        """Same chart width with longer labels should pick a non-zero angle."""

        charts = _resolved_charts()
        data = [
            {"x": v}
            for v in [
                "Northern California region",
                "Pacific Northwest region",
                "Greater Bay Area metropolitan",
                "Southern Oregon coast",
                "Eastern Washington plateau",
                "Central California valley",
                "Sierra Nevada foothills",
                "Mojave Desert southeast",
            ]
        ]
        angle, fits = _pick_tilt_angle("x", data, charts, chart_width=400)
        assert angle != 0  # at this density, angle 0 cannot fit

    def test_extreme_density_falls_through_to_last(self):
        """Too many long labels — picker exhausts the ladder and returns (last, False)."""

        charts = _resolved_charts()
        # 60 long labels at 200px chart — even at -90 the band width is tiny.
        data = [{"x": f"Very long category label number {i}"} for i in range(60)]
        angle, fits = _pick_tilt_angle("x", data, charts, chart_width=200)
        assert fits is False
        # Last entry of the default ladder.
        assert angle == charts.axis_x.labels.tilt_increments[-1]

    def test_honors_theme_override_ladder(self):
        """Picker uses tilt_increments from the resolved style, not a hardcode."""
        from dbt_charts.core.compile.config import get_config
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )

        get_config()  # ensure settings initialised
        patched = get_theme_style().model_copy(
            deep=True,
            update={
                "charts": get_theme_style().charts.model_copy(
                    deep=True,
                    update={
                        "axis_x": get_theme_style(
                            get_default_theme_name()
                        ).charts.axis_x.model_copy(
                            update={
                                "labels": get_theme_style(
                                    get_default_theme_name()
                                ).charts.axis_x.labels.model_copy(
                                    update={"tilt_increments": [-90]}
                                )
                            }
                        )
                    },
                )
            },
        )
        charts = resolve_chart_style_context(patched)
        data = [{"x": "A"}, {"x": "B"}]
        angle, _fits = _pick_tilt_angle("x", data, charts, chart_width=1200)
        # Single-entry ladder must pick that entry.
        assert angle == -90

    def test_no_data_returns_zero_fits_true(self):
        """Empty data — nothing to lay out; angle 0 is the safe default."""

        charts = _resolved_charts()
        angle, fits = _pick_tilt_angle("x", [], charts, chart_width=1200)
        assert angle == 0
        assert fits is True
