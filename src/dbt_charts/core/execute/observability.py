"""Warehouse query observer type and notification helper.

dataface core has no prometheus_client import. The observer pattern keeps
dataface metric-tool-neutral; Cloud's middleware is one consumer, CLI /
playground can register their own (or none).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

WarehouseObserver = Callable[[str, str, float], None]
"""Called as observer(warehouse_type, status, duration_seconds) after each query.

Status is one of "success" or "error". A None warehouse_type from the adapter is
normalized to "unknown" before the observer fires."""


def notify_observers(
    observers: list[WarehouseObserver],
    warehouse_type: str | None,
    status: str,
    duration_seconds: float,
) -> None:
    """Notify all observers after a warehouse query.

    Normalizes None warehouse_type to "unknown". An observer that raises is
    logged and skipped (one observer must not break others).
    """
    normalized_type = warehouse_type if warehouse_type is not None else "unknown"
    for observer in observers:
        try:
            observer(normalized_type, status, duration_seconds)
        except Exception:  # noqa: BLE001 — one observer must not break others
            logger.exception("warehouse observer raised; skipping")
