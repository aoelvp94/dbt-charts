"""Alias-URL semantics, shared by every host that resolves a board's ``aliases:``.

A leaf module on purpose. An alias is claimed in a board and matched against an
incoming request path as a *string*, so the two sides must normalize it
identically or a claim resolves on one host and silently does nothing on the
other. Hosts that keep their own board index (rather than building an
``AliasIndex``) need that rule without importing the ``dct serve`` HTTP
application to get it — ``core/serve/`` sits at the top of the dependency stack.
"""

from __future__ import annotations

from urllib.parse import unquote


def normalize_alias_url(url: str) -> str:
    """Normalize a URL key: percent-decode, ensure leading /, ensure trailing /."""
    decoded = unquote(url)
    if not decoded.startswith("/"):
        raise ValueError(
            f"Alias {url!r} is not absolute: aliases must start with a leading /. "
            "Example: /old-reports/"
        )
    # Trailing-slash canonical: add if missing
    if not decoded.endswith("/"):
        decoded = decoded + "/"
    return decoded
