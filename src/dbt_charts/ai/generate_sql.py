"""Shared text-to-SQL generation function.

Single code path for SQL generation used by:
- Eval runner (standalone question → SQL)
- Cloud AIService (thin async wrapper)
- Playground (SQL guidance for system prompts)

Takes a caller-supplied schema context string (evals build their own) so all
consumers share the same prompt quality.
"""

from __future__ import annotations

import json
from importlib.resources import files

from dbt_charts.ai.llm import OpenAIAdapter
from dbt_charts.ai.prompts import load_prompt, render_prompt_template

PROMPTS_DIR = files("dbt_charts.ai").joinpath("prompts")


def get_sql_generation_guidance() -> str:
    """Return the shared SQL rules used across text-to-SQL consumers."""
    return load_prompt("sql-guidance", PROMPTS_DIR)


def build_sql_system_prompt(schema_context: str) -> str:
    """Build the shared system prompt for standalone SQL generation."""
    return render_prompt_template(
        PROMPTS_DIR / "sql-system.md",
        schema_context=schema_context,
        sql_guidance=get_sql_generation_guidance(),
    )


def generate_sql(
    question: str,
    schema_context: str,
    *,
    client: OpenAIAdapter,
) -> str:
    """Generate SQL from a natural-language question using the LLM.

    Args:
        question: Natural-language question about the data.
        schema_context: Plain schema context string assembled by the caller.
        client: An ``OpenAIAdapter`` instance.

    Returns:
        The generated SQL query string.
    """
    system_prompt = build_sql_system_prompt(schema_context)

    response = client.create(
        model=client.model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "SQLResponse",
                "schema": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string"},
                    },
                    "required": ["sql"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        },
    )

    parsed = json.loads(response.output_text)
    return parsed["sql"]
