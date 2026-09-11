"""Walk a board's transitive import closure.

Returns every file the board pulls in (directly or transitively) via layout
imports (``rows``/``cols``/``grid.items``/``tabs.items`` strings ending in
``.yml``/``.yaml``) and cross-file refs (bare strings and ``{ref: ...}``
dicts in ``queries``/``charts``/``variables``), plus ``extends:`` file refs.

The result includes the root board itself as the first entry and is
deduplicated — a file imported via multiple paths appears once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.refs import (
    CHART_REF_RE,
    QUERY_REF_RE,
    VAR_REF_RE,
)
from dbt_charts.core.utils import YAML_LOADER

if TYPE_CHECKING:
    from dbt_charts.core.project import ProjectPath


def board_import_closure(board_path: ProjectPath) -> list[ProjectPath]:
    """Return all files in the transitive import closure of *board_path*.

    The list begins with *board_path* itself, followed by every file it imports
    (directly or transitively), in depth-first order with duplicates removed.
    Raises ``CompilationError`` on import cycles, missing files, or YAML errors.
    """
    result: list[ProjectPath] = []
    seen: set[str] = set()
    resolving: set[str] = set()

    def walk(path: ProjectPath) -> None:
        relpath = path.relpath
        if relpath in resolving:
            raise CompilationError(
                f"Import cycle detected: '{relpath}' imports itself transitively"
            )
        if relpath in seen:
            return
        seen.add(relpath)
        result.append(path)
        resolving.add(relpath)

        content = path.read_text()
        data = _load_board_yaml(content, relpath)

        if isinstance(data, dict):
            base_dir = path.parent
            for import_str in _extract_imports(data):
                try:
                    import_path = base_dir / import_str
                except ValueError as exc:
                    raise CompilationError(
                        f"Import '{import_str}' in '{relpath}' escapes the project root"
                    ) from exc
                if not import_path.exists():
                    raise CompilationError(
                        f"Import '{import_str}' in '{relpath}' does not exist"
                    )
                walk(import_path)

        resolving.discard(relpath)

    walk(board_path)
    return result


def _load_board_yaml(content: str, relpath: str) -> Any:
    """Parse board content to a Python object.

    Handles ``.md`` boards via their frontmatter YAML (not the raw markdown text,
    which contains two YAML documents and raises ``ComposerError``).
    Converts ``yaml.YAMLError`` to ``CompilationError`` so callers see one
    declared exception type.
    """
    try:
        if relpath.endswith((".md",)):
            from dbt_charts.core.compile.parse.markdown import parse_markdown_board

            content, _metadata = parse_markdown_board(content)
        return yaml.load(content, Loader=YAML_LOADER)
    except (ValueError, yaml.YAMLError) as exc:
        raise CompilationError(f"Parse error in '{relpath}': {exc}") from exc


def _extract_imports(data: dict[str, Any]) -> list[str]:
    """Collect all file paths imported by the board YAML mapping."""
    paths: list[str] = []
    _collect_extends(data, paths)
    _scan_dict(data, paths)
    return paths


def _collect_extends(data: dict[str, Any], paths: list[str]) -> None:
    """Extract .yml/.yaml file refs from the top-level extends: key.

    extends: can be a scalar or a list. Built-in theme names (cream, editorial,
    etc.) do not end in .yml/.yaml and are skipped automatically.
    """
    extends = data.get("extends")
    if isinstance(extends, str) and extends.endswith((".yml", ".yaml")):
        paths.append(extends)
    elif isinstance(extends, list):
        for item in extends:
            if isinstance(item, str) and item.endswith((".yml", ".yaml")):
                paths.append(item)


def _scan_dict(obj: dict[str, Any], paths: list[str]) -> None:
    ref = obj.get("ref")
    if isinstance(ref, str):
        file_path = _ref_file_path(ref)
        if file_path:
            paths.append(file_path)
        return  # ref dict is terminal — don't recurse into its siblings
    for v in obj.values():
        if isinstance(v, str):
            # Bare-string cross-file refs: the authored form per refs.py is a
            # plain string like "_shared.yml.queries.rev", coerced to {ref: ...}
            # at Pydantic parse time. We read authored YAML, so detect the
            # bare-string form here.
            file_path = _ref_file_path(v)
            if file_path:
                paths.append(file_path)
        elif isinstance(v, list):
            _scan_list(v, paths)
        elif isinstance(v, dict):
            _scan_dict(v, paths)


def _scan_list(items: list[Any], paths: list[str]) -> None:
    for item in items:
        if isinstance(item, str) and item.endswith((".yml", ".yaml")):
            paths.append(item)
        elif isinstance(item, dict):
            _scan_dict(item, paths)


def _ref_file_path(ref: str) -> str | None:
    """Extract the file path from a cross-file ref string like 'file.section.name'.

    Matches the compiler's anchored ref grammar (models/refs.py) — a substring
    scan would read prose like 'style.charts.callout' as a ref, and the
    resulting CompilationError silently disables invalidation for the board.
    """
    for regex, section in (
        (QUERY_REF_RE, "queries"),
        (CHART_REF_RE, "charts"),
        (VAR_REF_RE, "variables"),
    ):
        if regex.fullmatch(ref):
            file_part, _ = ref.rsplit(f".{section}.", 1)
            if not file_part.endswith((".yml", ".yaml")):
                file_part += ".yml"
            return file_part
    return None
