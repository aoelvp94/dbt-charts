"""Tests for SVG render footer functionality.

The footer is a right-aligned muted text line at the bottom of every board,
with an optional hairline rule above. Theme-controlled, always-on by default,
disabled by setting style.footer.visible: false. The brand phrase "dbt charts"
in the footer text is drawn as the dbt charts wordmark in the footer color, and
links to style.footer.link (a subtle watermark) when set.
"""

import re

from dbt_charts.core.compile.config import (
    get_chart_rendering,
    get_default_theme_name,
    get_theme_style,
)
from dbt_charts.core.font_measure import get_font_measurer

from ._svg_render import render_board_to_svg


class TestSVGFooter:
    def test_footer_text_is_visible_by_default(self):
        svg = render_board_to_svg()
        assert "made with" in svg
        assert 'class="dbt-footer-wordmark"' in svg

    def test_footer_text_is_right_anchored_and_uses_configured_styling(self):
        footer = get_theme_style(get_default_theme_name()).footer
        assert footer.font is not None
        assert footer.font.size is not None
        expected_size = int(footer.font.size)
        expected_color = footer.font.color

        svg_output = render_board_to_svg()

        # The footer <text> open tag carries the right anchor, size, and color;
        # "made with" is its own run, ending where the mark's gap begins.
        pattern = (
            rf'<text[^>]*text-anchor="end"[^>]*font-size="{expected_size}"'
            rf'[^>]*fill="{re.escape(expected_color)}"[^>]*>made with</text>'
        )
        assert re.search(pattern, svg_output) is not None

    def test_footer_hairline_rule_renders_above_text_by_default(self):
        svg_output = render_board_to_svg()
        footer_idx = svg_output.find("made with")
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
        svg = render_board_to_svg(yaml)
        assert "made with" not in svg
        assert 'class="dbt-footer-wordmark"' not in svg

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
        assert "made with" not in svg

    def test_footer_hairline_rule_color_matches_theme(self):
        footer = get_theme_style(get_default_theme_name()).footer
        assert footer.rule is not None
        svg_output = render_board_to_svg()
        footer_idx = svg_output.find("made with")
        prefix = svg_output[:footer_idx]
        rule_pattern = rf'<line[^>]*stroke="{re.escape(footer.rule.color)}"[^>]*/>'
        assert re.search(rule_pattern, prefix) is not None

    # --- wordmark and link ---------------------------------------------------

    def test_footer_brand_phrase_is_drawn_as_the_wordmark_not_set_in_type(self):
        svg = render_board_to_svg()
        assert re.search(r"<text[^>]*>[^<]*dbt charts", svg, re.IGNORECASE) is None
        assert re.search(
            r'<g class="dbt-footer-wordmark"[^>]*>(<path d="[^"]+"/>){3}</g>', svg
        )

    def test_footer_wordmark_is_painted_in_the_footer_font_color(self):
        footer = get_theme_style(get_default_theme_name()).footer
        svg = render_board_to_svg()
        lockup = re.search(r'<g class="dbt-footer-wordmark"[^>]*>', svg)
        assert lockup is not None
        assert f'fill="{footer.font.color}"' in lockup.group(0)
        assert "fill=" not in re.sub(
            r'<g class="dbt-footer-wordmark"[^>]*>', "", lockup.group(0)
        )

    def test_footer_wordmark_follows_an_overridden_footer_color(self):
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    font:
      color: "#123456"
"""
        svg = render_board_to_svg(yaml)
        lockup = re.search(r'<g class="dbt-footer-wordmark"[^>]*>', svg)
        assert lockup is not None
        assert 'fill="#123456"' in lockup.group(0)

    def test_footer_wordmark_links_to_configured_url_by_default(self):
        footer = get_theme_style(get_default_theme_name()).footer
        assert footer.link
        svg = render_board_to_svg()
        pattern = (
            rf'<a class="dbt-footer-link" href="{re.escape(footer.link)}"[^>]*>'
            r'<g class="dbt-footer-wordmark"'
        )
        assert re.search(pattern, svg) is not None
        # Subtle styling lives in the embedded stylesheet: pointer, dim on hover.
        assert ".dbt-footer-link" in svg
        assert ".dbt-footer-link:hover" in svg

    def test_footer_link_null_keeps_the_wordmark_but_no_link(self):
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    link: null
"""
        svg = render_board_to_svg(yaml)
        assert 'class="dbt-footer-wordmark"' in svg
        assert "<a " not in svg
        assert 'class="dbt-footer-link"' not in svg

    def test_footer_wordmark_absent_when_brand_word_not_in_text(self):
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
        assert 'class="dbt-footer-wordmark"' not in svg
        assert 'class="dbt-footer-link"' not in svg

    def test_footer_prefix_ends_before_the_wordmark_starts(self):
        """ "made with" is its own right-anchored run ending left of the lockup."""
        svg = render_board_to_svg()
        prefix = re.search(r'<text x="([\d.]+)"[^>]*>made with</text>', svg)
        lockup = re.search(
            r'<g class="dbt-footer-wordmark" transform="translate\(([\d.]+), [\d.]+\)',
            svg,
        )
        assert prefix is not None and lockup is not None
        assert float(prefix.group(1)) < float(lockup.group(1))

    def test_footer_text_after_the_brand_phrase_stays_right_of_the_wordmark(self):
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  footer:
    text: "made with dbt Charts for Acme"
"""
        svg = render_board_to_svg(yaml)
        suffix = re.search(r'<text x="([\d.]+)"[^>]*>for Acme</text>', svg)
        lockup = re.search(
            r'<g class="dbt-footer-wordmark" transform="translate\(([\d.]+), [\d.]+\) '
            r"scale\(([\d.]+)\)",
            svg,
        )
        assert suffix is not None and lockup is not None
        lockup_right = float(lockup.group(1)) + 997 * float(lockup.group(2))
        style = get_theme_style(get_default_theme_name())
        assert style.footer.font.size is not None
        suffix_w = get_font_measurer(style.font.family).measure(
            "for Acme", float(style.footer.font.size)
        )
        assert lockup_right < float(suffix.group(1)) - suffix_w

    def test_footer_right_timestamp_clears_the_lockup(self):
        """The timestamp ends the configured gap before the leftmost painted
        edge of the attribution, which is the start of "made with"."""
        style = get_theme_style(get_default_theme_name())
        assert style.footer.font.size is not None
        measure = get_font_measurer(style.font.family).measure
        size = float(style.footer.font.size)
        yaml = """\
title: Test
queries:
  q: {type: values, rows: [{n: 1}]}
charts:
  t: {query: q, type: table}
rows: [t]
style:
  timestamp:
    align: right
"""
        svg = render_board_to_svg(yaml)
        stamp = re.search(r'<text data-role="render-timestamp" x="([\d.]+)"', svg)
        prefix = re.search(r'<text x="([\d.]+)"[^>]*>made with</text>', svg)
        assert stamp is not None and prefix is not None
        lockup_left = float(prefix.group(1)) - measure("made with", size)
        gap = get_chart_rendering().frame.footer_timestamp_gap_px
        assert abs(lockup_left - float(stamp.group(1)) - gap) < 0.01
