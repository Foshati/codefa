"""OpenAI Platform (GPT) provider over the Chat Completions API."""

import re
from typing import Any

from loguru import logger

from codefa.core.anthropic import ReasoningReplayMode
from codefa.core.failures import ExecutionFailure, FailureKind
from codefa.core.reasoning import ReasoningEffort
from codefa.providers.admission import ProviderAdmissionController
from codefa.providers.base import ProviderConfig
from codefa.providers.failure_policy import transient_error_text
from codefa.providers.openai_chat import (
    NamedEffortReasoning,
    OpenAIChatProfile,
    OpenAIChatProvider,
    OpenAIChatRequestPolicy,
    validate_extra_body_does_not_override_canonical_fields,
)

from .parameters import (
    ParameterAdjustment,
    apply_parameter_adjustments,
    rejected_parameter_adjustment,
)

OPENAI_PROFILE = OpenAIChatProfile(
    OpenAIChatRequestPolicy(
        provider_name="OPENAI",
        reasoning_replay=ReasoningReplayMode.DISABLED,
        include_extra_body=True,
        extra_body_validator=validate_extra_body_does_not_override_canonical_fields,
        max_tokens_field="max_completion_tokens",
    ),
    NamedEffortReasoning(
        (
            (ReasoningEffort.MINIMAL, "minimal"),
            (ReasoningEffort.LOW, "low"),
            (ReasoningEffort.MEDIUM, "medium"),
            (ReasoningEffort.HIGH, "high"),
            (ReasoningEffort.XHIGH, "xhigh"),
            (ReasoningEffort.MAX, "xhigh"),
        ),
        disabled_value="none",
    ),
)

# Model families served by other OpenAI endpoints (embeddings, audio, images,
# moderation, legacy completions, or Responses-only models).
_NON_CHAT_MODEL = re.compile(
    r"embedding|tts|whisper|transcribe|dall-e|image|moderation|davinci|babbage"
    r"|realtime|audio|search|sora|instruct|computer-use|deep-research|codex"
    r"|(?:^|-)pro(?:$|-)"
)


def is_chat_model_id(model_id: str) -> bool:
    """Return whether an OpenAI model id is usable with Chat Completions tools."""
    return _NON_CHAT_MODEL.search(model_id.lower()) is None


class OpenAIProvider(OpenAIChatProvider):
    """OpenAI GPT models with learned per-model parameter compatibility."""

    def __init__(
        self, config: ProviderConfig, *, admission: ProviderAdmissionController
    ) -> None:
        super().__init__(config, profile=OPENAI_PROFILE, admission=admission)
        self._model_adjustments: dict[str, dict[str, ParameterAdjustment]] = {}

    async def list_model_ids(self) -> frozenset[str]:
        """Advertise only chat-capable models."""
        return frozenset(
            model_id
            for model_id in await super().list_model_ids()
            if is_chat_model_id(model_id)
        )

    def _provider_failure_override(self, error: Exception) -> ExecutionFailure | None:
        if getattr(
            error, "code", None
        ) == "insufficient_quota" or "insufficient_quota" in transient_error_text(
            error
        ):
            return ExecutionFailure(
                kind=FailureKind.PERMISSION,
                status_code=402,
                message="OpenAI quota exhausted: check your plan and billing details.",
                retryable=False,
            )
        return None

    def _prepare_create_body(self, body: dict[str, Any]) -> dict[str, Any]:
        adjustments = self._model_adjustments.get(str(body.get("model")))
        if not adjustments:
            return body
        return apply_parameter_adjustments(body, adjustments)

    def _next_create_retry_body(
        self,
        error: Exception,
        body: dict,
        used_retry_kinds: set[str],
    ) -> dict | None:
        retry_body = super()._next_create_retry_body(error, body, used_retry_kinds)
        if retry_body is not None:
            return retry_body
        model = body.get("model")
        if not isinstance(model, str):
            return None
        adjustment = rejected_parameter_adjustment(
            error, self._prepare_create_body(body)
        )
        if adjustment is None:
            return None
        learned = self._model_adjustments.setdefault(model, {})
        if learned.get(adjustment.param) == adjustment:
            return None
        learned[adjustment.param] = adjustment
        logger.warning(
            "{}_STREAM: model {} rejected {!r}; retrying with {} {}",
            self._provider_name,
            model,
            adjustment.param,
            adjustment.action,
            "" if adjustment.value is None else repr(adjustment.value),
        )
        return dict(body)
