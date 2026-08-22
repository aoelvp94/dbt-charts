"""Public docs site base URL for CLI hints and cross-links."""

from __future__ import annotations

import os

DEFAULT_DOCS_SITE_URL = "https://docs.dataface.com"


def docs_site_url() -> str:
    """Return the docs site base URL without a trailing slash.

    ``DCT_DOCS_URL`` overrides the shipped default when set to a non-empty
    value. Used by ``dct docs`` (web link on the topic index) and by structured
    error ``doc_url``s.
    """
    raw = os.environ.get("DCT_DOCS_URL", DEFAULT_DOCS_SITE_URL).strip()
    if not raw:
        return DEFAULT_DOCS_SITE_URL
    return raw.rstrip("/")
