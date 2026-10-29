"""Tests for the native Anthropic Messages provider."""

import json
from collections.abc import Callable

import httpx
import pytest

from codefa.application.errors import InvalidRequestError
from codefa.config.constants import ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS
from codefa.config.provider_catalog import ANTHROPIC_DEFAULT_BASE, PROVIDER_CATALOG
from codefa.core.anthropic.models import MessagesRequest
from codefa.core.failures import ExecutionFailure, FailureKind
from codefa.core.reasoning import ReasoningEffort, ReasoningPolicy
from codefa.providers.anthropic import ANTHROPIC_API_VERSION, AnthropicProvider
from codefa.providers.anthropic.errors import (
    AnthropicStreamError,
    anthropic_failure_override,
)
from codefa.providers.anthropic.request import (
    FALLBACK_BETAS,
    build_anthropic_request_plan,
    forwardable_betas,
    next_fallback_plan,
)
from codefa.providers.anthropic.stream import AnthropicEventRelay, iter_sse_events
from codefa.providers.base import ProviderConfig
from codefa.providers.stream_recovery import TruncatedProviderStreamError
from tests.providers.support import (
    REASONING_DEFAULT,
    REASONING_OFF,
    immediate_admission,
    reasoning_for,
)


def _request(**overrides) -> MessagesRequest:
    payload = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": "Hello"}],
        **overrides,
    }
    return MessagesRequest.model_validate(payload)


def _plan(request: MessagesRequest, reasoning: ReasoningPolicy | None = None):
    return build_anthropic_request_plan(
        request, reasoning=reasoning or reasoning_for(request)
    )


# --------------------------------------------------------------------------- catalog


def test_catalog_marks_anthropic_as_native_messages_upstream():
    descriptor = PROVIDER_CATALOG["anthropic_api"]
    assert descriptor.native_messages_api is True
    assert descriptor.credential_env == "ANTHROPIC_API_KEY"
    assert (
        descriptor.default_base_url
        == ANTHROPIC_DEFAULT_BASE
        == ("https://api.anthropic.com")
    )
    assert not PROVIDER_CATALOG["openai_api"].native_messages_api


# --------------------------------------------------------------------- request plan


def test_plan_forwards_native_fields_and_cache_control():
    request = _request(
        system=[
            {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
        ],
        tools=[
            {
                "name": "echo",
                "description": "Echo",
                "input_schema": {"type": "object"},
                "cache_control": {"type": "ephemeral"},
            },
            {"name": "web_search", "type": "web_search_20250305"},
        ],
        tool_choice={"type": "auto"},
        metadata={"user_id": "u1"},
        stop_sequences=["END"],
    )

    body = _plan(request, REASONING_DEFAULT).body

    assert body["model"] == "claude-sonnet-4-5"
    assert body["stream"] is True
    assert body["max_tokens"] == 4096
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][1] == {"name": "web_search", "type": "web_search_20250305"}
    assert body["tool_choice"] == {"type": "auto"}
    assert body["metadata"] == {"user_id": "u1"}
    assert body["stop_sequences"] == ["END"]
    assert "thinking" not in body


def test_plan_defaults_max_tokens_when_missing():
    request = _request(max_tokens=None)
    assert _plan(request).body["max_tokens"] == ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS


def test_plan_normalizes_foreign_history():
    request = _request(
        messages=[
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant",
                "reasoning_content": "hidden",
                "content": [
                    {"type": "thinking", "thinking": "unsigned"},
                    {"type": "thinking", "thinking": "signed", "signature": "sig"},
                    {"type": "text", "text": "  "},
                    {"type": "text", "text": "Hello!"},
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": " "}]},
            {"role": "user", "content": "Next"},
        ],
        system="Base.",
    )

    body = _plan(request).body

    assert body["system"] == [
        {"type": "text", "text": "Base."},
        {"type": "text", "text": "Be terse."},
    ]
    assert body["messages"] == [
        {"role": "user", "content": "Hi"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "signed", "signature": "sig"},
                {"type": "text", "text": "Hello!"},
            ],
        },
        {"role": "user", "content": "Next"},
    ]


def test_plan_rejects_request_without_usable_messages():
    with pytest.raises(InvalidRequestError, match="non-empty content"):
        _plan(_request(messages=[{"role": "user", "content": "   "}]))


def test_plan_merges_extra_body_and_rejects_overrides():
    body = _plan(_request(extra_body={"service_tier": "auto"})).body
    assert body["service_tier"] == "auto"
    assert "extra_body" not in body

    for key in ("model", "thinking", "stream"):
        with pytest.raises(InvalidRequestError, match=key):
            _plan(_request(extra_body={key: "x"}))


def test_forwardable_betas_dedupes_and_strips_oauth():
    assert forwardable_betas(None) == ()
    assert forwardable_betas(["a-2025, oauth-2025-04-20", "b-2025", "a-2025", " "]) == (
        "a-2025",
        "b-2025",
    )
    plan = _plan(_request(betas=["context-management-2025-06-27"]))
    assert plan.headers() == {"anthropic-beta": "context-management-2025-06-27"}
    assert _plan(_request()).headers() == {}


# ------------------------------------------------------------------------ reasoning


def test_client_budget_thinking_is_forwarded_as_enabled_budget():
    request = _request(
        thinking={"type": "enabled", "budget_tokens": 3000}, temperature=0.2
    )
    body = _plan(request).body
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 3000}
    # Anthropic rejects non-default temperature with thinking enabled.
    assert "temperature" not in body


def test_budget_is_clamped_to_documented_range():
    request = _request(
        max_tokens=2000, thinking={"type": "enabled", "budget_tokens": 500}
    )
    assert _plan(request).body["thinking"] == {"type": "enabled", "budget_tokens": 1024}

    request = _request(
        max_tokens=2000, thinking={"type": "enabled", "budget_tokens": 9000}
    )
    assert _plan(request).body["thinking"] == {"type": "enabled", "budget_tokens": 1999}


def test_adaptive_thinking_and_effort_pass_through():
    request = _request(thinking={"type": "adaptive"}, output_config={"effort": "xhigh"})
    body = _plan(request).body
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "xhigh"}


def test_off_policy_disables_thinking_and_drops_invalid_effort():
    request = _request(
        thinking={"type": "adaptive"},
        output_config={"effort": "none", "format": {"type": "text"}},
    )
    body = _plan(request, REASONING_OFF).body
    assert body["thinking"] == {"type": "disabled"}
    assert body["output_config"] == {"format": {"type": "text"}}


def test_configured_effort_uses_adaptive_thinking_and_named_effort():
    body = _plan(_request(), ReasoningPolicy.on(effort=ReasoningEffort.MINIMAL)).body
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "low"}


def test_default_policy_strips_codefa_shaped_thinking_fields():
    request = _request(thinking={"enabled": True})
    body = _plan(request).body
    # {"enabled": true} is ON without a budget -> native adaptive thinking only.
    assert body["thinking"] == {"type": "adaptive"}


# ------------------------------------------------------------------------ fallbacks


def test_fallbacks_are_bounded_and_ordered():
    request = _request(
        betas=["x-beta"],
        thinking={"type": "adaptive"},
        output_config={"effort": "max"},
        messages=[
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "t", "signature": "s"},
                    {"type": "text", "text": "ok"},
                ],
            },
            {"role": "user", "content": "go"},
        ],
    )
    plan = _plan(request)

    plan = next_fallback_plan(plan, "Unexpected value for the anthropic-beta header")
    assert plan is not None and plan.betas == ()
    assert FALLBACK_BETAS in plan.applied_fallbacks

    plan = next_fallback_plan(plan, "Invalid signature in thinking block")
    assert plan is not None
    assert plan.body["messages"][1]["content"] == [{"type": "text", "text": "ok"}]

    plan = next_fallback_plan(plan, "output_config.effort: not supported")
    assert plan is not None and "output_config" not in plan.body

    plan = next_fallback_plan(plan, "thinking.type: adaptive is not supported")
    assert plan is not None
    assert plan.body["thinking"]["type"] == "enabled"
    assert plan.body["thinking"]["budget_tokens"] >= 1024

    assert next_fallback_plan(plan, "thinking.type: enabled is not supported") is None


def test_enabled_thinking_falls_back_to_adaptive():
    plan = _plan(_request(thinking={"type": "enabled", "budget_tokens": 2048}))
    fallback = next_fallback_plan(plan, "budget_tokens is deprecated; use adaptive")
    assert fallback is not None
    assert fallback.body["thinking"] == {"type": "adaptive"}


def test_unrelated_errors_have_no_fallback():
    assert (
        next_fallback_plan(_plan(_request()), "messages: roles must alternate") is None
    )


# --------------------------------------------------------------------------- errors


def _status_error(status: int, error_type: str, message: str = "m") -> Exception:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        status,
        json={"type": "error", "error": {"type": error_type, "message": message}},
        request=request,
    )
    return httpx.HTTPStatusError("err", request=request, response=response)


@pytest.mark.parametrize(
    ("status", "error_type", "message", "kind", "code", "retryable"),
    [
        (
            401,
            "authentication_error",
            "bad key",
            FailureKind.AUTHENTICATION,
            401,
            False,
        ),
        (403, "permission_error", "no", FailureKind.PERMISSION, 403, False),
        (402, "billing_error", "pay", FailureKind.PERMISSION, 402, False),
        (404, "not_found_error", "model", FailureKind.INVALID_REQUEST, 404, False),
        (413, "request_too_large", "big", FailureKind.INVALID_REQUEST, 413, False),
        (429, "rate_limit_error", "slow", FailureKind.RATE_LIMIT, 429, True),
        (529, "overloaded_error", "busy", FailureKind.OVERLOADED, 529, True),
        (500, "api_error", "oops", FailureKind.UPSTREAM, 500, True),
        (504, "timeout_error", "late", FailureKind.TIMEOUT, 504, True),
        (
            400,
            "invalid_request_error",
            "prompt is too long: 250000 tokens > 200000 maximum",
            FailureKind.CONTEXT_WINDOW_EXCEEDED,
            400,
            False,
        ),
        (
            400,
            "invalid_request_error",
            "Your credit balance is too low",
            FailureKind.PERMISSION,
            402,
            False,
        ),
        (400, "invalid_request_error", "bad", FailureKind.INVALID_REQUEST, 400, False),
    ],
)
def test_failure_override_maps_documented_error_types(
    status, error_type, message, kind, code, retryable
):
    failure = anthropic_failure_override(_status_error(status, error_type, message))
    assert failure is not None
    assert (failure.kind, failure.status_code, failure.retryable) == (
        kind,
        code,
        retryable,
    )


def test_failure_override_defers_unknown_errors():
    assert anthropic_failure_override(RuntimeError("boom")) is None
    assert anthropic_failure_override(_status_error(418, "teapot_error")) is None
    stream_error = AnthropicStreamError(
        {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    )
    failure = anthropic_failure_override(stream_error)
    assert failure is not None and failure.kind is FailureKind.OVERLOADED


# --------------------------------------------------------------------------- relay


async def _lines(*lines: str):
    for line in lines:
        yield line


@pytest.mark.asyncio
async def test_iter_sse_events_parses_events_and_comments():
    events = [
        event
        async for event in iter_sse_events(
            _lines(
                ": comment",
                "event: ping",
                'data: {"type": "ping"}',
                "",
                'data: {"type": "message_stop"}',
            )
        )
    ]
    assert events == [
        ("ping", {"type": "ping"}),
        ("message_stop", {"type": "message_stop"}),
    ]


def test_relay_holds_frames_until_first_content_block():
    relay = AnthropicEventRelay(suppress_reasoning=False)
    assert relay.relay("message_start", {"type": "message_start", "message": {}}) == []
    assert relay.relay("ping", {"type": "ping"}) == []
    assert not relay.committed

    frames = relay.relay(
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
    )
    assert relay.committed
    assert [frame.split("\n", 1)[0] for frame in frames] == [
        "event: message_start",
        "event: ping",
        "event: content_block_start",
    ]
    with pytest.raises(TruncatedProviderStreamError):
        relay.finish()


def test_relay_suppresses_reasoning_and_renumbers_blocks():
    relay = AnthropicEventRelay(suppress_reasoning=True)
    relay.relay("message_start", {"type": "message_start", "message": {}})
    thinking = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "thinking"},
    }
    assert relay.relay("content_block_start", thinking) == []
    assert (
        relay.relay("content_block_delta", {"type": "content_block_delta", "index": 0})
        == []
    )
    assert not relay.committed

    frames = relay.relay(
        "content_block_start",
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
    )
    payload = json.loads(frames[-1].split("data: ", 1)[1])
    assert payload["index"] == 0
    delta = relay.relay(
        "content_block_delta", {"type": "content_block_delta", "index": 1}
    )
    assert json.loads(delta[0].split("data: ", 1)[1])["index"] == 0


def test_relay_raises_on_error_event():
    relay = AnthropicEventRelay(suppress_reasoning=False)
    with pytest.raises(AnthropicStreamError, match="overloaded_error"):
        relay.relay(
            "error",
            {"type": "error", "error": {"type": "overloaded_error", "message": "x"}},
        )


# -------------------------------------------------------------------- live provider

_SUCCESS_SSE = (
    "event: message_start\n"
    'data: {"type": "message_start", "message": {"id": "msg_1", "type": "message", '
    '"role": "assistant", "model": "claude-sonnet-4-5", "content": [], '
    '"stop_reason": null, "stop_sequence": null, '
    '"usage": {"input_tokens": 12, "output_tokens": 1, '
    '"cache_read_input_tokens": 7}}}\n\n'
    "event: content_block_start\n"
    'data: {"type": "content_block_start", "index": 0, '
    '"content_block": {"type": "text", "text": ""}}\n\n'
    "event: content_block_delta\n"
    'data: {"type": "content_block_delta", "index": 0, '
    '"delta": {"type": "text_delta", "text": "Hi!"}}\n\n'
    "event: content_block_stop\n"
    'data: {"type": "content_block_stop", "index": 0}\n\n'
    "event: message_delta\n"
    'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn", '
    '"stop_sequence": null}, "usage": {"output_tokens": 3}}\n\n'
    "event: message_stop\n"
    'data: {"type": "message_stop"}\n\n'
)


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> AnthropicProvider:
    provider = AnthropicProvider(
        ProviderConfig(api_key="sk-ant-test", base_url=ANTHROPIC_DEFAULT_BASE),
        admission=immediate_admission(provider_name="anthropic_api"),
    )
    provider._client = httpx.AsyncClient(
        base_url=ANTHROPIC_DEFAULT_BASE,
        headers=provider._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return provider


def _sse_response(text: str = _SUCCESS_SSE) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=text.encode()
    )


async def _collect(provider: AnthropicProvider, request: MessagesRequest) -> str:
    chunks = [
        chunk
        async for chunk in provider.stream_response(
            request, request_id="req_1", reasoning=reasoning_for(request)
        )
    ]
    return "".join(chunks)


@pytest.mark.asyncio
async def test_stream_forwards_native_events_and_headers():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _sse_response()

    provider = _provider(handler)
    output = await _collect(
        provider, _request(betas=["context-management-2025-06-27", "oauth-x"])
    )

    assert '"cache_read_input_tokens": 7' in output
    assert '"text": "Hi!"' in output
    assert output.rstrip().endswith('data: {"type": "message_stop"}')
    sent = seen[0]
    assert sent.url.path == "/v1/messages"
    assert sent.headers["x-api-key"] == "sk-ant-test"
    assert sent.headers["anthropic-version"] == ANTHROPIC_API_VERSION
    assert sent.headers["anthropic-beta"] == "context-management-2025-06-27"
    assert json.loads(sent.content)["stream"] is True
    await provider.cleanup()


@pytest.mark.asyncio
async def test_stream_retries_overload_before_output():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                529,
                json={
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": "busy"},
                },
            )
        return _sse_response()

    output = await _collect(_provider(handler), _request())
    assert calls["n"] == 2
    assert '"text": "Hi!"' in output


@pytest.mark.asyncio
async def test_stream_retries_error_event_before_first_content_block():
    calls = {"n": 0}
    early_error = (
        "event: message_start\n"
        'data: {"type": "message_start", "message": {"id": "m", "content": []}}\n\n'
        "event: error\n"
        'data: {"type": "error", "error": {"type": "overloaded_error", "message": "x"}}\n\n'
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _sse_response(early_error if calls["n"] == 1 else _SUCCESS_SSE)

    output = await _collect(_provider(handler), _request())
    assert calls["n"] == 2
    assert output.count("event: message_start") == 1


@pytest.mark.asyncio
async def test_stream_applies_thinking_fallback_on_400():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body["thinking"]["type"] == "adaptive":
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "thinking.type: adaptive is not supported for this model",
                    },
                },
            )
        return _sse_response()

    await _collect(_provider(handler), _request(thinking={"type": "adaptive"}))
    assert [body["thinking"]["type"] for body in bodies] == ["adaptive", "enabled"]


@pytest.mark.asyncio
async def test_stream_raises_canonical_failure_for_bad_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "invalid x-api-key",
                },
            },
        )

    with pytest.raises(ExecutionFailure) as excinfo:
        await _collect(_provider(handler), _request())
    assert excinfo.value.kind is FailureKind.AUTHENTICATION
    assert "ANTHROPIC_API_KEY" in excinfo.value.message
    assert "invalid x-api-key" in excinfo.value.message


@pytest.mark.asyncio
async def test_stream_failure_after_output_is_not_retried():
    calls = {"n": 0}
    truncated = _SUCCESS_SSE.split("event: message_delta")[0]

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _sse_response(truncated)

    chunks: list[str] = []
    stream = _provider(handler).stream_response(
        _request(), request_id="r", reasoning=REASONING_DEFAULT
    )
    with pytest.raises(ExecutionFailure):
        while True:
            chunks.append(await anext(stream))
    assert calls["n"] == 1
    assert any('"text": "Hi!"' in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_list_model_ids_paginates():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        if request.url.params.get("after_id") == "b":
            return httpx.Response(200, json={"data": [{"id": "c"}], "has_more": False})
        return httpx.Response(
            200,
            json={"data": [{"id": "a"}, {"id": "b"}], "has_more": True, "last_id": "b"},
        )

    assert await _provider(handler).list_model_ids() == frozenset({"a", "b", "c"})


def test_preflight_rejects_invalid_extra_body():
    provider = _provider(lambda _request: _sse_response())
    with pytest.raises(InvalidRequestError):
        provider.preflight_stream(
            _request(extra_body={"messages": []}), reasoning=REASONING_DEFAULT
        )
