# compile/resolve/chart

Family resolvers (`bar.py`, `line.py`, `area.py`, `scatter.py`, `heatmap.py`, plus
`pie.py`/`geo.py`/`simple.py`/`_table.py` for non-cartesian families) turn a
normalized `Chart` into a `Resolved*Chart`. Read `../../AGENTS.md` (compile) and
`../../../AGENTS.md` (core) first; this file covers the cartesian-family
composition invariant.

## Implementation philosophy

Exceeds the default budget: five distinct invariants below (composition, the
family/shared boundary, no inheritance, the axis-cascade context, the zero-anchor
decision) each need a code-anchored citation to stay reviewer-checkable, per
`docs/contributing/implementation-philosophy-style.md`.

### Compose shared policy, never hand-roll it

A cartesian family resolver (bar, line, area, scatter, heatmap) answers a policy
question by calling the shared function that answers it, never by re-deriving the
answer locally. The failure mode this directory is shaped to prevent is a
**skipped** policy call: an absent line is invisible in review, unlike a wrong one.

Every cartesian family calls `plan_cartesian()` / `build_cartesian_axes()`
(`_plan.py`) for the frame and `cartesian_series_naming()` (`_axes.py`) for the
legend-vs-rail decision. A family with "not applicable" to say passes that as an
explicit argument (`scatter`/`heatmap` pass `_NO_RAIL_ENDPOINT_LABELS`; they never
skip the call). A hand-rolled `top_legend` ternary, or reading `primary.legend`
directly instead of `_author_hid_legend`, reintroduces the same invisible gap.

Every family also calls `build_chart_style_context(chart_style_context, normalized)`
itself to get its own `chart_local_style_context` (used for
family-specific style reads like `.bar`/`.line`/`.area` and for `_title_font()`/
`_cartesian_kwargs()`). `plan_cartesian()` takes no chart-local context: it only
ever needs the board-level `chart_style_context`.

`histogram` (`_resolve_histogram` in `bar.py`) is a named exception, not a silent
one: it calls `plan_cartesian()` / `build_cartesian_axes()` for its frame like
every other family, but passes `multiples=None, y=None` and never calls
`cartesian_series_naming()`: a histogram bins x and counts rows, so it authors no
per-row series and has no legend-vs-rail decision to make.
`test_cartesian_family_invariants.py` carries `histogram` in `_FAMILIES` with a
reasoned `pytest.mark.skip` on every invariant that call would otherwise satisfy,
rather than leaving it absent from the parametrization.

### Where the family/shared line sits

Frame and policy are shared: `plan_cartesian()` / `build_cartesian_axes()` run the
identical prelude/postlude (channels, axis cascade bake, both `ResolvedAxisStyle`
builds, tooltip format); `cartesian_series_naming()` owns the
legend/rail decision. Tick, zero and domain maths stay per-family: bar's stacked
totals, area's log-domain bake and line's multi-metric zero ladder are genuinely
different maths over the same axis, not the same maths written five times, and are
unified only by the `_CartesianTickResolution` NamedTuple every family returns, so
the shared postlude can consume any family's result the same way. Do not fold
tick/zero/domain maths into the shared prelude/postlude to chase more sharing: a
config flag hiding that divergence trades a visible skipped call for an invisible
default.

### No base class, no template method

The five families are five plain functions (`_resolve_bar`, `_resolve_line`, ...)
dispatched by a `match` in `_dispatch.py`, not subclasses of a common resolver
base. A shared step is a function call at the call site, so a reviewer reads one
file top to bottom and sees whether `_resolve_scatter` calls the same
`cartesian_series_naming()` that `_resolve_line` does, without chasing `super()` or
a hook method up an inheritance chain. No ABC or template method across the
families: it would trade that readability for a symbol-count win the repo doesn't
want.

### The axis-cascade context

`_bake_cartesian_axes()`, called once from `plan_cartesian()`, takes the
board-level `chart_style_context`, never a per-chart one. Chart-local axis patches
are `SkipInheritSlots` fields on `_CartesianChartStyle`, extracted separately as
`AxisOverrides` and re-applied at cascade layers 11-13; passing the chart-local
context into the bake would only double-apply the same patch at a lower priority.
`chart_local_style_context` is still the right input for `_cartesian_kwargs()` and
`_title_font()`: `resolve_title_font()` has no overrides side channel and reads
color/style/decoration/case/line_height straight off the context it is given, so
the board-level context there silently drops a chart-local `style.title.font.color`.

### The zero-anchor decision

Line, area and scatter each call `_bake_y_zero` (`_domain.py`) at resolve for every
numeric-y shape they support: line for `y_field_line` singular or `normalized.y` as
a list (`line.py:183-186`), area for `y_field_area` singular or `normalized.y` as a
list (`area.py:269-272`), scatter for its single quantitative y field
(`scatter.py:133-139`). `_bake_y_zero` bakes a definitive True/False from
`resolve_y_zero`'s heuristic onto `ay.scale.continuous.zero`; that heuristic
(`enrich._pick_scale`) lives in exactly one place, decided once at resolve. It is a
no-op when the heuristic abstains (returns `None`) or the axis is log-typed. Bar
never calls `_bake_y_zero`: VL bars extend to/from zero unconditionally. An authored
`style.axis_y.scale.continuous.zero` bool on a bar chart flows through the standard
axis cascade to `ay_merged.scale.continuous.zero` and is the sole override path.

Line and area additionally ride the render-time `BaselineFeature`
(`render/chart/features/baseline.py`), which draws a `datum: 0` rule for any
bar/line/area chart whose axis does not carry an explicit `scale.zero=False`
(`_insert_zero_rule`); that rule's datum pulls 0 into Vega-Lite's domain fit
independently of the resolve-time bake. Scatter is not in
`BaselineFeature.applies_to` (bar/line/area only), so scatter's resolve-time
`_bake_y_zero` call is the only mechanism setting its zero anchor.

Line's multi-metric path (`y:` a list) has one further, narrower bake beyond the
shared `_bake_y_zero` call: when `resolve_y_zero` abstains but the tick ladder was
computed assuming a zero-anchored domain (no authored domain, a real tick count),
`_bake_zero_flag` pins `scale.continuous.zero` explicitly to the same decision the
ladder assumed (`line.py:210-233`). This guards the pre-computed ladder against
Vega-Lite auto-fitting a different domain than the ladder was built for, a concern
distinct from whether `BaselineFeature`'s rule fires.

Before adding or removing a bake for a family, verify through the real pipeline
(resolved `tick_values` against the compiled Vega scale's `domain`) whether a
floor-pinning mechanism already exists. Symmetry across families is not itself a
goal: different marks legitimately reach the same rendered result by different
valid routes.

### Adding a family

A sixth cartesian family extends
`dbt-charts/tests/core/compile/resolve/test_cartesian_family_invariants.py`'s
parametrization for every invariant. An invariant that does not apply is an
explicit `pytest.param(..., marks=pytest.mark.skip(reason=...))` naming why, never
a parametrization the family is simply absent from.

### If you catch yourself thinking...

| Objection | Response |
|---|---|
| "scatter/heatmap have no rail, they can skip cartesian_series_naming()" | They still own half the decision (multiples, legend). Call it with rail-off arguments; don't skip the call. |
| "I'll just pass chart_style_context, overrides land later either way" | True today because layers 11-13 re-apply regardless; that's the reason to use the board-level context, not a reason either works. |
| "a small base class would remove the repetition" | The repetition is five function bodies calling the same helpers; a base class hides that call, which is what review needs to see. |
