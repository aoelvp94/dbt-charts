"""Standing guard: two boards on different themes must not collide when their
SVGs land in one HTML document (the docs themes page, or any Cloud surface
stacking more than one board — review diffs, merge conflicts, chat embeds).

Inline SVG in an HTML page has no id scope: every ``id="..."`` a board's SVG
emits is document-global, so a duplicated, *referenced* id (``url(#...)``)
resolves to whichever def the DOM kept — silently repainting the second
board with the first board's fragment. This is the id-namespace sibling of
``test_svg_composition_no_scope_collision.py``'s CSS-selector guard.

An in-process render cannot reproduce the bug: vl-convert's own id counter
(``clip0``, ``clip1``, ...) is scoped to a single ``vegalite_to_svg`` call
and keeps advancing across renders made in one process, so two in-process
renders never mint the same low-numbered id. Two *separate processes* both
start that counter at zero — which is exactly what happens when a page like
the docs themes page composes boards rendered by independent build steps.
This test renders each board in its own subprocess to reproduce that.

Scope: every element id except the chart-wrapper form ``chart-<chart_id>``.
That id is a known duplicate across boards sharing a chart key (unlike
vl-convert's per-render ids, it is not scoped by anything) and is tolerated
here rather than fixed: nothing in the codebase selects it (no ``url(#...)``,
no ``href``, no CSS rule, no JS lookup) -- the sibling ``data-chart-id``
attribute is the documented hook for JS/CSS to key off a chart -- so it is
invalid-but-inert, unlike the vl-convert ids this test exists to guard. It is
excluded from the conflict set below, not from the guard's positive controls.
"""

from __future__ import annotations

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

_BOARD_YAML_TEMPLATE = """\
theme: {theme}
title: Board Title
queries:
  q1:
    type: values
    rows:
      - {{month: "Jan", revenue: 10}}
      - {{month: "Feb", revenue: 30}}
      - {{month: "Mar", revenue: 20}}
charts:
  trend:
    type: line
    query: q1
    x: month
    y: revenue
rows:
  - trend
"""

_RENDER_SCRIPT = """\
import sys
from pathlib import Path

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile import compile as compile_board
from dbt_charts.core.execute import Executor
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.render import render

board_yaml = sys.argv[1]
result = compile_board(board_yaml)
assert result.success, result.errors
assert result.board is not None
executor = Executor(
    result.board,
    adapter_registry=build_adapter_registry(FilesystemProject(Path.cwd())),
    query_registry=result.query_registry,
)
out = render(result.board, executor, format="svg").output
assert isinstance(out, str)
sys.stdout.write(out)
"""

# Element ids only -- anchored on the attribute boundary (preceded by `<` or
# whitespace) so `data-chart-id="trend"` doesn't spuriously match as an id
# `trend`: the `id=` inside it is preceded by `-`, never `<`/whitespace.
_ELEMENT_ID_RE = re.compile(r'(?<=[\s<])id="([^"]+)"')
_URL_REF_RE = re.compile(r"url\(#([^)\"']+)\)")
_HREF_REF_RE = re.compile(r'(?:xlink:href|href)="#([^"]+)"')
_VLC_ID_RE = re.compile(r"^(?:clip|gradient_)\d")
_CHART_WRAPPER_ID_RE = re.compile(r"^chart-")


def _render_svg_in_subprocess(theme: str) -> str:
    board_yaml = _BOARD_YAML_TEMPLATE.format(theme=theme)
    result = subprocess.run(
        [sys.executable, "-c", _RENDER_SCRIPT, board_yaml],
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _element_ids(svg: str) -> set[str]:
    return set(_ELEMENT_ID_RE.findall(svg))


def _referenced_ids(svg: str) -> set[str]:
    return set(_URL_REF_RE.findall(svg)) | set(_HREF_REF_RE.findall(svg))


def test_two_themed_boards_share_no_conflicting_element_id() -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        clarity_future = pool.submit(_render_svg_in_subprocess, "clarity")
        neon_future = pool.submit(_render_svg_in_subprocess, "neon")
        clarity_svg = clarity_future.result()
        neon_svg = neon_future.result()

    clarity_ids = _element_ids(clarity_svg)
    neon_ids = _element_ids(neon_svg)

    # Positive control: `assert not (a & b)` is also true of two empty sets, so
    # a change to id emission that stopped minting ids entirely would turn
    # this guard green instead of red. Both documents must have actually
    # minted vl-convert ids (clipPath/linearGradient defs a line chart's axis
    # clipping and gradient fills produce).
    clarity_vlc_ids = {i for i in clarity_ids if _VLC_ID_RE.match(i)}
    neon_vlc_ids = {i for i in neon_ids if _VLC_ID_RE.match(i)}
    assert clarity_vlc_ids, f"expected vl-convert ids in clarity render: {clarity_ids}"
    assert neon_vlc_ids, f"expected vl-convert ids in neon render: {neon_ids}"

    # Second positive control: every reference resolves within its own
    # document. This doesn't exercise the collision itself (a document's own
    # references always match its own defs) -- it guards the extraction
    # regexes themselves against silently matching nothing.
    for name, svg, ids in (
        ("clarity", clarity_svg, clarity_ids),
        ("neon", neon_svg, neon_ids),
    ):
        referenced = _referenced_ids(svg)
        assert referenced, f"expected at least one url(#...)/href reference in {name}"
        unresolved = referenced - ids
        assert not unresolved, f"{name} references ids it never defines: {unresolved}"

    conflicting = clarity_ids & neon_ids

    # Known-duplicate carve-out: the chart-wrapper id (`chart-<chart_id>`) is
    # unreferenced anywhere in the codebase, so a same-chart-key collision
    # between boards is invalid-but-inert rather than a repaint bug -- a
    # known duplicate awaiting its own change. Positive control: assert the
    # excluded set is exactly the wrapper id this board mints (both boards
    # define a chart keyed `trend`), so an over-matching regex here would
    # fail loudly instead of silently swallowing a real collision.
    chart_wrapper_conflicts = {i for i in conflicting if _CHART_WRAPPER_ID_RE.match(i)}
    assert chart_wrapper_conflicts == {"chart-trend"}, (
        f"expected only the known chart-wrapper duplicate, got: {chart_wrapper_conflicts}"
    )
    conflicting -= chart_wrapper_conflicts

    assert not conflicting, f"element ids defined by both documents: {conflicting}"
