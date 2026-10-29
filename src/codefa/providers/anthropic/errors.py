"""Anthropic API error classification (provider-owned failure semantics)."""

from contextlib import suppress
from typing import Any

import httpx

from codefa.core.anthropic.errors import failure_kind_for_anthropic_error_type
from codefa.core.failures import ExecutionFailure, FailureKind
from codefa.providers.failure_policy import (
    context_window_exceeded_provider_failure,
    overloaded_provider_failure,
)


class AnthropicStreamError(RuntimeError):
    """An ``event: error`` frame received inside an Anthropic SSE stream."""

    def __init__(self, payload: dict[str, Any]) -> None:
        error_type, message = anthropic_error_fields(payload)
        super().__init__(
            f"Anthropic stream error ({error_type or 'unknown'}): {message}".strip()
        )
        self.body = payload


def anthropic_error_fields(source: Any) -> tuple[str | None, str]:
    """Return ``(error.type, error.message)`` from an exception or JSON payload."""
    body = source
    if isinstance(source, BaseException):
        body = getattr(source, "body", None)
        if body is None and isinstance(source, httpx.HTTPStatusError):
            with suppress(Exception):
                body = source.response.json()
    if not isinstance(body, dict):
        return None, ""
    error = body.get("error")
    if not isinstance(error, dict):
        return None, ""
    error_type = error.get("type")
    message = error.get("message")
    return (
        error_type if isinstance(error_type, str) else None,
        message if isinstance(message, str) else "",
    )


def anthropic_failure_override(exc: Exception) -> ExecutionFailure | None:
    """Map documented Anthropic error types to canonical failures."""
    error_type, message = anthropic_error_fields(exc)
    if error_type is None:
        return None
    mapped = failure_kind_for_anthropic_error_type(error_type)
    if mapped is None:
        return None
    kind, status = mapped
    lowered = message.lower()

    match kind:
        case FailureKind.AUTHENTICATION:
            return _failure(
                kind,
                401,
                "Anthropic rejected the API key. Check ANTHROPIC_API_KEY.",
                False,
            )
        case FailureKind.PERMISSION if status == 402:
            return _billing_failure()
        case FailureKind.PERMISSION:
            return _failure(
                kind,
                403,
                "The Anthropic API key is not permitted to perform this request.",
                False,
            )
        case FailureKind.RATE_LIMIT:
            return _failure(
                kind, 429, "Anthropic rate limit reached. Please retry shortly.", True
            )
        case FailureKind.OVERLOADED:
            return overloaded_provider_failure()
        case FailureKind.TIMEOUT:
            return _failure(kind, 504, "Anthropic request timed out.", True)
        case FailureKind.UPSTREAM:
            return _failure(kind, 500, "Anthropic API internal error.", True)
        case FailureKind.INVALID_REQUEST if status == 404:
            return _failure(
                kind,
                404,
                "Anthropic could not find the requested model or resource.",
                False,
            )
        case FailureKind.INVALID_REQUEST if status == 413:
            return _failure(
                kind, 413, "The request is too large for the Anthropic API.", False
            )
        case FailureKind.INVALID_REQUEST:
            if "prompt is too long" in lowered or "context window" in lowered:
                return context_window_exceeded_provider_failure()
            if "credit balance" in lowered:
                return _billing_failure()
            return _failure(kind, 400, "Invalid request sent to Anthropic.", False)
    return None


def _billing_failure() -> ExecutionFailure:
    return _failure(
        FailureKind.PERMISSION,
        402,
        "Anthropic billing problem: check your plan and credit balance.",
        False,
    )


def _failure(
    kind: FailureKind, status_code: int, message: str, retryable: bool
) -> ExecutionFailure:
    return ExecutionFailure(
        kind=kind, status_code=status_code, message=message, retryable=retryable
    )
