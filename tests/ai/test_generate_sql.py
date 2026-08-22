"""Tests for the shared generate_sql() function.

Tests the core text-to-SQL generation path used by evals.
"""

from __future__ import annotations

from unittest.mock import MagicMock


class TestGenerateSql:
    """Tests for generate_sql() — the shared text-to-SQL core."""

    def test_passes_schema_context_in_system_prompt(self) -> None:
        """The schema context is included in the system prompt sent to the LLM."""
        from dbt_charts.ai.generate_sql import generate_sql

        mock_client = MagicMock()
        mock_client.provider = "openai"
        mock_response = MagicMock()
        mock_response.output_text = '{"sql": "SELECT 1"}'
        mock_client.create.return_value = mock_response

        schema = "## Database Schema (duckdb)\n### users | 1,000 rows"

        generate_sql(
            question="test",
            schema_context=schema,
            client=mock_client,
        )

        call_args = mock_client.create.call_args
        # The system prompt should contain the schema context
        input_messages = call_args.kwargs.get("input", call_args[1].get("input", []))
        system_content = next(
            m["content"] for m in input_messages if m["role"] == "system"
        )
        assert schema in system_content

    def test_sql_system_prompt_includes_reusable_sql_guidance(self) -> None:
        """Standalone SQL prompts reuse the same SQL rules as authoring prompts."""
        from dbt_charts.ai.generate_sql import build_sql_system_prompt

        prompt = build_sql_system_prompt("## Schema\n### orders")

        assert "## SQL Generation Rules" in prompt
        assert "Use real table and column names" in prompt
        assert "## Schema\n### orders" in prompt
        assert "{{ sql_guidance }}" not in prompt

    def test_question_sent_as_user_message(self) -> None:
        """The question is sent as the user message."""
        from dbt_charts.ai.generate_sql import generate_sql

        mock_client = MagicMock()
        mock_client.provider = "openai"
        mock_response = MagicMock()
        mock_response.output_text = '{"sql": "SELECT 1"}'
        mock_client.create.return_value = mock_response

        generate_sql(
            question="What is the average order value?",
            schema_context="schema here",
            client=mock_client,
        )

        call_args = mock_client.create.call_args
        input_messages = call_args.kwargs.get("input", call_args[1].get("input", []))
        user_content = next(m["content"] for m in input_messages if m["role"] == "user")
        assert "What is the average order value?" in user_content

    def test_sql_guidance_includes_query_plan_structure(self) -> None:
        """sql-guidance includes plan-first structure for correctness discipline."""
        from dbt_charts.ai.generate_sql import build_sql_system_prompt

        prompt = build_sql_system_prompt("## Schema\n### orders")

        # Plan-first framing
        assert "plan" in prompt.lower()
        # The five plan components that matter for correctness
        assert "GRAIN" in prompt
        assert "OUTPUT" in prompt
        assert "FROM" in prompt or "JOIN" in prompt
        assert "FILTERS" in prompt

    def test_sql_guidance_has_grain_fanout_guard(self) -> None:
        """sql-guidance explains grain to prevent fan-out / double-counting."""
        from dbt_charts.ai.generate_sql import build_sql_system_prompt

        prompt = build_sql_system_prompt("## Schema\n### orders")

        assert "grain" in prompt.lower()
        assert "double" in prompt.lower() or "fan" in prompt.lower()

    def test_sql_guidance_does_not_contain_bird_output_conventions(self) -> None:
        """Product agent guidance must not impose BIRD benchmark output constraints."""
        from dbt_charts.ai.generate_sql import build_sql_system_prompt

        prompt = build_sql_system_prompt("## Schema\n### orders")

        # BIRD-specific anti-formatting rules must NOT appear in product prompt
        assert "do not ROUND" not in prompt
        assert "Do NOT add `DISTINCT`" not in prompt
        assert "No decoration" not in prompt
        assert "EXACT result-set match" not in prompt
        assert "id/key column" not in prompt

    def test_openai_client_create_wraps_httpx_errors(self) -> None:
        """OpenAIClient.create() wraps httpx errors in LLMClientError."""
        import pytest

        from dbt_charts.ai.llm import LLMClientError, OpenAIClient

        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")

        client = OpenAIClient(model="test", api_key="fake")
        mock_inner = MagicMock()
        mock_inner.responses.create.side_effect = httpx.ConnectError(
            "connection refused"
        )
        client._client = mock_inner

        with pytest.raises(LLMClientError, match="connection refused"):
            client.create(model="test", input=[])

    def test_openai_client_create_propagates_programming_errors(self) -> None:
        """OpenAIClient.create() does not swallow non-API exceptions."""
        import pytest

        from dbt_charts.ai.llm import OpenAIClient

        client = OpenAIClient(model="test", api_key="fake")
        mock_inner = MagicMock()
        mock_inner.responses.create.side_effect = RuntimeError("bug")
        client._client = mock_inner

        with pytest.raises(RuntimeError, match="bug"):
            client.create(model="test", input=[])
