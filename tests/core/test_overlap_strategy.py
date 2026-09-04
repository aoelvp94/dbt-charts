"""Tests for overlap strategy struct: tilt/skip booleans (categorical axis labels).

Covers:
  - AxisLabelOverlapConfig: two-bool struct; extra=forbid rejects unknown keys;
    partial authoring (tilt: false only) inherits remainder from cascade
  - ResolvedAxisLabelOverlapConfig: required bools after resolve
  - Theme cascade: overlap struct with both bools set flows to axis_x.labels
  - resolve_axis_x_overlap: categorical labels tilt without skipping; temporal
    labels use fixed skip→tilt order; overlap, angle, and temporal
    visibility are render-local and never written onto the resolved model
  - Resolver outcomes: fits-flat, categorical tilt without skip, exhausted→allow,
    authored-angle short-circuit, horizontal-bar short-circuit
  - Font size on x-axis labels is never mutated by the resolver (shrink is gone)
  - Temporal-bucketed axes use fiscal-anchored visibility thinning
  - VL emission: directive parameter on axis_to_vl reaches labelOverlap in vl_field_maps
"""

from __future__ import annotations

import dataclasses
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _resolved_charts() -> Any:
    """Default ChartStyleContext from theme cascade."""
    from dbt_charts.core.compile.config import get_theme_style
    from dbt_charts.core.compile.resolve.style.board import resolve_chart_style_context

    return resolve_chart_style_context(get_theme_style())


def _overlap(tilt: bool = True, skip: bool = True) -> Any:
    """Convenience: build a ResolvedAxisLabelOverlapConfig."""
    from dbt_charts.core.compile.models.style.resolved import (
        ResolvedAxisLabelOverlapConfig,
    )

    return ResolvedAxisLabelOverlapConfig(tilt=tilt, skip=skip)


def _axis_x_with(
    overlap: Any = None,  # ResolvedAxisLabelOverlapConfig | None
    angle: float | None = None,
    tilt_increments: list[float] | None = None,
    font_size: float | None = None,
) -> Any:
    """Resolved axis_x with controlled overlap config and optional overrides.

    Starts from the fully-merged axis_x (resolved_axis_style — axis_x itself is
    now an authored-only sparse overlay, not theme-complete) so fonts,
    tilt_increments, etc. are populated, then patches specific fields via
    dataclasses.replace.
    """
    from dbt_charts.core.compile.resolve.style.axis_cascade import resolved_axis_style

    charts = _resolved_charts()
    axis_x = resolved_axis_style(
        charts, "axis_x", "ordinal", chart_type="", label_authored=False
    )
    label = axis_x.labels
    font = label.font

    if font_size is not None:
        font = font.model_copy(update={"size": font_size})

    label = dataclasses.replace(
        label,
        font=font,
        overlap=overlap,
        angle=angle,
        tilt_increments=(
            tilt_increments if tilt_increments is not None else label.tilt_increments
        ),
    )
    return dataclasses.replace(axis_x, labels=label)


def _make_mock_measurer(width_per_char: float = 5.0) -> Any:
    """Font measurer mock: width = width_per_char * len(text) * (size / 11)."""
    m = MagicMock()
    m.measure = lambda text, size: width_per_char * len(text) * (size / 11.0)
    return m


# ---------------------------------------------------------------------------
# 1. Authored model: AxisLabelOverlapConfig struct
# ---------------------------------------------------------------------------


class TestAxisLabelOverlapConfig:
    def test_both_true_accepted(self) -> None:
        from dbt_charts.core.compile.models.style.theme.axis import (
            AxisLabelOverlapConfig,
        )

        cfg = AxisLabelOverlapConfig(tilt=True, skip=True)
        assert cfg.tilt is True
        assert cfg.skip is True

    def test_partial_false_accepted(self) -> None:
        """Disable one strategy; the other unset (cascade-inherit)."""
        from dbt_charts.core.compile.models.style.theme.axis import (
            AxisLabelOverlapConfig,
        )

        cfg = AxisLabelOverlapConfig(tilt=False)
        assert cfg.tilt is False
        assert cfg.skip is None

    def test_both_false_accepted(self) -> None:
        from dbt_charts.core.compile.models.style.theme.axis import (
            AxisLabelOverlapConfig,
        )

        cfg = AxisLabelOverlapConfig(tilt=False, skip=False)
        assert cfg.tilt is False
        assert cfg.skip is False

    def test_empty_construction_all_none(self) -> None:
        """No args → all None (inherit everything from cascade)."""
        from dbt_charts.core.compile.models.style.theme.axis import (
            AxisLabelOverlapConfig,
        )

        cfg = AxisLabelOverlapConfig()
        assert cfg.tilt is None
        assert cfg.skip is None

    def test_unknown_key_rejected_via_extra_forbid(self) -> None:
        """extra=forbid: unknown keys are rejected without a custom validator."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.style.theme.axis import (
            AxisLabelOverlapConfig,
        )

        with pytest.raises(ValidationError, match="extra_forbidden"):
            AxisLabelOverlapConfig(tilt=True, greedy=True)  # type: ignore[call-arg]

    def test_list_rejected_for_overlap_field(self) -> None:
        """The old list format is rejected — AxisLabelStyle.overlap is the struct."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.style.theme.axis import AxisLabelStyle

        with pytest.raises(ValidationError):
            AxisLabelStyle(overlap=["tilt", "skip"])  # type: ignore[arg-type]

    def test_string_allow_rejected(self) -> None:
        """The old 'allow' sugar string is rejected — use { tilt: false, skip: false }."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.style.theme.axis import AxisLabelStyle

        with pytest.raises(ValidationError):
            AxisLabelStyle(overlap="allow")  # type: ignore[arg-type]

    def test_string_smart_rejected(self) -> None:
        """The old 'smart' sugar string is rejected — omit overlap to inherit."""
        from pydantic import ValidationError

        from dbt_charts.core.compile.models.style.theme.axis import AxisLabelStyle

        with pytest.raises(ValidationError):
            AxisLabelStyle(overlap="smart")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Theme cascade: struct with both bools flows through
# ---------------------------------------------------------------------------


class TestOverlapThemeCascade:
    def test_theme_cascade_provides_overlap_struct(self) -> None:
        """After cascade, axis_x.labels.overlap is a ResolvedAxisLabelOverlapConfig."""
        from dbt_charts.core.compile.config import get_theme_style
        from dbt_charts.core.compile.models.style.resolved import (
            ResolvedAxisLabelOverlapConfig,
        )
        from dbt_charts.core.compile.resolve.style.axis_cascade import (
            resolved_axis_style,
        )
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )

        charts = resolve_chart_style_context(get_theme_style())
        axis_x = resolved_axis_style(
            charts, "axis_x", "ordinal", chart_type="", label_authored=False
        )
        overlap = axis_x.labels.overlap
        assert isinstance(overlap, ResolvedAxisLabelOverlapConfig)

    def test_default_overlap_both_strategies_enabled(self) -> None:
        """The theme default enables both strategies."""
        from dbt_charts.core.compile.config import get_theme_style
        from dbt_charts.core.compile.resolve.style.axis_cascade import (
            resolved_axis_style,
        )
        from dbt_charts.core.compile.resolve.style.board import (
            resolve_chart_style_context,
        )

        charts = resolve_chart_style_context(get_theme_style())
        axis_x = resolved_axis_style(
            charts, "axis_x", "ordinal", chart_type="", label_authored=False
        )
        overlap = axis_x.labels.overlap
        assert overlap is not None
        assert overlap.tilt is True
        assert overlap.skip is True


# ---------------------------------------------------------------------------
# 3. Resolver: directive is render-local (not on the resolved model)
# ---------------------------------------------------------------------------


class TestLabelOverlapSeparateField:
    def test_resolver_does_not_overwrite_overlap_struct(self) -> None:
        """After resolve_axis_x_overlap, the authored overlap struct is intact."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        ov = _overlap()
        axis_x = _axis_x_with(overlap=ov)
        data = [{"x": "A"}, {"x": "B"}, {"x": "C"}]
        layout = resolve_axis_x_overlap(
            axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=1200.0
        )
        assert axis_x.labels.overlap is ov
        assert layout.label_overlap == "allow"


# ---------------------------------------------------------------------------
# 4. Resolver: strategy walk outcomes (categorical axes)
# ---------------------------------------------------------------------------


class TestResolverStrategyWalk:
    def test_all_disabled_returns_allow(self) -> None:
        """Both strategies disabled → no reduction, directive=allow."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis_x = _axis_x_with(overlap=_overlap(tilt=False, skip=False))
        data = [{"x": v} for v in ["A", "B", "C"]]
        layout = resolve_axis_x_overlap(
            axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=600.0
        )
        assert layout.label_overlap == "allow"

    def test_authored_angle_short_circuits_to_allow(self) -> None:
        """When angle is authored, strategy config is bypassed; directive = allow."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis_x = _axis_x_with(overlap=_overlap(), angle=-45.0)
        data = [{"x": v} for v in ["A", "B", "C"]]
        layout = resolve_axis_x_overlap(
            axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=600.0
        )
        assert layout.label_overlap == "allow"
        assert layout.angle == -45.0

    def test_horizontal_bar_short_circuits_to_allow_at_zero(self) -> None:
        """Horizontal bar pins angle=0, directive=allow regardless of strategies."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis_x = _axis_x_with(overlap=_overlap())
        data = [{"x": v} for v in ["A", "B", "C"]]
        layout = resolve_axis_x_overlap(
            axis_x,
            "x",
            data,
            1.0,
            is_horizontal_bar=True,
            edge_labels_flushed=False,
            chart_width=600.0,
        )
        assert layout.label_overlap == "allow"
        assert layout.angle == 0.0

    def test_short_labels_fit_flat_font_size_unchanged(self) -> None:
        """Short labels at a wide chart fit unrotated; font size never moves."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        mock_measurer = _make_mock_measurer(width_per_char=5.0)
        axis_x = _axis_x_with(overlap=_overlap(), font_size=11.0)
        data = [{"x": f"Aa{i:02d}"} for i in range(10)]  # 4-char labels

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=mock_measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=300.0
            )

        assert layout.label_overlap == "allow"
        assert axis_x.labels.font.size == 11.0
        assert layout.angle == 0.0

    def test_tilt_attempted_when_labels_dont_fit_flat(self) -> None:
        """When labels don't fit unrotated, tilt is attempted; font size is untouched."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        mock_measurer = _make_mock_measurer(width_per_char=5.0)
        axis_x = _axis_x_with(
            overlap=_overlap(),
            tilt_increments=[0.0, -30.0, -45.0, -60.0, -90.0],
            font_size=11.0,
        )
        data = [{"x": f"Hello{i}"} for i in range(30)]

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=mock_measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=200.0
            )

        assert layout.label_overlap == "allow"
        assert axis_x.labels.font.size == 11.0

    def test_nominal_tilt_angle_is_picked_against_domain_values_not_data(self) -> None:
        """The tilt angle picked for a nominal/ordinal axis must come from the
        same widths the flat-fit gate already measures against
        ``domain_values`` — not re-derived from ``data`` alone.

        ``data`` carries 3 short single-char labels: on their own they fit
        flat (wide per-label band). ``domain_values`` — the union an overlay
        layer widens the shared scale to (``overlay_x_domain_values``) —
        carries 30 same-width labels: a much narrower band that does not fit
        flat and needs the steepest tilt available. Picking the angle from
        ``data`` alone (the pre-fix behaviour) returns 0.0 here even though
        the rendered axis has 30 crowded bands, not 3.
        """
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        mock_measurer = _make_mock_measurer(width_per_char=5.0)
        tilt_increments = [0.0, -30.0, -45.0, -60.0, -90.0]
        axis_x = _axis_x_with(
            overlap=_overlap(), tilt_increments=tilt_increments, font_size=11.0
        )
        data = [{"x": f"L{i}"} for i in range(3)]
        domain_values = [f"L{i}" for i in range(30)]

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=mock_measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis_x,
                "x",
                data,
                1.0,
                edge_labels_flushed=False,
                chart_width=200.0,
                domain_values=domain_values,
            )

        assert layout.angle == tilt_increments[-1], layout.angle

    def test_skip_strategy_does_not_drop_categorical_labels(self) -> None:
        """Ordinal domains keep every label because skipped categories are unrecoverable."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        mock_measurer = _make_mock_measurer(width_per_char=5.0)
        axis_x = _axis_x_with(overlap=_overlap(tilt=False, skip=True), font_size=11.0)
        data = [{"x": f"Cat{i}"} for i in range(20)]

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=mock_measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=200.0
            )

        assert layout.label_overlap == "allow"

    def test_all_strategies_exhausted_produces_allow(self) -> None:
        """When all enabled strategies exhaust without fitting, fall through to allow."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        mock_measurer = _make_mock_measurer(width_per_char=5.0)
        axis_x = _axis_x_with(
            overlap=_overlap(tilt=True, skip=False),
            tilt_increments=[0.0],  # only tries horizontal
            font_size=11.0,
        )
        # Very crowded: 50 labels at 200px → band=4px, nothing fits
        data = [{"x": f"LongCat{i}"} for i in range(50)]

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=mock_measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=200.0
            )

        # No skip → exhausted list → allow (tolerate remaining overlap)
        assert layout.label_overlap == "allow"

    def test_pairwise_adjacent_fit_avoids_tilt_when_wide_label_has_short_neighbors(
        self,
    ) -> None:
        """Pairwise check: wide label adjacent to short neighbors fits at current size."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        mock_measurer = _make_mock_measurer(width_per_char=5.0)
        axis_x = _axis_x_with(overlap=_overlap(), font_size=11.0)
        data = [
            {"x": "Long Month Name"},  # 15 chars → 75px
            {"x": "Sep"},  # 3 chars → 15px
            {"x": "Oct"},  # 3 chars → 15px
        ]

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=mock_measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=200.0
            )

        assert layout.label_overlap == "allow"
        assert axis_x.labels.font.size == 11.0
        assert layout.angle == 0.0

    def test_skip_disabled_with_crowded_axis_falls_through_to_allow(self) -> None:
        """When skip is False and tilt fails to fit, result is allow (not parity)."""
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        mock_measurer = _make_mock_measurer(width_per_char=5.0)
        axis_x = _axis_x_with(
            overlap=_overlap(tilt=True, skip=False),
            tilt_increments=[0.0],
            font_size=11.0,
        )
        # 100 crowded labels: tilt will exhaust but skip is disabled → allow
        data = [{"x": f"LongLabel{i:03d}"} for i in range(100)]

        with patch(
            "dbt_charts.core.render.chart.emitters._label_overlap.get_font_measurer",
            return_value=mock_measurer,
        ):
            layout = resolve_axis_x_overlap(
                axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=200.0
            )

        assert layout.label_overlap == "allow"

    def test_temporal_cadence_detect_time_unit_gives_up_falls_through_to_none(
        self,
    ) -> None:
        """A temporal x with no recognizable calendar bucket grain (e.g. a
        28-day cadence — same weekday, but too sparse for detect_time_unit's
        weekly gate) must resolve to directive=None, not "allow": "allow"
        forces VL's own labelOverlap off with no custom thinning computed to
        replace it, so every distinct date renders unthinned. None lets VL's
        native adaptive default (parity) do the reduction instead.
        """
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis_x = _axis_x_with(overlap=_overlap())
        data = [
            {"x": d}
            for d in [
                "2024-01-07",
                "2024-02-04",
                "2024-03-03",
                "2024-03-31",
                "2024-04-28",
            ]
        ]
        layout = resolve_axis_x_overlap(
            axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=600.0
        )
        assert layout.label_overlap is None

    def test_unrecognized_cadence_with_skip_disabled_honors_never_drop(
        self,
    ) -> None:
        """Same unrecognized cadence, but ``overlap.skip: false`` — an explicit
        author opt-out of ever dropping a label. Must resolve to "allow" (VL's
        own thinning disabled too), not None (which hands dropping back to
        VL's adaptive default and silently overrides the opt-out).
        """
        from dbt_charts.core.render.chart.emitters._label_overlap import (
            resolve_axis_x_overlap,
        )

        axis_x = _axis_x_with(overlap=_overlap(skip=False))
        data = [
            {"x": d}
            for d in [
                "2024-01-07",
                "2024-02-04",
                "2024-03-03",
                "2024-03-31",
                "2024-04-28",
            ]
        ]
        layout = resolve_axis_x_overlap(
            axis_x, "x", data, 1.0, edge_labels_flushed=False, chart_width=600.0
        )
        assert layout.label_overlap == "allow"


# ---------------------------------------------------------------------------
# 5. VL emission: label_overlap reaches labelOverlap
# ---------------------------------------------------------------------------


class TestVlEmission:
    def test_label_overlap_parity_emits_to_vl(self) -> None:
        from dbt_charts.core.render.chart.vl_field_maps import axis_to_vl

        axis = _axis_x_with(overlap=_overlap())
        vl = axis_to_vl(axis, label_overlap="parity")
        assert vl.get("labelOverlap") == "parity"

    def test_label_overlap_allow_emits_false_to_vl(self) -> None:
        from dbt_charts.core.render.chart.vl_field_maps import axis_to_vl

        axis = _axis_x_with(overlap=_overlap())
        vl = axis_to_vl(axis, label_overlap="allow")
        assert vl.get("labelOverlap") is False

    def test_label_overlap_none_omits_from_vl(self) -> None:
        from dbt_charts.core.render.chart.vl_field_maps import axis_to_vl

        axis = _axis_x_with(overlap=_overlap())
        vl = axis_to_vl(axis)
        assert "labelOverlap" not in vl
