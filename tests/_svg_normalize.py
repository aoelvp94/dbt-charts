"""Test-only helper: make two renders of the same board comparable.

A raw render is not reproducible even for an unchanged board. Three things vary
between two renders in one process, none of them visual:

- ``data-rendered-at``, a wall-clock stamp at *second* resolution — so two
  renders agree until a second boundary falls between them, which is what makes
  a raw comparison pass locally and fail on CI;
- the ``data-role="render-timestamp"`` text the theme draws from the same clock;
- Vega-Lite's ``gradient_N`` / ``clip_N`` counters and the renderer's own
  ``clipN``, all of which increment per render for the process's lifetime.

Any test asserting that two renders are equal — or that they differ — has to
strip all four or it is asserting the clock. Kept here rather than in one test
module because the second caller is what found the first one's gaps.

A narrower sibling of ``tests/visual/discovery.py``'s ``normalize_svg``, which
also strips cross-tree-only noise (hitbox rects, editor/authored renames) that
two same-run renders never disagree on.
"""

from __future__ import annotations

import re


def normalize_same_run_svg(svg: str) -> str:
    """``svg`` with every same-run-varying token removed or renumbered."""
    # Not same-run-varying — it is md5 of the board's dimensions — but stripped
    # with the rest so a caller comparing across sizes is not tripped by a hash
    # that restates the width and height printed beside it.
    svg = re.sub(r'\s*id="dbt-charts-svg-[^"]*"', "", svg)
    svg = re.sub(r'\s*data-rendered-at="[^"]*"', "", svg)
    svg = re.sub(
        r'<text\s+data-role="render-timestamp"[^>]*>.*?</text>',
        "",
        svg,
        flags=re.DOTALL,
    )
    for pattern in (r"gradient_(\d+)", r"clip_(\d+)", r"clip(\d+)"):
        prefix = pattern.split("(")[0]
        ids = list(dict.fromkeys(re.findall(pattern, svg)))
        id_map = {old: str(new) for new, old in enumerate(ids)}
        svg = re.sub(
            pattern, lambda m, _m=id_map, _p=prefix: f"{_p}{_m[m.group(1)]}", svg
        )
    return svg
