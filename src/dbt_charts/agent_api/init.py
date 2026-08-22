"""Bootstrap (or refresh) a Dataface project layout."""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from dbt_charts.core.project import CHARTS_SUBDIR, PROJECT_CONFIG_NAME

GITIGNORE_ENTRIES = ("renders/", ".venv/", "__pycache__/", "*.duckdb")

_TEMPLATES = importlib.resources.files("dbt_charts.agent_api._init_templates")

# Scaffold path → packaged template filename (None = empty file).
_SCAFFOLD_TEMPLATES: dict[str, str | None] = {
    PROJECT_CONFIG_NAME: PROJECT_CONFIG_NAME,
    f"{CHARTS_SUBDIR}/README.md": "README.md",
    f"{CHARTS_SUBDIR}/guide.yaml": "guide.yaml",
    f"{CHARTS_SUBDIR}/meta.yaml": "meta.yaml",
    f"{CHARTS_SUBDIR}/partials/.gitkeep": None,
}

# Every path init_project may write. A caller that runs init_project against a
# materialized partial tree (Cloud's scaffold task builds one in a temp dir)
# must seed these paths with the real repo's versions first — otherwise the
# skip/merge protections see an empty tree and recreate everything from
# templates.
SCAFFOLD_PATHS: tuple[str, ...] = (*_SCAFFOLD_TEMPLATES, ".gitignore")


class InitResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_dir: Path
    dbt_detected: bool
    created_files: list[Path] = []
    skipped_files: list[Path] = []
    refreshed_files: list[Path] = []
    hints: list[str] = []


def init_project(
    project_dir: Path | None = None,
    *,
    force: bool = False,
    eject_inspect: bool = False,
) -> InitResult:
    """Bootstrap (or refresh) a Dataface project layout.

    Safe to re-run: scaffold files are skipped unless *force* is set.
    Agent markdown is never written; agent onboarding lives in installed skills.
    """
    root = (project_dir or Path()).resolve()
    dbt_detected = (root / "dbt_project.yml").exists()

    result = InitResult(project_dir=root, dbt_detected=dbt_detected)

    (root / CHARTS_SUBDIR).mkdir(exist_ok=True)
    (root / CHARTS_SUBDIR / "partials").mkdir(exist_ok=True)

    scaffolds: list[tuple[str, str]] = [
        (
            rel,
            ""
            if template is None
            else _TEMPLATES.joinpath(template).read_text(encoding="utf-8"),
        )
        for rel, template in _SCAFFOLD_TEMPLATES.items()
    ]

    for rel, content in scaffolds:
        target = root / rel
        if target.exists() and not force:
            result.skipped_files.append(Path(rel))
        elif target.exists():
            target.write_text(content, encoding="utf-8")
            result.refreshed_files.append(Path(rel))
        else:
            target.write_text(content, encoding="utf-8")
            result.created_files.append(Path(rel))

    _ensure_gitignore_entries(root, result)

    if eject_inspect:
        from dbt_charts.agent_api import inspect as _api_inspect

        try:
            ejected = _api_inspect.eject_templates(
                root / CHARTS_SUBDIR / "inspect", templates=None, force=False
            )
            result.created_files.extend(p.relative_to(root) for p in ejected)
        except (FileNotFoundError, ModuleNotFoundError) as exc:
            result.hints.append(
                f"warning: inspect templates could not be ejected ({exc!r}); "
                "your install may be partial. Run 'pip show dbt-charts' to verify."
            )

    return result


def _ensure_gitignore_entries(root: Path, result: InitResult) -> None:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("\n".join(GITIGNORE_ENTRIES) + "\n", encoding="utf-8")
        result.created_files.append(Path(".gitignore"))
        return

    text = gitignore.read_text(encoding="utf-8")
    existing = set(text.splitlines())
    missing = [e for e in GITIGNORE_ENTRIES if e not in existing]
    if not missing:
        return

    separator = "" if not text or text.endswith("\n") else "\n"
    gitignore.write_text(
        f"{text}{separator}" + "\n".join(missing) + "\n", encoding="utf-8"
    )
    result.refreshed_files.append(Path(".gitignore"))
