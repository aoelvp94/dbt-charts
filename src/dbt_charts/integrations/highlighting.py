"""dbt-Charts YAML Pygments lexer with embedded SQL block highlighting.

The lexer handles dbt-Charts board YAML and delegates the body of SQL block
scalars (``sql: |``, ``sql: >``, ``query: |``, ``query: >``, and
``queries.*: |`` shorthand blocks) to ``pygments.lexers.SqlLexer`` so SQL
keywords are visually distinct from the surrounding YAML structure.
Other block scalar bodies are emitted as plain text, because ``text: |`` and
similar fields contain Markdown or prose rather than YAML syntax.

SQL block keys are loaded from the highlight manifest
(``dbt_charts/data/highlighting/board.json``) so the lexer stays in sync with
the TextMate grammar and the manifest without any hand-maintained duplication.
Regenerate the manifest with ``just gen-highlight-artifacts`` whenever the
schema changes.

Public API
----------
- ``DbtChartsYamlLexer`` — Pygments lexer class.  Reference it from
  MkDocs / pymdownx config via
  ``!!python/name:dbt_charts.integrations.highlighting.DbtChartsYamlLexer``.
- ``highlight_board_yaml(source)`` — Highlight dbt-Charts YAML and return an
  HTML string.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from importlib.resources import files

from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexer import RegexLexer, bygroups
from pygments.lexers import SqlLexer
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Punctuation,
    String,
    Text,
    _TokenType,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _load_sql_block_scalar_keys() -> list[str]:
    """Return SQL block scalar keys from the committed highlight manifest."""
    manifest_text = (
        files("dbt_charts") / "data" / "highlighting" / "board.json"
    ).read_text(encoding="utf-8")
    data: dict[str, object] = json.loads(manifest_text)
    keys = data["sql_block_scalar_keys"]
    assert isinstance(keys, list)
    return [str(k) for k in keys]


_SQL_BLOCK_SCALAR_KEYS: list[str] = _load_sql_block_scalar_keys()

# Keys that open an explicit SQL block: "sql: |", "query: |", "sql: >", "query: >"
# Built from the manifest so the lexer stays in sync with gen-highlight-artifacts.
# Indent captured in group 1.
_SQL_BLOCK_OPEN_RE = re.compile(
    r"^( *)(?:"
    + "|".join(re.escape(k) for k in _SQL_BLOCK_SCALAR_KEYS)
    + r")\s*:\s*[|>]",
    re.MULTILINE,
)

# Any YAML mapping key that opens a block scalar. Used to detect query string
# shorthand under a parent ``queries:`` mapping.
_BLOCK_SCALAR_KEY_RE = re.compile(
    r"^( *)([a-zA-Z_][a-zA-Z0-9_\-]*)\s*:\s*[|>]",
)

# Detect a plain YAML key: <indent><word chars>:
_YAML_KEY_RE = re.compile(r"^( *)([a-zA-Z_][a-zA-Z0-9_\-]*)\s*:")

# Detect a list-item YAML key: <indent>- <word chars>:
# Effective indent is the column of the dash (group 1 length), not the key itself.
_YAML_LIST_KEY_RE = re.compile(r"^( *)-\s+([a-zA-Z_][a-zA-Z0-9_\-]*)\s*:")


def _is_queries_shorthand_block(lines: list[str], line_index: int) -> bool:
    """Return True when *line_index* is a ``queries.<name>: |`` shorthand block."""
    line = lines[line_index]
    m = _BLOCK_SCALAR_KEY_RE.match(line)
    if not m:
        return False

    opener_indent = len(m.group(1))
    for parent_index in range(line_index - 1, -1, -1):
        candidate = lines[parent_index]
        km = _YAML_KEY_RE.match(candidate)
        if km and len(km.group(1)) < opener_indent:
            return km.group(2) == "queries"
        lm = _YAML_LIST_KEY_RE.match(candidate)
        if lm and len(lm.group(1)) < opener_indent:
            return lm.group(2) == "queries"
    return False


def _sql_block_ranges(source: str) -> list[tuple[int, int]]:
    """Return (start, end) byte offsets of SQL block scalar bodies in *source*.

    The body starts on the line after the ``sql: |`` / ``query: |`` line, or
    a query shorthand line such as ``queries.sales: |``. It ends just before
    the next YAML key at the same or lower indent level (or at EOF). Offsets
    are character positions in *source*.
    """
    ranges: list[tuple[int, int]] = []
    lines = source.splitlines(keepends=True)
    line_starts: list[int] = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line)

    i = 0
    while i < len(lines):
        line = lines[i]
        explicit_sql = _SQL_BLOCK_OPEN_RE.match(line)
        shorthand_sql = _is_queries_shorthand_block(lines, i)
        if explicit_sql or shorthand_sql:
            opener_match = explicit_sql or _BLOCK_SCALAR_KEY_RE.match(line)
            assert opener_match is not None
            opener_indent = len(opener_match.group(1))
            body_start_line = i + 1
            # Find end: first line at indent <= opener_indent that is a YAML key.
            # Also treat "  - key:" list-item lines as terminators; their effective
            # indent is the dash column (group 1 length), not the key column.
            j = body_start_line
            while j < len(lines):
                candidate = lines[j]
                km = _YAML_KEY_RE.match(candidate)
                if km and len(km.group(1)) <= opener_indent:
                    break
                lm = _YAML_LIST_KEY_RE.match(candidate)
                if lm and len(lm.group(1)) <= opener_indent:
                    break
                j += 1
            if body_start_line < j:
                start = line_starts[body_start_line]
                end = line_starts[j] if j < len(line_starts) else pos
                ranges.append((start, end))
            i = j
        else:
            i += 1
    return ranges


def _block_scalar_body_ranges(source: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of every YAML block scalar body in *source*."""
    ranges: list[tuple[int, int]] = []
    lines = source.splitlines(keepends=True)
    line_starts: list[int] = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line)

    i = 0
    while i < len(lines):
        line = lines[i]
        opener_match = _BLOCK_SCALAR_KEY_RE.match(line)
        if not opener_match:
            i += 1
            continue

        opener_indent = len(opener_match.group(1))
        body_start_line = i + 1
        j = body_start_line
        while j < len(lines):
            candidate = lines[j]
            km = _YAML_KEY_RE.match(candidate)
            if km and len(km.group(1)) <= opener_indent:
                break
            lm = _YAML_LIST_KEY_RE.match(candidate)
            if lm and len(lm.group(1)) <= opener_indent:
                break
            j += 1

        if body_start_line < j:
            start = line_starts[body_start_line]
            end = line_starts[j] if j < len(line_starts) else pos
            ranges.append((start, end))
        i = j

    return ranges


class DbtChartsYamlLexer(RegexLexer):
    """Pygments lexer for dbt-Charts board YAML with embedded SQL in block scalars.

    Top-level and nested keys are coloured distinctly. Lines inside
    ``sql: |``, ``sql: >``, ``query: |``, ``query: >``, and ``queries.*: |``
    shorthand block scalars are delegated to ``SqlLexer`` so SQL keywords
    (SELECT, FROM, WHERE, ...) receive keyword styling. Other block scalar
    bodies are emitted as plain text, so Markdown headings inside ``text: |``
    are not highlighted as YAML comments.
    """

    name = "dbt-Charts YAML"
    aliases = ["dbt-charts", "dbt-charts-yaml", "dctyaml"]
    filenames = ["*.yml", "*.yaml"]
    mimetypes = ["text/x-dbt-charts-yaml"]

    tokens = {
        "root": [
            (r"#.*$", Comment),
            (r"\{#[^#]*#\}", Comment),
            (r"^---\s*$", Punctuation),
            (r"^\.\.\.\s*$", Punctuation),
            (r'"[^"]*"', String.Double),
            (r"'[^']*'", String.Single),
            (r"\{\{[^}]*\}\}", String.Interpol),
            (r"!![^\s]+", Keyword.Type),
            (r"&[^\s]+", Name.Variable),
            (r"\*[^\s]+", Name.Variable),
            (r"([a-zA-Z_][a-zA-Z0-9_\-]*)(\s*:)", bygroups(Name.Tag, Punctuation)),
            (r"^\s*-\s+", Punctuation),
            (r"[\[\]{}]", Punctuation),
            (r":", Punctuation),
            (r"\|", Punctuation),
            (r">", Punctuation),
            (r"[-+]", Punctuation),
            (r"\d+\.\d+", Number.Float),
            (r"\d+", Number.Integer),
            (r"\b(true|false|null|yes|no|on|off)\b", Keyword.Constant),
            (r"[^\s:]+", Text),
            (r"\s+", Text),
        ]
    }

    def get_tokens_unprocessed(
        self, text: str, stack: Iterable[str] = ("root",)
    ) -> Iterator[tuple[int, _TokenType, str]]:
        """Yield tokens, delegating SQL block bodies to SqlLexer.

        SQL block bodies are re-tokenised with SqlLexer. Other block scalar
        bodies are emitted as plain text, and the rest goes through the normal
        YAML rules.

        All yielded offsets are positions in *text* (the original string),
        not positions within a chunk — required by the Pygments contract.
        """
        block_ranges = _block_scalar_body_ranges(text)
        sql_ranges = _sql_block_ranges(text)
        if not block_ranges:
            yield from super().get_tokens_unprocessed(text, stack)
            return

        sql_range_set = set(sql_ranges)
        sql_lexer = SqlLexer()
        cursor = 0

        for block_start, block_end in block_ranges:
            # Yield YAML tokens for the segment before this block scalar,
            # adjusting chunk-relative offsets back to text-absolute positions.
            if cursor < block_start:
                yaml_chunk = text[cursor:block_start]
                for chunk_offset, ttype, value in super().get_tokens_unprocessed(
                    yaml_chunk, stack
                ):
                    yield cursor + chunk_offset, ttype, value

            block_chunk = text[block_start:block_end]
            if (block_start, block_end) in sql_range_set:
                for offset, ttype, value in sql_lexer.get_tokens_unprocessed(
                    block_chunk
                ):
                    yield block_start + offset, ttype, value
            else:
                yield block_start, Text, block_chunk

            cursor = block_end

        # Remaining YAML after the last block scalar.
        if cursor < len(text):
            yaml_tail = text[cursor:]
            for chunk_offset, ttype, value in super().get_tokens_unprocessed(
                yaml_tail, stack
            ):
                yield cursor + chunk_offset, ttype, value


def highlight_board_yaml(source: str) -> str:
    """Highlight dbt-Charts board YAML and return an HTML string.

    SQL inside ``sql: |``, ``sql: >``, ``query: |``, ``query: >``, and
    ``queries.*: |`` shorthand block scalars is coloured with SQL keyword
    rules.  The wrapping HTML uses ``cssclass="highlight"`` for compatibility
    with the existing ``extra.css`` rules.

    Args:
        source: Raw YAML source text.

    Returns:
        HTML string with Pygments token spans.
    """
    lexer = DbtChartsYamlLexer()
    formatter = HtmlFormatter(cssclass="highlight", nowrap=True)
    return pygments_highlight(source, lexer, formatter)
