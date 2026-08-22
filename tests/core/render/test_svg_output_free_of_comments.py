"""A rendered board's embedded `<script>`/`<style>` must carry no comments.

Goldens are normalized to strip `<script>` tags entirely (see
`normalize_svg` in the visual-test harness), so the committed-goldens
comment guard (`dbt-charts/tests/visual/test_goldens_free_of_comments.py`)
never exercises the JS half of the payload. This test renders a real
board -- which always embeds the variables and chart-interactivity
scripts -- and checks the actual `<script>` payload directly.
"""

from __future__ import annotations

import re

from .._svg_render import render_board_to_svg


def test_rendered_svg_script_has_no_comments() -> None:
    svg = render_board_to_svg()

    assert "<script" in svg, "expected the render to embed a <script> tag"

    scripts = re.findall(r"<!\[CDATA\[(.*?)\]\]>", svg, re.DOTALL)
    assert scripts, "expected at least one CDATA-wrapped script body"

    for script in scripts:
        assert "{#" not in script and "#}" not in script, (
            f"fenced comment survived in embedded script: {script[:200]}"
        )

    # The strip is fence-only: plain `//` comments and any `//` inside a string
    # (URLs, namespace literals) survive untouched.
    assert any("//" in script for script in scripts)


def test_rendered_svg_styles_have_no_css_comments() -> None:
    svg = render_board_to_svg()

    style_match = re.search(r"<style[^>]*>(.*?)</style>", svg, re.DOTALL)
    assert style_match, "expected an embedded <style> element"

    css = style_match.group(1)
    assert "/*" not in css
    assert "{#" not in css and "#}" not in css
