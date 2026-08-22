"""Tests for chart converter — specifically the vl-convert missing dependency path."""

from __future__ import annotations

import base64
import io
import sys
import types
from unittest import mock

import pytest
from PIL import Image

from dbt_charts.core.compile.config import (
    get_theme_style,
)
from dbt_charts.core.compile.resolve.style.board import (
    resolve_chart_style_context,
    resolve_style,
    resolve_style_and_context,
)
from dbt_charts.core.render.errors import FormatError


def _noop_register_fonts(vlc_module: object) -> None:
    pass


def test_render_vega_spec_raises_format_error_when_vlconvert_missing() -> None:
    """render_vega_spec must raise FormatError (not ImportError) when vl-convert is absent."""
    # Block the import so render_vega_spec hits the except branch.
    with mock.patch.dict(sys.modules, {"vl_convert": None}):
        # Re-import to get a fresh call that hits the guarded import.
        from dbt_charts.core.render.converters.chart import render_vega_spec

        with pytest.raises(FormatError, match="vl-convert-python is required"):
            render_vega_spec(
                {"$schema": "..."},
                "svg",
                resolve_style(get_theme_style()),
                None,
                None,
                False,
                chart_id="chart",
            )


@pytest.mark.parametrize(
    ("module_name", "helper_name"),
    [
        ("png", "svg_to_png"),
        ("pdf", "svg_to_pdf"),
    ],
)
def test_vl_convert_export_normalizes_inter_family_only_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    helper_name: str,
) -> None:
    """vl-convert exports should keep authored SVG as Inter but normalize internally."""
    module = __import__(
        f"dbt_charts.core.render.converters.{module_name}", fromlist=["*"]
    )
    fake_helper = mock.Mock(return_value=b"bytes")
    fake_vlc = types.SimpleNamespace(
        register_font_directory=mock.Mock(),
        **{helper_name: fake_helper},
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(module, "register_vl_convert_fonts", _noop_register_fonts)

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40">'
        "<style>.cls{font-family:Inter;} :root { --dbt-font-family: Inter; }</style>"
        '<text x="10" y="30" class="cls" font-family="Inter">Visible</text>'
        "</svg>"
    )

    if module_name == "png":
        result = module.to_png(svg, scale=1.0)
        fake_helper.assert_called_once()
        normalized_svg = fake_helper.call_args.args[0]
        assert fake_helper.call_args.kwargs["scale"] == 1.0
    else:
        result = module.to_pdf(svg)
        fake_helper.assert_called_once()
        normalized_svg = fake_helper.call_args.args[0]

    assert result == b"bytes"
    assert 'font-family="Inter"' in svg
    assert "font-family:Inter;" in svg
    assert "--dbt-font-family: Inter;" in svg
    assert 'font-family="Inter Variable"' in normalized_svg
    assert "font-family:Inter Variable;" in normalized_svg
    assert "--dbt-font-family: Inter Variable;" in normalized_svg


@pytest.mark.parametrize(
    ("module_name", "helper_name"),
    [
        ("png", "svg_to_png"),
        ("pdf", "svg_to_pdf"),
    ],
)
def test_vl_convert_export_preserves_dbt_serif_oldstyle_families(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    helper_name: str,
) -> None:
    """Derived serif families should pass through unchanged to vl-convert."""
    module = __import__(
        f"dbt_charts.core.render.converters.{module_name}", fromlist=["*"]
    )
    fake_helper = mock.Mock(return_value=b"bytes")
    fake_vlc = types.SimpleNamespace(
        register_font_directory=mock.Mock(),
        **{helper_name: fake_helper},
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(module, "register_vl_convert_fonts", _noop_register_fonts)

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40">'
        '<text x="10" y="30" '
        'font-family="dbt Serif Oldstyle Proportional">Visible</text>'
        "</svg>"
    )

    if module_name == "png":
        result = module.to_png(svg, scale=1.0)
    else:
        result = module.to_pdf(svg)

    normalized_svg = fake_helper.call_args.args[0]
    assert result == b"bytes"
    assert "dbt Serif Oldstyle Proportional" in normalized_svg


@pytest.mark.parametrize(
    ("format_name", "helper_name", "expected_bytes"),
    [
        ("png", "to_png", b"png-bytes"),
        ("pdf", "to_pdf", b"pdf-bytes"),
    ],
)
def test_render_vega_spec_derives_binary_formats_from_svg(
    monkeypatch: pytest.MonkeyPatch,
    format_name: str,
    helper_name: str,
    expected_bytes: bytes,
) -> None:
    """PNG/PDF chart exports should derive from the same SVG render path."""
    from dbt_charts.core.render.converters import chart as chart_converter

    fake_vlc = types.SimpleNamespace(
        vegalite_to_svg=mock.Mock(return_value='<svg width="600" height="320"></svg>'),
        vegalite_to_png=mock.Mock(side_effect=AssertionError("unexpected direct png")),
        vegalite_to_pdf=mock.Mock(side_effect=AssertionError("unexpected direct pdf")),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )
    helper = mock.Mock(return_value=expected_bytes)
    monkeypatch.setattr(chart_converter, helper_name, helper)

    encoded = chart_converter.render_vega_spec(
        {"$schema": "..."},
        format_name,
        resolve_style(get_theme_style()),
        600,
        320,
        False,
        chart_id="chart",
    )

    fake_vlc.vegalite_to_svg.assert_called_once_with({"$schema": "..."})
    if format_name == "png":
        helper.assert_called_once_with(
            '<svg width="600" height="320"></svg>', scale=1.0
        )
    else:
        helper.assert_called_once_with('<svg width="600" height="320"></svg>')
    assert base64.b64decode(encoded) == expected_bytes


def test_correct_concat_overshoot_corrects_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """render_vega_spec must correct hconcat SVG height when $df_target_height is set.

    vl-convert ignores autosize:fit on hconcat children, so the rendered SVG
    height overshoots the spec height by chart-chrome overhead (~80px). The two-
    pass correction probes the outer dimensions via vegalite_to_scenegraph (a
    structured read, no SVG-string regex) and shrinks both pane heights by the
    overshoot before the real render.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    target_height = 250.0
    overhead = 80.0
    probe_height = target_height + overhead

    pane0 = {"width": 595, "height": target_height}
    pane1 = {"width": 50, "height": target_height}
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "$df_target_height": target_height,
        "spacing": 5,
        "hconcat": [pane0, pane1],
    }

    real_svg = f'<svg width="645.0" height="{target_height}"></svg>'
    probe_call_count = 0

    def fake_vegalite_to_scenegraph(s):
        nonlocal probe_call_count
        probe_call_count += 1
        return {"width": 645.0, "height": probe_height, "origin": [0, 0]}

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_vegalite_to_scenegraph,
        vegalite_to_svg=mock.Mock(return_value=real_svg),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )

    result = chart_converter.render_vega_spec(
        spec,
        "svg",
        resolve_style(get_theme_style()),
        645,
        target_height,
        False,
        chart_id="chart",
    )

    assert probe_call_count == 1, "Expected one scenegraph probe"
    fake_vlc.vegalite_to_svg.assert_called_once()
    corrected_h0 = pane0.get("height")
    corrected_h1 = pane1.get("height")
    assert corrected_h0 == target_height - overhead, (
        f"pane[0] height must be corrected to {target_height - overhead}, "
        f"got {corrected_h0}"
    )
    assert corrected_h1 == target_height - overhead, (
        f"pane[1] height must be corrected to {target_height - overhead}, "
        f"got {corrected_h1}"
    )
    assert real_svg in result


def test_correct_concat_overshoot_corrects_vconcat_chart_pane_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """vconcat height overshoot must shrink the chart pane, not the rail.

    A horizontal stacked bar with a color channel wraps in a vconcat whose
    panes stack: rail on top, chart below. The chart pane's own axis chrome
    renders outside its declared height, so the rendered SVG overshoots the
    authored height exactly as it does for hconcat. Only the chart pane
    (index 1) may absorb it — the rail's height is fixed chrome, and shrinking
    it would clip the series labels.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    target_height = 400.0
    overhead = 30.0
    rail_height = 20.0
    chart_pane_height = 374.0

    rail = {"width": 600, "height": rail_height}
    chart_pane = {"width": 600, "height": chart_pane_height}
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "$df_target_height": target_height,
        "spacing": 6,
        "vconcat": [rail, chart_pane],
    }

    real_svg = f'<svg width="600.0" height="{target_height}"></svg>'

    def fake_vegalite_to_scenegraph(s):
        return {"width": 600.0, "height": target_height + overhead, "origin": [0, 0]}

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_vegalite_to_scenegraph,
        vegalite_to_svg=mock.Mock(return_value=real_svg),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )

    chart_converter.render_vega_spec(
        spec,
        "svg",
        resolve_style(get_theme_style()),
        600,
        target_height,
        False,
        chart_id="chart",
    )

    assert chart_pane["height"] == chart_pane_height - overhead, (
        f"chart pane must absorb the {overhead}px overshoot; got {chart_pane['height']}"
    )
    assert rail["height"] == rail_height, (
        f"rail height is fixed chrome and must not shrink; got {rail['height']}"
    )


def test_render_vega_spec_hconcat_title_wrap_uses_chart_local_title_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deferred hconcat title wrap must read $df_title_style, not
    resolved_style.charts.title.

    _render_vl_artifact stamps the chart's own resolved title_style onto the
    spec (alongside $df_target_width/$df_target_height) precisely so this
    two-pass wrap agrees with the non-hconcat path, which already reads the
    chart-local value directly off the resolved chart. Regression: before the
    fix, this deferred branch fell back to the board-level bag, so a
    chart-local style.<family>.title override was silently dropped for any
    chart that also gets an endpoint-label pane.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    target_width = 500.0
    chart_title_style = resolve_chart_style_context(get_theme_style()).title.model_copy(
        update={"overflow": "clip"}
    )
    pane0 = {"width": 495, "height": 300, "title": {"text": "Some Chart Title"}}
    pane1 = {"width": 50, "height": 300}
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "$df_target_width": target_width,
        # Stamped as a plain dict in production (JSON-safety — see
        # vega_lite.py's _render_vl_artifact) and reconstructed here by
        # render_vega_spec via TitleStyle.model_validate().
        "$df_title_style": chart_title_style.model_dump(),
        "spacing": 5,
        "hconcat": [pane0, pane1],
    }

    def fake_vegalite_to_scenegraph(s):
        return {"width": 550.0, "height": 300.0, "origin": [0, 0]}

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_vegalite_to_scenegraph,
        vegalite_to_svg=mock.Mock(
            return_value='<svg width="550.0" height="300"></svg>'
        ),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )

    captured_styles = []
    real_apply = chart_converter.apply_title_overflow_to_spec

    def spy_apply(spec_arg, title_style, **kwargs):
        captured_styles.append(title_style)
        return real_apply(spec_arg, title_style, **kwargs)

    monkeypatch.setattr(chart_converter, "apply_title_overflow_to_spec", spy_apply)

    # A board-level style distinct from the chart-local one above -- if the
    # deferred wrap ever falls back to this, the spy captures it instead.
    board_style = resolve_style(get_theme_style())

    chart_converter.render_vega_spec(
        spec, "svg", board_style, target_width, 300, False, chart_id="chart"
    )

    assert captured_styles, "apply_title_overflow_to_spec was never called"
    assert all(style == chart_title_style for style in captured_styles), (
        "hconcat deferred title wrap must use the chart-local $df_title_style, "
        f"not board_style.charts.title; got {captured_styles!r}"
    )


def test_correct_concat_overshoot_raises_on_nonpositive_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_correct_concat_overshoot must raise when overshoot correction yields new_w <= 0.

    A long unbounded subtitle can produce an overshoot so large that
    orig_w - overshoot becomes non-positive. The old guard silently skipped
    the correction, leaving the main pane oversized and pushing the endpoint-
    label pane off-canvas. After the fix, a clear error must be raised.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    target_width = 500.0
    # overshoot so large that orig_w - overshoot < 0
    huge_probe_width = target_width + 600.0  # overshoot = 600, new_w = 500 - 600 = -100

    pane0 = {"width": 500.0, "height": 300}
    pane1 = {"width": 50, "height": 300}
    spec = {
        "hconcat": [pane0, pane1],
    }

    def fake_vegalite_to_scenegraph(s: object) -> dict:
        return {"width": huge_probe_width, "height": 300.0, "origin": [0, 0]}

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_vegalite_to_scenegraph,
    )

    from dbt_charts.core.diagnostics.chart_data import ChartDataError

    with pytest.raises(ChartDataError, match="non-positive"):
        chart_converter._correct_concat_overshoot(
            spec, target_width, None, fake_vlc, None, "chart"
        )


def test_hconcat_subtitle_bounded_before_overshoot_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subtitle must be bounded before the overshoot probe for hconcat specs.

    Without pre-probe bounding, an unbounded long subtitle contributes its full
    natural width to the scenegraph, producing a huge overshoot that yields
    new_w <= 0 and raises ChartDataError. After the fix, the subtitle is wrapped
    to at most two lines before the probe, so the probe returns a reasonable
    width and pane[0].width remains positive after correction.

    This is the regression test for the endpoint-labels blow-up: long subtitle
    + fixed-width label pane (hconcat[1]) pushing the label pane off-canvas.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    target_width = 400.0
    pane_width = 380.0
    # A subtitle that, if unbounded, would report ~900px natural width —
    # far wider than the 400px target, producing new_w = 380 - 500 = -120 (negative).
    long_subtitle = "Endpoint labels regression: " + ("long subtitle text " * 25)

    pane0 = {
        "width": pane_width,
        "padding": {"left": 10, "right": 10},
        "title": {"text": "Title", "subtitle": long_subtitle},
        "mark": "line",
        "encoding": {},
    }
    pane1 = {"width": 50, "height": 300}
    spec = {
        "$df_target_width": target_width,
        "hconcat": [pane0, pane1],
    }

    # The probe width depends on whether subtitle was bounded before the call:
    # bounded (list) → small overshoot; unbounded (long str) → huge overshoot.
    def fake_scenegraph(s: object) -> dict:
        subtitle = s["hconcat"][0].get("title", {}).get("subtitle", "")  # type: ignore[union-attr]
        if isinstance(subtitle, list) or (
            isinstance(subtitle, str) and len(subtitle) < 200
        ):
            # Bounded: small overshoot (axis/legend chrome)
            return {"width": target_width + 30.0, "height": 300.0}
        # Unbounded: overshoot so large new_w would be negative
        return {"width": target_width + 500.0, "height": 300.0}

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_scenegraph,
        vegalite_to_svg=mock.Mock(return_value='<svg viewBox="0 0 400 300"></svg>'),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )

    # Must not raise — pre-probe bounding keeps new_w positive.
    chart_converter.render_vega_spec(
        spec,
        "svg",
        resolve_style(get_theme_style()),
        target_width,
        None,
        False,
        chart_id="chart",
    )

    corrected_w = pane0.get("width")
    assert isinstance(corrected_w, float) and corrected_w > 0, (
        f"pane[0].width must be positive after correction, got {corrected_w}"
    )


def test_hconcat_subtitle_rewrapped_at_corrected_width_not_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final subtitle wrap must reflect the corrected width, not the pre-probe width.

    render_vega_spec wraps the subtitle twice: once before the overshoot probe
    (using pane[0]'s original, un-corrected width, purely to bound the probe)
    and once after correction (using the real, shrunk width) so Vega clips at
    the right boundary. The second pass must re-wrap from the original text —
    if it instead reuses the array produced by the first pass (which was
    wrapped for a wider limit), Vega's ``title.limit`` re-truncates each
    already-wrapped line down to the narrower corrected limit, cutting text off
    far earlier than the wrap-two layout intended.
    """
    from dbt_charts.core.render.chart.title_overflow import (
        prepare_title_text,
        resolve_title_overflow,
    )
    from dbt_charts.core.render.converters import chart as chart_converter

    target_width = 400.0
    pre_probe_width = 500.0
    # Long enough that the pre-probe (width=500) and corrected (width=400 - 100
    # overshoot = ~pane width) wraps land on different line breaks.
    subtitle_text = "Endpoint labels regression " + ("wrap boundary text " * 8)

    pane0 = {
        "width": pre_probe_width,
        "padding": {"left": 10, "right": 10},
        "title": {"text": "Title", "subtitle": subtitle_text},
        "mark": "line",
        "encoding": {},
    }
    pane1 = {"width": 50, "height": 300}
    rs, ctx = resolve_style_and_context(get_theme_style())
    spec = {
        "$df_target_width": target_width,
        "$df_title_style": ctx.title.model_dump(),
        "hconcat": [pane0, pane1],
    }

    # Constant 100px overshoot regardless of subtitle content — isolates the
    # rewrap-vs-stale behavior from the earlier new_w<=0 guard.
    def fake_scenegraph(s: object) -> dict:
        return {"width": target_width + 100.0, "height": 300.0}

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_scenegraph,
        vegalite_to_svg=mock.Mock(return_value='<svg viewBox="0 0 400 300"></svg>'),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )

    chart_converter.render_vega_spec(
        spec,
        "svg",
        rs,
        target_width,
        None,
        False,
        chart_id="chart",
    )

    final_limit = pane0["title"]["limit"]
    final_subtitle = pane0["title"]["subtitle"]

    title_style = ctx.title
    subtitle_style = getattr(title_style, "subtitle", None)
    subtitle_font_size = float(
        getattr(getattr(subtitle_style, "font", None), "size", None) or 18
    )
    expected, _ = prepare_title_text(
        subtitle_text,
        overflow=resolve_title_overflow(subtitle_style),
        limit=final_limit,
        font_size=subtitle_font_size,
    )
    expected_lines = expected.split("\n")
    expected_result = expected_lines if len(expected_lines) > 1 else expected

    assert final_subtitle == expected_result, (
        "Final subtitle must be re-wrapped from the original text at the "
        f"corrected limit ({final_limit}), not left stale from the pre-probe "
        f"wrap. Got {final_subtitle!r}, expected {expected_result!r}."
    )


def test_hconcat_title_limit_uses_pane_footprint_not_shrunk_plot_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Title/subtitle limit must reflect pane[0]'s full visual footprint.

    ``_correct_concat_overshoot`` shrinks pane[0]["width"] — Vega-Lite's
    *data-plot* width — by the ENTIRE probe overshoot, which includes the
    y-axis tick-label gutter that vl-convert renders outside "width" (it
    ignores ``autosize: fit`` on concat children, so the gutter isn't folded
    back into the plot rect the way it would be for a plain, non-concat
    chart). Vega positions the title/subtitle spanning that whole visual
    footprint (axis gutter + plot rect), not just the shrunk plot rect. Using
    the shrunk ``pane[0]["width"]`` as the title's available width therefore
    under-counts by the gutter size, wrapping/truncating far earlier than the
    chart actually has room for — the title's real budget is
    ``target_width - pane[1].width - spacing``, not ``pane[0].width`` after
    correction.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    target_width = 320.0
    pane1_width = 80.0
    spacing = 5.0
    axis_gutter = 60.0  # chrome vl-convert renders outside pane[0]["width"]

    root_padding = {"left": 10.0, "right": 10.0, "top": 10.0, "bottom": 10.0}

    # Padding sits on the concat ROOT, which is the only node Vega-Lite reads it
    # from and therefore the only shape _render_vl_artifact emits. A copy on the
    # pane would be dropped, and a test that put it there would exercise a spec
    # production no longer builds.
    pane0 = {
        "width": target_width,
        "padding": {"left": 0, "right": 0, "top": 0, "bottom": 0},
        "title": {"text": "Win Rate by Source", "subtitle": "short subtitle"},
        "mark": "line",
        "encoding": {},
    }
    pane1 = {"width": pane1_width, "height": 300}
    spec = {
        "$df_target_width": target_width,
        "spacing": spacing,
        "padding": root_padding,
        "hconcat": [pane0, pane1],
    }

    # Constant overshoot standing in for axis gutter + spacing + pane[1] —
    # independent of pane[0]'s own (bounded) title/subtitle content.
    def fake_scenegraph(s: object) -> dict:
        return {
            "width": target_width + axis_gutter + spacing + pane1_width,
            "height": 300.0,
        }

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_scenegraph,
        vegalite_to_svg=mock.Mock(return_value='<svg viewBox="0 0 320 300"></svg>'),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )

    chart_converter.render_vega_spec(
        spec,
        "svg",
        resolve_style(get_theme_style()),
        target_width,
        None,
        False,
        chart_id="chart",
    )

    # Both root paddings come off the total before pane[0] gets its share:
    # the whole concat sits inside them.
    expected_limit = int(
        target_width
        - pane1_width
        - spacing
        - root_padding["left"]
        - root_padding["right"]
    )
    assert pane0["title"]["limit"] == expected_limit, (
        f"Title limit must be based on pane[0]'s visual footprint "
        f"({expected_limit}), not the shrunk plot-only width "
        f"({pane0['width']}). Got {pane0['title']['limit']}."
    )


def test_hconcat_title_limit_loses_both_root_paddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authored ``padding.right`` shrinks the hconcat title limit like any other.

    Reproduces the ``win_rate_trend`` chart in
    ``examples/playground-experimental/charts/general/dundersign-commercial-finance-default.yml``:
    it sets ``style.padding.right: 36`` (36 + the 16px theme base = 52) to keep
    the plot/axis away from the endpoint-label pane.

    This once asserted the opposite. While ``padding`` sat on ``hconcat[0]``,
    Vega-Lite dropped it and rendered the concat against its own 5px default, so
    the title's role-group really did extend past where the author's
    ``padding.right`` said the plot ended — and subtracting it would have thrown
    away title width the chart actually had. With ``padding`` on the root, where
    Vega-Lite reads it, the whole concat is inset by both sides and pane[0]'s
    footprint is what is left over. The old asymmetry was a symptom of the
    dropped padding, not a property of Vega's title placement.
    """
    from dbt_charts.core.render.converters import chart as chart_converter

    target_width = 389.76
    pane1_width = 83.255859375
    spacing = 6.0
    padding = {"left": 16.0, "right": 52.0, "top": 16.0, "bottom": 16.0}

    pane0 = {
        "width": target_width,
        "padding": {"left": 0, "right": 0, "top": 0, "bottom": 0},
        "title": {"text": "Win rate by source", "subtitle": "short subtitle"},
        "mark": "line",
        "encoding": {},
    }
    pane1 = {"width": pane1_width, "height": 200}
    spec = {
        "$df_target_width": target_width,
        "spacing": spacing,
        "padding": padding,
        "hconcat": [pane0, pane1],
    }

    def fake_scenegraph(s: object) -> dict:
        return {"width": target_width + 60.0, "height": 200.0}

    fake_vlc = types.SimpleNamespace(
        vegalite_to_scenegraph=fake_scenegraph,
        vegalite_to_svg=mock.Mock(return_value='<svg viewBox="0 0 390 200"></svg>'),
    )
    monkeypatch.setitem(sys.modules, "vl_convert", fake_vlc)
    monkeypatch.setattr(
        chart_converter, "register_vl_convert_fonts", _noop_register_fonts
    )

    chart_converter.render_vega_spec(
        spec,
        "svg",
        resolve_style(get_theme_style()),
        target_width,
        None,
        False,
        chart_id="chart",
    )

    expected_limit = int(
        target_width - pane1_width - spacing - padding["left"] - padding["right"]
    )
    assert pane0["title"]["limit"] == expected_limit, (
        f"Title limit must be pane[0]'s share of what the root padding leaves — "
        f"expected {expected_limit}, got {pane0['title']['limit']}."
    )


def test_render_chart_png_respects_requested_dimensions() -> None:
    """Direct chart PNG export should match the requested width and height."""
    from dbt_charts import compile as compile_dataface
    from dbt_charts.core.compile.config import reset_config
    from dbt_charts.core.render.chart.vega_lite import render_chart

    reset_config()
    result = compile_dataface(
        """
queries:
  q:
    columns: [month, revenue]
    values:
      - [Jan, 1]
      - [Feb, 2]
      - [Mar, 3]
      - [Apr, 4]
charts:
  c:
    type: line
    query: q
    x: month
    y: revenue
    title: Revenue Trend
rows:
  - c
"""
    )
    assert result.success and result.board is not None
    chart = result.board.charts["c"]
    data = [
        {"month": "Jan", "revenue": 1},
        {"month": "Feb", "revenue": 2},
        {"month": "Mar", "revenue": 3},
        {"month": "Apr", "revenue": 4},
    ]

    _rs, _ctx = resolve_style_and_context(get_theme_style())
    svg = render_chart(
        chart,
        _rs,
        _ctx,
        data,
        format="svg",
        width=600,
        height=320,
    )
    png = base64.b64decode(
        render_chart(
            chart,
            _rs,
            _ctx,
            data,
            format="png",
            width=600,
            height=320,
        )
    )

    assert 'width="600"' in svg
    assert 'height="320"' in svg
    image = Image.open(io.BytesIO(png))
    assert image.size == (600, 320)
