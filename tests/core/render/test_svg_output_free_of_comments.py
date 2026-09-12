"""The host-shipped runtime and a board's embedded `<style>` carry no comments.

Goldens are normalized to strip `<script>` tags entirely (see
`normalize_svg` in the visual-test harness), so the committed-goldens
comment guard (`dbt-charts/tests/visual/test_goldens_free_of_comments.py`)
never exercises the JS half of the payload -- and a board no longer embeds
a script at all: the hover and controls runtimes ship with the host. This
test checks that runtime source directly, and a real board's `<style>`.
"""

from __future__ import annotations

import re

from dbt_charts.core.render.controls import controls_runtime_source

from .._svg_render import render_board_to_svg


def test_host_runtime_has_no_fenced_comments() -> None:
    script = controls_runtime_source()

    assert "{#" not in script and "#}" not in script

    # The strip is fence-only: plain `//` comments and any `//` inside a string
    # (URLs, namespace literals) survive untouched.
    assert "//" in script


def test_rendered_svg_styles_have_no_css_comments() -> None:
    svg = render_board_to_svg()

    style_match = re.search(r"<style[^>]*>(.*?)</style>", svg, re.DOTALL)
    assert style_match, "expected an embedded <style> element"

    css = style_match.group(1)
    assert "/*" not in css
    assert "{#" not in css and "#}" not in css
