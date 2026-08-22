/*{# The variable-control runtime. Ships with the host, never with the artifact.

   The server draws every control into the board SVG, so this script adds no
   markup: it binds behaviour to elements that are already there. That is what
   keeps interactive surfaces out of the board's scaled coordinate system — a
   `position: fixed` element inside a transformed ancestor inherits the
   transform, so anything laid *over* a board comes out at the board's scale.

   A committed value rewrites the URL and asks for a fresh render, so controls
   only work where a server can serve one — `dft serve`, Cloud, the Playground.
   Those hosts inject this script and the controls stylesheet into their page.

   This script handles:
   - Binding the drawn controls of each board on the page (mount)
   - Variable change events (updateVariable function)
   - URL parameter updates
   - Chart loading states
   - Parent frame communication (for playground/suite embedding)
   - Variable hover highlighting

   The two transient exceptions to "no markup" — a select's popover and the
   native input a text field lifts — are page-level, native-size, and torn down
   when they close, which is why they can be HTML at all.

   Note: Chart menus are handled by Suite's JavaScript (init.js), not here. #}*/
(function() {
    /*{# Document-level listeners bind once per page. Binding is separately
       idempotent (per-control data-dbt-bound), so a host re-running this script
       after a board swap binds the new controls without double-binding these. #}*/
    var _documentWired = window.__dfVariablesInitialized === true;
    window.__dfVariablesInitialized = true;

    function setVariableIfMissing(vars, name, value) {
        if (Object.prototype.hasOwnProperty.call(vars, name)) {
            return;
        }
        vars[name] = value;
    }

    function markDependentChartsLoading(name) {
        var charts = document.querySelectorAll('[data-var-' + name + ']');
        for (var i = 0; i < charts.length; i++) {
            var chart = charts[i];
            /*{# Add loading class #}*/
            var currentClass = chart.getAttribute('class') || '';
            if (currentClass.indexOf('loading') === -1) {
                chart.setAttribute('class', currentClass + (currentClass ? ' ' : '') + 'loading');
            }

            /*{# Add spinner if not already present #}*/
            if (!chart.querySelector('.dbt-chart-spinner')) {
                var spinner = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                spinner.setAttribute('class', 'dbt-chart-spinner');
                /*{# Get chart bounds for centering spinner #}*/
                var bbox = chart.getBBox ? chart.getBBox() : {width: 200, height: 200};
                var centerX = bbox.x + bbox.width / 2;
                var centerY = bbox.y + bbox.height / 2;

                var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circle.setAttribute('cx', centerX);
                circle.setAttribute('cy', centerY);
                circle.setAttribute('r', '14');
                circle.setAttribute('fill', 'none');
                circle.setAttribute('stroke', '#e0e0e0');
                circle.setAttribute('stroke-width', '3');
                circle.setAttribute('stroke-dasharray', '20 60');
                circle.setAttribute('stroke-dashoffset', '0');
                circle.style.animation = 'dbt-spin 0.8s linear infinite';

                spinner.appendChild(circle);
                chart.appendChild(spinner);
            }
        }

        return charts;
    }

    function scheduleLoadingCleanup(charts) {
        setTimeout(function() {
            for (var i = 0; i < charts.length; i++) {
                var chart = charts[i];
                var currentClass = chart.getAttribute('class') || '';
                chart.setAttribute('class', currentClass.replace(/\s*loading\s*/g, ' ').trim());
                var spinner = chart.querySelector('.dbt-chart-spinner');
                if (spinner) {
                    spinner.remove();
                }
            }
        }, 5000);
    }

    /*{# The drawn control publishes the committed value, and the render is the #}*/
    /*{# only thing that has written it — so between a commit and the re-render #}*/
    /*{# that answers it, the attribute still holds the OLD value. Any reader in #}*/
    /*{# that window (getAllVariableValues, below) sees the value the user just #}*/
    /*{# replaced. Write it back at the moment of commit so the published state #}*/
    /*{# and the committed state never disagree, and every reader stays a reader. #}*/
    function publishCommitted(name, value) {
        var el = document.querySelector(
            '[data-dbt-variable="' + (window.CSS && CSS.escape ? CSS.escape(name) : name) + '"]'
        );
        if (!el) return;   /*{# hidden variable: nothing drawn to update #}*/
        if (el.getAttribute('data-dbt-input') === 'checkbox') {
            el.setAttribute('data-dbt-checked', value ? 'true' : 'false');
        }
        /*{# Same emptiness test the URL branch uses, so a cleared control reads #}*/
        /*{# back as unset rather than as the string "false". #}*/
        var empty = value === '' || value === null || value === false;
        el.setAttribute('data-dbt-value', empty ? '' : String(value));
    }

    /*{# Update URL and reload (or notify parent) #}*/
    function updateVariable(name, value) {
        /*{# Mark dependent charts as loading (add loading class and spinner) #}*/
        var charts = markDependentChartsLoading(name);

        /*{# Restore after timeout (fallback if reload fails or is prevented) #}*/
        scheduleLoadingCleanup(charts);

        publishCommitted(name, value);

        /*{# Update URL #}*/
        var url = new URL(window.location);
        if (value === '' || value === null || value === false) {
            url.searchParams.delete(name);
        } else {
            url.searchParams.set(name, String(value));
        }

        /*{# Notify parent (suite/playground) or reload (standalone) #}*/
        /*{# Using '*' is safe here because: #}*/
        /*{# 1. Iframe content is generated by us (not user input) #}*/
        /*{# 2. Parent checks message.type before processing #}*/
        /*{# 3. Blob URLs have null origin, so specific origin targeting doesn't work #}*/
        if (window.parent !== window) {
            var vars = getAllVariableValues();
            /*{# publishCommitted has already written this variable's attribute, #}*/
            /*{# so a drawn control reports the new value. A variable with no #}*/
            /*{# drawn control (hidden: true) has nothing to read, and the #}*/
            /*{# pending commit is its only source. #}*/
            setVariableIfMissing(vars, name, value);
            window.parent.postMessage({
                type: 'dbt-variable-change',
                variables: vars
            }, '*');
        } else if (typeof window.__dfHandleVariableUpdate === 'function') {
            /*{# Suite registers this hook to re-render in place (no page reload). #}*/
            window.__dfHandleVariableUpdate(url);
        } else {
            /*{# Plain dft serve: full page reload. Save scroll so #}*/
            /*{# restoreScrollIfSaved can put it back after the new page renders. #}*/
            try {
                sessionStorage.setItem('__dfScrollY_' + window.location.pathname, String(window.scrollY));
            } catch (e) { /*{# sessionStorage may be unavailable #}*/ }
            window.location.href = url.toString();
        }
    }

    /*{# Exposed for the inline handlers the control templates carry #}*/
    /*{# (onchange="updateVariable(...)"). #}*/
    window.updateVariable = updateVariable;

    var _popoverInstances = [];

    /*{# A host swaps boards in and out; a popover built for a control that is #}*/
    /*{# no longer in the document would otherwise sit on document.body forever, #}*/
    /*{# and its instance would keep answering the outside-click and Esc #}*/
    /*{# handlers. Both go when the control does. #}*/
    function _dropDetachedPopovers() {
        _popoverInstances = _popoverInstances.filter(function(inst) {
            if (inst.trigger.isConnected) return true;
            if (inst.popover && inst.popover.parentNode) inst.popover.remove();
            return false;
        });
    }

    /*{# Same story for a lifted native input. Being page-level is the whole #}*/
    /*{# point — that is what keeps it out of the board's scaled coordinate #}*/
    /*{# system — but it also means removing the board does not remove it, so #}*/
    /*{# it would float over whatever the host swaps in next. Dismissing rather #}*/
    /*{# than removing matters: its own teardown must not read a commit out of #}*/
    /*{# a board swap and navigate the page on the way down. #}*/
    function _dropOrphanedOverlays() {
        document.querySelectorAll('.dbt-variable-overlay').forEach(function(overlay) {
            if (overlay.__dbtOwner && !overlay.__dbtOwner.isConnected) {
                overlay.__dbtDismiss();
            }
        });
    }

    /*{# The click that opens a popover no longer stops here — a host reads its #}*/
    /*{# own meaning off it, which is how Cloud selects the variable. But a host #}*/
    /*{# may also *answer* it synchronously with a click of its own: Cloud opens #}*/
    /*{# the Design panel by clicking the sidebar tab, and that click bubbles #}*/
    /*{# back to the document handler below with a target outside every popover. #}*/
    /*{# Dismissing on it would close the dropdown the user just opened, on the #}*/
    /*{# first click only. So a popover is not dismissible in the turn that #}*/
    /*{# opened it: a real click away is a second gesture, and a second gesture #}*/
    /*{# is always a later task. #}*/
    var _openingTurn = false;

    function _registerPopover(inst) {
        _popoverInstances.push(inst);
        inst.trigger.addEventListener('click', function() {
            _openingTurn = true;
            setTimeout(function() { _openingTurn = false; }, 0);
            _popoverInstances.forEach(function(other) {
                if (other !== inst) other.close();
            });
        });
    }

    /*{# An open popover is dismissible from outside itself, or it is a trap: it #}*/
    /*{# is page-level and fixed, so it sits over the board until its own trigger #}*/
    /*{# is found again — and a multiselect deliberately stays open through option #}*/
    /*{# clicks, so it has no self-closing path at all. These also complete the #}*/
    /*{# ARIA combobox contract the drawn controls advertise (role + aria-expanded). #}*/
    function _closeOpenPopovers(except) {
        _popoverInstances.forEach(function(inst) {
            if (inst !== except && inst.isOpen()) inst.close();
        });
    }

    if (!_documentWired) {
        document.addEventListener('click', function(event) {
            if (_openingTurn) return;
            var inside = _popoverInstances.filter(function(inst) {
                return inst.popover.contains(event.target)
                    || inst.trigger.contains(event.target);
            })[0];
            /*{# The trigger's own handler toggles it; closing it here too would #}*/
            /*{# reopen-and-close on a single click. #}*/
            _closeOpenPopovers(inside);
        });
        document.addEventListener('keydown', function(event) {
            if (event.key !== 'Escape') return;
            var open = _popoverInstances.filter(function(inst) { return inst.isOpen(); });
            if (!open.length) return;
            /*{# Focus goes back to the control that opened it — Esc in a combobox #}*/
            /*{# returns you where you were, it does not drop you at the page top. #}*/
            open.forEach(function(inst) { inst.close(); });
            if (open[0].trigger.focus) open[0].trigger.focus();
        });
    }

    /*{# ── Intercept clicks on SVG <a href="?..."> links ──────────────────────── #}*/
    /*{# Blob URL iframes can't navigate to query-string URLs, so we parse the #}*/
    /*{# params ourselves and send a single postMessage with the merged variable #}*/
    /*{# snapshot instead of navigating. #}*/
    if (!_documentWired) document.addEventListener('click', function(event) {
        var link = event.target.closest('a[href]');
        if (!link) return;
        if (!link.ownerSVGElement && link.namespaceURI !== 'http://www.w3.org/2000/svg') return;
        var href = link.getAttribute('href');
        if (!href || href.charAt(0) !== '?') return;
        var inIframe = window.parent !== window;
        var hasHook = typeof window.__dfHandleVariableUpdate === 'function';
        var params = new URLSearchParams(href.slice(1));
        if (!params.toString()) {
            if (inIframe || hasHook) event.preventDefault();
            return;
        }

        if (!inIframe && !hasHook) {
            /*{# Standalone dft serve: let the browser navigate, but save scroll #}*/
            /*{# first so restoreScrollIfSaved() can recover position after reload. #}*/
            try {
                sessionStorage.setItem('__dfScrollY_' + window.location.pathname, String(window.scrollY));
            } catch (e) { /*{# sessionStorage may be unavailable #}*/ }
            return; /*{# browser follows the link naturally #}*/
        }

        event.preventDefault();
        var vars = getAllVariableValues();
        var tabUrl = inIframe ? null : new URL(window.location);
        var chartsToCleanup = [];
        params.forEach(function(value, name) {
            var charts = markDependentChartsLoading(name);
            for (var i = 0; i < charts.length; i++) {
                chartsToCleanup.push(charts[i]);
            }
            vars[name] = value;
            if (tabUrl) { tabUrl.searchParams.set(name, value); }
        });
        scheduleLoadingCleanup(chartsToCleanup);
        if (inIframe) {
            window.parent.postMessage({
                type: 'dbt-variable-change',
                variables: vars
            }, '*');
        } else {
            window.__dfHandleVariableUpdate(tabUrl);
        }
    });

    /*{# Collect all variable values from form controls #}*/
    /*{# The board's committed variable state, read off the drawn controls. #}*/
    /*{# Each publishes `data-dbt-value` in the form the query path uses, so #}*/
    /*{# there is nothing to infer from a widget's DOM shape any more — which is #}*/
    /*{# what the per-class ladder this replaced was doing. #}*/
    function getAllVariableValues() {
        var allVars = {};
        document.querySelectorAll('[data-dbt-variable]').forEach(function(el) {
            var name = el.getAttribute('data-dbt-variable');
            var raw = el.getAttribute('data-dbt-value') || '';
            var input = el.getAttribute('data-dbt-input');
            if (input === 'checkbox') {
                allVars[name] = el.getAttribute('data-dbt-checked') === 'true';
            } else if (input === 'multiselect' || input === 'daterange') {
                /*{# List-valued: published as JSON so a member may contain any #}*/
                /*{# delimiter. A malformed value is empty, never a raw string #}*/
                /*{# the query path would filter on literally. #}*/
                try {
                    var parsed = JSON.parse(raw);
                    allVars[name] = Array.isArray(parsed) ? parsed : [];
                } catch (e) { allVars[name] = []; }
            } else if (input === 'number' || input === 'slider' || input === 'range') {
                allVars[name] = raw === '' ? null : parseFloat(raw);
            } else {
                allVars[name] = raw;
            }
        });
        return allVars;
    }

    /*{# Restore scroll position saved before a standalone page reload (dft serve). #}*/
    function restoreScrollIfSaved() {
        try {
            var key = '__dfScrollY_' + window.location.pathname;
            var saved = sessionStorage.getItem(key);
            if (saved !== null) {
                sessionStorage.removeItem(key);
                window.scrollTo(0, parseInt(saved, 10));
            }
        } catch (e) { /*{# sessionStorage may be unavailable #}*/ }
    }

    /*{# Hovering a control outlines the charts it filters. Re-anchored to the #}*/
    /*{# drawn control, which names its variable directly — the wrapper-then- #}*/
    /*{# inner-input lookup this replaced was reading the deleted layer's markup. #}*/
    function setupVariableHoverHighlighting(root) {
        var controls = root.querySelectorAll('[data-dbt-variable]');
        for (var i = 0; i < controls.length; i++) {
            var control = controls[i];
            var varName = control.getAttribute('data-dbt-variable');
            if (!varName) continue;

            control.addEventListener('mouseenter', function(vName) {
                return function() {
                    var charts = document.querySelectorAll('[data-var-' + vName + ']');
                    for (var j = 0; j < charts.length; j++) {
                        var chart = charts[j];

                        /*{# Use transparent overlay for highlighting (cleaner than offset rects) #}*/
                        var existingOverlay = chart.querySelector('.dbt-chart-highlight-overlay');
                        if (!existingOverlay) {
                            try {
                                /*{# Use allocated dimensions from data attributes (set by renderer) #}*/
                                var chartWidth = parseFloat(chart.getAttribute('data-chart-width')) || 0;
                                var chartHeight = parseFloat(chart.getAttribute('data-chart-height')) || 0;

                                /*{# Fallback to getBBox if data attributes not available #}*/
                                if (chartWidth === 0 || chartHeight === 0) {
                                    var bbox = chart.getBBox ? chart.getBBox() : null;
                                    if (bbox) {
                                        chartWidth = bbox.width;
                                        chartHeight = bbox.height;
                                    }
                                }

                                if (chartWidth > 0 && chartHeight > 0) {
                                    /*{# Create overlay rect that covers entire chart area #}*/
                                    var overlay = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                                    overlay.setAttribute('class', 'dbt-chart-highlight-overlay');
                                    overlay.setAttribute('x', '0');
                                    overlay.setAttribute('y', '0');
                                    overlay.setAttribute('width', chartWidth);
                                    overlay.setAttribute('height', chartHeight);
                                    overlay.setAttribute('rx', '4'); /*{# Slight rounding #}*/
                                    /*{# Insert at end so it's on top (but pointer-events: none allows interaction) #}*/
                                    chart.appendChild(overlay);
                                }
                            } catch (e) {
                                /*{# Dimension calculation may fail, ignore silently #}*/
                            }
                        }
                    }
                };
            }(varName));

            control.addEventListener('mouseleave', function(vName) {
                return function() {
                    var charts = document.querySelectorAll('[data-var-' + vName + ']');
                    for (var j = 0; j < charts.length; j++) {
                        var chart = charts[j];

                        /*{# Remove highlight overlay #}*/
                        var highlightOverlay = chart.querySelector('.dbt-chart-highlight-overlay');
                        if (highlightOverlay) {
                            highlightOverlay.remove();
                        }
                    }
                };
            }(varName));
        }
    }

    /*{# ── Popover placement ──────────────────────────────────────────────────── #}*/

    /*{# A popover is page-level and viewport-positioned while open: it must not #}*/
    /*{# sit inside the board, because a fixed element under a scaled ancestor #}*/
    /*{# inherits that scale and the menu would shrink with the board. #}*/
    function _floatPopover(popover) {
        popover.style.position = 'fixed';
    }

    /*{# Drop the inline position so the stylesheet governs the closed popover. #}*/
    function _unfloatPopover(popover) {
        popover.style.position = '';
        popover.style.top = '';
        popover.style.left = '';
    }

    /*{# Position from the trigger's viewport coords, flipping to a right-edge #}*/
    /*{# anchor when a left anchor would overflow. getBoundingClientRect() on an #}*/
    /*{# SVG element returns its on-screen box, so this works against a drawn #}*/
    /*{# control unchanged. #}*/
    function _positionPopoverFixed(trigger, popover) {
        var rect = trigger.getBoundingClientRect();
        popover.style.top = (rect.bottom + 6) + 'px';
        var popoverWidth = popover.getBoundingClientRect().width;
        var margin = 8;
        if (rect.left + popoverWidth > window.innerWidth - margin) {
            popover.style.left = Math.max(margin, rect.right - popoverWidth) + 'px';
        } else {
            popover.style.left = rect.left + 'px';
        }
    }

    /*{# A fixed popover does not follow its anchor, so an open one is re-placed #}*/
    /*{# on scroll and resize. #}*/
    function _repositionOpenPopovers() {
        _popoverInstances.forEach(function(inst) {
            if (inst.isOpen()) _positionPopoverFixed(inst.trigger, inst.popover);
        });
    }

    /*{# ── Binding ────────────────────────────────────────────────────────────── #}*/

    /*{# The server draws every control into the board SVG and publishes each #}*/
    /*{# one's identity, resolved widget, and box. Nothing here lays anything #}*/
    /*{# out: a board is a fixed-viewBox SVG the host stretches to fit, so any #}*/
    /*{# element positioned over it is measured in page pixels while the space #}*/
    /*{# reserved for it was measured in board units — the two move in opposite #}*/
    /*{# directions as the board scales. Binding behaviour to what is already #}*/
    /*{# drawn is what makes that whole class of bug unreachable. #}*/

    /*{# ARIA role per resolved widget. A drawn control is a <g>, which carries #}*/
    /*{# no semantics of its own — a screen reader gets whatever we declare and #}*/
    /*{# nothing more, so an unmapped widget is a control nobody can operate. #}*/
    var _ROLE_BY_INPUT = {
        select: 'combobox',
        multiselect: 'combobox',
        radio: 'combobox',
        checkbox: 'checkbox',
        date: 'button',
        datepicker: 'button',
        daterange: 'button',
        slider: 'slider',
        range: 'slider',
        text: 'textbox',
        input: 'textbox',
        textarea: 'textbox',
        number: 'spinbutton'
    };

    function _controlLabel(el) {
        var text = el.querySelector('text');
        return text ? text.textContent.replace(/:$/, '') : '';
    }

    /*{# Checkbox commits in place: no overlay, no popover, nothing to position. #}*/
    /*{# Build a select popover at page level from the options the render #}*/
    /*{# published. Page-level is the whole point: a popover inside the board #}*/
    /*{# would inherit the board's scale, and a fixed element under a scaled #}*/
    /*{# ancestor inherits that scale too — menus would shrink with the board. #}*/
    /*{# At rest we are in board coordinates; on interaction, viewport ones. #}*/
    function _buildSelectPopover(el, varName) {
        var raw = el.getAttribute('data-dbt-options');
        var canUnset = el.getAttribute('data-dbt-can-unset') === 'true';
        var values = [];
        if (raw) {
            try { values = JSON.parse(raw); } catch (e) { values = []; }
        }
        /*{# An empty option list is still openable when the control can be #}*/
        /*{# returned to unset — that row is the whole menu. #}*/
        if (!values.length && !canUnset) return null;

        var raw_current = el.getAttribute('data-dbt-value') || '';
        var selected;
        try {
            var parsed = JSON.parse(raw_current);
            selected = Array.isArray(parsed) ? parsed : [raw_current];
        } catch (e) { selected = [raw_current]; }
        var popover = document.createElement('div');
        /*{# Both classes: .dbt-popover is the card — display:none included — and #}*/
        /*{# .dbt-select-popover only modifies it. Setting the modifier alone #}*/
        /*{# leaves every select's options rendered, unstyled, on the page. #}*/
        popover.className = 'dbt-popover dbt-select-popover';
        popover.setAttribute('role', 'listbox');

        /*{# A no-default, non-required control offers its way back to unset. #}*/
        /*{# Without this row the user can filter and never unfilter, since a #}*/
        /*{# commit's delete-the-param branch is unreachable from the UI. #}*/
        if (canUnset) {
            var clear = document.createElement('div');
            clear.className = 'dbt-select-option dbt-select-unset';
            clear.setAttribute('role', 'option');
            /*{# Marked by attribute, not by the class: the class is the row's #}*/
            /*{# appearance and this is what it *is* — the way back to unset. #}*/
            clear.setAttribute('data-unset', 'true');
            clear.setAttribute('data-value', '');
            clear.setAttribute(
                'aria-selected', selected.join('') === '' ? 'true' : 'false'
            );
            /*{# No `|| 'All'` fallback: the server emits this attribute on #}*/
            /*{# every can_unset control, and can_unset is the only branch that #}*/
            /*{# builds this row. A default here would silently diverge from #}*/
            /*{# read_only_unset_label the day that label changes. #}*/
            clear.textContent = el.getAttribute('data-dbt-unset-label');
            popover.appendChild(clear);
        }

        values.forEach(function(value, i) {
            var opt = document.createElement('div');
            opt.className = 'dbt-select-option';
            opt.setAttribute('role', 'option');
            opt.setAttribute('data-value', value);
            opt.setAttribute(
                'aria-selected', selected.indexOf(value) !== -1 ? 'true' : 'false'
            );
            opt.id = 'dbt-opt-' + varName + '-' + i;
            opt.textContent = value;
            popover.appendChild(opt);
        });
        document.body.appendChild(popover);
        return popover;
    }

    /*{# Select / multiselect: open the page-level popover anchored off the #}*/
    /*{# drawn control's client rect. getBoundingClientRect() on an SVG element #}*/
    /*{# returns its on-screen box, so the existing positioning machinery works #}*/
    /*{# against SVG unchanged. #}*/
    function _bindSelect(el, name) {
        var popover = _buildSelectPopover(el, name);
        if (!popover) {
            /*{# Nothing to open — an option query that returned empty, and no #}*/
            /*{# unset row either. Withdraw the affordances rather than leave a #}*/
            /*{# tab stop announced as a combobox that does nothing. #}*/
            el.removeAttribute('tabindex');
            el.removeAttribute('role');
            return;
        }

        function isOpen() { return popover.classList.contains('dbt-popover-open'); }
        function open() {
            _floatPopover(popover);
            popover.classList.add('dbt-popover-open');
            _positionPopoverFixed(el, popover);
            el.setAttribute('aria-expanded', 'true');
        }
        function close() {
            popover.classList.remove('dbt-popover-open');
            _unfloatPopover(popover);
            el.setAttribute('aria-expanded', 'false');
        }
        el.setAttribute('aria-expanded', 'false');
        /*{# The click keeps bubbling: a host draws its own meaning on a board #}*/
        /*{# click — Cloud selects the authored element under it — and a control #}*/
        /*{# that swallows the event is the one thing on the board it cannot #}*/
        /*{# see. The outside-click handler below already spares the trigger it #}*/
        /*{# came from, so nothing here needs stopPropagation to stay open. #}*/
        el.addEventListener('click', function() {
            if (isOpen()) close(); else open();
        });
        el.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
        });
        /*{# A multiselect commits a list, so it toggles members and stays open; #}*/
        /*{# a select commits one value and closes. Binding both as "pick one" #}*/
        /*{# silently narrowed every multiselect to its first choice. #}*/
        var multi = el.getAttribute('data-dbt-input') === 'multiselect';
        popover.addEventListener('click', function(e) {
            var opt = e.target.closest('.dbt-select-option');
            if (!opt) return;
            if (!multi) {
                close();
                updateVariable(name, opt.getAttribute('data-value'));
                return;
            }
            /*{# The unset row is not a member to toggle — it is the way out. #}*/
            /*{# Toggling it lands on `chosen = []`, which commits the literal #}*/
            /*{# string "[]" into the URL; the next render narrows that to a #}*/
            /*{# one-member selection of "[]" and filters the board on it. #}*/
            /*{# Clearing means committing empty, so the param is deleted. #}*/
            if (opt.hasAttribute('data-unset')) {
                close();
                updateVariable(name, '');
                return;
            }
            var wasOn = opt.getAttribute('aria-selected') === 'true';
            opt.setAttribute('aria-selected', wasOn ? 'false' : 'true');
            var chosen = Array.prototype.slice
                .call(popover.querySelectorAll('[aria-selected="true"]'))
                .map(function(row) { return row.getAttribute('data-value'); })
                .filter(function(v) { return v !== ''; });
            /*{# A required control with no default has no legal empty state: #}*/
            /*{# committing one renders the next page with no board, and so no #}*/
            /*{# control to get back from. Refuse rather than strand the user. #}*/
            if (!chosen.length && el.getAttribute('data-dbt-can-unset') !== 'true') {
                opt.setAttribute('aria-selected', 'true');
                return;
            }
            updateVariable(name, JSON.stringify(chosen));
        });
        el.setAttribute('aria-multiselectable', multi ? 'true' : 'false');
        _registerPopover({trigger: el, popover: popover, isOpen: isOpen, close: close});
    }

    /*{# Text entry lifts to a native input rather than being drawn. A caret, #}*/
    /*{# selection, IME, and a mobile keyboard are not things to reimplement in #}*/
    /*{# SVG. The overlay is page-level and native-size — the same rule the #}*/
    /*{# menus follow — so it never inherits the board's scale, and it is #}*/
    /*{# transient, so nothing persistent is positioned against a scaled board. #}*/
    function _bindTextEntry(el, name, inputType) {
        function lift() {
            if (document.querySelector('.dbt-variable-overlay')) return;
            var field = el.querySelector('[data-dbt-field]');
            var fieldRect = (field || el).getBoundingClientRect();

            var input = document.createElement('input');
            input.className = 'dbt-variable-overlay';
            input.type = inputType === 'number' ? 'number'
                : (inputType === 'date' || inputType === 'datepicker') ? 'date' : 'text';
            input.value = el.getAttribute('data-dbt-value') || '';
            input.style.position = 'fixed';
            input.style.left = fieldRect.left + 'px';
            input.style.top = fieldRect.top + 'px';
            input.style.width = fieldRect.width + 'px';
            input.style.height = fieldRect.height + 'px';
            document.body.appendChild(input);
            input.focus();
            input.select();

            /*{# The popover's rule, for the control that has no popover. This #}*/
            /*{# click is still bubbling, and a host answers it synchronously — #}*/
            /*{# Cloud reveals the path in its code editor, which focuses the #}*/
            /*{# editor. That blurs this input, and a blur is how it commits and #}*/
            /*{# removes itself, so the field would vanish inside the click that #}*/
            /*{# opened it and a text variable would be untypable in Cloud. The #}*/
            /*{# user clicked the control: in this turn the caret is theirs. A #}*/
            /*{# real click away is a second gesture and still commits below. #}*/
            var liftTurn = true;
            setTimeout(function() { liftTurn = false; }, 0);

            var done = false;
            function commit(save) {
                if (done) return;
                done = true;
                var next = input.value;
                input.remove();
                el.focus();
                if (save && next !== (el.getAttribute('data-dbt-value') || '')) {
                    updateVariable(name, next);
                }
            }
            input.__dbtOwner = el;
            input.__dbtDismiss = function() { done = true; input.remove(); };
            input.addEventListener('blur', function() {
                if (!liftTurn || done) { commit(true); return; }
                /*{# The host's own focus call is mid-flight — it blurs this #}*/
                /*{# input on its way in, so focusing back from inside the blur #}*/
                /*{# loses the race and it lands there anyway. Take the caret in #}*/
                /*{# the next turn, once that call has finished. #}*/
                setTimeout(function() { if (!done) input.focus(); }, 0);
            });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); commit(true); }
                else if (e.key === 'Escape') { e.preventDefault(); commit(false); }
            });
        }
        el.addEventListener('click', lift);
        el.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); lift(); }
        });
    }

    /*{# Slider commits in SVG: the track is drawn, so the pointer maths happens #}*/
    /*{# in the board's own coordinates and nothing is overlaid at all. #}*/
    function _bindSlider(el, name) {
        var track = el.querySelector('[data-dbt-ornament="slider"]');
        if (!track) return;

        function bounds() {
            var min = parseFloat(el.getAttribute('data-dbt-min'));
            var max = parseFloat(el.getAttribute('data-dbt-max'));
            var step = parseFloat(el.getAttribute('data-dbt-step'));
            if (isNaN(min) || isNaN(max) || max <= min) return null;
            return {min: min, max: max, step: (isNaN(step) || step <= 0) ? 1 : step};
        }

        /*{# Trim the float noise a fractional step introduces, without #}*/
        /*{# inventing precision the step does not have. #}*/
        function tidy(value) { return parseFloat(value.toFixed(6)); }

        /*{# On the track, not the group: the label sits left of the track, so a #}*/
        /*{# click there maps to a negative fraction, clamps to 0, and silently #}*/
        /*{# re-filters the board to the slider's minimum. Only the track is a #}*/
        /*{# position the user meant to pick. Keys stay on the group, which is #}*/
        /*{# what holds focus. #}*/
        track.addEventListener('click', function(e) {
            var b = bounds();
            if (!b) return;
            var rect = track.getBoundingClientRect();
            if (!rect.width) return;
            var fraction = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
            var raw = b.min + Math.round((fraction * (b.max - b.min)) / b.step) * b.step;
            updateVariable(name, tidy(Math.min(Math.max(raw, b.min), b.max)));
        });

        el.addEventListener('keydown', function(e) {
            var b = bounds();
            var current = parseFloat(el.getAttribute('data-dbt-value'));
            if (!b || isNaN(current)) return;
            var next = null;
            if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = current + b.step;
            else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = current - b.step;
            else if (e.key === 'Home') next = b.min;
            else if (e.key === 'End') next = b.max;
            if (next === null) return;
            e.preventDefault();
            updateVariable(name, tidy(Math.min(Math.max(next, b.min), b.max)));
        });
    }

    /*{# ── Daterange preset + calendar machinery ──────────────────────────── #}*/

    /*{# 8 non-divider presets + 2 dividers = 10 entries total. #}*/
    var PRESETS = [
        { id: 'today',          label: 'Today' },
        { id: 'last_7_days',    label: 'Last 7 days' },
        { id: 'last_28_days',   label: 'Last 28 days' },
        { id: 'last_90_days',   label: 'Last 90 days' },
        { id: 'last_12_months', label: 'Last 12 months' },
        { id: 'divider' },
        { id: 'mtd',            label: 'Month to date' },
        { id: 'ytd',            label: 'Year to date' },
        { id: 'divider' },
        { id: 'custom',         label: 'Custom' },
    ];

    /*{# All date math relative to local midnight so tests stay deterministic. #}*/
    function resolvePreset(id) {
        var now = new Date();
        var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        var end = new Date(today);
        var start = new Date(today);
        switch (id) {
            case 'today':          break;
            case 'last_7_days':    start.setDate(end.getDate() - 6); break;
            case 'last_28_days':   start.setDate(end.getDate() - 27); break;
            case 'last_90_days':   start.setDate(end.getDate() - 89); break;
            /*{# Single constructor call avoids the two-step setFullYear+setDate #}*/
            /*{# rollover on Feb 29 in leap years. #}*/
            case 'last_12_months': start = new Date(end.getFullYear() - 1, end.getMonth(), end.getDate() + 1); break;
            case 'mtd':            start = new Date(end.getFullYear(), end.getMonth(), 1); break;
            case 'ytd':            start = new Date(end.getFullYear(), 0, 1); break;
            case 'custom':         return null;
            default:               return null;
        }
        return [start, end];
    }

    /*{# ISO YYYY-MM-DD from a Date (local time). #}*/
    function toISO(d) {
        var m = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        return d.getFullYear() + '-' + m + '-' + day;
    }

    var _ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

    /*{# Date from an ISO string (local midnight), null if malformed or rolled. #}*/
    function fromISO(s) {
        if (!_ISO_RE.test(s)) return null;
        var parts = s.split('-');
        var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        if (d.getFullYear() !== parseInt(parts[0], 10) ||
            d.getMonth()    !== parseInt(parts[1], 10) - 1 ||
            d.getDate()     !== parseInt(parts[2], 10)) return null;
        return d;
    }

    function buildRail(railEl, onPick) {
        railEl.innerHTML = '';
        PRESETS.forEach(function(p) {
            if (p.id === 'divider') {
                var div = document.createElement('div');
                div.className = 'dbt-preset-divider';
                railEl.appendChild(div);
            } else {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.textContent = p.label;
                btn.dataset.preset = p.id;
                btn.addEventListener('click', function() { onPick(p); });
                railEl.appendChild(btn);
            }
        });
    }

    function markRailActive(railEl, presetId) {
        railEl.querySelectorAll('button').forEach(function(b) {
            b.classList.toggle('dbt-preset-active', b.dataset.preset === presetId);
        });
    }

    /*{# Which preset id matches the current [start, end] pair, or 'custom', or #}*/
    /*{# null if the range is unset. #}*/
    function matchPreset(range) {
        if (!range[0] || !range[1]) return null;
        var s = toISO(range[0]), e = toISO(range[1]);
        for (var i = 0; i < PRESETS.length; i++) {
            var p = PRESETS[i];
            if (!p.id || p.id === 'divider' || p.id === 'custom') continue;
            var r = resolvePreset(p.id);
            if (r && toISO(r[0]) === s && toISO(r[1]) === e) return p.id;
        }
        return 'custom';
    }

    /*{# Build the daterange popover once at bind time and append to document.body. #}*/
    /*{# Follows _buildSelectPopover: page-level, never inside the board. #}*/
    /*{# Returns the popover element; the calendar state lives in the closure. #}*/
    function _bindDateRange(el, name) {
        var canUnset = el.getAttribute('data-dbt-can-unset') === 'true';

        var range     = [null, null];
        var hoverDate = null;
        var viewMonth = new Date();

        var popover = document.createElement('div');
        popover.className = 'dbt-popover dbt-daterange-popover';

        var rail = document.createElement('div');
        rail.className = 'dbt-preset-rail';
        popover.appendChild(rail);

        var calEl = document.createElement('div');
        calEl.className = 'dbt-calendar-area';
        popover.appendChild(calEl);

        document.body.appendChild(popover);

        function isOpen() { return popover.classList.contains('dbt-popover-open'); }
        function open() {
            /*{# Re-seed every open so a commit from elsewhere (publishCommitted #}*/
            /*{# writes back data-dbt-value) is reflected in the popover's state. #}*/
            var raw = el.getAttribute('data-dbt-value') || '';
            range = [null, null];
            try {
                var parsed = JSON.parse(raw);
                if (Array.isArray(parsed) && parsed.length === 2) {
                    var s = fromISO(String(parsed[0])), e = fromISO(String(parsed[1]));
                    if (s && e) {
                        range = [s, e];
                        viewMonth = new Date(e.getFullYear(), e.getMonth(), 1);
                    }
                }
            } catch (ex) {}
            rebuildCalendar();
            _floatPopover(popover);
            popover.classList.add('dbt-popover-open');
            _positionPopoverFixed(el, popover);
            el.setAttribute('aria-expanded', 'true');
        }
        function close() {
            popover.classList.remove('dbt-popover-open');
            _unfloatPopover(popover);
            el.setAttribute('aria-expanded', 'false');
        }
        el.setAttribute('aria-expanded', 'false');
        /*{# Bubbles, for the reason the select's trigger does. #}*/
        el.addEventListener('click', function() {
            if (isOpen()) close(); else open();
        });
        el.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
        });

        /*{# DOM rebuilds inside the popover (pickDay, month nav) replace cells, #}*/
        /*{# making the just-clicked node a detached orphan. Without stopPropagation #}*/
        /*{# the document outside-click handler sees the click land on a node whose #}*/
        /*{# trigger.contains(target) is false and closes the popover. #}*/
        popover.addEventListener('click', function(e) { e.stopPropagation(); });

        function rebuildCalendar() {
            var year      = viewMonth.getFullYear();
            var month     = viewMonth.getMonth();
            var firstDay  = new Date(year, month, 1);
            var startWeek = firstDay.getDay();
            var monthName = firstDay.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
            /*{# Per rebuild, not per bind: a popover opened after midnight in a #}*/
            /*{# long-lived tab must bold the actual today. #}*/
            var now   = new Date();
            var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

            calEl.innerHTML = '';

            var header = document.createElement('div');
            header.className = 'dbt-cal-header';

            var prevBtn = document.createElement('button');
            prevBtn.type = 'button';
            prevBtn.className = 'dbt-cal-nav';
            prevBtn.setAttribute('aria-label', 'Previous month');
            prevBtn.textContent = '‹';
            prevBtn.addEventListener('click', function() {
                viewMonth = new Date(year, month - 1, 1);
                rebuildCalendar();
            });

            var monthSpan = document.createElement('span');
            monthSpan.className = 'dbt-cal-month';
            monthSpan.textContent = monthName;

            var nextBtn = document.createElement('button');
            nextBtn.type = 'button';
            nextBtn.className = 'dbt-cal-nav';
            nextBtn.setAttribute('aria-label', 'Next month');
            nextBtn.textContent = '›';
            nextBtn.addEventListener('click', function() {
                viewMonth = new Date(year, month + 1, 1);
                rebuildCalendar();
            });

            header.appendChild(prevBtn);
            header.appendChild(monthSpan);
            header.appendChild(nextBtn);
            calEl.appendChild(header);

            var grid = document.createElement('div');
            grid.className = 'dbt-cal-grid';

            ['S','M','T','W','T','F','S'].forEach(function(d) {
                var dow = document.createElement('div');
                dow.className = 'dbt-cal-dow';
                dow.textContent = d;
                grid.appendChild(dow);
            });

            var cursor = new Date(year, month, 1 - startWeek);
            for (var i = 0; i < 42; i++) {
                var dt      = new Date(cursor);
                var isOther = dt.getMonth() !== month;
                var isToday = dt.getTime() === today.getTime();
                var cell    = document.createElement('button');
                cell.type      = 'button';
                cell.className = 'dbt-cal-cell';
                if (isOther) { cell.classList.add('dbt-other-month'); cell.tabIndex = -1; }
                if (isToday) cell.classList.add('dbt-today');
                cell.textContent = dt.getDate();
                cell.dataset.day = String(dt.getTime());
                cell.setAttribute('aria-label', dt.toLocaleDateString('en-US', {
                    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
                }));
                (function(cellEl, cellDate) {
                    cellEl.addEventListener('click', function() { pickDay(cellDate.getTime()); });
                    cellEl.addEventListener('mouseenter', function() {
                        if (range[0] && !range[1]) {
                            hoverDate = new Date(cellDate.getTime());
                            paintCalendarState();
                        }
                    });
                }(cell, dt));
                grid.appendChild(cell);
                cursor.setDate(cursor.getDate() + 1);
            }
            calEl.appendChild(grid);

            /*{# Lingering-popover pattern: auto-commit on second pick; Apply only #}*/
            /*{# closes. Clear is gated on canUnset — a required control must never #}*/
            /*{# offer a path to the empty state. #}*/
            var footer = document.createElement('div');
            footer.className = 'dbt-cal-footer';
            if (canUnset && (range[0] !== null || range[1] !== null)) {
                var clearAction = document.createElement('button');
                clearAction.type = 'button';
                clearAction.className = 'dbt-cal-action';
                clearAction.setAttribute('data-action', 'clear');
                clearAction.textContent = 'Clear';
                footer.appendChild(clearAction);
            }
            var applyAction = document.createElement('button');
            applyAction.type = 'button';
            applyAction.className = 'dbt-cal-action dbt-cal-action-primary';
            applyAction.setAttribute('data-action', 'apply');
            applyAction.textContent = 'Apply';
            footer.appendChild(applyAction);
            footer.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-action]');
                if (!btn) return;
                var action = btn.getAttribute('data-action');
                if (action === 'clear') {
                    range = [null, null];
                    hoverDate = null;
                    markRailActive(rail, null);
                    rebuildCalendar();
                    updateVariable(name, '');
                } else if (action === 'apply') {
                    close();
                }
            });
            calEl.appendChild(footer);

            paintCalendarState();
            markRailActive(rail, matchPreset(range));
        }

        function paintCalendarState() {
            var startTs    = range[0] && range[0].getTime();
            var endTs      = range[1] && range[1].getTime();
            var previewing = startTs && !endTs && hoverDate;
            var hoverTs    = previewing && hoverDate.getTime();
            var lo         = previewing ? Math.min(startTs, hoverTs) : null;
            var hi         = previewing ? Math.max(startTs, hoverTs) : null;

            calEl.querySelectorAll('.dbt-cal-cell').forEach(function(c) {
                var ts           = parseInt(c.dataset.day, 10);
                var isStart      = startTs && ts === startTs;
                var isEnd        = endTs   && ts === endTs;
                var inRange      = startTs && endTs && ts > startTs && ts < endTs;
                var inPreview    = previewing && ts > lo && ts < hi;
                var isPreviewEnd = previewing && ts === hoverTs && ts !== startTs;

                c.classList.toggle('dbt-selected',         Boolean(isStart || isEnd));
                c.classList.toggle('dbt-range-start',      Boolean(isStart));
                c.classList.toggle('dbt-range-end',        Boolean(isEnd));
                c.classList.toggle('dbt-in-range',         Boolean(inRange));
                c.classList.toggle('dbt-preview-in-range', Boolean(inPreview));
                c.classList.toggle('dbt-preview-end',      Boolean(isPreviewEnd));
            });
        }

        function pickDay(timestamp) {
            var dt = new Date(timestamp);
            if (dt.getMonth() !== viewMonth.getMonth()) {
                viewMonth = new Date(dt.getFullYear(), dt.getMonth(), 1);
            }
            if (!range[0] || range[1]) {
                /*{# First pick (or re-start after a completed pair). #}*/
                range = [dt, null];
            } else if (dt < range[0]) {
                /*{# Second pick before the first — normalise to [earlier, later]. #}*/
                range = [dt, range[0]];
            } else if (dt.getTime() === range[0].getTime()) {
                range = [dt, dt];
            } else {
                range = [range[0], dt];
            }
            hoverDate = null;
            if (range[0] && range[1]) {
                markRailActive(rail, matchPreset(range));
                updateVariable(name, JSON.stringify([toISO(range[0]), toISO(range[1])]));
            } else {
                markRailActive(rail, null);
            }
            rebuildCalendar();
        }

        buildRail(rail, function(p) {
            var r = resolvePreset(p.id);
            if (r) {
                range = r;
                viewMonth = new Date(r[1].getFullYear(), r[1].getMonth(), 1);
                markRailActive(rail, p.id);
                updateVariable(name, JSON.stringify([toISO(r[0]), toISO(r[1])]));
            } else {
                /*{# 'custom' — just highlight the rail entry and let the user pick. #}*/
                markRailActive(rail, p.id);
            }
            rebuildCalendar();
        });

        calEl.addEventListener('mouseleave', function() {
            if (hoverDate) { hoverDate = null; paintCalendarState(); }
        });

        _registerPopover({trigger: el, popover: popover, isOpen: isOpen, close: close});
    }

    function _bindCheckbox(el, name) {
        function toggle() {
            var checked = el.getAttribute('data-dbt-checked') === 'true';
            updateVariable(name, !checked);
        }
        el.addEventListener('click', toggle);
        el.addEventListener('keydown', function(e) {
            if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); }
        });
    }

    /*{# Give one drawn control its semantics and its handlers. Returns whether #}*/
    /*{# it was newly bound, so mount() can report real work. #}*/
    function bindControl(el) {
        if (el.hasAttribute('data-dbt-bound')) return false;
        var name = el.getAttribute('data-dbt-variable');
        if (!name) return false;
        var input = el.getAttribute('data-dbt-input') || '';

        el.setAttribute('data-dbt-bound', 'true');
        /*{# A control the author gated off gets its semantics but no handlers #}*/
        /*{# and no tab stop: announcing it operable when it is not is worse #}*/
        /*{# than leaving it out of the tab order. #}*/
        if (el.getAttribute('data-dbt-enabled') === 'false') {
            el.setAttribute('aria-disabled', 'true');
            el.setAttribute('role', _ROLE_BY_INPUT[input] || 'button');
            return true;
        }
        el.setAttribute('tabindex', '0');
        el.setAttribute('role', _ROLE_BY_INPUT[input] || 'button');
        if (input === 'checkbox') {
            el.setAttribute('aria-checked', el.getAttribute('data-dbt-checked') || 'false');
        }
        var label = _controlLabel(el);
        if (label) el.setAttribute('aria-label', label);

        if (input === 'checkbox') _bindCheckbox(el, name);
        else if (input === 'select' || input === 'multiselect' || input === 'radio') {
            _bindSelect(el, name);
        } else if (input === 'daterange') _bindDateRange(el, name);
        else if (input === 'slider' || input === 'range') _bindSlider(el, name);
        else if (input === 'text' || input === 'input' || input === 'textarea'
                 || input === 'number' || input === 'date' || input === 'datepicker') {
            _bindTextEntry(el, name, input);
        }

        return true;
    }

    /*{# Bind every drawn control under `root` (default: the document). #}*/
    /*{# Idempotent — a host re-binds after swapping in a freshly rendered board, #}*/
    /*{# and already-bound controls are skipped. Returns how many were newly #}*/
    /*{# bound, so a caller can tell a real mount from a no-op. #}*/
    function mount(root) {
        var scope = root || document;
        var bound = 0;
        _dropDetachedPopovers();
        _dropOrphanedOverlays();
        /*{# A host hands us the container it just swapped a board into, and that #}*/
        /*{# container often *is* the board — querySelectorAll never matches its #}*/
        /*{# own root, so Cloud bound nothing at all. #}*/
        var boards = Array.prototype.slice.call(
            scope.querySelectorAll('[data-dbt-board]')
        );
        if (scope.matches && scope.matches('[data-dbt-board]')) boards.unshift(scope);
        boards.forEach(function(board) {
            board.querySelectorAll('[data-dbt-variable]').forEach(function(el) {
                if (bindControl(el)) bound++;
            });
            /*{# The affordance switch: a stylesheet rule under this class #}*/
            /*{# outranks the render's stroke="none" presentation attribute. #}*/
            /*{# Stroke takes no part in SVG layout, so drawing the borders #}*/
            /*{# cannot move anything — which is why this is a class and not a #}*/
            /*{# re-render. #}*/
            /*{# Both gated on the class: bindControl skips bound controls, but #}*/
            /*{# the hover wiring had no such guard, so a re-mount over an #}*/
            /*{# unchanged board stacked a second listener pair on every control. #}*/
            if (board.querySelector('[data-dbt-variable]')
                && !board.classList.contains('dbt-interactive')) {
                board.classList.add('dbt-interactive');
                setupVariableHoverHighlighting(board);
            }
        });
        return bound;
    }

    /*{# No resize wiring: a scaled board moves its controls with it, because #}*/
    /*{# they are drawn in the same document. Only an open popover still tracks #}*/
    /*{# the viewport (_repositionOpenPopovers), since a fixed element does not #}*/
    /*{# follow its anchor on its own. #}*/

    if (!_documentWired) {
        window.addEventListener('scroll', _repositionOpenPopovers, true);
        window.addEventListener('resize', _repositionOpenPopovers);
    }

    /*{# Hosts call window.dbtControls.mount(container) after swapping in a board. #}*/
    window.dbtControls = { mount: mount };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            mount(document);
            restoreScrollIfSaved();
        });
    } else {
        mount(document);
        restoreScrollIfSaved();
    }
})();
