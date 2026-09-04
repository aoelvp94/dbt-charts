"""Data-alias typo lint for /data/ prefixed board aliases.

Checks source names only (config only, no DB connection required) — called
from the validate path, which must stay connection-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbt_charts.core.project import Project


def validate_data_aliases(
    aliases: list[str],
    *,
    source_names: frozenset[str],
) -> list[str]:
    """Lint /data/ prefixed aliases against configured source names.

    Called at `dct validate` time (connection-free). Checks that every
    /data/ URL references a known source, and errors with available
    sources as a hint when not.

    Returns a list of error message strings (empty = all valid).
    Aliases not prefixed with /data/ are silently skipped.
    """
    errors: list[str] = []
    for raw_alias in aliases:
        # Normalize: trailing-slash canonical, strip percent-encoding
        from urllib.parse import unquote

        alias = unquote(raw_alias)
        if not alias.endswith("/"):
            alias = alias + "/"

        if not alias.startswith("/data/"):
            continue

        # Strip leading "/data/" and trailing "/" to get segments
        inner = alias[len("/data/") :]
        if inner.endswith("/"):
            inner = inner[:-1]
        segments = [s for s in inner.split("/") if s]

        if not segments:
            # Bare /data/ — no validation needed
            continue

        # Segment 0: source
        source = segments[0]
        if source not in source_names:
            available = sorted(source_names)
            hint = (
                f"available sources: {', '.join(available)}"
                if available
                else "no sources configured"
            )
            errors.append(
                f"Data alias {raw_alias!r} references unknown source {source!r}. "
                f"Did you mean one of: {hint}"
            )

    return errors


def data_alias_errors_for_file(
    board_file: str,
    source_names: frozenset[str],
    project: Project,
) -> list[str]:
    """Read aliases from a board file and lint any /data/ prefixed ones.

    Reads through *project* (the file-access seam), so it works against a
    git-blob store as well as the filesystem. Source-name check only — no DB
    connection, no resolver. Called from the validate path which must stay
    connection-free.

    Returns a list of error message strings; empty means no data alias issues.
    Silently returns [] when the file cannot be parsed (compile catches that).
    """
    from dbt_charts.core.serve.alias_index import read_aliases_from_file

    project_path = project.path(board_file)
    try:
        aliases = read_aliases_from_file(project_path)
    except ValueError:
        return []  # compile path reports alias-shape parse errors with context
    return validate_data_aliases(aliases, source_names=source_names)
