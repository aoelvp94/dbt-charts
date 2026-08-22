"""Unit tests for ``dbt_charts.ai.yaml_utils``."""

from dbt_charts.ai.yaml_utils import extract_yaml


class TestExtractYaml:
    """Tests for the extract_yaml function."""

    def test_extract_yaml_explicit_yaml_block(self) -> None:
        """Test extracting YAML from explicit ```yaml block."""
        text = """Here is the dashboard:

```yaml
title: "My Dashboard"
queries:
  sales: { sql: "SELECT * FROM sales" }
```

This is the configuration."""

        result = extract_yaml(text)

        assert result is not None
        assert 'title: "My Dashboard"' in result
        assert "queries:" in result

    def test_extract_yaml_no_yaml_block(self) -> None:
        """Test extract_yaml returns None when no YAML block exists."""
        text = "This is just plain text without any code blocks."

        result = extract_yaml(text)

        assert result is None

    def test_extract_yaml_empty_string(self) -> None:
        """Test extract_yaml handles empty string."""
        result = extract_yaml("")

        assert result is None

    def test_extract_yaml_generic_code_block_with_yaml_content(self) -> None:
        """Test extracting YAML from generic ``` block with YAML-like content."""
        text = """Here is the config:

```
title: Dashboard
queries:
  test: { sql: "SELECT 1" }
```
"""

        result = extract_yaml(text)

        assert result is not None
        assert "title: Dashboard" in result

    def test_extract_yaml_generic_block_non_yaml(self) -> None:
        """Test that generic ``` block with non-YAML content returns None."""
        text = """Here is some code:

```
function hello() {
    return "world";
}
```
"""

        result = extract_yaml(text)

        assert result is None

    def test_extract_yaml_multiple_blocks_returns_first(self) -> None:
        """Test that multiple YAML blocks returns the first one."""
        text = """First block:

```yaml
title: First
```

Second block:

```yaml
title: Second
```
"""

        result = extract_yaml(text)

        assert result is not None
        assert "title: First" in result
        assert "title: Second" not in result

    def test_extract_yaml_strips_whitespace(self) -> None:
        """Test that extracted YAML is stripped of extra whitespace."""
        text = """
```yaml

title: Dashboard

```
"""

        result = extract_yaml(text)

        assert result is not None
        assert result.startswith("title:")
        assert not result.startswith("\n")
        assert not result.endswith("\n\n")

    def test_extract_yaml_preserves_internal_formatting(self) -> None:
        """Test that internal YAML formatting is preserved."""
        yaml_content = """title: Dashboard
queries:
  sales:
    sql: |
      SELECT *
      FROM sales
      WHERE date > '2024-01-01'"""

        text = f"""Here's the YAML:

```yaml
{yaml_content}
```
"""

        result = extract_yaml(text)

        assert result is not None
        assert "sql: |" in result
        assert "SELECT *" in result
        assert "FROM sales" in result

    def test_extract_yaml_with_charts_keyword(self) -> None:
        """Test extracting YAML that starts with charts keyword."""
        text = """
```
charts:
  revenue:
    type: bar
    query: sales_data
```
"""

        result = extract_yaml(text)

        assert result is not None
        assert "charts:" in result

    def test_extract_yaml_with_rows_keyword(self) -> None:
        """Test extracting YAML that starts with rows keyword."""
        text = """
```
rows:
  - title: Overview
    cols:
      - revenue_chart
```
"""

        result = extract_yaml(text)

        assert result is not None
        assert "rows:" in result

    def test_extract_yaml_with_variables_keyword(self) -> None:
        """Test extracting YAML that starts with variables keyword."""
        text = """
```
variables:
  date_range:
    type: daterange
```
"""

        result = extract_yaml(text)

        assert result is not None
        assert "variables:" in result

    def test_extract_yaml_handles_indented_closing(self) -> None:
        """Test that YAML extraction does not crash on indented closing backticks."""
        text = """
```yaml
title: Test
  ```"""

        # The important thing is it doesn't crash
        result = extract_yaml(text)
        assert result is None or "title:" in result

    def test_extract_yaml_code_block_with_language_hint(self) -> None:
        """Test YAML extraction specifically looks for yaml language hint."""
        # Should NOT extract Python code even if it has colons
        text = """
```python
data = {
    "key": "value"
}
```
"""

        result = extract_yaml(text)

        assert result is None

    def test_extract_yaml_contains_queries_section(self) -> None:
        """Test extraction of YAML containing queries section."""
        text = """
```
something: value
queries:
  test: { sql: "SELECT 1" }
```
"""

        result = extract_yaml(text)

        assert result is not None
        assert "queries:" in result
