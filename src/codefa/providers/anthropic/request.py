"""Native Anthropic Messages request construction and bounded request fallbacks.

Requests are forwarded in Anthropic's own wire shape. This module only
normalizes conversation history that other upstreams may have produced
(unsigned thinking, whitespace-only text, ``system`` role turns) and lets the
provider-neutral reasoning policy author ``thinking`` and ``output_config.effort``.
"""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from codefa.application.errors import InvalidRequestError
from codefa.config.constants import ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS
from codefa.core.anthropic import dump_messages_request
from codefa.core.anthropic.models import MessagesRequest
from codefa.core.reasoning import ReasoningControl, ReasoningEffort, ReasoningPolicy

ANTHROPIC_MIN_THINKING_BUDGET = 1024

# Anthropic's documented named-effort vocabulary for ``output_config.effort``.
_EFFORT_VALUES: dict[ReasoningEffort, str] = {
    ReasoningEffort.MINIMAL: "low",
    ReasoningEffort.LOW: "low",
    ReasoningEffort.MEDIUM: "medium",
    ReasoningEffort.HIGH: "high",
    ReasoningEffort.XHIGH: "xhigh",
    ReasoningEffort.MAX: "max",
}

# Fields the reasoning policy or request plan owns; caller extra_body cannot set them.
_EXTRA_BODY_RESERVED_KEYS = frozenset({"thinking", "output_config", "stream"})
_THINKING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})

FALLBACK_BETAS = "betas"
FALLBACK_HISTORY_THINKING = "history_thinking"
FALLBACK_EFFORT = "effort"
FALLBACK_THINKING_SHAPE = "thinking_shape"


@dataclass(frozen=True, slots=True)
class AnthropicRequestPlan:
    """One upstream request: JSON body, beta header values, and applied fallbacks."""

    body: dict[str, Any]
    betas: tuple[str, ...] = ()
    thinking_budget: int | None = None
    applied_fallbacks: frozenset[str] = frozenset()

    def headers(self) -> dict[str, str]:
        return {"anthropic-beta": ",".join(self.betas)} if self.betas else {}


def build_anthropic_request_plan(
    request: MessagesRequest,
    *,
    reasoning: ReasoningPolicy,
) -> AnthropicRequestPlan:
    """Return the native upstream request for one routed Messages request."""
    body = dump_messages_request(request)
    body.pop("stream", None)
    _merge_extra_body(body, body.pop("extra_body", None))

    system, messages = _native_turns(body.get("system"), body.get("messages", []))
    if not messages:
        raise InvalidRequestError(
            "Anthropic requests need at least one message with non-empty content."
        )
    body["messages"] = messages
    if system is None:
        body.pop("system", None)
    else:
        body["system"] = system

    max_tokens = body.get("max_tokens")
    if not _is_positive_int(max_tokens):
        body["max_tokens"] = ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS

    thinking_budget = _enabled_budget(reasoning, body["max_tokens"])
    _apply_reasoning(body, reasoning, thinking_budget)
    body["stream"] = True
    return AnthropicRequestPlan(
        body=body,
        betas=forwardable_betas(request.betas),
        thinking_budget=thinking_budget,
    )


def next_fallback_plan(
    plan: AnthropicRequestPlan, error_text: str
) -> AnthropicRequestPlan | None:
    """Return one corrected plan for a 400 rejection, or ``None`` when exhausted.

    Each correction runs at most once per request, so retries stay bounded.
    Corrections react to the upstream's own error text; they never inspect the
    model name.
    """
    text = error_text.lower()
    applied = plan.applied_fallbacks

    if FALLBACK_BETAS not in applied and plan.betas and "anthropic-beta" in text:
        return replace(plan, betas=(), applied_fallbacks=applied | {FALLBACK_BETAS})

    if (
        FALLBACK_HISTORY_THINKING not in applied
        and "signature" in text
        and _has_history_thinking(plan.body)
    ):
        body = dict(plan.body)
        body["messages"] = _without_history_thinking(body["messages"])
        return replace(
            plan,
            body=body,
            applied_fallbacks=applied | {FALLBACK_HISTORY_THINKING},
        )

    output_config = plan.body.get("output_config")
    if (
        FALLBACK_EFFORT not in applied
        and "effort" in text
        and isinstance(output_config, dict)
        and "effort" in output_config
    ):
        body = dict(plan.body)
        remaining = {k: v for k, v in output_config.items() if k != "effort"}
        if remaining:
            body["output_config"] = remaining
        else:
            body.pop("output_config")
        return replace(plan, body=body, applied_fallbacks=applied | {FALLBACK_EFFORT})

    thinking = plan.body.get("thinking")
    if (
        FALLBACK_THINKING_SHAPE not in applied
        and isinstance(thinking, dict)
        and any(marker in text for marker in ("thinking", "adaptive", "budget_tokens"))
    ):
        replacement: dict[str, Any] | None = None
        if thinking.get("type") == "adaptive" and plan.thinking_budget is not None:
            replacement = {"type": "enabled", "budget_tokens": plan.thinking_budget}
        elif thinking.get("type") == "enabled":
            replacement = {"type": "adaptive"}
        if replacement is not None:
            body = dict(plan.body)
            body["thinking"] = replacement
            return replace(
                plan,
                body=body,
                applied_fallbacks=applied | {FALLBACK_THINKING_SHAPE},
            )
    return None


def forwardable_betas(betas: Iterable[str] | None) -> tuple[str, ...]:
    """Return de-duplicated client beta flags that are valid with an API key."""
    if not betas:
        return ()
    result: list[str] = []
    for raw in betas:
        for value in str(raw).split(","):
            beta = value.strip()
            # OAuth betas belong to claude.ai subscription logins, not API keys.
            if beta and not beta.startswith("oauth-") and beta not in result:
                result.append(beta)
    return tuple(result)


def _merge_extra_body(body: dict[str, Any], extra_body: Any) -> None:
    if extra_body in (None, {}):
        return
    if not isinstance(extra_body, Mapping):
        raise InvalidRequestError("extra_body must be an object when provided.")
    for key, value in extra_body.items():
        name = str(key)
        if name in body or name in _EXTRA_BODY_RESERVED_KEYS:
            raise InvalidRequestError(
                f"extra_body cannot override the Anthropic request field {name!r}."
            )
        body[name] = deepcopy(value)


def _native_turns(
    system: Any, messages: list[dict[str, Any]]
) -> tuple[Any, list[dict[str, Any]]]:
    """Move ``system`` role turns into ``system`` and drop empty content."""
    extra_system: list[dict[str, Any]] = []
    native: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            text = _content_text(content)
            if text.strip():
                extra_system.append({"type": "text", "text": text})
            continue
        cleaned = _native_content(content)
        if cleaned is not None:
            native.append({"role": role, "content": cleaned})

    if not extra_system:
        return system, native
    blocks: list[Any] = []
    if isinstance(system, str):
        if system.strip():
            blocks.append({"type": "text", "text": system})
    elif isinstance(system, list):
        blocks.extend(system)
    return [*blocks, *extra_system], native


def _native_content(content: Any) -> Any:
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return content
    blocks = [block for block in content if _keep_block(block)]
    return blocks or None


def _keep_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return True
    block_type = block.get("type")
    if block_type == "thinking":
        # Anthropic requires a valid signature; other upstreams never provide one.
        return bool(block.get("signature"))
    if block_type == "text":
        text = block.get("text")
        return isinstance(text, str) and bool(text.strip())
    return True


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _has_history_thinking(body: Mapping[str, Any]) -> bool:
    return any(
        isinstance(block, dict) and block.get("type") in _THINKING_BLOCK_TYPES
        for message in body.get("messages", [])
        if isinstance(message.get("content"), list)
        for block in message["content"]
    )


def _without_history_thinking(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            result.append(message)
            continue
        blocks = [
            block
            for block in content
            if not (
                isinstance(block, dict) and block.get("type") in _THINKING_BLOCK_TYPES
            )
        ]
        if blocks:
            result.append({**message, "content": blocks})
    return result


def _apply_reasoning(
    body: dict[str, Any],
    policy: ReasoningPolicy,
    thinking_budget: int | None,
) -> None:
    """Sole writer of ``thinking`` and ``output_config.effort``."""
    body.pop("thinking", None)
    raw_config = body.get("output_config")
    output_config = dict(raw_config) if isinstance(raw_config, dict) else {}
    output_config.pop("effort", None)
    if policy.effort is not None:
        output_config["effort"] = _EFFORT_VALUES[policy.effort]
    if output_config:
        body["output_config"] = output_config
    else:
        body.pop("output_config", None)

    if policy.control is ReasoningControl.OFF:
        body["thinking"] = {"type": "disabled"}
        return
    if policy.control is ReasoningControl.DEFAULT:
        return

    if policy.budget_tokens is not None and thinking_budget is not None:
        body["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    else:
        body["thinking"] = {"type": "adaptive"}
    _drop_sampling_incompatible_with_thinking(body)


def _enabled_budget(policy: ReasoningPolicy, max_tokens: int) -> int | None:
    """Return a documented-range budget (>= 1024 and < max_tokens), if possible."""
    if policy.control is not ReasoningControl.ON:
        return None
    if max_tokens <= ANTHROPIC_MIN_THINKING_BUDGET:
        return None
    requested = policy.numeric_budget_tokens or ANTHROPIC_MIN_THINKING_BUDGET
    return min(max(requested, ANTHROPIC_MIN_THINKING_BUDGET), max_tokens - 1)


def _drop_sampling_incompatible_with_thinking(body: dict[str, Any]) -> None:
    """Remove sampling fields Anthropic rejects while thinking is enabled."""
    if body.get("temperature") not in (None, 1, 1.0):
        body.pop("temperature")
    body.pop("top_k", None)
    top_p = body.get("top_p")
    if isinstance(top_p, int | float) and top_p < 0.95:
        body.pop("top_p")


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
