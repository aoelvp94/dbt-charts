"""Tests for the text_truncation ContextVar seam.

Pins the record/collect contract used by every truncation-surface detector.
"""

from __future__ import annotations

from dbt_charts.core.render.chart.text_truncation import (
    TextTruncation,
    collect_text_truncations,
    record_text_truncation,
)


def test_record_into_open_sink() -> None:
    """record_text_truncation writes into the active sink."""
    with collect_text_truncations() as sinks:
        record_text_truncation("chart1", "axis_title", "A Very Long Title", "x_label")
    assert "chart1" in sinks
    rec = sinks["chart1"][0]
    assert isinstance(rec, TextTruncation)
    assert rec.surface == "axis_title"
    assert rec.authored_field == "x_label"
    assert rec.authored_text == "A Very Long Title"


def test_no_op_when_no_sink_is_open() -> None:
    """record_text_truncation silently no-ops when no collector is open."""
    record_text_truncation("chart1", "axis_title", "text", "x_label")


def test_multiple_surfaces_accumulate() -> None:
    """Different surfaces accumulate into the same chart bucket."""
    with collect_text_truncations() as sinks:
        record_text_truncation("c1", "axis_title", "long x title", "x_label")
        record_text_truncation("c1", "kpi_label", "long kpi label", "label")
        record_text_truncation("c2", "chart_title", "long chart title", "title")
    assert len(sinks["c1"]) == 2
    assert sinks["c1"][0].surface == "axis_title"
    assert sinks["c1"][1].surface == "kpi_label"
    assert sinks["c2"][0].surface == "chart_title"


def test_nested_sinks_are_isolated() -> None:
    """Inner collect_text_truncations does not leak into the outer."""
    with collect_text_truncations() as outer:
        with collect_text_truncations() as inner:
            record_text_truncation("c1", "axis_title", "text", "x_label")
        assert "c1" not in outer
        assert "c1" in inner
