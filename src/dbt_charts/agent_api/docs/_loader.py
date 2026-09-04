"""Docs verb for the agent API — slices the single DBT_CHARTS_SYNTAX.md file.

`DBT_CHARTS_SYNTAX.md` is the only source. H2 headings define topics; topic IDs
are slugified headings. Bare `docs()` returns the topic index (slug + one-line
description per H2). `docs(topic="<slug>")` returns one slice.
`docs(topic="all")` returns the whole file. `docs(topic="reference")` returns
the auto-generated field spec from yaml-reference.md.
`docs(topic="error-reference")` / `docs(topic="warning-reference")` return the
auto-generated diagnostic references from error-reference.md / warning-reference.md.
`docs(search=...)` substring-matches across topics.
"""

from __future__ import annotations

import difflib
import importlib.resources
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_SYNTAX_FILE = importlib.resources.files("dbt_charts") / "DBT_CHARTS_SYNTAX.md"

# Generated field spec ships inside the wheel at dbt_charts/agent_api/docs/yaml-reference.md.
# Use importlib.resources so pip-installed users get the same file as editable installs.
_REFERENCE_FILE = (
    importlib.resources.files("dbt_charts.agent_api.docs") / "yaml-reference.md"
)

# Generated error/warning references ship inside the wheel at
# dbt_charts/agent_api/docs/{error,warning}-reference.md.
_ERROR_REFERENCE_FILE = (
    importlib.resources.files("dbt_charts.agent_api.docs") / "error-reference.md"
)
_WARNING_REFERENCE_FILE = (
    importlib.resources.files("dbt_charts.agent_api.docs") / "warning-reference.md"
)

_TOPIC_RE = re.compile(r"^[a-z0-9-]+$")
_ALL_TOPIC = "all"
_REFERENCE_TOPIC = "reference"
_ERROR_REFERENCE_TOPIC = "error-reference"
_WARNING_REFERENCE_TOPIC = "warning-reference"

DocsMode = Literal["index", "topic", "search"]


class DocsCorpusMissingError(RuntimeError):
    """`dbt_charts/DBT_CHARTS_SYNTAX.md` is unreachable. Indicates a broken wheel install."""


class Topic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    content: str = ""


class TopicEntry(BaseModel):
    """One row in the docs topic index: slug + heading + first-line description."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    description: str = ""


class DocsSearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    topic: str
    title: str
    score: float = 0.0
    snippet: str


class DocsArgs(BaseModel):
    """Browse the dbt charts YAML reference offline. Modes: no args = topic index (slug + one-line description per H2), topic='<slug>' = one section, topic='all' = whole reference unsliced, search='<query>' = substring search across topics. Use this before writing YAML to learn field names, valid values, and examples. Call with no args first to see the available topics."""

    topic: str | None = Field(
        None,
        description="Topic slug from the `dct docs` topic index (e.g. 'board', 'charts', 'all', 'reference', 'error-reference', 'warning-reference')",
    )
    search: str | None = Field(
        None, description="Full-text query — runs substring search across all topics"
    )
    limit: int = Field(5, ge=1, le=50, description="Max search hits to return")

    model_config = ConfigDict(extra="forbid")


class DocsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool = True
    mode: DocsMode
    topic: Topic | None = None
    search: list[DocsSearchHit] = []
    topics: list[TopicEntry] = []
    errors: list[str] = []
    hints: list[str] = []


def docs(
    topic: str | None = None,
    search: str | None = None,
    limit: int = 5,
) -> DocsResult:
    """Look up a docs topic, fetch the whole file, or search the corpus.

    - ``docs()`` — index mode: returns one entry per H2 with first-line description.
    - ``docs(topic="board")`` — return content for one H2 section.
    - ``docs(topic="all")`` — return the full ``DBT_CHARTS_SYNTAX.md`` unsliced.
    - ``docs(topic="reference")`` — return the auto-generated field spec.
    - ``docs(topic="error-reference")`` / ``docs(topic="warning-reference")`` —
      return the auto-generated diagnostic reference.
    - ``docs(search="grid")`` — substring search across H2 sections.
    """
    if topic is not None and search is not None:
        return DocsResult(
            success=False,
            mode="topic",
            errors=["topic and --search are mutually exclusive; use one"],
        )

    if search is not None:
        sections = _load_sections()
        return DocsResult(mode="search", search=_search(search, sections, limit=limit))

    if topic is None:
        return DocsResult(mode="index", topics=_topic_index())

    if topic == _ALL_TOPIC:
        return DocsResult(
            mode="topic",
            topic=Topic(
                id=_ALL_TOPIC, title="dbt charts YAML Syntax", content=read_full_text()
            ),
        )

    # Rebuilt on every call (not module-level) so tests that monkeypatch
    # _REFERENCE_FILE / _ERROR_REFERENCE_FILE / _WARNING_REFERENCE_FILE on
    # this module see their patched value — a frozen module-level dict would
    # keep the file reference bound at import time.
    generated_topics = {
        _REFERENCE_TOPIC: (
            _REFERENCE_FILE,
            "dbt charts YAML Field Reference (generated)",
            "yaml-reference.md not found inside the dbt_charts package. Regenerate with the repo's `gen-references`/`gen-yaml-reference` recipe and commit the result.",
        ),
        _ERROR_REFERENCE_TOPIC: (
            _ERROR_REFERENCE_FILE,
            "dbt charts Error Reference (generated)",
            "error-reference.md is missing from the installed package.",
        ),
        _WARNING_REFERENCE_TOPIC: (
            _WARNING_REFERENCE_FILE,
            "dbt charts Warning Reference (generated)",
            "warning-reference.md is missing from the installed package.",
        ),
    }
    if topic in generated_topics:
        generated_file, title, missing_message = generated_topics[topic]
        try:
            content = generated_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return DocsResult(success=False, mode="topic", errors=[missing_message])
        return DocsResult(
            mode="topic", topic=Topic(id=topic, title=title, content=content)
        )

    if not _TOPIC_RE.fullmatch(topic):
        return DocsResult(
            success=False,
            mode="topic",
            errors=[f"Invalid topic id: {topic!r}"],
            hints=[
                "Topic ids match [a-z0-9-]+ (lowercased H2 headings); run `dct docs` for the topic index"
            ],
        )

    sections = _load_sections()
    if topic not in sections:
        all_topics = list(sections.keys())
        close = difflib.get_close_matches(topic, all_topics, n=3, cutoff=0.4)
        hints = (
            [f"Did you mean: {', '.join(close)}"]
            if close
            else ["Run `dct docs` for the topic index"]
        )
        return DocsResult(
            success=False,
            mode="topic",
            errors=[f"Unknown topic: {topic}"],
            hints=hints,
        )

    title, body = sections[topic]
    return DocsResult(mode="topic", topic=Topic(id=topic, title=title, content=body))


def read_full_text() -> str:
    """Return the raw ``DBT_CHARTS_SYNTAX.md`` content unsliced.

    Shared file-load helper for callers that want the whole reference: the agent
    system prompt, the playground AI service, and the ``dct://docs/all``
    MCP resource.
    """
    try:
        return _SYNTAX_FILE.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DocsCorpusMissingError(
            f"Docs source file missing (path={_SYNTAX_FILE}). "
            "The dbt charts wheel is broken or the file was monkeypatched away."
        ) from exc


def slugify(heading: str) -> str:
    """Slugify an H2 heading to a topic ID.

    Locked-in rule: lowercase, strip leading `#`, trim whitespace, replace
    runs of whitespace with single hyphens, keep ASCII letters/digits/hyphens,
    drop everything else.
    """
    text = heading.lstrip("#").strip().lower()
    text = re.sub(r"\s+", "-", text)
    return re.sub(r"[^a-z0-9-]+", "", text)


def _load_sections() -> dict[str, tuple[str, str]]:
    """Read DBT_CHARTS_SYNTAX.md and slice on H2 headers.

    Returns an insertion-ordered mapping ``{slug: (title, body)}`` where body
    starts at the H2 line and runs up to (but not including) the next H2 line.
    Order matches the file — used by the topic index to preserve reading order.
    """
    text = read_full_text()
    lines = text.splitlines(keepends=True)
    sections: dict[str, tuple[str, str]] = {}
    current_title: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current_title is not None:
                sections[slugify(current_title)] = (
                    current_title,
                    "".join(current_lines).rstrip() + "\n",
                )
            current_title = line[3:].strip()
            current_lines = [line]
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections[slugify(current_title)] = (
            current_title,
            "".join(current_lines).rstrip() + "\n",
        )
    return sections


def _first_description_line(body: str) -> str:
    """Return the first non-empty, non-heading prose line from a section body.

    The body starts with the H2 line itself. Skip the H2 line, skip blank
    lines, skip sub-headings (lines starting with `#`), and return the first
    real text line with minimal markdown stripping (backticks, bold/italic).
    """
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        return _strip_markdown(line)
    return ""


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_INLINE_RE = re.compile(r"[`*_]+")


def _strip_markdown(text: str) -> str:
    text = _MD_LINK_RE.sub(r"\1", text)
    return _MD_INLINE_RE.sub("", text).strip()


def _topic_index() -> list[TopicEntry]:
    """Return one TopicEntry per H2 section, in file order."""
    return [
        TopicEntry(id=slug, title=title, description=_first_description_line(body))
        for slug, (title, body) in _load_sections().items()
    ]


def _search(
    query: str, sections: dict[str, tuple[str, str]], limit: int = 5
) -> list[DocsSearchHit]:
    """Substring search across H2 slices with bucketed scoring (1.0 / 0.8 / 0.5)."""
    q = query.lower()
    hits: list[DocsSearchHit] = []
    for slug, (title, body) in sections.items():
        if q in slug:
            snippet = _first_matching_line(body, q) or title
            hits.append(
                DocsSearchHit(topic=slug, title=title, score=1.0, snippet=snippet)
            )
        elif q in title.lower():
            snippet = _first_matching_line(body, q) or title
            hits.append(
                DocsSearchHit(topic=slug, title=title, score=0.8, snippet=snippet)
            )
        else:
            line = _first_matching_line(body, q)
            if line:
                hits.append(
                    DocsSearchHit(topic=slug, title=title, score=0.5, snippet=line)
                )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def _first_matching_line(content: str, query: str) -> str:
    for line in content.splitlines():
        if query in line.lower():
            return line.strip()
    return ""
