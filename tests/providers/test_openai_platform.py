"""Tests for the OpenAI Platform (GPT) provider."""

import httpx
import openai
import pytest

from codefa.config.provider_catalog import OPENAI_DEFAULT_BASE, PROVIDER_CATALOG
from codefa.core.anthropic.models import MessagesRequest
from codefa.core.failures import FailureKind
from codefa.core.reasoning import ReasoningEffort, ReasoningPolicy
from codefa.providers.base import ProviderConfig
from codefa.providers.openai_platform import OpenAIProvider, is_chat_model_id
from codefa.providers.openai_platform.parameters import (
    ParameterAdjustment,
    apply_parameter_adjustments,
    rejected_parameter_adjustment,
)
from tests.providers.support import REASONING_OFF, immediate_admission, reasoning_for


@pytest.fixture
def provider() -> OpenAIProvider:
    return OpenAIProvider(
        ProviderConfig(api_key="sk-test", base_url=OPENAI_DEFAULT_BASE),
        admission=immediate_admission(provider_name="openai_api"),
    )


def _bad_request(message: str, *, param: str | None = None) -> openai.BadRequestError:
    request = httpx.Request("POST", f"{OPENAI_DEFAULT_BASE}/chat/completions")
    response = httpx.Response(400, request=request)
    body = {"message": message, "type": "invalid_request_error", "param": param}
    return openai.BadRequestError(message, response=response, body=body)


def _request(**overrides) -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "gpt-5",
            "max_tokens": 32000,
            "messages": [{"role": "user", "content": "Hello"}],
            **overrides,
        }
    )


def test_catalog_entry():
    descriptor = PROVIDER_CATALOG["openai_api"]
    assert descriptor.credential_env == "OPENAI_API_KEY"
    assert descriptor.default_base_url == "https://api.openai.com/v1"


def test_request_uses_max_completion_tokens_and_named_effort(provider):
    request = _request(output_config={"effort": "high"})
    body = provider._build_request_body(request, reasoning=reasoning_for(request))
    assert body["max_completion_tokens"] == 32000
    assert "max_tokens" not in body
    assert body["reasoning_effort"] == "high"


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (ReasoningPolicy.on(effort=ReasoningEffort.MINIMAL), "minimal"),
        (ReasoningPolicy.on(effort=ReasoningEffort.MAX), "xhigh"),
        (REASONING_OFF, "none"),
    ],
)
def test_reasoning_effort_mapping(provider, policy, expected):
    body = provider._build_request_body(_request(), reasoning=policy)
    assert body["reasoning_effort"] == expected


def test_history_reasoning_is_not_replayed(provider):
    request = _request(
        messages=[
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "secret", "signature": "s"},
                    {"type": "text", "text": "Hello"},
                ],
            },
            {"role": "user", "content": "Again"},
        ]
    )
    body = provider._build_request_body(request, reasoning=reasoning_for(request))
    assistant = body["messages"][1]
    assert "secret" not in str(assistant)
    assert "reasoning_content" not in assistant


@pytest.mark.parametrize(
    ("model_id", "chat"),
    [
        ("gpt-5", True),
        ("gpt-4.1-mini", True),
        ("o3", True),
        ("chatgpt-4o-latest", True),
        ("text-embedding-3-large", False),
        ("tts-1", False),
        ("whisper-1", False),
        ("dall-e-3", False),
        ("gpt-image-1", False),
        ("omni-moderation-latest", False),
        ("gpt-4o-realtime-preview", False),
        ("gpt-4o-mini-search-preview", False),
        ("gpt-3.5-turbo-instruct", False),
        ("o1-pro", False),
        ("gpt-5-pro", False),
        ("gpt-5-codex", False),
    ],
)
def test_chat_model_filter(model_id, chat):
    assert is_chat_model_id(model_id) is chat


def test_reasoning_effort_value_rejection_picks_nearest_supported():
    error = _bad_request(
        "Unsupported value: 'reasoning_effort' does not support 'none' with this "
        "model. Supported values are: 'minimal', 'low', 'medium', and 'high'.",
        param="reasoning_effort",
    )
    adjustment = rejected_parameter_adjustment(error, {"reasoning_effort": "none"})
    assert adjustment == ParameterAdjustment("reasoning_effort", "set", "minimal")

    error = _bad_request(
        "Unsupported value: 'reasoning_effort' does not support 'xhigh'. "
        "Supported values are: 'low', 'medium', and 'high'.",
    )
    adjustment = rejected_parameter_adjustment(error, {"reasoning_effort": "xhigh"})
    assert adjustment == ParameterAdjustment("reasoning_effort", "set", "high")


def test_unsupported_parameters_are_removed_or_renamed():
    error = _bad_request("Unrecognized request argument supplied: reasoning_effort")
    assert rejected_parameter_adjustment(
        error, {"reasoning_effort": "high"}
    ) == ParameterAdjustment("reasoning_effort", "remove")

    error = _bad_request(
        "Unsupported value: 'temperature' does not support 0.2 with this model. "
        "Only the default (1) value is supported.",
        param="temperature",
    )
    assert rejected_parameter_adjustment(
        error, {"temperature": 0.2}
    ) == ParameterAdjustment("temperature", "remove")

    error = _bad_request(
        "Unsupported parameter: 'max_completion_tokens' is not supported with this "
        "model. Use 'max_tokens' instead.",
        param="max_completion_tokens",
    )
    adjustment = rejected_parameter_adjustment(error, {"max_completion_tokens": 10})
    assert adjustment is not None
    assert adjustment == ParameterAdjustment(
        "max_completion_tokens", "rename", "max_tokens"
    )
    assert apply_parameter_adjustments(
        {"max_completion_tokens": 10}, {adjustment.param: adjustment}
    ) == {"max_tokens": 10}


def test_essential_or_absent_parameters_are_never_adjusted():
    error = _bad_request("Unsupported parameter: 'tools'", param="tools")
    assert rejected_parameter_adjustment(error, {"tools": []}) is None
    error = _bad_request("Unsupported parameter: 'seed'", param="seed")
    assert rejected_parameter_adjustment(error, {}) is None
    assert rejected_parameter_adjustment(RuntimeError("x"), {"seed": 1}) is None


def test_retry_learns_per_model_and_stops_when_exhausted(provider):
    body = {"model": "gpt-4.1", "messages": [], "reasoning_effort": "high"}
    error = _bad_request(
        "Unrecognized request argument supplied: reasoning_effort",
        param="reasoning_effort",
    )

    retry = provider._next_create_retry_body(error, body, set())
    assert retry is not None
    assert "reasoning_effort" not in provider._prepare_create_body(body)
    # A second identical rejection cannot loop forever.
    assert provider._next_create_retry_body(error, body, set()) is None
    # Other models are unaffected.
    other = {**body, "model": "gpt-5"}
    assert provider._prepare_create_body(other) == other


def test_insufficient_quota_is_not_retried(provider):
    request = httpx.Request("POST", f"{OPENAI_DEFAULT_BASE}/chat/completions")
    error = openai.RateLimitError(
        "You exceeded your current quota",
        response=httpx.Response(429, request=request),
        body={"code": "insufficient_quota", "message": "quota"},
    )
    failure = provider._provider_failure_override(error)
    assert failure is not None
    assert failure.kind is FailureKind.PERMISSION
    assert failure.retryable is False
    assert provider._provider_failure_override(RuntimeError("other")) is None


@pytest.mark.asyncio
async def test_list_model_ids_filters_non_chat_models(provider, monkeypatch):
    async def fake_list(self):
        return frozenset({"gpt-5", "text-embedding-3-small", "tts-1-hd", "o4-mini"})

    monkeypatch.setattr(
        "codefa.providers.openai_chat.provider.OpenAIChatProvider.list_model_ids",
        fake_list,
    )
    assert await provider.list_model_ids() == frozenset({"gpt-5", "o4-mini"})
