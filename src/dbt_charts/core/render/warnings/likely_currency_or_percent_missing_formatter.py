"""Detector: WARN_LIKELY_CURRENCY_OR_PERCENT_MISSING_FORMATTER — see its `doc`
in core/diagnostics/codes_render.py for what this fires on.

Detection rule (v1, name-match only):

  Currency signals — field name (lowercased) ends in:
    _usd, _dollars, _revenue, _amount, _price, _cost, _spend, _value,
    _gmv, _arr, _mrr
  or contains the substrings: revenue, dollars, usd.

  Percent signals — field name (lowercased) ends in:
    _pct, _percent, _percentage, _rate, _share
  or contains the substring: percent.

  Either set also matches a bare field name (no prefix) that reliably implies
  money/percent standalone — currency: usd, dollars, revenue, price, gmv, arr,
  mrr; percent: pct, percent, percentage, share. Generic nouns that only
  signal a kind when prefixed (value, amount, rate, cost, spend) are excluded
  from the bare set; only their `_`-prefixed suffix form still matches.

  Fire when a matching field's effective y-axis format does not suit its kind.
  Every format source (chart-root ``format:``, authored ``style.axis_y.labels.format``,
  whole-chart ``style.number_format``, the theme default) is baked into the single
  resolved ``style.axis_y.labels.format`` by the time this detector runs, so it reads
  that one value rather than trying to recover authored-vs-default intent. A
  percent format carries ``%``; a currency format carries ``$``; the generic SI
  default (``.3~s``) suits neither.
  - Cartesian charts: check the chart's ``style.axis_y.labels.format``.
  - Layered charts share one y-axis, so its format is checked once per layer;
    a warning is emitted per layer whose y field matches a signal and whose
    shared format is unfit.

  Skip: charts with no y-axis encoding (kpi, table, callout, text, markdown,
  pivot, pie/donut, map families) that do not carry a layer list.

Out of scope for v1: value-range secondary signal (median >100 for currency;
all values in [0,1] for percent). Add as a tightener if precision validation
surfaces false positives.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.chart.resolved import ResolvedChart
from dbt_charts.core.compile.models.chart.resolved._base import (
    _CartesianResolvedChartFields,
)
from dbt_charts.core.compile.models.chart.resolved._layer import LayeredResolvedChart
from dbt_charts.core.compile.models.chart.resolved.area import ResolvedAreaChart
from dbt_charts.core.compile.models.chart.resolved.bar import ResolvedBarChart
from dbt_charts.core.compile.models.chart.resolved.line import ResolvedLineChart
from dbt_charts.core.diagnostics import (
    WARN_LIKELY_CURRENCY_OR_PERCENT_MISSING_FORMATTER,
    Diagnostic,
)
from dbt_charts.core.render.warnings.base import WarningContext

# Cartesian chart types whose y-axis renders and may need a format. Layered
# charts are handled separately in `_y_axis_check` (they share one y-axis), so
# "layered" is intentionally not listed here.
_Y_AXIS_TYPES = frozenset(
    {
        "bar",
        "line",
        "area",
        "scatter",
        "heatmap",
    }
)

# Currency: name suffix signals (checked after lowercasing field name).
_CURRENCY_SUFFIXES: frozenset[str] = frozenset(
    {
        "_usd",
        "_dollars",
        "_revenue",
        "_amount",
        "_price",
        "_cost",
        "_spend",
        "_value",
        "_gmv",
        "_arr",
        "_mrr",
    }
)

# Currency: substring signals (field name must contain one of these).
_CURRENCY_SUBSTRINGS: frozenset[str] = frozenset({"revenue", "dollars", "usd"})

# Percent: name suffix signals.
_PERCENT_SUFFIXES: frozenset[str] = frozenset(
    {"_pct", "_percent", "_percentage", "_rate", "_share"}
)

# Percent: substring signals.
_PERCENT_SUBSTRINGS: frozenset[str] = frozenset({"percent"})

# Bare-name signals (curated, not derived — see module docstring).
_CURRENCY_BARE_NAMES: frozenset[str] = frozenset(
    {"usd", "dollars", "revenue", "price", "gmv", "arr", "mrr"}
)
_PERCENT_BARE_NAMES: frozenset[str] = frozenset(
    {"pct", "percent", "percentage", "share"}
)


def _classify(field_name: str) -> str | None:
    """Return 'currency', 'percent', or None for the given field name."""
    name = field_name.lower()
    for suffix in _CURRENCY_SUFFIXES:
        if name.endswith(suffix):
            return "currency"
    for sub in _CURRENCY_SUBSTRINGS:
        if sub in name:
            return "currency"
    if name in _CURRENCY_BARE_NAMES:
        return "currency"
    for suffix in _PERCENT_SUFFIXES:
        if name.endswith(suffix):
            return "percent"
    for sub in _PERCENT_SUBSTRINGS:
        if sub in name:
            return "percent"
    if name in _PERCENT_BARE_NAMES:
        return "percent"
    return None


def _format_suits_kind(fmt: str | None, kind: str) -> bool:
    """Whether a resolved d3 number-format string renders ``kind`` sanely.

    Every format source (chart-root ``format:``, authored ``style.axis_y.labels.format``,
    the theme default, and whole-chart ``style.number_format``) is baked into the
    single ``style.axis_y.labels.format`` by the resolved boundary, so authored-vs-default
    can't be read off the resolved chart — but the effective format can. The
    generic SI default (``.3~s``) suits neither kind: a 0–1 percent renders as
    milli-units and currency loses its symbol. A percent format carries ``%``; a
    currency format carries ``$``.
    """
    if not fmt:
        return False
    return "%" in fmt if kind == "percent" else "$" in fmt


def _warn(chart_id: str, field: str, kind: str, axis_format: str | None) -> Diagnostic:
    return Diagnostic.from_code(
        WARN_LIKELY_CURRENCY_OR_PERCENT_MISSING_FORMATTER,
        chart=chart_id,
        # `format` lives on `axis_y.labels`, not on `axis_y` — the bare
        # `axis_y.format` spelling is pre-0.4.0 and now emits a migration
        # warning. This is the spelling `fix_template` tells authors to set.
        # Usually an *absent* key (that is the complaint), so it leans on the
        # candidate walk to land on `axis_y`, then `style`, then the chart.
        path=f"charts.{chart_id}.style.axis_y.labels.format",
        field=field,
        message=WARN_LIKELY_CURRENCY_OR_PERCENT_MISSING_FORMATTER.message_template.format(
            chart_id=chart_id, field=field, kind=kind, format=axis_format
        ),
        fix=WARN_LIKELY_CURRENCY_OR_PERCENT_MISSING_FORMATTER.fix_template,
    )


def _y_axis_check(chart: ResolvedChart) -> tuple[str | None, list[str]]:
    """The chart's shared y-axis format and the y fields that render against it.

    A bar/line/area/scatter chart's own y field(s) and any typed overlay
    ``chart.layers`` entries' y fields all share the SAME resolved y-axis
    format — layers are an overlay on the base chart, not a separate
    container — so both contribute fields checked against one format.
    Everything else (kpi, table, pie, maps, …) has no y-axis to format and
    yields no fields.
    """
    if not isinstance(chart, _CartesianResolvedChartFields):
        return None, []
    if chart.chart_type not in _Y_AXIS_TYPES:
        return None, []
    fields: list[str] = []
    if chart.y:
        # Wide charts fold y: list via VL's transform; check the authored measures,
        # not the synthetic WIDE_VALUE_FIELD that replaces chart.y at resolve time.
        if (
            isinstance(chart, (ResolvedBarChart, ResolvedLineChart, ResolvedAreaChart))
            and chart.wide_measures
        ):
            fields.extend(chart.wide_measures)
        else:
            # Heatmap is the only remaining family that can still carry a
            # list y (its own multi-measure render path, not the fold).
            fields.extend(chart.y if isinstance(chart.y, list) else [chart.y])
    if isinstance(chart, LayeredResolvedChart):
        fields.extend(layer.y for layer in chart.layers if layer.y)
    if not fields:
        return None, []
    return chart.style.axis_y.labels.format, fields


def detect(ctx: WarningContext) -> list[Diagnostic]:
    """Return one Diagnostic per y field whose baked format is unfit for its kind.

    A currency/percent-named y field warns unless the chart's resolved y-axis
    format suits that kind (see ``_format_suits_kind``). Layered charts share one
    y-axis, so its format is checked once per matching layer.
    """
    warnings: list[Diagnostic] = []

    for chart_id, chart in ctx.board_spec.charts.items():
        axis_format, fields = _y_axis_check(chart)
        for field in fields:
            kind = _classify(field)
            if kind is not None and not _format_suits_kind(axis_format, kind):
                warnings.append(_warn(chart_id, field, kind, axis_format))

    return warnings
