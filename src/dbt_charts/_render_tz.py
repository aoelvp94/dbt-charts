"""Process-wide timezone pin for vl-convert-backed static rendering.

``vl_convert.get_local_tz()`` has no setter and no per-call override: it
reads ``os.environ["TZ"]`` once and caches it for the process lifetime
(verified empirically -- mutating ``os.environ["TZ"]`` after vl-convert's
first call does not change what it reports; only a fresh process picks up a
new value). A composition root that never pins this leaves static rendering
(SVG/PNG/PDF export) dependent on whatever zone its own host happens to sit
in -- a committed golden regenerated on a non-UTC developer machine would
then silently differ from one approved elsewhere with no code change.

This lives outside ``dbt_charts.core``: ``core`` does not read or write
``os.environ`` (see ``core/ruff.toml``'s ``TID251`` banned-api) -- and
unlike a deployment knob (``DCT_MAX_WORKERS``, ``DCT_HTML_POLICY_CEILING``),
this is a process-wide write with no per-host variation today, so there is
nothing for core to accept as an injected value. A composition root (the
``dct`` CLI, the test suite, ...) calls ``pin_vl_convert_tz_utc()`` once at
its own startup, before it renders the first chart.

Client-side rendering is unaffected: a spec rendered in a browser uses the
viewer's own zone, same as before this pin exists.

The zone is unconditionally UTC today; making it configurable via project
config and a ``DCT_`` env override is tracked separately.
"""

from __future__ import annotations

import os


def pin_vl_convert_tz_utc() -> None:
    """Set ``TZ=UTC`` for this process.

    Call once, at composition-root startup, before rendering the first
    chart. The write itself is a plain, idempotent ``os.environ`` assignment
    -- safe to call more than once (e.g. once per request) -- but it only
    matters if it runs before vl-convert's own first call in this process;
    after that, vl-convert's cached zone can no longer be changed.
    """
    os.environ["TZ"] = "UTC"
