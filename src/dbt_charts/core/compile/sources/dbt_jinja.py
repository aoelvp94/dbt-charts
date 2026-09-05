"""Render dbt Jinja in source/profile config values.

dbt charts resolves `{{ env_var(...) }}` — and the rest of dbt's profile-rendering
Jinja — through dbt's own ``ProfileRenderer`` rather than a hand-rolled regex, so
these values resolve *exactly* as dbt would: env_var defaults, the
``DBT_ENV_SECRET_``-prefixed secret form, and non-string value preservation
(`port: 5432` stays an int) all come for free.

Behaviour matches dbt's, deliberately:
- A missing ``env_var()`` with no default raises (surfaced as ``ValueError`` —
  see :func:`_render`) for normal fields.
- dbt's ``SecretRenderer`` *defers* rendering for ``password`` keypaths (real
  passwords may contain ``{{``/``%`` characters), so a missing password env_var
  is left as a literal and fails at connect time rather than at parse. We accept
  dbt's contract here rather than re-deriving a stricter one.

A payload dbt would return byte-identical skips the call, and with it dbt-core's
import; see :func:`_nothing_to_render`. Such a payload is
returned *as the caller's own object*, where dbt always deep-rebuilt, so callers
must not write through the result.

dbt reads env vars from a process-global *invocation context* (a ``ContextVar``
it sets at CLI startup). dbt charts embeds dbt as a library, so we establish that
context from the live environment per render.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

# dbt's render-chars pattern, from ``dbt/clients/jinja.py``
# (``_HAS_RENDER_CHARS_PAT``). Necessary for the skip below, not sufficient:
# ``get_rendered``'s matching shortcut is disabled when ``native=True``, and
# ``renderer.py`` always passes it — so dbt compiles even a jinja-free string
# through Jinja, and Jinja rewrites some of them.
_HAS_RENDER_CHARS = re.compile(r"({[{%#]|[#}%]})")

# What that compile changes on a string with nothing in it to render — jinja2's
# lexer rewrites, and the whole surface of them:
#   - a single trailing "\n" is dropped   (keep_trailing_newline=False)
#   - every "\r" becomes "\n"             (newline_sequence="\n")
# A PEM private key or a password read from a file carries a trailing newline, so
# skipping these would corrupt a credential, not just reformat one.
_JINJA_REWRITES = re.compile(r"\r|\n\Z")

# ``dbt_common.constants.SECRET_ENV_PREFIX``, inlined to keep dbt off the import
# path (``test_secret_prefix_matches_dbt`` pins the two together). Any value
# containing it takes ``SecretRenderer``'s placeholder branch, which returns
# ``None`` when the placeholder regex misses. That is a dbt bug, but this
# function's job is to be indistinguishable from dbt, not better than it.
_SECRET_ENV_PREFIX = "DBT_ENV_SECRET"

# Leaf types dbt hands back untouched. ``str`` is absent because strings answer
# above; ``bool`` because ``isinstance(True, int)``. ``datetime.date`` is absent
# deliberately — ``deep_map_render`` treats it as atomic but ``render_value``
# ISO-formats it, and YAML gives us real dates for an unquoted ``2026-01-01``.
_INERT_LEAVES = (int, float, type(None))


def _nothing_to_render(
    data: Any,  # type-state: explicit_any — any yaml.safe_load output
) -> bool:
    """Whether ``ProfileRenderer`` would hand ``data`` back exactly as given.

    True only where that has been measured, never where it merely seems likely:
    a wrong True silently rewrites a config value, while a wrong False costs
    only the import this function exists to avoid.
    """

    def walk(
        value: Any,  # type-state: explicit_any — walks arbitrary YAML nodes
        path: tuple[int, ...],
    ) -> bool:
        if isinstance(value, dict | list):
            if id(value) in path:
                # A YAML anchor cycle (`a: &x {b: *x}` — safe_load builds these).
                # dbt detects it and raises a DbtProjectError that this module
                # adapts to ValueError; recursing here instead would raise
                # RecursionError, which is a RuntimeError and sails past the
                # `except ValueError` in detection.py on untrusted input.
                return False
            path += (id(value),)
            items = value.values() if isinstance(value, dict) else value
            return all(walk(item, path) for item in items)
        if isinstance(value, str):
            return (
                _HAS_RENDER_CHARS.search(value) is None
                and _JINJA_REWRITES.search(value) is None
                and _SECRET_ENV_PREFIX not in value
            )
        return isinstance(value, _INERT_LEAVES)

    try:
        return walk(data, ())
    except RecursionError:
        # Depth, where the check above catches self-reference: a chain of YAML
        # aliases builds an arbitrarily deep *acyclic* graph out of a shallow
        # document, so nothing repeats and the walk recurses until it gives out.
        # Answering False hands the payload to dbt, which either renders it or
        # overflows its own walk — and that overflow it already converts to a
        # `DbtBaseException`, which this module adapts to `ValueError` below.
        # What the caller must never get is a bare `RecursionError`: that is a
        # `RuntimeError`, and
        # detection.py's degrade-never-crash guard on untrusted `profiles.yml`
        # catches only `ValueError`.
        return False


def _refresh_invocation_context(env: Mapping[str, str]) -> None:
    """(Re)build dbt's invocation context for ``env_var()`` resolution.

    dbt's ``env_var()`` reads a process-global ``ContextVar``, not ``os.environ``
    directly. The context holds nothing but env-derived state (public/private env
    split + a secret cache), so rebuilding it per render is cheap, loses nothing,
    and keeps ``env_var()`` reading the chosen environment.

    ``env`` is resolved against exactly the mapping passed in: the live
    ``os.environ`` (dbt-faithful — for trusted local config) or an explicit
    mapping (e.g. ``{}``) when rendering Jinja from untrusted input (e.g. a
    remote-committed ``profiles.yml``) so the process environment's secrets are
    never reachable.

    This is a compile-stage, single-threaded path. If dbt charts ever rendered
    source configs concurrently with an active *embedded* dbt invocation, this
    overwrite would clobber that invocation's context — not a concern today.
    """
    from dbt_common.context import set_invocation_context

    set_invocation_context(dict(env))


def render_dbt_jinja_in_dict(
    data: dict[str, Any],
    *,
    # noqa rationale: dbt env_var() resolves YAML macros from the live process
    # environment by contract — this default is the composition root for that read.
    env: Mapping[str, str] = os.environ,  # noqa: TID251 — env_var() YAML macro default
) -> dict[str, Any]:
    """Render dbt Jinja in every (recursively nested) string value of a dict.

    Non-string values pass through unchanged. ``password`` keypaths follow dbt's
    secret-deferral (see module docstring); other fields raise ``ValueError`` on
    an unset env var with no default or on malformed/unresolvable Jinja.

    ``env`` selects the environment ``env_var()`` resolves against: the live
    ``os.environ`` (default) for trusted local config; pass ``{}`` to resolve
    only author-supplied ``env_var()`` defaults without exposing the process
    environment — mandatory for untrusted/remote-committed input.

    dbt raises its own hierarchy (``EnvVarMissingError`` / ``CompilationError``);
    we adapt it to ``ValueError`` at this boundary so Pydantic field/model
    validators surface a ``ValidationError``. The dbt message is preserved.
    """
    # Before the import, not after — skipping the work is the point, but
    # skipping dbt's several-hundred-millisecond import is the win.
    if _nothing_to_render(data):
        return data

    from dbt.config.renderer import ProfileRenderer
    from dbt_common.exceptions.base import DbtBaseException

    _refresh_invocation_context(env)
    try:
        return ProfileRenderer({}).render_data(data)
    except DbtBaseException as e:
        raise ValueError(str(e)) from e
