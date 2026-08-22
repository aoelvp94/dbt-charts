"""Render dbt Jinja in source/profile config values.

dataface resolves `{{ env_var(...) }}` — and the rest of dbt's profile-rendering
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

dbt reads env vars from a process-global *invocation context* (a ``ContextVar``
it sets at CLI startup). dataface embeds dbt as a library, so we establish that
context from the live environment per render.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


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

    This is a compile-stage, single-threaded path. If dataface ever rendered
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
    from dbt.config.renderer import ProfileRenderer
    from dbt_common.exceptions.base import DbtBaseException

    _refresh_invocation_context(env)
    try:
        return ProfileRenderer({}).render_data(data)
    except DbtBaseException as e:
        raise ValueError(str(e)) from e
