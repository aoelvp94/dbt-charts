"""Shared fixture: reproduction A (rows-only, sparse tail, 11 rows).

2 families x 2 event types x 4 months, with the last month's tail sparse
(family2 and event2 missing). Used by both the emitted-spec tier
(test_small_multiples_data_grain.py) and the resolve tier
(test_stacked_domain_multiples_fold.py); a single source avoids the two
suites silently drifting on the exact row shape.
"""

from __future__ import annotations

from typing import Any

from dbt_charts.core.compile.models.chart.normalized import BarChart


def repro_a_rows() -> list[dict[str, Any]]:
    """Rows-only, sparse tail (11 rows) — see module docstring."""
    rows: list[dict[str, Any]] = []
    for month in ("2026-06-01", "2026-07-01"):
        for family in ("family1", "family2"):
            for event in ("event1", "event2"):
                rows.append(
                    {
                        "month": month,
                        "plan_family": family,
                        "event_type": event,
                        "cnt": 5,
                    }
                )
    for event in ("event1", "event2"):
        rows.append(
            {
                "month": "2026-08-01",
                "plan_family": "family1",
                "event_type": event,
                "cnt": 5,
            }
        )
    rows.append(
        {
            "month": "2026-09-01",
            "plan_family": "family1",
            "event_type": "event1",
            "cnt": 5,
        }
    )
    return rows


def repro_a_chart(**extra: Any) -> BarChart:
    return BarChart.model_validate(
        {
            "id": "c",
            "type": "bar",
            "query_name": "q",
            "x": "month",
            "y": "cnt",
            "color": "plan_family",
            "stack": "zero",
            "multiples": {"rows": "event_type"},
            **extra,
        }
    )
