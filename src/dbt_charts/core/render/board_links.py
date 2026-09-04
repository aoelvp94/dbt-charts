"""Board link resolution.

Rewrites markdown board links at render time so authors can use
dashboard-root-relative paths (e.g. ``/zendesk/tickets/list?status=open``)
that work in both ``dct serve`` and Cloud.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from posixpath import normpath

from dbt_charts.core.project import BOARD_CANDIDATE_SUFFIXES

# Markdown link pattern: [text](url), excluding image syntax ![alt](src)
_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")

# Raw HTML anchor pattern: captures the href= prefix and the root-relative path.
# Only matches root-relative hrefs (starting with /) — external URLs are left to
# resolve_href's _PASSTHROUGH_PREFIXES guard.
_RAW_ANCHOR_RE = re.compile(r'(<a\s[^>]*href=")(/[^"]*)"', re.IGNORECASE)

# Stored SVG artifacts may contain links emitted for the in-app root. Standalone
# formats need those same attributes qualified with the serving origin. Keep this
# byte-oriented: rendered SVG can contain browser-valid script that is not strict XML.
_SVG_ROOT_LINK_RE = re.compile(
    r"(?P<prefix>\b(?:href|xlink:href)\s*=\s*(?P<quote>['\"]))"
    r"(?P<path>/(?!/)[^'\"]*)(?P=quote)",
    re.IGNORECASE,
)

# Schemes that bypass rewriting. cursor://, vscode://, file:// pass through so
# editor-deeplink URLs (e.g. ``cursor://file/{abs}/board.yaml`` from the compare
# UI) reach the browser unchanged — both the scheme and the .yaml suffix.
# "?" passes through so variable-update links (?var=value) reach variables.js
# unchanged instead of being treated as relative board paths.
_PASSTHROUGH_PREFIXES = (
    "http://",
    "https://",
    "mailto:",
    "#",
    "?",
    "command:",
    "cursor://",
    "vscode://",
    "file://",
)


@dataclass(frozen=True)
class LinkContext:
    """Runtime context for resolving board links.

    Attributes:
        root: URL prefix for this host's dashboard/view root, e.g.
            ``/boards`` for dct serve (default storage prefix),
            ``/{org}/{project}/d`` for Cloud. Links are built as
            ``{origin}{root}/{slug}``. Empty string means serve-at-root:
            links are ``/{slug}``. The ``/d`` segment is the host's
            responsibility — core emits a uniform ``{root}/{slug}`` for
            every slug (dashboard or system view).
        current_board_slug: Author-space slug of the board being rendered
            (e.g. ``"zendesk/tickets/list"``). Used to resolve relative links.
        origin: When non-empty (e.g. ``"https://dbtcharts.com"``),
            emitted links are fully-qualified. In-app renders leave this
            empty so links stay root-relative. Set for exported artifacts
            (downloaded HTML/PDF/PNG) opened outside the app where no base
            URL is implied by the browser context. When ``root`` is empty
            (serve-at-root or ``dct render`` with ``public_url``), the
            resolved link is ``{origin}/{slug}`` — ``origin`` is the sole
            absolute prefix.
    """

    root: str = ""
    current_board_slug: str = ""
    origin: str = ""

    def __post_init__(self) -> None:
        from dbt_charts.core.diagnostics import ERR_INPUT_INVALID
        from dbt_charts.core.render.errors import RenderError

        if self.root and not self.root.startswith("/"):
            raise RenderError.from_code(
                ERR_INPUT_INVALID,
                message=f"root must be empty or start with '/'; got {self.root!r}",
            )
        if self.root.endswith("/"):
            raise RenderError.from_code(
                ERR_INPUT_INVALID,
                message=f"root must not end with '/'; got {self.root!r}",
            )
        if self.origin.endswith("/"):
            raise RenderError.from_code(
                ERR_INPUT_INVALID,
                message=f"origin must not end with '/'; got {self.origin!r}",
            )


def resolve_href(href: str, ctx: LinkContext) -> str:
    """Resolve a single href against *ctx*.

    - External URLs (``http:``, ``https:``, ``mailto:``, ``#``) pass through.
    - Query-string-only URLs (``?…``) pass through unchanged for variables.js interception.
    - Root-relative (``/path``) maps from author namespace.
    - Relative (``../``, ``./``, bare) resolves against current board directory.
    - ``.md`` / ``.yml`` / ``.yaml`` suffixes are stripped.
    - Every slug — dashboard or system view — produces ``{origin}{root}/{slug}``.
    """
    for prefix in _PASSTHROUGH_PREFIXES:
        if href.startswith(prefix):
            return href

    # Split path / query / fragment (can't use urlparse — Jinja braces aren't valid)
    path, query, fragment = _split_url(href)

    resolved = _resolve_slug(path, ctx.current_board_slug)

    url = _build_url(resolved, query, ctx)
    return f"{url}#{fragment}" if fragment else url


def _resolve_slug(path: str, current_board_slug: str) -> str:
    """Map an authored link path to a board slug.

    Root-relative maps from the author namespace; relative resolves against the
    linking board's directory; ``.md``/``.yml``/``.yaml`` are author sugar and
    come off. Shared by ``resolve_href`` (which needs a URL) and
    ``link_target_slug`` (which needs the slug), so the two cannot drift.
    """
    if path.startswith("/"):
        resolved = path.lstrip("/")
    else:
        # Relative: resolve against current board's directory
        board_dir = "/".join(current_board_slug.split("/")[:-1])
        resolved = normpath(f"{board_dir}/{path}") if board_dir else normpath(path)
        # normpath may produce leading ".." — clamp to root
        if resolved.startswith(".."):
            resolved = resolved.lstrip("./")

    # Strip author-sugar suffixes
    for suffix in BOARD_CANDIDATE_SUFFIXES:
        if resolved.endswith(suffix):
            resolved = resolved[: -len(suffix)]
            break
    return resolved


def is_board_link(href: str) -> bool:
    """Whether *href* is in-app board navigation at all.

    False for the passthrough schemes ``resolve_href`` leaves untouched —
    external URLs, ``mailto:``, fragments, query-only variable links, and the
    editor deeplinks. Those name no board, so there is nothing to resolve.
    """
    return not href.startswith(_PASSTHROUGH_PREFIXES)


def board_link_slug(href: str, current_board_slug: str) -> str:
    """The board slug *href* navigates to.

    The slug half of ``resolve_href``: same resolution and the same suffix
    stripping, answering "which board" rather than "which URL", so a caller
    that needs to know what a board points at (the Home network graph) and a
    caller that renders the link agree by construction rather than by a second
    implementation.

    Callers gate on ``is_board_link`` first; passing a passthrough href here is
    a caller bug, not a value to encode in the return type. An empty slug is a
    real answer — ``/`` names the root, which is not a board.
    """
    from dbt_charts.core.diagnostics import ERR_INPUT_INVALID
    from dbt_charts.core.render.errors import RenderError

    if not is_board_link(href):
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message=(f"not board navigation: {href!r} — gate on is_board_link() first"),
        )
    path, _query, _fragment = _split_url(href)
    # `/spend/` is a normal authored spelling and resolves to the same board as
    # `/spend`. A URL keeps the trailing slash; a slug never has one.
    return _resolve_slug(path, current_board_slug).rstrip("/")


def markdown_link_slugs(markdown: str, current_board_slug: str) -> list[str]:
    """Board slugs the links in *markdown* point at, in document order.

    Reads the same two constructs ``rewrite_board_links`` rewrites — markdown
    ``[text](url)`` and raw ``<a href="/path">`` — so a link that renders as
    board navigation is exactly a link that shows up here.
    """
    hrefs = [match.group(2) for match in _MD_LINK_RE.finditer(markdown)]
    hrefs += [match.group(2) for match in _RAW_ANCHOR_RE.finditer(markdown)]
    slugs = [
        board_link_slug(href, current_board_slug)
        for href in hrefs
        if is_board_link(href)
    ]
    return [slug for slug in slugs if slug]


def _split_url(href: str) -> tuple[str, str, str]:
    """Split href into (path, query, fragment), preserving Jinja in the query."""
    fragment = ""
    hash_idx = href.find("#")
    if hash_idx != -1:
        href, fragment = href[:hash_idx], href[hash_idx + 1 :]
    q_idx = href.find("?")
    if q_idx == -1:
        return href, "", fragment
    return href[:q_idx], href[q_idx + 1 :], fragment


def _build_url(slug: str, query: str, ctx: LinkContext) -> str:
    """Build the final URL for *slug* in *ctx*.

    Uniform shape: ``{origin}{root}/{slug}`` for every slug — slashless, matching
    the canonical route each host registers (Cloud's ``d/<slug>`` reverse, serve's
    board URLs). The registered-view router treats a path as directory-like, so
    ``/data/wh/orders`` resolves like ``/data/wh/orders/``.

    The empty-slug home branches keep their trailing slash on purpose: a root nav
    link needs a valid target (``{root}/`` or ``/``), not a bare prefix — the
    slug/home asymmetry is intentional, not an oversight to "fix".
    """
    slug = slug.rstrip("/")
    if slug:
        url = f"{ctx.root}/{slug}"
    elif ctx.root:
        url = f"{ctx.root}/"
    else:
        url = "/"
    if query:
        url = f"{url}?{query}"
    if ctx.origin:
        url = f"{ctx.origin}{url}"
    return url


# ---------------------------------------------------------------------------
# Markdown-level rewriting
# ---------------------------------------------------------------------------


def _rewrite_raw_anchors(html: str, ctx: LinkContext) -> str:
    """Rewrite root-relative href attributes in raw <a> tags through resolve_href.

    Only runs when ctx.root is set (Cloud/serve-with-prefix); bare serve
    (root empty) has no prefix so raw anchors can stay root-relative.
    """
    if not ctx.root:
        return html

    def _replace(m: re.Match[str]) -> str:
        prefix, href = m.group(1), m.group(2)
        return f'{prefix}{resolve_href(href, ctx)}"'

    return _RAW_ANCHOR_RE.sub(_replace, html)


def rewrite_board_links(markdown: str, ctx: LinkContext | None) -> str:
    """Rewrite board links in *markdown* using *ctx*.

    Handles both Markdown ``[text](url)`` syntax and raw ``<a href="/path">``
    anchors (emitted by ``html_policy`` text blocks).  Returns *markdown*
    unchanged when *ctx* is ``None``.
    """
    if ctx is None:
        return markdown

    def _replace(m: re.Match[str]) -> str:
        text, href = m.group(1), m.group(2)
        return f"[{text}]({resolve_href(href, ctx)})"

    result = _MD_LINK_RE.sub(_replace, markdown)
    return _rewrite_raw_anchors(result, ctx)


def absolutize_svg_links(svg: str, origin: str) -> str:
    """Qualify root-relative SVG link attributes with *origin*.

    Only ``href`` and ``xlink:href`` values beginning with exactly one slash are
    rewritten. Absolute, protocol-relative, fragment-only, and query-only values
    remain byte-identical. The SVG body is deliberately not XML-parsed because
    rendered dashboard scripts are browser-valid without being strict XML.
    """
    from dbt_charts.core.diagnostics import ERR_INPUT_INVALID
    from dbt_charts.core.render.errors import RenderError

    if not origin:
        raise RenderError.from_code(
            ERR_INPUT_INVALID, message="origin must be non-empty"
        )
    if origin.endswith("/"):
        raise RenderError.from_code(
            ERR_INPUT_INVALID,
            message=f"origin must not end with '/'; got {origin!r}",
        )

    def _replace(match: re.Match[str]) -> str:
        return (
            f"{match.group('prefix')}{origin}{match.group('path')}"
            f"{match.group('quote')}"
        )

    return _SVG_ROOT_LINK_RE.sub(_replace, svg)


# ---------------------------------------------------------------------------
# Render-scoped context variable
# ---------------------------------------------------------------------------

_current_link_context: ContextVar[LinkContext | None] = ContextVar(
    "_current_link_context", default=None
)


def get_link_context() -> LinkContext | None:
    """Return the active link context (set by the renderer)."""
    return _current_link_context.get()


def set_link_context(ctx: LinkContext | None) -> None:
    """Set the active link context for the current render pass."""
    _current_link_context.set(ctx)
