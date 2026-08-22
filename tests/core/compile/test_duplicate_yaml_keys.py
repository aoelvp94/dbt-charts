from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.compile.errors import ParseError
from dbt_charts.core.compile.parse.parser import load_yaml_mapping


def test_duplicate_top_level_key_raises() -> None:
    yaml = "style:\n  color: red\ntitle: Foo\nstyle:\n  color: blue\n"
    with pytest.raises(ParseError, match="duplicate key"):
        load_yaml_mapping(yaml)


def test_duplicate_nested_key_raises() -> None:
    yaml = "charts:\n  rev:\n    type: bar\n    x: month\n    x: week\n"
    with pytest.raises(ParseError, match="duplicate key"):
        load_yaml_mapping(yaml)


def test_no_duplicate_keys_parses_normally() -> None:
    yaml = "title: Foo\nstyle:\n  color: red\n"
    result = load_yaml_mapping(yaml)
    assert result["title"] == "Foo"


def test_int_key_and_quoted_string_key_are_distinct() -> None:
    # 1: and "1": resolve to different Python types — must not be flagged as duplicate
    result = load_yaml_mapping('1: a\n"1": b\n')
    assert result[1] == "a"
    assert result["1"] == "b"


def test_non_hashable_complex_key_raises_parse_error_not_type_error() -> None:
    # Sequence keys are unhashable. Our TypeError guard lets the error propagate through
    # super().construct_mapping() as a ConstructorError → ParseError, not a bare TypeError.
    with pytest.raises(ParseError):
        load_yaml_mapping("? [a, b]\n: value\n")


def test_merge_key_override_is_not_flagged_as_duplicate() -> None:
    # A merge anchor + explicit override is valid YAML; must not raise.
    yaml_str = "base: &b\n  x: 1\nderived:\n  <<: *b\n  x: 99\n"
    result = load_yaml_mapping(yaml_str)
    assert result["derived"]["x"] == 99


def test_project_read_yaml_rejects_duplicate_key(
    tmp_path: Path, local_project: Callable[..., FilesystemProject]
) -> None:
    board = tmp_path / "charts" / "bad.yaml"
    board.parent.mkdir()
    board.write_text("title: Foo\ntitle: Bar\n")
    project = local_project(tmp_path)
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        project.read_yaml("charts/bad.yaml")
