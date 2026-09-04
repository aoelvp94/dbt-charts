"""Render-time capture of endpoint-label rails that could not honour their
intended gap.

``recascade_endpoint_labels`` (``features/endpoint_labels.py``) distributes
labels evenly across the raw y domain when ``(n - 1) * gap`` exceeds the
domain span, and drops individual labels that still collide even when that
check passes — both are defined degradations for a legitimate but cramped
layout, not a silent fallback. This module is the seam that lets a warning
detector see them, mirroring ``table_overflow.py``: the converter records the
outcome at the exact point it decides to distribute evenly or drop, into a
sink that ``endpoint_label_gap_overflow.py``'s detector reads via
``WarningContext.endpoint_label_gap_overflows``.

The sink is a ``ContextVar`` set around the SVG render, mirroring the existing
render-context vars in ``renderer.py``. Board rendering is single-threaded, so
the recorder's call lands in the same context the collector opened. When no
sink is open (non-SVG formats, which never probe the rendered scenegraph),
recording is a no-op.

A chart can be recascaded more than once while a single sink is open — the
render-first sizing pass tries a chart at an aspect-ratio estimate, then
again at its slot-fixed height, then again if cols-alignment stretches it to
match a taller sibling in the same row. Only the *last* recascade for a
chart id is the one whose SVG survives (gets cached, and is what a
cache-hit main pass reuses without recascading again) — an earlier trial's
verdict is not information about what shipped. ``record_endpoint_label_gap_overflow``
is therefore called on every recascade, including a ``fit`` outcome, passing
``None`` to clear a stale overflow a narrower/shorter trial left behind;
``sinks[-1][chart_id] = overflow`` unconditionally overwrites, so the sink
always reflects only the most recent recascade seen.
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
    intended pixel gap. ``cause`` distinguishes three degradations, which
    have different remedies: ``gap_did_not_fit`` is a height/series-count
    problem — every label is kept, spaced evenly below the intended gap.
    ``no_slope`` is a data one (every series ends on the same value, so no
    scale could be measured) — every label is kept. ``rail_overflow`` is the
    narrower case where the gap fits in the best case but the real anchors
    are clustered enough that some labels still could not be placed —
    ``dropped_series`` names them; they are omitted from the rendered rail
    rather than piled onto the domain edge. Reporting all three as one told
    authors to add height a chart height could not fix, or hid dropped
    labels behind a "labels are cramped" message that undersold what
    happened.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    series_count: int
    gap_px: float
    cause: Literal["gap_did_not_fit", "no_slope", "rail_overflow"]
    dropped_series: tuple[str, ...] = ()


_sinks: contextvars.ContextVar[
    tuple[dict[str, EndpointLabelGapOverflow | None], ...]
] = contextvars.ContextVar("endpoint_label_gap_overflow_sinks", default=())


@contextmanager
def collect_endpoint_label_gap_overflows() -> Generator[
    dict[str, EndpointLabelGapOverflow | None]
]:
    """Open a fresh sink for the duration of a render; yield the collected map.

    A chart id maps to ``None`` when its most recent recascade fit — callers
    that only want real overflows must drop those entries themselves (see
    ``renderer.py``, which filters before building ``WarningContext``).

    Pops the sink on exit so nested renders don't leak into each other.
    """
    collected: dict[str, EndpointLabelGapOverflow | None] = {}
    token = _sinks.set((*_sinks.get(), collected))
    try:
        yield collected
    finally:
        _sinks.reset(token)


def record_endpoint_label_gap_overflow(
    chart_id: str, overflow: EndpointLabelGapOverflow | None
) -> None:
    """Record the most recent recascade's outcome for ``chart_id``, if a sink is open.

    Pass ``None`` for a ``fit`` outcome — this clears any overflow an earlier
    recascade of the same chart recorded, so a chart recascaded more than
    once in a single sink's lifetime (render-first sizing may retry a chart
    at more than one candidate height) never keeps a verdict from a trial
    that was not the one that shipped. No-op when no sink is open (e.g.
    non-SVG formats).
    """
    sinks = _sinks.get()
    if sinks:
        sinks[-1][chart_id] = overflow
