"""YAML extraction utilities for AI responses.

This module provides utilities for extracting YAML content from AI-generated
text responses.
"""

from __future__ import annotations

import re


def extract_yaml(text: str) -> str | None:
    """Extract YAML code block from text.

    Looks for YAML content in markdown code blocks. Supports both
    explicit ```yaml blocks and generic ``` blocks that contain
    YAML-like content.

    Args:
        text: Text that may contain YAML code blocks

    Returns:
        Extracted YAML content or None if not found

    Example:
        >>> text = '''Here's the dashboard:
        ... ```yaml
        ... title: "My Dashboard"
        ... queries:
        ...   sales: { sql: "SELECT * FROM sales" }
        ... ```
        ... '''
        >>> extract_yaml(text)
        'title: "My Dashboard"\\nqueries:\\n  sales: { sql: "SELECT * FROM sales" }'
    """
    # Look for ```yaml ... ``` blocks (most specific)
    # Allow optional whitespace before closing backticks (handles indented code blocks)
    pattern = r"```yaml\s*\n(.*?)\n\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return matches[0].strip()

    # Also try ``` ... ``` (without yaml tag) - check if it looks like YAML
    pattern = r"```\s*\n(.*?)\n\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        content = matches[0].strip()
        # Check if it looks like YAML (starts with common YAML keys)
        if content.startswith(("title:", "queries:", "charts:", "rows:", "variables:")):
            return content
        # Also check if it contains YAML-like structure
        if ":" in content and (
            "queries:" in content or "charts:" in content or "rows:" in content
        ):
            return content

    return None
