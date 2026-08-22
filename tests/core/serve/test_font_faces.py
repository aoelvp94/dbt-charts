"""Regression tests for the dct serve font cascade.

Server-emitted SVG `font-family` attributes reference 'Inter Variable',
'dbt Sans Tabular', 'Source Serif 4', and 'Noto Emoji' (all defined by the
default and editorial themes). Each font referenced in those cascades MUST
have a matching `@font-face` rule in the served CSS, AND the corresponding
webfont must resolve over `/static/fonts/`.

If either side is missing the browser silently falls back to system fonts —
the most visible casualty is the wobble in tabular tick label columns
(every dollar tick or count tick in a chart axis).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_BAR_BOARD_YAML = """\
queries:
  q:
    type: values
    rows:
      - {month: "2024-01", revenue: 100}
      - {month: "2024-02", revenue: 200}
charts:
  c:
    query: q
    type: bar
    x: month
    y: revenue
rows:
  - c
"""

# Webfont contract: each family in any chart cascade must be backed by an
# `@font-face` rule with the right shape — family name, weight axis range,
# and source `format()` token. Family-only checks would green-light a
# single-weight pin on a variable font (the default theme requests
# kpi.font.weight: 500 — a `font-weight: 400` declaration silently misses
# and the browser falls back to system fonts at non-400 weights).
_REQUIRED_WEBFONTS: tuple[dict[str, str | None], ...] = (
    {
        "family": "Inter Variable",
        "style": "normal",
        "weight": "100 900",
        "format": "woff2-variations",
    },
    {
        "family": "Inter Variable",
        "style": "italic",
        "weight": "100 900",
        "format": "woff2-variations",
    },
    {
        "family": "dbt Sans Tabular",
        "style": "normal",
        "weight": "100 900",
        "format": "woff2-variations",
    },
    {
        "family": "Source Serif 4",
        "style": "normal",
        "weight": "200 900",
        "format": "woff2-variations",
    },
    {
        "family": "Source Serif 4",
        "style": "italic",
        "weight": "200 900",
        "format": "woff2-variations",
    },
    # Noto Emoji ships only one weight; weight assertion skipped (None).
    {"family": "Noto Emoji", "style": None, "weight": None, "format": "woff2"},
)

_REQUIRED_WOFF2_PATHS = (
    "/static/fonts/InterVariable.woff2",
    "/static/fonts/InterVariable-Italic.woff2",
    "/static/fonts/DBTSansTabular-Regular.woff2",
    "/static/fonts/SourceSerif4Variable.woff2",
    "/static/fonts/SourceSerif4-Italic.woff2",
    "/static/fonts/NotoEmoji-Regular.woff2",
)


@pytest.fixture
def board_file(tmp_path: Path) -> Path:
    boards = tmp_path / "charts"
    boards.mkdir()
    f = boards / "bar_board.yml"
    f.write_text(_BAR_BOARD_YAML)
    return f


def _font_face_blocks(body: str) -> dict[tuple[str, str | None], str]:
    """Map (font-family, font-style) → the raw body of its @font-face block."""
    import re

    out: dict[tuple[str, str | None], str] = {}
    for block in re.findall(r"@font-face\s*\{([^}]*)\}", body):
        family = re.search(r"font-family:\s*['\"]([^'\"]+)['\"]", block)
        style = re.search(r"font-style:\s*([^;]+)", block)
        if family:
            out[(family.group(1), style.group(1).strip() if style else None)] = block
    return out


@pytest.mark.parametrize(
    "spec",
    _REQUIRED_WEBFONTS,
    ids=[f"{s['family']} {s['style'] or 'unspecified'}" for s in _REQUIRED_WEBFONTS],
)
def test_served_html_declares_font_face_with_expected_shape(
    board_file: Path, spec: dict[str, str | None]
) -> None:
    """Each cascade family has @font-face with right family, weight, and format."""
    from fastapi.testclient import TestClient

    from dbt_charts.cli.filesystem_project import FilesystemProject
    from dbt_charts.core.serve.server import create_server

    app = create_server(FilesystemProject(board_file.parent.parent))
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"/{board_file.stem}")
    assert resp.status_code == 200
    blocks = _font_face_blocks(resp.text)
    family = spec["family"]
    style = spec["style"]
    assert family is not None
    key = (family, style)
    assert key in blocks, (
        f"@font-face missing for {family!r} style {style!r}. "
        f"Declared blocks: {sorted(blocks)}. Without an @font-face the browser "
        "silently falls back to system fonts."
    )
    block = blocks[key]
    fmt = spec["format"]
    assert f"format('{fmt}')" in block, (
        f"@font-face for {family!r} must declare format('{fmt}'). "
        f"`woff2` ignores the variable axis; `woff2-variations` honours it. "
        f"Block: {block!r}"
    )
    weight = spec["weight"]
    if weight is not None:
        assert f"font-weight: {weight}" in block, (
            f"@font-face for {family!r} must declare font-weight: {weight}. "
            f"A single-weight pin on a variable font silently misses cascade "
            f"requests at other weights — the wobble-in-tick-columns regression. "
            f"Block: {block!r}"
        )


@pytest.mark.parametrize("path", _REQUIRED_WOFF2_PATHS)
def test_static_fonts_route_serves_webfonts(board_file: Path, path: str) -> None:
    """Each webfont URL the @font-face references resolves over HTTP."""
    from fastapi.testclient import TestClient

    from dbt_charts.cli.filesystem_project import FilesystemProject
    from dbt_charts.core.serve.server import create_server

    app = create_server(FilesystemProject(board_file.parent.parent))
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(path)
    assert resp.status_code == 200, (
        f"Expected 200 for {path!r}, got {resp.status_code}. "
        "The served HTML's @font-face URLs must resolve — a 404 silently "
        "breaks chart typography."
    )
    assert len(resp.content) > 1000, f"woff2 body for {path!r} looks too small"
