"""Tests for the TokenRouter OpenAI-chat provider."""

import pytest

from codefa.config.constants import ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS
from codefa.config.provider_catalog import TOKENROUTER_DEFAULT_BASE
from codefa.core.anthropic.models import Message, MessagesRequest, Tool
from codefa.providers.base import ProviderConfig
from codefa.providers.openai_chat import (
    OpenAIChatProvider,
)
from tests.providers.support import (
    REASONING_OFF,
    immediate_admission,
    profiled_provider,
    reasoning_for,
)


@pytest.fixture
def tokenrouter_config():
    return ProviderConfig(
        api_key="test-tokenrouter-key",
        base_url=TOKENROUTER_DEFAULT_BASE,
        rate_limit=10,
        rate_window=60,
    )


@pytest.fixture
def tokenrouter_provider(tokenrouter_config):
    return profiled_provider(
        "tokenrouter",
        tokenrouter_config,
        admission=immediate_admission(),
    )


def test_default_base_url():
    assert TOKENROUTER_DEFAULT_BASE == "https://api.tokenrouter.com/v1"


def test_init_uses_openai_chat_provider(tokenrouter_provider):
    assert isinstance(tokenrouter_provider, OpenAIChatProvider)
    assert tokenrouter_provider._api_key == "test-tokenrouter-key"
    assert tokenrouter_provider._base_url == TOKENROUTER_DEFAULT_BASE
    assert tokenrouter_provider._provider_name == "TOKENROUTER"


def test_build_request_body_openai_shape_and_defaults(tokenrouter_provider):
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-5-sonnet",
            "messages": [Message(role="user", content="Hello TokenRouter")],
            "tools": [
                Tool(
                    name="echo",
                    description="Echo input",
                    input_schema={"type": "object", "properties": {}},
                )
            ],
            "thinking": {"type": "enabled", "budget_tokens": 2048},
        }
    )

    body = tokenrouter_provider._build_request_body(
        request, reasoning=reasoning_for(request)
    )

    assert body["model"] == "claude-3-5-sonnet"
    assert body["messages"][0] == {"role": "user", "content": "Hello TokenRouter"}
    assert body["tools"][0]["function"]["name"] == "echo"
    assert body["reasoning_effort"] == "high"
    assert body["max_tokens"] == ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS


def test_build_request_body_honors_effective_no_thinking(tokenrouter_provider):
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-5-sonnet",
            "messages": [{"role": "user", "content": "Explore the codebase."}],
        }
    )

    body = tokenrouter_provider._build_request_body(request, reasoning=REASONING_OFF)

    assert body["reasoning_effort"] == "none"
