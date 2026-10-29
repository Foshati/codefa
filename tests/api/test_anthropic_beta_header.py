"""The ``anthropic-beta`` request header is captured for native Anthropic upstreams."""

from starlette.requests import Request

from codefa.api.routes import _anthropic_betas
from codefa.core.anthropic import MessagesRequest
from codefa.core.anthropic.request_serialization import dump_messages_request


def _request(*headers: tuple[bytes, bytes]) -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": list(headers)}
    )


def test_beta_header_values_are_split_and_merged():
    request = _request(
        (b"anthropic-beta", b"claude-code-20250219, context-management-2025-06-27"),
        (b"anthropic-beta", b"interleaved-thinking-2025-05-14"),
    )
    assert _anthropic_betas(request) == [
        "claude-code-20250219",
        "context-management-2025-06-27",
        "interleaved-thinking-2025-05-14",
    ]


def test_missing_or_blank_beta_header_yields_none():
    assert _anthropic_betas(_request()) is None
    assert _anthropic_betas(_request((b"anthropic-beta", b" , "))) is None


def test_betas_never_leak_into_serialized_request_body():
    request = MessagesRequest.model_validate(
        {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    )
    request.betas = ["x-beta"]
    assert "betas" not in dump_messages_request(request)
    assert request.model_copy(deep=True).betas == ["x-beta"]
