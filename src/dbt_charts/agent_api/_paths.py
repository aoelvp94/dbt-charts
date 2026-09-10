"""Shared path helpers for AI tools and CLI render setup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

# tach-ignore(agent_api->cli: runtime host-type guard in resolve_board_or_error / _relpath_for_fs_location, and direct construction in compile_editor_buffer; the local-filesystem check needs a non-cli signal on Project — deferred)
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.diagnostics import (
    ERR_FILE_NOT_FOUND,
    ERR_INTERNAL,
    Diagnostic,
)
from dbt_charts.core.diagnostics.base import DbtChartsError
from dbt_charts.core.project import (
    BOARD_CANDIDATE_SUFFIXES as BOARD_CANDIDATE_SUFFIXES,
    CHARTS_SUBDIR as CHARTS_SUBDIR,
    BoardFile,
    InMemoryBoard,
    Project,
    ProjectPath,
    assert_relpath,
    posix_relpath,
)
from dbt_charts.core.project_roots import (
    DCT_ROOT_MARKERS as DCT_ROOT_MARKERS,
    find_dct_root as find_dct_root,
    find_repo_root as find_repo_root,
)

if TYPE_CHECKING:
    from dbt_charts.core.compile.compiler import CompileResult


def iter_expanded_board_files(project: Project, under: str) -> list[ProjectPath]:
    """Board files under ``under``, sorted — the shared directory-walk filter.

    Excludes private (leading-underscore) files, ``meta.yml``/``meta.yaml``
    cascade fragments, and inspect-manifest-owned directories: none of these
    are standalone boards. Shared by ``validate_paths`` and ``describe_paths``
    so the two verbs' expansion can't drift out of sync again.
    """
    # WHY: dbt_charts.core.inspect.manifest_utils triggers the inspect package
    # __init__, which eagerly imports TableInspector + grain/quality/semantic
    # detectors. Keep this lazy so `dct --help` doesn't pay that startup cost.
    from dbt_charts.core.inspect.manifest_utils import INSPECT_TEMPLATE_MANIFEST

    return sorted(
        pf
        for pf in project.iter_boards(under=under, recursive=True)
        if pf.is_yaml
        and not pf.is_private
        and not pf.is_meta
        and not (pf.parent / INSPECT_TEMPLATE_MANIFEST).exists()
    )


def resolve_board_relpath(relpath: PurePosixPath, project: Project) -> ProjectPath:
    """Project-relative board identity -> ProjectPath, with the boards-first retry.

    The relpath-native counterpart to ``resolve_board_path``: for callers that
    already hold a project-relative board identity (Cloud's context strings)
    rather than a real filesystem path, this is the single owner of the
    board-relative vs root-relative reconciliation — a bare name like
    ``looker/x.yaml`` retries under ``CHARTS_SUBDIR`` when it doesn't exist at
    root, without producing a ``charts/charts/...`` double prefix when the
    caller already supplies the full ``charts/looker/x.yaml``.

    Existence is checked via ``project.exists(...)`` so it works for all
    ``Project`` implementations (FilesystemProject, CloudManagedProject
    git-blob store, etc.) — not just the local filesystem. Paths that exist
    at root resolve from root — non-boards paths like ``models/schema.sql``
    are not rewritten under charts/. ``str`` is used only at the identity seam
    (``project.path`` / ``project.exists``); everything else is real
    ``PurePosixPath`` operations.
    """
    relpath_str = str(relpath)
    assert_relpath(relpath_str)
    if project.exists(relpath_str):
        return project.path(relpath_str)
    if not relpath.parts or relpath.parts[0] != CHARTS_SUBDIR:
        candidate = PurePosixPath(CHARTS_SUBDIR) / relpath
        candidate_str = str(candidate)
        if project.exists(candidate_str):
            return project.path(candidate_str)
    return project.path(relpath_str)  # caller reports not-found


def _relpath_for_fs_location(path: Path, project: Project) -> str:
    """Relativize an absolute, on-disk board location against a local project root.

    Absolute and ``..``-leading board paths are explicit filesystem locations —
    the one place this boundary genuinely needs a real ``Path`` op. Only
    ``FilesystemProject`` ever receives them: Cloud/MCP always supply
    project-relative identity strings, never a real filesystem path, so any
    other ``Project`` implementation here is a caller bug, not a store to
    fall back through.

    Two-try containment check (mirrors the pre-refactor behavior): ``resolve()``
    follows symlinks (handles e.g. ``/var`` -> ``/private/var`` on macOS); a
    symlink-blind ``normpath`` fallback accepts paths through intentional
    project-internal symlinks (e.g. ``charts/tasks/`` -> ``../../tasks/``).
    Raises ``ValueError`` if neither check places *path* inside the root.
    """
    if not isinstance(project, FilesystemProject):
        raise ValueError(
            "Absolute or '..'-relative board paths require a local filesystem "
            f"project; got {type(project).__name__}."
        )
    root = project.root
    resolved = path.resolve()
    try:
        return posix_relpath(resolved, root)
    except ValueError:
        pass
    normalized = Path(os.path.normpath(path.absolute()))
    try:
        return posix_relpath(normalized, root)
    except ValueError:
        raise ValueError(f"Path {path!r} is outside project root {root!r}") from None


def resolve_board_path(path: Path, project: Project) -> ProjectPath:
    """User/agent-supplied filesystem-shaped board path -> ProjectPath.

    Absolute and ``..``-leading paths are explicit locations: they relativize
    against a concrete ``FilesystemProject`` root (``_relpath_for_fs_location``,
    a leading ``..`` resolving against cwd for CLI shell-nav feel) and are
    returned as-is — no ``charts/`` retry, even when the exact path doesn't
    exist. A bare relative name (no explicit location) delegates to
    ``resolve_board_relpath`` for the boards-first retry, which works against
    any ``Project`` implementation.
    """
    if path.is_absolute():
        relpath = _relpath_for_fs_location(path, project)
    elif ".." in path.parts:
        relpath = _relpath_for_fs_location(
            Path(os.path.normpath(Path.cwd() / path)), project
        )
    else:
        return resolve_board_relpath(PurePosixPath(path), project)
    return project.path(relpath)


def resolve_board_or_error(path: Path, project: Project) -> BoardFile | Diagnostic:
    """Boards-first resolve a path to a stored ``BoardFile``, or a structured error.

    The one agent_api seam turning a user-supplied path into the compiler's
    located input — shared by the CLI render verb and the AI render tool so the
    boards-first retry and the ``ERR-FILE-NOT-FOUND`` envelope never drift
    between surfaces. Returns a ``Diagnostic`` for an escaping path
    (``ERR-INTERNAL``) or a missing board (``ERR-FILE-NOT-FOUND``).
    """
    try:
        resolved = resolve_board_path(path, project)
    except ValueError as exc:
        return DbtChartsError.from_code(ERR_INTERNAL, message=str(exc)).to_diagnostic()
    if not resolved.exists():
        return DbtChartsError.from_code(
            ERR_FILE_NOT_FOUND,
            path=resolved.relpath,
        ).to_diagnostic(file=resolved.relpath)
    if (
        isinstance(project, FilesystemProject)
        and not (project.root / resolved.relpath).is_file()
    ):
        # A directory (or other non-file) resolves + exists on disk but read_board
        # would raise past the structured envelope. This is a filesystem-only
        # concern — a non-filesystem store's `exists()` already gates real boards.
        return DbtChartsError.from_code(
            ERR_INTERNAL, message=f"Not a file: {resolved.relpath}"
        ).to_diagnostic(file=resolved.relpath)
    return resolved.read_board()


@dataclass(frozen=True)
class BoardRenderContext:
    """Path resolution result from a board path + project root.

    Adapter registry is built by `ProjectSession.open`, not by the context — call sites
    open a `ProjectSession` with `project_root` and read the registry off
    `project.adapter_registry`.
    """

    board_file: Path
    scoped_path: Path
    scoped_base: Path
    project_root: Path
    output_dir: Path


def build_board_render_context(
    board_path: Path,
    project_dir: Path,
) -> BoardRenderContext:
    """Resolve a board path against the given project root.

    ``project_dir`` is authoritative. Callers must resolve their project dir first
    (e.g. via ``resolve_project_dir(raw_dir)`` at the CLI boundary).
    """
    if board_path.is_absolute():
        board_file = board_path.resolve()
    elif ".." in board_path.parts:
        board_file = (Path.cwd() / board_path).resolve()
    else:
        board_file = (project_dir / board_path).resolve()

    project_root = project_dir

    try:
        scoped_path: Path = board_file.relative_to(project_root)
    except ValueError:
        raise ValueError(
            f"Board file {board_file} is outside project_dir {project_root}. "
            f"Pass an explicit --project-dir that contains the board file."
        ) from None

    return BoardRenderContext(
        board_file=board_file,
        scoped_path=scoped_path,
        scoped_base=project_root,
        project_root=project_root,
        output_dir=project_root,
    )


@dataclass(frozen=True)
class YamlRenderContext:
    """Path resolution result for rendering inline YAML against a project root.

    Adapter registry is built by `ProjectSession.open`, not by the context.
    """

    project_root: Path
    output_dir: Path


def build_yaml_render_context(
    project_dir: Path,
) -> YamlRenderContext:
    """Resolve the project root for rendering inline YAML.

    ``project_dir`` is authoritative. Callers must resolve their project dir
    first (e.g. via ``resolve_project_dir(raw_dir)`` at the CLI boundary).
    """
    project_root = project_dir.resolve()
    return YamlRenderContext(
        project_root=project_root,
        output_dir=project_root,
    )


@dataclass(frozen=True)
class EditorCompileResult:
    """Result of `compile_editor_buffer`.

    `own_file` is whatever identity string the compile was stamped with —
    `board_path.relpath` on the cascade path, `str(file)` on every fallback
    branch — the value a `Diagnostic`'s `range.file` equals for a finding on
    *this* buffer. A cascade merges other project files (`charts/meta.yml`,
    `extends` targets) into the same compile, and a finding in one of those
    carries that file's own `range.file` instead — the caller compares
    against `own_file` to attribute a foreign-origin finding to the file that
    actually has the problem, rather than squiggling it onto an unrelated
    line of this buffer.
    """

    result: CompileResult
    own_file: str
    config_error: str | None = None


def compile_editor_buffer(content: str, file: Path) -> EditorCompileResult:
    """Compile editor buffer text, applying the meta.yml cascade when ``file``
    sits inside a project.

    Resolves a `Project` from `file`'s ancestry, the same "does a project
    exist here" check the CLI uses (`find_dct_root`), so an editor buffer
    compiles under the same cascade `dct validate`/`dct render` would apply.

    Every fallback branch below drops to the non-cascade `compile()` with no
    `project_sources` — so alongside skipping the folder `meta.yml` cascade
    (`source:`, `extends:`, lint config), a SQL query's dialect is unknown and
    compile stays silent about SQL syntax rather than guessing one (see
    `_sql_parse_warnings`).

    `EditorCompileResult.config_error` is an optional config-load-error
    message for the caller to surface as a *separate* diagnostic — folding a
    broken `dbt_charts.yml` into the compile result would replace every real
    finding on the board with one line-1 error blaming the wrong document.
    """
    # Lazy: core.compile is the heavy stack agent_api's PEP 562 laziness
    # exists to keep out of `import dbt_charts.cli.main` — this module is
    # imported eagerly by cli/_project.py and cli/_workspace_guard.py, so a
    # top-level import here would defeat that (test_lazy_imports.py).
    from dbt_charts.core.compile.compiler import compile as dct_compile, compile_file

    own_file = str(file)
    root = find_dct_root(file.parent)
    if root is None:
        return EditorCompileResult(dct_compile(content, file=own_file), own_file)

    project = FilesystemProject(root)
    try:
        _ = project.sources
        _ = project.cache
    except Exception as exc:  # noqa: BLE001 — attributed below, not swallowed
        return EditorCompileResult(
            dct_compile(content, file=own_file),
            own_file,
            config_error=f"Project dbt_charts.yml could not be loaded: {exc}",
        )

    try:
        board_path = project.path_for_fspath(file)
    except ValueError:
        return EditorCompileResult(
            dct_compile(content, file=own_file),
            own_file,
            config_error=(
                f"{file} is outside project root {root}; folder meta.yml "
                "defaults were not applied"
            ),
        )

    result = compile_file(InMemoryBoard(content, path=board_path))
    return EditorCompileResult(result, board_path.relpath)
