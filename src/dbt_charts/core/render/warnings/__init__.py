"""Render-time warning system: data-aware detector registry and runner.

The wire shape (``Diagnostic``) and suppression (``partition``) live in
``dbt_charts.core.diagnostics`` — below render — since compile-time authoring
warnings need them too. This package owns only what genuinely needs
render-time data: ``WarningContext`` and the detector registry.
"""

from __future__ import annotations

from dbt_charts.core.render.warnings.base import WarningContext
from dbt_charts.core.render.warnings.registry import DETECTORS, run_all

__all__ = [
    "WarningContext",
    "DETECTORS",
    "run_all",
]
