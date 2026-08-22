"""Thin LLM client adapters for the terminal agent."""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from typing import Any, Protocol

import httpx

from dbt_charts.ai.events import (
    ContentDelta,
    StreamEvent,
    ThinkingStatus,
    ToolCallEvent,
)
from dbt_charts.ai.messages import (
    AgentMessage,
    AssistantMessage,
    ToolResultMessage,
    UserMessage,
)
from dbt_charts.ai.tool_schemas import ALL_TOOLS

if sys.version_info >= (3, 11):
    from typing import assert_never
else:
    from typing_extensions import assert_never

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"


#: Connect budget for a caller-supplied read timeout. Named so the callers that
#: reason about a total wall-clock bound can do the arithmetic against a
#: constant rather than a duplicated literal.
CONNECT_TIMEOUT_SECONDS = 5.0


def _llm_timeout() -> httpx.Timeout:
    """HTTP timeout for LLM calls.

    Bounds every LLM request so a stalled connection surfaces as an error
    instead of hanging for the SDK default (~10 min). ``read`` is the max gap
    between streamed chunks; kept well under callers' own stall watchdogs.
    Overridable via env for unusually slow models.
    """
    return httpx.Timeout(
        float(os.getenv("DCT_LLM_READ_TIMEOUT_SECONDS", "60")),
        connect=float(os.getenv("DCT_LLM_CONNECT_TIMEOUT_SECONDS", "10")),
    )


def _parse_data_uri(uri: str) -> tuple[str, str]:
    """Split a base64 ``data:`` URI into its media type and payload.

    Raises ``LLMClientError`` on anything that isn't a base64 data URI — the
    frontend and view already validate the shape, so a miss here is a bug, not
    user input to tolerate.
    """
    prefix, _, data = uri.partition(",")
    if not (prefix.startswith("data:") and prefix.endswith(";base64") and data):
        raise LLMClientError(f"Attachment is not a base64 data URI: {uri[:32]!r}...")
    media_type = prefix[len("data:") : -len(";base64")]
    return media_type, data


def _openai_content_block(block: dict[str, Any]) -> dict[str, Any]:
    """Convert one provider-neutral content block to a Responses API input block."""
    block_type = block.get("type")
    if block_type == "text" and isinstance(block.get("text"), str):
        return {"type": "input_text", "text": block["text"]}
    if block_type == "image_url":
        image_url = block.get("image_url")
        if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
            return {"type": "input_image", "image_url": image_url["url"]}
    if block_type == "document" and isinstance(block.get("url"), str):
        media_type, _ = _parse_data_uri(block["url"])
        subtype = media_type.rpartition("/")[2] or "bin"
        return {
            "type": "input_file",
            "filename": f"attachment.{subtype}",
            "file_data": block["url"],
        }
    raise LLMClientError(f"Unsupported OpenAI message content block: {block_type!r}.")


def _resolve_model(
    explicit_model: str | None,
    env_var: str,
    default_model: str,
) -> str:
    return explicit_model or os.getenv(env_var) or default_model


# OpenAI's Structured Outputs / strict function-calling schema validator only
# accepts this fixed allowlist for a string "format" — anything else (e.g. the
# "path" pydantic emits for pathlib.Path fields) is a 400 at request time,
# rejecting the whole tools array regardless of which tool the format lives on.
_OPENAI_ALLOWED_STRING_FORMATS = {
    "date-time",
    "time",
    "date",
    "duration",
    "email",
    "hostname",
    "ipv4",
    "ipv6",
    "uuid",
}


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a local ``#/`` JSON-Schema pointer against the document root."""
    if not ref.startswith("#/"):
        raise ValueError(f"Unexpected $ref format {ref!r}; does not start with '#/'")
    resolved: Any = root
    for key in ref[2:].split("/"):
        resolved = resolved[key]
    if not isinstance(resolved, dict):
        raise ValueError(
            f"$ref {ref!r} resolved to {type(resolved).__name__}, not dict"
        )
    return resolved


def _to_strict_json_schema(
    schema: dict[str, Any], root: dict[str, Any]
) -> dict[str, Any]:
    """Transform a JSON Schema dict in-place to conform to OpenAI strict-mode rules.

    Mirrors openai/lib/_pydantic.py::_ensure_strict_json_schema, plus one rule
    it doesn't need (its own SDK never emits pydantic-only formats): unsupported
    string `format` values are stripped, since OpenAI validates them by allowlist.
    - Every object gets additionalProperties: false.
    - required covers all property keys whenever properties is present.
    - 'default: null' entries are stripped (non-null defaults are left intact).
    - A `$ref` carrying sibling keys is inlined; OpenAI rejects that shape
      outright, and pydantic emits it for a nested model given a Field
      description.
    Recurses into $defs, definitions, properties, items, anyOf, allOf, oneOf.
    ``root`` is the document the ``#/`` pointers resolve against — the top-level
    schema, threaded through the recursion unchanged.
    """
    ref = schema.get("$ref")
    if isinstance(ref, str) and len(schema) > 1:
        # Sibling keys win over the target's, matching the OpenAI SDK; then the
        # inlined body still needs the rules below applied to it.
        schema.update({**_resolve_ref(root, ref), **schema})
        del schema["$ref"]

    if schema.get("type") == "object":
        schema.setdefault("additionalProperties", False)
    props = schema.get("properties", {})
    if props:
        schema["required"] = list(props.keys())

    if schema.get("default") is None and "default" in schema:
        del schema["default"]

    fmt = schema.get("format")
    if isinstance(fmt, str) and fmt not in _OPENAI_ALLOWED_STRING_FORMATS:
        del schema["format"]

    for defs_key in ("$defs", "definitions"):
        for sub in schema.get(defs_key, {}).values():
            _to_strict_json_schema(sub, root)

    for sub in schema.get("properties", {}).values():
        _to_strict_json_schema(sub, root)

    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            _to_strict_json_schema(sub, root)

    if "items" in schema:
        _to_strict_json_schema(schema["items"], root)

    return schema


def _strict_parameters(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Strict-transform a copy of ``input_schema``, resolving refs against itself.

    The copy is what makes the transform safe: ``_to_strict_json_schema`` edits
    in place, and the canonical tool dicts are shared module-level constants.
    """
    schema = copy.deepcopy(input_schema)
    return _to_strict_json_schema(schema, schema)


def normalize_openai_tools(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build the Responses API ``tools`` payload for a set of tool definitions.

    The one place tool schemas are prepared for OpenAI. Hosts that assemble
    their own tool list (Cloud, A lIe) call this rather than re-deriving the
    shape: strict mode and the string-``format`` allowlist are enforced here,
    so a schema rule fixed here is fixed for every surface.
    """
    # None means "use default agent tools"; [] means "no tools, text-only completion".
    source_tools = ALL_TOOLS if tools is None else tools
    result: list[dict[str, Any]] = []
    for tool in source_tools:
        if "input_schema" in tool:
            # First-party tool in MCP/input_schema format — strict-transform and
            # convert to OpenAI Responses API format. Strict mode is a property of
            # schemas we authored, not of the transport; MCP passthrough schemas
            # (already in OpenAI function format) are appended below unchanged.
            result.append(
                {
                    "type": "function",
                    "strict": True,
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": _strict_parameters(tool["input_schema"]),
                }
            )
        else:
            # Already in OpenAI function format (e.g. MCP passthrough) — pass through
            # untouched. Caller-supplied schemas must not be strict-marked or rewritten.
            result.append(tool)
    return result


class LLMClientError(RuntimeError):
    """Raised when a provider request fails."""


def _reasoning_block(event: Any) -> str:
    """Identity of one reasoning summary block: its item, then its part index.

    Doubles as the accumulator key while a block's deltas stream in, so the
    block's identity has one representation rather than a tuple here and a
    string on the wire.
    """
    return f"{_field(event, 'item_id', '')}:{_field(event, 'summary_index', '')}"


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from an attribute or a dict key.

    OpenAI Responses stream events are usually typed objects, but for some models
    (e.g. gpt-4.1-mini, gpt-4o) the SDK hands back raw ``dict`` payloads instead.
    Attribute access then raises (``'dict' object has no attribute 'id'``) or
    ``getattr`` silently returns the default (0-token usage). This reads either shape.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# Reasoning levels we offer, cheapest first. The provider also accepts "none" and
# "low", and they are deliberately absent: measured against gpt-5.6-luna
# (2026-08-12) both return zero reasoning items, so `summary: auto` has nothing to
# summarize and the UI hangs on a generic "Thinking...". Medium is the floor that
# actually emits summaries; every level here does.
REASONING_EFFORTS = ("medium", "high", "xhigh", "max")

DEFAULT_REASONING_EFFORT = "medium"


def _validate_effort(effort: str | None) -> str | None:
    """Return the level, or None for the explicit no-reasoning opt-out.

    None is not a fallback — a caller has to type it, and it means "send no
    reasoning block at all". Cloud's fast-cheap filler client is the one caller
    that wants that: it runs inside a request on an 8s single-attempt budget,
    where thinking tokens only make it lose its race.
    """
    if effort is None:
        return None
    if effort not in REASONING_EFFORTS:
        raise ValueError(
            f"Unsupported reasoning effort: {effort!r}. "
            f"Expected one of {', '.join(REASONING_EFFORTS)}."
        )
    return effort


def _supports_reasoning_summaries(model: str) -> bool:
    """Return whether this Responses model accepts reasoning summaries."""
    return model.startswith("gpt-5")


def _is_openai_api_error(exc: Exception) -> bool:
    try:
        from openai import APIError
    except ImportError:
        return isinstance(exc, httpx.HTTPError)
    return isinstance(exc, (APIError, httpx.HTTPError))


# -- Client protocol and implementation --------------------------------------


class LLMClient(Protocol):
    """Provider-neutral streaming interface."""

    provider: str
    model: str
    # Reasoning level this client actually sends, None when it sends no reasoning
    # block at all — either because the caller opted out or because the model
    # cannot take one. Declared alongside `model` because it is the other half of
    # "which arm ran", and run records read it for provenance: it has to describe
    # what went over the wire, not what was asked for.
    effort: str | None
    # Cumulative usage across this client's lifetime. Every implementation must
    # maintain these honestly — eval solvers read them to attribute per-case
    # cost/calls. Declared here so callers access them directly (no getattr
    # defaults, which would silently fabricate zeros for a client that forgot them).
    total_input_tokens: int
    total_output_tokens: int
    llm_calls: int

    def stream_with_tools(
        self,
        *,
        messages: list[AgentMessage],
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamEvent]: ...


class OpenAIClient:
    """Responses API client with streaming output and tool calls.

    Stateless by design: every call sends the full conversation, with no
    server-side response-chaining parameter linking one call to the next.
    (Dave, 2026-07-23) That chaining provoked the mixed-content bug this class
    replaced — it made the model's own tool-call history depend on server
    state we didn't fully control, and a missed shape in the incremental
    converter leaked a raw tool envelope into chat. The trade is losing
    OpenAI's server-side reasoning-item carryover between tool-loop
    iterations within one turn, which may degrade multi-step tool reasoning.
    Worth reconsidering once the provider-side chaining flakiness
    (community.openai.com thread 1354672) is resolved — re-measure against
    the eval canary before restoring it.
    """

    provider = "openai"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        read_timeout_seconds: float | None = None,
        max_retries: int | None = None,
        effort: str | None = DEFAULT_REASONING_EFFORT,
    ) -> None:
        # None means the shared _llm_timeout() budget and the SDK's own retry
        # default. A caller overrides both only when the defaults are wrong for
        # where it runs — a request-path call must fail fast rather than make a
        # user wait out a stalled provider, and the timeout alone cannot do that:
        # it is per-attempt, so retries multiply it.
        self._read_timeout_seconds = read_timeout_seconds
        self._max_retries = max_retries
        self.model = _resolve_model(
            model,
            "OPENAI_MODEL",
            DEFAULT_OPENAI_MODEL,
        )
        # Validated at construction, not at call time: an eval arm that asks for a
        # level the provider rejects must fail before it bills a run's worth of
        # tokens under an effort nobody chose. Resolved against the model in the
        # same breath, so `self.effort` is the level that will actually be sent —
        # a run record reading it can never claim a level a gpt-4o baseline never
        # received.
        requested = _validate_effort(effort)
        self.effort = requested if _supports_reasoning_summaries(self.model) else None
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client: Any = None
        # Cumulative token usage + call count across every call this client makes.
        # Eval solvers read these to attribute per-case cost/calls (a fresh client
        # per case = that case's usage; a shared client = diff before/after).
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.llm_calls = 0

    def _accumulate_usage(self, usage: Any) -> None:
        """Add a Responses-API usage payload to the running token totals."""
        if usage is None:
            return
        self.total_input_tokens += _field(usage, "input_tokens", 0) or 0
        self.total_output_tokens += _field(usage, "output_tokens", 0) or 0

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import openai
                from openai import OpenAI
            except ImportError as exc:
                # Not routed through _install_hint: that helper only builds
                # `<installer> "dbt-charts[...]"` strings, and openai is a
                # bring-your-own dependency here, not a Dataface extra.
                raise RuntimeError(
                    "OpenAI client is not installed. Install with: pip install openai"
                ) from exc
            timeout = (
                _llm_timeout()
                if self._read_timeout_seconds is None
                else httpx.Timeout(
                    self._read_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS
                )
            )
            # openai re-exports its own Timeout at the top level, aliased to
            # whichever httpx-shaped class its own constructor actually wants
            # (recent SDK majors vendor a private copy under a different
            # name). Building through that alias instead of httpx.Timeout
            # directly keeps this correct across majors without this module
            # having to know which one is installed.
            openai_timeout = openai.Timeout(**timeout.as_dict())
            # Branch rather than splat a kwargs dict: `max_retries` has an SDK
            # default we don't want to restate, and `**dict` erases the arg
            # types for the type checker.
            if self._max_retries is None:
                self._client = OpenAI(api_key=self.api_key, timeout=openai_timeout)
            else:
                self._client = OpenAI(
                    api_key=self.api_key,
                    timeout=openai_timeout,
                    max_retries=self._max_retries,
                )
        return self._client

    def create(self, **kwargs: Any) -> Any:
        """Non-streaming Responses API call with unified error handling.

        Wraps ``client.responses.create()`` with the same exception
        handling used by the streaming path, translating API and network
        errors into :class:`LLMClientError`, and sends the same reasoning
        block: the effort is a property of the client, so a caller that
        never streams must not silently run at the provider's default.
        A client built with ``effort=None`` sends no block on either path.
        """
        self.llm_calls += 1
        if self.effort is not None:
            kwargs["reasoning"] = {"effort": self.effort, "summary": "auto"}
        started = time.monotonic()
        try:
            resp = self.client.responses.create(**kwargs)
            self._accumulate_usage(getattr(resp, "usage", None))
        except Exception as exc:
            logger.warning(
                "llm_call_error model=%s stream=False elapsed=%.2fs error=%s",
                self.model,
                time.monotonic() - started,
                exc.__class__.__name__,
            )
            if _is_openai_api_error(exc):
                raise LLMClientError(str(exc)) from exc
            raise
        return resp

    def _user_message_input(self, message: UserMessage) -> dict[str, Any] | None:
        content = message.content
        if not content:
            return None
        if isinstance(content, list):
            return {
                "role": "user",
                "content": [_openai_content_block(block) for block in content],
            }
        return {"role": "user", "content": content}

    def _assistant_message_input(
        self, message: AssistantMessage
    ) -> list[dict[str, Any]]:
        # A preamble immediately followed by tool calls is discardable
        # commentary — the function_call items alone fully specify what
        # happened. Echoing that text back as a disconnected message is the
        # 2026-07-23 incident: it broke function_call/function_call_output
        # adjacency and degraded the model into writing the tool call as prose.
        if message.tool_calls:
            return [
                {
                    "type": "function_call",
                    "call_id": tc.id,
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                }
                for tc in message.tool_calls
            ]
        if not message.content:
            return []
        return [{"role": "assistant", "content": message.content}]

    def _messages_to_input(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            match message:
                case UserMessage():
                    user_item = self._user_message_input(message)
                    if user_item is not None:
                        items.append(user_item)
                case AssistantMessage():
                    items.extend(self._assistant_message_input(message))
                case ToolResultMessage():
                    items.append(
                        {
                            "type": "function_call_output",
                            "call_id": message.tool_call_id,
                            "output": message.content,
                        }
                    )
                case _:
                    assert_never(message)
        return items

    def stream_with_tools(
        self,
        *,
        messages: list[AgentMessage],
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamEvent]:
        input_items = self._messages_to_input(messages)
        if not input_items:
            return
        self.llm_calls += 1

        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": input_items,
            "tools": normalize_openai_tools(tools),
            "stream": True,
        }
        if self.effort is not None:
            # Effort must be explicit. Left to its default, gpt-5.x emits no
            # reasoning items at all, and "summary" then has nothing to
            # summarize — the UI is stuck on a generic "Thinking...".
            kwargs["reasoning"] = {"effort": self.effort, "summary": "auto"}

        logger.info("llm_stream_begin model=%s", self.model)
        started = time.monotonic()
        try:
            stream = self.client.responses.create(**kwargs)
        except Exception as exc:
            logger.warning(
                "llm_stream_error phase=open model=%s elapsed=%.2fs error=%s",
                self.model,
                time.monotonic() - started,
                exc.__class__.__name__,
            )
            if _is_openai_api_error(exc):
                raise LLMClientError(str(exc)) from exc
            raise
        event_count = 0
        reasoning_summaries: dict[str, str] = {}
        try:
            for event in stream:
                event_count += 1
                event_type = _field(event, "type", "")

                if event_type == "response.output_text.delta":
                    yield ContentDelta(delta=_field(event, "delta", ""))
                    continue

                if event_type == "response.reasoning_summary_text.delta":
                    block = _reasoning_block(event)
                    summary = reasoning_summaries.get(block, "") + _field(
                        event, "delta", ""
                    )
                    reasoning_summaries[block] = summary
                    if summary:
                        yield ThinkingStatus(status=summary, block=block)
                    continue

                if event_type == "response.reasoning_summary_text.done":
                    block = _reasoning_block(event)
                    summary = _field(event, "text", "")
                    reasoning_summaries[block] = summary
                    if summary:
                        yield ThinkingStatus(status=summary, block=block)
                    continue

                if event_type == "response.completed":
                    self._accumulate_usage(_field(_field(event, "response"), "usage"))
                    continue

                if event_type != "response.output_item.done":
                    continue

                item = _field(event, "item")
                if _field(item, "type") != "function_call":
                    continue

                raw_args = _field(item, "arguments")
                arguments = json.loads(raw_args) if raw_args else {}
                yield ToolCallEvent(
                    id=_field(item, "call_id"),
                    name=_field(item, "name"),
                    arguments=arguments,
                )
        except Exception as exc:
            logger.warning(
                "llm_stream_error phase=read model=%s events=%d elapsed=%.2fs error=%s",
                self.model,
                event_count,
                time.monotonic() - started,
                exc.__class__.__name__,
            )
            if _is_openai_api_error(exc):
                raise LLMClientError(str(exc)) from exc
            raise

        logger.info(
            "llm_stream_end model=%s events=%d elapsed=%.2fs",
            self.model,
            event_count,
            time.monotonic() - started,
        )


def create_client(
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = DEFAULT_REASONING_EFFORT,
) -> LLMClient:
    """Create an LLM client. OpenAI is the only supported provider."""
    if provider and provider != "openai":
        raise ValueError(f"Unsupported provider: {provider}")
    if not model and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "No LLM API key found. Set OPENAI_API_KEY in the environment, "
            "or pass --model to select a model explicitly."
        )
    return OpenAIClient(model=model, effort=effort)
