"""Pre-rename projects keep rendering: a store with only a physical ``faces/``
directory answers every canonical ``charts/`` path from it.

The faces/ -> charts/ directory rename shipped without a read fallback, so
existing projects (Cloud-connected repos, local checkouts) listed no boards at
all. The fix is a *store-level* translation in ``FilesystemProject``: when the
project has no ``charts/`` directory but does have ``faces/``, every
``charts/``-prefixed access maps to the physical ``faces/`` tree and listings
are rewritten back to the canonical prefix. Consumers never see ``faces/``;
``charts/`` wins outright when both exist (never merged); nothing ever
*creates* ``faces/``.
"""

from pathlib import Path

from dbt_charts.cli.filesystem_project import FilesystemProject

FACE_YAML = "title: Revenue\ncharts:\n  c1:\n    type: bar\n    x: a\n    y: b\n"


def _faces_project(tmp_path: Path) -> FilesystemProject:
    (tmp_path / "dataface.yml").write_text("name: legacy\n", encoding="utf-8")
    faces = tmp_path / "faces"
    (faces / "sub").mkdir(parents=True)
    (faces / "revenue.yml").write_text(FACE_YAML, encoding="utf-8")
    (faces / "sub" / "nested.yml").write_text(FACE_YAML, encoding="utf-8")
    return FilesystemProject(tmp_path)


def test_faces_only_project_answers_charts_paths(tmp_path: Path) -> None:
    project = _faces_project(tmp_path)

    assert project.exists("charts/revenue.yml")
    assert project.read_text("charts/revenue.yml") == FACE_YAML
    assert project.read_bytes("charts/sub/nested.yml") == FACE_YAML.encode()
    assert project.file_version("charts/revenue.yml")


def test_faces_only_project_lists_boards_under_canonical_prefix(
    tmp_path: Path,
) -> None:
    project = _faces_project(tmp_path)

    listed = sorted(p.relpath for p in project.iter_boards())
    assert listed == ["charts/revenue.yml", "charts/sub/nested.yml"]


def test_charts_wins_outright_when_both_directories_exist(tmp_path: Path) -> None:
    project = _faces_project(tmp_path)
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "only.yml").write_text(FACE_YAML, encoding="utf-8")

    listed = sorted(p.relpath for p in project.iter_boards())
    assert listed == ["charts/only.yml"]
    assert not project.exists("charts/revenue.yml")


def test_write_through_fallback_lands_in_faces_never_creates_charts(
    tmp_path: Path,
) -> None:
    project = _faces_project(tmp_path)

    project.write_text("charts/new.yml", FACE_YAML)

    assert (tmp_path / "faces" / "new.yml").read_text(encoding="utf-8") == FACE_YAML
    assert not (tmp_path / "charts").exists()


def test_non_charts_paths_are_untouched_by_the_fallback(tmp_path: Path) -> None:
    project = _faces_project(tmp_path)
    (tmp_path / "chartsy").mkdir()
    (tmp_path / "chartsy" / "x.txt").write_text("x\n", encoding="utf-8")

    assert project.read_text("dataface.yml") == "name: legacy\n"
    # Prefix match is on the path segment, not the string prefix.
    assert project.read_text("chartsy/x.txt") == "x\n"
