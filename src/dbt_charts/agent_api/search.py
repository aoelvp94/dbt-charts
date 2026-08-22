"""Typed search verb for the agent API."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dbt_charts.agent_api.boards import DASHBOARD_KEYS
from dbt_charts.core.diagnostics import Diagnostic
from dbt_charts.core.project import CHARTS_SUBDIR, Project, posix_relpath

MAX_SEARCH_LIMIT = 50
#: Cap on named chart-title match reasons per hit — keeps match_reasons compact.
MAX_CHART_MATCH_REASONS = 3
DEFAULT_SEARCH_LIMIT = 10

# Maintainer paths that must not appear in agent-facing search summaries.
_INTERNAL_REF_RE = re.compile(r"\s*;?\s*see\s+ai_notes/\S+", re.IGNORECASE)


def _agent_safe_summary(description: str) -> str:
    """Strip maintainer-only references from board descriptions."""
    return _INTERNAL_REF_RE.sub("", description).strip()


class SearchBoardsArgs(BaseModel):
    """Search existing dashboards by keyword. Returns ranked results with match scores and reasons. Use to discover relevant dashboards and reuse validated query patterns before creating new ones. Each hit's `charts` list carries per-chart detail (id, title, type, query) parsed from the same board — a chart-title or chart-id match is called out in match_reasons (e.g. "chart-title: monthly_revenue"), so you can see which chart already answers the question without opening the file. Each hit carries two path forms, named for the coordinate system they resolve in: board_path (relative to charts/) for render_board(path=board_path, chart=<chart id>, ...), and file_path (relative to the project root) for read_file/write_file/edit_file. Reuse the matching field's value unchanged — do not convert between the two. Results may also include sample SQL and literal file paths from matching queries; reuse those exact paths instead of inventing new file globs."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        description="Search query text (keywords to match against dashboard metadata)",
    )
    tags: list[str] | None = Field(
        None, description="Filter results to dashboards with ALL of these tags"
    )
    limit: int | None = Field(
        None, description="Maximum results to return (default 10, max 50)"
    )


class ChartSearchEntry(BaseModel):
    """Compact per-chart detail parsed from the same board YAML search already reads."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    type: str | None = None
    query: str | None = None


class BoardSearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    summary: str
    match_score: float
    match_reasons: list[str]
    board_path: str = Field(
        description=(
            "Path relative to charts/ (charts/ prefix stripped). Pass unchanged "
            "to render_board(path=...)."
        )
    )
    file_path: str = Field(
        description=(
            "Path relative to the project root (charts/ prefix kept). Pass "
            "unchanged to read_file/write_file/edit_file."
        )
    )
    query_names: list[str]
    charts: list[ChartSearchEntry]
    sample_sql: str | None = None
    referenced_data_paths: list[str] = Field(
        description=(
            "Literal data-file paths (CSV/Parquet/JSON) read by this dashboard's "
            "queries, extracted from read_csv()/read_parquet()/read_json() calls "
            "in its SQL. Unrelated to board_path/file_path — these point at data "
            "files, not the dashboard's own YAML."
        )
    )


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    errors: list[Diagnostic]
    results: list[BoardSearchHit]


def search_boards(
    query: str,
    project: Project,
    *,
    tags: list[str] | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> SearchResult:
    """Search dashboards by keyword with ranked results.

    Searches ``charts/`` unconditionally. Truncates to ``limit`` (default 10,
    max 50). Hosts with a per-principal access model (Cloud) must not truncate
    before filtering — see ``search_boards_hits``.
    """
    limit = max(0, min(limit, MAX_SEARCH_LIMIT))
    if limit == 0:
        return SearchResult(success=True, errors=[], results=[])
    hits = search_boards_hits(query, project, tags=tags)
    return SearchResult(success=True, errors=[], results=hits[:limit])


def search_boards_hits(
    query: str, project: Project, *, tags: list[str] | None = None
) -> list[BoardSearchHit]:
    """Score every indexed board against ``query``, sorted best-first, unlimited.

    This layer has no principal concept (agent_api thin-wrapper rule), so it
    cannot itself decide which hits a caller may see. A host with access
    control (Cloud) calls this directly to get the FULL ranked candidate set,
    filters it to visible paths, and only THEN truncates to the caller's
    ``limit`` — filtering an already-truncated ``search_boards()`` result
    would under-fill: a viewer who cannot see the top hits but can see the
    next few would get a false empty result.
    """
    query_stripped = query.strip()
    if not query_stripped:
        return []

    query_tokens = list(_tokenize(query_stripped))
    if not query_tokens:
        return []

    index = _build_index(project, under=CHARTS_SUBDIR)

    if tags:
        required_tags = {t.lower() for t in tags}
        index = [e for e in index if required_tags.issubset(set(e["tags"]))]

    scored: list[tuple[float, str, dict[str, Any], list[str]]] = []
    for entry in index:
        score, reasons = _score_entry(entry, query_tokens)
        if score > 0:
            scored.append((score, entry["file_path"], entry, reasons))

    scored.sort(key=lambda x: (-x[0], x[1]))

    return [
        BoardSearchHit(
            title=entry["title"],
            summary=entry["description"],
            match_score=round(score, 2),
            match_reasons=reasons,
            board_path=entry["board_path"],
            file_path=entry["file_path"],
            query_names=entry["query_names"],
            charts=[ChartSearchEntry(**c) for c in entry["charts"]],
            sample_sql=(entry["sql_snippets"][0] if entry["sql_snippets"] else None),
            referenced_data_paths=_extract_file_paths(entry["sql_snippets"]),
        )
        for score, _path, entry, reasons in scored
    ]


def _index_entry_from_content(
    *,
    board_path: str,
    file_path: str,
    title: str,
    description: str,
    content: dict[str, Any],
) -> dict[str, Any] | None:
    if not any(key in content for key in DASHBOARD_KEYS):
        return None

    tags = content.get("tags", [])
    queries = content.get("queries", {})
    charts = content.get("charts", {})

    sql_snippets: list[str] = []
    query_names: list[str] = []
    if isinstance(queries, dict):
        for qname, qdef in queries.items():
            query_names.append(qname)
            if isinstance(qdef, dict) and qdef.get("sql"):
                sql_snippets.append(qdef["sql"])

    chart_entries: list[dict[str, Any]] = []
    if isinstance(charts, dict):
        for raw_chart_id, chart_def in charts.items():
            # YAML mapping keys need not be strings (`2024:` parses as int).
            chart_id = str(raw_chart_id)
            chart_def = chart_def if isinstance(chart_def, dict) else {}
            # Search reads raw, possibly-invalid YAML: only string values are
            # usable here. An inline query (`query: {sql: ...}`) has no name
            # to reference, so it maps to None rather than the raw dict.
            chart_title = chart_def.get("title")
            chart_type = chart_def.get("type")
            chart_query = chart_def.get("query")
            chart_entries.append(
                {
                    "id": chart_id,
                    "title": (
                        chart_title
                        if isinstance(chart_title, str) and chart_title
                        else chart_id
                    ),
                    "type": chart_type if isinstance(chart_type, str) else None,
                    "query": chart_query if isinstance(chart_query, str) else None,
                }
            )

    return {
        "board_path": board_path,
        "file_path": file_path,
        "title": title,
        "description": _agent_safe_summary(description),
        "tags": [t.lower() for t in tags] if isinstance(tags, list) else [],
        "query_names": query_names,
        "charts": chart_entries,
        "sql_snippets": sql_snippets,
    }


def _build_index(project: Project, *, under: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for pf in sorted(
        project.iter_boards(under=under, recursive=True), key=lambda p: p.relpath
    ):
        if not pf.is_yaml:
            continue
        try:
            content = yaml.safe_load(pf.read_text())
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(content, dict):
            continue
        title = content.get("title", pf.stem)
        rel = PurePosixPath(pf.relpath)
        # iter_boards(under=CHARTS_SUBDIR) guarantees relpath is under "charts/",
        # but the fallback keeps board_path sane if that ever changes.
        board_path = (
            posix_relpath(rel, PurePosixPath(CHARTS_SUBDIR))
            if rel.is_relative_to(CHARTS_SUBDIR)
            else pf.relpath
        )
        entry = _index_entry_from_content(
            board_path=board_path,
            file_path=pf.relpath,
            title=title,
            description=content.get("description", ""),
            content=content,
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _extract_file_paths(sql_snippets: list[str]) -> list[str]:
    paths: list[str] = []
    pattern = re.compile(
        r"""read_(?:csv|csv_auto|parquet|json(?:_auto)?)\(\s*['"]([^'"]+)['"]""",
        re.IGNORECASE,
    )
    for snippet in sql_snippets:
        for match in pattern.findall(snippet):
            if match not in paths:
                paths.append(match)
    return paths


def _score_entry(
    entry: dict[str, Any], query_tokens: list[str]
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    title_tokens = _tokenize(entry["title"])
    desc_tokens = _tokenize(entry["description"])
    tag_set = set(entry["tags"])
    query_name_tokens = _tokenize(" ".join(entry["query_names"]))
    sql_tokens = _tokenize(" ".join(entry["sql_snippets"]))
    chart_tokens = [
        (chart["id"], _tokenize(chart["title"]) | _tokenize(chart["id"]))
        for chart in entry["charts"]
    ]

    for qt in query_tokens:
        if qt in title_tokens:
            score += 3.0
            if "title_match" not in reasons:
                reasons.append("title_match")

        if qt in tag_set:
            score += 2.5
            if "tag_match" not in reasons:
                reasons.append("tag_match")

        if qt in desc_tokens:
            score += 1.5
            if "description_match" not in reasons:
                reasons.append("description_match")

        for chart_id, tokens in chart_tokens:
            if qt in tokens:
                score += 2.0
                reason = f"chart-title: {chart_id}"
                # Reasons stay compact for agent token budgets: name at most
                # MAX_CHART_MATCH_REASONS charts; further matches still score.
                named = sum(1 for r in reasons if r.startswith("chart-title: "))
                if reason not in reasons and named < MAX_CHART_MATCH_REASONS:
                    reasons.append(reason)

        if qt in query_name_tokens:
            score += 1.0
            if "metric_overlap" not in reasons:
                reasons.append("metric_overlap")

        if qt in sql_tokens:
            score += 0.5
            if "sql_match" not in reasons:
                reasons.append("sql_match")

    return score, reasons
