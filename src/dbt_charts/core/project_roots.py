"""Shared project/dbt root discovery used by render and MCP commands.

The reads here are deliberately NOT routed through the Project file-access
seam. find_root/find_dct_root/find_project_root walk *up* the filesystem from
cwd to locate the root — there is no project yet at that point. resolve_profiles_path / infer_dialect_from_dbt read dbt
profiles.yml from $DBT_PROFILES_DIR / ~/.dbt / project-local, i.e. paths outside
the project root that a project-relative plugin cannot address. Cloud supplies
the dbt connection config by another path; these stay filesystem-coupled.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path  # noqa: TID251 — walks disk to find the project root

import yaml

from dbt_charts.core.project import PROJECT_CONFIG_NAME

logger = logging.getLogger(__name__)

REPO_MARKERS = (".git",)
DCT_ROOT_MARKERS = (PROJECT_CONFIG_NAME, "dbt_project.yml")
_SERVE_ONLY_CONFIG_KEYS = {"server"}


def find_root(start: Path | None, markers: tuple[str, ...]) -> Path | None:
    """Walk up from *start* (default cwd); return the first dir with any marker, else None."""
    current = (start or Path.cwd()).resolve()
    while True:
        if any((current / marker).exists() for marker in markers):
            return current
        if current.parent == current:
            return None
        current = current.parent


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default cwd) to the repo root (dir containing ``.git``), else None.

    Locates where editor/AI-client config lives (``.cursor/``, ``.vscode/``, skill
    dirs) — distinct from the dbt charts project root.
    """
    return find_root(start, REPO_MARKERS)


def find_dbt_charts_dir() -> Path:
    """Return the dbt-charts/ package root (contains ``pyproject.toml`` + ``src/dbt_charts/``).

    Derived from the installed ``dbt_charts`` package location, not a git-root
    walk — resolves identically inside the monorepo and after a standalone OSS
    export, where dbt-charts/ IS the checkout root.
    """
    import dbt_charts

    pkg_file = dbt_charts.__file__
    assert pkg_file is not None
    candidate = Path(pkg_file).resolve().parent
    while not (
        (candidate / "pyproject.toml").exists()
        and (candidate / "src" / "dbt_charts").is_dir()
    ):
        if candidate.parent == candidate:
            raise RuntimeError(
                "Could not locate the dbt-charts package root "
                "(expected an ancestor with both pyproject.toml and src/dbt_charts)"
            )
        candidate = candidate.parent
    return candidate


def find_dct_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default cwd) to the dbt charts project root, else None.

    The root is the nearest ancestor with a ``dbt_charts.yml`` / ``dbt_project.yml``.
    Returns None outside a dbt charts project; callers that want a fallback append
    ``or Path.cwd()``.
    """
    return find_root(start, DCT_ROOT_MARKERS)


def _has_render_project_config(path: Path) -> bool:
    """Return True when dbt_charts.yml contains render-relevant project config."""
    config_path = path / PROJECT_CONFIG_NAME
    if not config_path.exists():
        return False
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return True
    return not (
        isinstance(data, dict) and data and set(data) <= _SERVE_ONLY_CONFIG_KEYS
    )


def find_project_root(
    start_dir: Path,
    boundary: Path | None,
) -> Path:
    """Walk upward from ``start_dir`` to find the project root for a render request.

    The project root is the nearest ancestor that contains a non-serve-only
    ``dbt_charts.yml``.

    If ``boundary`` is None, walks until the filesystem root. If set, stops after
    processing the ``boundary`` directory (inclusive).
    """
    start_resolved = start_dir.resolve()
    current = start_resolved
    boundary_resolved = boundary.resolve() if boundary is not None else None

    while True:
        if _has_render_project_config(current):
            return current

        if current.parent == current:
            break
        if boundary_resolved is not None and current == boundary_resolved:
            break

        current = current.parent

    return boundary_resolved or start_resolved


def resolve_profiles_path(
    project_dir: Path,
    profiles_dir: Path | None,
) -> Path:
    """Locate profiles.yml using the canonical resolution order.

    Resolution order:
      1. ``profiles_dir/profiles.yml`` — explicit field from DbtProfileSourceConfig
      2. ``$DBT_PROFILES_DIR/profiles.yml`` — env var
      3. ``project_dir/profiles.yml`` — project-local
      4. ``~/.dbt/profiles.yml`` — global fallback

    Raises ``FileNotFoundError`` with a clear message when none contains
    profiles.yml. Never falls back silently past a candidate that was
    explicitly named (profiles_dir set but missing → error, not next step).

    Args:
        project_dir: The dbt charts project root (where dbt_charts.yml lives).
        profiles_dir: Explicit directory from the ``profiles_dir`` source field,
            already resolved to an absolute Path. None means not set.
    """
    # Step 1: explicit profiles_dir from source config — no fallback when set
    if profiles_dir is not None:
        candidate = profiles_dir / "profiles.yml"
        if candidate.exists():
            return candidate
        raise FileNotFoundError(
            f"profiles_dir={profiles_dir!r} does not contain profiles.yml. "
            "Create profiles.yml there or remove the profiles_dir field."
        )

    # Step 2: DBT_PROFILES_DIR env var — no fallback when set
    env_dir = os.environ.get("DBT_PROFILES_DIR")  # noqa: TID251 — dbt-convention parity
    if env_dir:
        candidate = Path(env_dir) / "profiles.yml"
        if candidate.exists():
            return candidate
        raise FileNotFoundError(
            f"DBT_PROFILES_DIR={env_dir!r} does not contain profiles.yml. "
            "Create profiles.yml there or unset DBT_PROFILES_DIR."
        )

    # Step 3: project-local profiles.yml
    candidate = project_dir / "profiles.yml"
    if candidate.exists():
        return candidate

    # Step 4: global ~/.dbt/profiles.yml
    candidate = Path.home() / ".dbt" / "profiles.yml"
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"No profiles.yml found. Checked: {project_dir}/profiles.yml, ~/.dbt/profiles.yml. "
        "Set profiles_dir in your dbt_profile source or export DBT_PROFILES_DIR."
    )


def infer_dialect_from_dbt(
    project_dir: Path,
    target_name: str | None = None,
) -> str | None:
    """Read the resolved dbt profile target and return its adapter ``type``.

    Resolution order for profiles.yml: profiles_dir field → DBT_PROFILES_DIR
    → project_dir → ~/.dbt. See resolve_profiles_path.

    Returns ``None`` when the dbt project or profile cannot be resolved.
    """
    import yaml

    dbt_project_path = project_dir / "dbt_project.yml"
    if not dbt_project_path.exists():
        return None

    try:
        dbt_config = yaml.safe_load(dbt_project_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None

    profile_name = dbt_config.get("profile")
    if not profile_name:
        return None

    try:
        profiles_path = resolve_profiles_path(project_dir, profiles_dir=None)
    except FileNotFoundError:
        return None

    try:
        profiles = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None

    profile = profiles.get(profile_name, {})
    target = target_name or profile.get("target", "dev")
    target_config = profile.get("outputs", {}).get(target, {})
    return target_config.get("type")
