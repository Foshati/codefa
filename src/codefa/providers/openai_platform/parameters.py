"""Learn request parameters an OpenAI model rejects, and adjust future requests.

OpenAI models differ in which Chat Completions parameters they accept (for
example ``reasoning_effort``, ``temperature``, or ``max_completion_tokens``).
Instead of guessing from model names, the provider reacts to the upstream's own
400 rejection, which names the parameter and sometimes its supported values.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

_ESSENTIAL_PARAMS = frozenset({"model", "messages", "stream", "tools", "tool_choice"})
_TOKEN_FIELD_RENAMES = {
    "max_completion_tokens": "max_tokens",
    "max_tokens": "max_completion_tokens",
}
_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh")
_PARAM_PATTERNS = (
    re.compile(r"unsupported parameter:\s*'([a-z_]+)'"),
    re.compile(r"unsupported value:\s*'([a-z_]+)'"),
    re.compile(r"unrecognized request argument supplied:\s*([a-z_]+)"),
)
_SUPPORTED_VALUES = re.compile(r"supported values are:?\s*([^.]+)")
_QUOTED = re.compile(r"'([^']+)'")


@dataclass(frozen=True, slots=True)
class ParameterAdjustment:
    """One learned correction for a top-level request parameter."""

    param: str
    action: Literal["remove", "set", "rename"]
    value: Any = None


def rejected_parameter_adjustment(
    error: Exception, body: dict[str, Any]
) -> ParameterAdjustment | None:
    """Return the correction implied by a 400 parameter rejection, if any."""
    if getattr(error, "status_code", None) != 400:
        return None
    message = _error_message(error)
    param = getattr(error, "param", None)
    if not isinstance(param, str) or not param:
        param = _param_from_message(message)
    if param is None or param in _ESSENTIAL_PARAMS or param not in body:
        return None

    if param in _TOKEN_FIELD_RENAMES and "unsupported parameter" in message:
        return ParameterAdjustment(param, "rename", _TOKEN_FIELD_RENAMES[param])

    current = body[param]
    supported = _supported_values(message)
    if param == "reasoning_effort" and isinstance(current, str) and supported:
        nearest = _nearest_effort(current, supported)
        if nearest is not None and nearest != current:
            return ParameterAdjustment(param, "set", nearest)
    return ParameterAdjustment(param, "remove")


def apply_parameter_adjustments(
    body: dict[str, Any], adjustments: dict[str, ParameterAdjustment]
) -> dict[str, Any]:
    """Return a shallow copy of ``body`` with learned corrections applied."""
    adjusted = dict(body)
    for adjustment in adjustments.values():
        if adjustment.param not in adjusted:
            continue
        if adjustment.action == "remove":
            adjusted.pop(adjustment.param)
        elif adjustment.action == "set":
            adjusted[adjustment.param] = adjustment.value
        elif adjustment.value not in adjusted:
            adjusted[adjustment.value] = adjusted.pop(adjustment.param)
    return adjusted


def _error_message(error: Exception) -> str:
    parts = [str(error)]
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message not in parts[0]:
            parts.append(message)
    return " ".join(parts).lower()


def _param_from_message(message: str) -> str | None:
    for pattern in _PARAM_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1)
    return None


def _supported_values(message: str) -> list[str]:
    match = _SUPPORTED_VALUES.search(message)
    return _QUOTED.findall(match.group(1)) if match else []


def _nearest_effort(current: str, supported: list[str]) -> str | None:
    if current not in _EFFORT_ORDER:
        return None
    position = _EFFORT_ORDER.index(current)
    candidates = [value for value in supported if value in _EFFORT_ORDER]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda value: (
            abs(_EFFORT_ORDER.index(value) - position),
            value != current,
        ),
    )
