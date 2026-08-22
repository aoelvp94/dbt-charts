"""Wire-contract tests for OpenAIClient.stream_with_tools.

Pins the Responses-API request shape so a silent regression in how the client
threads tool results is caught here — not two weeks later in a slow, flaky e2e.
This is the legitimate parity-test carve-out: the contract lives across two
genuinely separate surfaces (client ↔ any fake/stub), not a duplicated helper.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from dbt_charts.ai.llm import (
    REASONING_EFFORTS,
    OpenAIClient,
    _to_strict_json_schema,
    create_client,
    normalize_openai_tools,
)
from dbt_charts.ai.messages import (
    AgentMessage,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from dbt_charts.ai.tool_schemas import (
    AGENT_TOOLS,
    RENDER_BOARD,
    SUGGEST_BOARD_PLACEMENT,
    subset_tool,
)

from .conftest import strict_mode_violations


class _StubResponses:
    """Captures the kwargs passed to responses.create; returns an empty stream."""

    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> list[Any]:
        self.last_kwargs = kwargs
        return []


class _StubClient:
    def __init__(self) -> None:
        self.responses = _StubResponses()


def _make_client() -> tuple[OpenAIClient, _StubResponses]:
    client = OpenAIClient(model="gpt-test", api_key="fake")
    stub = _StubClient()
    client._client = stub
    return client, stub.responses


def test_opening_request_has_no_function_call_output() -> None:
    """An opening turn (user message only) must not include function_call_output items."""
    client, stub = _make_client()
    messages: list[AgentMessage] = [UserMessage(content="show revenue")]
    list(client.stream_with_tools(messages=messages, system_prompt="you are helpful"))

    input_items: list[dict[str, Any]] = stub.last_kwargs["input"]
    types = [item.get("type") for item in input_items]
    assert "function_call_output" not in types


def test_follow_up_request_carries_function_call_output_and_no_previous_response_id() -> (
    None
):
    """A follow-up turn must carry function_call_output with the originating call_id
    and must not include previous_response_id anywhere in the request kwargs.

    The absence of previous_response_id is the stateless contract introduced
    2026-07-23 to replace server-side response chaining.
    """
    client, stub = _make_client()
    messages: list[AgentMessage] = [
        UserMessage(content="show revenue"),
        AssistantMessage(
            tool_calls=[
                ToolCall(
                    id="call_abc", name="execute_query", arguments={"sql": "SELECT 1"}
                )
            ]
        ),
        ToolResultMessage(tool_call_id="call_abc", name="execute_query", content="[1]"),
    ]
    list(client.stream_with_tools(messages=messages, system_prompt="you are helpful"))

    kwargs = stub.last_kwargs
    assert "previous_response_id" not in kwargs

    input_items: list[dict[str, Any]] = kwargs["input"]
    tool_results = [
        item for item in input_items if item.get("type") == "function_call_output"
    ]
    assert len(tool_results) == 1
    assert tool_results[0]["call_id"] == "call_abc"


def test_normalized_openai_tools_carry_strict_flag() -> None:
    """normalize_openai_tools must set strict=True on every emitted tool.

    Once the open-keyed variables schema is removed, strict mode is valid for
    all 13 tools. This pins that the flag is wired — a future revert silently
    killing it would fail here before reaching a live API call.
    """
    client, stub = _make_client()
    list(
        client.stream_with_tools(messages=[UserMessage(content="x")], system_prompt="y")
    )
    tools = stub.last_kwargs["tools"]
    assert tools, "no tools emitted"
    for tool in tools:
        assert tool.get("strict") is True, (
            f"tool {tool.get('name')!r} missing strict=True: {tool}"
        )


def test_normalized_openai_tools_satisfy_strict_mode_schema_rules() -> None:
    """Every first-party tool schema must satisfy OpenAI's strict-mode /
    Structured Outputs constraints, not just the `format` allowlist.

    Generalizes the #7013 regression (`validate_board` / `render_board` /
    `query_board` / `describe_board`'s `path: Path` fields serializing to
    `format: "path"`, which OpenAI validates before dispatching any call —
    400ing every chat request regardless of prompt) to the full ruleset a
    *different* violation would break identically and just as invisibly, via
    the shared `strict_mode_violations` checker in `conftest.py` (also used
    by `test_tool_schemas.py` — one validator, not two). This test adds the
    one check that's specific to the full payload rather than any one
    schema: the root of each tool's parameters must itself be an object.
    This is offline and fast; `apps/evals/tests/e2e/test_openai_tool_schema_acceptance.py`
    is the live-API companion that catches a rule OpenAI adds or tightens later.

    Covers the full first-party surface Cloud actually sends
    (`AGENT_TOOLS + SUGGEST_BOARD_PLACEMENT`), not just `ALL_TOOLS` — a
    violation added to a file tool must fail here too. MCP passthrough
    schemas are excluded on purpose: they are third-party, never
    strict-marked, so OpenAI does not apply these rules to them.
    """
    tools = normalize_openai_tools([*AGENT_TOOLS, SUGGEST_BOARD_PLACEMENT])
    assert tools, "no tools emitted"
    violations: list[str] = []
    for tool in tools:
        parameters = tool["parameters"]
        if parameters.get("type") != "object":
            violations.append(f"{tool['name']}: root schema is not type object")
        violations.extend(strict_mode_violations(parameters, tool["name"]))
    assert not violations, "strict-mode schema violations found:\n" + "\n".join(
        violations
    )


def test_normalize_does_not_mutate_the_canonical_tool_definitions() -> None:
    """The canonical tool dicts survive normalization byte-identical.

    `_to_strict_json_schema` edits in place (`del schema["format"]`,
    `schema["required"] = ...`) and only `normalize_openai_tools`' deepcopy
    stands between it and the module-level constants — which are shared, not
    copied, by every consumer and by `subset_tool`. Drop that deepcopy and the
    first normalize call rewrites `RENDER_BOARD` for the rest of the process, so
    MCP would advertise a silently strict-ified schema with no test failing.
    """
    before = copy.deepcopy(RENDER_BOARD)
    normalize_openai_tools([subset_tool(RENDER_BOARD, ["path"]), *AGENT_TOOLS])
    assert before == RENDER_BOARD


def test_to_strict_json_schema_unravels_ref_with_sibling_keys() -> None:
    """A `$ref` carrying sibling keys is inlined, not passed through.

    OpenAI rejects `{"$ref": ..., "description": ...}` outright — its own SDK
    unravels the shape (`openai/lib/_pydantic.py`: "we can't use `$ref`s if
    there are also other properties defined"). Pydantic emits exactly that for
    a nested model field annotated with `Field(description=...)`, which is a
    mandated convention in this repo, so this is the most reachable way to
    reproduce #7013's outage: a 400 on the entire tools array, every chat
    request dead, offline suite green. Today's payload is sibling-free only by
    accident — no current Args model nests another model with a description.
    """
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "nested": {"$ref": "#/$defs/Nested", "description": "a nested model"}
        },
        "$defs": {
            "Nested": {"type": "object", "properties": {"a": {"type": "string"}}}
        },
    }

    result = _to_strict_json_schema(schema, schema)

    nested = result["properties"]["nested"]
    assert "$ref" not in nested, f"$ref survived with siblings: {nested}"
    assert nested["type"] == "object"
    assert nested["description"] == "a nested model"
    assert nested["additionalProperties"] is False
    assert nested["required"] == ["a"]


def test_reasoning_effort_defaults_to_medium() -> None:
    """The default preserves the pre-`--effort` wire shape exactly.

    The model is passed to the constructor rather than assigned afterwards: the
    level is resolved against the model once, at construction, so that
    `client.effort` is always the level actually sent.
    """
    client = OpenAIClient(model="gpt-5.6-luna", api_key="fake")
    stub_client = _StubClient()
    client._client = stub_client
    stub = stub_client.responses
    list(
        client.stream_with_tools(messages=[UserMessage(content="hi")], system_prompt="")
    )

    assert stub.last_kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}


def test_reasoning_effort_is_threaded_to_the_request() -> None:
    """An explicit effort reaches the Responses call, with summaries still on.

    `summary: auto` is not optional at any level: it is why the hardcoded
    medium existed — without it gpt-5.x emits no reasoning items and the UI
    hangs on a generic "Thinking...".
    """
    client = OpenAIClient(model="gpt-5.6-luna", api_key="fake", effort="max")
    stub = _StubClient()
    client._client = stub
    list(
        client.stream_with_tools(messages=[UserMessage(content="hi")], system_prompt="")
    )

    assert stub.responses.last_kwargs["reasoning"] == {
        "effort": "max",
        "summary": "auto",
    }


@pytest.mark.parametrize("effort", REASONING_EFFORTS)
def test_every_supported_effort_keeps_summaries_on(effort: str) -> None:
    """Measured 2026-08-12 against gpt-5.6-luna: these four levels emit reasoning
    items; `none` and `low` emit zero, which is why they are not offered."""
    client = OpenAIClient(model="gpt-5.6-luna", api_key="fake", effort=effort)
    stub = _StubClient()
    client._client = stub
    list(
        client.stream_with_tools(messages=[UserMessage(content="hi")], system_prompt="")
    )

    assert stub.responses.last_kwargs["reasoning"]["summary"] == "auto"


@pytest.mark.parametrize("effort", ["none", "low", "minimal", "MAX", "", "maximum"])
def test_unsupported_effort_raises_instead_of_falling_back(effort: str) -> None:
    """No silent coercion to a working level — a typo must fail loudly at
    construction, not quietly measure a different arm than the one requested."""
    with pytest.raises(ValueError, match="effort"):
        OpenAIClient(model="gpt-5.6-luna", api_key="fake", effort=effort)


def test_create_client_threads_effort() -> None:
    client = create_client(model="gpt-5.6-luna", effort="xhigh")
    assert client.effort == "xhigh"


def test_non_streaming_create_carries_the_same_effort() -> None:
    """`create()` must send the client's effort too, not just `stream_with_tools`.

    The single-pass BIRD rungs go through `generate_sql` → `create()`. If only the
    streaming path carried the reasoning block, `--effort max --solver sql` would
    record `effort: max` on a run whose requests never asked for it — a provenance
    claim about a level that never applied, which is worse than no field at all.
    """
    client = OpenAIClient(model="gpt-5.6-luna", api_key="fake", effort="xhigh")
    stub = _StubClient()
    client._client = stub
    client.create(model=client.model, input=[])

    assert stub.responses.last_kwargs["reasoning"] == {
        "effort": "xhigh",
        "summary": "auto",
    }


def test_non_streaming_create_omits_reasoning_on_a_model_without_it() -> None:
    """A model that rejects reasoning summaries must not receive the block."""
    client = OpenAIClient(model="gpt-4.1-mini", api_key="fake")
    stub = _StubClient()
    client._client = stub
    client.create(model=client.model, input=[])

    assert "reasoning" not in stub.responses.last_kwargs


def test_effort_none_sends_no_reasoning_block() -> None:
    """`effort=None` is the explicit opt-out, and it must reach the wire.

    Cloud's fast-cheap client generates filler (session titles, starter
    suggestions) inside a request, on an 8s single-attempt budget. Thinking
    tokens there buy nothing and lose the race, so it opts out — and the opt-out
    has to be a level the caller can name, not a model check, because the model
    it runs (`gpt-5.4-nano`) does accept reasoning.
    """
    client = OpenAIClient(model="gpt-5.4-nano", api_key="fake", effort=None)
    stub = _StubClient()
    client._client = stub
    client.create(model=client.model, input=[])

    assert "reasoning" not in stub.responses.last_kwargs
    assert client.effort is None


def test_effort_is_none_when_the_model_cannot_receive_it() -> None:
    """`client.effort` is what was *sent*, so a non-reasoning model reports None.

    Run records read this for provenance. `--effort` defaults to medium, so a
    `--model gpt-4o` baseline is built with `effort="medium"` while every request
    goes out with no reasoning block at all. Recording "medium" there would file
    that run as a fourth replicate in the ladder's medium bar — a level that
    never applied, which is exactly the invention the ladder's SQL refuses to do
    for pre-flag runs.
    """
    client = OpenAIClient(model="gpt-4o", api_key="fake", effort="medium")

    assert client.effort is None
