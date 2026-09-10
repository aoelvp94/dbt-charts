"""Meta.yml cascading configuration resolution.

Stage: COMPILE
Purpose: Resolve meta.yml chain from board file to project root.

Entry Points:
    find_meta_files(board_path, root_dir) -> list[ProjectPath]
    load_meta_file(meta_path) -> tuple[dict[str, Any], MetaLintConfig]
    resolve_meta_lint(board_path, root_dir) -> MetaLintConfig | None

meta.yml is a partial AuthoredBoard — the same authoring surface as a board file,
but without a layout requirement. Content fields are merged by the resolution engine
(merge_metas / merged_patch). Lint directives are extracted separately here.

lint: is extracted before the AuthoredBoard merge and threaded separately; it
is not a board content field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.diagnostics.suppression import validate_suppression_codes

if TYPE_CHECKING:
    from dbt_charts.core.project import ProjectDirectory, ProjectPath


@dataclass(frozen=True)
class MetaLintConfig:
    """Lint-suppression directives extracted from meta.yml lint: section.

    Carried separately from the AuthoredBoard merge so lint policy does not
    pollute the board content model.
    """

    ignore: list[str]
    ignore_queries: dict[str, list[str]]


def load_meta_file(meta_path: ProjectPath) -> tuple[dict[str, Any], MetaLintConfig]:
    """Load a meta.yml file.

    Returns the meta dict (a partial ``AuthoredBoard``) and the extracted lint
    config. The ``lint`` key is stripped out of the returned dict — it is a
    validation directive, not board content. Every other key stays and is
    validated downstream by ``AuthoredBoard`` once meta is merged under the board,
    so a stray non-board key (``access``, ``boards``, the old ``board:`` wrapper)
    fails loudly there rather than being silently dropped here.

    Raises:
        CompilationError: file missing, unreadable, not a YAML mapping, or
            ``lint`` is not a mapping.
    """
    if not meta_path.exists():
        raise CompilationError(f"Meta file not found: {meta_path.relpath}")

    try:
        data = meta_path.read_yaml() or {}
    except (yaml.YAMLError, OSError) as e:
        raise CompilationError(f"Failed to parse {meta_path.relpath}: {e}") from e

    if not isinstance(data, dict):
        raise CompilationError(
            f"{meta_path.relpath} must be a YAML mapping, got {type(data).__name__}"
        )

    # Extract lint before the AuthoredBoard merge — validation policy, not content.
    lint_data = data.pop("lint", {}) or {}
    if not isinstance(lint_data, dict):
        raise CompilationError(
            f"{meta_path.relpath}: 'lint' must be a mapping, "
            f"got {type(lint_data).__name__}"
        )
    lint = MetaLintConfig(
        ignore=lint_data.get("ignore", []),
        ignore_queries=lint_data.get("ignore_queries", {}),
    )
    try:
        validate_suppression_codes(
            lint.ignore, source=f"{meta_path.relpath}: lint.ignore"
        )
        for query_name, codes in lint.ignore_queries.items():
            validate_suppression_codes(
                codes,
                source=f"{meta_path.relpath}: lint.ignore_queries[{query_name!r}]",
            )
    except ValueError as e:
        raise CompilationError(str(e)) from e

    return data, lint


def find_meta_files(
    board_path: ProjectPath, root_dir: ProjectDirectory
) -> list[ProjectPath]:
    """Find all meta.yml files from board directory up to root.

    Walks up the directory tree from the board file's directory to root_dir,
    collecting meta.yml files found. Returns them ordered root → board directory
    (so child configs come last for proper override order).

    Args:
        board_path: ProjectPath handle for the board file.
        root_dir:  Root directory to stop searching (the walk upper bound).
    """
    meta_paths: list[ProjectPath] = []
    current = board_path.parent

    while True:
        for name in ("meta.yml", "meta.yaml"):
            candidate = current / name
            if candidate.exists():
                meta_paths.append(candidate)
                break

        if (
            current.relpath == root_dir.relpath
            or current.parent.relpath == current.relpath
        ):
            break
        current = current.parent

    meta_paths.reverse()
    return meta_paths


def resolve_meta_lint(
    board_path: ProjectPath,
    root_dir: ProjectDirectory,
) -> MetaLintConfig | None:
    """Return combined MetaLintConfig for the meta.yml chain above board_path.

    Walks up from board_path to root_dir, collects lint directives from every
    meta.yml found, merges them root→leaf, and returns the result. Returns
    None when no meta files exist or none carry a lint: block.

    Args:
        board_path: ProjectPath handle for the board file.
        root_dir:  Upper bound for the meta walk.

    Returns:
        MetaLintConfig with merged ignore / ignore_queries, or None.
    """
    meta_paths = find_meta_files(board_path, root_dir)
    merged_ignore: list[str] = []
    merged_ignore_queries: dict[str, list[str]] = {}
    for mp in meta_paths:
        _, lint = load_meta_file(mp)
        merged_ignore = list(dict.fromkeys(merged_ignore + lint.ignore))
        for qname, codes in lint.ignore_queries.items():
            existing = merged_ignore_queries.get(qname, [])
            merged_ignore_queries[qname] = list(dict.fromkeys(existing + codes))
    if not merged_ignore and not merged_ignore_queries:
        return None
    return MetaLintConfig(ignore=merged_ignore, ignore_queries=merged_ignore_queries)
