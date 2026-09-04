"""Tests for dbt charts YAML highlighting with embedded SQL."""

import re

from dbt_charts.integrations.highlighting import highlight_board_yaml

QUERIES_SQL_FIXTURE = """\
queries:
  monthly_revenue:
    sql: |
      SELECT month, SUM(revenue) as revenue
      FROM orders
      WHERE status = 'complete'
      GROUP BY 1
charts:
  revenue:
    type: bar
    query: monthly_revenue
    x: month
    y: revenue
"""

CHARTS_QUERY_FIXTURE = """\
charts:
  revenue:
    type: bar
    query: |
      SELECT month, SUM(revenue) as revenue
      FROM orders
      WHERE status = 'complete'
    x: month
    y: revenue
"""

QUERY_SHORTHAND_FIXTURE = """\
source: my_postgres
queries:
  sales: |
    SELECT month, SUM(revenue) as revenue
    FROM orders
    GROUP BY 1
"""

TEXT_BLOCK_FIXTURE = """\
text: |
  # Segment: {{ segment }}
  SELECT is just prose here.
"""

SCALAR_VALUES_FIXTURE = """\
variables:
  segment:
    input: select
charts:
  total_revenue:
    query: q_revenue
    type: kpi
    value: revenue
"""


def _keyword_spans(html: str) -> set[str]:
    spans = re.findall(r'<span class="[^"]*k[^"]*">[^<]+</span>', html)
    return {span_text for span in spans for span_text in re.findall(r">([^<]+)<", span)}


class TestHighlightBoardYaml:
    """highlight_board_yaml returns HTML with SQL keyword spans."""

    def test_queries_sql_block_keywords_in_spans(self) -> None:
        """SQL keywords SELECT and FROM appear inside span elements."""
        html = highlight_board_yaml(QUERIES_SQL_FIXTURE)
        # Pygments wraps keyword tokens in <span class="...">
        keyword_spans = re.findall(r'<span class="[^"]*k[^"]*">[^<]+</span>', html)
        found_keywords = {
            span_text
            for span in keyword_spans
            for span_text in re.findall(r">([^<]+)<", span)
        }
        assert "SELECT" in found_keywords, (
            f"SELECT not found in keyword spans. Found: {found_keywords}"
        )
        assert "FROM" in found_keywords, (
            f"FROM not found in keyword spans. Found: {found_keywords}"
        )

    def test_charts_query_block_keywords_in_spans(self) -> None:
        """SQL keywords in charts.*.query: | block are highlighted."""
        html = highlight_board_yaml(CHARTS_QUERY_FIXTURE)
        found_keywords = _keyword_spans(html)
        assert "SELECT" in found_keywords, (
            f"SELECT not found in keyword spans in charts query block. "
            f"Found: {found_keywords}"
        )
        assert "FROM" in found_keywords, (
            f"FROM not found in keyword spans in charts query block. "
            f"Found: {found_keywords}"
        )

    def test_query_string_shorthand_block_keywords_in_spans(self) -> None:
        """SQL keywords in queries.*: | string shorthand are highlighted."""
        html = highlight_board_yaml(QUERY_SHORTHAND_FIXTURE)
        found_keywords = _keyword_spans(html)
        assert "SELECT" in found_keywords, (
            f"SELECT not found in keyword spans in query shorthand block. "
            f"Found: {found_keywords}"
        )
        assert "FROM" in found_keywords, (
            f"FROM not found in keyword spans in query shorthand block. "
            f"Found: {found_keywords}"
        )

    def test_non_query_block_scalar_is_not_sql_highlighted(self) -> None:
        """Other YAML block scalars are not delegated to the SQL lexer."""
        html = highlight_board_yaml(TEXT_BLOCK_FIXTURE)
        assert "SELECT" not in _keyword_spans(html)

    def test_text_block_markdown_heading_is_not_yaml_comment(self) -> None:
        """Markdown headings inside text: | are block content, not YAML comments."""
        html = highlight_board_yaml(TEXT_BLOCK_FIXTURE)
        assert '<span class="c"># Segment' not in html
        assert "# Segment" in html

    def test_dbt_charts_scalar_values_are_not_keyword_highlighted(self) -> None:
        """YAML scalar values like select/value are plain text outside SQL blocks."""
        html = highlight_board_yaml(SCALAR_VALUES_FIXTURE)
        keyword_values = _keyword_spans(html)

        assert "select" not in keyword_values
        assert "value" not in keyword_values

    def test_dbt_charts_keys_use_nt_class(self) -> None:
        """dbt charts YAML keys like 'charts', 'queries', 'type' use Name.Tag (nt) class."""
        html = highlight_board_yaml(QUERIES_SQL_FIXTURE)
        assert 'class="nt"' in html, "Expected Name.Tag spans for YAML keys"


ROWS_LIST_FIXTURE = """\
rows:
  - charts:
      c1:
        query: |
          SELECT * FROM t
  - charts:
      c2:
        type: line
"""


class TestSqlBlockRangeListItems:
    """_sql_block_ranges must not extend SQL highlighting past a list-item key."""

    def test_second_charts_key_is_yaml_not_sql(self) -> None:
        """The '- charts:' list-item key after a query block is a YAML key, not SQL body."""
        html = highlight_board_yaml(ROWS_LIST_FIXTURE)
        # Find all nt (Name.Tag) spans — these are YAML keys
        nt_spans = re.findall(r'<span class="nt">([^<]+)</span>', html)
        # "charts" must appear as a YAML key span (at least twice — once per list item)
        charts_nt_count = nt_spans.count("charts")
        assert charts_nt_count >= 2, (
            f"Expected 'charts' to appear at least twice as a YAML key (nt) span, "
            f"got {charts_nt_count}. nt spans found: {nt_spans}"
        )
