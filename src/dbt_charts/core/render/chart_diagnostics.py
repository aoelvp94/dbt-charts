"""Turning a chart-scoped exception into the Diagnostic every surface publishes.

Stage: RENDER. A neutral leaf so the three modules that materialise chart
errors — the sizing pass, the SVG walk, and the data-format walk — share one
payload shape instead of each stamping its own subset of identity fields.
"""

from __future__ import annotations

from dbt_charts.core.diagnostics import Diagnostic
from dbt_charts.core.diagnostics.base import DbtChartsError


def stamp_chart_diagnostic(
    exc: DbtChartsError, chart_id: str, source_path: str
) -> Diagnostic:
    """Attach chart identity to ``exc`` and return its Diagnostic.

    The two identity keys are deliberately different channels, not duplicates:
    ``fields["chart_id"]`` rides into the ``_error`` marker that agents and CI
    read, while ``path`` is what the compile-time source map resolves to a
    line number for click-to-source.
    """
    exc.fields["chart_id"] = chart_id
    diagnostic = exc.to_diagnostic()
    diagnostic.path = source_path
    return diagnostic
