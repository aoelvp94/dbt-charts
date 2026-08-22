"""Render-time capture of endpoint-label rails whose intended gap could not fit
the available plot height.

``recascade_endpoint_labels`` (``features/endpoint_labels.py``) distributes
labels evenly across the raw y domain when ``(n - 1) * gap`` exceeds the
domain span — a defined degradation for a legitimate but cramped layout, not a
silent fallback. This module is the seam that lets a warning detector see it,
mirroring ``table_overflow.py``: the converter records the overflow at the
exact point it decides to distribute evenly, into a sink that
``WARN_ENDPOINT_LABEL_GAP_OVERFLOW`` reads via
``WarningContext.endpoint_label_gap_overflows``.

The sink is a ``ContextVar`` set around the SVG render, mirroring the existing
render-context vars in ``renderer.py``. Board rendering is single-threaded, so
the recorder's call lands in the same context the collector opened. When no
sink is open (non-SVG formats, which never probe the rendered scenegraph),
recording is a no-op.
"""

from __future__ import annotations

import contextvars
from collections.abc import Generator
from contextlib import contextmanager
from typing import Literal

from pydantic import BaseModel, ConfigDict


class EndpointLabelGapOverflow(BaseModel):
    """An endpoint-label rail whose intended gap could not fit its plot height.

    ``series_count`` is how many labels the rail carries; ``gap_px`` is the
    intended pixel gap. ``cause`` distinguishes the two degradations, which
    have different remedies: ``gap_did_not_fit`` is a height/series-count
    problem, ``no_slope`` is a data one (every series ends on the same value,
    so no scale could be measured). Reporting both as the former told authors
    to add height to a chart height could not fix.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    series_count: int
    gap_px: float
    cause: Literal["gap_did_not_fit", "no_slope"]


_sinks: contextvars.ContextVar[tuple[dict[str, EndpointLabelGapOverflow], ...]] = (
    contextvars.ContextVar("endpoint_label_gap_overflow_sinks", default=())
)


@contextmanager
def collect_endpoint_label_gap_overflows() -> Generator[
    dict[str, EndpointLabelGapOverflow]
]:
    """Open a fresh sink for the duration of a render; yield the collected map.

    Pops the sink on exit so nested renders don't leak into each other.
    """
    collected: dict[str, EndpointLabelGapOverflow] = {}
    token = _sinks.set((*_sinks.get(), collected))
    try:
        yield collected
    finally:
        _sinks.reset(token)


def record_endpoint_label_gap_overflow(
    chart_id: str, overflow: EndpointLabelGapOverflow
) -> None:
    """Record a rail's gap overflow into the innermost open sink, if any.

    No-op when no sink is open (e.g. non-SVG formats).
    """
    sinks = _sinks.get()
    if sinks:
        sinks[-1][chart_id] = overflow
