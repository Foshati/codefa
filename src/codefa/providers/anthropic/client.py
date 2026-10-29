"""Native Anthropic Messages API provider (no protocol conversion)."""

import asyncio
import sys
from collections.abc import AsyncIterator
from typing import Any

import httpx
from loguru import logger

from codefa.core.anthropic.models import MessagesRequest
from codefa.core.failures import ExecutionFailure
from codefa.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from codefa.core.trace import trace_event
from codefa.core.version import package_version
from codefa.providers.admission import ProviderAdmissionController, ProviderAttempt
from codefa.providers.base import BaseProvider, ProviderConfig
from codefa.providers.failure_policy import (
    classify_provider_failure,
    transient_error_text,
    underlying_provider_error,
)
from codefa.providers.http import close_provider_stream
from codefa.providers.model_listing import ModelListResponseError

from .errors import anthropic_failure_override
from .request import (
    AnthropicRequestPlan,
    build_anthropic_request_plan,
    next_fallback_plan,
)
from .stream import AnthropicEventRelay, iter_sse_events

ANTHROPIC_API_VERSION = "2023-06-01"
_PROVIDER_NAME = "ANTHROPIC"
_MODELS_PAGE_LIMIT = 1000
_MODELS_MAX_PAGES = 20


class AnthropicProvider(BaseProvider):
    """Forward Anthropic Messages requests to ``api.anthropic.com`` natively."""

    def __init__(
        self, config: ProviderConfig, *, admission: ProviderAdmissionController
    ) -> None:
        super().__init__(config)
        self._provider_name = _PROVIDER_NAME
        self._admission = admission
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            proxy=config.proxy or None,
            timeout=httpx.Timeout(
                config.http_read_timeout,
                connect=config.http_connect_timeout,
                read=config.http_read_timeout,
                write=config.http_write_timeout,
            ),
            headers={
                "x-api-key": config.api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "user-agent": f"codefa/{package_version()}",
            },
        )

    async def cleanup(self) -> None:
        """Release HTTP client resources."""
        await self._client.aclose()

    async def list_model_ids(self) -> frozenset[str]:
        """Return model ids from Anthropic's paginated ``/v1/models`` endpoint."""
        return await self._admission.run_with_retry(
            self._fetch_model_ids,
            provider_failure_override=anthropic_failure_override,
        )

    async def _fetch_model_ids(self) -> frozenset[str]:
        model_ids: set[str] = set()
        after_id: str | None = None
        for _ in range(_MODELS_MAX_PAGES):
            params: dict[str, Any] = {"limit": _MODELS_PAGE_LIMIT}
            if after_id is not None:
                params["after_id"] = after_id
            response = await self._client.get("/v1/models", params=params)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise ModelListResponseError(
                    f"{_PROVIDER_NAME} model list response has no data array."
                )
            model_ids.update(
                item["id"]
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            )
            last_id = payload.get("last_id")
            if not payload.get("has_more") or not isinstance(last_id, str):
                break
            after_id = last_id
        return frozenset(model_ids)

    def preflight_stream(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> None:
        """Validate native request construction before streaming."""
        build_anthropic_request_plan(request, reasoning=reasoning)

    def stream_response(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> AsyncIterator[str]:
        """Stream the upstream's native Anthropic SSE."""
        return self._stream(request, request_id=request_id, reasoning=reasoning)

    async def _stream(
        self,
        request: MessagesRequest,
        *,
        request_id: str | None,
        reasoning: ReasoningPolicy,
    ) -> AsyncIterator[str]:
        tag = self._provider_name
        req_tag = f" request_id={request_id}" if request_id else ""
        plan = build_anthropic_request_plan(request, reasoning=reasoning)
        session = self._admission.new_retry_session(request_id=request_id)
        trace_event(
            stage="provider",
            event="provider.request.sent",
            source="provider",
            provider=tag,
            request_id=request_id,
            gateway_model=request.model,
            downstream_model=plan.body.get("model"),
            message_count=len(plan.body.get("messages", [])),
            tool_count=len(plan.body.get("tools", [])),
            betas=list(plan.betas),
        )

        while True:
            attempt: ProviderAttempt | None = None
            response: httpx.Response | None = None
            relay = AnthropicEventRelay(suppress_reasoning=not reasoning.output_enabled)
            try:
                attempt = await self._admission.open_attempt(session)
                response = await self._open_stream(plan)
                async for event_type, data in iter_sse_events(response.aiter_lines()):
                    frames = relay.relay(event_type, data)
                    if relay.committed and not attempt.accepted:
                        await attempt.succeeded()
                    for frame in frames:
                        yield frame
                for frame in relay.finish():
                    yield frame
                trace_event(
                    stage="provider",
                    event="provider.response.completed",
                    source="provider",
                    provider=tag,
                    request_id=request_id,
                    finish_reason=relay.stop_reason,
                    output_tokens=relay.output_tokens,
                    fallbacks=sorted(plan.applied_fallbacks),
                )
                return
            except asyncio.CancelledError, GeneratorExit:
                raise
            except Exception as error:
                if attempt is not None and not relay.committed:
                    fallback = _fallback_for(error, plan)
                    if fallback is not None and session.can_attempt:
                        logger.warning(
                            "{}_STREAM:{} retrying with request fallback {}",
                            tag,
                            req_tag,
                            sorted(fallback.applied_fallbacks - plan.applied_fallbacks),
                        )
                        await attempt.retry_immediately()
                        plan = fallback
                        continue
                    if await attempt.retry(
                        error, provider_failure_override=anthropic_failure_override
                    ):
                        continue
                failure = self._classify(error, request_id=request_id)
                self._log_stream_transport_error(
                    tag,
                    req_tag,
                    underlying_provider_error(error),
                    request_id=request_id,
                )
                trace_event(
                    stage="provider",
                    event="provider.response.error",
                    source="provider",
                    provider=tag,
                    request_id=request_id,
                    exc_type=type(error).__name__,
                    failure_kind=failure.kind.value,
                    status_code=failure.status_code,
                    provider_retryable=failure.retryable,
                    committed=relay.committed,
                )
                raise failure from error
            finally:
                if response is not None:
                    await close_provider_stream(
                        response,
                        active_error=sys.exception(),
                        provider_name=tag,
                        request_id=request_id,
                    )
                if attempt is not None:
                    await attempt.aclose()

    async def _open_stream(self, plan: AnthropicRequestPlan) -> httpx.Response:
        request = self._client.build_request(
            "POST", "/v1/messages", json=plan.body, headers=plan.headers()
        )
        response = await self._client.send(request, stream=True)
        if response.is_success:
            return response
        try:
            await response.aread()
        finally:
            await response.aclose()
        raise httpx.HTTPStatusError(
            f"Anthropic API returned HTTP {response.status_code}",
            request=request,
            response=response,
        )

    def _classify(
        self, error: Exception, *, request_id: str | None
    ) -> ExecutionFailure:
        return classify_provider_failure(
            underlying_provider_error(error),
            provider_name=self._provider_name,
            read_timeout_s=self._config.http_read_timeout,
            request_id=request_id,
            provider_failure_override=anthropic_failure_override,
        )


def _fallback_for(
    error: Exception, plan: AnthropicRequestPlan
) -> AnthropicRequestPlan | None:
    if not (
        isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 400
    ):
        return None
    return next_fallback_plan(plan, transient_error_text(error))
