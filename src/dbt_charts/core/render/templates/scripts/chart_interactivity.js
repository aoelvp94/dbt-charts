(function () {
    const DCT_FONT_FAMILY = "__DCT_FONT_FAMILY__";
    const DCT_TOOLTIP_STYLE = "__DCT_TOOLTIP_STYLE__";

    /*{# Role markers baked by emitters/_tooltip.py's ROLE_HEADER / ROLE_HEADER_SWATCHED / #}*/
    /*{# ROLE_SERIES / ROLE_TOTAL / ROLE_ORDER -- zero-width Unicode format characters, #}*/
    /*{# invisible on screen and not vocalized by screen readers, but valid XML/SVG #}*/
    /*{# attribute content (unlike C0 control chars). Keep these five codepoints in #}*/
    /*{# sync with that module. #}*/
    const ROLE_HEADER = '⁡';
    const ROLE_HEADER_SWATCHED = '⁤';
    const ROLE_SERIES = '⁢';
    const ROLE_TOTAL = '⁣';
    /*{# A precomputed display-order rank for this mark's series, baked once at #}*/
    /*{# emission time from the SAME order that already drives scale.domain / #}*/
    /*{# legend.values (features/structured_tooltip.py) -- present whenever that #}*/
    /*{# order exists, regardless of whether a legend actually renders. Families #}*/
    /*{# with no reordered domain (grouped bar, a numeric/boolean color field) #}*/
    /*{# carry no ROLE_ORDER entry; collectMatchingMarks falls back to reading #}*/
    /*{# the rendered legend's DOM order for those, as before. #}*/
    const ROLE_ORDER = '‌';
    /*{# Emphasis modifier (emitters/_tooltip.py's MUTED), orthogonal to the role #}*/
    /*{# markers above: prefixes a value/total row whose VALUE should render at the #}*/
    /*{# low-contrast label colour, not the loud value colour -- a companion number #}*/
    /*{# beside a percent lead (pie's raw slice count + grand total). Composes with #}*/
    /*{# a role marker, so it's peeled ahead of the role marker below. #}*/
    const MUTED = '⁠';

    /*{# Internal structural dividers (header underline, footer-total rule) are a #}*/
    /*{# fixed hairline, decoupled from the box frame's border.width. The frame #}*/
    /*{# width is 0 on the shadowed themes (the shadow separates the card) but the #}*/
    /*{# header/total lines must persist regardless -- they organise the content, #}*/
    /*{# they aren't the outer edge. Colour still comes from the theme (border.color). #}*/
    const DIVIDER_WIDTH = 1;
    // Vertical gap that detaches the overlay reference row (combo target/
    // goal) from the parts+total group in the x-unified bubble (xUnifiedHtml).
    const OVERLAY_DETACH_GAP = 8;

    /*{# Vega's mark-group class. A data mark is always INSIDE one; axes #}*/
    /*{# (role-axis), legends (role-legend), the chart <g>, and the board-root #}*/
    /*{# <svg> never are. #}*/
    const MARK_GROUP_SELECTOR = '.role-mark';

    /*{# Containment decides datum-hood; the label's text never does. The label #}*/
    /*{# shape only decides whether there is anything to SHOW: a role marker, or #}*/
    /*{# a bare "key: value" -- the latter is load-bearing for geo families, #}*/
    /*{# which carry Vega's auto-generated label and no role marker. #}*/
    /*{# Cheap test first: every [aria-label] in the chart runs through here on #}*/
    /*{# each hover transition, so short-circuit on the label before paying for #}*/
    /*{# the ancestor walk. #}*/
    function isDataMark(element) {
        if (!element || typeof element.getAttribute !== 'function') return false;
        const label = element.getAttribute('aria-label');
        if (!label) return false;
        const showable = label.indexOf(ROLE_HEADER) !== -1 || label.indexOf(ROLE_SERIES) !== -1 ||
            label.indexOf(ROLE_HEADER_SWATCHED) !== -1 || label.indexOf(ROLE_TOTAL) !== -1 ||
            label.includes(':');
        return showable && element.closest(MARK_GROUP_SELECTOR) !== null;
    }

    function coerceNumeric(value) {
        const numValue = parseFloat(value);
        return !isNaN(numValue) && value === String(numValue) ? numValue : value;
    }

    /*{# Returns an ORDERED list of {role, label?, value} entries -- order matters #}*/
    /*{# (header -> series -> dependent values -> footer total), so a plain object #}*/
    /*{# (used pre-hierarchy, when every row rendered identically) can't carry it. #}*/
    function parseAriaLabel(label) {
        if (!label) return [];

        const entries = [];
        const pairs = label.split(';');

        for (const raw of pairs) {
            let pair = raw.trim();
            if (!pair) continue;

            /*{# Peel the emphasis modifier ahead of the role marker it composes #}*/
            /*{# with -- only value/total rows carry it (header/series never do). #}*/
            let muted = false;
            if (pair.charAt(0) === MUTED) { muted = true; pair = pair.slice(1); }

            const marker = pair.charAt(0);
            if (marker === ROLE_HEADER || marker === ROLE_HEADER_SWATCHED) {
                entries.push({
                    role: 'header',
                    swatch: marker === ROLE_HEADER_SWATCHED,
                    value: coerceNumeric(pair.slice(1)),
                });
                continue;
            }
            if (marker === ROLE_SERIES) {
                entries.push({ role: 'series', value: coerceNumeric(pair.slice(1)) });
                continue;
            }
            if (marker === ROLE_ORDER) {
                entries.push({ role: 'order', value: coerceNumeric(pair.slice(1)) });
                continue;
            }

            const isTotal = marker === ROLE_TOTAL;
            const rest = isTotal ? pair.slice(1) : pair;
            const colonIndex = rest.indexOf(':');
            if (colonIndex === -1) continue;

            const key = rest.substring(0, colonIndex).trim();
            const value = rest.substring(colonIndex + 1).trim();
            if (!key) continue;

            entries.push({ role: isTotal ? 'total' : 'value', label: key, value: coerceNumeric(value), muted: muted });
        }

        return entries;
    }

    /*{# Row cap for the x-unified bubble (grouped bar / stacked bar / aligned #}*/
    /*{# multi-series line): shows at most MAX_XUNIFIED_ROWS - 1 individual rows #}*/
    /*{# plus one "+N more" remainder row (MAX_XUNIFIED_ROWS lines total). #}*/
    const MAX_XUNIFIED_ROWS = 8;
    /*{# Past this many exact-identity matches the bubble would be unreadably #}*/
    /*{# tall -- fall back to the single-mark tooltip instead of expanding. #}*/
    /*{# Mirrors the theme's default legend.symbol_limit (defaults/themes/_base.yaml) #}*/
    /*{# as the same "this many distinct series stops being legible" cutoff. #}*/
    const XUNIFIED_ABANDON_THRESHOLD = 20;

    function markHeaderEntry(entries) {
        for (let i = 0; i < entries.length; i++) {
            if (entries[i].role === 'header') return entries[i];
        }
        return null;
    }

    /*{# ALL header-role entries, in aria-label order. Every family but heatmap #}*/
    /*{# carries exactly one (x, or the colour dim); heatmap's compound [x, y] #}*/
    /*{# identity carries two -- both must contribute to the match key below, or #}*/
    /*{# grouping-by-header would collapse every heatmap cell sharing just the x #}*/
    /*{# value into one (wrong) bubble. #}*/
    function headerEntries(entries) {
        return entries.filter(function (e) { return e.role === 'header'; });
    }

    /*{# The identity to group marks by -- joins every header entry's value. #}*/
    /*{# Degenerates to a single value for every family but heatmap, so this is #}*/
    /*{# not a behavior change for the single-header case. #}*/
    function headerKey(entries) {
        return headerEntries(entries).map(function (e) { return String(e.value); }).join('|');
    }

    function markSeriesEntry(entries) {
        for (let i = 0; i < entries.length; i++) {
            if (entries[i].role === 'series') return entries[i];
        }
        return null;
    }

    function markOrderEntry(entries) {
        for (let i = 0; i < entries.length; i++) {
            if (entries[i].role === 'order') return entries[i];
        }
        return null;
    }

    function findTotalEntry(matches) {
        for (let i = 0; i < matches.length; i++) {
            const total = matches[i].entries.find(function (e) { return e.role === 'total'; });
            if (total) return total;
        }
        return null;
    }

    /*{# The chart's canonical series order, read from the color legend's labels #}*/
    /*{# in DOM order (VL renders them in the color-scale domain order). Returns a #}*/
    /*{# {seriesValue: index} map, or an empty map when there's no legend (e.g. #}*/
    /*{# endpoint-labelled lines) -- in which case matches keep their natural order. #}*/
    function legendSeriesOrder(svg) {
        const order = {};
        let i = 0;
        svg.querySelectorAll('.role-legend-label').forEach(function (el) {
            const name = (el.textContent || '').trim();
            if (name && !(name in order)) { order[name] = i++; }
        });
        return order;
    }

    /*{# Groups every data mark in the chart whose IDENTITY (header value) #}*/
    /*{# EXACTLY matches the hovered mark's -- string equality only, no #}*/
    /*{# nearest-point tracking. A mark with no header (rare, deferred families) #}*/
    /*{# or a mismatched x never groups; the caller's single-mark path covers it. #}*/

    /*{# Dedup key is (header, series), not the raw aria-label text: a line's #}*/
    /*{# halo/fg/invisible-hover-target sub-layers all read the same datum and #}*/
    /*{# would otherwise triple-count one series as three rows. #}*/

    /*{# Rows are then ordered to match the chart's canonical series order, never #}*/
    /*{# the marks' DOM/stacking order -- so the tooltip reads top-to-bottom in #}*/
    /*{# that order. The per-mark baked rank (ROLE_ORDER) wins when present -- #}*/
    /*{# it's set directly from the same order authority regardless of whether a #}*/
    /*{# legend actually renders (a line with endpoint labels instead of a #}*/
    /*{# legend has no `.role-legend-label` DOM to read). Falls back to the #}*/
    /*{# rendered legend's DOM order otherwise. Series with neither sort last, #}*/
    /*{# stably. #}*/
    function collectMatchingMarks(svg, hoveredMark, hoveredEntries) {
        if (!markHeaderEntry(hoveredEntries)) return [{ mark: hoveredMark, entries: hoveredEntries }];
        const identity = headerKey(hoveredEntries);

        /*{# Scope grouping to the hovered mark's OWN chart. The interactivity #}*/
        /*{# script is bound once at the board-root <svg>, but each chart is a #}*/
        /*{# nested standalone <svg>; querying the whole board would collect #}*/
        /*{# same-identity marks from OTHER charts (e.g. two `x: month` charts) and #}*/
        /*{# contaminate the bubble with foreign rows / wrong values. Mirrors the #}*/
        /*{# .dbt-chart scoping nearestDataMark already uses. #}*/
        const scope = hoveredMark.closest('.dbt-chart') || svg;

        const seen = {};
        const matches = [];
        scope.querySelectorAll('[aria-label]').forEach(function (candidate) {
            if (!isDataMark(candidate)) return;
            const entries = parseAriaLabel(candidate.getAttribute('aria-label'));
            if (!markHeaderEntry(entries) || headerKey(entries) !== identity) return;

            const series = markSeriesEntry(entries);
            const key = identity + '|' + (series ? String(series.value) : '');
            if (seen[key]) return;
            seen[key] = true;
            matches.push({ mark: candidate, entries: entries });
        });

        const order = legendSeriesOrder(scope);
        const hasLegendOrder = Object.keys(order).length > 0;
        const hasBakedOrder = matches.some(function (m) { return markOrderEntry(m.entries); });
        if (hasLegendOrder || hasBakedOrder) {
            matches.forEach(function (m, idx) { m._i = idx; });
            matches.sort(function (a, b) {
                const oa = markOrderEntry(a.entries);
                const ob = markOrderEntry(b.entries);
                const sa = markSeriesEntry(a.entries);
                const sb = markSeriesEntry(b.entries);
                const ka = oa ? oa.value : (sa && String(sa.value) in order ? order[String(sa.value)] : Infinity);
                const kb = ob ? ob.value : (sb && String(sb.value) in order ? order[String(sb.value)] : Infinity);
                return ka !== kb ? ka - kb : a._i - b._i;
            });
        }
        return matches;
    }

    /*{# Splits matches into the rows to render individually and the rows to #}*/
    /*{# fold into a "+N more" remainder -- always keeping the hovered mark's #}*/
    /*{# own row visible, even when it would otherwise fall past the cap. #}*/
    function buildRowPlan(matches, hoveredMark) {
        if (matches.length <= MAX_XUNIFIED_ROWS) {
            return { shown: matches, remainder: [] };
        }
        let hoveredIndex = -1;
        for (let i = 0; i < matches.length; i++) {
            if (matches[i].mark === hoveredMark) { hoveredIndex = i; break; }
        }
        const visibleCount = MAX_XUNIFIED_ROWS - 1;
        let shown = matches.slice(0, visibleCount);
        if (hoveredIndex >= visibleCount) {
            shown = shown.slice(0, visibleCount - 1).concat([matches[hoveredIndex]]);
        }
        const shownMarks = shown.map(function (m) { return m.mark; });
        const remainder = matches.filter(function (m) { return shownMarks.indexOf(m.mark) === -1; });
        return { shown: shown, remainder: remainder };
    }

    function nearestDataMark(chart, x, y) {
        let nearest = null;
        let nearestDistance = Infinity;

        chart.querySelectorAll('[aria-label]').forEach(function (mark) {
            if (!isDataMark(mark)) return;

            const rect = mark.getBoundingClientRect();
            const dx = Math.max(rect.left - x, 0, x - rect.right);
            const dy = Math.max(rect.top - y, 0, y - rect.bottom);
            const distance = dx * dx + dy * dy;
            if (distance < nearestDistance) {
                nearest = mark;
                nearestDistance = distance;
            }
        });

        return nearest;
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';

        const div = document.createElement('div');
        div.textContent = String(value);
        return div.innerHTML;
    }

    function formatFieldName(key) {
        return escapeHtml(key
            .replace(/_/g, ' ')
            .replace(/-/g, ' ')
            .replace(/\b\w/g, function (c) { return c.toUpperCase(); }));
    }

    function formatValue(value) {
        if (value === null || value === undefined) return "__DCT_NULL_DISPLAY__";
        if (typeof value === 'number') {
            return escapeHtml(value.toLocaleString(undefined, { maximumFractionDigits: 2 }));
        }
        return escapeHtml(value);
    }

    function ensureState() {
        if (window.__dbtChartsChartHoverState) {
            return window.__dbtChartsChartHoverState;
        }

        const ts = DCT_TOOLTIP_STYLE;
        const tooltip = document.createElement('div');
        tooltip.className = 'dbt-tooltip';
        tooltip.setAttribute('role', 'tooltip');
        tooltip.style.position = 'fixed';
        tooltip.style.display = 'none';
        tooltip.style.background = ts.background;
        tooltip.style.padding = ts.padding.top + 'px ' + ts.padding.right + 'px ' + ts.padding.bottom + 'px ' + ts.padding.left + 'px';
        tooltip.style.borderRadius = ts.border.radius + 'px';
        tooltip.style.fontSize = ts.font.size + 'px';
        tooltip.style.lineHeight = String(ts.lineHeight);
        tooltip.style.pointerEvents = 'none';
        tooltip.style.zIndex = '10000';
        /*{# Size to content, capped at maxWidth. A fixed-position box is #}*/
        /*{# shrink-to-fit by default, but that only holds when it's laid out #}*/
        /*{# against the viewport; inside an embedding host's iframe the box can #}*/
        /*{# stretch toward maxWidth, ballooning the x-unified grid's 1fr name #}*/
        /*{# column and the hovered-row highlight with it. max-content pins the #}*/
        /*{# width to the content in every host, so the highlight stays tight. #}*/
        tooltip.style.width = 'max-content';
        tooltip.style.maxWidth = ts.maxWidth + 'px';
        tooltip.style.boxShadow = ts.shadow.visible ? '0 10px 25px rgba(15, 23, 42, 0.25)' : 'none';
        tooltip.style.backdropFilter = 'blur(4px)';
        tooltip.style.border = ts.border.width + 'px solid ' + ts.border.color;
        tooltip.style.fontFamily = DCT_FONT_FAMILY;
        if (document.body) {
            document.body.appendChild(tooltip);
        }

        window.__dbtChartsChartHoverState = {
            activeMark: null,
            tooltip: tooltip,
        };

        return window.__dbtChartsChartHoverState;
    }

    function positionTooltip(state, x, y) {
        const padding = 12;
        const rect = state.tooltip.getBoundingClientRect();
        let left = x + padding;
        let top = y + padding;

        if (left + rect.width > window.innerWidth - padding) {
            left = x - rect.width - padding;
        }

        if (top + rect.height > window.innerHeight - padding) {
            top = y - rect.height - padding;
        }

        state.tooltip.style.left = Math.max(padding, left) + 'px';
        state.tooltip.style.top = Math.max(padding, top) + 'px';
    }

    function hideTooltip(state) {
        state.activeMark = null;
        state.tooltip.style.display = 'none';
    }

    /*{# Marks paint the series color as fill (bar/pie/point) or stroke (line); #}*/
    /*{# 'none' is Vega's explicit "not painted" value, not a real color. #}*/
    function markSeriesColor(mark) {
        const fill = mark.getAttribute('fill');
        if (fill && fill !== 'none') return fill;
        const stroke = mark.getAttribute('stroke');
        return stroke && stroke !== 'none' ? stroke : null;
    }

    function seriesSwatch(color) {
        const sw = DCT_TOOLTIP_STYLE.swatch;
        return '<span style="display:inline-block;width:' + sw.size + 'px;height:' + sw.size +
            'px;border-radius:' + sw.radius + 'px;' +
            'background:' + color + ';margin-right:6px;flex-shrink:0;"></span>';
    }

    /*{# active_marker: 'triangle' -- an edge-flush directional indicator on the #}*/
    /*{# hovered x-unified row, the alternative to the 'fill' background tint #}*/
    /*{# (stark's utilitarian look vs. every other theme's soft tint). Absolute- #}*/
    /*{# positioned inside the row's own left-padding gutter -- the row's left #}*/
    /*{# edge already sits at x = padding.left from the tooltip box's border, so #}*/
    /*{# left:-padding.left lands the wedge flush on the border line, pointing #}*/
    /*{# inward. Row content never shifts: this is an overlay, not a layout change. #}*/
    function triangleMarker(ts) {
        return '<span style="position:absolute;left:-' + ts.padding.left + 'px;top:50%;' +
            'transform:translateY(-50%);width:0;height:0;' +
            'border-top:5px solid transparent;border-bottom:5px solid transparent;' +
            'border-left:6px solid ' + ts.value.font.color + ';"></span>';
    }

    /*{# header/series rows: bold identity headline, swatch+bare-value series row, #}*/
    /*{# field label dropped on both (the LUT's role marker already tells us which #}*/
    /*{# is which -- no title-text matching needed). Both set the themed value #}*/
    /*{# colour EXPLICITLY: without it the text inherits the page/iframe default #}*/
    /*{# (black), which vanishes on dark-box themes (stark, plain, editorial). #}*/
    function headerRow(entry, seriesColor, ts) {
        const swatch = entry.swatch && seriesColor ? seriesSwatch(seriesColor) : '';
        return '<div style="display:flex;align-items:center;font-weight:700;padding:2px 0 4px;color:' +
            ts.value.font.color + ';">' + swatch + formatValue(entry.value) + '</div>';
    }

    function seriesRow(entry, seriesColor, ts) {
        const swatch = seriesColor ? seriesSwatch(seriesColor) : '';
        return '<div style="display:flex;align-items:center;padding:2px 0;color:' +
            ts.value.font.color + ';">' + swatch + formatValue(entry.value) + '</div>';
    }

    /*{# dependent value row (today's label -> value shape); the footer total #}*/
    /*{# reuses it with a top border + heavier weight instead of a new layout. #}*/
    function valueRow(entry, ts, isTotal) {
        const rowStyle = isTotal
            ? 'display:flex;justify-content:space-between;gap:' + ts.gap + 'px;margin-top:4px;padding-top:4px;border-top:' + DIVIDER_WIDTH + 'px solid ' + ts.border.color + ';'
            : 'display:flex;justify-content:space-between;gap:' + ts.gap + 'px;padding:2px 0;';
        const labelWeight = isTotal ? ts.value.font.weight : ts.label.font.weight;
        /*{# Contrast is colour, not weight (matches the x-unified grid): a muted #}*/
        /*{# value drops to the low-contrast label colour; weight stays uniform so #}*/
        /*{# the total's border still reads as the footer emphasis. #}*/
        const valueColor = entry.muted ? ts.label.font.color : ts.value.font.color;
        return (
            '<div style="' + rowStyle + '">' +
                '<span style="color:' + ts.label.font.color + ';font-weight:' + labelWeight + ';">' + formatFieldName(entry.label) + '</span>' +
                '<span style="color:' + valueColor + ';font-weight:' + ts.value.font.weight + ';text-align:right;font-variant-numeric:tabular-nums lining-nums;">' + formatValue(entry.value) + '</span>' +
            '</div>'
        );
    }

    /*{# The single-mark tooltip -- today's rendering, unchanged. This is the #}*/
    /*{# degenerate case of x-unified grouping (exactly one match) and the #}*/
    /*{# fallback when grouping doesn't apply (no header, misaligned-x lines) or #}*/
    /*{# cardinality exceeds XUNIFIED_ABANDON_THRESHOLD. #}*/
    /*{# An 'order' entry carries no `label` -- it's sort metadata for the #}*/
    /*{# x-unified path (xUnifiedRow filters to role === 'value' and never sees #}*/
    /*{# it), not a row to render here. Skipping it explicitly, rather than #}*/
    /*{# falling through to valueRow(), avoids formatFieldName(undefined). #}*/
    function singleMarkHtml(entries, seriesColor, ts) {
        return entries.map(function (entry) {
            if (entry.role === 'header') return headerRow(entry, seriesColor, ts);
            if (entry.role === 'series') return seriesRow(entry, seriesColor, ts);
            if (entry.role === 'order') return '';
            return valueRow(entry, ts, entry.role === 'total');
        }).join('');
    }

    /*{# One cell inside the x-unified grid body. Rounding is applied ONLY to #}*/
    /*{# the first/last cell of a logical row: with the grid's column-gap:0, #}*/
    /*{# adjoining cells' backgrounds touch, so rounding just the two end #}*/
    /*{# corners makes a hovered row's per-cell tint read as ONE continuous #}*/
    /*{# span instead of a series of separate boxes with visible gaps. #}*/
    /*{# Spacing between columns comes from padding-right (never the gap), per #}*/
    /*{# the locked design -- the last cell in a row gets none. #}*/
    function xUnifiedCell(html, style, activeBg, isFirst, isLast) {
        let radius = '';
        if (isFirst) radius += 'border-top-left-radius:3px;border-bottom-left-radius:3px;';
        if (isLast) radius += 'border-top-right-radius:3px;border-bottom-right-radius:3px;';
        /*{# Outer cells carry horizontal breathing room so the hovered-row tint #}*/
        /*{# insets a little past the swatch and past the last value, rather than #}*/
        /*{# sitting flush against the content edges (the "too tight" regression). #}*/
        const paddingLeft = isFirst ? '6px' : '0';
        const paddingRight = isLast ? '6px' : '8px';
        return '<div style="padding:2px ' + paddingRight + ' 2px ' + paddingLeft + ';' + (activeBg || '') + radius + style + '">' + html + '</div>';
    }

    /*{# One row in the x-unified bubble: swatch, series name, percent (value/ #}*/
    /*{# foreground colour, only when the bubble's rows carry one), and raw #}*/
    /*{# value (label/dim colour, weight 500, no parens) -- each its own grid #}*/
    /*{# cell so percent and raw form true right-aligned columns regardless of #}*/
    /*{# digit count, instead of one drifting joined string. #}*/
    function xUnifiedRow(entries, seriesColor, isActive, ts, hasPercent) {
        const series = markSeriesEntry(entries);
        const values = entries.filter(function (e) { return e.role === 'value'; });
        const label = series ? formatValue(series.value) : (values[0] ? formatFieldName(values[0].label) : '');
        const swatch = seriesColor ? seriesSwatch(seriesColor) : '';

        /*{# active_marker='fill' (default): background-only tint on the row that #}*/
        /*{# triggered the hover -- no border/weight change, reads as a subtle tint, #}*/
        /*{# not a redraw. active_marker='triangle' (stark): an edge-flush wedge #}*/
        /*{# anchored to the row's first (swatch) cell instead -- see triangleMarker(). #}*/
        const useTriangle = ts.activeMarker === 'triangle';
        const activeBg = (isActive && !useTriangle) ? 'background:rgba(127,127,127,0.16);' : '';
        const marker = (isActive && useTriangle) ? triangleMarker(ts) : '';

        const swatchCell = xUnifiedCell(marker + swatch, 'position:relative;', activeBg, true, false);
        const nameCell = xUnifiedCell(label, 'color:' + ts.label.font.color + ';', activeBg, false, false);

        /*{# Weight is uniform across every numeric cell (matching the total row); #}*/
        /*{# lead-vs-companion contrast is carried by COLOUR, not weight. #}*/
        const valueWeight = 'font-weight:' + ts.value.font.weight + ';';

        let pctCell = '';
        let valueText;
        if (hasPercent) {
            pctCell = xUnifiedCell(
                formatValue(values[0].value),
                'text-align:right;color:' + ts.value.font.color + ';' + valueWeight + 'font-variant-numeric:tabular-nums lining-nums;',
                activeBg, false, false
            );
            valueText = values.length > 1 ? formatValue(values[values.length - 1].value) : '';
        } else {
            valueText = values[0] ? formatValue(values[0].value) : '';
        }
        /*{# Contrast rule: the lead value takes the high-contrast value colour; a #}*/
        /*{# value drops to the low-contrast label colour ONLY when it's the raw #}*/
        /*{# companion beside a percent (there the % is the lead). A sole value #}*/
        /*{# (no % column) IS its row's lead -> value colour, matching single-mark. #}*/
        const valueColor = hasPercent ? ts.label.font.color : ts.value.font.color;
        const valueCell = xUnifiedCell(
            valueText,
            'text-align:right;color:' + valueColor + ';' + valueWeight + 'font-variant-numeric:tabular-nums lining-nums;',
            activeBg, false, true
        );

        return swatchCell + nameCell + pctCell + valueCell;
    }

    /*{# "+N more" overflow row for the series folded out of view. It carries NO #}*/
    /*{# value: the hidden rows are never summed here. Summing them client-side #}*/
    /*{# would fabricate a total for mixed-unit/combo families the emit layer never #}*/
    /*{# gated a total for -- the same no-fabrication rule the footer total follows #}*/
    /*{# via findTotalEntry -- and would be lossy regardless, since each row's value #}*/
    /*{# is an already-formatted display string (grouping separators and all). #}*/
    /*{# When a real group total exists it is shown by the footer total row below. #}*/
    /*{# Fits the same grid as the data rows: name-column "+N more", value blank. #}*/
    function xUnifiedRemainderRow(remainder, ts, hasPercent) {
        const swatchCell = xUnifiedCell('', '', '', true, false);
        const nameCell = xUnifiedCell('+' + remainder.length + ' more', 'font-style:italic;color:' + ts.label.font.color + ';', '', false, false);
        const pctCell = hasPercent ? xUnifiedCell('', '', '', false, false) : '';
        const valueCell = xUnifiedCell('', '', '', false, true);
        return swatchCell + nameCell + pctCell + valueCell;
    }

    /*{# The shared identity header, spanning every grid column with a bottom #}*/
    /*{# border separating it from the rows below -- same header content as #}*/
    /*{# the single-mark path (headerRow, untouched), just wrapped to span. #}*/
    function xUnifiedHeaderCell(headerEntriesList, ts) {
        const inner = headerEntriesList.map(function (h) { return headerRow(h, null, ts); }).join('');
        return '<div style="grid-column:1/-1;border-bottom:' + DIVIDER_WIDTH + 'px solid ' + ts.border.color + ';padding-bottom:4px;margin-bottom:4px;">' + inner + '</div>';
    }

    /*{# Footer total: the label spans grid-column 1 through the percent #}*/
    /*{# column (or through name when there's no percent column), and the #}*/
    /*{# value cell sits in the value column -- both carry border-top, and with #}*/
    /*{# the grid's column-gap:0 the two segments read as ONE unbroken line. #}*/
    function xUnifiedTotalRow(entry, ts, hasPercent) {
        const borderTop = 'border-top:' + DIVIDER_WIDTH + 'px solid ' + ts.border.color + ';';
        const labelSpan = hasPercent ? '1 / span 3' : '1 / span 2';
        const label = (
            '<div style="grid-column:' + labelSpan + ';' + borderTop +
                'margin-top:4px;padding:4px 8px 0 0;color:' + ts.label.font.color + ';font-weight:' + ts.value.font.weight + ';">' +
                formatFieldName(entry.label) +
            '</div>'
        );
        /*{# The total tracks the weight of the numbers it sums: dim when a #}*/
        /*{# percent leads the bubble (the total is a raw sum, matching its dim raw #}*/
        /*{# rows -- normalized stack, and pie via its own muted marker), dark when #}*/
        /*{# there's no percent (the value is itself the lead -- absolute stack). #}*/
        const totalColor = hasPercent ? ts.label.font.color : ts.value.font.color;
        const value = (
            '<div style="' + borderTop + 'margin-top:4px;padding:4px 6px 0 0;text-align:right;color:' +
                totalColor + ';font-weight:' + ts.value.font.weight + ';font-variant-numeric:tabular-nums lining-nums;">' +
                formatValue(entry.value) +
            '</div>'
        );
        return label + value;
    }

    /*{# True when this row carries its own ROLE_TOTAL entry -- the shared #}*/
    /*{# group-total transform stamps one onto every commensurable base segment; #}*/
    /*{# a combo overlay reference never does (_layer_tooltip_description's "no #}*/
    /*{# total" contract in emitters/_overlay.py). Only meaningful as a base-part #}*/
    /*{# vs. overlay-reference split when the bubble actually HAS a total (see #}*/
    /*{# the caller below) -- a bubble with no total at all (a non-combo grouped #}*/
    /*{# bar/multi-series line, or a single-series combo base + target) carries #}*/
    /*{# no ROLE_TOTAL on any row, so this predicate can't distinguish base from #}*/
    /*{# overlay there; there's nothing to sandwich a footer between anyway. #}*/
    function carriesGroupTotal(match) {
        return match.entries.some(function (e) { return e.role === 'total'; });
    }

    /*{# The x-unified bubble: a zero-column-gap CSS grid (swatch/name/%/value), #}*/
    /*{# shared header spanning it once, then rows -- the footer total ONLY when #}*/
    /*{# a matched mark actually carries a ROLE_TOTAL entry (the emit layer #}*/
    /*{# already gates that to commensurable/additive families: normalized #}*/
    /*{# stacks, pie; this never computes a total itself for a family that has #}*/
    /*{# none). When a total exists, base-part rows (the ones carrying it) come #}*/
    /*{# first, then the "+N more" remainder, then the Total footer, then any #}*/
    /*{# combo overlay/reference rows (e.g. a target line) LAST -- the Total is #}*/
    /*{# the buildup the overlay is compared against, so it must land between #}*/
    /*{# the parts and the overlay, never after it. When there's no total at all #}*/
    /*{# (plain multi-series charts, or a combo whose base has none), every row #}*/
    /*{# renders together in its baked/legend order with the remainder last -- #}*/
    /*{# unchanged, prior behavior; the base/overlay split only matters when #}*/
    /*{# there's a footer to position between the two groups. #}*/
    /*{# The percent column is decided once per bubble (hasPercent) from #}*/
    /*{# whether any matched row carries 2 values ([%, raw], vs. 1 for a plain #}*/
    /*{# single value) and collapses to 3 columns when absent. #}*/
    function xUnifiedHtml(hoveredMark, hoveredEntries, matches, ts) {
        const plan = buildRowPlan(matches, hoveredMark);
        const hasPercent = matches.some(function (m) {
            return m.entries.filter(function (e) { return e.role === 'value'; }).length > 1;
        });
        const columns = hasPercent ? 'auto minmax(0,1fr) auto auto' : 'auto minmax(0,1fr) auto';
        const totalEntry = findTotalEntry(matches);
        function renderRow(m) {
            return xUnifiedRow(m.entries, markSeriesColor(m.mark), m.mark === hoveredMark, ts, hasPercent);
        }

        let html = '<div style="display:grid;grid-template-columns:' + columns + ';column-gap:0;align-items:center;">';
        html += xUnifiedHeaderCell(headerEntries(hoveredEntries), ts);
        if (totalEntry) {
            const baseShown = plan.shown.filter(carriesGroupTotal);
            const overlayShown = plan.shown.filter(function (m) { return !carriesGroupTotal(m); });
            html += baseShown.map(renderRow).join('');
            if (plan.remainder.length) {
                html += xUnifiedRemainderRow(plan.remainder, ts, hasPercent);
            }
            html += xUnifiedTotalRow(totalEntry, ts, hasPercent);
            // Detach the overlay reference row(s) (combo target/goal) from the
            // parts+total group: the sum line above the total already binds the
            // total to the parts it sums, so a target sitting flush below reads
            // as "grouped with the total". A full-width gap re-frames it as a
            // separate comparison against that total, not a member of the stack.
            if (overlayShown.length) {
                html += '<div style="grid-column:1/-1;height:' + OVERLAY_DETACH_GAP + 'px;"></div>';
            }
            html += overlayShown.map(renderRow).join('');
        } else {
            html += plan.shown.map(renderRow).join('');
            if (plan.remainder.length) {
                html += xUnifiedRemainderRow(plan.remainder, ts, hasPercent);
            }
        }
        html += '</div>';
        return html;
    }

    function showTooltip(state, mark, event, svg) {
        const entries = parseAriaLabel(mark.getAttribute('aria-label'));
        if (!entries.length) {
            hideTooltip(state);
            return;
        }

        const ts = DCT_TOOLTIP_STYLE;
        state.activeMark = mark;
        const matches = svg ? collectMatchingMarks(svg, mark, entries) : [{ mark: mark, entries: entries }];

        state.tooltip.innerHTML = (matches.length > 1 && matches.length <= XUNIFIED_ABANDON_THRESHOLD)
            ? xUnifiedHtml(mark, entries, matches, ts)
            : singleMarkHtml(entries, markSeriesColor(mark), ts);
        state.tooltip.style.display = 'block';
        positionTooltip(state, event.clientX, event.clientY);
    }

    function initializeSvg(svg) {
        if (!svg || svg.dataset.dbtHoverInitialized === 'true') {
            return;
        }

        svg.dataset.dbtHoverInitialized = 'true';
        const state = ensureState();

        svg.addEventListener('mousemove', function (event) {
            const target = event.target;
            const labelledTarget = target && target.closest
                ? event.target.closest('[aria-label]')
                : null;
            let mark = labelledTarget && isDataMark(labelledTarget)
                ? labelledTarget
                : null;

            /*{# Vega area paths are aria-hidden because one path represents every #}*/
            /*{# datum; their labelled point siblings carry the correct values. #}*/
            /*{# Layered marks can have the same visible-mark/labelled-sibling split. #}*/
            if (!mark && target && target.closest && target.closest(MARK_GROUP_SELECTOR)) {
                const chart = target.closest('.dbt-chart');
                if (chart) {
                    mark = nearestDataMark(chart, event.clientX, event.clientY);
                }
            }

            if (!mark || !svg.contains(mark)) {
                if (state.activeMark) {
                    hideTooltip(state);
                }
                return;
            }

            if (state.activeMark !== mark || state.tooltip.style.display === 'none') {
                showTooltip(state, mark, event, svg);
            } else {
                positionTooltip(state, event.clientX, event.clientY);
            }
        });

        svg.addEventListener('mouseleave', function () {
            hideTooltip(state);
        });
    }

    function initialize() {
        const script = document.currentScript;
        const ownerSvg = script && script.closest ? script.closest('svg') : null;

        if (ownerSvg) {
            initializeSvg(ownerSvg);
            return;
        }

        document.querySelectorAll('svg').forEach(initializeSvg);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
})();
