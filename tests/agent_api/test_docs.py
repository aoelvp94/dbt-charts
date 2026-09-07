"""Tests for agent_api.docs — single-file syntax slicer with isolated fixture corpus."""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import pytest

from dbt_charts.agent_api.docs import (
    DocsResult,
    TopicEntry,
    docs,
    read_full_text,
    slugify,
)


@pytest.fixture(autouse=True)
def patch_syntax_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch ``_SYNTAX_FILE`` and ``_REFERENCE_FILE`` to controlled corpora
    for every test in this module.

    The missing-file crash tests point a path somewhere else by re-patching;
    autouse keeps the rest of the suite isolated from the wheel's real files.
    """
    fake = tmp_path / "DBT_CHARTS_SYNTAX.md"
    fake.write_text(
        "# dbt charts YAML Syntax\n\n"
        "## Cheatsheet\nOne screen of essentials. Each topic below has a dedicated H2.\n\n"
        "## Board\nThe board is the root dashboard object.\nContains charts and layout.\n\n"
        "## Conditional formatting\nRule-driven style overrides applied per column.\n\n"
        "## Charts\nBar chart documentation.\nUse x and y fields.\n\n"
        "## Layout\nGrid layout documentation.\nArrange charts in a grid.\n\n"
    )
    fake_ref = tmp_path / "yaml-reference.md"
    fake_ref.write_text(
        "# Generated\n\n"
        "## BarChart\n\n"
        "| Field | Type | Description |\n"
        "|---|---|---|\n"
        "| `endpoint_labels` | EndpointLabelsConfig | Series names printed on "
        "stacked bars instead of in a legend. |\n\n"
    )

    import dbt_charts.agent_api.docs._loader as _loader

    monkeypatch.setattr(_loader, "_SYNTAX_FILE", fake)
    monkeypatch.setattr(_loader, "_REFERENCE_FILE", fake_ref)


# ---------------------------------------------------------------------------
# Topic index mode (default — bare `docs()`)
# ---------------------------------------------------------------------------


def test_docs_default_returns_topic_index() -> None:
    result = docs()
    assert result.success is True
    assert result.mode == "index"
    assert all(isinstance(entry, TopicEntry) for entry in result.topics)
    slugs = [entry.id for entry in result.topics]
    assert slugs == [
        "cheatsheet",
        "board",
        "conditional-formatting",
        "charts",
        "layout",
    ]


def test_docs_topic_descriptions_strip_markdown() -> None:
    result = docs()
    by_id = {entry.id: entry for entry in result.topics}
    assert by_id["board"].description == "The board is the root dashboard object."
    assert by_id["charts"].description == "Bar chart documentation."
    assert (
        by_id["conditional-formatting"].description
        == "Rule-driven style overrides applied per column."
    )


# ---------------------------------------------------------------------------
# Topic lookup
# ---------------------------------------------------------------------------


def test_docs_lookup_returns_topic_content() -> None:
    result = docs(topic="charts")
    assert result.success is True
    assert result.mode == "topic"
    assert result.topic is not None
    assert result.topic.id == "charts"
    assert "Charts" in result.topic.title
    assert "Bar chart documentation" in result.topic.content


def test_docs_all_returns_whole_file() -> None:
    result = docs(topic="all")
    assert result.success is True
    assert result.mode == "topic"
    assert result.topic is not None
    assert result.topic.id == "all"
    assert "dbt charts YAML Syntax" in result.topic.content
    assert "## Cheatsheet" in result.topic.content
    assert "## Layout" in result.topic.content


def test_docs_cheatsheet_is_a_topic() -> None:
    result = docs(topic="cheatsheet")
    assert result.success is True
    assert result.topic is not None
    assert "essentials" in result.topic.content


def test_docs_reference_returns_generated_spec(tmp_path: Path) -> None:
    import dbt_charts.agent_api.docs._loader as _loader

    fake_ref = tmp_path / "yaml-reference.md"
    fake_ref.write_text("# Generated\n\n## Fields\n\nAll fields here.\n")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_loader, "_REFERENCE_FILE", fake_ref)
    result = docs(topic="reference")
    monkeypatch.undo()
    assert result.success is True
    assert result.mode == "topic"
    assert result.topic is not None
    assert result.topic.id == "reference"
    assert "Generated" in result.topic.content


def test_docs_reference_missing_file_returns_error(tmp_path: Path) -> None:
    import dbt_charts.agent_api.docs._loader as _loader

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_loader, "_REFERENCE_FILE", tmp_path / "nonexistent.md")
    result = docs(topic="reference")
    monkeypatch.undo()
    assert result.success is False
    assert any("gen-yaml-reference" in e for e in result.errors)


def test_docs_error_reference_returns_generated_spec(tmp_path: Path) -> None:
    import dbt_charts.agent_api.docs._loader as _loader

    fake_ref = tmp_path / "error-reference.md"
    fake_ref.write_text(
        "# dbt charts Error Reference\n\n| Code | Domain |\n|---|---|\n"
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_loader, "_ERROR_REFERENCE_FILE", fake_ref)
    result = docs(topic="error-reference")
    monkeypatch.undo()
    assert result.success is True
    assert result.mode == "topic"
    assert result.topic is not None
    assert result.topic.id == "error-reference"
    assert "dbt charts Error Reference" in result.topic.content


def test_docs_error_reference_missing_file_returns_error(tmp_path: Path) -> None:
    import dbt_charts.agent_api.docs._loader as _loader

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_loader, "_ERROR_REFERENCE_FILE", tmp_path / "nonexistent.md")
    result = docs(topic="error-reference")
    monkeypatch.undo()
    assert result.success is False
    assert any("error-reference.md is missing" in e for e in result.errors)


def test_docs_warning_reference_returns_generated_spec(tmp_path: Path) -> None:
    import dbt_charts.agent_api.docs._loader as _loader

    fake_ref = tmp_path / "warning-reference.md"
    fake_ref.write_text("# dbt charts Warning Reference\n\n### WARN-FOO\n")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_loader, "_WARNING_REFERENCE_FILE", fake_ref)
    result = docs(topic="warning-reference")
    monkeypatch.undo()
    assert result.success is True
    assert result.mode == "topic"
    assert result.topic is not None
    assert result.topic.id == "warning-reference"
    assert "dbt charts Warning Reference" in result.topic.content


def test_docs_warning_reference_missing_file_returns_error(tmp_path: Path) -> None:
    import dbt_charts.agent_api.docs._loader as _loader

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(_loader, "_WARNING_REFERENCE_FILE", tmp_path / "nonexistent.md")
    result = docs(topic="warning-reference")
    monkeypatch.undo()
    assert result.success is False
    assert any("warning-reference.md is missing" in e for e in result.errors)


def test_docs_unknown_topic_offers_close_match() -> None:
    result = docs(topic="char")
    assert result.success is False
    assert any("char" in e for e in result.errors)
    assert any("charts" in h for h in result.hints)


@pytest.mark.parametrize(
    "bad_topic",
    [
        "../README",
        "../../etc/passwd",
        "/etc/hosts",
        "board/",
        "board\\",
        "Board",
        "",
        " board",
    ],
)
def test_docs_rejects_invalid_topic_ids(bad_topic: str) -> None:
    """Topic ids that contain path separators, '..', or non-grammar chars
    must be rejected before any filesystem read.
    """
    result = docs(topic=bad_topic)
    assert result.success is False
    assert result.topic is None
    assert any("Invalid topic id" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Slugify rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("## Conditional formatting", "conditional-formatting"),
        ("## Custom chart plugins", "custom-chart-plugins"),
        ("## Board", "board"),
        ("## Errors", "errors"),
        ("Charts (29 total)", "charts-29-total"),
        ("## Two   Spaces", "two-spaces"),
        ("## Punctuation, hello!", "punctuation-hello"),
    ],
)
def test_slugify_rule(heading: str, expected: str) -> None:
    assert slugify(heading) == expected


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_docs_search_returns_ranked_hits() -> None:
    result = docs(search="grid", limit=3)
    assert result.success is True
    assert result.mode == "search"
    assert len(result.search) <= 3
    topics_found = [h.topic for h in result.search]
    assert "layout" in topics_found
    scores = [h.score for h in result.search]
    assert scores == sorted(scores, reverse=True)


def test_docs_search_no_match_returns_empty() -> None:
    result = docs(search="xyzzy_no_such_term_42")
    assert result.success is True
    assert result.mode == "search"
    assert result.search == []


def test_docs_search_finds_generated_reference_field() -> None:
    """`endpoint_labels` lives in the generated schema reference (a field on
    BarChart/LineChart/AreaChart's `style`), not in the prose syntax doc —
    the search corpus must cover both so this term is findable at all. The
    hit's topic must be the fetchable `reference` topic id, not a per-field
    slug with no corresponding `docs(topic=...)` lookup.
    """
    result = docs(search="endpoint_labels")
    assert result.success is True
    assert result.mode == "search"
    assert any(hit.topic == "reference" for hit in result.search)


# ---------------------------------------------------------------------------
# Bad combinations
# ---------------------------------------------------------------------------


def test_docs_rejects_topic_and_search_together() -> None:
    result = docs(topic="board", search="grid")
    assert result.success is False
    assert any("exclusive" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# Missing source file crashes loud
# ---------------------------------------------------------------------------


def test_read_full_text_missing_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dbt_charts.agent_api.docs._loader as _loader
    from dbt_charts.agent_api.docs import DocsCorpusMissingError

    monkeypatch.setattr(_loader, "_SYNTAX_FILE", tmp_path / "nonexistent.md")
    with pytest.raises(DocsCorpusMissingError, match="source file missing"):
        read_full_text()


# ---------------------------------------------------------------------------
# Pydantic round-trip
# ---------------------------------------------------------------------------


def test_docs_result_json_round_trip() -> None:
    result = docs(topic="board")
    assert result.success is True
    round_tripped = DocsResult.model_validate_json(result.model_dump_json())
    assert round_tripped.success is True
    assert round_tripped.topic is not None
    assert round_tripped.topic.id == "board"


# ---------------------------------------------------------------------------
# DocsArgs forbids unknown keys
# ---------------------------------------------------------------------------


def test_docs_args_forbids_extra_keys() -> None:
    from dbt_charts.agent_api.docs import DocsArgs

    with pytest.raises(ValueError, match="extra"):
        DocsArgs.model_validate({"list": True})


# ---------------------------------------------------------------------------
# Real corpus integrity — guards against accidental wheel-shipping breakage
# ---------------------------------------------------------------------------


def test_real_syntax_file_present_in_wheel() -> None:
    syntax = importlib.resources.files("dbt_charts") / "DBT_CHARTS_SYNTAX.md"
    assert syntax.is_file(), (
        "DBT_CHARTS_SYNTAX.md must ship with the wheel for `dct docs`"
    )


def test_docs_package_attribute_is_not_shadowed() -> None:
    """`from dbt_charts.agent_api.docs import ... docs` must not rebind the
    `docs` submodule attribute on the parent package. Regression for the
    function/package name collision.
    """
    import dbt_charts.agent_api.docs as docs_pkg
    import dbt_charts.agent_api.docs._loader  # would AttributeError if shadowed

    assert docs_pkg.__name__ == "dbt_charts.agent_api.docs"
    assert dbt_charts.agent_api.docs._loader.__name__.endswith("._loader")
