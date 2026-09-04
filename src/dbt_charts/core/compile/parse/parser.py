"""YAML parsing module.

Stage: COMPILE (Step 1 of 4)
Purpose: Parse YAML strings into AuthoredBoard input types.

Entry Points:
    - parse_yaml(content: str) -> AuthoredBoard

Inputs:
    - YAML string (board definition)

Outputs:
    - AuthoredBoard (input type with optional fields)

Dependencies:
    - yaml (PyYAML)
    - .types (AuthoredBoard)

Errors:
    - ParseError: Invalid YAML syntax (with line numbers, context, suggestions)

See also:
    - compile/validate/dispatch.py for the next step

Refs #94
"""

import re
from typing import Any

import yaml

from dbt_charts.core.compile.errors import ParseError
from dbt_charts.core.compile.models.board.authored import AuthoredBoard
from dbt_charts.core.utils import UniqueKeyLoader


def parse_yaml(content: str) -> AuthoredBoard:
    """Parse YAML content into a AuthoredBoard object.

    Stage: COMPILE (Step 1 of 4: Parsing)

    This is the first step of compilation. It converts a raw YAML string
    into a structured AuthoredBoard object. Only basic syntax validation happens
    here - schema validation is the next step.

    Enhanced error messages include:
    - Line numbers where errors occur
    - YAML context showing the problematic snippet
    - Helpful suggestions ("Did you mean?")

    Args:
        content: Raw YAML string to parse

    Returns:
        AuthoredBoard object with parsed structure

    Raises:
        ParseError: If YAML syntax is invalid or parsing fails

    Example:
        >>> yaml_content = '''
        ... title: My dbt charts
        ... queries:
        ...   sales: SELECT * FROM sales
        ... charts:
        ...   revenue:
        ...     query: sales
        ...     type: line
        ... rows:
        ...   - revenue
        ... '''
        >>> board = parse_yaml(yaml_content)
        >>> board.title
        'My dbt charts'
    """
    # Step 1a–1b: YAML string → mapping
    parsed_data = load_yaml_mapping(content)
    # Step 1c–1d: mapping → AuthoredBoard
    return parse_mapping(parsed_data, content)


def load_yaml_mapping(content: str) -> dict[str, Any]:
    """Parse a YAML string into a top-level mapping.

    Raises ``ParseError`` (with line context) on syntax errors, empty
    documents, or a non-mapping top-level value.
    """
    try:
        parsed_data = yaml.load(content, Loader=UniqueKeyLoader)
    except yaml.YAMLError as e:
        # problem_mark is the actual error position (e.g. where an unterminated
        # flow sequence was found to be missing its close); it's only present
        # on yaml.error.MarkedYAMLError, not the plain yaml.YAMLError base, so
        # this is a genuine type-narrowing check on a third-party exception —
        # not a guaranteed field we're being defensive about.
        problem_mark = (
            e.problem_mark if isinstance(e, yaml.error.MarkedYAMLError) else None
        )
        line_num = problem_mark.line + 1 if problem_mark is not None else None
        column_num = problem_mark.column + 1 if problem_mark is not None else None
        context = _get_yaml_context_for_error(content, line_num) if line_num else None
        suggestion = _get_yaml_parse_suggestion(str(e))
        raise ParseError(
            f"Invalid YAML syntax: {e}",
            line=line_num,
            column=column_num,
            context=context,
            suggestion=suggestion,
        ) from e

    if parsed_data is None:
        raise ParseError("Empty YAML document")

    if not isinstance(parsed_data, dict):
        raise ParseError(f"YAML must be a mapping, got {type(parsed_data).__name__}")

    return parsed_data


def parse_mapping(parsed_data: dict[str, Any], content: str = "") -> AuthoredBoard:
    """Convert an already-parsed YAML mapping into an ``AuthoredBoard``.

    Shared by ``parse_yaml`` (string entry) and the meta-merge path in
    ``compile_file`` (which builds the mapping by deep-merging meta under the
    board, so there is no source string to re-parse). ``content`` is only used to
    enrich validation errors with line context; pass the original board text when
    available, else leave empty.

    Raises ``ParseError`` on schema-validation failure.
    """
    from dbt_charts.core.compile.migrations import prepare_board_mapping

    parsed_data = prepare_board_mapping(parsed_data)

    from pydantic import ValidationError as PydanticValidationError

    try:
        return AuthoredBoard.model_validate(parsed_data)
    except PydanticValidationError as e:
        # compiler._parse_error_to_diagnostics re-reads e.__cause__ as a
        # PydanticValidationError and routes through format_validation_errors_structured.
        # The ParseError message is not user-visible for this branch; the original
        # PydanticValidationError carries the diagnostic details.
        raise ParseError(f"Board schema validation failed: {e}") from e
    except (TypeError, ValueError) as e:
        raise ParseError(f"Failed to parse board structure: {e}") from e


def _get_yaml_context_for_error(
    content: str,
    line_num: int,
    context_lines: int = 2,
) -> str:
    """Get YAML context around an error line.

    Args:
        content: Full YAML content
        line_num: Line number of the error (1-indexed)
        context_lines: Number of lines to show before/after

    Returns:
        Formatted context string
    """
    from dbt_charts.core.compile.parse.yaml_error_formatter import get_yaml_context

    return get_yaml_context(content, line_num, context_lines)


def _get_yaml_parse_suggestion(error_msg: str) -> str | None:
    """Get a helpful suggestion for a YAML parse error.

    Args:
        error_msg: The error message

    Returns:
        Suggestion string or None
    """
    error_lower = error_msg.lower()

    if "indent" in error_lower:
        return "💡 Check your indentation - YAML requires consistent spacing (typically 2 spaces)"
    elif "expected" in error_lower and "block" in error_lower:
        return "💡 This often happens with incorrect indentation or missing colons"
    elif "mapping" in error_lower:
        return "💡 Check for missing colons after key names or incorrect nesting"
    elif "duplicate" in error_lower:
        return "💡 You have duplicate keys - each key name must be unique at the same level"
    elif "found character" in error_lower:
        return (
            "💡 Check for special characters that need quoting, or invalid YAML syntax"
        )

    return None


_SQL_PREFIX_RE = re.compile(
    r"^\s*(SELECT|WITH|PRAGMA|INSERT|UPDATE|DELETE|CREATE)\b",
    re.IGNORECASE,
)


def looks_like_sql(s: str) -> bool:
    """Return True when a string starts like a raw SQL statement."""
    return bool(_SQL_PREFIX_RE.match(s))
