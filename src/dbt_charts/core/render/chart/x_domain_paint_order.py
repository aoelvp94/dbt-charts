"""Render-time capture of a shared categorical x scale left in paint order.

``rendered_x_domain`` places a layer's own x categories into the order the
base query already states. When the base states no order to extend, it
declines rather than guesses, and the union renders in paint order across two
independently-ordered result sets — an axis that reads as a sequence it is
not.

This module is the seam that lets ``WARN_LAYER_X_DOMAIN_PAINT_ORDER`` see that
decision instead of re-deriving it. Re-deriving is what the first version did,
and it drifted immediately: it had no x-type gate (so a layered scatter on a
continuous scale, where no domain is ever pinned, warned), it read raw query
rows rather than the canonicalized ones the emitter actually unions, and it
approximated the authored-sort gate with ``chart.sort is not None`` — true
only for vertical bar, so line/area never warned. Recording at the one site
that makes the call leaves nothing to approximate.

The sink is a ``ContextVar`` set around the render, mirroring
``endpoint_label_overflow.py``. Board rendering is single-threaded, so the
recorder's call lands in the same context the collector opened. When no sink
is open, recording is a no-op.
"""

from __future__ import annotations

import contextvars
from collections.abc import Generator
from contextlib import contextmanager

from pydantic import BaseModel, ConfigDict

from dbt_charts.core.render.utils import DomainValue


class XDomainPaintOrder(BaseModel):
    """A shared x domain whose layer-only values could not be placed.

    ``layer_only`` is the values a layer contributed that the base query never
    returned, in the order they were first painted — the sample the warning
    names.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    x_field: str
    layer_only: tuple[DomainValue, ...]


_sinks: contextvars.ContextVar[tuple[dict[str, XDomainPaintOrder], ...]] = (
    contextvars.ContextVar("x_domain_paint_order_sinks", default=())
)


@contextmanager
def collect_x_domain_paint_orders() -> Generator[dict[str, XDomainPaintOrder]]:
    """Open a fresh sink for the duration of a render; yield the collected map.

    Pops the sink on exit so nested renders don't leak into each other.
    """
    collected: dict[str, XDomainPaintOrder] = {}
    token = _sinks.set((*_sinks.get(), collected))
    try:
        yield collected
    finally:
        _sinks.reset(token)


def record_x_domain_paint_order(chart_id: str, paint_order: XDomainPaintOrder) -> None:
    """Record a paint-ordered x domain into the innermost open sink, if any."""
    sinks = _sinks.get()
    if sinks:
        sinks[-1][chart_id] = paint_order
