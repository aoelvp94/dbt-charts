"""Tests for the KPI glyph/tone migration: chart root → style namespace.

Covers:
* Rejection of glyph: / tone: at chart root with did-you-mean hints.
* style.glyph.character compiles through the cascade and renders correctly.
* style.tone is retired entirely — tone lives only on support.tone (the
  block it paints); style.tone is rejected at both the chart root and the
  style namespace.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.models.chart.authored import (
    KpiChart as AuthoredKpiChart,
    KpiSupportConfig,
)
from dbt_charts.core.compile.models.chart.normalized import Chart, KpiChart
from dbt_charts.core.compile.models.query.normalized import SqlQuery
from dbt_charts.core.compile.models.style.authored import KpiChartStylePatch
from dbt_charts.core.compile.resolve import resolve
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.render.chart.kpi import render_kpi_svg

_DUMMY_QUERY = SqlQuery(sql="SELECT 1", source="t")


def _es():
    return resolve_chart_style_context(get_theme_style())


def _board_style():
    return resolve_style(get_theme_style())


def _chart_style_context():
    return resolve_chart_style_context(get_theme_style())


# ---------------------------------------------------------------------------
# Rejection: glyph / tone at chart root must raise with did-you-mean hint
# ---------------------------------------------------------------------------


class TestChartRootRejection:
    def test_glyph_at_chart_root_rejected_with_hint(self):
        """glyph: at KPI chart root must be rejected; author must use style.glyph.character."""
        with pytest.raises(ValidationError, match="style.glyph"):
            AuthoredKpiChart(type="kpi", value="revenue", glyph="▲")

    def test_tone_at_chart_root_rejected_with_hint(self):
        """tone: at KPI chart root must be rejected; author must use support.tone —
        tone lives on the block it paints (the support row), not the headline."""
        with pytest.raises(ValidationError, match="support.tone"):
            AuthoredKpiChart(type="kpi", value="revenue", tone="positive")

    def test_tone_rejection_message_example_requires_value_field(self):
        """The rejection message's example must include value: so the shown
        support block is valid (KpiSupportConfig._require_non_empty rejects
        bare tone without value/label/glyph).

        This test will fail if the message reverts to the old bare
        'support:\\n  tone: positive\\n' example — that shape is rejected by
        _require_non_empty and would mislead authors.
        """
        with pytest.raises(ValidationError) as exc_info:
            AuthoredKpiChart(type="kpi", value="revenue", tone="positive")
        assert "value: <delta_column>" in str(exc_info.value)

    def test_tone_rejection_message_recommended_support_shape_validates(self):
        """The exact support shape recommended in the rejection message is valid.

        support.tone alongside value: is accepted by KpiSupportConfig — authors
        who follow the hint will not hit a second validation error.
        """
        # Must not raise
        config = KpiSupportConfig(value="delta_col", tone="positive")
        assert config.value == "delta_col"
        assert config.tone == "positive"

    def test_bare_tone_without_value_label_glyph_is_invalid_support(self):
        """bare support: {tone: positive} (the OLD broken hint) is rejected.

        _require_non_empty enforces that at least one of value/label/glyph
        must be set — tone alone is insufficient.
        """
        with pytest.raises(ValidationError, match="Empty"):
            KpiSupportConfig(tone="positive")

    def test_both_at_chart_root_rejected(self):
        with pytest.raises(ValidationError):
            AuthoredKpiChart(type="kpi", value="revenue", glyph="▲", tone="positive")

    def test_format_at_chart_root_rejected_with_hint(self):
        """format: at KPI chart root must be rejected; author must use style.value.format."""
        with pytest.raises(ValidationError, match="style.value.format"):
            AuthoredKpiChart(type="kpi", value="revenue", format=",.0f")

    def test_formatter_at_chart_root_rejected_with_hint(self):
        """formatter: at KPI chart root must be rejected; author must use style.value.format."""
        with pytest.raises(ValidationError, match="style.value.format"):
            AuthoredKpiChart(type="kpi", value="revenue", formatter=",.0f")

    def test_style_value_format_accepted(self):
        """The corrected style.value.format shape is accepted at the chart root."""
        chart = AuthoredKpiChart(
            type="kpi",
            value="revenue",
            style=KpiChartStylePatch.model_validate({"value": {"format": ",.0f"}}),
        )
        assert chart.style is not None
        assert chart.style.value is not None
        assert chart.style.value.format == ",.0f"  # type: ignore[union-attr]

    def test_style_tone_rejected(self):
        """style.tone no longer exists on KpiChartStylePatch — extra=forbid rejects it."""
        with pytest.raises(ValidationError, match="tone"):
            KpiChartStylePatch.model_validate({"tone": "positive"})


# ---------------------------------------------------------------------------
# Positive path: style.glyph.character compiles and renders; support.tone
# paints the support row, never the headline value or its glyph.
# ---------------------------------------------------------------------------


def _compiled_kpi_with_style(
    *, glyph_char: str | None = None, support_tone: str | None = None
) -> Chart:
    """Build a compiled Chart with glyph.character via the style namespace and
    an optional tone-carrying support row."""
    kpi_patch: dict = {}
    if glyph_char is not None:
        kpi_patch["glyph"] = {"character": glyph_char}
    style = KpiChartStylePatch.model_validate(kpi_patch) if kpi_patch else None
    support = (
        KpiSupportConfig(label="vs last quarter", tone=support_tone)
        if support_tone is not None
        else None
    )
    return KpiChart(
        id="t",
        query=_DUMMY_QUERY,
        query_name="q",
        type="kpi",
        label="Revenue",
        value="revenue",
        style=style,
        support=support,
    )


class TestStyleNamespacePositivePath:
    def test_glyph_character_renders_in_svg(self):
        """style.glyph.character flows through cascade and appears in KPI SVG output."""
        chart = _compiled_kpi_with_style(glyph_char="▲")
        data = [{"revenue": 1_500_000}]
        resolved = resolve(chart, data, chart_style_context=_chart_style_context())
        svg = render_kpi_svg(
            resolved, data, width=300, height=160, board_style=_board_style()
        )
        assert "▲" in svg

    def test_glyph_character_renders_neutral_regardless_of_support_tone(self):
        """The value-row glyph has no tone source of its own — it renders in the
        neutral value color even when the support row carries a tone."""
        chart = _compiled_kpi_with_style(glyph_char="●", support_tone="positive")
        data = [{"revenue": 1_500_000}]
        resolved = resolve(chart, data, chart_style_context=_chart_style_context())
        es = _es()
        svg = render_kpi_svg(
            resolved, data, width=300, height=160, board_style=_board_style()
        )
        assert "●" in svg
        # The value-row glyph tspan carries the neutral kpi font color, not
        # the support tone — assert the tone hex is absent from that tspan.
        import re

        glyph_tspan = re.search(r"<tspan[^>]*>●\s*</tspan>", svg)
        assert glyph_tspan is not None
        assert es.kpi.tones.positive not in glyph_tspan.group(0)

    def test_no_glyph_character_no_glyph_in_svg(self):
        """When style.glyph.character is absent, no glyph tspan is emitted."""
        chart = _compiled_kpi_with_style()
        data = [{"revenue": 1_500_000}]
        resolved = resolve(chart, data, chart_style_context=_chart_style_context())
        svg = render_kpi_svg(
            resolved, data, width=300, height=160, board_style=_board_style()
        )
        # No ▲, ▼, ● or similar glyphs expected in a plain KPI
        for glyph_char in ("▲", "▼", "●"):
            assert glyph_char not in svg

    def test_style_cascade_via_normalize_chart(self):
        """Authored style dict { glyph: { character: '▲' } } survives compile
        normalization (the _wrap_authored_style path); style.tone in the same
        dict is rejected."""
        from dbt_charts.core.compile.normalize.charts import normalize_chart

        query_registry = {"q": SqlQuery(sql="SELECT 1", source="t")}
        chart = normalize_chart(
            "revenue_kpi",
            {
                "type": "kpi",
                "query": "q",
                "value": "revenue",
                "style": {
                    "glyph": {"character": "▲"},
                },
            },
            query_registry,
            sources={},
        )
        assert chart.style is not None
        assert chart.style.glyph is not None
        assert chart.style.glyph.character == "▲"  # type: ignore[union-attr]

    def test_style_tone_via_normalize_chart_rejected(self):
        """style.tone in authored YAML fails compilation — the field is gone."""
        from dbt_charts.core.compile.errors import CompilationError
        from dbt_charts.core.compile.normalize.charts import normalize_chart

        query_registry = {"q": SqlQuery(sql="SELECT 1", source="t")}
        with pytest.raises(CompilationError, match="tone"):
            normalize_chart(
                "revenue_kpi",
                {
                    "type": "kpi",
                    "query": "q",
                    "value": "revenue",
                    "style": {"tone": "positive"},
                },
                query_registry,
                sources={},
            )
