"""Content-addressed memo for rendered chart SVGs.

Stage: RENDER (vl-convert)
Purpose: Give a render somewhere to keep the SVG a chart already rendered to, so a
re-render of unchanged content skips vl-convert, which dominates render compute.

The key is **the content**, never the version that asked for it. It hashes the
Vega-Lite spec (which already carries the resolved rows and the theme-cascaded
encodings), the dimensions, the output format, the placeholder flag, the board's
resolved style, the active link context, and a renderer fingerprint. Same key
therefore means byte-identical SVG, and that one property is what the whole
design rests on:

- Staleness is **unrepresentable**, not merely unlikely. New warehouse rows, a
  theme edit, a variable change, an edited nested board, and a vl-convert upgrade
  each produce a different spec or a different fingerprint, so each produces a
  different key. There is no invalidation policy here because there is nothing
  to invalidate — only entries to evict.
- Nothing version-shaped belongs in the key. A board's git blob sha rotates for
  every chart on the board whenever any one of them is edited, so keying on it
  would miss on exactly the case this exists for; keying on it *and* reading the
  previous version's entry would answer with the previous render of the chart
  that just changed. The same goes for a chart's id: it is board-local identity,
  stable across edits while the content under it changes.

**This object is a plain in-memory dict, and that is the whole point.** A durable
host does not implement it — the host *fills* it, in one query, before the render
starts, and drains it, in one query, after. Nothing here touches a database, so a
render costs zero round-trips no matter how many charts it draws. The metadata a
host needs to do that (which board a chart belongs to, which chart minted an
entry) rides alongside the entries rather than in the key: `board_path` and
`chart_id` are for fetching and cleanup, never part of the key — the same split
`QueryResultCache` makes between its key and its `board_slug`/`query_name`.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from dbt_charts.core.diagnostics.chart_data import ChartDataError

if TYPE_CHECKING:
    from dbt_charts.core.compile.models.style.resolved import ResolvedStyle
    from dbt_charts.core.render.board_links import LinkContext

# Bump when something outside the two versioned dependencies below alters the
# SVG for an unchanged spec. Rarely needed: the fingerprint already folds in the
# installed vl-convert version *and* this package's own, and the package version
# is what tracks the vendored font set and every post-processing step in
# render_svg_content. A host store need not expire anything — an upgrade rotates
# every entry on its own, with no migration and no manual purge.
RENDERER_VERSION = "1"

# Largest single entry worth keeping. Above this the entry would dominate any
# store it is drained into and push out the small hot entries that make an edit
# feel instant — and re-rendering one chart is cheap next to that.
MAX_ENTRY_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class MintedSvg:
    """An entry this render produced, for a host that wants to keep it.

    ``chart_id`` is diagnostic metadata, not part of ``key`` — it answers
    "which chart is this 3 MB row?" without ever narrowing what the entry can
    answer for.
    """

    key: str
    svg: str
    chart_id: str


class RenderedSvgCache:
    """The render's SVG memo: an LRU dict, optionally pre-filled by a host.

    Nothing wires this by default — with no cache passed to ``render_board``
    there is no ambient memo and every chart goes through vl-convert exactly as
    before. A host that wants durability preloads a board's entries into one of
    these and reads ``touched`` / ``minted`` afterwards to write back.

    Entries are evicted, never invalidated: the key is content, so an entry is
    correct until it is dropped.
    """

    def __init__(
        self,
        entries: dict[str, str] | None = None,
        max_entries: int = 4096,
        max_entry_bytes: int = MAX_ENTRY_BYTES,
    ) -> None:
        self._entries: OrderedDict[str, str] = OrderedDict(
            entries if entries is not None else {}
        )
        self._max_entries = max_entries
        self._max_entry_bytes = max_entry_bytes
        self._preloaded = frozenset(self._entries)
        self._touched: set[str] = set()
        self._minted: dict[str, MintedSvg] = {}

    def get(self, key: str) -> str | None:
        svg = self._entries.get(key)
        if svg is None:
            return None
        self._entries.move_to_end(key)
        if key in self._preloaded:
            self._touched.add(key)
        return svg

    def put(self, key: str, svg: str, chart_id: str) -> None:
        if len(svg.encode()) > self._max_entry_bytes:
            return
        self._entries[key] = svg
        self._entries.move_to_end(key)
        self._minted[key] = MintedSvg(key=key, svg=svg, chart_id=chart_id)
        while len(self._entries) > self._max_entries:
            evicted, _ = self._entries.popitem(last=False)
            self._minted.pop(evicted, None)

    @property
    def touched(self) -> frozenset[str]:
        """Preloaded keys this render actually used.

        A host bumps these so a chart that draws on every page load doesn't age
        out of an LRU store precisely because it keeps hitting.
        """
        return frozenset(self._touched)

    @property
    def minted(self) -> tuple[MintedSvg, ...]:
        """Entries this render produced that were not preloaded."""
        return tuple(self._minted.values())


_active_cache: ContextVar[RenderedSvgCache | None] = ContextVar(
    "_active_svg_cache", default=None
)


def active_svg_cache() -> RenderedSvgCache | None:
    """The memo for the render in flight, or None when nobody supplied one.

    None is a real state, not a missing value: every caller that has not opted
    in renders uncached, exactly as before this module existed.
    """
    return _active_cache.get()


@contextmanager
def svg_cache_scope(cache: RenderedSvgCache | None) -> Generator[None]:
    """Bind *cache* for the duration of a render.

    Scoped rather than global so one render's memo cannot leak into an unrelated
    render, and restored on exit so nested renders (a nested board rendered inside
    a board) put the outer memo back.
    """
    token = _active_cache.set(cache)
    try:
        yield
    finally:
        _active_cache.reset(token)


@lru_cache(maxsize=1)
def _renderer_fingerprint() -> str:
    """The versions that decide the bytes: the renderer, and us.

    ``dbt-charts`` is in here because the emit path, the SVG post-processing, and
    the vendored font set all ship with this package and all change the output of
    an unchanged spec. Without it a release would serve the previous release's
    pixels out of a durable store until someone remembered to bump
    ``RENDERER_VERSION`` by hand.
    """
    from importlib.metadata import version  # noqa: PLC0415

    return f"{version('vl-convert-python')}/{version('dbt-charts')}"


def svg_cache_key(
    spec: dict[str, Any],
    *,
    output_format: str,
    width: float | None,
    height: float | None,
    is_placeholder: bool,
    resolved_style: ResolvedStyle,
    link_context: LinkContext | None,
) -> str:
    """Hash everything that can change the rendered bytes.

    Call this *before* rendering: `render_vega_spec` pops its ``$df_*`` sentinels
    out of ``spec`` in place, and those sentinels change the output, so a key
    taken afterwards would collide across genuinely different renders.

    Two arguments are content that is **not** in the spec, and both are here for
    the same reason — `render_vega_spec` reads them after vl-convert returns:
    ``resolved_style`` through the placeholder overlay, and ``link_context``
    through the sentinel-href rewrite, which bakes the host's board-root prefix
    (including the branch segment) straight into the markup. Leave either out and
    one board's SVG answers for another's links. Anything a future
    post-processing step reads belongs here too — the rule is that the key covers
    every input to the bytes, not merely every input to Vega.

    ``spec`` is serialized strictly, and deliberately: vl-convert serializes the
    same dict itself and refuses exactly what `json.dumps` refuses, so a spec that
    cannot be hashed could never have rendered. The failure is re-raised as the
    same per-chart error vl-convert's own refusal produces, so injecting a cache
    cannot turn one chart's error tile into a whole failed board.
    """
    try:
        canonical_spec = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ChartDataError(f"Chart spec is not JSON-serializable: {exc}") from exc
    payload = json.dumps(
        [
            canonical_spec,
            output_format,
            width,
            height,
            is_placeholder,
            repr(resolved_style),
            repr(link_context),
            RENDERER_VERSION,
            _renderer_fingerprint(),
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
