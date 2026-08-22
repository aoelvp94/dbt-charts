"""dbt_charts.agent_api.docs — single-file syntax reference, sliced by H2."""

from dbt_charts.agent_api.docs._loader import (
    DocsArgs,
    DocsCorpusMissingError,
    DocsResult,
    DocsSearchHit,
    Topic,
    TopicEntry,
    docs,
    read_full_text,
    slugify,
)

__all__ = [
    "docs",
    "read_full_text",
    "slugify",
    "TopicEntry",
    "DocsArgs",
    "DocsCorpusMissingError",
    "DocsResult",
    "DocsSearchHit",
    "Topic",
]
