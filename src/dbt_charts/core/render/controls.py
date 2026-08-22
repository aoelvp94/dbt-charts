"""The control runtime and stylesheet a host ships to bind a board's controls.

Stage: RENDER
Purpose: Hand a host the JS and CSS that make the *drawn* controls live.

No markup: the server draws every variable control into the board SVG
(``variables_strip.py``), so a host adds behaviour, never elements. That is what
keeps every interactive surface out of the board's scaled coordinate system —
the defect this replaced was an HTML layer measured in page pixels sitting over
a band measured in board units.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING

from dbt_charts.core.render.comment_stripping import strip_js_comments
from dbt_charts.core.render.template_loader import render_template

if TYPE_CHECKING:
    from collections.abc import Generator

_INTERACTIVE: ContextVar[bool] = ContextVar("dft_interactive_controls", default=False)


@contextmanager
def interactive_controls(enabled: bool) -> Generator[None]:
    """Hang the behaviour payload on the drawn controls, for one render.

    The *drawing* never varies: a picture must not depend on who is looking at
    it, so the same board renders the same chrome live or exported. What varies
    is the payload a runtime needs and an artifact cannot use — a select's full
    option list, which is data the board fetched and deliberately did not draw.

    A context manager rather than a parameter because the decision is the
    host's and the reader is eight frames down; ``collect_table_overflows`` in
    the same ``with`` block scopes render-wide state the same way.
    """
    token = _INTERACTIVE.set(enabled)
    try:
        yield
    finally:
        _INTERACTIVE.reset(token)


def controls_are_interactive() -> bool:
    """True while a render is being done for a host that can act on it."""
    return _INTERACTIVE.get()


@cache
def controls_runtime_source() -> str:
    """The variable-control runtime, as JS for a host to ship in its page.

    Strips the ``/*{# ... #}*/``-fenced comments — engineering notes with no
    audience once the runtime is shipped. Cached: hosts rebuild this per page
    render, and a packaged asset can't change under a running process.
    """
    source = (
        files("dbt_charts.core.render") / "templates" / "scripts" / "variables.js"
    ).read_text(encoding="utf-8")
    return strip_js_comments(source)


@cache
def controls_stylesheet() -> str:
    """The control styles, as CSS for a host to ship in its page.

    Rendered through Jinja, not read raw: the source authors its comments as
    ``{# ... #}``, which a browser would choke on. Cached for the same reason as
    the runtime above.
    """
    return render_template("controls/_styles.css")
