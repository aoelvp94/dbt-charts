"""Chart output conversion helpers."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from dbt_charts.core.compile.models.style.theme import TitleStyle
from dbt_charts.core.render.board_links import get_link_context, resolve_href
from dbt_charts.core.render.chart._types import VLDict
from dbt_charts.core.render.chart.artifacts import RenderArtifact
from dbt_charts.core.render.chart.endpoint_label_overflow import (
    EndpointLabelGapOverflow,
    record_endpoint_label_gap_overflow,
)
from dbt_charts.core.render.chart.features.endpoint_labels import (
    recascade_endpoint_labels,
)

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.style.resolved import ResolvedStyle
from dbt_charts.core.diagnostics.chart_data import ChartDataError
from dbt_charts.core.diagnostics.codes_render import (
    ERR_CONCAT_OVERSHOOT_NONPOSITIVE,
)
from dbt_charts.core.render.chart.title_overflow import (
    apply_title_overflow_to_spec,
    fix_title_alignment,
)
from dbt_charts.core.render.converters.pdf import to_pdf
from dbt_charts.core.render.converters.png import to_png
from dbt_charts.core.render.errors import FormatError
from dbt_charts.core.render.font_support import register_vl_convert_fonts
from dbt_charts.core.render.svg_cache import active_svg_cache, svg_cache_key
from dbt_charts.core.render.svg_utils import authored_kind_attr

# Strip sentinel prefix from vl_convert-rendered chart href <a> elements.
# vl_convert uses xlink:href and mangles relative URLs, so we embed a sentinel
# prefix that we can detect and strip here. The prefix is defined as
# _HREF_SENTINEL in render/chart/features/click_interactivity.py — change both.
_SENTINEL_HREF_RE = re.compile(r'<a xlink:href="http://dct\.invalid([^"]*)"')


def _fix_chart_click_hrefs(svg: str) -> str:
    """Convert sentinel xlink:href to plain href in SVG <a> elements.

    Converts ``<a xlink:href="http://dct.invalid/path?q=v">``
    to ``<a href="/path?q=v">`` so variables.js can intercept variable-update
    clicks and the browser can follow navigation clicks directly.

    When a link context is active (board resolver), board-root paths are
    rewritten for the current runtime (serve vs Cloud). Query-string-only
    links (?var=value) pass through unchanged — they are in-page variable
    updates intercepted by variables.js, not cross-board navigation.
    """
    ctx = get_link_context()

    def _replace(m: re.Match[str]) -> str:
        url = m.group(1)
        if ctx is not None:
            url = resolve_href(url, ctx)
        return f'<a href="{url}"'

    return _SENTINEL_HREF_RE.sub(_replace, svg)


# Inject stroke-linecap="round" on legend-symbol <path> elements emitted by
# vl_convert. Vega-Lite has no spec-level surface for this (probed
# legend.symbolStrokeCap, config.legend.symbolStrokeCap, config.style.symbol.
# strokeCap, config.mark.strokeCap — all silently dropped), so the legend's
# dash segments render with butt caps while the chart lines use round caps
# (LineStyle theme default). The mismatch is most visible when the dash
# palette contains a dotted entry: round caps render 0-length dashes as
# circular dots, butt caps render them as nothing. Match the chart's cap by
# stamping round onto the legend paths during post-processing — but only on
# charts that actually use the strokeDash encoding (gated by the caller),
# so that charts with no dashes keep producing byte-identical SVG output.
_LEGEND_SYMBOL_LINECAP_RE = re.compile(
    r'(class="[^"]*role-legend-symbol[^"]*"[^>]*><path)(?![^/]*stroke-linecap)([^/]*?)(/>)'
)


def _fix_legend_symbol_linecap(svg: str) -> str:
    """Stamp ``stroke-linecap="round"`` onto legend-symbol paths."""
    return _LEGEND_SYMBOL_LINECAP_RE.sub(r'\1 stroke-linecap="round"\2\3', svg)


# Vega's own role-title-text / role-title-subtitle classes are a genuine 1:1
# signal for the chart's title:/subtitle: keys (unlike md-heading, which the
# renderer also emits for prose headings) — transcribed here into the
# data-authored-kind leaf vocabulary rather than left for Cloud to read the
# foreign class directly. Selectors.md's "data-* for JS selection, never a
# class" rule carves out core-generated dbt-* classes as safe to query; these
# are vl_convert's, not ours, so the carve-out does not reach them and the
# dependency stays inside the module that already owns vl_convert output.
_TITLE_KIND_RE = re.compile(r'(class="mark-text role-title-text")')
_SUBTITLE_KIND_RE = re.compile(r'(class="mark-text role-title-subtitle")')


def _stamp_chart_title_kind(svg: str) -> str:
    """Tag the chart's own title/subtitle text runs with their leaf kind."""
    svg = _TITLE_KIND_RE.sub(rf"\1{authored_kind_attr('title')}", svg)
    return _SUBTITLE_KIND_RE.sub(rf"\1{authored_kind_attr('subtitle')}", svg)


def _spec_has_encoding(spec: dict[str, Any], channels: Iterable[str]) -> bool:
    """True when ``spec`` carries any of ``channels`` in an encoding.

    Recurses through ``spec["encoding"]``, ``spec["layer"]``, ``spec["hconcat"]``,
    and ``spec["vconcat"]`` at every depth — deep enough to catch the
    endpoint-label-rail wrapper that wraps a layered line chart inside
    ``hconcat[0]``, and any future nested composition.  Cheap gate used before
    SVG post-processors so charts that don't use the channel keep producing
    byte-identical SVG.
    """
    channel_set = frozenset(channels)

    def _has(node: dict[str, Any]) -> bool:
        if channel_set & node.get("encoding", {}).keys():
            return True
        for child in node.get("layer", []):
            if isinstance(child, dict) and _has(child):
                return True
        for child in node.get("hconcat", []):
            if isinstance(child, dict) and _has(child):
                return True
        for child in node.get("vconcat", []):
            if isinstance(child, dict) and _has(child):
                return True
        return False

    return _has(spec)


def _padding_side(spec: VLDict, side: str) -> float:
    """One side of a spec's root padding.

    Vega-Lite accepts either a 4-key dict or a single number standing for all
    four sides; both reach here from authored themes and from our own emitters.
    """
    padding = spec.get("padding")
    if isinstance(padding, dict):
        return float(padding.get(side, 0) or 0)
    if isinstance(padding, (int, float)):
        return float(padding)
    return 0.0


def _label_pane_mark_leaves(probe: VLDict, chart_id: str) -> list[VLDict]:
    """Text-mark leaves for the label pane in vl-convert's probe scenegraph.

    Fixed nesting confirmed against vl_convert-python 1.9.0's scenegraph shape
    for the two-pane endpoint-label hconcat: pane[1]'s ``concat_1_marks`` text
    group sits at ``items[0].items[1].items[0].items[0].items``.
    ``vegalite_to_scenegraph`` carries no ``scale``/``domain`` anywhere — this
    is pixel-space mark data only, which is exactly what a slope measurement
    needs.
    """
    try:
        return probe["scenegraph"]["items"][0]["items"][1]["items"][0]["items"][0][
            "items"
        ]
    except (KeyError, IndexError, TypeError) as exc:
        raise ChartDataError(
            f"could not locate endpoint-label marks in the probe scenegraph: {exc}",
            chart_id=chart_id,
        ) from exc


def _recascade_endpoint_label_pane(
    spec: VLDict,
    probe: VLDict,
    cascade: VLDict,
    chart_id: str,
    height_correction_ratio: float,
) -> None:
    """Rewrite the label pane's inline dataset with re-cascaded positions.

    Mechanical: reads the pre-probe (raw anchor) rows the label pane rendered,
    hands them plus this same probe's own label marks and the pane's
    height-correction ratio to the one pure cascade entry point in
    ``features/endpoint_labels.py``, and writes the returned positions back.
    All cascade math and pixel<->data conversion — including the slope's
    height-correction adjustment — lives in that module; this function moves
    data, it does not compute it.

    Runs when the spec carries the ``$df_endpoint_label_cascade`` sentinel *and*
    a probe was obtained. A spec with an attached ``data_table`` strip (no
    ``$df_target_height``) still qualifies — it re-cascades off this same probe
    with ``height_correction_ratio == 1.0``, since nothing shrank.

    Two paths skip it: the caller returns early when both size targets are None,
    and the probe's own ``except`` returns when ``vegalite_to_scenegraph``
    throws. Labels then keep their un-cascaded anchor positions. No case is
    known where the scenegraph call fails while the SVG render of the same spec
    succeeds, but the cost of that path is now all of the collision avoidance,
    not just the size correction — worth knowing before widening the catch.
    """
    series_field = cascade["series_field"]
    value_alias = cascade["value_alias"]
    pane = spec["hconcat"][1]
    # From the sentinel, not the pane: the pane's rows may have been spread
    # apart purely so the probe could measure the scale (translate.py's
    # _spread_for_measurement). These are the real endpoint values.
    anchors = {name: float(y) for name, y in cascade["anchors"]}
    emitted = {
        row[series_field]: float(row[value_alias]) for row in pane["data"]["values"]
    }
    result = recascade_endpoint_labels(
        anchors=anchors,
        pixel_gap=cascade["gap_px"],
        y_domain_min=cascade["y_domain_min"],
        y_domain_max=cascade["y_domain_max"],
        label_mark_leaves=_label_pane_mark_leaves(probe, chart_id),
        height_correction_ratio=height_correction_ratio,
        emitted=emitted,
    )
    pane["data"]["values"] = [
        {series_field: s, value_alias: y} for s, y in result.positions
    ]
    if result.outcome != "fit":
        record_endpoint_label_gap_overflow(
            chart_id,
            EndpointLabelGapOverflow(
                series_count=len(anchors),
                gap_px=cascade["gap_px"],
                cause=result.outcome,
            ),
        )


def _correct_concat_overshoot(
    spec: dict[str, Any],
    target_width: float | None,
    target_height: float | None,
    vlc: Any,
    endpoint_label_cascade: VLDict | None,
    chart_id: str,
) -> None:
    """Two-pass width/height correction for hconcat/vconcat endpoint-label specs.

    vl-convert ignores ``autosize: fit`` on concat children, so the first
    render measures the actual outer dimensions via ``vegalite_to_scenegraph``
    (structured — no SVG-string regex); the overshoot is subtracted from the
    resizable pane(s) before the real render.

    Width: hconcat shrinks pane[0] only (label pane is fixed-width). vconcat
    shrinks both panes — they share the x scale and must resize together so rail
    labels stay centered.

    Height: hconcat panes sit side by side, so both shrink equally — neither may
    govern a taller total. vconcat panes stack, and the rail's height is fixed
    chrome, so only the chart pane absorbs the overshoot; shrinking the rail
    would clip the series labels.

    A spec carrying an attached ``data_table`` strip opts out of the height pass
    by arriving without ``$df_target_height`` at all (dropped in
    ``vega_lite._apply_data_table_strip``): the strip's layers are pixel literals
    anchored to ``spec.height``, so resizing the pane here would detach them.
    Don't reinstate a height target for those specs — their fit is handled by a
    pre-shrunk re-render (``layout_sizing._correct_data_table_height``).

    ``endpoint_label_cascade`` (right_pane endpoint-label charts only — see
    ``vega_lite.py``'s ``$df_endpoint_label_cascade`` sentinel) re-cascades the
    label pane's positions against this same probe once it's in hand, so a
    chart carrying it pays for exactly one ``vegalite_to_scenegraph`` call
    regardless of which corrections fire.
    """
    if target_width is None and target_height is None:
        return
    is_hconcat = "hconcat" in spec and spec["hconcat"]
    is_vconcat = "vconcat" in spec and spec["vconcat"]
    if not is_hconcat and not is_vconcat:
        return
    try:
        probe = vlc.vegalite_to_scenegraph(spec)
    except Exception:  # noqa: BLE001, S110 — vl-convert throws untyped JS errors
        return
    if target_width is not None:
        overshoot = float(probe["width"]) - float(target_width)
        if overshoot > 0:
            width_panes = [spec["hconcat"][0]] if is_hconcat else list(spec["vconcat"])
            for pane in width_panes:
                orig_w = float(pane.get("width", target_width))
                new_w = orig_w - overshoot
                if new_w <= 0:
                    raise ChartDataError.from_code(
                        ERR_CONCAT_OVERSHOOT_NONPOSITIVE,
                        new_w=new_w,
                        orig_w=orig_w,
                        overshoot=overshoot,
                        target_width=target_width,
                    )
                pane["width"] = new_w
    if target_height is not None:
        overshoot = float(probe["height"]) - float(target_height)
        if overshoot > 0:
            # Stacked vconcat panes share the total, so only the chart pane
            # (index 1) gives up the overshoot — the rail above it is fixed.
            height_panes = list(spec["hconcat"]) if is_hconcat else [spec["vconcat"][1]]
            for pane in height_panes:
                orig_h = float(pane.get("height", target_height))
                new_h = orig_h - overshoot
                # Height overshoot is driven by Vega chrome (axes, legend) that
                # is outside author control — a zero/negative result is possible
                # for very tall chrome on a small canvas, and is a layout concern,
                # not a bug signal.  Width overshoot can be caused by title, subtitle,
                # axis tick labels, axis titles, or the fixed-width label pane itself —
                # anything that contributes to the scenegraph width; non-positive width
                # is always a bug signal.
                if new_h > 0:
                    pane["height"] = new_h
    if endpoint_label_cascade is not None and is_hconcat:
        # The label pane carries no axis/title chrome (see
        # recascade_endpoint_labels' docstring), so its plot rectangle scales
        # 1:1 with its declared height — the measured slope must be scaled by
        # the same ratio the height-correction pass above just applied to it.
        # vega_lite.py always stamps pane[1]'s pre-correction declared height
        # to exactly target_height in the same step it stamps
        # $df_target_height, so target_height IS that pre-correction value —
        # no separate snapshot needed. Exactly 1.0 — the identity, not an
        # estimate — when target_height is None: there was no declared
        # height to correct (height=None, "let Vega auto-size vertically"),
        # so nothing shrank and the probe's own slope already matches the
        # real render.
        height_correction_ratio = 1.0
        if target_height is not None:
            # vega_lite.py stamps pane[1]["height"] in the same step it stamps
            # $df_target_height, so the key is always present here — direct
            # indexing, not a defaulted read, is the honest contract.
            pane1_height_after = float(spec["hconcat"][1]["height"])
            height_correction_ratio = pane1_height_after / target_height
        _recascade_endpoint_label_pane(
            spec,
            probe,
            endpoint_label_cascade,
            chart_id,
            height_correction_ratio,
        )


def render_svg_content(svg_content: str, format: str, *, scale: float = 1.0) -> str:
    """Convert SVG content to the requested encoded output."""
    if format == "svg":
        return svg_content
    if format == "png":
        return base64.b64encode(to_png(svg_content, scale=scale)).decode("utf-8")
    if format == "pdf":
        return base64.b64encode(to_pdf(svg_content)).decode("utf-8")
    raise ValueError(f"Unsupported SVG format: {format}")


def render_vega_spec(
    spec: dict[str, Any],
    format: str,
    resolved_style: ResolvedStyle,
    width: float | None,
    height: float | None,
    is_placeholder: bool,
    chart_id: str,
) -> str:
    """Render a Vega-Lite spec into SVG, PNG, or PDF."""
    try:
        import vl_convert as vlc
    except ImportError:
        raise FormatError(
            f"vl-convert-python is required for {format} rendering. "
            "Install with: pip install vl-convert-python",
        ) from None

    register_vl_convert_fonts(vlc)

    # Content-addressed memo. Keyed before the ``$df_*`` pops below, which mutate
    # ``spec`` in place and shape the output. A hit skips the overshoot probe
    # render as well as the real one — the probe is inside this function, so
    # memoizing at this level is what makes both free.
    cache = active_svg_cache()
    cache_key: str | None = None
    if cache is not None:
        cache_key = svg_cache_key(
            spec,
            output_format=format,
            width=width,
            height=height,
            is_placeholder=is_placeholder,
            resolved_style=resolved_style,
            # Read below by _fix_chart_click_hrefs, which bakes this host's
            # board-root prefix into the markup — so it is content, not context.
            link_context=get_link_context(),
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    # Two-pass width/height correction for hconcat endpoint-label specs.
    # vl-convert ignores autosize:fit on concat children, so the first render
    # measures the actual outer dimensions; the overshoots are subtracted from
    # the resizable pane(s) before the real render. All three sentinels are
    # stamped in vega_lite.py's _render_vl_artifact and must be popped before
    # rendering. $df_title_style carries the chart's own resolved title style
    # (chart-local overflow mode / font-size fallback) as a plain dict — see
    # the sentinel's JSON-safety note in vega_lite.py's _render_vl_artifact —
    # so this deferred wrap reads the same source as the non-hconcat path,
    # instead of re-deriving it from the board-level resolved_style.chart_defaults.title.
    target_width = spec.pop("$df_target_width", None)
    target_height = spec.pop("$df_target_height", None)
    endpoint_label_cascade = spec.pop("$df_endpoint_label_cascade", None)
    title_style_dict = spec.pop("$df_title_style", None)
    title_style = (
        TitleStyle.model_validate(title_style_dict)
        if title_style_dict is not None
        else None
    )
    if target_width is not None or target_height is not None:
        # Bound title/subtitle BEFORE the overshoot probe. Without this, an
        # unbounded subtitle reports its full natural width into the
        # scenegraph, driving a huge overshoot that can produce new_w <= 0
        # (raising ChartDataError). Wrapping now against pane[0]'s current
        # (pre-correction, usually wider) width only needs to bound the probe
        # — the raw strings are saved so the post-correction pass below can
        # re-wrap from source at the real, corrected limit instead of
        # re-truncating this pass's (too-wide) wrapped lines.
        title_block = (
            spec["hconcat"][0].get("title")
            if "hconcat" in spec and spec["hconcat"]
            else None
        )
        original_text = (
            title_block.get("text") if isinstance(title_block, dict) else None
        )
        original_subtitle = (
            title_block.get("subtitle") if isinstance(title_block, dict) else None
        )
        if "hconcat" in spec and spec["hconcat"]:
            apply_title_overflow_to_spec(spec["hconcat"][0], title_style)
        _correct_concat_overshoot(
            spec, target_width, target_height, vlc, endpoint_label_cascade, chart_id
        )
        if isinstance(title_block, dict):
            # Restore the raw strings so this pass re-wraps from source at the
            # corrected limit, rather than reusing the pre-correction wrap
            # (which Vega would then re-truncate a second time, cutting text
            # off far earlier than the wrap-two layout intended).
            if original_text is not None:
                title_block["text"] = original_text
            if original_subtitle is not None:
                title_block["subtitle"] = original_subtitle
            # pane[0]["width"] after correction is the *data-plot* width only
            # — vl-convert ignores autosize:fit on concat children, so the
            # y-axis tick-label gutter renders outside "width". Title/subtitle
            # span pane[0]'s whole visual footprint (gutter + plot), so use
            # target_width minus the fixed label pane and spacing instead of
            # the shrunk plot width, or the title wraps far earlier than the
            # chart actually has room for. Root padding comes off too: it is
            # outside that footprint, and a title allowed to run into it
            # governs the concat's width and pushes the whole chart past the
            # box it declared.
            hconcat_panes = spec["hconcat"]
            available_width = None
            if target_width is not None and len(hconcat_panes) > 1:
                pane1_width_raw = hconcat_panes[1].get("width")
                pane1_width = (
                    pane1_width_raw
                    if isinstance(pane1_width_raw, (int, float))
                    else 0.0
                )
                spacing_raw = spec.get("spacing")
                spacing = spacing_raw if isinstance(spacing_raw, (int, float)) else 0.0
                available_width = (
                    target_width
                    - pane1_width
                    - spacing
                    - _padding_side(spec, "left")
                    - _padding_side(spec, "right")
                )
            apply_title_overflow_to_spec(
                spec["hconcat"][0],
                title_style,
                available_width=available_width,
            )

    try:
        svg_result = vlc.vegalite_to_svg(spec)
    except Exception as exc:
        # vl-convert JS errors (e.g. Vega scene-graph TypeErrors on unsupported
        # layered specs) escape as Python exceptions.  Re-raise as ChartDataError
        # so render_chart_item records a per-tile error card instead of aborting
        # the entire dashboard render process.
        raise ChartDataError(str(exc)) from exc
    svg_result = _fix_chart_click_hrefs(svg_result)
    svg_result = _stamp_chart_title_kind(svg_result)
    if _spec_has_encoding(spec, ["strokeDash"]):
        svg_result = _fix_legend_symbol_linecap(svg_result)

    padding_left = _padding_side(spec, "left")
    if padding_left > 0:
        svg_result = fix_title_alignment(svg_result, padding_left)

    if is_placeholder:
        from dbt_charts.core.compile.models.primitives import FontStyle
        from dbt_charts.core.render.placeholder import (
            add_placeholder_overlay,
            apply_placeholder_opacity,
        )

        chart_width = width or 400
        chart_height = height or resolved_style.chart_defaults.default_chart_height
        svg_result = apply_placeholder_opacity(
            svg_result, resolved_style=resolved_style
        )
        svg_result = add_placeholder_overlay(
            svg_result,
            chart_width,
            chart_height,
            font=FontStyle(family=resolved_style.font.family),
            resolved_style=resolved_style,
        )

    rendered = render_svg_content(svg_result, format, scale=1.0)
    if cache is not None and cache_key is not None:
        cache.put(cache_key, rendered, chart_id)
    return rendered


def render_chart_artifact(
    artifact: RenderArtifact,
    format: str,
    resolved_style: ResolvedStyle,
    width: float | None,
    height: float | None,
    chart_id: str,
    is_placeholder: bool = False,
) -> str:
    """Render a chart-domain artifact into the requested output format."""
    if artifact.kind == "json":
        if format != "json":
            raise ValueError(f"JSON artifact cannot render as {format}")
        return json.dumps(artifact.payload, indent=2)

    if artifact.kind == "svg":
        return render_svg_content(str(artifact.payload), format)

    if artifact.kind == "vega_spec":
        if not isinstance(artifact.payload, dict):
            raise ValueError("Vega spec artifact payload must be a dictionary")
        return render_vega_spec(
            artifact.payload,
            format,
            resolved_style=resolved_style,
            width=width,
            height=height,
            is_placeholder=is_placeholder,
            chart_id=chart_id,
        )

    raise ValueError(f"Unsupported artifact kind: {artifact.kind}")
