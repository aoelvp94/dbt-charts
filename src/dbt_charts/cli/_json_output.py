"""Shared JSON output helper for dct verbs."""

from pydantic import BaseModel


def print_json_result(result: BaseModel) -> None:
    """Write result as JSON to stdout — stable wire contract for all dct verbs."""
    print(result.model_dump_json(exclude_none=True, indent=2))
