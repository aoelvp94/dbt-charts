"""`published_to:` -- parsing, the nearest-file lookup, the local write target,
and the textual splice that writes it into dbt_charts.yml.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from dbt_charts.cloud_client.published_to import (
    EXPECTED_FORM,
    PublishedTo,
    find_local_project_dir,
    parse_published_to,
    published_to_url,
    resolve_published_to,
    set_published_to,
)
from dbt_charts.core.compile.config import get_config
from dbt_charts.core.compile.models.config import Config


class TestPublishedToUrl:
    def test_builds_the_slashed_project_home_url(self) -> None:
        """Cloud mounts the project at `/<org>/<project>/` and runs with
        APPEND_SLASH off, so the unslashed form is not a page."""
        assert (
            published_to_url("https://dbtcharts.com", "acme-data", "analytics")
            == "https://dbtcharts.com/acme-data/analytics/"
        )

    def test_refuses_to_build_a_value_the_parser_would_reject(self) -> None:
        """A path-bearing --host would write a three-segment value that
        `Config` then rejects, breaking `dct render` for the whole project."""
        with pytest.raises(ValueError, match="published_to must be"):
            published_to_url("https://example.com/dct", "acme-data", "analytics")


class TestParsePublishedTo:
    def test_parses_host_org_project(self) -> None:
        assert parse_published_to("https://dbtcharts.com/acme-data/analytics/") == (
            "https://dbtcharts.com",
            "acme-data",
            "analytics",
        )

    def test_reads_a_hand_written_value_without_the_trailing_slash(self) -> None:
        assert parse_published_to("https://dbtcharts.com/acme-data/analytics") == (
            "https://dbtcharts.com",
            "acme-data",
            "analytics",
        )

    @pytest.mark.parametrize(
        "value",
        [
            "acme-data/analytics",
            "https://dbtcharts.com/acme-data/",
            "https://dbtcharts.com/acme-data/analytics/extra/",
            "ftp://dbtcharts.com/acme-data/analytics",
            "https://dbtcharts.com/",
            "",
        ],
    )
    def test_rejects_anything_but_an_absolute_org_project_url(self, value: str) -> None:
        with pytest.raises(ValueError, match=re.escape(EXPECTED_FORM)):
            parse_published_to(value)


class TestResolvePublishedTo:
    def test_none_with_no_dbt_charts_yml_above(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        assert resolve_published_to(nested) is None

    def test_none_when_the_nearest_file_declares_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text("cache:\n  path: x\n")
        assert resolve_published_to(tmp_path) is None

    def test_reads_the_declared_value(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text(
            'published_to: "https://dbtcharts.com/acme-data/analytics/"\n'
        )

        result = resolve_published_to(tmp_path)

        assert result == PublishedTo(
            yml_path=tmp_path / "dbt_charts.yml",
            host="https://dbtcharts.com",
            org="acme-data",
            project="analytics",
        )

    def test_walks_up_to_the_nearest_file_only(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text(
            'published_to: "https://dbtcharts.com/outer/outer"\n'
        )
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "dbt_charts.yml").write_text("cache:\n  path: x\n")

        result = resolve_published_to(nested)

        assert result is None  # nearest file declares nothing; never keeps walking

    def test_raises_naming_the_file_on_a_malformed_value(self, tmp_path: Path) -> None:
        yml_path = tmp_path / "dbt_charts.yml"
        yml_path.write_text('published_to: "not-a-url"\n')

        with pytest.raises(ValueError, match=re.escape(str(yml_path))):
            resolve_published_to(tmp_path)

    @pytest.mark.parametrize(
        "line", ['published_to: ""', "published_to: 42", "published_to: [a, b]"]
    )
    def test_raises_naming_the_file_on_an_empty_or_non_string_value(
        self, tmp_path: Path, line: str
    ) -> None:
        """A cleared or mistyped value is a half-edited record: Config rejects
        it, so the CLI must too, never fall through to the git remote."""
        yml_path = tmp_path / "dbt_charts.yml"
        yml_path.write_text(line + "\n")

        with pytest.raises(ValueError, match=re.escape(str(yml_path))):
            resolve_published_to(tmp_path)

    def test_raises_naming_the_file_on_a_duplicate_key(self, tmp_path: Path) -> None:
        """The project loader rejects duplicate keys; reading last-wins here
        would make `dct cloud status` answer from a file `dct render` refuses."""
        yml_path = tmp_path / "dbt_charts.yml"
        yml_path.write_text(
            'published_to: "https://a.example/o/p/"\n'
            'published_to: "https://b.example/o/p/"\n'
        )

        with pytest.raises(ValueError, match=re.escape(str(yml_path))):
            resolve_published_to(tmp_path)

    def test_reads_a_file_with_merge_keys(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_charts.yml").write_text(
            "defaults: &d\n  strict: true\n"
            "execution:\n  <<: *d\n"
            'published_to: "https://dbtcharts.com/acme-data/analytics/"\n'
        )

        assert resolve_published_to(tmp_path) is not None

    def test_raises_naming_the_file_on_an_unhashable_key(self, tmp_path: Path) -> None:
        yml_path = tmp_path / "dbt_charts.yml"
        yml_path.write_text("? [a, b]\n: 1\n")

        with pytest.raises(ValueError, match=re.escape(str(yml_path))):
            resolve_published_to(tmp_path)

    def test_stops_at_a_dbt_root_without_dbt_charts_yml(self, tmp_path: Path) -> None:
        """A nested dbt root is its own project; answering with the ancestor's
        record would act on a sibling's boards. None lets resolution fall back
        to the exact-match-or-error repo step."""
        (tmp_path / "dbt_charts.yml").write_text(
            'published_to: "https://dbtcharts.com/acme-data/analytics/"\n'
        )
        nested = tmp_path / "analytics"
        nested.mkdir()
        (nested / "dbt_project.yml").write_text("name: analytics\n")

        assert resolve_published_to(nested) is None
        assert resolve_published_to(tmp_path) is not None

    def test_raises_naming_the_file_on_unparseable_yaml(self, tmp_path: Path) -> None:
        """Every `dct cloud` verb resolves through here, so a half-edited
        dbt_charts.yml must be a reportable error, not a YAMLError traceback."""
        yml_path = tmp_path / "dbt_charts.yml"
        yml_path.write_text("published_to: [unclosed\n")

        with pytest.raises(ValueError, match=re.escape(str(yml_path))):
            resolve_published_to(tmp_path)

    def test_raises_naming_the_file_on_undecodable_bytes(self, tmp_path: Path) -> None:
        yml_path = tmp_path / "dbt_charts.yml"
        yml_path.write_bytes(b"published_to: \xff\xfe\n")

        with pytest.raises(ValueError, match=re.escape(str(yml_path))):
            resolve_published_to(tmp_path)

    def test_a_directory_of_that_name_is_not_a_config_file(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "dbt_charts.yml").mkdir()

        assert resolve_published_to(tmp_path) is None


class TestFindLocalProjectDir:
    def test_none_outside_a_git_checkout(self, tmp_path: Path) -> None:
        assert find_local_project_dir(tmp_path, "") is None

    def test_repo_root_with_no_subdirectory(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()

        assert find_local_project_dir(tmp_path, "") == tmp_path

    def test_descends_into_the_git_subdirectory(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "analytics" / "dbt"
        nested.mkdir(parents=True)

        assert find_local_project_dir(tmp_path, "analytics/dbt") == nested

    def test_walks_up_from_a_subdirectory_to_find_git(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        cwd = tmp_path / "analytics" / "dbt"
        cwd.mkdir(parents=True)

        assert find_local_project_dir(cwd, "") == tmp_path

    @pytest.mark.parametrize(
        "subdirectory", ["../outside", "/etc", "C:foo", "dbt\\..\\outside"]
    )
    def test_raises_when_the_subdirectory_escapes_the_repo_root(
        self, tmp_path: Path, subdirectory: str
    ) -> None:
        (tmp_path / ".git").mkdir()

        with pytest.raises(ValueError, match="escapes"):
            find_local_project_dir(tmp_path, subdirectory)

    def test_accepts_a_symlinked_dbt_root(self, tmp_path: Path) -> None:
        """`repo/dbt -> /elsewhere/real` is a legitimate checkout layout: the
        escape check is about the declared subdirectory, not where the
        filesystem sends it."""
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (repo / "dbt").symlink_to(elsewhere, target_is_directory=True)

        assert find_local_project_dir(repo, "dbt") == repo / "dbt"


class TestSetPublishedTo:
    URL = "https://dbtcharts.com/acme-data/analytics"

    @pytest.mark.parametrize("key", ['"published_to"', "'published_to'"])
    def test_replaces_a_quoted_key_in_place(self, key: str) -> None:
        text = f'cache: false\n{key}: "https://old.example/o/p/"\nstrict: true\n'

        out = set_published_to(text, self.URL)

        assert out == f'cache: false\npublished_to: "{self.URL}"\nstrict: true\n'

    def test_refuses_a_layout_it_would_duplicate(self) -> None:
        """A complex-key spelling is not matched by the splice; appending a
        second key would read back fine under last-wins but break the project
        loader, so it must be refused rather than written."""
        text = '? published_to\n: "https://old.example/o/p/"\n'

        with pytest.raises(ValueError, match="duplicate key"):
            set_published_to(text, self.URL)

    def test_keeps_a_merge_key_file_editable(self) -> None:
        """`<<: *anchor` is legal in dbt_charts.yml and the project loader
        accepts it; the duplicate-key check must not choke on the merge tag."""
        text = "defaults: &d\n  strict: true\nexecution:\n  <<: *d\n  max_rows: 10\n"

        out = set_published_to(text, self.URL)

        assert out.endswith(f'published_to: "{self.URL}"\n')

    def test_appends_to_a_file_with_no_published_to(self) -> None:
        text = "cache:\n  path: x\n"

        result = set_published_to(text, self.URL)

        assert result == f'cache:\n  path: x\n\npublished_to: "{self.URL}"\n'

    def test_appends_to_an_empty_file(self) -> None:
        assert set_published_to("", self.URL) == f'published_to: "{self.URL}"\n'

    def test_replaces_an_existing_value_in_place(self) -> None:
        text = (
            "# a hand-written comment\n"
            'published_to: "https://dbtcharts.com/old-org/old-project"\n'
            "cache:\n  path: x\n"
        )

        result = set_published_to(text, self.URL)

        assert result == (
            f'# a hand-written comment\npublished_to: "{self.URL}"\ncache:\n  path: x\n'
        )

    def test_preserves_comments_and_key_order_elsewhere_in_the_file(self) -> None:
        text = (
            "# top comment\n"
            "sources:\n"
            "  warehouse:\n"
            "    type: bigquery  # inline comment\n"
        )

        result = set_published_to(text, self.URL)

        assert "# top comment" in result
        assert "# inline comment" in result
        assert result.index("sources:") < result.index("published_to:")

    def test_preserves_crlf_line_endings_when_replacing(self) -> None:
        """Verification only reads back the one key, so a wholesale rewrite of
        every other line would pass unnoticed."""
        text = 'published_to: "https://dbtcharts.com/old/old/"\r\ncache: 1\r\n'

        result = set_published_to(text, self.URL)

        assert result == f'published_to: "{self.URL}"\r\ncache: 1\r\n'

    def test_replaces_through_a_utf8_bom(self) -> None:
        """PyYAML's last-wins would make a second top-level key verify fine,
        and the next connect on that file could no longer edit it."""
        text = '\ufeffpublished_to: "https://dbtcharts.com/old/old/"\ncache: 1\n'

        result = set_published_to(text, self.URL)

        assert result == f'\ufeffpublished_to: "{self.URL}"\ncache: 1\n'
        assert result.count("published_to:") == 1


class TestUrlGrammarParity:
    """`Config._validate_published_to` (core, author-facing) and
    `parse_published_to` (cloud_client, write-facing) are the same rule
    written twice -- tach forbids cloud_client importing core, so nothing but
    this pins them together. The connect that writes a value core rejects
    breaks `dct render` for the whole project.
    """

    @pytest.mark.parametrize(
        "value",
        [
            "https://dbtcharts.com/acme-data/analytics/",
            "https://dbtcharts.com/acme-data/analytics",
            "http://localhost:8000/acme-data/analytics/",
        ],
    )
    def test_both_surfaces_accept(self, value: str) -> None:
        parse_published_to(value)
        assert _config_with(value).published_to == value

    @pytest.mark.parametrize(
        "value",
        [
            "acme-data/analytics",
            "https://dbtcharts.com/acme-data/",
            "https://dbtcharts.com/acme-data/analytics/extra/",
            "ftp://dbtcharts.com/acme-data/analytics/",
            "https://dbtcharts.com/",
            "",
        ],
    )
    def test_both_surfaces_reject(self, value: str) -> None:
        with pytest.raises(ValueError, match=re.escape(EXPECTED_FORM)):
            parse_published_to(value)
        with pytest.raises(ValidationError, match=re.escape(EXPECTED_FORM)):
            _config_with(value)


def _config_with(value: str) -> Config:
    compiled = get_config().to_plain_dict(exclude_none=False)
    compiled["published_to"] = value
    return Config.model_validate(compiled)
