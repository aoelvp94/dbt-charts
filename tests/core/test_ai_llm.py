"""Tests for provider selection in terminal agent LLM clients."""

from unittest import mock

import httpx
import pytest


class _SentinelTimeout(httpx.Timeout):
    """Distinct from plain ``httpx.Timeout`` so a test can tell whether the
    client built its timeout through ``openai.Timeout`` (this class, once
    patched in as that attribute) or reverted to constructing
    ``httpx.Timeout`` directly — the latter would make
    ``type(seen["timeout"]) is _SentinelTimeout`` false even though every
    field still matches (both classes have the same fields), which a
    value-only assertion could not catch."""


def test_create_client_uses_openai_by_default() -> None:
    """create_client returns the OpenAI client for any model name."""
    from dbt_charts.ai.llm import OpenAIClient, create_client

    client = create_client(model="gpt-4.1-mini")

    assert isinstance(client, OpenAIClient)


def test_create_client_uses_openai_when_only_openai_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no model arg and OPENAI_API_KEY set, pick OpenAI."""
    from dbt_charts.ai.llm import OpenAIClient, create_client

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    client = create_client()

    assert isinstance(client, OpenAIClient)


def test_create_client_errors_clearly_when_no_keys_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No model and no keys should fail fast with a useful message."""
    from dbt_charts.ai.llm import create_client

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        create_client()

    message = str(exc_info.value)
    assert "OPENAI_API_KEY" in message


def test_create_client_rejects_unsupported_provider() -> None:
    """A provider other than openai fails like any other bad input."""
    from dbt_charts.ai.llm import create_client

    with pytest.raises(ValueError, match="Unsupported provider"):
        create_client(provider="not-a-real-provider")


def test_openai_default_model_is_current_gpt5() -> None:
    """Regression: keep the OpenAI default on the current GPT-5 line.

    The stale `gpt-4o` default shipped to production Cloud chat; this pins the
    upgrade so a revert can't silently drop the whole product back to 4o.
    """
    from dbt_charts.ai.llm import DEFAULT_OPENAI_MODEL

    assert DEFAULT_OPENAI_MODEL == "gpt-5.6-terra"
    assert not DEFAULT_OPENAI_MODEL.startswith("gpt-4")


def test_openai_client_second_call_replays_tool_history_without_assistant_echo() -> (
    None
):
    """Regression (2026-07-23 leaked-tool-envelope incident): after a tool-calling
    turn, the next call's input must carry the tool result and must never echo the
    assistant's preamble text as a bare disconnected message — that echo is what
    degrades the model into writing the tool call as prose instead of using it.

    Must fail against current main: the incremental branch
    (``OpenAIClient._messages_to_input``) has no case for an assistant message
    carrying ``tool_calls``, so it falls through to the generic role-based branch
    and emits ``{"role": "assistant", "content": <preamble>}`` — the exact echo
    this test forbids.
    """
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import (
        AssistantMessage,
        ToolCall,
        ToolResultMessage,
        UserMessage,
    )

    class FakeEvent:
        def __init__(self, event_type: str, **kw: object) -> None:
            self.type = event_type
            for k, v in kw.items():
                setattr(self, k, v)

    captured_inputs: list[list[dict]] = []

    class FakeResponses:
        def __init__(self) -> None:
            self.call_count = 0

        def create(self, **kwargs):
            self.call_count += 1
            captured_inputs.append(kwargs["input"])
            if self.call_count == 1:

                def first_call():
                    yield FakeEvent(
                        "response.created",
                        response=type("R", (), {"id": "resp_1"})(),
                    )
                    yield FakeEvent(
                        "response.output_item.done",
                        item=type(
                            "Item",
                            (),
                            {
                                "type": "function_call",
                                "call_id": "call_1",
                                "name": "execute_query",
                                "arguments": "{}",
                            },
                        )(),
                    )

                return first_call()

            def second_call():
                yield FakeEvent(
                    "response.created", response=type("R", (), {"id": "resp_2"})()
                )
                yield FakeEvent("response.output_text.delta", delta="Done.")

            return second_call()

    client = OpenAIClient(model="gpt-5.6", api_key="test")
    client._client = type("Client", (), {"responses": FakeResponses()})()

    messages = [UserMessage(content="render a chart")]
    list(client.stream_with_tools(messages=messages, system_prompt="SYSTEM", tools=[]))

    # Simulate what run_agent appends after the tool call: the assistant's
    # preamble + tool_calls, then the tool result.
    messages.append(
        AssistantMessage(
            content="Let me render that for you.",
            tool_calls=[ToolCall(id="call_1", name="execute_query", arguments={})],
        )
    )
    messages.append(
        ToolResultMessage(tool_call_id="call_1", name="execute_query", content="{}")
    )

    list(client.stream_with_tools(messages=messages, system_prompt="SYSTEM", tools=[]))

    second_call_input = captured_inputs[1]
    assert not any(
        item.get("role") == "assistant" and item.get("content")
        for item in second_call_input
    ), f"assistant preamble echoed into input: {second_call_input}"
    assert any(
        item.get("type") == "function_call_output" for item in second_call_input
    ), f"tool result missing from second call input: {second_call_input}"


def test_openai_client_translates_stream_error() -> None:
    """A network failure mid-stream must surface as LLMClientError."""
    from dbt_charts.ai.llm import LLMClientError, OpenAIClient
    from dbt_charts.ai.messages import AssistantMessage, UserMessage

    class FakeEvent:
        def __init__(self, event_type, response_id=None):
            self.type = event_type
            if response_id is not None:
                self.response = type("Response", (), {"id": response_id})()

    class FakeResponses:
        def create(self, **kwargs):
            def generator():
                yield FakeEvent("response.created", response_id="resp_new")
                raise httpx.ReadError("socket lost")

            return generator()

    client = OpenAIClient(model="gpt-4.1-mini", api_key="test")
    client._client = type("Client", (), {"responses": FakeResponses()})()

    with pytest.raises(LLMClientError):
        list(
            client.stream_with_tools(
                messages=[
                    UserMessage(content="first"),
                    AssistantMessage(content="done"),
                    UserMessage(content="next"),
                ],
                system_prompt="SYSTEM",
                tools=[],
            )
        )


def test_openai_client_converts_multimodal_content_to_responses_input() -> None:
    """Provider-neutral image messages must use Responses API block names."""
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import AssistantMessage, UserMessage

    client = OpenAIClient(model="gpt-5.6", api_key="test")
    image_uri = "data:image/png;base64,aW1hZ2U="

    items = client._messages_to_input(
        [
            UserMessage(
                content=[
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": image_uri}},
                ],
            ),
            AssistantMessage(content="It is a chart."),
        ],
    )

    assert items == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What is in this image?"},
                {"type": "input_image", "image_url": image_uri},
            ],
        },
        {"role": "assistant", "content": "It is a chart."},
    ]


def test_openai_client_converts_document_block_to_input_file() -> None:
    """Provider-neutral document blocks become Responses `input_file` items.

    A `file_data` data-URI needs an accompanying filename; the subtype drives
    the synthesized extension so the model sees a plausibly-named PDF.
    """
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import UserMessage

    client = OpenAIClient(model="gpt-5.6", api_key="test")
    pdf_uri = "data:application/pdf;base64,cGRm"

    items = client._messages_to_input(
        [
            UserMessage(
                content=[
                    {"type": "text", "text": "Summarize this."},
                    {"type": "document", "url": pdf_uri},
                ],
            )
        ],
    )

    assert items == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Summarize this."},
                {
                    "type": "input_file",
                    "filename": "attachment.pdf",
                    "file_data": pdf_uri,
                },
            ],
        }
    ]


def test_parse_data_uri_rejects_malformed_uri() -> None:
    """A non-base64 / non-data URI must fail fast, not silently split wrong."""
    from dbt_charts.ai.llm import LLMClientError, _parse_data_uri

    with pytest.raises(LLMClientError, match="not a base64 data URI"):
        _parse_data_uri("https://example.com/foo.png")


def test_openai_client_rejects_unsupported_content_block() -> None:
    """Unknown internal block shapes must not reach the provider API."""
    from dbt_charts.ai.llm import LLMClientError, OpenAIClient
    from dbt_charts.ai.messages import UserMessage

    client = OpenAIClient(model="gpt-5.6", api_key="test")

    with pytest.raises(LLMClientError, match="Unsupported OpenAI message"):
        client._messages_to_input(
            [UserMessage(content=[{"type": "input_file"}])],
        )


def test_openai_client_accumulates_token_usage() -> None:
    """_accumulate_usage sums input/output tokens; None is a no-op."""
    from types import SimpleNamespace

    from dbt_charts.ai.llm import OpenAIClient

    c = OpenAIClient(model="gpt-4.1-mini")
    assert (c.total_input_tokens, c.total_output_tokens, c.llm_calls) == (0, 0, 0)

    c._accumulate_usage(SimpleNamespace(input_tokens=100, output_tokens=20))
    c._accumulate_usage(SimpleNamespace(input_tokens=5, output_tokens=3))
    c._accumulate_usage(None)  # no usage payload — must not raise or change totals

    assert c.total_input_tokens == 105
    assert c.total_output_tokens == 23


def test_field_reads_attribute_or_dict() -> None:
    """_field handles both typed objects and the raw dicts the SDK sometimes returns."""
    from types import SimpleNamespace

    from dbt_charts.ai.llm import _field

    assert _field(SimpleNamespace(id="x"), "id") == "x"
    assert _field({"id": "x"}, "id") == "x"
    assert _field(SimpleNamespace(), "missing", 7) == 7
    assert _field({}, "missing", 7) == 7
    assert _field(None, "anything", "fallback") == "fallback"


def test_accumulate_usage_handles_dict_payload() -> None:
    """Regression: gpt-4o/gpt-4.1 hand back a dict usage; getattr would read 0."""
    from dbt_charts.ai.llm import OpenAIClient

    c = OpenAIClient(model="gpt-4o")
    c._accumulate_usage({"input_tokens": 100, "output_tokens": 20})
    assert (c.total_input_tokens, c.total_output_tokens) == (100, 20)


def test_stream_parses_dict_shaped_events() -> None:
    """Regression: when the SDK yields raw-dict events (gpt-4.1-mini), the stream must
    still parse tool calls + usage instead of crashing on `event.response.id`."""
    from dbt_charts.ai.events import ToolCallEvent
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import UserMessage

    events = [
        {"type": "response.created", "response": {"id": "resp_new"}},
        {"type": "response.output_text.delta", "delta": "thinking"},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": "call_1",
                "name": "execute_query",
                "arguments": '{"sql": "SELECT 1"}',
            },
        },
        {
            "type": "response.completed",
            "response": {
                "usage": {
                    "input_tokens": 42,
                    "output_tokens": 8,
                }
            },
        },
    ]

    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return iter(events)

    client = OpenAIClient(model="gpt-4.1-mini", api_key="test")
    client._client = type("Client", (), {"responses": FakeResponses()})()

    out = list(
        client.stream_with_tools(
            messages=[UserMessage(content="hi")],
            system_prompt="SYSTEM",
            tools=[],
        )
    )

    tool_calls = [e for e in out if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "execute_query"
    assert tool_calls[0].arguments == {"sql": "SELECT 1"}
    assert "reasoning" not in captured
    assert (client.total_input_tokens, client.total_output_tokens) == (42, 8)


def test_openai_client_requests_and_streams_reasoning_summaries_for_gpt5() -> None:
    """GPT-5 reasoning summaries become stable Cloud progress blurbs."""
    from dbt_charts.ai.events import ThinkingStatus
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import UserMessage

    captured: dict[str, object] = {}
    events = [
        {"type": "response.created", "response": {"id": "resp_new"}},
        {
            "type": "response.reasoning_summary_text.done",
            "item_id": "rs_1",
            "summary_index": 0,
            "text": "I am inventorying the source dashboard tiles.",
        },
    ]

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return iter(events)

    client = OpenAIClient(model="gpt-5.6", api_key="test")
    client._client = type("Client", (), {"responses": FakeResponses()})()

    out = list(
        client.stream_with_tools(
            messages=[UserMessage(content="Replicate this dashboard.")],
            system_prompt="SYSTEM",
            tools=[],
        )
    )

    # The effort is not decoration: gpt-5.x reasons only when asked to, so a
    # request carrying summary alone streams no reasoning items whatsoever and
    # every turn shows the generic "Thinking..." with no breadcrumb.
    assert captured["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert out == [
        ThinkingStatus(
            status="I am inventorying the source dashboard tiles.", block="rs_1:0"
        )
    ]


def test_openai_client_streams_incremental_reasoning_summaries_for_gpt5() -> None:
    """Reasoning summary deltas replace the generic thinking status immediately."""
    from dbt_charts.ai.events import ThinkingStatus
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import UserMessage

    events = [
        {
            "type": "response.reasoning_summary_text.delta",
            "item_id": "rs_1",
            "summary_index": 0,
            "delta": "I am reviewing ",
        },
        {
            "type": "response.reasoning_summary_text.delta",
            "item_id": "rs_1",
            "summary_index": 0,
            "delta": "the dashboard structure.",
        },
    ]

    class FakeResponses:
        def create(self, **kwargs):
            return iter(events)

    client = OpenAIClient(model="gpt-5.6", api_key="test")
    client._client = type("Client", (), {"responses": FakeResponses()})()

    out = list(
        client.stream_with_tools(
            messages=[UserMessage(content="Replicate this dashboard.")],
            system_prompt="SYSTEM",
            tools=[],
        )
    )

    assert out == [
        ThinkingStatus(status="I am reviewing ", block="rs_1:0"),
        ThinkingStatus(
            status="I am reviewing the dashboard structure.", block="rs_1:0"
        ),
    ]


def test_reasoning_summary_parts_get_distinct_block_keys() -> None:
    """Each reasoning block carries its own key, so consumers can collapse per block.

    Deltas restate the whole summary so far, so a consumer that appends would
    show one paragraph many times. Adjacency cannot separate them: two summary
    parts arrive back to back with no tool call between, so only the key
    distinguishes "same block, longer text" from "next block".
    """
    from dbt_charts.ai.events import ThinkingStatus
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import UserMessage

    events = [
        {
            "type": "response.reasoning_summary_text.delta",
            "item_id": "rs_1",
            "summary_index": 0,
            "delta": "Checking the schema.",
        },
        {
            "type": "response.reasoning_summary_text.done",
            "item_id": "rs_1",
            "summary_index": 0,
            "text": "Checking the schema.",
        },
        {
            "type": "response.reasoning_summary_text.delta",
            "item_id": "rs_1",
            "summary_index": 1,
            "delta": "Now picking a chart type.",
        },
    ]

    class FakeResponses:
        def create(self, **kwargs):
            return iter(events)

    client = OpenAIClient(model="gpt-5.6", api_key="test")
    client._client = type("Client", (), {"responses": FakeResponses()})()

    out = list(
        client.stream_with_tools(
            messages=[UserMessage(content="Build me a chart.")],
            system_prompt="SYSTEM",
            tools=[],
        )
    )

    assert out == [
        ThinkingStatus(status="Checking the schema.", block="rs_1:0"),
        ThinkingStatus(status="Checking the schema.", block="rs_1:0"),
        ThinkingStatus(status="Now picking a chart type.", block="rs_1:1"),
    ]


def test_llm_timeout_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The LLM HTTP timeout is bounded by default and env-overridable."""
    from dbt_charts.ai.llm import _llm_timeout

    monkeypatch.delenv("DCT_LLM_READ_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DCT_LLM_CONNECT_TIMEOUT_SECONDS", raising=False)
    timeout = _llm_timeout()
    assert timeout.read == 60.0
    assert timeout.connect == 10.0

    monkeypatch.setenv("DCT_LLM_READ_TIMEOUT_SECONDS", "5")
    assert _llm_timeout().read == 5.0


def test_openai_client_constructed_with_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OpenAI SDK client is built with an explicit non-None timeout so a
    stalled call surfaces as an error instead of hanging for the SDK default."""
    monkeypatch.delenv("DCT_LLM_READ_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DCT_LLM_CONNECT_TIMEOUT_SECONDS", raising=False)

    import openai

    from dbt_charts.ai.llm import OpenAIClient

    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    # A distinct subclass, not plain httpx.Timeout: under a real (unmocked)
    # `import openai`, `openai.Timeout` is openai's own re-export, aliased
    # to `httpx.Timeout` under openai<3 and to an unrelated `httpx2.Timeout`
    # class under openai>=3 — patching in a class the client's own code
    # can't reach any other way is what lets `type(...) is _SentinelTimeout`
    # tell "built through openai.Timeout" apart from "reverted to
    # httpx.Timeout directly", which a value-only assertion could not.
    monkeypatch.setattr(openai, "Timeout", _SentinelTimeout)
    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    _ = client.client  # trigger lazy construction

    timeout = captured["timeout"]
    assert type(timeout) is _SentinelTimeout
    assert timeout.read == 60.0
    assert timeout.connect == 10.0


def test_stream_with_tools_logs_lifecycle(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A streaming call emits begin/end markers for latency diagnosis."""
    from dbt_charts.ai.llm import OpenAIClient
    from dbt_charts.ai.messages import UserMessage

    class FakeResponses:
        def create(self, **_kwargs: object) -> object:
            return iter([])

    client = OpenAIClient(model="gpt-4o", api_key="sk-test")
    client._client = type("Client", (), {"responses": FakeResponses()})()

    with caplog.at_level("INFO", logger="dbt_charts.ai.llm"):
        list(
            client.stream_with_tools(
                messages=[UserMessage(content="hi")],
                system_prompt="SYSTEM",
                tools=[],
            )
        )

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "llm_stream_begin" in joined
    assert "llm_stream_end" in joined


class TestClientTransportOverrides:
    """A caller on a request path needs a hard wall-clock bound, which the
    timeout alone cannot give: it is per-attempt, so SDK retries multiply it."""

    @staticmethod
    def _constructed(**kwargs: object) -> dict[str, object]:
        """Build a client and capture the kwargs it hands the OpenAI SDK."""
        seen: dict[str, object] = {}

        class FakeOpenAI:
            def __init__(self, **sdk_kwargs: object) -> None:
                seen.update(sdk_kwargs)

        from dbt_charts.ai.llm import OpenAIClient

        client = OpenAIClient(model="gpt-5.4-nano", api_key="test", **kwargs)  # type: ignore[arg-type]
        with mock.patch.dict(
            "sys.modules",
            # Timeout=_SentinelTimeout: the real SDK re-exports its own
            # accepted Timeout type from the top level, aliased to whatever
            # class its constructor actually wants under the installed
            # major version — a distinct subclass here, not plain
            # httpx.Timeout, so building the value through openai.Timeout is
            # what these tests actually pin.
            {"openai": mock.MagicMock(OpenAI=FakeOpenAI, Timeout=_SentinelTimeout)},
        ):
            _ = client.client
        return seen

    def test_overrides_reach_the_sdk(self) -> None:
        seen = self._constructed(read_timeout_seconds=8.0, max_retries=0)

        assert seen["max_retries"] == 0
        assert type(seen["timeout"]) is _SentinelTimeout
        assert seen["timeout"].read == 8.0
        assert seen["timeout"].connect == 5.0

    def test_defaults_leave_the_sdk_alone(self) -> None:
        """No override means the shared budget and the SDK's own retry default —
        not a Dataface-side restatement of either."""
        seen = self._constructed()

        assert "max_retries" not in seen
        assert type(seen["timeout"]) is _SentinelTimeout
        assert seen["timeout"].read == 60.0
