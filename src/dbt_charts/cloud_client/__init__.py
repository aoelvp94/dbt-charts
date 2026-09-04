"""The dbt charts Cloud client package.

Home of the ``dct cloud`` verbs' HTTP client (``client.py``), the user-level
token/config store (``config.py``), per-invocation org/project resolution
(``context.py``), the failure vocabulary (``errors.py``), and ``contract.py``,
the request/response types the client and Cloud's own API views both use.
Deliberately outside ``agent_api`` (local-by-contract: no Django, no network)
and outside ``core`` (board semantics), and it imports from neither.

Modules import each other in one direction — ``errors`` ← ``config`` ←
``client`` ← ``context`` — and nothing re-exports a sibling: callers import the
module that owns the thing they want.
"""

from __future__ import annotations
