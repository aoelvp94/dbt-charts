"""The rendered board's root <svg> must expose its accessible name via a root
aria-label, never a <title> child.

Browsers render an SVG <title> element as a native hover tooltip covering the
whole canvas -- it fires the moment the mouse enters the chart, well before it
reaches a mark, and collides head-on with the custom JS hover tooltip. Same
class of bug as the earlier fix that moved the chart *description* out of
aria-label; here the fix runs the other direction -- the accessible name moves
OFF <title> and ONTO a root aria-label. No information is lost: the title text
is already visible as on-canvas <text>.
"""

from __future__ import annotations

import re

from ._svg_render import render_board_to_svg

_TITLED_BOARD = """\
title: "Root Title Test"
queries:
  q:
    type: values
    rows:
      - {x: 1, y: 10}
      - {x: 2, y: 20}
charts:
  c:
    query: q
    type: bar
    x: x
    y: y
rows:
  - c
"""


def test_svg_root_has_no_title_element_uses_aria_label() -> None:
    svg = render_board_to_svg(_TITLED_BOARD)

    root_open = re.match(r"<svg\b[^>]*>", svg)
    assert root_open is not None

    # No <title> as the root's own first child -- that's the native-tooltip trigger.
    assert not svg[root_open.end() :].lstrip().startswith("<title>"), svg[
        root_open.end() : root_open.end() + 200
    ]

    # Accessible name preserved via a root aria-label instead.
    assert 'aria-label="Root Title Test"' in root_open.group(0)
