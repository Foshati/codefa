"""Anthropic SSE parsing and relay with a commit boundary for safe retries."""

import json
from collections.abc import AsyncIterator
from typing import Any

from codefa.core.anthropic.streaming import format_sse_event
from codefa.providers.failure_policy import RetryableProviderProtocolError
from codefa.providers.stream_recovery import TruncatedProviderStreamError

from .errors import AnthropicStreamError

_BLOCK_EVENTS = frozenset(
    {"content_block_start", "content_block_delta", "content_block_stop"}
)
_REASONING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})


async def iter_sse_events(
    lines: AsyncIterator[str],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``(event, data)`` pairs from raw SSE lines."""
    event_type = ""
    data_lines: list[str] = []
    async for raw_line in lines:
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                yield _decode_event(event_type, data_lines)
            event_type = ""
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            event_type = value
        elif name == "data":
            data_lines.append(value)
    if data_lines:
        yield _decode_event(event_type, data_lines)


def _decode_event(event_type: str, data_lines: list[str]) -> tuple[str, dict[str, Any]]:
    try:
        data = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise RetryableProviderProtocolError(
            "Anthropic stream contained malformed JSON."
        ) from exc
    if not isinstance(data, dict):
        raise RetryableProviderProtocolError("Anthropic stream event is not an object.")
    resolved = event_type or data.get("type")
    return (resolved if isinstance(resolved, str) else "", data)


class AnthropicEventRelay:
    """Forward native events, holding output until the first visible content.

    Holding ``message_start`` and pings until a content block starts lets the
    provider retry transparently when the upstream fails before producing
    output. When reasoning output is disabled, reasoning blocks are removed and
    later block indexes are renumbered so the client sees a contiguous stream.
    """

    def __init__(self, *, suppress_reasoning: bool) -> None:
        self._suppress_reasoning = suppress_reasoning
        self._pending: list[str] = []
        self._index_map: dict[int, int] = {}
        self._skipped: set[int] = set()
        self._next_index = 0
        self.committed = False
        self.stopped = False
        self.output_tokens: int | None = None
        self.stop_reason: str | None = None

    def relay(self, event_type: str, data: dict[str, Any]) -> list[str]:
        """Return frames to emit now; raise on upstream error events."""
        if event_type == "error" or data.get("type") == "error":
            raise AnthropicStreamError(data)
        frame = self._translate(event_type, data)
        if frame is None:
            return []
        if event_type == "message_stop":
            self.stopped = True
        if self.committed:
            return [frame]
        self._pending.append(frame)
        if event_type in ("content_block_start", "message_stop"):
            self.committed = True
            frames, self._pending = self._pending, []
            return frames
        return []

    def finish(self) -> list[str]:
        """Validate stream completion and return any held frames."""
        if not self.stopped:
            raise TruncatedProviderStreamError(
                "Anthropic stream ended without message_stop."
            )
        frames, self._pending = self._pending, []
        return frames

    def _translate(self, event_type: str, data: dict[str, Any]) -> str | None:
        if event_type in _BLOCK_EVENTS and isinstance(data.get("index"), int):
            index: int = data["index"]
            if event_type == "content_block_start":
                block = data.get("content_block")
                block_type = block.get("type") if isinstance(block, dict) else None
                if self._suppress_reasoning and block_type in _REASONING_BLOCK_TYPES:
                    self._skipped.add(index)
                    return None
                self._index_map[index] = self._next_index
                self._next_index += 1
            if index in self._skipped:
                return None
            mapped = self._index_map.get(index, index)
            if mapped != index:
                data = {**data, "index": mapped}
        elif event_type == "message_delta":
            self._record_message_delta(data)
        return format_sse_event(event_type, data)

    def _record_message_delta(self, data: dict[str, Any]) -> None:
        usage = data.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("output_tokens"), int):
            self.output_tokens = usage["output_tokens"]
        delta = data.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
            self.stop_reason = delta["stop_reason"]
