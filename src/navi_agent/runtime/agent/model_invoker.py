from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from ..models import Message, ModelResponse
from ..transports import ModelRequest, ModelTransport


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    response: ModelResponse
    started_at: str
    completed_at: str
    duration_ms: int


class ModelInvoker:
    """Invoke a model transport without owning runtime policy or persistence."""

    def __init__(self, transport: ModelTransport) -> None:
        self._transport = transport

    def invoke(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, object]],
        cancellation_requested: Callable[[], bool],
        on_text_delta: Callable[[str], None],
    ) -> ModelInvocation:
        request = ModelRequest(
            messages=messages,
            tools=tools,
            cancellation_requested=cancellation_requested,
        )
        started_at = _utc_now_iso()
        started_perf = perf_counter()
        generate_stream = getattr(self._transport, "generate_stream", None)
        if callable(generate_stream):
            response = generate_stream(request, on_text_delta)
        else:
            response = self._transport.generate(request)
        return ModelInvocation(
            response=response,
            started_at=started_at,
            completed_at=_utc_now_iso(),
            duration_ms=int((perf_counter() - started_perf) * 1000),
        )
