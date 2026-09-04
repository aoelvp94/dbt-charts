"""Per-invocation context resolution: flags, then the repo, then the default.

Never a guess — an ambiguous repo lists its candidates and refuses.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from dbt_charts.cloud_client.client import CloudClient
from dbt_charts.cloud_client.config import CloudConfig
from dbt_charts.cloud_client.context import (
    git_remotes,
    repo_key,
    resolve_org,
    resolve_project,
)
from dbt_charts.cloud_client.errors import ContextUnresolved

Handler = Callable[[httpx.Request], httpx.Response]

ORGS = {
    "organizations": [
        {"slug": "acme-data", "name": "Acme Data", "role": "ADMIN"},
        {"slug": "other-co", "name": "Other Co", "role": "MEMBER"},
    ]
}


def _project(slug: str, repo_label: str) -> dict[str, object]:
    return {
        "slug": slug,
        "name": slug,
        "repo_label": repo_label,
        "trunk_branch": "main",
        "work_branch": f"dbt-charts/{slug}",
        "git_subdirectory": "",
        "unmapped_source_count": 0,
    }


PROJECTS = {
    "/api/orgs/acme-data/projects": {
        "projects": [
            _project("analytics", "GitHub: acme/analytics"),
            _project("marts", "https://gitlab.com/acme/marts.git"),
        ]
    },
    "/api/orgs/other-co/projects": {
        "projects": [_project("elsewhere", "GitHub: other/elsewhere")]
    },
}


def cloud(handler: Handler | None = None) -> CloudClient:
    def default(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/orgs":
            return httpx.Response(200, json=ORGS)
        return httpx.Response(200, json=PROJECTS[request.url.path])

    return CloudClient(
        host="https://cloud.example",
        token="t0ken",
        transport=httpx.MockTransport(handler or default),
    )


class TestRepoKey:
    @pytest.mark.parametrize(
        "url",
        [
            "git@github.com:acme/analytics.git",
            "https://github.com/acme/analytics",
            "https://github.com/acme/analytics.git",
            "https://dave:token@github.com/acme/analytics.git",
            "ssh://git@github.com/acme/analytics.git",
            "GitHub: acme/analytics",
        ],
    )
    def test_every_spelling_of_one_repo_shares_a_key(self, url: str) -> None:
        assert repo_key(url) == "github.com/acme/analytics"

    def test_a_non_github_remote_keeps_its_host(self) -> None:
        assert repo_key("https://gitlab.com/acme/marts.git") == "gitlab.com/acme/marts"


class TestResolveProject:
    def test_flags_win_without_asking_the_api(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("explicit flags need no lookup")

        with cloud(handler) as client:
            context = resolve_project(
                client,
                org_flag="acme-data",
                project_flag="analytics",
                config=CloudConfig(org="ignored", project="ignored"),
                remotes=["git@github.com:acme/analytics.git"],
            )
        assert (context.org, context.project) == ("acme-data", "analytics")

    def test_an_exact_remote_match_beats_the_stored_default(self) -> None:
        with cloud() as client:
            context = resolve_project(
                client,
                org_flag=None,
                project_flag=None,
                config=CloudConfig(org="other-co", project="elsewhere"),
                remotes=["git@github.com:acme/analytics.git"],
            )
        assert (context.org, context.project) == ("acme-data", "analytics")

    def test_the_stored_default_answers_when_the_repo_matches_nothing(self) -> None:
        with cloud() as client:
            context = resolve_project(
                client,
                org_flag=None,
                project_flag=None,
                config=CloudConfig(org="other-co", project="elsewhere"),
                remotes=["git@github.com:someone/unrelated.git"],
            )
        assert (context.org, context.project) == ("other-co", "elsewhere")

    def test_strict_refuses_the_stored_default_when_the_repo_matches_nothing(
        self,
    ) -> None:
        """HIGH-6: a destructive verb must not silently delete against a
        stale `dct cloud use` default just because the repo it happens to
        be run from matches nothing."""
        with cloud() as client, pytest.raises(ContextUnresolved) as caught:
            resolve_project(
                client,
                org_flag=None,
                project_flag=None,
                config=CloudConfig(org="other-co", project="elsewhere"),
                remotes=["git@github.com:someone/unrelated.git"],
                strict=True,
            )

        message = str(caught.value)
        assert "destructive" in message
        assert "--org" in message

    def test_strict_still_honors_an_exact_repo_match(self) -> None:
        with cloud() as client:
            context = resolve_project(
                client,
                org_flag=None,
                project_flag=None,
                config=CloudConfig(org="other-co", project="elsewhere"),
                remotes=["git@github.com:acme/analytics.git"],
                strict=True,
            )
        assert (context.org, context.project) == ("acme-data", "analytics")

    def test_strict_still_honors_explicit_flags(self) -> None:
        with cloud() as client:
            context = resolve_project(
                client,
                org_flag="other-co",
                project_flag="elsewhere",
                config=CloudConfig(),
                remotes=[],
                strict=True,
            )
        assert (context.org, context.project) == ("other-co", "elsewhere")

    def test_an_ambiguous_repo_lists_candidates_and_refuses(self) -> None:
        two_roots = {
            "/api/orgs/acme-data/projects": {
                "projects": [
                    _project("analytics", "GitHub: acme/analytics"),
                    _project("finance", "GitHub: acme/analytics"),
                ]
            },
            "/api/orgs/other-co/projects": {"projects": []},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/orgs":
                return httpx.Response(200, json=ORGS)
            return httpx.Response(200, json=two_roots[request.url.path])

        with cloud(handler) as client, pytest.raises(ContextUnresolved) as caught:
            resolve_project(
                client,
                org_flag=None,
                project_flag=None,
                config=CloudConfig(),
                remotes=["git@github.com:acme/analytics.git"],
            )

        message = str(caught.value)
        assert "--org acme-data --project analytics" in message
        assert "--org acme-data --project finance" in message

    def test_nothing_to_go_on_is_an_actionable_error(self) -> None:
        with cloud() as client, pytest.raises(ContextUnresolved) as caught:
            resolve_project(
                client,
                org_flag=None,
                project_flag=None,
                config=CloudConfig(),
                remotes=[],
            )

        message = str(caught.value)
        assert "dct cloud use" in message
        assert "--org acme-data --project analytics" in message

    def test_naming_only_a_project_asks_for_the_org_not_the_project(self) -> None:
        """Bug: `--project X` with no resolvable org answered "No project
        selected", telling the caller to supply what they had just supplied.
        The org is the missing half, so the org refusal is the useful one."""
        with cloud() as client, pytest.raises(ContextUnresolved) as caught:
            resolve_project(
                client,
                org_flag=None,
                project_flag="analytics",
                config=CloudConfig(),
                remotes=[],
            )

        message = str(caught.value)
        assert "No organization selected" in message
        assert "No project selected" not in message

    def test_a_stale_stored_org_does_not_get_queried_while_composing_the_error(
        self,
    ) -> None:
        """Bug: the stored `dct cloud use` default is never validated against
        Cloud -- composing the "no project" refusal must not blindly query
        `list_projects` for it, or a deleted/typo'd org turns an actionable
        ContextUnresolved into a confusing ApiFailed instead."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/orgs":
                return httpx.Response(200, json=ORGS)
            if request.url.path == "/api/orgs/deleted-org/projects":
                raise AssertionError(
                    "must not query list_projects for an unvalidated stored org"
                )
            return httpx.Response(200, json=PROJECTS[request.url.path])

        with cloud(handler) as client, pytest.raises(ContextUnresolved) as caught:
            resolve_project(
                client,
                org_flag=None,
                project_flag=None,
                config=CloudConfig(org="deleted-org", project=""),
                remotes=[],
            )

        message = str(caught.value)
        assert "acme-data" in message
        assert "other-co" in message

    def test_an_org_flag_narrows_the_repo_search_to_that_org(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json=PROJECTS[request.url.path])

        with cloud(handler) as client:
            context = resolve_project(
                client,
                org_flag="acme-data",
                project_flag=None,
                config=CloudConfig(),
                remotes=["https://gitlab.com/acme/marts.git"],
            )

        assert (context.org, context.project) == ("acme-data", "marts")
        assert seen == ["/api/orgs/acme-data/projects"]


class TestResolveOrg:
    def test_flag_wins(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("explicit flag needs no lookup")

        with cloud(handler) as client:
            assert (
                resolve_org(
                    client, org_flag="acme-data", config=CloudConfig(), remotes=[]
                )
                == "acme-data"
            )

    def test_the_repo_names_the_org(self) -> None:
        with cloud() as client:
            org = resolve_org(
                client,
                org_flag=None,
                config=CloudConfig(org="other-co"),
                remotes=["git@github.com:acme/analytics.git"],
            )
        assert org == "acme-data"

    def test_the_stored_default_answers_with_no_repo(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("a stored default needs no lookup")

        with cloud(handler) as client:
            assert (
                resolve_org(
                    client,
                    org_flag=None,
                    config=CloudConfig(org="other-co"),
                    remotes=[],
                )
                == "other-co"
            )

    def test_strict_refuses_the_stored_default_with_no_repo_match(self) -> None:
        """HIGH-6: org delete/connection delete must not fall back to a
        stale `dct cloud use` default with no repo evidence at all."""
        with cloud() as client, pytest.raises(ContextUnresolved) as caught:
            resolve_org(
                client,
                org_flag=None,
                config=CloudConfig(org="other-co"),
                remotes=[],
                strict=True,
            )

        assert "destructive" in str(caught.value)

    def test_strict_still_honors_the_repo_match(self) -> None:
        with cloud() as client:
            org = resolve_org(
                client,
                org_flag=None,
                config=CloudConfig(org="other-co"),
                remotes=["git@github.com:acme/analytics.git"],
                strict=True,
            )
        assert org == "acme-data"

    def test_a_repo_in_two_orgs_refuses_and_names_each_once(self) -> None:
        """One repository can be connected under two organizations — which one
        this call is about is then unknowable, so it refuses. The candidate
        lines name only ``--org``: the verbs that resolve an org this way
        (``status``, ``orgs``, ``connections``) declare no ``--project``, so
        printing one would hand back a flag they reject."""
        shared = {
            "/api/orgs/acme-data/projects": {
                "projects": [
                    _project("analytics", "GitHub: acme/analytics"),
                    _project("finance", "GitHub: acme/analytics"),
                ]
            },
            "/api/orgs/other-co/projects": {
                "projects": [_project("mirror", "GitHub: acme/analytics")]
            },
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/orgs":
                return httpx.Response(200, json=ORGS)
            return httpx.Response(200, json=shared[request.url.path])

        with cloud(handler) as client, pytest.raises(ContextUnresolved) as caught:
            resolve_org(
                client,
                org_flag=None,
                config=CloudConfig(),
                remotes=["git@github.com:acme/analytics.git"],
            )

        message = str(caught.value)
        assert "--project" not in message
        assert message.count("--org acme-data") == 1
        assert message.count("--org other-co") == 1

    def test_no_org_anywhere_lists_the_callers_orgs(self) -> None:
        with cloud() as client, pytest.raises(ContextUnresolved) as caught:
            resolve_org(client, org_flag=None, config=CloudConfig(), remotes=[])

        message = str(caught.value)
        assert "acme-data" in message
        assert "other-co" in message
        assert "dct cloud use" in message


class TestGitRemotes:
    def test_reads_every_remote_url_of_the_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:acme/analytics.git"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "remote", "add", "fork", "https://github.com/dave/analytics.git"],
            cwd=tmp_path,
            check=True,
        )
        assert sorted(git_remotes(tmp_path)) == [
            "git@github.com:acme/analytics.git",
            "https://github.com/dave/analytics.git",
        ]

    def test_outside_a_repo_there_are_no_remotes(self, tmp_path: Path) -> None:
        assert git_remotes(tmp_path / "nope") == []
