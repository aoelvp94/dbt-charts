"""Canonical builders for data system-view URLs.

One mapper per concept: the ``/data/<source>[/<schema>[/<table>]]/`` grammar
is defined here and nowhere else. Both the agent-facing data-path API
(``agent_api/data_paths.py``) and the pack planner build their URLs through
these helpers, so a change to the grammar (trailing slash, segment order,
encoding) lands in exactly one place and can't drift between producers.

Segments are interpolated unencoded — identical to how the data router matches
the same route — so a URL built here matches the system-view route for the same
source/schema/table. Callers pass warehouse identifiers, expected to be URL-safe;
a name containing a path-structural character (``/``, ``?``, ``#``) is out of
contract.
"""

from __future__ import annotations


def data_source_url(source: str) -> str:
    """Canonical data URL for a source: ``/data/<source>/``."""
    return f"/data/{source}/"


def data_schema_url(source: str, schema: str) -> str:
    """Canonical data URL for a schema: ``/data/<source>/<schema>/``."""
    return f"/data/{source}/{schema}/"


def data_table_url(source: str, schema: str, table: str) -> str:
    """Canonical data URL for a table: ``/data/<source>/<schema>/<table>/``."""
    return f"/data/{source}/{schema}/{table}/"
