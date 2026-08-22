"""Tests for dbt_charts.ai.agent."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from dbt_charts.ai.agent import AgentProfile, run_agent
from dbt_charts.ai.context import DbtChartsAIContext
from dbt_charts.ai.events import ContentDelta, ToolCallEvent
from dbt_charts.ai.messages import AgentMessage


def test_run_agent_accepts_content_array_prompt() -> None:
    """Passing a list as prompt (vision content array) must not raise."""

    content_array = [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    client = MagicMock()
    client.stream_with_tools.return_value = iter([ContentDelta(delta="It's a chart.")])

    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()

    # Build a minimal profile that doesn't call real schema or file reads
    profile = AgentProfile(
        name="test",
        tools=[],
        build_system_prompt=lambda _ctx: "You are a test assistant.",
    )

    events = list(
        run_agent(content_array, client=client, context=context, profile=profile)
    )
    # Should have yielded ContentDelta and AgentDone — no exception
    assert any(isinstance(e, ContentDelta) for e in events)


def test_run_agent_threads_extra_handlers_to_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host (Cloud) passes extra_handlers through to dispatch_tool_call, so
    host-only tools (with no meaning to dft-core) still execute."""
    captured: dict[str, object] = {}

    def fake_dispatch(
        name,
        args,
        *,
        context,
        extra_handlers=None,
        tool_overrides=None,
    ):
        captured["extra_handlers"] = extra_handlers
        return {"ok": True}

    monkeypatch.setattr("dbt_charts.ai.agent.dispatch_tool_call", fake_dispatch)

    tool_call = ToolCallEvent(id="1", name="host_only_tool", arguments={})
    client = MagicMock()
    client.stream_with_tools.side_effect = [
        iter([tool_call]),
        iter([ContentDelta(delta="done")]),
    ]
    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()
    profile = AgentProfile(
        name="test", tools=[], build_system_prompt=lambda _ctx: "prompt"
    )

    def handle_host_only(
        args: dict[str, Any], ctx: DbtChartsAIContext
    ) -> dict[str, Any]:
        return {"ok": True}

    extra_handlers = {"host_only_tool": handle_host_only}

    list(
        run_agent(
            "hi",
            client=client,
            context=context,
            profile=profile,
            extra_handlers=extra_handlers,
        )
    )

    assert captured["extra_handlers"] is extra_handlers


def test_run_agent_threads_profile_tool_overrides_to_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile's tool_overrides (e.g. Cloud's governed move_file/delete_file)
    is threaded through to dispatch_tool_call."""
    captured: dict[str, object] = {}

    def fake_dispatch(
        name,
        args,
        *,
        context,
        extra_handlers=None,
        tool_overrides=None,
    ):
        captured["tool_overrides"] = tool_overrides
        return {"ok": True}

    monkeypatch.setattr("dbt_charts.ai.agent.dispatch_tool_call", fake_dispatch)

    tool_call = ToolCallEvent(id="1", name="move_file", arguments={})
    client = MagicMock()
    client.stream_with_tools.side_effect = [
        iter([tool_call]),
        iter([ContentDelta(delta="done")]),
    ]
    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()

    def governed_move_file(
        args: dict[str, Any], ctx: DbtChartsAIContext
    ) -> dict[str, Any]:
        return {"success": True}

    overrides = {"move_file": governed_move_file}
    profile = AgentProfile(
        name="test",
        tools=[],
        build_system_prompt=lambda _ctx: "prompt",
        tool_overrides=overrides,
    )

    list(run_agent("hi", client=client, context=context, profile=profile))

    assert captured["tool_overrides"] is overrides


def _run_agent_capture_conversation(
    tool_result: dict[str, Any],
) -> list[AgentMessage]:
    """Run one tool round-trip and return the conversation the model saw."""
    seen: list[list[AgentMessage]] = []

    def _stream(messages: Any, **kwargs: Any) -> Any:
        seen.append(list(messages))
        if len(seen) == 1:
            return iter([ToolCallEvent(id="1", name="render_board", arguments={})])
        return iter([ContentDelta(delta="done")])

    client = MagicMock()
    client.stream_with_tools.side_effect = _stream
    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()
    profile = AgentProfile(
        name="test",
        tools=[],
        build_system_prompt=lambda _ctx: "prompt",
        tool_overrides={"render_board": lambda args, ctx: tool_result},
    )
    list(run_agent("hi", client=client, context=context, profile=profile))
    return seen[1]


def test_svg_tool_result_is_compacted_in_model_conversation() -> None:
    """Raw SVG never reaches the model: the conversation copy replaces the
    display artifact with an omission marker while success/warnings survive.
    Regression for the 2026-07-22 incident where a ~100KB SVG tool result was
    echoed back into chat as assistant prose."""
    svg = "<svg xmlns='http://www.w3.org/2000/svg'>" + "x" * 500 + "</svg>"
    conversation = _run_agent_capture_conversation(
        {"success": True, "data": svg, "warnings": [{"code": "W1"}]}
    )
    tool_msg = next(m for m in conversation if m.role == "tool")
    assert "<svg" not in tool_msg.content
    assert '"success": true' in tool_msg.content
    assert "W1" in tool_msg.content
    assert str(len(svg)) in tool_msg.content  # marker states the omitted size


def test_svg_under_a_non_data_key_is_also_elided_from_model() -> None:
    """A host override (e.g. Cloud's render_board merge) may carry pixel
    SVG under a key other than ``data`` (``data`` stays the agent's requested
    semantic payload). ``_model_facing_result`` must elide SVG wherever it
    appears, not just under ``data`` — a second, uninspected key is exactly
    how a ~100KB blob leaks into model context."""
    svg = "<svg xmlns='http://www.w3.org/2000/svg'>" + "x" * 500 + "</svg>"
    conversation = _run_agent_capture_conversation(
        {
            "success": True,
            "data": "title: Preview\nqueries: {}\n",
            "rendered_svg": svg,
        }
    )
    tool_msg = next(m for m in conversation if m.role == "tool")
    assert "<svg" not in tool_msg.content
    assert "title: Preview" in tool_msg.content
    assert str(len(svg)) in tool_msg.content


def test_non_svg_tool_result_reaches_model_unchanged() -> None:
    """Data-bearing results (yaml/terminal text) pass through untouched."""
    conversation = _run_agent_capture_conversation(
        {"success": True, "data": "title: Preview\nqueries: {}\n"}
    )
    tool_msg = next(m for m in conversation if m.role == "tool")
    assert "title: Preview" in tool_msg.content


def test_identical_consecutive_calls_error_before_third_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tool called with identical arguments N consecutive times yields AgentError
    before dispatching the Nth call. Regression guard for the 25-repeat drift bug."""
    from dbt_charts.ai.events import AgentError

    dispatch_count = 0

    def fake_dispatch(name, args, *, context, extra_handlers=None, tool_overrides=None):
        nonlocal dispatch_count
        dispatch_count += 1
        return {"ok": True}

    monkeypatch.setattr("dbt_charts.ai.agent.dispatch_tool_call", fake_dispatch)

    repeated_call = ToolCallEvent(
        id="1", name="render_board", arguments={"path": "charts/rev.yaml"}
    )
    client = MagicMock()
    # Each stream call returns the same tool call forever
    client.stream_with_tools.side_effect = [iter([repeated_call]) for _ in range(10)]

    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()
    profile = AgentProfile(
        name="test", tools=[], build_system_prompt=lambda _ctx: "prompt"
    )

    events = list(run_agent("hi", client=client, context=context, profile=profile))

    error_events = [e for e in events if isinstance(e, AgentError)]
    assert len(error_events) == 1
    assert "render_board" in error_events[0].message
    assert "3" in error_events[0].message
    assert "identical arguments" in error_events[0].message
    # Two dispatches completed (calls 1 and 2); the 3rd was blocked
    assert dispatch_count == 2


def test_varied_arguments_repeat_runs_to_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same tool called with different arguments each time is legitimate progress
    and must NOT be blocked by the identical-call guard."""
    from dbt_charts.ai.events import AgentDone

    dispatch_count = 0

    def fake_dispatch(name, args, *, context, extra_handlers=None, tool_overrides=None):
        nonlocal dispatch_count
        dispatch_count += 1
        return {"ok": True}

    monkeypatch.setattr("dbt_charts.ai.agent.dispatch_tool_call", fake_dispatch)

    client = MagicMock()
    client.stream_with_tools.side_effect = [
        iter(
            [ToolCallEvent(id="1", name="render_board", arguments={"path": "a.yaml"})]
        ),
        iter(
            [ToolCallEvent(id="2", name="render_board", arguments={"path": "b.yaml"})]
        ),
        iter(
            [ToolCallEvent(id="3", name="render_board", arguments={"path": "c.yaml"})]
        ),
        iter([ContentDelta(delta="done")]),
    ]

    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()
    profile = AgentProfile(
        name="test", tools=[], build_system_prompt=lambda _ctx: "prompt"
    )

    events = list(run_agent("hi", client=client, context=context, profile=profile))

    done_events = [e for e in events if isinstance(e, AgentDone)]
    assert len(done_events) == 1
    assert dispatch_count == 3


def test_interleaved_different_tool_resets_identical_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different tool call between identical repeats resets the counter, so the
    guard only fires on consecutive repeats, not on any repeat at all."""
    from dbt_charts.ai.events import AgentDone, AgentError

    def fake_dispatch(name, args, *, context, extra_handlers=None, tool_overrides=None):
        return {"ok": True}

    monkeypatch.setattr("dbt_charts.ai.agent.dispatch_tool_call", fake_dispatch)

    same = ToolCallEvent(id="1", name="render_board", arguments={"path": "rev.yaml"})
    diff = ToolCallEvent(id="2", name="validate_board", arguments={"path": "rev.yaml"})
    client = MagicMock()
    # same, same, different, same, same — the 'same' counter never reaches 3 consecutively
    client.stream_with_tools.side_effect = [
        iter([same]),
        iter([same]),
        iter([diff]),
        iter([same]),
        iter([same]),
        iter([ContentDelta(delta="done")]),
    ]

    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()
    profile = AgentProfile(
        name="test", tools=[], build_system_prompt=lambda _ctx: "prompt"
    )

    events = list(run_agent("hi", client=client, context=context, profile=profile))

    error_events = [e for e in events if isinstance(e, AgentError)]
    done_events = [e for e in events if isinstance(e, AgentDone)]
    assert not error_events
    assert len(done_events) == 1


def test_svg_tool_result_event_keeps_full_payload() -> None:
    """The host-facing ToolResultEvent keeps the raw SVG (Cloud snapshots it)."""
    from dbt_charts.ai.events import ToolResultEvent

    svg = "<svg>full</svg>"

    def _stream(messages: Any, **kwargs: Any) -> Any:
        if not any(m.role == "tool" for m in messages):
            return iter([ToolCallEvent(id="1", name="render_board", arguments={})])
        return iter([ContentDelta(delta="done")])

    client = MagicMock()
    client.stream_with_tools.side_effect = _stream
    context = MagicMock()
    context.project_session.adapter_registry = MagicMock()
    profile = AgentProfile(
        name="test",
        tools=[],
        build_system_prompt=lambda _ctx: "prompt",
        tool_overrides={
            "render_board": lambda args, ctx: {"success": True, "data": svg}
        },
    )
    events = list(run_agent("hi", client=client, context=context, profile=profile))
    result_event = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result_event.result["data"] == svg
