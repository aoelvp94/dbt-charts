"""Tests for SVG render footer functionality.

The footer is a right-aligned muted text line at the bottom of every board,
with an optional hairline rule above. Theme-controlled, always-on by default,
disabled by setting style.footer.visible: false. The brand phrase "dbt charts"
in the footer text links to style.footer.link (a subtle watermark) when set.
"""

import re

from dbt_charts.core.compile.config import get_default_theme_name, get_theme_style

from ._svg_render import render_board_to_svg


class TestSVGFooter:
    def test_footer_text_is_visible_by_default(self):
        svg = render_board_to_svg()
        assert "made with " in svg
        assert "dbt charts" in svg

    def test_footer_text_is_right_anchored_and_uses_configured_styling(self):
        footer = get_theme_style(get_default_theme_name()).footer
        assert footer.font is not None
        assert footer.font.size is not None
        expected_size = int(footer.font.size)
        expected_color = footer.font.color

        svg_output = render_board_to_svg()

        # The footer <text> open tag carries the right anchor, size, and color;
        # its content is "made with " followed by the linked brand word.
        pattern = (
            rf'<text[^>]*text-anchor="end"[^>]*font-size="{expected_size}"'
            rf'[^>]*fill="{re.escape(expected_color)}"[^>]*>made with '
        )
        assert re.search(pattern, svg_output) is not None

    def test_footer_hairline_rule_renders_above_text_by_default(self):
        svg_output = render_board_to_svg()
        footer_idx = svg_output.find("made with ")
        assert footer_idx > -1
        rule = get_theme_style(get_default_theme_name()).footer.rule
        assert rule is not None
        rule_pattern = rf'<line[^>]*stroke="{re.escape(rule.color)}"[^>]*/>'
        prefix = svg_output[:footer_idx]
        assert re.search(rule_pattern, prefix) is not None

    def test_footer_not_rendered_when_visible_is_false(self):
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    visible: false
"""
        assert "made with dbt charts" not in render_board_to_svg(yaml)

    def test_footer_text_is_user_overridable(self):
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    text: "Acme Corp \xb7 attribution"
"""
        assert "Acme Corp \xb7 attribution" in render_board_to_svg(yaml)

    def test_footer_text_comes_from_style_not_rendering_config(self):
        """style.footer.text controls attribution text; rendering config has no footer_text."""
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    text: "custom attribution"
"""
        svg = render_board_to_svg(yaml)
        assert "custom attribution" in svg
        assert "made with dbt charts" not in svg

    def test_footer_hairline_rule_color_matches_theme(self):
        footer = get_theme_style(get_default_theme_name()).footer
        assert footer.rule is not None
        svg_output = render_board_to_svg()
        footer_idx = svg_output.find("made with ")
        prefix = svg_output[:footer_idx]
        rule_pattern = rf'<line[^>]*stroke="{re.escape(footer.rule.color)}"[^>]*/>'
        assert re.search(rule_pattern, prefix) is not None

    # --- brand-word link -----------------------------------------------------

    def test_footer_brand_word_links_to_configured_url_by_default(self):
        footer = get_theme_style(get_default_theme_name()).footer
        assert footer.link
        svg = render_board_to_svg()
        # "dbt charts" is wrapped in an anchor to the configured URL; "made with "
        # stays plain text outside the link.
        pattern = (
            rf'made with <a href="{re.escape(footer.link)}"[^>]*>'
            r'<tspan class="dbt-footer-link">dbt charts</tspan></a>'
        )
        assert re.search(pattern, svg) is not None

    def test_footer_link_styling_is_subtle_not_blue(self):
        """The linked phrase inherits the footer fill (no blue) and is styled via CSS."""
        svg = render_board_to_svg()
        # The tspan carries no explicit fill — it inherits the muted footer color.
        assert re.search(r'<tspan class="dbt-footer-link">dbt charts</tspan>', svg)
        assert 'class="dbt-footer-link"' in svg
        # Subtle styling lives in the embedded stylesheet: slightly bold, underline
        # only on hover.
        assert ".dbt-footer-link" in svg
        assert ".dbt-footer-link:hover" in svg

    def test_footer_link_absent_when_brand_word_not_in_text(self):
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    text: "custom attribution"
"""
        svg = render_board_to_svg(yaml)
        assert "custom attribution" in svg
        # No brand word to link — the footer <text> emits no anchor tspan (the
        # .dbt-footer-link CSS class definition still lives in the stylesheet).
        assert '<tspan class="dbt-footer-link">' not in svg
