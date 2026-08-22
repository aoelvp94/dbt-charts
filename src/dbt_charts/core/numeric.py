"""Neutral numeric primitives shared by compile and render.

Leaf module — no dependency on compile/, execute/, or render/ (see the
module-dependency-direction section in ``core/AGENTS.md``). Both compile
(real axis tick baking) and render (upper-bound label-width estimation) import
from here.
"""

from __future__ import annotations

import math


def aspect_ratio_height(
    width: float, aspect_ratio: float, min_height: float, max_height: float
) -> float:
    """Height implied by an aspect ratio at a given width, clamped to [min_height, max_height].

    The one canonical form of the ``width / aspect_ratio`` clamp shared by
    ``render/sizing.py``'s ``get_chart_content_height`` (the render-time static
    height estimate) and ``compile/resolve/chart/bar.py``'s plot-height estimate (the
    resolve-time stacked-bar legend-yield classifier). Callers supply their own
    min/max — the two sit at different points in the style cascade (global vs
    per-family) — this only owns the shared arithmetic.
    """
    return max(min_height, min(max_height, width / aspect_ratio))


def nice_tick_values(
    domain_min: float,
    domain_max: float,
    target_count: int,
) -> list[float]:
    """Return <= target_count tick values at a "nice" step: 1, 2, or 5 x 10^k.

    This mirrors the spirit of d3-scale's tick algorithm, but enforces an upper
    bound on the number of ticks.

    The important detail is that tick count must be checked against the actual
    rounded extent:

        floor(domain_min / step) * step
        ceil(domain_max / step) * step

    rather than just the raw span. Rounding the extent outward can add extra
    ticks.

    Examples:
        nice_tick_values(0, 4000, 6) -> [0, 1000, 2000, 3000, 4000]
        nice_tick_values(0, 1400, 5) -> [0, 500, 1000, 1500]
        nice_tick_values(0, 60, 6)   -> [0, 20, 40, 60]

        nice_tick_values(99.8, 124.6, 6)
            -> [90, 100, 110, 120, 130]

        The step 5 would produce:
            [95, 100, 105, 110, 115, 120, 125]
        which has 7 ticks, so step 10 is chosen instead.
    """
    if target_count <= 1 or domain_min == domain_max:
        return [round(domain_min, 10)]

    reverse = domain_max < domain_min
    if reverse:
        domain_min, domain_max = domain_max, domain_min

    span = domain_max - domain_min
    raw_step = span / (target_count - 1)

    exp = math.floor(math.log10(raw_step)) if raw_step > 0 else 0
    magnitude = 10.0**exp

    # Include the next magnitude so there is always a fallback candidate.
    nice_steps = [
        magnitude,
        2 * magnitude,
        5 * magnitude,
        10 * magnitude,
    ]

    def rounded_extent_for_step(step: float) -> tuple[float, float]:
        start = math.floor(domain_min / step) * step
        end = math.ceil(domain_max / step) * step
        return start, end

    def tick_count_for_step(step: float) -> int:
        start, end = rounded_extent_for_step(step)
        return round((end - start) / step) + 1

    step = next(
        (
            candidate
            for candidate in nice_steps
            if tick_count_for_step(candidate) <= target_count
        ),
        nice_steps[-1],
    )

    start, end = rounded_extent_for_step(step)
    intervals = round((end - start) / step)

    ticks = [round(start + i * step, 10) for i in range(intervals + 1)]

    if reverse:
        ticks.reverse()

    return ticks
