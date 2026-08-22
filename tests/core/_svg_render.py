"""Shared helper for tests that need a rendered-SVG output of a minimal board."""

import re
from pathlib import Path
from typing import Any

from dbt_charts.agent_api.project_session import ProjectSession
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.board import raise_on_dashboard_failure
from dbt_charts.core.compile import compile
from dbt_charts.core.execute import Executor
from dbt_charts.core.execute.adapters import build_adapter_registry
from dbt_charts.core.project import Project
from dbt_charts.core.render import render
from dbt_charts.core.render_format import RenderFormat

SAMPLE_BOARD_YAML = """
title: Test Dashboard
queries:
  q1:
    type: values
    rows:
      - {month: Jan, revenue: 100}
      - {month: Feb, revenue: 150}
charts:
  c1:
    query: q1
    type: bar
    x: month
    y: revenue
rows:
  - c1
"""


def render_board_to_svg(yaml_content: str = SAMPLE_BOARD_YAML) -> str:
    result = compile(yaml_content)
    assert result.success
    executor = Executor(
        result.board,
        adapter_registry=build_adapter_registry(FilesystemProject(Path.cwd())),
        query_registry=result.query_registry,
    )
    return render(result.board, executor, format="svg").output


def cumulative_ink_x(svg: str, authored_path: str, until: str) -> float:
    """Absolute local x of the first ``until``-tagged element under the
    authored group at ``authored_path``, summing every ``translate(x, ...)``
    wrapper along the way (a padded box wraps its content in its own inset
    translate, on top of the group's own position) and skipping the
    selection-boundary rects, which carry no offset of their own.
    """
    open_tag = re.search(
        r'<g transform="translate\(([-\d.]+),\s*[-\d.]+\)"[^>]*'
        rf'data-authored-path="{re.escape(authored_path)}"[^>]*>',
        svg,
    )
    assert open_tag, f"no tagged group for authored path {authored_path!r}"
    total = float(open_tag.group(1))
    rest = svg[open_tag.end() :]
    while True:
        m = re.match(
            r'<g[^>]*transform="translate\(([-\d.]+),\s*[-\d.]+\)"[^>]*>\s*', rest
        )
        if m:
            total += float(m.group(1))
            rest = rest[m.end() :]
            continue
        m = re.match(r'<rect class="dbt-box-(?:outer|inner)"[^>]*/>\s*', rest)
        if m:
            rest = rest[m.end() :]
            continue
        break
    assert rest.startswith(f"<{until}"), f"expected <{until}, found: {rest[:80]!r}"
    return total


def legend_label_order(svg: str) -> list[str]:
    """Rendered color-legend label text, in SVG document (top-to-bottom) order.

    Mirrors ``chart_interactivity.js``'s ``legendSeriesOrder`` — the DOM order
    a real browser (or the JS tooltip runtime) sees. Vega's own SVG renderer
    marks each legend label group with the ``role-legend-label`` class
    (unrelated to the JS runtime's aria-label role markers).
    """
    labels = []
    for m in re.finditer(r'class="[^"]*\brole-legend-label\b[^"]*"', svg):
        text_match = re.search(
            r"<text[^>]*>([^<]*)</text>", svg[m.end() : m.end() + 300]
        )
        if text_match:
            labels.append(text_match.group(1))
    return labels


def render_board_file(
    path: Path,
    *,
    format: RenderFormat = "svg",
    project: Project | None = None,
    **render_options: Any,
) -> str | bytes:
    """Render an on-disk board file through the standard ProjectSession path.

    Mirrors the composition-root pattern used by Cloud and Playground (open a
    session, render, raise on failure, close) so tests exercising a saved board
    file don't hand-roll that plumbing. ``project`` defaults to the project
    discovered upward from ``path`` (matching a board with no explicit project).
    """
    session = (
        ProjectSession.from_project(project)
        if project is not None
        else ProjectSession.from_board(path)
    )
    try:
        board = session.project.path_for_fspath(path).read_board()
        rendered = session.render_board(board=board, format=format, **render_options)
        raise_on_dashboard_failure(rendered)
        # This helper renders to embeddable output (svg/html/png/pdf/text/yaml);
        # the json arm's dict payload is out of contract — fail loudly, not silently.
        assert isinstance(rendered.data, (str, bytes))
        return rendered.data
    finally:
        session.close()


def authored_boxes(
    svg: str, box_class: str
) -> dict[str, tuple[float, float, float, float]]:
    """Every authored block's selection box of ``box_class``, in absolute page
    coordinates (``dbt-box-outer`` or ``dbt-box-inner``).

    Resolves the nested ``translate(...)`` chain so boxes from different depths
    are comparable — which is what "do two blocks' marks overlap" needs and what
    a per-group local offset cannot answer. The inner box carries its own
    ``x``/``y`` inset on top of that chain; the outer one is always at 0,0.

    Returns ``authored_path -> (x, y, width, height)``.
    """
    tag = re.compile(r"<(/?)g\b([^>]*)>")
    translate = re.compile(r"translate\(\s*(-?[\d.]+)[,\s]+(-?[\d.]+)\s*\)")
    box = re.compile(
        rf'<rect class="{box_class}" x="(-?[\d.]+)" y="(-?[\d.]+)"'
        r'[^>]*?width="([\d.]+)" height="([\d.]+)"'
    )

    stack: list[tuple[float, float, str | None]] = [(0.0, 0.0, None)]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    pos = 0
    for m in tag.finditer(svg):
        found = box.search(svg[pos : m.start()])
        pos = m.end()
        if found:
            x, y, path = stack[-1]
            if path is not None:
                boxes[path] = (
                    x + float(found.group(1)),
                    y + float(found.group(2)),
                    float(found.group(3)),
                    float(found.group(4)),
                )
        closing, attrs = m.groups()
        if closing:
            if len(stack) > 1:
                stack.pop()
            continue
        if attrs.rstrip().endswith("/"):
            continue
        x, y, path = stack[-1]
        moved = translate.search(attrs)
        if moved:
            x += float(moved.group(1))
            y += float(moved.group(2))
        named = re.search(r'data-authored-path="([^"]*)"', attrs)
        stack.append((x, y, named.group(1) if named else path))
    return boxes


def leaf_kind_subtrees(svg: str, kind: str) -> list[str]:
    """Every ``data-authored-kind="<kind>"`` group, each as its whole subtree.

    Walks ``<g>``/``</g>`` depth to the *matching* close tag. A non-greedy
    ``(.*?)</g>`` regex stops at the first close instead, which on a group whose
    first child is itself a ``<g>`` returns that child and nothing else — a
    containment assertion written that way passes without ever seeing the
    content it was meant to reject.
    """
    out = []
    for opening in re.finditer(
        rf'<g[^>]*data-authored-kind="{re.escape(kind)}"[^>]*>', svg
    ):
        depth = 0
        for tag in re.finditer(r"<g\b[^>]*>|</g>", svg[opening.start() :]):
            depth += 1 if tag.group(0).startswith("<g") else -1
            if depth == 0:
                out.append(svg[opening.start() : opening.start() + tag.end()])
                break
    return out
