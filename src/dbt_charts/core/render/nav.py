"""Top-of-board navigation strip for ``dct serve``.

Stage: RENDER
Purpose: derive the nav's routing facts from a dir context dict and render them
into an HTML block via a Jinja template. The serve layer injects that HTML
directly into the served board's page body — no board, no SVG. Theme colors are
injected as CSS custom properties on the ``.dbt-nav`` wrapper by the serve
layer — this module owns only the routing facts and the markup.

Serve-only: only ``dct serve`` builds and renders the nav; static ``dct render``
output never carries it.
"""

from __future__ import annotations

from typing import Any


def _crumbs_from_url(dir_url: str) -> list[dict[str, str]]:
    """Derive crumb dicts from ``this_dir["url"]`` (already mount-stripped).

    E.g. ``"/support/"``           → ``[{"label": "support", "url": "/support/"}]``
         ``"/enterprise/finance/"``→ ``[{"label": "enterprise", "url": "/enterprise/"},
                                        {"label": "finance", "url": "/enterprise/finance/"}]``
         ``"/"``                   → ``[]``
    """
    parts = [p for p in dir_url.strip("/").split("/") if p]
    crumbs: list[dict[str, str]] = []
    accum = ""
    for part in parts:
        accum = f"{accum}/{part}"
        crumbs.append({"label": part, "url": f"{accum}/"})
    return crumbs


def _visible_crumbs(
    crumbs: list[dict[str, str]],
) -> list[dict[str, str] | None]:
    """Collapse middle directory crumbs for compact serve navigation."""
    if len(crumbs) <= 4:
        return list(crumbs)
    return [crumbs[0], None, *crumbs[-2:]]


def nav_context(
    current_label: str,
    current_url: str,
    dir_ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """Build the Jinja context for the nav strip, or None when dir_ctx is empty.

    Args:
        current_label: text shown in the dropdown trigger. Also the value matched
            against ``f.label`` for the file-menu checkmark — pass the board's stem
            for a board URL; pass the directory's name (or "/") for a listing.
        current_url: where the dropdown trigger links to. Empty string means the
            trigger is not a link (used for directory listings, which have no
            self-URL distinct from the directory the menu already lists).
        dir_ctx: Result of ``lazy_dir_context()``. An empty dict suppresses the
            nav strip (returns None).

    Returns None when ``dir_ctx`` is falsy.
    """
    if not dir_ctx:
        return None

    is_directory_listing = current_url == ""
    this_dir_url = str(dir_ctx["this_dir"]["url"])
    files = [
        {
            "label": f"{s['label']}/" if s["is_dir"] else s["label"],
            "url": s["url"],
        }
        for s in dir_ctx["siblings"]
        if not (this_dir_url == "/" and s["is_dir"] and s["name"] == "inspect")
    ]

    parent_dir = dir_ctx["parent_dir"]
    parent = {"label": "Up one level", "url": parent_dir["url"]} if parent_dir else None
    crumbs = _crumbs_from_url(this_dir_url)
    if is_directory_listing:
        crumbs = crumbs[:-1]
    return {
        "visible_crumbs": _visible_crumbs(crumbs),
        "current_label": current_label,
        "current_file_url": current_url or str(dir_ctx["this_dir"]["url"]),
        "parent": parent,
        "files": files,
    }
