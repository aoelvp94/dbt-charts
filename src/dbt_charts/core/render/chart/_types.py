"""Shared type aliases for render-v2 Vega-Lite spec construction.

``VLDict`` documents the compile↛render boundary: Vega-Lite specs and their
fragments are inherently untyped dicts (VL, not dbt charts, owns that shape),
so ``dict[str, Any]`` here is a deliberate, single-source boundary alias —
not a dodge. Import this everywhere a VL fragment is built or passed,
rather than repeating ``dict[str, Any]`` or declaring a parallel alias.
"""

from __future__ import annotations

from typing import Any

VLDict = dict[str, Any]
