"""Tests for font wiring between resolved dbt-charts style and mdsvg.

Validates that:
- get_compact_style includes font_family, base_font_size, line_height from resolved style
- mdsvg public API accepts font_path/mono_font_path forwarding to SVGRenderer
- Layout dimensions are stable with vendored Inter (regression guard)
"""

import pytest

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
)
from dbt_charts.core.fonts import (
    DBT_SANS_TABULAR_FONT_FAMILY,
    DBT_SERIF_OLDSTYLE_PROPORTIONAL_FONT_FAMILY,
    DBT_SERIF_OLDSTYLE_TABULAR_FONT_FAMILY,
    INTER_VARIABLE_FONT_FAMILY,
    NOTO_EMOJI_FONT_FAMILY,
    SOURCE_SERIF_4_FONT_FAMILY,
    get_face,
    get_fonts_dir,
)


class TestCompactStyleIncludesConfig:
    """get_compact_style should pull font_family and typography from resolved style."""

    def test_font_family_from_resolved_text_stack(self):
        from dbt_charts.core.compile.resolve.style.board import resolve_style
        from dbt_charts.core.render.sizing import get_compact_style

        rs = resolve_style(get_theme_style())
        style = get_compact_style(rs)
        assert style.font_family == rs.text.font.family

    def test_base_font_size_from_config(self):
        from dbt_charts.core.render.sizing import get_compact_style

        style = get_compact_style(resolve_style(get_theme_style()))
        assert style.base_font_size == get_theme_style().text.font.size

    def test_line_height_on_font_slot_propagates_to_mdsvg(self):
        """line_height lives on font slot; mdsvg gets it from text.font.line_height."""
        from dbt_charts.core.render.sizing import get_compact_style

        rs = resolve_style(get_theme_style())
        style = get_compact_style(rs)
        # After Stage 1: line_height is on the font slot, not a sibling of font.
        assert style.line_height == rs.text.font.line_height

    def test_title_line_height_from_title_font_slot(self):
        """heading_line_height comes from title.font.line_height after Stage 1."""
        from dbt_charts.core.render.sizing import compact_style_kwargs

        rs = resolve_style(get_theme_style())
        kwargs = compact_style_kwargs(rs)
        assert kwargs["heading_line_height"] == rs.title.font.line_height

    def test_font_line_height_cascade_distinctive_value(self):
        """Root line_height reaches inheriting slots; a declared slot keeps its own.

        ``style.variables.font`` inherits leading from the root font slot, so a
        distinctive root value must reach it. ``style.text.font`` and
        ``style.title.font`` declare their own leading (prose and headline
        respectively), so the nearer declared value wins over the root patch --
        that is the cascade working, not bypassing it.
        """
        from dbt_charts.core.compile.models.style.authored import StylePatch

        base = get_theme_style()
        patch = StylePatch.model_validate({"font": {"line_height": 2.37}})
        rs = resolve_style(base, patch)

        assert rs.variables.font.line_height == 2.37
        assert rs.text.font.line_height != 2.37
        assert rs.title.font.line_height != 2.37

    def test_chrome_heading_margins_ignore_prose_typography(self):
        """Board-title spacing must not move when prose size or leading changes.

        The chrome scale exists so a card holding a chart -- with no prose in it
        at all -- does not grow when body text is resized. Golden diffs catch a
        regression here, but only as a whole-board pixel mismatch; this fails
        with a number instead.
        """
        from dbt_charts.core.compile.models.style.authored import StylePatch
        from dbt_charts.core.render.sizing import compact_style_kwargs

        base = resolve_style(get_theme_style())
        bumped = resolve_style(
            get_theme_style(),
            StylePatch.model_validate(
                {"text": {"font": {"size": 31.0, "line_height": 2.4}}}
            ),
        )

        chrome_before = compact_style_kwargs(base, heading_margin_scale="chrome")
        chrome_after = compact_style_kwargs(bumped, heading_margin_scale="chrome")
        assert (
            chrome_after["heading_margin_top_px"]
            == chrome_before["heading_margin_top_px"]
        )
        assert (
            chrome_after["heading_margin_bottom_px"]
            == chrome_before["heading_margin_bottom_px"]
        )

        # ...while the prose scale does track it, which is the whole point.
        prose_before = compact_style_kwargs(base, heading_margin_scale="prose")
        prose_after = compact_style_kwargs(bumped, heading_margin_scale="prose")
        assert (
            prose_after["heading_margin_top_px"] > prose_before["heading_margin_top_px"]
        )

    def test_text_line_height_is_authorable(self):
        """Prose leading is independently settable without moving chrome leading."""
        from dbt_charts.core.compile.models.style.authored import StylePatch

        patch = StylePatch.model_validate({"text": {"font": {"line_height": 1.93}}})
        rs = resolve_style(get_theme_style(), patch)

        assert rs.text.font.line_height == 1.93
        assert rs.variables.font.line_height != 1.93

    def test_dark_theme_changes_colors(self):
        from dbt_charts.core.render.sizing import get_compact_style

        light_style = get_compact_style(resolve_style(get_theme_style()))
        dark_rs = resolve_style(get_theme_style("neon"))
        dark_style = get_compact_style(dark_rs)
        # A different theme yields different prose colors — derived from the
        # resolved style, with no is_dark_color(background) branch.
        assert dark_style.text_color != light_style.text_color
        assert dark_style.font_family == dark_rs.text.font.family


class TestCompactStyleColorsTrackTheme:
    """Markdown prose colors derive from the resolved theme style, not a
    hardcoded light/dark table — so prose tracks the active theme like the
    rest of the board."""

    def test_text_color_tracks_font_color(self):
        from dbt_charts.core.render.sizing import get_compact_style

        rs = resolve_style(get_theme_style())
        assert get_compact_style(rs).text_color == rs.font.color

    def test_heading_color_tracks_title_color(self):
        from dbt_charts.core.render.sizing import get_compact_style

        rs = resolve_style(get_theme_style())
        assert get_compact_style(rs).heading_color == rs.title.font.color

    def test_link_color_tracks_accent(self):
        """Inline links paint with the accent so the affordance tracks the theme.
        (Inline code uses its own box token — covered in test_text_box_style_cascade.)
        """
        from dbt_charts.core.render.sizing import get_compact_style

        rs = resolve_style(get_theme_style())
        assert get_compact_style(rs).link_color == rs.accent

    def test_table_and_hr_rules_track_table_border_tier(self):
        """Table grid + hr track the soft table-border tier (code/blockquote box
        tokens are covered in test_text_box_style_cascade)."""
        from dbt_charts.core.render.sizing import get_compact_style

        rs = resolve_style(get_theme_style())
        csc = resolve_chart_style_context(get_theme_style())
        style = get_compact_style(rs)
        assert style.table_border_color == csc.table.border.color
        assert style.hr_color == csc.table.border.color

    def test_table_header_background_tracks_theme(self):
        from dbt_charts.core.render.sizing import get_compact_style

        rs = resolve_style(get_theme_style())
        csc = resolve_chart_style_context(get_theme_style())
        assert get_compact_style(rs).table_header_background == (
            csc.table.header.background or rs.background
        )


class TestVendoredFontPaths:
    """Custom chart-lab fonts should be vendored alongside Inter.

    The chart-lab mirror sync check is intentionally not covered here,
    since design/experiments/ is outside dbt-charts/.
    """

    def test_dbt_sans_tabular_font_exists(self):
        assert get_face(DBT_SANS_TABULAR_FONT_FAMILY).measure_path.exists()

    def test_dbt_serif_oldstyle_tabular_font_exists(self):
        assert get_face(DBT_SERIF_OLDSTYLE_TABULAR_FONT_FAMILY).measure_path.exists()

    def test_dbt_serif_oldstyle_proportional_font_exists(self):
        assert get_face(
            DBT_SERIF_OLDSTYLE_PROPORTIONAL_FONT_FAMILY
        ).measure_path.exists()

    def test_source_serif_4_font_exists(self):
        assert (get_fonts_dir() / "SourceSerif4Variable.woff2").exists()
        assert get_face(SOURCE_SERIF_4_FONT_FAMILY).measure_path.exists()

    def test_noto_emoji_font_exists(self):
        assert get_face(NOTO_EMOJI_FONT_FAMILY).measure_path.exists()
        woff2 = get_fonts_dir() / "NotoEmoji-Regular.woff2"
        assert woff2.exists()

    def test_vendored_font_docs_exist(self):
        fonts_dir = get_fonts_dir()
        assert (fonts_dir / "README.md").exists()
        assert (fonts_dir / "SOURCE_SERIF_4_LICENSE.txt").exists()
        assert (fonts_dir / "NOTO_EMOJI_LICENSE.txt").exists()


class TestMdsvgPublicAPIFontPath:
    """mdsvg render/measure should accept font_path kwarg."""

    def test_render_accepts_font_path(self):
        from mdsvg import render

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        svg = render("Hello world", width=200, font_path=font_path)
        assert "<svg" in svg

    def test_measure_accepts_font_path(self):
        from mdsvg import measure

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        size = measure("Hello world", width=200, font_path=font_path)
        assert size.width > 0
        assert size.height > 0

    def test_render_content_accepts_font_path(self):
        from mdsvg import render_content

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        result = render_content("Hello world", width=200, font_path=font_path)
        assert result.height > 0

    def test_render_blocks_accepts_font_path(self):
        from mdsvg import parse, render_blocks

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        blocks = parse("Hello world")
        svg = render_blocks(blocks, width=200, font_path=font_path)
        assert "<svg" in svg

    def test_table_font_measurer_raises_when_precise_measurement_is_unavailable(
        self,
    ):
        from dbt_charts.core import font_measure as measurement_module

        original = measurement_module._load_measurer

        def _fail(_font_path: str):
            raise RuntimeError("boom")

        measurement_module._load_measurer = _fail
        try:
            with pytest.raises(RuntimeError, match="boom"):
                measurement_module.get_font_measurer("Inter")
        finally:
            measurement_module._load_measurer = original


class TestRenderTitleUsesTextStack:
    """render_title SVG output should reference the resolved text stack."""

    def test_title_svg_uses_resolved_text_font_family(self):
        from dbt_charts.core.render.svg_utils import render_title

        rs = resolve_style(get_theme_style())
        svg = render_title("Hello", width=400, resolved_style=rs)
        assert rs.text.font.family.split(",")[0].strip() in svg


class TestVlConvertFontNormalization:
    """SVG family normalization rewrites Inter but passes vendored serif families through unchanged."""

    def test_dbt_oldstyle_tabular_family_passes_through_unchanged(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="dbt Serif Oldstyle Tabular">Hello</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="dbt Serif Oldstyle Tabular"' in normalized

    def test_dbt_oldstyle_proportional_stack_passes_through_unchanged(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = (
            "<text font-family=\"'dbt Serif Oldstyle Proportional', "
            "'Source Serif 4', Georgia, serif\">Hello</text>"
        )
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert "'dbt Serif Oldstyle Proportional', 'Source Serif 4'" in normalized
        assert "Variable" not in normalized

    def test_source_serif_4_family_passes_through_unchanged(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="Source Serif 4">Hello</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="Source Serif 4"' in normalized
        assert "Variable" not in normalized

    def test_source_serif_4_stack_passes_through_unchanged(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = (
            "<text font-family=\"'Source Serif 4', Georgia, "
            "'Times New Roman', serif\">Hello</text>"
        )
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert "'Source Serif 4'" in normalized
        assert "'Source Serif 4 Variable'" not in normalized

    def test_source_serif_4_weight_500_rewritten_to_dbt_serif_medium(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = (
            "<text font-family=\"'Source Serif 4', Georgia, serif\" "
            'font-weight="500">40</text>'
        )
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert "'dbt Serif Medium', Georgia, serif" in normalized
        assert "Source Serif 4" not in normalized

    def test_source_serif_4_weight_600_rewritten_to_dbt_serif_semibold(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="Source Serif 4" font-weight="600">40</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="dbt Serif SemiBold"' in normalized

    def test_source_serif_4_weight_400_passes_through_unchanged(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="Source Serif 4" font-weight="400">40</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="Source Serif 4"' in normalized

    def test_source_serif_4_weight_700_has_no_registered_board_passes_through(self):
        """700 is outside the closed weight set — no static board exists for it,
        so the rewrite must not invent one."""
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="Source Serif 4" font-weight="700">40</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="Source Serif 4"' in normalized

    def test_dbt_sans_tabular_weight_500_rewritten_to_its_medium_board(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="dbt Sans Tabular" font-weight="500">40</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="dbt Sans Tabular Medium"' in normalized

    def test_inter_weight_500_rewritten_after_the_inter_variable_alias(self):
        """The Inter -> Inter Variable rewrite and the weight rewrite compose:
        a bare public 'Inter' family at weight 500 ends up at the Medium board."""
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="Inter" font-weight="500">Hello</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="Inter Variable Medium"' in normalized

    def test_inter_variable_weight_600_rewritten_to_its_semibold_board(self):
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = '<text font-family="Inter Variable" font-weight="600">Hello</text>'
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="Inter Variable SemiBold"' in normalized

    def test_weight_rewrite_is_scoped_per_tag_not_whole_document(self):
        """A weight=500 attribute on one tag must not leak into a sibling tag."""
        from dbt_charts.core.render.font_support import (
            normalize_svg_font_families_for_vl_convert,
        )

        svg = (
            '<text font-family="Source Serif 4" font-weight="500">A</text>'
            '<text font-family="Source Serif 4" font-weight="400">B</text>'
        )
        normalized = normalize_svg_font_families_for_vl_convert(svg)
        assert 'font-family="dbt Serif Medium" font-weight="500">A' in normalized
        assert 'font-family="Source Serif 4" font-weight="400">B' in normalized


class TestLayoutDimensionStability:
    """Regression guard: markdown dimensions should be stable with vendored Inter."""

    def test_simple_paragraph_height(self):
        """A simple paragraph at width=400 should have a stable positive height with Inter."""
        from mdsvg import Style, measure

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        style = Style(font_family="Inter", base_font_size=14.0, line_height=1.6)
        text = "The quick brown fox jumps over the lazy dog."
        size1 = measure(text, width=400, padding=0.0, style=style, font_path=font_path)
        size2 = measure(text, width=400, padding=0.0, style=style, font_path=font_path)
        assert size1.height > 0, f"Height must be positive, got: {size1.height}"
        assert size1.height == size2.height, "Repeated measurement must be stable"

    def test_measure_render_height_agreement(self):
        """measure() and render() with same font_path should produce same height."""
        from dbt_charts.core.render.svg_utils import extract_svg_dimensions
        from mdsvg import Style, measure, render

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        style = Style(font_family="Inter", base_font_size=14.0, line_height=1.6)
        text = "A paragraph with **bold** and *italic* text that might wrap."

        measured = measure(
            text, width=300, padding=0.0, style=style, font_path=font_path
        )
        svg = render(text, width=300, padding=0.0, style=style, font_path=font_path)
        dims = extract_svg_dimensions(svg)

        assert abs(measured.height - dims.height) < 1.0, (
            f"Height mismatch: measure={measured.height}, render={dims.height}"
        )

    def test_precise_measurement_does_not_add_safety_scale_to_body_text(self):
        """Precise fonttools widths should not be inflated for normal body text."""
        from mdsvg import Style, measure
        from mdsvg.fonts import FontMeasurer

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        text = (
            "This line should stay on one line when precise font measurement is active."
        )
        exact_width = FontMeasurer(font_path).measure(text, 14.0)
        style = Style(font_family="Inter", base_font_size=14.0, line_height=1.6)

        size = measure(
            text,
            width=exact_width + 1.0,
            padding=0.0,
            style=style,
            font_path=font_path,
        )

        assert size.height < 30.0, (
            "Precise measurement should keep this paragraph on one line; "
            "inflating widths with a safety scale makes it wrap early."
        )

    def test_render_title_does_not_add_safety_scale_to_precise_board_titles(self):
        """Board titles should wrap on exact measured width, not a 10% inflated width."""
        from dbt_charts.core.render.svg_utils import render_title
        from mdsvg.fonts import FontMeasurer

        font_path = str(get_face(INTER_VARIABLE_FONT_FAMILY).measure_path)
        title = (
            "Board title wrapping should use the real measured width, not an "
            "inflated safety margin"
        )
        exact_width = FontMeasurer(font_path).measure(title, 32.0)

        svg = render_title(
            title,
            width=exact_width + 1.0,
            resolved_style=resolve_style(get_theme_style()),
        )

        assert svg.count('class="md-heading"') == 1
        assert title in svg
